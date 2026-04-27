# Spellshape Agent Guide

Spellshape is a SvelteKit + TypeScript project for AI-native 3D authoring.

## Live OBJ Approach

The `/app` experience uses a **Live OBJ workflow**:
- user prompt/history is sent to the Live OBJ API,
- model returns Live OBJ text (`#@` metadata + OBJ cache),
- executor expands/regenerates geometry from metadata,
- UI shows chat, source outputs (live/raw/executed), and metadata-driven controls.

Treat `#@` metadata as the editable source of truth; mesh `v/f` is cache/output.

## Working Principles

1. **Think before coding.** If something is ambiguous, ask. Don't silently pick one interpretation and run with it. Surface tradeoffs, stop when confused.
2. **Simplicity first.** Minimum code that solves the problem. No speculative abstractions, no "flexibility" nobody asked for. If 200 lines could be 50, rewrite it.
3. **Surgical changes.** Only touch what the task requires. Don't "improve" neighboring code, don't refactor what isn't broken, don't delete comments you don't fully understand.
4. **Goal-driven execution.** Transform vague instructions into verifiable targets before writing a line. "Add validation" becomes "write tests for invalid inputs, then make them pass."
