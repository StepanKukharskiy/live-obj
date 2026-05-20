# Spellshape

AI-native 3D authoring for portable, editable Live OBJ scenes.

## What is Spellshape?

Spellshape is a web-based 3D modeling tool for creating and iterating on semantic 3D scenes with AI. It runs on Live OBJ: standard OBJ geometry plus ignored-by-default `#@` metadata for editable parts, parameters, procedural intent, signed distance fields (SDF), simulations, and more.

Spellshape scenes are valid OBJ files. They open in ordinary 3D software as normal meshes, and reopen in Spellshape-aware tools as editable semantic scenes.

### Key Features

- **Natural Language to Editable Scenes**: Describe what you want to build, then keep editing semantic parts and parameters
- **Live OBJ Format**: Standard OBJ files with `#@` metadata that drives editable scene regeneration
- **Portable Project Artifact**: Save a Live OBJ that works as mesh geometry anywhere and stays editable in Spellshape
- **Bring Your Own API Key**: Use your own OpenAI API key for model access
- **Multiple Generation Methods**:
  - Procedural generation (CADQuery kernel)
  - Signed Distance Fields (SDF) with CSG operations
  - Simulations (cellular automata, differential growth, boids, flow fields)
  - Mesh operations (voxelization, smoothing, beveling, etc.)
- **Platform Support**: Web (beta), Grasshopper (beta), Blender (coming soon)

## Architecture

### Live OBJ Workflow

1. User sends prompt/chat history to Live OBJ API
2. Model returns Live OBJ text (`#@` metadata + OBJ cache)
3. Executor expands/regenerates geometry from metadata
4. UI shows chat, source outputs (live/raw/executed), and metadata-driven controls
5. User saves the Live OBJ as the durable editable scene artifact

The `#@` metadata is the editable source of truth; mesh `v/f` is cache/output.

### Live OBJ as Project File

A saved Live OBJ is not just a baked mesh export. It is a standard OBJ file with Spellshape metadata:

```obj
#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1

o roof
#@source: procedural
#@semantic: dominant sculptural roof
#@params: width=6.0, depth=4.0, overhang=1.2
v ...
f ...
```

Other tools can ignore the `#@` comments and read the geometry. Spellshape reads the metadata first, treats it as authoritative, and can regenerate the cached mesh when parameters or semantic edits change.

Raw-first scenes can also carry post-parametric edit intent without becoming procedural CAD:

```obj
o roof
#@source: llm_mesh
#@semantic: heavy chapel roof
#@part: id=roof role=dominant_form edit=direct
#@params: roof_lift=0
#@bbox: min=[-4,2,-2] max=[4,5,2]
#@lock: silhouette, material
#@anchor: id=roof_left_edge at=[-4,2,0]
#@constraint: roof must_touch walls
#@post:
#@ - transform position=[0,roof_lift,0]
v ...
f ...
```

In raw-post mode, `#@post` is the executable mesh modifier stack. Metadata such as `#@bbox`, `#@lock`, `#@part`, `#@anchor`, `#@constraint`, and `#@variant` records semantic edit intent for planning, validation, targeted edits, and future UI controls.

### Tech Stack

- **Frontend**: SvelteKit + TypeScript
- **Styling**: CSS
- **3D Rendering**: Three.js (via sceneBuilder.js)
- **AI**: OpenAI API (user-provided API key)

## Project Structure

```
src/
├── lib/
│   ├── components/     # UI components
│   ├── liveObj/       # Live OBJ parsing and execution logic
│   └── sceneBuilder.js # 3D scene setup and rendering
├── routes/
│   ├── api/           # API endpoints
│   ├── app/           # Main application interface
│   └── +page.svelte   # Landing page
└── app.html           # HTML template
```

## Development

```sh
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Legal

- [MIT License](LICENSE)
- [Privacy Policy](/src/routes/privacy/+page.svelte)
- [Terms of Use](/src/routes/terms/+page.svelte)

## Live OBJ Syntax Examples

### Procedural Generation

```
o wall
#@source: procedural
#@type: extrude
#@params: kernel=cadquery, profile=[[0,0,0],[4,0,0],[4,0,3],[0,0,3]], height=0.2
```

### SDF Operations

```
#@sdf:
#@ - box id=a center=[0,0,0] size=[1,1,1]
#@ - box id=b center=[0.5,0,0] size=[1,1,1]
#@ - union a b
```

### Transformations

```
#@ops:
#@ - transform position=[1,0,0] rotation=[0,0,45] scale=[2,2,2]
```

### Simulation

```
o coral
#@source: simulation
#@sim: cellular_automata
#@params: grid=[32,32,32], cell=0.08, steps=45, seed=8, mode=coral
```

## Contributing

This project follows the working principles outlined in AGENTS.md:

1. Think before coding - ask when ambiguous
2. Simplicity first - minimum code that solves the problem
3. Surgical changes - only touch what the task requires
4. Goal-driven execution - transform vague instructions into verifiable targets

## License

See LICENSE file for details.

## Links

- GitHub: https://github.com/StepanKukharskiy/live-obj
- Discord: https://discord.gg/58zSgpaGc
