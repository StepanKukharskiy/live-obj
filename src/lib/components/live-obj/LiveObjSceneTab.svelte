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
		toneMappingExposure = $bindable(1)
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
	} = $props();
</script>

<div class="live-obj-scene">
	<div class="planner-chain">
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
