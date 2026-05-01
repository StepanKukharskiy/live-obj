# Live OBJ Executor for Grasshopper (GHPython)
# Paste into a GHPython component.

import ast
import math
import os
import random
import re
import Rhino.Geometry as rg

# Set to True for stricter Live OBJ op compatibility diagnostics.
STRICT_COMPAT = True


class ObjObject(object):
    def __init__(self, name="unnamed"):
        self.name = name
        self.meta = {}
        self.vertices = []
        self.faces = []
        self.ops = []


def _parse_scalar(value):
    value = value.strip()
    if not value:
        return ""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if any(c in value for c in ".eE"):
            return float(value)
        return int(value)
    except Exception:
        pass

    if value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except Exception:
            return value
    return value


def _split_top_level_commas(text):
    parts, cur = [], []
    depth = 0
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            token = "".join(cur).strip()
            if token:
                parts.append(token)
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts




def _split_top_level_spaces(s):
    parts = []
    cur = []
    depth = 0
    for ch in str(s):
        if ch in "[({":
            depth += 1
        elif ch in "]) }".replace(" ", ""):
            depth = max(0, depth - 1)
        if ch.isspace() and depth == 0:
            token = "".join(cur).strip()
            if token:
                parts.append(token)
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts

def _parse_params(raw):
    params = {}
    for part in _split_top_level_commas(raw):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        key = k.strip()
        val = _parse_scalar(v)
        if key in params and (val == "" or val is None):
            continue
        params[key] = val
    return params


def parse_live_obj(text):
    objects = []
    current = ObjObject()
    current_block = None
    scene_meta = {}  # Store scene-level metadata like units

    def push_current():
        if current.vertices or current.faces or current.meta or current.name != "unnamed":
            objects.append(current)

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("o "):
            push_current()
            current = ObjObject(name=s[2:].strip() or "unnamed")
            current_block = None
            # Apply scene-level metadata to new object
            for key, value in scene_meta.items():
                if key not in current.meta:
                    current.meta[key] = value
            continue

        if s.startswith("#@"):
            payload = s[2:].strip()
            if payload.startswith("- "):
                item = payload[2:].strip()
                if current_block == "anchors":
                    if "=" in item:
                        k, v = item.split("=", 1)
                        anchors = current.meta.get("anchors")
                        if not isinstance(anchors, dict):
                            anchors = {}
                        anchors[k.strip()] = _parse_scalar(v.strip())
                        current.meta["anchors"] = anchors
                elif current_block == "sdf":
                    sdf_ops = current.meta.get("sdf_ops")
                    if not isinstance(sdf_ops, list):
                        sdf_ops = []
                    sdf_ops.append(_parse_op_line(item))
                    current.meta["sdf_ops"] = sdf_ops
                else:
                    current.ops.append(_parse_op_line(item))
                continue
            if ":" in payload:
                key, value = payload.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "params":
                    current.meta["params"] = _parse_params(value)
                    current_block = None
                elif key == "ops":
                    current.meta["ops_block"] = True
                    current_block = "ops"
                elif key == "anchors":
                    current.meta["anchors"] = {}
                    current_block = "anchors"
                elif key == "sdf":
                    current.meta["sdf_ops"] = []
                    current_block = "sdf"
                else:
                    # Store scene-level metadata (units, up, etc.) in scene_meta when on initial object
                    if current.name == "unnamed" and not current.vertices and not current.faces:
                        scene_meta[key] = _parse_scalar(value)
                    else:
                        current.meta[key] = _parse_scalar(value)
                    current_block = None
            continue

        if s.startswith("v "):
            parts = s.split()
            if len(parts) >= 4:
                current.vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            continue

        if s.startswith("f "):
            idxs = []
            for token in s.split()[1:]:
                base = token.split("/")[0]
                if base:
                    idxs.append(int(base))
            if len(idxs) >= 3:
                current.faces.append(idxs)

    push_current()
    return objects


def _to_pt(v):
    return rg.Point3d(float(v[0]), float(v[1]), float(v[2]))


def _parse_op_line(line):
    parts = line.split(None, 1)
    if not parts:
        return {}
    op = {"op": parts[0].strip().lower()}
    if len(parts) > 1:
        rest = parts[1].strip()
        parsed = {}
        positional = []
        for token in _split_top_level_spaces(rest):
            if "=" not in token:
                # Preserve positional args so handlers (e.g. sdf union) can
                # accept `union shaft cap_top` in addition to `ids=shaft,cap_top`.
                positional.append(token.strip())
                continue
            k, v = token.split("=", 1)
            key = k.strip()
            val = _parse_scalar(v)
            if key in parsed and (val == "" or val is None):
                continue
            parsed[key] = val
        if not parsed and "=" in rest:
            parsed = _parse_params(rest)
        op.update(parsed)
        if positional:
            op["_args"] = positional
    return op


def build_rhino_mesh(obj, warnings=None):
    m = rg.Mesh()
    for v in obj.vertices:
        m.Vertices.Add(*v)

    face_indices = [idx for f in obj.faces for idx in f if isinstance(idx, int)]
    base_index = min(face_indices) if face_indices else 1

    for f in obj.faces:
        loc = [i - base_index for i in f]
        if len(loc) == 3:
            m.Faces.AddFace(loc[0], loc[1], loc[2])
        elif len(loc) == 4:
            m.Faces.AddFace(loc[0], loc[1], loc[2], loc[3])
        elif len(loc) > 4:
            for i in range(1, len(loc) - 1):
                m.Faces.AddFace(loc[0], loc[i], loc[i + 1])

    # Live OBJ `v`/`f` caches are sometimes written with per-face duplicated
    # vertices (e.g. voxel-shell meshers that emit 4 fresh verts per quad).
    # Weld defensively so the rendered mesh isn't a heap of isolated tiles.
    try:
        m.Vertices.CombineIdentical(True, True)
    except Exception:
        pass
    m = _weld_mesh_by_tolerance(m, tol=1e-5, warnings=warnings, label="obj_cache")

    m.Normals.ComputeNormals()
    m.Compact()
    return m


def _vec3(params, key, default):
    raw = params.get(key, default)
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        return float(raw[0]), float(raw[1]), float(raw[2])
    return default


# `anchor(assembly.anchor_id)` references resolved at orchestration time.
# Populated by `resolve_all_anchors`; keyed as `(assembly_name, anchor_id)`.
ANCHOR_MAP = {}

_ANCHOR_CALL_RE = re.compile(r"anchor\(\s*([A-Za-z_][\w]*)\s*\.\s*([A-Za-z_][\w]*)\s*\)")


def _substitute_anchors(expr, anchor_map=None):
    """Rewrite `anchor(asm.id)` calls into bracketed vec3 literals so the safe
    arithmetic evaluator can consume them. Unresolvable references are left
    alone so the caller sees the original expression and can degrade gracefully.
    """
    if not isinstance(expr, str):
        return expr
    if "anchor(" not in expr:
        return expr
    src = anchor_map if anchor_map is not None else ANCHOR_MAP

    def _sub(match):
        key = (match.group(1), match.group(2))
        vec = src.get(key)
        if not (isinstance(vec, (list, tuple)) and len(vec) >= 3):
            return match.group(0)
        return "[%r, %r, %r]" % (float(vec[0]), float(vec[1]), float(vec[2]))

    return _ANCHOR_CALL_RE.sub(_sub, expr)


def _safe_eval_expr(expr, scope):
    expr_str = _substitute_anchors(expr)
    try:
        node = ast.parse(str(expr_str), mode="eval")
    except Exception:
        return expr
    allowed = [
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
        ast.Pow, ast.USub, ast.UAdd, ast.Load, ast.Num, ast.Name, ast.Tuple, ast.List
    ]
    ast_constant = getattr(ast, "Constant", None)
    if ast_constant is not None:
        allowed.append(ast_constant)
    allowed = tuple(allowed)
    for n in ast.walk(node):
        if not isinstance(n, allowed):
            return expr
        if isinstance(n, ast.Name) and n.id not in scope:
            return expr
    try:
        return eval(compile(node, "<expr>", "eval"), {"__builtins__": {}}, scope)
    except Exception:
        return expr


def _resolve_scalar(v, scope):
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, str):
        if v in scope:
            return scope[v]
        r = _safe_eval_expr(v, scope)
        return r
    return v


def resolve_all_anchors(objs, warnings):
    """Walk every object with `#@anchors` entries, evaluate them against the
    object's own resolved params, and stash the results both on the object
    (`meta['anchors']`) and in the module-level `ANCHOR_MAP` so any
    `anchor(asm.id)` reference elsewhere in the scene resolves to a vec3.
    """
    global ANCHOR_MAP
    ANCHOR_MAP = {}
    for obj in objs:
        raw_anchors = obj.meta.get("anchors") or {}
        if not isinstance(raw_anchors, dict) or not raw_anchors:
            continue
        # Build the local scope from the object's own params (which may also
        # contain expressions). Anchors don't reference other anchors, so this
        # one-pass scope is sufficient.
        scope = {}
        for k, v in _dict_items_safe(obj.meta.get("params") or {}):
            scope[k] = _resolve_value(v, scope)
        resolved = {}
        for aname, aval in _dict_items_safe(raw_anchors):
            try:
                vec = _resolve_value(aval, scope)
            except Exception as ex:
                warnings.append("anchor %r on '%s' failed: %s" % (aname, obj.name, ex))
                continue
            if isinstance(vec, (list, tuple)) and len(vec) >= 3:
                triple = (float(vec[0]), float(vec[1]), float(vec[2]))
                resolved[aname] = triple
                ANCHOR_MAP[(obj.name, aname)] = triple
            else:
                warnings.append(
                    "anchor %r on '%s' must resolve to a 3-vector, got %r" % (aname, obj.name, vec)
                )
        obj.meta["anchors"] = resolved


def _resolve_dict_strings(d, scope):
    """In-place: replace any string values inside `d` with their resolved
    counterparts using `scope`. Used for SDF-op dicts and top-level op dicts
    where param values can contain `anchor(...)` references.
    """
    if not isinstance(d, dict):
        return
    for k in list(d.keys()):
        v = d[k]
        if isinstance(v, str):
            d[k] = _resolve_value(v, scope)
        elif isinstance(v, list):
            d[k] = [_resolve_value(x, scope) if isinstance(x, str) else x for x in v]


def _resolve_value(v, scope):
    if isinstance(v, list):
        return [_resolve_value(x, scope) for x in v]
    if isinstance(v, tuple):
        return tuple(_resolve_value(x, scope) for x in v)
    return _resolve_scalar(v, scope)




def _parse_list_value(value_str):
    """Parse a bracketed list value like '[2,1,0.1]' into a Python list."""
    if not isinstance(value_str, str):
        return value_str
    value_str = value_str.strip()
    if value_str.startswith("[") and value_str.endswith("]"):
        inner = value_str[1:-1].strip()
        if not inner:
            return []
        try:
            # Try to evaluate as a Python list literal
            import ast
            return ast.literal_eval(value_str)
        except Exception:
            # Fallback: split by commas and convert to floats
            parts = [p.strip() for p in inner.split(",")]
            result = []
            for p in parts:
                try:
                    result.append(float(p))
                except ValueError:
                    result.append(p)
            return result
    return value_str


def _parse_transform(transform_str):
    """Parse a transform string like 'position=[0,0,0.5]' into a dict."""
    if not isinstance(transform_str, str):
        return transform_str
    if "=" not in transform_str:
        return {}
    result = {}
    parts = []
    current = ""
    bracket_depth = 0
    for char in transform_str:
        if char in "[]" and (char == "[" or bracket_depth > 0):
            bracket_depth += 1 if char == "[" else -1
            current += char
        elif char == "," and bracket_depth == 0:
            if current:
                parts.append(current)
                current = ""
        else:
            current += char
    if current:
        parts.append(current)
    
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            result[key.strip()] = _parse_list_value(value.strip())
    return result


def _parse_params_string(params_str):
    """Parse space-separated key=value pairs from a string into a dict."""
    if not isinstance(params_str, str):
        return params_str
    result = {}
    # Split by spaces but preserve bracketed expressions
    parts = []
    current = ""
    bracket_depth = 0
    for char in params_str:
        if char in "[]" and (char == "[" or bracket_depth > 0):
            bracket_depth += 1 if char == "[" else -1
            current += char
        elif char == " " and bracket_depth == 0:
            if current:
                parts.append(current)
                current = ""
        else:
            current += char
    if current:
        parts.append(current)
    
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            result[key.strip()] = _parse_list_value(value.strip())
    return result, parts


def _dict_items_safe(d):
    if not d:
        return []
    try:
        return list(d.items())
    except Exception:
        pass
    out = []
    try:
        keys = list(d.keys())
    except Exception:
        return out
    for k in keys:
        try:
            out.append((k, d[k]))
        except Exception:
            try:
                out.append((k, d.get(k)))
            except Exception:
                pass
    return out

def _build_scope_for_object(obj, assembly_params):
    scope = {}
    parent = str(obj.meta.get("parent", "")).strip()
    if parent and parent in assembly_params:
        scope.update(assembly_params[parent])
    if isinstance(obj.meta.get("params", {}), dict):
        for k, v in _dict_items_safe(obj.meta.get("params")):
            rv = _resolve_value(v, scope)
            scope[k] = rv
    return scope


