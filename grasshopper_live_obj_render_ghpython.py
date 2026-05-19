# Spellshape Grasshopper - Live OBJ / Raw OBJ Renderer
# Release date: 2026-05-17
# License: MIT
# Source: https://github.com/StepanKukharskiy/live-obj
#
# Network behavior:
# - No network calls.
# - No telemetry.
# - Reads OBJ/Live OBJ text locally and creates Rhino preview meshes.
#
# Inputs to create:
#   live_obj          str
#   values            list access, item access also works if one value
#   refresh_controls  bool
#   clear_controls    bool
#   controls_below_px int optional, default 170
#
# Outputs to create:
#   meshes
#   controls
#   executed_obj
#   warnings
#   status
#
# Supported:
#   OBJ cache/raw v/f/o mesh parsing
#   #@up: y conversion into Rhino Z-up coordinates
#   #@params
#   #@controls: slider, seed, toggle, choice/value_list
#   #@post:
#     transform position=[x,y,z] rotation=[rx,ry,rz] scale=[sx,sy,sz]
#       optional: pivot=[x,y,z] for scale/rotation pivot in source coordinates
#     mirror axis=x|y|z
#     array count=n offset=[x,y,z] centered=true|false scale=[sx,sy,sz] position=[x,y,z] pivot=[x,y,z]
#       expressions may use i, index, step, count, t, params, sin(), cos(), sqrt(), pi, tau
#     deform position=[x,y,z]
#       expressions may use x, y, z plus normalized u, v, w vertex coordinates
#     symmetrize axis=x|y|z side=positive|negative
#     subdivide level=n
#     smooth iterations=n strength=0.5
#     simplify ratio=0.5
#     snap_to_ground axis=x|y|z
#     center_origin axes=xz|xy|yz|xyz

import ast
import math
import re
import System
import Rhino.Geometry as rg
import Grasshopper
import Grasshopper.Kernel as ghk
import Grasshopper.Kernel.Special as ghks


GENERATED_PREFIX = "spellshape:"
EXPR_FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
}
EXPR_CONSTANTS = {
    "pi": math.pi,
    "tau": math.pi * 2.0,
}


class ControlSpec(object):
    def __init__(self, object_name, kind, key, label, min_v=None, max_v=None, step=None, options=None, value=None):
        self.object_name = object_name or "unnamed"
        self.kind = (kind or "slider").lower()
        self.key = key or ""
        self.label = (label or key or "").replace("_", " ")
        self.min = min_v
        self.max = max_v
        self.step = step
        self.options = options or []
        self.value = value

    @property
    def full_key(self):
        return "%s.%s" % (self.object_name, self.key)

    @property
    def nickname(self):
        return GENERATED_PREFIX + self.full_key

    def display(self):
        return "%s [%s] value=%s min=%s max=%s step=%s" % (
            self.full_key,
            self.kind,
            self.value,
            self.min,
            self.max,
            self.step,
        )


class PostOp(object):
    def __init__(self, cmd, args):
        self.cmd = (cmd or "").lower()
        self.args = args or {}


class Obj(object):
    def __init__(self, name="unnamed", first_vertex_index=1):
        self.name = name
        self.first_vertex_index = first_vertex_index
        self.vertices = []
        self.faces = []
        self.params = {}
        self.controls = []
        self.post_ops = []


class Scene(object):
    def __init__(self):
        self.objects = []
        self.controls = []
        self.params = {}
        self.up = "z"


