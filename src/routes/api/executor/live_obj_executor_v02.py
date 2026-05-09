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
class LiveObject:
    name: str
    declaration: str = "o"
    meta_lines: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    ops: List[Dict[str, Any]] = field(default_factory=list)
    sdf_ops: List[Dict[str, Any]] = field(default_factory=list)
    recipe_ops: List[Dict[str, Any]] = field(default_factory=list)
    mesh: Mesh = field(default_factory=Mesh)
    raw_nonlive_lines: List[str] = field(default_factory=list)


@dataclass
class Scene:
    header_lines: List[str] = field(default_factory=list)
    objects: List[LiveObject] = field(default_factory=list)
    materials: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def record_kernel_event(obj: LiveObject, event: str) -> None:
    events = obj.meta.setdefault("_kernel_events", [])
    if isinstance(events, list) and event not in events:
        events.append(event)


def metadata_flag(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    return None


def is_explicitly_visible(obj: LiveObject) -> bool:
    for key in ("visible", "render", "renderable"):
        flag = metadata_flag(obj.meta.get(key))
        if flag is True:
            return True
    return False


def is_render_hidden(obj: LiveObject) -> bool:
    if metadata_flag(obj.meta.get("helper")) is True:
        return True
    if metadata_flag(obj.meta.get("hidden")) is True:
        return True
    for key in ("visible", "render", "renderable"):
        flag = metadata_flag(obj.meta.get(key))
        if flag is False:
            return True
    return False


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
    if isinstance(node, ast.Attribute):
        # Support parent.param_name syntax
        if isinstance(node.value, ast.Name) and node.value.id == "parent":
            parent_obj = obn.get(env.get("_parent", ""))
            if parent_obj is None:
                raise KeyError(f"parent object not found")
            parent_params = parent_obj.meta.get("params", {})
            if node.attr not in parent_params:
                raise KeyError(f"parent parameter {node.attr!r} not found")
            val = parent_params[node.attr]
            if isinstance(val, (int, float)):
                return float(val)
            raise TypeError(f"parent parameter {node.attr!r} is not numeric")
        raise ValueError("only parent.param_name attribute references are supported")
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
    if not isinstance(raw, dict):
        print(
            "[live-obj] assembly anchors on '%s' must be a key/value block; ignoring malformed anchors" % asm.name,
            file=sys.stderr,
        )
        asm.meta["anchors"] = {}
        return
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
    try:
        r = eval_mixed_value(t, env, obn)
    except (SyntaxError, ValueError, TypeError, KeyError):
        # Be permissive for malformed model output: keep scene running instead of
        # hard-failing anchor resolution on one bad token.
        if re.match(r"^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$", t):
            return float(t)
        return 0.0
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

    # Inherit params from all ancestor assemblies (root -> leaf) so nested assemblies
    # can still resolve references to top-level design variables.
    lineage: List[LiveObject] = []
    pn = obj.meta.get("parent")
    while pn and str(pn) in obn:
        pobj = obn[str(pn)]
        lineage.append(pobj)
        pn = pobj.meta.get("parent")

    for anc in reversed(lineage):
        if str(anc.meta.get("source", "")) == "assembly":
            base = {**base, **assembly_params_eval_env(anc.meta.get("params") or {}, obn)}

    # Add parent reference for child objects to access parent parameters via parent.param_name
    if obj.meta.get("parent") and str(obj.meta.get("parent")) in obn:
        base["_parent"] = str(obj.meta.get("parent"))

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
                except KeyError as ex:
                    if _SINGLE_IDENTIFIER_TOKEN.match(vs):
                        merged[k] = vs
                    else:
                        # Unresolvable reference (e.g. anchor() on an object
                        # without #@anchors). Don't kill the whole executor
                        # for one object's bad param -- warn and keep the raw
                        # expression so any op that actually needs it fails
                        # locally with context, while others still run.
                        print(
                            "[live-obj] param %r on '%s' skipped: %s" % (k, obj.name, ex),
                            file=sys.stderr,
                        )
                        merged[k] = vs
    out = {**base, **merged}
    return out


def parse_tokens(s: str) -> Dict[str, Any]:
    s = s.strip()
    if s.startswith("-"):
        s = s[1:].strip()
    tokens: List[str] = []
    cur: List[str] = []
    depth = 0
    for ch in s:
        if ch == "[":
            depth += 1
            cur.append(ch)
            continue
        if ch == "]":
            depth = max(0, depth - 1)
            cur.append(ch)
            continue
        if ch.isspace() and depth == 0:
            if cur:
                tokens.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if cur:
        tokens.append("".join(cur))
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


def parse_meta(meta_lines: List[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    meta: Dict[str, Any] = {}
    ops: List[Dict[str, Any]] = []
    sdf_ops: List[Dict[str, Any]] = []
    recipe_ops: List[Dict[str, Any]] = []
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
        if body == "recipe:":
            block = "recipe"
            continue
        if body == "params:":
            block = "params"
            meta.setdefault("params", {})
            continue
        if body == "anchors:":
            block = "anchors"
            meta["anchors"] = {}
            continue
        if body == "controls:":
            block = "controls"
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

        if block == "controls" and body.startswith("-"):
            continue

        if block in {"ops", "sdf", "recipe"} and body.startswith("-"):
            parsed = parse_tokens(body)
            if parsed:
                if block == "sdf":
                    sdf_ops.append(parsed)
                    if parsed.get("cmd") == "mesh_from_sdf":
                        p = dict(meta.get("params", {}) or {})
                        if parsed.get("resolution") is not None and p.get("resolution") is None:
                            p["resolution"] = parsed.get("resolution")
                        if parsed.get("method") is not None and p.get("method") is None:
                            p["method"] = parsed.get("method")
                        if p:
                            meta["params"] = p
                elif block == "recipe":
                    recipe_ops.append(parsed)
                else:
                    ops.append(parsed)
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

    return meta, ops, sdf_ops, recipe_ops


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
        obj.meta, obj.ops, obj.sdf_ops, obj.recipe_ops = parse_meta(obj.meta_lines)

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


def rounded_box_mesh(center: Vec3, size: Vec3, radius: float, segments: int = 1) -> Mesh:
    """Generate a rounded box by subdividing then projecting to a filleted profile."""
    cx, cy, cz = center
    sx, sy, sz = size
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    r = max(0.0, min(float(radius), hx * 0.999, hy * 0.999, hz * 0.999))
    if r <= 1e-9:
        return box_mesh(center, size)

    # Subdivision growth is exponential (each level ~4x triangles), so clamp hard.
    # High authored bevel `segments` values (e.g. 8-12) must not explode geometry.
    lvl = max(1, min(3, int(segments)))
    dense = op_subdivide(box_mesh(center, size), lvl)
    ix, iy, iz = max(0.0, hx - r), max(0.0, hy - r), max(0.0, hz - r)
    new_vertices: List[Vec3] = []
    for x, y, z in dense.vertices:
        lx, ly, lz = x - cx, y - cy, z - cz
        qx = min(max(lx, -ix), ix)
        qy = min(max(ly, -iy), iy)
        qz = min(max(lz, -iz), iz)
        dx, dy, dz = lx - qx, ly - qy, lz - qz
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        if d > 1e-9:
            s = r / d
            nx, ny, nz = qx + dx * s, qy + dy * s, qz + dz * s
        else:
            nx, ny, nz = lx, ly, lz
        new_vertices.append((cx + nx, cy + ny, cz + nz))
    dense.vertices = new_vertices
    return dense


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


def cadquery_cylinder_mesh(
    axis: str,
    center: Vec3,
    radius: float,
    depth: float,
    segments: int,
    bevel_radius: float,
) -> Optional[Mesh]:
    if axis != "z":
        return None
    if bevel_radius <= 0:
        return None
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq

    solid = cq.Workplane("XY").cylinder(depth, radius)
    bevel = min(float(bevel_radius), float(radius) * 0.999, float(depth) * 0.499)
    if bevel <= 0:
        return None
    try:
        solid = solid.edges("|Z").fillet(bevel)
    except Exception:
        return None
    shape = solid.val()
    tri = shape.tessellate(1.0 / max(6, int(segments)))
    vertices = [(float(v.x) + center[0], float(v.y) + center[1], float(v.z) + center[2]) for v in tri[0]]
    faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in tri[1]]
    return Mesh(vertices, faces)


def cadquery_box_mesh(center: Vec3, size: Vec3, segments: int, bevel_radius: float = 0.0) -> Optional[Mesh]:
    if min(size) <= 0:
        return None
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq

    sx, sy, sz = size
    solid = cq.Workplane("XY").box(sx, sy, sz)
    if bevel_radius > 0:
        bevel = min(float(bevel_radius), sx * 0.499, sy * 0.499, sz * 0.499)
        if bevel > 0:
            try:
                solid = solid.edges().fillet(bevel)
            except Exception:
                return None
    shape = solid.val()
    tri = shape.tessellate(1.0 / max(6, int(segments)))
    vertices = [(float(v.x) + center[0], float(v.y) + center[1], float(v.z) + center[2]) for v in tri[0]]
    faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in tri[1]]
    return Mesh(vertices, faces)


def cadquery_cone_mesh(axis: str, center: Vec3, radius: float, height: float, segments: int) -> Optional[Mesh]:
    if axis != "z":
        return None
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq
    solid = cq.Workplane("XY").cone(height, radius, 0.0)
    tri = solid.val().tessellate(1.0 / max(8, int(segments)))
    vertices = [(float(v.x) + center[0], float(v.y) + center[1], float(v.z) + center[2]) for v in tri[0]]
    faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in tri[1]]
    return Mesh(vertices, faces)


def cadquery_sphere_mesh(center: Vec3, radius: float, segments: int) -> Optional[Mesh]:
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq
    solid = cq.Workplane("XY").sphere(radius)
    tri = solid.val().tessellate(1.0 / max(8, int(segments)))
    vertices = [(float(v.x) + center[0], float(v.y) + center[1], float(v.z) + center[2]) for v in tri[0]]
    faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in tri[1]]
    return Mesh(vertices, faces)


def kernel_mesh_primitive(
    kernel: str,
    typ: str,
    params: Dict[str, Any],
    center: Vec3,
) -> Optional[Mesh]:
    """Kernel plugin contract for procedural primitives.

    Contract:
    - input shape parameters are normalized upstream
    - return Mesh when handled
    - return None when unsupported/unavailable so caller can fallback
    """
    if kernel != "cadquery":
        return None
    segments = int(params.get("segments", 16))
    bevel_radius = float(params.get("bevel_radius", 0.0))
    if typ == "cylinder":
        axis = str(params.get("axis", "z")).lower()
        depth = float(params.get("depth", params.get("height", params.get("width", 1))))
        radius = float(params.get("radius", 0.5))
        return cadquery_cylinder_mesh(axis, center, radius, depth, segments, bevel_radius)
    if typ == "box":
        size = params.get("size", [params.get("width", 1), params.get("depth", params.get("length", 1)), params.get("height", 1)])
        if isinstance(size, str):
            return None
        return cadquery_box_mesh(center, _as_float3(size, (1.0, 1.0, 1.0)), segments, bevel_radius)
    if typ == "cone":
        axis = str(params.get("axis", "z")).lower()
        height = float(params.get("height", params.get("depth", 1.0)))
        radius = float(params.get("radius", 0.5))
        return cadquery_cone_mesh(axis, center, radius, height, segments)
    if typ == "sphere":
        radius = float(params.get("radius", 0.5))
        return cadquery_sphere_mesh(center, radius, segments)
    return None


def cadquery_profile_mesh(
    mode: str,
    center: Vec3,
    profile_points: List[List[float]],
    height: float,
    segments: int,
    angle_degrees: float = 360.0,
    axis: str = "y",
) -> Optional[Mesh]:
    if len(profile_points) < 3:
        return None
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq
    import math

    axis = axis.lower()
    
    # Split profile_points on None into separate curves
    # None values are delimiters between separate profile curves (for boolean operations)
    curves = []
    current_curve = []
    for p in profile_points:
        if p is None:
            if current_curve:
                curves.append(current_curve)
                current_curve = []
        else:
            current_curve.append(p)
    if current_curve:
        curves.append(current_curve)
    
    if not curves or len(curves[0]) < 3:
        return None
    
    # Use first curve as outer shape, subsequent curves as holes
    profile_points = curves[0]
    
    if mode == "extrude":
        # Handle 3D profile points by extracting 2D coordinates
        # For vertical walls: profile is in X-Z plane (p[0], p[2]), extrude along Y
        # For horizontal surfaces: profile is in X-Y plane (p[0], p[1]), extrude along Z
        # Detect which plane to use based on which coordinates vary
        x_vals = [float(p[0]) if len(p) > 0 else 0.0 for p in profile_points]
        y_vals = [float(p[1]) if len(p) > 1 else 0.0 for p in profile_points]
        z_vals = [float(p[2]) if len(p) > 2 else 0.0 for p in profile_points]

        x_range = max(x_vals) - min(x_vals)
        y_range = max(y_vals) - min(y_vals)
        z_range = max(z_vals) - min(z_vals)

        # For simple rectangular profiles without holes, generate mesh manually to avoid CadQuery tessellation issues
        if len(profile_points) == 4 and len(curves) == 1:
            # Check if it's a rectangle in XZ plane (y constant)
            if y_range == 0:
                # Generate box mesh manually
                x0, x1 = min(x_vals), max(x_vals)
                z0, z1 = min(z_vals), max(z_vals)
                y0, y1 = min(y_vals), min(y_vals) + height
                vertices = [
                    [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],  # bottom face
                    [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],  # top face
                ]
                # Add center offset
                vertices = [[v[0] + center[0], v[1] + center[1], v[2] + center[2]] for v in vertices]
                faces = [
                    [1, 2, 3], [1, 3, 4],  # bottom
                    [5, 6, 7], [5, 7, 8],  # top
                    [1, 5, 8], [1, 8, 4],  # left
                    [2, 6, 5], [2, 5, 1],  # front
                    [3, 7, 6], [3, 6, 2],  # right
                    [4, 8, 7], [4, 7, 3],  # back
                ]
                return Mesh(vertices, faces)

        # Fallback to CadQuery for complex profiles
        # For XZ plane profiles (y constant), use XZ workplane and negate height to get positive Y extrusion
        if y_range == 0:
            profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[2]) if len(p) > 2 else 0.0) for p in profile_points]
            wp = cq.Workplane("XZ")
            extrude_height = -float(height)  # Negate to get positive Y extrusion
        elif z_range == 0:
            profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in profile_points]
            wp = cq.Workplane("XY")
            extrude_height = float(height)
        else:
            # 3D profile, default to XY plane
            profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in profile_points]
            wp = cq.Workplane("XY")
            extrude_height = float(height)

        try:
            # Use shapely + trimesh for robust hole support
            # Create a 2D polygon with holes, then extrude it directly
            # This avoids 3D boolean operations entirely
            from shapely.geometry import Polygon
            import trimesh
            import numpy as np
            
            # Prepare hole curves for shapely
            hole_curves_2d = []
            if len(curves) > 1:
                for hole_curve in curves[1:]:
                    if len(hole_curve) < 3:
                        continue
                    hole_2d = []
                    if y_range == 0:
                        hole_2d = [(float(p[0]), float(p[2])) for p in hole_curve]
                    elif z_range == 0:
                        hole_2d = [(float(p[0]), float(p[1])) for p in hole_curve]
                    else:
                        hole_2d = [(float(p[0]), float(p[1])) for p in hole_curve]
                    hole_curves_2d.append(hole_2d)
            
            # Create shapely polygon with holes
            if hole_curves_2d:
                poly = Polygon(shell=profile_2d, holes=hole_curves_2d)
                # Fix invalid polygon using buffer(0)
                if not poly.is_valid:
                    poly = poly.buffer(0)
            else:
                poly = Polygon(shell=profile_2d)
                if not poly.is_valid:
                    poly = poly.buffer(0)
            
            # Extrude the polygon directly to a watertight mesh
            wall_mesh = trimesh.creation.extrude_polygon(poly, height=extrude_height)
            
            # For XZ plane profiles (y constant), rotate mesh to extrude along Y instead of Z
            if y_range == 0:
                # Rotate 90 degrees around X axis to change extrusion from Z to Y
                wall_mesh = wall_mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(90), [1, 0, 0]))
            
            # Convert trimesh back to our Mesh format
            vertices = [[float(v[0]), float(v[1]), float(v[2])] for v in wall_mesh.vertices]
            faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in wall_mesh.faces]
            # Add center offset
            vertices = [[v[0] + center[0], v[1] + center[1], v[2] + center[2]] for v in vertices]
            return Mesh(vertices, faces)
        except ImportError:
            # Fallback to CadQuery without holes
            try:
                wp.polyline(profile_2d)
                wp.close()
                solid = wp.extrude(extrude_height)
                if solid is None:
                    return None
                return cadquery_tessellated_mesh(solid.val(), center, segments)
            except Exception:
                return None
        except Exception:
            # Fallback to CadQuery without holes
            try:
                wp.polyline(profile_2d)
                wp.close()
                solid = wp.extrude(extrude_height)
                if solid is None:
                    return None
                return cadquery_tessellated_mesh(solid.val(), center, segments)
            except Exception:
                return None
    elif mode in {"revolve", "lathe"}:
        # Manual revolve: generate mesh directly without CadQuery's revolve
        # This avoids CadQuery's confusing coordinate system issues
        import math
        
        # Use first curve only for revolve (holes not supported yet)
        profile_points = curves[0]
        
        # Generate vertices by revolving profile points around axis
        vertices = []
        faces = []
        
        # Number of segments around the revolve
        revolve_segments = max(8, int(segments))
        angle_rad = math.radians(angle_degrees)
        
        # For each profile point, create a circle of vertices
        for i, p in enumerate(profile_points):
            radius = float(p[0]) if axis == "z" or axis == "y" else float(p[1])
            height_val = float(p[2]) if axis == "z" or axis == "x" else (float(p[1]) if axis == "y" else float(p[2]))
            
            # Create circle of vertices at this height
            for j in range(revolve_segments):
                angle = (j / revolve_segments) * angle_rad
                if axis == "z":
                    # Revolve around Z: x = radius*cos, y = radius*sin, z = height
                    x = radius * math.cos(angle)
                    y = radius * math.sin(angle)
                    z = height_val
                elif axis == "x":
                    # Revolve around X: x = height, y = radius*cos, z = radius*sin
                    x = height_val
                    y = radius * math.cos(angle)
                    z = radius * math.sin(angle)
                else:  # axis == "y"
                    # Revolve around Y: x = radius*cos, y = height, z = radius*sin
                    x = radius * math.cos(angle)
                    y = height_val
                    z = radius * math.sin(angle)
                
                vertices.append([x + center[0], y + center[1], z + center[2]])
        
        # Generate faces connecting the circles
        for i in range(len(profile_points) - 1):
            for j in range(revolve_segments):
                # Current circle index
                curr = i * revolve_segments + j
                # Next circle index
                next_circle = (i + 1) * revolve_segments + j
                # Next vertex in current circle
                next_curr = i * revolve_segments + ((j + 1) % revolve_segments)
                # Next vertex in next circle
                next_next = (i + 1) * revolve_segments + ((j + 1) % revolve_segments)
                
                # Two triangles per quad
                faces.append([curr + 1, next_circle + 1, next_curr + 1])
                faces.append([next_circle + 1, next_next + 1, next_curr + 1])
        
        return Mesh(vertices, faces)
    else:
        return None


def cadquery_sweep_mesh(
    center: Vec3,
    profile_points: List[List[float]],
    path_points: List[List[float]],
    segments: int,
) -> Optional[Mesh]:
    if len(profile_points) < 3 or len(path_points) < 2:
        return None
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq

    # None values are delimiters between separate profile curves
    curves = []
    current_curve = []
    for p in profile_points:
        if p is None:
            if current_curve:
                curves.append(current_curve)
                current_curve = []
        else:
            current_curve.append(p)
    if current_curve:
        curves.append(current_curve)
    
    if not curves or len(curves[0]) < 3:
        return None
    
    # Use first curve as profile, subsequent curves as holes
    profile = cq.Workplane("XY").polyline([(float(p[0]), float(p[1])) for p in curves[0]]).close()
    path_wire = cq.Wire.makePolygon([cq.Vector(float(p[0]), float(p[1]), float(p[2])) for p in path_points])
    solid = profile.sweep(path_wire)
    tri = solid.val().tessellate(1.0 / max(8, int(segments)))
    vertices = [(float(v.x) + center[0], float(v.y) + center[1], float(v.z) + center[2]) for v in tri[0]]
    faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in tri[1]]
    return Mesh(vertices, faces)


def cadquery_loft_mesh(center: Vec3, sections: List[List[List[float]]], segments: int) -> Optional[Mesh]:
    if len(sections) < 2:
        return None
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq

    wires = []
    for sec in sections:
        if not isinstance(sec, list) or len(sec) < 3:
            return None
        pts = [cq.Vector(float(p[0]), float(p[1]), float(p[2])) for p in sec]
        wires.append(cq.Wire.makePolygon(pts))
    solid = cq.Solid.makeLoft(wires, True)
    tri = solid.tessellate(1.0 / max(8, int(segments)))
    vertices = [(float(v.x) + center[0], float(v.y) + center[1], float(v.z) + center[2]) for v in tri[0]]
    faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in tri[1]]
    return Mesh(vertices, faces)


def cadquery_to_trimesh(shape: Any) -> Any:
    """Convert a CadQuery shape to a trimesh.Trimesh object."""
    import trimesh
    # Tessellate the CadQuery shape with higher quality for watertight meshes
    tri = shape.tessellate(0.01)  # Smaller tolerance for better tessellation
    vertices = [(float(v.x), float(v.y), float(v.z)) for v in tri[0]]
    faces = [(int(f[0]), int(f[1]), int(f[2])) for f in tri[1]]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    
    # Ensure mesh is watertight for boolean operations
    if not mesh.is_watertight:
        try:
            # Try to fix the mesh
            mesh = mesh.process()
        except:
            pass
    
    return mesh


def cadquery_tessellated_mesh(shape: Any, center: Vec3, segments: int) -> Mesh:
    # Use smaller tolerance for higher quality tessellation
    tolerance = 1.0 / max(16, int(segments) * 2)
    tri = shape.tessellate(tolerance)
    vertices = [(float(v.x) + center[0], float(v.y) + center[1], float(v.z) + center[2]) for v in tri[0]]
    faces = [[int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1] for f in tri[1]]
    return Mesh(vertices, faces)


def cadquery_solid_from_params(typ: str, params: Dict[str, Any]) -> Optional[Any]:
    import importlib.util
    if importlib.util.find_spec("cadquery") is None:
        return None
    import cadquery as cq
    if typ == "box":
        size = params.get("size", [params.get("width", 1), params.get("depth", params.get("length", 1)), params.get("height", 1)])
        if isinstance(size, str):
            return None
        sx, sy, sz = _as_float3(size, (1.0, 1.0, 1.0))
        return cq.Workplane("XY").box(sx, sy, sz).val()
    if typ == "cylinder":
        axis = str(params.get("axis", "z")).lower()
        depth = float(params.get("depth", params.get("height", params.get("width", 1))))
        radius = float(params.get("radius", 0.5))
        if axis == "x":
            # Cylinder aligned with X axis: create in XY plane and rotate
            solid = cq.Workplane("XY").cylinder(depth, radius).val()
            solid = solid.rotate((0, 0, 0), (0, 1, 0), 90)
            return solid
        elif axis == "y":
            # Cylinder aligned with Y axis: create in XY plane and rotate
            solid = cq.Workplane("XY").cylinder(depth, radius).val()
            solid = solid.rotate((0, 0, 0), (1, 0, 0), 90)
            return solid
        else:
            # Default to Z axis
            return cq.Workplane("XY").cylinder(depth, radius).val()
    if typ == "cone":
        axis = str(params.get("axis", "z")).lower()
        if axis != "z":
            return None
        height = float(params.get("height", params.get("depth", 1.0)))
        radius = float(params.get("radius", 0.5))
        return cq.Workplane("XY").cone(height, radius, 0.0).val()
    if typ == "sphere":
        radius = float(params.get("radius", 0.5))
        return cq.Workplane("XY").sphere(radius).val()
    if typ == "extrude":
        profile_points = params.get("profile", [])
        if not isinstance(profile_points, list):
            return None
        height = float(params.get("height", params.get("depth", 1.0)))
        if len(profile_points) < 3:
            return None

        # Split profile_points on None into separate curves
        curves = []
        current_curve = []
        for p in profile_points:
            if p is None:
                if current_curve:
                    curves.append(current_curve)
                    current_curve = []
            else:
                current_curve.append(p)
        if current_curve:
            curves.append(current_curve)
        
        if not curves or len(curves[0]) < 3:
            return None
        
        # Use first curve as outer shape, subsequent curves as holes
        profile_points = curves[0]
        
        # For simple rectangular profiles, use box primitive for better solid generation
        x_vals = [float(p[0]) if len(p) > 0 else 0.0 for p in profile_points]
        y_vals = [float(p[1]) if len(p) > 1 else 0.0 for p in profile_points]
        z_vals = [float(p[2]) if len(p) > 2 else 0.0 for p in profile_points]

        x_range = max(x_vals) - min(x_vals)
        y_range = max(y_vals) - min(y_vals)
        z_range = max(z_vals) - min(z_vals)

        # If profile is a rectangle in XZ plane (y constant), use box primitive
        if y_range == 0 and len(profile_points) == 4:
            size = [x_range, height, z_range]
            # Create box at origin then translate to correct position
            solid = cq.Workplane("XY").box(size[0], size[1], size[2], centered=False)
            solid = solid.translate((min(x_vals), min(y_vals), min(z_vals)))
            return solid.val()

        # Use shapely + trimesh for robust hole support (same approach as cadquery_profile_mesh)
        try:
            from shapely.geometry import Polygon
            import trimesh
            
            # Prepare 2D profile and holes
            profile_2d = []
            hole_curves_2d = []
            
            if y_range == 0:
                profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[2]) if len(p) > 2 else 0.0) for p in profile_points]
                for hole_curve in curves[1:]:
                    if len(hole_curve) < 3:
                        continue
                    hole_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[2]) if len(p) > 2 else 0.0) for p in hole_curve]
                    hole_curves_2d.append(hole_2d)
            elif z_range == 0:
                profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in profile_points]
                for hole_curve in curves[1:]:
                    if len(hole_curve) < 3:
                        continue
                    hole_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in hole_curve]
                    hole_curves_2d.append(hole_2d)
            else:
                profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in profile_points]
                for hole_curve in curves[1:]:
                    if len(hole_curve) < 3:
                        continue
                    hole_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in hole_curve]
                    hole_curves_2d.append(hole_2d)
            
            # Create shapely polygon with holes
            if hole_curves_2d:
                poly = Polygon(shell=profile_2d, holes=hole_curves_2d)
            else:
                poly = Polygon(shell=profile_2d)
            
            # Extrude the polygon directly to a watertight mesh
            wall_mesh = trimesh.creation.extrude_polygon(poly, height=height if z_range != 0 else -height)
            
            # Convert trimesh back to CadQuery solid
            # Note: This returns a trimesh object, not a CadQuery solid
            # For consistency with the function signature, we need to convert back
            # But since this function returns a CadQuery solid, we'll return None
            # and let the caller handle the mesh generation directly
            return None
        except ImportError:
            pass  # Fall through to CadQuery approach
        except Exception:
            pass  # Fall through to CadQuery approach
        
        # Fallback to original CadQuery approach (without holes)
        # For any XZ plane profile (y constant), use XZ workplane and negate height to get positive Y extrusion
        if y_range == 0:
            profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[2]) if len(p) > 2 else 0.0) for p in profile_points]
            wp = cq.Workplane("XZ")
            try:
                wp.moveTo(profile_2d[0][0], profile_2d[0][1])
                for x, y in profile_2d[1:]:
                    wp.lineTo(x, y)
                wp.close()
                # Negate height to get positive Y extrusion (XZ workplane extrudes in negative Y by default)
                solid = wp.extrude(-float(height))
                if solid is None:
                    return None
                return solid.val()
            except Exception as e:
                return None

        # Otherwise use standard extrude for XY plane or 3D profiles
        elif z_range == 0:
            # Profile is in XY plane, extract (x, y)
            profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in profile_points]
            wp = cq.Workplane("XY")
            try:
                wp.moveTo(profile_2d[0][0], profile_2d[0][1])
                for x, y in profile_2d[1:]:
                    wp.lineTo(x, y)
                wp.close()
                solid = wp.extrude(float(height))
                if solid is None:
                    return None
                return solid.val()
            except Exception as e:
                return None
        else:
            # Profile is in 3D, default to XY plane
            profile_2d = [(float(p[0]) if len(p) > 0 else 0.0, float(p[1]) if len(p) > 1 else 0.0) for p in profile_points]
            wp = cq.Workplane("XY")
            try:
                wp.moveTo(profile_2d[0][0], profile_2d[0][1])
                for x, y in profile_2d[1:]:
                    wp.lineTo(x, y)
                wp.close()
                solid = wp.extrude(float(height))
                if solid is None:
                    return None
                return solid.val()
            except Exception as e:
                return None
    return None

def kernel_mesh_profile_op(kernel: str, typ: str, params: Dict[str, Any], center: Vec3) -> Optional[Mesh]:
    if kernel != "cadquery":
        return None
    profile_points = params.get("profile", [])
    if not isinstance(profile_points, list):
        return None
    segments = int(params.get("segments", 24))
    if typ == "extrude":
        height = float(params.get("height", params.get("depth", 1.0)))
        return cadquery_profile_mesh("extrude", center, profile_points, height, segments)
    if typ in {"revolve", "lathe"}:
        angle = float(params.get("angle", 360.0))
        axis = str(params.get("axis", "y"))
        return cadquery_profile_mesh(typ, center, profile_points, 0.0, segments, angle, axis)
    if typ == "sweep":
        path_points = params.get("path", [])
        if not isinstance(path_points, list):
            return None
        return cadquery_sweep_mesh(center, profile_points, path_points, segments)
    if typ == "loft":
        sections = params.get("sections", [])
        if not isinstance(sections, list):
            return None
        return cadquery_loft_mesh(center, sections, segments)
    if typ == "curve":
        kind = str(params.get("kind", "")).lower()
        if kind == "helix":
            path_r = float(params.get("radius", 1.0))
            height = float(params.get("height", params.get("total_rise", 3.0)))
            if params.get("turns") is not None:
                turn = float(params["turns"]) * 2 * math.pi
            elif params.get("total_turn_degrees") is not None:
                turn = math.radians(float(params["total_turn_degrees"]))
            else:
                turn = math.radians(360.0)
            start_z = float(params.get("z_offset", params.get("start_z", 0.0)))
            segs = max(32, int(float(params.get("segments", 48))))
            cx, cy, cz = center
            mesh = Mesh()
            pts: List[Vec3] = []
            for i in range(segs + 1):
                t = i / segs
                th = turn * t
                zz = cz + start_z + t * height
                pts.append((cx + path_r * math.cos(th), cy + path_r * math.sin(th), zz))
            for i in range(len(pts) - 1):
                mesh.extend(tube_between(pts[i], pts[i + 1], 0.01, 6))
            return mesh
        path_points = params.get("points", [])
        if not isinstance(path_points, list) or len(path_points) < 2:
            return None
        radius = float(params.get("radius", 0.05))
        sides = max(8, int(params.get("profile_segments", 16)))
        prof: List[List[float]] = []
        for i in range(sides):
            a = 2 * math.pi * i / sides
            prof.append([radius * math.cos(a), radius * math.sin(a)])
        return cadquery_sweep_mesh(center, prof, path_points, segments)
    return None


