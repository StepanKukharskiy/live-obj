# Spellshape

AI-native 3D authoring platform. Create 3D models by describing them in natural language.

## What is Spellshape?

Spellshape is a web-based 3D modeling tool that uses AI to generate 3D geometry from text descriptions. It runs on top of the OBJ file format enhanced with metadata, allowing for procedural generation, signed distance fields (SDF), simulations, and more.

### Key Features

- **Natural Language to 3D**: Type what you want to build, and AI generates the geometry
- **Live OBJ Format**: OBJ files with `#@` metadata that drives geometry generation
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

The `#@` metadata is the editable source of truth; mesh `v/f` is cache/output.

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
#@ - move offset=[1,0,0]
#@ - scale factor=2.0
#@ - rotate angle=45 axis=z
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
