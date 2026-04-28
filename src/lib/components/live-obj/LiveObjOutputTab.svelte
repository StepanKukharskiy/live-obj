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
	/* Block column: tab body scrolls; min-height only on the editor strip (not a flex-filled cage). */
	.planner-output-block {
		margin: 0;
		padding: 12px 14px 14px;
		box-sizing: border-box;
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
	}
	.planner-output-block .live-obj-source-editor {
		flex: none;
		width: 100%;
		min-width: 0;
		display: flex;
		flex-direction: column;
		min-height: clamp(120px, 20vh, 320px);
	}
	/* planner-panel.css uses flex:1 + tall editor mins — override so toolbar stays in-flow below the editor */
	.planner-output-block .live-obj-source-editor :global(.monaco-editor-wrapper) {
		flex: 1 1 auto;
		min-height: 0;
	}
	.planner-output-block .live-obj-source-editor :global(.editor-container) {
		min-height: clamp(72px, 14vh, 260px) !important;
	}
	.planner-section-head {
		align-items: center;
	}
</style>
