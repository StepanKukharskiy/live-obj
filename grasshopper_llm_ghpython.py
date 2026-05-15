# Grasshopper GHPython component: direct LLM caller.
#
# Inputs to create:
#   run            bool
#   provider       str   "openai", "openrouter", "anthropic", "google", "gemini", or "custom"
#   api_key        str
#   model          str   optional; sensible default per provider
#   prompt         str
#   current_obj    str   optional override latest OBJ/Live OBJ text for iterative edits
#   history        str   optional override visible chat/source history text
#   system_prompt  str   optional extra instructions appended after the built-in raw OBJ prompt
#   base_url       str   optional; for custom/OpenAI-compatible providers
#   reset_memory   bool  optional; clears this component's stored chat/source memory
#   force          bool  optional; allows rerunning the exact same prompt/signature
#   max_tokens     int   optional; default 16000, matching the web raw pipeline budget
#
# Outputs to create:
#   live_obj
#   raw_response
#   error
#   status
#   next_history
#   current_obj_out
#   debug
#
# Notes:
#   This calls providers directly from the user's machine.
#   It does not call Spellshape's API.
#   For provider="google" or "gemini", this uses Gemini API generateContent.
#   For provider="custom", base_url should be an OpenAI-compatible base URL,
#   for example: https://api.example.com/v1

import json
import re
import System
import scriptcontext as sc
from System import Array, Byte
from System.IO import StreamReader
from System.Net import WebRequest, ServicePointManager, SecurityProtocolType
from System.Text import Encoding


RAW_OBJ_SYSTEM_PROMPT = """You are Spellshape's raw OBJ generator for Grasshopper.

Return only OBJ text. Do not return Markdown, JSON, Python, comments outside OBJ metadata, or explanations.

This is raw-first OBJ mode:
- Mesh v/f is the base geometry.
- Use direct vertices and faces.
- Do not use procedural, SDF, simulation, assembly, #@ops, or Live OBJ recipe metadata.
- You may use #@post metadata for simple post-processing controls.
- Keep geometry compact, valid, low-poly, and grouped into semantic objects.
- Use Y-up coordinates.

Required header:
#@live_obj_version: 0.1
#@up: y

Optional material presets before objects:
#@material_preset: material_id color=#RRGGBB roughness=0.7 metalness=0.0

Every object must use:
o stable_semantic_object_id
#@source: llm_mesh
#@editable: transform,material,duplicate,delete
#@semantic: short human-readable role
#@transform: position=[0,0,0],rotation=[0,0,0],scale=[1,1,1]

Use #@params and #@controls when useful for user-editable post controls:
#@params: roof_lift=0.0, roof_scale=1.0
#@controls:
#@ - slider key=roof_lift label=Roof_lift min=-2 max=2 step=0.1
#@ - slider key=roof_scale label=Roof_scale min=0.25 max=4 step=0.05

Hard control rule:
- Every #@control key must be referenced by at least one executable #@post line on a visible object.
- Do not create decorative/fake controls. A control that only appears in #@params/#@controls but not in #@post is invalid.
- If a desired editable dimension cannot be implemented using supported #@post ops, expose an executable approximation or omit the control.

Supported #@controls kinds:
- slider key=name label=Label min=a max=b step=s
- seed key=name label=Label min=a max=b step=1
- toggle key=name label=Label
- choice key=name label=Label options=a,b,c

Supported #@post ops:
#@post:
#@ - transform position=[x,y,z] rotation=[rx,ry,rz] scale=[sx,sy,sz]
#@ - transform position=[x,y,z] rotation=[rx,ry,rz] scale=[sx,sy,sz] pivot=[x,y,z]
#@ - mirror axis=x|y|z
#@ - array count=n offset=[x,y,z]
#@ - array count=n offset=[x,y,z] centered=true
#@ - snap_to_ground axis=x|y|z
#@ - center_origin axes=xz|xy|yz|xyz
#@ - material name=material_id
#@ - tag value=architectural|product|game|art|structural|decorative

Values in #@post may reference #@params by key, for example:
#@post:
#@ - transform position=[0,roof_lift,0] scale=[roof_scale,1,1]

Raw OBJ rules:
- Use one-based OBJ face indices.
- Faces must reference existing vertices.
- Prefer quads where reasonable, triangles where needed.
- No degenerate faces.
- For complex requests, still return a compact first-pass mesh. Prefer a small semantic mesh with executable #@params/#@controls/#@post over a huge exhaustive mesh.
- Add #@params and #@controls for obvious editable dimensions only when each key is used by executable #@post metadata.
- Since this is Y-up, use #@post snap_to_ground axis=y when snapping to the ground.
- Do not emit vertices-only objects.
- For repeated visual modules, either make a small clean mesh and use #@post array, or emit a few semantic mesh objects.
- When a spacing control changes paired supports/legs/rails, keep the overall object centered. Either model the repeated module around the origin and use #@post array centered=true, or add #@post center_origin axes=x after the array.
- When scaling height/depth of a part that should stay attached, use transform pivot=[x,y,z] so the base/contact edge stays put.
- For symmetric objects, you may model one side and use #@post mirror axis=x.
- Include material presets and material post ops when material intent is clear.

Output only the OBJ file."""