def build_native_geometry(obj, warnings, sdf_registry=None):
    meta = obj.meta
    source = str(meta.get("source", "")).lower()
    if source not in {"procedural", "simulation", "sdf"}:
        return None

    p = meta.get("params", {}) if isinstance(meta.get("params", {}), dict) else {}
    if source == "simulation":
        return build_simulation_geometry(obj, p, warnings)
    if source == "sdf":
        return build_sdf_geometry(obj, warnings, sdf_registry)

    typ = str(meta.get("type", "")).lower()

    if typ == "box":
        # Parse params if they're in string format
        parsed_p = {}
        for k, v in _dict_items_safe(p):
            # First resolve the value through scope if it's a reference
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                v = v[2:-1]
                if v in scope:
                    v = scope[v]
            # Then parse if it's still a string
            if isinstance(v, str):
                parsed, parts = _parse_params_string(v)
                # Always check for bracketed list values in parts
                for part in parts:
                    if part.startswith("[") and part.endswith("]"):
                        # This is a list value, assign it to the original key
                        parsed_p[k] = _parse_list_value(part)
                        break
                # Then merge any key=value pairs from the parsed dict
                if isinstance(parsed, dict) and len(parsed) > 0:
                    if k in parsed:
                        parsed_p[k] = parsed[k]
                    else:
                        parsed_p.update(parsed)
                else:
                    # If no parsed dict and no bracketed list, use original value
                    if k not in parsed_p:
                        parsed_p[k] = v
            else:
                parsed_p[k] = v
        p = parsed_p
        
        cx, cy, cz = _vec3(p, "center", (0.0, 0.0, 0.0))
        sx, sy, sz = _vec3(p, "size", (1.0, 1.0, 1.0))
        # Note: bevel parameter is parsed but not applied due to Rhino API limitations
        # Can be added later once correct API is identified
        plane = rg.Plane(_to_pt((cx, cy, cz)), rg.Vector3d.ZAxis)
        box = rg.Box(plane, rg.Interval(-sx / 2.0, sx / 2.0), rg.Interval(-sy / 2.0, sy / 2.0), rg.Interval(-sz / 2.0, sz / 2.0))
        return box.ToBrep()

    if typ == "sphere":
        cx, cy, cz = _vec3(p, "center", (0.0, 0.0, 0.0))
        radius = float(p.get("radius", 1.0))
        return rg.Sphere(_to_pt((cx, cy, cz)), radius).ToBrep()

    if typ == "cylinder":
        cx, cy, cz = _vec3(p, "center", (0.0, 0.0, 0.0))
        radius = float(p.get("radius", 1.0))
        height = float(p.get("height", 1.0))
        circle = rg.Circle(rg.Plane(_to_pt((cx, cy, cz)), rg.Vector3d.ZAxis), radius)
        return rg.Cylinder(circle, height).ToBrep(True, True)

    if typ == "polyline":
        pts = p.get("points", [])
        if isinstance(pts, list) and len(pts) >= 2:
            return rg.Polyline([_to_pt(q) for q in pts]).ToNurbsCurve()
        warnings.append("polyline requires params points=[[x,y,z],...] with at least 2 points")
        return None

    if typ == "cone":
        # Cone aligned to `axis` (z by default). Either `apex=[...]` (tip) or
        # `center=[...]` (base) may be supplied; v02 uses the same convention.
        height = float(p.get("height", p.get("depth", 1.0)))
        radius = float(p.get("radius", 0.5))
        axis = str(p.get("axis", "z")).lower()
        if axis == "x":
            n = rg.Vector3d.XAxis
        elif axis == "y":
            n = rg.Vector3d.YAxis
        else:
            n = rg.Vector3d.ZAxis
        apex = p.get("apex")
        if isinstance(apex, (list, tuple)) and len(apex) >= 3:
            ax, ay, az = float(apex[0]), float(apex[1]), float(apex[2])
            base = rg.Point3d(ax - n.X * height, ay - n.Y * height, az - n.Z * height)
        else:
            cx, cy, cz = _vec3(p, "center", (0.0, 0.0, 0.0))
            base = rg.Point3d(cx, cy, cz)
        return rg.Cone(rg.Plane(base, n), height, radius).ToBrep(True)

    if typ in {"surface_grid", "heightfield"}:
        # Flat grid mesh. v02 supports `width`/`depth`/`resolution`.
        width = float(p.get("width", 10.0))
        depth = float(p.get("depth", 10.0))
        n = max(2, int(p.get("resolution", 20)))
        cx, cy, cz = _vec3(p, "center", (0.0, 0.0, 0.0))
        m = rg.Mesh()
        for j in range(n + 1):
            for i in range(n + 1):
                u = i / float(n)
                v = j / float(n)
                m.Vertices.Add(cx + (u - 0.5) * width, cy + (v - 0.5) * depth, cz)
        for j in range(n):
            for i in range(n):
                a = j * (n + 1) + i
                b = a + 1
                c = a + (n + 1)
                d = c + 1
                m.Faces.AddFace(a, b, d, c)
        m.Normals.ComputeNormals()
        m.Compact()
        return m

    if typ in {"revolve", "lathe"}:
        # Rotate a 2D `profile` (list of [x,z] or [x,y,z] points) around `axis`.
        profile = p.get("profile", [])
        if not isinstance(profile, list) or len(profile) < 2:
            warnings.append("%s requires params profile=[[x,z],...] with >= 2 points" % typ)
            return None
        cx, cy, cz = _vec3(p, "center", (0.0, 0.0, 0.0))
        axis = str(p.get("axis", "z")).lower()
        angle_deg = float(p.get("angle_degrees", p.get("angle", 360.0)))
        if axis == "x":
            axis_dir = rg.Vector3d.XAxis
        elif axis == "y":
            axis_dir = rg.Vector3d.YAxis
        else:
            axis_dir = rg.Vector3d.ZAxis
        pts = []
        for q in profile:
            if isinstance(q, (list, tuple)) and len(q) >= 2:
                # 2D profiles are interpreted in the (radial, axial) plane.
                if len(q) >= 3:
                    pts.append(rg.Point3d(cx + float(q[0]), cy + float(q[1]), cz + float(q[2])))
                else:
                    pts.append(rg.Point3d(cx + float(q[0]), cy, cz + float(q[1])))
        if len(pts) < 2:
            return None
        crv = rg.Polyline(pts).ToNurbsCurve()
        try:
            rev = rg.RevSurface.Create(crv, rg.Line(rg.Point3d(cx, cy, cz),
                                                   rg.Point3d(cx + axis_dir.X, cy + axis_dir.Y, cz + axis_dir.Z)),
                                       0.0, math.radians(angle_deg))
            if rev is not None:
                return rev.ToBrep()
        except Exception as ex:
            warnings.append("%s failed on '%s': %s" % (typ, obj.name, ex))
        return None

    if typ == "mesh":
        # Generator-based mesh primitives (v02's `spiral_treads`,
        # `spiral_post_array`). Anything else falls through.
        gen = str(p.get("generator", "")).lower()
        if gen == "spiral_treads":
            return _build_spiral_treads_brep(p, _vec3(p, "center", (0.0, 0.0, 0.0)))
        if gen == "spiral_post_array":
            return _build_spiral_post_array_breps(p, _vec3(p, "center", (0.0, 0.0, 0.0)))
        if gen:
            warnings.append("unsupported mesh generator on '%s': %s" % (obj.name, gen))
        return None

    if typ:
        warnings.append("unsupported procedural type on '%s': %s" % (obj.name, typ))
    return None


def _build_spiral_treads_brep(p, center):
    """Wedge boxes along a rising helix \u2014 ghpython port of v02 `spiral_treads_mesh`."""
    count = int(p.get("count", p.get("step_count", 12)))
    total_turn = math.radians(float(p.get("total_turn_degrees", 360.0)))
    total_h = float(p.get("total_height", 3.0))
    rise = float(p.get("rise_per_step", total_h / max(1, count)))
    r_in = float(p.get("inner_radius", 0.25))
    r_out = float(p.get("outer_radius", 1.0))
    thick = float(p.get("thickness", p.get("tread_thickness", 0.05)))
    tread_ang = math.radians(max(1.0, float(p.get("tread_angle_degrees", 24.0))))
    cx, cy, cz = center
    r_mid = 0.5 * (r_in + r_out)
    radial = max(0.02, r_out - r_in)
    tangential = max(0.03, r_mid * tread_ang)
    treads = []
    for i in range(count):
        frac = (i * rise) / max(total_h, 1e-6)
        theta = total_turn * frac
        z0 = cz + i * rise
        zc = z0 + thick / 2.0
        cr, sr = math.cos(theta), math.sin(theta)
        px = cx + r_mid * cr
        py = cy + r_mid * sr
        # Build axis-aligned brick then rotate+translate into the spiral slot.
        plane = rg.Plane(rg.Point3d(px, py, zc),
                         rg.Vector3d(cr, sr, 0.0),
                         rg.Vector3d(-sr, cr, 0.0))
        brick = rg.Box(plane,
                       rg.Interval(-radial / 2.0, radial / 2.0),
                       rg.Interval(-tangential / 2.0, tangential / 2.0),
                       rg.Interval(-thick / 2.0, thick / 2.0)).ToBrep()
        treads.append(brick)
    return treads


def _build_spiral_post_array_breps(p, center):
    """Vertical posts along the stair spiral \u2014 ghpython port of `spiral_post_array_mesh`."""
    count = int(p.get("count", p.get("step_count", 12)))
    total_turn = math.radians(float(p.get("total_turn_degrees", 360.0)))
    total_h = float(p.get("total_height", 3.0))
    rise = float(p.get("rise_per_step", total_h / max(1, count)))
    r = float(p.get("radius", 1.0))
    post_r = float(p.get("post_radius", 0.025))
    ph = float(p.get("post_height", 0.9))
    cx, cy, cz = center
    posts = []
    for i in range(count):
        frac = (i * rise) / max(total_h, 1e-6)
        theta = total_turn * frac
        z0 = cz + i * rise
        px = cx + r * math.cos(theta)
        py = cy + r * math.sin(theta)
        circle = rg.Circle(rg.Plane(rg.Point3d(px, py, z0), rg.Vector3d.ZAxis), post_r)
        posts.append(rg.Cylinder(circle, ph).ToBrep(True, True))
    return posts




def _weld_mesh_by_tolerance(mesh, tol=1e-4, warnings=None, label=""):
    """Return a new `Mesh` with coincident vertices merged within `tol`.

    Rhino's `MeshVertexList.CombineIdentical` requires exact position equality.
    `Mesh.CreateFromBrep` computes seam vertices independently per face, so
    floating-point drift along shared edges leaves duplicates CombineIdentical
    never merges. That disconnects the surface -> smoothing (and rendering)
    treats every face as an isolated island. This snaps coincident vertices
    onto a shared grid before merging.

    Returns a fresh mesh rather than mutating in place; in-place Clear+rebuild
    on a `Rhino.Geometry.Mesh` can leave internal caches out of sync.
    """
    if mesh is None:
        return mesh
    n = mesh.Vertices.Count
    if n == 0:
        return mesh
    try:
        inv = 1.0 / max(tol, 1e-12)
        buckets = {}
        remap = [0] * n
        unique_pts = []
        for i in range(n):
            v = mesh.Vertices[i]
            key = (int(round(v.X * inv)), int(round(v.Y * inv)), int(round(v.Z * inv)))
            idx = buckets.get(key)
            if idx is None:
                idx = len(unique_pts)
                buckets[key] = idx
                unique_pts.append((float(v.X), float(v.Y), float(v.Z)))
            remap[i] = idx
        if warnings is not None:
            warnings.append("weld[%s]: verts %d -> %d (tol=%g)" % (label, n, len(unique_pts), tol))
        if len(unique_pts) == n:
            return mesh
        new_mesh = rg.Mesh()
        for (x, y, z) in unique_pts:
            new_mesh.Vertices.Add(x, y, z)
        for fi in range(mesh.Faces.Count):
            f = mesh.Faces[fi]
            if f.IsQuad:
                a, b, c, d = remap[f.A], remap[f.B], remap[f.C], remap[f.D]
                if len({a, b, c, d}) == 4:
                    new_mesh.Faces.AddFace(a, b, c, d)
                elif len({a, b, c}) == 3:
                    new_mesh.Faces.AddFace(a, b, c)
                elif len({a, c, d}) == 3:
                    new_mesh.Faces.AddFace(a, c, d)
            else:
                a, b, c = remap[f.A], remap[f.B], remap[f.C]
                if len({a, b, c}) == 3:
                    new_mesh.Faces.AddFace(a, b, c)
        new_mesh.Normals.ComputeNormals()
        new_mesh.Compact()
        return new_mesh
    except Exception as ex:
        if warnings is not None:
            warnings.append("weld[%s] failed: %s" % (label, ex))
        return mesh


def _prepare_mesh_for_smooth(mesh, warnings=None):
    try:
        mesh.Vertices.CombineIdentical(True, True)
    except Exception:
        pass
    try:
        mesh.Weld(math.radians(180.0))
    except Exception:
        pass
    try:
        mesh.UnifyNormals()
    except Exception:
        pass
    # Caller should replace its reference with the returned mesh; but since
    # smooth ops iterate and mutate in place afterward, return the welded copy
    # so callers can swap if they want.
    return _weld_mesh_by_tolerance(mesh, tol=1e-4, warnings=warnings, label="smooth_prep")


def _smooth_mesh_safe(mesh, iters, strength):
    for _ in range(max(1, int(iters))):
        if hasattr(mesh, "LaplacianSmooth"):
            try:
                mesh.LaplacianSmooth(True, True, True, float(strength))
                continue
            except Exception:
                pass
        if hasattr(mesh, "Smooth"):
            # bFixBoundaries=False: if any seam vertices remain unwelded they
            # would otherwise be pinned, and the interior of each patch would
            # smooth inward on its own, producing a faceted "separate planes"
            # look instead of a continuous surface.
            try:
                mesh.Smooth(float(strength), True, True, True, False, rg.SmoothingCoordinateSystem.World)
                continue
            except Exception:
                try:
                    mesh.Smooth(float(strength), True, True, True, False)
                    continue
                except Exception:
                    pass
        return False
    return True


def _mesh_from_brep(brep, edge_len=0.15, warnings=None):
    try:
        mp = rg.MeshingParameters()
        mp.MaximumEdgeLength = max(0.001, float(edge_len))
        mp.MinimumEdgeLength = max(0.0, float(edge_len) * 0.25)
        parts = rg.Mesh.CreateFromBrep(brep, mp)
        if not parts:
            return None
        m = rg.Mesh()
        for part in parts:
            m.Append(part)
        # CreateFromBrep emits one patch per face; Append concatenates without
        # merging shared seam vertices, leaving the surface topologically
        # disconnected. Weld here so downstream ops (smooth, displace) see a
        # continuous mesh instead of isolated planar patches.
        try:
            m.Vertices.CombineIdentical(True, True)
        except Exception:
            pass
        # Seam vertices from adjacent Brep faces are computed independently and
        # can differ by floating-point epsilon, so exact-equality merging above
        # often misses them. Tolerance-based weld is the real fix.
        tol = max(1e-4, float(edge_len) * 0.1)
        m = _weld_mesh_by_tolerance(m, tol=tol, warnings=warnings, label="mesh_from_brep")
        try:
            m.Weld(math.radians(180.0))
        except Exception:
            pass
        m.Normals.ComputeNormals()
        m.Compact()
        return m
    except Exception as ex:
        if warnings is not None:
            warnings.append("_mesh_from_brep failed: %s" % ex)
        return None

def _clean_ref(v):
    return str(v).strip().strip(',').strip()


def _coerce_single_brep(v):
    """Solids registered under an id are expected to be single Breps. If a
    list of Breps slipped in (e.g. unioning a procedural mesh-generator
    result), unify it to a single Brep so boolean ops keep working. Returns
    None if no usable Brep can be produced.
    """
    if isinstance(v, rg.Brep):
        return v
    if isinstance(v, (list, tuple)):
        breps = [g for g in v if isinstance(g, rg.Brep)]
        if not breps:
            return None
        if len(breps) == 1:
            return breps[0]
        try:
            u = rg.Brep.CreateBooleanUnion(breps, 0.01)
            if u and len(u) > 0:
                return u[0]
        except Exception:
            pass
        # Boolean union failed (disjoint pieces?) — join surface-level so
        # callers at least get a valid single Brep instead of a None.
        joined = rg.Brep.JoinBreps(breps, 0.01)
        if joined and len(joined) > 0:
            return joined[0]
        return breps[0]
    return None


