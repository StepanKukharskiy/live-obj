# Spellshape Grasshopper - Decomposed Raw OBJ Builder
# Release date: 2026-05-17
# License: MIT
# Source: https://github.com/StepanKukharskiy/live-obj
#
# Network behavior:
# - Calls the selected LLM provider directly from this machine.
# - Does not call Spellshape servers.
# - Does not send telemetry from this script.
# - Never paste/share a GH file with a filled API key panel.
#
# Prompt source of truth:
# - Planner and part-generation prompts are synced from the web app TypeScript
#   prompt constants by scripts/sync_ghpython_prompts.py.
#
# Inputs to create:
#   plan_run       bool  button: create a part plan from prompt
#   next_run       bool  button: generate and append the next planned part
#   auto_run       bool  toggle: keep generating one remaining part per solution
#   auto_delay_ms  int   optional delay between automatic parts, default 250
#   reset          bool  button: clear plan and scene memory
#   provider       str   openai, openrouter, anthropic, google, gemini, custom
#   api_key        str
#   model          str   optional
#   prompt         str   scene request
#   base_url       str   optional for OpenAI-compatible custom providers
#   max_tokens     int   optional, default 16000
#   timeout_sec    int   optional HTTP timeout, default 300
#
# Outputs to create:
#   current_obj
#   plan_json
#   parts
#   active_part
#   progress
#   status
#   error
#   debug
#
# Workflow:
#   1. Set prompt, press plan_run.
#   2. Press next_run repeatedly, or set auto_run=True.
#   3. Wire current_obj into the Live OBJ render GHPython node.
#   4. Press reset to start a new decomposed scene.

import json
import re
import System
import scriptcontext as sc
from System.IO import StreamReader
from System.Net import WebRequest, ServicePointManager, SecurityProtocolType
from System.Text import Encoding


DEFAULT_HEADER = "#@live_obj_version: 0.1\n#@up: y\n"


PLANNER_PROMPT = '''You are the planner for an AI-native Live OBJ modeling pipeline.

Decompose the requested scene into a build queue of semantic parts. Do not generate geometry.
The next system stage will ask for each part as a separate Live OBJ object/group and append it to the scene.

Return only JSON with this shape:
{
  "scene": "short scene description",
  "units": "meters",
  "up": "y",
  "materials": [
    { "id": "material_id", "color": "#RRGGBB", "roughness": 0.7, "metalness": 0, "role": "short role" }
  ],
  "parts": [
    {
      "id": "stable_object_or_group_id",
      "role": "what this part contributes",
      "method": "llm_mesh",
      "dependencies": ["prior_part_id"],
      "prompt": "specific instructions for generating only this part",
      "validationHints": ["bbox/contact/detail expectations"]
    }
  ],
  "notes": ["global composition notes"]
}

Planning rules:
- Prefer 5-8 parts for rich scenes; fewer for simple objects.
- First pass should be compact semantic massing: major ground/support, primary structure, main envelope/shell, major infill/openings, and one restrained interior/context part only when important.
- Build from coarse support/massing to envelope, structure, major infill, then one optional accent/detail part.
- Merge related elements into one part instead of producing many small parts.
- Do not plan separate first-pass parts for seams, fasteners, bolts, handles, bollards, expansion joints, connection plates, tiny context objects, or micro facade details unless the user explicitly asks for them.
- Make dependencies explicit so later parts can align to earlier geometry.
- Use y as the vertical/up axis unless the user explicitly asks otherwise.
- Plan raw mesh parts. Each part method must be "llm_mesh".
- Do not use method values "procedural", "recipe", or "hybrid" in this iterative raw OBJ planner.
- Do not invent executor operations. The default generation method is llm_mesh with semantic metadata and optional generic post notes.
- If the user asks for controls, sliders, parameters, adjustable dimensions, or editability, preserve that requirement in the relevant part prompts. Do not treat metadata controls as forbidden UI objects.
- In this Grasshopper decomposed builder, every planned part should expose 2-5 practical Grasshopper controls by default. Add that requirement to each part prompt using #@params and #@controls metadata, with every control referenced by executable #@post syntax.
- Use stable snake_case ids.'''


