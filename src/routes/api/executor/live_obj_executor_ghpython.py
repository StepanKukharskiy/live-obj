# Live OBJ Executor for Grasshopper (GHPython)
# Paste into a GHPython component.

import ast
import math
import os
import random
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


def _safe_eval_expr(expr, scope):
    try:
        node = ast.parse(str(expr), mode="eval")
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


def _resolve_value(v, scope):
    if isinstance(v, list):
        return [_resolve_value(x, scope) for x in v]
    if isinstance(v, tuple):
        return tuple(_resolve_value(x, scope) for x in v)
    return _resolve_scalar(v, scope)




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
        cx, cy, cz = _vec3(p, "center", (0.0, 0.0, 0.0))
        sx, sy, sz = _vec3(p, "size", (1.0, 1.0, 1.0))
        plane = rg.Plane(_to_pt((cx, cy, cz)), rg.Vector3d.ZAxis)
        return rg.Box(plane, rg.Interval(-sx / 2.0, sx / 2.0), rg.Interval(-sy / 2.0, sy / 2.0), rg.Interval(-sz / 2.0, sz / 2.0)).ToBrep()

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

    if typ:
        warnings.append("unsupported procedural type on '%s': %s" % (obj.name, typ))
    return None




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

def _sdf_vec3(op, key, default):
    raw = op.get(key, default)
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return float(raw[0]), float(raw[1]), float(raw[2])
        except Exception:
            return default
    return default


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
            a = solids.get(id_a)
            b = solids.get(id_b)
            if a is not None and b is not None:
                diff = rg.Brep.CreateBooleanDifference(a, [b], 0.01)
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
            geoms = [solids.get(i) for i in ids if solids.get(i) is not None]
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
            geoms = [solids.get(i) for i in ids if solids.get(i) is not None]
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
        elif name == "mesh_from_sdf":
            want_mesh = True
            if op.get("resolution") is not None:
                try:
                    mesh_resolution = float(op.get("resolution"))
                except Exception:
                    pass
            continue
        elif name == "repeat":
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
    """Apply a deferred SDF deformer (noise_displace/twist/bend/displace) to a mesh in place."""
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
                    d = rg.Brep.CreateBooleanDifference(a, bs, 0.01)
                    if d:
                        out = list(d)
                else:
                    inter = rg.Brep.CreateBooleanIntersection([a] + bs, 0.01)
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
    supported_types = {"box", "sphere", "cylinder", "polyline", "extrude", "loft", "sweep", ""}
    supported_sims = {"boids", "differential_growth", "cellular_automata", ""}
    supported_deformers = {"twist", "taper", "wave", "bend", ""}

    supported_sdf_ops = {"sphere", "box", "cylinder", "capsule", "torus", "union", "subtract", "intersect", "smooth_union", "repeat", "twist", "bend", "displace", "mesh_from_sdf", ""}
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

for o in objs:
    names.append(o.name)
    if STRICT_COMPAT:
        validate_compat(o, warn)
    if isinstance(o.meta.get("params", {}), dict):
        scope = _build_scope_for_object(o, assembly_params)
        resolved = {}
        for k, v in _dict_items_safe(o.meta.get("params")):
            resolved[k] = _resolve_value(v, scope)
        o.meta["params"] = resolved

    if o.vertices and o.faces:
        try:
            mesh = build_rhino_mesh(o, warnings=warn)
            mesh = apply_deformer(mesh, o, warn)
            meshes.append(mesh)
        except Exception as ex:
            warn.append("mesh build failed on '%s': %s" % (o.name, ex))

    g = build_native_geometry(o, warn, sdf_registry)
    if g is None and str(o.meta.get("source", "")).lower() == "procedural":
        g = build_procedural_advanced(o, warn)
    if g is not None and o.ops:
        g = apply_native_ops(g, o.ops, warn)
    if g is not None:
        if isinstance(g, list):
            native.extend(g)
        else:
            native.append(g)

A = meshes
B = native
C = names
D = warn
