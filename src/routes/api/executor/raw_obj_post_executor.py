#!/usr/bin/env python3
"""
Raw OBJ Post Executor

This executor is intentionally separate from the Live OBJ executor. It treats
raw LLM-authored OBJ vertices/faces as the base geometry, then applies a small
`#@post:` modifier stack on top.

Supported post ops:
    transform selection=group_name position=[x,y,z] rotation=[rx,ry,rz] scale=[sx,sy,sz] pivot=[x,y,z]
    symmetrize axis=x|y|z side=positive|negative
    mirror axis=x|y|z
    array count=n offset=[x,y,z] centered=true|false scale=[sx,sy,sz] position=[x,y,z] pivot=[x,y,z]
    scatter count=n width=x depth=z seed=n min_distance=v jitter=v rotation=[rx,ry,rz] scale=[sx,sy,sz] position=[x,y,z] pivot=[x,y,z]
    surface_snap target=object normal_offset=v align_to_normal=true|false
    conform target=object strength=v normal_offset=v
    path_array path=object count=n spacing=v rotation_mode=tangent
    surface_array target=object spacing=v pattern=grid|hex
    orient mode=face target=object pivot=[x,y,z]
    clip axis=x|y|z min=v max=v
    deform selection=group_name position=[x,y,z]
    subdivide level=n
    smooth iterations=n strength=v
    simplify ratio=v
    face_lattice inset=v thickness=v weld=v guide_subdivide=n guide_smooth=n subdivide=n smooth=n mode=replace|append
    skin_edges radius=v resolution=n edges=feature|boundary|all angle=v mode=replace|append
    build_glazed_openings frame_width=v frame_depth=v panel_recess=v panel_thickness=v mode=append
    snap_to_ground axis=x|y|z
    center_origin axes=xz|xy|yz|xyz
    material name=mat_id
    tag value=...

Material and tag ops are metadata-only; they remain in the output for the UI.
"""

from __future__ import annotations

import argparse
import ast
import math
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


Vec3 = Tuple[float, float, float]
Face = List[int]


@dataclass
class Mesh:
    vertices: List[Vec3] = field(default_factory=list)
    faces: List[Face] = field(default_factory=list)
    groups: List[List[int]] = field(default_factory=list)
    named_groups: Dict[str, List[int]] = field(default_factory=dict)

    def copy(self) -> "Mesh":
        return Mesh(
            vertices=list(self.vertices),
            faces=[list(f) for f in self.faces],
            groups=[list(group) for group in self.groups],
            named_groups={name: list(group) for name, group in self.named_groups.items()},
        )

    def extend(self, other: "Mesh") -> None:
        offset = len(self.vertices)
        self.vertices.extend(other.vertices)
        self.faces.extend([[i + offset for i in f] for f in other.faces])
        self.groups.extend([[i + offset for i in group] for group in other.groups])
        for name, group in other.named_groups.items():
            self.named_groups.setdefault(name, []).extend([i + offset for i in group])


@dataclass
class RawObject:
    name: str
    declaration: str = "o"
    meta_lines: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    post_ops: List[Dict[str, Any]] = field(default_factory=list)
    mesh: Mesh = field(default_factory=Mesh)
    raw_nonlive_lines: List[str] = field(default_factory=list)


@dataclass
class Scene:
    header_lines: List[str] = field(default_factory=list)
    objects: List[RawObject] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)


AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
EXPR_FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
}
EXPR_CONSTANTS = {"pi": math.pi, "tau": math.tau}
TEMPLATE_PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}|(?<!\[)\{[A-Za-z_][A-Za-z0-9_]*\}")
SUPPORTED_POST_ATTRIBUTES = {
    "transform": {"selection", "group", "position", "translate", "rotation", "scale", "pivot"},
    "symmetrize": {"axis", "side", "tolerance"},
    "mirror": {"axis"},
    "array": {"count", "offset", "centered", "center", "scale", "position", "pivot"},
    "scatter": {
        "count",
        "width",
        "depth",
        "area",
        "size",
        "axes",
        "plane",
        "target",
        "surface",
        "on",
        "center",
        "seed",
        "min_distance",
        "spacing",
        "jitter",
        "attempts",
        "mode",
        "align_to_normal",
        "normal_offset",
        "surface_offset",
        "height_offset",
        "scale",
        "scale_min",
        "scale_max",
        "min_scale",
        "max_scale",
        "uniform_scale",
        "position",
        "rotation",
        "rotation_x",
        "rotation_y",
        "rotation_z",
        "pivot",
        "height_min",
        "height_max",
        "slope_min",
        "slope_max",
        "avoid",
        "clearance",
        "cluster_count",
        "clusters",
        "cluster_radius",
    },
    "surface_snap": {
        "target",
        "surface",
        "on",
        "axes",
        "plane",
        "pivot",
        "normal_offset",
        "surface_offset",
        "height_offset",
        "align_to_normal",
        "mode",
    },
    "conform": {
        "target",
        "surface",
        "on",
        "axes",
        "plane",
        "strength",
        "normal_offset",
        "surface_offset",
        "height_offset",
    },
    "path_array": {
        "path",
        "target",
        "curve",
        "count",
        "spacing",
        "closed",
        "rotation_mode",
        "rotation",
        "rotation_x",
        "rotation_y",
        "rotation_z",
        "scale",
        "scale_min",
        "scale_max",
        "min_scale",
        "max_scale",
        "uniform_scale",
        "position",
        "pivot",
        "seed",
    },
    "surface_array": {
        "target",
        "surface",
        "on",
        "count",
        "spacing",
        "pattern",
        "axes",
        "plane",
        "normal_offset",
        "surface_offset",
        "height_offset",
        "align_to_normal",
        "rotation",
        "rotation_x",
        "rotation_y",
        "rotation_z",
        "scale",
        "scale_min",
        "scale_max",
        "min_scale",
        "max_scale",
        "uniform_scale",
        "position",
        "pivot",
        "seed",
    },
    "orient": {
        "mode",
        "target",
        "point",
        "pivot",
        "axis",
        "up",
        "rotation",
    },
    "clip": {
        "axis",
        "min",
        "max",
        "below",
        "above",
        "center",
        "size",
        "invert",
    },
    "deform": {"selection", "group", "position", "expr", "xyz"},
    "subdivide": {"level"},
    "smooth": {"iterations", "strength"},
    "simplify": {"ratio"},
    "face_lattice": {
        "inset",
        "thickness",
        "weld",
        "guide_subdivide",
        "guide_smooth",
        "subdivide",
        "smooth",
        "smooth_strength",
        "mode",
    },
    "skin_edges": {"radius", "resolution", "edges", "angle", "mode", "padding"},
    "build_glazed_openings": {
        "ids",
        "role",
        "type",
        "frame_width",
        "frame_depth",
        "panel_inset",
        "panel_recess",
        "panel_thickness",
        "mode",
    },
    "snap_to_ground": {"axis"},
    "center_origin": {"axes"},
    "material": {"name"},
    "tag": {"value"},
}


def warn(message: str) -> None:
    print(f"raw-post warning: {message}", file=sys.stderr)


def has_template_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return TEMPLATE_PLACEHOLDER_RE.search(value) is not None
    if isinstance(value, (list, tuple)):
        return any(has_template_placeholder(item) for item in value)
    return False


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except Exception:
            return value
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if any(c in value for c in ".eE"):
            return float(value)
        return int(value)
    except ValueError:
        return value


def split_top_level(s: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    quote: Optional[str] = None
    escape = False
    for ch in s:
        if quote is not None:
            cur.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"'}:
            quote = ch
            cur.append(ch)
            continue
        if ch in "[({":
            depth += 1
        elif ch in "])}":
            depth = max(0, depth - 1)
        if ch.isspace() and depth == 0:
            if cur:
                out.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def split_top_level_commas(s: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    quote: Optional[str] = None
    escape = False
    for ch in s:
        if quote is not None:
            cur.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"'}:
            quote = ch
            cur.append(ch)
            continue
        if ch in "[({":
            depth += 1
        elif ch in "])}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            if cur:
                out.append("".join(cur).strip())
                cur = []
            continue
        cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    return [p for p in out if p]


def parse_key_values(body: str) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for piece in split_top_level_commas(body):
        if "=" not in piece:
            continue
        key, raw_value = piece.split("=", 1)
        key = key.strip()
        if key:
            parsed[key] = parse_scalar(raw_value)
    return parsed


def parse_tokens(body: str) -> Dict[str, Any]:
    tokens = split_top_level(body.strip())
    if not tokens:
        return {}
    parsed: Dict[str, Any] = {"cmd": tokens[0].strip()}
    args: List[Any] = []
    for token in tokens[1:]:
        if "=" in token:
            key, raw_value = token.split("=", 1)
            parsed[key.strip()] = parse_scalar(raw_value)
        else:
            args.append(parse_scalar(token))
    if args:
        parsed["args"] = args
    return parsed


def parse_params(meta_lines: List[str]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    block: Optional[str] = None
    for raw_line in meta_lines:
        line = raw_line.strip()
        if not line.startswith("#@"):
            continue
        body = line[2:].strip()
        if body == "params:":
            block = "params"
            continue
        if body.startswith("params:"):
            params.update(parse_key_values(body[len("params:") :].strip()))
            block = "params"
            continue
        if body.endswith(":") and not body.startswith("-"):
            block = None
            continue
        if block == "params" and body.startswith("-"):
            params.update(parse_key_values(body[1:].strip()))
            continue
        if ":" in body and not body.startswith("-"):
            block = None
    return params


def parse_post_ops(meta_lines: List[str]) -> List[Dict[str, Any]]:
    post_ops: List[Dict[str, Any]] = []
    block: Optional[str] = None
    for raw_line in meta_lines:
        line = raw_line.strip()
        if not line.startswith("#@"):
            continue
        body = line[2:].strip()
        if body == "post:":
            block = "post"
            continue
        if body.lower().startswith("post:"):
            warn("malformed #@post block syntax; use #@post: followed by #@ - op lines")
            block = None
            continue
        if body.startswith("post "):
            parsed = parse_tokens(body[len("post ") :].strip())
            if parsed:
                post_ops.append(parsed)
            block = None
            continue
        if body.endswith(":") and not body.startswith("-"):
            block = None
            continue
        if block == "post" and body.startswith("-"):
            parsed = parse_tokens(body[1:].strip())
            if parsed:
                post_ops.append(parsed)
            continue
        if ":" in body and not body.startswith("-"):
            block = None
    return post_ops


def parse_obj(path: Path) -> Scene:
    scene = Scene()
    current: Optional[RawObject] = None
    global_vertex_index_to_local: Dict[int, Tuple[RawObject, int]] = {}
    global_vertex_count = 0
    current_group_names: List[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("o "):
            declaration, name = stripped.split(maxsplit=1)
            current = RawObject(name=name.strip(), declaration=declaration)
            scene.objects.append(current)
            current_group_names = []
            continue
        if current is None:
            scene.header_lines.append(line)
            continue
        if stripped.startswith("g "):
            current_group_names = [
                part.strip()
                for part in stripped.split()[1:]
                if part.strip()
            ]
            continue
        if stripped.startswith("#@"):
            current.meta_lines.append(line)
            continue
        if stripped.startswith("v "):
            parts = stripped.split()
            if len(parts) >= 4:
                x, y, z = map(float, parts[1:4])
                current.mesh.vertices.append((x, y, z))
                global_vertex_count += 1
                global_vertex_index_to_local[global_vertex_count] = (
                    current,
                    len(current.mesh.vertices),
                )
            continue
        if stripped.startswith("f "):
            face: Face = []
            for token in stripped.split()[1:]:
                raw_index = token.split("/")[0]
                if not raw_index:
                    continue
                idx = int(raw_index)
                if idx < 0:
                    idx = global_vertex_count + idx + 1
                obj_ref, local_idx = global_vertex_index_to_local.get(idx, (current, idx))
                if obj_ref is current:
                    face.append(local_idx)
            if len(face) >= 3:
                current.mesh.faces.append(face)
                for group_name in current_group_names:
                    group = current.mesh.named_groups.setdefault(group_name, [])
                    group.extend(face)
            continue
        current.raw_nonlive_lines.append(line)

    scene.params = parse_params(scene.header_lines)
    for obj in scene.objects:
        obj.params = {**scene.params, **parse_params(obj.meta_lines)}
        obj.post_ops = parse_post_ops(obj.meta_lines)
    return scene


def axis_index(axis: Any, default: str = "y") -> int:
    key = str(axis or default).strip().lower()
    return AXIS_INDEX.get(key, AXIS_INDEX[default])


def mesh_bbox(mesh: Mesh) -> Tuple[Vec3, Vec3]:
    if not mesh.vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*mesh.vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def vec_scale(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def coerce_vec3(value: Any) -> Optional[Vec3]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def coerce_vec3_loop(value: Any) -> List[Vec3]:
    if not isinstance(value, (list, tuple)):
        return []
    loop: List[Vec3] = []
    for item in value:
        vec = coerce_vec3(item)
        if vec is not None:
            loop.append(vec)
    return loop


def face_normal_from_points(points: List[Vec3]) -> Vec3:
    if len(points) < 3:
        return (0.0, 0.0, 1.0)
    normal = (0.0, 0.0, 0.0)
    for i, point in enumerate(points):
        nxt = points[(i + 1) % len(points)]
        normal = vec_add(
            normal,
            (
                (point[1] - nxt[1]) * (point[2] + nxt[2]),
                (point[2] - nxt[2]) * (point[0] + nxt[0]),
                (point[0] - nxt[0]) * (point[1] + nxt[1]),
            ),
        )
    return vec_normalize(normal)


def plane_basis(normal: Vec3) -> Tuple[Vec3, Vec3]:
    n = vec_normalize(normal)
    helper = (0.0, 1.0, 0.0) if abs(n[1]) < 0.9 else (1.0, 0.0, 0.0)
    u = vec_normalize(vec_cross(helper, n), (1.0, 0.0, 0.0))
    v = vec_normalize(vec_cross(n, u), (0.0, 1.0, 0.0))
    return u, v


def signed_polygon_area_2d(points: List[Tuple[float, float]]) -> float:
    area = 0.0
    for i, point in enumerate(points):
        nxt = points[(i + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    return area * 0.5


def line_intersection_2d(
    point_a: Tuple[float, float],
    dir_a: Tuple[float, float],
    point_b: Tuple[float, float],
    dir_b: Tuple[float, float],
) -> Optional[Tuple[float, float]]:
    det = dir_a[0] * dir_b[1] - dir_a[1] * dir_b[0]
    if abs(det) <= 1e-9:
        return None
    dx = point_b[0] - point_a[0]
    dy = point_b[1] - point_a[1]
    t = (dx * dir_b[1] - dy * dir_b[0]) / det
    return (point_a[0] + dir_a[0] * t, point_a[1] + dir_a[1] * t)


def inset_planar_loop(loop: List[Vec3], normal: Vec3, amount: float) -> List[Vec3]:
    if len(loop) < 3 or amount <= 1e-9:
        return list(loop)
    origin = loop[0]
    u, v = plane_basis(normal)
    pts2 = [(vec_dot(vec_sub(point, origin), u), vec_dot(vec_sub(point, origin), v)) for point in loop]
    area = signed_polygon_area_2d(pts2)
    if abs(area) <= 1e-9:
        centroid = (
            sum(point[0] for point in loop) / len(loop),
            sum(point[1] for point in loop) / len(loop),
            sum(point[2] for point in loop) / len(loop),
        )
        return [vec_add(point, vec_scale(vec_normalize(vec_sub(centroid, point)), amount)) for point in loop]

    orientation = 1.0 if area > 0 else -1.0
    offset_lines: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for i, point in enumerate(pts2):
        nxt = pts2[(i + 1) % len(pts2)]
        edge = (nxt[0] - point[0], nxt[1] - point[1])
        edge_len = math.sqrt(edge[0] * edge[0] + edge[1] * edge[1])
        if edge_len <= 1e-9:
            offset_lines.append((point, (1.0, 0.0)))
            continue
        direction = (edge[0] / edge_len, edge[1] / edge_len)
        inward = (-orientation * direction[1], orientation * direction[0])
        offset_point = (point[0] + inward[0] * amount, point[1] + inward[1] * amount)
        offset_lines.append((offset_point, direction))

    inset2: List[Tuple[float, float]] = []
    for i in range(len(pts2)):
        prev_line = offset_lines[(i - 1) % len(offset_lines)]
        next_line = offset_lines[i]
        hit = line_intersection_2d(prev_line[0], prev_line[1], next_line[0], next_line[1])
        if hit is None:
            point = pts2[i]
            centroid2 = (
                sum(p[0] for p in pts2) / len(pts2),
                sum(p[1] for p in pts2) / len(pts2),
            )
            inward = (centroid2[0] - point[0], centroid2[1] - point[1])
            length = math.sqrt(inward[0] * inward[0] + inward[1] * inward[1]) or 1.0
            hit = (point[0] + inward[0] / length * amount, point[1] + inward[1] / length * amount)
        inset2.append(hit)

    return [
        vec_add(origin, vec_add(vec_scale(u, point[0]), vec_scale(v, point[1])))
        for point in inset2
    ]


def face_centroid(mesh: Mesh, face: Face) -> Vec3:
    pts = [mesh.vertices[i - 1] for i in face if 1 <= i <= len(mesh.vertices)]
    if not pts:
        return (0.0, 0.0, 0.0)
    return (
        sum(p[0] for p in pts) / len(pts),
        sum(p[1] for p in pts) / len(pts),
        sum(p[2] for p in pts) / len(pts),
    )


def mirror_mesh(mesh: Mesh, axis: Any) -> Mesh:
    ax = axis_index(axis, "x")
    vertices: List[Vec3] = []
    for vertex in mesh.vertices:
        values = list(vertex)
        values[ax] = -values[ax]
        vertices.append((values[0], values[1], values[2]))
    return Mesh(vertices, [list(reversed(face)) for face in mesh.faces])


def op_mirror(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    out = mesh.copy()
    out.extend(mirror_mesh(mesh, op.get("axis", "x")))
    return out


def compact_mesh(mesh: Mesh, faces: List[Face]) -> Mesh:
    used: Dict[int, int] = {}
    vertices: List[Vec3] = []
    remapped_faces: List[Face] = []
    for face in faces:
        remapped: Face = []
        for idx in face:
            if idx < 1 or idx > len(mesh.vertices):
                continue
            if idx not in used:
                used[idx] = len(vertices) + 1
                vertices.append(mesh.vertices[idx - 1])
            remapped.append(used[idx])
        if len(remapped) >= 3:
            remapped_faces.append(remapped)
    return Mesh(vertices, remapped_faces)


def op_symmetrize(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    ax = axis_index(op.get("axis", "x"), "x")
    side = str(op.get("side", "positive")).strip().lower()
    sign = -1.0 if side in {"negative", "minus", "-"} else 1.0
    tol = float(op.get("tolerance", 1e-6))
    selected_faces = [
        face
        for face in mesh.faces
        if sign * face_centroid(mesh, face)[ax] >= -tol
    ]
    if not selected_faces:
        warn("symmetrize found no faces on requested side; falling back to mirror")
        return op_mirror(mesh, {"axis": op.get("axis", "x")})
    half = compact_mesh(mesh, selected_faces)
    mirrored = mirror_mesh(half, op.get("axis", "x"))
    half.extend(mirrored)
    return half


def op_array(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    count = max(1, int(round(eval_numeric_expr(op.get("count", 1), params))))
    offset = parse_vec3(op.get("offset", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    centered = parse_bool(op.get("centered", op.get("center")), False)
    origin_shift = -0.5 * (count - 1) if centered and count > 1 else 0.0
    out = Mesh()
    for n in range(count):
        step = n + origin_shift
        scope = {
            "i": float(n),
            "index": float(n),
            "step": float(step),
            "count": float(count),
            "t": float(n / max(1, count - 1)),
        }
        scale = parse_vec3(op.get("scale", [1, 1, 1]), params, (1.0, 1.0, 1.0), scope)
        position = parse_vec3(op.get("position", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope)
        pivot = parse_vec3(op.get("pivot", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope)
        source_groups = mesh.groups or [list(range(1, len(mesh.vertices) + 1))]
        copy = Mesh(
            [
                (
                    pivot[0] + (v[0] - pivot[0]) * scale[0] + offset[0] * step + position[0],
                    pivot[1] + (v[1] - pivot[1]) * scale[1] + offset[1] * step + position[1],
                    pivot[2] + (v[2] - pivot[2]) * scale[2] + offset[2] * step + position[2],
                )
                for v in mesh.vertices
            ],
            [list(face) for face in mesh.faces],
            [list(group) for group in source_groups],
            {name: list(group) for name, group in mesh.named_groups.items()},
        )
        out.extend(copy)
    return out


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "center", "centered"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def unique_indices(indices: List[int]) -> List[int]:
    seen = set()
    out: List[int] = []
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        out.append(idx)
    return out


def selected_vertex_indices(mesh: Mesh, op: Dict[str, Any]) -> Optional[set[int]]:
    raw = op.get("selection", op.get("group", op.get("part")))
    if raw is None:
        return None
    names: List[str] = []
    if isinstance(raw, (list, tuple)):
        names = [str(item).strip() for item in raw if str(item).strip()]
    else:
        names = [
            part.strip()
            for part in re.split(r"[|,]", str(raw))
            if part.strip()
        ]
    if not names or any(name.lower() in {"*", "all"} for name in names):
        return None

    selected: set[int] = set()
    missing: List[str] = []
    for name in names:
        group = mesh.named_groups.get(name)
        if group is None:
            missing.append(name)
            continue
        selected.update(idx for idx in group if 1 <= idx <= len(mesh.vertices))
    if missing:
        warn(f"selection group not found: {', '.join(missing)}")
    return selected


def selected_bbox(mesh: Mesh, selected: Optional[set[int]]) -> Tuple[Vec3, Vec3]:
    if selected is None:
        return mesh_bbox(mesh)
    points = [
        mesh.vertices[idx - 1]
        for idx in selected
        if 1 <= idx <= len(mesh.vertices)
    ]
    if not points:
        return mesh_bbox(mesh)
    xs, ys, zs = zip(*points)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def eval_numeric_expr(value: Any, params: Dict[str, Any], scope: Optional[Dict[str, Any]] = None) -> float:
    scope = scope or {}
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        if has_template_placeholder(text):
            raise ValueError(
                f"template placeholder syntax is not supported in '{text}'; use bare parameter names"
            )
        try:
            return float(text)
        except ValueError:
            pass
        if text in scope:
            return eval_numeric_expr(scope[text], params, scope)
        if text in params:
            return eval_numeric_expr(params[text], params, scope)
        if text in EXPR_CONSTANTS:
            return EXPR_CONSTANTS[text]
        node = ast.parse(text, mode="eval")

        def visit(n: ast.AST) -> float:
            if isinstance(n, ast.Expression):
                return visit(n.body)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
                return float(n.value)
            if isinstance(n, ast.Name):
                if n.id in scope:
                    return eval_numeric_expr(scope[n.id], params, scope)
                if n.id in params:
                    return eval_numeric_expr(params[n.id], params, scope)
                if n.id in EXPR_CONSTANTS:
                    return EXPR_CONSTANTS[n.id]
                if n.id in EXPR_FUNCTIONS:
                    raise ValueError(f"function '{n.id}' must be called")
                else:
                    raise ValueError(f"unknown parameter '{n.id}'")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                if n.func.id not in EXPR_FUNCTIONS:
                    raise ValueError(f"unsupported function '{n.func.id}'")
                args = [visit(arg) for arg in n.args]
                return float(EXPR_FUNCTIONS[n.func.id](*args))
            if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
                val = visit(n.operand)
                return val if isinstance(n.op, ast.UAdd) else -val
            if isinstance(n, ast.BinOp) and isinstance(
                n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
            ):
                left = visit(n.left)
                right = visit(n.right)
                if isinstance(n.op, ast.Add):
                    return left + right
                if isinstance(n.op, ast.Sub):
                    return left - right
                if isinstance(n.op, ast.Mult):
                    return left * right
                if isinstance(n.op, ast.Div):
                    return left / right
                if isinstance(n.op, ast.Pow):
                    return left**right
            raise ValueError(f"unsupported expression '{text}'")

        return visit(node)
    raise ValueError(f"expected numeric value, got {value!r}")


def parse_vec3(
    value: Any,
    params: Dict[str, Any],
    default: Vec3,
    scope: Optional[Dict[str, Any]] = None,
) -> Vec3:
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if text in params:
            raw = params[text]
        elif text.startswith("[") and text.endswith("]"):
            raw = split_top_level_commas(text[1:-1])
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return default
    try:
        return (
            eval_numeric_expr(raw[0], params, scope),
            eval_numeric_expr(raw[1], params, scope),
            eval_numeric_expr(raw[2], params, scope),
        )
    except Exception as e:
        warn(f"invalid vector expression {value!r}: {e}; using default {default}")
        return default


def parse_pair(
    value: Any,
    params: Dict[str, Any],
    default: Tuple[float, float],
    scope: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float]:
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if text in params:
            raw = params[text]
        elif text.startswith("[") and text.endswith("]"):
            raw = split_top_level_commas(text[1:-1])
    if isinstance(raw, (int, float, str)) and not isinstance(raw, bool):
        try:
            value = eval_numeric_expr(raw, params, scope)
            return (value, value)
        except Exception:
            return default
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return default
    try:
        return (
            eval_numeric_expr(raw[0], params, scope),
            eval_numeric_expr(raw[1], params, scope),
        )
    except Exception as e:
        warn(f"invalid pair expression {value!r}: {e}; using default {default}")
        return default


def scatter_plane_axes(op: Dict[str, Any]) -> Tuple[int, int, int]:
    plane = str(op.get("axes", op.get("plane", "xz"))).strip().lower()
    axes: List[int] = []
    for ch in plane:
        idx = AXIS_INDEX.get(ch)
        if idx is not None and idx not in axes:
            axes.append(idx)
    if len(axes) < 2:
        axes = [AXIS_INDEX["x"], AXIS_INDEX["z"]]
    scatter_axes = (axes[0], axes[1])
    vertical_candidates = [idx for idx in range(3) if idx not in scatter_axes]
    return scatter_axes[0], scatter_axes[1], vertical_candidates[0]


def scatter_numeric(value: Any, params: Dict[str, Any], scope: Dict[str, Any]) -> float:
    if isinstance(value, str) and value.strip().lower() in {"random", "rand"}:
        return float(scope.get("rand", 0.0)) * 360.0
    return eval_numeric_expr(value, params, scope)


def scatter_rotation(
    op: Dict[str, Any],
    params: Dict[str, Any],
    scope: Dict[str, Any],
    vertical_axis: int,
) -> Vec3:
    raw = op.get("rotation", [0, 0, 0])
    if isinstance(raw, str) and raw.strip().lower() in {"random", "rand"}:
        values = [0.0, 0.0, 0.0]
        values[vertical_axis] = float(scope.get("rand", 0.0)) * 360.0
        return (values[0], values[1], values[2])
    values = list(parse_vec3(raw, params, (0.0, 0.0, 0.0), scope))
    for axis_name, axis_idx in AXIS_INDEX.items():
        key = f"rotation_{axis_name}"
        if key in op:
            try:
                values[axis_idx] = scatter_numeric(op[key], params, scope)
            except Exception as e:
                warn(f"invalid scatter {key}={op[key]!r}: {e}; using {values[axis_idx]}")
    return (values[0], values[1], values[2])


def scatter_scale(op: Dict[str, Any], params: Dict[str, Any], scope: Dict[str, Any]) -> Vec3:
    raw = op.get("uniform_scale", op.get("scale"))
    if raw is not None:
        if isinstance(raw, str):
            text = raw.strip()
            if text in params:
                raw = params[text]
            elif text.startswith("[") and text.endswith("]"):
                raw = split_top_level_commas(text[1:-1])
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            try:
                lo = eval_numeric_expr(raw[0], params, scope)
                hi = eval_numeric_expr(raw[1], params, scope)
                if hi < lo:
                    lo, hi = hi, lo
                value = lo + (hi - lo) * float(scope.get("rand_scale", scope.get("rand", 0.0)))
                return (value, value, value)
            except Exception as e:
                warn(f"invalid scatter scale range {raw!r}: {e}; using [1,1,1]")
                return (1.0, 1.0, 1.0)
        return parse_vec3(raw, params, (1.0, 1.0, 1.0), scope)

    lo = op.get("scale_min", op.get("min_scale"))
    hi = op.get("scale_max", op.get("max_scale"))
    if lo is not None or hi is not None:
        try:
            min_scale = eval_numeric_expr(lo if lo is not None else 1.0, params, scope)
            max_scale = eval_numeric_expr(hi if hi is not None else min_scale, params, scope)
            if max_scale < min_scale:
                min_scale, max_scale = max_scale, min_scale
            value = min_scale + (max_scale - min_scale) * float(scope.get("rand_scale", scope.get("rand", 0.0)))
            return (value, value, value)
        except Exception as e:
            warn(f"invalid scatter scale_min/scale_max: {e}; using [1,1,1]")
    return (1.0, 1.0, 1.0)


def scatter_target_name(op: Dict[str, Any]) -> str:
    return str(op.get("target", op.get("surface", op.get("on", "")))).strip()


def surface_target_name(op: Dict[str, Any]) -> str:
    return str(op.get("target", op.get("surface", op.get("on", "")))).strip()


def path_target_name(op: Dict[str, Any]) -> str:
    return str(op.get("path", op.get("target", op.get("curve", "")))).strip()


def named_object(
    name: str,
    scene_objects: Optional[Dict[str, RawObject]],
    op_name: str,
) -> Optional[RawObject]:
    if not name or not scene_objects:
        warn(f"{op_name} skipped missing target object name")
        return None
    target = scene_objects.get(name)
    if target is None:
        warn(f"{op_name} target '{name}' not found")
        return None
    return target


def parse_name_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[, ]+", str(value)) if part.strip()]


def surface_triangles(mesh: Mesh) -> List[Tuple[Vec3, Vec3, Vec3, Vec3, float]]:
    triangles: List[Tuple[Vec3, Vec3, Vec3, Vec3, float]] = []
    for face in mesh.faces:
        clean = [idx for idx in face if 1 <= idx <= len(mesh.vertices)]
        if len(clean) < 3:
            continue
        anchor = mesh.vertices[clean[0] - 1]
        for i in range(1, len(clean) - 1):
            b = mesh.vertices[clean[i] - 1]
            c = mesh.vertices[clean[i + 1] - 1]
            cross = vec_cross(vec_sub(b, anchor), vec_sub(c, anchor))
            area = vec_length(cross) * 0.5
            if area <= 1e-10:
                continue
            triangles.append((anchor, b, c, vec_normalize(cross, (0.0, 1.0, 0.0)), area))
    return triangles


def sample_surface_point(
    triangles: List[Tuple[Vec3, Vec3, Vec3, Vec3, float]],
    rng: random.Random,
) -> Tuple[Vec3, Vec3]:
    total_area = sum(item[4] for item in triangles)
    pick = rng.random() * total_area
    running = 0.0
    selected = triangles[-1]
    for triangle in triangles:
        running += triangle[4]
        if pick <= running:
            selected = triangle
            break
    a, b, c, normal, _area = selected
    r1 = rng.random()
    r2 = rng.random()
    sqrt_r1 = math.sqrt(r1)
    wa = 1.0 - sqrt_r1
    wb = sqrt_r1 * (1.0 - r2)
    wc = sqrt_r1 * r2
    point = (
        a[0] * wa + b[0] * wb + c[0] * wc,
        a[1] * wa + b[1] * wb + c[1] * wc,
        a[2] * wa + b[2] * wb + c[2] * wc,
    )
    return point, normal


def barycentric_2d(
    point: Tuple[float, float],
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
) -> Optional[Tuple[float, float, float]]:
    denom = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(denom) <= 1e-10:
        return None
    w1 = ((b[1] - c[1]) * (point[0] - c[0]) + (c[0] - b[0]) * (point[1] - c[1])) / denom
    w2 = ((c[1] - a[1]) * (point[0] - c[0]) + (a[0] - c[0]) * (point[1] - c[1])) / denom
    w3 = 1.0 - w1 - w2
    tolerance = -1e-6
    if w1 < tolerance or w2 < tolerance or w3 < tolerance:
        return None
    return (w1, w2, w3)


def project_to_surface(
    triangles: List[Tuple[Vec3, Vec3, Vec3, Vec3, float]],
    point: Vec3,
    axis_a: int,
    axis_b: int,
    vertical_axis: int,
) -> Optional[Tuple[Vec3, Vec3]]:
    point2 = (point[axis_a], point[axis_b])
    best: Optional[Tuple[Vec3, Vec3, float]] = None
    for a, b, c, normal, _area in triangles:
        weights = barycentric_2d(
            point2,
            (a[axis_a], a[axis_b]),
            (b[axis_a], b[axis_b]),
            (c[axis_a], c[axis_b]),
        )
        if weights is None:
            continue
        w1, w2, w3 = weights
        projected = [point[0], point[1], point[2]]
        projected[vertical_axis] = a[vertical_axis] * w1 + b[vertical_axis] * w2 + c[vertical_axis] * w3
        distance = abs(projected[vertical_axis] - point[vertical_axis])
        if best is None or distance < best[2]:
            best = ((projected[0], projected[1], projected[2]), normal, distance)
    if best is None:
        return None
    return best[0], best[1]


def mesh_center(mesh: Mesh) -> Vec3:
    min_corner, max_corner = mesh_bbox(mesh)
    return (
        (min_corner[0] + max_corner[0]) * 0.5,
        (min_corner[1] + max_corner[1]) * 0.5,
        (min_corner[2] + max_corner[2]) * 0.5,
    )


def mesh_bottom_center(mesh: Mesh, vertical_axis: int) -> Vec3:
    min_corner, max_corner = mesh_bbox(mesh)
    values = [
        (min_corner[0] + max_corner[0]) * 0.5,
        (min_corner[1] + max_corner[1]) * 0.5,
        (min_corner[2] + max_corner[2]) * 0.5,
    ]
    values[vertical_axis] = min_corner[vertical_axis]
    return (values[0], values[1], values[2])


def bbox_contains_point(mesh: Mesh, point: Vec3, clearance: float = 0.0) -> bool:
    min_corner, max_corner = mesh_bbox(mesh)
    return all(min_corner[i] - clearance <= point[i] <= max_corner[i] + clearance for i in range(3))


def mesh_polyline(mesh: Mesh, closed: bool = False) -> List[Vec3]:
    points = list(mesh.vertices)
    if closed and len(points) > 1 and points[0] != points[-1]:
        points.append(points[0])
    return points


def polyline_length(points: List[Vec3]) -> float:
    return sum(vec_length(vec_sub(points[i + 1], points[i])) for i in range(max(0, len(points) - 1)))


def sample_polyline(points: List[Vec3], distance: float) -> Tuple[Vec3, Vec3]:
    if not points:
        return (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
    if len(points) == 1:
        return points[0], (1.0, 0.0, 0.0)
    remaining = max(0.0, distance)
    for i in range(len(points) - 1):
        start = points[i]
        end = points[i + 1]
        segment = vec_sub(end, start)
        length = vec_length(segment)
        if length <= 1e-10:
            continue
        if remaining <= length:
            t = remaining / length
            return vec_add(start, vec_mul(segment, t)), vec_normalize(segment, (1.0, 0.0, 0.0))
        remaining -= length
    tangent = vec_normalize(vec_sub(points[-1], points[-2]), (1.0, 0.0, 0.0))
    return points[-1], tangent


def rotate_vector_axis_angle(point: Vec3, axis: Vec3, angle: float) -> Vec3:
    axis = vec_normalize(axis)
    if vec_length(axis) <= 1e-12 or abs(angle) <= 1e-12:
        return point
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return vec_add(
        vec_add(vec_mul(point, cos_a), vec_mul(vec_cross(axis, point), sin_a)),
        vec_mul(axis, vec_dot(axis, point) * (1.0 - cos_a)),
    )


def align_vector_between(point: Vec3, source: Vec3, target: Vec3) -> Vec3:
    src = vec_normalize(source, (0.0, 1.0, 0.0))
    dst = vec_normalize(target, src)
    dot = max(-1.0, min(1.0, vec_dot(src, dst)))
    if dot > 0.999999:
        return point
    if dot < -0.999999:
        helper = (1.0, 0.0, 0.0) if abs(src[0]) < 0.9 else (0.0, 0.0, 1.0)
        axis = vec_normalize(vec_cross(src, helper), (0.0, 0.0, 1.0))
        return rotate_vector_axis_angle(point, axis, math.pi)
    axis = vec_normalize(vec_cross(src, dst))
    return rotate_vector_axis_angle(point, axis, math.acos(dot))


def yaw_from_direction(direction: Vec3, axis_a: int, axis_b: int, vertical_axis: int) -> Vec3:
    angle = math.degrees(math.atan2(direction[axis_b], direction[axis_a]))
    values = [0.0, 0.0, 0.0]
    values[vertical_axis] = angle
    return (values[0], values[1], values[2])


def transformed_copy(
    mesh: Mesh,
    placement: Vec3,
    rotation: Vec3,
    scale: Vec3,
    pivot: Vec3,
    offset: Vec3 = (0.0, 0.0, 0.0),
    align_from: Optional[Vec3] = None,
    align_to: Optional[Vec3] = None,
) -> Mesh:
    vertices: List[Vec3] = []
    for vertex in mesh.vertices:
        local = (
            (vertex[0] - pivot[0]) * scale[0],
            (vertex[1] - pivot[1]) * scale[1],
            (vertex[2] - pivot[2]) * scale[2],
        )
        rotated = rotate_point(local, rotation)
        if align_from is not None and align_to is not None:
            rotated = align_vector_between(rotated, align_from, align_to)
        vertices.append(
            (
                rotated[0] + pivot[0] + placement[0] + offset[0],
                rotated[1] + pivot[1] + placement[1] + offset[1],
                rotated[2] + pivot[2] + placement[2] + offset[2],
            )
        )
    return Mesh(
        vertices,
        [list(face) for face in mesh.faces],
        [list(group) for group in mesh.groups],
        {name: list(group) for name, group in mesh.named_groups.items()},
    )


def rotate_point(vertex: Vec3, rotation_degrees: Vec3) -> Vec3:
    x, y, z = vertex
    rx, ry, rz = [math.radians(a) for a in rotation_degrees]
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return (x, y, z)


def op_transform(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    position = parse_vec3(op.get("position", op.get("translate", [0, 0, 0])), params, (0.0, 0.0, 0.0))
    rotation = parse_vec3(op.get("rotation", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    scale = parse_vec3(op.get("scale", [1, 1, 1]), params, (1.0, 1.0, 1.0))
    pivot = parse_vec3(op.get("pivot", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    selected = selected_vertex_indices(mesh, op)
    vertices: List[Vec3] = []
    for idx, (x, y, z) in enumerate(mesh.vertices, start=1):
        if selected is not None and idx not in selected:
            vertices.append((x, y, z))
            continue
        x -= pivot[0]
        y -= pivot[1]
        z -= pivot[2]
        x, y, z = rotate_point((x * scale[0], y * scale[1], z * scale[2]), rotation)
        vertices.append((x + position[0], y + position[1], z + position[2]))
        vertices[-1] = (
            vertices[-1][0] + pivot[0],
            vertices[-1][1] + pivot[1],
            vertices[-1][2] + pivot[2],
        )
    return Mesh(
        vertices,
        [list(face) for face in mesh.faces],
        [list(group) for group in mesh.groups],
        {name: list(group) for name, group in mesh.named_groups.items()},
    )


def op_surface_snap(
    mesh: Mesh,
    op: Dict[str, Any],
    params: Dict[str, Any],
    scene_objects: Optional[Dict[str, RawObject]],
) -> Mesh:
    axis_a, axis_b, vertical_axis = scatter_plane_axes(op)
    target = named_object(surface_target_name(op), scene_objects, "surface_snap")
    if target is None:
        return mesh
    triangles = surface_triangles(target.mesh)
    if not triangles:
        warn("surface_snap target has no usable faces")
        return mesh
    offset = eval_numeric_expr(op.get("normal_offset", op.get("surface_offset", op.get("height_offset", 0.0))), params)
    align_to_normal = parse_bool(op.get("align_to_normal"), False)
    mode = str(op.get("mode", "instances" if mesh.groups else "object")).strip().lower()
    snap_groups = mesh.groups if mode in {"instances", "groups", "copies"} and mesh.groups else [list(range(1, len(mesh.vertices) + 1))]
    vertices = list(mesh.vertices)
    snapped_groups: List[List[int]] = []
    up = [0.0, 0.0, 0.0]
    up[vertical_axis] = 1.0

    for group in snap_groups:
        valid = [idx for idx in group if 1 <= idx <= len(vertices)]
        if not valid:
            continue
        group_points = [vertices[idx - 1] for idx in valid]
        min_corner = (
            min(point[0] for point in group_points),
            min(point[1] for point in group_points),
            min(point[2] for point in group_points),
        )
        max_corner = (
            max(point[0] for point in group_points),
            max(point[1] for point in group_points),
            max(point[2] for point in group_points),
        )
        pivot_default = [
            (min_corner[0] + max_corner[0]) * 0.5,
            (min_corner[1] + max_corner[1]) * 0.5,
            (min_corner[2] + max_corner[2]) * 0.5,
        ]
        pivot_default[vertical_axis] = min_corner[vertical_axis]
        pivot = parse_vec3(op.get("pivot", pivot_default), params, (pivot_default[0], pivot_default[1], pivot_default[2]))
        projected = project_to_surface(triangles, pivot, axis_a, axis_b, vertical_axis)
        if projected is None:
            continue
        point, normal = projected
        destination = vec_add(point, vec_mul(normal, offset))
        delta_values = [0.0, 0.0, 0.0]
        delta_values[vertical_axis] = destination[vertical_axis] - pivot[vertical_axis]
        delta = (delta_values[0], delta_values[1], delta_values[2])
        pivot_after = vec_add(pivot, delta)
        for idx in valid:
            moved = vec_add(vertices[idx - 1], delta)
            if align_to_normal:
                moved = vec_add(pivot_after, align_vector_between(vec_sub(moved, pivot_after), tuple(up), normal))
            vertices[idx - 1] = moved
        snapped_groups.append(list(group))

    if not snapped_groups:
        warn("surface_snap found no surface below pivot")
        return mesh
    return Mesh(
        vertices,
        [list(face) for face in mesh.faces],
        [list(group) for group in mesh.groups],
        {name: list(group) for name, group in mesh.named_groups.items()},
    )


def op_conform(
    mesh: Mesh,
    op: Dict[str, Any],
    params: Dict[str, Any],
    scene_objects: Optional[Dict[str, RawObject]],
) -> Mesh:
    axis_a, axis_b, vertical_axis = scatter_plane_axes(op)
    target = named_object(surface_target_name(op), scene_objects, "conform")
    if target is None:
        return mesh
    triangles = surface_triangles(target.mesh)
    if not triangles:
        warn("conform target has no usable faces")
        return mesh
    strength = max(0.0, min(1.0, eval_numeric_expr(op.get("strength", 1.0), params)))
    offset = eval_numeric_expr(op.get("normal_offset", op.get("surface_offset", op.get("height_offset", 0.0))), params)
    base = mesh_bottom_center(mesh, vertical_axis)
    vertices: List[Vec3] = []
    for vertex in mesh.vertices:
        projected = project_to_surface(triangles, vertex, axis_a, axis_b, vertical_axis)
        if projected is None:
            vertices.append(vertex)
            continue
        surface_point, normal = projected
        relative_height = vertex[vertical_axis] - base[vertical_axis]
        desired = list(vertex)
        desired[vertical_axis] = surface_point[vertical_axis] + relative_height
        desired_point = vec_add((desired[0], desired[1], desired[2]), vec_mul(normal, offset))
        vertices.append(vec_add(vec_mul(vertex, 1.0 - strength), vec_mul(desired_point, strength)))
    return Mesh(
        vertices,
        [list(face) for face in mesh.faces],
        [list(group) for group in mesh.groups],
        {name: list(group) for name, group in mesh.named_groups.items()},
    )


def op_path_array(
    mesh: Mesh,
    op: Dict[str, Any],
    params: Dict[str, Any],
    scene_objects: Optional[Dict[str, RawObject]],
) -> Mesh:
    axis_a, axis_b, vertical_axis = scatter_plane_axes(op)
    path = named_object(path_target_name(op), scene_objects, "path_array")
    if path is None:
        return mesh
    points = mesh_polyline(path.mesh, parse_bool(op.get("closed"), False))
    if len(points) < 2:
        warn("path_array path needs at least two vertices")
        return mesh
    total = polyline_length(points)
    spacing_value = op.get("spacing")
    if spacing_value is not None:
        spacing = max(1e-6, eval_numeric_expr(spacing_value, params))
        count = max(1, int(math.floor(total / spacing)) + 1)
    else:
        count = max(1, int(round(eval_numeric_expr(op.get("count", 2), params))))
        spacing = total / max(1, count - 1)
    seed = int(round(eval_numeric_expr(op.get("seed", 1), params)))
    rng = random.Random(seed)
    mode = str(op.get("rotation_mode", "tangent")).strip().lower()
    out = Mesh()
    for n in range(count):
        point, tangent = sample_polyline(points, spacing * n)
        rand = rng.random()
        scope = {
            "i": float(n),
            "index": float(n),
            "count": float(count),
            "t": float(n / max(1, count - 1)),
            "px": point[0],
            "py": point[1],
            "pz": point[2],
            "tx": tangent[0],
            "ty": tangent[1],
            "tz": tangent[2],
            "rand": rand,
            "random": rand,
            "rand_scale": rng.random(),
        }
        rotation = scatter_rotation(op, params, scope, vertical_axis)
        if mode in {"tangent", "path"}:
            yaw = yaw_from_direction(tangent, axis_a, axis_b, vertical_axis)
            rotation = (rotation[0] + yaw[0], rotation[1] + yaw[1], rotation[2] + yaw[2])
        out.extend(
            transformed_copy(
                mesh,
                point,
                rotation,
                scatter_scale(op, params, scope),
                parse_vec3(op.get("pivot", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope),
                parse_vec3(op.get("position", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope),
            )
        )
    return out


def op_surface_array(
    mesh: Mesh,
    op: Dict[str, Any],
    params: Dict[str, Any],
    scene_objects: Optional[Dict[str, RawObject]],
) -> Mesh:
    axis_a, axis_b, vertical_axis = scatter_plane_axes(op)
    target = named_object(surface_target_name(op), scene_objects, "surface_array")
    if target is None:
        return mesh
    triangles = surface_triangles(target.mesh)
    if not triangles:
        warn("surface_array target has no usable faces")
        return mesh
    min_corner, max_corner = mesh_bbox(target.mesh)
    spacing = max(1e-6, eval_numeric_expr(op.get("spacing", 1.0), params))
    pattern = str(op.get("pattern", "grid")).strip().lower()
    max_count = int(round(eval_numeric_expr(op.get("count", 1000000), params)))
    seed = int(round(eval_numeric_expr(op.get("seed", 1), params)))
    rng = random.Random(seed)
    up = [0.0, 0.0, 0.0]
    up[vertical_axis] = 1.0
    align_to_normal = parse_bool(op.get("align_to_normal"), False)
    offset = eval_numeric_expr(op.get("normal_offset", op.get("surface_offset", op.get("height_offset", 0.0))), params)
    out = Mesh()
    placed = 0
    row = 0
    a = min_corner[axis_a]
    while a <= max_corner[axis_a] + 1e-9 and placed < max_count:
        b_offset = spacing * 0.5 if pattern == "hex" and row % 2 else 0.0
        b = min_corner[axis_b] + b_offset
        while b <= max_corner[axis_b] + 1e-9 and placed < max_count:
            point = [0.0, 0.0, 0.0]
            point[axis_a] = a
            point[axis_b] = b
            projected = project_to_surface(triangles, (point[0], point[1], point[2]), axis_a, axis_b, vertical_axis)
            if projected is not None:
                surface_point, normal = projected
                placement = vec_add(surface_point, vec_mul(normal, offset))
                rand = rng.random()
                scope = {
                    "i": float(placed),
                    "index": float(placed),
                    "count": float(max_count),
                    "t": float(placed / max(1, max_count - 1)),
                    "px": placement[0],
                    "py": placement[1],
                    "pz": placement[2],
                    "nx": normal[0],
                    "ny": normal[1],
                    "nz": normal[2],
                    "rand": rand,
                    "random": rand,
                    "rand_scale": rng.random(),
                }
                out.extend(
                    transformed_copy(
                        mesh,
                        placement,
                        scatter_rotation(op, params, scope, vertical_axis),
                        scatter_scale(op, params, scope),
                        parse_vec3(op.get("pivot", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope),
                        parse_vec3(op.get("position", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope),
                        tuple(up) if align_to_normal else None,
                        normal if align_to_normal else None,
                    )
                )
                placed += 1
            b += spacing
        a += spacing
        row += 1
    return out if out.vertices else mesh


def op_orient(
    mesh: Mesh,
    op: Dict[str, Any],
    params: Dict[str, Any],
    scene_objects: Optional[Dict[str, RawObject]],
) -> Mesh:
    mode = str(op.get("mode", "face")).strip().lower()
    pivot = parse_vec3(op.get("pivot", mesh_center(mesh)), params, mesh_center(mesh))
    target_point = coerce_vec3(op.get("point"))
    target_name = str(op.get("target", "")).strip()
    if target_point is None and target_name and scene_objects and target_name in scene_objects:
        target_point = mesh_center(scene_objects[target_name].mesh)
    if target_point is None:
        warn("orient skipped missing point or target")
        return mesh
    axis_a, axis_b, vertical_axis = scatter_plane_axes(op)
    direction = vec_sub(target_point, pivot)
    if mode in {"away", "away_from"}:
        direction = vec_mul(direction, -1.0)
    rotation = yaw_from_direction(direction, axis_a, axis_b, vertical_axis)
    extra = parse_vec3(op.get("rotation", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    rotation = (rotation[0] + extra[0], rotation[1] + extra[1], rotation[2] + extra[2])
    return transformed_copy(mesh, (0.0, 0.0, 0.0), rotation, (1.0, 1.0, 1.0), pivot)


def op_clip(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    invert = parse_bool(op.get("invert"), False)
    min_corner, max_corner = mesh_bbox(mesh)
    bounds_min = list(min_corner)
    bounds_max = list(max_corner)
    if "center" in op or "size" in op:
        center = parse_vec3(op.get("center", mesh_center(mesh)), params, mesh_center(mesh))
        size = parse_vec3(op.get("size", [max_corner[i] - min_corner[i] for i in range(3)]), params, (1.0, 1.0, 1.0))
        bounds_min = [center[i] - abs(size[i]) * 0.5 for i in range(3)]
        bounds_max = [center[i] + abs(size[i]) * 0.5 for i in range(3)]
    axis = str(op.get("axis", "")).strip().lower()
    if axis in AXIS_INDEX:
        idx = AXIS_INDEX[axis]
        if "min" in op or "above" in op:
            bounds_min[idx] = eval_numeric_expr(op.get("min", op.get("above")), params)
        if "max" in op or "below" in op:
            bounds_max[idx] = eval_numeric_expr(op.get("max", op.get("below")), params)
    kept_faces: List[Face] = []
    for face in mesh.faces:
        centroid = face_centroid(mesh, face)
        inside = all(bounds_min[i] <= centroid[i] <= bounds_max[i] for i in range(3))
        if inside != invert:
            kept_faces.append(face)
    if not kept_faces:
        warn("clip removed every face; leaving mesh unchanged")
        return mesh
    return compact_mesh(mesh, kept_faces)


def op_scatter(
    mesh: Mesh,
    op: Dict[str, Any],
    params: Dict[str, Any],
    scene_objects: Optional[Dict[str, RawObject]] = None,
) -> Mesh:
    count = max(1, int(round(eval_numeric_expr(op.get("count", 1), params))))
    area = parse_pair(op.get("area", op.get("size", [1, 1])), params, (1.0, 1.0))
    width = max(0.0, eval_numeric_expr(op.get("width", area[0]), params))
    depth = max(0.0, eval_numeric_expr(op.get("depth", area[1]), params))
    center = parse_vec3(op.get("center", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    axis_a, axis_b, vertical_axis = scatter_plane_axes(op)
    seed = int(round(eval_numeric_expr(op.get("seed", 1), params)))
    rng = random.Random(seed)
    min_distance = max(0.0, eval_numeric_expr(op.get("min_distance", op.get("spacing", 0.0)), params))
    jitter = max(0.0, eval_numeric_expr(op.get("jitter", 0.0), params))
    attempts = max(count, int(round(eval_numeric_expr(op.get("attempts", count * 200), params))))
    target_name = scatter_target_name(op)
    surface_offset = eval_numeric_expr(
        op.get("normal_offset", op.get("surface_offset", op.get("height_offset", 0.0))), params
    )
    align_to_normal = parse_bool(op.get("align_to_normal"), False)
    up_vector = [0.0, 0.0, 0.0]
    up_vector[vertical_axis] = 1.0
    surface_samples: Optional[List[Tuple[Vec3, Vec3, Vec3, Vec3, float]]] = None
    if target_name:
        target = scene_objects.get(target_name) if scene_objects else None
        if target is None:
            warn(f"scatter target '{target_name}' not found; falling back to rectangular field")
        else:
            surface_samples = surface_triangles(target.mesh)
            if not surface_samples:
                warn(f"scatter target '{target_name}' has no usable faces; falling back to rectangular field")
                surface_samples = None
    avoid_objects = [
        scene_objects[name]
        for name in parse_name_list(op.get("avoid"))
        if scene_objects is not None and name in scene_objects
    ]
    clearance = max(0.0, eval_numeric_expr(op.get("clearance", 0.0), params))
    height_min = op.get("height_min")
    height_max = op.get("height_max")
    slope_min = op.get("slope_min")
    slope_max = op.get("slope_max")
    cluster_count = max(
        0,
        int(round(eval_numeric_expr(op.get("cluster_count", op.get("clusters", 0)), params))),
    )
    cluster_radius = max(0.0, eval_numeric_expr(op.get("cluster_radius", 0.0), params))
    cluster_centers: List[Tuple[Vec3, Vec3]] = []
    for _ in range(cluster_count):
        normal = tuple(up_vector)
        if surface_samples is not None:
            cluster_point, normal = sample_surface_point(surface_samples, rng)
        else:
            point = [center[0], center[1], center[2]]
            point[axis_a] += rng.uniform(-width * 0.5, width * 0.5)
            point[axis_b] += rng.uniform(-depth * 0.5, depth * 0.5)
            cluster_point = (point[0], point[1], point[2])
        cluster_centers.append((cluster_point, normal))

    placements: List[Tuple[Vec3, Vec3]] = []
    min_d2 = min_distance * min_distance
    tries = 0
    while len(placements) < count and tries < attempts:
        tries += 1
        normal = tuple(up_vector)
        if cluster_centers:
            cluster_point, normal = cluster_centers[rng.randrange(len(cluster_centers))]
            angle = rng.random() * math.tau
            radius = cluster_radius * math.sqrt(rng.random())
            if surface_samples is not None:
                tangent_a, tangent_b = plane_basis(normal)
                sampled = vec_add(
                    cluster_point,
                    vec_add(vec_mul(tangent_a, math.cos(angle) * radius), vec_mul(tangent_b, math.sin(angle) * radius)),
                )
                projected = project_to_surface(surface_samples, sampled, axis_a, axis_b, vertical_axis)
                if projected is not None:
                    sampled, normal = projected
            else:
                values = [cluster_point[0], cluster_point[1], cluster_point[2]]
                values[axis_a] += math.cos(angle) * radius
                values[axis_b] += math.sin(angle) * radius
                sampled = (values[0], values[1], values[2])
            candidate = vec_add(sampled, vec_mul(normal, surface_offset))
        elif surface_samples is not None:
            sampled, normal = sample_surface_point(surface_samples, rng)
            if jitter > 0:
                tangent_a, tangent_b = plane_basis(normal)
                sampled = vec_add(
                    sampled,
                    vec_add(
                        vec_mul(tangent_a, rng.uniform(-jitter, jitter)),
                        vec_mul(tangent_b, rng.uniform(-jitter, jitter)),
                    ),
                )
            candidate = vec_add(sampled, vec_mul(normal, surface_offset))
        else:
            a = rng.uniform(-width * 0.5, width * 0.5)
            b = rng.uniform(-depth * 0.5, depth * 0.5)
            if jitter > 0:
                a += rng.uniform(-jitter, jitter)
                b += rng.uniform(-jitter, jitter)
            point = [center[0], center[1], center[2]]
            point[axis_a] += a
            point[axis_b] += b
            candidate = (point[0], point[1], point[2])
        if height_min is not None and candidate[vertical_axis] < eval_numeric_expr(height_min, params):
            continue
        if height_max is not None and candidate[vertical_axis] > eval_numeric_expr(height_max, params):
            continue
        slope_degrees = math.degrees(
            math.acos(max(-1.0, min(1.0, abs(vec_dot(vec_normalize(normal), tuple(up_vector))))))
        )
        if slope_min is not None and slope_degrees < eval_numeric_expr(slope_min, params):
            continue
        if slope_max is not None and slope_degrees > eval_numeric_expr(slope_max, params):
            continue
        if any(bbox_contains_point(avoid.mesh, candidate, clearance) for avoid in avoid_objects):
            continue
        if min_distance > 0:
            too_close = False
            for existing, _existing_normal in placements:
                da = existing[axis_a] - candidate[axis_a]
                db = existing[axis_b] - candidate[axis_b]
                if da * da + db * db < min_d2:
                    too_close = True
                    break
            if too_close:
                continue
        placements.append((candidate, normal))

    if len(placements) < count:
        warn(
            f"scatter placed {len(placements)}/{count} copies; reduce min_distance or increase target area/width/depth/attempts"
        )

    scattered = Mesh()
    for n, (placement, normal) in enumerate(placements):
        rand = rng.random()
        scope = {
            "i": float(n),
            "index": float(n),
            "count": float(count),
            "t": float(n / max(1, count - 1)),
            "px": placement[0],
            "py": placement[1],
            "pz": placement[2],
            "nx": normal[0],
            "ny": normal[1],
            "nz": normal[2],
            "rand": rand,
            "random": rand,
            "rand_scale": rng.random(),
            "rand_x": rng.random(),
            "rand_y": rng.random(),
            "rand_z": rng.random(),
        }
        scale = scatter_scale(op, params, scope)
        rotation = scatter_rotation(op, params, scope, vertical_axis)
        offset = parse_vec3(op.get("position", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope)
        pivot = parse_vec3(op.get("pivot", [0, 0, 0]), params, (0.0, 0.0, 0.0), scope)
        copy_vertices: List[Vec3] = []
        for vertex in mesh.vertices:
            local = (
                (vertex[0] - pivot[0]) * scale[0],
                (vertex[1] - pivot[1]) * scale[1],
                (vertex[2] - pivot[2]) * scale[2],
            )
            rotated = rotate_point(local, rotation)
            if align_to_normal:
                rotated = align_vector_between(rotated, tuple(up_vector), normal)
            copy_vertices.append(
                (
                    rotated[0] + pivot[0] + placement[0] + offset[0],
                    rotated[1] + pivot[1] + placement[1] + offset[1],
                    rotated[2] + pivot[2] + placement[2] + offset[2],
                )
            )
        scattered.extend(Mesh(copy_vertices, [list(face) for face in mesh.faces]))

    if str(op.get("mode", "replace")).strip().lower() == "append":
        out = mesh.copy()
        out.extend(scattered)
        return out
    return scattered


def op_deform(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    expr = op.get("position", op.get("expr", op.get("xyz", ["x", "y", "z"])))
    selected = selected_vertex_indices(mesh, op)
    min_corner, max_corner = selected_bbox(mesh, selected)
    spans = [
        max(max_corner[0] - min_corner[0], 1e-9),
        max(max_corner[1] - min_corner[1], 1e-9),
        max(max_corner[2] - min_corner[2], 1e-9),
    ]
    vertices: List[Vec3] = []
    selected_order = [
        idx for idx in range(1, len(mesh.vertices) + 1)
        if selected is None or idx in selected
    ]
    selected_rank = {idx: rank for rank, idx in enumerate(selected_order)}
    vertex_count = max(1, len(selected_order))
    for idx, (x, y, z) in enumerate(mesh.vertices):
        vertex_idx = idx + 1
        if selected is not None and vertex_idx not in selected:
            vertices.append((x, y, z))
            continue
        rank = selected_rank.get(vertex_idx, idx)
        scope = {
            "x": x,
            "y": y,
            "z": z,
            "u": (x - min_corner[0]) / spans[0],
            "v": (y - min_corner[1]) / spans[1],
            "w": (z - min_corner[2]) / spans[2],
            "i": float(rank),
            "index": float(rank),
            "vertex_count": float(vertex_count),
            "t": float(rank / max(1, vertex_count - 1)),
        }
        vertices.append(parse_vec3(expr, params, (x, y, z), scope))
    return Mesh(
        vertices,
        [list(face) for face in mesh.faces],
        [list(group) for group in mesh.groups],
        {name: list(group) for name, group in mesh.named_groups.items()},
    )


def op_subdivide(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    level = max(0, min(3, int(op.get("level", 1))))
    out = mesh.copy()
    for _ in range(level):
        next_vertices = list(out.vertices)
        next_faces: List[Face] = []
        for face in out.faces:
            pts = [out.vertices[i - 1] for i in face if 1 <= i <= len(out.vertices)]
            if len(pts) < 3:
                continue
            center = (
                sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts),
                sum(p[2] for p in pts) / len(pts),
            )
            center_idx = len(next_vertices) + 1
            next_vertices.append(center)
            for i, a in enumerate(face):
                b = face[(i + 1) % len(face)]
                next_faces.append([a, b, center_idx])
        out = Mesh(next_vertices, next_faces)
    return out


def vertex_neighbors(mesh: Mesh) -> List[set[int]]:
    neighbors: List[set[int]] = [set() for _ in mesh.vertices]
    for face in mesh.faces:
        for i, idx in enumerate(face):
            if idx < 1 or idx > len(mesh.vertices):
                continue
            prev_idx = face[i - 1]
            next_idx = face[(i + 1) % len(face)]
            if 1 <= prev_idx <= len(mesh.vertices):
                neighbors[idx - 1].add(prev_idx - 1)
            if 1 <= next_idx <= len(mesh.vertices):
                neighbors[idx - 1].add(next_idx - 1)
    return neighbors


def op_smooth(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    iterations = max(0, min(20, int(op.get("iterations", 1))))
    strength = max(0.0, min(1.0, float(op.get("strength", 0.5))))
    out = mesh.copy()
    for _ in range(iterations):
        neighbors = vertex_neighbors(out)
        vertices: List[Vec3] = []
        for idx, vertex in enumerate(out.vertices):
            ns = neighbors[idx]
            if not ns:
                vertices.append(vertex)
                continue
            avg = (
                sum(out.vertices[n][0] for n in ns) / len(ns),
                sum(out.vertices[n][1] for n in ns) / len(ns),
                sum(out.vertices[n][2] for n in ns) / len(ns),
            )
            vertices.append(
                (
                    vertex[0] * (1 - strength) + avg[0] * strength,
                    vertex[1] * (1 - strength) + avg[1] * strength,
                    vertex[2] * (1 - strength) + avg[2] * strength,
                )
            )
        out.vertices = vertices
    return out


def op_simplify(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    ratio = max(0.05, min(1.0, float(op.get("ratio", 1.0))))
    if ratio >= 0.999 or not mesh.faces:
        return mesh
    target = max(1, int(math.ceil(len(mesh.faces) * ratio)))
    step = max(1, int(round(len(mesh.faces) / target)))
    faces = [face for i, face in enumerate(mesh.faces) if i % step == 0][:target]
    return compact_mesh(mesh, faces)


def vec_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def vec_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_length(a: Vec3) -> float:
    return math.sqrt(vec_dot(a, a))


def vec_normalize(a: Vec3, fallback: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    length = vec_length(a)
    if length <= 1e-12:
        return fallback
    return (a[0] / length, a[1] / length, a[2] / length)


def face_normal(mesh: Mesh, face: Face) -> Vec3:
    pts = [mesh.vertices[i - 1] for i in face if 1 <= i <= len(mesh.vertices)]
    if len(pts) < 3:
        return (0.0, 0.0, 0.0)
    nx = ny = nz = 0.0
    for i, current in enumerate(pts):
        nxt = pts[(i + 1) % len(pts)]
        nx += (current[1] - nxt[1]) * (current[2] + nxt[2])
        ny += (current[2] - nxt[2]) * (current[0] + nxt[0])
        nz += (current[0] - nxt[0]) * (current[1] + nxt[1])
    return vec_normalize((nx, ny, nz))


def mesh_edges(mesh: Mesh, mode: Any, angle_degrees: float) -> List[Tuple[int, int]]:
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    normals = [face_normal(mesh, face) for face in mesh.faces]
    for face_index, face in enumerate(mesh.faces):
        clean = [idx for idx in face if 1 <= idx <= len(mesh.vertices)]
        for i, a in enumerate(clean):
            b = clean[(i + 1) % len(clean)]
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            edge_faces.setdefault(key, []).append(face_index)

    edge_mode = str(mode or "feature").strip().lower()
    if edge_mode == "all":
        return sorted(edge_faces.keys())
    if edge_mode == "boundary":
        return sorted(edge for edge, faces in edge_faces.items() if len(faces) == 1)

    threshold = math.cos(math.radians(max(0.0, min(180.0, angle_degrees))))
    selected: List[Tuple[int, int]] = []
    for edge, faces in edge_faces.items():
        if len(faces) != 2:
            selected.append(edge)
            continue
        a = normals[faces[0]]
        b = normals[faces[1]]
        if vec_length(a) <= 1e-12 or vec_length(b) <= 1e-12:
            continue
        if abs(vec_dot(a, b)) <= threshold:
            selected.append(edge)
    return sorted(selected)


def point_segment_distance(point: Vec3, a: Vec3, b: Vec3) -> float:
    ab = vec_sub(b, a)
    denom = vec_dot(ab, ab)
    if denom <= 1e-12:
        return vec_length(vec_sub(point, a))
    t = max(0.0, min(1.0, vec_dot(vec_sub(point, a), ab) / denom))
    closest = vec_add(a, vec_mul(ab, t))
    return vec_length(vec_sub(point, closest))


def orient_faces_outward(vertices: List[Vec3], faces: List[Face]) -> List[Face]:
    if not vertices:
        return faces
    center = (
        sum(v[0] for v in vertices) / len(vertices),
        sum(v[1] for v in vertices) / len(vertices),
        sum(v[2] for v in vertices) / len(vertices),
    )
    oriented: List[Face] = []
    for face in faces:
        pts = [vertices[i - 1] for i in face if 1 <= i <= len(vertices)]
        if len(pts) < 3:
            continue
        normal = vec_cross(vec_sub(pts[1], pts[0]), vec_sub(pts[2], pts[0]))
        centroid = (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
            sum(p[2] for p in pts) / len(pts),
        )
        if vec_dot(normal, vec_sub(centroid, center)) < 0:
            oriented.append(list(reversed(face)))
        else:
            oriented.append(face)
    return oriented


def face_area(vertices: List[Vec3], face: Face) -> float:
    pts = [vertices[i - 1] for i in face if 1 <= i <= len(vertices)]
    if len(pts) < 3:
        return 0.0
    origin = pts[0]
    area = 0.0
    for i in range(1, len(pts) - 1):
        area += vec_length(vec_cross(vec_sub(pts[i], origin), vec_sub(pts[i + 1], origin))) * 0.5
    return area


def weld_mesh(mesh: Mesh, tolerance: float) -> Mesh:
    if tolerance <= 0.0 or not mesh.vertices:
        return mesh

    vertices: List[Vec3] = []
    remap: Dict[int, int] = {}
    buckets: Dict[Tuple[int, int, int], List[int]] = {}
    inv = 1.0 / tolerance

    def cell_for(vertex: Vec3) -> Tuple[int, int, int]:
        return (
            math.floor(vertex[0] * inv),
            math.floor(vertex[1] * inv),
            math.floor(vertex[2] * inv),
        )

    for old_index, vertex in enumerate(mesh.vertices, start=1):
        cx, cy, cz = cell_for(vertex)
        found: Optional[int] = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for candidate in buckets.get((cx + dx, cy + dy, cz + dz), []):
                        if vec_length(vec_sub(vertices[candidate - 1], vertex)) <= tolerance:
                            found = candidate
                            break
                    if found is not None:
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            vertices.append(vertex)
            found = len(vertices)
            buckets.setdefault((cx, cy, cz), []).append(found)
        remap[old_index] = found

    faces: List[Face] = []
    seen_faces: set[Tuple[int, ...]] = set()
    for face in mesh.faces:
        remapped: Face = []
        for idx in face:
            next_idx = remap.get(idx)
            if next_idx is None:
                continue
            if remapped and remapped[-1] == next_idx:
                continue
            remapped.append(next_idx)
        if len(remapped) > 1 and remapped[0] == remapped[-1]:
            remapped.pop()
        if len(set(remapped)) < 3:
            continue
        key = tuple(sorted(remapped))
        if key in seen_faces:
            continue
        if face_area(vertices, remapped) <= 1e-10:
            continue
        seen_faces.add(key)
        faces.append(remapped)
    return compact_mesh(Mesh(vertices, faces), faces)


def cohere_face_winding(mesh: Mesh) -> Mesh:
    edge_faces: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = {}
    for face_index, face in enumerate(mesh.faces):
        clean = [idx for idx in face if 1 <= idx <= len(mesh.vertices)]
        for i, a in enumerate(clean):
            b = clean[(i + 1) % len(clean)]
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            edge_faces.setdefault(key, []).append((face_index, a, b))

    adjacency: List[List[Tuple[int, bool]]] = [[] for _ in mesh.faces]
    for entries in edge_faces.values():
        if len(entries) != 2:
            continue
        a_face, a_start, a_end = entries[0]
        b_face, b_start, b_end = entries[1]
        same_direction = a_start == b_start and a_end == b_end
        adjacency[a_face].append((b_face, same_direction))
        adjacency[b_face].append((a_face, same_direction))

    should_flip: List[Optional[bool]] = [None for _ in mesh.faces]
    for start in range(len(mesh.faces)):
        if should_flip[start] is not None:
            continue
        should_flip[start] = False
        stack = [start]
        while stack:
            current = stack.pop()
            current_flip = bool(should_flip[current])
            for neighbor, same_direction in adjacency[current]:
                desired_flip = (not current_flip) if same_direction else current_flip
                if should_flip[neighbor] is None:
                    should_flip[neighbor] = desired_flip
                    stack.append(neighbor)

    faces = [
        list(reversed(face)) if should_flip[index] else list(face)
        for index, face in enumerate(mesh.faces)
    ]
    return Mesh(list(mesh.vertices), faces)


def vertex_normals(mesh: Mesh) -> List[Vec3]:
    normals: List[Vec3] = [(0.0, 0.0, 0.0) for _ in mesh.vertices]
    for face in mesh.faces:
        normal = face_normal(mesh, face)
        if vec_length(normal) <= 1e-12:
            continue
        for idx in face:
            if 1 <= idx <= len(normals):
                normals[idx - 1] = vec_add(normals[idx - 1], normal)
    return [vec_normalize(normal) for normal in normals]


def catmull_clark_subdivide(mesh: Mesh, levels: int) -> Mesh:
    out = mesh.copy()
    for _ in range(max(0, levels)):
        if not out.vertices or not out.faces:
            return out

        face_points: List[Vec3] = []
        vertex_faces: List[List[int]] = [[] for _ in out.vertices]
        vertex_edges: List[set[Tuple[int, int]]] = [set() for _ in out.vertices]
        edge_faces: Dict[Tuple[int, int], List[int]] = {}

        for face_index, face in enumerate(out.faces):
            pts = [out.vertices[idx - 1] for idx in face if 1 <= idx <= len(out.vertices)]
            if len(pts) < 3:
                face_points.append((0.0, 0.0, 0.0))
                continue
            face_points.append(
                (
                    sum(p[0] for p in pts) / len(pts),
                    sum(p[1] for p in pts) / len(pts),
                    sum(p[2] for p in pts) / len(pts),
                )
            )
            clean = [idx for idx in face if 1 <= idx <= len(out.vertices)]
            for i, a in enumerate(clean):
                b = clean[(i + 1) % len(clean)]
                key = (a, b) if a < b else (b, a)
                edge_faces.setdefault(key, []).append(face_index)
                vertex_faces[a - 1].append(face_index)
                vertex_edges[a - 1].add(key)

        edge_points: Dict[Tuple[int, int], Vec3] = {}
        for edge, adjacent_faces in edge_faces.items():
            a, b = edge
            pa = out.vertices[a - 1]
            pb = out.vertices[b - 1]
            if len(adjacent_faces) >= 2:
                fp_a = face_points[adjacent_faces[0]]
                fp_b = face_points[adjacent_faces[1]]
                edge_points[edge] = (
                    (pa[0] + pb[0] + fp_a[0] + fp_b[0]) * 0.25,
                    (pa[1] + pb[1] + fp_a[1] + fp_b[1]) * 0.25,
                    (pa[2] + pb[2] + fp_a[2] + fp_b[2]) * 0.25,
                )
            else:
                edge_points[edge] = ((pa[0] + pb[0]) * 0.5, (pa[1] + pb[1]) * 0.5, (pa[2] + pb[2]) * 0.5)

        next_vertices: List[Vec3] = []
        old_vertex_map: Dict[int, int] = {}
        for old_index, vertex in enumerate(out.vertices, start=1):
            faces_for_vertex = vertex_faces[old_index - 1]
            edges_for_vertex = list(vertex_edges[old_index - 1])
            boundary_neighbors: List[int] = []
            for edge in edges_for_vertex:
                if len(edge_faces.get(edge, [])) == 1:
                    boundary_neighbors.append(edge[1] if edge[0] == old_index else edge[0])

            if len(boundary_neighbors) >= 2:
                p1 = out.vertices[boundary_neighbors[0] - 1]
                p2 = out.vertices[boundary_neighbors[1] - 1]
                new_vertex = (
                    vertex[0] * 0.75 + (p1[0] + p2[0]) * 0.125,
                    vertex[1] * 0.75 + (p1[1] + p2[1]) * 0.125,
                    vertex[2] * 0.75 + (p1[2] + p2[2]) * 0.125,
                )
            elif faces_for_vertex and edges_for_vertex:
                n = float(len(faces_for_vertex))
                f_avg = (
                    sum(face_points[i][0] for i in faces_for_vertex) / n,
                    sum(face_points[i][1] for i in faces_for_vertex) / n,
                    sum(face_points[i][2] for i in faces_for_vertex) / n,
                )
                r_avg = (
                    sum((out.vertices[e[0] - 1][0] + out.vertices[e[1] - 1][0]) * 0.5 for e in edges_for_vertex)
                    / len(edges_for_vertex),
                    sum((out.vertices[e[0] - 1][1] + out.vertices[e[1] - 1][1]) * 0.5 for e in edges_for_vertex)
                    / len(edges_for_vertex),
                    sum((out.vertices[e[0] - 1][2] + out.vertices[e[1] - 1][2]) * 0.5 for e in edges_for_vertex)
                    / len(edges_for_vertex),
                )
                new_vertex = (
                    (f_avg[0] + 2.0 * r_avg[0] + (n - 3.0) * vertex[0]) / n,
                    (f_avg[1] + 2.0 * r_avg[1] + (n - 3.0) * vertex[1]) / n,
                    (f_avg[2] + 2.0 * r_avg[2] + (n - 3.0) * vertex[2]) / n,
                )
            else:
                new_vertex = vertex
            next_vertices.append(new_vertex)
            old_vertex_map[old_index] = len(next_vertices)

        edge_vertex_map: Dict[Tuple[int, int], int] = {}
        for edge, point in edge_points.items():
            next_vertices.append(point)
            edge_vertex_map[edge] = len(next_vertices)

        face_vertex_map: Dict[int, int] = {}
        for face_index, point in enumerate(face_points):
            next_vertices.append(point)
            face_vertex_map[face_index] = len(next_vertices)

        next_faces: List[Face] = []
        for face_index, face in enumerate(out.faces):
            clean = [idx for idx in face if 1 <= idx <= len(out.vertices)]
            if len(clean) < 3:
                continue
            face_point_idx = face_vertex_map[face_index]
            for i, current in enumerate(clean):
                prev_idx = clean[i - 1]
                next_idx = clean[(i + 1) % len(clean)]
                prev_edge = (prev_idx, current) if prev_idx < current else (current, prev_idx)
                next_edge = (current, next_idx) if current < next_idx else (next_idx, current)
                next_faces.append(
                    [
                        old_vertex_map[current],
                        edge_vertex_map[next_edge],
                        face_point_idx,
                        edge_vertex_map[prev_edge],
                    ]
                )

        out = weld_mesh(Mesh(next_vertices, next_faces), 1e-8)
    return out


def op_face_lattice(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    if not mesh.vertices or not mesh.faces:
        return mesh

    inset = max(0.02, min(0.92, eval_numeric_expr(op.get("inset", 0.28), params)))
    thickness = max(1e-5, eval_numeric_expr(op.get("thickness", 0.04), params))
    weld = max(0.0, eval_numeric_expr(op.get("weld", thickness * 0.3), params))
    guide_subdivide = max(
        0,
        min(
            2,
            int(
                round(
                    eval_numeric_expr(
                        op.get("guide_subdivide", 0),
                        params,
                    )
                )
            ),
        ),
    )
    guide_smooth = max(
        0,
        min(
            12,
            int(
                round(
                    eval_numeric_expr(
                        op.get("guide_smooth", 0),
                        params,
                    )
                )
            ),
        ),
    )
    subdivide_levels = max(0, min(3, int(round(eval_numeric_expr(op.get("subdivide", 0), params)))))
    smooth_iterations = max(0, min(8, int(round(eval_numeric_expr(op.get("smooth", 0), params)))))
    smooth_strength = max(0.0, min(1.0, eval_numeric_expr(op.get("smooth_strength", 0.25), params)))

    source = weld_mesh(mesh, weld)
    if guide_subdivide > 0:
        source = catmull_clark_subdivide(source, guide_subdivide)
    if guide_smooth > 0:
        source = op_smooth(source, {"iterations": guide_smooth, "strength": 0.25})
    normals = vertex_normals(source)

    vertices: List[Vec3] = []
    faces: List[Face] = []
    outer_top_by_source: Dict[int, int] = {}
    outer_bottom_by_source: Dict[int, int] = {}

    def add_vertex(vertex: Vec3) -> int:
        vertices.append(vertex)
        return len(vertices)

    def outer_indices(source_idx: int) -> Tuple[int, int]:
        top = outer_top_by_source.get(source_idx)
        bottom = outer_bottom_by_source.get(source_idx)
        if top is not None and bottom is not None:
            return top, bottom
        point = source.vertices[source_idx - 1]
        normal = normals[source_idx - 1] if 1 <= source_idx <= len(normals) else (0.0, 0.0, 1.0)
        if vec_length(normal) <= 1e-12:
            normal = (0.0, 0.0, 1.0)
        offset = vec_mul(normal, thickness * 0.5)
        top = add_vertex(vec_add(point, offset))
        bottom = add_vertex(vec_sub(point, offset))
        outer_top_by_source[source_idx] = top
        outer_bottom_by_source[source_idx] = bottom
        return top, bottom

    def add_cap_fan(ring: List[int], center_point: Vec3) -> None:
        if len(ring) < 3:
            return
        center_idx = add_vertex(center_point)
        for i, idx in enumerate(ring):
            nxt = ring[(i + 1) % len(ring)]
            if idx != nxt:
                faces.append([center_idx, idx, nxt])

    face_records: List[Dict[str, Any]] = []
    edge_records: Dict[Tuple[int, int], List[Dict[str, int]]] = {}
    vertex_records: Dict[int, List[Dict[str, int]]] = {}

    for face_index, face in enumerate(source.faces):
        clean = [idx for idx in face if 1 <= idx <= len(source.vertices)]
        if len(clean) < 3:
            continue
        pts = [source.vertices[idx - 1] for idx in clean]
        normal = face_normal(source, clean)
        if vec_length(normal) <= 1e-12:
            continue
        center = (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
            sum(p[2] for p in pts) / len(pts),
        )
        inset_pts = [vec_add(vec_mul(p, 1.0 - inset), vec_mul(center, inset)) for p in pts]
        half = thickness * 0.5
        offset = vec_mul(normal, half)

        inner_top = [add_vertex(vec_add(p, offset)) for p in inset_pts]
        inner_bottom = [add_vertex(vec_sub(p, offset)) for p in inset_pts]
        record = {
            "clean": clean,
            "inner_top": inner_top,
            "inner_bottom": inner_bottom,
        }
        face_records.append(record)

        count = len(pts)
        for i in range(count):
            j = (i + 1) % count
            a = clean[i]
            b = clean[j]
            edge = (a, b) if a < b else (b, a)
            edge_records.setdefault(edge, []).append({"face": len(face_records) - 1, "i": i, "j": j})
            vertex_records.setdefault(a, []).append({"face": len(face_records) - 1, "i": i})
            faces.append([inner_bottom[j], inner_bottom[i], inner_top[i], inner_top[j]])

    for edge, records in edge_records.items():
        if len(records) == 1:
            record = face_records[records[0]["face"]]
            i = records[0]["i"]
            j = records[0]["j"]
            a = record["clean"][i]
            b = record["clean"][j]
            outer_a_top, outer_a_bottom = outer_indices(a)
            outer_b_top, outer_b_bottom = outer_indices(b)
            inner_top = record["inner_top"]
            inner_bottom = record["inner_bottom"]

            faces.append([outer_a_top, outer_b_top, inner_top[j], inner_top[i]])
            faces.append([outer_b_bottom, outer_a_bottom, inner_bottom[i], inner_bottom[j]])
            faces.append([outer_a_bottom, outer_b_bottom, outer_b_top, outer_a_top])
            continue

        first = face_records[records[0]["face"]]
        second = face_records[records[1]["face"]]
        i0 = records[0]["i"]
        j0 = records[0]["j"]
        i1 = records[1]["i"]
        j1 = records[1]["j"]
        first_top_i = first["inner_top"][i0]
        first_top_j = first["inner_top"][j0]
        second_top_i = second["inner_top"][i1]
        second_top_j = second["inner_top"][j1]
        first_bottom_i = first["inner_bottom"][i0]
        first_bottom_j = first["inner_bottom"][j0]
        second_bottom_i = second["inner_bottom"][i1]
        second_bottom_j = second["inner_bottom"][j1]

        if first["clean"][i0] == second["clean"][i1]:
            second_top_a = second_top_i
            second_top_b = second_top_j
            second_bottom_a = second_bottom_i
            second_bottom_b = second_bottom_j
        else:
            second_top_a = second_top_j
            second_top_b = second_top_i
            second_bottom_a = second_bottom_j
            second_bottom_b = second_bottom_i

        faces.append([first_top_i, first_top_j, second_top_b, second_top_a])
        faces.append([first_bottom_j, first_bottom_i, second_bottom_a, second_bottom_b])

    for source_idx, records in vertex_records.items():
        unique: Dict[int, Dict[str, int]] = {}
        for record in records:
            top_idx = face_records[record["face"]]["inner_top"][record["i"]]
            unique[top_idx] = record
        has_boundary_edge = any(
            source_idx in edge and len(edge_record_list) == 1
            for edge, edge_record_list in edge_records.items()
        )
        if len(unique) < 3 and not (has_boundary_edge and len(unique) >= 2):
            continue

        point = source.vertices[source_idx - 1]
        normal = normals[source_idx - 1] if 1 <= source_idx <= len(normals) else (0.0, 0.0, 1.0)
        if vec_length(normal) <= 1e-12:
            normal = (0.0, 0.0, 1.0)
        tangent = vec_cross(normal, (0.0, 0.0, 1.0))
        if vec_length(tangent) <= 1e-12:
            tangent = vec_cross(normal, (0.0, 1.0, 0.0))
        tangent = vec_normalize(tangent)
        bitangent = vec_normalize(vec_cross(normal, tangent))

        sorted_records = sorted(
            unique.values(),
            key=lambda record: math.atan2(
                vec_dot(
                    vec_sub(
                        vertices[face_records[record["face"]]["inner_top"][record["i"]] - 1],
                        point,
                    ),
                    bitangent,
                ),
                vec_dot(
                    vec_sub(
                        vertices[face_records[record["face"]]["inner_top"][record["i"]] - 1],
                        point,
                    ),
                    tangent,
                ),
            ),
        )
        top_cap = [face_records[record["face"]]["inner_top"][record["i"]] for record in sorted_records]
        bottom_cap = [
            face_records[record["face"]]["inner_bottom"][record["i"]]
            for record in reversed(sorted_records)
        ]
        if has_boundary_edge:
            outer_top, outer_bottom = outer_indices(source_idx)
            top_cap.insert(0, outer_top)
            bottom_cap.append(outer_bottom)
        add_cap_fan(top_cap, vec_add(point, vec_mul(normal, thickness * 0.5)))
        add_cap_fan(bottom_cap, vec_sub(point, vec_mul(normal, thickness * 0.5)))

    if not vertices or not faces:
        warn("face_lattice generated an empty mesh; leaving mesh unchanged")
        return mesh

    lattice = cohere_face_winding(weld_mesh(Mesh(vertices, faces), weld))
    if subdivide_levels > 0:
        lattice = cohere_face_winding(catmull_clark_subdivide(lattice, subdivide_levels))
    if smooth_iterations > 0:
        lattice = op_smooth(lattice, {"iterations": smooth_iterations, "strength": smooth_strength})

    mode = str(op.get("mode", "replace")).strip().lower()
    if mode == "append":
        out = mesh.copy()
        out.extend(lattice)
        return out
    return lattice


def op_skin_edges(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    if not mesh.vertices or not mesh.faces:
        return mesh

    radius = max(1e-4, eval_numeric_expr(op.get("radius", 0.08), params))
    resolution = max(8, min(72, int(round(eval_numeric_expr(op.get("resolution", 36), params)))))
    angle = eval_numeric_expr(op.get("angle", 25), params)
    edges = mesh_edges(mesh, op.get("edges", "feature"), angle)
    if not edges:
        warn("skin_edges found no matching edges; leaving mesh unchanged")
        return mesh

    segments = [(mesh.vertices[a - 1], mesh.vertices[b - 1]) for a, b in edges]
    xs = [p[0] for seg in segments for p in seg]
    ys = [p[1] for seg in segments for p in seg]
    zs = [p[2] for seg in segments for p in seg]
    raw_min = (min(xs), min(ys), min(zs))
    raw_max = (max(xs), max(ys), max(zs))
    base_span = max(raw_max[0] - raw_min[0], raw_max[1] - raw_min[1], raw_max[2] - raw_min[2], radius)
    padding = max(radius * 2.0, eval_numeric_expr(op.get("padding", radius * 2.0), params))
    min_corner = (raw_min[0] - padding, raw_min[1] - padding, raw_min[2] - padding)
    max_corner = (raw_max[0] + padding, raw_max[1] + padding, raw_max[2] + padding)
    span = (
        max(max_corner[0] - min_corner[0], radius),
        max(max_corner[1] - min_corner[1], radius),
        max(max_corner[2] - min_corner[2], radius),
    )
    cell_size = max(base_span + padding * 2.0, radius * 4.0) / resolution
    nx = max(3, int(math.ceil(span[0] / cell_size)) + 1)
    ny = max(3, int(math.ceil(span[1] / cell_size)) + 1)
    nz = max(3, int(math.ceil(span[2] / cell_size)) + 1)

    values: List[float] = [0.0] * (nx * ny * nz)

    def grid_index(i: int, j: int, k: int) -> int:
        return (k * ny + j) * nx + i

    def grid_point(i: int, j: int, k: int) -> Vec3:
        return (
            min_corner[0] + i * cell_size,
            min_corner[1] + j * cell_size,
            min_corner[2] + k * cell_size,
        )

    def field(point: Vec3) -> float:
        return min(point_segment_distance(point, a, b) for a, b in segments) - radius

    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                values[grid_index(i, j, k)] = field(grid_point(i, j, k))

    corner_offsets = [
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    ]
    cube_edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    out_vertices: List[Vec3] = []
    cell_vertices: Dict[Tuple[int, int, int], int] = {}

    for k in range(nz - 1):
        for j in range(ny - 1):
            for i in range(nx - 1):
                samples = [
                    values[grid_index(i + ox, j + oy, k + oz)]
                    for ox, oy, oz in corner_offsets
                ]
                if min(samples) > 0.0 or max(samples) <= 0.0:
                    continue
                intersections: List[Vec3] = []
                for a_idx, b_idx in cube_edges:
                    va = samples[a_idx]
                    vb = samples[b_idx]
                    if (va <= 0.0) == (vb <= 0.0):
                        continue
                    ao = corner_offsets[a_idx]
                    bo = corner_offsets[b_idx]
                    pa = grid_point(i + ao[0], j + ao[1], k + ao[2])
                    pb = grid_point(i + bo[0], j + bo[1], k + bo[2])
                    t = va / (va - vb) if abs(va - vb) > 1e-12 else 0.5
                    intersections.append(vec_add(pa, vec_mul(vec_sub(pb, pa), t)))
                if not intersections:
                    intersections.append(
                        (
                            min_corner[0] + (i + 0.5) * cell_size,
                            min_corner[1] + (j + 0.5) * cell_size,
                            min_corner[2] + (k + 0.5) * cell_size,
                        )
                    )
                vertex = (
                    sum(p[0] for p in intersections) / len(intersections),
                    sum(p[1] for p in intersections) / len(intersections),
                    sum(p[2] for p in intersections) / len(intersections),
                )
                out_vertices.append(vertex)
                cell_vertices[(i, j, k)] = len(out_vertices)

    out_faces: List[Face] = []

    def add_face(cells: List[Tuple[int, int, int]], flip: bool) -> None:
        if not all(cell in cell_vertices for cell in cells):
            return
        face = [cell_vertices[cell] for cell in cells]
        out_faces.append(list(reversed(face)) if flip else face)

    for k in range(nz):
        for j in range(ny):
            for i in range(nx - 1):
                if (values[grid_index(i, j, k)] <= 0.0) == (values[grid_index(i + 1, j, k)] <= 0.0):
                    continue
                if j == 0 or j >= ny - 1 or k == 0 or k >= nz - 1:
                    continue
                add_face(
                    [(i, j - 1, k - 1), (i, j, k - 1), (i, j, k), (i, j - 1, k)],
                    values[grid_index(i, j, k)] <= 0.0,
                )

    for k in range(nz):
        for j in range(ny - 1):
            for i in range(nx):
                if (values[grid_index(i, j, k)] <= 0.0) == (values[grid_index(i, j + 1, k)] <= 0.0):
                    continue
                if i == 0 or i >= nx - 1 or k == 0 or k >= nz - 1:
                    continue
                add_face(
                    [(i - 1, j, k - 1), (i, j, k - 1), (i, j, k), (i - 1, j, k)],
                    values[grid_index(i, j, k)] > 0.0,
                )

    for k in range(nz - 1):
        for j in range(ny):
            for i in range(nx):
                if (values[grid_index(i, j, k)] <= 0.0) == (values[grid_index(i, j, k + 1)] <= 0.0):
                    continue
                if i == 0 or i >= nx - 1 or j == 0 or j >= ny - 1:
                    continue
                add_face(
                    [(i - 1, j - 1, k), (i, j - 1, k), (i, j, k), (i - 1, j, k)],
                    values[grid_index(i, j, k)] <= 0.0,
                )

    if not out_vertices or not out_faces:
        warn("skin_edges generated an empty mesh; leaving mesh unchanged")
        return mesh

    skinned = Mesh(out_vertices, orient_faces_outward(out_vertices, out_faces))
    mode = str(op.get("mode", "replace")).strip().lower()
    if mode == "append":
        out = mesh.copy()
        out.extend(skinned)
        return out
    return skinned


def opening_specs_from_meta(meta_lines: List[str]) -> List[Dict[str, Any]]:
    openings: List[Dict[str, Any]] = []
    for raw_line in meta_lines:
        line = raw_line.strip()
        if not line.startswith("#@"):
            continue
        body = line[2:].strip()
        if not body.lower().startswith("opening"):
            continue
        if body.startswith("opening:"):
            raw_spec = body[len("opening:") :].strip()
        elif body.startswith("opening "):
            raw_spec = body[len("opening ") :].strip()
        else:
            continue
        spec = parse_tokens("opening " + raw_spec)
        spec.pop("cmd", None)
        if spec:
            openings.append(spec)
    return openings


def opening_matches_filter(spec: Dict[str, Any], op: Dict[str, Any]) -> bool:
    ids = op.get("ids")
    if ids:
        wanted = {
            str(item).strip()
            for item in (ids if isinstance(ids, (list, tuple)) else str(ids).split(","))
            if str(item).strip()
        }
        if wanted and str(spec.get("id", "")).strip() not in wanted:
            return False
    for key in ("role", "type"):
        wanted = op.get(key)
        if wanted and str(spec.get(key, "")).strip().lower() != str(wanted).strip().lower():
            return False
    return True


def add_loop_vertices(mesh: Mesh, points: List[Vec3]) -> List[int]:
    start = len(mesh.vertices) + 1
    mesh.vertices.extend(points)
    return [start + i for i in range(len(points))]


def add_ring_faces(mesh: Mesh, outer: List[int], inner: List[int], reverse: bool = False) -> None:
    count = min(len(outer), len(inner))
    for i in range(count):
        face = [outer[i], outer[(i + 1) % count], inner[(i + 1) % count], inner[i]]
        mesh.faces.append(list(reversed(face)) if reverse else face)


def add_loop_solid(mesh: Mesh, front: List[Vec3], back: List[Vec3]) -> None:
    front_indices = add_loop_vertices(mesh, front)
    back_indices = add_loop_vertices(mesh, back)
    mesh.faces.append(front_indices)
    mesh.faces.append(list(reversed(back_indices)))
    count = len(front_indices)
    for i in range(count):
        mesh.faces.append(
            [
                front_indices[i],
                front_indices[(i + 1) % count],
                back_indices[(i + 1) % count],
                back_indices[i],
            ]
        )


def build_glazed_opening_mesh(spec: Dict[str, Any], op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    loop = coerce_vec3_loop(spec.get("loop"))
    if len(loop) < 3:
        return Mesh()
    normal = coerce_vec3(spec.get("normal")) or face_normal_from_points(loop)
    normal = vec_normalize(normal)
    frame_width = max(
        0.0,
        eval_numeric_expr(spec.get("frame_width", op.get("frame_width", 0.04)), params),
    )
    frame_depth = max(
        0.0,
        eval_numeric_expr(spec.get("frame_depth", op.get("frame_depth", 0.035)), params),
    )
    panel_recess = max(
        0.0,
        eval_numeric_expr(spec.get("panel_recess", op.get("panel_recess", 0.018)), params),
    )
    panel_thickness = max(
        0.001,
        eval_numeric_expr(spec.get("panel_thickness", op.get("panel_thickness", 0.01)), params),
    )
    panel_inset = max(
        frame_width,
        eval_numeric_expr(spec.get("panel_inset", spec.get("inset", frame_width)), params),
    )
    inner = inset_planar_loop(loop, normal, panel_inset)
    if len(inner) != len(loop):
        return Mesh()

    out = Mesh()
    outer_front = add_loop_vertices(out, loop)
    inner_front = add_loop_vertices(out, inner)
    outer_back = add_loop_vertices(out, [vec_sub(point, vec_scale(normal, frame_depth)) for point in loop])
    inner_back = add_loop_vertices(out, [vec_sub(point, vec_scale(normal, frame_depth)) for point in inner])

    add_ring_faces(out, outer_front, inner_front)
    add_ring_faces(out, outer_back, inner_back, reverse=True)
    add_ring_faces(out, outer_front, outer_back, reverse=True)
    add_ring_faces(out, inner_front, inner_back)

    glass_front = [vec_sub(point, vec_scale(normal, panel_recess)) for point in inner]
    glass_back = [vec_sub(point, vec_scale(normal, panel_recess + panel_thickness)) for point in inner]
    add_loop_solid(out, glass_front, glass_back)
    return out


def op_build_glazed_openings(
    mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any], meta_lines: List[str]
) -> Mesh:
    openings = [
        spec for spec in opening_specs_from_meta(meta_lines) if opening_matches_filter(spec, op)
    ]
    if not openings:
        warn("build_glazed_openings found no matching #@opening metadata; leaving mesh unchanged")
        return mesh

    generated = Mesh()
    for spec in openings:
        opening_mesh = build_glazed_opening_mesh(spec, op, params)
        if not opening_mesh.vertices or not opening_mesh.faces:
            warn(f"build_glazed_openings skipped malformed opening {spec.get('id', '(unnamed)')!r}")
            continue
        generated.extend(opening_mesh)

    if not generated.vertices or not generated.faces:
        warn("build_glazed_openings generated an empty mesh; leaving mesh unchanged")
        return mesh

    mode = str(op.get("mode", "append")).strip().lower()
    if mode == "replace":
        return generated
    out = mesh.copy()
    out.extend(generated)
    return out


def op_snap_to_ground(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    ax = axis_index(op.get("axis", "y"), "y")
    min_corner, _ = mesh_bbox(mesh)
    delta = -min_corner[ax]
    vertices: List[Vec3] = []
    for vertex in mesh.vertices:
        values = list(vertex)
        values[ax] += delta
        vertices.append((values[0], values[1], values[2]))
    return Mesh(
        vertices,
        [list(face) for face in mesh.faces],
        [list(group) for group in mesh.groups],
        {name: list(group) for name, group in mesh.named_groups.items()},
    )


def op_center_origin(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    axes = str(op.get("axes", "xz")).strip().lower()
    min_corner, max_corner = mesh_bbox(mesh)
    center = [
        (min_corner[0] + max_corner[0]) * 0.5,
        (min_corner[1] + max_corner[1]) * 0.5,
        (min_corner[2] + max_corner[2]) * 0.5,
    ]
    vertices: List[Vec3] = []
    for vertex in mesh.vertices:
        values = list(vertex)
        for axis, idx in AXIS_INDEX.items():
            if axis in axes:
                values[idx] -= center[idx]
        vertices.append((values[0], values[1], values[2]))
    return Mesh(
        vertices,
        [list(face) for face in mesh.faces],
        [list(group) for group in mesh.groups],
        {name: list(group) for name, group in mesh.named_groups.items()},
    )


def validate_post_op(obj_name: str, op: Dict[str, Any]) -> None:
    cmd = str(op.get("cmd", "")).strip().lower()
    supported_attrs = SUPPORTED_POST_ATTRIBUTES.get(cmd)
    if supported_attrs is not None:
        for key in op.keys():
            if key != "cmd" and key not in supported_attrs:
                warn(f"{obj_name}: unsupported #@post {cmd} attribute '{key}'")
    for key, value in op.items():
        if key == "cmd":
            continue
        if has_template_placeholder(value):
            warn(
                f"{obj_name}: #@post {cmd} uses template placeholder syntax in {key}={value!r}; use bare parameter names"
            )
    if cmd == "smooth" and "level" in op and "iterations" not in op:
        warn(f"{obj_name}: smooth uses level=; use smooth iterations=n strength=v")
    if cmd == "tag" and "name" in op and "value" not in op:
        warn(f"{obj_name}: tag uses name=; use tag value=...")
    if cmd == "snap_to_ground" and ("surface" in op or "anchor" in op):
        warn(f"{obj_name}: snap_to_ground only supports axis=x|y|z")
    if cmd == "deform" and not any(k in op for k in ("position", "expr", "xyz")):
        warn(f"{obj_name}: deform requires position=[x,y,z]")


def apply_post_ops(obj: RawObject, scene_objects: Optional[Dict[str, RawObject]] = None) -> None:
    mesh = obj.mesh.copy()
    for op in obj.post_ops:
        cmd = str(op.get("cmd", "")).strip().lower()
        validate_post_op(obj.name, op)
        if cmd in {"material", "tag"}:
            continue
        if cmd == "transform":
            try:
                mesh = op_transform(mesh, op, obj.params)
            except Exception as e:
                warn(f"{obj.name}: transform failed: {e}")
        elif cmd == "symmetrize":
            mesh = op_symmetrize(mesh, op)
        elif cmd == "mirror":
            mesh = op_mirror(mesh, op)
        elif cmd == "array":
            mesh = op_array(mesh, op, obj.params)
        elif cmd == "scatter":
            try:
                mesh = op_scatter(mesh, op, obj.params, scene_objects)
            except Exception as e:
                warn(f"{obj.name}: scatter failed: {e}")
        elif cmd == "surface_snap":
            try:
                mesh = op_surface_snap(mesh, op, obj.params, scene_objects)
            except Exception as e:
                warn(f"{obj.name}: surface_snap failed: {e}")
        elif cmd == "conform":
            try:
                mesh = op_conform(mesh, op, obj.params, scene_objects)
            except Exception as e:
                warn(f"{obj.name}: conform failed: {e}")
        elif cmd == "path_array":
            try:
                mesh = op_path_array(mesh, op, obj.params, scene_objects)
            except Exception as e:
                warn(f"{obj.name}: path_array failed: {e}")
        elif cmd == "surface_array":
            try:
                mesh = op_surface_array(mesh, op, obj.params, scene_objects)
            except Exception as e:
                warn(f"{obj.name}: surface_array failed: {e}")
        elif cmd == "orient":
            try:
                mesh = op_orient(mesh, op, obj.params, scene_objects)
            except Exception as e:
                warn(f"{obj.name}: orient failed: {e}")
        elif cmd == "clip":
            try:
                mesh = op_clip(mesh, op, obj.params)
            except Exception as e:
                warn(f"{obj.name}: clip failed: {e}")
        elif cmd == "deform":
            mesh = op_deform(mesh, op, obj.params)
        elif cmd == "subdivide":
            mesh = op_subdivide(mesh, op)
        elif cmd == "smooth":
            mesh = op_smooth(mesh, op)
        elif cmd == "simplify":
            mesh = op_simplify(mesh, op)
        elif cmd == "face_lattice":
            try:
                mesh = op_face_lattice(mesh, op, obj.params)
            except Exception as e:
                warn(f"{obj.name}: face_lattice failed: {e}")
        elif cmd == "skin_edges":
            try:
                mesh = op_skin_edges(mesh, op, obj.params)
            except Exception as e:
                warn(f"{obj.name}: skin_edges failed: {e}")
        elif cmd == "build_glazed_openings":
            try:
                mesh = op_build_glazed_openings(mesh, op, obj.params, obj.meta_lines)
            except Exception as e:
                warn(f"{obj.name}: build_glazed_openings failed: {e}")
        elif cmd == "snap_to_ground":
            mesh = op_snap_to_ground(mesh, op)
        elif cmd == "center_origin":
            mesh = op_center_origin(mesh, op)
        elif cmd:
            warn(f"{obj.name}: unsupported #@post op '{cmd}'")
    obj.mesh = mesh


def execute_scene(scene: Scene) -> Scene:
    scene_objects = {obj.name: obj for obj in scene.objects}
    for obj in scene.objects:
        apply_post_ops(obj, scene_objects)
    return scene


def serialize_scene(scene: Scene) -> str:
    lines: List[str] = []
    lines.extend(scene.header_lines)
    while lines and not lines[-1].strip():
        lines.pop()
    global_index = 1
    first_object = True
    for obj in scene.objects:
        if not first_object:
            lines.append("")
        first_object = False
        lines.append(f"{obj.declaration} {obj.name}")
        lines.extend([line for line in obj.meta_lines if not line.strip().startswith("#@runtime:")])
        for line in obj.raw_nonlive_lines:
            if line.strip() and not line.strip().startswith("#@runtime:"):
                lines.append(line)
        for x, y, z in obj.mesh.vertices:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        group_sets = {
            name: set(unique_indices(indices))
            for name, indices in obj.mesh.named_groups.items()
            if indices
        }
        current_group: Optional[str] = None
        for face in obj.mesh.faces:
            face_group: Optional[str] = None
            if group_sets:
                face_set = set(face)
                for name, indices in group_sets.items():
                    if face_set.issubset(indices):
                        face_group = name
                        break
            if face_group != current_group:
                if face_group is not None:
                    lines.append(f"g {face_group}")
                current_group = face_group
            lines.append("f " + " ".join(str(global_index + i - 1) for i in face))
        global_index += len(obj.mesh.vertices)
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply raw OBJ #@post modifier stack.")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()

    output = args.output or args.input.with_suffix(".post.obj")
    scene = parse_obj(args.input)
    execute_scene(scene)
    output.write_text(serialize_scene(scene), encoding="utf-8")

    print(f"Wrote {output}")
    print(f"Objects: {len(scene.objects)}")
    print(f"Vertices: {sum(len(o.mesh.vertices) for o in scene.objects)}")
    print(f"Faces: {sum(len(o.mesh.faces) for o in scene.objects)}")


if __name__ == "__main__":
    main()