def _apply_transform_to_geom(geom, transform):
    """Apply position/rotation/scale transform to Rhino Mesh or Brep."""
    if geom is None:
        return None
    if not isinstance(transform, dict):
        return geom
    
    pos = transform.get("position", [0, 0, 0])
    scale = transform.get("scale", [1, 1, 1])
    rot = transform.get("rotation", [0, 0, 0])
    
    px, py, pz = float(pos[0]), float(pos[1]), float(pos[2]) if isinstance(pos, (list, tuple)) and len(pos) >= 3 else (float(pos), 0.0, 0.0)
    sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2]) if isinstance(scale, (list, tuple)) and len(scale) >= 3 else (float(scale), float(scale), float(scale))
    rx, ry, rz = [math.radians(float(a)) for a in (rot if isinstance(rot, (list, tuple)) and len(rot) >= 3 else [rot, 0, 0])]
    
    # Build composite transform: scale -> rotate -> translate
    xform = rg.Transform.Identity
    
    # Scale
    scale_xform = rg.Transform.Scale(rg.Plane.WorldXY, sx, sy, sz)
    xform = rg.Transform.Multiply(xform, scale_xform)
    
    # Rotate
    if abs(rx) > 1e-9:
        rot_x = rg.Transform.Rotation(rx, rg.Vector3d.XAxis, rg.Point3d.Origin)
        xform = rg.Transform.Multiply(xform, rot_x)
    if abs(ry) > 1e-9:
        rot_y = rg.Transform.Rotation(ry, rg.Vector3d.YAxis, rg.Point3d.Origin)
        xform = rg.Transform.Multiply(xform, rot_y)
    if abs(rz) > 1e-9:
        rot_z = rg.Transform.Rotation(rz, rg.Vector3d.ZAxis, rg.Point3d.Origin)
        xform = rg.Transform.Multiply(xform, rot_z)
    
    # Translate
    if abs(px) > 1e-9 or abs(py) > 1e-9 or abs(pz) > 1e-9:
        trans = rg.Transform.Translation(px, py, pz)
        xform = rg.Transform.Multiply(xform, trans)
    
    if isinstance(geom, list):
        # Apply transform to each item in the list
        result = []
        for g in geom:
            if hasattr(g, 'Duplicate'):
                g = g.Duplicate()
            if isinstance(g, (rg.Mesh, rg.Brep)):
                g.Transform(xform)
            result.append(g)
        return result
    elif isinstance(geom, rg.Mesh):
        geom.Transform(xform)
        return geom
    elif isinstance(geom, rg.Brep):
        geom.Transform(xform)
        return geom
    else:
        return geom


def _parse_attach_spec(attach_val):
    """Parse attach spec like 'center to table_01.leg_FL' into (self_anchor, target_obj, target_anchor)."""
    text = str(attach_val or "").strip()
    if not text:
        return None
    
    match = re.match(r"^([A-Za-z0-9_-]+)\s+to\s+([A-Za-z0-9_.-]+)\.([A-Za-z0-9_-]+)$", text)
    if match:
        return (match.group(1), match.group(2), match.group(3))
    
    explicit_self = re.search(r"(?:self_anchor|self)=([A-Za-z0-9_-]+)", text)
    explicit_target = re.search(r"(?:to|target)=([A-Za-z0-9_.-]+)\.([A-Za-z0-9_-]+)", text)
    if explicit_self and explicit_target:
        return (explicit_self.group(1), explicit_target.group(1), explicit_target.group(2))
    
    return None


def _compute_geom_anchor(geom, anchor_name):
    """Compute geometric anchor from Rhino Mesh or Brep bounds."""
    if geom is None:
        return None
    
    bbox = None
    if isinstance(geom, rg.Mesh):
        bbox = geom.GetBoundingBox(False)
    elif isinstance(geom, rg.Brep):
        bbox = geom.GetBoundingBox(False)
    
    if bbox is None:
        return None
    
    min_pt = bbox.Min
    max_pt = bbox.Max
    cx, cy, cz = (min_pt.X + max_pt.X) / 2, (min_pt.Y + max_pt.Y) / 2, (min_pt.Z + max_pt.Z) / 2
    
    anchors = {
        "center": (cx, cy, cz),
        "top_center": (cx, cy, max_pt.Z),
        "bottom_center": (cx, cy, min_pt.Z),
        "left_center": (min_pt.X, cy, cz),
        "right_center": (max_pt.X, cy, cz),
        "front_center": (cx, max_pt.Y, cz),
        "back_center": (cx, min_pt.Y, cz),
    }
    return anchors.get(anchor_name)


def _resolve_object_anchor_world(obj, anchor_name, object_by_name, anchor_map, geom_cache=None, warnings=None):
    """Resolve an anchor point on an object to world coordinates, accounting for parent transforms."""
    if warnings is None:
        warnings = []
    
    # First check ANCHOR_MAP for explicit anchors
    key = (obj.name, anchor_name)
    if key in anchor_map:
        vec = anchor_map[key]
        # Apply object's own transform
        transform = obj.meta.get("transform")
        # Parse transform if it's a string
        if isinstance(transform, str):
            transform = _parse_transform(transform)
        if isinstance(transform, dict):
            pos = transform.get("position", [0, 0, 0])
            scale = transform.get("scale", [1, 1, 1])
            rot = transform.get("rotation", [0, 0, 0])
            px, py, pz = float(pos[0]), float(pos[1]), float(pos[2]) if isinstance(pos, (list, tuple)) and len(pos) >= 3 else (float(pos), 0.0, 0.0)
            sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2]) if isinstance(scale, (list, tuple)) and len(scale) >= 3 else (float(scale), float(scale), float(scale))
            rx, ry, rz = [math.radians(float(a)) for a in (rot if isinstance(rot, (list, tuple)) and len(rot) >= 3 else [rot, 0, 0])]
            
            # Simple scale and translate (rotation omitted for anchor points to match v02 behavior)
            result = (vec[0] * sx + px, vec[1] * sy + py, vec[2] * sz + pz)
            return result
        return vec
    
    # For assemblies, check if any children have the anchor (hierarchical anchor resolution)
    if str(obj.meta.get("source", "")).lower() == "assembly":
        children_raw = obj.meta.get("children", [])
        # Parse children from comma-separated string or list
        if isinstance(children_raw, str):
            children = [c.strip() for c in children_raw.split(",") if c.strip()]
        elif isinstance(children_raw, list):
            children = children_raw
        else:
            children = []
        if isinstance(children, list):
            for child_name in children:
                child_obj = object_by_name.get(str(child_name))
                if child_obj:
                    child_anchor = _resolve_object_anchor_world(child_obj, anchor_name, object_by_name, anchor_map, geom_cache, warnings)
                    if child_anchor:
                        return child_anchor
    
    # Fallback: compute geometric anchor from geometry if available
    if geom_cache and obj.name in geom_cache:
        geom = geom_cache[obj.name]
        local_anchor = _compute_geom_anchor(geom, anchor_name)
        if local_anchor:
            # Apply object's transform
            transform = obj.meta.get("transform")
            if isinstance(transform, dict):
                pos = transform.get("position", [0, 0, 0])
                scale = transform.get("scale", [1, 1, 1])
                px, py, pz = float(pos[0]), float(pos[1]), float(pos[2]) if isinstance(pos, (list, tuple)) and len(pos) >= 3 else (float(pos), 0.0, 0.0)
                sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2]) if isinstance(scale, (list, tuple)) and len(scale) >= 3 else (float(scale), float(scale), float(scale))
                return (local_anchor[0] * sx + px, local_anchor[1] * sy + py, local_anchor[2] * sz + pz)
            return local_anchor
    
    return None


# =============================
# SDF Expression System
# =============================

def _length3(p):
    return math.sqrt(p[0]*p[0] + p[1]*p[1] + p[2]*p[2])

