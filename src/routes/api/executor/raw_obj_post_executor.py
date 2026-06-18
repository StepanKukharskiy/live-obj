#!/usr/bin/env python3
"""
Raw OBJ Post Executor

This executor is intentionally separate from the Live OBJ executor. It treats
raw LLM-authored OBJ vertices/faces as the base geometry, then applies a small
`#@post:` modifier stack on top.

Supported post ops:
    transform position=[x,y,z] rotation=[rx,ry,rz] scale=[sx,sy,sz] pivot=[x,y,z]
    symmetrize axis=x|y|z side=positive|negative
    mirror axis=x|y|z
    array count=n offset=[x,y,z] centered=true|false scale=[sx,sy,sz] position=[x,y,z] pivot=[x,y,z]
    deform position=[x,y,z]
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

    def copy(self) -> "Mesh":
        return Mesh(vertices=list(self.vertices), faces=[list(f) for f in self.faces])

    def extend(self, other: "Mesh") -> None:
        offset = len(self.vertices)
        self.vertices.extend(other.vertices)
        self.faces.extend([[i + offset for i in f] for f in other.faces])


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
    "transform": {"position", "rotation", "scale", "pivot"},
    "symmetrize": {"axis", "side", "tolerance"},
    "mirror": {"axis"},
    "array": {"count", "offset", "centered", "center", "scale", "position", "pivot"},
    "deform": {"position", "expr", "xyz"},
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

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("o "):
            declaration, name = stripped.split(maxsplit=1)
            current = RawObject(name=name.strip(), declaration=declaration)
            scene.objects.append(current)
            continue
        if current is None:
            scene.header_lines.append(line)
            continue
        if stripped.startswith("g "):
            current.raw_nonlive_lines.append(line)
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


def rotate_point(vertex: Vec3, rotation_degrees: Vec3) -> Vec3:
    x, y, z = vertex
    rx, ry, rz = [math.radians(a) for a in rotation_degrees]
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return (x, y, z)


def op_transform(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    position = parse_vec3(op.get("position", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    rotation = parse_vec3(op.get("rotation", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    scale = parse_vec3(op.get("scale", [1, 1, 1]), params, (1.0, 1.0, 1.0))
    pivot = parse_vec3(op.get("pivot", [0, 0, 0]), params, (0.0, 0.0, 0.0))
    vertices: List[Vec3] = []
    for x, y, z in mesh.vertices:
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
    return Mesh(vertices, [list(face) for face in mesh.faces])


def op_deform(mesh: Mesh, op: Dict[str, Any], params: Dict[str, Any]) -> Mesh:
    expr = op.get("position", op.get("expr", op.get("xyz", ["x", "y", "z"])))
    min_corner, max_corner = mesh_bbox(mesh)
    spans = [
        max(max_corner[0] - min_corner[0], 1e-9),
        max(max_corner[1] - min_corner[1], 1e-9),
        max(max_corner[2] - min_corner[2], 1e-9),
    ]
    vertices: List[Vec3] = []
    vertex_count = max(1, len(mesh.vertices))
    for idx, (x, y, z) in enumerate(mesh.vertices):
        scope = {
            "x": x,
            "y": y,
            "z": z,
            "u": (x - min_corner[0]) / spans[0],
            "v": (y - min_corner[1]) / spans[1],
            "w": (z - min_corner[2]) / spans[2],
            "i": float(idx),
            "index": float(idx),
            "vertex_count": float(vertex_count),
            "t": float(idx / max(1, vertex_count - 1)),
        }
        vertices.append(parse_vec3(expr, params, (x, y, z), scope))
    return Mesh(vertices, [list(face) for face in mesh.faces])


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
    return Mesh(vertices, [list(face) for face in mesh.faces])


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
    return Mesh(vertices, [list(face) for face in mesh.faces])


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


def apply_post_ops(obj: RawObject) -> None:
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
    for obj in scene.objects:
        apply_post_ops(obj)
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
        for face in obj.mesh.faces:
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
