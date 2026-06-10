#!/usr/bin/env python3
"""
Dream Rebuild Reconstruction Executor

Reconstruction path:
    six orthographic silhouette masks + aligned depth maps
    -> fused truncated signed distance field
    -> marching-tetrahedra isosurface mesh

The mesh is generated in canonical [0, 1]^3 space, then transformed into the
target object's original OBJ bounding box. This preserves the old part's size
and position while replacing its mesh cache.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np


Vec3 = Tuple[float, float, float]
Face = List[int]
VIEW_NAMES = ("top", "bottom", "left", "right", "front", "back")
OBJECT_RE = re.compile(r"^\s*o\s+([^\s#]+)")
VERTEX_RE = re.compile(r"^\s*v\s+(.+)$")
FACE_RE = re.compile(r"^\s*f\s+(.+)$")
MESH_RE = re.compile(r"^\s*(v|vn|vt|vp|f|l)\s+")
UP_RE = re.compile(r"^\s*#@up:\s*([xyz])\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass
class ObjBlock:
    name: str
    lines: List[str] = field(default_factory=list)
    vertices: List[Vec3] = field(default_factory=list)
    vertex_indices: List[int] = field(default_factory=list)
    faces: List[List[Tuple[int, str]]] = field(default_factory=list)


def warn(message: str) -> None:
    print(f"dream-rebuild warning: {message}", file=sys.stderr)


def parse_vertex(line: str) -> Optional[Vec3]:
    match = VERTEX_RE.match(line)
    if not match:
        return None
    parts = match.group(1).strip().split()[:3]
    if len(parts) < 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


def parse_face(line: str, vertex_count: int) -> List[Tuple[int, str]]:
    match = FACE_RE.match(line)
    if not match:
        return []
    out: List[Tuple[int, str]] = []
    for token in match.group(1).strip().split():
        token_match = re.match(r"^(-?\d+)(.*)$", token)
        if not token_match:
            continue
        index = int(token_match.group(1))
        if index < 0:
            index = vertex_count + index + 1
        if 1 <= index <= vertex_count:
            out.append((index, token_match.group(2) or ""))
    return out


def parse_obj(text: str) -> Tuple[List[str], List[ObjBlock], Dict[int, ObjBlock]]:
    header: List[str] = []
    blocks: List[ObjBlock] = []
    owner: Dict[int, ObjBlock] = {}
    current: Optional[ObjBlock] = None
    vertex_count = 0

    for line in text.splitlines():
        object_match = OBJECT_RE.match(line)
        if object_match:
            current = ObjBlock(name=object_match.group(1), lines=[line])
            blocks.append(current)
            continue
        if current is None:
            header.append(line)
            continue

        current.lines.append(line)
        vertex = parse_vertex(line)
        if vertex is not None:
            vertex_count += 1
            current.vertices.append(vertex)
            current.vertex_indices.append(vertex_count)
            owner[vertex_count] = current
            continue
        face = parse_face(line, vertex_count)
        if len(face) >= 3:
            current.faces.append(face)

    return header, blocks, owner


def scene_up_axis(text: str) -> str:
    match = UP_RE.search(text)
    if not match:
        return "z"
    up = match.group(1).lower()
    if up not in {"y", "z"}:
        warn(f"#@up: {up} is not supported by dream rebuild yet; using z-up view mapping")
        return "z"
    return up


def bounds(vertices: Iterable[Vec3]) -> Tuple[np.ndarray, np.ndarray]:
    arr = np.array(list(vertices), dtype=float)
    if arr.size == 0:
        raise ValueError("Target object has no vertices")
    return arr.min(axis=0), arr.max(axis=0)


def triangulate_faces(faces: List[Face]) -> List[Face]:
    triangles: List[Face] = []
    for face in faces:
        clean = [
            index[0] if isinstance(index, tuple) else index
            for index in face
            if (index[0] if isinstance(index, tuple) else index) > 0
        ]
        if len(clean) < 3:
            continue
        if len(clean) == 3:
            triangles.append(clean)
            continue
        for i in range(1, len(clean) - 1):
            triangles.append([clean[0], clean[i], clean[i + 1]])
    return triangles


def midpoint(a: Vec3, b: Vec3) -> Vec3:
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


def midpoint_subdivide(vertices: List[Vec3], faces: List[Face], levels: int) -> Tuple[List[Vec3], List[Face]]:
    out_vertices = list(vertices)
    out_faces = triangulate_faces(faces)
    for _ in range(max(0, levels)):
        edge_midpoints: Dict[Tuple[int, int], int] = {}

        def mid_index(a: int, b: int) -> int:
            key = tuple(sorted((a, b)))
            existing = edge_midpoints.get(key)
            if existing is not None:
                return existing
            out_vertices.append(midpoint(out_vertices[a - 1], out_vertices[b - 1]))
            index = len(out_vertices)
            edge_midpoints[key] = index
            return index

        next_faces: List[Face] = []
        for a, b, c in out_faces:
            ab = mid_index(a, b)
            bc = mid_index(b, c)
            ca = mid_index(c, a)
            next_faces.extend([[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]])
        out_faces = next_faces
    return out_vertices, out_faces


def mask_matrix(mask: dict) -> np.ndarray:
    width = int(mask.get("width") or 0)
    height = int(mask.get("height") or 0)
    rows = mask.get("rows")
    if width <= 0 or height <= 0 or not isinstance(rows, list) or len(rows) != height:
        raise ValueError("Mask must include width, height, and rows")
    matrix = np.zeros((height, width), dtype=bool)
    for y, row in enumerate(rows):
        row_text = str(row)
        if len(row_text) < width:
            raise ValueError("Mask row is shorter than width")
        for x, ch in enumerate(row_text[:width]):
            matrix[y, x] = ch not in {"0", ".", " ", "_"}
    return matrix


def depth_value(ch: str) -> float:
    if ch in {".", " ", "_"}:
        return 0.0
    if "0" <= ch <= "9":
        return int(ch, 16) / 15.0
    low = ch.lower()
    if "a" <= low <= "f":
        return int(low, 16) / 15.0
    return 1.0


def depth_matrix(depth_map: dict) -> np.ndarray:
    width = int(depth_map.get("width") or 0)
    height = int(depth_map.get("height") or 0)
    rows = depth_map.get("rows")
    if width <= 0 or height <= 0 or not isinstance(rows, list) or len(rows) != height:
        raise ValueError("Depth map must include width, height, and rows")
    matrix = np.zeros((height, width), dtype=float)
    for y, row in enumerate(rows):
        row_text = str(row)
        if len(row_text) < width:
            raise ValueError("Depth map row is shorter than width")
        if len(row_text) >= width * 2 and re.fullmatch(r"[0-9a-fA-F]+", row_text[: width * 2]):
            for x in range(width):
                matrix[y, x] = int(row_text[x * 2 : x * 2 + 2], 16) / 255.0
        else:
            for x, ch in enumerate(row_text[:width]):
                matrix[y, x] = depth_value(ch)
    return matrix


def sample_mask(mask: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    cols = np.clip(np.rint(u * (width - 1)).astype(int), 0, width - 1)
    rows = np.clip(np.rint((1.0 - v) * (height - 1)).astype(int), 0, height - 1)
    return mask[rows, cols]


def sample_depth(depth: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    height, width = depth.shape
    px = np.clip(u * (width - 1), 0, width - 1)
    py = np.clip((1.0 - v) * (height - 1), 0, height - 1)
    x0 = np.floor(px).astype(int)
    y0 = np.floor(py).astype(int)
    x1 = np.clip(x0 + 1, 0, width - 1)
    y1 = np.clip(y0 + 1, 0, height - 1)
    tx = px - x0
    ty = py - y0
    with np.errstate(invalid="ignore"):
        a = depth[y0, x0] * (1.0 - tx) + depth[y0, x1] * tx
        b = depth[y1, x0] * (1.0 - tx) + depth[y1, x1] * tx
        return a * (1.0 - ty) + b * ty


def sample_depth_scalar(depth: np.ndarray, u: float, v: float) -> float:
    return float(sample_depth(depth, np.array(u), np.array(v)))


def depth_detail_matrix(depth: np.ndarray) -> np.ndarray:
    detail = np.zeros_like(depth, dtype=float)
    for y in range(depth.shape[0]):
        row = depth[y]
        valid = row > 0.08
        if not np.any(valid):
            continue
        baseline = float(np.median(row[valid]))
        residual = row - baseline
        scale = float(np.percentile(np.abs(residual[valid]), 90))
        if scale < 1e-6:
            continue
        detail[y, valid] = np.clip(residual[valid] / scale, -1.0, 1.0)
    return detail


def gaussian_kernel1d(sigma: float) -> np.ndarray:
    radius = max(1, int(round(sigma * 3.0)))
    xs = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-(xs * xs) / max(2.0 * sigma * sigma, 1e-9))
    return kernel / np.sum(kernel)


def gaussian_blur(matrix: np.ndarray, sigma: float = 1.1) -> np.ndarray:
    if matrix.size == 0:
        return matrix
    kernel = gaussian_kernel1d(sigma)
    radius = len(kernel) // 2
    padded_x = np.pad(matrix, ((0, 0), (radius, radius)), mode="edge")
    tmp = np.zeros_like(matrix, dtype=float)
    for offset, weight in enumerate(kernel):
        tmp += padded_x[:, offset : offset + matrix.shape[1]] * weight
    padded_y = np.pad(tmp, ((radius, radius), (0, 0)), mode="edge")
    out = np.zeros_like(matrix, dtype=float)
    for offset, weight in enumerate(kernel):
        out += padded_y[offset : offset + matrix.shape[0], :] * weight
    return out


def erode_mask(mask: np.ndarray, iterations: int = 2) -> np.ndarray:
    out = mask.astype(bool)
    for _ in range(max(0, iterations)):
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        next_out = out.copy()
        for dy in range(3):
            for dx in range(3):
                next_out &= padded[dy : dy + out.shape[0], dx : dx + out.shape[1]]
        out = next_out
    return out


def source_depth_maps(
    vertices: List[Vec3],
    faces: List[Face],
    view_names: Iterable[str],
    width: int,
    height: int,
    bb_min: np.ndarray,
    bb_max: np.ndarray,
    up_axis: str,
) -> Dict[str, np.ndarray]:
    arr = np.array(vertices, dtype=float)
    size = np.maximum(bb_max - bb_min, 1e-9)
    canonical = np.clip((arr - bb_min) / size, 0.0, 1.0)
    out: Dict[str, np.ndarray] = {}
    for view in view_names:
        u, v = projected_uv(view, canonical[:, 0], canonical[:, 1], canonical[:, 2], up_axis)
        depth = 1.0 - ray_depth(view, canonical[:, 0], canonical[:, 1], canonical[:, 2], up_axis)
        zbuffer = np.full((height, width), -np.inf, dtype=float)
        px = np.clip(u * (width - 1), 0, width - 1)
        py = np.clip((1.0 - v) * (height - 1), 0, height - 1)

        for face in faces:
            if len(face) < 3:
                continue
            ids = [index - 1 for index in face[:3]]
            xs = px[ids]
            ys = py[ids]
            zs = depth[ids]
            minx = max(0, int(np.floor(np.min(xs))))
            maxx = min(width - 1, int(np.ceil(np.max(xs))))
            miny = max(0, int(np.floor(np.min(ys))))
            maxy = min(height - 1, int(np.ceil(np.max(ys))))
            denom = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(float(denom)) < 1e-9:
                continue
            for yy in range(miny, maxy + 1):
                cols = np.arange(minx, maxx + 1, dtype=float)
                rows = np.full_like(cols, yy, dtype=float)
                w0 = ((ys[1] - ys[2]) * (cols - xs[2]) + (xs[2] - xs[1]) * (rows - ys[2])) / denom
                w1 = ((ys[2] - ys[0]) * (cols - xs[2]) + (xs[0] - xs[2]) * (rows - ys[2])) / denom
                w2 = 1.0 - w0 - w1
                inside = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
                if not np.any(inside):
                    continue
                interpolated = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
                xi = cols.astype(int)
                better = inside & (interpolated > zbuffer[yy, xi])
                if np.any(better):
                    zbuffer[yy, xi[better]] = interpolated[better]
        out[view] = zbuffer
    return out


def view_toward_camera(view: str, up_axis: str) -> np.ndarray:
    if up_axis == "y":
        vectors = {
            "front": np.array([0.0, 0.0, -1.0]),
            "back": np.array([0.0, 0.0, 1.0]),
            "right": np.array([1.0, 0.0, 0.0]),
            "left": np.array([-1.0, 0.0, 0.0]),
            "top": np.array([0.0, 1.0, 0.0]),
            "bottom": np.array([0.0, -1.0, 0.0]),
        }
    else:
        vectors = {
            "front": np.array([0.0, -1.0, 0.0]),
            "back": np.array([0.0, 1.0, 0.0]),
            "right": np.array([1.0, 0.0, 0.0]),
            "left": np.array([-1.0, 0.0, 0.0]),
            "top": np.array([0.0, 0.0, 1.0]),
            "bottom": np.array([0.0, 0.0, -1.0]),
        }
    return vectors[view]


def projected_uv(view: str, x: np.ndarray, y: np.ndarray, z: np.ndarray, up_axis: str) -> Tuple[np.ndarray, np.ndarray]:
    if up_axis == "y":
        if view == "front":
            return x, y
        if view == "back":
            return 1.0 - x, y
        if view == "right":
            return z, y
        if view == "left":
            return 1.0 - z, y
        if view == "top":
            return x, z
        if view == "bottom":
            return x, 1.0 - z
    else:
        if view == "front":
            return x, z
        if view == "back":
            return 1.0 - x, z
        if view == "right":
            return y, z
        if view == "left":
            return 1.0 - y, z
        if view == "top":
            return x, y
        if view == "bottom":
            return x, 1.0 - y
    raise ValueError(f"Unsupported view: {view}")


def ray_depth(view: str, x: np.ndarray, y: np.ndarray, z: np.ndarray, up_axis: str) -> np.ndarray:
    if up_axis == "y":
        if view == "front":
            return z
        if view == "back":
            return 1.0 - z
        if view == "right":
            return 1.0 - x
        if view == "left":
            return x
        if view == "top":
            return 1.0 - y
        if view == "bottom":
            return y
    else:
        if view == "front":
            return y
        if view == "back":
            return 1.0 - y
        if view == "right":
            return 1.0 - x
        if view == "left":
            return x
        if view == "top":
            return 1.0 - z
        if view == "bottom":
            return z
    raise ValueError(f"Unsupported view: {view}")


def fused_tsdf_field(
    view_masks: Dict[str, dict],
    view_depth_maps: Dict[str, dict],
    resolution: int,
    up_axis: str,
    profile: str,
) -> Tuple[np.ndarray, np.ndarray]:
    missing = [name for name in VIEW_NAMES if name not in view_masks]
    if missing:
        raise ValueError(f"Missing masks: {', '.join(missing)}")
    missing_depth = [name for name in VIEW_NAMES if name not in view_depth_maps]
    if missing_depth:
        raise ValueError(f"Missing depth maps: {', '.join(missing_depth)}")

    masks = {name: mask_matrix(view_masks[name]) for name in VIEW_NAMES}
    depths = {name: depth_matrix(view_depth_maps[name]) for name in VIEW_NAMES}
    coords = np.linspace(0.0, 1.0, resolution + 1, dtype=float)
    x, y, z = np.meshgrid(coords, coords, coords, indexing="ij")
    truncation = 3.0 / float(resolution)
    silhouette = np.ones((resolution + 1, resolution + 1, resolution + 1), dtype=bool)
    signed_samples: List[np.ndarray] = []
    depth_view_names = (
        ("front", "back", "left", "right")
        if profile == "object"
        else VIEW_NAMES
    )

    for name, mask in masks.items():
        u, v = projected_uv(name, x, y, z, up_axis)
        in_silhouette = sample_mask(mask, u, v)
        silhouette &= in_silhouette
        if name not in depth_view_names:
            continue
        # Depth map convention: white is closest to camera, black is farthest
        # inside the part's canonical bounding volume.
        surface_t = 1.0 - sample_depth(depths[name], u, v)
        signed = surface_t - ray_depth(name, x, y, z, up_axis)
        signed_samples.append(signed)

    if not signed_samples:
        raise ValueError("No depth views selected for TSDF reconstruction")

    signed_stack = np.stack(signed_samples, axis=0)
    # AI-generated views are often mutually inconsistent. Hard intersection
    # destroys recognizable objects, so use a robust high percentile instead:
    # one bad view can bend the field, but it cannot amputate the whole shape.
    percentile = 68.0 if profile == "object" else 82.0
    field = np.percentile(signed_stack, percentile, axis=0)
    field = np.where(silhouette, field, truncation)

    field = np.clip(field, -truncation, truncation)
    if not np.any(field <= 0.0):
        raise ValueError("Masks and depth maps produced an empty reconstruction field")

    # Padding supplies a definite outside value, so surfaces on the original
    # bounding-box boundary are extracted instead of disappearing at the array edge.
    padded = np.pad(field, 1, mode="constant", constant_values=truncation)
    step = 1.0 / float(resolution)
    padded_coords = np.concatenate(([-step], coords, [1.0 + step]))
    return padded, padded_coords


TETRAHEDRA = (
    (0, 5, 1, 6),
    (0, 1, 2, 6),
    (0, 2, 3, 6),
    (0, 3, 7, 6),
    (0, 7, 4, 6),
    (0, 4, 5, 6),
)


def canonical_to_world(point: np.ndarray, bb_min: np.ndarray, bb_max: np.ndarray) -> Vec3:
    canonical = np.clip(point, 0.0, 1.0)
    world = bb_min + canonical * (bb_max - bb_min)
    return (float(world[0]), float(world[1]), float(world[2]))


def keep_largest_inside_component(field: np.ndarray) -> np.ndarray:
    inside = field <= 0.0
    if not np.any(inside):
        return field
    visited = np.zeros_like(inside, dtype=bool)
    components: List[List[Tuple[int, int, int]]] = []
    shape = inside.shape
    neighbors = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))

    for start_raw in np.argwhere(inside):
        start = (int(start_raw[0]), int(start_raw[1]), int(start_raw[2]))
        if visited[start]:
            continue
        stack = [start]
        visited[start] = True
        component: List[Tuple[int, int, int]] = []
        while stack:
            cell = stack.pop()
            component.append(cell)
            for dx, dy, dz in neighbors:
                nxt = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                if (
                    nxt[0] < 0
                    or nxt[1] < 0
                    or nxt[2] < 0
                    or nxt[0] >= shape[0]
                    or nxt[1] >= shape[1]
                    or nxt[2] >= shape[2]
                    or visited[nxt]
                    or not inside[nxt]
                ):
                    continue
                visited[nxt] = True
                stack.append(nxt)
        components.append(component)

    if len(components) <= 1:
        return field
    keep = max(components, key=len)
    keep_mask = np.zeros_like(inside, dtype=bool)
    for cell in keep:
        keep_mask[cell] = True
    cleaned = field.copy()
    cleaned[inside & ~keep_mask] = float(np.max(field))
    warn(f"removed {len(components) - 1} disconnected TSDF island(s)")
    return cleaned


def marching_tetrahedra_mesh(field: np.ndarray, coords: np.ndarray, bb_min: np.ndarray, bb_max: np.ndarray) -> Tuple[List[Vec3], List[Face]]:
    vertices: List[Vec3] = []
    faces: List[Face] = []
    vertex_cache: Dict[Tuple[Tuple[int, int, int], Tuple[int, int, int]], int] = {}

    def edge_vertex(
        a_key: Tuple[int, int, int],
        b_key: Tuple[int, int, int],
        a_point: np.ndarray,
        b_point: np.ndarray,
        a_value: float,
        b_value: float,
    ) -> int:
        key = tuple(sorted((a_key, b_key)))  # type: ignore[arg-type]
        existing = vertex_cache.get(key)
        if existing is not None:
            return existing

        denom = a_value - b_value
        if abs(denom) < 1e-12:
            t = 0.5
        else:
            t = a_value / denom
        point = a_point + np.clip(t, 0.0, 1.0) * (b_point - a_point)
        vertices.append(canonical_to_world(point, bb_min, bb_max))
        index = len(vertices)
        vertex_cache[key] = index
        return index

    corner_offsets = (
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    )
    last = field.shape[0] - 1
    for i in range(last):
        for j in range(last):
            for k in range(last):
                keys = [(i + dx, j + dy, k + dz) for dx, dy, dz in corner_offsets]
                values = [float(field[key]) for key in keys]
                if all(value <= 0.0 for value in values) or all(value > 0.0 for value in values):
                    continue
                points = [
                    np.array([coords[key[0]], coords[key[1]], coords[key[2]]], dtype=float)
                    for key in keys
                ]
                for tet in TETRAHEDRA:
                    tet_values = [values[index] for index in tet]
                    inside = [local_index for local_index, value in enumerate(tet_values) if value <= 0.0]
                    outside = [local_index for local_index, value in enumerate(tet_values) if value > 0.0]
                    if len(inside) == 0 or len(outside) == 0:
                        continue

                    def ev(a: int, b: int) -> int:
                        ia = tet[a]
                        ib = tet[b]
                        return edge_vertex(
                            keys[ia],
                            keys[ib],
                            points[ia],
                            points[ib],
                            values[ia],
                            values[ib],
                        )

                    if len(inside) == 1:
                        i0 = inside[0]
                        faces.append([ev(i0, outside[0]), ev(i0, outside[1]), ev(i0, outside[2])])
                    elif len(inside) == 3:
                        o0 = outside[0]
                        faces.append([ev(o0, inside[0]), ev(o0, inside[2]), ev(o0, inside[1])])
                    elif len(inside) == 2:
                        i0, i1 = inside
                        o0, o1 = outside
                        a = ev(i0, o0)
                        b = ev(i0, o1)
                        c = ev(i1, o0)
                        d = ev(i1, o1)
                        faces.append([a, b, c])
                        faces.append([b, d, c])
                    else:
                        intersections: List[int] = []
                        for a in inside:
                            for b in outside:
                                intersections.append(
                                    ev(a, b)
                                )
                        unique = []
                        for index in intersections:
                            if index not in unique:
                                unique.append(index)
                        if len(unique) >= 3:
                            faces.append(unique[:3])

    if not faces:
        raise ValueError("TSDF extraction produced no surface faces")
    return vertices, faces


def smooth_mesh(vertices: List[Vec3], faces: List[Face], bb_min: np.ndarray, bb_max: np.ndarray, iterations: int = 2, strength: float = 0.35) -> List[Vec3]:
    if iterations <= 0 or not vertices:
        return vertices
    arr = np.array(vertices, dtype=float)
    original_min = arr.min(axis=0)
    original_max = arr.max(axis=0)
    adjacency: List[set[int]] = [set() for _ in vertices]
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            adjacency[a - 1].add(b - 1)
            adjacency[b - 1].add(a - 1)
    for _ in range(iterations):
        next_arr = arr.copy()
        for index, neighbors in enumerate(adjacency):
            if not neighbors:
                continue
            avg = arr[list(neighbors)].mean(axis=0)
            next_arr[index] = arr[index] * (1.0 - strength) + avg * strength
        arr = next_arr

    # Preserve the reconstructed part's fitted bounds after smoothing.
    current_min = arr.min(axis=0)
    current_max = arr.max(axis=0)
    current_size = np.maximum(current_max - current_min, 1e-9)
    original_size = np.maximum(original_max - original_min, 1e-9)
    arr = (arr - current_min) / current_size * original_size + original_min
    arr = np.clip(arr, bb_min, bb_max)
    return [(float(x), float(y), float(z)) for x, y, z in arr]


def refit_vertices_to_bbox(vertices: List[Vec3], bb_min: np.ndarray, bb_max: np.ndarray) -> List[Vec3]:
    if not vertices:
        return vertices
    arr = np.array(vertices, dtype=float)
    current_min = arr.min(axis=0)
    current_max = arr.max(axis=0)
    current_size = np.maximum(current_max - current_min, 1e-9)
    target_size = bb_max - bb_min
    arr = (arr - current_min) / current_size * target_size + bb_min
    arr = np.clip(arr, bb_min, bb_max)
    return [(float(x), float(y), float(z)) for x, y, z in arr]


def anchor_vertices_to_source_envelope(
    vertices: List[Vec3],
    source_vertices: List[Vec3],
    bb_min: np.ndarray,
    bb_max: np.ndarray,
    up_axis: str,
    bins: int = 48,
) -> List[Vec3]:
    if not vertices or not source_vertices:
        return vertices
    up = 1 if up_axis == "y" else 2
    horizontal = [axis for axis in range(3) if axis != up]
    center = (bb_min + bb_max) * 0.5
    height_size = max(float(bb_max[up] - bb_min[up]), 1e-9)

    def bin_index(point: np.ndarray) -> int:
        t = float((point[up] - bb_min[up]) / height_size)
        return max(0, min(bins - 1, int(round(t * (bins - 1)))))

    def radius(point: np.ndarray) -> float:
        return float(np.linalg.norm(point[horizontal] - center[horizontal]))

    source_radii = np.zeros(bins, dtype=float)
    for source in source_vertices:
        point = np.array(source, dtype=float)
        idx = bin_index(point)
        source_radii[idx] = max(source_radii[idx], radius(point))

    known = np.where(source_radii > 1e-9)[0]
    if len(known) == 0:
        return vertices
    all_bins = np.arange(bins)
    source_radii = np.interp(all_bins, known, source_radii[known])

    arr = np.array(vertices, dtype=float)
    generated_bins: List[List[float]] = [[] for _ in range(bins)]
    for point in arr:
        generated_bins[bin_index(point)].append(radius(point))
    generated_radii = np.zeros(bins, dtype=float)
    for idx, values in enumerate(generated_bins):
        if values:
            generated_radii[idx] = float(np.percentile(values, 92))
    known_generated = np.where(generated_radii > 1e-9)[0]
    if len(known_generated) == 0:
        return vertices
    generated_radii = np.interp(all_bins, known_generated, generated_radii[known_generated])

    for index, point in enumerate(arr):
        idx = bin_index(point)
        current_radius = radius(point)
        if current_radius < 1e-9:
            continue
        target_scale = source_radii[idx] / max(generated_radii[idx], 1e-9)
        # Keep detail alive, but prevent generated maps from collapsing or
        # exploding the LLM-authored low-poly volume.
        target_scale = max(0.65, min(1.55, target_scale))
        point[horizontal] = center[horizontal] + (point[horizontal] - center[horizontal]) * target_scale
        arr[index] = point

    arr = np.clip(arr, bb_min, bb_max)
    return [(float(x), float(y), float(z)) for x, y, z in arr]


def keep_largest_mesh_component(vertices: List[Vec3], faces: List[Face]) -> Tuple[List[Vec3], List[Face]]:
    if not vertices or not faces:
        return vertices, faces
    face_neighbors: Dict[int, set[int]] = {index: set() for index in range(len(faces))}
    edge_owners: Dict[Tuple[int, int], List[int]] = {}
    for face_index, face in enumerate(faces):
        for a, b in zip(face, face[1:] + face[:1]):
            edge = tuple(sorted((a, b)))
            edge_owners.setdefault(edge, []).append(face_index)
    for owners in edge_owners.values():
        if len(owners) < 2:
            continue
        for owner in owners:
            face_neighbors[owner].update(other for other in owners if other != owner)

    seen: set[int] = set()
    components: List[List[int]] = []
    for start in range(len(faces)):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: List[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in face_neighbors[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(component)

    if len(components) <= 1:
        return vertices, faces

    keep_faces = [faces[index] for index in max(components, key=len)]
    used = sorted({vertex for face in keep_faces for vertex in face})
    index_map = {old: new_index + 1 for new_index, old in enumerate(used)}
    next_vertices = [vertices[old - 1] for old in used]
    next_faces = [[index_map[index] for index in face] for face in keep_faces]
    warn(f"removed {len(components) - 1} disconnected mesh component(s)")
    return next_vertices, next_faces


def enhance_source_mesh_with_depth_maps(
    target_block: ObjBlock,
    view_depth_maps: Dict[str, dict],
    bb_min: np.ndarray,
    bb_max: np.ndarray,
    up_axis: str,
    levels: int = 3,
) -> Tuple[List[Vec3], List[Face]]:
    vertices, faces = midpoint_subdivide(target_block.vertices, target_block.faces, levels)
    if not vertices or not faces:
        raise ValueError("Target object has no mesh to enhance")
    depth_views = [name for name in VIEW_NAMES if name in view_depth_maps]
    if len(depth_views) < 2:
        raise ValueError("Enhance mode needs at least two depth maps")

    arr = np.array(vertices, dtype=float)
    size = np.maximum(bb_max - bb_min, 1e-9)
    canonical = np.clip((arr - bb_min) / size, 0.0, 1.0)
    generated_depths = {name: depth_matrix(view_depth_maps[name]) for name in depth_views}
    first_depth = next(iter(generated_depths.values()))
    height, width = first_depth.shape
    source_depths = source_depth_maps(vertices, faces, depth_views, width, height, bb_min, bb_max, up_axis)

    residual_maps: Dict[str, np.ndarray] = {}
    confidence_maps: Dict[str, np.ndarray] = {}
    for view in depth_views:
        generated = generated_depths[view]
        source = source_depths[view]
        visible = np.isfinite(source) & (generated > 0.08)
        if not np.any(visible):
            continue
        residual = np.zeros_like(generated, dtype=float)
        raw = generated - source
        raw = raw - float(np.median(raw[visible]))
        raw = gaussian_blur(np.where(visible, raw, 0.0), sigma=1.2)
        scale = float(np.percentile(np.abs(raw[visible]), 92))
        if scale < 1e-6:
            continue
        residual[visible] = np.clip(raw[visible] / scale, -1.0, 1.0)
        residual_maps[view] = residual
        core = erode_mask(visible, iterations=2)
        confidence = np.where(core, 1.0, np.where(visible, 0.28, 0.0))
        confidence_maps[view] = gaussian_blur(confidence, sigma=0.8)

    if len(residual_maps) < 2:
        raise ValueError("Enhance mode could not derive usable residual depth maps")

    normals = np.array(vertex_normals(vertices, faces), dtype=float)
    proposals = np.zeros_like(arr)
    weights = np.zeros(len(vertices), dtype=float)
    amplitude = 0.10 * float(np.min(size))

    for index, point in enumerate(canonical):
        point_proposals: List[Tuple[float, np.ndarray]] = []
        for view, residual in residual_maps.items():
            u, v = projected_uv(
                view,
                np.array(point[0]),
                np.array(point[1]),
                np.array(point[2]),
                up_axis,
            )
            uu = float(u)
            vv = float(v)
            source_depth = source_depths[view]
            visible_depth = sample_depth_scalar(source_depth, uu, vv)
            if not np.isfinite(visible_depth):
                continue
            vertex_depth = float(1.0 - ray_depth(view, np.array(point[0]), np.array(point[1]), np.array(point[2]), up_axis))
            if abs(vertex_depth - visible_depth) > 0.08:
                continue
            confidence = sample_depth_scalar(confidence_maps[view], uu, vv)
            if confidence <= 0.02:
                continue
            detail = sample_depth_scalar(residual, uu, vv)
            if abs(detail) < 0.02:
                continue
            toward_camera = view_toward_camera(view, up_axis)
            facing = abs(float(np.dot(normals[index], toward_camera)))
            weight = confidence * (0.35 + 0.65 * facing)
            point_proposals.append((weight, toward_camera * detail * amplitude))

        if not point_proposals:
            continue
        total_weight = sum(weight for weight, _ in point_proposals)
        proposals[index] = sum(weight * vector for weight, vector in point_proposals) / max(total_weight, 1e-9)
        weights[index] = min(1.0, total_weight / 1.7)

    adjacency: List[set[int]] = [set() for _ in vertices]
    edge_counts: Dict[Tuple[int, int], int] = {}
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            ia = a - 1
            ib = b - 1
            adjacency[ia].add(ib)
            adjacency[ib].add(ia)
            key = tuple(sorted((ia, ib)))
            edge_counts[key] = edge_counts.get(key, 0) + 1

    boundary = np.zeros(len(vertices), dtype=bool)
    for (a, b), count in edge_counts.items():
        if count == 1:
            boundary[a] = True
            boundary[b] = True

    displacement = proposals.copy()
    smooth_weight = 2.8
    for _ in range(36):
        next_displacement = displacement.copy()
        for index, neighbors in enumerate(adjacency):
            if not neighbors:
                continue
            avg = displacement[list(neighbors)].mean(axis=0)
            data_weight = weights[index]
            next_displacement[index] = (
                proposals[index] * data_weight + avg * smooth_weight
            ) / max(data_weight + smooth_weight, 1e-9)
        displacement = next_displacement

    max_displacement = 0.13 * float(np.min(size))
    lengths = np.linalg.norm(displacement, axis=1)
    over = lengths > max_displacement
    if np.any(over):
        displacement[over] *= (max_displacement / lengths[over])[:, None]
    displacement[boundary] *= 0.25

    enhanced_arr = np.clip(arr + displacement, bb_min, bb_max)
    enhanced = [(float(x), float(y), float(z)) for x, y, z in enhanced_arr]
    enhanced = refit_vertices_to_bbox(enhanced, bb_min, bb_max)
    return enhanced, faces


def orient_faces_outward(vertices: List[Vec3], faces: List[Face]) -> List[Face]:
    if not vertices or not faces:
        return faces
    arr = np.array(vertices, dtype=float)
    center = arr.mean(axis=0)
    oriented: List[Face] = []
    for face in faces:
        if len(face) < 3:
            continue
        points = arr[[index - 1 for index in face]]
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        face_center = points.mean(axis=0)
        if float(np.dot(normal, face_center - center)) < 0.0:
            oriented.append(list(reversed(face)))
        else:
            oriented.append(face)
    return oriented


def vertex_normals(vertices: List[Vec3], faces: List[Face]) -> List[Vec3]:
    if not vertices:
        return []
    arr = np.array(vertices, dtype=float)
    normals = np.zeros_like(arr)
    for face in faces:
        if len(face) < 3:
            continue
        indices = [index - 1 for index in face]
        points = arr[indices]
        face_normal = np.cross(points[1] - points[0], points[2] - points[0])
        length = float(np.linalg.norm(face_normal))
        if length < 1e-12:
            continue
        for index in indices:
            normals[index] += face_normal
    for index, normal in enumerate(normals):
        length = float(np.linalg.norm(normal))
        if length < 1e-12:
            fallback = arr[index] - arr.mean(axis=0)
            fallback_length = float(np.linalg.norm(fallback))
            normal = fallback / fallback_length if fallback_length > 1e-12 else np.array([0.0, 1.0, 0.0])
        else:
            normal = normal / length
        normals[index] = normal
    return [(float(x), float(y), float(z)) for x, y, z in normals]


def non_mesh_lines(block: ObjBlock) -> List[str]:
    return [line for line in block.lines if not MESH_RE.match(line)]


def write_obj(
    header: List[str],
    blocks: List[ObjBlock],
    owner: Dict[int, ObjBlock],
    target_name: str,
    new_vertices: List[Vec3],
    new_faces: List[Face],
) -> str:
    out: List[str] = []
    out.extend([line for line in header if line.strip()])
    next_index = 1
    next_normal_index = 1

    for block in blocks:
        if out and out[-1].strip():
            out.append("")
        out.extend(non_mesh_lines(block))
        if block.name == target_name:
            normals = vertex_normals(new_vertices, new_faces)
            normal_start = next_normal_index
            for x, y, z in new_vertices:
                out.append(f"v {x:.6f} {y:.6f} {z:.6f}")
            for nx, ny, nz in normals:
                out.append(f"vn {nx:.6f} {ny:.6f} {nz:.6f}")
            for face in new_faces:
                out.append(
                    "f "
                    + " ".join(
                        f"{next_index + index - 1}//{normal_start + index - 1}" for index in face
                    )
                )
            next_index += len(new_vertices)
            next_normal_index += len(normals)
            continue

        index_map: Dict[int, int] = {}
        for old_index, vertex in zip(block.vertex_indices, block.vertices):
            index_map[old_index] = next_index
            out.append(f"v {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}")
            next_index += 1
        for face in block.faces:
            remapped: List[str] = []
            for old_index, suffix in face:
                if owner.get(old_index) is not block or old_index not in index_map:
                    continue
                remapped.append(f"{index_map[old_index]}{suffix}")
            if len(remapped) >= 3:
                out.append("f " + " ".join(remapped))

    return "\n".join(out).rstrip() + "\n"


def reconstruct(payload: dict) -> str:
    live_obj = str(payload.get("liveObj") or "")
    target = str(payload.get("targetObjectId") or "").strip()
    if not live_obj:
        raise ValueError("liveObj is required")
    if not target:
        raise ValueError("targetObjectId is required")
    resolution = int(payload.get("resolution") or 48)
    resolution = max(8, min(96, resolution))
    profile = str(payload.get("profile") or "object").strip().lower()
    if profile not in {"object", "surface"}:
        profile = "object"
    mode = str(payload.get("mode") or "enhance").strip().lower()
    if mode not in {"enhance", "replace"}:
        mode = "enhance"

    header, blocks, owner = parse_obj(live_obj)
    up_axis = scene_up_axis(live_obj)
    target_block = next((block for block in blocks if block.name == target), None)
    if target_block is None:
        raise ValueError(f'Target object "{target}" was not found')

    bb_min, bb_max = bounds(target_block.vertices)
    size = bb_max - bb_min
    if np.any(np.abs(size) < 1e-6):
        raise ValueError("Target object bounds are degenerate; cannot place reconstructed volume")

    view_depth_maps = payload.get("viewDepthMaps")
    if not view_depth_maps:
        raise ValueError("viewDepthMaps are required for TSDF reconstruction")

    if mode == "enhance":
        vertices, faces = enhance_source_mesh_with_depth_maps(
            target_block,
            view_depth_maps,
            bb_min,
            bb_max,
            up_axis,
        )
        faces = orient_faces_outward(vertices, faces)
        warn(
            f"depth enhancement: up={up_axis}, profile={profile}, source_vertices={len(target_block.vertices)}, vertices={len(vertices)}, faces={len(faces)}"
        )
        return write_obj(header, blocks, owner, target, vertices, faces)

    field, field_coords = fused_tsdf_field(
        payload.get("viewMasks") or {},
        view_depth_maps,
        resolution,
        up_axis,
        profile,
    )
    field = keep_largest_inside_component(field)
    vertices, faces = marching_tetrahedra_mesh(field, field_coords, bb_min, bb_max)
    vertices, faces = keep_largest_mesh_component(vertices, faces)
    vertices = smooth_mesh(vertices, faces, bb_min, bb_max)
    if profile == "object":
        vertices = refit_vertices_to_bbox(vertices, bb_min, bb_max)
        vertices = anchor_vertices_to_source_envelope(
            vertices,
            target_block.vertices,
            bb_min,
            bb_max,
            up_axis,
        )
    faces = orient_faces_outward(vertices, faces)
    warn(
        f"tsdf reconstruction: resolution={resolution}, up={up_axis}, profile={profile}, field_shape={list(field.shape)}, vertices={len(vertices)}, faces={len(faces)}"
    )
    warn("depth-constrained reconstruction: fused six grayscale depth maps into a smooth isosurface")
    return write_obj(header, blocks, owner, target, vertices, faces)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    Path(args.output).write_text(reconstruct(payload), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"dream-rebuild error: {exc}", file=sys.stderr)
        raise
