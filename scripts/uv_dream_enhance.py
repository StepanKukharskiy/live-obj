#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np


Vec3 = Tuple[float, float, float]
Face = List[int]
OBJECT_RE = re.compile(r"^\s*o\s+([^\s#]+)")
VERTEX_RE = re.compile(r"^\s*v\s+(.+)$")
FACE_RE = re.compile(r"^\s*f\s+(.+)$")
UV_ISLAND_RE = re.compile(r"^\s*#@uv_island:\s*(.+)$")
UV_HINT_RE = re.compile(r"^\s*#@uv_hint:\s*(.+)$")

ATLAS_W = 1024
ATLAS_H = 1024
TOP_NORMAL_THRESHOLD = 0.56
RADIAL_CAP_NORMAL_THRESHOLD = 0.78
RADIAL_CAP_HEIGHT_FRACTION = 0.08
RADIAL_ISLAND_RECTS = {
    "top": (0, 0, ATLAS_W // 2, ATLAS_H // 3),
    "bottom": (ATLAS_W // 2, 0, ATLAS_W // 2, ATLAS_H // 3),
    "side": (0, ATLAS_H // 3, ATLAS_W, ATLAS_H * 2 // 3),
}
RADIAL_HOLLOW_ISLAND_RECTS = {
    "top": (0, 0, ATLAS_W // 2, ATLAS_H // 4),
    "bottom": (ATLAS_W // 2, 0, ATLAS_W // 2, ATLAS_H // 4),
    "side": (0, ATLAS_H // 4, ATLAS_W, ATLAS_H // 2),
    "inner": (0, ATLAS_H * 3 // 4, ATLAS_W, ATLAS_H // 4),
}
ISLAND_GAINS = {"top": 0.42, "bottom": 0.55, "side": 1.35, "inner": 0.72}
SPELL_NAVY = np.array([2, 2, 42], dtype=np.float32)
SPELL_BLUE = np.array([0, 0, 235], dtype=np.float32)
SPELL_PERIWINKLE = np.array([142, 160, 255], dtype=np.float32)
SPELL_WHITE = np.array([247, 247, 251], dtype=np.float32)
SPELL_SOFT_SURFACE = np.array([244, 244, 246], dtype=np.float32)
SPELL_INK = np.array([8, 8, 22], dtype=np.float32)


@dataclass
class UvIsland:
    id: str
    role: str
    rect: Tuple[int, int, int, int]
    face_indices: List[int]
    axis_u: np.ndarray
    axis_v: np.ndarray
    min_u: float
    max_u: float
    min_v: float
    max_v: float
    gain: float
    damping: str
    cylindrical: bool = False


@dataclass
class UvLayout:
    islands: List[UvIsland]
    face_island_indices: List[int]
    radial: bool
    bb_min: np.ndarray
    bb_max: np.ndarray


def parse_vertex(line: str) -> Vec3 | None:
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


def token_value(source: str, key: str) -> str | None:
    match = re.search(rf"(?:^|\s){re.escape(key)}=([^\s,]+)", source)
    return match.group(1).strip("\"'") if match else None


def parse_uv_hint_strategy(text: str, target: str) -> str | None:
    current = ""
    for line in text.splitlines():
        object_match = OBJECT_RE.match(line)
        if object_match:
            current = object_match.group(1)
            continue
        hint_match = UV_HINT_RE.match(line)
        if not hint_match or current != target:
            continue
        strategy = token_value(hint_match.group(1), "strategy")
        if strategy:
            return strategy.lower()
    return None


def parse_obj_with_uv_islands(text: str, target: str) -> Tuple[List[str], List[Vec3], List[Face], List[str | None]]:
    header: List[str] = []
    vertices: List[Vec3] = []
    target_faces: List[Face] = []
    target_face_roles: List[str | None] = []
    current = ""
    current_uv_role: str | None = None
    vertex_count = 0
    target_vertex_indices: set[int] = set()

    for line in text.splitlines():
        object_match = OBJECT_RE.match(line)
        if object_match:
            current = object_match.group(1)
            current_uv_role = None
            continue
        uv_island_match = UV_ISLAND_RE.match(line)
        if uv_island_match and current == target:
            payload = uv_island_match.group(1)
            current_uv_role = token_value(payload, "role") or token_value(payload, "id")
            continue
        vertex = parse_vertex(line)
        if vertex is not None:
            vertex_count += 1
            vertices.append(vertex)
            if current == target:
                target_vertex_indices.add(vertex_count)
            continue
        if current != target:
            continue
        face_match = FACE_RE.match(line)
        if not face_match:
            continue
        indices: Face = []
        for token in face_match.group(1).strip().split():
            head = token.split("/")[0]
            if not head:
                continue
            index = int(head)
            if index < 0:
                index = vertex_count + index + 1
            if index > 0:
                indices.append(index)
        for i in range(1, len(indices) - 1):
            target_faces.append([indices[0], indices[i], indices[i + 1]])
            target_face_roles.append(current_uv_role)

    if not target_faces:
        raise RuntimeError(f"No target faces found for {target}")
    used = sorted({index for face in target_faces for index in face})
    remap = {old: next_index + 1 for next_index, old in enumerate(used)}
    target_vertices = [vertices[index - 1] for index in used]
    target_faces = [[remap[index] for index in face] for face in target_faces]

    # Preserve only scene-level metadata for the standalone trial output.
    for line in text.splitlines():
        if OBJECT_RE.match(line):
            break
        if line.strip():
            header.append(line)
    return header, target_vertices, target_faces, target_face_roles


def parse_obj(text: str, target: str) -> Tuple[List[str], List[Vec3], List[Face]]:
    header, vertices, faces, _ = parse_obj_with_uv_islands(text, target)
    return header, vertices, faces


def parse_obj_polygons_with_uv_islands(text: str, target: str) -> Tuple[List[Vec3], List[Face], List[str | None]]:
    vertices: List[Vec3] = []
    target_polygons: List[Face] = []
    target_roles: List[str | None] = []
    current = ""
    current_uv_role: str | None = None
    vertex_count = 0

    for line in text.splitlines():
        object_match = OBJECT_RE.match(line)
        if object_match:
            current = object_match.group(1)
            current_uv_role = None
            continue
        uv_island_match = UV_ISLAND_RE.match(line)
        if uv_island_match and current == target:
            payload = uv_island_match.group(1)
            current_uv_role = token_value(payload, "role") or token_value(payload, "id")
            continue
        vertex = parse_vertex(line)
        if vertex is not None:
            vertex_count += 1
            vertices.append(vertex)
            continue
        if current != target:
            continue
        face_match = FACE_RE.match(line)
        if not face_match:
            continue
        indices: Face = []
        for token in face_match.group(1).strip().split():
            head = token.split("/")[0]
            if not head:
                continue
            index = int(head)
            if index < 0:
                index = vertex_count + index + 1
            if index > 0:
                indices.append(index)
        if len(indices) >= 3:
            target_polygons.append(indices)
            target_roles.append(current_uv_role)

    if not target_polygons:
        raise RuntimeError(f"No target polygons found for {target}")
    used = sorted({index for face in target_polygons for index in face})
    remap = {old: next_index + 1 for next_index, old in enumerate(used)}
    target_vertices = [vertices[index - 1] for index in used]
    target_polygons = [[remap[index] for index in face] for face in target_polygons]
    return target_vertices, target_polygons, target_roles


def face_normal(arr: np.ndarray, face: Face) -> np.ndarray:
    a, b, c = [arr[index - 1] for index in face[:3]]
    normal = np.cross(b - a, c - a)
    length = float(np.linalg.norm(normal))
    return normal / length if length > 1e-12 else np.array([0.0, 1.0, 0.0])


def radial_role_for_normal(normal: np.ndarray) -> str:
    if normal[1] >= TOP_NORMAL_THRESHOLD:
        return "top"
    if normal[1] <= -TOP_NORMAL_THRESHOLD:
        return "bottom"
    return "side"


def radial_role_for_face(arr: np.ndarray, face: Face, normal: np.ndarray, bb_min: np.ndarray, bb_max: np.ndarray) -> str:
    points = np.array([arr[index - 1] for index in face], dtype=float)
    height = max(float(bb_max[1] - bb_min[1]), 1e-9)
    cap_band = max(height * RADIAL_CAP_HEIGHT_FRACTION, height * 0.015)
    centroid_y = float(points[:, 1].mean())
    min_y = float(points[:, 1].min())
    max_y = float(points[:, 1].max())
    horizontal = abs(float(normal[1])) >= RADIAL_CAP_NORMAL_THRESHOLD
    if horizontal and centroid_y >= float(bb_max[1]) - cap_band and min_y >= float(bb_max[1]) - cap_band * 1.8:
        return "top"
    if horizontal and centroid_y <= float(bb_min[1]) + cap_band and max_y <= float(bb_min[1]) + cap_band * 1.8:
        return "bottom"
    center = (bb_min + bb_max) * 0.5
    radial = np.array([float(points[:, 0].mean() - center[0]), 0.0, float(points[:, 2].mean() - center[2])])
    radial_length = float(np.linalg.norm(radial))
    if radial_length > 1e-9:
        radial = radial / radial_length
        if float(np.dot(normal, radial)) < -0.18:
            return "inner"
    return "side"


def planar_role_for_normal(normal: np.ndarray) -> str:
    if normal[1] >= TOP_NORMAL_THRESHOLD:
        return "top"
    if normal[1] <= -TOP_NORMAL_THRESHOLD:
        return "bottom"
    if abs(float(normal[0])) >= abs(float(normal[2])):
        return "right" if normal[0] >= 0 else "left"
    return "front" if normal[2] >= 0 else "back"


def role_gain(role: str) -> float:
    if role in ISLAND_GAINS:
        return ISLAND_GAINS[role]
    if role in {"left", "right", "front", "back"}:
        return 1.05
    return 0.8


def role_damping(role: str) -> str:
    if role == "top":
        return "high"
    if role in {"bottom", "inner"}:
        return "medium"
    return "low"


def side_u(point: np.ndarray, center: np.ndarray) -> float:
    # One seam at the back of the object; side faces unwrap into a continuous cylindrical strip.
    angle = math.atan2(float(point[0] - center[0]), float(point[2] - center[2]))
    return (angle + math.pi) / (2.0 * math.pi)


def role_axes(role: str) -> Tuple[np.ndarray, np.ndarray]:
    if role == "top":
        return np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
    if role == "bottom":
        return np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, -1.0])
    if role == "left":
        return np.array([0.0, 0.0, -1.0]), np.array([0.0, 1.0, 0.0])
    if role == "right":
        return np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0])
    if role == "back":
        return np.array([-1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    return np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])


def project_island(point: np.ndarray, island: UvIsland, bb_min: np.ndarray, bb_max: np.ndarray) -> Tuple[float, float]:
    size = np.maximum(bb_max - bb_min, 1e-9)
    p = (point - bb_min) / size
    center = (bb_min + bb_max) * 0.5
    if island.cylindrical:
        u, v = side_u(point, center), p[1]
    else:
        raw_u = float(np.dot(point, island.axis_u))
        raw_v = float(np.dot(point, island.axis_v))
        u = (raw_u - island.min_u) / max(island.max_u - island.min_u, 1e-9)
        v = (raw_v - island.min_v) / max(island.max_v - island.min_v, 1e-9)
    x, y, w, h = island.rect
    pad = 0.035 if island.role in {"side", "inner"} else 0.10
    uu = x + (pad + u * (1.0 - 2.0 * pad)) * w
    vv = y + (1.0 - (pad + v * (1.0 - 2.0 * pad))) * h
    return float(uu), float(vv)


def project_face_points(
    arr: np.ndarray,
    face: Face,
    island: UvIsland,
    bb_min: np.ndarray,
    bb_max: np.ndarray,
    unwrap_cylindrical_seam: bool = True,
) -> List[Tuple[float, float]]:
    pts = [project_island(arr[index - 1], island, bb_min, bb_max) for index in face]
    if not island.cylindrical or not unwrap_cylindrical_seam:
        return pts
    x0, _, w, _ = island.rect
    local_us = [(x - x0) / max(w, 1) for x, _ in pts]
    if max(local_us) - min(local_us) <= 0.5:
        return pts
    return [(x + (w if local_u < 0.5 else 0.0), y) for (x, y), local_u in zip(pts, local_us)]


def wrap_projected_point(point: Tuple[float, float], island: UvIsland) -> Tuple[float, float]:
    x, y = point
    if not island.cylindrical:
        return x, y
    x0, _, w, _ = island.rect
    local = (x - x0) % max(w, 1)
    return x0 + local, y


def project_sample_points(
    arr: np.ndarray, face: Face, island: UvIsland, bb_min: np.ndarray, bb_max: np.ndarray
) -> List[Tuple[float, float]]:
    return [
        wrap_projected_point(point, island)
        for point in project_face_points(arr, face, island, bb_min, bb_max, unwrap_cylindrical_seam=False)
    ]


def project_raster_face_point_sets(
    arr: np.ndarray, face: Face, island: UvIsland, bb_min: np.ndarray, bb_max: np.ndarray
) -> List[List[Tuple[float, float]]]:
    pts = project_face_points(arr, face, island, bb_min, bb_max, unwrap_cylindrical_seam=True)
    if not island.cylindrical:
        return [pts]
    x0, _, w, _ = island.rect
    x1 = x0 + w
    out = [pts]
    if any(x >= x1 for x, _ in pts):
        out.append([(x - w, y) for x, y in pts])
    if any(x < x0 for x, _ in pts):
        out.append([(x + w, y) for x, y in pts])
    return out


def face_edges(face: Face) -> Iterable[Tuple[int, int]]:
    for a, b in zip(face, face[1:] + face[:1]):
        yield tuple(sorted((a - 1, b - 1)))


def face_adjacency(faces: List[Face]) -> List[set[int]]:
    by_edge: Dict[Tuple[int, int], List[int]] = {}
    for face_index, face in enumerate(faces):
        for edge in face_edges(face):
            by_edge.setdefault(edge, []).append(face_index)
    out = [set() for _ in faces]
    for owners in by_edge.values():
        for a in owners:
            for b in owners:
                if a != b:
                    out[a].add(b)
    return out


def connected_face_components(faces: List[Face]) -> List[List[int]]:
    adj = face_adjacency(faces)
    visited: set[int] = set()
    components: List[List[int]] = []
    for start in range(len(faces)):
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        component: List[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in adj[current]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                stack.append(neighbor)
        components.append(component)
    return components


def is_radial_like(vertices: List[Vec3], faces: List[Face]) -> bool:
    if len(connected_face_components(faces)) > 1:
        return False
    arr = np.array(vertices, dtype=float)
    bb_min = arr.min(axis=0)
    bb_max = arr.max(axis=0)
    size = np.maximum(bb_max - bb_min, 1e-9)
    footprint = max(float(size[0]), float(size[2]))
    if float(size[1]) < footprint * 0.30:
        return False
    if min(float(size[0]), float(size[2])) < footprint * 0.25:
        return False
    normals = [face_normal(arr, face) for face in faces]
    side_count = sum(1 for normal in normals if radial_role_for_normal(normal) == "side")
    horizontal_count = len(faces) - side_count
    return side_count >= max(6, len(faces) * 0.35) and horizontal_count >= 1


def island_projected_bounds(arr: np.ndarray, faces: List[Face], face_indices: List[int], role: str) -> Tuple[np.ndarray, np.ndarray, float, float, float, float]:
    axis_u, axis_v = role_axes(role)
    points = [arr[index - 1] for face_index in face_indices for index in faces[face_index]]
    if not points:
        points = [arr[0]]
    us = np.array([float(np.dot(point, axis_u)) for point in points])
    vs = np.array([float(np.dot(point, axis_v)) for point in points])
    return axis_u, axis_v, float(us.min()), float(us.max()), float(vs.min()), float(vs.max())


def pack_rects(sizes: List[Tuple[int, int]]) -> List[Tuple[int, int, int, int]]:
    scale = 1.0
    while True:
        rects: List[Tuple[int, int, int, int]] = []
        x = 0
        y = 0
        shelf_h = 0
        ok = True
        for raw_w, raw_h in sizes:
            w = max(36, int(round(raw_w * scale)))
            h = max(36, int(round(raw_h * scale)))
            if w > ATLAS_W:
                ratio = ATLAS_W / max(w, 1)
                w = ATLAS_W
                h = max(36, int(round(h * ratio)))
            if x + w > ATLAS_W:
                x = 0
                y += shelf_h
                shelf_h = 0
            if y + h > ATLAS_H:
                ok = False
                break
            rects.append((x, y, w, h))
            x += w
            shelf_h = max(shelf_h, h)
        if ok:
            return rects
        scale *= 0.88


def fit_rects_to_square_atlas(rects: List[Tuple[int, int, int, int]]) -> List[Tuple[int, int, int, int]]:
    if not rects:
        return rects
    min_x = min(x for x, _, _, _ in rects)
    min_y = min(y for _, y, _, _ in rects)
    max_x = max(x + w for x, _, w, _ in rects)
    max_y = max(y + h for _, y, _, h in rects)
    span_x = max(max_x - min_x, 1)
    span_y = max(max_y - min_y, 1)
    margin = 12
    available_w = max(1, ATLAS_W - margin * 2)
    available_h = max(1, ATLAS_H - margin * 2)
    scale = min(available_w / span_x, available_h / span_y)
    origin_x = margin + (available_w - span_x * scale) * 0.5
    origin_y = margin + (available_h - span_y * scale) * 0.5
    fitted: List[Tuple[int, int, int, int]] = []
    for x, y, w, h in rects:
        x0 = int(round(origin_x + (x - min_x) * scale))
        y0 = int(round(origin_y + (y - min_y) * scale))
        x1 = int(round(origin_x + (x + w - min_x) * scale))
        y1 = int(round(origin_y + (y + h - min_y) * scale))
        fitted.append((x0, y0, max(1, x1 - x0), max(1, y1 - y0)))
    return fitted


def build_uv_layout(
    vertices: List[Vec3],
    faces: List[Face],
    authored_face_roles: List[str | None] | None = None,
    layout_strategy: str | None = None,
) -> UvLayout:
    arr = np.array(vertices, dtype=float)
    bb_min = arr.min(axis=0)
    bb_max = arr.max(axis=0)
    size = np.maximum(bb_max - bb_min, 1e-9)
    normals = [face_normal(arr, face) for face in faces]
    authored_roles_valid = (
        authored_face_roles is not None
        and len(authored_face_roles) == len(faces)
        and any(role for role in authored_face_roles)
    )
    force_radial = (layout_strategy or "").lower() == "radial"
    if force_radial:
        radial = True
        face_roles = [radial_role_for_face(arr, face, normal, bb_min, bb_max) for face, normal in zip(faces, normals)]
    elif authored_roles_valid:
        face_roles = [
            role if role else planar_role_for_normal(normal)
            for role, normal in zip(authored_face_roles or [], normals)
        ]
        role_set = {role for role in face_roles if role}
        radial = "side" in role_set and role_set.issubset({"top", "bottom", "side", "inner"})
        if radial:
            face_roles = [
                radial_role_for_face(arr, face, normal, bb_min, bb_max) if role == "side" else role
                for role, face, normal in zip(face_roles, faces, normals)
            ]
    else:
        radial = is_radial_like(vertices, faces)
        face_roles = [
            radial_role_for_face(arr, face, normal, bb_min, bb_max) if radial else planar_role_for_normal(normal)
            for face, normal in zip(faces, normals)
        ]

    groups: List[Tuple[str, List[int]]] = []
    if authored_roles_valid:
        role_order = ["top", "bottom", "side", "inner"] if radial else sorted({role for role in face_roles if role})
        for role in role_order:
            ids = [index for index, face_role in enumerate(face_roles) if face_role == role]
            if ids:
                groups.append((role, ids))
    elif radial:
        for role in ("top", "bottom", "side", "inner"):
            ids = [index for index, face_role in enumerate(face_roles) if face_role == role]
            if ids:
                groups.append((role, ids))
    else:
        adj = face_adjacency(faces)
        visited = set()
        for start, role in enumerate(face_roles):
            if start in visited:
                continue
            frontier = [start]
            visited.add(start)
            ids: List[int] = []
            while frontier:
                current = frontier.pop()
                ids.append(current)
                for neighbor in adj[current]:
                    if neighbor in visited or face_roles[neighbor] != role:
                        continue
                    visited.add(neighbor)
                    frontier.append(neighbor)
            groups.append((role, ids))
        groups.sort(key=lambda item: (-len(item[1]), item[0]))

    provisional_sizes: List[Tuple[int, int]] = []
    bounds: List[Tuple[np.ndarray, np.ndarray, float, float, float, float]] = []
    for role, ids in groups:
        axis_u, axis_v, min_u, max_u, min_v, max_v = island_projected_bounds(arr, faces, ids, role)
        bounds.append((axis_u, axis_v, min_u, max_u, min_v, max_v))
        if radial:
            radial_rects = RADIAL_HOLLOW_ISLAND_RECTS if any(group_role == "inner" for group_role, _ in groups) else RADIAL_ISLAND_RECTS
            rect = radial_rects[role]
            provisional_sizes.append((rect[2], rect[3]))
            continue
        span_u = max(max_u - min_u, 1e-6)
        span_v = max(max_v - min_v, 1e-6)
        density = math.sqrt((ATLAS_W * ATLAS_H * 0.62) / max(float(np.prod(size)), 1e-6))
        provisional_sizes.append((int(span_u * density) + 34, int(span_v * density) + 34))

    rects = (
        [
            (RADIAL_HOLLOW_ISLAND_RECTS if any(group_role == "inner" for group_role, _ in groups) else RADIAL_ISLAND_RECTS)[role]
            for role, _ in groups
        ]
        if radial
        else fit_rects_to_square_atlas(pack_rects(provisional_sizes))
    )
    islands: List[UvIsland] = []
    face_island_indices = [-1] * len(faces)
    for island_index, ((role, ids), rect, bound) in enumerate(zip(groups, rects, bounds)):
        axis_u, axis_v, min_u, max_u, min_v, max_v = bound
        island = UvIsland(
            id=f"island_{island_index + 1:03d}",
            role=role,
            rect=rect,
            face_indices=ids,
            axis_u=axis_u,
            axis_v=axis_v,
            min_u=min_u,
            max_u=max_u,
            min_v=min_v,
            max_v=max_v,
            gain=role_gain(role),
            damping=role_damping(role),
            cylindrical=radial and role in {"side", "inner"},
        )
        islands.append(island)
        for face_index in ids:
            face_island_indices[face_index] = island_index
    return UvLayout(
        islands=islands,
        face_island_indices=face_island_indices,
        radial=radial,
        bb_min=bb_min.copy(),
        bb_max=bb_max.copy(),
    )


def write_ppm(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(f"P6\n{image.shape[1]} {image.shape[0]}\n255\n".encode())
        handle.write(np.clip(image, 0, 255).astype(np.uint8).tobytes())


def write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = np.clip(image, 0, 255).astype(np.uint8)
    height, width = rgb.shape[:2]

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    scanlines = b"".join(b"\x00" + rgb[y].tobytes() for y in range(height))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def blend_pixel(img: np.ndarray, x: int, y: int, color: np.ndarray, alpha: float) -> None:
    if x < 0 or y < 0 or y >= img.shape[0] or x >= img.shape[1]:
        return
    img[y, x] = img[y, x] * (1.0 - alpha) + color * alpha


def draw_line(img: np.ndarray, a: Tuple[float, float], b: Tuple[float, float], color: np.ndarray, alpha: float, thickness: int = 1) -> None:
    x0, y0 = int(round(a[0])), int(round(a[1]))
    x1, y1 = int(round(b[0])), int(round(b[1]))
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    radius = max(0, thickness - 1)
    while True:
        for yy in range(y0 - radius, y0 + radius + 1):
            for xx in range(x0 - radius, x0 + radius + 1):
                blend_pixel(img, xx, yy, color, alpha)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def raster_triangle(img: np.ndarray, mask: np.ndarray, pts: List[Tuple[float, float]], color: np.ndarray) -> None:
    minx = max(0, int(math.floor(min(p[0] for p in pts))))
    maxx = min(img.shape[1] - 1, int(math.ceil(max(p[0] for p in pts))))
    miny = max(0, int(math.floor(min(p[1] for p in pts))))
    maxy = min(img.shape[0] - 1, int(math.ceil(max(p[1] for p in pts))))
    a, b, c = [np.array(p, dtype=float) for p in pts]
    denom = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(float(denom)) < 1e-9:
        return
    for y in range(miny, maxy + 1):
        xs = np.arange(minx, maxx + 1, dtype=float)
        ys = np.full_like(xs, y, dtype=float)
        w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / denom
        w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / denom
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
        if np.any(inside):
            xi = xs.astype(int)[inside]
            img[y, xi] = color
            mask[y, xi] = True


def raster_triangle_scalar(
    img: np.ndarray, mask: np.ndarray, pts: List[Tuple[float, float]], values: List[float]
) -> None:
    minx = max(0, int(math.floor(min(p[0] for p in pts))))
    maxx = min(img.shape[1] - 1, int(math.ceil(max(p[0] for p in pts))))
    miny = max(0, int(math.floor(min(p[1] for p in pts))))
    maxy = min(img.shape[0] - 1, int(math.ceil(max(p[1] for p in pts))))
    if minx > maxx or miny > maxy:
        return
    a, b, c = [np.array(p, dtype=float) for p in pts]
    denom = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(float(denom)) < 1e-9:
        return
    va, vb, vc = values
    for y in range(miny, maxy + 1):
        xs = np.arange(minx, maxx + 1, dtype=float)
        ys = np.full_like(xs, y, dtype=float)
        w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / denom
        w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / denom
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
        if np.any(inside):
            xi = xs.astype(int)[inside]
            img[y, xi] = va * w0[inside] + vb * w1[inside] + vc * w2[inside]
            mask[y, xi] = True


def atlas_image(vertices: List[Vec3], faces: List[Face], layout: UvLayout | None = None) -> Tuple[np.ndarray, np.ndarray]:
    layout = layout or build_uv_layout(vertices, faces)
    arr = np.array(vertices, dtype=float)
    bb_min = layout.bb_min
    bb_max = layout.bb_max
    img = np.zeros((ATLAS_H, ATLAS_W, 3), dtype=np.float32)
    mask = np.zeros((ATLAS_H, ATLAS_W), dtype=bool)
    img[:, :] = SPELL_NAVY
    for island in layout.islands:
        x, y, w, h = island.rect
        void_color = SPELL_NAVY * 0.86 + SPELL_BLUE * 0.14
        if island.role in {"side", "inner"}:
            void_color = SPELL_NAVY * 0.78 + SPELL_BLUE * 0.22
        img[y : y + h, x : x + w] = void_color
    light = np.array([0.35, 0.7, 0.55], dtype=float)
    light /= np.linalg.norm(light)
    for face_index, face in enumerate(faces):
        normal = face_normal(arr, face)
        island = layout.islands[layout.face_island_indices[face_index]]
        shade = 0.70 + 0.30 * max(0.0, float(np.dot(normal, light)))
        for pts in project_raster_face_point_sets(arr, face, island, bb_min, bb_max):
            for i in range(1, len(pts) - 1):
                raster_triangle(img, mask, [pts[0], pts[i], pts[i + 1]], SPELL_SOFT_SURFACE * shade)
    return img, mask


def fit_gray_to_atlas(image: np.ndarray) -> np.ndarray:
    if image.shape == (ATLAS_H, ATLAS_W):
        return image
    ys = np.linspace(0, image.shape[0] - 1, ATLAS_H).astype(int)
    xs = np.linspace(0, image.shape[1] - 1, ATLAS_W).astype(int)
    return image[ys[:, None], xs[None, :]]


def height_map_rgb(height_map: np.ndarray) -> np.ndarray:
    scaled = fit_gray_to_atlas(height_map)
    gray = np.clip(scaled * 255.0, 0, 255).astype(np.float32)
    return np.dstack([gray, gray, gray]).astype(np.float32)


def fit_rgb_to_atlas(image: np.ndarray) -> np.ndarray:
    if image.shape[:2] == (ATLAS_H, ATLAS_W):
        return image.astype(np.float32)
    ys = np.linspace(0, image.shape[0] - 1, ATLAS_H).astype(int)
    xs = np.linspace(0, image.shape[1] - 1, ATLAS_W).astype(int)
    return image[ys[:, None], xs[None, :]].astype(np.float32)


def uv_overlay_image(
    vertices: List[Vec3],
    faces: List[Face],
    background: np.ndarray,
    layout: UvLayout | None = None,
    face_island_indices: List[int] | None = None,
) -> np.ndarray:
    layout = layout or build_uv_layout(vertices, faces)
    face_island_indices = face_island_indices or layout.face_island_indices
    arr = np.array(vertices, dtype=float)
    bb_min = layout.bb_min
    bb_max = layout.bb_max
    img = background.astype(np.float32).copy()
    edge_color = SPELL_PERIWINKLE
    seam_color = SPELL_WHITE
    island_color = SPELL_BLUE

    for island in layout.islands:
        x, y, w, h = island.rect
        corners = [(x, y), (x + w - 1, y), (x + w - 1, y + h - 1), (x, y + h - 1)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            draw_line(img, a, b, island_color, 0.80, thickness=2)

    edge_islands: Dict[Tuple[int, int], set[int]] = {}
    edge_points: List[Tuple[Tuple[int, int], Tuple[float, float], Tuple[float, float]]] = []
    for face_index, face in enumerate(faces):
        island_index = face_island_indices[face_index]
        island = layout.islands[island_index]
        for edge_index, (a, b) in enumerate(zip(face, face[1:] + face[:1])):
            edge_islands.setdefault(tuple(sorted((a - 1, b - 1))), set()).add(island_index)
        for pts in project_raster_face_point_sets(arr, face, island, bb_min, bb_max):
            for edge_index, (a, b) in enumerate(zip(face, face[1:] + face[:1])):
                key = tuple(sorted((a - 1, b - 1)))
                edge_points.append((key, pts[edge_index], pts[(edge_index + 1) % len(pts)]))

    for key, a, b in edge_points:
        seam = len(edge_islands.get(key, set())) > 1
        draw_line(img, a, b, seam_color if seam else edge_color, 0.72 if seam else 0.32, thickness=2 if seam else 1)
    return img


def parse_bmp24(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if data[:2] != b"BM":
        raise RuntimeError("Expected BMP file")
    pixel_offset = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little", signed=True)
    raw_height = int.from_bytes(data[22:26], "little", signed=True)
    height = abs(raw_height)
    top_down = raw_height < 0
    bits = int.from_bytes(data[28:30], "little")
    if bits != 24:
        raise RuntimeError(f"Expected 24-bit BMP, got {bits}")
    stride = math.ceil((width * 3) / 4) * 4
    img = np.zeros((height, width), dtype=float)
    for y in range(height):
        row = y if top_down else height - 1 - y
        offset = pixel_offset + row * stride
        for x in range(width):
            b, g, r = data[offset + x * 3 : offset + x * 3 + 3]
            img[y, x] = (int(r) + int(g) + int(b)) / (3.0 * 255.0)
    return img


def parse_bmp24_rgb(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if data[:2] != b"BM":
        raise RuntimeError("Expected BMP file")
    pixel_offset = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little", signed=True)
    raw_height = int.from_bytes(data[22:26], "little", signed=True)
    height = abs(raw_height)
    top_down = raw_height < 0
    bits = int.from_bytes(data[28:30], "little")
    if bits != 24:
        raise RuntimeError(f"Expected 24-bit BMP, got {bits}")
    stride = math.ceil((width * 3) / 4) * 4
    img = np.zeros((height, width, 3), dtype=np.float32)
    for y in range(height):
        row = y if top_down else height - 1 - y
        offset = pixel_offset + row * stride
        for x in range(width):
            b, g, r = data[offset + x * 3 : offset + x * 3 + 3]
            img[y, x] = (int(r), int(g), int(b))
    return img


def bilinear(image: np.ndarray, x: float, y: float) -> float:
    h, w = image.shape
    x = min(max(x, 0.0), w - 1.0)
    y = min(max(y, 0.0), h - 1.0)
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    x1 = min(w - 1, x0 + 1)
    y1 = min(h - 1, y0 + 1)
    tx = x - x0
    ty = y - y0
    a = image[y0, x0] * (1.0 - tx) + image[y0, x1] * tx
    b = image[y1, x0] * (1.0 - tx) + image[y1, x1] * tx
    return float(a * (1.0 - ty) + b * ty)


def gaussian_kernel1d(sigma: float) -> np.ndarray:
    radius = max(1, int(round(sigma * 3.0)))
    xs = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-(xs * xs) / max(2.0 * sigma * sigma, 1e-9))
    return kernel / np.sum(kernel)


def gaussian_blur(image: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    kernel = gaussian_kernel1d(sigma)
    radius = len(kernel) // 2
    padded_x = np.pad(image, ((0, 0), (radius, radius)), mode="edge")
    tmp = np.zeros_like(image, dtype=float)
    for offset, weight in enumerate(kernel):
        tmp += padded_x[:, offset : offset + image.shape[1]] * weight
    padded_y = np.pad(tmp, ((radius, radius), (0, 0)), mode="edge")
    out = np.zeros_like(image, dtype=float)
    for offset, weight in enumerate(kernel):
        out += padded_y[offset : offset + image.shape[0], :] * weight
    return out


def make_periodic_side_gray(image: np.ndarray, layout: UvLayout, band: int = 36) -> np.ndarray:
    out = image.copy()
    for island in layout.islands:
        if island.role not in {"side", "inner"}:
            continue
        x, y, w, h = island.rect
        band_width = min(max(1, band), max(1, w // 4))
        panel = out[y : y + h, x : x + w].copy()
        for k in range(band_width):
            t = k / max(band_width - 1, 1)
            left_col = panel[:, k].copy()
            right_col = panel[:, w - band_width + k].copy()
            avg = (left_col + right_col) * 0.5
            panel[:, k] = avg * (1.0 - t) + left_col * t
            panel[:, w - band_width + k] = avg * t + right_col * (1.0 - t)
        panel[:, 0] = panel[:, -1] = (panel[:, 0] + panel[:, -1]) * 0.5
        out[y : y + h, x : x + w] = panel
    return out


def make_periodic_side_rgb(image: np.ndarray, layout: UvLayout, band: int = 36) -> np.ndarray:
    channels = [make_periodic_side_gray(image[:, :, channel], layout, band) for channel in range(3)]
    return np.dstack(channels).astype(np.float32)


def repair_side_missing_values(image: np.ndarray, source_mask: np.ndarray, layout: UvLayout) -> np.ndarray:
    out = image.copy()
    for island in layout.islands:
        if island.role not in {"side", "inner"}:
            continue
        x, y, w, h = island.rect
        panel = out[y : y + h, x : x + w].copy()
        panel_mask = source_mask[y : y + h, x : x + w]
        missing = panel_mask & (panel <= 0.025)
        if not np.any(missing):
            continue
        column_missing = np.mean(missing, axis=0) > 0.5
        column_covered = np.mean(panel_mask, axis=0) > 0.5
        missing_cols = np.flatnonzero(column_missing)
        if len(missing_cols) > 0:
            start = int(missing_cols[0])
            suffix = np.arange(start, w)
            if np.array_equal(missing_cols, suffix):
                source_start_candidates = np.flatnonzero(column_covered & ~column_missing)
                if len(source_start_candidates) > 0:
                    source_start = int(source_start_candidates[0])
                    source_width = max(1, start - source_start)
                    for col in suffix:
                        src_col = source_start + ((col - start) % source_width)
                        rows = missing[:, col] & panel_mask[:, src_col]
                        panel[rows, col] = panel[rows, src_col]
                    missing = panel_mask & (panel <= 0.025)
        for row in range(h):
            missing_x = np.flatnonzero(missing[row])
            if len(missing_x) == 0:
                continue
            good_x = np.flatnonzero(panel_mask[row] & ~missing[row])
            if len(good_x) == 0:
                continue
            for col in missing_x:
                distances = np.abs(good_x - col)
                circular_distances = np.minimum(distances, w - distances)
                panel[row, col] = panel[row, good_x[int(np.argmin(circular_distances))]]
        out[y : y + h, x : x + w] = panel
    return out


def preprocess_height_map(height_map: np.ndarray, source_mask: np.ndarray, layout: UvLayout) -> np.ndarray:
    out = repair_side_missing_values(height_map, source_mask, layout)
    for island in layout.islands:
        x, y, w, h = island.rect
        panel_mask = source_mask[y : y + h, x : x + w]
        panel = out[y : y + h, x : x + w]
        values = panel[panel_mask]
        if len(values) == 0:
            continue
        baseline = float(np.median(values))
        filled = panel.copy()
        filled[~panel_mask] = baseline
        blurred = gaussian_blur(filled, sigma=0.9 if island.role in {"side", "inner"} else 1.65)
        residual = blurred - baseline
        scale = float(np.percentile(np.abs(residual[panel_mask]), 96))
        if scale > 1e-6:
            residual = np.clip(residual, -scale, scale)
        panel[panel_mask] = np.clip(baseline + residual[panel_mask], 0.0, 1.0)
        panel[~panel_mask] = 0.0
        out[y : y + h, x : x + w] = panel
    return make_periodic_side_gray(out, layout)


def bleed_rgb(image: np.ndarray, mask: np.ndarray, iterations: int = 24) -> np.ndarray:
    out = image.astype(np.float32).copy()
    filled = mask.copy()
    for _ in range(max(0, iterations)):
        neighbor_sum = np.zeros_like(out)
        neighbor_count = np.zeros(filled.shape, dtype=np.float32)
        for y0, y1, src_y0, src_y1, x0, x1, src_x0, src_x1 in (
            (1, None, 0, -1, 0, None, 0, None),
            (0, -1, 1, None, 0, None, 0, None),
            (0, None, 0, None, 1, None, 0, -1),
            (0, None, 0, None, 0, -1, 1, None),
        ):
            src_mask = filled[src_y0:src_y1, src_x0:src_x1]
            neighbor_sum[y0:y1, x0:x1] += out[src_y0:src_y1, src_x0:src_x1] * src_mask[:, :, None]
            neighbor_count[y0:y1, x0:x1] += src_mask
        fillable = (~filled) & (neighbor_count > 0)
        if not np.any(fillable):
            break
        next_out = out.copy()
        next_filled = filled.copy()
        next_out[fillable] = neighbor_sum[fillable] / neighbor_count[fillable, None]
        next_filled[fillable] = True
        out = next_out
        filled = next_filled
    return out


def diffuse_texture(height_map: np.ndarray, source_mask: np.ndarray, layout: UvLayout) -> np.ndarray:
    height = preprocess_height_map(height_map, source_mask, layout)
    base = np.array([236, 231, 221], dtype=np.float32)
    glaze = np.array([214, 222, 255], dtype=np.float32)
    accent = SPELL_BLUE
    outside = base * 0.82 + glaze * 0.18
    detail = np.clip((height - 0.5) * 2.0, -1.0, 1.0)
    glaze_mix = np.clip(0.28 + detail * 0.22, 0.08, 0.62)
    accent_mix = np.clip(np.maximum(-detail, 0.0) * 0.16, 0.0, 0.16)
    rgb = base[None, None, :] * (1.0 - glaze_mix[:, :, None]) + glaze[None, None, :] * glaze_mix[:, :, None]
    rgb = rgb * (1.0 - accent_mix[:, :, None]) + accent[None, None, :] * accent_mix[:, :, None]
    # Diffuse atlases should never expose debug/background colors. Mipmapping and UV seams can
    # sample outside islands, so keep empty pixels close to the object material.
    rgb[~source_mask] = outside
    rgb = make_periodic_side_rgb(rgb, layout)
    rgb = bleed_rgb(rgb, source_mask, iterations=28)
    return np.clip(rgb, 0, 255)


def bake_vertex_scalar_to_atlas(
    vertices: List[Vec3],
    faces: List[Face],
    layout: UvLayout,
    face_island_indices: List[int],
    values: List[float],
) -> Tuple[np.ndarray, np.ndarray]:
    arr = np.array(vertices, dtype=float)
    bb_min = layout.bb_min
    bb_max = layout.bb_max
    raw = np.array(values, dtype=float)
    scale = float(np.percentile(np.abs(raw), 96)) if len(raw) else 1.0
    if scale <= 1e-9:
        scale = 1.0
    normalized = np.clip(raw / scale, -1.0, 1.0)
    img = np.full((ATLAS_H, ATLAS_W), 0.5, dtype=float)
    mask = np.zeros((ATLAS_H, ATLAS_W), dtype=bool)
    for face, island_index in zip(faces, face_island_indices):
        island = layout.islands[island_index]
        face_values = [0.5 + 0.5 * float(normalized[index - 1]) for index in face]
        for pts in project_raster_face_point_sets(arr, face, island, bb_min, bb_max):
            for i in range(1, len(pts) - 1):
                raster_triangle_scalar(
                    img,
                    mask,
                    [pts[0], pts[i], pts[i + 1]],
                    [face_values[0], face_values[i], face_values[i + 1]],
                )
    img = repair_side_missing_values(img, mask, layout)
    img = make_periodic_side_gray(img, layout, band=36)
    return np.clip(img, 0.0, 1.0), mask


def diffuse_texture_from_displacement(displacement_map: np.ndarray, source_mask: np.ndarray, layout: UvLayout) -> np.ndarray:
    base = np.array([236, 231, 221], dtype=np.float32)
    glaze = np.array([214, 222, 255], dtype=np.float32)
    accent = SPELL_BLUE
    outside = base * 0.82 + glaze * 0.18
    detail = np.clip((displacement_map - 0.5) * 2.0, -1.0, 1.0)
    glaze_mix = np.clip(0.24 + detail * 0.18, 0.08, 0.58)
    valley = np.maximum(-detail, 0.0)
    ridge = np.maximum(detail, 0.0)
    accent_mix = np.clip(valley * 0.30 + ridge * 0.05, 0.0, 0.34)
    rgb = base[None, None, :] * (1.0 - glaze_mix[:, :, None]) + glaze[None, None, :] * glaze_mix[:, :, None]
    rgb = rgb * (1.0 - accent_mix[:, :, None]) + accent[None, None, :] * accent_mix[:, :, None]
    rgb[~source_mask] = outside
    rgb = make_periodic_side_rgb(rgb, layout)
    rgb = bleed_rgb(rgb, source_mask, iterations=28)
    return np.clip(rgb, 0, 255)


def reconciled_generated_diffuse(
    generated_rgb: np.ndarray,
    fallback_rgb: np.ndarray,
    source_mask: np.ndarray,
    layout: UvLayout,
) -> np.ndarray:
    generated = fit_rgb_to_atlas(generated_rgb)
    out = fallback_rgb.astype(np.float32).copy()
    brightness = np.mean(generated, axis=2)
    spread = np.max(generated, axis=2) - np.min(generated, axis=2)
    valid_inside = source_mask & (brightness > 24.0) & ~((brightness > 232.0) & (spread < 28.0))
    out[valid_inside] = generated[valid_inside] * 0.72 + fallback_rgb[valid_inside] * 0.28
    out[~source_mask] = fallback_rgb[~source_mask]
    out = make_periodic_side_rgb(out, layout)
    out = bleed_rgb(out, source_mask, iterations=32)
    return np.clip(out, 0, 255)


def island_height_stats(height_map: np.ndarray, source_mask: np.ndarray, layout: UvLayout) -> Tuple[List[float], List[float]]:
    baselines: List[float] = []
    scales: List[float] = []
    for island in layout.islands:
        x, y, w, h = island.rect
        mx = source_mask[y : y + h, x : x + w]
        values = height_map[y : y + h, x : x + w][mx]
        if len(values) == 0:
            baselines.append(0.5)
            scales.append(1.0)
            continue
        baseline = float(np.median(values))
        residual = values - baseline
        scale = float(np.percentile(np.abs(residual), 90))
        baselines.append(baseline)
        scales.append(max(scale, 0.02 if island.role in {"side", "inner"} else 0.045))
    return baselines, scales


def barycentric_2d(point: Tuple[float, float], triangle: np.ndarray) -> Tuple[float, float, float] | None:
    a, b, c = triangle
    px, py = point
    denom = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(float(denom)) < 1e-9:
        return None
    w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / denom
    w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / denom
    w2 = 1.0 - w0 - w1
    if w0 < -1e-5 or w1 < -1e-5 or w2 < -1e-5:
        return None
    return float(w0), float(w1), float(w2)


def boundary_weight_for_island(island: UvIsland, u: float, v: float) -> float:
    if island.role in {"side", "inner"}:
        edge = min(v, 1.0 - v)
        fade = min(1.0, max(0.0, edge * 14.0))
        return fade ** 0.75
    edge = min(u, 1.0 - u, v, 1.0 - v)
    fade = min(1.0, max(0.0, edge * 10.0))
    if island.role == "top":
        return fade ** 2.4
    return fade ** 1.6


def island_seam_fade(faces: List[Face], count: int, face_island_indices: List[int], rings: int = 10) -> np.ndarray:
    edge_islands: Dict[Tuple[int, int], set[int]] = {}
    for face, island_index in zip(faces, face_island_indices):
        for a, b in zip(face, face[1:] + face[:1]):
            key = tuple(sorted((a - 1, b - 1)))
            edge_islands.setdefault(key, set()).add(island_index)
    seam_vertices = {
        index for edge, islands_for_edge in edge_islands.items() if len(islands_for_edge) > 1 for index in edge
    }
    if not seam_vertices:
        return np.ones(count, dtype=float)
    adj = adjacency(faces, count)
    distance = np.full(count, rings + 1, dtype=int)
    frontier = list(seam_vertices)
    for index in frontier:
        distance[index] = 0
    cursor = 0
    while cursor < len(frontier):
        current = frontier[cursor]
        cursor += 1
        if distance[current] >= rings:
            continue
        for neighbor in adj[current]:
            if distance[neighbor] <= distance[current] + 1:
                continue
            distance[neighbor] = distance[current] + 1
            frontier.append(neighbor)
    return np.clip(distance / max(rings, 1), 0.0, 1.0)


def map_remesh(
    vertices: List[Vec3],
    faces: List[Face],
    height_map: np.ndarray,
    amount: float,
    remesh_step: float,
    remesh_levels: int | None = None,
    authored_face_roles: List[str | None] | None = None,
    layout_strategy: str | None = None,
) -> Tuple[List[Vec3], List[Face], List[Vec3], List[Vec3], UvLayout, List[int], List[float], List[Vec3]]:
    source_layout = build_uv_layout(vertices, faces, authored_face_roles, layout_strategy)
    _, source_mask = atlas_image(vertices, faces, source_layout)
    height_map = preprocess_height_map(height_map, source_mask, source_layout)
    island_baselines, island_scales = island_height_stats(height_map, source_mask, source_layout)

    if remesh_levels is None:
        if len(faces) < 500:
            remesh_levels = 3
        elif len(faces) < 2500:
            remesh_levels = 2
        elif len(faces) < 12000:
            remesh_levels = 1
        else:
            remesh_levels = 0
        if remesh_step <= 8 and len(faces) < 2500:
            remesh_levels = min(4, remesh_levels + 1)
    remesh_levels = max(0, min(4, remesh_levels))

    sub_vertices, sub_faces, parent_faces = subdivide(vertices, faces, remesh_levels)
    uv_vertices = list(sub_vertices)
    sub_vertices = fair_subdivided_surface(sub_vertices, sub_faces, iterations=5 if remesh_levels > 0 else 0)
    arr = np.array(sub_vertices, dtype=float)
    uv_arr = np.array(uv_vertices, dtype=float)
    bb_min = source_layout.bb_min
    bb_max = source_layout.bb_max
    normals = smoothed_vertex_normals(sub_vertices, sub_faces)
    proposals = np.zeros(len(sub_vertices), dtype=float)
    weights = np.zeros(len(sub_vertices), dtype=float)
    sub_face_island_indices = [source_layout.face_island_indices[parent] for parent in parent_faces]

    for face, island_index in zip(sub_faces, sub_face_island_indices):
        island = source_layout.islands[island_index]
        pts = project_sample_points(uv_arr, face, island, bb_min, bb_max)
        for index, (x, y) in zip(face, pts):
            sample = bilinear(height_map, x, y)
            detail = max(-1.0, min(1.0, (sample - island_baselines[island_index]) / island_scales[island_index]))
            x0, y0, w, h = island.rect
            uu = (x - x0) / max(w - 1, 1)
            vv = (y - y0) / max(h - 1, 1)
            proposals[index - 1] += detail * island.gain * boundary_weight_for_island(island, uu, vv)
            weights[index - 1] += 1.0

    valid = weights > 0
    proposals[valid] /= weights[valid]
    disp = proposals.copy()
    adj = adjacency(sub_faces, len(sub_vertices))
    for _ in range(8):
        next_disp = disp.copy()
        for i, neighbors in enumerate(adj):
            if not neighbors:
                continue
            avg = float(np.mean(disp[list(neighbors)]))
            data_weight = min(1.0, weights[i])
            next_disp[i] = (proposals[i] * data_weight + avg * 0.65) / (data_weight + 0.65)
        disp = next_disp

    island_weights = vertex_island_weights(sub_vertices, sub_faces, sub_face_island_indices, source_layout)
    open_boundary = boundary_fade(sub_faces, len(sub_vertices), rings=10)
    uv_seams = island_seam_fade(sub_faces, len(sub_vertices), sub_face_island_indices, rings=12)
    top_damping = 1.0 - 0.65 * island_weights.get("top", np.zeros(len(sub_vertices), dtype=float))
    disp *= np.power(open_boundary, 1.5) * np.power(uv_seams, 1.8) * top_damping
    amplitude = 0.085 * max(0.0, amount) * float(np.min(np.maximum(bb_max - bb_min, 1e-9)))
    disp = clamp_displacement_to_local_scale(disp, amplitude, sub_vertices, sub_faces, bb_min, bb_max)
    base_arr = arr.copy()
    out_arr = arr + normals * (disp[:, None] * amplitude)
    out_vertices = [(float(x), float(y), float(z)) for x, y, z in out_arr]
    base_vertices = [(float(x), float(y), float(z)) for x, y, z in base_arr]
    out_faces = sub_faces
    deltas = [
        (float(final[0] - base[0]), float(final[1] - base[1]), float(final[2] - base[2]))
        for final, base in zip(out_vertices, base_vertices)
    ]
    return (
        out_vertices,
        out_faces,
        base_vertices,
        deltas,
        source_layout,
        sub_face_island_indices,
        [float(value) for value in disp],
        uv_vertices,
    )


def midpoint(a: Vec3, b: Vec3) -> Vec3:
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


def subdivide(vertices: List[Vec3], faces: List[Face], levels: int) -> Tuple[List[Vec3], List[Face], List[int]]:
    out_vertices = list(vertices)
    out_faces = [list(face) for face in faces]
    parent_faces = list(range(len(faces)))
    for _ in range(levels):
        edge_midpoints: Dict[Tuple[int, int], int] = {}

        def mid_index(a: int, b: int) -> int:
            key = tuple(sorted((a, b)))
            if key in edge_midpoints:
                return edge_midpoints[key]
            out_vertices.append(midpoint(out_vertices[a - 1], out_vertices[b - 1]))
            edge_midpoints[key] = len(out_vertices)
            return len(out_vertices)

        next_faces: List[Face] = []
        next_parents: List[int] = []
        for parent_face, (a, b, c) in zip(parent_faces, out_faces):
            ab = mid_index(a, b)
            bc = mid_index(b, c)
            ca = mid_index(c, a)
            next_faces.extend([[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]])
            next_parents.extend([parent_face, parent_face, parent_face, parent_face])
        out_faces = next_faces
        parent_faces = next_parents
    return out_vertices, out_faces, parent_faces


def vertex_normals(vertices: List[Vec3], faces: List[Face]) -> np.ndarray:
    arr = np.array(vertices, dtype=float)
    normals = np.zeros_like(arr)
    for face in faces:
        normal = face_normal(arr, face)
        for index in face:
            normals[index - 1] += normal
    for i, normal in enumerate(normals):
        length = float(np.linalg.norm(normal))
        normals[i] = normal / length if length > 1e-12 else np.array([0.0, 1.0, 0.0])
    return normals


def adjacency(faces: List[Face], count: int) -> List[set[int]]:
    adj = [set() for _ in range(count)]
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            adj[a - 1].add(b - 1)
            adj[b - 1].add(a - 1)
    return adj


def fair_subdivided_surface(vertices: List[Vec3], faces: List[Face], iterations: int = 8) -> List[Vec3]:
    if iterations <= 0 or not vertices:
        return vertices
    arr = np.array(vertices, dtype=float)
    adj = adjacency(faces, len(vertices))
    boundary = boundary_fade(faces, len(vertices), rings=4)
    weights = np.power(boundary, 0.65)[:, None]
    for _ in range(iterations):
        for strength in (0.34, -0.36):
            lap = np.zeros_like(arr)
            for index, neighbors in enumerate(adj):
                if neighbors:
                    lap[index] = arr[list(neighbors)].mean(axis=0) - arr[index]
            arr = arr + lap * weights * strength
    return [(float(x), float(y), float(z)) for x, y, z in arr]


def local_edge_lengths(vertices: List[Vec3], faces: List[Face]) -> np.ndarray:
    arr = np.array(vertices, dtype=float)
    lengths: List[List[float]] = [[] for _ in vertices]
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            distance = float(np.linalg.norm(arr[a - 1] - arr[b - 1]))
            if distance > 1e-12:
                lengths[a - 1].append(distance)
                lengths[b - 1].append(distance)
    fallback = float(np.linalg.norm(arr.max(axis=0) - arr.min(axis=0))) * 0.015
    return np.array([float(np.median(items)) if items else fallback for items in lengths], dtype=float)


def clamp_displacement_to_local_scale(
    disp: np.ndarray,
    amplitude: float,
    vertices: List[Vec3],
    faces: List[Face],
    bb_min: np.ndarray,
    bb_max: np.ndarray,
) -> np.ndarray:
    if amplitude <= 1e-12 or disp.size == 0:
        return disp
    min_dim = float(np.min(np.maximum(bb_max - bb_min, 1e-9)))
    edge = local_edge_lengths(vertices, faces)
    distance_cap = np.maximum(edge * 2.4, min_dim * 0.040)
    distance_cap = np.minimum(distance_cap, min_dim * 0.145)
    return np.clip(disp, -distance_cap / amplitude, distance_cap / amplitude)


def smoothed_vertex_normals(vertices: List[Vec3], faces: List[Face], iterations: int = 10) -> np.ndarray:
    normals = vertex_normals(vertices, faces)
    adj = adjacency(faces, len(vertices))
    for _ in range(max(0, iterations)):
        next_normals = normals.copy()
        for index, neighbors in enumerate(adj):
            if not neighbors:
                continue
            blended = normals[index] * 0.45 + normals[list(neighbors)].mean(axis=0) * 0.55
            length = float(np.linalg.norm(blended))
            if length > 1e-12:
                next_normals[index] = blended / length
        normals = next_normals
    return normals


def face_islands(vertices: List[Vec3], faces: List[Face], layout: UvLayout | None = None) -> List[str]:
    layout = layout or build_uv_layout(vertices, faces)
    return [layout.islands[index].role for index in layout.face_island_indices]


def vertex_island_weights(vertices: List[Vec3], faces: List[Face], face_island_indices: List[int], layout: UvLayout) -> Dict[str, np.ndarray]:
    roles = sorted({island.role for island in layout.islands} | {"top", "bottom", "side"})
    weights = {role: np.zeros(len(vertices), dtype=float) for role in roles}
    for face, island_index in zip(faces, face_island_indices):
        role = layout.islands[island_index].role
        for index in face:
            weights[role][index - 1] += 1.0
    total = sum(weights.values())
    valid = total > 0
    for role in weights:
        weights[role][valid] /= total[valid]
    return weights


def boundary_fade(faces: List[Face], count: int, rings: int = 6) -> np.ndarray:
    adj = adjacency(faces, count)
    edge_counts: Dict[Tuple[int, int], int] = {}
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            key = tuple(sorted((a - 1, b - 1)))
            edge_counts[key] = edge_counts.get(key, 0) + 1
    boundary = {index for edge, c in edge_counts.items() if c == 1 for index in edge}
    if not boundary:
        return np.ones(count, dtype=float)
    distance = np.full(count, rings + 1, dtype=int)
    frontier = list(boundary)
    for index in frontier:
        distance[index] = 0
    cursor = 0
    while cursor < len(frontier):
        current = frontier[cursor]
        cursor += 1
        if distance[current] >= rings:
            continue
        for neighbor in adj[current]:
            if distance[neighbor] <= distance[current] + 1:
                continue
            distance[neighbor] = distance[current] + 1
            frontier.append(neighbor)
    return np.clip(distance / max(rings, 1), 0.0, 1.0)


def seam_fade(vertices: List[Vec3], faces: List[Face], rings: int = 5) -> np.ndarray:
    islands = face_islands(vertices, faces)
    edge_islands: Dict[Tuple[int, int], set[str]] = {}
    for face, island in zip(faces, islands):
        for a, b in zip(face, face[1:] + face[:1]):
            key = tuple(sorted((a - 1, b - 1)))
            edge_islands.setdefault(key, set()).add(island)
    seam_vertices = {
        index for edge, islands_for_edge in edge_islands.items() if len(islands_for_edge) > 1 for index in edge
    }
    if not seam_vertices:
        return np.ones(len(vertices), dtype=float)
    adj = adjacency(faces, len(vertices))
    distance = np.full(len(vertices), rings + 1, dtype=int)
    frontier = list(seam_vertices)
    for index in frontier:
        distance[index] = 0
    cursor = 0
    while cursor < len(frontier):
        current = frontier[cursor]
        cursor += 1
        if distance[current] >= rings:
            continue
        for neighbor in adj[current]:
            if distance[neighbor] <= distance[current] + 1:
                continue
            distance[neighbor] = distance[current] + 1
            frontier.append(neighbor)
    return np.clip(distance / max(rings, 1), 0.0, 1.0)


def apply_height(
    vertices: List[Vec3],
    faces: List[Face],
    height_map: np.ndarray,
    levels: int,
    amount: float,
    authored_face_roles: List[str | None] | None = None,
    layout_strategy: str | None = None,
) -> Tuple[List[Vec3], List[Face], List[Vec3], List[Vec3], UvLayout, List[int], List[float], List[Vec3]]:
    source_layout = build_uv_layout(vertices, faces, authored_face_roles, layout_strategy)
    sub_vertices, sub_faces, parent_faces = subdivide(vertices, faces, levels)
    uv_vertices = list(sub_vertices)
    sub_vertices = fair_subdivided_surface(sub_vertices, sub_faces, iterations=8 if levels > 0 else 0)
    arr = np.array(sub_vertices, dtype=float)
    uv_arr = np.array(uv_vertices, dtype=float)
    bb_min = source_layout.bb_min
    bb_max = source_layout.bb_max
    normals = smoothed_vertex_normals(sub_vertices, sub_faces)
    proposals = np.zeros(len(sub_vertices), dtype=float)
    weights = np.zeros(len(sub_vertices), dtype=float)

    # Build a source coverage mask and use generated values only inside that mask.
    _, source_mask = atlas_image(vertices, faces, source_layout)
    height_map = preprocess_height_map(height_map, source_mask, source_layout)
    island_baselines, island_scales = island_height_stats(height_map, source_mask, source_layout)

    sub_face_island_indices = [source_layout.face_island_indices[parent] for parent in parent_faces]
    for face, island_index in zip(sub_faces, sub_face_island_indices):
        island = source_layout.islands[island_index]
        pts = project_sample_points(uv_arr, face, island, bb_min, bb_max)
        for index, (x, y) in zip(face, pts):
            sample = bilinear(height_map, x, y)
            detail = max(-1.0, min(1.0, (sample - island_baselines[island_index]) / island_scales[island_index]))
            proposals[index - 1] += detail * island.gain
            weights[index - 1] += 1.0

    valid = weights > 0
    proposals[valid] /= weights[valid]
    disp = proposals.copy()
    adj = adjacency(sub_faces, len(sub_vertices))
    smooth_weight = 1.45
    for _ in range(18):
        next_disp = disp.copy()
        for i, neighbors in enumerate(adj):
            if not neighbors:
                continue
            avg = float(np.mean(disp[list(neighbors)]))
            data_weight = min(1.0, weights[i])
            next_disp[i] = (proposals[i] * data_weight + avg * smooth_weight) / (data_weight + smooth_weight)
        disp = next_disp
    island_weights = vertex_island_weights(sub_vertices, sub_faces, sub_face_island_indices, source_layout)
    open_boundary = boundary_fade(sub_faces, len(sub_vertices), rings=14)
    uv_seams = island_seam_fade(sub_faces, len(sub_vertices), sub_face_island_indices, rings=12)
    top_damping = 1.0 - 0.86 * island_weights.get("top", np.zeros(len(sub_vertices), dtype=float))
    disp *= np.power(open_boundary, 2.2) * np.power(uv_seams, 1.8) * top_damping
    amplitude = 0.095 * max(0.0, amount) * float(np.min(np.maximum(bb_max - bb_min, 1e-9)))
    disp = clamp_displacement_to_local_scale(disp, amplitude, sub_vertices, sub_faces, bb_min, bb_max)
    base_arr = arr.copy()
    arr = arr + normals * (disp[:, None] * amplitude)
    enhanced_vertices = [(float(x), float(y), float(z)) for x, y, z in arr]
    base_vertices = [(float(x), float(y), float(z)) for x, y, z in base_arr]
    deltas = [
        (float(final[0] - base[0]), float(final[1] - base[1]), float(final[2] - base[2]))
        for final, base in zip(enhanced_vertices, base_vertices)
    ]
    return (
        enhanced_vertices,
        sub_faces,
        base_vertices,
        deltas,
        source_layout,
        sub_face_island_indices,
        [float(value) for value in disp],
        uv_vertices,
    )


def write_obj(
    header: List[str],
    target: str,
    vertices: List[Vec3],
    faces: List[Face],
    shade: str,
    amount: float,
    base_vertices: List[Vec3] | None = None,
    deltas: List[Vec3] | None = None,
    topology: str = "subdivision_displace",
    layout: UvLayout | None = None,
    face_island_indices: List[int] | None = None,
    diffuse_path: str | None = None,
    height_path: str | None = None,
    debug_image_paths: List[Tuple[str, str]] | None = None,
    uv_vertices: List[Vec3] | None = None,
) -> str:
    layout = layout or build_uv_layout(vertices, faces)
    face_island_indices = face_island_indices or layout.face_island_indices
    shade = "flat" if shade == "flat" else "smooth"
    arr = np.array(vertices, dtype=float)
    if uv_vertices is not None and len(uv_vertices) == len(vertices):
        uv_arr = np.array(uv_vertices, dtype=float)
    elif base_vertices is not None and len(base_vertices) == len(vertices):
        uv_arr = np.array(base_vertices, dtype=float)
    else:
        uv_arr = arr
    vertex_normal_values = vertex_normals(vertices, faces)
    face_normal_values = [face_normal(arr, face) for face in faces]
    uv_bb_min = layout.bb_min
    uv_bb_max = layout.bb_max
    face_uvs: List[List[int]] = []
    uv_values: List[Tuple[float, float]] = []
    for face_index, face in enumerate(faces):
        island = layout.islands[face_island_indices[face_index]]
        projected = project_face_points(uv_arr, face, island, uv_bb_min, uv_bb_max)
        uv_indices: List[int] = []
        for x, y in projected:
            u = x / max(ATLAS_W - 1, 1)
            v = max(0.0, min(1.0, 1.0 - y / max(ATLAS_H - 1, 1)))
            uv_values.append((u, v))
            uv_index = len(uv_values)
            uv_indices.append(uv_index)
        face_uvs.append(uv_indices)

    material_name = f"{target}_uv_dream_mat"
    lines = [
        line
        for line in header
        if line.strip() and not line.startswith(f"#@material_preset: {material_name} ")
    ]
    lines.append(
        f"#@material_preset: {material_name} color=#d8d1c4 roughness=0.82 metalness=0.0 "
        f"shade_smooth={'false' if shade == 'flat' else 'true'}"
    )
    lines.append("")
    lines.append(f"o {target}")
    lines.append("#@source: llm_mesh")
    lines.append("#@workflow_step: uv_dream_enhance")
    lines.append(
        f"#@params: dream_displacement_amount={amount:.4f}, dream_shade={shade}, "
        f"dream_topology={topology}"
    )
    lines.append("#@controls:")
    lines.append(
        "#@ - slider key=dream_displacement_amount label=Displacement min=0 max=2 step=0.05"
    )
    lines.append("#@ - select key=dream_shade label=Shading options=smooth|flat")
    lines.append(f"#@material: {material_name}")
    if diffuse_path:
        lines.append(f"#@texture: kind=diffuse path={diffuse_path}")
    if height_path:
        lines.append(f"#@texture: kind=height path={height_path}")
    for kind, path in debug_image_paths or []:
        lines.append(f"#@debug_image: kind={kind} path={path}")
    lines.append(f"#@shade: {shade}")
    if base_vertices is not None and deltas is not None and len(base_vertices) == len(vertices):
        delta_scale = amount if math.isfinite(amount) and abs(amount) > 1e-9 else 1.0
        for (bx, by, bz), (dx, dy, dz) in zip(base_vertices, deltas):
            lines.append(f"#@dream_base_v {bx:.6f} {by:.6f} {bz:.6f}")
            lines.append(
                f"#@dream_delta_v {dx / delta_scale:.6f} {dy / delta_scale:.6f} {dz / delta_scale:.6f}"
            )
    for x, y, z in vertices:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for u, v in uv_values:
        lines.append(f"vt {u:.6f} {v:.6f}")
    if shade == "flat":
        for x, y, z in face_normal_values:
            lines.append(f"vn {x:.6f} {y:.6f} {z:.6f}")
        for normal_index, (face, uv_indices) in enumerate(zip(faces, face_uvs), start=1):
            lines.append(
                "f " + " ".join(f"{index}/{uv}/{normal_index}" for index, uv in zip(face, uv_indices))
            )
    else:
        for x, y, z in vertex_normal_values:
            lines.append(f"vn {x:.6f} {y:.6f} {z:.6f}")
        for face, uv_indices in zip(faces, face_uvs):
            lines.append("f " + " ".join(f"{index}/{uv}/{index}" for index, uv in zip(face, uv_indices)))
    return "\n".join(lines).rstrip() + "\n"


def layout_manifest(layout: UvLayout, amount: float = 1.0, shade: str = "smooth") -> Dict[str, object]:
    return {
        "atlas_size": [ATLAS_W, ATLAS_H],
        "unwrap": "radial_side_strip" if layout.radial else "adaptive_connected_normal_charts",
        "displacement_amount": amount,
        "shade": "flat" if shade == "flat" else "smooth",
        "islands": [
            {
                "id": island.id,
                "role": island.role,
                "bbox": list(island.rect),
                "face_count": len(island.face_indices),
                "displacement_gain": island.gain,
                "boundary_damping": island.damping,
                "projection": "cylindrical" if island.cylindrical else "planar",
            }
            for island in layout.islands
        ],
    }


def write_manifest(
    path: Path,
    vertices: List[Vec3],
    faces: List[Face],
    amount: float = 1.0,
    shade: str = "smooth",
    layout: UvLayout | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    layout = layout or build_uv_layout(vertices, faces)
    path.write_text(json.dumps(layout_manifest(layout, amount=amount, shade=shade), indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--target", required=True)
    parser.add_argument("--atlas-out")
    parser.add_argument("--debug-source-uv-out")
    parser.add_argument("--debug-final-uv-out")
    parser.add_argument("--processed-height-out")
    parser.add_argument("--diffuse-out")
    parser.add_argument("--input-diffuse-bmp")
    parser.add_argument("--manifest-out")
    parser.add_argument("--height-bmp")
    parser.add_argument("--out")
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--amount", type=float, default=1.0)
    parser.add_argument("--shade", choices=("smooth", "flat"), default="smooth")
    parser.add_argument("--mode", choices=("displace", "map-remesh"), default="displace")
    parser.add_argument("--remesh-step", type=float, default=16.0)
    parser.add_argument("--remesh-levels", type=int)
    args = parser.parse_args()

    text = Path(args.input).read_text()
    header, vertices, faces, authored_face_roles = parse_obj_with_uv_islands(text, args.target)
    layout_strategy = parse_uv_hint_strategy(text, args.target)
    source_layout = build_uv_layout(vertices, faces, authored_face_roles, layout_strategy)
    if args.atlas_out:
        atlas, _ = atlas_image(vertices, faces, source_layout)
        write_ppm(Path(args.atlas_out), atlas)
    if args.debug_source_uv_out:
        polygon_vertices, polygons, polygon_roles = parse_obj_polygons_with_uv_islands(text, args.target)
        polygon_layout = build_uv_layout(polygon_vertices, polygons, polygon_roles, layout_strategy)
        atlas, _ = atlas_image(polygon_vertices, polygons, polygon_layout)
        write_png(
            Path(args.debug_source_uv_out),
            uv_overlay_image(polygon_vertices, polygons, atlas, polygon_layout),
        )
    if args.height_bmp and args.out:
        height_map = parse_bmp24(Path(args.height_bmp))
        if args.mode == "map-remesh":
            (
                enhanced_vertices,
                enhanced_faces,
                base_vertices,
                deltas,
                output_layout,
                output_face_island_indices,
                displacement_values,
                uv_vertices,
            ) = map_remesh(
                vertices,
                faces,
                height_map,
                args.amount,
                args.remesh_step,
                args.remesh_levels,
                authored_face_roles,
                layout_strategy,
            )
        else:
            (
                enhanced_vertices,
                enhanced_faces,
                base_vertices,
                deltas,
                output_layout,
                output_face_island_indices,
                displacement_values,
                uv_vertices,
            ) = apply_height(
                vertices, faces, height_map, args.levels, args.amount, authored_face_roles, layout_strategy
            )
        Path(args.out).write_text(
            write_obj(
                header,
                args.target,
                enhanced_vertices,
                enhanced_faces,
                args.shade,
                args.amount,
                base_vertices=base_vertices,
                deltas=deltas,
                topology="map_remesh" if args.mode == "map-remesh" else "subdivision_displace",
                layout=output_layout,
                face_island_indices=output_face_island_indices,
                diffuse_path=args.diffuse_out,
                height_path=args.processed_height_out,
                debug_image_paths=[
                    item
                    for item in [
                        ("source_uv", args.debug_source_uv_out),
                        ("final_uv", args.debug_final_uv_out),
                    ]
                    if item[1]
                ],
                uv_vertices=uv_vertices,
            )
        )
        if args.manifest_out:
            write_manifest(
                Path(args.manifest_out),
                enhanced_vertices,
                enhanced_faces,
                amount=args.amount,
                shade=args.shade,
                layout=output_layout,
            )
        _, source_mask = atlas_image(vertices, faces, output_layout)
        processed_height = preprocess_height_map(height_map, source_mask, output_layout)
        displacement_map, displacement_mask = bake_vertex_scalar_to_atlas(
            uv_vertices,
            enhanced_faces,
            output_layout,
            output_face_island_indices,
            displacement_values,
        )
        if args.debug_final_uv_out:
            write_png(
                Path(args.debug_final_uv_out),
                uv_overlay_image(
                    uv_vertices,
                    enhanced_faces,
                    height_map_rgb(displacement_map),
                    output_layout,
                    output_face_island_indices,
                ),
            )
        if args.processed_height_out:
            write_png(Path(args.processed_height_out), height_map_rgb(processed_height))
        if args.diffuse_out:
            fallback_diffuse = diffuse_texture_from_displacement(displacement_map, displacement_mask, output_layout)
            if args.input_diffuse_bmp:
                generated_diffuse = parse_bmp24_rgb(Path(args.input_diffuse_bmp))
                fallback_diffuse = reconciled_generated_diffuse(
                    generated_diffuse,
                    fallback_diffuse,
                    displacement_mask,
                    output_layout,
                )
            write_png(Path(args.diffuse_out), fallback_diffuse)
    elif args.manifest_out:
        write_manifest(Path(args.manifest_out), vertices, faces, amount=args.amount, shade=args.shade)


if __name__ == "__main__":
    main()
