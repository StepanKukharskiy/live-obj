<script lang="ts">
	let {
		backgroundColor = $bindable('#e8ebf2'),
		showGrid = $bindable(true),
		showAxes = $bindable(true),
		wireframe = $bindable(false),
		ambientLightIntensity = $bindable(1),
		directionalLightIntensity = $bindable(1.5),
		enableShadows = $bindable(false),
		fogEnabled = $bindable(false),
		fogNear = $bindable(10),
		fogFar = $bindable(50),
		fogColor = $bindable('#f8fafc'),
		cameraFov = $bindable(50),
		toneMappingExposure = $bindable(1),
		kernelDefault = $bindable<'auto' | 'cadquery'>('cadquery'),
		executedObjText = ''
	}: {
		backgroundColor?: string;
		showGrid?: boolean;
		showAxes?: boolean;
		wireframe?: boolean;
		ambientLightIntensity?: number;
		directionalLightIntensity?: number;
		enableShadows?: boolean;
		fogEnabled?: boolean;
		fogNear?: number;
		fogFar?: number;
		fogColor?: string;
		cameraFov?: number;
		toneMappingExposure?: number;
		kernelDefault?: 'auto' | 'cadquery';
		executedObjText?: string;
	} = $props();

	function downloadObj() {
		if (!executedObjText.trim()) return;
		const blob = new Blob([executedObjText], { type: 'text/plain' });
		const url = URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.href = url;
		link.download = 'project-name.obj';
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(url);
	}
</script>

<div class="live-obj-scene">
	<button type="button" class="send-button" onclick={downloadObj} disabled={!executedObjText.trim()}>
		Download OBJ
	</button>
	<div class="planner-chain">
		<label class="planner-context-field kernel-default">
			<span class="planner-label-inline">Kernel</span>
			<select bind:value={kernelDefault}>
				<option value="auto">Auto</option>
				<option value="cadquery">CadQuery</option>
			</select>
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Background</span>
			<input class="planner-text-input" type="color" bind:value={backgroundColor} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Ambient</span>
			<input class="planner-text-input" type="number" step="0.1" bind:value={ambientLightIntensity} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Directional</span>
			<input class="planner-text-input" type="number" step="0.1" bind:value={directionalLightIntensity} />
		</label>
		<label class="planner-context-field planner-checkbox-row"
			><span class="planner-label-inline">Grid</span>
			<input type="checkbox" bind:checked={showGrid} />
		</label>
		<label class="planner-context-field planner-checkbox-row"
			><span class="planner-label-inline">Axes</span>
			<input type="checkbox" bind:checked={showAxes} />
		</label>
		<label class="planner-context-field planner-checkbox-row"
			><span class="planner-label-inline">Wireframe</span>
			<input type="checkbox" bind:checked={wireframe} />
		</label>
		<label class="planner-context-field planner-checkbox-row"
			><span class="planner-label-inline">Shadows</span>
			<input type="checkbox" bind:checked={enableShadows} />
		</label>
		<label class="planner-context-field planner-checkbox-row"
			><span class="planner-label-inline">Fog</span>
			<input type="checkbox" bind:checked={fogEnabled} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Fog near</span>
			<input class="planner-text-input" type="number" step="0.5" min="0" bind:value={fogNear} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Fog far</span>
			<input class="planner-text-input" type="number" step="0.5" min="0" bind:value={fogFar} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Fog color</span>
			<input class="planner-text-input" type="color" bind:value={fogColor} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Camera FOV</span>
			<input class="planner-text-input" type="number" step="1" min="10" max="120" bind:value={cameraFov} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Exposure</span>
			<input class="planner-text-input" type="number" step="0.05" min="0" bind:value={toneMappingExposure} />
		</label>
	</div>
</div>

<style>
	.live-obj-scene > button {
		margin: 12px 0;
		width: 100%;
	}

	.kernel-default select {
		box-sizing: border-box;
		max-width: 140px;
		height: 32px;
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.12);
		border-radius: 999px;
		padding: 0 10px;
		background: rgba(255, 255, 255, 0.95);
		cursor: pointer;
	}
</style>
