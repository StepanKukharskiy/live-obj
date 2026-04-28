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

Parametric assemblies (v0.2+)
-------------------------------
- Assembly #@params: are numeric design variables (e.g. seat_width=0.5).
- #@anchors: entries may be expressions using those param names, or literal lists, e.g.:
  leg_FR=[(seat_width/2-leg_inset),-(seat_depth/2-leg_inset),leg_height/2]
- Child #@source: procedural objects with #@parent: assembly_name receive merged param scope
  from the parent, so lists like size=[leg_size,leg_size,leg_height] and center=anchor(chair_01.leg_FL)
  (only anchor(assembly.anchor) calls allowed; no arbitrary Python) resolve before meshing.
- Execution order: topological by #@parent, resolve assembly anchors, then expand each child.

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
    parts: List[str] = []
    cur: List[str] = []
    square_depth = 0
    paren_depth = 0
    brace_depth = 0
    quote: Optional[str] = None
    escape = False
    for ch in s:
        if quote is not None:
            cur.append(ch)
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == quote:
                quote = None
            continue

        if ch in {"'", '"'}:
            quote = ch
            cur.append(ch)
            continue

        if ch == "[":
            square_depth += 1
        elif ch == "]":
            square_depth = max(0, square_depth - 1)
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)

        if ch == "," and square_depth == 0 and paren_depth == 0 and brace_depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


def parse_key_values_space_separated(s: str) -> Dict[str, Any]:
    """Parse `count=12 offset=[0,0,1]` (space-separated pairs; bracket values may contain commas)."""
    result: Dict[str, Any] = {}
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        eq = s.find("=", i)
        if eq < 0:
            break
        key = s[i:eq].strip()
        i = eq + 1
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            result[key] = True
            break
        if s[i] == "[":
            depth, j = 0, i
            while j < n:
                if s[j] == "[":
                    depth += 1
                elif s[j] == "]":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            val = s[i:j]
            i = j
        else:
            j = i
            while j < n and not s[j].isspace():
                j += 1
            val = s[i:j]
            i = j
        result[key] = parse_scalar(val.strip())
    return result