def safe_str(value, fallback=""):
    if value is None:
        return fallback
    return str(value)


def input_value(name, fallback=None):
    try:
        return globals().get(name, fallback)
    except Exception:
        return fallback


def memory_key(name):
    try:
        guid = str(ghenv.Component.InstanceGuid)
    except Exception:
        guid = "default"
    return "spellshape_llm_memory:%s:%s" % (guid, name)


def memory_get(name):
    return sc.sticky.get(memory_key(name), "") or ""


def memory_set(name, value):
    sc.sticky[memory_key(name)] = safe_str(value)


def memory_clear():
    memory_set("current_obj", "")
    memory_set("history", "")
    memory_set("last_signature", "")
    memory_set("last_raw_response", "")


def set_component_status(text):
    try:
        ghenv.Component.Message = text
    except Exception:
        pass


def built_system_prompt(extra):
    extra = safe_str(extra).strip()
    if extra:
        return RAW_OBJ_SYSTEM_PROMPT + "\n\nAdditional user/developer instructions:\n" + extra
    return RAW_OBJ_SYSTEM_PROMPT


def build_user_prompt(user_prompt, current_obj, history):
    user_prompt = safe_str(user_prompt).strip()
    current_obj = safe_str(current_obj).strip()
    history = safe_str(history).strip()

    if current_obj:
        parts = [
            "You are editing an existing raw OBJ scene.",
            "",
            "User request:",
            user_prompt,
            "",
            "Current OBJ source:",
            current_obj,
            "",
            "Return the complete updated OBJ source, not a patch.",
            "Preserve unrelated object IDs, #@params, #@controls, #@post blocks, materials, and geometry where possible.",
            "Make the smallest useful edit that satisfies the request.",
        ]
    else:
        parts = [
            "Generate a new raw OBJ scene for this request:",
            user_prompt,
        ]

    parts.extend([
        "",
        "Grasshopper response budget:",
        "- Keep the answer compact enough to fit one chat completion.",
        "- Target 40-160 vertices total unless the user explicitly asks for high detail.",
        "- Prefer repeated modules and executable #@post controls over enumerating many near-identical mesh parts.",
        "- If exact geometry would be too long, return the simplest valid controlled low-poly version instead of returning nothing.",
    ])

    if history:
        parts.extend([
            "",
            "Visible prior chat/source history for context:",
            history[-12000:],
        ])

    return "\n".join(parts)


def cheap_hash(text):
    text = safe_str(text)
    h = 2166136261
    for ch in text:
        h = h ^ ord(ch)
        h = (h * 16777619) & 0xffffffff
    return "%08x" % h


def request_signature(provider_name, model_name, user_prompt, current_obj):
    return "|".join([
        safe_str(provider_name),
        safe_str(model_name),
        safe_str(user_prompt),
        cheap_hash(current_obj),
    ])


def append_history(history, user_prompt, result_obj, provider_name, model_name):
    history = safe_str(history).strip()
    user_prompt = safe_str(user_prompt).strip()
    result_obj = safe_str(result_obj).strip()
    header = "provider=%s model=%s" % (provider_name or "", model_name or "")
    turn = "\n".join([
        "## User",
        user_prompt,
        "",
        "## Assistant OBJ (" + header + ")",
        result_obj,
    ]).strip()
    return (history + "\n\n" + turn).strip() if history else turn


