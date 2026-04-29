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
		onApplySource,
		sectionLabel = 'Live OBJ Output'
	}: {
		sourceTab?: SourceTab;
		liveObjText?: string;
		rawLlmText?: string;
		executedObjText?: string;
		sceneEpoch?: number;
		applyBusy?: boolean;
		onApplySource?: (liveObjOrSceneText: string) => void | Promise<void>;
		sectionLabel?: string;
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

	const expandedSameAsLive = $derived(
		Boolean(
			liveObjText.trim() &&
				executedObjText.trim() &&
				liveObjText.trim() === executedObjText.trim()
		)
	);

	const hintLine = $derived(
		sourceTab === 'executed'
			? `Expanded mesh after Python executor (what the 3D view parses).${
					expandedSameAsLive ? ' Matches Live OBJ byte-for-byte when the executor echoes input unchanged.' : ''
				}`
			: sourceTab === 'live'
				? 'Direct Live OBJ from the model — first fenced code block is peeled off when present; preamble stays in Raw.'
				: sourceTab === 'raw'
					? 'Unmodified assistant message (often includes markdown fences and extra prose). Compare with Live OBJ.'
					: `#@ metadata, comments, and non-mesh directives (no v/vn/vt/vp/f/l lines). Derived from Expanded when present, else Live.`
	);

	const editable = $derived(sourceTab !== 'meta');

	const editorHint = $derived(
		editable
			? 'Edit below, then Apply to re-run the Python executor and refresh the 3D view.'
			: 'Metadata-only preview is read-only — switch to Expanded / Live / Raw to edit.'
	);

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
	<div class="planner-section-head">
		<span class="live-obj-source-title">{sectionLabel}</span>
		<div class="live-obj-source-tabs live-obj-source-tabs--four" role="tablist" aria-label="Live OBJ source view">
			<button type="button" role="tab" aria-selected={sourceTab === 'executed'} class:active={sourceTab === 'executed'} onclick={() => (sourceTab = 'executed')}>
				Expanded (v/f)
			</button>
			<button type="button" role="tab" aria-selected={sourceTab === 'live'} class:active={sourceTab === 'live'} onclick={() => (sourceTab = 'live')}>
				Live OBJ
			</button>
			<button type="button" role="tab" aria-selected={sourceTab === 'raw'} class:active={sourceTab === 'raw'} onclick={() => (sourceTab = 'raw')}>
				Raw LLM
			</button>
			<button type="button" role="tab" aria-selected={sourceTab === 'meta'} class:active={sourceTab === 'meta'} onclick={() => (sourceTab = 'meta')}>
				Metadata
			</button>
		</div>
	</div>
	<p class="live-obj-source-hint">{hintLine}</p>
	<p class="live-obj-edit-hint">{editorHint}</p>
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
	.live-obj-edit-hint {
		margin: 0;
		font-size: 11px;
		color: rgba(0, 0, 0, 0.48);
		line-height: 1.35;
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
	.live-obj-source-tabs--four {
		flex-wrap: wrap;
		gap: 6px;
	}
</style>
