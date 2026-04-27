<script lang="ts">
	import MonacoEditor from '$lib/components/MonacoEditor.svelte';

	export type SourceTab = 'live' | 'raw' | 'executed';

	let {
		sourceTab = $bindable<SourceTab>('executed'),
		liveObjText = '',
		rawLlmText = '',
		executedObjText = ''
	}: {
		sourceTab?: SourceTab;
		liveObjText?: string;
		rawLlmText?: string;
		executedObjText?: string;
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

<div class="source-block">
	<div class="source-head">
		<span class="source-label">Live OBJ Output</span>
		<div class="source-tabs" role="tablist" aria-label="Live OBJ source view">
			<button type="button" role="tab" aria-selected={sourceTab === 'executed'} class="source-tab" class:active={sourceTab === 'executed'} onclick={() => (sourceTab = 'executed')}>Expanded (v/f)</button>
			<button type="button" role="tab" aria-selected={sourceTab === 'live'} class="source-tab" class:active={sourceTab === 'live'} onclick={() => (sourceTab = 'live')}>Live OBJ</button>
			<button type="button" role="tab" aria-selected={sourceTab === 'raw'} class="source-tab" class:active={sourceTab === 'raw'} onclick={() => (sourceTab = 'raw')}>Raw LLM</button>
		</div>
	</div>
	<p class="source-hint">
		{sourceTab === 'executed'
			? 'Expanded mesh after Python executor (what the 3D view parses).'
			: sourceTab === 'live'
				? 'Direct Live OBJ from the model (code fences stripped).'
				: 'Unmodified LLM text for debugging format issues.'}
	</p>
	<div class="source-monaco">
		<MonacoEditor language="plaintext" theme="vs" readOnly={true} viewOnly={true} value={monacoValue} />
	</div>
</div>

<style>
	.source-block { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 6px; }
	.source-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
	.source-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: #666; }
	.source-tabs { display: flex; gap: 4px; flex-wrap: wrap; }
	.source-tab { border: 1px solid rgba(0, 0, 0, 0.1); background: rgba(255, 255, 255, 0.7); border-radius: 6px; padding: 4px 8px; font-size: 11px; cursor: pointer; color: #444; }
	.source-tab.active { border-color: #0000eb; background: rgba(0, 0, 235, 0.08); color: #0000a8; font-weight: 600; }
	.source-hint { margin: 0; font-size: 10px; line-height: 1.35; color: #777; }
	.source-monaco { flex: 1; min-height: 220px; display: flex; flex-direction: column; min-width: 0; }
	.source-monaco :global(.monaco-editor-wrapper) { flex: 1; min-height: 220px; display: flex; flex-direction: column; background: #fff; border: 1px solid rgba(0, 0, 0, 0.1); }
	.source-monaco :global(.editor-container) { flex: 1; min-height: 200px !important; }
</style>