PART_SYSTEM_PROMPT = '''You generate one raw OBJ part for an iterative scene builder.

Return only OBJ text for the requested part. Do not return JSON, Markdown, a scene header, or explanations.

Critical OBJ indexing rule:
- Use local vertex numbering in your returned part. The first vertex you emit is v 1 for face purposes.
- Face lines must reference only vertices defined in this returned part, starting at 1.
- The server will remap indices when appending to the full scene.

Raw-first part rules:
- Use #@source: llm_mesh for the generated object/group.
- Include #@editable, #@semantic, #@part, #@part_of, and #@depends_on metadata where useful.
- Use #@bbox: min=[x,y,z] max=[x,y,z] when the intended extents are clear.
- Use #@lock: footprint, position, silhouette, material when future edits should preserve those properties.
- Use #@anchor: id=anchor_id at=[x,y,z] for meaningful connection, contact, edge, support, hinge, or alignment points.
- Use #@constraint: as soft edit intent only, such as roof must_touch walls or object must_rest_on_ground.
- Use #@variant: id=base name="Base" when a generated part is one named concept alternative.
- Generate only the requested part, not the whole scene.
- Fit the part to the existing scene summary and dependencies.
- Use y as the vertical/up axis unless the current scene summary says otherwise.
- Keep geometry compact and clean: target 20-90 vertices for ordinary parts and at most about 160 vertices for a main shell. Use simple topology for the first pass; use #@post smooth/subdivide when a softer surface is intended.
- Match topology to visible intent: if the requested visual property cannot be produced by supported executable #@post syntax, bake it into the raw v/f mesh with enough vertices/faces for the effect to be visible. Do not satisfy visible geometry requests only with object names, #@semantic, #@tag, material names, or unsupported #@post attributes.
- Prefer quads and simple polygons. Avoid dense grids, seam networks, individual fasteners, tiny bolts, repeated micro-panels, or context clutter in the first pass.
- Every raw mesh object or group with vertices must include faces for those vertices. Do not emit vertices-only logs, rings, lattices, supports, or roof members.
- If you create multiple log cylinders or beams in one object, include the side faces and cap faces for every member. Do not list only section rings or endpoints.
- Avoid usemtl-only groups. A group is useful only when it contains renderable faces.
- Use #@post: for raw-post modifier intent. Supported #@post ops are transform, symmetrize, mirror, array, deform, subdivide, smooth, simplify, snap_to_ground, center_origin, material, and tag.
- For repeated modules, #@post array supports per-copy expressions in scale, position, and pivot using i, index, step, count, t, sin(), cos(), min(), max(), abs(), sqrt(), pi, and tau.
- For per-vertex edits, #@post deform supports position=[x,y,z] expressions with x/y/z, normalized u/v/w bbox coordinates, i/index, t, vertex_count, params, and the same math functions.
- Prefer #@post symmetrize for bilaterally symmetric forms and #@post smooth/subdivide for fluid surfaces.
- If the user request, plan, or part prompt asks for controls, include #@params: and #@controls: metadata for meaningful dimensions. Every control key must be referenced by executable #@post metadata such as transform, array, mirror/symmetrize, smooth, subdivide, simplify, snap_to_ground, or center_origin. For raw v/f meshes, use controls for object-level scale, height, spacing, count, smoothing, or placement rather than pretending baked vertex coordinates are parametric.
- Parameter references in #@post expressions must use bare names such as voxel_size or (voxel_size*grid_width)/10. Never use template placeholder syntax such as dollar-brace or curly-brace parameter wrappers.
- Put material and tag assignments inside #@post blocks. Do not use #@ops in raw-first mode.
- Always use block syntax: #@post: then lines like #@ - material name=mat_id. Do not emit inline #@post material id=... lines.'''


SUPPORTED_POST_OPS = set([
    "transform",
    "symmetrize",
    "mirror",
    "array",
    "deform",
    "subdivide",
    "smooth",
    "simplify",
    "snap_to_ground",
    "center_origin",
    "material",
    "tag",
])

SUPPORTED_POST_ATTRS = {
    "transform": set(["position", "rotation", "scale", "pivot"]),
    "symmetrize": set(["axis", "side", "tolerance"]),
    "mirror": set(["axis"]),
    "array": set(["count", "offset", "centered", "center", "scale", "position", "pivot"]),
    "deform": set(["position", "expr", "xyz"]),
    "subdivide": set(["level"]),
    "smooth": set(["iterations", "strength"]),
    "simplify": set(["ratio"]),
    "snap_to_ground": set(["axis"]),
    "center_origin": set(["axes"]),
    "material": set(["name"]),
    "tag": set(["value"]),
}


POST_REPAIR_PROMPT = '''You repair one raw OBJ part for the Spellshape Live OBJ executor.

Return only complete OBJ text for the same part. Do not return Markdown or explanations.
Preserve the object's geometry, object names, metadata, faces, and material intent.
Fix only invalid #@post syntax reported by the executor validation.

Supported #@post operations:
- transform position=[x,y,z] rotation=[rx,ry,rz] scale=[sx,sy,sz] pivot=[x,y,z]
- symmetrize axis=x|y|z side=positive|negative tolerance=0.000001
- mirror axis=x|y|z
- array count=n offset=[x,y,z] centered=true|false scale=[sx,sy,sz] position=[x,y,z] pivot=[x,y,z]
- deform position=[x,y,z]
- subdivide level=n
- smooth iterations=n strength=0.5
- simplify ratio=0.5
- snap_to_ground axis=x|y|z
- center_origin axes=xz|xy|yz|xyz
- material name=material_id
- tag value=tag_text

Important:
- smooth uses iterations=, not level=.
- subdivide uses level=.
- material uses name= only. Do not include target=, object=, id=, color=, roughness=, or metalness=.
- transform uses position=, rotation=, scale=, and optional pivot=. Do not use target=, origin=, translate=, rotate=, rotate_y=, axis=, spacing=, or mode=.
- Unsupported visible behavior must be baked into v/f geometry rather than described with unsupported #@post attributes.
- Always use block syntax: #@post: then #@ - operation args...'''


CONTROL_REPAIR_PROMPT = '''You repair one raw OBJ part for the Spellshape Grasshopper renderer.

Return only complete OBJ text for the same part. Do not return Markdown or explanations.
Preserve the object's geometry, object names, faces, material intent, and role.
This Grasshopper decomposed-builder part requires controls, but it did not include #@controls metadata.

Add minimal useful controls using:
#@params: key=value, key=value
#@controls:
#@ - slider key=key label=Readable_label min=a max=b step=c

Rules:
- Every control key must be referenced by executable #@post metadata.
- For raw v/f meshes, useful controls are object scale, height, width/depth, vertical exaggeration, smoothing, array count/spacing, or placement.
- Parameter references in #@post expressions must use bare names such as tree_scale or (voxel_size*grid_width)/10.
- Never use template syntax like ${tree_scale}, {tree_scale}, or ${voxel_size}.
- Do not create controls that only sit in #@params without affecting geometry.
- Keep controls small and practical.'''


