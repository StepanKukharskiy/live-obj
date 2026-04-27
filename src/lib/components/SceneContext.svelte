<script>
	import { sceneContext, updateSceneContext, clearSceneContext, parseColorFormat } from '$lib/stores/scene-context.js';
	import { onMount } from 'svelte';
	
	let style = '';
	let period = '';
	let paletteText = '';
	let description = '';
	let dominantMaterial = '';
	
	$: context = {
		style,
		period,
		palette: paletteText ? parseColorFormat(paletteText) : [],
		description,
		dominantMaterial,
		objects: []
	};
	
	function updateContext() {
		updateSceneContext(context);
	}
	
	function clearAll() {
		style = '';
		period = '';
		paletteText = '';
		description = '';
		dominantMaterial = '';
		clearSceneContext();
	}
	
	onMount(() => {
		// Load existing context
		sceneContext.subscribe(value => {
			if (value) {
				style = value.style || '';
				period = value.period || '';
				paletteText = (value.palette || []).join(', ');
				description = value.description || '';
				dominantMaterial = value.dominantMaterial || '';
			}
		})();
	});
</script>

<div class="scene-context-panel">
	<details class="obj-block" open>
		<summary class="obj-header">
			<span class="obj-name">Scene Context</span>
			<span class="obj-badge">Aesthetic Guide</span>
		</summary>
		
		<div class="context-fields">
			<div class="field-group">
				<label>Style</label>
				<input type="text" bind:value={style} placeholder="e.g., brutalist, minimalist" on:blur={updateContext} />
			</div>
			
			<div class="field-group">
				<label>Period</label>
				<input type="text" bind:value={period} placeholder="e.g., mid-century, modern" on:blur={updateContext} />
			</div>
			
			<div class="field-group">
				<label>Description</label>
				<input type="text" bind:value={description} placeholder="e.g., serene and contemplative space with warm lighting" on:blur={updateContext} />
			</div>
			
			<div class="field-group">
				<label>Palette</label>
				<input type="text" bind:value={paletteText} placeholder="#8B7355, rgb(44,44,44), white, terracotta, navy" on:blur={updateContext} />
			</div>
			
			<div class="field-group">
				<label>Dominant Materials</label>
				<input type="text" bind:value={dominantMaterial} placeholder="e.g., dark oak + black steel" on:blur={updateContext} />
			</div>
		</div>
		
		<div class="actions-list">
			<button class="clear-btn" on:click={clearAll}>Clear All</button>
		</div>
	</details>
</div>

<style>
	.scene-context-panel {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 4px;
		margin-bottom: 16px;
	}

	/* Main object block styling - matching params tab */
	.obj-block {
		background: rgba(255,255,255,0.6);
		border: 1px solid rgba(0,0,0,0.08);
		border-radius: 10px;
		margin-bottom: 10px;
		overflow: hidden;
	}

	.obj-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: 13px;
		font-weight: 600;
		color: #1a1a1a;
	}

	.obj-header::-webkit-details-marker { display: none; }
	.obj-name { flex: 1; }
	.obj-badge {
		background: rgba(0,0,235,0.08);
		color: #0000eb;
		font-size: 10px;
		font-weight: 500;
		padding: 2px 7px;
		border-radius: 10px;
	}

	.context-fields {
		padding: 2px 10px 8px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.field-group {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
	}

	.field-group label {
		color: #555;
		font-weight: 500;
		min-width: 110px;
		flex-shrink: 0;
	}

	.field-group input {
		background: rgba(255,255,255,0.8);
		border: 1px solid rgba(0,0,0,0.1);
		border-radius: 4px;
		padding: 6px 8px;
		font-size: 12px;
		color: #1a1a1a;
		font-family: inherit;
		flex: 1;
	}

	.field-group input:focus {
		outline: none;
		border-color: #0000eb;
		box-shadow: 0 0 0 2px rgba(0,0,235,0.1);
	}

	.actions-list {
		padding: 2px 10px 8px;
		display: flex;
		justify-content: flex-end;
	}

	.clear-btn {
		padding: 6px 12px;
		background: rgba(0, 0, 0, 0.06);
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 6px;
		font-size: 11px;
		cursor: pointer;
		transition: all 0.2s;
	}

	.clear-btn:hover {
		background: rgba(0, 0, 0, 0.1);
		border-color: rgba(0, 0, 0, 0.2);
		color: #000;
	}
</style>
