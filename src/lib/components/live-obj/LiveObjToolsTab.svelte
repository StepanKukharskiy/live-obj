<script lang="ts">
	interface OpParam {
		name: string;
		type: string;
		description: string;
		default?: string;
	}

	interface Operation {
		name: string;
		category: string;
		description: string;
		params: OpParam[];
		example?: string;
		examples?: { label: string; code: string }[];
	}

	interface Category {
		name: string;
		operations: Operation[];
	}

	let expandedCategories = $state(
		new Set(['raw obj setup', 'post transforms', 'post mesh cleanup', 'post metadata'])
	);

	const categories: Category[] = [
		{
			name: 'raw obj setup',
			operations: [
				{
					name: '#@source: llm_mesh',
					category: 'Raw OBJ metadata',
					description: 'Marks an object as raw LLM-authored OBJ geometry for raw-post execution.',
					params: [
						{ name: 'o', type: 'string', description: 'Stable object name used by target edits' },
						{
							name: '#@semantic',
							type: 'string',
							description: 'Short editable intent for the mesh'
						},
						{
							name: '#@bbox',
							type: 'vec3 pairs',
							description: 'Approximate min and max bounds for validation and targeting'
						}
					],
					example:
						'o half_mask_raw\n#@source: llm_mesh\n#@semantic: sculptural half mask\n#@bbox min=[0,-0.35,0] max=[0.55,0.35,0.9]\nv 0.00 0.00 0.00\nv 0.50 0.00 0.00\nv 0.20 0.20 0.60\nf 1 2 3'
				},
				{
					name: '#@params',
					category: 'Raw OBJ metadata',
					description: 'Defines simple numeric values that #@post ops can reuse.',
					params: [
						{
							name: 'name',
							type: 'number | vec3',
							description: 'Bare parameter names, referenced without ${...} templating'
						}
					],
					example:
						'#@params: module_count=4, lift=0.28\n\no module\n#@source: llm_mesh\n#@post:\n#@ - array count=module_count offset=[0,0,lift]'
				}
			]
		},
		{
			name: 'post transforms',
			operations: [
				{
					name: 'transform',
					category: '#@post',
					description: 'Moves, rotates, scales, or pivots raw mesh vertices after generation.',
					params: [
						{
							name: 'position',
							type: 'vec3',
							description: 'Translation after rotation and scale',
							default: '[0,0,0]'
						},
						{
							name: 'rotation',
							type: 'vec3',
							description: 'Euler rotation in degrees',
							default: '[0,0,0]'
						},
						{ name: 'scale', type: 'vec3', description: 'Per-axis scale', default: '[1,1,1]' },
						{
							name: 'pivot',
							type: 'vec3',
							description: 'Pivot point for scale and rotation',
							default: '[0,0,0]'
						}
					],
					example:
						'#@post:\n#@ - transform position=[0,0,0.2] rotation=[0,0,12] scale=[1.1,1,1] pivot=[0,0,0]'
				},
				{
					name: 'symmetrize',
					category: '#@post',
					description: 'Keeps one side of the mesh and mirrors it across an axis.',
					params: [
						{ name: 'axis', type: 'x | y | z', description: 'Mirror plane normal', default: 'x' },
						{
							name: 'side',
							type: 'positive | negative',
							description: 'Side to preserve before mirroring',
							default: 'positive'
						}
					],
					example: '#@post:\n#@ - symmetrize axis=x side=positive'
				},
				{
					name: 'mirror',
					category: '#@post',
					description: 'Duplicates the whole mesh as a mirrored copy.',
					params: [
						{ name: 'axis', type: 'x | y | z', description: 'Axis to negate', default: 'x' }
					],
					example: '#@post:\n#@ - mirror axis=x'
				},
				{
					name: 'array',
					category: '#@post',
					description: 'Repeats the raw mesh in a linear stack.',
					params: [
						{ name: 'count', type: 'int', description: 'Number of copies', default: '1' },
						{
							name: 'offset',
							type: 'vec3',
							description: 'Per-copy translation',
							default: '[0,0,0]'
						},
						{
							name: 'centered',
							type: 'boolean',
							description: 'Center the array around the original',
							default: 'false'
						},
						{
							name: 'scale',
							type: 'vec3 expr',
							description: 'Per-copy scale; supports i, t, step, count, sin/cos, pi/tau',
							default: '[1,1,1]'
						},
						{
							name: 'position',
							type: 'vec3 expr',
							description: 'Extra per-copy translation expression',
							default: '[0,0,0]'
						},
						{
							name: 'pivot',
							type: 'vec3 expr',
							description: 'Scale pivot for per-copy transforms',
							default: '[0,0,0]'
						}
					],
					example:
						'#@post:\n#@ - array count=frame_count offset=[bay_spacing,0,0] centered=true scale=[1,1,1+sin(t*tau)*wave_amount] pivot=[0,0,0]'
				},
				{
					name: 'scatter',
					category: '#@post',
					description:
						'Duplicates the raw mesh across a rectangular field with seeded random placement.',
					params: [
						{ name: 'count', type: 'int', description: 'Number of copies to place', default: '1' },
						{
							name: 'width',
							type: 'number expr',
							description: 'Field size along the first scatter axis',
							default: '1'
						},
						{
							name: 'depth',
							type: 'number expr',
							description: 'Field size along the second scatter axis',
							default: '1'
						},
						{
							name: 'axes',
							type: 'xz | xy | yz',
							description: 'Plane to scatter on; xz suits y-up scenes',
							default: 'xz'
						},
						{
							name: 'target',
							type: 'object id',
							description: 'Optional mesh object to sample as the placement surface'
						},
						{ name: 'seed', type: 'int', description: 'Stable random seed', default: '1' },
						{
							name: 'min_distance',
							type: 'number expr',
							description: 'Minimum spacing between placements',
							default: '0'
						},
						{
							name: 'jitter',
							type: 'number expr',
							description: 'Extra per-placement offset noise',
							default: '0'
						},
						{
							name: 'normal_offset',
							type: 'number expr',
							description: 'Lift each copy along the sampled surface normal',
							default: '0'
						},
						{
							name: 'align_to_normal',
							type: 'boolean',
							description: 'Tilt local up toward the sampled surface normal',
							default: 'false'
						},
						{
							name: 'rotation',
							type: 'vec3 expr',
							description: 'Per-copy rotation; supports rand/random values',
							default: '[0,0,0]'
						},
						{
							name: 'scale',
							type: 'vec3 expr | [min,max]',
							description: 'Per-copy scale or uniform random scale range',
							default: '[1,1,1]'
						},
						{
							name: 'position',
							type: 'vec3 expr',
							description: 'Extra per-copy offset using px, py, pz, rand, i, count, and t',
							default: '[0,0,0]'
						},
						{
							name: 'pivot',
							type: 'vec3 expr',
							description: 'Scale and rotation pivot',
							default: '[0,0,0]'
						}
					],
					example:
						'#@post:\n#@ - scatter count=gate_count target=landscape axes=xz seed=scatter_seed min_distance=gate_spacing jitter=0.25 normal_offset=0.02 rotation=[0,rand*360,0] scale=[0.85,1.15] pivot=[0,0,0]'
				},
				{
					name: 'surface_snap',
					category: '#@post',
					description:
						'Places one raw mesh onto a named mesh surface; array copies snap independently.',
					params: [
						{ name: 'target', type: 'object id', description: 'Surface object to project onto' },
						{
							name: 'normal_offset',
							type: 'number expr',
							description: 'Lift along sampled normal',
							default: '0'
						},
						{
							name: 'align_to_normal',
							type: 'boolean',
							description: 'Tilt local up toward the sampled normal',
							default: 'false'
						},
						{
							name: 'pivot',
							type: 'vec3 expr',
							description: 'Point on this mesh to place on the surface',
							default: 'bottom center'
						},
						{
							name: 'mode',
							type: 'instances | object',
							description: 'Snap remembered array copies or the entire object',
							default: 'instances'
						}
					],
					example: '#@post:\n#@ - surface_snap target=terrain normal_offset=0.02'
				},
				{
					name: 'conform',
					category: '#@post',
					description: 'Projects vertices onto a named surface while preserving local thickness.',
					params: [
						{ name: 'target', type: 'object id', description: 'Surface object to conform to' },
						{ name: 'strength', type: 'number', description: 'Blend amount', default: '1' },
						{
							name: 'normal_offset',
							type: 'number expr',
							description: 'Lift along sampled normal',
							default: '0'
						}
					],
					example: '#@post:\n#@ - conform target=terrain strength=1 normal_offset=0.01'
				},
				{
					name: 'path_array',
					category: '#@post',
					description: 'Repeats the raw mesh along a named path object vertex polyline.',
					params: [
						{
							name: 'path',
							type: 'object id',
							description: 'Path object whose vertices define the route'
						},
						{ name: 'count', type: 'int', description: 'Number of copies', default: '2' },
						{ name: 'spacing', type: 'number expr', description: 'Distance between copies' },
						{
							name: 'rotation_mode',
							type: 'tangent | none',
							description: 'Orient copies along path direction',
							default: 'tangent'
						},
						{
							name: 'scale',
							type: 'vec3 expr | [min,max]',
							description: 'Per-copy scale or uniform random range',
							default: '[1,1,1]'
						}
					],
					example:
						'#@post:\n#@ - path_array path=trail spacing=1.2 rotation_mode=tangent scale=[0.95,1.05]'
				},
				{
					name: 'surface_array',
					category: '#@post',
					description: 'Repeats the raw mesh in an ordered grid or hex pattern on a named surface.',
					params: [
						{ name: 'target', type: 'object id', description: 'Surface object to populate' },
						{ name: 'spacing', type: 'number expr', description: 'Pattern spacing', default: '1' },
						{ name: 'pattern', type: 'grid | hex', description: 'Ordered layout', default: 'grid' },
						{ name: 'count', type: 'int', description: 'Maximum copies' },
						{
							name: 'align_to_normal',
							type: 'boolean',
							description: 'Tilt local up toward each sampled normal',
							default: 'false'
						}
					],
					example:
						'#@post:\n#@ - surface_array target=terrain spacing=1.5 pattern=hex normal_offset=0.02'
				},
				{
					name: 'orient',
					category: '#@post',
					description: 'Rotates a mesh to face toward or away from a point or object.',
					params: [
						{ name: 'mode', type: 'face | away', description: 'Orientation mode', default: 'face' },
						{ name: 'target', type: 'object id', description: 'Object to face' },
						{
							name: 'point',
							type: 'vec3',
							description: 'Point to face when no target is supplied'
						},
						{
							name: 'pivot',
							type: 'vec3 expr',
							description: 'Rotation pivot',
							default: 'mesh center'
						}
					],
					example: '#@post:\n#@ - orient mode=face target=center_marker'
				},
				{
					name: 'clip',
					category: '#@post',
					description: 'Conservatively removes faces outside an axis or box range.',
					params: [
						{ name: 'axis', type: 'x | y | z', description: 'Axis for min/max clipping' },
						{ name: 'min', type: 'number expr', description: 'Minimum kept coordinate' },
						{ name: 'max', type: 'number expr', description: 'Maximum kept coordinate' },
						{ name: 'center', type: 'vec3 expr', description: 'Optional clipping box center' },
						{ name: 'size', type: 'vec3 expr', description: 'Optional clipping box size' }
					],
					example: '#@post:\n#@ - clip axis=y min=0 max=2.5'
				},
				{
					name: 'deform',
					category: '#@post',
					description: 'Moves each vertex with an expression after previous post ops.',
					params: [
						{
							name: 'position',
							type: 'vec3 expr',
							description: 'New vertex position using x, y, z plus normalized u, v, w',
							default: '[x,y,z]'
						}
					],
					example: '#@post:\n#@ - deform position=[x,y+(w*w*sin(u*tau)*wave_amount),z]'
				}
			]
		},
		{
			name: 'post mesh cleanup',
			operations: [
				{
					name: 'subdivide',
					category: '#@post',
					description: 'Splits faces to add simple mesh density before smoothing.',
					params: [
						{
							name: 'level',
							type: 'int',
							description: 'Subdivision passes, clamped to 0-3',
							default: '1'
						}
					],
					example: '#@post:\n#@ - subdivide level=1'
				},
				{
					name: 'smooth',
					category: '#@post',
					description: 'Applies Laplacian smoothing to soften raw vertices.',
					params: [
						{ name: 'iterations', type: 'int', description: 'Smoothing passes', default: '1' },
						{
							name: 'strength',
							type: 'float',
							description: 'Blend toward neighbor average, 0-1',
							default: '0.5'
						}
					],
					example: '#@post:\n#@ - smooth iterations=3 strength=0.35'
				},
				{
					name: 'simplify',
					category: '#@post',
					description: 'Keeps a ratio of faces for lighter raw meshes.',
					params: [
						{
							name: 'ratio',
							type: 'float',
							description: 'Face ratio to keep, clamped to 0.05-1.0',
							default: '1.0'
						}
					],
					example: '#@post:\n#@ - simplify ratio=0.65'
				},
				{
					name: 'snap_to_ground',
					category: '#@post',
					description: 'Moves the mesh so its minimum bound on the chosen axis is zero.',
					params: [{ name: 'axis', type: 'x | y | z', description: 'Ground axis', default: 'y' }],
					example: '#@post:\n#@ - snap_to_ground axis=z'
				},
				{
					name: 'center_origin',
					category: '#@post',
					description: 'Centers the mesh around the origin on selected axes.',
					params: [
						{
							name: 'axes',
							type: 'xz | xy | yz | xyz',
							description: 'Axes to center',
							default: 'xz'
						}
					],
					example: '#@post:\n#@ - center_origin axes=xz'
				}
			]
		},
		{
			name: 'post metadata',
			operations: [
				{
					name: 'material',
					category: '#@post',
					description: 'Assigns a named material preset without changing geometry.',
					params: [{ name: 'name', type: 'string', description: 'Material preset id' }],
					example:
						'#@material_preset: clay_warm color=#b98d72 roughness=0.82 metalness=0.0\n\n#@post:\n#@ - material name=clay_warm'
				},
				{
					name: 'tag',
					category: '#@post',
					description: 'Adds a lightweight semantic category for downstream tools.',
					params: [
						{
							name: 'value',
							type: 'string',
							description: 'Tag such as product, art, architectural, prop, or structural'
						}
					],
					example: '#@post:\n#@ - tag value=architectural'
				}
			]
		}
	];

	function expandAll() {
		expandedCategories = new Set(categories.map((c) => c.name));
	}

	function collapseAll() {
		expandedCategories = new Set<string>();
	}

	async function copyToClipboard(text: string) {
		try {
			await navigator.clipboard.writeText(text);
		} catch (err) {
			console.error('Failed to copy:', err);
		}
	}
