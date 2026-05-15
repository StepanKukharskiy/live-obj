# Grasshopper GHPython component: decomposed raw OBJ builder.
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


PLANNER_PROMPT = """You plan a raw OBJ scene for a Grasshopper iterative builder.

Return only JSON, no Markdown.

Shape:
{
  "scene": "short description",
  "materials": [
    {"id": "material_id", "color": "#RRGGBB", "roughness": 0.7, "metalness": 0.0, "role": "short role"}
  ],
  "parts": [
    {
      "id": "stable_snake_case_id",
      "role": "what this part contributes",
      "prompt": "specific instructions for generating only this part as compact raw OBJ",
      "dependencies": ["prior_part_id"]
    }
  ]
}

Rules:
- Use y-up coordinates.
- Prefer 3-7 parts.
- Generate coarse-to-fine: support/base, main structure, repeated modules, details.
- Each part prompt must ask for one or a few renderable raw mesh objects with vertices and faces.
- Each part prompt should request #@source: llm_mesh, #@semantic, #@editable, #@post material/tag.
- Keep each part compact enough for one completion.
- Do not generate OBJ here, only the JSON plan."""


PART_SYSTEM_PROMPT = """You generate one raw OBJ part for an iterative Grasshopper scene builder.

Return only OBJ text. Do not return Markdown, JSON, Python, or explanations.

Critical OBJ indexing rule:
- Use local vertex numbering in this returned part.
- The first vertex you emit is v 1 for face purposes.
- Face lines must reference only vertices defined in this returned part.
- The builder will remap indices when appending to the scene.

Raw OBJ part rules:
- Use y-up coordinates.
- Usually generate only the requested part, not the whole scene.
- Use one or a few stable semantic object names.
- Every object with vertices must include faces.
- Include #@source: llm_mesh, #@editable, #@semantic.
- Include #@post: material/tag when useful.
- Include needed #@material_preset lines before the first object only if the material is new.
- Keep geometry compact and low-poly.
- Prefer quads where reasonable.
- Avoid vertices-only rings, rails, logs, supports, or lattices.
- If a part has repeated modules, use a small renderable module and executable #@post array/mirror/transform controls where possible.
- If you include #@controls, every control key must be referenced by executable #@post metadata."""


def safe_str(value, fallback=""):
    if value is None:
        return fallback
    return str(value)


def input_value(name, fallback=None):
    try:
        return globals().get(name, fallback)
    except Exception:
        return fallback


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


def clear_mem():
    for name in ("current_obj", "plan_json", "part_index", "last_raw", "last_part"):
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
    clean = strip_code_fence(raw_part)
    lines = clean.splitlines()
    first_obj = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*o\s+", line):
            first_obj = i
            break
    if first_obj < 0:
        raise Exception("Generated part did not contain an object line: o name")
    preamble = [l for l in lines[:first_obj] if re.match(r"^\s*#@material_preset:\s+", l)]
    obj_text = "\n".join(lines[first_obj:]).strip()
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


def summarize_scene(scene_text):
    names = re.findall(r"^\s*o\s+([^\s#]+)", safe_str(scene_text), re.M)
    return "objects=%s vertices=%d faces=%d" % (", ".join(names[-12:]) if names else "(none)", count_vertices(scene_text), count_faces(scene_text))


def part_list(plan):
    try:
        return plan.get("parts", [])
    except Exception:
        return []


def build_part_prompt(plan, part, current_scene):
    return "\n".join([
        "Overall scene:",
        safe_str(plan.get("scene", "")),
        "",
        "Full plan JSON:",
        json.dumps(plan),
        "",
        "Current scene summary:",
        summarize_scene(current_scene),
        "",
        "Current OBJ source:",
        safe_str(current_scene)[-12000:],
        "",
        "Generate only this part:",
        json.dumps(part),
    ])


current_obj = safe_str(get_mem("current_obj", ""))
plan_json = safe_str(get_mem("plan_json", ""))
part_index = int(get_mem("part_index", 0) or 0)
status = "ready"
error = ""
debug = ""
active_part = ""

if input_value("reset", False):
    clear_mem()
    current_obj = ""
    plan_json = ""
    part_index = 0
    status = "reset"

provider_name = safe_str(input_value("provider", "openai"), "openai").strip().lower()
api_key = safe_str(input_value("api_key", "")).strip()
model_name = safe_str(input_value("model", "")).strip()
scene_prompt = safe_str(input_value("prompt", "")).strip()
base_url = safe_str(input_value("base_url", "")).strip()
max_out = parse_max_tokens(input_value("max_tokens", None))
auto = bool(input_value("auto_run", False))
auto_delay = input_value("auto_delay_ms", 250)
try:
    auto_delay = max(50, int(auto_delay))
except Exception:
    auto_delay = 250

try:
    if input_value("plan_run", False):
        if not api_key:
            raise Exception("Missing api_key")
        if not scene_prompt:
            raise Exception("Missing prompt")
        status = "planning..."
        set_message(status)
        user = "Plan this raw OBJ scene for iterative generation:\n" + scene_prompt
        raw = call_provider(provider_name, api_key, model_name, PLANNER_PROMPT, user, base_url, max_out)
        text = extract_text(provider_name, raw)
        plan = parse_json_object(text)
        plan_json = json.dumps(plan, indent=2)
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
        part_index = 0
        status = "planned %d parts" % len(part_list(plan))

    should_generate_next = bool(input_value("next_run", False)) or auto
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
            raw_part = call_provider(
                provider_name,
                api_key,
                model_name,
                PART_SYSTEM_PROMPT,
                build_part_prompt(plan, part, current_obj),
                base_url,
                max_out,
            )
            part_text = extract_text(provider_name, raw_part)
            current_obj, normalized = append_part(current_obj, part_text)
            part_index += 1
            set_mem("current_obj", current_obj)
            set_mem("part_index", part_index)
            set_mem("last_raw", raw_part)
            set_mem("last_part", normalized)
            status = "appended part %d/%d: %s" % (part_index, len(all_parts), part.get("id", "part"))
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