def safe_str(value, fallback=""):
    if value is None:
        return fallback
    return str(value)


def input_value(name, fallback=None):
    try:
        return globals().get(name, fallback)
    except Exception:
        return fallback


def bool_input(name, fallback=False):
    return bool(input_value(name, fallback))


def key(name):
    try:
        guid = str(ghenv.Component.InstanceGuid)
    except Exception:
        guid = "default"
    return "spellshape_decomposed:%s:%s" % (guid, name)


def get_mem(name, fallback=""):
    return sc.sticky.get(key(name), fallback)


def set_mem(name, value):
    sc.sticky[key(name)] = value


def button_pressed(name):
    now = bool_input(name, False)
    last_key = key("last_input:" + name)
    was = bool(sc.sticky.get(last_key, False))
    sc.sticky[last_key] = now
    return now and not was


def clear_mem():
    for name in ("current_obj", "plan_json", "part_index", "last_raw", "last_part", "scene_prompt"):
        set_mem(name, "" if name != "part_index" else 0)


def set_message(text):
    try:
        ghenv.Component.Message = text
    except Exception:
        pass


def schedule_next(delay_ms):
    try:
        doc = ghenv.Component.OnPingDocument()
        if doc is not None:
            doc.ScheduleSolution(int(delay_ms), lambda d: ghenv.Component.ExpireSolution(False))
    except Exception:
        pass


def parse_max_tokens(value):
    try:
        n = int(value)
    except Exception:
        n = 16000
    return max(512, min(16000, n))


def parse_timeout_ms(value):
    try:
        seconds = int(value)
    except Exception:
        seconds = 300
    seconds = max(30, min(900, seconds))
    return seconds * 1000


def normalize_base_url(url):
    url = safe_str(url).strip()
    if not url:
        return ""
    if url.lower().endswith("/chat/completions"):
        url = url[:-len("/chat/completions")]
    return url.rstrip("/")


def post_json(url, headers, payload):
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
    except Exception:
        pass

    body = json.dumps(payload)
    data = Encoding.UTF8.GetBytes(body)
    req = WebRequest.Create(url)
    req.Method = "POST"
    req.ContentType = "application/json"
    req.ContentLength = data.Length
    timeout_ms = parse_timeout_ms(input_value("timeout_sec", None))
    try:
        req.Timeout = timeout_ms
        req.ReadWriteTimeout = timeout_ms
    except Exception:
        pass
    for k, v in headers.items():
        req.Headers[k] = v
    stream = req.GetRequestStream()
    try:
        stream.Write(data, 0, data.Length)
    finally:
        stream.Close()

    try:
        resp = req.GetResponse()
        reader = StreamReader(resp.GetResponseStream())
        try:
            return reader.ReadToEnd()
        finally:
            reader.Close()
            resp.Close()
    except System.Net.WebException as ex:
        resp = ex.Response
        if resp is None:
            raise
        reader = StreamReader(resp.GetResponseStream())
        try:
            detail = reader.ReadToEnd()
        finally:
            reader.Close()
            resp.Close()
        raise Exception("HTTP request failed: " + detail)


def use_max_completion_tokens(provider_name, base_url, model_name):
    provider_name = safe_str(provider_name).lower()
    base_url = safe_str(base_url).lower()
    model_name = safe_str(model_name).lower()
    return provider_name == "openai" or "api.openai.com" in base_url or model_name.startswith("gpt-5") or model_name.startswith("o1") or model_name.startswith("o3") or model_name.startswith("o4")


def call_openai_compatible(provider_name, api_key, model_name, system_prompt, user_prompt, base_url, max_tokens):
    base = normalize_base_url(base_url)
    if not base:
        base = "https://openrouter.ai/api/v1" if provider_name == "openrouter" else "https://api.openai.com/v1"
    endpoint = base + "/chat/completions"
    if not model_name:
        model_name = "openai/gpt-4.1-mini" if provider_name == "openrouter" else "gpt-4.1-mini"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if use_max_completion_tokens(provider_name, base, model_name):
        payload["max_completion_tokens"] = max_tokens
    else:
        payload["max_tokens"] = max_tokens
    headers = {"Authorization": "Bearer " + api_key}
    if provider_name == "openrouter":
        headers["HTTP-Referer"] = "https://spellshape.local"
        headers["X-Title"] = "Spellshape Grasshopper"
    return post_json(endpoint, headers, payload)


def call_anthropic(api_key, model_name, system_prompt, user_prompt, max_tokens):
    if not model_name:
        model_name = "claude-3-5-sonnet-latest"
    payload = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    return post_json("https://api.anthropic.com/v1/messages", {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }, payload)


def call_google(api_key, model_name, system_prompt, user_prompt, max_tokens):
    if not model_name:
        model_name = "gemini-2.5-flash"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model_name
    return post_json(url, {"x-goog-api-key": api_key}, payload)


def call_provider(provider_name, api_key, model_name, system_prompt, user_prompt, base_url, max_tokens):
    provider_name = safe_str(provider_name, "openai").strip().lower()
    if provider_name == "anthropic":
        return call_anthropic(api_key, model_name, system_prompt, user_prompt, max_tokens)
    if provider_name in ("google", "gemini"):
        return call_google(api_key, model_name, system_prompt, user_prompt, max_tokens)
    return call_openai_compatible(provider_name, api_key, model_name, system_prompt, user_prompt, base_url, max_tokens)