def cone_mesh(axis: str, center: Vec3, radius: float, height: float, segments: int = 16) -> Mesh:
    cx, cy, cz = center
    axis = axis.lower()
    h0, h1 = -height / 2, height / 2
    verts: List[Vec3] = []
    faces: List[List[int]] = []

    def ring_pt(a: float) -> Vec3:
        ca, sa = math.cos(a), math.sin(a)
        if axis == "x":
            return (cx + h0, cy + ca * radius, cz + sa * radius)
        if axis == "y":
            return (cx + ca * radius, cy + h0, cz + sa * radius)
        return (cx + ca * radius, cy + sa * radius, cz + h0)

    if axis == "x":
        apex = (cx + h1, cy, cz)
    elif axis == "y":
        apex = (cx, cy + h1, cz)
    else:
        apex = (cx, cy, cz + h1)

    ring: List[int] = []
    for i in range(max(3, int(segments))):
        verts.append(ring_pt(2 * math.pi * i / max(3, int(segments))))
        ring.append(len(verts))
    verts.append(apex)
    apex_idx = len(verts)

    faces.append(list(reversed(ring)))  # base cap
    n = len(ring)
    for i in range(n):
        faces.append([ring[i], ring[(i + 1) % n], apex_idx])
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


def sphere_mesh(center: Vec3, radius: float, segments: int = 16) -> Mesh:
    cx, cy, cz = center
    lon = max(8, int(segments))
    lat = max(6, lon // 2)
    verts: List[Vec3] = []
    faces: List[List[int]] = []

    # north pole
    verts.append((cx, cy, cz + radius))
    rings: List[List[int]] = []
    for iy in range(1, lat):
        phi = math.pi * iy / lat
        z = cz + radius * math.cos(phi)
        rr = radius * math.sin(phi)
        ring: List[int] = []
        for ix in range(lon):
            th = 2 * math.pi * ix / lon
            verts.append((cx + rr * math.cos(th), cy + rr * math.sin(th), z))
            ring.append(len(verts))
        rings.append(ring)
    # south pole
    verts.append((cx, cy, cz - radius))
    south = len(verts)

    if rings:
        first = rings[0]
        for i in range(lon):
            faces.append([1, first[i], first[(i + 1) % lon]])
        for r in range(len(rings) - 1):
            a, b = rings[r], rings[r + 1]
            for i in range(lon):
                faces.append([a[i], a[(i + 1) % lon], b[(i + 1) % lon], b[i]])
        last = rings[-1]
        for i in range(lon):
            faces.append([last[(i + 1) % lon], last[i], south])
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


class SDFCapsule(SDFExpr):
    def __init__(self, a: Vec3, b: Vec3, radius: float):
        self.a = a
        self.b = b
        self.r = radius

    def dist(self, p: Vec3) -> float:
        pax, pay, paz = p[0] - self.a[0], p[1] - self.a[1], p[2] - self.a[2]
        bax, bay, baz = self.b[0] - self.a[0], self.b[1] - self.a[1], self.b[2] - self.a[2]
        denom = bax * bax + bay * bay + baz * baz
        h = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, (pax * bax + pay * bay + paz * baz) / denom))
        q = (pax - bax * h, pay - bay * h, paz - baz * h)
        return length3(q) - self.r


class SDFCylinderZ(SDFExpr):
    def __init__(self, center: Vec3, radius: float, height: float):
        self.c = center
        self.r = radius
        self.h = height / 2

    def dist(self, p: Vec3) -> float:
        dx = math.sqrt((p[0]-self.c[0])**2 + (p[1]-self.c[1])**2) - self.r
        dz = abs(p[2]-self.c[2]) - self.h
        return min(max(dx, dz), 0.0) + length3((max(dx,0), max(dz,0), 0))

class SDFCylinderX(SDFExpr):
    def __init__(self, center: Vec3, radius: float, height: float):
        self.c = center
        self.r = radius
        self.h = height / 2

    def dist(self, p: Vec3) -> float:
        # Cylinder aligned with X axis: circular cross-section in Y-Z plane
        dy = math.sqrt((p[1]-self.c[1])**2 + (p[2]-self.c[2])**2) - self.r
        dx = abs(p[0]-self.c[0]) - self.h
        return min(max(dx, dy), 0.0) + length3((max(dx,0), max(dy,0), 0))

class SDFCylinderY(SDFExpr):
    def __init__(self, center: Vec3, radius: float, height: float):
        self.c = center
        self.r = radius
        self.h = height / 2

    def dist(self, p: Vec3) -> float:
        # Cylinder aligned with Y axis: circular cross-section in X-Z plane
        dx = math.sqrt((p[0]-self.c[0])**2 + (p[2]-self.c[2])**2) - self.r
        dy = abs(p[1]-self.c[1]) - self.h
        return min(max(dx, dy), 0.0) + length3((max(dx,0), max(dy,0), 0))


class SDFUnion(SDFExpr):
    def __init__(self, a: SDFExpr, b: SDFExpr): self.a, self.b = a, b
    def dist(self, p: Vec3) -> float: return min(self.a.dist(p), self.b.dist(p))


class SDFSubtract(SDFExpr):
    def __init__(self, a: SDFExpr, b: SDFExpr): self.a, self.b = a, b
    def dist(self, p: Vec3) -> float: return max(self.a.dist(p), -self.b.dist(p))


class SDFIntersect(SDFExpr):
    def __init__(self, a: SDFExpr, b: SDFExpr): self.a, self.b = a, b
    def dist(self, p: Vec3) -> float: return max(self.a.dist(p), self.b.dist(p))


class SDFSmoothUnion(SDFExpr):
    def __init__(self, a: SDFExpr, b: SDFExpr, radius: float):
        self.a, self.b, self.r = a, b, max(1e-6, radius)

    def dist(self, p: Vec3) -> float:
        da = self.a.dist(p)
        db = self.b.dist(p)
        h = max(0.0, min(1.0, 0.5 + 0.5 * (db - da) / self.r))
        return (db * (1 - h) + da * h) - self.r * h * (1 - h)


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
        elif c == "capsule":
            sid = str(cmd.get("id", f"capsule_{len(registry)}"))
            a = tuple(cmd.get("a", [0, 0, 0]))
            b = tuple(cmd.get("b", [0, 0, 1]))
            radius = float(cmd.get("radius", 0.1))
            registry[sid] = SDFCapsule(tuple(map(float, a)), tuple(map(float, b)), radius)
            current = registry[sid]
        elif c == "cylinder":
            sid = str(cmd.get("id", f"cylinder_{len(registry)}"))
            center = tuple(cmd.get("center", [0,0,0]))
            radius = float(cmd.get("radius", 1))
            height = float(cmd.get("height", 1))
            axis_param = cmd.get("axis", "z")
            # Parse axis parameter - might be a string or list
            if isinstance(axis_param, list):
                axis = str(axis_param[0]).lower() if axis_param else "z"
            else:
                axis = str(axis_param).lower()
            # Select appropriate cylinder class based on axis
            if axis == "x":
                registry[sid] = SDFCylinderX(tuple(map(float, center)), radius, height)
            elif axis == "y":
                registry[sid] = SDFCylinderY(tuple(map(float, center)), radius, height)
            else:
                registry[sid] = SDFCylinderZ(tuple(map(float, center)), radius, height)
            current = registry[sid]
        elif c in {"union", "subtract", "intersect", "smooth_union"}:
            args = cmd.get("args", [])
            a_id = b_id = None
            if len(args) >= 2:
                a_id, b_id = str(args[0]), str(args[1])
            elif cmd.get("id_a") is not None and cmd.get("id_b") is not None:
                a_id, b_id = str(cmd.get("id_a")), str(cmd.get("id_b"))
            if a_id and b_id and a_id in registry and b_id in registry:
                if c == "smooth_union" and a_id == b_id:
                    # Smooth-unioning an SDF with itself is a no-op.
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
                # Chain-friendly semantics: update lhs id in-place so later ops like
                # `subtract outer inner` then `subtract outer top_cut` operate on the
                # previously modified `outer`, not the original primitive.
                registry[a_id] = current
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


def sdf_to_marching_cubes_mesh(expr: SDFExpr, bounds: List[List[float]], resolution: float, iso: float = 0.0) -> Mesh:
    """Dependency-free marching cubes using tetrahedral decomposition (portable across adapters)."""
    mn, mx = bounds
    nx = max(2, int((mx[0] - mn[0]) / resolution))
    ny = max(2, int((mx[1] - mn[1]) / resolution))
    nz = max(2, int((mx[2] - mn[2]) / resolution))
    ox, oy, oz = float(mn[0]), float(mn[1]), float(mn[2])

    # Safeguard: limit total voxels to prevent freezing
    max_voxels = 1000000  # 1 million voxels max
    total_voxels = nx * ny * nz
    if total_voxels > max_voxels:
        print("sdf: resolution %s produces %s voxels, exceeding limit of %s. Using safer resolution." % (resolution, total_voxels, max_voxels))
        # Recalculate resolution to stay within limit
        target_voxels = max_voxels
        scale_factor = (target_voxels / total_voxels) ** (1/3)
        resolution = resolution / scale_factor
        nx = max(2, int((mx[0] - mn[0]) / resolution))
        ny = max(2, int((mx[1] - mn[1]) / resolution))
        nz = max(2, int((mx[2] - mn[2]) / resolution))
        print("sdf: adjusted resolution to %s (%s voxels)" % (resolution, nx * ny * nz))

    def p(i: int, j: int, k: int) -> Vec3:
        return (ox + i*resolution, oy + j*resolution, oz + k*resolution)

    vals = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            for k in range(nz + 1):
                pt = p(i, j, k)
                vals[(i, j, k)] = expr.dist(pt)

    cube_tets = [
        (0, 5, 1, 6),
        (0, 1, 2, 6),
        (0, 2, 3, 6),
        (0, 3, 7, 6),
        (0, 7, 4, 6),
        (0, 4, 5, 6),
    ]
    cverts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]

    mesh = Mesh()

    def lerp(a: Vec3, b: Vec3, va: float, vb: float) -> Vec3:
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
                        base = len(mesh.vertices) + 1
                        mesh.vertices.extend(points)
                        mesh.faces.append([base, base + 1, base + 2])
                    elif len(points) == 4:
                        base = len(mesh.vertices) + 1
                        mesh.vertices.extend(points)
                        # Triangulate correctly using a true diagonal (0 to 3)
                        mesh.faces.append([base, base + 1, base + 3])
                        mesh.faces.append([base, base + 3, base + 2])

    if mesh.vertices:
        mesh = weld_vertices(mesh, epsilon=resolution * 0.1)
    return mesh


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
    surface = str(params.get("surface", "voxel")).lower()
    mc_resolution = float(params.get("mc_resolution", cell * 0.5))
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
    
    # If smooth surface requested, convert voxels to SDF and use marching cubes
    if surface == "smooth" or surface == "marching_cubes":
        # Build SDF from voxel grid using distance field
        class VoxelSDF(SDFExpr):
            def __init__(self, occ, orig, cl):
                self.occupied = occ
                self.origin = orig
                self.cell = cl
            
            def dist(self, p):
                px, py, pz = p
                # Convert world position to grid position
                gx = int((px - self.origin[0]) / self.cell)
                gy = int((py - self.origin[1]) / self.cell)
                gz = int((pz - self.origin[2]) / self.cell)
                
                # Check if position is inside an occupied cell
                if (gx, gy, gz) in self.occupied:
                    # Negative distance inside occupied cells
                    cx = self.origin[0] + (gx + 0.5) * self.cell
                    cy = self.origin[1] + (gy + 0.5) * self.cell
                    cz = self.origin[2] + (gz + 0.5) * self.cell
                    # Distance to nearest face of this cell
                    dx = max(abs(px - cx) - self.cell/2, 0)
                    dy = max(abs(py - cy) - self.cell/2, 0)
                    dz = max(abs(pz - cz) - self.cell/2, 0)
                    return -math.sqrt(dx*dx + dy*dy + dz*dz)
                else:
                    # Positive distance outside - find nearest occupied cell
                    min_dist = float('inf')
                    # Search nearby cells (limited radius for performance)
                    search_radius = 3
                    for dx in range(-search_radius, search_radius + 1):
                        for dy in range(-search_radius, search_radius + 1):
                            for dz in range(-search_radius, search_radius + 1):
                                nx_, ny_, nz_ = gx + dx, gy + dy, gz + dz
                                if (nx_, ny_, nz_) in self.occupied:
                                    cx = self.origin[0] + (nx_ + 0.5) * self.cell
                                    cy = self.origin[1] + (ny_ + 0.5) * self.cell
                                    cz = self.origin[2] + (nz_ + 0.5) * self.cell
                                    dist = math.sqrt((px - cx)**2 + (py - cy)**2 + (pz - cz)**2) - (self.cell * 0.5)
                                    if dist < min_dist:
                                        min_dist = dist
                    return min_dist if min_dist != float('inf') else self.cell * 2
        
        # Build bounds for marching cubes with extra padding to ensure closed surface
        pad = max(cell * 2, mc_resolution * 4.0)
        bounds = [
            [origin[0] - pad, origin[1] - pad, origin[2] - pad],
            [origin[0] + nx * cell + pad, origin[1] + ny * cell + pad, origin[2] + nz * cell + pad]
        ]
        
        # Use marching cubes
        voxel_sdf = VoxelSDF(occupied, origin, cell)
        return sdf_to_marching_cubes_mesh(voxel_sdf, bounds, mc_resolution)
    
    # Default voxel output with welding to merge separate planes
    mesh = mesh_from_voxels(occupied, origin, cell)
    if mesh.vertices:
        mesh = weld_vertices(mesh, epsilon=cell * 0.001)
    return mesh


def cellular_automata_instances_mesh(params: Dict[str, Any], obn: Optional[Dict[str, LiveObject]] = None) -> Mesh:
    grid = params.get("grid", [8, 8, 4])
    nx, ny, nz = map(int, grid)
    cell = float(params.get("cell", 1.0))
    fill = float(params.get("fill", 0.18))
    instance_ref = str(params.get("instance", params.get("primitive", "sphere")))
    scale = float(params.get("instance_scale", params.get("scale", 0.35)))
    seed = int(params.get("seed", 1))
    rng = random.Random(seed)
    rotation_step = float(params.get("rotation_step", 90.0))
    
    # CA rule parameters
    steps = int(params.get("steps", 0))
    birth_rules = params.get("birth_rules", [3])
    survival_rules = params.get("survival_rules", [2, 3])
    if isinstance(birth_rules, (int, float)):
        birth_rules = [int(birth_rules)]
    elif isinstance(birth_rules, str):
        birth_rules = [int(x.strip()) for x in birth_rules.split(",")]
    elif not isinstance(birth_rules, (list, tuple)):
        birth_rules = [3]
    if isinstance(survival_rules, (int, float)):
        survival_rules = [int(survival_rules)]
    elif isinstance(survival_rules, str):
        survival_rules = [int(x.strip()) for x in survival_rules.split(",")]
    elif not isinstance(survival_rules, (list, tuple)):
        survival_rules = [2, 3]
    birth_rules = set(birth_rules)
    survival_rules = set(survival_rules)

    # Determine if instance is a primitive or object reference
    primitives = {"box", "cylinder", "sphere"}
    is_primitive = instance_ref.lower() in primitives

    # Get instance template mesh
    if is_primitive:
        primitive = instance_ref.lower()
        template_mesh = None
    else:
        # Look up referenced object
        if obn and instance_ref in obn:
            template_obj = obn[instance_ref]
            # Ensure the referenced object is executed first with its ops applied
            source = template_obj.meta.get("source", "")
            
            if source == "procedural":
                # For procedural objects, we need to generate the mesh with ops applied
                base_mesh = generate_procedural(template_obj, obn)
                if base_mesh.vertices:
                    template_mesh = apply_ops(base_mesh, template_obj, obn, "")
                else:
                    template_mesh = None
            elif source == "assembly":
                # For assemblies, generate by combining children
                base_mesh = Mesh()
                for child in obn.values():
                    if str(child.meta.get("parent")) == instance_ref:
                        child_source = child.meta.get("source", "")
                        if child_source == "procedural":
                            child_mesh = generate_procedural(child, obn)
                            if child_mesh.vertices:
                                child_mesh = apply_ops(child_mesh, child, obn, "")
                                base_mesh.extend(child_mesh)
                        elif child.mesh and child.mesh.vertices:
                            base_mesh.extend(child.mesh.copy())
                # Apply the assembly's own ops to the combined mesh
                if base_mesh.vertices:
                    base_mesh = apply_ops(base_mesh, template_obj, obn, "")
                template_mesh = base_mesh if base_mesh.vertices else None
            elif template_obj.mesh and template_obj.mesh.vertices:
                # For other sources, use the already-executed mesh
                template_mesh = template_obj.mesh.copy()
            else:
                template_mesh = None
        else:
            template_mesh = None

    alive = set()
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                if rng.random() <= fill:
                    alive.add((ix, iy, iz))

    # Run CA simulation steps if specified
    if steps > 0:
        neigh = [(dx, dy, dz) for dx in [-1, 0, 1] for dy in [-1, 0, 1] for dz in [-1, 0, 1] if not (dx == dy == dz == 0)]
        for _ in range(steps):
            new_alive = set()
            for ix in range(nx):
                for iy in range(ny):
                    for iz in range(nz):
                        count = sum((ix + dx, iy + dy, iz + dz) in alive for dx, dy, dz in neigh)
                        if (ix, iy, iz) in alive:
                            if count in survival_rules:
                                new_alive.add((ix, iy, iz))
                        else:
                            if count in birth_rules:
                                new_alive.add((ix, iy, iz))
            alive = new_alive
            if not alive:
                break

    if not alive:
        return Mesh()

    mesh = Mesh()
    gx, gy, gz = float(nx), float(ny), float(nz)
    
    # Pre-calculate neighbor counts for rotation
    neighbor_counts = {}
    if rotation_step > 0:
        neigh = [(dx, dy, dz) for dx in [-1, 0, 1] for dy in [-1, 0, 1] for dz in [-1, 0, 1] if not (dx == dy == dz == 0)]
        for pos in alive:
            ix, iy, iz = pos
            count = sum((ix + dx, iy + dy, iz + dz) in alive for dx, dy, dz in neigh)
            neighbor_counts[pos] = count

    for ix, iy, iz in alive:
        x = (ix - gx / 2.0) * cell
        y = (iy - gy / 2.0) * cell
        z = (iz - gz / 2.0) * cell
        size = max(1e-6, cell * scale)

        # Calculate neighbor-based rotation around Z axis
        neighbor_angle_deg = 0.0
        if rotation_step > 0 and (ix, iy, iz) in neighbor_counts:
            count = neighbor_counts[(ix, iy, iz)]
            neighbor_angle_deg = min(count, 5) * rotation_step

        if is_primitive:
            if primitive == "box":
                instance_mesh = box_mesh((0, 0, 0), (size, size, size))
            elif primitive == "cylinder":
                radius = max(1e-6, size * 0.5)
                height = max(1e-6, size)
                instance_mesh = cylinder_mesh("z", (0, 0, 0), radius, height, 8)
            else:  # sphere or default
                radius = max(1e-6, size * 0.5)
                instance_mesh = sphere_mesh((0, 0, 0), radius, 8)
            
            # Apply neighbor-based rotation around Z axis
            if neighbor_angle_deg > 0:
                transform = {
                    "position": [0, 0, 0],
                    "scale": [1, 1, 1],
                    "rotation": [0, 0, neighbor_angle_deg]
                }
                instance_mesh = apply_transform(instance_mesh, transform)
            
            # Translate to final position
            transform = {
                "position": [x, y, z],
                "scale": [size, size, size],
                "rotation": [0, 0, 0]
            }
            instance_mesh = apply_transform(instance_mesh, transform)
            
        elif template_mesh:
            # Transform and place the template mesh
            instance_mesh = template_mesh.copy()
            
            # Scale around origin
            transform = {
                "position": [0, 0, 0],
                "scale": [size, size, size],
                "rotation": [0, 0, 0]
            }
            instance_mesh = apply_transform(instance_mesh, transform)
            
            # Apply neighbor-based rotation around Z axis
            if neighbor_angle_deg > 0:
                transform = {
                    "position": [0, 0, 0],
                    "scale": [1, 1, 1],
                    "rotation": [0, 0, neighbor_angle_deg]
                }
                instance_mesh = apply_transform(instance_mesh, transform)
            
            # Translate to final position
            transform = {
                "position": [x, y, z],
                "scale": [1, 1, 1],
                "rotation": [0, 0, 0]
            }
            instance_mesh = apply_transform(instance_mesh, transform)
            
            # Weld vertices after transformation to fix holes
            instance_mesh = weld_vertices(instance_mesh, epsilon=size * 0.001)
        else:
            # Fallback to sphere if reference not found
            radius = max(1e-6, size * 0.5)
            instance_mesh = sphere_mesh((x, y, z), radius, 8)

        mesh.extend(instance_mesh)

    return mesh


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
    if params.get("turns") is not None:
        total_turn = float(params["turns"]) * 2 * math.pi
    else:
        total_turn = math.radians(float(params.get("total_turn_degrees", 360)))
    total_h = float(params.get("height", params.get("total_height", 3.0)))
    rise = float(params.get("rise_per_step", total_h / max(1, count)))
    r_in = float(params.get("inner_radius", 0.25))
    r_out = float(params.get("outer_radius", 1.0))
    thick = float(params.get("thickness", params.get("tread_thickness", 0.05)))
    tread_deg = float(params.get("tread_angle", params.get("tread_angle_degrees", 24)))
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
        # Generate corners: bottom face (szgn=-1) then top face (szgn=1)
        # Each face: 4 corners in CCW order from above: (-x,-y), (x,-y), (x,y), (-x,y)
        for szgn in (-1, 1):
            for srgn, stgn in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                ox = srgn * hx * cr + stgn * hy * (-sr)
                oy = srgn * hx * sr + stgn * hy * cr
                oz = szgn * hz
                corner = (px + ox, py + oy, zc + oz)
                corners.append(corner)
        base = len(mesh.vertices)
        mesh.vertices.extend(corners)

        def fi(*idx: int) -> Face:
            return [base + i for i in idx]

        # Box faces (matching original implementation)
        mesh.faces.append(fi(0, 1, 2, 3))
        mesh.faces.append(fi(4, 7, 6, 5))
        mesh.faces.append(fi(0, 4, 5, 1))
        mesh.faces.append(fi(1, 5, 6, 2))
        mesh.faces.append(fi(2, 6, 7, 3))
        mesh.faces.append(fi(3, 7, 4, 0))
    return mesh


def helix_array_mesh(params: Dict[str, Any], center: Vec3) -> Mesh:
    """Copy a base mesh along a helix path."""
    count = int(params.get("count", params.get("step_count", 12)))
    if params.get("turns") is not None:
        total_turn = float(params["turns"]) * 2 * math.pi
    else:
        total_turn = math.radians(float(params.get("total_turn_degrees", 360)))
    total_h = float(params.get("height", params.get("total_height", 3.0)))
    rise = total_h / max(1, count)
    radius = float(params.get("radius", 1.0))
    cx, cy, cz = center
    
    # Get base mesh dimensions from params
    base_size = params.get("base_size", [1.0, 1.0, 0.05])
    base_size = [float(v) for v in (base_size if isinstance(base_size, (list, tuple)) else [base_size, base_size, base_size])]
    
    # Generate base mesh (simple box)
    base_mesh = box_mesh((0, 0, 0), base_size)
    
    mesh = Mesh()
    for i in range(count):
        frac = i / max(1, count - 1) if count > 1 else 0
        theta = total_turn * frac
        z = cz + i * rise
        
        # Position on helix
        px = cx + radius * math.cos(theta)
        py = cy + radius * math.sin(theta)
        pz = z
        
        # Rotation around Z axis (tangent to helix)
        rot_z = theta
        
        # Transform: position, rotation
        transform = {
            "position": [px, py, pz],
            "rotation": [0, 0, math.degrees(rot_z)],
            "scale": [1, 1, 1]
        }
        
        transformed = apply_transform(base_mesh, transform)
        base_idx = len(mesh.vertices)
        mesh.vertices.extend(transformed.vertices)
        mesh.faces.extend([[base_idx + f for f in face] for face in transformed.faces])
    
    return mesh


def spiral_post_array_mesh(params: Dict[str, Any], center: Vec3) -> Mesh:
    """Vertical cylinders along the stair spiral at outer radius."""
    count = int(params.get("count", params.get("step_count", 12)))
    if params.get("turns") is not None:
        total_turn = float(params["turns"]) * 2 * math.pi
    else:
        total_turn = math.radians(float(params.get("total_turn_degrees", 360)))
    total_h = float(params.get("height", params.get("total_height", 3.0)))
    rise = total_h / max(1, count)
    r = float(params.get("radius", 1.0))
    post_r = float(params.get("post_radius", 0.025))
    ph = float(params.get("post_height", 0.9))
    start_z = float(params.get("start_z", 0.0))
    cx, cy, cz = center
    mesh = Mesh()
    for i in range(count):
        frac = i / max(1, count - 1) if count > 1 else 0
        theta = total_turn * frac
        px = cx + r * math.cos(theta)
        py = cy + r * math.sin(theta)
        pz = cz + start_z + i * rise
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
    
    # If count is provided (from spiral staircase), match the tread angle distribution
    # Treads use frac = (i * rise) / total_h, so last tread is at (count-1)/count of turn
    count = params.get("count")
    if count is not None:
        count = int(count)
        if count > 1:
            turn = turn * (count - 1) / count
    
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


def bezier_point(points: List[Vec3], t: float) -> Vec3:
    work = [p for p in points]
    n = len(work)
    for level in range(1, n):
        for i in range(n - level):
            ax, ay, az = work[i]
            bx, by, bz = work[i + 1]
            work[i] = (
                ax + (bx - ax) * t,
                ay + (by - ay) * t,
                az + (bz - az) * t,
            )
    return work[0]


def curve_params_to_points(params: Dict[str, Any]) -> List[Vec3]:
    raw_points = params.get("points", [])
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        return []
    pts: List[Vec3] = []
    for p in raw_points:
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            pts.append((float(p[0]), float(p[1]), float(p[2])))
    if len(pts) < 2:
        return []

    kind = str(params.get("kind", "polyline")).lower()
    if kind == "bezier" and len(pts) >= 3:
        segs = max(8, int(float(params.get("segments", 48))))
        return [bezier_point(pts, i / segs) for i in range(segs + 1)]
    return pts


def curve_path_sweep_mesh(params: Dict[str, Any], center: Vec3, obn: Dict[str, LiveObject]) -> Optional[Mesh]:
    along_name = str(params.get("along", "")).strip()
    curve_obj = obn.get(along_name)
    if curve_obj is None:
        return None
    curve_params = get_effective_params(curve_obj, obn)
    pts = curve_params_to_points(curve_params)
    if len(pts) < 2:
        return None

    radius = float(params.get("profile_radius", params.get("radius", params.get("tube_radius", 0.035))))
    segments = max(4, int(float(params.get("segments", 12))))
    tube_segments = max(6, min(16, segments))
    cx, cy, cz = center
    mesh = Mesh()
    world_pts = [(x + cx, y + cy, z + cz) for x, y, z in pts]
    for a, b in zip(world_pts, world_pts[1:]):
        mesh.extend(tube_between(a, b, radius, tube_segments))
    return mesh


Point2 = Tuple[float, float]


def _as_float2(val: Any, default: Point2 = (0.0, 0.0)) -> Point2:
    v = val if val is not None else default
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return (float(v[0]), float(v[1]))
    return default


