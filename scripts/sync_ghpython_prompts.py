#!/usr/bin/env python3
"""Sync pasteable Grasshopper GHPython prompt constants from the web source.

The web TypeScript prompt constants are the source of truth. The GHPython
scripts are standalone paste artifacts, so they need embedded copies.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_PROMPTS = ROOT / "src/lib/server/llm/liveObjChat.ts"
GH_DECOMPOSED = ROOT / "grasshopper_decomposed_builder_ghpython.py"


def decode_ts_string(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("`") and raw.endswith("`"):
        body = raw[1:-1]
        return body.replace("\\`", "`").replace("\\${", "${").replace("\\n", "\n")
    return ast.literal_eval(raw).replace("\\`", "`")


def extract_const(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"(?:export\s+)?const\s+"
        + re.escape(name)
        + r"\s*=\s*(?P<value>`(?:\\.|[^`])*`|'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")\s*(?:as const)?\s*;",
        text,
        re.S,
    )
    if not match:
        raise SystemExit(f"Could not find {name} in {path}")
    return decode_ts_string(match.group("value"))


def py_triple_string(value: str) -> str:
    if "'''" not in value:
        return "'''" + value + "'''"
    if '"""' not in value:
        return '"""' + value + '"""'
    return repr(value)


def replace_assignment(path: Path, name: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    replacement = f"{name} = {py_triple_string(value)}"
    pattern = (
        r"^"
        + re.escape(name)
        + r"\s*=\s*(?:'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")"
    )
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"Could not replace {name} in {path}")
    path.write_text(new_text, encoding="utf-8")


def main() -> None:
    plan_prompt = extract_const(CHAT_PROMPTS, "LIVE_OBJ_ITERATIVE_PLAN_SYSTEM_PROMPT")
    raw_part_prompt = extract_const(CHAT_PROMPTS, "RAW_OBJ_ITERATIVE_PART_SYSTEM_PROMPT")

    replace_assignment(GH_DECOMPOSED, "PLANNER_PROMPT", plan_prompt)
    replace_assignment(GH_DECOMPOSED, "PART_SYSTEM_PROMPT", raw_part_prompt)

    print("Synced GHPython prompts from web TypeScript source.")


if __name__ == "__main__":
    main()