def strip_code_fence(text):
    if not text:
        return ""
    trimmed = text.strip()
    if not trimmed.startswith("```"):
        return trimmed
    first_newline = trimmed.find("\n")
    last_fence = trimmed.rfind("```")
    if first_newline >= 0 and last_fence > first_newline:
        return trimmed[first_newline + 1:last_fence].strip()
    return trimmed


def normalize_base_url(url):
    url = safe_str(url).strip()
    if not url:
        return ""
    if url.lower().endswith("/chat/completions"):
        url = url[:-len("/chat/completions")]
    return url.rstrip("/")


def post_json(url, headers, payload):
    # Rhino 7 / macOS can otherwise negotiate old TLS defaults.
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
    except Exception:
        pass

    body = json.dumps(payload)
    data = Encoding.UTF8.GetBytes(body)
    request = WebRequest.Create(url)
    request.Method = "POST"
    request.ContentType = "application/json"
    request.ContentLength = data.Length

    for key, value in headers.items():
        if key.lower() == "authorization":
            request.Headers["Authorization"] = value
        elif key.lower() == "content-type":
            pass
        else:
            request.Headers[key] = value

    stream = request.GetRequestStream()
    try:
        stream.Write(data, 0, data.Length)
    finally:
        stream.Close()

    try:
        response = request.GetResponse()
        reader = StreamReader(response.GetResponseStream())
        try:
            return reader.ReadToEnd()
        finally:
            reader.Close()
            response.Close()
    except System.Net.WebException as ex:
        response = ex.Response
        if response is None:
            raise
        reader = StreamReader(response.GetResponseStream())
        try:
            detail = reader.ReadToEnd()
        finally:
            reader.Close()
            response.Close()
        raise Exception("HTTP request failed: " + detail)


def should_use_max_completion_tokens(provider_name, base_url, model_name):
    provider_name = safe_str(provider_name).strip().lower()
    base_url = safe_str(base_url).strip().lower()
    model_name = safe_str(model_name).strip().lower()
    if provider_name == "openai":
        return True
    if "api.openai.com" in base_url:
        return True
    # Reasoning/o-series and GPT-5-family Chat Completions expect
    # max_completion_tokens rather than deprecated max_tokens.
    return model_name.startswith("gpt-5") or model_name.startswith("o1") or model_name.startswith("o3") or model_name.startswith("o4")


def call_openai_compatible(provider_name, key, model_name, user_prompt, sys_prompt, url, max_tokens):
    base = normalize_base_url(url)
    if not base:
        if provider_name == "openrouter":
            base = "https://openrouter.ai/api/v1"
        else:
            base = "https://api.openai.com/v1"
    endpoint = base + "/chat/completions"

    if not model_name:
        model_name = "openai/gpt-4.1-mini" if provider_name == "openrouter" else "gpt-4.1-mini"

    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model_name,
        "messages": messages,
    }
    if should_use_max_completion_tokens(provider_name, base, model_name):
        payload["max_completion_tokens"] = max_tokens
    else:
        payload["max_tokens"] = max_tokens
    headers = {
        "Authorization": "Bearer " + key,
    }
    if provider_name == "openrouter":
        headers["HTTP-Referer"] = "https://spellshape.local"
        headers["X-Title"] = "Spellshape Grasshopper"

    return post_json(endpoint, headers, payload)


def call_anthropic(key, model_name, user_prompt, sys_prompt, max_tokens):
    if not model_name:
        model_name = "claude-3-5-sonnet-latest"
    payload = {
        "model": model_name,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": user_prompt}
        ],
    }
    if sys_prompt:
        payload["system"] = sys_prompt
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }
    return post_json("https://api.anthropic.com/v1/messages", headers, payload)


def call_google_gemini(key, model_name, user_prompt, sys_prompt, max_tokens):
    if not model_name:
        model_name = "gemini-2.5-flash"

    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model_name
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_prompt}
                ],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
        },
    }
    if sys_prompt:
        payload["systemInstruction"] = {
            "parts": [
                {"text": sys_prompt}
            ]
        }

    headers = {
        "x-goog-api-key": key,
    }
    return post_json(endpoint, headers, payload)