def parse_key_values(s: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    parts = split_top_level_commas(s)
    ambiguous = False
    for part in parts:
        if not part:
            continue
        if "=" not in part:
            result[part.strip()] = True
            continue
        k, v = part.split("=", 1)
        if " " in v.strip() and re.search(r"\s+[A-Za-z_][A-Za-z0-9_]*\s*=", v):
            ambiguous = True
            break
        result[k.strip()] = parse_scalar(v)
    if ambiguous:
        return parse_key_values_space_separated(s.strip())
    return result


# ----------------------------
# Parametric: expressions + assembly scope
# ----------------------------


def parse_list_body(s: str) -> str:
    """Return inner of [...] (first matching bracket pair) or original stripped."""
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        return s[1:-1].strip()
    if s.startswith("(") and s.endswith(")"):
        return s[1:-1].strip()
    return s


def _validate_safe_ast(node: ast.AST) -> None:
    """Allow only safe numeric expressions + single anchor(assembly.anchor) calls."""
    bad = (
        ast.Import, ast.ImportFrom, ast.Lambda, ast.Await, ast.Yield, ast.Dict, ast.Set,
        ast.GeneratorExp, ast.ListComp, ast.DictComp, ast.SetComp, ast.Starred, ast.Ellipsis,
    )
    for child in ast.walk(node):
        if isinstance(child, bad):
            raise ValueError("unsupported syntax in parametric expression")
        if isinstance(child, ast.Call):
            f = child.func
            if not (isinstance(f, ast.Name) and f.id == "anchor"):
                raise ValueError("only anchor(assembly.anchor_id) is allowed as a function call")
            if len(child.args) != 1 or child.keywords:
                raise ValueError("anchor() takes exactly one dotted reference")
            a0 = child.args[0]
            if not (isinstance(a0, ast.Attribute) and isinstance(a0.value, ast.Name)):
                raise ValueError("use anchor(chair_01.leg_FL) (assembly.anchor name)")


def _eval_ast_safe(
    node: ast.AST,
    env: Dict[str, Any],
    obn: Dict[str, LiveObject],
) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_ast_safe(node.body, env, obn)
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            raise ValueError("string constants not allowed in numeric expressions (use unquoted param names)")
        raise ValueError("unsupported constant type")
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise KeyError(f"unknown name in expression: {node.id}")
        w = env[node.id]
        if isinstance(w, (list, tuple)) and len(w) == 3:
            raise TypeError("vector values cannot be used as scalars; reference components explicitly")
        if isinstance(w, (int, float)):
            return float(w)
        raise TypeError(f"parameter {node.id!r} is not numeric")
    if isinstance(node, ast.UnaryOp):
        v = _eval_ast_safe(node.operand, env, obn)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        raise TypeError("unsupported unary op")
    if isinstance(node, ast.BinOp):
        a = _eval_ast_safe(node.left, env, obn)
        b = _eval_ast_safe(node.right, env, obn)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        if isinstance(node.op, ast.Pow):
            return a ** b
        raise TypeError("unsupported binary op")
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "anchor":
            if len(node.args) != 1 or node.keywords:
                raise ValueError("anchor() takes one dotted reference")
            arg0 = node.args[0]
            if not (isinstance(arg0, ast.Attribute) and isinstance(arg0.value, ast.Name)):
                raise ValueError("anchor(assembly_id.anchor_id)")
            assembly_name = arg0.value.id
            anchor_id = arg0.attr
            ass = obn.get(assembly_name)
            if ass is None:
                raise KeyError(f"unknown assembly: {assembly_name}")
            m = (ass.meta.get("anchors") or {})
            vec = m.get(anchor_id)
            if not (isinstance(vec, (list, tuple)) and len(vec) >= 3):
                raise KeyError(f"anchor {assembly_name!r}.{anchor_id!r} not available (define #@anchors on the assembly, run assembly resolution first)")
            return (float(vec[0]), float(vec[1]), float(vec[2]))
    raise TypeError("unsupported expression form")


def eval_mixed_value(expr_str: Any, env: Dict[str, Any], obn: Dict[str, LiveObject]) -> Any:
    if isinstance(expr_str, bool):
        return expr_str
    if isinstance(expr_str, (int, float)):
        return float(expr_str)
    if isinstance(expr_str, (list, tuple)):
        return [eval_mixed_value(p, env, obn) if isinstance(p, str) else float(p) if isinstance(p, (int, float)) else p for p in expr_str]
    if not isinstance(expr_str, str):
        return expr_str
    s = expr_str.strip()
    if not s:
        return None
    if s.startswith("[") and s.endswith("]"):
        body = parse_list_body(s)
        parts = split_top_level_commas(body)
        return [_eval_arg_piece(p.strip(), env, obn) for p in parts if p.strip()]
    if s.startswith("anchor(") or s.startswith("("):
        tree = ast.parse(s, mode="eval")
        _validate_safe_ast(tree)
        return _eval_ast_safe(tree, env, obn)
    if re.match(r"^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$", s) or re.match(r"^[-+]?[0-9]+$", s):
        return float(s) if any(c in s for c in ".eE") else float(int(s))
    try:
        tree = ast.parse(s, mode="eval")
        _validate_safe_ast(tree)
        return _eval_ast_safe(tree, env, obn)
    except SyntaxError as e:
        raise ValueError(f"could not parse expression: {s!r}") from e


def _eval_arg_piece(p: str, env: Dict[str, Any], obn: Dict[str, LiveObject]) -> Any:
    return eval_mixed_value(p, env, obn)


def resolve_assembly_anchors(asm: LiveObject, obn: Dict[str, LiveObject]) -> None:
    if str(asm.meta.get("source", "")) != "assembly":
        return
    params = asm.meta.get("params") or {}
    env0 = assembly_params_eval_env(params, obn)
    raw = asm.meta.get("anchors") or {}
    resolved: Dict[str, Any] = {}
    for aname, aval in raw.items():
        v = _resolve_anchor_value(aval, env0, obn)
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            resolved[aname] = (float(v[0]), float(v[1]), float(v[2]))
        else:
            raise ValueError(f"anchor {aname!r} must resolve to a 3-vector, got {v!r}")
    asm.meta["anchors"] = resolved


def _resolve_anchor_value(aval: Any, env0: Dict[str, Any], obn: Dict[str, LiveObject]) -> Any:
    if isinstance(aval, (int, float)):
        return float(aval)
    if isinstance(aval, (list, tuple)) and len(aval) == 3:
        env = dict(env0)
        out = []
        for i, p in enumerate(aval):
            if isinstance(p, (int, float)):
                out.append(float(p))
            elif isinstance(p, str):
                r = _eval_string_or_scalar(p, env, obn)
                if isinstance(r, (int, float)):
                    out.append(float(r))
                elif isinstance(r, (list, tuple)) and len(r) == 3:
                    raise ValueError("nested vectors not supported in one anchor component")
                else:
                    raise TypeError("anchor list element type")
        return tuple(out)  # type: ignore
    if isinstance(aval, str) and aval.strip().startswith("["):
        body = parse_list_body(aval)
        parts = [x.strip() for x in split_top_level_commas(body) if x.strip()]
        env = dict(env0)
        if len(parts) != 3:
            raise ValueError("anchor list must have three comma-separated values")
        return tuple(_eval_string_or_scalar(p, env, obn) for p in parts)  # type: ignore
    if isinstance(aval, str):
        env = dict(env0)
        return _eval_string_or_scalar(aval, env, obn)
    return aval


def _eval_string_or_scalar(s: str, env: Dict[str, Any], obn: Dict[str, LiveObject]) -> Any:
    t = s.strip()
    if not t:
        return 0.0
    r = eval_mixed_value(t, env, obn)
    if isinstance(r, (list, tuple)) and len(r) == 3 and not t.startswith("["):
        # single anchor() call returns 3-tuple; fine
        return r
    if isinstance(r, (int, float)):
        return float(r)
    if isinstance(r, (list, tuple)) and len(r) == 3:
        if t.startswith("anchor("):
            return r
    return r


def topological_objects(objects: List[LiveObject], obn: Dict[str, LiveObject]) -> List[LiveObject]:
    seen: set = set()
    out: List[LiveObject] = []

    def visit(o: LiveObject) -> None:
        if o.name in seen:
            return
        p = o.meta.get("parent")
        if p and str(p) in obn:
            visit(obn[str(p)])
        seen.add(o.name)
        out.append(o)

    for o in objects:
        visit(o)
    return out


# Param keys whose values are axis labels (x/y/z), not numeric expressions or param refs.
_AXIS_PARAM_KEYS = frozenset({"axis"})

# LLM-authored enum tokens (path=helix, mode=linear, …) are single identifiers, not param refs.
_SINGLE_IDENTIFIER_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def assembly_params_eval_env(params: Optional[Dict[str, Any]], obn: Dict[str, LiveObject]) -> Dict[str, Any]:
    """Resolve assembly #@params values for anchors and inherited child params — same rules as child param merge:
    string values may be arithmetic expressions referencing other params (e.g. rise_per_step=num_steps * 0.04).
    Multiple passes allow params to appear in any order in the OBJ metadata."""
    merged: Dict[str, Any] = {}
    pending = {k: v for k, v in (params or {}).items() if not isinstance(v, bool)}
    if not pending:
        return merged
    max_rounds = max(len(pending) + 2, 12)
    for _ in range(max_rounds):
        if not pending:
            return merged
        settled: List[str] = []
        for k, v in list(pending.items()):
            if not isinstance(v, str):
                if isinstance(v, (int, float)):
                    merged[k] = float(v)
                else:
                    merged[k] = v
                settled.append(k)
                continue
            vs = v.strip()
            if k in _AXIS_PARAM_KEYS and vs in ("x", "y", "z"):
                merged[k] = vs
                settled.append(k)
                continue
            try:
                merged[k] = eval_mixed_value(vs, {**merged}, obn)
                settled.append(k)
            except KeyError:
                if _SINGLE_IDENTIFIER_TOKEN.match(vs):
                    merged[k] = vs
                    settled.append(k)
        for k in settled:
            pending.pop(k, None)
        if not settled:
            break
    if pending:
        k0, v0 = next(iter(pending.items()))
        if isinstance(v0, str):
            eval_mixed_value(v0.strip(), {**merged}, obn)
        raise ValueError(
            f"could not resolve assembly #@params (missing refs or cyclic?): "
            f"stuck keys {list(pending.keys())!r}"
        )
    return merged


def get_effective_params(obj: LiveObject, obn: Dict[str, LiveObject]) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    pn = obj.meta.get("parent")
    if pn and str(pn) in obn:
        pobj = obn[str(pn)]
        if str(pobj.meta.get("source", "")) == "assembly":
            base = dict(assembly_params_eval_env(pobj.meta.get("params") or {}, obn))
    raw = obj.meta.get("params") or {}
    merged: Dict[str, Any] = {}
    for k, v in raw.items():
        if not isinstance(v, str):
            merged[k] = v
        else:
            vs = v.strip()
            if k in _AXIS_PARAM_KEYS and vs in ("x", "y", "z"):
                merged[k] = vs
            else:
                env: Dict[str, Any] = {**base, **merged}
                try:
                    merged[k] = eval_mixed_value(vs, env, obn)
                except KeyError:
                    if _SINGLE_IDENTIFIER_TOKEN.match(vs):
                        merged[k] = vs
                    else:
                        raise
    out = {**base, **merged}
    return out


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
        if body == "params:":
            block = "params"
            meta.setdefault("params", {})
            continue
        if body == "anchors:":
            block = "anchors"
            meta["anchors"] = {}
            continue

        if block == "params":
            params_body = body[1:].strip() if body.startswith("-") else body
            if params_body:
                for k, v in parse_key_values(params_body).items():
                    meta.setdefault("params", {})[k] = v
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
        elif key in {"array", "radial_array", "sweep"}:
            meta[key] = parse_key_values(val)
        else:
            meta[key] = parse_scalar(val)

    return meta, ops, sdf_ops


def _cylinder_anchor_is_base(obj: LiveObject) -> bool:
    """True if center=anchor(assembly.base|floor|bottom) — anchor is floor contact, not volume midpoint."""
    blob = "\n".join(obj.meta_lines)
    return bool(
        re.search(r"center\s*=\s*anchor\s*\([^)]+\.(base|floor|bottom)\s*\)", blob, re.I)
    )


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


def cylinder_mesh(
    axis: str,
    center: Vec3,
    radius: float,
    depth: float,
    segments: int = 16,
    *,
    base_aligned: bool = False,
) -> Mesh:
    cx, cy, cz = center
    verts, faces = [], []
    axis = axis.lower()
    z0, z1 = (0.0, depth) if base_aligned else (-depth / 2, depth / 2)

    def pt(side: float, a: float) -> Vec3:
        ca, sa = math.cos(a), math.sin(a)
        if axis == "x":
            return (cx + side, cy + ca * radius, cz + sa * radius)
        if axis == "y":
            return (cx + ca * radius, cy + side, cz + sa * radius)
        return (cx + ca * radius, cy + sa * radius, cz + side)

    r1, r2 = [], []
    for i in range(segments):
        verts.append(pt(z0, 2 * math.pi * i / segments)); r1.append(len(verts))
    for i in range(segments):
        verts.append(pt(z1, 2 * math.pi * i / segments)); r2.append(len(verts))
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


def _resolve_sdf_value(v: Any, env: Dict[str, Any], obn: Dict[str, LiveObject]) -> Any:
    """Turn assembly param names / expressions in SDF tokens into numbers (or anchor vectors)."""
    if isinstance(v, str):
        vs = v.strip()
        if not vs:
            return v
        try:
            tree = ast.parse(vs, mode="eval")
            _validate_safe_ast(tree)
            return eval_mixed_value(vs, env, obn)
        except (SyntaxError, ValueError, KeyError, TypeError):
            return v
    if isinstance(v, list):
        return [_resolve_sdf_value(x, env, obn) for x in v]
    return v


def build_sdf(sdf_ops: List[Dict[str, Any]]) -> Optional[SDFExpr]:
    registry: Dict[str, SDFExpr] = {}
    current: Optional[SDFExpr] = None

    for cmd in sdf_ops:
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


def spiral_treads_mesh(params: Dict[str, Any], center: Vec3) -> Mesh:
    """Wedge-like tread boxes along a rising helix (LLM spiral stair preset)."""
    count = int(params.get("count", params.get("step_count", 12)))
    total_turn = math.radians(float(params.get("total_turn_degrees", 360)))
    total_h = float(params.get("total_height", 3.0))
    rise = float(params.get("rise_per_step", total_h / max(1, count)))
    r_in = float(params.get("inner_radius", 0.25))
    r_out = float(params.get("outer_radius", 1.0))
    thick = float(params.get("thickness", params.get("tread_thickness", 0.05)))
    tread_deg = float(params.get("tread_angle_degrees", 24))
    tread_ang = math.radians(max(1.0, tread_deg))
    cx, cy, cz = center
    mesh = Mesh()
    r_mid = 0.5 * (r_in + r_out)
    radial = max(0.02, r_out - r_in)
    tangential = max(0.03, r_mid * tread_ang)
    for i in range(count):
        frac = (i * rise) / max(total_h, 1e-6)
        theta = total_turn * frac
        z0 = cz + i * rise
        zc = z0 + thick / 2
        cr, sr = math.cos(theta), math.sin(theta)
        px = cx + r_mid * cr
        py = cy + r_mid * sr
        hx, hy, hz = radial / 2, tangential / 2, thick / 2
        corners: List[Vec3] = []
        for szgn in (-1, 1):
            for srgn, stgn in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                ox = srgn * hx * cr + stgn * hy * (-sr)
                oy = srgn * hx * sr + stgn * hy * cr
                oz = szgn * hz
                corners.append((px + ox, py + oy, zc + oz))
        base = len(mesh.vertices)
        mesh.vertices.extend(corners)

        def fi(*idx: int) -> Face:
            return [base + i for i in idx]

        mesh.faces.append(fi(0, 1, 2, 3))
        mesh.faces.append(fi(4, 7, 6, 5))
        mesh.faces.append(fi(0, 4, 5, 1))
        mesh.faces.append(fi(1, 5, 6, 2))
        mesh.faces.append(fi(2, 6, 7, 3))
        mesh.faces.append(fi(3, 7, 4, 0))
    return mesh


def spiral_post_array_mesh(params: Dict[str, Any], center: Vec3) -> Mesh:
    """Vertical cylinders along the stair spiral at outer radius."""
    count = int(params.get("count", params.get("step_count", 12)))
    total_turn = math.radians(float(params.get("total_turn_degrees", 360)))
    total_h = float(params.get("total_height", 3.0))
    rise = float(params.get("rise_per_step", total_h / max(1, count)))
    r = float(params.get("radius", 1.0))
    post_r = float(params.get("post_radius", 0.025))
    ph = float(params.get("post_height", 0.9))
    cx, cy, cz = center
    mesh = Mesh()
    for i in range(count):
        frac = (i * rise) / max(total_h, 1e-6)
        theta = total_turn * frac
        px = cx + r * math.cos(theta)
        py = cy + r * math.sin(theta)
        pz = cz + i * rise
        mesh.extend(cylinder_mesh("z", (px, py, pz + ph / 2), post_r, ph, 12))
    return mesh


def helix_sweep_mesh(params: Dict[str, Any], center: Vec3) -> Mesh:
    """Tube along a circular helix (rising along +Z).

    Prefer explicit ``profile_radius`` (tube) and ``path_radius`` (XY helix). For legacy `#@ sweep path=helix`
    payloads that only set ``radius``, that value is interpreted as tube cross-section; use ``path_radius`` for XY.
    """
    cx, cy, cz = center
    pr: float
    if params.get("profile_radius") is not None:
        pr = float(params["profile_radius"])
    elif params.get("tube_radius") is not None:
        pr = float(params["tube_radius"])
    else:
        pr = float(params.get("radius", 0.035))

    path_r: float
    if params.get("path_radius") is not None:
        path_r = float(params["path_radius"])
    elif params.get("helix_radius") is not None:
        path_r = float(params["helix_radius"])
    else:
        path_r = 1.0

    if params.get("turns") is not None:
        turn = float(params["turns"]) * 2 * math.pi
    elif params.get("start_angle") is not None and params.get("end_angle") is not None:
        turn = math.radians(float(params["end_angle"]) - float(params["start_angle"]))
    else:
        turn = math.radians(float(params.get("total_turn_degrees", 360)))

    height = float(params.get("height", params.get("total_rise", 3.0)))
    start_z = float(params.get("start_z", params.get("z_offset", 0.0)))
    if params.get("end_z") is not None:
        end_z = float(params["end_z"])
    else:
        end_z = start_z + height

    segs = max(8, int(float(params.get("segments", 48))))
    tube_seg = max(6, min(12, max(4, segs // 12)))
    mesh = Mesh()
    pts: List[Vec3] = []
    for i in range(segs + 1):
        t = i / segs
        th = turn * t
        zz = cz + start_z + t * (end_z - start_z)
        pts.append((cx + path_r * math.cos(th), cy + path_r * math.sin(th), zz))
    for i in range(len(pts) - 1):
        mesh.extend(tube_between(pts[i], pts[i + 1], pr, tube_seg))
    return mesh


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

def _resolve_vec3_meta(
    val: Any,
    env: Dict[str, Any],
    obn: Dict[str, LiveObject],
    defaults: Tuple[float, float, float],
) -> List[float]:
    """Resolve position/rotation/scale lists that may contain param names or expressions (from #@transform)."""
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("[") and s.endswith("]"):
            parts = [p.strip() for p in split_top_level_commas(parse_list_body(s)) if p.strip()]
            val = parts if len(parts) >= 3 else val
    if not isinstance(val, (list, tuple)) or len(val) < 3:
        return [defaults[0], defaults[1], defaults[2]]
    out: List[float] = []
    for i in range(3):
        p = val[i]
        if isinstance(p, (int, float)):
            out.append(float(p))
        elif isinstance(p, str):
            out.append(float(eval_mixed_value(p.strip(), env, obn)))
        else:
            raise TypeError(f"transform component must be number or expression, got {p!r}")
    return out


def resolve_transform_dict(transform: Dict[str, Any], env: Dict[str, Any], obn: Dict[str, LiveObject]) -> Dict[str, Any]:
    t = dict(transform)
    if "position" in t:
        t["position"] = _resolve_vec3_meta(t["position"], env, obn, (0.0, 0.0, 0.0))
    if "scale" in t:
        t["scale"] = _resolve_vec3_meta(t["scale"], env, obn, (1.0, 1.0, 1.0))
    if "rotation" in t:
        t["rotation"] = _resolve_vec3_meta(t["rotation"], env, obn, (0.0, 0.0, 0.0))
    return t


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
    def point_bbox_distance(point: Vec3, bbox: Tuple[float, float, float, float, float, float]) -> float:
        minx, maxx, miny, maxy, minz, maxz = bbox
        dx = 0.0 if minx <= point[0] <= maxx else min(abs(point[0] - minx), abs(point[0] - maxx))
        dy = 0.0 if miny <= point[1] <= maxy else min(abs(point[1] - miny), abs(point[1] - maxy))
        dz = 0.0 if minz <= point[2] <= maxz else min(abs(point[2] - minz), abs(point[2] - maxz))
        return dx + dy + dz

    def object_origin(local_obj: LiveObject) -> Vec3:
        params = local_obj.meta.get("params", {}) or {}
        center = params.get("center", params.get("position", [0,0,0]))
        if isinstance(center, list) and len(center) >= 3:
            return (float(center[0]), float(center[1]), float(center[2]))
        return (0.0, 0.0, 0.0)

    anchors = scene_obj.meta.get("anchors", {}) or {}
    local = anchors.get(anchor_name)
    local_is_world = False
    if isinstance(local, (list, tuple)) and len(local) >= 3:
        raw = (float(local[0]), float(local[1]), float(local[2]))
        mesh_bbox = compute_bbox(scene_obj.mesh)
        # Authoring is mixed in the wild: some scenes emit object-local anchor vectors,
        # others emit already-world anchor points. If mesh exists, pick the interpretation
        # that best matches the current generated mesh bbox.
        if mesh_bbox is not None:
            origin = object_origin(scene_obj)
            local_candidate = (raw[0] + origin[0], raw[1] + origin[1], raw[2] + origin[2])
            transform = scene_obj.meta.get("transform")
            if isinstance(transform, dict):
                local_candidate = apply_transform_to_point(local_candidate, transform)
            abs_candidate = raw
            p = local_candidate if point_bbox_distance(local_candidate, mesh_bbox) <= point_bbox_distance(abs_candidate, mesh_bbox) else abs_candidate
            local_is_world = True
        else:
            origin = object_origin(scene_obj)
            p = (raw[0] + origin[0], raw[1] + origin[1], raw[2] + origin[2])
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


def rotate_mesh_z(mesh: Mesh, rad: float) -> Mesh:
    """CCW rotation in XY (standard right-handed Z-up)."""
    if abs(rad) < 1e-12:
        return mesh.copy()
    c, s = math.cos(rad), math.sin(rad)
    out = Mesh(faces=[list(f) for f in mesh.faces])
    for x, y, z in mesh.vertices:
        out.vertices.append((x * c - y * s, x * s + y * c, z))
    return out


def _resolve_meta_spec_dict(spec: Any, env: Dict[str, Any], obn: Dict[str, LiveObject]) -> Optional[Dict[str, Any]]:
    if spec is None:
        return None
    if isinstance(spec, str):
        spec = parse_key_values(spec)
    if not isinstance(spec, dict):
        return None
    out: Dict[str, Any] = {}
    for k, v in spec.items():
        if isinstance(v, str):
            vs = v.strip()
            try:
                out[k] = eval_mixed_value(vs, env, obn)
            except KeyError:
                if _SINGLE_IDENTIFIER_TOKEN.match(vs):
                    out[k] = vs
                else:
                    raise
        elif isinstance(v, list):
            row: List[Any] = []
            for el in v:
                if isinstance(el, str):
                    row.append(eval_mixed_value(el.strip(), env, obn))
                elif isinstance(el, (int, float)):
                    row.append(float(el))
                else:
                    row.append(el)
            out[k] = row
        else:
            out[k] = v
    return out


def apply_meta_instancing(mesh: Mesh, obj: LiveObject, obn: Dict[str, LiveObject]) -> Mesh:
    """#@array (linear) and/or #@radial_array (around Z): combined gives spiral step placement."""
    arr_raw = obj.meta.get("array")
    rad_raw = obj.meta.get("radial_array")
    if not arr_raw and not rad_raw:
        return mesh
    env = get_effective_params(obj, obn)
    arr = _resolve_meta_spec_dict(arr_raw, env, obn) or {}
    rad = _resolve_meta_spec_dict(rad_raw, env, obn) or {}
    count = 1
    if arr:
        count = max(count, int(arr.get("count", 1)))
    if rad:
        count = max(count, int(rad.get("count", 1)))
    count = max(1, count)

    ox = oy = oz = 0.0
    if arr:
        off = arr.get("offset", [0, 0, 0])
        if isinstance(off, (list, tuple)) and len(off) >= 3:
            ox, oy, oz = float(off[0]), float(off[1]), float(off[2])

    axis = str(rad.get("axis", "z")).lower() if rad else "z"
    radius = float(rad.get("radius", 0.0)) if rad else 0.0

    if rad and not arr:
        out = Mesh()
        for i in range(count):
            th = 2 * math.pi * i / count
            if axis == "z":
                dx, dy, dz = radius * math.cos(th), radius * math.sin(th), 0.0
            elif axis == "y":
                dx, dy, dz = radius * math.cos(th), 0.0, radius * math.sin(th)
            else:
                dx, dy, dz = 0.0, radius * math.cos(th), radius * math.sin(th)
            m = mesh.copy()
            m.vertices = [(x + dx, y + dy, z + dz) for x, y, z in m.vertices]
            out.extend(m)
        return out
    if arr and not rad:
        return op_array(mesh, count, (ox, oy, oz))

    # Combined linear + radial: spiral stairs — rotate in XY so local +Y (second size component → depth / radial run)
    # points outward; local +X (width) runs tangentially along the arc.
    out = Mesh()
    for i in range(count):
        th = 2 * math.pi * i / count
        orient = (th - math.pi / 2) if axis == "z" else 0.0
        if axis == "z":
            dx = radius * math.cos(th) + ox * i
            dy = radius * math.sin(th) + oy * i
            dz = oz * i
        elif axis == "y":
            dx = radius * math.cos(th) + ox * i
            dy = oy * i
            dz = radius * math.sin(th) + oz * i
        else:
            dx = ox * i
            dy = radius * math.cos(th) + oy * i
            dz = radius * math.sin(th) + oz * i
        m = rotate_mesh_z(mesh, orient)
        m.vertices = [(x + dx, y + dy, z + dz) for x, y, z in m.vertices]
        out.extend(m)
    return out


def _infer_handrail_radius_from_radial_steps(steps_obj: LiveObject, obn: Dict[str, LiveObject]) -> Optional[float]:
    """Radial distance to tread box center orbit for `#@radial_array` spirals."""
    env = get_effective_params(steps_obj, obn)
    rad_raw = steps_obj.meta.get("radial_array")
    specs = _resolve_meta_spec_dict(rad_raw, env, obn) if rad_raw else None
    pole = env.get("pole_radius", env.get("inner_radius"))
    sz = env.get("size")
    # Spiral instancing rotates +local Y radially outward; size[1] = radial run, size[0] ≈ chord.
    radial_half = float(sz[1]) / 2.0 if isinstance(sz, (list, tuple)) and len(sz) >= 2 else None
    tangential_half = float(sz[0]) / 2.0 if isinstance(sz, (list, tuple)) and len(sz) >= 2 else None
    if specs and specs.get("radius") is not None and pole is not None and radial_half is not None and tangential_half is not None:
        explicit = float(specs["radius"])
        pf = float(pole)
        # Common authoring bug: `radius=pole_radius + step_width/2` instead of `+ step_depth/2`.
        wrong_guess = pf + tangential_half
        right_guess = pf + radial_half
        if abs(explicit - wrong_guess) < 1e-4 and abs(explicit - right_guess) > 1e-4:
            return right_guess
        return explicit
    if specs and specs.get("radius") is not None:
        return float(specs["radius"])
    if pole is None or not isinstance(sz, (list, tuple)) or len(sz) < 2:
        return None
    return float(pole) + float(sz[1]) / 2.0


def _curve_sweep_resolve_path_radius(
    params: Dict[str, Any], sweep: Dict[str, Any], obn: Optional[Dict[str, LiveObject]]
) -> float:
    """Params often say `radius=handrail_radius` (tube)—that must NOT become XY path radius (~0.05 m). Prefer `along=steps`."""
    if params.get("path_radius") is not None:
        return float(params["path_radius"])
    if params.get("helix_radius") is not None:
        return float(params["helix_radius"])

    sweep_tube_r: Optional[float] = None
    if sweep.get("radius") is not None:
        sr = sweep["radius"]
        if not isinstance(sr, str):
            sweep_tube_r = float(sr)

    pr = params.get("radius")
    ambiguous_tube_duplicate = False
    if pr is not None:
        prv = float(pr)
        if sweep_tube_r is not None and abs(prv - sweep_tube_r) < 1e-5:
            ambiguous_tube_duplicate = True
        elif sweep_tube_r is not None and prv < 3.0 * sweep_tube_r:
            ambiguous_tube_duplicate = True

    along = sweep.get("along") or params.get("along")
    if along and obn:
        sob = obn.get(str(along).strip())
        if sob is not None:
            inf = _infer_handrail_radius_from_radial_steps(sob, obn)
            if inf is not None:
                return inf

    if pr is not None and not ambiguous_tube_duplicate:
        return float(pr)
    return 1.0


def curve_sweep_tube_mesh(
    params: Dict[str, Any], center: Vec3, sweep: Dict[str, Any], obn: Optional[Dict[str, LiveObject]] = None
) -> Mesh:
    """Helical sweep tube ascending +Z. `sweep.radius` = tube; XY path from `path_radius` / `along=steps`.

    `#@radial_array` + box: after `rotate_mesh_z`, local +Y points outward radially, so
    `size=[width, depth, height]` → **depth (Y)** = tread run (radial thickness), **width (X)** ≈ chord / along-arc length.
    Prefer `#@radial_array: radius=pole_radius + depth/2` (not `+ width/2`).
    """
    path_r = _curve_sweep_resolve_path_radius(params, sweep, obn)
    tr = sweep.get("radius", params.get("handrail_radius", 0.05))
    if isinstance(tr, (int, float)):
        tube_r = float(tr)
    else:
        tube_r = float(params.get("handrail_radius", 0.05))

    height = float(params.get("height", params.get("pole_height", params.get("total_rise", 3.0))))
    z0 = float(params.get("base_z", params.get("z0", params.get("start_z", 0.0))))

    theta_top = 2 * math.pi
    if params.get("total_turn_degrees") is not None:
        theta_top = math.radians(float(params["total_turn_degrees"]))
    elif params.get("step_count") is not None:
        sc = max(1, int(float(params["step_count"])))
        theta_top = 2 * math.pi * (sc - 1) / sc if sc > 1 else 2 * math.pi

    segs = max(32, int(float(params.get("segments", 48))))
    cx, cy, cz = center
    mesh = Mesh()
    pts: List[Vec3] = []
    for i in range(segs + 1):
        t = i / segs
        th = theta_top * t
        zz = cz + z0 + t * height
        pts.append((cx + path_r * math.cos(th), cy + path_r * math.sin(th), zz))
    tube_seg = max(6, min(12, segs // 8))
    for i in range(len(pts) - 1):
        mesh.extend(tube_between(pts[i], pts[i + 1], tube_r, tube_seg))
    return mesh


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

def _as_float3(val: Any, default: Tuple[float, float, float]) -> Tuple[float, float, float]:
    v = val if val is not None else default
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return (float(v[0]), float(v[1]), float(v[2]))
    raise TypeError(f"expected 3 floats, got {val!r}")


def merge_sweep_params_with_along_helix(
    sw_params: Dict[str, Any], along_raw: Any, obn: Dict[str, LiveObject]
) -> Dict[str, Any]:
    """Resolve `#@type: sweep` + `along=some_curve` by merging helix path parameters from the named `curve` object."""
    out = dict(sw_params)
    along_name = str(along_raw or "").strip()
    tube_profile: Optional[float] = None
    if str(out.get("profile", "")).lower() == "circle":
        tr = out.get("radius", out.get("rail_radius", out.get("stringer_radius")))
        if tr is not None:
            tube_profile = float(tr)

    cur = obn.get(along_name) if along_name else None
    if cur is None:
        if tube_profile is not None:
            out["profile_radius"] = tube_profile
        return out

    cp = get_effective_params(cur, obn)
    shape = str(cp.get("shape", "")).lower()
    if str(cur.meta.get("type", "")).lower() != "curve" and shape != "helix":
        if tube_profile is not None:
            out["profile_radius"] = tube_profile
        return out

    if cp.get("radius") is not None:
        out["path_radius"] = float(cp["radius"])
    if cp.get("height") is not None:
        out["height"] = float(cp["height"])
    elif cp.get("total_rise") is not None:
        out["height"] = float(cp["total_rise"])
    if cp.get("turns") is not None:
        out["turns"] = float(cp["turns"])
    if cp.get("total_turn_degrees") is not None:
        out["total_turn_degrees"] = float(cp["total_turn_degrees"])
    if cp.get("start_angle") is not None:
        out["start_angle"] = float(cp["start_angle"])
    if cp.get("end_angle") is not None:
        out["end_angle"] = float(cp["end_angle"])
    if cp.get("segments") is not None:
        out["segments"] = int(float(cp["segments"]))
    if cp.get("z_offset") is not None:
        z_off = float(cp["z_offset"])
        out["start_z"] = z_off
        out["z_offset"] = z_off

    if tube_profile is not None:
        out["profile_radius"] = tube_profile
    return out


def generate_procedural(obj: LiveObject, obn: Optional[Dict[str, LiveObject]] = None) -> Mesh:
    typ = str(obj.meta.get("type", "mesh"))
    params = obj.meta.get("params", {}) or {}
    center = _as_float3(params.get("center", params.get("position", [0, 0, 0])), (0.0, 0.0, 0.0))

    if typ == "mesh":
        gen = str(params.get("generator", ""))
        if gen == "spiral_treads":
            return spiral_treads_mesh(params, center)
        if gen == "spiral_post_array":
            return spiral_post_array_mesh(params, center)
        return obj.mesh.copy()

    if typ == "sweep":
        p = dict(params)
        along = p.get("along")
        if along and obn is not None:
            p = merge_sweep_params_with_along_helix(p, along, obn)
        path_k = str(p.get("path", p.get("shape", "line"))).lower()
        if path_k == "helix" or p.get("path_radius") is not None or bool(along and obn is not None):
            return helix_sweep_mesh(p, center)
        return obj.mesh.copy()

    if typ == "curve":
        sw = obj.meta.get("sweep")
        if isinstance(sw, dict) and str(sw.get("profile", "circle")).lower() == "circle":
            return curve_sweep_tube_mesh(params, center, sw, obn)
        return obj.mesh.copy()

    if typ == "box":
        size = params.get("size", [params.get("width", 1), params.get("depth", params.get("length", 1)), params.get("height", 1)])
        if isinstance(size, str):
            raise TypeError("size should be a 3-vector after parametric resolution")
        return box_mesh(center, _as_float3(size, (1.0, 1.0, 1.0)))
    if typ == "cylinder":
        axis = str(params.get("axis", "z")).lower()
        depth = float(params.get("depth", params.get("height", params.get("width", 1))))
        base_aligned = str(params.get("align", "")).lower() in ("base", "bottom") or _cylinder_anchor_is_base(obj)
        if params.get("center") is None and params.get("position") is None:
            if base_aligned:
                center = (0.0, 0.0, 0.0)
            elif axis == "z":
                center = (0.0, 0.0, depth / 2)
            elif axis == "y":
                center = (0.0, depth / 2, 0.0)
            else:
                center = (depth / 2, 0.0, 0.0)
        return cylinder_mesh(
            axis,
            center,
            float(params.get("radius", 0.5)),
            depth,
            int(params.get("segments", 16)),
            base_aligned=base_aligned,
        )
    if typ in {"surface_grid", "heightfield"}:
        return surface_grid(float(params.get("width",10)), float(params.get("depth",10)), int(params.get("resolution",20)), center)

    return obj.mesh.copy()


def generate_sdf(obj: LiveObject, obn: Dict[str, LiveObject]) -> Mesh:
    params = obj.meta.get("params", {}) or {}
    env = get_effective_params(obj, obn)
    resolved_ops = [
        {k: _resolve_sdf_value(val, env, obn) for k, val in cmd.items()}
        for cmd in obj.sdf_ops
    ]
    expr = build_sdf(resolved_ops)
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
    obn: Dict[str, LiveObject] = {o.name: o for o in scene.objects}
    order = topological_objects(scene.objects, obn)
    for obj in order:
        if str(obj.meta.get("source", "")) == "assembly":
            resolve_assembly_anchors(obj, obn)
    for obj in order:
        if isinstance(obj.meta.get("transform"), dict):
            env = get_effective_params(obj, obn)
            obj.meta["transform"] = resolve_transform_dict(obj.meta["transform"], env, obn)
    for obj in order:
        source = str(obj.meta.get("source", "llm_mesh"))
        if source == "assembly":
            continue
        if source == "procedural":
            oldp = obj.meta.get("params")
            obj.meta["params"] = get_effective_params(obj, obn)
            try:
                base = generate_procedural(obj, obn)
                base = apply_meta_instancing(base, obj, obn)
            finally:
                if oldp is not None:
                    obj.meta["params"] = oldp
        elif source == "sdf":
            base = generate_sdf(obj, obn)
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
