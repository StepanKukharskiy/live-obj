# Spellshape Grasshopper Canvas Panels

Copy these into large Grasshopper Panels in the downloadable `.gh` file.

## Quick Start

```text
SPELLSHAPE GRASSHOPPER QUICK START

1. Choose a provider: openai, openrouter, anthropic, google, gemini, or custom.
2. Paste your own API key into the api_key Panel.
3. Type a scene prompt.
4. Press plan_run once.
5. Press next_run repeatedly, or enable auto_run.
6. Watch progress / active_part / status.
7. The builder current_obj output goes into the renderer live_obj input.
8. The renderer creates Rhino meshes and automatic sliders from #@controls.
9. Press reset before starting a totally unrelated object.

Never share a GH file with your API key still inside it.
```

## Builder Node

```text
DECOMPOSED BUILDER NODE

plan_run:
Creates a part plan from the prompt.

next_run:
Generates one part and appends it to the current OBJ.

auto_run:
Keeps generating one part per solution until complete.

reset:
Clears the stored plan and OBJ scene.

status / error / debug:
Use these first when something seems stuck.
```

## Renderer Node

```text
RENDERER NODE

live_obj:
OBJ / Live OBJ text from the builder.

values:
Automatic sliders, toggles, and value lists connect here.

refresh_controls:
Press once after new #@controls appear.

clear_controls:
Removes generated controls.

The renderer reads #@up: y and displays geometry correctly in Rhino Z-up.
```

## Privacy

```text
PRIVACY

This GH file calls your chosen LLM provider directly from your Rhino machine.
Spellshape does not proxy these LLM calls.
The GHPython scripts do not send telemetry to Spellshape.
API keys, prompts, and OBJ files stay between you and your selected provider.
```

## Updates

```text
UPDATES

Use the Spellshape Update Checker node to check for the latest .gh file.
Default site URL:
https://live-obj-production.up.railway.app/

The GHPython scripts include a release date at the top.
If the checker says your local release date is older than the website release date, download the new GH file.
The checker only sends one GET request when you press check.
```
