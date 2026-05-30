<script lang="ts">
	type RenderingMode = 'standard' | 'outline' | 'toon';
	type CanvasAspectRatio =
		| 'fill'
		| '1:1'
		| '4:3'
		| '16:9'
		| '9:16'
		| '4:5'
		| '3:2'
		| '2:3'
		| '21:9';

	let {
		backgroundColor = $bindable('#3a3a36'),
		canvasAspectRatio = $bindable<CanvasAspectRatio>('fill'),
		showGrid = $bindable(false),
		showAxes = $bindable(false),
		wireframe = $bindable(false),
		ambientLightIntensity = $bindable(1),
		directionalLightIntensity = $bindable(1.5),
		enableShadows = $bindable(true),
		fogEnabled = $bindable(false),
		fogNear = $bindable(10),
		fogFar = $bindable(50),
		fogColor = $bindable('#f8fafc'),
		cameraFov = $bindable(50),
		toneMappingExposure = $bindable(1),
		renderingMode = $bindable<RenderingMode>('standard'),
		outlineThickness = $bindable(1),
		outlineDepthSensitivity = $bindable(1),
		outlineNormalSensitivity = $bindable(1),
		toonSteps = $bindable<2 | 3 | 4 | 5>(3),
		toonOutline = $bindable(true),
		liveObjText = '',
		onOpenLiveObj
	}: {
		backgroundColor?: string;
		canvasAspectRatio?: CanvasAspectRatio;
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
		renderingMode?: RenderingMode;
		outlineThickness?: number;
		outlineDepthSensitivity?: number;
		outlineNormalSensitivity?: number;
		toonSteps?: 2 | 3 | 4 | 5;
		toonOutline?: boolean;
		liveObjText?: string;
		onOpenLiveObj?: (sourceText: string) => void | Promise<void>;
	} = $props();

	let openFileInput: HTMLInputElement | undefined = $state();

	function downloadObj() {
		if (!liveObjText.trim()) return;
		const blob = new Blob([liveObjText], { type: 'text/plain' });
		const url = URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.href = url;
		link.download = 'spellshape-live.obj';
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(url);
	}

	async function openObjFile(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		const text = await file.text();
		await Promise.resolve(onOpenLiveObj?.(text));
		input.value = '';
	}
</script>

<div class="live-obj-scene">
	<div class="live-obj-file-actions">
		<button
			type="button"
			class="send-button live-obj-file-secondary-button"
			onclick={() => openFileInput?.click()}
		>
			Open Live OBJ
		</button>
		<button type="button" class="send-button" onclick={downloadObj} disabled={!liveObjText.trim()}>
			Save Live OBJ
		</button>
		<input
			bind:this={openFileInput}
			type="file"
			accept=".obj,text/plain"
			class="live-obj-file-input"
			onchange={openObjFile}
		/>
	</div>
	<p class="live-obj-save-helper">
		A standard OBJ with Spellshape metadata. Opens in any 3D app; reopen in Spellshape for editable
		parts and parameters.
	</p>
	<div class="planner-chain">
		<label class="planner-context-field rendering-mode">
			<span class="planner-label-inline">Canvas</span>
			<select bind:value={canvasAspectRatio}>
				<option value="fill">Fill window</option>
				<option value="1:1">1:1 square</option>
				<option value="4:3">4:3 landscape</option>
				<option value="16:9">16:9 wide</option>
				<option value="9:16">9:16 portrait</option>
				<option value="4:5">4:5 portrait</option>
				<option value="3:2">3:2 photo</option>
				<option value="2:3">2:3 portrait</option>
				<option value="21:9">21:9 cinema</option>
			</select>
		</label>
		<label class="planner-context-field rendering-mode">
			<span class="planner-label-inline">Render</span>
			<select bind:value={renderingMode}>
				<option value="standard">Standard</option>
				<option value="outline">Outlines</option>
				<option value="toon">Toon</option>
			</select>
		</label>
		{#if renderingMode === 'outline'}
			<label class="planner-context-field"
				><span class="planner-label-inline">Outline thickness</span>
				<input
					class="planner-text-input"
					type="number"
					step="0.1"
					min="0.1"
					max="5"
					bind:value={outlineThickness}
				/>
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Depth sensitivity</span>
				<input
					class="planner-text-input"
					type="number"
					step="0.1"
					min="0"
					max="5"
					bind:value={outlineDepthSensitivity}
				/>
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Normal sensitivity</span>
				<input
					class="planner-text-input"
					type="number"
					step="0.1"
					min="0"
					max="5"
					bind:value={outlineNormalSensitivity}
				/>
			</label>
		{/if}
		{#if renderingMode === 'toon'}
			<label class="planner-context-field planner-checkbox-row"
				><span class="planner-label-inline">Toon outline</span>
				<input type="checkbox" bind:checked={toonOutline} />
			</label>
			<label class="planner-context-field toon-steps">
				<span class="planner-label-inline">Toon steps</span>
				<select bind:value={toonSteps}>
					<option value={2}>2</option>
					<option value={3}>3</option>
					<option value={4}>4</option>
					<option value={5}>5</option>
				</select>
			</label>
		{/if}
		<label class="planner-context-field"
			><span class="planner-label-inline">Background</span>
			<input class="planner-text-input" type="color" bind:value={backgroundColor} />
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Ambient</span>
			<input
				class="planner-text-input"
				type="number"
				step="0.1"
				bind:value={ambientLightIntensity}
			/>
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Directional</span>
			<input
				class="planner-text-input"
				type="number"
				step="0.1"
				bind:value={directionalLightIntensity}
			/>
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
			<input
				class="planner-text-input"
				type="number"
				step="1"
				min="10"
				max="120"
				bind:value={cameraFov}
			/>
		</label>
		<label class="planner-context-field"
			><span class="planner-label-inline">Exposure</span>
			<input
				class="planner-text-input"
				type="number"
				step="0.05"
				min="0"
				bind:value={toneMappingExposure}
			/>
		</label>
	</div>
</div>

<style>
	.live-obj-file-actions {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
		margin: 12px 0;
	}

	.live-obj-file-actions > button {
		width: 100%;
	}

	.live-obj-file-secondary-button {
		border: 1px solid rgba(0, 0, 235, 0.48);
		background: transparent;
		color: var(--spell-blue);
		box-shadow: none;
	}

	.live-obj-file-secondary-button:hover:not(:disabled) {
		border-color: var(--spell-blue);
		background: rgba(0, 0, 235, 0.05);
		color: var(--spell-blue-hover);
		box-shadow: none;
	}

	.live-obj-file-secondary-button:disabled {
		border-color: rgba(0, 0, 0, 0.14);
		background: transparent;
		color: rgba(0, 0, 0, 0.3);
		box-shadow: none;
	}

	.live-obj-file-input {
		display: none;
	}

	.live-obj-save-helper {
		margin: -4px 0 12px;
		color: rgba(15, 23, 42, 0.68);
		font-size: 0.82rem;
		line-height: 1.35;
	}

	.rendering-mode select,
	.toon-steps select {
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
