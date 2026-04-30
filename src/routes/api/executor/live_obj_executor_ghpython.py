"""
Live OBJ Executor for Grasshopper (GHPython)

Purpose
-------
A minimal, standalone executor that can be pasted into a GHPython component.
It accepts raw OBJ or Live OBJ text from a Grasshopper Panel input and builds
native Rhino/Grasshopper geometry.

Input (GHPython)
----------------
x: str
    OBJ or Live OBJ text. Live OBJ metadata lines begin with '#@'.

Outputs (suggested)
-------------------
A: list[Rhino.Geometry.Mesh]      Parsed mesh objects from v/f sections.
B: list[Rhino.Geometry.GeometryBase]  Metadata-driven native geometry.
C: list[str]                      Object names.
D: list[str]                      Parse/execution warnings.

Supported metadata (native geometry path)
-----------------------------------------
- #@source: procedural
- #@type: box | sphere | cylinder | polyline
- #@params: key=value, ...

Example:
    o demo_box
    #@source: procedural
    #@type: box
    #@params: center=[0,0,0], size=[10,8,4]

Notes
-----
- This is intentionally small and Grasshopper-first.
- It does not attempt to replicate the full server-side Python executor.
- OBJ mesh cache is still parsed and returned as Rhino meshes.
"""

from __future__ import annotations

import ast
import math
import random
from dataclasses import dataclass, field

import Rhino.Geometry as rg

# Set to True for stricter Live OBJ op compatibility diagnostics.
STRICT_COMPAT = True


@dataclass
class ObjObject:
    name: str = "unnamed"
    meta: dict = field(default_factory=dict)
    vertices: list = field(default_factory=list)
    faces: list = field(default_factory=list)
    ops: list = field(default_factory=list)


def _parse_scalar(value: str):
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


def _split_top_level_commas(text: str):
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


def _parse_params(raw: str):
    params = {}
    for part in _split_top_level_commas(raw):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        params[k.strip()] = _parse_scalar(v)
    return params


def parse_live_obj(text: str):
    objects = []
    current = ObjObject()

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
            continue

        if s.startswith("#@"):
            payload = s[2:].strip()
            if payload.startswith("- "):
                current.ops.append(_parse_op_line(payload[2:].strip()))
                continue
            if ":" in payload:
                key, value = payload.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "params":
                    current.meta["params"] = _parse_params(value)
                elif key == "ops":
                    current.meta["ops_block"] = True
                else:
                    current.meta[key] = _parse_scalar(value)
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


def _parse_op_line(line: str):
    parts = line.split(None, 1)
    if not parts:
        return {}
    op = {"op": parts[0].strip().lower()}
    if len(parts) > 1:
        op.update(_parse_params(parts[1]))
    return op


def build_rhino_mesh(obj: ObjObject):
    m = rg.Mesh()
    for v in obj.vertices:
        m.Vertices.Add(*v)

    for f in obj.faces:
        loc = [i - 1 for i in f]
        if len(loc) == 3:
            m.Faces.AddFace(loc[0], loc[1], loc[2])
        elif len(loc) == 4:
            m.Faces.AddFace(loc[0], loc[1], loc[2], loc[3])
        elif len(loc) > 4:
            for i in range(1, len(loc) - 1):
                m.Faces.AddFace(loc[0], loc[i], loc[i + 1])

    m.Normals.ComputeNormals()
    m.Compact()
    return m


def _vec3(params, key, default):
    raw = params.get(key, default)
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        return float(raw[0]), float(raw[1]), float(raw[2])
    return default


def build_native_geometry(obj: ObjObject, warnings: list):
    meta = obj.meta
    source = str(meta.get("source", "")).lower()
    if source not in {"procedural", "simulation"}:
        return None

    p = meta.get("params", {}) if isinstance(meta.get("params", {}), dict) else {}
    if source == "simulation":
        return build_simulation_geometry(obj, p, warnings)

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


