#!/usr/bin/env python3
"""
Live OBJ Executor v0.2 — mesh + SDF + simple simulations

Purpose
-------
This script is a prototype executor for "Live OBJ":

    Live OBJ = #@ procedural intent comments + cached OBJ vertices/faces

External tools see a normal OBJ. Your system treats #@ metadata as the editable
source of truth and regenerates the mesh cache.

What's new in v0.2
------------------
Adds first-pass support for:
    1. SDF primitives and CSG-like composition
    2. Cellular automata volume growth
    3. Differential growth curves
    4. Boids path simulation

This is still intentionally minimal. It is not a production CAD/SDF/simulation
kernel. It is a reference implementation that proves the format/execution model.

Supported object sources
------------------------
    #@source: procedural
    #@source: llm_mesh
    #@source: assembly
    #@source: sdf
    #@source: simulation

Supported procedural types
--------------------------
    box
    cylinder
    surface_grid
    heightfield
    mesh

Supported SDF block
-------------------
Example:

    o eroded_cube_sdf
    #@source: sdf
    #@params: bounds=[[-2,-2,-2],[2,2,2]], resolution=0.15
    #@sdf:
    #@ - box id=base center=[0,0,0] size=[2,2,2]
    #@ - sphere id=cut center=[0.6,0.6,0.6] radius=0.8
    #@ - subtract base cut
    #@ - noise_displace strength=0.15 frequency=4 seed=3
    #@ops:
    #@ - smooth iterations=1

Supported simulations
---------------------
Cellular automata:

    o coral_ca
    #@source: simulation
    #@sim: cellular_automata
    #@params: grid=[32,32,32], cell=0.08, steps=45, seed=8, mode=coral
    #@ops:
    #@ - smooth iterations=1

Differential growth:

    o growth_ring
    #@source: simulation
    #@sim: differential_growth
    #@params: radius=1.0, points=40, steps=180, split_distance=0.18, repel_radius=0.25, thickness=0.035, seed=2

Boids:

    o boid_pavilion
    #@source: simulation
    #@sim: boids
    #@params: agents=40, steps=160, bounds=[8,5,5], seed=4, trace_radius=0.035

Important design choice
-----------------------
The #@ metadata is the truth for procedural/simulation/SDF objects.
The v/f mesh below it is only a cache. For #@source: llm_mesh, the mesh is the
truth unless ops are added on top.

CAD kernel note
---------------
For production, make kernels pluggable:
    - simple mesh executor: fast, portable, good for MVP
    - SDF/voxel engine: good for organic forms, CSG, growth
    - CadQuery/build123d/OpenCascade: precise BREP/CAD/booleans/manufacturing
    - Blender BMesh/Geometry Nodes: DCC-style mesh ops
This script keeps dependencies to Python stdlib only, so its algorithms are
approximate and intentionally simple.
"""

from __future__ import annotations

import argparse
import ast
import math
import random
import re
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
class LiveObject:
    name: str
    declaration: str = "o"
    meta_lines: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    ops: List[Dict[str, Any]] = field(default_factory=list)
    sdf_ops: List[Dict[str, Any]] = field(default_factory=list)
    mesh: Mesh = field(default_factory=Mesh)
    raw_nonlive_lines: List[str] = field(default_factory=list)


@dataclass
class Scene:
    header_lines: List[str] = field(default_factory=list)
    objects: List[LiveObject] = field(default_factory=list)


# ----------------------------
# Parsing
# ----------------------------

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


def split_top_level_commas(s: str) -> List[str]:
    parts, cur, depth = [], [], 0
    for ch in s:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


