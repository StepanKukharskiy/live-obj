"""
Live OBJ Executor for Blender (bpy)

Paste into Blender's Text Editor and run.
Set LIVE_OBJ_TEXT to raw OBJ/Live OBJ text (with #@ metadata).

What it does
------------
- Parses OBJ object blocks (`o`, `v`, `f`) and #@ metadata.
- Builds Blender mesh objects from cache geometry.
- Builds procedural objects from metadata (`box`, `sphere`, `cylinder`, `extrude`).
- Supports simple simulations (`boids`, `differential_growth`, `cellular_automata`).
- Applies simple ops (`move`, `scale`, `rotate`, `array`, `radial_array`).

Notes
-----
This is Blender-native and intentionally compact; it does not fully replicate
server-side executor behavior.
"""

from __future__ import annotations

import ast
import math
import random

import bpy
import bmesh
from mathutils import Vector, Matrix

LIVE_OBJ_TEXT = ""  # assign your panel/live-obj text here
COLLECTION_NAME = "LiveOBJ"


class ObjObject(object):
    def __init__(self):
        self.name = "unnamed"
        self.meta = {}
        self.vertices = []
        self.faces = []
        self.ops = []


def parse_scalar(value):
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


def split_top_level_commas(text):
    parts, cur = [], []
    depth = 0
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            t = "".join(cur).strip()
            if t:
                parts.append(t)
            cur = []
        else:
            cur.append(ch)
    t = "".join(cur).strip()
    if t:
        parts.append(t)
    return parts


def parse_params(raw):
    out = {}
    for part in split_top_level_commas(raw):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = parse_scalar(v)
    return out


def parse_op_line(line):
    parts = line.split(None, 1)
    op = {"op": parts[0].strip().lower()} if parts else {}
    if len(parts) > 1:
        op.update(parse_params(parts[1]))
    return op


def parse_live_obj(text):
    objects = []
    cur = ObjObject()

    def push():
        if cur.vertices or cur.faces or cur.meta or cur.name != "unnamed":
            objects.append(cur)

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("o "):
            push()
            cur = ObjObject()
            cur.name = s[2:].strip() or "unnamed"
            continue
        if s.startswith("#@"):
            payload = s[2:].strip()
            if payload.startswith("- "):
                cur.ops.append(parse_op_line(payload[2:].strip()))
                continue
            if ":" in payload:
                k, v = payload.split(":", 1)
                k, v = k.strip().lower(), v.strip()
                if k == "params":
                    cur.meta["params"] = parse_params(v)
                else:
                    cur.meta[k] = parse_scalar(v)
            continue
        if s.startswith("v "):
            p = s.split()
            if len(p) >= 4:
                cur.vertices.append((float(p[1]), float(p[2]), float(p[3])))
            continue
        if s.startswith("f "):
            idxs = []
            for tok in s.split()[1:]:
                idxs.append(int(tok.split("/")[0]))
            if len(idxs) >= 3:
                cur.faces.append(idxs)
    push()
    return objects


def vec3(params, key, default):
    v = params.get(key, default)
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return float(v[0]), float(v[1]), float(v[2])
    return default


def ensure_collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def link_obj(obj, col):
    if obj.name not in col.objects:
        col.objects.link(obj)


def mesh_object_from_data(name, verts, faces):
    mesh = bpy.data.meshes.new(name + "_mesh")
    zero_faces = []
    for f in faces:
        if len(f) == 3:
            zero_faces.append((f[0] - 1, f[1] - 1, f[2] - 1))
        elif len(f) == 4:
            zero_faces.append((f[0] - 1, f[1] - 1, f[2] - 1, f[3] - 1))
        else:
            for i in range(1, len(f) - 1):
                zero_faces.append((f[0] - 1, f[i] - 1, f[i + 1] - 1))
    mesh.from_pydata(verts, [], zero_faces)
    mesh.update()
    return bpy.data.objects.new(name, mesh)


def procedural_object(obj):
    p = obj.meta.get("params", {}) if isinstance(obj.meta.get("params", {}), dict) else {}
    typ = str(obj.meta.get("type", "")).lower()

    if typ == "box":
        sx, sy, sz = vec3(p, "size", (1.0, 1.0, 1.0))
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        o = bpy.context.active_object
        o.scale = (sx / 2.0, sy / 2.0, sz / 2.0)
    elif typ == "sphere":
        r = float(p.get("radius", 1.0))
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r)
        o = bpy.context.active_object
    elif typ == "cylinder":
        r = float(p.get("radius", 1.0))
        d = float(p.get("height", 2.0))
        bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=d)
        o = bpy.context.active_object
    elif typ == "extrude":
        profile = p.get("profile", [])
        h = float(p.get("height", 1.0))
        if not isinstance(profile, list) or len(profile) < 3:
            return None
        bm = bmesh.new()
        vs = [bm.verts.new(Vector((q[0], q[1], q[2]))) for q in profile]
        bm.faces.new(vs)
        ret = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
        verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=verts, vec=Vector((0, 0, h)))
        me = bpy.data.meshes.new(obj.name + "_extrude")
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(obj.name, me)
    else:
        return None

    cx, cy, cz = vec3(p, "center", (0.0, 0.0, 0.0))
    o.location = (cx, cy, cz)
    o.name = obj.name
    return o


