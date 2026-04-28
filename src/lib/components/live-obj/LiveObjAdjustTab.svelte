<script lang="ts">
	import LiveObjOutputTab from './LiveObjOutputTab.svelte';
	import type { SourceTab } from './LiveObjOutputTab.svelte';
	import LiveObjMetadataParams from './LiveObjMetadataParams.svelte';

	let {
		sourceTab = $bindable<SourceTab>('executed'),
		objectColor = $bindable('#7185d4'),
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
		onLiveObjMetadataChange,
		onApplyEditedSource
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
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
		onApplyEditedSource?: (sceneText: string) => void | Promise<void>;
	} = $props();
</script>

<div class="live-obj-adjust">
	<div class="live-obj-adjust-output">
		<LiveObjOutputTab
			sectionLabel="Source"
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
			<div class="planner-object-title-stack"><strong>Object</strong></div>
		</div>
		<div class="planner-chain">
			<label class="planner-context-field"
				><span class="planner-label-inline">Mesh color</span>
				<input class="planner-text-input" type="color" bind:value={objectColor} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Scale</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectScale} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Pos X</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectPosX} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Pos Y</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectPosY} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Pos Z</span>
				<input class="planner-text-input" type="number" step="0.05" bind:value={objectPosZ} />
			</label>
			<label class="planner-context-field"
				><span class="planner-label-inline">Rotate Y</span>
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
</style>