def extract_text(provider_name, raw):
    try:
        root = json.loads(raw)
    except Exception:
        return raw
    provider_name = safe_str(provider_name).lower()
    if provider_name == "anthropic":
        return "".join([p.get("text", "") for p in root.get("content", []) if isinstance(p, dict)])
    if provider_name in ("google", "gemini"):
        candidates = root.get("candidates", [])
        if not candidates:
            return raw
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join([p.get("text", "") for p in parts if isinstance(p, dict)])
    choices = root.get("choices", [])
    if not choices:
        return raw
    content = choices[0].get("message", {}).get("content", "")
    return content or raw


def strip_code_fence(text):
    text = safe_str(text).strip()
    if not text.startswith("```"):
        return text
    first = text.find("\n")
    last = text.rfind("```")
    if first >= 0 and last > first:
        return text[first + 1:last].strip()
    return text


def parse_json_object(text):
    clean = strip_code_fence(text)
    try:
        return json.loads(clean)
    except Exception:
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            return json.loads(clean[start:end + 1])
        raise


def count_vertices(text):
    return len([l for l in safe_str(text).splitlines() if re.match(r"^\s*v\s+", l)])


def count_faces(text):
    return len([l for l in safe_str(text).splitlines() if re.match(r"^\s*f\s+", l)])


def split_part_text(raw_part):
    clean = normalize_generated_part_metadata(raw_part)
    lines = clean.splitlines()
    first_obj = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*o\s+", line):
            first_obj = i
            break
    if first_obj < 0:
        raise Exception("Generated part did not contain an object line: o name")
    preamble = []
    object_metadata = []
    for line in lines[:first_obj]:
        if re.match(r"^\s*#@material_preset:\s+", line):
            preamble.append(line)
        elif re.match(r"^\s*#@", line):
            object_metadata.append(line)
    obj_lines = list(lines[first_obj:])
    if object_metadata:
        obj_lines = [obj_lines[0]] + object_metadata + obj_lines[1:]
    obj_text = "\n".join(obj_lines).strip()
    return preamble, obj_text


def face_refs(line):
    if not re.match(r"^\s*[fl]\s+", line):
        return []
    out = []
    for token in line.strip().split()[1:]:
        head = token.split("/")[0]
        try:
            out.append(int(head))
        except Exception:
            pass
    return out


def remap_token(token, vertex_offset, local_offset):
    parts = token.split("/")
    try:
        n = int(parts[0])
    except Exception:
        return token
    if n <= 0:
        return token
    parts[0] = str(n - local_offset + vertex_offset)
    return "/".join(parts)


def remap_part_faces(obj_text, vertex_offset):
    local_count = count_vertices(obj_text)
    refs = []
    for line in obj_text.splitlines():
        refs.extend(face_refs(line))
    max_ref = max(refs) if refs else 0
    min_ref = min(refs) if refs else 1
    local_offset = 0
    if max_ref > local_count and min_ref > 1:
        proposed = min_ref - 1
        if all((r - proposed) >= 1 and (r - proposed) <= local_count for r in refs):
            local_offset = proposed
    if max_ref - local_offset > local_count:
        raise Exception("Generated part uses face index %s but only defines %s vertices" % (max_ref, local_count))
    out = []
    for line in obj_text.splitlines():
        if not re.match(r"^\s*[fl]\s+", line):
            out.append(line)
            continue
        tokens = line.strip().split()
        out.append(" ".join([tokens[0]] + [remap_token(t, vertex_offset, local_offset) for t in tokens[1:]]))
    return "\n".join(out)


def material_ids(text):
    return set(re.findall(r"^\s*#@material_preset:\s+([^\s]+)", safe_str(text), re.M))


def first_post_attribute_value(body, keys):
    for attr in keys:
        m = re.search(r"(?:^|\s)%s\s*=\s*(\"[^\"]+\"|'[^']+'|[^\s]+)" % re.escape(attr), safe_str(body), re.I)
        if not m:
            continue
        return m.group(1).strip().strip("\"'")
    return ""


def normalize_material_post_line(raw_line):
    block = re.match(r"^(\s*)#@\s*-\s*material\b(.*)$", safe_str(raw_line), re.I)
    if block:
        material_name = first_post_attribute_value(block.group(2), ["name", "id"])
        if material_name:
            return [block.group(1) + "#@ - material name=" + material_name]
        return None
    inline = re.match(r"^(\s*)#@post\s+material\b(.*)$", safe_str(raw_line), re.I)
    if inline:
        material_name = first_post_attribute_value(inline.group(2), ["name", "id"])
        if material_name:
            indent = inline.group(1)
            return [indent + "#@post:", indent + "#@ - material name=" + material_name]
        return None
    return None


def normalize_generated_part_metadata(raw_part):
    lines = []
    for line in strip_code_fence(raw_part).splitlines():
        normalized = normalize_material_post_line(line)
        if normalized is None:
            lines.append(line)
        else:
            lines.extend(normalized)
    return "\n".join(lines)


def insert_materials(scene_text, preamble):
    existing = material_ids(scene_text)
    additions = []
    for line in preamble:
        m = re.match(r"^\s*#@material_preset:\s+([^\s]+)", line)
        if m and m.group(1) not in existing:
            additions.append(line)
    if not additions:
        return scene_text
    lines = scene_text.splitlines()
    first_obj = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*o\s+", line):
            first_obj = i
            break
    if first_obj < 0:
        return scene_text.rstrip() + "\n" + "\n".join(additions) + "\n"
    return "\n".join(lines[:first_obj] + additions + lines[first_obj:]) + "\n"