def parse_key_values(s: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for part in split_top_level_commas(s):
        if not part:
            continue
        if "=" not in part:
            result[part.strip()] = True
            continue
        k, v = part.split("=", 1)
        result[k.strip()] = parse_scalar(v)
    return result


def parse_tokens(s: str) -> Dict[str, Any]:
    s = s.strip()
    if s.startswith("-"):
        s = s[1:].strip()
    tokens = s.split()
    if not tokens:
        return {}
    d: Dict[str, Any] = {"cmd": tokens[0], "op": tokens[0]}
    positional = []
    for token in tokens[1:]:
        if "=" in token:
            k, v = token.split("=", 1)
            d[k] = parse_scalar(v)
        else:
            positional.append(parse_scalar(token))
    if positional:
        d["args"] = positional
    return d


def parse_meta(meta_lines: List[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    meta: Dict[str, Any] = {}
    ops: List[Dict[str, Any]] = []
    sdf_ops: List[Dict[str, Any]] = []
    block: Optional[str] = None

    for line in meta_lines:
        body = line.strip()
        if not body.startswith("#@"):
            continue
        body = body[2:].strip()

        if body == "ops:":
            block = "ops"
            continue
        if body == "sdf:":
            block = "sdf"
            continue
        if body == "anchors:":
            block = "anchors"
            meta["anchors"] = {}
            continue

        if block == "anchors" and body.startswith("-"):
            anchor_body = body[1:].strip()
            if "=" in anchor_body:
                k, v = anchor_body.split("=", 1)
                meta.setdefault("anchors", {})[k.strip()] = parse_scalar(v)
            continue

        if block in {"ops", "sdf"} and body.startswith("-"):
            parsed = parse_tokens(body)
            if parsed:
                (ops if block == "ops" else sdf_ops).append(parsed)
            continue

        block = None
        if ":" not in body:
            continue

        key, val = body.split(":", 1)
        key, val = key.strip(), val.strip()
        if key in {"params", "transform", "rules"}:
            meta[key] = parse_key_values(val)
        elif key == "gen":
            parsed_gen = parse_tokens(val)
            if parsed_gen.get("op"):
                meta["type"] = parsed_gen.get("op")
            merged_params = dict(meta.get("params", {}) or {})
            for k, v in parsed_gen.items():
                if k in {"cmd", "op", "args"}:
                    continue
                merged_params[k] = v
            if merged_params:
                meta["params"] = merged_params
        elif key == "op":
            parsed_op = parse_tokens(val)
            if parsed_op:
                ops.append(parsed_op)
        elif key == "anchor":
            parsed_anchor = parse_tokens(f"anchor {val}")
            anchor_name = parsed_anchor.get("name", parsed_anchor.get("id"))
            anchor_pos = parsed_anchor.get("position")
            if anchor_name and isinstance(anchor_pos, list) and len(anchor_pos) >= 3:
                meta.setdefault("anchors", {})[str(anchor_name)] = anchor_pos
        elif key == "constraint":
            parsed_constraint = parse_tokens(val)
            if parsed_constraint.get("op") == "attach":
                self_anchor = parsed_constraint.get("self")
                target = parsed_constraint.get("target")
                if self_anchor and target:
                    mode = parsed_constraint.get("mode", parsed_constraint.get("solve"))
                    attach_val = f"self={self_anchor} target={target}"
                    if mode:
                        attach_val += f" mode={mode}"
                    meta["attach"] = attach_val
        elif key in {"children", "tags"}:
            meta[key] = [x.strip() for x in val.split(",") if x.strip()]
        else:
            meta[key] = parse_scalar(val)

    return meta, ops, sdf_ops


def parse_obj(path: Path) -> Scene:
    scene = Scene()
    current: Optional[LiveObject] = None
    global_vertex_index_to_local: Dict[int, Tuple[LiveObject, int]] = {}
    global_vertex_count = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()

        if stripped.startswith("o ") or stripped.startswith("g "):
            declaration, name = stripped.split(maxsplit=1)
            current = LiveObject(name=name.strip(), declaration=declaration)
            scene.objects.append(current)
            continue

        if current is None:
            scene.header_lines.append(line)
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
                global_vertex_index_to_local[global_vertex_count] = (current, len(current.mesh.vertices))
            continue

        if stripped.startswith("f "):
            inds = []
            for tok in stripped.split()[1:]:
                idx = int(tok.split("/")[0])
                obj_ref, local_idx = global_vertex_index_to_local.get(idx, (current, idx))
                if obj_ref is current:
                    inds.append(local_idx)
            if len(inds) >= 3:
                current.mesh.faces.append(inds)
            continue

        current.raw_nonlive_lines.append(line)

    for obj in scene.objects:
        obj.meta, obj.ops, obj.sdf_ops = parse_meta(obj.meta_lines)

    return scene


# ----------------------------
# Basic mesh generators
# ----------------------------

def box_mesh(center: Vec3, size: Vec3) -> Mesh:
    cx, cy, cz = center
    sx, sy, sz = size
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    z0, z1 = cz - sz / 2, cz + sz / 2
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    f = [[1,2,3,4],[5,8,7,6],[1,5,6,2],[2,6,7,3],[3,7,8,4],[4,8,5,1]]
    return Mesh(v, f)


def cylinder_mesh(axis: str, center: Vec3, radius: float, depth: float, segments: int = 16) -> Mesh:
    cx, cy, cz = center
    verts, faces = [], []
    axis = axis.lower()

    def pt(side: float, a: float) -> Vec3:
        ca, sa = math.cos(a), math.sin(a)
        if axis == "x":
            return (cx + side, cy + ca * radius, cz + sa * radius)
        if axis == "y":
            return (cx + ca * radius, cy + side, cz + sa * radius)
        return (cx + ca * radius, cy + sa * radius, cz + side)

    r1, r2 = [], []
    for i in range(segments):
        verts.append(pt(-depth/2, 2*math.pi*i/segments)); r1.append(len(verts))
    for i in range(segments):
        verts.append(pt(depth/2, 2*math.pi*i/segments)); r2.append(len(verts))
    faces.append(list(reversed(r1)))
    faces.append(r2)
    for i in range(segments):
        faces.append([r1[i], r1[(i+1)%segments], r2[(i+1)%segments], r2[i]])
    return Mesh(verts, faces)


def surface_grid(width: float, depth: float, resolution: int, center: Vec3 = (0,0,0)) -> Mesh:
    cx, cy, cz = center
    n = max(2, int(resolution))
    verts, faces = [], []
    for iy in range(n):
        y = cy - depth/2 + depth * iy / (n-1)
        for ix in range(n):
            x = cx - width/2 + width * ix / (n-1)
            verts.append((x, y, cz))
    for iy in range(n-1):
        for ix in range(n-1):
            a = iy*n + ix + 1
            faces.append([a, a+1, a+1+n, a+n])
    return Mesh(verts, faces)


# ----------------------------
# SDF
# ----------------------------

def length3(p: Vec3) -> float:
    return math.sqrt(p[0]*p[0] + p[1]*p[1] + p[2]*p[2])


def sub3(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


class SDFExpr:
    def dist(self, p: Vec3) -> float:
        raise NotImplementedError


class SDFBox(SDFExpr):
    def __init__(self, center: Vec3, size: Vec3):
        self.c = center
        self.s = (size[0]/2, size[1]/2, size[2]/2)

    def dist(self, p: Vec3) -> float:
        q = (abs(p[0]-self.c[0])-self.s[0], abs(p[1]-self.c[1])-self.s[1], abs(p[2]-self.c[2])-self.s[2])
        outside = length3((max(q[0],0), max(q[1],0), max(q[2],0)))
        inside = min(max(q[0], max(q[1], q[2])), 0)
        return outside + inside


class SDFSphere(SDFExpr):
    def __init__(self, center: Vec3, radius: float):
        self.c = center
        self.r = radius

    def dist(self, p: Vec3) -> float:
        return length3(sub3(p, self.c)) - self.r


class SDFCylinderZ(SDFExpr):
    def __init__(self, center: Vec3, radius: float, height: float):
        self.c = center
        self.r = radius
        self.h = height / 2

    def dist(self, p: Vec3) -> float:
        dx = math.sqrt((p[0]-self.c[0])**2 + (p[1]-self.c[1])**2) - self.r
        dz = abs(p[2]-self.c[2]) - self.h
        return min(max(dx, dz), 0.0) + length3((max(dx,0), max(dz,0), 0))


class SDFUnion(SDFExpr):
    def __init__(self, a: SDFExpr, b: SDFExpr): self.a, self.b = a, b
    def dist(self, p: Vec3) -> float: return min(self.a.dist(p), self.b.dist(p))


class SDFSubtract(SDFExpr):
    def __init__(self, a: SDFExpr, b: SDFExpr): self.a, self.b = a, b
    def dist(self, p: Vec3) -> float: return max(self.a.dist(p), -self.b.dist(p))


class SDFIntersect(SDFExpr):
    def __init__(self, a: SDFExpr, b: SDFExpr): self.a, self.b = a, b
    def dist(self, p: Vec3) -> float: return max(self.a.dist(p), self.b.dist(p))


class SDFNoiseDisplace(SDFExpr):
    def __init__(self, base: SDFExpr, strength: float, frequency: float, seed: int):
        self.base, self.strength, self.frequency, self.seed = base, strength, frequency, seed

    def dist(self, p: Vec3) -> float:
        x, y, z = p
        f = self.frequency
        n = (
            math.sin(x*f + self.seed) * 0.5 +
            math.sin(y*f*1.7 + self.seed*0.31) * 0.3 +
            math.sin(z*f*2.1 + self.seed*0.73) * 0.2
        )
        return self.base.dist(p) + self.strength * n


def build_sdf(obj: LiveObject) -> Optional[SDFExpr]:
    registry: Dict[str, SDFExpr] = {}
    current: Optional[SDFExpr] = None

    for cmd in obj.sdf_ops:
        c = cmd.get("cmd")
        if c == "box":
            sid = str(cmd.get("id", f"box_{len(registry)}"))
            center = tuple(cmd.get("center", [0,0,0]))
            size = tuple(cmd.get("size", [1,1,1]))
            registry[sid] = SDFBox(tuple(map(float, center)), tuple(map(float, size)))
            current = registry[sid]
        elif c == "sphere":
            sid = str(cmd.get("id", f"sphere_{len(registry)}"))
            center = tuple(cmd.get("center", [0,0,0]))
            radius = float(cmd.get("radius", 1))
            registry[sid] = SDFSphere(tuple(map(float, center)), radius)
            current = registry[sid]
        elif c == "cylinder":
            sid = str(cmd.get("id", f"cylinder_{len(registry)}"))
            center = tuple(cmd.get("center", [0,0,0]))
            radius = float(cmd.get("radius", 1))
            height = float(cmd.get("height", 1))
            registry[sid] = SDFCylinderZ(tuple(map(float, center)), radius, height)
            current = registry[sid]
        elif c in {"union", "subtract", "intersect"}:
            args = cmd.get("args", [])
            if len(args) >= 2 and str(args[0]) in registry and str(args[1]) in registry:
                a, b = registry[str(args[0])], registry[str(args[1])]
                if c == "union": current = SDFUnion(a, b)
                elif c == "subtract": current = SDFSubtract(a, b)
                else: current = SDFIntersect(a, b)
                registry["result"] = current
        elif c == "noise_displace" and current is not None:
            current = SDFNoiseDisplace(
                current,
                strength=float(cmd.get("strength", 0.1)),
                frequency=float(cmd.get("frequency", 3)),
                seed=int(cmd.get("seed", 0)),
            )
            registry["result"] = current

    return current


def mesh_from_voxels(occupied: set[Tuple[int,int,int]], origin: Vec3, cell: float) -> Mesh:
    """Voxel surface mesher: emits exposed cube faces. Crude but dependency-free."""
    mesh = Mesh()
    dirs = [
        ((1,0,0), [(1,-1,-1),(1,1,-1),(1,1,1),(1,-1,1)]),
        ((-1,0,0), [(-1,-1,-1),(-1,-1,1),(-1,1,1),(-1,1,-1)]),
        ((0,1,0), [(-1,1,-1),(-1,1,1),(1,1,1),(1,1,-1)]),
        ((0,-1,0), [(-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1)]),
        ((0,0,1), [(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]),
        ((0,0,-1), [(-1,-1,-1),(-1,1,-1),(1,1,-1),(1,-1,-1)]),
    ]
    ox, oy, oz = origin
    half = cell / 2
    for i, j, k in occupied:
        cx, cy, cz = ox + i*cell, oy + j*cell, oz + k*cell
        for (di,dj,dk), corners in dirs:
            if (i+di, j+dj, k+dk) in occupied:
                continue
            face = []
            for sx, sy, sz in corners:
                mesh.vertices.append((cx + sx*half, cy + sy*half, cz + sz*half))
                face.append(len(mesh.vertices))
            mesh.faces.append(face)
    return mesh


def sdf_to_voxel_mesh(expr: SDFExpr, bounds: List[List[float]], resolution: float) -> Mesh:
    mn, mx = bounds
    nx = max(2, int((mx[0] - mn[0]) / resolution))
    ny = max(2, int((mx[1] - mn[1]) / resolution))
    nz = max(2, int((mx[2] - mn[2]) / resolution))
    occupied = set()
    origin = (float(mn[0]), float(mn[1]), float(mn[2]))
    for i in range(nx + 1):
        for j in range(ny + 1):
            for k in range(nz + 1):
                p = (origin[0] + i*resolution, origin[1] + j*resolution, origin[2] + k*resolution)
                if expr.dist(p) <= 0:
                    occupied.add((i,j,k))
    return mesh_from_voxels(occupied, origin, resolution)


# ----------------------------
# Simulation generators
# ----------------------------

def cellular_automata_mesh(params: Dict[str, Any]) -> Mesh:
    grid = params.get("grid", [28,28,28])
    nx, ny, nz = map(int, grid)
    cell = float(params.get("cell", 0.1))
    steps = int(params.get("steps", 40))
    seed = int(params.get("seed", 1))
    mode = str(params.get("mode", "coral"))
    rng = random.Random(seed)

    occupied = set()
    # Start with a seed cluster near bottom/center.
    cx, cy = nx//2, ny//2
    for _ in range(max(6, nx//4)):
        occupied.add((cx + rng.randint(-2,2), cy + rng.randint(-2,2), rng.randint(0,2)))

    neigh = [(dx,dy,dz) for dx in [-1,0,1] for dy in [-1,0,1] for dz in [-1,0,1] if not (dx==dy==dz==0)]

    for _ in range(steps):
        candidates = set()
        for cell_idx in occupied:
            i,j,k = cell_idx
            for dx,dy,dz in neigh:
                ni,nj,nk = i+dx,j+dy,k+dz
                if 0 <= ni < nx and 0 <= nj < ny and 0 <= nk < nz:
                    candidates.add((ni,nj,nk))
        new_occ = set(occupied)
        for c in candidates:
            if c in occupied:
                continue
            i,j,k = c
            count = sum((i+dx,j+dy,k+dz) in occupied for dx,dy,dz in neigh)
            upward_bias = 0.015 * (k / max(1, nz-1))
            if mode == "coral":
                p = 0.015 + 0.025 * min(count, 5) + upward_bias
            else:
                p = 0.02 + 0.015 * count
            if rng.random() < p:
                new_occ.add(c)
        occupied = new_occ
        if len(occupied) > nx*ny*nz*0.18:
            break

    origin = (-nx*cell/2, -ny*cell/2, 0)
    return mesh_from_voxels(occupied, origin, cell)


def tube_between(a: Vec3, b: Vec3, radius: float, segments: int = 8) -> Mesh:
    # Simple cylinder-like segment aligned to vector using approximate basis.
    ax,ay,az = a; bx,by,bz = b
    vx,vy,vz = bx-ax, by-ay, bz-az
    length = math.sqrt(vx*vx+vy*vy+vz*vz)
    if length < 1e-6:
        return Mesh()
    ux,uy,uz = vx/length, vy/length, vz/length
    # choose perpendicular basis
    px,py,pz = (0,0,1) if abs(uz) < 0.9 else (0,1,0)
    # cross u x p
    bx1,by1,bz1 = uy*pz-uz*py, uz*px-ux*pz, ux*py-uy*px
    bl = math.sqrt(bx1*bx1+by1*by1+bz1*bz1)
    bx1,by1,bz1 = bx1/bl, by1/bl, bz1/bl
    # second basis u x b1
    cx1,cy1,cz1 = uy*bz1-uz*by1, uz*bx1-ux*bz1, ux*by1-uy*bx1

    verts, faces = [], []
    r1, r2 = [], []
    for i in range(segments):
        t = 2*math.pi*i/segments
        ox = math.cos(t)*bx1*radius + math.sin(t)*cx1*radius
        oy = math.cos(t)*by1*radius + math.sin(t)*cy1*radius
        oz = math.cos(t)*bz1*radius + math.sin(t)*cz1*radius
        verts.append((ax+ox, ay+oy, az+oz)); r1.append(len(verts))
    for i in range(segments):
        t = 2*math.pi*i/segments
        ox = math.cos(t)*bx1*radius + math.sin(t)*cx1*radius
        oy = math.cos(t)*by1*radius + math.sin(t)*cy1*radius
        oz = math.cos(t)*bz1*radius + math.sin(t)*cz1*radius
        verts.append((bx+ox, by+oy, bz+oz)); r2.append(len(verts))
    for i in range(segments):
        faces.append([r1[i], r1[(i+1)%segments], r2[(i+1)%segments], r2[i]])
    return Mesh(verts, faces)


def differential_growth_mesh(params: Dict[str, Any]) -> Mesh:
    radius = float(params.get("radius", 1.0))
    n = int(params.get("points", 32))
    steps = int(params.get("steps", 120))
    split_distance = float(params.get("split_distance", 0.16))
    repel_radius = float(params.get("repel_radius", 0.22))
    attraction = float(params.get("attraction", 0.03))
    thickness = float(params.get("thickness", 0.03))

    pts = [(math.cos(2*math.pi*i/n)*radius, math.sin(2*math.pi*i/n)*radius, 0.0) for i in range(n)]

    for _ in range(steps):
        forces = [[0.0, 0.0, 0.0] for _ in pts]
        # edge tension
        for i, p in enumerate(pts):
            prev = pts[(i-1)%len(pts)]
            nxt = pts[(i+1)%len(pts)]
            forces[i][0] += (prev[0]+nxt[0]-2*p[0]) * attraction
            forces[i][1] += (prev[1]+nxt[1]-2*p[1]) * attraction
        # repulsion
        for i in range(len(pts)):
            for j in range(i+1, len(pts)):
                dx,dy,dz = pts[i][0]-pts[j][0], pts[i][1]-pts[j][1], pts[i][2]-pts[j][2]
                d = math.sqrt(dx*dx+dy*dy+dz*dz) + 1e-6
                if d < repel_radius:
                    mag = (repel_radius-d)/repel_radius * 0.015
                    fx,fy,fz = dx/d*mag, dy/d*mag, dz/d*mag
                    forces[i][0] += fx; forces[i][1] += fy
                    forces[j][0] -= fx; forces[j][1] -= fy
        pts = [(p[0]+forces[i][0], p[1]+forces[i][1], p[2]+forces[i][2]) for i,p in enumerate(pts)]

        # split long edges
        new_pts = []
        for i, p in enumerate(pts):
            q = pts[(i+1)%len(pts)]
            new_pts.append(p)
            d = math.sqrt((p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2)
            if d > split_distance and len(pts) < 600:
                new_pts.append(((p[0]+q[0])/2, (p[1]+q[1])/2, (p[2]+q[2])/2))
        pts = new_pts

    mesh = Mesh()
    for i in range(len(pts)):
        mesh.extend(tube_between(pts[i], pts[(i+1)%len(pts)], thickness, 8))
    return mesh


def boids_mesh(params: Dict[str, Any]) -> Mesh:
    agents = int(params.get("agents", 30))
    steps = int(params.get("steps", 120))
    bounds = params.get("bounds", [6,4,4])
    bx, by, bz = map(float, bounds)
    seed = int(params.get("seed", 1))
    radius = float(params.get("trace_radius", 0.025))
    rng = random.Random(seed)

    pos = [(rng.uniform(-bx/2,bx/2), rng.uniform(-by/2,by/2), rng.uniform(0,bz)) for _ in range(agents)]
    vel = [(rng.uniform(-0.04,0.04), rng.uniform(-0.04,0.04), rng.uniform(-0.02,0.04)) for _ in range(agents)]
    paths = [[p] for p in pos]

    for _ in range(steps):
        new_pos, new_vel = [], []
        for i, p in enumerate(pos):
            vx,vy,vz = vel[i]
            center = [0,0,0]; count = 0
            sep = [0,0,0]
            align = [0,0,0]
            for j,q in enumerate(pos):
                if i == j:
                    continue
                dx,dy,dz = q[0]-p[0], q[1]-p[1], q[2]-p[2]
                d = math.sqrt(dx*dx+dy*dy+dz*dz)
                if d < 1.2:
                    center[0]+=q[0]; center[1]+=q[1]; center[2]+=q[2]
                    align[0]+=vel[j][0]; align[1]+=vel[j][1]; align[2]+=vel[j][2]
                    count += 1
                if d < 0.35 and d > 1e-6:
                    sep[0]-=dx/d; sep[1]-=dy/d; sep[2]-=dz/d
            if count:
                center = [c/count for c in center]
                align = [a/count for a in align]
                vx += (center[0]-p[0])*0.0008 + align[0]*0.03 + sep[0]*0.012
                vy += (center[1]-p[1])*0.0008 + align[1]*0.03 + sep[1]*0.012
                vz += (center[2]-p[2])*0.0008 + align[2]*0.03 + sep[2]*0.012
            # attract upward/center
            vx += -p[0]*0.0005
            vy += -p[1]*0.0005
            vz += (bz*0.5-p[2])*0.0004
            speed = math.sqrt(vx*vx+vy*vy+vz*vz) + 1e-6
            max_speed = 0.08
            if speed > max_speed:
                vx,vy,vz = vx/speed*max_speed, vy/speed*max_speed, vz/speed*max_speed
            np = (max(-bx/2,min(bx/2,p[0]+vx)), max(-by/2,min(by/2,p[1]+vy)), max(0,min(bz,p[2]+vz)))
            new_pos.append(np); new_vel.append((vx,vy,vz))
        pos, vel = new_pos, new_vel
        for i,p in enumerate(pos):
            if _ % 3 == 0:
                paths[i].append(p)

    mesh = Mesh()
    for path in paths:
        for a,b in zip(path, path[1:]):
            mesh.extend(tube_between(a,b,radius,6))
    return mesh


# ----------------------------
# Mesh ops
# ----------------------------

def apply_transform(mesh: Mesh, transform: Dict[str, Any]) -> Mesh:
    pos = transform.get("position", [0,0,0])
    scale = transform.get("scale", [1,1,1])
    rot = transform.get("rotation", [0,0,0])
    px,py,pz = map(float, pos)
    sx,sy,sz = map(float, scale)
    rx,ry,rz = [math.radians(float(a)) for a in rot]

    def rotate(v: Vec3) -> Vec3:
        x,y,z = v
        y,z = y*math.cos(rx)-z*math.sin(rx), y*math.sin(rx)+z*math.cos(rx)
        x,z = x*math.cos(ry)+z*math.sin(ry), -x*math.sin(ry)+z*math.cos(ry)
        x,y = x*math.cos(rz)-y*math.sin(rz), x*math.sin(rz)+y*math.cos(rz)
        return x,y,z

    out = Mesh(faces=[list(f) for f in mesh.faces])
    for x,y,z in mesh.vertices:
        x,y,z = rotate((x*sx, y*sy, z*sz))
        out.vertices.append((x+px, y+py, z+pz))
    return out


def apply_transform_to_point(point: Vec3, transform: Dict[str, Any]) -> Vec3:
    pos = transform.get("position", [0,0,0])
    scale = transform.get("scale", [1,1,1])
    rot = transform.get("rotation", [0,0,0])
    px,py,pz = map(float, pos)
    sx,sy,sz = map(float, scale)
    rx,ry,rz = [math.radians(float(a)) for a in rot]

    x,y,z = point
    x,y,z = (x*sx, y*sy, z*sz)
    y,z = y*math.cos(rx)-z*math.sin(rx), y*math.sin(rx)+z*math.cos(rx)
    x,z = x*math.cos(ry)+z*math.sin(ry), -x*math.sin(ry)+z*math.cos(ry)
    x,y = x*math.cos(rz)-y*math.sin(rz), x*math.sin(rz)+y*math.cos(rz)
    return (x+px, y+py, z+pz)


def translate_mesh(mesh: Mesh, delta: Vec3) -> Mesh:
    dx,dy,dz = delta
    out = mesh.copy()
    out.vertices = [(x+dx, y+dy, z+dz) for x,y,z in out.vertices]
    return out


def compute_bbox(mesh: Mesh) -> Optional[Tuple[float, float, float, float, float, float]]:
    if not mesh.vertices:
        return None
    xs = [v[0] for v in mesh.vertices]
    ys = [v[1] for v in mesh.vertices]
    zs = [v[2] for v in mesh.vertices]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def mesh_anchor(mesh: Mesh, anchor_name: str) -> Optional[Vec3]:
    bbox = compute_bbox(mesh)
    if bbox is None:
        return None
    minx, maxx, miny, maxy, minz, maxz = bbox
    cx, cy, cz = ((minx+maxx)/2, (miny+maxy)/2, (minz+maxz)/2)
    anchors = {
        "center": (cx, cy, cz),
        "top_center": (cx, cy, maxz),
        "bottom_center": (cx, cy, minz),
        "left_center": (minx, cy, cz),
        "right_center": (maxx, cy, cz),
        "front_center": (cx, maxy, cz),
        "back_center": (cx, miny, cz),
    }
    return anchors.get(anchor_name)


def parse_attach_spec(attach_val: Any) -> Optional[Tuple[str, str, str]]:
    text = str(attach_val or "").strip()
    if not text:
        return None

    match = re.match(r"^([A-Za-z0-9_-]+)\s+to\s+([A-Za-z0-9_.-]+)\.([A-Za-z0-9_-]+)$", text)
    if match:
        return (match.group(1), match.group(2), match.group(3))

    explicit_self = re.search(r"(?:self_anchor|self)=([A-Za-z0-9_-]+)", text)
    explicit_target = re.search(r"(?:to|target)=([A-Za-z0-9_.-]+)\.([A-Za-z0-9_-]+)", text)
    explicit_mode = re.search(r"(?:mode|solve)=([A-Za-z0-9_-]+)", text)
    if explicit_mode and explicit_mode.group(1).lower() not in {"translate", "translation"}:
        return None
    if explicit_self and explicit_target:
        return (explicit_self.group(1), explicit_target.group(1), explicit_target.group(2))

    return None


def resolve_object_anchor_world(
    scene_obj: LiveObject,
    anchor_name: str,
    object_by_name: Dict[str, LiveObject],
) -> Optional[Vec3]:
    anchors = scene_obj.meta.get("anchors", {}) or {}
    local = anchors.get(anchor_name)
    local_is_world = False
    if isinstance(local, list) and len(local) >= 3:
        p = (float(local[0]), float(local[1]), float(local[2]))
    else:
        p = mesh_anchor(scene_obj.mesh, anchor_name)
        if p is None:
            return None
        # mesh-derived anchors are already in object/world coordinates after generation+ops
        local_is_world = True

    if local_is_world:
        return p

    cur: Optional[LiveObject] = scene_obj
    out = p
    while cur is not None:
        transform = cur.meta.get("transform")
        if isinstance(transform, dict):
            out = apply_transform_to_point(out, transform)
        parent_name = cur.meta.get("parent")
        cur = object_by_name.get(str(parent_name)) if parent_name else None
    return out


def apply_attach_constraints(scene: Scene) -> None:
    object_by_name = {o.name: o for o in scene.objects}
    for obj in scene.objects:
        spec = parse_attach_spec(obj.meta.get("attach"))
        if not spec:
            continue
        self_anchor, target_obj_name, target_anchor = spec
        target_obj = object_by_name.get(target_obj_name)
        if target_obj is None:
            continue
        self_world = resolve_object_anchor_world(obj, self_anchor, object_by_name)
        target_world = resolve_object_anchor_world(target_obj, target_anchor, object_by_name)
        if self_world is None or target_world is None:
            continue
        delta = (
            target_world[0] - self_world[0],
            target_world[1] - self_world[1],
            target_world[2] - self_world[2],
        )
        obj.mesh = translate_mesh(obj.mesh, delta)


def op_displace(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    field = str(op.get("field", "wave"))
    axis = str(op.get("axis", "z"))
    amp = float(op.get("amplitude", op.get("strength", 0.1)))
    freq = float(op.get("frequency", 1.0))
    seed = int(op.get("seed", 0))
    out = mesh.copy()
    vs = []
    for x,y,z in out.vertices:
        if field == "wave":
            d = amp * math.sin(freq*x) * math.cos(freq*y)
        else:
            d = amp * (math.sin(freq*x + seed)*0.5 + math.sin(freq*y*1.7 + seed*.37)*0.3 + math.sin(freq*z*2.3 + seed*.11)*0.2)
        if axis == "x": x += d
        elif axis == "y": y += d
        else: z += d
        vs.append((x,y,z))
    out.vertices = vs
    return out


def op_smooth(mesh: Mesh, iterations: int = 1, strength: float = 0.5) -> Mesh:
    out = mesh.copy()
    for _ in range(iterations):
        nbr = {i: set() for i in range(1, len(out.vertices)+1)}
        for face in out.faces:
            for i,a in enumerate(face):
                b = face[(i+1)%len(face)]
                nbr[a].add(b); nbr[b].add(a)
        newv = list(out.vertices)
        for idx1, ns in nbr.items():
            if not ns:
                continue
            idx = idx1 - 1
            x,y,z = out.vertices[idx]
            ax = sum(out.vertices[n-1][0] for n in ns)/len(ns)
            ay = sum(out.vertices[n-1][1] for n in ns)/len(ns)
            az = sum(out.vertices[n-1][2] for n in ns)/len(ns)
            newv[idx] = (x*(1-strength)+ax*strength, y*(1-strength)+ay*strength, z*(1-strength)+az*strength)
        out.vertices = newv
    return out


def op_mirror(mesh: Mesh, axis: str = "x") -> Mesh:
    m = Mesh()
    for x,y,z in mesh.vertices:
        if axis == "x": m.vertices.append((-x,y,z))
        elif axis == "y": m.vertices.append((x,-y,z))
        else: m.vertices.append((x,y,-z))
    m.faces = [list(reversed(f)) for f in mesh.faces]
    out = mesh.copy()
    out.extend(m)
    return out


def op_array(mesh: Mesh, count: int, offset: Vec3) -> Mesh:
    out = Mesh()
    ox,oy,oz = offset
    for i in range(count):
        m = mesh.copy()
        m.vertices = [(x+ox*i, y+oy*i, z+oz*i) for x,y,z in m.vertices]
        out.extend(m)
    return out


def op_tread(mesh: Mesh, op: Dict[str, Any]) -> Mesh:
    count = int(op.get("count", 12))
    depth = float(op.get("depth", 0.035))
    if not mesh.vertices:
        return mesh
    xs, ys, zs = [v[0] for v in mesh.vertices], [v[1] for v in mesh.vertices], [v[2] for v in mesh.vertices]
    cx, cy, cz = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2
    width = max(xs)-min(xs)
    r = max(max(ys)-min(ys), max(zs)-min(zs))/2
    out = mesh.copy()
    for i in range(count):
        a = 2*math.pi*i/count
        y = cy + math.cos(a)*(r+depth/2)
        z = cz + math.sin(a)*(r+depth/2)
        out.extend(box_mesh((cx,y,z),(width*1.05,depth,depth*1.4)))
    return out


def apply_ops(mesh: Mesh, obj: LiveObject) -> Mesh:
    out = mesh
    if isinstance(obj.meta.get("transform"), dict):
        out = apply_transform(out, obj.meta["transform"])

    for op in obj.ops:
        name = op.get("op")
        if name == "displace":
            out = op_displace(out, op)
        elif name == "smooth":
            out = op_smooth(out, int(op.get("iterations",1)), float(op.get("strength",0.5)))
        elif name == "mirror":
            out = op_mirror(out, str(op.get("axis","x")))
        elif name == "array":
            offset = op.get("offset", [1,0,0])
            out = op_array(out, int(op.get("count",2)), tuple(map(float, offset)))
        elif name == "tread":
            out = op_tread(out, op)
        elif name == "bevel":
            # placeholder
            pass
    return out


# ----------------------------
# Object execution
# ----------------------------

def generate_procedural(obj: LiveObject) -> Mesh:
    typ = str(obj.meta.get("type", "mesh"))
    params = obj.meta.get("params", {}) or {}

    if typ == "mesh":
        return obj.mesh.copy()

    center = params.get("center", params.get("position", [0,0,0]))
    center = tuple(map(float, center))

    if typ == "box":
        size = params.get("size", [params.get("width",1), params.get("depth",params.get("length",1)), params.get("height",1)])
        return box_mesh(center, tuple(map(float, size)))
    if typ == "cylinder":
        return cylinder_mesh(
            str(params.get("axis","z")),
            center,
            float(params.get("radius",0.5)),
            float(params.get("depth", params.get("height", params.get("width",1)))),
            int(params.get("segments",16)),
        )
    if typ in {"surface_grid", "heightfield"}:
        return surface_grid(float(params.get("width",10)), float(params.get("depth",10)), int(params.get("resolution",20)), center)

    return obj.mesh.copy()


def generate_sdf(obj: LiveObject) -> Mesh:
    params = obj.meta.get("params", {}) or {}
    expr = build_sdf(obj)
    if expr is None:
        return obj.mesh.copy()
    bounds = params.get("bounds", [[-2,-2,-2],[2,2,2]])
    resolution = float(params.get("resolution", 0.15))
    return sdf_to_voxel_mesh(expr, bounds, resolution)


def generate_simulation(obj: LiveObject) -> Mesh:
    sim = str(obj.meta.get("sim", ""))
    params = obj.meta.get("params", {}) or {}

    if sim == "cellular_automata":
        return cellular_automata_mesh(params)
    if sim == "differential_growth":
        return differential_growth_mesh(params)
    if sim == "boids":
        return boids_mesh(params)

    return obj.mesh.copy()


def execute_scene(scene: Scene) -> Scene:
    for obj in scene.objects:
        source = str(obj.meta.get("source", "llm_mesh"))

        if source == "assembly":
            continue
        if source == "procedural":
            base = generate_procedural(obj)
        elif source == "sdf":
            base = generate_sdf(obj)
        elif source == "simulation":
            base = generate_simulation(obj)
        else:
            base = obj.mesh.copy()

        obj.mesh = apply_ops(base, obj)

    apply_attach_constraints(scene)

    return scene


def serialize_scene(scene: Scene) -> str:
    lines: List[str] = []
    lines.extend(scene.header_lines)
    global_index = 1

    for obj in scene.objects:
        lines.append("")
        lines.append(f"{obj.declaration} {obj.name}")
        lines.extend(obj.meta_lines)
        for l in obj.raw_nonlive_lines:
            if l.strip():
                lines.append(l)
        for x,y,z in obj.mesh.vertices:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for face in obj.mesh.faces:
            lines.append("f " + " ".join(str(global_index+i-1) for i in face))
        global_index += len(obj.mesh.vertices)

    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Execute Live OBJ metadata and refresh OBJ mesh cache.")
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()

    output = args.output or args.input.with_suffix(".executed.obj")
    scene = parse_obj(args.input)
    execute_scene(scene)
    output.write_text(serialize_scene(scene), encoding="utf-8")

    print(f"Wrote {output}")
    print(f"Objects: {len(scene.objects)}")
    print(f"Vertices: {sum(len(o.mesh.vertices) for o in scene.objects)}")
    print(f"Faces: {sum(len(o.mesh.faces) for o in scene.objects)}")


if __name__ == "__main__":
    main()
