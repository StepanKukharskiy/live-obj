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