def split_lines(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def split_top_level(text, separator=","):
    out = []
    buf = []
    depth = 0
    quote = None
    for ch in text or "":
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch in "[({":
            depth += 1
        elif ch in "])}":
            depth = max(0, depth - 1)
        if ch == separator and depth == 0:
            token = "".join(buf).strip()
            if token:
                out.append(token)
            buf = []
            continue
        buf.append(ch)
    token = "".join(buf).strip()
    if token:
        out.append(token)
    return out


def split_top_level_spaces(text):
    out = []
    buf = []
    depth = 0
    quote = None
    for ch in text or "":
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch in "[({":
            depth += 1
        elif ch in "])}":
            depth = max(0, depth - 1)
        if ch.isspace() and depth == 0:
            token = "".join(buf).strip()
            if token:
                out.append(token)
            buf = []
            continue
        buf.append(ch)
    token = "".join(buf).strip()
    if token:
        out.append(token)
    return out


def parse_comma_kvs(text):
    out = {}
    for part in split_top_level(text, ","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def parse_param_kvs(text):
    parts = split_top_level(text, ",")
    if len(parts) <= 1:
        parts = split_top_level_spaces(text)
    out = {}
    for part in parts:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip().strip("\"'")
    return out


def parse_space_kvs(text):
    out = {}
    for token in split_top_level_spaces(text):
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip().strip("\"'")
    return out


def parse_control(object_name, line, params=None):
    parts = split_top_level_spaces(line)
    if not parts:
        return None
    first = parts[0].strip()
    args = parse_space_kvs(" ".join(parts[1:]))
    if "type" in args or "kind" in args:
        kind = (args.get("type") or args.get("kind") or "slider").strip().lower()
        key = args.get("key") or args.get("param") or args.get("name") or first
    elif "=" in first:
        kind = "slider"
        key = args.get("key") or args.get("param") or args.get("name") or first
    else:
        kind = first.lower()
        key = args.get("key") or args.get("param") or args.get("name")
    if not key:
        return None
    options_raw = args.get("options") or args.get("values") or ""
    options = [p.strip() for p in re.split(r"[|,]", options_raw) if p.strip()]
    value = args.get("value") or args.get("default") or args.get("current")
    if value is None and params is not None:
        value = params.get(key.strip())
    return ControlSpec(
        object_name,
        kind,
        key.strip(),
        (args.get("label") or key).strip(),
        args.get("min"),
        args.get("max"),
        args.get("step"),
        options,
        value,
    )


def parse_post(line):
    parts = split_top_level_spaces(line)
    if not parts:
        return PostOp("", {})
    return PostOp(parts[0], parse_space_kvs(" ".join(parts[1:])))


def parse_face_index(token):
    head = token.split("/")[0]
    try:
        return int(head)
    except Exception:
        return 0


def parse_live_obj(text, warn):
    scene = Scene()
    current = None
    block = None
    global_vertex = 0
    seen_object = False

    def flush():
        if current is None:
            return
        if not (current.vertices or current.faces or current.params or current.controls or current.post_ops):
            return
        scene.objects.append(current)
        scene.controls.extend(current.controls)

    for raw in split_lines(text):
        line = raw.strip()
        if not line:
            continue

        m = re.match(r"^o\s+(.+)$", line)
        if m:
            flush()
            current = Obj(m.group(1).strip(), global_vertex + 1)
            block = None
            seen_object = True
            continue

        if current is None and seen_object:
            current = Obj("unnamed", global_vertex + 1)

        if line.startswith("#@"):
            body = line[2:].strip()
            low = body.lower()
            if low.startswith("up:"):
                up = body.split(":", 1)[1].strip().lower()
                if up in ("x", "y", "z"):
                    scene.up = up
                continue
            if low == "controls:":
                block = "controls"
                continue
            if low.startswith("controls:"):
                item = body[len("controls:") :].strip()
                c = parse_control(current.name if current is not None else "scene", item, current.params if current is not None else scene.params)
                if c:
                    if current is None:
                        scene.controls.append(c)
                    else:
                        current.controls.append(c)
                block = "controls"
                continue
            if low == "post:":
                block = "post"
                continue
            if low.startswith("params:"):
                if current is None:
                    scene.params.update(parse_param_kvs(body[len("params:") :]))
                else:
                    current.params.update(parse_param_kvs(body[len("params:") :]))
                block = "params"
                continue
            if body.endswith(":") and not body.startswith("-"):
                block = None
                continue
            if body.startswith("- "):
                item = body[2:].strip()
                if block == "controls":
                    c = parse_control(current.name if current is not None else "scene", item, current.params if current is not None else scene.params)
                    if c:
                        if current is None:
                            scene.controls.append(c)
                        else:
                            current.controls.append(c)
                elif block == "post":
                    op = parse_post(item)
                    if op.cmd:
                        current.post_ops.append(op)
                elif block == "params":
                    if current is None:
                        scene.params.update(parse_param_kvs(item))
                    else:
                        current.params.update(parse_param_kvs(item))
                continue
            if low.startswith("post "):
                op = parse_post(body[len("post ") :])
                if op.cmd:
                    current.post_ops.append(op)
            continue

        if line.startswith("v "):
            if current is None:
                current = Obj("unnamed", global_vertex + 1)
            parts = line.split()
            if len(parts) >= 4:
                try:
                    current.vertices.append(rg.Point3d(float(parts[1]), float(parts[2]), float(parts[3])))
                    global_vertex += 1
                except Exception as e:
                    warn.append("bad vertex on %s: %s" % (current.name, e))
            continue

        if line.startswith("f "):
            if current is None:
                current = Obj("unnamed", global_vertex + 1)
            ids = [parse_face_index(t) for t in line.split()[1:]]
            ids = [i for i in ids if i > 0]
            if len(ids) >= 3:
                current.faces.append(ids)

    flush()
    return scene


def values_to_overrides(ctrls, vals):
    if vals is None:
        vals = []
    elif not isinstance(vals, (list, tuple)):
        vals = [vals]
    out = {}
    for i, c in enumerate(ctrls):
        if i >= len(vals):
            break
        if vals[i] is None:
            continue
        out[c.full_key] = str(vals[i])
    return out


def apply_overrides(scene, overrides):
    for c in scene.controls:
        if c.full_key in overrides:
            scene.params[c.key] = overrides[c.full_key]
    for obj in scene.objects:
        for c in obj.controls:
            if c.full_key in overrides:
                obj.params[c.key] = overrides[c.full_key]


def object_scope(scene, obj):
    scope = dict(scene.params)
    scope.update(obj.params)
    return scope


def _scope_number(name, scope):
    if name in EXPR_CONSTANTS:
        return EXPR_CONSTANTS[name]
    if name not in scope:
        raise ValueError("unknown expression name: %s" % name)
    value = eval_number_or_none(scope[name], scope)
    if value is None:
        raise ValueError("non-numeric expression name: %s" % name)
    return value


def _eval_expr_node(node, scope):
    if isinstance(node, ast.Expression):
        return _eval_expr_node(node.body, scope)
    if isinstance(node, ast.Num):
        return float(node.n)
    if hasattr(ast, "Constant") and isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError("unsupported expression constant")
    if isinstance(node, ast.Name):
        return _scope_number(node.id, scope)
    if isinstance(node, ast.UnaryOp):
        value = _eval_expr_node(node.operand, scope)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("unsupported unary expression")
    if isinstance(node, ast.BinOp):
        left = _eval_expr_node(node.left, scope)
        right = _eval_expr_node(node.right, scope)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left ** right
        raise ValueError("unsupported binary expression")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = EXPR_FUNCTIONS.get(node.func.id)
        if fn is None:
            raise ValueError("unsupported expression function")
        return float(fn(*[_eval_expr_node(arg, scope) for arg in node.args]))
    raise ValueError("unsupported expression")


def eval_number_or_none(raw, scope):
    if raw is None:
        return None
    text = str(raw).strip()
    if text in scope:
        return eval_number_or_none(scope[text], scope)
    if re.search(r"\$\{[^}]+\}", text) or re.search(r"(?<!\[)\{[A-Za-z_][A-Za-z0-9_]*\}", text):
        return None
    try:
        return float(text)
    except Exception:
        pass
    try:
        return float(_eval_expr_node(ast.parse(text, mode="eval"), scope))
    except Exception:
        return None


def eval_number(raw, scope):
    value = eval_number_or_none(raw, scope)
    return 0.0 if value is None else value


def eval_bool(raw, default=False):
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on", "center", "centered"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def control_default_number(ctrl, fallback):
    raw = ctrl.value
    if raw in (None, ""):
        raw = fallback
    try:
        return float(raw)
    except Exception:
        try:
            return float(fallback)
        except Exception:
            return 0.0


def parse_vec3(raw, scope, default):
    if raw is None:
        return rg.Vector3d(*default)
    text = str(raw).strip()
    if text in scope:
        text = str(scope[text]).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    parts = split_top_level(text, ",")
    if len(parts) < 3:
        return rg.Vector3d(*default)
    values = [eval_number_or_none(parts[0], scope), eval_number_or_none(parts[1], scope), eval_number_or_none(parts[2], scope)]
    if any(v is None for v in values):
        return rg.Vector3d(*default)
    return rg.Vector3d(values[0], values[1], values[2])


def source_to_rhino_transform(scene):
    # Rhino is Z-up. Web/raw OBJ files are often Y-up. Convert Y-up source
    # coordinates (x, y, z) to Rhino coordinates (x, -z, y), which is a
    # right-handed +90 degree rotation around X.
    if scene.up == "y":
        return rg.Transform.Rotation(math.radians(90.0), rg.Vector3d.XAxis, rg.Point3d.Origin)
    if scene.up == "x":
        # Defensive support only: X-up source to Rhino Z-up.
        return rg.Transform.Rotation(math.radians(-90.0), rg.Vector3d.YAxis, rg.Point3d.Origin)
    return rg.Transform.Identity


def rhino_to_source_transform(scene):
    if scene.up == "y":
        return rg.Transform.Rotation(math.radians(-90.0), rg.Vector3d.XAxis, rg.Point3d.Origin)
    if scene.up == "x":
        return rg.Transform.Rotation(math.radians(90.0), rg.Vector3d.YAxis, rg.Point3d.Origin)
    return rg.Transform.Identity


def source_to_rhino_axis(axis, scene):
    axis = (axis or "z").lower()
    if scene.up == "y":
        return {"x": "x", "y": "z", "z": "y"}.get(axis, axis)
    if scene.up == "x":
        return {"x": "z", "y": "y", "z": "x"}.get(axis, axis)
    return axis


def build_mesh(obj, warn, scene):
    if not obj.vertices or not obj.faces:
        return None
    source_to_rhino = source_to_rhino_transform(scene)
    mesh = rg.Mesh()
    for p in obj.vertices:
        p = rg.Point3d(p)
        p.Transform(source_to_rhino)
        mesh.Vertices.Add(p)
    for f in obj.faces:
        local = [i - obj.first_vertex_index for i in f]
        if any(i < 0 or i >= len(obj.vertices) for i in local):
            warn.append("skipped out-of-range face on %s" % obj.name)
            continue
        if len(local) == 3:
            mesh.Faces.AddFace(local[0], local[1], local[2])
        elif len(local) == 4:
            mesh.Faces.AddFace(local[0], local[1], local[2], local[3])
        else:
            for i in range(1, len(local) - 1):
                mesh.Faces.AddFace(local[0], local[i], local[i + 1])
    if mesh.Faces.Count == 0:
        return None
    mesh.Normals.ComputeNormals()
    mesh.Compact()
    return mesh


def get_arg(op, key, fallback):
    return op.args.get(key, fallback)


def sandwich_source_xform(source_xform, scene):
    if scene.up == "z":
        return source_xform
    return source_to_rhino_transform(scene) * source_xform * rhino_to_source_transform(scene)


def source_mirror_transform(axis):
    axis = (axis or "x").lower()
    plane = rg.Plane.WorldYZ if axis == "x" else rg.Plane.WorldZX if axis == "y" else rg.Plane.WorldXY
    return rg.Transform.Mirror(plane)


def face_indices(face):
    if face.IsTriangle:
        return [face.A, face.B, face.C]
    return [face.A, face.B, face.C, face.D]


def add_face(mesh, ids):
    if len(ids) == 3:
        mesh.Faces.AddFace(ids[0], ids[1], ids[2])
    elif len(ids) == 4:
        mesh.Faces.AddFace(ids[0], ids[1], ids[2], ids[3])


def face_centroid(mesh, face):
    ids = face_indices(face)
    if not ids:
        return rg.Point3d.Origin
    x = y = z = 0.0
    for idx in ids:
        p = mesh.Vertices[idx]
        x += p.X
        y += p.Y
        z += p.Z
    n = float(len(ids))
    return rg.Point3d(x / n, y / n, z / n)


def axis_value(point, axis):
    if axis == "x":
        return point.X
    if axis == "y":
        return point.Y
    return point.Z


def compact_mesh_faces(mesh, face_ids):
    out = rg.Mesh()
    used = {}
    for face_id in face_ids:
        face = mesh.Faces[face_id]
        remapped = []
        for idx in face_indices(face):
            if idx not in used:
                p = mesh.Vertices[idx]
                used[idx] = out.Vertices.Add(p.X, p.Y, p.Z)
            remapped.append(used[idx])
        add_face(out, remapped)
    out.Normals.ComputeNormals()
    out.Compact()
    return out


def duplicate_mirrored(mesh, axis, scene):
    copy = mesh.DuplicateMesh()
    copy.Transform(sandwich_source_xform(source_mirror_transform(axis), scene))
    return copy


def apply_symmetrize(mesh, op, scene, warn, obj_name):
    source_axis = get_arg(op, "axis", "x").lower()
    rhino_axis = source_to_rhino_axis(source_axis, scene)
    side = get_arg(op, "side", "positive").lower()
    sign = -1.0 if side in ("negative", "minus", "-") else 1.0
    try:
        tol = abs(eval_number(get_arg(op, "tolerance", "0.000001"), dict(scene.params)))
    except Exception:
        tol = 0.000001
    selected = []
    for i in range(mesh.Faces.Count):
        c = face_centroid(mesh, mesh.Faces[i])
        if sign * axis_value(c, rhino_axis) >= -tol:
            selected.append(i)
    if not selected:
        warn.append("symmetrize found no faces on requested side for %s; used mirror fallback" % obj_name)
        mesh.Append(duplicate_mirrored(mesh, source_axis, scene))
        return mesh
    half = compact_mesh_faces(mesh, selected)
    half.Append(duplicate_mirrored(half, source_axis, scene))
    return half


def apply_subdivide(mesh, op, scope):
    try:
        level = int(round(eval_number(get_arg(op, "level", "1"), scope)))
    except Exception:
        level = 1
    level = max(0, min(3, level))
    out = mesh.DuplicateMesh()
    for _ in range(level):
        next_mesh = rg.Mesh()
        for v in out.Vertices:
            next_mesh.Vertices.Add(v.X, v.Y, v.Z)
        for face in out.Faces:
            ids = face_indices(face)
            pts = [out.Vertices[i] for i in ids]
            x = sum(p.X for p in pts) / float(len(pts))
            y = sum(p.Y for p in pts) / float(len(pts))
            z = sum(p.Z for p in pts) / float(len(pts))
            center_idx = next_mesh.Vertices.Add(x, y, z)
            for i, a in enumerate(ids):
                b = ids[(i + 1) % len(ids)]
                next_mesh.Faces.AddFace(a, b, center_idx)
        next_mesh.Normals.ComputeNormals()
        next_mesh.Compact()
        out = next_mesh
    return out


def vertex_neighbors(mesh):
    neighbors = [set() for _ in range(mesh.Vertices.Count)]
    for face in mesh.Faces:
        ids = face_indices(face)
        for i, idx in enumerate(ids):
            prev_idx = ids[i - 1]
            next_idx = ids[(i + 1) % len(ids)]
            neighbors[idx].add(prev_idx)
            neighbors[idx].add(next_idx)
    return neighbors


def apply_smooth(mesh, op, scope):
    try:
        iterations = int(round(eval_number(get_arg(op, "iterations", get_arg(op, "level", "1")), scope)))
    except Exception:
        iterations = 1
    try:
        strength = eval_number(get_arg(op, "strength", "0.5"), scope)
    except Exception:
        strength = 0.5
    iterations = max(0, min(20, iterations))
    strength = max(0.0, min(1.0, strength))
    out = mesh.DuplicateMesh()
    for _ in range(iterations):
        neighbors = vertex_neighbors(out)
        points = []
        for i, v in enumerate(out.Vertices):
            ns = list(neighbors[i])
            if not ns:
                points.append(rg.Point3d(v.X, v.Y, v.Z))
                continue
            ax = sum(out.Vertices[n].X for n in ns) / float(len(ns))
            ay = sum(out.Vertices[n].Y for n in ns) / float(len(ns))
            az = sum(out.Vertices[n].Z for n in ns) / float(len(ns))
            points.append(rg.Point3d(
                v.X * (1.0 - strength) + ax * strength,
                v.Y * (1.0 - strength) + ay * strength,
                v.Z * (1.0 - strength) + az * strength,
            ))
        next_mesh = rg.Mesh()
        for p in points:
            next_mesh.Vertices.Add(p)
        for face in out.Faces:
            add_face(next_mesh, face_indices(face))
        next_mesh.Normals.ComputeNormals()
        next_mesh.Compact()
        out = next_mesh
    return out


def apply_simplify(mesh, op, scope):
    try:
        ratio = eval_number(get_arg(op, "ratio", "1"), scope)
    except Exception:
        ratio = 1.0
    ratio = max(0.05, min(1.0, ratio))
    if ratio >= 0.999 or mesh.Faces.Count == 0:
        return mesh
    target = max(1, int(math.ceil(mesh.Faces.Count * ratio)))
    step = max(1, int(round(float(mesh.Faces.Count) / float(target))))
    selected = [i for i in range(mesh.Faces.Count) if i % step == 0][:target]
    return compact_mesh_faces(mesh, selected)


def apply_deform(mesh, op, scope, scene):
    expr = get_arg(op, "position", get_arg(op, "xyz", "[x,y,z]"))
    out = mesh.DuplicateMesh()
    to_source = rhino_to_source_transform(scene)
    to_rhino = source_to_rhino_transform(scene)
    source_points = []
    for i in range(out.Vertices.Count):
        p = rg.Point3d(out.Vertices[i])
        p.Transform(to_source)
        source_points.append(p)
    if not source_points:
        return out

    min_x = min(p.X for p in source_points)
    min_y = min(p.Y for p in source_points)
    min_z = min(p.Z for p in source_points)
    max_x = max(p.X for p in source_points)
    max_y = max(p.Y for p in source_points)
    max_z = max(p.Z for p in source_points)
    span_x = max(max_x - min_x, 0.000001)
    span_y = max(max_y - min_y, 0.000001)
    span_z = max(max_z - min_z, 0.000001)
    count = max(1, len(source_points))

    for i, p in enumerate(source_points):
        local_scope = dict(scope)
        local_scope.update({
            "x": p.X,
            "y": p.Y,
            "z": p.Z,
            "u": (p.X - min_x) / span_x,
            "v": (p.Y - min_y) / span_y,
            "w": (p.Z - min_z) / span_z,
            "i": float(i),
            "index": float(i),
            "vertex_count": float(count),
            "count": float(count),
            "t": float(i) / float(max(1, count - 1)),
        })
        moved = parse_vec3(expr, local_scope, (p.X, p.Y, p.Z))
        rp = rg.Point3d(moved.X, moved.Y, moved.Z)
        rp.Transform(to_rhino)
        out.Vertices.SetVertex(i, rp.X, rp.Y, rp.Z)

    out.Normals.ComputeNormals()
    out.Compact()
    return out


def apply_post_ops(mesh, obj, warn, scene):
    scope = object_scope(scene, obj)
    for op in obj.post_ops:
        if op.cmd == "transform":
            pos = parse_vec3(get_arg(op, "position", "[0,0,0]"), scope, (0, 0, 0))
            rot = parse_vec3(get_arg(op, "rotation", "[0,0,0]"), scope, (0, 0, 0))
            scale = parse_vec3(get_arg(op, "scale", "[1,1,1]"), scope, (1, 1, 1))
            pivot = parse_vec3(get_arg(op, "pivot", "[0,0,0]"), scope, (0, 0, 0))
            xform = rg.Transform.Scale(rg.Plane.WorldXY, scale.X, scale.Y, scale.Z)
            xform = rg.Transform.Rotation(math.radians(rot.X), rg.Vector3d.XAxis, rg.Point3d.Origin) * xform
            xform = rg.Transform.Rotation(math.radians(rot.Y), rg.Vector3d.YAxis, rg.Point3d.Origin) * xform
            xform = rg.Transform.Rotation(math.radians(rot.Z), rg.Vector3d.ZAxis, rg.Point3d.Origin) * xform
            if pivot.Length > 0:
                xform = rg.Transform.Translation(pivot) * xform * rg.Transform.Translation(-pivot)
            xform = rg.Transform.Translation(pos) * xform
            mesh.Transform(sandwich_source_xform(xform, scene))
        elif op.cmd == "mirror":
            axis = get_arg(op, "axis", "x").lower()
            mesh.Append(duplicate_mirrored(mesh, axis, scene))
        elif op.cmd == "symmetrize":
            mesh = apply_symmetrize(mesh, op, scene, warn, obj.name)
        elif op.cmd == "array":
            count = max(1, int(round(eval_number(get_arg(op, "count", "1"), scope))))
            centered = eval_bool(get_arg(op, "centered", get_arg(op, "center", None)), False)
            base = mesh.DuplicateMesh()
            combined = rg.Mesh()
            for i in range(count):
                step = float(i)
                if centered and count > 1:
                    step = float(i) - 0.5 * float(count - 1)
                local_scope = dict(scope)
                local_scope.update({
                    "i": float(i),
                    "index": float(i),
                    "step": step,
                    "count": float(count),
                    "t": float(i) / float(max(1, count - 1)),
                })
                offset = parse_vec3(get_arg(op, "offset", "[1,0,0]"), local_scope, (1, 0, 0))
                scale = parse_vec3(get_arg(op, "scale", "[1,1,1]"), local_scope, (1, 1, 1))
                position = parse_vec3(get_arg(op, "position", "[0,0,0]"), local_scope, (0, 0, 0))
                pivot = parse_vec3(get_arg(op, "pivot", "[0,0,0]"), local_scope, (0, 0, 0))
                translation = offset * step + position
                xform = rg.Transform.Scale(rg.Plane.WorldXY, scale.X, scale.Y, scale.Z)
                if pivot.Length > 0:
                    xform = rg.Transform.Translation(pivot) * xform * rg.Transform.Translation(-pivot)
                xform = rg.Transform.Translation(translation) * xform
                copy = base.DuplicateMesh()
                copy.Transform(sandwich_source_xform(xform, scene))
                combined.Append(copy)
            mesh = combined
        elif op.cmd == "deform":
            mesh = apply_deform(mesh, op, scope, scene)
        elif op.cmd == "subdivide":
            mesh = apply_subdivide(mesh, op, scope)
        elif op.cmd == "smooth":
            if "level" in op.args and "iterations" not in op.args:
                warn.append("accepted smooth level= as iterations= on %s; generator should emit iterations=" % obj.name)
            mesh = apply_smooth(mesh, op, scope)
        elif op.cmd == "simplify":
            mesh = apply_simplify(mesh, op, scope)
        elif op.cmd == "snap_to_ground":
            axis = source_to_rhino_axis(get_arg(op, "axis", scene.up), scene)
            bb = mesh.GetBoundingBox(True)
            if axis == "x":
                move = rg.Vector3d(-bb.Min.X, 0, 0)
            elif axis == "y":
                move = rg.Vector3d(0, -bb.Min.Y, 0)
            else:
                move = rg.Vector3d(0, 0, -bb.Min.Z)
            mesh.Transform(rg.Transform.Translation(move))
        elif op.cmd == "center_origin":
            source_axes = get_arg(op, "axes", "xyz").lower()
            axes = "".join(sorted(set(source_to_rhino_axis(a, scene) for a in source_axes if a in "xyz")))
            bb = mesh.GetBoundingBox(True)
            c = bb.Center
            mesh.Transform(rg.Transform.Translation(
                -c.X if "x" in axes else 0,
                -c.Y if "y" in axes else 0,
                -c.Z if "z" in axes else 0,
            ))
        elif op.cmd in ("material", "tag"):
            pass
        else:
            warn.append("unsupported #@post op on %s: %s" % (obj.name, op.cmd))
    mesh.Normals.ComputeNormals()
    mesh.Compact()
    return mesh


def serialize_meshes(mesh_list):
    lines = []
    offset = 1
    for mi, mesh in enumerate(mesh_list):
        lines.append("o mesh_%d" % mi)
        for v in mesh.Vertices:
            lines.append("v %.8g %.8g %.8g" % (v.X, v.Y, v.Z))
        for f in mesh.Faces:
            if f.IsTriangle:
                lines.append("f %d %d %d" % (f.A + offset, f.B + offset, f.C + offset))
            else:
                lines.append("f %d %d %d %d" % (f.A + offset, f.B + offset, f.C + offset, f.D + offset))
        offset += mesh.Vertices.Count
    return "\n".join(lines)


def gh_doc():
    try:
        return ghenv.Component.OnPingDocument()
    except Exception:
        return None


def remove_generated_controls():
    doc = gh_doc()
    if doc is None:
        return
    mine = []
    for obj in doc.Objects:
        if getattr(obj, "NickName", "").startswith(GENERATED_PREFIX):
            mine.append(obj)
    for obj in mine:
        doc.RemoveObject(obj, False)


def controls_need_refresh(ctrls):
    try:
        input_param = ghenv.Component.Params.Input[1]
    except Exception:
        return False
    sources = list(input_param.Sources)
    if len(sources) != len(ctrls):
        return True
    for source, ctrl in zip(sources, ctrls):
        if source.NickName != ctrl.nickname:
            return True
    return False


def create_control_object(ctrl):
    kind = ctrl.kind
    if kind in ("toggle", "bool", "boolean"):
        obj = ghks.GH_BooleanToggle()
        obj.Name = ctrl.label
        obj.NickName = ctrl.nickname
        obj.Value = eval_bool(ctrl.value, False)
        obj.CreateAttributes()
        return obj

    if kind in ("choice", "value_list", "select", "dropdown"):
        obj = ghks.GH_ValueList()
        obj.Name = ctrl.label
        obj.NickName = ctrl.nickname
        obj.ListItems.Clear()
        opts = ctrl.options or ["default"]
        for opt in opts:
            obj.ListItems.Add(ghks.GH_ValueListItem(opt, '"%s"' % opt))
        obj.CreateAttributes()
        return obj

    obj = ghks.GH_NumberSlider()
    obj.Name = ctrl.label
    obj.NickName = ctrl.nickname
    min_v = float(ctrl.min) if ctrl.min not in (None, "") else 0.0
    max_v = float(ctrl.max) if ctrl.max not in (None, "") else 1.0
    step_v = abs(float(ctrl.step)) if ctrl.step not in (None, "") else 0.01
    value_v = control_default_number(ctrl, min_v)
    value_v = max(min_v, min(max_v, value_v))
    obj.Slider.Minimum = System.Decimal(min_v)
    obj.Slider.Maximum = System.Decimal(max_v)
    obj.Slider.DecimalPlaces = 0 if step_v >= 1 else 1 if step_v >= 0.1 else 2 if step_v >= 0.01 else 3
    obj.SetSliderValue(System.Decimal(value_v))
    obj.CreateAttributes()
    return obj


def create_or_refresh_controls(ctrls):
    doc = gh_doc()
    if doc is None:
        return
    try:
        input_param = ghenv.Component.Params.Input[1]
    except Exception:
        return

    input_param.RemoveAllSources()
    remove_generated_controls()

    pivot = ghenv.Component.Attributes.Pivot
    try:
        below_px = int(controls_below_px)
    except Exception:
        below_px = 170
    below_px = max(80, min(600, below_px))
    x = pivot.X - 220
    y = pivot.Y + below_px

    created = []
    for i, ctrl in enumerate(ctrls):
        obj = create_control_object(ctrl)
        obj.Attributes.Pivot = System.Drawing.PointF(x, y + i * 32)
        doc.AddObject(obj, False)
        created.append(obj)
        try:
            input_param.AddSource(obj)
        except Exception:
            pass

    ghenv.Component.Params.OnParametersChanged()
    doc.ScheduleSolution(10, lambda d: ghenv.Component.ExpireSolution(False))


# Main execution.
warnings = []
scene = parse_live_obj(live_obj or "", warnings)

if clear_controls:
    remove_generated_controls()

if scene.controls and (refresh_controls or controls_need_refresh(scene.controls)):
    create_or_refresh_controls(scene.controls)

overrides = values_to_overrides(scene.controls, values)
apply_overrides(scene, overrides)

meshes = []
for obj in scene.objects:
    mesh = build_mesh(obj, warnings, scene)
    if mesh is None:
        continue
    mesh = apply_post_ops(mesh, obj, warnings, scene)
    meshes.append(mesh)

controls = [c.display() for c in scene.controls]
executed_obj = serialize_meshes(meshes)
status = "objects=%d controls=%d meshes=%d warnings=%d up=%s input_chars=%d" % (
    len(scene.objects),
    len(scene.controls),
    len(meshes),
    len(warnings),
    scene.up,
    len(live_obj or ""),
)

if len(scene.objects) == 0 and (live_obj or "").strip():
    warnings.append("No OBJ objects parsed. Input starts with: %r" % ((live_obj or "").strip()[:240],))
elif len(meshes) == 0 and len(scene.objects) > 0:
    summary = []
    for obj in scene.objects[:8]:
        summary.append("%s: v=%d f=%d" % (obj.name, len(obj.vertices), len(obj.faces)))
    warnings.append("Parsed objects but no renderable meshes: " + "; ".join(summary))

try:
    ghenv.Component.Message = status
except Exception:
    pass