def simulation_objects(obj):
    p = obj.meta.get("params", {}) if isinstance(obj.meta.get("params", {}), dict) else {}
    sim = str(obj.meta.get("sim", "")).lower()
    rnd = random.Random(int(p.get("seed", 1)))
    out = []

    if sim == "boids":
        agents = max(1, int(p.get("agents", 24)))
        steps = max(2, int(p.get("steps", 60)))
        bx, by, bz = vec3(p, "bounds", (8.0, 8.0, 8.0))
        for i in range(agents):
            pts = []
            x, y, z = rnd.uniform(-bx/2,bx/2), rnd.uniform(-by/2,by/2), rnd.uniform(-bz/2,bz/2)
            for _ in range(steps):
                x += rnd.uniform(-0.25, 0.25); y += rnd.uniform(-0.25, 0.25); z += rnd.uniform(-0.25, 0.25)
                pts.append((x, y, z))
            crv = bpy.data.curves.new(f"{obj.name}_boid_{i}", "CURVE")
            crv.dimensions = "3D"
            spl = crv.splines.new("POLY")
            spl.points.add(len(pts)-1)
            for j, q in enumerate(pts):
                spl.points[j].co = (q[0], q[1], q[2], 1.0)
            out.append(bpy.data.objects.new(f"{obj.name}_boid_{i}", crv))

    elif sim == "differential_growth":
        n = max(8, int(p.get("points", 64)))
        r = float(p.get("radius", 2.0))
        pts = []
        for i in range(n+1):
            t = 2 * math.pi * (i / float(n))
            rr = r + rnd.uniform(-0.3, 0.3)
            pts.append((rr*math.cos(t), rr*math.sin(t), 0.0))
        crv = bpy.data.curves.new(f"{obj.name}_growth", "CURVE")
        crv.dimensions = "3D"
        spl = crv.splines.new("POLY")
        spl.points.add(len(pts)-1)
        for j, q in enumerate(pts):
            spl.points[j].co = (q[0], q[1], q[2], 1.0)
        out.append(bpy.data.objects.new(f"{obj.name}_growth", crv))

    elif sim == "cellular_automata":
        gx, gy, gz = vec3(p, "grid", (8, 8, 4))
        cell = float(p.get("cell", 0.5))
        fill = float(p.get("fill", 0.2))
        for ix in range(int(gx)):
            for iy in range(int(gy)):
                for iz in range(int(gz)):
                    if rnd.random() <= fill:
                        bpy.ops.mesh.primitive_cube_add(size=cell, location=((ix-gx/2)*cell, (iy-gy/2)*cell, (iz-gz/2)*cell))
                        out.append(bpy.context.active_object)

    return out


def apply_ops(bl_obj, ops):
    if bl_obj is None:
        return
    for op in ops:
        name = str(op.get("op", "")).lower()
        if name == "array":
            name = "array_linear"
        if name == "move":
            dx, dy, dz = vec3(op, "offset", (0.0, 0.0, 0.0))
            bl_obj.location += Vector((dx, dy, dz))
        elif name == "scale":
            s = float(op.get("factor", 1.0))
            bl_obj.scale = (bl_obj.scale.x * s, bl_obj.scale.y * s, bl_obj.scale.z * s)
        elif name == "rotate":
            a = math.radians(float(op.get("angle_deg", op.get("angle", 0.0))))
            axis = vec3(op, "axis", (0.0, 0.0, 1.0))
            bl_obj.rotation_mode = "XYZ"
            if abs(axis[2]) >= max(abs(axis[0]), abs(axis[1])):
                bl_obj.rotation_euler.z += a
            elif abs(axis[1]) >= abs(axis[0]):
                bl_obj.rotation_euler.y += a
            else:
                bl_obj.rotation_euler.x += a
        elif name == "array_linear":
            count = max(1, int(op.get("count", 4)))
            dx, dy, dz = vec3(op, "step", (1.0, 0.0, 0.0))
            for i in range(1, count):
                c = bl_obj.copy(); c.data = bl_obj.data.copy() if bl_obj.data else None
                c.location += Vector((dx*i, dy*i, dz*i))
                bpy.context.scene.collection.objects.link(c)
        elif name == "radial_array":
            count = max(1, int(op.get("count", 8)))
            for i in range(1, count):
                c = bl_obj.copy(); c.data = bl_obj.data.copy() if bl_obj.data else None
                ang = (2*math.pi*i)/float(count)
                c.matrix_world = Matrix.Rotation(ang, 4, 'Z') @ bl_obj.matrix_world
                bpy.context.scene.collection.objects.link(c)


def run(live_obj_text):
    objects = parse_live_obj(live_obj_text)
    col = ensure_collection(COLLECTION_NAME)

    created = []
    for obj in objects:
        source = str(obj.meta.get("source", "")).lower()
        bl_obj = None

        if obj.vertices and obj.faces:
            bl_obj = mesh_object_from_data(obj.name, obj.vertices, obj.faces)
        elif source == "procedural":
            bl_obj = procedural_object(obj)
        elif source == "simulation":
            sims = simulation_objects(obj)
            for s in sims:
                link_obj(s, col)
                created.append(s)

        if bl_obj is not None:
            apply_ops(bl_obj, obj.ops)
            link_obj(bl_obj, col)
            created.append(bl_obj)

    return created


if __name__ == "__main__":
    run(LIVE_OBJ_TEXT)