def extract_text(provider_name, raw):
    try:
        root = json.loads(raw)
    except Exception:
        return raw

    if provider_name == "anthropic":
        parts = root.get("content", [])
        out = []
        for item in parts:
            if isinstance(item, dict) and item.get("text") is not None:
                out.append(item.get("text"))
        return "".join(out)

    if provider_name in ("google", "gemini"):
        candidates = root.get("candidates", [])
        if not candidates:
            return raw
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        out = []
        for item in parts:
            if isinstance(item, dict) and item.get("text") is not None:
                out.append(item.get("text"))
        return "".join(out) if out else raw

    choices = root.get("choices", [])
    if not choices:
        return raw
    message = choices[0].get("message", {})
    content = message.get("content", raw)
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, dict):
                if item.get("text") is not None:
                    out.append(item.get("text"))
                elif item.get("content") is not None:
                    out.append(item.get("content"))
            elif item is not None:
                out.append(str(item))
        return "".join(out)
    if content is None and message.get("refusal"):
        return str(message.get("refusal"))
    return content


def raw_response_hint(raw):
    raw = safe_str(raw).strip()
    if not raw:
        return "(empty raw response)"
    try:
        root = json.loads(raw)
        if isinstance(root, dict):
            if "error" in root:
                return json.dumps(root.get("error"))[:1200]
            if "choices" in root:
                choices = root.get("choices") or []
                if choices:
                    first = choices[0]
                    return json.dumps({
                        "finish_reason": first.get("finish_reason"),
                        "message": first.get("message"),
                    })[:1600]
            if "candidates" in root:
                candidates = root.get("candidates") or []
                if candidates:
                    first = candidates[0]
                    return json.dumps({
                        "finishReason": first.get("finishReason"),
                        "content": first.get("content"),
                        "safetyRatings": first.get("safetyRatings"),
                    })[:1600]
    except Exception:
        pass
    return raw[:1600]


def control_keys_and_post_text(obj_text):
    keys = []
    post_lines = []
    block = None
    for raw in safe_str(obj_text).splitlines():
        line = raw.strip()
        if not line.startswith("#@"):
            continue
        body = line[2:].strip()
        low = body.lower()
        if low == "controls:":
            block = "controls"
            continue
        if low == "post:":
            block = "post"
            continue
        if body.endswith(":") and not body.startswith("-"):
            block = None
            continue
        if body.startswith("- "):
            item = body[2:].strip()
            if block == "controls":
                m = re.search(r"(?:^|\s)key=([A-Za-z_][A-Za-z0-9_]*)", item)
                if m:
                    key = m.group(1)
                    if key not in keys:
                        keys.append(key)
            elif block == "post":
                cmd = item.split(None, 1)[0].lower() if item.split() else ""
                if cmd not in ("material", "tag"):
                    post_lines.append(item)
            continue
        if low.startswith("post "):
            post_lines.append(body[len("post "):].strip())
    return keys, "\n".join(post_lines)


def unused_control_keys(obj_text):
    keys, post_text = control_keys_and_post_text(obj_text)
    unused = []
    for key in keys:
        if not re.search(r"\b%s\b" % re.escape(key), post_text):
            unused.append(key)
    return unused


def build_control_repair_prompt(obj_text, bad_keys):
    return "\n".join([
        "Repair this raw OBJ control contract.",
        "",
        "Problem:",
        "The OBJ declares #@controls whose keys are not referenced by executable #@post metadata:",
        ", ".join(bad_keys),
        "",
        "Rules:",
        "- Return the complete OBJ source only.",
        "- Every #@control key you keep must be referenced by at least one executable #@post line on a visible object.",
        "- Executable #@post lines include transform, mirror, array, snap_to_ground, and center_origin.",
        "- material and tag are metadata only and do not count as using a control.",
        "- If a control cannot be made executable with supported #@post ops, remove that control and its unused param.",
        "- Preserve the visual design and unrelated geometry as much as possible.",
        "",
        "OBJ to repair:",
        obj_text,
    ])


def parse_max_tokens(value):
    try:
        n = int(value)
    except Exception:
        n = 16000
    return max(512, min(16000, n))


def call_provider(provider_name, key, model_name, request_prompt, sys_prompt, url, max_out):
    if provider_name == "anthropic":
        return call_anthropic(key, model_name, request_prompt, sys_prompt, max_out)
    if provider_name in ("google", "gemini"):
        return call_google_gemini(key, model_name, request_prompt, sys_prompt, max_out)
    return call_openai_compatible(provider_name, key, model_name, request_prompt, sys_prompt, url, max_out)


