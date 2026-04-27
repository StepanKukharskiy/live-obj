<script lang="ts">
	import MonacoEditor from '$lib/components/MonacoEditor.svelte';

	export type SourceTab = 'live' | 'raw' | 'executed';

	let {
		sourceTab = $bindable<SourceTab>('executed'),
		liveObjText = '',
		rawLlmText = '',
		executedObjText = '',
		sectionLabel = 'Live OBJ Output'
	}: {
		sourceTab?: SourceTab;
		liveObjText?: string;
		rawLlmText?: string;
		executedObjText?: string;
		sectionLabel?: string;
	} = $props();

	const emptySourceHint =
		'# Send a prompt in Chat.\n# Live OBJ (model output), raw LLM text, and expanded v/f output will appear here.';

	const monacoValue = $derived(
		sourceTab === 'live'
			? liveObjText || emptySourceHint
			: sourceTab === 'raw'
				? rawLlmText || emptySourceHint
				: executedObjText || emptySourceHint
	);
</script>

<div class="planner-block planner-output-block">
	<div class="planner-section-head">
		<span class="live-obj-source-title">{sectionLabel}</span>
		<div class="live-obj-source-tabs" role="tablist" aria-label="Live OBJ source view">
			<button type="button" role="tab" aria-selected={sourceTab === 'executed'} class:active={sourceTab === 'executed'} onclick={() => (sourceTab = 'executed')}>
				Expanded (v/f)
			</button>
			<button type="button" role="tab" aria-selected={sourceTab === 'live'} class:active={sourceTab === 'live'} onclick={() => (sourceTab = 'live')}>
				Live OBJ
			</button>
			<button type="button" role="tab" aria-selected={sourceTab === 'raw'} class:active={sourceTab === 'raw'} onclick={() => (sourceTab = 'raw')}>
				Raw LLM
			</button>
		</div>
	</div>
	<p class="live-obj-source-hint">
		{sourceTab === 'executed'
			? 'Expanded mesh after Python executor (what the 3D view parses).'
			: sourceTab === 'live'
				? 'Direct Live OBJ from the model (code fences stripped).'
				: 'Unmodified LLM text for debugging format issues.'}
	</p>
	<div class="live-obj-source-editor planner-output-meta">
		<MonacoEditor language="plaintext" theme="vs" readOnly={true} viewOnly={true} value={monacoValue} />
	</div>
</div>

<style>
	.planner-output-block {
		margin: 0;
		height: 100%;
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 12px 14px 14px;
	}
	.live-obj-source-editor {
		flex: 1;
		min-height: 220px;
	}
	.planner-section-head {
		align-items: center;
	}
</style>