def _sub3(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

class SDFExpr:
    def dist(self, p):
        raise NotImplementedError

class SDFBox(SDFExpr):
    def __init__(self, center, size):
        self.c = center
        self.s = (size[0]/2, size[1]/2, size[2]/2)

    def dist(self, p):
        q = (abs(p[0]-self.c[0])-self.s[0], abs(p[1]-self.c[1])-self.s[1], abs(p[2]-self.c[2])-self.s[2])
        outside = _length3((max(q[0],0), max(q[1],0), max(q[2],0)))
        inside = min(max(q[0], max(q[1], q[2])), 0)
        return outside + inside

class SDFSphere(SDFExpr):
    def __init__(self, center, radius):
        self.c = center
        self.r = radius

    def dist(self, p):
        return _length3(_sub3(p, self.c)) - self.r

class SDFCylinderZ(SDFExpr):
    def __init__(self, center, radius, height):
        self.c = center
        self.r = radius
        self.h = height / 2

    def dist(self, p):
        dx = math.sqrt((p[0]-self.c[0])**2 + (p[1]-self.c[1])**2) - self.r
        dz = abs(p[2]-self.c[2]) - self.h
        return min(max(dx, dz), 0.0) + _length3((max(dx,0), max(dz,0), 0))

class SDFCylinderX(SDFExpr):
    def __init__(self, center, radius, height):
        self.c = center
        self.r = radius
        self.h = height / 2

    def dist(self, p):
        # Cylinder aligned with X axis: circular cross-section in Y-Z plane
        dy = math.sqrt((p[1]-self.c[1])**2 + (p[2]-self.c[2])**2) - self.r
        dx = abs(p[0]-self.c[0]) - self.h
        return min(max(dx, dy), 0.0) + _length3((max(dx,0), max(dy,0), 0))

class SDFCylinderY(SDFExpr):
    def __init__(self, center, radius, height):
        self.c = center
        self.r = radius
        self.h = height / 2

    def dist(self, p):
        # Cylinder aligned with Y axis: circular cross-section in X-Z plane
        dx = math.sqrt((p[0]-self.c[0])**2 + (p[2]-self.c[2])**2) - self.r
        dy = abs(p[1]-self.c[1]) - self.h
        return min(max(dx, dy), 0.0) + _length3((max(dx,0), max(dy,0), 0))

class SDFUnion(SDFExpr):
    def __init__(self, a, b):
        self.a, self.b = a, b

    def dist(self, p):
        return min(self.a.dist(p), self.b.dist(p))

class SDFSubtract(SDFExpr):
    def __init__(self, a, b):
        self.a, self.b = a, b

    def dist(self, p):
        return max(self.a.dist(p), -self.b.dist(p))

class SDFIntersect(SDFExpr):
    def __init__(self, a, b):
        self.a, self.b = a, b

    def dist(self, p):
        return max(self.a.dist(p), self.b.dist(p))

class SDFSmoothUnion(SDFExpr):
    def __init__(self, a, b, radius):
        self.a, self.b, self.r = a, b, max(1e-6, radius)

    def dist(self, p):
        da = self.a.dist(p)
        db = self.b.dist(p)
        h = max(0.0, min(1.0, 0.5 + 0.5 * (db - da) / self.r))
        return (db * (1 - h) + da * h) - self.r * h * (1 - h)

class SDFNoiseDisplace(SDFExpr):
    def __init__(self, base, strength, frequency, seed):
        self.base, self.strength, self.frequency, self.seed = base, strength, frequency, seed

    def dist(self, p):
        x, y, z = p
        f = self.frequency
        n = (
            math.sin(x*f + self.seed) * 0.5 +
            math.sin(y*f*1.7 + self.seed*0.31) * 0.3 +
            math.sin(z*f*2.1 + self.seed*0.73) * 0.2
        )
        return self.base.dist(p) + self.strength * n

def _calculate_sdf_bounds(sdf_ops, unit_scale=1.0):
    """Calculate bounding box from SDF primitives."""
    min_bounds = [float('inf'), float('inf'), float('inf')]
    max_bounds = [float('-inf'), float('-inf'), float('-inf')]
    
    for cmd in sdf_ops:
        c = cmd.get("op") or cmd.get("cmd")
        if c == "box":
            center = cmd.get("center", [0,0,0])
            size = cmd.get("size", [1,1,1])
            if isinstance(center, str):
                center = _parse_list_value(center)
            if isinstance(size, str):
                size = _parse_list_value(size)
            center = tuple(map(float, center))
            size = tuple(map(float, size))
            # Convert to Rhino units
            center = (center[0] * unit_scale, center[1] * unit_scale, center[2] * unit_scale)
            size = (size[0] * unit_scale, size[1] * unit_scale, size[2] * unit_scale)
            half_size = (size[0]/2, size[1]/2, size[2]/2)
            for i in range(3):
                min_bounds[i] = min(min_bounds[i], center[i] - half_size[i])
                max_bounds[i] = max(max_bounds[i], center[i] + half_size[i])
        elif c == "sphere":
            center = cmd.get("center", [0,0,0])
            radius = cmd.get("radius", 1)
            if isinstance(center, str):
                center = _parse_list_value(center)
            if isinstance(radius, str):
                radius = float(radius)
            else:
                radius = float(radius)
            # Convert to Rhino units
            center = tuple(map(float, center))
            center = (center[0] * unit_scale, center[1] * unit_scale, center[2] * unit_scale)
            radius = radius * unit_scale
            for i in range(3):
                min_bounds[i] = min(min_bounds[i], center[i] - radius)
                max_bounds[i] = max(max_bounds[i], center[i] + radius)
        elif c == "cylinder":
            center = cmd.get("center", [0,0,0])
            radius = cmd.get("radius", 1)
            height = cmd.get("height", 1)
            if isinstance(center, str):
                center = _parse_list_value(center)
            if isinstance(radius, str):
                radius = float(radius)
            else:
                radius = float(radius)
            if isinstance(height, str):
                height = float(height)
            else:
                height = float(height)
            # Convert to Rhino units
            center = tuple(map(float, center))
            center = (center[0] * unit_scale, center[1] * unit_scale, center[2] * unit_scale)
            radius = radius * unit_scale
            height = height * unit_scale
            half_height = height / 2
            for i in range(3):
                if i == 2:  # Z axis
                    min_bounds[i] = min(min_bounds[i], center[i] - half_height)
                    max_bounds[i] = max(max_bounds[i], center[i] + half_height)
                else:  # X, Y axes
                    min_bounds[i] = min(min_bounds[i], center[i] - radius)
                    max_bounds[i] = max(max_bounds[i], center[i] + radius)
    
    # Add padding (20% on each side)
    if min_bounds[0] == float('inf'):
        # No primitives found, return default bounds
        return [[-2*unit_scale, -2*unit_scale, -2*unit_scale], [2*unit_scale, 2*unit_scale, 2*unit_scale]]
    
    padding = 0.2
    for i in range(3):
        extent = max_bounds[i] - min_bounds[i]
        min_bounds[i] -= extent * padding
        max_bounds[i] += extent * padding
    
    return [min_bounds, max_bounds]


def _build_sdf(sdf_ops, unit_scale=1.0, warnings=None):
    """Build an SDF expression from a list of SDF operations."""
    if warnings is None:
        warnings = []
    registry = {}
    current = None

    for cmd in sdf_ops:
        # Live OBJ uses 'op' for operation name, but also check for 'cmd' for compatibility
        c = cmd.get("op") or cmd.get("cmd")
        if c == "box":
            sid = str(cmd.get("id", f"box_{len(registry)}"))
            center = cmd.get("center", [0,0,0])
            size = cmd.get("size", [1,1,1])
            # Parse parameters if they're in string format
            if isinstance(center, str):
                center = _parse_list_value(center)
            if isinstance(size, str):
                size = _parse_list_value(size)
            # Convert to Rhino units
            center = tuple(map(float, center))
            size = tuple(map(float, size))
            center = (center[0] * unit_scale, center[1] * unit_scale, center[2] * unit_scale)
            size = (size[0] * unit_scale, size[1] * unit_scale, size[2] * unit_scale)
            registry[sid] = SDFBox(center, size)
            current = registry[sid]
            warnings.append("sdf: box %s center=%s size=%s" % (sid, center, size))
        elif c == "sphere":
            sid = str(cmd.get("id", f"sphere_{len(registry)}"))
            center = cmd.get("center", [0,0,0])
            radius = cmd.get("radius", 1)
            # Parse parameters if they're in string format
            if isinstance(center, str):
                center = _parse_list_value(center)
            if isinstance(radius, str):
                radius = float(radius)
            else:
                radius = float(radius)
            # Convert to Rhino units
            center = tuple(map(float, center))
            center = (center[0] * unit_scale, center[1] * unit_scale, center[2] * unit_scale)
            radius = radius * unit_scale
            registry[sid] = SDFSphere(center, radius)
            current = registry[sid]
            warnings.append("sdf: sphere %s center=%s radius=%s" % (sid, center, radius))
        elif c == "cylinder":
            sid = str(cmd.get("id", f"cylinder_{len(registry)}"))
            center = cmd.get("center", [0,0,0])
            radius = cmd.get("radius", 1)
            height = cmd.get("height", 1)
            axis_param = cmd.get("axis", "z")
            # Parse axis parameter - might be a string or list
            if isinstance(axis_param, list):
                axis = str(axis_param[0]).lower() if axis_param else "z"
            else:
                axis = str(axis_param).lower()
            # Parse parameters if they're in string format
            if isinstance(center, str):
                center = _parse_list_value(center)
            if isinstance(radius, str):
                radius = float(radius)
            else:
                radius = float(radius)
            if isinstance(height, str):
                height = float(height)
            else:
                height = float(height)
            # Convert to Rhino units
            center = tuple(map(float, center))
            center = (center[0] * unit_scale, center[1] * unit_scale, center[2] * unit_scale)
            radius = radius * unit_scale
            height = height * unit_scale
            # Select appropriate cylinder class based on axis
            if axis == "x":
                registry[sid] = SDFCylinderX(center, radius, height)
                warnings.append("sdf: cylinder %s center=%s radius=%s height=%s axis=x (aligned along X)" % (sid, center, radius, height))
            elif axis == "y":
                registry[sid] = SDFCylinderY(center, radius, height)
                warnings.append("sdf: cylinder %s center=%s radius=%s height=%s axis=y (aligned along Y)" % (sid, center, radius, height))
            else:
                registry[sid] = SDFCylinderZ(center, radius, height)
                warnings.append("sdf: cylinder %s center=%s radius=%s height=%s axis=z (aligned along Z)" % (sid, center, radius, height))
            current = registry[sid]
        elif c in {"union", "subtract", "intersect", "smooth_union"}:
            args = cmd.get("args", []) or cmd.get("_args", [])
            a_id = b_id = None
            if len(args) >= 2:
                a_id, b_id = str(args[0]), str(args[1])
            elif cmd.get("id_a") is not None and cmd.get("id_b") is not None:
                a_id, b_id = str(cmd.get("id_a")), str(cmd.get("id_b"))
            warnings.append("sdf: %s op args=%s id_a=%s id_b=%s" % (c, args, cmd.get("id_a"), cmd.get("id_b")))
            if a_id and b_id and a_id in registry and b_id in registry:
                if c == "smooth_union" and a_id == b_id:
                    current = registry[a_id]
                    registry["result"] = current
                    continue
                a, b = registry[a_id], registry[b_id]
                if c == "union":
                    current = SDFUnion(a, b)
                elif c == "subtract":
                    current = SDFSubtract(a, b)
                elif c == "intersect":
                    current = SDFIntersect(a, b)
                else:
                    current = SDFSmoothUnion(a, b, float(cmd.get("radius", 0.1)))
                registry[a_id] = current
                registry["result"] = current
                warnings.append("sdf: %s %s %s -> result" % (c, a_id, b_id))
            else:
                warnings.append("sdf: %s skipped - a_id=%s in registry=%s, b_id=%s in registry=%s" % (c, a_id, a_id in registry, b_id, b_id in registry))
        elif c == "noise_displace" and current is not None:
            current = SDFNoiseDisplace(
                current,
                strength=float(cmd.get("strength", 0.1)),
                frequency=float(cmd.get("frequency", 3)),
                seed=int(cmd.get("seed", 0)),
            )
            registry["result"] = current

    return current


def _sdf_to_marching_cubes_mesh(expr, bounds, resolution, iso=0.0, warnings=None):
    """Dependency-free marching cubes using tetrahedral decomposition."""
    if warnings is None:
        warnings = []
    
    mn, mx = bounds
    nx = max(2, int((mx[0] - mn[0]) / resolution))
    ny = max(2, int((mx[1] - mn[1]) / resolution))
    nz = max(2, int((mx[2] - mn[2]) / resolution))
    
    # Safeguard: limit total voxels to prevent freezing
    max_voxels = 1000000  # 1 million voxels max
    total_voxels = nx * ny * nz
    if total_voxels > max_voxels:
        warnings.append("sdf: resolution %s produces %s voxels, exceeding limit of %s. Using safer resolution." % (resolution, total_voxels, max_voxels))
        # Recalculate resolution to stay within limit
        target_voxels = max_voxels
        scale_factor = (target_voxels / total_voxels) ** (1/3)
        resolution = resolution / scale_factor
        nx = max(2, int((mx[0] - mn[0]) / resolution))
        ny = max(2, int((mx[1] - mn[1]) / resolution))
        nz = max(2, int((mx[2] - mn[2]) / resolution))
        warnings.append("sdf: adjusted resolution to %s (%s voxels)" % (resolution, nx * ny * nz))
    
    ox, oy, oz = float(mn[0]), float(mn[1]), float(mn[2])

    def p(i, j, k):
        return (ox + i * resolution, oy + j * resolution, oz + k * resolution)

    vals = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            for k in range(nz + 1):
                pt = p(i, j, k)
                vals[(i, j, k)] = expr.dist(pt)
    
    # Debug: check SDF values at center and near expected bowl location
    if warnings is not None:
        center_pt = p(nx//2, ny//2, nz//2)
        center_dist = expr.dist(center_pt)
        warnings.append("sdf: debug center_pt=%s center_dist=%s" % (center_pt, center_dist))

    cube_tets = [
        (0, 5, 1, 6),
        (0, 1, 2, 6),
        (0, 2, 3, 6),
        (0, 3, 7, 6),
        (0, 7, 4, 6),
        (0, 4, 5, 6),
    ]
    cverts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]

    vertices = []
    faces = []

    def lerp(a, b, va, vb):
        d = (vb - va)
        if abs(d) < 1e-12:
            t = 0.5
        else:
            t = (iso - va) / d
        t = max(0.0, min(1.0, t))
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)

    tet_edges = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))

    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                cps = [p(i + dx, j + dy, k + dz) for (dx, dy, dz) in cverts]
                cvs = [vals[(i + dx, j + dy, k + dz)] for (dx, dy, dz) in cverts]
                for a, b, c, d in cube_tets:
                    tps = [cps[a], cps[b], cps[c], cps[d]]
                    tvs = [cvs[a], cvs[b], cvs[c], cvs[d]]
                    inside = [idx for idx, v in enumerate(tvs) if v <= iso]
                    if len(inside) == 0 or len(inside) == 4:
                        continue
                    points = []
                    for e0, e1 in tet_edges:
                        v0, v1 = tvs[e0], tvs[e1]
                        if (v0 <= iso and v1 > iso) or (v1 <= iso and v0 > iso):
                            points.append(lerp(tps[e0], tps[e1], v0, v1))
                    if len(points) == 3:
                        base = len(vertices)
                        vertices.extend(points)
                        faces.append([base, base + 1, base + 2])
                    elif len(points) == 4:
                        base = len(vertices)
                        vertices.extend(points)
                        # Triangulate correctly using a true diagonal (0 to 3)
                        faces.append([base, base + 1, base + 3])
                        faces.append([base, base + 3, base + 2])

    if vertices:
        warnings.append("sdf: before welding - vertices=%s faces=%s" % (len(vertices), len(faces)))
        # Custom welding similar to v02
        epsilon = float(resolution) * 0.1
        welded_vertices = []
        welded_faces = []
        remap = {}
        for i, v in enumerate(vertices):
            # Find if this vertex already exists within epsilon
            found_idx = None
            for j, wv in enumerate(welded_vertices):
                if (abs(v[0] - wv[0]) < epsilon and 
                    abs(v[1] - wv[1]) < epsilon and 
                    abs(v[2] - wv[2]) < epsilon):
                    found_idx = j
                    break
            if found_idx is None:
                found_idx = len(welded_vertices)
                welded_vertices.append(v)
            remap[i] = found_idx
        for face in faces:
            welded_faces.append([remap[face[0]], remap[face[1]], remap[face[2]]])
        
        warnings.append("sdf: after welding - vertices=%s faces=%s" % (len(welded_vertices), len(welded_faces)))
        
        # Filter out degenerate faces (faces with duplicate vertices)
        non_degenerate_faces = []
        for face in welded_faces:
            if len(set(face)) == 3:
                non_degenerate_faces.append(face)
        welded_faces = non_degenerate_faces
        warnings.append("sdf: removed %s degenerate faces, remaining %s" % (len(welded_faces) - len(non_degenerate_faces), len(non_degenerate_faces)))
        
        # Convert to Rhino mesh
        mesh = rg.Mesh()
        for v in welded_vertices:
            mesh.Vertices.Add(v[0], v[1], v[2])
        for face in welded_faces:
            mesh.Faces.AddFace(face[0], face[1], face[2])
        mesh.Normals.ComputeNormals()
        mesh.Compact()
        
        warnings.append("sdf: mesh.IsValid=%s" % mesh.IsValid)
        
        # Use Rhino's mesh repair to fix remaining issues
        try:
            success = mesh.Repair(rg.MeshRepairConditions.All, True)
            warnings.append("sdf: after repair mesh.IsValid=%s success=%s" % (mesh.IsValid, success))
        except Exception as e:
            warnings.append("sdf: mesh repair failed: %s" % str(e))
        
        return mesh
    warnings.append("sdf: no vertices generated, returning empty mesh")
    return rg.Mesh()