def append_part(scene_text, raw_part):
    base = safe_str(scene_text).strip()
    if not base:
        base = DEFAULT_HEADER.strip()
    preamble, obj_text = split_part_text(raw_part)
    remapped = remap_part_faces(obj_text, count_vertices(base))
    with_materials = insert_materials(base + "\n", preamble)
    return with_materials.rstrip() + "\n\n" + remapped.strip() + "\n", remapped


def split_scene_blocks(scene_text):
    lines = safe_str(scene_text).splitlines()
    first_obj = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*o\s+", line):
            first_obj = i
            break
    if first_obj < 0:
        return "\n".join(lines).rstrip(), []
    header = "\n".join(lines[:first_obj]).rstrip()
    blocks = []
    start = first_obj
    for i in range(first_obj + 1, len(lines)):
        if re.match(r"^\s*o\s+", lines[i]):
            block = "\n".join(lines[start:i]).strip()
            name = lines[start].strip().split(None, 1)[1].strip()
            blocks.append((name, block))
            start = i
    block = "\n".join(lines[start:]).strip()
    if block:
        name = lines[start].strip().split(None, 1)[1].strip()
        blocks.append((name, block))
    return header, blocks


def object_names(scene_text):
    return [name for name, _ in split_scene_blocks(scene_text)[1]]


def has_scene_objects(scene_text):
    return len(object_names(scene_text)) > 0


def normalize_scene_indices(scene_text):
    header, blocks = split_scene_blocks(scene_text)
    if not blocks:
        return safe_str(scene_text).strip() + "\n"
    out = [header] if header else []
    vertex_offset = 0
    normalized_blocks = []
    for name, block in blocks:
        remapped = remap_part_faces(block, vertex_offset)
        normalized_blocks.append(remapped.strip())
        vertex_offset += count_vertices(remapped)
    return "\n\n".join(out + normalized_blocks).strip() + "\n"


def replace_part(scene_text, raw_part, target_name):
    base = safe_str(scene_text).strip() or DEFAULT_HEADER.strip()
    preamble, obj_text = split_part_text(raw_part)
    with_materials = insert_materials(base + "\n", preamble)
    header, blocks = split_scene_blocks(with_materials)
    if not target_name:
        target_name = split_scene_blocks(obj_text)[1][0][0]
    replaced = False
    out_blocks = []
    for name, block in blocks:
        if name == target_name:
            out_blocks.append(obj_text.strip())
            replaced = True
        else:
            out_blocks.append(block.strip())
    if not replaced:
        out_blocks.append(obj_text.strip())
    return normalize_scene_indices("\n\n".join(([header] if header else []) + out_blocks)), obj_text.strip()


def part_target(part):
    for key_name in ("target", "target_object", "object", "object_id", "id"):
        value = part.get(key_name)
        if value:
            return safe_str(value).strip()
    return ""


def part_action(part, current_scene):
    action = safe_str(part.get("action") or part.get("operation") or part.get("mode"), "").strip().lower()
    target = part_target(part)
    if action in ("replace", "modify", "update", "regenerate", "edit"):
        return "replace", target
    if action in ("append", "add", "create", "new"):
        return "append", target
    if target and target in object_names(current_scene):
        return "replace", target
    return "append", target


def summarize_scene(scene_text):
    names = re.findall(r"^\s*o\s+([^\s#]+)", safe_str(scene_text), re.M)
    return "objects=%s vertices=%d faces=%d" % (", ".join(names[-12:]) if names else "(none)", count_vertices(scene_text), count_faces(scene_text))


def part_list(plan):
    try:
        return plan.get("parts", [])
    except Exception:
        return []


def build_part_prompt(plan, part, current_scene, original_request=""):
    action, target = part_action(part, current_scene)
    return "\n".join([
        "Original user request: " + (safe_str(original_request).strip() or "Generate the requested part"),
        "",
        "Requested part spec:",
        json.dumps(part, indent=2),
        "",
        "Overall part plan:",
        json.dumps(plan, indent=2),
        "",
        "Current scene summary:",
        summarize_scene(current_scene) or "(empty scene)",
        "",
        "Execution action:",
        action + ((" target=" + target) if target else ""),
        "",
        "If the action is replace, return one complete OBJ block for the target object. Keep the target object name stable.",
        "",
        "Grasshopper control policy:",
        "Include #@params: and #@controls: metadata for 2-5 meaningful part controls by default.",
        "Use canonical control syntax:",
        "#@controls:",
        "#@ - slider key=scale label=Scale min=0.5 max=2.0 step=0.05",
        "Every control key must be referenced by executable #@post syntax. Prefer transform scale/position with pivot, array count/offset, deform position, smooth iterations/strength, simplify ratio, or center_origin.",
        "Do not emit unsupported #@post attributes such as target=, origin=, translate=, rotate_y=, axis= for array spacing, or mode=.",
        "",
        "Generate only the requested part now.",
    ])


def request_mentions_controls(text):
    text = safe_str(text).lower()
    return any(word in text for word in [
        "control",
        "controls",
        "slider",
        "sliders",
        "parametric",
        "parameter",
        "parameters",
        "adjustable",
        "editable",
    ])


def has_controls_metadata(text):
    return re.search(r"^\s*#@controls\s*:", safe_str(text), re.M) is not None


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


def parse_post_line(text):
    parts = split_top_level_spaces(text)
    if not parts:
        return "", {}
    args = {}
    for token in parts[1:]:
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        k = k.strip().lower()
        if k:
            args[k] = v.strip()
    return parts[0].strip().lower(), args