def _poly_centroid(points: List[Point2]) -> Point2:
    if not points:
        return (0.0, 0.0)
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _point_in_polygon(pt: Point2, polygon: List[Point2]) -> bool:
    x, y = pt
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def _capsule_boundary(params: Dict[str, Any]) -> List[Point2]:
    cx, cy = _as_float2(params.get("center"), (0.0, 0.0))
    length = float(params.get("length", params.get("width", 2.0)))
    depth = float(params.get("depth", params.get("height", 0.8)))
    radius = min(float(params.get("radius", depth * 0.5)), depth * 0.5, length * 0.5)
    seg = max(8, int(params.get("segments", 48)) // 2)
    half_straight = max(0.0, length * 0.5 - radius)
    pts: List[Point2] = []
    for i in range(seg + 1):
        a = -math.pi * 0.5 + math.pi * i / seg
        pts.append((cx + half_straight + math.cos(a) * radius, cy + math.sin(a) * radius))
    for i in range(seg + 1):
        a = math.pi * 0.5 + math.pi * i / seg
        pts.append((cx - half_straight + math.cos(a) * radius, cy + math.sin(a) * radius))
    return pts


def _rounded_rect_boundary(params: Dict[str, Any]) -> List[Point2]:
    cx, cy = _as_float2(params.get("center"), (0.0, 0.0))
    width = float(params.get("width", params.get("length", 2.0)))
    depth = float(params.get("depth", params.get("height", 1.0)))
    radius = min(float(params.get("radius", params.get("corner_radius", 0.12))), width * 0.5, depth * 0.5)
    seg = max(3, int(params.get("corner_segments", max(4, int(params.get("segments", 48)) // 8))))
    corners = [
        (cx + width * 0.5 - radius, cy - depth * 0.5 + radius, -math.pi * 0.5, 0.0),
        (cx + width * 0.5 - radius, cy + depth * 0.5 - radius, 0.0, math.pi * 0.5),
        (cx - width * 0.5 + radius, cy + depth * 0.5 - radius, math.pi * 0.5, math.pi),
        (cx - width * 0.5 + radius, cy - depth * 0.5 + radius, math.pi, math.pi * 1.5),
    ]
    pts: List[Point2] = []
    for ox, oy, a0, a1 in corners:
        for i in range(seg + 1):
            a = a0 + (a1 - a0) * i / seg
            pts.append((ox + math.cos(a) * radius, oy + math.sin(a) * radius))
    return pts


def _circle_boundary(params: Dict[str, Any]) -> List[Point2]:
    cx, cy = _as_float2(params.get("center"), (0.0, 0.0))
    radius = float(params.get("radius", 0.5))
    seg = max(16, int(params.get("segments", 64)))
    return [(cx + math.cos(math.tau * i / seg) * radius, cy + math.sin(math.tau * i / seg) * radius) for i in range(seg)]


def _offset_boundary(points: List[Point2], amount: float) -> List[Point2]:
    cx, cy = _poly_centroid(points)
    out: List[Point2] = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        d = math.sqrt(dx * dx + dy * dy)
        if d < 1e-6:
            out.append((x, y))
        else:
            out.append((x + dx / d * amount, y + dy / d * amount))
    return out


def _boundary_bbox(points: List[Point2]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _recipe_infill_paths(boundary: List[Point2], params: Dict[str, Any]) -> List[List[Vec3]]:
    min_x, min_y, max_x, max_y = _boundary_bbox(boundary)
    spacing = max(0.02, float(params.get("spacing", 0.12)))
    step = max(spacing * 0.35, float(params.get("sample_step", spacing * 0.45)))
    z = float(params.get("z", 0.0))
    amplitude = float(params.get("amplitude", params.get("curl", spacing * 0.42)))
    frequency = float(params.get("frequency", 2.3))
    phase = float(params.get("phase", 0.0))
    seed = int(params.get("seed", 1))
    rng = random.Random(seed)
    jitter = float(params.get("jitter", spacing * 0.18))
    margin = float(params.get("margin", spacing * 0.15))
    paths: List[List[Vec3]] = []
    row = 0
    y = min_y + spacing * 0.5
    while y <= max_y - spacing * 0.35:
        row_phase = phase + rng.uniform(-0.65, 0.65)
        row_y = y + rng.uniform(-jitter, jitter)
        current: List[Vec3] = []
        x = min_x + margin
        while x <= max_x - margin:
            t = (x - min_x) / max(1e-6, max_x - min_x)
            wave_y = row_y + math.sin(math.tau * (frequency * t + row * 0.17) + row_phase) * amplitude
            if _point_in_polygon((x, wave_y), boundary):
                current.append((x, wave_y, z))
            else:
                if len(current) >= 2:
                    paths.append(current if row % 2 == 0 else list(reversed(current)))
                current = []
            x += step
        if len(current) >= 2:
            paths.append(current if row % 2 == 0 else list(reversed(current)))
        row += 1
        y += spacing
    return paths


def _formula_clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _formula_lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _formula_noise(x: float, y: float = 0.0, seed: float = 0.0) -> float:
    # Deterministic value-noise-ish hash in [-1, 1]. Good enough for recipe variation.
    v = math.sin(x * 12.9898 + y * 78.233 + seed * 37.719) * 43758.5453
    return (v - math.floor(v)) * 2.0 - 1.0


FORMULA_FUNCS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sqrt": math.sqrt,
    "abs": abs,
    "min": min,
    "max": max,
    "pow": pow,
    "floor": math.floor,
    "ceil": math.ceil,
    "clamp": _formula_clamp,
    "lerp": _formula_lerp,
    "noise": _formula_noise,
}


def _eval_formula_ast(node: ast.AST, env: Dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_formula_ast(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"unknown formula variable: {node.id}")
        return float(env[node.id])
    if isinstance(node, ast.UnaryOp):
        v = _eval_formula_ast(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
    if isinstance(node, ast.BinOp):
        a = _eval_formula_ast(node.left, env)
        b = _eval_formula_ast(node.right, env)
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
        if isinstance(node.op, ast.Mod):
            return a % b
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = FORMULA_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"unsupported formula function: {node.func.id}")
        args = [_eval_formula_ast(arg, env) for arg in node.args]
        return float(fn(*args))
    if isinstance(node, ast.Compare):
        left = _eval_formula_ast(node.left, env)
        ok = True
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_formula_ast(comparator, env)
            if isinstance(op, ast.Lt):
                ok = ok and left < right
            elif isinstance(op, ast.LtE):
                ok = ok and left <= right
            elif isinstance(op, ast.Gt):
                ok = ok and left > right
            elif isinstance(op, ast.GtE):
                ok = ok and left >= right
            elif isinstance(op, ast.Eq):
                ok = ok and abs(left - right) < 1e-9
            elif isinstance(op, ast.NotEq):
                ok = ok and abs(left - right) >= 1e-9
            else:
                raise ValueError("unsupported formula comparison")
            left = right
        return 1.0 if ok else 0.0
    if isinstance(node, ast.BoolOp):
        values = [_eval_formula_ast(v, env) != 0.0 for v in node.values]
        if isinstance(node.op, ast.And):
            return 1.0 if all(values) else 0.0
        if isinstance(node.op, ast.Or):
            return 1.0 if any(values) else 0.0
    raise ValueError("unsupported formula expression")


def _eval_formula(expr: Any, env: Dict[str, float], default: float = 0.0) -> float:
    if isinstance(expr, (int, float)):
        return float(expr)
    if not isinstance(expr, str) or not expr.strip():
        return default
    tree = ast.parse(expr.strip(), mode="eval")
    for child in ast.walk(tree):
        if isinstance(child, (ast.Attribute, ast.Subscript, ast.List, ast.Tuple, ast.Dict, ast.Lambda)):
            raise ValueError("unsupported formula syntax")
    return _eval_formula_ast(tree, env)


def _recipe_formula_paths(boundary: List[Point2], params: Dict[str, Any]) -> List[List[Vec3]]:
    min_x, min_y, max_x, max_y = _boundary_bbox(boundary)
    width = max(1e-6, max_x - min_x)
    depth = max(1e-6, max_y - min_y)
    center_x, center_y = _poly_centroid(boundary)
    rows = max(1, int(params.get("rows", params.get("count", 8))))
    samples = max(2, int(params.get("samples", params.get("points", 80))))
    z = float(params.get("z", 0.0))
    reverse_alternate = metadata_flag(params.get("reverse_alternate")) is not False
    clip = metadata_flag(params.get("clip")) is not False

    x_expr = params.get("x", params.get("formula_x", "min_x+width*u"))
    y_expr = params.get("y", params.get("formula_y", "min_y+depth*v"))
    z_expr = params.get("z_formula", params.get("formula_z"))

    numeric_params = {
        str(k): float(v)
        for k, v in params.items()
        if isinstance(k, str) and isinstance(v, (int, float)) and k not in {"rows", "count", "samples", "points"}
    }
    paths: List[List[Vec3]] = []
    for row in range(rows):
        v = row / max(1, rows - 1) if rows > 1 else 0.5
        row_y = min_y + depth * v
        current: List[Vec3] = []
        for sample in range(samples):
            u = sample / max(1, samples - 1)
            env: Dict[str, float] = {
                "u": u,
                "v": v,
                "t": u,
                "row": float(row),
                "sample": float(sample),
                "rows": float(rows),
                "samples": float(samples),
                "pi": math.pi,
                "tau": math.tau,
                "min_x": min_x,
                "max_x": max_x,
                "min_y": min_y,
                "max_y": max_y,
                "width": width,
                "depth": depth,
                "center_x": center_x,
                "center_y": center_y,
                "row_y": row_y,
                **numeric_params,
            }
            x = _eval_formula(x_expr, env, min_x + width * u)
            y = _eval_formula(y_expr, env, row_y)
            zz = _eval_formula(z_expr, env, z) if z_expr is not None else z
            if (not clip) or _point_in_polygon((x, y), boundary):
                current.append((x, y, zz))
            else:
                if len(current) >= 2:
                    paths.append(current if (row % 2 == 0 or not reverse_alternate) else list(reversed(current)))
                current = []
        if len(current) >= 2:
            paths.append(current if (row % 2 == 0 or not reverse_alternate) else list(reversed(current)))
    return paths


def _surface_formula_mesh(params: Dict[str, Any]) -> Mesh:
    u_segments = max(1, int(params.get("u_segments", params.get("segments_u", params.get("columns", 32)))))
    v_segments = max(1, int(params.get("v_segments", params.get("segments_v", params.get("rows", 12)))))
    x_expr = params.get("x", params.get("formula_x", "(u-0.5)*width"))
    y_expr = params.get("y", params.get("formula_y", "(v-0.5)*depth"))
    z_expr = params.get("z", params.get("formula_z", "0"))
    numeric_params = {
        str(k): float(v)
        for k, v in params.items()
        if isinstance(k, str) and isinstance(v, (int, float))
    }
    defaults = {
        "width": float(params.get("width", 2.0)),
        "depth": float(params.get("depth", 1.0)),
        "height": float(params.get("height", 1.0)),
        "radius": float(params.get("radius", 1.0)),
        "twist": float(params.get("twist", 0.0)),
        "curl": float(params.get("curl", 0.0)),
        "phase": float(params.get("phase", 0.0)),
    }
    numeric_params = {**defaults, **numeric_params}

    mesh = Mesh()
    for j in range(v_segments + 1):
        v = j / v_segments
        for i in range(u_segments + 1):
            u = i / u_segments
            env: Dict[str, float] = {
                "u": u,
                "v": v,
                "i": float(i),
                "j": float(j),
                "u_segments": float(u_segments),
                "v_segments": float(v_segments),
                "pi": math.pi,
                "tau": math.tau,
                **numeric_params,
            }
            mesh.vertices.append((
                _eval_formula(x_expr, env, 0.0),
                _eval_formula(y_expr, env, 0.0),
                _eval_formula(z_expr, env, 0.0),
            ))
    row_len = u_segments + 1
    for j in range(v_segments):
        for i in range(u_segments):
            a = j * row_len + i + 1
            b = a + 1
            c = a + row_len + 1
            d = a + row_len
            mesh.faces.append([a, b, c, d])
    return mesh


def _surface_boundary_tubes(surface: Mesh, u_segments: int, v_segments: int, radius: float, sides: int) -> Mesh:
    mesh = Mesh()
    row_len = u_segments + 1

    def vtx(i: int, j: int) -> Vec3:
        return surface.vertices[j * row_len + i]

    for i in range(u_segments):
        mesh.extend(tube_between(vtx(i, 0), vtx(i + 1, 0), radius, sides))
        mesh.extend(tube_between(vtx(i, v_segments), vtx(i + 1, v_segments), radius, sides))
    for j in range(v_segments):
        mesh.extend(tube_between(vtx(0, j), vtx(0, j + 1), radius, sides))
        mesh.extend(tube_between(vtx(u_segments, j), vtx(u_segments, j + 1), radius, sides))
    return mesh


def _perforate_surface_grid(surface: Mesh, u_segments: int, v_segments: int, params: Dict[str, Any]) -> Mesh:
    u_every = max(1, int(params.get("u_every", params.get("every_u", 4))))
    v_every = max(1, int(params.get("v_every", params.get("every_v", 3))))
    u_phase = int(params.get("u_phase", params.get("phase_u", 0)))
    v_phase = int(params.get("v_phase", params.get("phase_v", 0)))
    condition = params.get("condition", params.get("formula"))
    keep_border = metadata_flag(params.get("keep_border")) is not False
    out = Mesh(vertices=list(surface.vertices), faces=[])
    for j in range(v_segments):
        for i in range(u_segments):
            face_index = j * u_segments + i
            u = (i + 0.5) / max(1, u_segments)
            v = (j + 0.5) / max(1, v_segments)
            remove = ((i - u_phase) % u_every == 0) and ((j - v_phase) % v_every == 0)
            if condition is not None:
                env = {
                    "i": float(i),
                    "j": float(j),
                    "u": u,
                    "v": v,
                    "u_segments": float(u_segments),
                    "v_segments": float(v_segments),
                    "pi": math.pi,
                    "tau": math.tau,
                }
                for k, val in params.items():
                    if isinstance(k, str) and isinstance(val, (int, float)):
                        env[k] = float(val)
                remove = _eval_formula(condition, env, 0.0) != 0.0
            if keep_border and (i == 0 or j == 0 or i == u_segments - 1 or j == v_segments - 1):
                remove = False
            if not remove and 0 <= face_index < len(surface.faces):
                out.faces.append(surface.faces[face_index])
    return out


def _recipe_boundary_from_op(op: Dict[str, Any]) -> List[Point2]:
    kind = str(op.get("kind", op.get("shape", "capsule"))).lower()
    if kind in {"capsule", "pill"}:
        return _capsule_boundary(op)
    if kind in {"rounded_rect", "rounded_rectangle", "roundrect", "rect", "rectangle"}:
        return _rounded_rect_boundary(op)
    if kind in {"circle", "disk"}:
        return _circle_boundary(op)
    pts = op.get("points")
    if isinstance(pts, list):
        out: List[Point2] = []
        for p in pts:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                out.append((float(p[0]), float(p[1])))
        if len(out) >= 3:
            return out
    return _capsule_boundary(op)


@dataclass
class SurfaceData:
    mesh: Mesh
    u_segments: int
    v_segments: int


@dataclass
class GridData:
    size: Tuple[int, int, int]
    cell: float
    origin: Vec3
    occupied: set[Tuple[int, int, int]] = field(default_factory=set)


@dataclass
class FieldData:
    kind: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleData:
    kind: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlacementData:
    position: Vec3
    rotation: Vec3 = (0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)
    tile: str = ""
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecipeContext:
    obn: Optional[Dict[str, LiveObject]] = None
    boundaries: Dict[str, List[Point2]] = field(default_factory=dict)
    curves: Dict[str, List[List[Vec3]]] = field(default_factory=dict)
    surfaces: Dict[str, SurfaceData] = field(default_factory=dict)
    points: Dict[str, List[Vec3]] = field(default_factory=dict)
    grids: Dict[str, GridData] = field(default_factory=dict)
    fields: Dict[str, FieldData] = field(default_factory=dict)
    modules: Dict[str, ModuleData] = field(default_factory=dict)
    sockets: Dict[str, set[str]] = field(default_factory=dict)
    directional_sockets: Dict[str, Dict[str, set[str]]] = field(default_factory=dict)
    placements: Dict[str, List[PlacementData]] = field(default_factory=dict)
    meshes: Dict[str, Mesh] = field(default_factory=dict)
    emitted: Mesh = field(default_factory=Mesh)


def _recipe_warn(obj: LiveObject, message: str) -> None:
    print(f"[live-obj] recipe '{obj.name}' {message}", file=sys.stderr)


def _recipe_output_id(op: Dict[str, Any], fallback: str = "") -> str:
    return str(op.get("id", op.get("name", fallback))).strip()


def _recipe_source_id(op: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = op.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _recipe_op_boundary(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if oid:
        ctx.boundaries[oid] = _recipe_boundary_from_op(op)


def _recipe_op_offset(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    source = _recipe_source_id(op, "from", "source")
    if oid and source in ctx.boundaries:
        ctx.boundaries[oid] = _offset_boundary(ctx.boundaries[source], float(op.get("amount", op.get("distance", -0.05))))
    elif source:
        _recipe_warn(obj, f"offset skipped missing boundary '{source}'")


def _recipe_op_infill(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    source = _recipe_source_id(op, "inside", "boundary")
    if oid and source in ctx.boundaries:
        ctx.curves[oid] = _recipe_infill_paths(ctx.boundaries[source], op)
    elif source:
        _recipe_warn(obj, f"infill skipped missing boundary '{source}'")


def _recipe_op_path_formula(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    source = _recipe_source_id(op, "inside", "boundary")
    if oid and source in ctx.boundaries:
        ctx.curves[oid] = _recipe_formula_paths(ctx.boundaries[source], op)
    elif source:
        cmd = str(op.get("cmd", op.get("op", "path_formula")))
        _recipe_warn(obj, f"{cmd} skipped missing boundary '{source}'")


def _recipe_curve_from_op(op: Dict[str, Any]) -> List[Vec3]:
    kind = str(op.get("kind", op.get("shape", "polyline"))).strip().lower()
    z = float(op.get("z", op.get("elevation", 0.0)))
    if kind in {"circle", "loop", "ring"}:
        cx, cy = _as_float2(op.get("center"), (0.0, 0.0))
        radius = float(op.get("radius", 0.5))
        count = max(8, int(op.get("points", op.get("segments", 48))))
        return [(cx + math.cos(math.tau * i / count) * radius, cy + math.sin(math.tau * i / count) * radius, z) for i in range(count)]
    if kind in {"capsule", "pill", "rounded_rect", "rounded_rectangle", "roundrect", "rect", "rectangle"}:
        return [(x, y, z) for x, y in _recipe_boundary_from_op(op)]
    pts = _coerce_point_list(op.get("points", []), z)
    if pts:
        return pts
    return []


def _recipe_op_curve(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    pts = _recipe_curve_from_op(op)
    if oid and len(pts) >= 2:
        ctx.curves[oid] = [pts]
    elif oid:
        _recipe_warn(obj, f"curve '{oid}' skipped because it has fewer than two points")


def _recipe_op_points(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if not oid:
        return
    count = max(0, int(op.get("count", op.get("points", 16))))
    seed = int(op.get("seed", 1))
    z = float(op.get("z", 0.0))
    rng = random.Random(seed)
    source = _recipe_source_id(op, "inside", "boundary")
    pts: List[Vec3] = []
    if source in ctx.boundaries:
        boundary = ctx.boundaries[source]
        min_x, min_y, max_x, max_y = _boundary_bbox(boundary)
        attempts = 0
        while len(pts) < count and attempts < count * 80:
            attempts += 1
            x = rng.uniform(min_x, max_x)
            y = rng.uniform(min_y, max_y)
            if _point_in_polygon((x, y), boundary):
                pts.append((x, y, z))
    elif source:
        _recipe_warn(obj, f"points skipped missing boundary '{source}'")
        return
    else:
        width = float(op.get("width", op.get("size", 1.0)))
        depth = float(op.get("depth", width))
        height = float(op.get("height", 0.0))
        for _ in range(count):
            pts.append((
                rng.uniform(-width * 0.5, width * 0.5),
                rng.uniform(-depth * 0.5, depth * 0.5),
                z + rng.uniform(0.0, height),
            ))
    ctx.points[oid] = pts


def _recipe_vec3(value: Any, default: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    if isinstance(value, (int, float)):
        v = float(value)
        return (v, v, v)
    return default


def _recipe_normalize(v: Vec3, default: Vec3 = (1.0, 0.0, 0.0)) -> Vec3:
    x, y, z = v
    d = math.sqrt(x * x + y * y + z * z)
    if d < 1e-9:
        return default
    return (x / d, y / d, z / d)


def _recipe_op_field(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if not oid:
        return
    kind = str(op.get("kind", op.get("type", op.get("mode", "direction")))).strip().lower()
    ctx.fields[oid] = FieldData(kind, dict(op))


def _recipe_eval_field(field: FieldData, point: Vec3, step: int) -> Vec3:
    p = field.params
    kind = field.kind
    x, y, z = point
    strength = float(p.get("strength", 1.0))
    center = _recipe_vec3(p.get("center"), (0.0, 0.0, 0.0))

    if kind in {"direction", "linear", "constant"}:
        direction = _recipe_normalize(_recipe_vec3(p.get("direction", p.get("vector")), (1.0, 0.0, 0.0)))
        return (direction[0] * strength, direction[1] * strength, direction[2] * strength)

    if kind in {"attractor", "attract"}:
        direction = _recipe_normalize((center[0] - x, center[1] - y, center[2] - z))
        return (direction[0] * strength, direction[1] * strength, direction[2] * strength)

    if kind in {"radial", "repulsor", "repel"}:
        direction = _recipe_normalize((x - center[0], y - center[1], z - center[2]))
        return (direction[0] * strength, direction[1] * strength, direction[2] * strength)

    if kind in {"swirl", "vortex", "orbit"}:
        dx, dy = x - center[0], y - center[1]
        tangent = _recipe_normalize((-dy, dx, 0.0), (0.0, 1.0, 0.0))
        radial = _recipe_normalize((dx, dy, 0.0), (1.0, 0.0, 0.0))
        outward = float(p.get("outward", p.get("radial", 0.0)))
        upward = float(p.get("upward", p.get("lift", 0.0)))
        v = (
            tangent[0] + radial[0] * outward,
            tangent[1] + radial[1] * outward,
            upward,
        )
        direction = _recipe_normalize(v)
        return (direction[0] * strength, direction[1] * strength, direction[2] * strength)

    if kind in {"noise", "turbulence"}:
        frequency = float(p.get("frequency", 1.0))
        seed = int(p.get("seed", 1)) + step
        v = (
            noise3d(x * frequency, y * frequency, z * frequency, seed),
            noise3d(x * frequency + 41.0, y * frequency, z * frequency, seed),
            noise3d(x * frequency, y * frequency + 83.0, z * frequency, seed),
        )
        direction = _recipe_normalize(v)
        return (direction[0] * strength, direction[1] * strength, direction[2] * strength)

    if kind in {"curl_noise", "curl-noise", "curl"}:
        frequency = float(p.get("frequency", 1.0))
        seed = int(p.get("seed", 1))
        eps = max(1e-4, float(p.get("epsilon", 0.01)))
        t = seed + int(step * float(p.get("time_scale", 1.0)))
        sx, sy, sz = x * frequency, y * frequency, z * frequency
        d_bz_dy = (noise3d(sx, sy + eps, sz, t) - noise3d(sx, sy - eps, sz, t)) / (2 * eps)
        d_by_dz = (noise3d(sx, sy, sz + eps, t + 101) - noise3d(sx, sy, sz - eps, t + 101)) / (2 * eps)
        d_bx_dz = (noise3d(sx + 101, sy, sz + eps, t) - noise3d(sx + 101, sy, sz - eps, t)) / (2 * eps)
        d_bz_dx = (noise3d(sx + eps, sy, sz, t) - noise3d(sx - eps, sy, sz, t)) / (2 * eps)
        d_by_dx = (noise3d(sx + eps, sy, sz, t + 101) - noise3d(sx - eps, sy, sz, t + 101)) / (2 * eps)
        d_bx_dy = (noise3d(sx + 101, sy + eps, sz, t) - noise3d(sx + 101, sy - eps, sz, t)) / (2 * eps)
        direction = _recipe_normalize((d_bz_dy - d_by_dz, d_bx_dz - d_bz_dx, d_by_dx - d_bx_dy))
        return (direction[0] * strength, direction[1] * strength, direction[2] * strength)

    return (0.0, 0.0, 0.0)


def _recipe_inside_bounds(point: Vec3, bounds: Any) -> bool:
    if not (isinstance(bounds, list) and len(bounds) >= 2):
        return True
    mn = _recipe_vec3(bounds[0], (-float("inf"), -float("inf"), -float("inf")))
    mx = _recipe_vec3(bounds[1], (float("inf"), float("inf"), float("inf")))
    return mn[0] <= point[0] <= mx[0] and mn[1] <= point[1] <= mx[1] and mn[2] <= point[2] <= mx[2]


def _recipe_op_trace_field(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    source = _recipe_source_id(op, "from", "points", "seeds")
    field_name = _recipe_source_id(op, "field")
    if not oid:
        return
    if source not in ctx.points:
        _recipe_warn(obj, f"trace_field skipped missing point set '{source}'")
        return
    if field_name not in ctx.fields:
        _recipe_warn(obj, f"trace_field skipped missing field '{field_name}'")
        return

    field = ctx.fields[field_name]
    steps = max(1, int(op.get("steps", 80)))
    step_size = float(op.get("step_size", op.get("distance", 0.05)))
    sample_every = max(1, int(op.get("sample_every", 1)))
    bounds = op.get("bounds")
    curves: List[List[Vec3]] = []
    for seed in ctx.points[source]:
        current = seed
        path = [current]
        for step in range(steps):
            v = _recipe_eval_field(field, current, step)
            speed = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
            if speed < 1e-9:
                break
            current = (
                current[0] + v[0] * step_size,
                current[1] + v[1] * step_size,
                current[2] + v[2] * step_size,
            )
            if not _recipe_inside_bounds(current, bounds):
                break
            if (step + 1) % sample_every == 0:
                path.append(current)
        if len(path) >= 2:
            curves.append(path)
    ctx.curves[oid] = curves


def _recipe_op_module(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if not oid:
        return
    kind = str(op.get("kind", op.get("type", op.get("primitive", "box")))).strip().lower()
    ctx.modules[oid] = ModuleData(kind, dict(op))


def _recipe_string_list(value: Any, default: Optional[List[str]] = None) -> List[str]:
    if value is None:
        return list(default or [])
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,|]", value) if p.strip()]
        return parts or list(default or [])
    return [str(value).strip()] if str(value).strip() else list(default or [])


def _recipe_float_list(value: Any, default: Optional[List[float]] = None) -> List[float]:
    if value is None:
        return list(default or [])
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,|]", value) if p.strip()]
        if parts:
            return [float(p) for p in parts]
    return list(default or [])


def _recipe_tile_value(op: Dict[str, Any], tile: str, key: str, default: Any = None) -> Any:
    if tile:
        tile_key = f"{tile}_{key}"
        if tile_key in op:
            return op[tile_key]
    return op.get(key, default)


def _recipe_random_scale(op: Dict[str, Any], rng: random.Random) -> Vec3:
    if op.get("scale") is not None:
        return _recipe_vec3(op.get("scale"), (1.0, 1.0, 1.0))
    lo = float(op.get("scale_min", op.get("min_scale", 1.0)))
    hi = float(op.get("scale_max", op.get("max_scale", lo)))
    if hi < lo:
        lo, hi = hi, lo
    s = rng.uniform(lo, hi)
    return (s, s, s)


def _recipe_random_rotation(op: Dict[str, Any], rng: random.Random, x: float, y: float, z: float) -> Vec3:
    raw = op.get("rotation", op.get("rotate", op.get("rotation_z", 0.0)))
    mode = str(raw).strip().lower() if isinstance(raw, str) else ""
    if mode in {"random", "rand"}:
        angle = rng.uniform(0.0, 360.0)
    elif mode in {"noise", "field"}:
        frequency = float(op.get("rotation_frequency", op.get("frequency", 1.0)))
        angle = (noise3d(x * frequency, y * frequency, z * frequency, int(op.get("seed", 1))) * 0.5 + 0.5) * 360.0
    else:
        angle = float(raw or 0.0)
    step = float(op.get("rotation_step", op.get("angle_step", 0.0)))
    if step > 0:
        angle = round(angle / step) * step
    return (float(op.get("rotation_x", 0.0)), float(op.get("rotation_y", 0.0)), angle)


def _recipe_tile_rotation(op: Dict[str, Any], tile: str, rng: random.Random, x: float, y: float, z: float) -> Vec3:
    raw = _recipe_tile_value(op, tile, "rotation", None)
    if raw is None:
        raw = _recipe_tile_value(op, tile, "rotation_z", None)
    if raw is None:
        return _recipe_random_rotation(op, rng, x, y, z)
    if isinstance(raw, (list, tuple)):
        return _recipe_vec3(raw, (0.0, 0.0, 0.0))
    return (0.0, 0.0, float(raw or 0.0))


def _recipe_op_socket(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    tile = _recipe_source_id(op, "module", "tile", "for")
    if not tile:
        return
    accepts = set(_recipe_string_list(op.get("accepts", op.get("neighbors", op.get("connects"))), []))
    if accepts:
        ctx.sockets[tile] = accepts
        for other in accepts:
            ctx.sockets.setdefault(other, set()).add(tile)
    direction_aliases = {
        "east": "east",
        "e": "east",
        "west": "west",
        "w": "west",
        "north": "north",
        "n": "north",
        "south": "south",
        "s": "south",
        "up": "up",
        "u": "up",
        "top": "up",
        "down": "down",
        "d": "down",
        "bottom": "down",
    }
    for key, direction in direction_aliases.items():
        if key not in op:
            continue
        allowed = set(_recipe_string_list(op.get(key), []))
        if allowed:
            ctx.directional_sockets.setdefault(tile, {}).setdefault(direction, set()).update(allowed)


def _recipe_grid_cell_center(grid: GridData, ix: int, iy: int, iz: int) -> Vec3:
    return (
        grid.origin[0] + (ix + 0.5) * grid.cell,
        grid.origin[1] + (iy + 0.5) * grid.cell,
        grid.origin[2] + (iz + 0.5) * grid.cell,
    )


def _recipe_op_scatter(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if not oid:
        return
    seed = int(op.get("seed", 1))
    rng = random.Random(seed)
    source = _recipe_source_id(op, "from", "points", "grid")
    inside = _recipe_source_id(op, "inside", "boundary")
    count = max(0, int(op.get("count", op.get("points", 32))))
    z = float(op.get("z", 0.0))
    min_distance = max(0.0, float(op.get("min_distance", op.get("spacing", 0.0))))
    jitter = float(op.get("jitter", 0.0))
    tile = str(op.get("tile", op.get("module", ""))).strip()
    mode = str(op.get("mode", op.get("distribution", "random"))).strip().lower()
    frequency = float(op.get("frequency", 1.0))
    threshold = float(op.get("threshold", -1.0 if mode != "noise" else 0.0))
    placements: List[PlacementData] = []

    def maybe_add(point: Vec3) -> None:
        x, y, pz = point
        if jitter > 0:
            x += rng.uniform(-jitter, jitter)
            y += rng.uniform(-jitter, jitter)
        if threshold > -1.0:
            n = noise3d(x * frequency, y * frequency, pz * frequency, seed)
            if n < threshold:
                return
        if min_distance > 0:
            min_d2 = min_distance * min_distance
            for existing in placements:
                dx = existing.position[0] - x
                dy = existing.position[1] - y
                dz = existing.position[2] - pz
                if dx * dx + dy * dy + dz * dz < min_d2:
                    return
        placements.append(PlacementData(
            position=(x, y, pz),
            rotation=_recipe_random_rotation(op, rng, x, y, pz),
            scale=_recipe_random_scale(op, rng),
            tile=tile,
        ))

    if source in ctx.points:
        for point in ctx.points[source]:
            maybe_add(point)
            if count and len(placements) >= count:
                break
    elif source in ctx.grids:
        grid = ctx.grids[source]
        for ix, iy, iz in sorted(grid.occupied):
            maybe_add(_recipe_grid_cell_center(grid, ix, iy, iz))
            if count and len(placements) >= count:
                break
    elif inside in ctx.boundaries:
        boundary = ctx.boundaries[inside]
        min_x, min_y, max_x, max_y = _boundary_bbox(boundary)
        attempts = 0
        max_attempts = max(count * 160, 200)
        while len(placements) < count and attempts < max_attempts:
            attempts += 1
            x = rng.uniform(min_x, max_x)
            y = rng.uniform(min_y, max_y)
            if _point_in_polygon((x, y), boundary):
                maybe_add((x, y, z))
    else:
        width = float(op.get("width", op.get("size", 1.0)))
        depth = float(op.get("depth", width))
        height = float(op.get("height", 0.0))
        for _ in range(count):
            maybe_add((
                rng.uniform(-width * 0.5, width * 0.5),
                rng.uniform(-depth * 0.5, depth * 0.5),
                z + rng.uniform(0.0, height),
            ))

    ctx.placements[oid] = placements


def _recipe_arch_module_mesh(params: Dict[str, Any]) -> Mesh:
    size = _recipe_vec3(params.get("size"), (
        float(params.get("width", 0.16)),
        float(params.get("depth", 0.035)),
        float(params.get("height", 0.28)),
    ))
    width, depth, height = size
    opening_width = min(width * 0.82, float(params.get("opening_width", width * 0.46)))
    spring_height = min(height * 0.8, float(params.get("spring_height", height * 0.45)))
    arch_thickness = max(width * 0.04, float(params.get("arch_thickness", width * 0.09)))
    radius_inner = opening_width * 0.5
    radius_mid = radius_inner + arch_thickness * 0.5
    crown_z = spring_height + radius_inner + arch_thickness
    side_width = max(width * 0.05, (width - opening_width) * 0.5)
    mesh = Mesh()

    if side_width > 1e-6 and spring_height > 1e-6:
        mesh.extend(box_mesh((-(opening_width + side_width) * 0.5, 0.0, spring_height * 0.5), (side_width, depth, spring_height)))
        mesh.extend(box_mesh(((opening_width + side_width) * 0.5, 0.0, spring_height * 0.5), (side_width, depth, spring_height)))
    if crown_z < height:
        top_h = height - crown_z
        mesh.extend(box_mesh((0.0, 0.0, crown_z + top_h * 0.5), (width, depth, top_h)))

    segments = max(5, int(params.get("arch_segments", params.get("segments", 10))))
    block_w = max(arch_thickness * 0.75, math.pi * radius_mid / segments * 0.9)
    block_h = arch_thickness
    for i in range(segments + 1):
        theta = math.pi * i / segments
        x = math.cos(theta) * radius_mid
        z = spring_height + math.sin(theta) * radius_mid
        block = box_mesh((0.0, 0.0, 0.0), (block_w, depth * 1.04, block_h))
        block = apply_transform(block, {
            "position": [x, 0.0, z],
            "rotation": [0.0, 90.0 - math.degrees(theta), 0.0],
            "scale": [1.0, 1.0, 1.0],
        })
        mesh.extend(block)

    return mesh


def _recipe_window_module_mesh(params: Dict[str, Any]) -> Mesh:
    size = _recipe_vec3(params.get("size"), (
        float(params.get("width", 0.16)),
        float(params.get("depth", 0.035)),
        float(params.get("height", 0.28)),
    ))
    width, depth, height = size
    opening_width = min(width * 0.85, float(params.get("opening_width", width * 0.45)))
    opening_height = min(height * 0.85, float(params.get("opening_height", height * 0.46)))
    sill_height = min(height * 0.7, float(params.get("sill_height", height * 0.28)))
    side_width = max(width * 0.04, (width - opening_width) * 0.5)
    top_h = max(0.0, height - (sill_height + opening_height))
    mesh = Mesh()
    if sill_height > 0:
        mesh.extend(box_mesh((0.0, 0.0, sill_height * 0.5), (width, depth, sill_height)))
    mesh.extend(box_mesh((-(opening_width + side_width) * 0.5, 0.0, sill_height + opening_height * 0.5), (side_width, depth, opening_height)))
    mesh.extend(box_mesh(((opening_width + side_width) * 0.5, 0.0, sill_height + opening_height * 0.5), (side_width, depth, opening_height)))
    if top_h > 0:
        mesh.extend(box_mesh((0.0, 0.0, sill_height + opening_height + top_h * 0.5), (width, depth, top_h)))
    return mesh


def _recipe_object_template_mesh(params: Dict[str, Any], obn: Optional[Dict[str, LiveObject]]) -> Mesh:
    ref = str(params.get("ref", params.get("object", params.get("template", "")))).strip()
    if not ref or not obn or ref not in obn:
        return Mesh()
    template = obn[ref]
    if template.mesh.vertices:
        return template.mesh.copy()
    source = str(template.meta.get("source", "")).lower()
    try:
        if source == "procedural":
            base = generate_procedural(template, obn)
            return apply_ops(base, template, obn, "") if base.vertices else Mesh()
        if source == "sdf":
            return generate_sdf(template)
        if source == "simulation":
            return generate_simulation(template, obn)
        if source == "recipe":
            return generate_recipe(template, obn)
    except Exception as exc:
        print(f"[live-obj] recipe object template '{ref}' skipped: {exc}", file=sys.stderr)
    return Mesh()


def _recipe_apply_module_origin(mesh: Mesh, origin: Any) -> Mesh:
    mode = str(origin or "").strip().lower()
    if not mode or not mesh.vertices:
        return mesh
    bbox = compute_bbox(mesh)
    if bbox is None:
        return mesh
    min_x, max_x, min_y, max_y, min_z, max_z = bbox
    if mode in {"center", "centroid", "middle"}:
        anchor = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
    elif mode in {"center_bottom", "bottom_center", "base", "base_center", "origin"}:
        anchor = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, min_z)
    elif mode in {"min", "min_corner", "corner"}:
        anchor = (min_x, min_y, min_z)
    elif isinstance(origin, (list, tuple)) and len(origin) >= 3:
        anchor = (float(origin[0]), float(origin[1]), float(origin[2]))
    else:
        return mesh
    return translate_mesh(mesh, (-anchor[0], -anchor[1], -anchor[2]))


def _recipe_module_mesh(module: ModuleData, obn: Optional[Dict[str, LiveObject]] = None) -> Mesh:
    params = module.params
    kind = module.kind
    if kind in {"object", "ref", "template"} or params.get("ref") or params.get("object") or params.get("template"):
        mesh = _recipe_object_template_mesh(params, obn)
        if mesh.vertices:
            return _recipe_apply_module_origin(mesh, params.get("origin", params.get("anchor_origin")))
    size = _recipe_vec3(params.get("size"), (
        float(params.get("width", 0.1)),
        float(params.get("depth", 0.1)),
        float(params.get("height", 0.1)),
    ))
    if kind in {"arch", "arched_wall", "arch_wall", "portal"}:
        return _recipe_apply_module_origin(_recipe_arch_module_mesh(params), params.get("origin"))
    if kind in {"window", "window_wall", "facade"}:
        return _recipe_apply_module_origin(_recipe_window_module_mesh(params), params.get("origin"))
    if kind in {"column", "pillar", "post"}:
        radius = float(params.get("radius", min(size[0], size[1]) * 0.5))
        height = float(params.get("height", size[2]))
        return _recipe_apply_module_origin(cylinder_mesh("z", (0.0, 0.0, height * 0.5), radius, height, max(8, int(params.get("segments", 12)))), params.get("origin"))
    if kind in {"cylinder", "tube"}:
        radius = float(params.get("radius", min(size[0], size[1]) * 0.5))
        height = float(params.get("height", size[2]))
        return _recipe_apply_module_origin(cylinder_mesh("z", (0.0, 0.0, height * 0.5), radius, height, max(6, int(params.get("segments", 12)))), params.get("origin"))
    if kind in {"sphere", "ball"}:
        radius = float(params.get("radius", max(size) * 0.5))
        return _recipe_apply_module_origin(sphere_mesh((0.0, 0.0, radius), radius, max(8, int(params.get("segments", 10)))), params.get("origin"))
    return _recipe_apply_module_origin(box_mesh((0.0, 0.0, size[2] * 0.5), size), params.get("origin"))


def _recipe_primitive_instance_mesh(op: Dict[str, Any], placement: PlacementData) -> Mesh:
    tile = placement.tile
    primitive = str(_recipe_tile_value(op, tile, "primitive", op.get("shape", "box"))).strip().lower()
    anchor = str(_recipe_tile_value(op, tile, "anchor", op.get("anchor", "base"))).strip().lower()
    size = _recipe_vec3(_recipe_tile_value(op, tile, "size", op.get("size", [0.1, 0.1, 0.1])), (0.1, 0.1, 0.1))
    if primitive in {"cylinder", "tube"}:
        radius = float(_recipe_tile_value(op, tile, "radius", min(size[0], size[1]) * 0.5))
        height = float(_recipe_tile_value(op, tile, "height", size[2]))
        center = (0.0, 0.0, height * 0.5) if anchor in {"base", "bottom"} else (0.0, 0.0, 0.0)
        mesh = cylinder_mesh("z", center, radius, height, max(6, int(op.get("segments", 12))))
    elif primitive in {"sphere", "ball"}:
        radius = float(_recipe_tile_value(op, tile, "radius", max(size) * 0.5))
        center = (0.0, 0.0, radius) if anchor in {"base", "bottom"} else (0.0, 0.0, 0.0)
        mesh = sphere_mesh(center, radius, max(8, int(op.get("segments", 10))))
    else:
        center = (0.0, 0.0, size[2] * 0.5) if anchor in {"base", "bottom"} else (0.0, 0.0, 0.0)
        mesh = box_mesh(center, size)

    transform = {
        "position": list(placement.position),
        "rotation": list(placement.rotation),
        "scale": list(placement.scale),
    }
    return apply_transform(mesh, transform)


def _recipe_instance_mesh(ctx: RecipeContext, op: Dict[str, Any], placement: PlacementData) -> Mesh:
    requested_module = str(op.get("module", op.get("ref", ""))).strip()
    module_id = ""
    if requested_module in {"tile", "by_tile", "$tile"}:
        module_id = placement.tile
    elif requested_module:
        module_id = requested_module
    elif placement.tile in ctx.modules:
        module_id = placement.tile

    if module_id and module_id in ctx.modules:
        mesh = _recipe_module_mesh(ctx.modules[module_id], ctx.obn)
        transform = {
            "position": list(placement.position),
            "rotation": list(placement.rotation),
            "scale": list(placement.scale),
        }
        return apply_transform(mesh, transform)
    return _recipe_primitive_instance_mesh(op, placement)


def _recipe_op_instance(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    source = _recipe_source_id(op, "from", "placements", "points")
    if source in ctx.placements:
        placements = ctx.placements[source]
    elif source in ctx.points:
        placements = [PlacementData(position=p) for p in ctx.points[source]]
    elif source in ctx.grids:
        grid = ctx.grids[source]
        placements = [PlacementData(position=_recipe_grid_cell_center(grid, ix, iy, iz)) for ix, iy, iz in sorted(grid.occupied)]
    else:
        if source:
            _recipe_warn(obj, f"instance skipped missing placements '{source}'")
        return

    skip_tiles = set(_recipe_string_list(op.get("skip", op.get("skip_tiles")), []))
    mesh = Mesh()
    for placement in placements:
        if placement.tile and placement.tile in skip_tiles:
            continue
        mesh.extend(_recipe_instance_mesh(ctx, op, placement))

    target = _recipe_output_id(op)
    if target and target != source:
        ctx.meshes[target] = mesh
    if metadata_flag(op.get("emit")) is not False:
        ctx.emitted.extend(mesh)
        material_name = op.get("material")
        if material_name:
            obj.meta["material"] = str(material_name)


def _recipe_int_set(value: Any, default: set[int]) -> set[int]:
    if value is None:
        return set(default)
    if isinstance(value, (int, float)):
        return {int(value)}
    if isinstance(value, (list, tuple, set)):
        return {int(v) for v in value}
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[, ]+", value) if p.strip()]
        if parts:
            return {int(float(p)) for p in parts}
    return set(default)


def _recipe_grid_size(value: Any) -> Tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (max(1, int(value[0])), max(1, int(value[1])), max(1, int(value[2])))
    if isinstance(value, (int, float)):
        n = max(1, int(value))
        return (n, n, n)
    return (16, 16, 8)


def _recipe_grid_neighborhood(kind: Any) -> List[Tuple[int, int, int]]:
    k = str(kind or "moore").strip().lower()
    if k in {"6", "von_neumann", "von-neumann", "axis"}:
        return [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    return [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if not (dx == 0 and dy == 0 and dz == 0)
    ]


def _recipe_op_grid(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if not oid:
        return
    nx, ny, nz = _recipe_grid_size(op.get("size", op.get("grid", op.get("dims", [16, 16, 8]))))
    cell = float(op.get("cell", 0.1))
    raw_origin = op.get("origin")
    if isinstance(raw_origin, (list, tuple)) and len(raw_origin) >= 3:
        origin = (float(raw_origin[0]), float(raw_origin[1]), float(raw_origin[2]))
    else:
        origin = (-nx * cell * 0.5, -ny * cell * 0.5, 0.0)
    seed = int(op.get("seed", 1))
    rng = random.Random(seed)
    init = str(op.get("init", op.get("mode", "seed_cluster"))).strip().lower()
    fill = float(op.get("fill", 0.0))
    occupied: set[Tuple[int, int, int]] = set()

    if init in {"random", "noise"} or fill > 0:
        chance = fill if fill > 0 else 0.14
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    if rng.random() <= chance:
                        occupied.add((ix, iy, iz))

    if init in {"sphere", "ball"}:
        cx, cy, cz = nx * 0.5, ny * 0.5, nz * 0.5
        radius = float(op.get("radius", min(nx, ny, nz) * 0.22))
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    dx, dy, dz = ix + 0.5 - cx, iy + 0.5 - cy, iz + 0.5 - cz
                    if math.sqrt(dx * dx + dy * dy + dz * dz) <= radius:
                        occupied.add((ix, iy, iz))

    if not occupied or init in {"seed_cluster", "cluster", "center"}:
        cx, cy = nx // 2, ny // 2
        seed_count = max(1, int(op.get("seed_count", max(6, nx // 3))))
        seed_radius = max(0, int(op.get("seed_radius", 2)))
        seed_z = max(0, min(nz - 1, int(op.get("seed_z", 0))))
        seed_z_span = max(0, int(op.get("seed_z_span", min(2, nz - 1))))
        for _ in range(seed_count):
            ix = max(0, min(nx - 1, cx + rng.randint(-seed_radius, seed_radius)))
            iy = max(0, min(ny - 1, cy + rng.randint(-seed_radius, seed_radius)))
            iz = max(0, min(nz - 1, seed_z + rng.randint(0, seed_z_span)))
            occupied.add((ix, iy, iz))

    ctx.grids[oid] = GridData((nx, ny, nz), cell, origin, occupied)


def _recipe_parse_wfc_rules(value: Any, tiles: List[str]) -> Dict[str, set[str]]:
    rules: Dict[str, set[str]] = {tile: set(tiles) for tile in tiles}
    if not value:
        return rules
    parsed: Dict[str, set[str]] = {tile: set() for tile in tiles}
    if isinstance(value, str):
        chunks = [chunk.strip() for chunk in value.split(";") if chunk.strip()]
        for chunk in chunks:
            if ":" not in chunk:
                continue
            tile, allowed_raw = chunk.split(":", 1)
            tile = tile.strip()
            if tile not in parsed:
                continue
            allowed = {v for v in _recipe_string_list(allowed_raw) if v in parsed}
            parsed[tile].update(allowed)
            for neighbor in allowed:
                parsed[neighbor].add(tile)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and ":" in item:
                tile, allowed_raw = item.split(":", 1)
                tile = tile.strip()
                if tile in parsed:
                    allowed = {v for v in _recipe_string_list(allowed_raw) if v in parsed}
                    parsed[tile].update(allowed)
                    for neighbor in allowed:
                        parsed[neighbor].add(tile)
    for tile in tiles:
        if parsed[tile]:
            rules[tile] = parsed[tile]
    return rules


def _recipe_weighted_choice(options: List[str], weights: Dict[str, float], rng: random.Random) -> str:
    if not options:
        return ""
    total = sum(max(0.0, weights.get(option, 1.0)) for option in options)
    if total <= 0:
        return rng.choice(options)
    pick = rng.random() * total
    running = 0.0
    for option in options:
        running += max(0.0, weights.get(option, 1.0))
        if pick <= running:
            return option
    return options[-1]


RECIPE_WFC_DIRECTION_OFFSETS: Dict[str, Tuple[int, int, int]] = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "north": (0, 1, 0),
    "south": (0, -1, 0),
    "up": (0, 0, 1),
    "down": (0, 0, -1),
}

RECIPE_WFC_INVERSE_DIRECTIONS: Dict[str, str] = {
    "east": "west",
    "west": "east",
    "north": "south",
    "south": "north",
    "up": "down",
    "down": "up",
}


def _recipe_wfc_neighbor_items(size: Tuple[int, int, int], cell: Tuple[int, int, int], neighborhood: str) -> List[Tuple[Tuple[int, int, int], str]]:
    nx, ny, nz = size
    ix, iy, iz = cell
    if neighborhood in {"moore", "8", "26"}:
        offsets: List[Tuple[int, int, int, str]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in ((-1, 0, 1) if nz > 1 else (0,)):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    direction = "any"
                    for name, offset in RECIPE_WFC_DIRECTION_OFFSETS.items():
                        if offset == (dx, dy, dz):
                            direction = name
                            break
                    offsets.append((dx, dy, dz, direction))
    else:
        offsets = [(1, 0, 0, "east"), (-1, 0, 0, "west"), (0, 1, 0, "north"), (0, -1, 0, "south")]
        if nz > 1:
            offsets.extend([(0, 0, 1, "up"), (0, 0, -1, "down")])
    out: List[Tuple[Tuple[int, int, int], str]] = []
    for dx, dy, dz, direction in offsets:
        nx_, ny_, nz_ = ix + dx, iy + dy, iz + dz
        if 0 <= nx_ < nx and 0 <= ny_ < ny and 0 <= nz_ < nz:
            out.append(((nx_, ny_, nz_), direction))
    return out


def _recipe_wfc_allowed_neighbors(
    ctx: RecipeContext,
    tile: str,
    direction: str,
    generic_rules: Dict[str, set[str]],
    tiles: List[str],
) -> set[str]:
    if direction != "any":
        directional = ctx.directional_sockets.get(tile, {})
        if direction in directional:
            return {other for other in directional[direction] if other in tiles}
    return set(generic_rules.get(tile, set(tiles)))


def _recipe_wfc_tiles_compatible(
    ctx: RecipeContext,
    tile: str,
    neighbor_tile: str,
    direction: str,
    generic_rules: Dict[str, set[str]],
    tiles: List[str],
) -> bool:
    if neighbor_tile not in _recipe_wfc_allowed_neighbors(ctx, tile, direction, generic_rules, tiles):
        return False
    inverse = RECIPE_WFC_INVERSE_DIRECTIONS.get(direction)
    if inverse:
        inverse_rules = ctx.directional_sockets.get(neighbor_tile, {})
        if inverse in inverse_rules and tile not in inverse_rules[inverse]:
            return False
    return True


def _recipe_parse_wfc_forced(value: Any, tiles: List[str]) -> Dict[Tuple[int, int, int], str]:
    forced: Dict[Tuple[int, int, int], str] = {}
    if not value:
        return forced
    chunks: List[Any]
    if isinstance(value, str):
        chunks = [chunk.strip() for chunk in value.split(";") if chunk.strip()]
    elif isinstance(value, list):
        chunks = value
    else:
        chunks = [value]
    for chunk in chunks:
        if isinstance(chunk, str):
            sep = ":" if ":" in chunk else "=" if "=" in chunk else ""
            if not sep:
                continue
            cell_raw, tile = chunk.split(sep, 1)
            coords = [int(float(part.strip())) for part in cell_raw.split(",") if part.strip()]
            tile = tile.strip()
        elif isinstance(chunk, (list, tuple)) and len(chunk) >= 3:
            coords = [int(float(chunk[0])), int(float(chunk[1]))]
            if len(chunk) >= 4 and isinstance(chunk[3], str):
                coords.append(int(float(chunk[2])))
                tile = str(chunk[3]).strip()
            else:
                tile = str(chunk[2]).strip()
        else:
            continue
        if len(coords) == 2:
            coords.append(0)
        if len(coords) >= 3 and tile in tiles:
            forced[(coords[0], coords[1], coords[2])] = tile
    return forced


def _recipe_op_wfc(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if not oid:
        return
    tiles = _recipe_string_list(op.get("tiles"), ["empty", "solid"])
    if not tiles:
        return
    raw_weights = _recipe_float_list(op.get("weights"), [1.0] * len(tiles))
    weights = {tile: raw_weights[i] if i < len(raw_weights) else 1.0 for i, tile in enumerate(tiles)}
    raw_rules = op.get("rules", op.get("adjacency"))
    rules = _recipe_parse_wfc_rules(raw_rules, tiles)
    if not raw_rules and ctx.sockets:
        for tile in tiles:
            if tile in ctx.sockets:
                rules[tile] = {other for other in ctx.sockets[tile] if other in tiles}
    nx, ny, nz = _recipe_grid_size(op.get("size", op.get("grid", [8, 8, 1])))
    cell_size = float(op.get("cell", 0.1))
    origin = _recipe_vec3(op.get("origin"), (-nx * cell_size * 0.5, -ny * cell_size * 0.5, 0.0))
    neighborhood = str(op.get("neighborhood", "von_neumann")).strip().lower()
    rng = random.Random(int(op.get("seed", 1)))
    cells = [(ix, iy, iz) for ix in range(nx) for iy in range(ny) for iz in range(nz)]
    domains: Dict[Tuple[int, int, int], set[str]] = {cell: set(tiles) for cell in cells}

    border_tile = str(op.get("border", "")).strip()
    if border_tile in tiles:
        for ix, iy, iz in cells:
            if ix == 0 or iy == 0 or iz == 0 or ix == nx - 1 or iy == ny - 1 or iz == nz - 1:
                domains[(ix, iy, iz)] = {border_tile}
    forced_cells = _recipe_parse_wfc_forced(op.get("force", op.get("constraints", op.get("pins"))), tiles)
    locked_cells = set()
    for cell, tile in forced_cells.items():
        if cell in domains:
            domains[cell] = {tile}
            locked_cells.add(cell)

    def propagate(start: Tuple[int, int, int]) -> None:
        queue = [start]
        while queue:
            current = queue.pop()
            for neighbor, direction in _recipe_wfc_neighbor_items((nx, ny, nz), current, neighborhood):
                if neighbor in locked_cells:
                    continue
                allowed = set()
                for tile in domains[current]:
                    for candidate in _recipe_wfc_allowed_neighbors(ctx, tile, direction, rules, tiles):
                        if _recipe_wfc_tiles_compatible(ctx, tile, candidate, direction, rules, tiles):
                            allowed.add(candidate)
                if not allowed:
                    allowed = set(tiles)
                narrowed = domains[neighbor].intersection(allowed)
                if not narrowed:
                    narrowed = {_recipe_weighted_choice(sorted(allowed), weights, rng)}
                if narrowed != domains[neighbor]:
                    domains[neighbor] = narrowed
                    queue.append(neighbor)

    for cell in cells:
        if len(domains[cell]) == 1:
            propagate(cell)

    while True:
        open_cells = [cell for cell in cells if len(domains[cell]) > 1]
        if not open_cells:
            break
        open_cells.sort(key=lambda c: (len(domains[c]), rng.random()))
        cell = open_cells[0]
        choice = _recipe_weighted_choice(sorted(domains[cell]), weights, rng)
        domains[cell] = {choice}
        propagate(cell)

    skip_tiles = set(_recipe_string_list(op.get("skip", op.get("skip_tiles")), ["empty", "void", "air", "none"]))
    placements: List[PlacementData] = []
    for ix, iy, iz in cells:
        tile = next(iter(domains[(ix, iy, iz)]))
        if tile in skip_tiles:
            continue
        pos = (
            origin[0] + (ix + 0.5) * cell_size,
            origin[1] + (iy + 0.5) * cell_size,
            origin[2] + (iz + 0.5) * cell_size,
        )
        placements.append(PlacementData(
            position=pos,
            rotation=_recipe_tile_rotation(op, tile, rng, *pos),
            scale=_recipe_vec3(_recipe_tile_value(op, tile, "scale", op.get("scale")), (1.0, 1.0, 1.0)),
            tile=tile,
            attrs={"cell": (ix, iy, iz)},
        ))
    ctx.placements[oid] = placements


def _recipe_op_surface_formula(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    oid = _recipe_output_id(op)
    if oid:
        u_segments = max(1, int(op.get("u_segments", op.get("segments_u", op.get("columns", 32)))))
        v_segments = max(1, int(op.get("v_segments", op.get("segments_v", op.get("rows", 12)))))
        ctx.surfaces[oid] = SurfaceData(_surface_formula_mesh(op), u_segments, v_segments)


def _recipe_op_perforate_surface(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    source = _recipe_source_id(op, "surface", "from")
    target = _recipe_output_id(op, source)
    if source in ctx.surfaces and target:
        data = ctx.surfaces[source]
        ctx.surfaces[target] = SurfaceData(
            _perforate_surface_grid(data.mesh, data.u_segments, data.v_segments, op),
            data.u_segments,
            data.v_segments,
        )
    elif source:
        _recipe_warn(obj, f"perforate_surface skipped missing surface '{source}'")


def _recipe_step_cellular_automata(grid: GridData, op: Dict[str, Any]) -> GridData:
    nx, ny, nz = grid.size
    neigh = _recipe_grid_neighborhood(op.get("neighborhood", op.get("neighbors", "moore")))
    mode = str(op.get("mode", op.get("style", "life"))).strip().lower()
    if mode in {"growth", "grow", "coral"}:
        default_birth = {1, 2, 3}
        default_survive = set(range(27))
    else:
        default_birth = {5}
        default_survive = {4, 5, 6}
    birth = _recipe_int_set(op.get("birth", op.get("birth_rules")), default_birth)
    survive = _recipe_int_set(op.get("survive", op.get("survival", op.get("survival_rules"))), default_survive)
    max_fill = max(0.0, min(1.0, float(op.get("max_fill", 0.35))))
    total = max(1, nx * ny * nz)
    occupied = set(grid.occupied)

    for _ in range(max(0, int(op.get("steps", 1)))):
        candidates = set(occupied)
        for ix, iy, iz in occupied:
            for dx, dy, dz in neigh:
                nx_, ny_, nz_ = ix + dx, iy + dy, iz + dz
                if 0 <= nx_ < nx and 0 <= ny_ < ny and 0 <= nz_ < nz:
                    candidates.add((nx_, ny_, nz_))

        next_occupied: set[Tuple[int, int, int]] = set(occupied) if mode in {"growth", "grow", "coral"} else set()
        for ix, iy, iz in candidates:
            count = sum((ix + dx, iy + dy, iz + dz) in occupied for dx, dy, dz in neigh)
            alive = (ix, iy, iz) in occupied
            if alive and count in survive:
                next_occupied.add((ix, iy, iz))
            elif not alive and count in birth:
                next_occupied.add((ix, iy, iz))

        occupied = next_occupied
        if max_fill > 0 and len(occupied) / total > max_fill:
            break

    return GridData(grid.size, grid.cell, grid.origin, occupied)


def _recipe_op_iterate(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    rule = str(op.get("rule", op.get("mode", ""))).strip().lower()
    source = _recipe_source_id(op, "target", "from", "grid", "curve", "curves")
    target = _recipe_output_id(op, source)
    steps = max(0, int(op.get("steps", 1)))
    if rule in {"cellular_automata", "cellular", "ca"}:
        if source not in ctx.grids:
            _recipe_warn(obj, f"iterate skipped missing grid target '{source}'")
            return
        if target:
            ctx.grids[target] = _recipe_step_cellular_automata(ctx.grids[source], op)
        return
    if rule not in {"differential_growth", "growth", "curve_growth"}:
        _recipe_warn(obj, f"iterate skipped unsupported rule '{rule}'")
        return
    if source not in ctx.curves:
        _recipe_warn(obj, f"iterate skipped missing curve target '{source}'")
        return

    grown: List[List[Vec3]] = []
    for curve in ctx.curves[source]:
        if len(curve) < 3:
            continue
        pts = list(curve)
        for _ in range(steps):
            pts = _differential_growth_step(pts, op)
        smooth_iterations = max(0, int(op.get("smooth_iterations", op.get("smooth", 0))))
        if smooth_iterations > 0:
            pts = _smooth_closed_polyline(pts, smooth_iterations, float(op.get("smooth_strength", 0.35)))
        grown.append(pts)
    if target and grown:
        ctx.curves[target] = grown


def _normal_from_points(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    d = math.sqrt(nx * nx + ny * ny + nz * nz)
    if d < 1e-9:
        return (0.0, 0.0, 1.0)
    return (nx / d, ny / d, nz / d)


def _recipe_panel_mesh(surface: SurfaceData, op: Dict[str, Any]) -> Mesh:
    scale = max(0.05, min(1.0, float(op.get("scale", op.get("panel_scale", 0.82)))))
    offset = float(op.get("offset", op.get("normal_offset", 0.0)))
    thickness = max(0.0, float(op.get("thickness", 0.0)))
    mesh = Mesh()

    for face in surface.mesh.faces:
        if len(face) < 3:
            continue
        pts = [surface.mesh.vertices[i - 1] for i in face if 1 <= i <= len(surface.mesh.vertices)]
        if len(pts) < 3:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        cz = sum(p[2] for p in pts) / len(pts)
        normal = _normal_from_points(pts[0], pts[1], pts[2])
        top = [
            (
                cx + (p[0] - cx) * scale + normal[0] * (offset + thickness * 0.5),
                cy + (p[1] - cy) * scale + normal[1] * (offset + thickness * 0.5),
                cz + (p[2] - cz) * scale + normal[2] * (offset + thickness * 0.5),
            )
            for p in pts
        ]
        base = len(mesh.vertices) + 1
        mesh.vertices.extend(top)
        mesh.faces.append([base + i for i in range(len(top))])
        if thickness <= 0:
            continue
        bottom = [
            (
                cx + (p[0] - cx) * scale + normal[0] * (offset - thickness * 0.5),
                cy + (p[1] - cy) * scale + normal[1] * (offset - thickness * 0.5),
                cz + (p[2] - cz) * scale + normal[2] * (offset - thickness * 0.5),
            )
            for p in pts
        ]
        bottom_base = len(mesh.vertices) + 1
        mesh.vertices.extend(bottom)
        mesh.faces.append([bottom_base + i for i in range(len(bottom) - 1, -1, -1)])
        for i in range(len(top)):
            j = (i + 1) % len(top)
            mesh.faces.append([base + i, base + j, bottom_base + j, bottom_base + i])
    return mesh


def _recipe_op_panelize_surface(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    source = _recipe_source_id(op, "surface", "from")
    target = _recipe_output_id(op, source)
    if source in ctx.surfaces and target:
        ctx.meshes[target] = _recipe_panel_mesh(ctx.surfaces[source], op)
    elif source:
        _recipe_warn(obj, f"panelize_surface skipped missing surface '{source}'")


def _grid_to_smooth_mesh(grid: GridData, resolution: float) -> Mesh:
    class GridSDF(SDFExpr):
        def __init__(self, g: GridData):
            self.g = g

        def dist(self, p: Vec3) -> float:
            px, py, pz = p
            gx = int(round((px - self.g.origin[0]) / self.g.cell))
            gy = int(round((py - self.g.origin[1]) / self.g.cell))
            gz = int(round((pz - self.g.origin[2]) / self.g.cell))
            min_dist = float("inf")
            for ix, iy, iz in self.g.occupied:
                cx = self.g.origin[0] + ix * self.g.cell
                cy = self.g.origin[1] + iy * self.g.cell
                cz = self.g.origin[2] + iz * self.g.cell
                dist = math.sqrt((px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2) - self.g.cell * 0.55
                if dist < min_dist:
                    min_dist = dist
            if min_dist == float("inf"):
                return self.g.cell
            if (gx, gy, gz) in self.g.occupied:
                return -abs(min_dist)
            return min_dist

    nx, ny, nz = grid.size
    pad = max(grid.cell * 2.0, resolution * 3.0)
    bounds = [
        [grid.origin[0] - pad, grid.origin[1] - pad, grid.origin[2] - pad],
        [grid.origin[0] + nx * grid.cell + pad, grid.origin[1] + ny * grid.cell + pad, grid.origin[2] + nz * grid.cell + pad],
    ]
    return sdf_to_marching_cubes_mesh(GridSDF(grid), bounds, max(1e-4, resolution))


def _recipe_op_emit_volume(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    source = _recipe_source_id(op, "grid", "from", "volume")
    if source not in ctx.grids:
        if source:
            _recipe_warn(obj, f"emit_volume skipped missing grid '{source}'")
        return
    grid = ctx.grids[source]
    method = str(op.get("method", "voxels")).strip().lower()
    if method in {"smooth", "marching_cubes", "marching", "mc"}:
        resolution = float(op.get("resolution", grid.cell * 0.75))
        mesh = _grid_to_smooth_mesh(grid, resolution)
    else:
        mesh = mesh_from_voxels(grid.occupied, grid.origin, grid.cell)
        if mesh.vertices:
            mesh = weld_vertices(mesh, epsilon=grid.cell * 0.001)
    ctx.emitted.extend(mesh)
    material_name = op.get("material")
    if material_name:
        obj.meta["material"] = str(material_name)


def _recipe_op_emit_mesh(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    source = _recipe_source_id(op, "mesh", "from", "panels")
    if source in ctx.meshes:
        ctx.emitted.extend(ctx.meshes[source])
        material_name = op.get("material")
        if material_name:
            obj.meta["material"] = str(material_name)
    elif source:
        _recipe_warn(obj, f"emit_mesh skipped missing mesh '{source}'")


def _recipe_op_emit_surface(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    source = _recipe_source_id(op, "surface", "from") or _recipe_output_id(op)
    if source in ctx.surfaces:
        data = ctx.surfaces[source]
        ctx.emitted.extend(data.mesh)
        rim_radius = float(op.get("rim_radius", op.get("edge_radius", 0.0)))
        if rim_radius > 0:
            sides = max(5, int(op.get("rim_segments", 8)))
            ctx.emitted.extend(_surface_boundary_tubes(data.mesh, data.u_segments, data.v_segments, rim_radius, sides))
        material_name = op.get("material")
        if material_name:
            obj.meta["material"] = str(material_name)
    elif source:
        _recipe_warn(obj, f"emit_surface skipped missing surface '{source}'")


def _recipe_op_emit_tubes(ctx: RecipeContext, obj: LiveObject, op: Dict[str, Any]) -> None:
    source = _recipe_source_id(op, "paths", "curves", "curve", "from")
    radius = float(op.get("radius", op.get("tube_radius", 0.025)))
    sides = max(5, int(op.get("segments", op.get("tube_segments", 8))))
    z_offset = float(op.get("z", 0.0))
    close_curves = metadata_flag(op.get("closed", op.get("close"))) is True
    if source in ctx.curves:
        for path in ctx.curves[source]:
            shifted = [(x, y, z + z_offset) for x, y, z in path]
            if close_curves and len(shifted) > 2:
                pairs = zip(shifted, shifted[1:] + [shifted[0]])
            else:
                pairs = zip(shifted, shifted[1:])
            for a, b in pairs:
                ctx.emitted.extend(tube_between(a, b, radius, sides))
        material_name = op.get("material")
        if material_name:
            obj.meta["material"] = str(material_name)
    elif source:
        _recipe_warn(obj, f"emit_tubes skipped missing paths '{source}'")


RECIPE_OP_HANDLERS = {
    "boundary": _recipe_op_boundary,
    "offset": _recipe_op_offset,
    "infill": _recipe_op_infill,
    "path_formula": _recipe_op_path_formula,
    "formula_path": _recipe_op_path_formula,
    "path_field": _recipe_op_path_formula,
    "curve": _recipe_op_curve,
    "points": _recipe_op_points,
    "field": _recipe_op_field,
    "vector_field": _recipe_op_field,
    "trace_field": _recipe_op_trace_field,
    "field_trace": _recipe_op_trace_field,
    "trace": _recipe_op_trace_field,
    "module": _recipe_op_module,
    "socket": _recipe_op_socket,
    "grid": _recipe_op_grid,
    "scatter": _recipe_op_scatter,
    "scatter_points": _recipe_op_scatter,
    "wfc": _recipe_op_wfc,
    "wave_function_collapse": _recipe_op_wfc,
    "surface_formula": _recipe_op_surface_formula,
    "formula_surface": _recipe_op_surface_formula,
    "ribbon_formula": _recipe_op_surface_formula,
    "ribbon": _recipe_op_surface_formula,
    "perforate_surface": _recipe_op_perforate_surface,
    "surface_perforation": _recipe_op_perforate_surface,
    "perforate": _recipe_op_perforate_surface,
    "iterate": _recipe_op_iterate,
    "panelize_surface": _recipe_op_panelize_surface,
    "panelize": _recipe_op_panelize_surface,
    "emit_surface": _recipe_op_emit_surface,
    "surface": _recipe_op_emit_surface,
    "emit_tubes": _recipe_op_emit_tubes,
    "tubes": _recipe_op_emit_tubes,
    "emit_volume": _recipe_op_emit_volume,
    "volume": _recipe_op_emit_volume,
    "instance": _recipe_op_instance,
    "instances": _recipe_op_instance,
    "emit_instances": _recipe_op_instance,
    "emit_mesh": _recipe_op_emit_mesh,
    "emit_panels": _recipe_op_emit_mesh,
}


def _recipe_param_env(obj: LiveObject) -> Dict[str, Any]:
    raw = obj.meta.get("params") or {}
    if not isinstance(raw, dict):
        return {}
    try:
        return assembly_params_eval_env(raw, {obj.name: obj})
    except Exception:
        return {str(k): v for k, v in raw.items() if isinstance(v, (int, float))}


def _recipe_resolve_op_value(value: Any, env: Dict[str, Any], obj: LiveObject) -> Any:
    if isinstance(value, str):
        try:
            return eval_mixed_value(value, env, {obj.name: obj})
        except Exception:
            return value
    if isinstance(value, list):
        return [_recipe_resolve_op_value(v, env, obj) for v in value]
    if isinstance(value, tuple):
        return tuple(_recipe_resolve_op_value(v, env, obj) for v in value)
    return value


def _recipe_resolve_op(op: Dict[str, Any], env: Dict[str, Any], obj: LiveObject) -> Dict[str, Any]:
    return {key: _recipe_resolve_op_value(value, env, obj) for key, value in op.items()}


def generate_recipe(obj: LiveObject, obn: Optional[Dict[str, LiveObject]] = None) -> Mesh:
    ctx = RecipeContext(obn=obn)
    env = _recipe_param_env(obj)
    for op in obj.recipe_ops:
        resolved_op = _recipe_resolve_op(op, env, obj)
        cmd = str(resolved_op.get("cmd", resolved_op.get("op", ""))).lower()
        handler = RECIPE_OP_HANDLERS.get(cmd)
        if handler is None:
            _recipe_warn(obj, f"skipped unsupported op '{cmd}'")
            continue
        handler(ctx, obj, resolved_op)
    return ctx.emitted


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


def _param_bool(params: Dict[str, Any], key: str, default: bool) -> bool:
    value = params.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _closed_polyline_length(points: List[Vec3]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        total += math.sqrt((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2)
    return total


def _coerce_point_list(raw: Any, z: float = 0.0) -> List[Vec3]:
    pts: List[Vec3] = []
    if not isinstance(raw, list):
        return pts
    for p in raw:
        if isinstance(p, list) and len(p) >= 2:
            pts.append((float(p[0]), float(p[1]), float(p[2]) if len(p) >= 3 else z))
        elif isinstance(p, tuple) and len(p) >= 2:
            pts.append((float(p[0]), float(p[1]), float(p[2]) if len(p) >= 3 else z))
    return pts


def _polyline_centroid(points: List[Vec3]) -> Vec3:
    if not points:
        return (0.0, 0.0, 0.0)
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
        sum(p[2] for p in points) / len(points),
    )


def _resample_closed_polyline(points: List[Vec3], count: int) -> List[Vec3]:
    if not points:
        return []
    count = max(3, int(count))
    perimeter = _closed_polyline_length(points)
    if perimeter < 1e-9:
        return [points[0] for _ in range(count)]

    targets = [perimeter * i / count for i in range(count)]
    result: List[Vec3] = []
    edge_index = 0
    travelled = 0.0
    for target in targets:
        while edge_index < len(points):
            p = points[edge_index]
            q = points[(edge_index + 1) % len(points)]
            edge_len = math.sqrt((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2)
            if travelled + edge_len >= target or edge_len < 1e-9:
                t = 0.0 if edge_len < 1e-9 else (target - travelled) / edge_len
                result.append((
                    p[0] + (q[0] - p[0]) * t,
                    p[1] + (q[1] - p[1]) * t,
                    p[2] + (q[2] - p[2]) * t,
                ))
                break
            travelled += edge_len
            edge_index += 1
    return result


def _rectangle_profile(width: float, depth: float, count: int) -> List[Vec3]:
    w = max(1e-6, width) * 0.5
    d = max(1e-6, depth) * 0.5
    corners: List[Vec3] = [(-w, -d, 0.0), (w, -d, 0.0), (w, d, 0.0), (-w, d, 0.0)]
    return _resample_closed_polyline(corners, count)


def _boundary_points_from_params(params: Dict[str, Any], z: float = 0.0) -> List[Vec3]:
    return _coerce_point_list(params.get("boundary_points", params.get("contour_points")), z)


def _initial_growth_profile(params: Dict[str, Any], rng: random.Random) -> List[Vec3]:
    profile = str(params.get("profile", "circle")).strip().lower()
    n = max(4, int(params.get("points", 48)))
    jitter = max(0.0, float(params.get("jitter", params.get("initial_jitter", 0.01))))

    if profile in {"rectangle", "rect", "square"}:
        width = float(params.get("width", params.get("radius", 0.5) * 2.0))
        depth = float(params.get("depth", params.get("radius", 0.5) * 2.0))
        pts = _rectangle_profile(width, depth, n)
    elif profile == "custom":
        raw = params.get("profile_points", params.get("points_profile", []))
        pts = []
        if isinstance(raw, list):
            for p in raw:
                if isinstance(p, list) and len(p) >= 2:
                    pts.append((float(p[0]), float(p[1]), float(p[2]) if len(p) >= 3 else 0.0))
        if len(pts) < 3:
            pts = _rectangle_profile(1.0, 1.0, n)
        else:
            pts = _resample_closed_polyline(pts, max(n, len(pts)))
    else:
        radius = float(params.get("radius", 0.5))
        pts = [
            (math.cos(2 * math.pi * i / n) * radius, math.sin(2 * math.pi * i / n) * radius, 0.0)
            for i in range(n)
        ]

    if jitter > 0:
        jittered = []
        for x, y, z in pts:
            length = math.sqrt(x * x + y * y) or 1.0
            amount = rng.uniform(-jitter, jitter)
            jittered.append((x + x / length * amount, y + y / length * amount, z))
        return jittered
    return pts


def _signed_area_xy(points: List[Vec3]) -> float:
    area = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        area += p[0] * q[1] - q[0] * p[1]
    return area * 0.5


def _differential_growth_step(points: List[Vec3], params: Dict[str, Any]) -> List[Vec3]:
    split_distance = float(params.get("split_distance", 0.16))
    repel_radius = float(params.get("repel_radius", 0.22))
    attraction = float(params.get("attraction", 0.03))
    repulsion = float(params.get("repulsion", 0.015))
    outward = float(params.get("outward", params.get("growth_rate", 0.0)))
    normal_pressure = float(params.get("normal_pressure", params.get("curve_pressure", 0.0)))
    max_points = int(params.get("max_points", 700))
    max_step_value = params.get("max_step")
    max_step = float(max_step_value) if max_step_value is not None else 0.0

    pts = points
    avg_edge_len = _closed_polyline_length(pts) / max(1, len(pts))
    if "repel_skip_neighbors" in params:
        repel_skip_neighbors = max(0, int(params.get("repel_skip_neighbors", 0)))
    else:
        repel_skip_neighbors = max(1, min(32, int(round(repel_radius / max(avg_edge_len, 1e-6) * 0.75))))
    forces = [[0.0, 0.0, 0.0] for _ in pts]
    cx = sum(p[0] for p in pts) / max(1, len(pts))
    cy = sum(p[1] for p in pts) / max(1, len(pts))
    area_sign = -1.0 if _signed_area_xy(pts) < 0 else 1.0

    for i, p in enumerate(pts):
        prev = pts[(i - 1) % len(pts)]
        nxt = pts[(i + 1) % len(pts)]
        forces[i][0] += (prev[0] + nxt[0] - 2 * p[0]) * attraction
        forces[i][1] += (prev[1] + nxt[1] - 2 * p[1]) * attraction
        if normal_pressure:
            tx, ty = nxt[0] - prev[0], nxt[1] - prev[1]
            tl = math.sqrt(tx * tx + ty * ty) + 1e-6
            nx, ny = area_sign * ty / tl, -area_sign * tx / tl
            forces[i][0] += nx * normal_pressure
            forces[i][1] += ny * normal_pressure
        if outward:
            dx, dy = p[0] - cx, p[1] - cy
            d = math.sqrt(dx * dx + dy * dy) + 1e-6
            forces[i][0] += dx / d * outward
            forces[i][1] += dy / d * outward

    cell_size = max(repel_radius, 1e-6)
    grid: Dict[Tuple[int, int, int], List[int]] = {}
    for i, p in enumerate(pts):
        key = (math.floor(p[0] / cell_size), math.floor(p[1] / cell_size), math.floor(p[2] / cell_size))
        grid.setdefault(key, []).append(i)

    for i, p in enumerate(pts):
        cx0, cy0, cz0 = math.floor(p[0] / cell_size), math.floor(p[1] / cell_size), math.floor(p[2] / cell_size)
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                for oz in (-1, 0, 1):
                    for j in grid.get((cx0 + ox, cy0 + oy, cz0 + oz), []):
                        if j <= i:
                            continue
                        ring_gap = abs(j - i)
                        ring_gap = min(ring_gap, len(pts) - ring_gap)
                        if ring_gap <= repel_skip_neighbors:
                            continue
                        dx, dy, dz = p[0] - pts[j][0], p[1] - pts[j][1], p[2] - pts[j][2]
                        d = math.sqrt(dx * dx + dy * dy + dz * dz) + 1e-6
                        if d < repel_radius:
                            mag = (repel_radius - d) / repel_radius * repulsion
                            fx, fy = dx / d * mag, dy / d * mag
                            forces[i][0] += fx
                            forces[i][1] += fy
                            forces[j][0] -= fx
                            forces[j][1] -= fy

    moved = []
    for i, p in enumerate(pts):
        fx, fy, fz = forces[i]
        if max_step > 0:
            length = math.sqrt(fx * fx + fy * fy + fz * fz)
            if length > max_step:
                scale = max_step / length
                fx, fy, fz = fx * scale, fy * scale, fz * scale
        moved.append((p[0] + fx, p[1] + fy, p[2] + fz))

    new_pts: List[Vec3] = []
    for i, p in enumerate(moved):
        q = moved[(i + 1) % len(moved)]
        new_pts.append(p)
        d = math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)
        if d > split_distance and len(moved) + len(new_pts) < max_points:
            new_pts.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, (p[2] + q[2]) / 2))
    return new_pts


def _smooth_closed_polyline(points: List[Vec3], iterations: int, strength: float = 0.5) -> List[Vec3]:
    out = list(points)
    strength = max(0.0, min(1.0, strength))
    for _ in range(max(0, iterations)):
        if len(out) < 3:
            return out
        smoothed = []
        for i, p in enumerate(out):
            prev = out[(i - 1) % len(out)]
            nxt = out[(i + 1) % len(out)]
            avg = ((prev[0] + nxt[0]) * 0.5, (prev[1] + nxt[1]) * 0.5, (prev[2] + nxt[2]) * 0.5)
            smoothed.append((
                p[0] * (1.0 - strength) + avg[0] * strength,
                p[1] * (1.0 - strength) + avg[1] * strength,
                p[2] * (1.0 - strength) + avg[2] * strength,
            ))
        out = smoothed
    return out


def _profile_outline_points(params: Dict[str, Any], count: int, z: float = 0.0, inset: float = 0.0) -> List[Vec3]:
    boundary_points = _boundary_points_from_params(params, z)
    if len(boundary_points) >= 3:
        pts = [(x, y, z) for x, y, _ in boundary_points]
        if inset > 0:
            cx, cy, _ = _polyline_centroid(pts)
            inset_pts: List[Vec3] = []
            for x, y, _ in pts:
                dx, dy = x - cx, y - cy
                d = math.sqrt(dx * dx + dy * dy) + 1e-6
                inset_pts.append((x - dx / d * inset, y - dy / d * inset, z))
            pts = inset_pts
        return _resample_closed_polyline(pts, count)

    profile = str(params.get("profile", "circle")).strip().lower()
    count = max(4, int(count))
    inset = max(0.0, float(inset))
    if profile in {"rectangle", "rect", "square"}:
        width = max(1e-6, float(params.get("width", params.get("radius", 0.5) * 2.0)) - inset * 2.0)
        depth = max(1e-6, float(params.get("depth", params.get("radius", 0.5) * 2.0)) - inset * 2.0)
        corner_radius = max(0.0, float(params.get("corner_radius", params.get("rounding", 0.0))) - inset)
        if corner_radius <= 1e-6:
            return [(x, y, z) for x, y, _ in _rectangle_profile(width, depth, count)]
        r = min(corner_radius, width * 0.5 - 1e-6, depth * 0.5 - 1e-6)
        hw = width * 0.5
        hd = depth * 0.5
        per_corner = max(3, count // 4)
        pts: List[Vec3] = []
        corners = [
            (hw - r, hd - r, 0.0, math.pi / 2.0),
            (-(hw - r), hd - r, math.pi / 2.0, math.pi),
            (-(hw - r), -(hd - r), math.pi, math.pi * 1.5),
            (hw - r, -(hd - r), math.pi * 1.5, math.pi * 2.0),
        ]
        for cx, cy, a0, a1 in corners:
            for i in range(per_corner):
                t = i / max(1, per_corner - 1)
                a = a0 + (a1 - a0) * t
                pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r, z))
        return _resample_closed_polyline(pts, count)
    if profile == "custom":
        raw = params.get("profile_points", params.get("points_profile", []))
        pts = []
        if isinstance(raw, list):
            for p in raw:
                if isinstance(p, list) and len(p) >= 2:
                    pts.append((float(p[0]), float(p[1]), z))
        if len(pts) >= 3:
            if inset > 0:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                inset_pts = []
                for x, y, _ in pts:
                    dx, dy = x - cx, y - cy
                    d = math.sqrt(dx * dx + dy * dy) + 1e-6
                    inset_pts.append((x - dx / d * inset, y - dy / d * inset, z))
                pts = inset_pts
            return _resample_closed_polyline(pts, count)
    radius = max(1e-6, float(params.get("radius", 0.5)) - inset)
    return [
        (math.cos(2 * math.pi * i / count) * radius, math.sin(2 * math.pi * i / count) * radius, z)
        for i in range(count)
    ]


def _smooth_open_polyline(points: List[Vec3], iterations: int) -> List[Vec3]:
    out = list(points)
    for _ in range(max(0, iterations)):
        if len(out) < 3:
            return out
        smoothed = [out[0]]
        for a, b in zip(out, out[1:]):
            smoothed.append((a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25, a[2] * 0.75 + b[2] * 0.25))
            smoothed.append((a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75, a[2] * 0.25 + b[2] * 0.75))
        smoothed.append(out[-1])
        out = smoothed
    return out


def _open_polyline_length(points: List[Vec3]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)
    return total


def _resample_open_polyline(points: List[Vec3], count: int) -> List[Vec3]:
    if len(points) <= 2:
        return list(points)
    count = max(2, int(count))
    total = _open_polyline_length(points)
    if total < 1e-9:
        return [points[0] for _ in range(count)]
    result = [points[0]]
    target_index = 1
    travelled = 0.0
    a = points[0]
    for b in points[1:]:
        segment = math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)
        while target_index < count - 1 and travelled + segment >= total * target_index / (count - 1):
            target = total * target_index / (count - 1)
            t = 0.0 if segment < 1e-9 else (target - travelled) / segment
            result.append((
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t,
            ))
            target_index += 1
        travelled += segment
        a = b
    result.append(points[-1])
    return result


def _point_in_polygon_2d(x: float, y: float, polygon: List[Vec3]) -> bool:
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi, _ = polygon[i]
        xj, yj, _ = polygon[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def _profile_outline_cached(params: Dict[str, Any], count: int, z: float, inset: float) -> List[Vec3]:
    raw_boundary = _boundary_points_from_params(params, z)
    if len(raw_boundary) >= 3 and params.get("boundary_samples") is None and params.get("contour_points_count") is None:
        count = len(raw_boundary)
    cache = params.get("_profile_outline_cache")
    if not isinstance(cache, dict):
        cache = {}
        params["_profile_outline_cache"] = cache
    key = (max(3, int(count)), round(float(z), 6), round(float(inset), 6))
    cached = cache.get(key)
    if isinstance(cached, list):
        return cached
    outline = _profile_outline_points(params, key[0], z, inset)
    cache[key] = outline
    return outline


def _point_inside_profile(params: Dict[str, Any], x: float, y: float, inset: float) -> bool:
    if len(_boundary_points_from_params(params)) >= 3:
        outline = _profile_outline_cached(params, max(32, int(params.get("section_points", 96))), 0.0, inset)
        return _point_in_polygon_2d(x, y, outline)

    profile = str(params.get("profile", "circle")).strip().lower()
    if profile in {"rectangle", "rect", "square"}:
        width = max(1e-6, float(params.get("width", params.get("radius", 0.5) * 2.0)) - inset * 2.0)
        depth = max(1e-6, float(params.get("depth", params.get("radius", 0.5) * 2.0)) - inset * 2.0)
        corner_radius = max(0.0, float(params.get("corner_radius", params.get("rounding", 0.0))) - inset)
        hw = width * 0.5
        hd = depth * 0.5
        if abs(x) > hw or abs(y) > hd:
            return False
        r = min(corner_radius, hw, hd)
        if r <= 1e-6:
            return True
        qx = abs(x) - (hw - r)
        qy = abs(y) - (hd - r)
        return max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2 <= r * r
    if profile == "custom":
        outline = _profile_outline_cached(params, max(32, int(params.get("section_points", 96))), 0.0, inset)
        return _point_in_polygon_2d(x, y, outline)
    radius = max(1e-6, float(params.get("radius", 0.5)) - inset)
    return x * x + y * y <= radius * radius


def _project_point_inside_profile(params: Dict[str, Any], point: Vec3, inset: float) -> Vec3:
    x, y, z = point
    if _point_inside_profile(params, x, y, inset):
        return point
    if len(_boundary_points_from_params(params)) >= 3:
        outline = _profile_outline_cached(params, max(32, int(params.get("section_points", 96))), 0.0, inset)
        cx = sum(p[0] for p in outline) / len(outline)
        cy = sum(p[1] for p in outline) / len(outline)
        lo, hi = 0.0, 1.0
        for _ in range(18):
            mid = (lo + hi) * 0.5
            tx = cx + (x - cx) * mid
            ty = cy + (y - cy) * mid
            if _point_in_polygon_2d(tx, ty, outline):
                lo = mid
            else:
                hi = mid
        return (cx + (x - cx) * lo, cy + (y - cy) * lo, z)

    profile = str(params.get("profile", "circle")).strip().lower()
    if profile in {"rectangle", "rect", "square"}:
        width = max(1e-6, float(params.get("width", params.get("radius", 0.5) * 2.0)) - inset * 2.0)
        depth = max(1e-6, float(params.get("depth", params.get("radius", 0.5) * 2.0)) - inset * 2.0)
        corner_radius = max(0.0, float(params.get("corner_radius", params.get("rounding", 0.0))) - inset)
        hw = width * 0.5
        hd = depth * 0.5
        r = min(corner_radius, hw, hd)
        if r <= 1e-6:
            return (max(-hw, min(hw, x)), max(-hd, min(hd, y)), z)
        clamped_x = max(-(hw - r), min(hw - r, x))
        clamped_y = max(-(hd - r), min(hd - r, y))
        dx, dy = x - clamped_x, y - clamped_y
        d = math.sqrt(dx * dx + dy * dy)
        if d <= r:
            return (max(-hw, min(hw, x)), max(-hd, min(hd, y)), z)
        return (clamped_x + dx / d * r, clamped_y + dy / d * r, z)
    if profile == "custom":
        outline = _profile_outline_cached(params, max(32, int(params.get("section_points", 96))), 0.0, inset)
        cx = sum(p[0] for p in outline) / len(outline)
        cy = sum(p[1] for p in outline) / len(outline)
        lo, hi = 0.0, 1.0
        for _ in range(18):
            mid = (lo + hi) * 0.5
            tx = cx + (x - cx) * mid
            ty = cy + (y - cy) * mid
            if _point_in_polygon_2d(tx, ty, outline):
                lo = mid
            else:
                hi = mid
        return (cx + (x - cx) * lo, cy + (y - cy) * lo, z)
    radius = max(1e-6, float(params.get("radius", 0.5)) - inset)
    d = math.sqrt(x * x + y * y)
    if d <= radius:
        return point
    return (x / d * radius, y / d * radius, z)


def _profile_bounds(points: List[Vec3]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def _serpentine_infill_path(params: Dict[str, Any], z: float, layer_index: int) -> List[Vec3]:
    thickness = float(params.get("thickness", params.get("section_thickness", 0.015)))
    repel_radius = float(params.get("repel_radius", 0.08))
    spacing = float(params.get("infill_spacing", max(thickness * 3.2, repel_radius)))
    wall_thickness = float(params.get("wall_thickness", max(thickness * 2.5, 0.035)))
    inset = float(params.get("infill_margin", wall_thickness + thickness * 1.7))
    smooth_iterations = int(params.get("path_smooth", params.get("smooth_path", 3)))
    sample_count = max(80, int(params.get("infill_resolution", 180)))
    max_path_points = max(24, int(params.get("max_path_points", 420)))
    wave_amplitude = float(params.get("wave_amplitude", spacing * 0.18))
    wave_frequency = float(params.get("wave_frequency", 1.25))

    outline = _profile_outline_points(params, max(64, int(params.get("section_points", 96))), 0.0, inset)
    min_x, max_x, min_y, max_y = _profile_bounds(outline)
    if max_x - min_x < spacing or max_y - min_y < spacing:
        return [(x, y, z) for x, y, _ in outline]

    row_count = max(2, int((max_y - min_y) / spacing) + 1)
    rows = [min_y + (max_y - min_y) * i / max(1, row_count - 1) for i in range(row_count)]
    points: List[Vec3] = []
    reverse = False
    phase = layer_index * 0.67 + float(params.get("phase", 0.0))

    for row_index, y in enumerate(rows):
        samples = []
        inside = False
        start_x = min_x
        last_x = min_x
        for i in range(sample_count + 1):
            x = min_x + (max_x - min_x) * i / sample_count
            ok = _point_inside_profile(params, x, y, inset)
            if ok and not inside:
                start_x = x
                inside = True
            if inside and (not ok or i == sample_count):
                end_x = last_x if not ok else x
                if end_x - start_x > spacing * 1.5:
                    samples.append((start_x, end_x))
                inside = False
            last_x = x
        if not samples:
            continue
        start_x, end_x = max(samples, key=lambda interval: interval[1] - interval[0])
        segment_points = max(8, int((end_x - start_x) / max(spacing * 0.55, 1e-6)))
        row_pts: List[Vec3] = []
        for i in range(segment_points + 1):
            t = i / max(1, segment_points)
            x = start_x + (end_x - start_x) * t
            yy = y + math.sin(t * math.pi * 2.0 * wave_frequency + phase + row_index * 0.55) * wave_amplitude
            if not _point_inside_profile(params, x, yy, inset):
                yy = y
            row_pts.append((x, yy, z))
        if reverse:
            row_pts.reverse()
        points.extend(row_pts)
        reverse = not reverse

    points = _smooth_open_polyline(points, smooth_iterations)
    if len(points) > max_path_points:
        points = _resample_open_polyline(points, max_path_points)
    return points


def _dist_sq(a: Vec3, b: Vec3) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _smooth_section_stack(
    sections: List[List[Vec3]],
    iterations: int,
    strength: float = 0.35,
    preserve_ends: bool = True,
) -> List[List[Vec3]]:
    if len(sections) < 3 or not sections[0] or iterations <= 0:
        return sections
    out = [[p for p in section] for section in sections]
    strength = max(0.0, min(1.0, strength))
    for _ in range(iterations):
        next_out = [[p for p in section] for section in out]
        start = 1 if preserve_ends else 0
        stop = len(out) - 1 if preserve_ends else len(out)
        for level in range(start, stop):
            prev_section = out[(level - 1) % len(out)]
            section = out[level]
            next_section = out[(level + 1) % len(out)]
            if len(prev_section) != len(section) or len(next_section) != len(section):
                continue
            smoothed: List[Vec3] = []
            for j, p in enumerate(section):
                avg_x = (prev_section[j][0] + next_section[j][0]) * 0.5
                avg_y = (prev_section[j][1] + next_section[j][1]) * 0.5
                # Keep each section's Z plane fixed; only fair sideways drift.
                smoothed.append((p[0] * (1.0 - strength) + avg_x * strength, p[1] * (1.0 - strength) + avg_y * strength, p[2]))
            next_out[level] = smoothed
        out = next_out
    return out


def _limit_section_delta(sections: List[List[Vec3]], max_delta: float) -> List[List[Vec3]]:
    if len(sections) < 2 or max_delta <= 0:
        return sections
    out = [[p for p in section] for section in sections]
    for level in range(1, len(out)):
        prev_section = out[level - 1]
        section = out[level]
        if len(prev_section) != len(section):
            continue
        limited: List[Vec3] = []
        for p, prev in zip(section, prev_section):
            dx = p[0] - prev[0]
            dy = p[1] - prev[1]
            d = math.sqrt(dx * dx + dy * dy)
            if d > max_delta:
                scale = max_delta / max(d, 1e-9)
                limited.append((prev[0] + dx * scale, prev[1] + dy * scale, p[2]))
            else:
                limited.append(p)
        out[level] = limited
    return out


def _add_section_loft(mesh: Mesh, sections: List[List[Vec3]], cap_ends: bool = False, triangulate: bool = False) -> None:
    if len(sections) < 2 or not sections[0]:
        return
    section_count = len(sections[0])
    base_index = len(mesh.vertices) + 1
    for section in sections:
        mesh.vertices.extend(section)
    for level in range(len(sections) - 1):
        row = base_index + level * section_count
        nxt = row + section_count
        for j in range(section_count):
            a_idx = row + j
            b_idx = row + (j + 1) % section_count
            c_idx = nxt + (j + 1) % section_count
            d_idx = nxt + j
            if not triangulate:
                mesh.faces.append([a_idx, b_idx, c_idx, d_idx])
                continue
            a = mesh.vertices[a_idx - 1]
            b = mesh.vertices[b_idx - 1]
            c = mesh.vertices[c_idx - 1]
            d = mesh.vertices[d_idx - 1]
            if _dist_sq(a, c) <= _dist_sq(b, d):
                mesh.faces.append([a_idx, b_idx, c_idx])
                mesh.faces.append([a_idx, c_idx, d_idx])
            else:
                mesh.faces.append([a_idx, b_idx, d_idx])
                mesh.faces.append([b_idx, c_idx, d_idx])
    if cap_ends:
        mesh.faces.append([base_index + i for i in range(section_count - 1, -1, -1)])
        top = base_index + (len(sections) - 1) * section_count
        mesh.faces.append([top + i for i in range(section_count)])


def _add_profile_wall(mesh: Mesh, params: Dict[str, Any], levels: int, z0: float, layer_height: float, section_count: int) -> None:
    outer_sections = [
        _profile_outline_points(params, section_count, z0 + i * layer_height, 0.0)
        for i in range(levels)
    ]
    _add_section_loft(mesh, outer_sections, False)

    wall_thickness = float(params.get("wall_thickness", 0.0))
    if wall_thickness <= 0:
        return
    inner_sections = [
        _profile_outline_points(params, section_count, z0 + i * layer_height, wall_thickness)
        for i in range(levels)
    ]
    inner_base = len(mesh.vertices) + 1
    for section in inner_sections:
        mesh.vertices.extend(section)
    for level in range(levels - 1):
        row = inner_base + level * section_count
        nxt = row + section_count
        for j in range(section_count):
            mesh.faces.append([row + j, nxt + j, nxt + (j + 1) % section_count, row + (j + 1) % section_count])
    outer_base = inner_base - levels * section_count
    top_outer = outer_base + (levels - 1) * section_count
    top_inner = inner_base + (levels - 1) * section_count
    bottom_outer = outer_base
    bottom_inner = inner_base
    for j in range(section_count):
        mesh.faces.append([top_outer + j, top_outer + (j + 1) % section_count, top_inner + (j + 1) % section_count, top_inner + j])
        mesh.faces.append([bottom_outer + j, bottom_inner + j, bottom_inner + (j + 1) % section_count, bottom_outer + (j + 1) % section_count])


def _scale_points_xy(points: List[Vec3], scale: float) -> List[Vec3]:
    cx = sum(p[0] for p in points) / max(1, len(points))
    cy = sum(p[1] for p in points) / max(1, len(points))
    return [(cx + (p[0] - cx) * scale, cy + (p[1] - cy) * scale, p[2]) for p in points]


def _align_closed_polyline_to_reference(points: List[Vec3], reference: List[Vec3]) -> List[Vec3]:
    if len(points) != len(reference) or len(points) < 4:
        return points
    count = len(points)
    stride = max(1, count // 80)
    best_shift = 0
    best_score = float("inf")
    for shift in range(count):
        score = 0.0
        for i in range(0, count, stride):
            p = points[(i + shift) % count]
            q = reference[i]
            dx = p[0] - q[0]
            dy = p[1] - q[1]
            score += dx * dx + dy * dy
        if score < best_score:
            best_score = score
            best_shift = shift
    if best_shift == 0:
        return points
    return points[best_shift:] + points[:best_shift]


def _nearest_profile_boundary_vector(params: Dict[str, Any], point: Vec3, boundary_inset: float) -> Tuple[float, float, float]:
    has_boundary_points = len(_boundary_points_from_params(params)) >= 3
    profile = str(params.get("profile", "circle")).strip().lower()
    x, y, _ = point
    if (not has_boundary_points) and profile in {"rectangle", "rect", "square"}:
        width = max(1e-6, float(params.get("width", params.get("radius", 0.5) * 2.0)) - boundary_inset * 2.0)
        depth = max(1e-6, float(params.get("depth", params.get("radius", 0.5) * 2.0)) - boundary_inset * 2.0)
        hw = width * 0.5
        hd = depth * 0.5
        distances = [
            (hw - x, -1.0, 0.0),
            (x + hw, 1.0, 0.0),
            (hd - y, 0.0, -1.0),
            (y + hd, 0.0, 1.0),
        ]
        dist, vx, vy = min(distances, key=lambda item: item[0])
        return (max(0.0, dist), vx, vy)
    if (not has_boundary_points) and profile not in {"custom"}:
        radius = max(1e-6, float(params.get("radius", 0.5)) - boundary_inset)
        d = math.sqrt(x * x + y * y)
        if d <= 1e-9:
            return (radius, 0.0, 0.0)
        return (max(0.0, radius - d), -x / d, -y / d)

    raw_boundary = _boundary_points_from_params(params)
    if len(raw_boundary) >= 3:
        outline_count = max(64, int(params.get("boundary_samples", params.get("section_points", 160))))
        outline = _profile_outline_cached(params, outline_count, 0.0, boundary_inset)
    else:
        outline_count = max(64, int(params.get("boundary_samples", params.get("section_points", 160))))
        outline = _profile_outline_cached(params, outline_count, 0.0, boundary_inset)
    if len(outline) < 2:
        return (float("inf"), 0.0, 0.0)
    best_dist_sq = float("inf")
    best_x = outline[0][0]
    best_y = outline[0][1]
    for i, a in enumerate(outline):
        b = outline[(i + 1) % len(outline)]
        ax, ay = a[0], a[1]
        bx, by = b[0], b[1]
        vx, vy = bx - ax, by - ay
        denom = vx * vx + vy * vy
        t = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / denom))
        px = ax + vx * t
        py = ay + vy * t
        dx = x - px
        dy = y - py
        dist_sq = dx * dx + dy * dy
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_x = px
            best_y = py
    dist = math.sqrt(best_dist_sq)
    if dist <= 1e-9:
        cx = sum(p[0] for p in outline) / len(outline)
        cy = sum(p[1] for p in outline) / len(outline)
        dx = cx - x
        dy = cy - y
        length = math.sqrt(dx * dx + dy * dy) + 1e-6
        return (0.0, dx / length, dy / length)
    return (dist, (x - best_x) / dist, (y - best_y) / dist)


def _vector_growth_candidate_is_clear(
    candidate: Vec3,
    points: List[Vec3],
    index: int,
    params: Dict[str, Any],
    boundary_inset: float,
    min_spacing: float,
    boundary_clearance: float,
    skip_neighbors: int,
    grid: Dict[Tuple[int, int], List[int]],
    cell_size: float,
) -> bool:
    if not _point_inside_profile(params, candidate[0], candidate[1], boundary_inset):
        return False
    boundary_dist, _, _ = _nearest_profile_boundary_vector(params, candidate, boundary_inset)
    if boundary_dist < boundary_clearance:
        return False
    min_spacing_sq = min_spacing * min_spacing
    count = len(points)
    cx = math.floor(candidate[0] / cell_size)
    cy = math.floor(candidate[1] / cell_size)
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            for j in grid.get((cx + ox, cy + oy), []):
                if j == index:
                    continue
                ring_gap = abs(j - index)
                ring_gap = min(ring_gap, count - ring_gap)
                if ring_gap <= skip_neighbors:
                    continue
                q = points[j]
                dx = candidate[0] - q[0]
                dy = candidate[1] - q[1]
                if dx * dx + dy * dy < min_spacing_sq:
                    return False
    return True


def _vector_growth_step(points: List[Vec3], params: Dict[str, Any], boundary_inset: float, step: int = 0) -> List[Vec3]:
    if len(points) < 4:
        return points
    target_spacing = max(1e-4, float(params.get("target_spacing", params.get("split_distance", 0.035))))
    step_size = float(params.get("vector_step", params.get("growth_step", target_spacing * 0.055)))
    ramp_steps = int(params.get("growth_ramp_steps", params.get("ramp_steps", 0)))
    if ramp_steps > 0:
        ramp_exponent = max(0.1, float(params.get("growth_ramp_exponent", 1.0)))
        step_size *= min(1.0, max(0.0, step / max(1, ramp_steps))) ** ramp_exponent
    if step_size <= 0:
        return points

    avg_edge_len = _closed_polyline_length(points) / max(1, len(points))
    skip_neighbors = int(params.get("repel_skip_neighbors", max(1, min(32, int(round(target_spacing / max(avg_edge_len, 1e-6) * 0.75))))))
    neighbor_radius = float(params.get("vector_neighbor_radius", params.get("neighbor_radius", target_spacing * 1.65)))
    min_spacing = float(params.get("collision_spacing", params.get("min_spacing", target_spacing * 0.72)))
    boundary_clearance = float(params.get("boundary_clearance", params.get("edge_clearance", target_spacing * 0.45)))
    boundary_avoid_radius = float(params.get("boundary_avoid_radius", target_spacing * 1.5))
    boundary_weight = float(params.get("boundary_weight", 1.35))
    neighbor_weight = float(params.get("neighbor_weight", 0.85))
    tension_weight = float(params.get("tension_weight", 0.18))
    direction = str(params.get("growth_direction", "outward")).strip().lower()
    direction_sign = -1.0 if direction in {"inward", "inside", "interior"} else 1.0
    area_sign = -1.0 if _signed_area_xy(points) < 0 else 1.0
    cell_size = max(neighbor_radius, min_spacing, boundary_clearance, 1e-6)
    grid: Dict[Tuple[int, int], List[int]] = {}
    for i, p in enumerate(points):
        key = (math.floor(p[0] / cell_size), math.floor(p[1] / cell_size))
        grid.setdefault(key, []).append(i)

    out: List[Vec3] = []
    count = len(points)
    for i, p in enumerate(points):
        prev = points[(i - 1) % count]
        nxt = points[(i + 1) % count]
        tx, ty = nxt[0] - prev[0], nxt[1] - prev[1]
        tangent_len = math.sqrt(tx * tx + ty * ty) + 1e-6
        nx = area_sign * ty / tangent_len * direction_sign
        ny = -area_sign * tx / tangent_len * direction_sign
        vx = nx
        vy = ny

        # Mild curve fairing keeps the path smooth without a physical relaxation jump.
        vx += (prev[0] + nxt[0] - 2.0 * p[0]) / max(target_spacing, 1e-6) * tension_weight
        vy += (prev[1] + nxt[1] - 2.0 * p[1]) / max(target_spacing, 1e-6) * tension_weight

        boundary_dist, bx, by = _nearest_profile_boundary_vector(params, p, boundary_inset)
        if boundary_dist < boundary_avoid_radius:
            strength = (1.0 - boundary_dist / max(boundary_avoid_radius, 1e-6)) ** 2
            vx += bx * strength * boundary_weight
            vy += by * strength * boundary_weight

        cx = math.floor(p[0] / cell_size)
        cy = math.floor(p[1] / cell_size)
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                for j in grid.get((cx + ox, cy + oy), []):
                    if j == i:
                        continue
                    ring_gap = abs(j - i)
                    ring_gap = min(ring_gap, count - ring_gap)
                    if ring_gap <= skip_neighbors:
                        continue
                    q = points[j]
                    dx = p[0] - q[0]
                    dy = p[1] - q[1]
                    d = math.sqrt(dx * dx + dy * dy) + 1e-6
                    if d < neighbor_radius:
                        strength = (1.0 - d / max(neighbor_radius, 1e-6)) ** 2
                        vx += dx / d * strength * neighbor_weight
                        vy += dy / d * strength * neighbor_weight

        length = math.sqrt(vx * vx + vy * vy)
        if length <= 1e-9:
            out.append(p)
            continue

        accepted = p
        ux, uy = vx / length, vy / length
        for scale in (1.0, 0.5, 0.25, 0.125, 0.0625):
            candidate = (p[0] + ux * step_size * scale, p[1] + uy * step_size * scale, p[2])
            candidate = _project_point_inside_profile(params, candidate, boundary_inset)
            if _vector_growth_candidate_is_clear(candidate, points, i, params, boundary_inset, min_spacing, boundary_clearance, skip_neighbors, grid, cell_size):
                accepted = candidate
                break
        out.append(accepted)

    smooth_each_step = int(params.get("vector_smooth", params.get("growth_smooth", 1)))
    if smooth_each_step > 0:
        smooth_strength = float(params.get("vector_smooth_strength", params.get("smooth_strength", 0.22)))
        out = _smooth_closed_polyline(out, smooth_each_step, smooth_strength)
        out = [_project_point_inside_profile(params, p, boundary_inset) for p in out]
    return out


def _limit_vec2(x: float, y: float, limit: float) -> Tuple[float, float]:
    length = math.sqrt(x * x + y * y)
    if limit <= 0 or length <= limit or length <= 1e-9:
        return (x, y)
    scale = limit / length
    return (x * scale, y * scale)


def _random_unit_vec2(rng: random.Random) -> Tuple[float, float]:
    angle = rng.random() * math.tau
    return (math.cos(angle), math.sin(angle))


def _node_growth_grid(points: List[Vec3], cell_size: float) -> Dict[Tuple[int, int], List[int]]:
    grid: Dict[Tuple[int, int], List[int]] = {}
    for i, p in enumerate(points):
        key = (math.floor(p[0] / cell_size), math.floor(p[1] / cell_size))
        grid.setdefault(key, []).append(i)
    return grid


def _node_growth_neighbors(point: Vec3, grid: Dict[Tuple[int, int], List[int]], cell_size: float) -> List[int]:
    cx = math.floor(point[0] / cell_size)
    cy = math.floor(point[1] / cell_size)
    out: List[int] = []
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            out.extend(grid.get((cx + ox, cy + oy), []))
    return out


def _p5_node_growth_step(
    points: List[Vec3],
    velocities: List[Tuple[float, float]],
    max_speeds: List[float],
    max_forces: List[float],
    params: Dict[str, Any],
    boundary_inset: float,
    rng: random.Random,
) -> Tuple[List[Vec3], List[Tuple[float, float]], List[float], List[float]]:
    if len(points) < 3:
        return points, velocities, max_speeds, max_forces

    target_spacing = max(1e-4, float(params.get("target_spacing", params.get("split_distance", 0.035))))
    min_separation = float(params.get("min_separation", params.get("separation_distance", target_spacing * 1.15)))
    neighbor_dist = float(params.get("neighbor_dist", params.get("cohesion_distance", target_spacing * 3.0)))
    separate_weight = float(params.get("separate_weight", params.get("separation_weight", 1.5)))
    cohesion_weight = float(params.get("cohesion_weight", 0.25))
    max_speed_default = float(params.get("max_speed", params.get("node_max_speed", target_spacing * 0.16)))
    max_force_default = float(params.get("max_force", params.get("node_max_force", max_speed_default * 1.25)))
    max_edge_length = float(params.get("max_edge_length", params.get("split_distance", target_spacing * 1.22)))
    max_nodes = max(3, int(params.get("max_nodes", params.get("max_points", 500))))
    boundary_clearance = float(params.get("boundary_clearance", params.get("edge_clearance", target_spacing * 0.45)))
    boundary_dist = float(params.get("boundary_avoid_distance", params.get("boundary_avoid_radius", target_spacing * 2.0)))
    boundary_weight = float(params.get("boundary_weight", 1.2))
    allow_boundary_slide = _param_bool(params, "allow_boundary_slide", True)

    cell_size = max(min_separation, neighbor_dist, boundary_dist, 1e-6)
    grid = _node_growth_grid(points, cell_size)
    next_points: List[Vec3] = []
    next_velocities: List[Tuple[float, float]] = []

    for i, p in enumerate(points):
        vx, vy = velocities[i] if i < len(velocities) else _random_unit_vec2(rng)
        max_speed = max_speeds[i] if i < len(max_speeds) else max_speed_default
        max_force = max_forces[i] if i < len(max_forces) else max_force_default

        sep_x = 0.0
        sep_y = 0.0
        coh_x = 0.0
        coh_y = 0.0
        coh_count = 0
        for j in _node_growth_neighbors(p, grid, cell_size):
            if j == i:
                continue
            q = points[j]
            dx = p[0] - q[0]
            dy = p[1] - q[1]
            d = math.sqrt(dx * dx + dy * dy) + 1e-6
            if d < min_separation:
                sep_x += dx / (d * d)
                sep_y += dy / (d * d)
            if d < neighbor_dist:
                coh_x += q[0]
                coh_y += q[1]
                coh_count += 1

        if sep_x * sep_x + sep_y * sep_y > 1e-12:
            sep_len = math.sqrt(sep_x * sep_x + sep_y * sep_y)
            sep_x = sep_x / sep_len * max_speed - vx
            sep_y = sep_y / sep_len * max_speed - vy
            sep_x, sep_y = _limit_vec2(sep_x, sep_y, max_force)

        if coh_count > 0:
            coh_x = coh_x / coh_count - p[0]
            coh_y = coh_y / coh_count - p[1]
            coh_len = math.sqrt(coh_x * coh_x + coh_y * coh_y)
            if coh_len > 1e-9:
                coh_x = coh_x / coh_len * max_speed - vx
                coh_y = coh_y / coh_len * max_speed - vy
                coh_x, coh_y = _limit_vec2(coh_x, coh_y, max_force)
            else:
                coh_x = 0.0
                coh_y = 0.0

        force_x = sep_x * separate_weight + coh_x * cohesion_weight
        force_y = sep_y * separate_weight + coh_y * cohesion_weight

        dist_to_boundary, bx, by = _nearest_profile_boundary_vector(params, p, boundary_inset)
        if dist_to_boundary < boundary_dist:
            strength = (1.0 - dist_to_boundary / max(boundary_dist, 1e-6)) ** 2
            force_x += bx * max_force * boundary_weight * strength
            force_y += by * max_force * boundary_weight * strength

        nvx, nvy = _limit_vec2(vx + force_x, vy + force_y, max_speed)
        candidate = (p[0] + nvx, p[1] + nvy, p[2])
        if not _point_inside_profile(params, candidate[0], candidate[1], boundary_inset):
            if allow_boundary_slide:
                candidate = _project_point_inside_profile(params, candidate, boundary_inset + boundary_clearance)
                nvx = candidate[0] - p[0]
                nvy = candidate[1] - p[1]
            else:
                candidate = p
                nvx = 0.0
                nvy = 0.0
        else:
            candidate_dist, _, _ = _nearest_profile_boundary_vector(params, candidate, boundary_inset)
            if candidate_dist < boundary_clearance:
                candidate = p
                nvx = 0.0
                nvy = 0.0
        next_points.append(candidate)
        next_velocities.append((nvx, nvy))

    grown_points: List[Vec3] = []
    grown_velocities: List[Tuple[float, float]] = []
    grown_speeds: List[float] = []
    grown_forces: List[float] = []
    for i, p in enumerate(next_points):
        j = (i + 1) % len(next_points)
        q = next_points[j]
        grown_points.append(p)
        grown_velocities.append(next_velocities[i])
        grown_speeds.append(max_speeds[i] if i < len(max_speeds) else max_speed_default)
        grown_forces.append(max_forces[i] if i < len(max_forces) else max_force_default)
        d = math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)
        if d > max_edge_length and len(grown_points) < max_nodes:
            mx = (p[0] + q[0]) * 0.5
            my = (p[1] + q[1]) * 0.5
            mz = (p[2] + q[2]) * 0.5
            rvx, rvy = _random_unit_vec2(rng)
            speed = ((max_speeds[i] if i < len(max_speeds) else max_speed_default) + (max_speeds[j] if j < len(max_speeds) else max_speed_default)) * 0.5
            force = ((max_forces[i] if i < len(max_forces) else max_force_default) + (max_forces[j] if j < len(max_forces) else max_force_default)) * 0.5
            grown_points.append((mx, my, mz))
            grown_velocities.append((rvx * speed, rvy * speed))
            grown_speeds.append(speed)
            grown_forces.append(force)

    return grown_points, grown_velocities, grown_speeds, grown_forces


def _contour_points_from_object(ref_name: str, obn: Optional[Dict[str, LiveObject]], count: int) -> List[Vec3]:
    if not ref_name or not obn:
        return []
    contour_obj = obn.get(ref_name)
    if contour_obj is None:
        return []
    params = contour_obj.meta.get("params", {}) or {}
    raw = params.get("boundary_points", params.get("contour_points", params.get("profile_points", params.get("points"))))
    pts = _coerce_point_list(raw)
    if pts:
        transform = contour_obj.meta.get("transform")
        if isinstance(transform, dict):
            pts = [apply_transform_to_point(p, transform) for p in pts]
        if count > 0:
            return _resample_closed_polyline(pts, max(3, count))
        return pts
    if contour_obj.mesh and contour_obj.mesh.vertices:
        if count > 0:
            return _resample_closed_polyline(contour_obj.mesh.vertices, max(3, count))
        return contour_obj.mesh.vertices
    return []


def _apply_contour_reference_params(params: Dict[str, Any], obn: Optional[Dict[str, LiveObject]]) -> Dict[str, Any]:
    ref = params.get("contour", params.get("boundary_object", params.get("contour_object")))
    if not ref:
        return params
    # Keep explicit contour objects lightweight by default. A rectangle contour
    # should stay four boundary edges for containment math; section_points is a
    # loft/rendering detail and should not silently turn the boundary into
    # hundreds of collision segments.
    contour_count = 0
    if params.get("contour_points_count") is not None or params.get("boundary_samples") is not None:
        contour_count = max(16, int(params.get("contour_points_count", params.get("boundary_samples", 160))))
    pts = _contour_points_from_object(str(ref), obn, contour_count)
    if len(pts) < 3:
        return params
    out = dict(params)
    out["boundary_points"] = [[x, y, z] for x, y, z in pts]
    cx, cy, cz = _polyline_centroid(pts)
    out.setdefault("boundary_center", [cx, cy, cz])
    return out


def _apply_growth_curl(points: List[Vec3], params: Dict[str, Any], boundary_inset: float, step: int) -> List[Vec3]:
    curl_strength = float(params.get("curl_strength", params.get("curviness", 0.0)))
    if curl_strength <= 0 or len(points) < 4:
        return points

    spacing = float(params.get("target_spacing", params.get("split_distance", 0.035)))
    frequency = float(params.get("curl_frequency", max(3.0, len(points) / 18.0)))
    phase_speed = float(params.get("curl_phase_speed", 0.12))
    amount = curl_strength * spacing
    center_x = sum(p[0] for p in points) / len(points)
    center_y = sum(p[1] for p in points) / len(points)

    curled: List[Vec3] = []
    for i, p in enumerate(points):
        prev = points[(i - 1) % len(points)]
        nxt = points[(i + 1) % len(points)]
        tx, ty = nxt[0] - prev[0], nxt[1] - prev[1]
        length = math.sqrt(tx * tx + ty * ty) + 1e-6
        nx, ny = -ty / length, tx / length
        # Keep the normal facing consistently relative to the profile center so the
        # sinusoid creates alternating inward/outward lobes instead of drifting.
        radial_x, radial_y = p[0] - center_x, p[1] - center_y
        if nx * radial_x + ny * radial_y < 0:
            nx, ny = -nx, -ny
        wave = math.sin((i / max(1, len(points))) * math.tau * frequency + step * phase_speed)
        curled.append(_project_point_inside_profile(params, (p[0] + nx * wave * amount, p[1] + ny * wave * amount, p[2]), boundary_inset))
    return curled


def _constrained_growth_step(points: List[Vec3], params: Dict[str, Any], boundary_inset: float, step: int = 0) -> List[Vec3]:
    local_params = dict(params)
    target_spacing_value = local_params.get("target_spacing")
    if target_spacing_value is not None:
        target_spacing = max(1e-4, float(target_spacing_value))
        local_params.setdefault("split_distance", target_spacing * 1.18)
        local_params.setdefault("repel_radius", target_spacing * 1.55)
        local_params.setdefault("max_step", target_spacing * 0.18)
        local_params.setdefault("attraction", 0.055)
        local_params.setdefault("repulsion", 0.006)
    if "normal_pressure" not in local_params and "curve_pressure" not in local_params:
        pressure = float(local_params.get("growth_pressure", 0.55))
        spacing = float(local_params.get("target_spacing", local_params.get("split_distance", 0.035)))
        local_params["normal_pressure"] = max(0.0, pressure) * spacing * 0.10
    direction = str(local_params.get("growth_direction", "outward")).strip().lower()
    normal_pressure = float(local_params.get("normal_pressure", local_params.get("curve_pressure", 0.0)))
    if direction in {"inward", "inside", "interior"}:
        normal_pressure = -abs(normal_pressure)
    elif direction in {"outward", "outside", "exterior"}:
        normal_pressure = abs(normal_pressure)
    ramp_steps = int(local_params.get("growth_ramp_steps", local_params.get("ramp_steps", 0)))
    ramp = 1.0
    if ramp_steps > 0:
        ramp_exponent = max(0.1, float(local_params.get("growth_ramp_exponent", 1.0)))
        ramp = min(1.0, max(0.0, step / max(1, ramp_steps))) ** ramp_exponent
        normal_pressure *= ramp
    local_params["normal_pressure"] = normal_pressure
    repulsion_ramp_steps = int(local_params.get("repulsion_ramp_steps", local_params.get("force_ramp_steps", ramp_steps)))
    if repulsion_ramp_steps > 0:
        repulsion_ramp_exponent = max(0.1, float(local_params.get("repulsion_ramp_exponent", local_params.get("growth_ramp_exponent", 1.0))))
        repulsion_ramp = min(1.0, max(0.0, step / max(1, repulsion_ramp_steps))) ** repulsion_ramp_exponent
        local_params["repulsion"] = float(local_params.get("repulsion", 0.015)) * repulsion_ramp
    if "outward" not in local_params and "growth_rate" not in local_params:
        local_params["outward"] = 0.0
    next_points = _differential_growth_step(points, local_params)
    projected = [_project_point_inside_profile(params, p, boundary_inset) for p in next_points]
    projected = _apply_growth_curl(projected, params, boundary_inset, step)
    smooth_each_step = int(params.get("smooth_each_step", params.get("growth_smooth", 1)))
    smooth_strength = float(params.get("smooth_strength", 0.35))
    if smooth_each_step > 0:
        projected = _smooth_closed_polyline(projected, smooth_each_step, smooth_strength)
        projected = [_project_point_inside_profile(params, p, boundary_inset) for p in projected]
    return projected


def differential_growth_constrained_stack_mesh(params: Dict[str, Any], obn: Optional[Dict[str, LiveObject]] = None) -> Mesh:
    params = dict(params)
    params = _apply_contour_reference_params(params, obn)
    growth_solver = str(params.get("growth_solver", params.get("solver", "force"))).strip().lower()
    unified_points = params.get("curve_points", params.get("profile_resolution", params.get("resolution")))
    if unified_points is not None:
        point_count = max(8, int(unified_points))
        params["section_points"] = point_count
        if growth_solver in {"node", "p5", "p5_node", "differential_node"}:
            params.setdefault("points", int(params.get("nodes_start", params.get("initial_nodes", 10))))
            params.setdefault("max_points", int(params.get("max_nodes", 500)))
        else:
            params["points"] = point_count
            params.setdefault("max_points", max(point_count, int(point_count * 1.45)))
    elif "points" in params:
        params["section_points"] = max(8, int(params.get("points", 160)))

    target_spacing_value = params.get("target_spacing")
    if target_spacing_value is not None:
        target_spacing = max(1e-4, float(target_spacing_value))
        params.setdefault("split_distance", target_spacing * 1.18)
        params.setdefault("repel_radius", target_spacing * 1.55)
        params.setdefault("max_step", target_spacing * 0.18)
        params.setdefault("section_points", max(96, min(220, int(round(_closed_polyline_length(_profile_outline_points(params, 96)) / target_spacing * 1.15)))))
        params.setdefault("max_points", max(240, min(720, int(round(_closed_polyline_length(_profile_outline_points(params, 96)) / target_spacing * 6.0)))))

    rng = random.Random(int(params.get("seed", 1)))
    steps = max(0, int(params.get("steps", 120)))
    sample_every = max(1, int(params.get("sample_every", params.get("section_every", 10))))
    section_count = max(8, int(params.get("section_points", 160)))
    thickness = float(params.get("thickness", params.get("section_thickness", 0.015)))
    tube_segments = max(6, int(params.get("tube_segments", 10)))
    make_surface = _param_bool(params, "loft", _param_bool(params, "surface", True))
    show_sections = _param_bool(params, "show_sections", True)
    cap_ends = _param_bool(params, "cap_ends", False)
    boundary_inset = float(params.get("boundary_margin", params.get("infill_margin", max(thickness * 1.75, 0.015))))
    seed_scale = float(params.get("seed_scale", params.get("infill_seed_scale", 0.28)))
    seed_scale = max(0.05, min(0.98, seed_scale))
    max_points = int(params.get("max_points", max(section_count, 900)))
    show_seed_section = _param_bool(params, "show_seed_section", _param_bool(params, "show_initial_section", False))
    progressive = _param_bool(params, "progressive", show_seed_section)
    fixed_point_count = _param_bool(params, "fixed_point_count", progressive)
    warmup_steps = max(0, int(params.get("warmup_steps", params.get("start_after_steps", params.get("skip_initial_steps", 0)))))
    if progressive:
        warmup_steps = 0

    seed_params = dict(params)
    seed_params["jitter"] = params.get("jitter", 0.0)
    pts = _scale_points_xy(_initial_growth_profile(seed_params, rng), seed_scale)
    seed_center = params.get("seed_center", params.get("boundary_center"))
    if isinstance(seed_center, list) and len(seed_center) >= 2:
        cx = sum(p[0] for p in pts) / max(1, len(pts))
        cy = sum(p[1] for p in pts) / max(1, len(pts))
        cz = sum(p[2] for p in pts) / max(1, len(pts))
        sx, sy, sz = float(seed_center[0]), float(seed_center[1]), float(seed_center[2]) if len(seed_center) >= 3 else 0.0
        pts = [(x + sx - cx, y + sy - cy, z + sz - cz) for x, y, z in pts]
    pts = [_project_point_inside_profile(params, p, boundary_inset) for p in pts]
    seed_smooth = max(0, int(params.get("seed_smooth", params.get("initial_smooth", 2))))
    if seed_smooth > 0:
        seed_smooth_strength = float(params.get("seed_smooth_strength", params.get("initial_smooth_strength", 0.35)))
        pts = _smooth_closed_polyline(pts, seed_smooth, seed_smooth_strength)
        pts = [_project_point_inside_profile(params, p, boundary_inset) for p in pts]
    if fixed_point_count and growth_solver not in {"node", "p5", "p5_node", "differential_node"}:
        pts = _resample_closed_polyline(pts, section_count)

    snapshots: List[List[Vec3]] = []
    if show_seed_section:
        snapshots.append(list(pts))

    velocities: List[Tuple[float, float]] = []
    max_speeds: List[float] = []
    max_forces: List[float] = []
    if growth_solver in {"node", "p5", "p5_node", "differential_node"}:
        target_spacing = max(1e-4, float(params.get("target_spacing", params.get("split_distance", 0.035))))
        default_speed = float(params.get("max_speed", params.get("node_max_speed", target_spacing * 0.16)))
        default_force = float(params.get("max_force", params.get("node_max_force", default_speed * 1.25)))
        velocities = []
        for _ in pts:
            ux, uy = _random_unit_vec2(rng)
            velocities.append((ux * default_speed, uy * default_speed))
        max_speeds = [default_speed for _ in pts]
        max_forces = [default_force for _ in pts]

    for warmup_step in range(1, warmup_steps + 1):
        step_params = dict(params)
        step_params["max_points"] = max_points
        if growth_solver in {"node", "p5", "p5_node", "differential_node"}:
            pts, velocities, max_speeds, max_forces = _p5_node_growth_step(pts, velocities, max_speeds, max_forces, step_params, boundary_inset, rng)
        elif growth_solver in {"vector", "step", "incremental", "conservative"}:
            pts = _vector_growth_step(pts, step_params, boundary_inset, warmup_step)
        else:
            pts = _constrained_growth_step(pts, step_params, boundary_inset, warmup_step)
        if fixed_point_count and growth_solver not in {"node", "p5", "p5_node", "differential_node"}:
            pts = _resample_closed_polyline(pts, section_count)

    if (not show_seed_section) or warmup_steps > 0:
        snapshots.append(list(pts))
    for step in range(1, steps + 1):
        step_params = dict(params)
        step_params["max_points"] = max_points
        if growth_solver in {"node", "p5", "p5_node", "differential_node"}:
            pts, velocities, max_speeds, max_forces = _p5_node_growth_step(pts, velocities, max_speeds, max_forces, step_params, boundary_inset, rng)
        elif growth_solver in {"vector", "step", "incremental", "conservative"}:
            pts = _vector_growth_step(pts, step_params, boundary_inset, warmup_steps + step)
        else:
            pts = _constrained_growth_step(pts, step_params, boundary_inset, warmup_steps + step)
        if fixed_point_count and growth_solver not in {"node", "p5", "p5_node", "differential_node"}:
            pts = _resample_closed_polyline(pts, section_count)
        if step % sample_every == 0 or step == steps:
            snapshots.append(list(pts))

    if len(snapshots) < 2:
        snapshots.append(list(pts))

    height = params.get("height")
    if height is not None:
        layer_height = float(height) / max(1, len(snapshots) - 1)
    else:
        layer_height = float(params.get("layer_height", 0.05))
    z0 = float(params.get("start_z", 0.0))

    section_smooth = int(params.get("section_smooth", 2))
    section_smooth_strength = float(params.get("section_smooth_strength", 0.32))
    sections: List[List[Vec3]] = []
    previous_section: Optional[List[Vec3]] = None
    for i, section in enumerate(snapshots):
        z = z0 + i * layer_height
        resampled = _resample_closed_polyline(section, section_count)
        if section_smooth > 0:
            resampled = _smooth_closed_polyline(resampled, section_smooth, section_smooth_strength)
        next_section = [_project_point_inside_profile(params, (x, y, z), boundary_inset) for x, y, _ in resampled]
        if previous_section is not None:
            next_section = _align_closed_polyline_to_reference(next_section, previous_section)
        sections.append(next_section)
        previous_section = next_section

    max_section_delta = float(params.get("max_section_delta", params.get("loft_max_delta", 0.0)))
    if max_section_delta > 0:
        sections = _limit_section_delta(sections, max_section_delta)
    vertical_smooth = int(params.get("vertical_smooth", params.get("loft_smooth", 0)))
    if vertical_smooth > 0:
        vertical_strength = float(params.get("vertical_smooth_strength", params.get("loft_smooth_strength", 0.35)))
        sections = _smooth_section_stack(sections, vertical_smooth, vertical_strength, _param_bool(params, "preserve_ends", True))

    mesh = Mesh()
    if make_surface and len(sections) >= 2:
        triangulate_loft = _param_bool(params, "triangulate_loft", _param_bool(params, "loft_triangles", False))
        _add_section_loft(mesh, sections, cap_ends, triangulate_loft)

    if show_sections and thickness > 0:
        for section in sections:
            for i, p in enumerate(section):
                mesh.extend(tube_between(p, section[(i + 1) % len(section)], thickness, tube_segments))

    return mesh


def differential_growth_infill_stack_mesh(params: Dict[str, Any]) -> Mesh:
    steps = max(0, int(params.get("steps", 120)))
    sample_every = max(1, int(params.get("sample_every", params.get("section_every", 10))))
    section_count = max(16, int(params.get("section_points", 128)))
    thickness = float(params.get("thickness", params.get("section_thickness", 0.015)))
    tube_segments = max(6, int(params.get("tube_segments", 10)))
    make_wall = _param_bool(params, "loft", _param_bool(params, "surface", True))
    show_infill = _param_bool(params, "show_infill", True)
    layer_stride = max(1, int(params.get("infill_layer_stride", params.get("visible_every", 1))))

    layers = max(2, steps // sample_every + 1)
    if steps % sample_every:
        layers += 1
    height = params.get("height")
    if height is not None:
        layer_height = float(height) / max(1, layers - 1)
    else:
        layer_height = float(params.get("layer_height", 0.05))
    z0 = float(params.get("start_z", 0.0))

    mesh = Mesh()
    if make_wall:
        _add_profile_wall(mesh, params, layers, z0, layer_height, section_count)

    if show_infill and thickness > 0:
        for layer_index in range(layers):
            if layer_index % layer_stride != 0 and layer_index != layers - 1:
                continue
            z = z0 + layer_index * layer_height
            path = _serpentine_infill_path(params, z, layer_index)
            for a, b in zip(path, path[1:]):
                mesh.extend(tube_between(a, b, thickness, tube_segments))

    return mesh


def _radial_scaled_section(section: List[Vec3], offset: float) -> List[Vec3]:
    if not section:
        return []
    cx = sum(p[0] for p in section) / len(section)
    cy = sum(p[1] for p in section) / len(section)
    out: List[Vec3] = []
    for x, y, z in section:
        dx, dy = x - cx, y - cy
        d = math.sqrt(dx * dx + dy * dy) + 1e-6
        out.append((x + dx / d * offset, y + dy / d * offset, z))
    return out


def _pleat_section(params: Dict[str, Any], count: int, z: float, t: float) -> List[Vec3]:
    base = _profile_outline_points(params, count, z, 0.0)
    cx = sum(p[0] for p in base) / len(base)
    cy = sum(p[1] for p in base) / len(base)
    amplitude = float(params.get("pleat_amplitude", params.get("curl_amplitude", 0.045)))
    frequency = float(params.get("pleat_frequency", params.get("curl_frequency", 10.0)))
    phase = float(params.get("phase", 0.0)) + math.tau * float(params.get("twist", 0.0)) * t
    secondary_amp = float(params.get("secondary_amplitude", amplitude * 0.22))
    secondary_freq = float(params.get("secondary_frequency", frequency * 2.0 + 1.0))
    vertical_amp = float(params.get("vertical_wave_amplitude", 0.0))
    vertical_freq = float(params.get("vertical_wave_frequency", 2.0))
    flare = float(params.get("flare", 0.0))
    waist = float(params.get("waist", 0.0))

    section: List[Vec3] = []
    for i, p in enumerate(base):
        x, y, _ = p
        dx, dy = x - cx, y - cy
        d = math.sqrt(dx * dx + dy * dy) + 1e-6
        nx, ny = dx / d, dy / d
        u = i / max(1, count)
        wave = math.sin(math.tau * frequency * u + phase) * amplitude
        wave += math.sin(math.tau * secondary_freq * u - phase * 0.65) * secondary_amp
        wave += math.sin(math.tau * vertical_freq * t + phase) * vertical_amp
        scale_offset = flare * t + waist * math.sin(math.pi * t)
        section.append((x + nx * (wave + scale_offset), y + ny * (wave + scale_offset), z))
    return section


def pleated_wall_stack_mesh(params: Dict[str, Any]) -> Mesh:
    section_count = max(16, int(params.get("section_points", 180)))
    height = float(params.get("height", 0.5))
    levels = params.get("levels")
    if levels is None:
        sample_every = max(1, int(params.get("sample_every", 10)))
        levels = max(3, int(params.get("steps", 180)) // sample_every + 1)
    level_count = max(2, int(levels))
    wall_thickness = float(params.get("wall_thickness", max(float(params.get("thickness", 0.012)) * 2.6, 0.03)))
    z0 = float(params.get("start_z", 0.0))
    cap_bottom = _param_bool(params, "cap_bottom", True)
    rim_thickness = float(params.get("rim_thickness", wall_thickness * 1.15))

    outer_sections: List[List[Vec3]] = []
    inner_sections: List[List[Vec3]] = []
    for level in range(level_count):
        t = level / max(1, level_count - 1)
        z = z0 + height * t
        outer = _pleat_section(params, section_count, z, t)
        inner = _radial_scaled_section(outer, -wall_thickness)
        outer_sections.append(outer)
        inner_sections.append(inner)

    mesh = Mesh()
    outer_base = len(mesh.vertices) + 1
    for section in outer_sections:
        mesh.vertices.extend(section)
    for level in range(level_count - 1):
        row = outer_base + level * section_count
        nxt = row + section_count
        for j in range(section_count):
            mesh.faces.append([row + j, row + (j + 1) % section_count, nxt + (j + 1) % section_count, nxt + j])

    inner_base = len(mesh.vertices) + 1
    for section in inner_sections:
        mesh.vertices.extend(section)
    for level in range(level_count - 1):
        row = inner_base + level * section_count
        nxt = row + section_count
        for j in range(section_count):
            mesh.faces.append([row + j, nxt + j, nxt + (j + 1) % section_count, row + (j + 1) % section_count])

    top_outer = outer_base + (level_count - 1) * section_count
    top_inner = inner_base + (level_count - 1) * section_count
    bottom_outer = outer_base
    bottom_inner = inner_base
    for j in range(section_count):
        mesh.faces.append([top_outer + j, top_outer + (j + 1) % section_count, top_inner + (j + 1) % section_count, top_inner + j])
        if cap_bottom:
            mesh.faces.append([bottom_outer + j, bottom_inner + j, bottom_inner + (j + 1) % section_count, bottom_outer + (j + 1) % section_count])

    if rim_thickness > wall_thickness:
        rim_outer = _radial_scaled_section(outer_sections[-1], rim_thickness - wall_thickness)
        rim_base = len(mesh.vertices) + 1
        mesh.vertices.extend(rim_outer)
        for j in range(section_count):
            mesh.faces.append([top_outer + j, rim_base + j, rim_base + (j + 1) % section_count, top_outer + (j + 1) % section_count])

    return mesh


def differential_growth_stack_mesh(params: Dict[str, Any], obn: Optional[Dict[str, LiveObject]] = None) -> Mesh:
    mode = str(params.get("mode", params.get("style", "boundary"))).strip().lower()
    if mode in {"pleated_wall", "pleated", "folded_wall", "vase"}:
        return pleated_wall_stack_mesh(params)
    if mode in {"infill", "interior", "constrained", "growth_infill", "space_filling"}:
        return differential_growth_constrained_stack_mesh(params, obn)
    if mode in {"path_infill", "serpentine", "print_infill"}:
        return differential_growth_infill_stack_mesh(params)

    rng = random.Random(int(params.get("seed", 1)))
    steps = max(0, int(params.get("steps", 120)))
    sample_every = max(1, int(params.get("sample_every", params.get("section_every", 10))))
    section_count = max(8, int(params.get("section_points", 96)))
    thickness = float(params.get("thickness", params.get("section_thickness", 0.015)))
    tube_segments = max(4, int(params.get("tube_segments", 8)))
    show_sections = _param_bool(params, "show_sections", True)
    make_surface = _param_bool(params, "loft", _param_bool(params, "surface", True))
    cap_ends = _param_bool(params, "cap_ends", False)

    pts = _initial_growth_profile(params, rng)
    snapshots: List[List[Vec3]] = [list(pts)]
    for step in range(1, steps + 1):
        pts = _differential_growth_step(pts, params)
        if step % sample_every == 0 or step == steps:
            snapshots.append(list(pts))

    if len(snapshots) < 2:
        snapshots.append(list(pts))

    height = params.get("height")
    if height is not None:
        layer_height = float(height) / max(1, len(snapshots) - 1)
    else:
        layer_height = float(params.get("layer_height", 0.05))
    z0 = float(params.get("start_z", 0.0))

    sections: List[List[Vec3]] = []
    for i, section in enumerate(snapshots):
        z = z0 + i * layer_height
        resampled = _resample_closed_polyline(section, section_count)
        sections.append([(x, y, z) for x, y, _ in resampled])

    mesh = Mesh()

    if make_surface and len(sections) >= 2:
        base_index = len(mesh.vertices) + 1
        for section in sections:
            mesh.vertices.extend(section)
        for level in range(len(sections) - 1):
            row = base_index + level * section_count
            nxt = row + section_count
            for j in range(section_count):
                mesh.faces.append([
                    row + j,
                    row + (j + 1) % section_count,
                    nxt + (j + 1) % section_count,
                    nxt + j,
                ])
        if cap_ends:
            mesh.faces.append([base_index + i for i in range(section_count - 1, -1, -1)])
            top = base_index + (len(sections) - 1) * section_count
            mesh.faces.append([top + i for i in range(section_count)])

    if show_sections and thickness > 0:
        for section in sections:
            for i, p in enumerate(section):
                mesh.extend(tube_between(p, section[(i + 1) % len(section)], thickness, tube_segments))

    return mesh


def boids_mesh(params: Dict[str, Any]) -> Mesh:
    agents = int(params.get("agents", 30))
    steps = int(params.get("steps", 120))
    step_size = float(params.get("step_size", 0.05))
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
                # Perception radius for cohesion and alignment
                if d < 1.5:
                    center[0]+=q[0]; center[1]+=q[1]; center[2]+=q[2]
                    align[0]+=vel[j][0]; align[1]+=vel[j][1]; align[2]+=vel[j][2]
                    count += 1
                # Separation radius (smaller)
                if d < 0.4 and d > 1e-6:
                    sep[0]-=dx/d; sep[1]-=dy/d; sep[2]-=dz/d
            if count:
                center = [c/count for c in center]
                align = [a/count for a in align]
                # Cohesion: steer towards average position of neighbors
                vx += (center[0]-p[0])*0.01
                vy += (center[1]-p[1])*0.01
                vz += (center[2]-p[2])*0.01
                # Alignment: steer towards average heading of neighbors
                vx += align[0]*0.02
                vy += align[1]*0.02
                vz += align[2]*0.02
            # Separation: avoid crowding
            vx += sep[0]*0.05
            vy += sep[1]*0.05
            vz += sep[2]*0.05
            # Boundary repulsion (keep within bounds)
            margin = 0.5
            if p[0] < -bx/2 + margin: vx += 0.02
            if p[0] > bx/2 - margin: vx -= 0.02
            if p[1] < -by/2 + margin: vy += 0.02
            if p[1] > by/2 - margin: vy -= 0.02
            if p[2] < margin: vz += 0.02
            if p[2] > bz - margin: vz -= 0.02
            # Speed limit
            speed = math.sqrt(vx*vx+vy*vy+vz*vz) + 1e-6
            max_speed = 0.08
            min_speed = 0.02
            if speed > max_speed:
                vx,vy,vz = vx/speed*max_speed, vy/speed*max_speed, vz/speed*max_speed
            elif speed < min_speed:
                vx,vy,vz = vx/speed*min_speed, vy/speed*min_speed, vz/speed*min_speed
            np = (max(-bx/2,min(bx/2,p[0]+vx*step_size)), max(-by/2,min(by/2,p[1]+vy*step_size)), max(0,min(bz,p[2]+vz*step_size)))
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


def noise3d(x: float, y: float, z: float, seed: int) -> float:
    """3D Simplex noise implementation."""
    # Permutation table with seed
    p = list(range(256))
    rng = random.Random(seed)
    rng.shuffle(p)
    p = p + p  # Duplicate for overflow
    
    # Skewing and unskewing factors for 3D
    F3 = 1.0 / 3.0
    G3 = 1.0 / 6.0
    
    # Skew the input space to determine which simplex cell we're in
    s = (x + y + z) * F3
    i = int(x + s)
    j = int(y + s)
    k = int(z + s)
    
    t = (i + j + k) * G3
    X0 = i - t
    Y0 = j - t
    Z0 = k - t
    x0 = x - X0
    y0 = y - Y0
    z0 = z - Z0
    
    # Determine which simplex we're in
    i1, j1, k1, i2, j2, k2 = 0, 0, 0, 0, 0, 0
    if x0 >= y0:
        if y0 >= z0:
            i1, j1, k1 = 1, 0, 0
            i2, j2, k2 = 1, 1, 0
        elif x0 >= z0:
            i1, j1, k1 = 1, 0, 0
            i2, j2, k2 = 1, 0, 1
        else:
            i1, j1, k1 = 0, 0, 1
            i2, j2, k2 = 1, 0, 1
    else:
        if y0 < z0:
            i1, j1, k1 = 0, 0, 1
            i2, j2, k2 = 0, 1, 1
        elif x0 < z0:
            i1, j1, k1 = 0, 1, 0
            i2, j2, k2 = 0, 1, 1
        else:
            i1, j1, k1 = 0, 1, 0
            i2, j2, k2 = 1, 1, 0
    
    # Offsets for corners
    x1 = x0 - i1 + G3
    y1 = y0 - j1 + G3
    z1 = z0 - k1 + G3
    x2 = x0 - i2 + 2.0 * G3
    y2 = y0 - j2 + 2.0 * G3
    z2 = z0 - k2 + 2.0 * G3
    x3 = x0 - 1.0 + 3.0 * G3
    y3 = y0 - 1.0 + 3.0 * G3
    z3 = z0 - 1.0 + 3.0 * G3
    
    # Calculate contribution from each corner
    def grad(hash_val, x, y, z):
        # Convert hash to one of 12 gradients
        h = hash_val & 15
        u = x if h < 8 else y
        v = y if h < 4 else (x if h == 12 or h == 14 else z)
        return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)
    
    n0, n1, n2, n3 = 0.0, 0.0, 0.0, 0.0
    
    # Corner 0
    t0 = 0.6 - x0*x0 - y0*y0 - z0*z0
    if t0 >= 0:
        t0 *= t0
        n0 = t0 * t0 * grad(p[(i + p[(j + p[k & 255]) & 255]) & 255], x0, y0, z0)
    
    # Corner 1
    t1 = 0.6 - x1*x1 - y1*y1 - z1*z1
    if t1 >= 0:
        t1 *= t1
        n1 = t1 * t1 * grad(p[(i + i1 + p[(j + j1 + p[(k + k1) & 255]) & 255]) & 255], x1, y1, z1)
    
    # Corner 2
    t2 = 0.6 - x2*x2 - y2*y2 - z2*z2
    if t2 >= 0:
        t2 *= t2
        n2 = t2 * t2 * grad(p[(i + i2 + p[(j + j2 + p[(k + k2) & 255]) & 255]) & 255], x2, y2, z2)
    
    # Corner 3
    t3 = 0.6 - x3*x3 - y3*y3 - z3*z3
    if t3 >= 0:
        t3 *= t3
        n3 = t3 * t3 * grad(p[(i + 1 + p[(j + 1 + p[(k + 1) & 255]) & 255]) & 255], x3, y3, z3)
    
    # Scale and return
    return 32.0 * (n0 + n1 + n2 + n3)


def flow_field_mesh(params: Dict[str, Any]) -> Mesh:
    agents = int(params.get("agents", 50))
    steps = int(params.get("steps", 200))
    step_size = float(params.get("step_size", 0.1))
    bounds = params.get("bounds", [10,10,10])
    bx, by, bz = map(float, bounds)
    mode = str(params.get("mode", "curl-noise")).lower()
    frequency = float(params.get("frequency", 1.0))
    octaves = int(params.get("octaves", 3))
    strength = float(params.get("strength", 1.0))
    scale = float(params.get("scale", 0.1))
    time_scale = float(params.get("time_scale", 0.01))
    damping = float(params.get("damping", 0.0))
    seed = int(params.get("seed", 1))
    radius = float(params.get("trace_radius", 0.025))
    rng = random.Random(seed)

    # Initialize particle positions randomly within bounds
    pos = [(rng.uniform(-bx/2,bx/2), rng.uniform(-by/2,by/2), rng.uniform(-bz/2,bz/2)) for _ in range(agents)]
    # Initialize velocities randomly
    vel = [(rng.uniform(-0.01,0.01), rng.uniform(-0.01,0.01), rng.uniform(-0.01,0.01)) for _ in range(agents)]
    paths = [[p] for p in pos]

    # Define field function based on mode
    def field_fn(x: float, y: float, z: float, time: float) -> Tuple[float, float, float]:
        if mode == "curl-noise":
            # 3D CURL NOISE matching JS implementation
            s = frequency
            eps = 0.01
            t = int(time * 100)
            
            # Calculate curl using JS formula
            # vx = dBzdY - dBydZ
            dBzdY = (noise3d(s * x, s * (y + eps), s * z, t) - noise3d(s * x, s * (y - eps), s * z, t)) / (2 * eps)
            dBydZ = (noise3d(s * x, s * y, s * (z + eps), t) - noise3d(s * x, s * y, s * (z - eps), t)) / (2 * eps)
            vx = dBzdY - dBydZ
            
            # vy = dBxdZ - dBzdX
            dBxdZ = (noise3d(s * x + 100, s * y, s * (z + eps), t) - noise3d(s * x + 100, s * y, s * (z - eps), t)) / (2 * eps)
            dBzdX = (noise3d(s * (x + eps), s * y, s * z, t) - noise3d(s * (x - eps), s * y, s * z, t)) / (2 * eps)
            vy = dBxdZ - dBzdX
            
            # vz = dBydX - dBxdY
            dBydX = (noise3d(s * (x + eps) + 100, s * y, s * z, t) - noise3d(s * (x - eps) + 100, s * y, s * z, t)) / (2 * eps)
            dBxdY = (noise3d(s * x + 100, s * (y + eps), s * z, t) - noise3d(s * x + 100, s * (y - eps), s * z, t)) / (2 * eps)
            vz = dBydX - dBxdY
            
            # Normalize direction
            mag = math.sqrt(vx*vx + vy*vy + vz*vz) + 1e-6
            return vx/mag, vy/mag, vz/mag
        
        elif mode == "turbulence":
            # Multi-octave noise
            vx, vy, vz = 0.0, 0.0, 0.0
            amp = 1.0
            freq = frequency
            t = int(time * 100)
            
            for _ in range(octaves):
                vx += noise3d(x * freq, y * freq, z * freq, t) * amp
                vy += noise3d(x * freq + 1000, y * freq + 1000, z * freq, t) * amp
                vz += noise3d(x * freq + 2000, y * freq, z * freq + 2000, t) * amp
                freq *= 2
                amp *= 0.5
            
            return vx, vy, vz
        
        elif mode == "attractor":
            # Single attractor at center
            dist = math.sqrt(x*x + y*y + z*z) + 1e-6
            vx, vy, vz = -x/dist, -y/dist, -z/dist
            return vx, vy, vz
        
        elif mode == "wave":
            # Expanding/contracting waves
            dist = math.sqrt(x*x + y*y + z*z)
            wave = math.sin(dist * frequency - time)
            if dist > 1e-6:
                return x/dist * wave, y/dist * wave, z/dist * wave
            return 0.0, 0.0, 0.0
        
        elif mode == "laminar":
            # Simple linear flow along X
            return 1.0, 0.0, 0.0
        
        else:
            return 0.0, 0.0, 0.0

    for step in range(steps):
        time = step * time_scale
        new_pos, new_vel = [], []
        for i, p in enumerate(pos):
            # Get field direction at current position
            nx, ny, nz = field_fn(p[0], p[1], p[2], time)
            
            # Apply strength and scale
            nx, ny, nz = nx * strength * scale, ny * strength * scale, nz * strength * scale
            
            # Apply damping
            if damping > 0:
                dist = math.sqrt(p[0]*p[0] + p[1]*p[1] + p[2]*p[2])
                damp = math.exp(-damping * dist)
                nx, ny, nz = nx * damp, ny * damp, nz * damp
            
            # Lerp velocity toward field direction (matching JS approach)
            vx, vy, vz = vel[i]
            vx = vx * 0.7 + nx * 0.3
            vy = vy * 0.7 + ny * 0.3
            vz = vz * 0.7 + nz * 0.3
            
            # Normalize velocity
            vmag = math.sqrt(vx*vx + vy*vy + vz*vz) + 1e-6
            vx, vy, vz = vx/vmag, vy/vmag, vz/vmag
            
            # Move particle in direction of velocity
            np = (
                p[0] + vx * step_size,
                p[1] + vy * step_size,
                p[2] + vz * step_size
            )
            
            # Keep within bounds (wrap around)
            np = (
                np[0] if np[0] > -bx/2 and np[0] < bx/2 else (-bx/2 if np[0] <= -bx/2 else bx/2),
                np[1] if np[1] > -by/2 and np[1] < by/2 else (-by/2 if np[1] <= -by/2 else by/2),
                np[2] if np[2] > -bz/2 and np[2] < bz/2 else (-bz/2 if np[2] <= -bz/2 else bz/2)
            )
            
            new_pos.append(np)
            new_vel.append((vx, vy, vz))
            
            # Record path every step for smoother curves
            paths[i].append(np)
        
        pos, vel = new_pos, new_vel

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
    if out.vertices:
        xs = [v[0] for v in out.vertices]
        ys = [v[1] for v in out.vertices]
        zs = [v[2] for v in out.vertices]
        span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)
        out = weld_vertices(out, epsilon=max(1e-6, span * 1e-6))
    # Pure Laplacian smoothing on very coarse primitives (e.g., an 8-vertex box)
    # mostly shrinks corners toward center but keeps the same faceted topology.
    # Add one adaptive subdivision pass so smoothing can actually round the shape.
    if len(out.vertices) <= 16 and len(out.faces) <= 12 and iterations > 0:
        out = op_subdivide(out, 1)
    for _ in range(iterations):
        nbr = {i: set() for i in range(1, len(out.vertices)+1)}
        for face in out.faces:
            valid = [int(ix) for ix in face if isinstance(ix, int) and 1 <= int(ix) <= len(out.vertices)]
            if len(valid) < 2:
                continue
            for i, a in enumerate(valid):
                b = valid[(i + 1) % len(valid)]
                nbr[a].add(b)
                nbr[b].add(a)
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


def op_radial_array(mesh: Mesh, count: int, axis: str = "z", radius: float = 0.0) -> Mesh:
    out = Mesh()
    n = max(1, int(count))
    ax = str(axis).lower()
    r = float(radius)
    for i in range(n):
        th = 2 * math.pi * i / n
        if ax == "z":
            dx, dy, dz = r * math.cos(th), r * math.sin(th), 0.0
        elif ax == "y":
            dx, dy, dz = r * math.cos(th), 0.0, r * math.sin(th)
        else:
            dx, dy, dz = 0.0, r * math.cos(th), r * math.sin(th)
        m = mesh.copy()
        m.vertices = [(x + dx, y + dy, z + dz) for x, y, z in m.vertices]
        out.extend(m)
    return out


def op_taper(mesh: Mesh, axis: str = "z", amount: float = 0.0) -> Mesh:
    out = mesh.copy()
    if not out.vertices:
        return out
    ax = axis.lower()
    xs, ys, zs = [v[0] for v in out.vertices], [v[1] for v in out.vertices], [v[2] for v in out.vertices]
    min_a, max_a = (min(zs), max(zs)) if ax == "z" else ((min(ys), max(ys)) if ax == "y" else (min(xs), max(xs)))
    span = max(1e-9, max_a - min_a)
    nv: List[Vec3] = []
    for x, y, z in out.vertices:
        t = ((z if ax == "z" else (y if ax == "y" else x)) - min_a) / span
        s = 1.0 + amount * (t - 0.5) * 2.0
        if ax == "z":
            nv.append((x * s, y * s, z))
        elif ax == "y":
            nv.append((x * s, y, z * s))
        else:
            nv.append((x, y * s, z * s))
    out.vertices = nv
    return out


def op_twist(mesh: Mesh, axis: str = "z", angle_deg: float = 0.0) -> Mesh:
    out = mesh.copy()
    if not out.vertices:
        return out
    ax = axis.lower()
    xs, ys, zs = [v[0] for v in out.vertices], [v[1] for v in out.vertices], [v[2] for v in out.vertices]
    min_a, max_a = (min(zs), max(zs)) if ax == "z" else ((min(ys), max(ys)) if ax == "y" else (min(xs), max(xs)))
    span = max(1e-9, max_a - min_a)
    total = math.radians(angle_deg)
    nv: List[Vec3] = []
    for x, y, z in out.vertices:
        acoord = z if ax == "z" else (y if ax == "y" else x)
        t = (acoord - min_a) / span
        th = total * t
        c, s = math.cos(th), math.sin(th)
        if ax == "z":
            nv.append((x * c - y * s, x * s + y * c, z))
        elif ax == "y":
            nv.append((x * c - z * s, y, x * s + z * c))
        else:
            nv.append((x, y * c - z * s, y * s + z * c))
    out.vertices = nv
    return out


def op_bend(mesh: Mesh, axis: str = "x", angle_deg: float = 0.0) -> Mesh:
    out = mesh.copy()
    if not out.vertices or abs(angle_deg) < 1e-8:
        return out
    ax = axis.lower()
    nv: List[Vec3] = []
    k = math.radians(angle_deg) / max(1e-6, max(abs(v[0]) + abs(v[1]) + abs(v[2]) for v in out.vertices))
    for x, y, z in out.vertices:
        if ax == "x":
            th = x * k
            c, s = math.cos(th), math.sin(th)
            nv.append((x, y * c - z * s, y * s + z * c))
        elif ax == "y":
            th = y * k
            c, s = math.cos(th), math.sin(th)
            nv.append((x * c - z * s, y, x * s + z * c))
        else:
            th = z * k
            c, s = math.cos(th), math.sin(th)
            nv.append((x * c - y * s, x * s + y * c, z))
    out.vertices = nv
    return out


def op_simplify(mesh: Mesh, ratio: float = 1.0) -> Mesh:
    out = mesh.copy()
    keep = max(0.05, min(1.0, ratio))
    if keep >= 0.999 or len(out.faces) < 8:
        return out
    step = max(1, int(round(1.0 / keep)))
    out.faces = [f for i, f in enumerate(out.faces) if i % step == 0]
    return out


def op_voxelize(mesh: Mesh, resolution: float = 0.1) -> Mesh:
    out = mesh.copy()
    cell = max(1e-4, float(resolution))
    out.vertices = [
        (round(x / cell) * cell, round(y / cell) * cell, round(z / cell) * cell)
        for x, y, z in out.vertices
    ]
    return out


def _sample_mesh_path_points(mesh: Mesh, sample_every: int = 1) -> List[Vec3]:
    if not mesh.vertices:
        return []
    step = max(1, int(sample_every))
    return [mesh.vertices[i] for i in range(0, len(mesh.vertices), step)]


def op_trace_paths(mesh: Mesh, sample_every: int = 1) -> Mesh:
    pts = _sample_mesh_path_points(mesh, sample_every)
    if len(pts) < 2:
        return mesh.copy()
    out = Mesh()
    for i in range(len(pts) - 1):
        out.extend(tube_between(pts[i], pts[i + 1], 0.01, 6))
    return out


def op_sdf_tubes(mesh: Mesh, radius: float = 0.03, sample_every: int = 1) -> Mesh:
    pts = _sample_mesh_path_points(mesh, sample_every)
    if len(pts) < 2:
        return mesh.copy()
    out = Mesh()
    seg = 8 if radius <= 0.05 else 10
    for i in range(len(pts) - 1):
        out.extend(tube_between(pts[i], pts[i + 1], float(radius), seg))
    return out


def weld_vertices(mesh: Mesh, epsilon: float = 1e-6) -> Mesh:
    if not mesh.vertices:
        return mesh.copy()
    out = Mesh()
    key_to_new: Dict[Tuple[int, int, int], int] = {}
    old_to_new: Dict[int, int] = {}
    inv = 1.0 / max(1e-9, epsilon)
    for i, (x, y, z) in enumerate(mesh.vertices, start=1):
        key = (int(round(x * inv)), int(round(y * inv)), int(round(z * inv)))
        idx = key_to_new.get(key)
        if idx is None:
            out.vertices.append((x, y, z))
            idx = len(out.vertices)
            key_to_new[key] = idx
        old_to_new[i] = idx

    for f in mesh.faces:
        nf = [old_to_new.get(v, v) for v in f]
        # drop collapsed/degenerate faces after weld
        if len(set(nf)) >= 3:
            out.faces.append(nf)
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


def op_subdivide(mesh: Mesh, level: int = 1) -> Mesh:
    out = mesh.copy()
    for _ in range(max(0, int(level))):
        edge_mid: Dict[Tuple[int, int], int] = {}
        new_vertices = list(out.vertices)
        new_faces: List[List[int]] = []

        def midpoint_index(a: int, b: int) -> int:
            key = (a, b) if a < b else (b, a)
            if key in edge_mid:
                return edge_mid[key]
            ax, ay, az = new_vertices[a - 1]
            bx, by, bz = new_vertices[b - 1]
            new_vertices.append(((ax + bx) * 0.5, (ay + by) * 0.5, (az + bz) * 0.5))
            idx = len(new_vertices)
            edge_mid[key] = idx
            return idx

        for face in out.faces:
            if len(face) < 3:
                continue
            # fan triangulate for stability
            tris = [[face[0], face[i], face[i + 1]] for i in range(1, len(face) - 1)]
            for a, b, c in tris:
                ab = midpoint_index(a, b)
                bc = midpoint_index(b, c)
                ca = midpoint_index(c, a)
                new_faces.extend([[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]])

        out.vertices = new_vertices
        out.faces = new_faces
    return out


def _axis_aligned_bbox(mesh: Mesh) -> Optional[Tuple[Vec3, Vec3]]:
    if not mesh.vertices:
        return None
    xs = [v[0] for v in mesh.vertices]
    ys = [v[1] for v in mesh.vertices]
    zs = [v[2] for v in mesh.vertices]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def op_bevel(mesh: Mesh, amount: float = 0.05, segments: int = 1) -> Mesh:
    """Approximate a CAD-like edge bevel for boxy meshes.

    Current executor primitives often produce axis-aligned cuboids. For those,
    generate a rounded box directly (12 edge strips + 8 corner patches) instead
    of Laplacian smoothing, which shrinks/distorts the whole mesh.
    """
    def fallback_bevel(m: Mesh, amt: float, seg: int) -> Mesh:
        lvl = min(2, max(1, seg))
        out = op_subdivide(m, lvl)
        return op_smooth(out, min(4, max(1, seg)), min(0.8, 0.2 + max(0.0, amt)))

    bbox = _axis_aligned_bbox(mesh)
    if bbox is None:
        return mesh.copy()
    # Only replace geometry with a rounded box for truly box-like meshes.
    # Cylinders/tubes were being incorrectly converted into rounded boxes.
    if len(mesh.faces) > 24 or len(mesh.vertices) > 32:
        return fallback_bevel(mesh, float(amount), max(1, int(segments)))
    (min_x, min_y, min_z), (max_x, max_y, max_z) = bbox
    sx, sy, sz = max_x - min_x, max_y - min_y, max_z - min_z
    if sx <= 1e-9 or sy <= 1e-9 or sz <= 1e-9:
        return mesh.copy()

    seg = max(1, int(segments))
    r = max(0.0, float(amount))
    r = min(r, sx * 0.499, sy * 0.499, sz * 0.499)
    if r <= 1e-8:
        return mesh.copy()
    return rounded_box_mesh(((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5), (sx, sy, sz), r, seg)


def _resolve_kernel_center(obj: LiveObject, params: Dict[str, Any], env: Dict[str, Any]) -> Vec3:
    """Resolve a kernel op's `center`/`position`, degrading to origin on unresolvable refs."""
    # First check for transform position
    transform = obj.meta.get("transform")
    if isinstance(transform, dict):
        position = transform.get("position")
        if isinstance(position, (list, tuple)) and len(position) >= 3:
            return _as_float3(position, (0.0, 0.0, 0.0))
    # Then check params center/position
    center_raw = params.get("center", params.get("position", [0, 0, 0]))
    if isinstance(center_raw, str):
        try:
            center_raw = eval_mixed_value(center_raw, env, {})
        except KeyError as ex:
            # Unresolvable reference (e.g. anchor() without #@anchors) must not
            # kill the whole scene: warn and fall back to origin.
            print(
                "[live-obj] kernel center on '%s' unresolved (%s); using [0,0,0]" % (obj.name, ex),
                file=sys.stderr,
            )
            center_raw = [0.0, 0.0, 0.0]
    return _as_float3(center_raw, (0.0, 0.0, 0.0))


def kernel_op_bevel(obj: LiveObject, env: Dict[str, Any], amount: float, segments: int, kernel_default: str = "") -> Optional[Mesh]:
    params = dict(obj.meta.get("params", {}) or {})
    params["bevel_radius"] = amount
    params["segments"] = segments
    kernel = str(params.get("kernel", "")).lower()
    if not kernel:
        kernel = kernel_default
    if not kernel:
        return None
    center = _resolve_kernel_center(obj, params, env)
    typ = str(obj.meta.get("type", "")).lower()
    if typ not in {"box", "cylinder"}:
        return None
    return kernel_mesh_primitive(kernel, typ, params, center)


def kernel_op_cadquery_solid(obj: LiveObject, env: Dict[str, Any]) -> Optional[Tuple[Any, Vec3, int]]:
    params = dict(obj.meta.get("params", {}) or {})
    kernel = str(params.get("kernel", "")).lower()
    if kernel != "cadquery":
        return None
    center = _resolve_kernel_center(obj, params, env)
    typ = str(obj.meta.get("type", "")).lower()
    solid = cadquery_solid_from_params(typ, params)
    if solid is None:
        return None
    segments = int(params.get("segments", 24))
    # For primitives created at origin, translate to center
    if typ in {"box", "cylinder", "sphere", "cone"}:
        cx, cy, cz = center
        solid = solid.translate((cx, cy, cz))
        return (solid, (0.0, 0.0, 0.0), segments)
    # For profile-based ops (extrude, revolve, sweep, loft), the solid is already
    # translated to world position in cadquery_solid_from_params, so use origin for tessellation
    return (solid, (0.0, 0.0, 0.0), segments)


def apply_ops(mesh: Mesh, obj: LiveObject, obn: Dict[str, LiveObject], kernel_default: str = "") -> Mesh:
    out = mesh
    env = get_effective_params(obj, obn)
    def resolve_op_value(op: Dict[str, Any], key: str, default: Any) -> Any:
        raw = op.get(key, default)
        if isinstance(raw, str):
            return eval_mixed_value(raw, env, obn)
        return raw
    if isinstance(obj.meta.get("transform"), dict):
        transform_dict = dict(obj.meta["transform"])
        # Common Live OBJ pattern: procedural params define `center=anchor(...)` and
        # transform repeats `position=anchor(...)`. Applying both double-translates.
        if str(obj.meta.get("source", "")) == "procedural":
            params = obj.meta.get("params", {}) or {}
            c = params.get("center")
            p = transform_dict.get("position")
            if isinstance(c, (list, tuple)) and isinstance(p, (list, tuple)) and len(c) >= 3 and len(p) >= 3:
                if (
                    abs(float(c[0]) - float(p[0])) <= 1e-8
                    and abs(float(c[1]) - float(p[1])) <= 1e-8
                    and abs(float(c[2]) - float(p[2])) <= 1e-8
                ):
                    transform_dict["position"] = [0.0, 0.0, 0.0]
        out = apply_transform(out, transform_dict)
    # Child object transforms are local to their parent assembly/object.
    # Promote mesh into world space by applying ancestor transforms (root -> leaf).
    parent_chain: List[Dict[str, Any]] = []
    pn = obj.meta.get("parent")
    while pn and str(pn) in obn:
        pobj = obn[str(pn)]
        tr = pobj.meta.get("transform")
        if isinstance(tr, dict):
            parent_chain.append(tr)
        pn = pobj.meta.get("parent")
    for tr in reversed(parent_chain):
        out = apply_transform(out, tr)

    for op in obj.ops:
        name = op.get("op")
        if name == "transform":
            transform_dict = {
                "position": resolve_op_value(op, "position", [0, 0, 0]),
                "scale": resolve_op_value(op, "scale", [1, 1, 1]),
                "rotation": resolve_op_value(op, "rotation", [0, 0, 0])
            }
            out = apply_transform(out, transform_dict)
        elif name == "displace":
            out = op_displace(out, op)
        elif name == "smooth":
            out = op_smooth(out, int(op.get("iterations",1)), float(op.get("strength",0.5)))
        elif name == "mirror":
            out = op_mirror(out, str(op.get("axis","x")))
        elif name == "array":
            offset = op.get("offset", [1,0,0])
            if isinstance(offset, str):
                offset = eval_mixed_value(offset, env, obn)
            if isinstance(offset, (list, tuple)):
                resolved_offset: List[float] = []
                for item in offset:
                    if isinstance(item, str):
                        item = eval_mixed_value(item, env, obn)
                    resolved_offset.append(float(item))
                offset = resolved_offset
            count_raw = resolve_op_value(op, "count", 2)
            out = op_array(out, int(count_raw), tuple(map(float, offset)))
        elif name == "radial_array":
            count_raw = resolve_op_value(op, "count", 6)
            radius_raw = resolve_op_value(op, "radius", 1.0)
            out = op_radial_array(
                out,
                int(count_raw),
                str(op.get("axis", "z")),
                float(radius_raw)
            )
        elif name == "tread":
            out = op_tread(out, op)
        elif name == "bevel":
            amount = float(resolve_op_value(op, "amount", 0.05))
            seg = int(resolve_op_value(op, "segments", 1))
            ker_mesh = kernel_op_bevel(obj, env, amount, seg, kernel_default)
            if ker_mesh is not None:
                record_kernel_event(obj, "op:bevel")
                out = ker_mesh
            else:
                out = op_bevel(out, amount, seg)
        elif name in {"union", "subtract", "intersect"}:
            target_name = str(op.get("with", op.get("target", "")))
            target_obj = obn.get(target_name) if target_name else None
            cur = kernel_op_cadquery_solid(obj, env)
            tgt = kernel_op_cadquery_solid(target_obj, env) if target_obj is not None else None
            if cur is not None and tgt is not None:
                solid_a, center_a, seg_a = cur
                solid_b, _, _ = tgt
                try:
                    # Use center_a for tessellation - primitives return (0,0,0) after translation,
                    # profile ops return actual center for offset
                    if name == "union":
                        record_kernel_event(obj, "op:union")
                        out = cadquery_tessellated_mesh(solid_a.fuse(solid_b), center_a, seg_a)
                    elif name == "subtract":
                        record_kernel_event(obj, "op:subtract")
                        out = cadquery_tessellated_mesh(solid_a.cut(solid_b), center_a, seg_a)
                    else:
                        record_kernel_event(obj, "op:intersect")
                        out = cadquery_tessellated_mesh(solid_a.intersect(solid_b), center_a, seg_a)
                except Exception as e:
                    pass
        elif name == "boolean":
            # Support boolean operation with mode parameter: #@op: boolean mode=subtract target=arch_cutout
            mode = str(op.get("mode", "")).lower()
            if mode in {"union", "subtract", "intersect"}:
                target_name = str(op.get("with", op.get("target", "")))
                target_obj = obn.get(target_name) if target_name else None

                # Try trimesh-based boolean first (better for complex profiles)
                if mesh is not None and target_obj is not None and target_obj.mesh is not None:
                    trimesh_result = trimesh_boolean(mesh, target_obj.mesh, mode)
                    if trimesh_result is not None:
                        record_kernel_event(obj, f"op:boolean:{mode}")
                        out = trimesh_result

                # Fallback to CadQuery kernel boolean
                if out is None:
                    cur = kernel_op_cadquery_solid(obj, env)
                    tgt = kernel_op_cadquery_solid(target_obj, env) if target_obj is not None else None
                    if cur is not None and tgt is not None:
                        solid_a, center_a, seg_a = cur
                        solid_b, _, _ = tgt
                        try:
                            if mode == "union":
                                record_kernel_event(obj, "op:boolean:union")
                                out = cadquery_tessellated_mesh(solid_a.fuse(solid_b), center_a, seg_a)
                            elif mode == "subtract":
                                record_kernel_event(obj, "op:boolean:subtract")
                                out = cadquery_tessellated_mesh(solid_a.cut(solid_b), center_a, seg_a)
                            else:
                                record_kernel_event(obj, "op:boolean:intersect")
                                out = cadquery_tessellated_mesh(solid_a.intersect(solid_b), center_a, seg_a)
                        except Exception as e:
                            pass
        elif name == "chamfer":
            amount = float(resolve_op_value(op, "amount", op.get("distance", 0.02)))
            cur = kernel_op_cadquery_solid(obj, env)
            if cur is not None and amount > 0:
                solid, center_s, seg_s = cur
                try:
                    record_kernel_event(obj, "op:chamfer")
                    out = cadquery_tessellated_mesh(solid.chamfer(amount), center_s, seg_s)
                except Exception:
                    out = op_bevel(out, amount, int(resolve_op_value(op, "segments", 1)))
            else:
                out = op_bevel(out, amount, int(resolve_op_value(op, "segments", 1)))
        elif name in {"shell", "thicken", "offset"}:
            thickness = float(resolve_op_value(op, "thickness", op.get("amount", 0.05)))
            cur = kernel_op_cadquery_solid(obj, env)
            if cur is not None and abs(thickness) > 1e-9:
                solid, center_s, seg_s = cur
                try:
                    record_kernel_event(obj, f"op:{name}")
                    out = cadquery_tessellated_mesh(solid.shell(thickness), center_s, seg_s)
                except Exception:
                    pass
        elif name == "subdivide":
            out = op_subdivide(out, int(op.get("level", 1)))
        elif name == "taper":
            amount_raw = resolve_op_value(op, "amount", 0.0)
            out = op_taper(out, str(op.get("axis", "z")), float(amount_raw))
        elif name == "twist":
            angle_raw = resolve_op_value(op, "angle", 0.0)
            out = op_twist(out, str(op.get("axis", "z")), float(angle_raw))
        elif name == "bend":
            angle_raw = resolve_op_value(op, "angle", 0.0)
            out = op_bend(out, str(op.get("axis", "x")), float(angle_raw))
        elif name == "simplify":
            out = op_simplify(out, float(op.get("ratio", 1.0)))
        elif name == "remesh":
            res = float(op.get("resolution", 0.25))
            lvl = 2 if res <= 0.08 else (1 if res <= 0.2 else 0)
            if lvl > 0:
                out = op_subdivide(out, lvl)
        elif name == "trace_paths":
            out = op_trace_paths(out, int(op.get("sample_every", 1)))
        elif name == "sdf_tubes":
            out = op_sdf_tubes(
                out,
                float(op.get("radius", 0.03)),
                int(op.get("sample_every", 1)),
            )
        elif name == "voxelize":
            out = op_voxelize(out, float(op.get("resolution", 0.1)))
        elif name == "mesh_from_volume":
            # In this stdlib executor, volume conversion is approximated by keeping
            # current mesh output from previous ops (e.g., voxelize/sdf_tubes).
            pass
        elif name == "material":
            # Material operation: apply material preset to object
            material_name = str(op.get("name", ""))
            if material_name:
                obj.meta["material"] = material_name
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
    kernel = str(params.get("kernel", "")).lower()

    if typ == "mesh":
        gen = str(params.get("generator", ""))
        if gen == "spiral_treads":
            return spiral_treads_mesh(params, center)
        if gen == "spiral_post_array":
            return spiral_post_array_mesh(params, center)
        if gen == "helix_array":
            return helix_array_mesh(params, center)
        return obj.mesh.copy()

    if typ == "sweep":
        if kernel:
            ker_mesh = kernel_mesh_profile_op(kernel, "sweep", params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, "generate:sweep")
                return ker_mesh
        p = dict(params)
        along = p.get("along")
        if along and obn is not None:
            curve_mesh = curve_path_sweep_mesh(p, center, obn)
            if curve_mesh is not None:
                return curve_mesh
            p = merge_sweep_params_with_along_helix(p, along, obn)
        path_k = str(p.get("path", p.get("shape", "line"))).lower()
        if path_k == "helix" or p.get("path_radius") is not None or bool(along and obn is not None):
            return helix_sweep_mesh(p, center)
        return obj.mesh.copy()

    if typ == "curve":
        if kernel:
            ker_mesh = kernel_mesh_profile_op(kernel, "curve", params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, "generate:curve")
                return ker_mesh
        sw = obj.meta.get("sweep")
        if isinstance(sw, dict) and str(sw.get("profile", "circle")).lower() == "circle":
            return curve_sweep_tube_mesh(params, center, sw, obn)
        return obj.mesh.copy()

    if typ in {"extrude", "revolve", "lathe"}:
        if kernel:
            ker_mesh = kernel_mesh_profile_op(kernel, typ, params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, f"generate:{typ}")
                return ker_mesh
        # Non-kernel path: use cadquery_profile_mesh for extrude/revolve/lathe
        if typ == "extrude":
            profile_points = params.get("profile", [])
            if isinstance(profile_points, list) and len(profile_points) >= 3:
                height = float(params.get("height", params.get("depth", 1.0)))
                segments = int(params.get("segments", 24))
                return cadquery_profile_mesh("extrude", center, profile_points, height, segments)
        elif typ in {"revolve", "lathe"}:
            profile_points = params.get("profile", [])
            if isinstance(profile_points, list) and len(profile_points) >= 2:
                angle = float(params.get("angle", 360.0))
                axis = str(params.get("axis", "y"))
                segments = int(params.get("segments", 24))
                return cadquery_profile_mesh(typ, center, profile_points, segments, angle, axis)
        return obj.mesh.copy()
    if typ == "loft":
        if kernel:
            ker_mesh = kernel_mesh_profile_op(kernel, "loft", params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, "generate:loft")
                return ker_mesh
        return obj.mesh.copy()

    if typ == "box":
        size = params.get("size", [params.get("width", 1), params.get("depth", params.get("length", 1)), params.get("height", 1)])
        if isinstance(size, str):
            raise TypeError("size should be a 3-vector after parametric resolution")
        if kernel:
            ker_mesh = kernel_mesh_primitive(kernel, "box", params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, "generate:box")
                return ker_mesh
        return box_mesh(center, _as_float3(size, (1.0, 1.0, 1.0)))
    if typ == "cylinder":
        axis = str(params.get("axis", "z")).lower()
        depth = float(params.get("depth", params.get("height", params.get("width", 1))))
        radius = float(params.get("radius", 0.5))
        segments = int(params.get("segments", 16))
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
        kernel = str(params.get("kernel", "")).lower()
        if kernel and not base_aligned:
            ker_mesh = kernel_mesh_primitive(kernel, "cylinder", params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, "generate:cylinder")
                return ker_mesh
        return cylinder_mesh(
            axis,
            center,
            radius,
            depth,
            segments,
            base_aligned=base_aligned,
        )
    if typ == "cone":
        if kernel:
            ker_mesh = kernel_mesh_primitive(kernel, "cone", params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, "generate:cone")
                return ker_mesh
        axis = str(params.get("axis", "z")).lower()
        height = float(params.get("height", params.get("depth", 1.0)))
        return cone_mesh(
            axis,
            center,
            float(params.get("radius", 0.5)),
            height,
            int(params.get("segments", 16)),
        )
    if typ == "sphere":
        if kernel:
            ker_mesh = kernel_mesh_primitive(kernel, "sphere", params, center)
            if ker_mesh is not None:
                record_kernel_event(obj, "generate:sphere")
                return ker_mesh
        return sphere_mesh(
            center,
            float(params.get("radius", 0.5)),
            int(params.get("segments", 20)),
        )
    if typ in {"surface_grid", "heightfield"}:
        return surface_grid(float(params.get("width",10)), float(params.get("depth",10)), int(params.get("resolution",20)), center)

    return obj.mesh.copy()


def _infer_sdf_bounds(sdf_ops: List[Dict[str, Any]], default: List[List[float]]) -> List[List[float]]:
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]

    def include_box(center: Vec3, half: Vec3) -> None:
        for i in range(3):
            mins[i] = min(mins[i], center[i] - half[i])
            maxs[i] = max(maxs[i], center[i] + half[i])

    for cmd in sdf_ops:
        name = str(cmd.get("cmd", "")).lower()
        center = _as_float3(cmd.get("center", [0.0, 0.0, 0.0]), (0.0, 0.0, 0.0))
        if name == "sphere":
            r = max(1e-6, float(cmd.get("radius", 0.5)))
            include_box(center, (r, r, r))
        elif name == "capsule":
            r = max(1e-6, float(cmd.get("radius", 0.1)))
            a = _as_float3(cmd.get("a", [0.0, 0.0, 0.0]), (0.0, 0.0, 0.0))
            b = _as_float3(cmd.get("b", [0.0, 0.0, 1.0]), (0.0, 0.0, 1.0))
            lo = (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]))
            hi = (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]))
            include_box(
                ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5),
                ((hi[0] - lo[0]) * 0.5 + r, (hi[1] - lo[1]) * 0.5 + r, (hi[2] - lo[2]) * 0.5 + r),
            )
        elif name == "box":
            sx, sy, sz = _as_float3(cmd.get("size", [1.0, 1.0, 1.0]), (1.0, 1.0, 1.0))
            include_box(center, (max(1e-6, sx * 0.5), max(1e-6, sy * 0.5), max(1e-6, sz * 0.5)))
        elif name == "cylinder":
            r = max(1e-6, float(cmd.get("radius", 0.5)))
            h = max(1e-6, float(cmd.get("height", cmd.get("depth", 1.0))))
            axis = str(cmd.get("axis", "z")).lower()
            if axis == "x":
                include_box(center, (h * 0.5, r, r))
            elif axis == "y":
                include_box(center, (r, h * 0.5, r))
            else:
                include_box(center, (r, r, h * 0.5))

    if not math.isfinite(mins[0]):
        return default

    span = [maxs[i] - mins[i] for i in range(3)]
    margin = max(0.02, max(span) * 0.15)
    return [[mins[0] - margin, mins[1] - margin, mins[2] - margin], [maxs[0] + margin, maxs[1] + margin, maxs[2] + margin]]


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
    has_explicit_bounds = "bounds" in params
    bounds = params.get("bounds", [[-2,-2,-2],[2,2,2]])
    if not has_explicit_bounds:
        bounds = _infer_sdf_bounds(resolved_ops, bounds)
    resolution = float(params.get("resolution", 0.15))
    method = str(params.get("method", "marching_cubes")).lower()
    for cmd in resolved_ops:
        if cmd.get("method") is not None:
            method = str(cmd.get("method", method)).lower()
        if str(cmd.get("cmd", "")).lower() == "mesh_from_sdf" and cmd.get("resolution") is not None:
            resolution = float(cmd["resolution"])
    if method in {"marching_cubes", "marching", "mc"}:
        base = sdf_to_marching_cubes_mesh(expr, bounds, resolution)
    elif method == "voxel":
        base = sdf_to_voxel_mesh(expr, bounds, resolution)
    else:
        base = sdf_to_voxel_mesh(expr, bounds, resolution)
    return base


def normalize_misplaced_assembly_anchors(scene: Scene) -> None:
    """Heuristic repair for malformed scenes where an assembly's anchors block is emitted on a child."""
    by_name = {o.name: o for o in scene.objects}
    children_by_parent: Dict[str, List[LiveObject]] = {}
    for o in scene.objects:
        p = o.meta.get("parent")
        if p:
            children_by_parent.setdefault(str(p), []).append(o)

    for asm in scene.objects:
        if str(asm.meta.get("source", "")) != "assembly":
            continue
        asm_name = asm.name
        asm_anchors = dict(asm.meta.get("anchors") or {})
        required: set[str] = set()
        for ch in children_by_parent.get(asm_name, []):
            spec = parse_attach_spec(ch.meta.get("attach"))
            if spec and spec[1] == asm_name:
                required.add(spec[2])
        missing = [a for a in required if a not in asm_anchors]
        if not missing:
            continue
        for ch in children_by_parent.get(asm_name, []):
            ch_anchors = ch.meta.get("anchors") or {}
            if not isinstance(ch_anchors, dict):
                continue
            moved_any = False
            for key in list(ch_anchors.keys()):
                if key in missing and key not in asm_anchors:
                    asm_anchors[key] = ch_anchors[key]
                    ch_anchors.pop(key, None)
                    moved_any = True
            if moved_any:
                ch.meta["anchors"] = ch_anchors
        if asm_anchors:
            asm.meta["anchors"] = asm_anchors


def generate_simulation(obj: LiveObject, obn: Optional[Dict[str, LiveObject]] = None) -> Mesh:
    sim = str(obj.meta.get("sim", ""))
    params = obj.meta.get("params", {}) or {}

    if sim == "cellular_automata":
        return cellular_automata_mesh(params)
    if sim == "cellular_automata_instances":
        return cellular_automata_instances_mesh(params, obn)
    if sim == "differential_growth":
        return differential_growth_mesh(params)
    if sim == "differential_growth_stack":
        return differential_growth_stack_mesh(params, obn)
    if sim == "boids":
        return boids_mesh(params)
    if sim == "flow_field":
        return flow_field_mesh(params)

    return obj.mesh.copy()


def is_curve_path_reference(obj: LiveObject, obn: Dict[str, LiveObject]) -> bool:
    if is_explicitly_visible(obj):
        return False
    if str(obj.meta.get("source", "")).lower() != "procedural":
        return False
    if str(obj.meta.get("type", "")).lower() != "curve":
        return False
    for other in obn.values():
        if other is obj:
            continue
        if str(other.meta.get("source", "")).lower() != "procedural":
            continue
        if str(other.meta.get("type", "")).lower() == "sweep":
            params = other.meta.get("params", {}) or {}
            if isinstance(params, dict) and str(params.get("along", "")).strip() == obj.name:
                return True
        for op in other.ops:
            if str(op.get("cmd", "")).lower() == "sweep" and str(op.get("along", "")).strip() == obj.name:
                return True
    return False


def is_metadata_only_curve_reference(obj: LiveObject, obn: Dict[str, LiveObject]) -> bool:
    if not (is_render_hidden(obj) or is_curve_path_reference(obj, obn)):
        return False
    if str(obj.meta.get("source", "")).lower() != "procedural":
        return False
    if str(obj.meta.get("type", "")).lower() != "curve":
        return False
    params = obj.meta.get("params", {}) or {}
    if not isinstance(params, dict):
        return False
    return any(k in params for k in ("points", "boundary_points", "contour_points", "profile_points", "kind"))


def execute_scene(scene: Scene) -> Scene:
    obn: Dict[str, LiveObject] = {o.name: o for o in scene.objects}
    kernel_default = ""
    for line in scene.header_lines:
        t = line.strip()
        if t.startswith("#@kernel_default:"):
            kernel_default = t.split(":", 1)[1].strip().lower()
            break
        elif t.startswith("#@material_preset:"):
            preset_line = t.split(":", 1)[1].strip()
            parts = preset_line.split()
            if parts:
                name = parts[0]
                params = parse_key_values(" ".join(parts[1:]))
                scene.materials[name] = params
    normalize_misplaced_assembly_anchors(scene)
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
            resolved_params = get_effective_params(obj, obn)
            metadata_only_curve = is_metadata_only_curve_reference(obj, obn)
            if kernel_default and not metadata_only_curve and not str(resolved_params.get("kernel", "")).strip():
                resolved_params["kernel"] = kernel_default
            obj.meta["params"] = resolved_params
            try:
                if metadata_only_curve:
                    base = Mesh()
                else:
                    base = generate_procedural(obj, obn)
                    base = apply_meta_instancing(base, obj, obn)
            finally:
                if oldp is not None:
                    obj.meta["params"] = oldp
        elif source == "sdf":
            base = generate_sdf(obj, obn)
        elif source == "simulation":
            base = generate_simulation(obj, obn)
        elif source == "recipe":
            base = generate_recipe(obj, obn)
        else:
            base = obj.mesh.copy()

        obj.mesh = apply_ops(base, obj, obn, kernel_default)

    apply_attach_constraints(scene)

    return scene


def serialize_scene(scene: Scene) -> str:
    lines: List[str] = []
    lines.extend(scene.header_lines)
    # Remove trailing empty lines from header
    while lines and not lines[-1].strip():
        lines.pop()
    existing_materials = set()
    for line in lines:
        t = line.strip()
        if t.startswith("#@material_preset:"):
            parts = t.split(":", 1)[1].strip().split()
            if parts:
                existing_materials.add(parts[0])
    # Output material presets
    for name, params in scene.materials.items():
        if name in existing_materials:
            continue
        param_str = " ".join([f"{k}={v}" for k, v in params.items()])
        lines.append(f"#@material_preset: {name} {param_str}")
    global_index = 1
    first_object = True
    obn: Dict[str, LiveObject] = {o.name: o for o in scene.objects}

    for obj in scene.objects:
        # Only add empty line before object if it's not the first object
        if not first_object:
            lines.append("")
        first_object = False

        lines.append(f"{obj.declaration} {obj.name}")
        # Filter out old runtime debug messages
        lines.extend([l for l in obj.meta_lines if not l.strip().startswith("#@runtime:")])

        # Keep hidden/helper objects editable in the executed source, but do not
        # serialize their geometry. The UI can still expose their metadata while
        # the canvas has no v/f cache to render for them.
        if is_render_hidden(obj) or is_curve_path_reference(obj, obn):
            continue

        # Add material metadata if present
        material_name = obj.meta.get("material")
        if material_name and material_name in scene.materials:
            lines.append(f"#@material: {material_name}")
        events = obj.meta.get("_kernel_events", [])
        if isinstance(events, list) and events:
            lines.append(f"#@runtime: kernel_used=true, events={events}")
        # Filter out old runtime debug messages from raw lines as well
        for l in obj.raw_nonlive_lines:
            if l.strip() and not l.strip().startswith("#@runtime:"):
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

    # Count only non-helper objects for output stats
    obn = {o.name: o for o in scene.objects}
    visible_objects = [o for o in scene.objects if not (is_render_hidden(o) or is_curve_path_reference(o, obn))]
    print(f"Wrote {output}")
    print(f"Objects: {len(visible_objects)}")
    print(f"Vertices: {sum(len(o.mesh.vertices) for o in visible_objects)}")
    print(f"Faces: {sum(len(o.mesh.faces) for o in visible_objects)}")


if __name__ == "__main__":
    main()