</script>

<div class="tools-tab">
	<div class="tools-header">
		<h2>Raw OBJ Post Ops Reference</h2>
		<div class="tools-actions">
			<button type="button" onclick={expandAll} class="tools-action-btn">Expand All</button>
			<button type="button" onclick={collapseAll} class="tools-action-btn">Collapse All</button>
		</div>
	</div>

	<div class="tools-categories">
		{#each categories as category (category.name)}
			<details
				class="tools-category"
				open={expandedCategories.has(category.name)}
				ontoggle={(e) => {
					const details = e.currentTarget as HTMLDetailsElement;
					if (details.open) {
						expandedCategories = new Set([...expandedCategories, category.name]);
					} else {
						expandedCategories = new Set(
							[...expandedCategories].filter((n) => n !== category.name)
						);
					}
				}}
			>
				<summary class="tools-category-header">
					<span class="tools-category-title">{category.name}</span>
					<span class="tools-category-toggle">▶</span>
				</summary>

				<div class="tools-category-content">
					{#each category.operations as op (op.name)}
						<div class="tools-operation">
							<h3 class="tools-operation-name">{op.name}</h3>
							<p class="tools-operation-description">{op.description}</p>
							{#if op.params.length > 0}
								<div class="tools-params">
									<h4 class="tools-params-title">Parameters:</h4>
									{#each op.params as param (param.name)}
										<div class="tools-param">
											<code class="tools-param-name">{param.name}</code>
											<span class="tools-param-type">({param.type})</span>
											<span class="tools-param-desc">: {param.description}</span>
											{#if param.default}
												<span class="tools-param-default"> = {param.default}</span>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
							{#if op.examples && op.examples.length > 0}
								{#each op.examples as ex (ex.label)}
									<div class="tools-example">
										<div class="tools-example-header">
											<h4 class="tools-example-title">{ex.label}:</h4>
											<button
												type="button"
												class="tools-copy-btn"
												onclick={() => copyToClipboard(ex.code)}
												title="Copy to clipboard"
											>
												<svg
													width="14"
													height="14"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												>
													<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
													<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
												</svg>
											</button>
										</div>
										<pre class="tools-example-code">{ex.code}</pre>
									</div>
								{/each}
							{/if}
							{#if op.example && !op.examples}
								<div class="tools-example">
									<div class="tools-example-header">
										<h4 class="tools-example-title">Example:</h4>
										<button
											type="button"
											class="tools-copy-btn"
											onclick={() => copyToClipboard(op.example || '')}
											title="Copy to clipboard"
										>
											<svg
												width="14"
												height="14"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="2"
												stroke-linecap="round"
												stroke-linejoin="round"
											>
												<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
												<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
											</svg>
										</button>
									</div>
									<pre class="tools-example-code">{op.example}</pre>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</details>
		{/each}
	</div>
</div>

<style>
	.tools-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.tools-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		padding: 0 0 12px;
		border-bottom: 1px solid var(--spell-border-soft);
		flex-shrink: 0;
	}

	.tools-header h2 {
		margin: 0;
		font-size: 14px;
		font-weight: 750;
		color: var(--spell-ink);
	}

	.tools-actions {
		display: flex;
		gap: 8px;
	}

	.tools-action-btn {
		padding: 6px 11px;
		font-size: 11px;
		font-weight: 700;
		border: 1px solid var(--spell-border);
		background: var(--spell-surface-soft);
		border-radius: var(--spell-radius-pill);
		cursor: pointer;
		color: var(--spell-muted);
		transition: all 0.15s;
	}

	.tools-action-btn:hover {
		background: var(--spell-surface);
		border-color: rgba(0, 0, 235, 0.16);
		color: var(--spell-ink);
	}

	.tools-categories {
		flex: 1;
		overflow-y: auto;
		padding: 12px 0 0;
	}

	.tools-category {
		margin-bottom: 10px;
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-md);
		background: var(--spell-surface-soft);
		overflow: hidden;
	}

	.tools-category-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: 11px 12px;
		border: none;
		background: transparent;
		cursor: pointer;
		font-size: 12px;
		font-weight: 750;
		color: var(--spell-ink);
		transition: background 0.15s;
		list-style: none;
		box-sizing: border-box;
	}

	.tools-category-header:hover {
		background: rgba(255, 255, 255, 0.48);
	}

	.tools-category[open] .tools-category-header {
		background: rgba(255, 255, 255, 0.56);
		border-bottom: 1px solid var(--spell-border-soft);
	}

	.tools-category-header::-webkit-details-marker {
		display: none;
	}

	.tools-category-title {
		text-transform: capitalize;
	}

	.tools-category-toggle {
		color: var(--spell-muted);
		font-size: 10px;
	}

	.tools-category-content {
		padding: 8px 12px 12px;
	}

	.tools-operation {
		padding: 10px 0;
		border-bottom: 1px solid var(--spell-border-soft);
	}

	.tools-operation:last-child {
		border-bottom: none;
		padding-bottom: 0;
	}

	.tools-operation-name {
		margin: 0 0 4px;
		font-size: 12px;
		font-weight: 750;
		color: var(--spell-ink);
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
	}

	.tools-operation-description {
		margin: 0 0 8px;
		font-size: 11px;
		color: var(--spell-muted);
		line-height: 1.4;
	}

	.tools-params {
		margin-top: 8px;
		padding: 8px;
		background: var(--spell-surface-faint);
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-sm);
	}

	.tools-params-title {
		margin: 0 0 6px;
		font-size: 10px;
		font-weight: 750;
		color: var(--spell-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.tools-param {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 8px;
		margin-bottom: 4px;
		font-size: 11px;
		line-height: 1.5;
	}

	.tools-param:last-child {
		margin-bottom: 0;
	}

	.tools-param-name {
		color: var(--spell-blue);
		background: var(--spell-blue-soft);
		padding: 2px 6px;
		border-radius: var(--spell-radius-xs);
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
		font-size: 10px;
	}

	.tools-param-type {
		color: var(--spell-muted);
		font-style: italic;
	}

	.tools-param-desc {
		color: var(--spell-muted);
		flex: 1;
		min-width: 120px;
	}

	.tools-param-default {
		color: #059669;
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
		font-size: 10px;
	}

	.tools-example {
		margin-top: 8px;
		padding: 8px;
		background: rgba(0, 0, 235, 0.035);
		border-radius: var(--spell-radius-sm);
		border: 1px solid rgba(0, 0, 235, 0.15);
	}

	.tools-example-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 6px;
	}

	.tools-example-title {
		margin: 0;
		font-size: 10px;
		font-weight: 750;
		color: var(--spell-blue);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.tools-copy-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 4px;
		background: var(--spell-blue-soft);
		border: 1px solid rgba(0, 0, 235, 0.2);
		border-radius: var(--spell-radius-pill);
		cursor: pointer;
		color: var(--spell-blue);
		transition: all 0.15s;
	}

	.tools-copy-btn:hover {
		background: rgba(0, 0, 235, 0.15);
		border-color: rgba(0, 0, 235, 0.3);
	}

	.tools-copy-btn:active {
		background: rgba(0, 0, 235, 0.2);
	}

	.tools-example-code {
		margin: 0;
		padding: 8px;
		background: var(--spell-surface);
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-sm);
		font-size: 11px;
		color: var(--spell-ink);
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
		white-space: pre-wrap;
		word-break: break-all;
		overflow-x: auto;
		line-height: 1.4;
	}
</style>
