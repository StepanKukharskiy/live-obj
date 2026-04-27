<script lang="ts">
	export let backgroundColor = '#e8ebf2';
	export let showGrid = true;
	export let showAxes = true;
	export let wireframe = false;
	export let objectColor = '#7185d4';
	export let objectScale = 1;
	export let objectPosX = 0;
	export let objectPosY = 0;
	export let objectPosZ = 0;
	export let objectRotYDeg = 0;
	export let ambientLightIntensity = 1;
	export let directionalLightIntensity = 1.5;
</script>

<div class="controls">
	<section>
		<h3>Scene</h3>
		<label>Background <input type="color" bind:value={backgroundColor} /></label>
		<label>Ambient Light <input type="range" min="0" max="3" step="0.1" bind:value={ambientLightIntensity} /></label>
		<label>Directional Light <input type="range" min="0" max="4" step="0.1" bind:value={directionalLightIntensity} /></label>
		<label class="check"><input type="checkbox" bind:checked={showGrid} /> Show Grid</label>
		<label class="check"><input type="checkbox" bind:checked={showAxes} /> Show Axes</label>
	</section>

	<section>
		<h3>Object</h3>
		<label>Color <input type="color" bind:value={objectColor} /></label>
		<label>Scale <input type="range" min="0.2" max="3" step="0.05" bind:value={objectScale} /></label>
		<label>Position X <input type="range" min="-3" max="3" step="0.05" bind:value={objectPosX} /></label>
		<label>Position Y <input type="range" min="-3" max="3" step="0.05" bind:value={objectPosY} /></label>
		<label>Position Z <input type="range" min="-3" max="3" step="0.05" bind:value={objectPosZ} /></label>
		<label>Rotate Y <input type="range" min="-180" max="180" step="1" bind:value={objectRotYDeg} /></label>
		<label class="check"><input type="checkbox" bind:checked={wireframe} /> Wireframe</label>
	</section>
</div>

<style>
	.controls {
		display: grid;
		gap: 12px;
		overflow-y: auto;
		padding-right: 4px;
		height: 100%;
	}
	section {
		background: rgba(255, 255, 255, 0.7);
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 10px;
		padding: 10px;
		display: grid;
		gap: 8px;
	}
	h3 {
		margin: 0;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		color: #555;
	}
	label {
		display: grid;
		grid-template-columns: 110px 1fr;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		color: #333;
	}
	label input[type='range'] {
		width: 100%;
	}
	label.check {
		grid-template-columns: 1fr;
	}
</style>