def _sdf_to_voxel_mesh(expr, bounds, resolution, warnings=None):
    """Simple voxel approximation: sample SDF on grid and emit voxel faces."""
    if warnings is None:
        warnings = []
    
    mn, mx = bounds
    nx = max(2, int((mx[0] - mn[0]) / resolution))
    ny = max(2, int((mx[1] - mn[1]) / resolution))
    nz = max(2, int((mx[2] - mn[2]) / resolution))
    ox, oy, oz = float(mn[0]), float(mn[1]), float(mn[2])
    
    occupied = set()
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                pt = (ox + i * resolution, oy + j * resolution, oz + k * resolution)
                if expr.dist(pt) <= 0:
                    occupied.add((i, j, k))
    
    mesh = rg.Mesh()
    dirs = [
        ((1,0,0), [(1,-1,-1),(1,1,-1),(1,1,1),(1,-1,1)]),
        ((-1,0,0), [(-1,-1,-1),(-1,-1,1),(-1,1,1),(-1,1,-1)]),
        ((0,1,0), [(-1,1,-1),(-1,1,1),(1,1,1),(1,1,-1)]),
        ((0,-1,0), [(-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1)]),
        ((0,0,1), [(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]),
        ((0,0,-1), [(-1,-1,-1),(-1,1,-1),(1,1,-1),(1,-1,-1)]),
    ]
    half = resolution / 2
    for i, j, k in occupied:
        cx, cy, cz = ox + i*resolution, oy + j*resolution, oz + k*resolution
        for (di,dj,dk), corners in dirs:
            if (i+di, j+dj, k+dk) in occupied:
                continue
            face_indices = []
            for sx, sy, sz in corners:
                mesh.Vertices.Add(cx + sx*half, cy + sy*half, cz + sz*half)
                face_indices.append(mesh.Vertices.Count - 1)
            mesh.Faces.AddFace(face_indices[0], face_indices[1], face_indices[2], face_indices[3])
    
    if mesh.Vertices.Count > 0:
        mesh.Normals.ComputeNormals()
        mesh.Compact()
        # Use conservative welding tolerance to fix invalid mesh while preventing corruption
        tol = max(1e-8, float(resolution) * 0.001)
        mesh = _weld_mesh_by_tolerance(mesh, tol=tol, warnings=warnings, label="voxel")
    return mesh


def _apply_attach_constraints(objs, anchor_map, warnings, geom_cache):
    """Apply attach constraints by computing delta between anchor points and translating geometry."""
    object_by_name = {o.name: o for o in objs}
    
    for obj in objs:
        spec = _parse_attach_spec(obj.meta.get("attach"))
        if not spec:
            continue
        
        self_anchor, target_obj_name, target_anchor = spec
        target_obj = object_by_name.get(target_obj_name)
        if target_obj is None:
            warnings.append("attach: target object '%s' not found for '%s'" % (target_obj_name, obj.name))
            continue
        
        self_world = _resolve_object_anchor_world(obj, self_anchor, object_by_name, anchor_map, geom_cache, warnings)
        target_world = _resolve_object_anchor_world(target_obj, target_anchor, object_by_name, anchor_map, geom_cache, warnings)
        
        if self_world is None or target_world is None:
            warnings.append("attach: could not resolve anchors for '%s' (self=%s, target=%s.%s)" % (obj.name, self_anchor, target_obj_name, target_anchor))
            continue
        
        delta = (target_world[0] - self_world[0], target_world[1] - self_world[1], target_world[2] - self_world[2])
        
        # For "center" self-anchor, adjust z to position the top of the object at the target point
        if self_anchor == "center" and geom_cache and obj.name in geom_cache:
            geom = geom_cache[obj.name]
            bbox = None
            if isinstance(geom, rg.Mesh):
                bbox = geom.GetBoundingBox(False)
            elif isinstance(geom, rg.Brep):
                bbox = geom.GetBoundingBox(False)
            if bbox:
                height = bbox.Max.Z - bbox.Min.Z
                # Adjust delta so the top of the object is at the target point (subtract half height)
                delta = (delta[0], delta[1], delta[2] - height / 2)
        
        # Apply delta to object's transform
        transform = obj.meta.get("transform")
        if isinstance(transform, dict):
            pos = transform.get("position", [0, 0, 0])
            if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                transform["position"] = [pos[0] + delta[0], pos[1] + delta[1], pos[2] + delta[2]]
            else:
                transform["position"] = [delta[0], delta[1], delta[2]]
        else:
            obj.meta["transform"] = {"position": [delta[0], delta[1], delta[2]]}


def _sdf_vec3(op, key, default):
    raw = op.get(key, default)
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return float(raw[0]), float(raw[1]), float(raw[2])
        except Exception:
            return default
    return default


def _build_torus_brep(op):
    """Torus from `center=[...] major_radius=R minor_radius=r axis=z`.

    Falls back to `r1`/`r2` aliases for compatibility with v02 op syntax.
    """
    try:
        cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
        R = float(op.get("major_radius", op.get("r1", op.get("R", 1.0))))
        r = float(op.get("minor_radius", op.get("r2", op.get("r", 0.25))))
        axis = str(op.get("axis", "z")).lower()
        if axis == "x":
            normal = rg.Vector3d.XAxis
        elif axis == "y":
            normal = rg.Vector3d.YAxis
        else:
            normal = rg.Vector3d.ZAxis
        plane = rg.Plane(rg.Point3d(cx, cy, cz), normal)
        torus = rg.Torus(plane, R, r)
        return torus.ToRevSurface().ToBrep()
    except Exception:
        return None


def _build_cone_brep(op):
    """Cone from `apex=[...] axis=z height=H radius=R` or `center=[...] height=H radius=R axis=z`.

    `apex` is the tip; `center` is the base center. Defaults match v02.
    """
    try:
        h = float(op.get("height", 1.0))
        r = float(op.get("radius", 0.5))
        axis = str(op.get("axis", "z")).lower()
        if axis == "x":
            n = rg.Vector3d.XAxis
        elif axis == "y":
            n = rg.Vector3d.YAxis
        else:
            n = rg.Vector3d.ZAxis
        apex = op.get("apex")
        if isinstance(apex, (list, tuple)) and len(apex) >= 3:
            ax, ay, az = float(apex[0]), float(apex[1]), float(apex[2])
            base_pt = rg.Point3d(ax - n.X * h, ay - n.Y * h, az - n.Z * h)
        else:
            cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
            base_pt = rg.Point3d(cx, cy, cz)
        plane = rg.Plane(base_pt, n)
        cone = rg.Cone(plane, h, r)
        return cone.ToBrep(True)
    except Exception:
        return None


def _build_plane_brep(op):
    """Half-space plane approximated as a large box on one side of the plane.

    Accepts `point=[...] normal=[...]` or `axis=z offset=v`. The box extends
    `extent` units past the plane on the negative-normal side, so subsequent
    `subtract` operations can slice solids at that plane.
    """
    try:
        extent = float(op.get("extent", 50.0))
        pt_raw = op.get("point", op.get("origin"))
        n_raw = op.get("normal")
        if (isinstance(pt_raw, (list, tuple)) and len(pt_raw) >= 3 and
            isinstance(n_raw, (list, tuple)) and len(n_raw) >= 3):
            origin = rg.Point3d(float(pt_raw[0]), float(pt_raw[1]), float(pt_raw[2]))
            normal = rg.Vector3d(float(n_raw[0]), float(n_raw[1]), float(n_raw[2]))
        else:
            axis = str(op.get("axis", "z")).lower()
            offset = float(op.get("offset", 0.0))
            if axis == "x":
                origin, normal = rg.Point3d(offset, 0, 0), rg.Vector3d.XAxis
            elif axis == "y":
                origin, normal = rg.Point3d(0, offset, 0), rg.Vector3d.YAxis
            else:
                origin, normal = rg.Point3d(0, 0, offset), rg.Vector3d.ZAxis
        if not normal.Unitize():
            return None
        plane = rg.Plane(origin, normal)
        # Half-space on the -normal side: a thick slab from 0 down to -extent.
        return rg.Box(plane,
                      rg.Interval(-extent, extent),
                      rg.Interval(-extent, extent),
                      rg.Interval(-extent, 0)).ToBrep()
    except Exception:
        return None


def _build_capsule_brep(op):
    """Build a capsule Brep from an SDF op dict.

    Accepts either `p1=[...] p2=[...] radius=R` or
    `center=[cx,cy,cz] height=H radius=R axis=z` (default axis z).
    Caps are spheres unioned to a cylinder body.
    """
    try:
        r = float(op.get("radius", 0.5))
        p1 = op.get("p1")
        p2 = op.get("p2")
        if (isinstance(p1, (list, tuple)) and len(p1) >= 3 and
            isinstance(p2, (list, tuple)) and len(p2) >= 3):
            pt1 = rg.Point3d(float(p1[0]), float(p1[1]), float(p1[2]))
            pt2 = rg.Point3d(float(p2[0]), float(p2[1]), float(p2[2]))
        else:
            cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
            h = float(op.get("height", 1.0))
            axis = str(op.get("axis", "z")).lower()
            if axis == "x":
                d = rg.Vector3d(h * 0.5, 0.0, 0.0)
            elif axis == "y":
                d = rg.Vector3d(0.0, h * 0.5, 0.0)
            else:
                d = rg.Vector3d(0.0, 0.0, h * 0.5)
            pt1 = rg.Point3d(cx - d.X, cy - d.Y, cz - d.Z)
            pt2 = rg.Point3d(cx + d.X, cy + d.Y, cz + d.Z)
        axis_vec = pt2 - pt1
        if axis_vec.Length < 1e-6:
            return rg.Sphere(pt1, r).ToBrep()
        plane = rg.Plane(pt1, axis_vec)
        circle = rg.Circle(plane, r)
        body = rg.Cylinder(circle, axis_vec.Length).ToBrep(True, True)
        s1 = rg.Sphere(pt1, r).ToBrep()
        s2 = rg.Sphere(pt2, r).ToBrep()
        u = rg.Brep.CreateBooleanUnion([body, s1, s2], 0.01)
        return u[0] if (u and len(u) > 0) else body
    except Exception:
        return None


def build_sdf_geometry(obj, warnings, sdf_registry=None):
    sdf_ops = obj.meta.get("sdf_ops", [])
    if not isinstance(sdf_ops, list) or not sdf_ops:
        warnings.append("sdf source on '%s' has no #@sdf ops" % obj.name)
        return None

    # Check if method is marching_cubes - use SDF expression approach
    params = obj.meta.get("params", {}) or {}
    method = str(params.get("method", "marching_cubes")).lower()
    for op in sdf_ops:
        if op.get("method") is not None:
            method = str(op.get("method", method)).lower()
    
    if method in {"marching_cubes", "marching", "mc"}:
        # Determine unit scale from OBJ units
        obj_units = obj.meta.get("units", "millimeters")
        unit_scale = 1.0
        if isinstance(obj_units, str):
            obj_units = obj_units.lower()
            if obj_units in {"meter", "meters", "m"}:
                unit_scale = 1000.0
            elif obj_units in {"centimeter", "centimeters", "cm"}:
                unit_scale = 10.0
            # millimeters is the default (no conversion)
        
        # Use SDF expression approach with marching cubes
        expr = _build_sdf(sdf_ops, unit_scale, warnings)
        if expr is None:
            # Fall back to Rhino Brep approach if SDF expression build fails
            warnings.append("sdf: failed to build SDF expression for '%s', falling back to Brep" % obj.name)
            method = "brep"
        else:
            resolution = float(params.get("resolution", 0.15))
            # Also check for resolution in mesh_from_sdf op
            for op in sdf_ops:
                if str(op.get("cmd", "")).lower() == "mesh_from_sdf" or str(op.get("op", "")).lower() == "mesh_from_sdf":
                    if op.get("resolution") is not None:
                        resolution = float(op["resolution"])
            
            # Auto-calculate bounds from SDF primitives if not explicitly provided
            # DISABLED - includes cutting primitives which are too large
            # if "bounds" not in params or params.get("bounds") is None:
            #     auto_bounds = _calculate_sdf_bounds(sdf_ops, unit_scale)
            #     # Check if auto-calculated bounds would produce too many voxels
            #     auto_extent = [auto_bounds[1][i] - auto_bounds[0][i] for i in range(3)]
            #     auto_voxels = (auto_extent[0] / resolution) * (auto_extent[1] / resolution) * (auto_extent[2] / resolution)
            #     if auto_voxels > 10000000:  # 10 million voxel limit for auto-calculated bounds
            #         warnings.append("sdf: auto-calculated bounds would produce %s voxels, using default bounds instead" % int(auto_voxels))
            #         bounds = params.get("bounds", [[-2,-2,-2],[2,2,2]])
            #     else:
            #         bounds = auto_bounds
            #         warnings.append("sdf: auto-calculated bounds from SDF primitives: %s" % bounds)
            # else:
            bounds = params.get("bounds", [[-2,-2,-2],[2,2,2]])
            
            # Convert resolution and bounds from OBJ units to Rhino units (millimeters)
            warnings.append("sdf: obj_units=%s, original_resolution=%s" % (obj.meta.get("units", "millimeters"), resolution))
            warnings.append("sdf: unit_scale=%s" % unit_scale)
            if unit_scale != 1.0:
                resolution = resolution * unit_scale
                warnings.append("sdf: converted resolution to mm: %s" % resolution)
            
            # Convert bounds if they were explicitly provided (auto-calculated bounds are already in Rhino units)
            if "bounds" in params and params.get("bounds") is not None:
                bounds = [[bounds[0][0] * unit_scale, bounds[0][1] * unit_scale, bounds[0][2] * unit_scale],
                          [bounds[1][0] * unit_scale, bounds[1][1] * unit_scale, bounds[1][2] * unit_scale]]
                warnings.append("sdf: converted bounds to mm: %s" % bounds)
            else:
                # Default bounds are in meters, need to convert
                bounds = [[bounds[0][0] * unit_scale, bounds[0][1] * unit_scale, bounds[0][2] * unit_scale],
                          [bounds[1][0] * unit_scale, bounds[1][1] * unit_scale, bounds[1][2] * unit_scale]]
                warnings.append("sdf: converted default bounds to mm: %s" % bounds)
            
            mesh = _sdf_to_marching_cubes_mesh(expr, bounds, resolution, warnings=warnings)
            if mesh is None:
                warnings.append("sdf: marching cubes failed for '%s', falling back to Brep" % obj.name)
                method = "brep"
            else:
                return mesh
    elif method == "voxel":
        # Determine unit scale from OBJ units
        obj_units = obj.meta.get("units", "millimeters")
        unit_scale = 1.0
        if isinstance(obj_units, str):
            obj_units = obj_units.lower()
            if obj_units in {"meter", "meters", "m"}:
                unit_scale = 1000.0
            elif obj_units in {"centimeter", "centimeters", "cm"}:
                unit_scale = 10.0
            # millimeters is the default (no conversion)
        
        # Use SDF expression approach with voxel approximation
        expr = _build_sdf(sdf_ops, unit_scale, warnings)
        if expr is None:
            # Fall back to Rhino Brep approach if SDF expression build fails
            warnings.append("sdf: failed to build SDF expression for '%s', falling back to Brep" % obj.name)
            method = "brep"
        else:
            resolution = float(params.get("resolution", 0.15))
            # Also check for resolution in mesh_from_sdf op
            for op in sdf_ops:
                if str(op.get("cmd", "")).lower() == "mesh_from_sdf" or str(op.get("op", "")).lower() == "mesh_from_sdf":
                    if op.get("resolution") is not None:
                        resolution = float(op["resolution"])
            
            # Auto-calculate bounds from SDF primitives if not explicitly provided
            # DISABLED - includes cutting primitives which are too large
            # if "bounds" not in params or params.get("bounds") is None:
            #     auto_bounds = _calculate_sdf_bounds(sdf_ops, unit_scale)
            #     # Check if auto-calculated bounds would produce too many voxels
            #     auto_extent = [auto_bounds[1][i] - auto_bounds[0][i] for i in range(3)]
            #     auto_voxels = (auto_extent[0] / resolution) * (auto_extent[1] / resolution) * (auto_extent[2] / resolution)
            #     if auto_voxels > 10000000:  # 10 million voxel limit for auto-calculated bounds
            #         warnings.append("sdf: auto-calculated bounds would produce %s voxels, using default bounds instead" % int(auto_voxels))
            #         bounds = params.get("bounds", [[-2,-2,-2],[2,2,2]])
            #     else:
            #         bounds = auto_bounds
            #         warnings.append("sdf: auto-calculated bounds from SDF primitives: %s" % bounds)
            # else:
            bounds = params.get("bounds", [[-2,-2,-2],[2,2,2]])
            
            # Convert resolution and bounds from OBJ units to Rhino units (millimeters)
            warnings.append("sdf: obj_units=%s, original_resolution=%s" % (obj.meta.get("units", "millimeters"), resolution))
            warnings.append("sdf: unit_scale=%s" % unit_scale)
            if unit_scale != 1.0:
                resolution = resolution * unit_scale
                warnings.append("sdf: converted resolution to mm: %s" % resolution)
            
            # Convert bounds if they were explicitly provided (auto-calculated bounds are already in Rhino units)
            if "bounds" in params and params.get("bounds") is not None:
                bounds = [[bounds[0][0] * unit_scale, bounds[0][1] * unit_scale, bounds[0][2] * unit_scale],
                          [bounds[1][0] * unit_scale, bounds[1][1] * unit_scale, bounds[1][2] * unit_scale]]
                warnings.append("sdf: converted bounds to mm: %s" % bounds)
            else:
                # Default bounds are in meters, need to convert
                bounds = [[bounds[0][0] * unit_scale, bounds[0][1] * unit_scale, bounds[0][2] * unit_scale],
                          [bounds[1][0] * unit_scale, bounds[1][1] * unit_scale, bounds[1][2] * unit_scale]]
                warnings.append("sdf: converted default bounds to mm: %s" % bounds)
            
            # Simple voxel approximation: sample SDF on grid and emit voxel faces
            mesh = _sdf_to_voxel_mesh(expr, bounds, resolution, warnings=warnings)
            if mesh is None:
                warnings.append("sdf: voxel approximation failed for '%s', falling back to Brep" % obj.name)
                method = "brep"
            else:
                return mesh

    # Original Rhino Brep approach
    solids = {}
    if isinstance(sdf_registry, dict):
        solids.update(sdf_registry)
    last = None
    want_mesh = False
    mesh_resolution = 0.15
    # SDF deformers (noise_displace, twist, bend, displace) have no Brep
    # analogue. Queue them here so booleans in the same block can keep
    # operating on Breps; apply after mesh_from_sdf expands to a Mesh.
    pending_mesh_ops = []
    for op in sdf_ops:
        name = str(op.get("op", "")).lower()
        if name == "sphere":
            cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
            r = float(op.get("radius", 1.0))
            g = rg.Sphere(rg.Point3d(cx, cy, cz), r).ToBrep()
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = g
            last = g
        elif name == "cylinder":
            cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
            r = float(op.get("radius", 1.0))
            h = float(op.get("height", 1.0))
            circle = rg.Circle(rg.Plane(rg.Point3d(cx, cy, cz), rg.Vector3d.ZAxis), r)
            g = rg.Cylinder(circle, h).ToBrep(True, True)
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = g
            last = g
        elif name == "box":
            cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
            sx, sy, sz = _sdf_vec3(op, "size", (1.0, 1.0, 1.0))
            plane = rg.Plane(rg.Point3d(cx, cy, cz), rg.Vector3d.ZAxis)
            g = rg.Box(plane, rg.Interval(-sx/2.0, sx/2.0), rg.Interval(-sy/2.0, sy/2.0), rg.Interval(-sz/2.0, sz/2.0)).ToBrep()
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = g
            last = g
        elif name == "subtract":
            # Accept `subtract A B`, `subtract id_a=A id_b=B`, or `subtract ids=A,B`.
            pos = op.get("_args", []) or []
            id_a = _clean_ref(op.get("id_a", pos[0] if len(pos) >= 1 else ""))
            id_b = _clean_ref(op.get("id_b", pos[1] if len(pos) >= 2 else ""))
            if not (id_a and id_b) and "ids" in op:
                parts = [p.strip() for p in str(op.get("ids", "")).split(",") if p.strip()]
                if len(parts) >= 2:
                    id_a, id_b = parts[0], parts[1]
            a = _coerce_single_brep(solids.get(id_a))
            b = _coerce_single_brep(solids.get(id_b))
            if a is not None and b is not None:
                diff = rg.Brep.CreateBooleanDifference(a, b, 0.01)
                if diff and len(diff) > 0:
                    last = diff[0]
                    sid = _clean_ref(op.get("id", ""))
                    if sid:
                        solids[sid] = last
            else:
                warnings.append("sdf subtract missing id_a/id_b geometry on '%s' (id_a=%s, id_b=%s)" % (obj.name, id_a, id_b))
        elif name == "union":
            # Accept `union A B [C...]`, `union ids=A,B,...`.
            pos = op.get("_args", []) or []
            if "ids" in op:
                ids = [p.strip() for p in str(op.get("ids", "")).split(",") if p.strip()]
            else:
                ids = [_clean_ref(a) for a in pos if _clean_ref(a)]
            geoms = [_coerce_single_brep(solids.get(i)) for i in ids]
            geoms = [g for g in geoms if g is not None]
            if len(geoms) >= 2:
                u = rg.Brep.CreateBooleanUnion(geoms, 0.01)
                if u and len(u) > 0:
                    last = u[0]
                    sid = _clean_ref(op.get("id", ""))
                    if sid:
                        solids[sid] = last
            else:
                warnings.append("sdf union needs at least two known solids on '%s' (ids=%s)" % (obj.name, ids))
        elif name == "capsule":
            g = _build_capsule_brep(op)
            if g is None:
                warnings.append("sdf capsule could not be built on '%s'" % obj.name)
                continue
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = g
            last = g
        elif name == "torus":
            g = _build_torus_brep(op)
            if g is None:
                warnings.append("sdf torus could not be built on '%s'" % obj.name)
                continue
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = g
            last = g
        elif name == "cone":
            g = _build_cone_brep(op)
            if g is None:
                warnings.append("sdf cone could not be built on '%s'" % obj.name)
                continue
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = g
            last = g
        elif name == "plane":
            g = _build_plane_brep(op)
            if g is None:
                warnings.append("sdf plane could not be built on '%s'" % obj.name)
                continue
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = g
            last = g
        elif name == "smooth_union":
            # Rhino has no native SDF smooth-union; approximate by regular
            # boolean-union then filleting the seam edges to the requested
            # radius. If fillet fails (common on tangential contact), fall
            # back to the plain union so we don't lose the geometry.
            pos = op.get("_args", []) or []
            if "ids" in op:
                ids = [p.strip() for p in str(op.get("ids", "")).split(",") if p.strip()]
            else:
                ids = [_clean_ref(a) for a in pos if _clean_ref(a)]
            geoms = [_coerce_single_brep(solids.get(i)) for i in ids]
            geoms = [g for g in geoms if g is not None]
            blend = float(op.get("radius", op.get("blend", 0.1)))
            if len(geoms) >= 2:
                u = rg.Brep.CreateBooleanUnion(geoms, 0.01)
                if u and len(u) > 0:
                    base_u = u[0]
                    filleted = None
                    try:
                        edge_ids = [e.EdgeIndex for e in base_u.Edges if e.Valence == rg.EdgeAdjacency.Interior]
                        if edge_ids:
                            rads = [blend] * len(edge_ids)
                            f = rg.Brep.CreateFilletEdges(
                                base_u, edge_ids, rads, rads,
                                rg.BlendType.Fillet, rg.RailType.RollingBall, 0.01
                            )
                            if f and len(f) > 0:
                                filleted = f[0]
                    except Exception as ex:
                        warnings.append("sdf smooth_union fillet failed on '%s': %s" % (obj.name, ex))
                    last = filleted if filleted is not None else base_u
                    sid = _clean_ref(op.get("id", ""))
                    if sid:
                        solids[sid] = last
            else:
                warnings.append("sdf smooth_union needs at least two known solids on '%s' (ids=%s)" % (obj.name, ids))
        elif name == "noise_displace":
            # SDF-level noise displacement has no Brep equivalent. Defer it
            # until after mesh_from_sdf runs so subsequent SDF booleans still
            # operate on a Brep.
            pending_mesh_ops.append({
                "kind": "noise_displace",
                "strength": float(op.get("strength", 0.1)),
                "frequency": float(op.get("frequency", 3.0)),
                "seed": int(op.get("seed", 0)),
            })
        elif name == "twist":
            pending_mesh_ops.append({
                "kind": "twist",
                "axis": str(op.get("axis", "z")).lower(),
                "angle_deg": float(op.get("angle_deg", op.get("angle", 30.0))),
            })
        elif name == "bend":
            pending_mesh_ops.append({
                "kind": "bend",
                "axis": str(op.get("axis", "x")).lower(),
                "angle_deg": float(op.get("angle_deg", op.get("angle", 20.0))),
            })
        elif name == "displace":
            pending_mesh_ops.append({
                "kind": "displace",
                "amount": float(op.get("amount", op.get("strength", 0.1))),
                "direction": op.get("direction", op.get("normal")),
            })
        elif name == "repeat":
            # SDF domain repetition: duplicate `last` `count` times along
            # `axis` with `spacing`. Applied immediately so booleans after
            # the repeat operate on the array.
            if last is None:
                warnings.append("sdf repeat on '%s' has no current solid" % obj.name)
                continue
            count = max(1, int(op.get("count", 2)))
            spacing = float(op.get("spacing", 1.0))
            axis = str(op.get("axis", "x")).lower()
            if axis == "y":
                step = rg.Vector3d(0.0, spacing, 0.0)
            elif axis == "z":
                step = rg.Vector3d(0.0, 0.0, spacing)
            else:
                step = rg.Vector3d(spacing, 0.0, 0.0)
            copies = []
            for i in range(count):
                c = last.DuplicateBrep() if isinstance(last, rg.Brep) else None
                if c is None:
                    continue
                c.Transform(rg.Transform.Translation(step.X * i, step.Y * i, step.Z * i))
                copies.append(c)
            if len(copies) >= 2:
                u = rg.Brep.CreateBooleanUnion(copies, 0.01)
                last = u[0] if (u and len(u) > 0) else copies[0]
            elif copies:
                last = copies[0]
            sid = _clean_ref(op.get("id", ""))
            if sid:
                solids[sid] = last
        elif name == "mesh_from_sdf":
            want_mesh = True
            if op.get("resolution") is not None:
                try:
                    mesh_resolution = float(op.get("resolution"))
                except Exception:
                    pass
            continue
        else:
            warnings.append("unsupported sdf op on '%s': %s" % (obj.name, name))

    if want_mesh and isinstance(last, rg.Brep):
        mesh = _mesh_from_brep(last, mesh_resolution, warnings=warnings)
        if mesh is not None:
            last = mesh
        else:
            warnings.append("mesh_from_sdf failed to mesh brep on '%s'" % obj.name)
    # If any SDF-level deformers were queued, apply them now on the mesh.
    if pending_mesh_ops:
        if isinstance(last, rg.Brep):
            meshed = _mesh_from_brep(last, mesh_resolution, warnings=warnings)
            if meshed is not None:
                last = meshed
        if isinstance(last, rg.Mesh):
            for pending in pending_mesh_ops:
                _apply_sdf_mesh_op(last, pending)
            last.Normals.ComputeNormals()
    return last


def _apply_sdf_mesh_op(mesh, pending):
    """Apply a deferred SDF deformer (noise_displace/twist/bend/displace) to a mesh in place.

    These run only after `mesh_from_sdf` because Rhino has no SDF-domain
    equivalent. Helpers from the top-level op layer are reused so behavior
    matches the corresponding mesh ops.
    """
    kind = pending.get("kind")
    if kind == "noise_displace":
        strength = float(pending.get("strength", 0.1))
        freq = float(pending.get("frequency", 3.0))
        phase = float(pending.get("seed", 0)) * 0.173
        for i in range(mesh.Vertices.Count):
            v = mesh.Vertices[i]
            # Cheap tri-axis sinusoid stand-in for gradient noise.
            n = (math.sin(v.X * freq + phase) *
                 math.cos(v.Y * freq + phase * 1.3) *
                 math.sin(v.Z * freq + phase * 0.7))
            mesh.Vertices.SetVertex(
                i,
                v.X + n * strength,
                v.Y + n * strength * 0.6,
                v.Z + n * strength * 0.4,
            )
    elif kind == "twist":
        _mesh_twist_inplace(mesh, pending.get("axis", "z"), pending.get("angle_deg", 0.0))
    elif kind == "bend":
        _mesh_bend_inplace(mesh, pending.get("axis", "x"), pending.get("angle_deg", 0.0))
    elif kind == "displace":
        amount = float(pending.get("amount", 0.0))
        direction = pending.get("direction")
        if isinstance(direction, (list, tuple)) and len(direction) >= 3:
            # Uniform vector displacement.
            dx, dy, dz = float(direction[0]) * amount, float(direction[1]) * amount, float(direction[2]) * amount
            for i in range(mesh.Vertices.Count):
                v = mesh.Vertices[i]
                mesh.Vertices.SetVertex(i, v.X + dx, v.Y + dy, v.Z + dz)
        else:
            # Along-normal displacement. Falls back to a no-op if the mesh
            # has no vertex normals.
            try:
                mesh.Normals.ComputeNormals()
                for i in range(mesh.Vertices.Count):
                    v = mesh.Vertices[i]
                    n = mesh.Normals[i] if i < mesh.Normals.Count else None
                    if n is None:
                        continue
                    mesh.Vertices.SetVertex(i, v.X + n.X * amount, v.Y + n.Y * amount, v.Z + n.Z * amount)
            except Exception:
                pass


def prebuild_sdf_registry(objs, warnings):
    registry = {}
    for obj in objs:
        if str(obj.meta.get("source", "")).lower() != "sdf":
            continue
        for op in obj.meta.get("sdf_ops", []):
            name = str(op.get("op", "")).lower()
            sid = _clean_ref(op.get("id", "")).strip()
            if not sid:
                continue
            try:
                if name == "sphere":
                    cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
                    r = float(op.get("radius", 1.0))
                    g = rg.Sphere(rg.Point3d(cx, cy, cz), r).ToBrep()
                    registry[sid] = g
                    registry[_clean_ref(obj.name)] = g
                elif name == "cylinder":
                    cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
                    r = float(op.get("radius", 1.0))
                    h = float(op.get("height", 1.0))
                    circle = rg.Circle(rg.Plane(rg.Point3d(cx, cy, cz), rg.Vector3d.ZAxis), r)
                    g = rg.Cylinder(circle, h).ToBrep(True, True)
                    registry[sid] = g
                    registry[_clean_ref(obj.name)] = g
                elif name == "box":
                    cx, cy, cz = _sdf_vec3(op, "center", (0.0, 0.0, 0.0))
                    sx, sy, sz = _sdf_vec3(op, "size", (1.0, 1.0, 1.0))
                    plane = rg.Plane(rg.Point3d(cx, cy, cz), rg.Vector3d.ZAxis)
                    g = rg.Box(plane, rg.Interval(-sx/2.0, sx/2.0), rg.Interval(-sy/2.0, sy/2.0), rg.Interval(-sz/2.0, sz/2.0)).ToBrep()
                    registry[sid] = g
                    registry[_clean_ref(obj.name)] = g
                elif name == "capsule":
                    g = _build_capsule_brep(op)
                    if g is not None:
                        registry[sid] = g
                        registry[_clean_ref(obj.name)] = g
                elif name == "torus":
                    g = _build_torus_brep(op)
                    if g is not None:
                        registry[sid] = g
                        registry[_clean_ref(obj.name)] = g
                elif name == "cone":
                    g = _build_cone_brep(op)
                    if g is not None:
                        registry[sid] = g
                        registry[_clean_ref(obj.name)] = g
                elif name == "plane":
                    g = _build_plane_brep(op)
                    if g is not None:
                        registry[sid] = g
                        registry[_clean_ref(obj.name)] = g
            except Exception as ex:
                warnings.append("sdf prebuild failed for id '%s': %s" % (sid, ex))
    return registry


def _axis_bounds(bb, axis):
    """Return (min, max, span) along a named axis ('x'/'y'/'z')."""
    a = (axis or "z").lower()
    if a == "x":
        lo, hi = bb.Min.X, bb.Max.X
    elif a == "y":
        lo, hi = bb.Min.Y, bb.Max.Y
    else:
        lo, hi = bb.Min.Z, bb.Max.Z
    return lo, hi, max(1e-9, hi - lo)


def _mesh_twist_inplace(mesh, axis, angle_deg):
    """Rotate cross-sections progressively along `axis` by up to `angle_deg`."""
    bb = mesh.GetBoundingBox(True)
    lo, _, span = _axis_bounds(bb, axis)
    rad = math.radians(float(angle_deg))
    a = (axis or "z").lower()
    for i in range(mesh.Vertices.Count):
        v = mesh.Vertices[i]
        if a == "x":
            t = (v.X - lo) / span
            theta = rad * t
            c, s = math.cos(theta), math.sin(theta)
            y = v.Y * c - v.Z * s
            z = v.Y * s + v.Z * c
            mesh.Vertices.SetVertex(i, v.X, y, z)
        elif a == "y":
            t = (v.Y - lo) / span
            theta = rad * t
            c, s = math.cos(theta), math.sin(theta)
            x = v.X * c - v.Z * s
            z = v.X * s + v.Z * c
            mesh.Vertices.SetVertex(i, x, v.Y, z)
        else:
            t = (v.Z - lo) / span
            theta = rad * t
            c, s = math.cos(theta), math.sin(theta)
            x = v.X * c - v.Y * s
            y = v.X * s + v.Y * c
            mesh.Vertices.SetVertex(i, x, y, v.Z)


def _mesh_taper_inplace(mesh, axis, factor):
    """Scale cross-sections perpendicular to `axis` by 1 - factor*t."""
    bb = mesh.GetBoundingBox(True)
    lo, _, span = _axis_bounds(bb, axis)
    a = (axis or "z").lower()
    f = float(factor)
    for i in range(mesh.Vertices.Count):
        v = mesh.Vertices[i]
        if a == "x":
            t = (v.X - lo) / span
            s = 1.0 - f * t
            mesh.Vertices.SetVertex(i, v.X, v.Y * s, v.Z * s)
        elif a == "y":
            t = (v.Y - lo) / span
            s = 1.0 - f * t
            mesh.Vertices.SetVertex(i, v.X * s, v.Y, v.Z * s)
        else:
            t = (v.Z - lo) / span
            s = 1.0 - f * t
            mesh.Vertices.SetVertex(i, v.X * s, v.Y * s, v.Z)


def _mesh_bend_inplace(mesh, axis, angle_deg):
    """Progressive rotation around `axis` based on position along `axis`."""
    bb = mesh.GetBoundingBox(True)
    lo, _, span = _axis_bounds(bb, axis)
    rad = math.radians(float(angle_deg))
    a = (axis or "x").lower()
    for i in range(mesh.Vertices.Count):
        v = mesh.Vertices[i]
        if a == "x":
            t = (v.X - lo) / span
            theta = rad * t
            c, s = math.cos(theta), math.sin(theta)
            y = v.Y * c - v.Z * s
            z = v.Y * s + v.Z * c
            mesh.Vertices.SetVertex(i, v.X, y, z)
        elif a == "y":
            t = (v.Y - lo) / span
            theta = rad * t
            c, s = math.cos(theta), math.sin(theta)
            x = v.X * c - v.Z * s
            z = v.X * s + v.Z * c
            mesh.Vertices.SetVertex(i, x, v.Y, z)
        else:
            t = (v.Z - lo) / span
            theta = rad * t
            c, s = math.cos(theta), math.sin(theta)
            x = v.X * c - v.Y * s
            y = v.X * s + v.Y * c
            mesh.Vertices.SetVertex(i, x, y, v.Z)


def _mesh_wave_inplace(mesh, amplitude, frequency):
    """Displace `z` by `amp * sin(x*f) * cos(y*f)`."""
    amp = float(amplitude)
    freq = float(frequency)
    for i in range(mesh.Vertices.Count):
        v = mesh.Vertices[i]
        dz = amp * math.sin(v.X * freq) * math.cos(v.Y * freq)
        mesh.Vertices.SetVertex(i, v.X, v.Y, v.Z + dz)


def apply_deformer(mesh, obj, warnings):
    meta = obj.meta
    deformer = str(meta.get("deformer", "")).lower()
    if not deformer:
        return mesh

    p = meta.get("params", {}) if isinstance(meta.get("params", {}), dict) else {}
    m = mesh.DuplicateMesh()
    if m.Vertices.Count == 0:
        return m

    axis = str(p.get("axis", "z")).lower()
    if deformer == "twist":
        _mesh_twist_inplace(m, axis, p.get("angle_deg", p.get("angle", 30.0)))
    elif deformer == "taper":
        _mesh_taper_inplace(m, axis, p.get("factor", p.get("amount", 0.5)))
    elif deformer == "wave":
        _mesh_wave_inplace(m, p.get("amplitude", 0.4), p.get("frequency", 1.0))
    elif deformer == "bend":
        _mesh_bend_inplace(m, str(p.get("axis", "x")).lower(), p.get("angle_deg", p.get("angle", 20.0)))
    else:
        warnings.append("unsupported deformer on '%s': %s" % (obj.name, deformer))
        return mesh

    m.Normals.ComputeNormals()
    m.Compact()
    return m


def build_simulation_geometry(obj, p, warnings):
    sim = str(obj.meta.get("sim", "")).lower()
    seed = int(p.get("seed", 1))
    rnd = random.Random(seed)

    if sim == "boids":
        agents = max(1, int(p.get("agents", 24)))
        steps = max(2, int(p.get("steps", 60)))
        bx, by, bz = _vec3(p, "bounds", (10.0, 10.0, 10.0))
        curves = []
        for _ in range(agents):
            pts = []
            x, y, z = rnd.uniform(-bx / 2, bx / 2), rnd.uniform(-by / 2, by / 2), rnd.uniform(-bz / 2, bz / 2)
            for _ in range(steps):
                x += rnd.uniform(-0.25, 0.25)
                y += rnd.uniform(-0.25, 0.25)
                z += rnd.uniform(-0.25, 0.25)
                x, y, z = max(-bx / 2, min(bx / 2, x)), max(-by / 2, min(by / 2, y)), max(-bz / 2, min(bz / 2, z))
                pts.append(rg.Point3d(x, y, z))
            curves.append(rg.Polyline(pts).ToNurbsCurve())
        return curves

    if sim == "differential_growth":
        n = max(8, int(p.get("points", 48)))
        r = float(p.get("radius", 5.0))
        amp = float(p.get("noise", 0.35))
        pts = []
        for i in range(n + 1):
            t = 2 * math.pi * (i / float(n))
            rr = r + rnd.uniform(-amp, amp)
            pts.append(rg.Point3d(rr * math.cos(t), rr * math.sin(t), 0.0))
        return rg.Polyline(pts).ToNurbsCurve()

    if sim == "cellular_automata":
        gx, gy, gz = _vec3(p, "grid", (8, 8, 4))
        cell = float(p.get("cell", 1.0))
        prob = float(p.get("fill", 0.18))
        boxes = []
        for ix in range(int(gx)):
            for iy in range(int(gy)):
                for iz in range(int(gz)):
                    if rnd.random() <= prob:
                        x = (ix - gx / 2.0) * cell
                        y = (iy - gy / 2.0) * cell
                        z = (iz - gz / 2.0) * cell
                        plane = rg.Plane(rg.Point3d(x, y, z), rg.Vector3d.ZAxis)
                        b = rg.Box(plane, rg.Interval(-cell / 2, cell / 2), rg.Interval(-cell / 2, cell / 2), rg.Interval(-cell / 2, cell / 2))
                        boxes.append(b.ToBrep())
        return boxes

    warnings.append("unsupported simulation type on '%s': %s" % (obj.name, sim))
    return None


def build_procedural_advanced(obj, warnings):
    p = obj.meta.get("params", {}) if isinstance(obj.meta.get("params", {}), dict) else {}
    typ = str(obj.meta.get("type", "")).lower()
    if typ == "extrude":
        profile = p.get("profile", [])
        h = float(p.get("height", 1.0))
        if isinstance(profile, list) and len(profile) >= 2:
            crv = rg.Polyline([_to_pt(q) for q in profile] + [_to_pt(profile[0])]).ToNurbsCurve()
            return rg.Extrusion.Create(crv, h, True)
    if typ == "loft":
        sections = p.get("sections", [])
        if isinstance(sections, list) and len(sections) >= 2:
            curves = []
            for sec in sections:
                if isinstance(sec, list) and len(sec) >= 2:
                    curves.append(rg.Polyline([_to_pt(q) for q in sec]).ToNurbsCurve())
            if len(curves) >= 2:
                breps = rg.Brep.CreateFromLoft(curves, rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Normal, False)
                if breps and len(breps) > 0:
                    return breps
    if typ == "sweep":
        rail = p.get("rail", [])
        profile = p.get("profile", [])
        if isinstance(rail, list) and len(rail) >= 2 and isinstance(profile, list) and len(profile) >= 2:
            rail_crv = rg.Polyline([_to_pt(q) for q in rail]).ToNurbsCurve()
            profile_crv = rg.Polyline([_to_pt(q) for q in profile] + [_to_pt(profile[0])]).ToNurbsCurve()
            sw = rg.SweepOneRail()
            breps = sw.PerformSweep(rail_crv, profile_crv)
            if breps and len(breps) > 0:
                return breps
    return None


def apply_native_ops(geom, ops, warnings):
    out = geom

    def each_geom(g):
        return g if isinstance(g, list) else [g]

    def to_meshes(g):
        meshes = []
        for item in each_geom(g):
            if isinstance(item, rg.Mesh):
                meshes.append(item)
            elif isinstance(item, rg.Brep):
                msh = rg.Mesh.CreateFromBrep(item, rg.MeshingParameters.FastRenderMesh)
                if msh:
                    m = rg.Mesh()
                    for mm in msh:
                        m.Append(mm)
                    meshes.append(m)
        return meshes

    for op in ops:
        name = str(op.get("op", "")).lower()
        if name == "array":
            name = "array_linear"
        if name == "move":
            dx, dy, dz = _vec3(op, "offset", (0.0, 0.0, 0.0))
            xform = rg.Transform.Translation(dx, dy, dz)
            if isinstance(out, list):
                for g in out:
                    g.Transform(xform)
            else:
                out.Transform(xform)
        elif name == "scale":
            s = float(op.get("factor", 1.0))
            xform = rg.Transform.Scale(rg.Point3d.Origin, s)
            if isinstance(out, list):
                for g in out:
                    g.Transform(xform)
            else:
                out.Transform(xform)
        elif name == "rotate":
            a = math.radians(float(op.get("angle_deg", op.get("angle", 0.0))))
            axis = _vec3(op, "axis", (0.0, 0.0, 1.0))
            xform = rg.Transform.Rotation(a, rg.Vector3d(*axis), rg.Point3d.Origin)
            if isinstance(out, list):
                for g in out:
                    g.Transform(xform)
            else:
                out.Transform(xform)
        elif name == "mirror":
            nx, ny, nz = _vec3(op, "normal", (1.0, 0.0, 0.0))
            ox, oy, oz = _vec3(op, "origin", (0.0, 0.0, 0.0))
            plane = rg.Plane(rg.Point3d(ox, oy, oz), rg.Vector3d(nx, ny, nz))
            xform = rg.Transform.Mirror(plane)
            if isinstance(out, list):
                mirrored = []
                for g in out:
                    c = g.Duplicate()
                    c.Transform(xform)
                    mirrored.append(c)
                out.extend(mirrored)
            else:
                c = out.Duplicate()
                c.Transform(xform)
                out = [out, c]
        elif name == "array_linear":
            count = max(1, int(op.get("count", 2)))
            dx, dy, dz = _vec3(op, "step", _vec3(op, "offset", (1.0, 0.0, 0.0)))
            base = each_geom(out)
            clones = []
            for i in range(count):
                xf = rg.Transform.Translation(dx * i, dy * i, dz * i)
                for g in base:
                    c = g.Duplicate()
                    c.Transform(xf)
                    clones.append(c)
            out = clones
        elif name == "radial_array":
            count = max(1, int(op.get("count", 6)))
            angle_deg = float(op.get("angle_deg", 360.0))
            axis = _vec3(op, "axis", (0.0, 0.0, 1.0))
            center = _vec3(op, "center", (0.0, 0.0, 0.0))
            base = each_geom(out)
            clones = []
            for i in range(count):
                a = math.radians(angle_deg) * (float(i) / float(max(1, count)))
                xf = rg.Transform.Rotation(a, rg.Vector3d(*axis), rg.Point3d(*center))
                for g in base:
                    c = g.Duplicate()
                    c.Transform(xf)
                    clones.append(c)
            out = clones
        elif name in {"displace", "noise_displace"}:
            amp = float(op.get("strength", op.get("amplitude", 0.25)))
            for g in each_geom(out):
                if isinstance(g, rg.Mesh):
                    for i in range(g.Vertices.Count):
                        v = g.Vertices[i]
                        dz = amp * math.sin(v.X * 0.7) * math.cos(v.Y * 0.7)
                        g.Vertices.SetVertex(i, v.X, v.Y, v.Z + dz)
                    g.Normals.ComputeNormals()
        elif name == "subdivide":
            result = []
            for g in each_geom(out):
                if isinstance(g, rg.Mesh):
                    m = g.DuplicateMesh()
                    m.Subdivide(1)
                    result.append(m)
                else:
                    result.append(g)
            out = result if isinstance(out, list) else result[0]
        elif name == "smooth":
            iters = max(1, int(op.get("iterations", 1)))
            # Live OBJ spec uses `strength`; older scripts used `factor`.
            strength = float(op.get("strength", op.get("factor", 0.5)))
            geoms = each_geom(out)
            new_list = []
            for g in geoms:
                if isinstance(g, rg.Mesh):
                    g = _prepare_mesh_for_smooth(g, warnings=warnings) or g
                    ok = _smooth_mesh_safe(g, iters, strength)
                    if not ok:
                        warnings.append("smooth not supported for current Rhino mesh API")
                    g.Normals.ComputeNormals()
                new_list.append(g)
            out = new_list if isinstance(out, list) else new_list[0]
        elif name == "simplify":
            ratio = float(op.get("ratio", 0.5))
            target = max(4, int(1000 * max(0.05, min(1.0, ratio))))
            result = []
            for g in each_geom(out):
                if isinstance(g, rg.Mesh):
                    m = g.DuplicateMesh()
                    m.Reduce(target, False, 10, True)
                    result.append(m)
                else:
                    result.append(g)
            out = result if isinstance(out, list) else result[0]
        elif name == "remesh":
            edge = float(op.get("target_edge", op.get("edge_length", 1.0)))
            result = []
            for g in each_geom(out):
                if isinstance(g, rg.Mesh):
                    p = rg.MeshingParameters()
                    p.MaximumEdgeLength = max(0.001, edge)
                    p.MinimumEdgeLength = max(0.0005, edge * 0.25)
                    p.SimplePlanes = True
                    breps = rg.Brep.CreateFromMesh(g, True)
                    if breps:
                        msh = rg.Mesh.CreateFromBrep(breps[0], p)
                        if msh:
                            mm = rg.Mesh()
                            for part in msh:
                                mm.Append(part)
                            result.append(mm)
                            continue
                result.append(g)
            out = result if isinstance(out, list) else result[0]
        elif name in {"bevel", "chamfer"}:
            dist = float(op.get("distance", 0.2))
            result = []
            for g in each_geom(out):
                if isinstance(g, rg.Brep):
                    edges = [e.EdgeIndex for e in g.Edges]
                    if name == "chamfer":
                        b = g.ChamferEdges(edges, [dist] * len(edges), [dist] * len(edges), 1e-3)
                    else:
                        b = g.FilletEdges(edges, [dist] * len(edges), [dist] * len(edges), rg.BlendType.Fillet, rg.RailType.RollingBall, 1e-3)
                    if b:
                        result.extend(list(b))
                        continue
                result.append(g)
            out = result if isinstance(out, list) else result[0]
        elif name == "trace_paths":
            curves = []
            for m in to_meshes(out):
                topo = m.TopologyEdges
                for i in range(min(topo.Count, int(op.get("max_paths", 64)))):
                    crv = topo.EdgeLine(i).ToNurbsCurve()
                    curves.append(crv)
            out = curves
        elif name == "sdf_tubes":
            radius = float(op.get("radius", 0.1))
            pipes = []
            for g in each_geom(out):
                if isinstance(g, rg.Curve):
                    b = rg.Brep.CreatePipe(g, radius, False, rg.PipeCapMode.Round, True, 0.01, 0.1)
                    if b:
                        pipes.extend(list(b))
            out = pipes if pipes else out
        elif name == "voxelize":
            cell = float(op.get("cell", 1.0))
            vox = []
            for m in to_meshes(out):
                bb = m.GetBoundingBox(True)
                nx = max(1, int((bb.Max.X - bb.Min.X) / cell))
                ny = max(1, int((bb.Max.Y - bb.Min.Y) / cell))
                nz = max(1, int((bb.Max.Z - bb.Min.Z) / cell))
                for ix in range(nx):
                    for iy in range(ny):
                        for iz in range(nz):
                            x = bb.Min.X + (ix + 0.5) * cell
                            y = bb.Min.Y + (iy + 0.5) * cell
                            z = bb.Min.Z + (iz + 0.5) * cell
                            if m.IsPointInside(rg.Point3d(x, y, z), 0.001, False):
                                plane = rg.Plane(rg.Point3d(x, y, z), rg.Vector3d.ZAxis)
                                box = rg.Box(plane, rg.Interval(-cell / 2, cell / 2), rg.Interval(-cell / 2, cell / 2), rg.Interval(-cell / 2, cell / 2))
                                vox.append(box.ToBrep())
            out = vox if vox else out
        elif name == "mesh_from_volume":
            cell = float(op.get("cell", 1.0))
            meshes = []
            for g in each_geom(out):
                if isinstance(g, rg.Brep):
                    msh = rg.Mesh.CreateFromBrep(g, rg.MeshingParameters.FastRenderMesh)
                    if msh:
                        m = rg.Mesh()
                        for part in msh:
                            m.Append(part)
                        meshes.append(m)
            out = meshes if meshes else out
        elif name == "tread":
            count = max(1, int(op.get("count", 16)))
            rise = float(op.get("rise", 0.2))
            run = float(op.get("run", 0.4))
            treads = []
            base = rg.Box(rg.Plane.WorldXY, rg.Interval(-run / 2, run / 2), rg.Interval(-0.5, 0.5), rg.Interval(0, 0.1)).ToBrep()
            for i in range(count):
                b = base.DuplicateBrep()
                b.Transform(rg.Transform.Translation(i * run, 0, i * rise))
                treads.append(b)
            out = treads
        elif name in {"union", "subtract", "intersect"}:
            geoms = [g for g in each_geom(out) if isinstance(g, rg.Brep)]
            if len(geoms) >= 2:
                a = geoms[0]
                bs = geoms[1:]
                if name == "union":
                    u = rg.Brep.CreateBooleanUnion(geoms, 0.01)
                    if u:
                        out = list(u)
                elif name == "subtract":
                    # Union multiple subtractors first, then subtract the result
                    if len(bs) == 1:
                        d = rg.Brep.CreateBooleanDifference(a, [bs[0]], 0.01)
                    else:
                        u = rg.Brep.CreateBooleanUnion(bs, 0.01)
                        if u and len(u) > 0:
                            d = rg.Brep.CreateBooleanDifference(a, u, 0.01)
                        else:
                            d = None
                    if d:
                        out = list(d)
                else:
                    # Intersect all geometries
                    inter = rg.Brep.CreateBooleanIntersection(geoms, 0.01)
                    if inter:
                        out = list(inter)
        elif name in {"taper", "twist", "bend"}:
            # Whole-object deformers applied to meshes. Brep inputs are meshed
            # first since there's no Brep-level equivalent.
            axis = str(op.get("axis", "x" if name == "bend" else "z")).lower()
            amount = op.get("angle_deg", op.get("angle", op.get("factor", op.get("amount", 0.0))))
            new_list = []
            for g in each_geom(out):
                target = g
                if isinstance(target, rg.Brep):
                    target = _mesh_from_brep(target, 0.1, warnings=warnings)
                if isinstance(target, rg.Mesh):
                    target = target.DuplicateMesh()
                    if name == "taper":
                        _mesh_taper_inplace(target, axis, amount)
                    elif name == "twist":
                        _mesh_twist_inplace(target, axis, amount)
                    else:
                        _mesh_bend_inplace(target, axis, amount)
                    target.Normals.ComputeNormals()
                new_list.append(target if target is not None else g)
            out = new_list if isinstance(out, list) else new_list[0]
        elif name in {"shell", "thicken", "offset"}:
            # Brep-only: inward shell using Rhino's CreateShell. `thickness` can
            # be negative to shell outward; `offset` maps to signed shell.
            thickness = float(op.get("thickness", op.get("amount", op.get("distance", 0.05))))
            result = []
            for g in each_geom(out):
                if isinstance(g, rg.Brep):
                    try:
                        # Remove the top face by default so the shell has an opening.
                        face_ids = []
                        if g.Faces.Count > 0 and name == "shell":
                            face_ids = [g.Faces.Count - 1]
                        shelled = rg.Brep.CreateShell(g, face_ids, thickness, 0.01) if hasattr(rg.Brep, "CreateShell") else None
                        if shelled and len(shelled) > 0:
                            result.append(shelled[0])
                            continue
                    except Exception as ex:
                        warnings.append("%s failed on '%s': %s" % (name, "brep", ex))
                result.append(g)
            out = result if isinstance(out, list) else result[0]
        else:
            warnings.append("unsupported op: %s" % name)
            if STRICT_COMPAT:
                warnings.append("compat: unsupported op '%s' in strict mode" % name)
    return out


def validate_compat(obj, warnings):
    supported_sources = {"procedural", "simulation", "llm_mesh", "assembly", "sdf", ""}
    supported_types = {
        "box", "sphere", "cylinder", "cone", "polyline",
        "extrude", "loft", "sweep", "revolve", "lathe",
        "surface_grid", "heightfield", "mesh", "curve", "",
    }
    supported_sims = {"boids", "differential_growth", "cellular_automata", ""}
    supported_deformers = {"twist", "taper", "wave", "bend", ""}

    supported_sdf_ops = {
        "sphere", "box", "cylinder", "capsule", "torus", "cone", "plane",
        "union", "subtract", "intersect", "smooth_union",
        "repeat", "twist", "bend", "displace", "noise_displace",
        "mesh_from_sdf", "",
    }
    supported_ops = {
        "move", "scale", "rotate", "mirror",
        "array", "array_linear", "radial_array",
        "displace", "noise_displace", "subdivide",
        "smooth", "simplify", "remesh",
        "bevel", "chamfer", "trace_paths", "sdf_tubes",
        "voxelize", "mesh_from_volume", "tread",
        "union", "subtract", "intersect",
        "taper", "twist", "bend",
        "shell", "thicken", "offset",
    }

    source = str(obj.meta.get("source", "")).lower()
    typ = str(obj.meta.get("type", "")).lower()
    sim = str(obj.meta.get("sim", "")).lower()
    deformer = str(obj.meta.get("deformer", "")).lower()

    if source not in supported_sources:
        warnings.append("compat: unsupported source on '%s': %s" % (obj.name, source))
    if typ not in supported_types:
        warnings.append("compat: unsupported type on '%s': %s" % (obj.name, typ))
    if sim not in supported_sims:
        warnings.append("compat: unsupported sim on '%s': %s" % (obj.name, sim))
    if deformer not in supported_deformers:
        warnings.append("compat: unsupported deformer on '%s': %s" % (obj.name, deformer))

    for op in obj.ops:
        opname = str(op.get("op", "")).lower()
        if opname not in supported_ops:
            warnings.append("compat: unsupported op on '%s': %s" % (obj.name, opname))

    for sdfop in obj.meta.get("sdf_ops", []):
        opname = str(sdfop.get("op", "")).lower()
        if opname not in supported_sdf_ops:
            warnings.append("compat: unsupported sdf op on '%s': %s" % (obj.name, opname))


def _looks_like_obj_text(s):
    if not isinstance(s, str):
        return False
    t = s.strip()
    if not t:
        return False
    if "\n" in t or "\r" in t:
        return True
    if "#@" in t:
        return True
    if t.startswith("o ") or t.startswith("v ") or t.startswith("f "):
        return True
    return False


def _read_input_text(x_in, warnings):
    if isinstance(x_in, str):
        raw = x_in
    elif x_in is None:
        raw = ""
    else:
        try:
            raw = str(x_in)
        except Exception:
            raw = ""

    if _looks_like_obj_text(raw):
        return raw

    path = raw.strip()
    if path and os.path.isfile(path):
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception as ex:
            warnings.append("failed to read input file '%s': %s" % (path, ex))
            return ""

    if path:
        warnings.append("input does not look like OBJ text and file was not found: %s" % path)
    return ""


# ---- GHPython entrypoint ----

warn = []
text_in = _read_input_text(x, warn)
objs = parse_live_obj(text_in)

# Resolve assembly anchors first so `anchor(asm.id)` references in any
# downstream object's params/sdf_ops/ops can be substituted with vec3
# literals before the arithmetic evaluator runs.
resolve_all_anchors(objs, warn)

# `prebuild_sdf_registry` reads SDF op strings before the per-object
# resolution loop, so any `anchor(asm.id)` inside those op dicts must be
# substituted now or prebuilt geometry would be placed at the wrong
# position. Empty scope is fine: substitution only needs ANCHOR_MAP, and
# the arithmetic evaluator can already resolve the resulting list literals.
for _o in objs:
    _sdf_ops = _o.meta.get("sdf_ops")
    if isinstance(_sdf_ops, list):
        for _op_dict in _sdf_ops:
            for _k in list(_op_dict.keys()):
                _v = _op_dict[_k]
                if isinstance(_v, str) and "anchor(" in _v:
                    _op_dict[_k] = _resolve_value(_v, {})

sdf_registry = prebuild_sdf_registry(objs, warn)

# Precompute assembly param scopes so child procedural objects can resolve
# expressions like seat_width/2 and references to parent params.
assembly_params = {}
for o in objs:
    if str(o.meta.get("source", "")).lower() == "assembly":
        raw = o.meta.get("params", {})
        if isinstance(raw, dict):
            scope = {}
            for k, v in _dict_items_safe(raw):
                scope[k] = _resolve_value(v, scope)
            assembly_params[o.name] = scope

meshes = []
native = []
names = []
geom_cache = {}
obj_geoms = {}  # Track geometry per object for transform application

# First pass: build all geometry without transforms, cache it
for o in objs:
    names.append(o.name)
    if STRICT_COMPAT:
        validate_compat(o, warn)
    scope = _build_scope_for_object(o, assembly_params)
    if isinstance(o.meta.get("params", {}), dict):
        resolved = {}
        for k, v in _dict_items_safe(o.meta.get("params")):
            resolved[k] = _resolve_value(v, scope)
        o.meta["params"] = resolved
    # Anchor refs can also appear inside SDF op params (`center=anchor(...)`)
    # and top-level op params (`with=anchor(...)` etc.). Resolve them now
    # using the per-object scope so downstream builders see concrete values.
    sdf_ops = o.meta.get("sdf_ops")
    if isinstance(sdf_ops, list):
        for op_dict in sdf_ops:
            _resolve_dict_strings(op_dict, scope)
    if isinstance(o.ops, list):
        for op_dict in o.ops:
            _resolve_dict_strings(op_dict, scope)

    geom = None
    if o.vertices and o.faces:
        try:
            mesh = build_rhino_mesh(o, warnings=warn)
            mesh = apply_deformer(mesh, o, warn)
            geom = mesh
            meshes.append(mesh)
        except Exception as ex:
            warn.append("mesh build failed on '%s': %s" % (o.name, ex))

    g = build_native_geometry(o, warn, sdf_registry)
    if g is None and str(o.meta.get("source", "")).lower() == "procedural":
        g = build_procedural_advanced(o, warn)
    if g is not None and o.ops:
        g = apply_native_ops(g, o.ops, warn)
    if g is not None:
        geom = g
        if isinstance(g, list):
            native.extend(g)
        else:
            native.append(g)
    
    # Cache geometry for attach constraint resolution and transform application
    if geom is not None:
        geom_cache[o.name] = geom
        obj_geoms[o.name] = geom

# Apply attach constraints to adjust object transforms based on anchor points
_apply_attach_constraints(objs, ANCHOR_MAP, warn, geom_cache)

# Second pass: apply transforms to geometry after attach constraints have adjusted them
meshes_transformed = []
native_transformed = []
for o in objs:
    transform = o.meta.get("transform")
    # Parse transform if it's a string
    if isinstance(transform, str):
        transform = _parse_transform(transform)
    geom = obj_geoms.get(o.name)
    
    if geom is None:
        continue
    
    
    if isinstance(geom, rg.Mesh):
        # This is a mesh from obj cache
        if transform:
            geom = _apply_transform_to_geom(geom, transform)
        meshes_transformed.append(geom)
    else:
        # This is native geometry (Brep or list)
        if transform:
            geom = _apply_transform_to_geom(geom, transform)
        if isinstance(geom, list):
            native_transformed.extend(geom)
        else:
            native_transformed.append(geom)

A = meshes_transformed if meshes_transformed else meshes
B = native_transformed if native_transformed else native
C = names
D = warn