def validate_post_line(text, object_name):
    cmd, args = parse_post_line(text)
    if not cmd:
        return []
    label = object_name or "object"
    issues = []
    if cmd not in SUPPORTED_POST_OPS:
        issues.append("%s: unsupported #@post operation '%s'" % (label, cmd))
        return issues
    allowed_attrs = SUPPORTED_POST_ATTRS.get(cmd, set())
    for key, value in args.items():
        if key not in allowed_attrs:
            issues.append("%s: unsupported #@post %s attribute '%s'" % (label, cmd, key))
        if re.search(r"\$\{[^}]+\}", value) or re.search(r"(?<!\[)\{[A-Za-z_][A-Za-z0-9_]*\}", value):
            issues.append("%s: #@post %s uses template placeholder syntax in %s=%s; use bare parameter names instead" % (label, cmd, key, value))
    if cmd == "smooth" and "level" in args and "iterations" not in args:
        issues.append("%s: smooth uses level=, but the executor expects smooth iterations=n strength=0.5" % label)
    if cmd == "tag" and "name" in args and "value" not in args:
        issues.append("%s: tag uses name=, but the executor contract expects tag value=..." % label)
    if cmd == "deform" and not ("position" in args or "expr" in args or "xyz" in args):
        issues.append("%s: deform expects position=[x,y,z]" % label)
    if cmd == "snap_to_ground" and ("surface" in args or "anchor" in args):
        issues.append("%s: snap_to_ground only supports axis=x|y|z; contact-to-surface placement is not supported in #@post" % label)
    return issues


def post_op_issues(obj_text):
    issues = []
    block = None
    object_name = "object"
    for raw in safe_str(obj_text).splitlines():
        line = raw.strip()
        if re.match(r"^\s*o\s+", raw):
            object_name = raw.strip().split(None, 1)[1].strip()
            block = None
            continue
        if not line.startswith("#@"):
            continue
        body = line[2:].strip()
        if body == "post:":
            block = "post"
            continue
        if body.startswith("post "):
            issues.extend(validate_post_line(body[len("post "):].strip(), object_name))
            block = None
            continue
        if body.endswith(":") and not body.startswith("-"):
            block = None
            continue
        if block == "post" and body.startswith("-"):
            issues.extend(validate_post_line(body[1:].strip(), object_name))
            continue
        if ":" in body and not body.startswith("-"):
            block = None
    return issues


def build_post_repair_prompt(part_text, issues):
    return "\n".join([
        "The previous raw OBJ part has invalid #@post syntax.",
        "Repair the #@post lines and return the full corrected OBJ part only.",
        "",
        "Validation issues:",
        "\n".join(["- " + issue for issue in issues]),
        "",
        "OBJ part to repair:",
        safe_str(part_text),
    ])


def repair_post_ops_if_needed(provider_name, api_key, model_name, part_text, base_url, max_out):
    issues = post_op_issues(part_text)
    if not issues:
        return part_text, []
    raw_repair = call_provider(
        provider_name,
        api_key,
        model_name,
        POST_REPAIR_PROMPT,
        build_post_repair_prompt(part_text, issues),
        base_url,
        max_out,
    )
    repaired = extract_text(provider_name, raw_repair)
    repaired = strip_code_fence(repaired)
    remaining = post_op_issues(repaired)
    if remaining:
        raise Exception("Generated part still has invalid #@post syntax after repair: " + "; ".join(remaining[:4]))
    return repaired, issues


def repair_controls_if_needed(provider_name, api_key, model_name, part_text, part, original_request, base_url, max_out):
    if has_controls_metadata(part_text):
        return part_text, False
    prompt = "\n".join([
        "Original user request:",
        safe_str(original_request) or "Generate the requested part",
        "",
        "Part plan:",
        json.dumps(part),
        "",
        "OBJ part to repair:",
        safe_str(part_text),
    ])
    raw_repair = call_provider(
        provider_name,
        api_key,
        model_name,
        CONTROL_REPAIR_PROMPT,
        prompt,
        base_url,
        max_out,
    )
    repaired = strip_code_fence(extract_text(provider_name, raw_repair))
    if not has_controls_metadata(repaired):
        raise Exception("Generated part still has no #@controls metadata after repair")
    return repaired, True


def visible_part_validation_issues(part_text):
    issues = []
    try:
        _, obj_text = split_part_text(part_text)
    except Exception as e:
        return [str(e)]
    blocks = split_scene_blocks(obj_text)[1]
    if not blocks:
        issues.append("No OBJ objects found")
    for name, block in blocks:
        vertices = count_vertices(block)
        faces = count_faces(block)
        if not has_controls_metadata(block):
            issues.append("Object '%s' is missing required #@controls metadata" % name)
        if vertices > 0 and faces == 0:
            issues.append("Object '%s' defines %d vertices but no faces, so it will not render" % (name, vertices))
        for line_no, line in enumerate(block.splitlines(), 1):
            if not re.match(r"^\s*f\s+", line):
                continue
            refs = face_refs(line)
            if len(refs) < 3:
                issues.append("Object '%s' has a face with fewer than 3 vertices near local line %d" % (name, line_no))
    issues.extend(post_op_issues(obj_text))
    return issues


