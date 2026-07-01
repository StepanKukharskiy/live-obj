<script lang="ts">
	import LiveObjOutputTab from './LiveObjOutputTab.svelte';
	import type { SourceTab } from './LiveObjOutputTab.svelte';
	import LiveObjMetadataParams from './LiveObjMetadataParams.svelte';

	type EditorTransformMode = 'select' | 'translate' | 'rotate' | 'scale';
	type PartTransformUpdate = {
		objectName: string;
		position: [number, number, number];
		rotation: [number, number, number];
		scale: [number, number, number];
		pivot?: [number, number, number];
	};

	let {
		sourceTab = $bindable<SourceTab>('executed'),
		objectColor = $bindable('#e6e4dd'),
		objectScale = $bindable(1),
		objectPosX = $bindable(0),
		objectPosY = $bindable(0),
		objectPosZ = $bindable(0),
		objectRotYDeg = $bindable(0),
		liveObjText = '',
		rawLlmText = '',
		executedObjText = '',
		sceneEpoch = 0,
		sourceApplyBusy = false,
		selectedTargetObjectId = $bindable(''),
		editorTransformMode = $bindable<EditorTransformMode>('select'),
		targetObjectOptions = [],
		onLiveObjMetadataChange,
		onApplyEditedSource,
		onApplyPartTransform,
		onResetPartTransform
	}: {
		sourceTab?: SourceTab;
		objectColor?: string;
		objectScale?: number;
		objectPosX?: number;
		objectPosY?: number;
		objectPosZ?: number;
		objectRotYDeg?: number;
		liveObjText?: string;
		rawLlmText?: string;
		executedObjText?: string;
		sceneEpoch?: number;
		sourceApplyBusy?: boolean;
		selectedTargetObjectId?: string;
		editorTransformMode?: EditorTransformMode;
		targetObjectOptions?: string[];
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
		onApplyEditedSource?: (sceneText: string) => void | Promise<void>;
		onApplyPartTransform?: (update: PartTransformUpdate) => void | Promise<void>;
		onResetPartTransform?: (objectName: string) => void | Promise<void>;
	} = $props();

	let tx = $state(0);
	let ty = $state(0);
	let tz = $state(0);
	let rx = $state(0);
	let ry = $state(0);
	let rz = $state(0);
	let sx = $state(1);
	let sy = $state(1);
	let sz = $state(1);
	let px = $state(0);
	let py = $state(0);
	let pz = $state(0);

	function objectBlock(sourceText: string, objectName: string): string {
		if (!objectName) return '';
		return (
			sourceText
				.split(/(?=^\s*o\s+)/gm)
				.find((block) => block.match(/^\s*o\s+([^\s#]+)/m)?.[1] === objectName) ?? ''
		);
	}

	function parseVec(raw: string | undefined, fallback: [number, number, number]): [number, number, number] {
		if (!raw) return fallback;
		const values = raw
			.replace(/^\[|\]$/g, '')
			.split(',')
			.map((value) => Number(value.trim()));
		return [0, 1, 2].map((index) =>
			Number.isFinite(values[index]) ? values[index] : fallback[index]
		) as [number, number, number];
	}

	function metadataToken(raw: string, key: string): string | undefined {
		return raw.match(new RegExp(`(?:^|\\s)${key}=(\\[[^\\]]+\\]|\\S+)`))?.[1];
	}

	function finiteFieldValue(value: unknown, fallback: number): number {
		const numeric = Number(value);
		return Number.isFinite(numeric) ? numeric : fallback;
	}

	function finiteFieldVec(
		values: [unknown, unknown, unknown],
		fallback: [number, number, number]
	): [number, number, number] {
		return values.map((value, index) => finiteFieldValue(value, fallback[index])) as [
			number,
			number,
			number
		];
	}

	function loadSelectedTransform() {
		const block = objectBlock(liveObjText, selectedTargetObjectId);
		const line = block.match(/^\s*#@\s*-\s*transform\s+(.+)$/im)?.[1] ?? '';
		const position = parseVec(metadataToken(line, 'position'), [0, 0, 0]);
		const rotation = parseVec(metadataToken(line, 'rotation'), [0, 0, 0]);
		const scale = parseVec(metadataToken(line, 'scale'), [1, 1, 1]);
		const pivot = parseVec(metadataToken(line, 'pivot'), [0, 0, 0]);
		[tx, ty, tz] = position;
		[rx, ry, rz] = rotation;
		[sx, sy, sz] = scale;
		[px, py, pz] = pivot;
	}

	async function applySelectedTransform() {
		if (!selectedTargetObjectId || !onApplyPartTransform) return;
		await onApplyPartTransform({
			objectName: selectedTargetObjectId,
			position: finiteFieldVec([tx, ty, tz], [0, 0, 0]),
			rotation: finiteFieldVec([rx, ry, rz], [0, 0, 0]),
			scale: finiteFieldVec([sx, sy, sz], [1, 1, 1]),
			pivot: finiteFieldVec([px, py, pz], [0, 0, 0])
		});
	}

	async function resetSelectedTransform() {
		if (!selectedTargetObjectId || !onResetPartTransform) return;
		await onResetPartTransform(selectedTargetObjectId);
	}

	function toggleTransformMode(mode: Exclude<EditorTransformMode, 'select'>) {
		editorTransformMode = editorTransformMode === mode ? 'select' : mode;
	}

	$effect(() => {
		void liveObjText;
		void selectedTargetObjectId;
		void sceneEpoch;
		loadSelectedTransform();
	});
</script>

<div class="live-obj-adjust">
	<div class="live-obj-adjust-output">
		<LiveObjOutputTab
			bind:sourceTab
			{liveObjText}
			{rawLlmText}
			{executedObjText}
			{sceneEpoch}
			applyBusy={sourceApplyBusy}
			onApplySource={onApplyEditedSource}
		/>
	</div>
	<div class="planner-object-section">
		<div class="planner-object-header">
			<div class="planner-object-title-stack"><strong>Part Transform</strong></div>
		</div>
		<div class="planner-chain">
			<label class="planner-context-field">
				<span class="planner-label-inline">Target</span>
				<select class="planner-text-input" bind:value={selectedTargetObjectId}>
					<option value="">Choose part</option>
					{#each targetObjectOptions as objectName}
						<option value={objectName}>{objectName}</option>
					{/each}
				</select>
			</label>
			<div class="transform-mode-row" aria-label="Transform mode">
				<button
					type="button"
					class:active={editorTransformMode === 'translate'}
					onclick={() => toggleTransformMode('translate')}>Move</button
				>
				<button
					type="button"
					class:active={editorTransformMode === 'rotate'}
					onclick={() => toggleTransformMode('rotate')}>Rotate</button
				>
				<button
					type="button"
					class:active={editorTransformMode === 'scale'}
					onclick={() => toggleTransformMode('scale')}>Scale</button
				>
			</div>
			<div class="transform-grid">
				<label><span>X</span><input class="planner-text-input" type="number" step="0.05" bind:value={tx} /></label>
				<label><span>Y</span><input class="planner-text-input" type="number" step="0.05" bind:value={ty} /></label>
				<label><span>Z</span><input class="planner-text-input" type="number" step="0.05" bind:value={tz} /></label>
				<label><span>RX</span><input class="planner-text-input" type="number" step="1" bind:value={rx} /></label>
				<label><span>RY</span><input class="planner-text-input" type="number" step="1" bind:value={ry} /></label>
				<label><span>RZ</span><input class="planner-text-input" type="number" step="1" bind:value={rz} /></label>
				<label><span>SX</span><input class="planner-text-input" type="number" step="0.05" bind:value={sx} /></label>
				<label><span>SY</span><input class="planner-text-input" type="number" step="0.05" bind:value={sy} /></label>
				<label><span>SZ</span><input class="planner-text-input" type="number" step="0.05" bind:value={sz} /></label>
			</div>
			<div class="transform-actions">
				<button
					type="button"
					class="send-button transform-apply-button"
					onclick={() => void applySelectedTransform()}
					disabled={!selectedTargetObjectId || sourceApplyBusy}>Apply</button
				>
				<button
					type="button"
					class="transform-reset-button"
					onclick={() => void resetSelectedTransform()}
					disabled={!selectedTargetObjectId || sourceApplyBusy}>Reset</button
				>
			</div>
		</div>
	</div>
	<div class="planner-object-section">
		<div class="planner-object-header">
			<div class="planner-object-title-stack"><strong>Global Scene Transform</strong></div>
		</div>
		<div class="planner-chain">
			<label class="planner-context-field"
				><span class="planner-label-inline">Fallback mesh color</span>
				<input class="planner-text-input" type="color" bind:value={objectColor} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Global scale</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectScale} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Global Pos X</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectPosX} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Global Pos Y</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectPosY} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Global Pos Z</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectPosZ} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Global Rotate Y</span>
				<input class="planner-text-input" type="number" step="1" bind:value={objectRotYDeg} />
			</label>
		</div>
	</div>
	<LiveObjMetadataParams {liveObjText} {onLiveObjMetadataChange} />
</div>

<style>
	/* Block stack; `.planner-tab-panel` scrolls — no fixed-height box (that + overflow:hidden clipped Monaco’s toolbar). */
	.live-obj-adjust {
		display: block;
		box-sizing: border-box;
		min-width: 0;
	}
	.live-obj-adjust > * + * {
		margin-top: 12px;
	}
	.live-obj-adjust-output {
		width: 100%;
		min-width: 0;
	}
	.transform-mode-row {
		display: flex;
		gap: 4px;
		padding: 4px;
		border: 1px solid var(--spell-border);
		border-radius: var(--spell-radius-pill);
		background: var(--spell-surface-soft);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
	}
	.transform-mode-row button {
		flex: 1 1 0;
		min-width: 0;
		min-height: 30px;
		border: 1px solid transparent;
		border-radius: var(--spell-radius-pill);
		background: transparent;
		color: var(--spell-muted);
		cursor: pointer;
		font-size: 12px;
		font-weight: 750;
		font-family: inherit;
		transition:
			background 0.16s ease,
			color 0.16s ease,
			box-shadow 0.16s ease;
	}
	.transform-mode-row button:hover:not(.active) {
		background: rgba(255, 255, 255, 0.6);
		color: var(--spell-ink);
	}
	.transform-mode-row button.active {
		border: 1px solid rgba(0, 0, 235, 0.18);
		background: var(--spell-blue-soft);
		color: var(--spell-blue);
		box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.68);
	}
	.transform-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 6px;
	}
	.transform-grid label {
		display: grid;
		grid-template-columns: 28px minmax(0, 1fr);
		align-items: center;
		gap: 4px;
		font-size: 11px;
		font-weight: 700;
		color: var(--spell-muted);
	}
	.transform-grid input {
		min-width: 0;
		padding: 7px 8px;
		border-radius: var(--spell-radius-sm);
		font-size: 12px;
	}
	.transform-actions {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
		align-items: center;
	}
	.transform-apply-button {
		width: 100%;
	}
	.transform-reset-button {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 34px;
		border: 1px solid rgba(0, 0, 235, 0.34);
		border-radius: var(--spell-radius-pill);
		background: transparent;
		color: var(--spell-blue);
		font: inherit;
		font-size: 12px;
		font-weight: 750;
		cursor: pointer;
	}
	.transform-reset-button:hover:not(:disabled) {
		border-color: var(--spell-blue);
		background: rgba(0, 0, 235, 0.05);
		color: var(--spell-blue-hover);
	}
	.transform-actions button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}
</style>
