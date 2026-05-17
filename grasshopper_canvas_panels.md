# Spellshape Grasshopper Canvas Panels

Copy these into large Grasshopper Panels in the downloadable `.gh` file.

## Quick Start

```text
SPELLSHAPE GRASSHOPPER QUICK START

There are two main GHPython nodes:

1. Decomposed Builder
   Calls your chosen LLM provider and outputs current_obj.

2. Live OBJ Renderer
   Reads current_obj, creates Rhino meshes, and creates automatic controls.

Basic wiring:
Builder current_obj -> Renderer live_obj
Renderer meshes -> Mesh preview / Custom Preview / Bake workflow
Generated sliders/toggles -> Renderer values

How to run:
1. In the Decomposed Builder node, choose provider: openai, openrouter, anthropic, google, gemini, or custom.
2. Paste your own API key into the api_key Panel.
3. Type a scene prompt into the prompt Panel.
4. Press the Builder plan_run button once.
5. Press the Builder next_run button repeatedly, or enable auto_run.
6. Watch Builder progress / active_part / status.
7. In the Renderer node, press refresh_controls after new #@controls appear.
8. Adjust generated sliders/toggles. They feed the Renderer values input.
9. Press Builder reset before starting a totally unrelated object.

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