def build_append_repair_hint(raw_part, append_error):
    return "\n".join([
        "Your previous OBJ part was invalid and could not be appended.",
        "Append error: " + safe_str(append_error),
        "Return the same requested part again as valid OBJ/Live OBJ only.",
        "The response must contain at least one OBJ object line like `o main_body` before any mesh vertices.",
        "Use local face indices starting at 1 for this returned part.",
        "Every visible raw mesh object/group with vertices must include faces.",
        "For #@post material, use only name=material_id. Do not include object=, target=, id=, color=, roughness, or metalness on the material op.",
        "Do not return the plan JSON, scene JSON, Markdown, or explanations.",
        "Previous invalid output:",
        safe_str(raw_part)[-12000:],
    ])


def build_validation_repair_hint(raw_part, issues):
    return "\n".join([
        "Your previous OBJ part appended but failed validation.",
        "Validation errors: " + "; ".join(issues[:12]),
        "Return the same requested part again as valid OBJ/Live OBJ only.",
        "Use a unique object name, include vertices, and ensure all visible raw mesh objects include faces.",
        "Every raw mesh object/group with vertices must include faces. Vertices without f lines are invisible and are not acceptable.",
        "If you model a body shell, connect section rings with side faces and cap the ends.",
        "For #@post material, use only name=material_id. Do not include object=, target=, id=, color=, roughness, or metalness on the material op.",
        "Use only supported #@post attributes. If a visual behavior needs unsupported attributes, bake it into real v/f geometry.",
        "Previous invalid output:",
        safe_str(raw_part)[-12000:],
    ])


def append_or_replace_part(current_scene, part_text, part):
    action, target = part_action(part, current_scene)
    if action == "replace":
        next_scene, normalized = replace_part(current_scene, part_text, target)
    else:
        next_scene, normalized = append_part(current_scene, part_text)
    return action, next_scene, normalized


def request_part_text(provider_name, api_key, model_name, plan, part, current_scene, original_request, base_url, max_out, repair_hint=""):
    user_prompt = build_part_prompt(plan, part, current_scene, original_request)
    if repair_hint:
        user_prompt = user_prompt + "\n\nRepair instruction for this part:\n" + repair_hint
    raw_part = call_provider(
        provider_name,
        api_key,
        model_name,
        PART_SYSTEM_PROMPT,
        user_prompt,
        base_url,
        max_out,
    )
    part_text = normalize_generated_part_metadata(extract_text(provider_name, raw_part))
    return raw_part, part_text


def prepare_part_text(provider_name, api_key, model_name, part_text, part, original_request, base_url, max_out):
    part_text = normalize_generated_part_metadata(part_text)
    part_text, _ = repair_controls_if_needed(
        provider_name,
        api_key,
        model_name,
        part_text,
        part,
        original_request,
        base_url,
        max_out,
    )
    part_text, _ = repair_post_ops_if_needed(
        provider_name,
        api_key,
        model_name,
        part_text,
        base_url,
        max_out,
    )
    return normalize_generated_part_metadata(part_text)


def generate_part_with_web_retries(provider_name, api_key, model_name, plan, part, current_scene, original_request, base_url, max_out):
    raw_attempts = []

    raw_part, part_text = request_part_text(
        provider_name, api_key, model_name, plan, part, current_scene, original_request, base_url, max_out
    )
    raw_attempts.append(extract_text(provider_name, raw_part))
    part_text = prepare_part_text(provider_name, api_key, model_name, part_text, part, original_request, base_url, max_out)

    try:
        action, next_scene, normalized = append_or_replace_part(current_scene, part_text, part)
    except Exception as first_error:
        raw_part, part_text = request_part_text(
            provider_name,
            api_key,
            model_name,
            plan,
            part,
            current_scene,
            original_request,
            base_url,
            max_out,
            build_append_repair_hint(part_text, first_error),
        )
        raw_attempts.append(extract_text(provider_name, raw_part))
        part_text = prepare_part_text(provider_name, api_key, model_name, part_text, part, original_request, base_url, max_out)
        action, next_scene, normalized = append_or_replace_part(current_scene, part_text, part)

    issues = visible_part_validation_issues(part_text)
    if issues:
        raw_part, part_text = request_part_text(
            provider_name,
            api_key,
            model_name,
            plan,
            part,
            current_scene,
            original_request,
            base_url,
            max_out,
            build_validation_repair_hint(part_text, issues),
        )
        raw_attempts.append(extract_text(provider_name, raw_part))
        part_text = prepare_part_text(provider_name, api_key, model_name, part_text, part, original_request, base_url, max_out)
        try:
            action, next_scene, normalized = append_or_replace_part(current_scene, part_text, part)
        except Exception as append_error:
            raw_part, part_text = request_part_text(
                provider_name,
                api_key,
                model_name,
                plan,
                part,
                current_scene,
                original_request,
                base_url,
                max_out,
                build_append_repair_hint(part_text, append_error),
            )
            raw_attempts.append(extract_text(provider_name, raw_part))
            part_text = prepare_part_text(provider_name, api_key, model_name, part_text, part, original_request, base_url, max_out)
            action, next_scene, normalized = append_or_replace_part(current_scene, part_text, part)
        issues = visible_part_validation_issues(part_text)
    if issues:
        raise Exception("Generated part failed validation after repair: " + "; ".join(issues[:6]))

    return action, next_scene, normalized, "\n\n# --- repair attempt ---\n\n".join([safe_str(a) for a in raw_attempts])


current_obj = safe_str(get_mem("current_obj", ""))
plan_json = safe_str(get_mem("plan_json", ""))
part_index = int(get_mem("part_index", 0) or 0)
status = "ready"
error = ""
debug = ""
active_part = ""

