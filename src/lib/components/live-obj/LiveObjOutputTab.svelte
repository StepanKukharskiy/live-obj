<script lang="ts">
	import MonacoEditor from '$lib/components/MonacoEditor.svelte';
	import { stripLiveObjMeshLines } from '$lib/liveObj/stripLiveObjMeshLines';
	import { stripCodeFences } from '$lib/liveObj/stripCodeFences';

	export type SourceTab = 'live' | 'raw' | 'executed' | 'meta';

	let {
		sourceTab = $bindable<SourceTab>('executed'),
		liveObjText = '',
		rawLlmText = '',
		executedObjText = '',
		sceneEpoch = 0,
		applyBusy = false,
		onApplySource
	}: {
		sourceTab?: SourceTab;
		liveObjText?: string;
		rawLlmText?: string;
		executedObjText?: string;
		sceneEpoch?: number;
		applyBusy?: boolean;
		onApplySource?: (liveObjOrSceneText: string) => void | Promise<void>;
	} = $props();

	const emptySourceHint =
		'# Send a prompt in Chat.\n# Live OBJ (model output), raw LLM text, expanded v/f output, or metadata-only view will appear here.';

	const meshBasis = $derived(executedObjText || liveObjText);
	let showMeshLines = $state(true);

	let editorValue = $state('');

	function seedEditor(): string {
		const metaBody = meshBasis.trim()
			? stripLiveObjMeshLines(meshBasis)
			: '';
		if (sourceTab === 'live') {
			const liveBody = liveObjText.trim() ? liveObjText : emptySourceHint;
			return showMeshLines ? liveBody : stripLiveObjMeshLines(liveBody) || emptySourceHint;
		}
		if (sourceTab === 'raw') {
			const rawBody = rawLlmText.trim() ? rawLlmText : emptySourceHint;
			return showMeshLines ? rawBody : stripLiveObjMeshLines(rawBody) || emptySourceHint;
		}
		if (sourceTab === 'meta') return metaBody.trim() ? metaBody : emptySourceHint;
		const expanded = executedObjText.trim() ? executedObjText : emptySourceHint;
		return showMeshLines ? expanded : stripLiveObjMeshLines(expanded) || emptySourceHint;
	}

	/** Pre-DOM so `bind:value` sees seeded text on Monaco’s first bind (avoids empty model + missed sync). */
	$effect.pre(() => {
		void sceneEpoch;
		void sourceTab;
		void liveObjText;
		void rawLlmText;
		void executedObjText;
		void showMeshLines;
		editorValue = seedEditor();
	});

	const editable = $derived(sourceTab !== 'meta');

	function revertEditor() {
		editorValue = seedEditor();
	}

	function buildPayloadForExecute(): string | null {
		let t = editorValue;
		if (!t.trim()) return null;
		if (t.trim() === emptySourceHint.trim()) return null;

		if (sourceTab === 'meta') return null;

		if (sourceTab === 'raw' || sourceTab === 'live') {
			return stripCodeFences(t).trim() || null;
		}
		return t.trim();
	}

	async function handleApply() {
		const payload = buildPayloadForExecute();
		if (!payload || !onApplySource) return;
		await Promise.resolve(onApplySource(payload));
	}

	const applyDisabled = $derived.by(() => {
		if (!editable || applyBusy) return true;
		return !buildPayloadForExecute();
	});
</script>

<div class="planner-block planner-output-block">
	<div class="live-obj-source-editor planner-output-meta">
		{#key `${sceneEpoch}-${sourceTab}`}
			<MonacoEditor
				language="plaintext"
				theme="vs"
				readOnly={!editable}
				viewOnly={true}
				panelChrome={true}
				bind:value={editorValue}
				onApply={() => void handleApply()}
			>
				{#snippet toolbarExtra()}
					<button
						type="button"
						class="planner-monaco-action-btn"
						disabled={sourceTab === 'meta'}
						title={showMeshLines ? 'Hide v/f mesh lines in editor' : 'Show v/f mesh lines in editor'}
						onclick={() => {
							showMeshLines = !showMeshLines;
						}}
					>
						{showMeshLines ? 'Hide v/f' : 'Show v/f'}
					</button>
					<button
						type="button"
						class="planner-monaco-action-btn"
						disabled={!editable || applyBusy}
						title="Revert edits to displayed source"
						onclick={() => revertEditor()}
					>
						Revert
					</button>
					<button
						type="button"
						class="planner-monaco-action-btn planner-monaco-action-btn--accent"
						disabled={applyDisabled}
						title="Re-run executor and refresh 3D (Ctrl/Cmd+S)"
						onclick={() => void handleApply()}
					>
						{applyBusy ? 'Applying…' : 'Apply'}
					</button>
				{/snippet}
			</MonacoEditor>
		{/key}
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
</style>