stored_current_obj = memory_get("current_obj")
stored_history = memory_get("history")

live_obj = stored_current_obj
raw_response = memory_get("last_raw_response")
error = ""
status = "idle: memory obj=%d chars history=%d chars" % (len(stored_current_obj), len(stored_history))
debug = "stored_current_obj starts: %r" % (stored_current_obj[:240],)

if input_value("reset_memory", False):
    memory_clear()
    status = "memory reset"

current_obj_out = stored_current_obj
next_history = stored_history

if input_value("run", False):
    try:
        provider_name = safe_str(input_value("provider", "openai"), "openai").strip().lower()
        key = safe_str(input_value("api_key", "")).strip()
        model_name = safe_str(input_value("model", "")).strip()
        user_prompt = safe_str(input_value("prompt", "")).strip()
        current_obj = safe_str(input_value("current_obj", "")).strip() or stored_current_obj
        history_text = safe_str(input_value("history", "")).strip() or stored_history
        sys_prompt = built_system_prompt(input_value("system_prompt", ""))
        url = safe_str(input_value("base_url", "")).strip()
        max_out = parse_max_tokens(input_value("max_tokens", None))
        if not key:
            raise Exception("Missing api_key.")
        if not user_prompt:
            raise Exception("Missing prompt.")

        sig = request_signature(provider_name, model_name, user_prompt, current_obj)
        last_sig = memory_get("last_signature")
        if stored_current_obj and sig == last_sig and not input_value("force", False):
            live_obj = stored_current_obj
            raw_response = memory_get("last_raw_response")
            current_obj_out = stored_current_obj
            next_history = stored_history
            status = "skipped duplicate run: memory obj=%d chars. Change prompt or set force=True." % len(stored_current_obj)
            set_component_status("cached")
            raise StopIteration

        request_prompt = build_user_prompt(user_prompt, current_obj, history_text)
        mode = "edit" if current_obj else "new"
        status = "calling %s (%s, current=%d chars, max=%d tokens)..." % (provider_name, mode, len(current_obj), max_out)
        set_component_status(status)

        raw_response = call_provider(provider_name, key, model_name, request_prompt, sys_prompt, url, max_out)

        live_obj = strip_code_fence(extract_text(provider_name, raw_response))
        if not safe_str(live_obj).strip():
            raise Exception("Model returned no OBJ text. Raw response hint: " + raw_response_hint(raw_response))
        invalid_controls = unused_control_keys(live_obj)
        repaired = False
        if invalid_controls:
            status = "repairing unwired controls: " + ", ".join(invalid_controls[:8])
            set_component_status("repairing")
            repair_prompt = build_control_repair_prompt(live_obj, invalid_controls)
            repair_raw = call_provider(provider_name, key, model_name, repair_prompt, sys_prompt, url, max_out)
            raw_response = raw_response + "\n\n--- control repair raw response ---\n" + repair_raw
            repaired_obj = strip_code_fence(extract_text(provider_name, repair_raw))
            if safe_str(repaired_obj).strip():
                live_obj = repaired_obj
                repaired = True
            invalid_controls = unused_control_keys(live_obj)

        debug = "live_obj chars=%d repaired=%s unused_controls=%s starts: %r" % (
            len(live_obj or ""),
            repaired,
            ",".join(invalid_controls),
            (live_obj or "")[:300],
        )
        if invalid_controls:
            error = "Unwired controls remain after repair: " + ", ".join(invalid_controls)
        next_history = append_history(history_text, user_prompt, live_obj, provider_name, model_name)
        memory_set("current_obj", live_obj)
        memory_set("history", next_history)
        memory_set("last_signature", sig)
        memory_set("last_raw_response", raw_response)
        current_obj_out = live_obj
        status = "ok: %s %s returned %d chars; memory saved%s" % (
            provider_name,
            mode,
            len(live_obj or ""),
            " (control repaired)" if repaired else "",
        )
        set_component_status(status)
    except StopIteration:
        pass
    except Exception as e:
        error = str(e)
        status = "error: " + error[:180]
        debug = "raw_response hint: " + raw_response_hint(raw_response)
        set_component_status("error")
else:
    set_component_status("idle")

# Optional outputs if you create them:
#   current_obj_out gives the stored latest source
#   next_history gives the stored/updated chat history