reset_pressed = button_pressed("reset")
plan_pressed = button_pressed("plan_run")
next_pressed = button_pressed("next_run")

if reset_pressed:
    clear_mem()
    current_obj = ""
    plan_json = ""
    part_index = 0
    status = "reset"

provider_name = safe_str(input_value("provider", "openai"), "openai").strip().lower()
api_key = safe_str(input_value("api_key", "")).strip()
model_name = safe_str(input_value("model", "")).strip()
scene_prompt = safe_str(input_value("prompt", "")).strip()
stored_scene_prompt = safe_str(get_mem("scene_prompt", scene_prompt)).strip() or scene_prompt
base_url = safe_str(input_value("base_url", "")).strip()
max_out = parse_max_tokens(input_value("max_tokens", None))
auto = bool_input("auto_run", False)
auto_delay = input_value("auto_delay_ms", 250)
try:
    auto_delay = max(50, int(auto_delay))
except Exception:
    auto_delay = 250

try:
    if plan_pressed:
        if not api_key:
            raise Exception("Missing api_key")
        if not scene_prompt:
            raise Exception("Missing prompt")
        status = "planning..."
        set_message(status)
        editing_existing = has_scene_objects(current_obj)
        if editing_existing:
            user = "\n".join([
                "Generation mode: tools-off raw-first OBJ edit.",
                "The current OBJ below is the source of truth.",
                "Plan ONLY raw mesh edit steps. Each part method must be \"llm_mesh\".",
                "For changes to an existing object, set action=\"replace\" and target to the existing o object name.",
                "For newly requested objects, set action=\"append\".",
                "Each replacement part prompt must ask for one complete replacement OBJ block with the same target object name.",
                "Preserve unrelated objects by not planning steps for them.",
                "Every replacement/addition prompt must explicitly require #@params: and #@controls: metadata for 2-5 practical Grasshopper controls. Controls are metadata, not visible scene objects.",
                "",
                "User edit request:",
                scene_prompt,
                "",
                "Current OBJ source:",
                safe_str(current_obj)[-12000:],
                "",
                "Create the iterative edit plan now.",
            ])
        else:
            user = "\n".join([
                "Generation mode: tools-off raw-first OBJ.",
                "Plan ONLY raw mesh parts. Each part method must be \"llm_mesh\".",
                "Every part prompt must explicitly require #@params: and #@controls: metadata for 2-5 practical Grasshopper controls. Controls are metadata, not visible scene objects.",
                "",
                "Plan this raw OBJ scene for iterative generation:",
                scene_prompt,
            ])
        raw = call_provider(provider_name, api_key, model_name, PLANNER_PROMPT, user, base_url, max_out)
        text = extract_text(provider_name, raw)
        plan = parse_json_object(text)
        plan_json = json.dumps(plan, indent=2)
        if not editing_existing:
            current_obj = DEFAULT_HEADER
            for mat in plan.get("materials", []):
                mid = mat.get("id")
                if not mid:
                    continue
                current_obj += "#@material_preset: %s color=%s roughness=%s metalness=%s\n" % (
                    mid,
                    mat.get("color", "#888888"),
                    mat.get("roughness", 0.7),
                    mat.get("metalness", 0.0),
                )
        set_mem("plan_json", plan_json)
        set_mem("current_obj", current_obj)
        set_mem("part_index", 0)
        set_mem("last_raw", raw)
        set_mem("scene_prompt", scene_prompt)
        stored_scene_prompt = scene_prompt
        part_index = 0
        status = ("planned edit " if editing_existing else "planned ") + "%d parts" % len(part_list(plan))

    should_generate_next = next_pressed or auto
    if should_generate_next:
        if not api_key:
            raise Exception("Missing api_key")
        if not plan_json:
            raise Exception("No plan yet. Press plan_run first.")
        plan = json.loads(plan_json)
        all_parts = part_list(plan)
        if part_index >= len(all_parts):
            status = "complete: %d/%d parts" % (part_index, len(all_parts))
        else:
            part = all_parts[part_index]
            active_part = "%s: %s" % (part.get("id", "part"), part.get("role", ""))
            status = "generating part %d/%d: %s" % (part_index + 1, len(all_parts), part.get("id", "part"))
            set_message(status)
            action, current_obj, normalized, raw_attempts = generate_part_with_web_retries(
                provider_name,
                api_key,
                model_name,
                plan,
                part,
                current_obj,
                stored_scene_prompt,
                base_url,
                max_out,
            )
            part_index += 1
            set_mem("current_obj", current_obj)
            set_mem("part_index", part_index)
            set_mem("last_raw", raw_attempts)
            set_mem("last_part", normalized)
            status = "%s part %d/%d: %s" % ("replaced" if action == "replace" else "appended", part_index, len(all_parts), part.get("id", "part"))
            if auto and part_index < len(all_parts):
                schedule_next(auto_delay)
except Exception as e:
    error = str(e)
    status = "error: " + error[:160]

try:
    plan = json.loads(plan_json) if plan_json else {"parts": []}
    plist = part_list(plan)
    parts = ["%02d %s - %s" % (i + 1, p.get("id", "part"), p.get("role", "")) for i, p in enumerate(plist)]
    if part_index < len(plist):
        p = plist[part_index]
        active_part = "%s: %s" % (p.get("id", "part"), p.get("role", ""))
    progress = "%d/%d" % (part_index, len(plist))
except Exception:
    parts = []
    progress = "0/0"

debug = "scene %s\nlast raw starts: %r" % (summarize_scene(current_obj), safe_str(get_mem("last_raw", ""))[:500])
set_message(status)
