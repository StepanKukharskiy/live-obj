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
		onLiveObjMetadataChange
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
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
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
	/* Let this tab’s natural height grow; the side panel’s `.planner-tab-panel` scrolls (don’t fill 100vh in one column). */
	.live-obj-adjust {
		display: flex;
		flex-direction: column;
		gap: 12px;
		box-sizing: border-box;
		min-width: 0;
	}
	/* Bounded code area: Object + metadata stack below and scroll with the tab. */
	.live-obj-adjust-output {
		flex: 0 0 auto;
		width: 100%;
		min-width: 0;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		height: clamp(240px, 40vh, 480px);
		min-height: 220px;
	}
	.live-obj-adjust-output :global(.planner-output-block) {
		flex: 1;
		min-height: 0;
	}
</style>