def apply_deformer(mesh: rg.Mesh, obj: ObjObject, warnings: list):
    meta = obj.meta
    deformer = str(meta.get("deformer", "")).lower()
    if not deformer:
        return mesh

    p = meta.get("params", {}) if isinstance(meta.get("params", {}), dict) else {}
    m = mesh.DuplicateMesh()
    if m.Vertices.Count == 0:
        return m

    bb = m.GetBoundingBox(True)
    z0, z1 = bb.Min.Z, bb.Max.Z
    zspan = max(1e-9, z1 - z0)

    if deformer == "twist":
        angle_deg = float(p.get("angle_deg", p.get("angle", 30.0)))
        angle_rad = math.radians(angle_deg)
        for i in range(m.Vertices.Count):
            v = m.Vertices[i]
            t = (v.Z - z0) / zspan
            a = angle_rad * t
            c, s = math.cos(a), math.sin(a)
            x = v.X * c - v.Y * s
            y = v.X * s + v.Y * c
            m.Vertices.SetVertex(i, x, y, v.Z)
    elif deformer == "taper":
        factor = float(p.get("factor", 0.5))
        for i in range(m.Vertices.Count):
            v = m.Vertices[i]
            t = (v.Z - z0) / zspan
            s = 1.0 - factor * t
            m.Vertices.SetVertex(i, v.X * s, v.Y * s, v.Z)
    elif deformer == "wave":
        amp = float(p.get("amplitude", 0.4))
        freq = float(p.get("frequency", 1.0))
        for i in range(m.Vertices.Count):
            v = m.Vertices[i]
            dz = amp * math.sin(v.X * freq) * math.cos(v.Y * freq)
            m.Vertices.SetVertex(i, v.X, v.Y, v.Z + dz)
    elif deformer == "bend":
        angle_deg = float(p.get("angle_deg", 20.0))
        angle_rad = math.radians(angle_deg)
        for i in range(m.Vertices.Count):
            v = m.Vertices[i]
            t = (v.X - bb.Min.X) / max(1e-9, bb.Max.X - bb.Min.X)
            a = angle_rad * t
            c, s = math.cos(a), math.sin(a)
            y = v.Y * c - v.Z * s
            z = v.Y * s + v.Z * c
            m.Vertices.SetVertex(i, v.X, y, z)
    else:
        warnings.append("unsupported deformer on '%s': %s" % (obj.name, deformer))
        return mesh

    m.Normals.ComputeNormals()
    m.Compact()
    return m


def build_simulation_geometry(obj: ObjObject, p: dict, warnings: list):
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


def build_procedural_advanced(obj: ObjObject, warnings: list):
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


def apply_native_ops(geom, ops: list, warnings: list):
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
            strength = float(op.get("factor", 1.0))
            for g in each_geom(out):
                if isinstance(g, rg.Mesh):
                    for _ in range(iters):
                        g.LaplacianSmooth(True, True, True, strength)
                    g.Normals.ComputeNormals()
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
        elif name in {"union", "subtract"}:
            geoms = [g for g in each_geom(out) if isinstance(g, rg.Brep)]
            if len(geoms) >= 2:
                a = geoms[0]
                bs = geoms[1:]
                if name == "union":
                    u = rg.Brep.CreateBooleanUnion(geoms, 0.01)
                    if u:
                        out = list(u)
                else:
                    d = rg.Brep.CreateBooleanDifference(a, bs, 0.01)
                    if d:
                        out = list(d)
        else:
            warnings.append("unsupported op: %s" % name)
            if STRICT_COMPAT:
                warnings.append("compat: unsupported op '%s' in strict mode" % name)
    return out


def validate_compat(obj: ObjObject, warnings: list):
    supported_sources = {"procedural", "simulation", "llm_mesh", ""}
    supported_types = {"box", "sphere", "cylinder", "polyline", "extrude", "loft", "sweep", ""}
    supported_sims = {"boids", "differential_growth", "cellular_automata", ""}
    supported_deformers = {"twist", "taper", "wave", "bend", ""}
    supported_ops = {
        "move", "scale", "rotate", "mirror",
        "array", "array_linear", "radial_array",
        "displace", "noise_displace", "subdivide",
        "smooth", "simplify", "remesh",
        "bevel", "chamfer", "trace_paths", "sdf_tubes",
        "voxelize", "mesh_from_volume", "tread",
        "union", "subtract",
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


# ---- GHPython entrypoint ----

text_in = x if isinstance(x, str) else ""
objs = parse_live_obj(text_in)

meshes = []
native = []
names = []
warn = []

for o in objs:
    names.append(o.name)
    if STRICT_COMPAT:
        validate_compat(o, warn)
    if o.vertices and o.faces:
        try:
            mesh = build_rhino_mesh(o)
            mesh = apply_deformer(mesh, o, warn)
            meshes.append(mesh)
        except Exception as ex:
            warn.append("mesh build failed on '%s': %s" % (o.name, ex))

    g = build_native_geometry(o, warn)
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
