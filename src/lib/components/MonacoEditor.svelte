<script lang="ts">
	import { onDestroy, onMount, tick, type Snippet } from 'svelte';
	import type * as Monaco from 'monaco-editor/esm/vs/editor/editor.api';
	import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
	import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';
	import CssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker';
	import HtmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker';
	import TsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';

	type Props = {
		value?: string;
		language?: string;
		readOnly?: boolean;
		theme?: string;
		/** When true, hides Reset/Apply (e.g. read-only file preview). */
		viewOnly?: boolean;
		/** Light chrome for side panel: grey bar + brand accent; pairs with theme="vs". */
		panelChrome?: boolean;
		/** Placed in the bottom toolbar immediately before the fullscreen control. */
		toolbarExtra?: Snippet;
		/** Apply toolbar button and Ctrl/Cmd+S when not read-only */
		onApply?: () => void;
		/** Reset toolbar button — parent typically reloads bindable value */
		onReset?: () => void;
	};

	let {
		value = $bindable(''),
		language = 'json',
		readOnly = false,
		theme = 'vs-dark',
		viewOnly = false,
		panelChrome = false,
		toolbarExtra,
		onApply,
		onReset
	}: Props = $props();

	/** Must be reactive: plain `let` does not re-run `$effect` after `onMount` assigns the async import. */
	let monaco = $state.raw<typeof Monaco | null>(null);
	/** Tracked so `$effect` that syncs `value` re-runs once the instance exists (plain `let` is not reactive). */
	let editor = $state.raw<Monaco.editor.IStandaloneCodeEditor | null>(null);
	let activeContainer: HTMLDivElement | null = null;
	let panelContainer: HTMLDivElement | null = null;
	let fullscreenContainer: HTMLDivElement | null = null;
	let fullscreenDialog: HTMLDialogElement | null = null;
	let resizeObserver: ResizeObserver | null = null;
	let isFullscreen = $state(false);

	onMount(async () => {
		self.MonacoEnvironment = {
			getWorker: (_workerId: string, label: string) => {
				switch (label) {
					case 'json':
						return new JsonWorker();
					case 'css':
					case 'scss':
					case 'less':
						return new CssWorker();
					case 'html':
					case 'handlebars':
					case 'razor':
						return new HtmlWorker();
					case 'typescript':
					case 'javascript':
						return new TsWorker();
					default:
						return new EditorWorker();
				}
			}
		};

		const monacoInstance = await import('monaco-editor/esm/vs/editor/editor.api');
		await Promise.all([
			import('monaco-editor/esm/vs/language/json/monaco.contribution'),
			import('monaco-editor/esm/vs/language/css/monaco.contribution'),
			import('monaco-editor/esm/vs/language/html/monaco.contribution'),
			import('monaco-editor/esm/vs/language/typescript/monaco.contribution'),
			import('monaco-editor/esm/vs/basic-languages/css/css.contribution'),
			import('monaco-editor/esm/vs/basic-languages/scss/scss.contribution'),
			import('monaco-editor/esm/vs/basic-languages/less/less.contribution')
		]);
		monaco = monacoInstance;
	});

	onDestroy(() => {
		resizeObserver?.disconnect();
		editor?.dispose();
		if (fullscreenDialog?.open) {
			fullscreenDialog.close();
		}
		document.body.classList.remove('monaco-fullscreen-open');
	});

	const desiredContainer = $derived(isFullscreen ? fullscreenContainer : panelContainer);

	$effect(() => {
		if (monaco && desiredContainer) {
			recreateEditor(desiredContainer);
		}
	});

	$effect(() => {
		if (editor && value !== editor.getValue()) {
			editor.setValue(value);
		}
	});

	$effect(() => {
		const ed = editor;
		if (!ed || !language) return;
		const model = ed.getModel();
		if (model) {
			monaco?.editor.setModelLanguage(model, language);
		}
	});

	$effect(() => {
		if (!editor) return;
		editor.updateOptions({ readOnly });
	});

	$effect(() => {
		document.body.classList.toggle('monaco-fullscreen-open', isFullscreen);
	});

	function recreateEditor(target: HTMLDivElement) {
		if (!monaco?.editor) {
			return;
		}
		if (activeContainer === target && editor) {
			editor.layout();
			return;
		}

		const existingModel = editor?.getModel() ?? null;
		const previousValue = editor?.getValue() ?? value;
		const viewState = editor?.saveViewState() ?? null;

		resizeObserver?.disconnect();
		editor?.dispose();

		const model = existingModel ?? monaco.editor.createModel(previousValue, language);

		editor = monaco.editor.create(target, {
			model,
			theme,
			readOnly,
			automaticLayout: true,
			minimap: { enabled: false },
			scrollBeyondLastLine: false,
			fontSize: 12,
			lineNumbers: 'on',
			renderLineHighlight: 'line',
			selectOnLineNumbers: true,
			wordWrap: 'on',
			tabSize: 2,
			formatOnPaste: true,
			smoothScrolling: true,
			cursorBlinking: 'smooth',
			cursorSmoothCaretAnimation: 'on',
			folding: true,
			foldingStrategy: 'auto',
			showFoldingControls: 'always',
			bracketPairColorization: { enabled: true }
		});

		if (viewState) {
			editor.restoreViewState(viewState);
		}

		// Match bindable `value` once the instance exists (covers effect ordering vs async monaco load).
		if (editor.getValue() !== value) {
			editor.setValue(value);
		}

		editor.onDidChangeModelContent(() => {
			value = editor?.getValue() ?? '';
		});

		resizeObserver = new ResizeObserver(() => {
			editor?.layout();
		});
		resizeObserver.observe(target);
		activeContainer = target;
		void tick().then(() => editor?.layout());
	}

	function toggleFullscreen() {
		isFullscreen = !isFullscreen;
		if (isFullscreen) {
			fullscreenDialog?.showModal();
		} else {
			fullscreenDialog?.close();
		}
	}

	function handleApply() {
		if (readOnly) return;
		onApply?.();
	}

	function handleReset() {
		onReset?.();
	}

	function handleKeyDown(e: KeyboardEvent) {
		if ((e.ctrlKey || e.metaKey) && e.key === 's') {
			if (!readOnly) {
				e.preventDefault();
				handleApply();
			}
			return;
		}

		if (e.key === 'Escape' && isFullscreen) {
			e.preventDefault();
			isFullscreen = false;
			fullscreenDialog?.close();
		}
	}

	function handleDialogClose() {
		if (isFullscreen) {
			isFullscreen = false;
		}
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions (Capture Ctrl/Cmd+S for apply; fullscreen Escape) -->
<div
	class="monaco-editor-wrapper"
	class:monaco-editor-wrapper--panel={panelChrome}
	onkeydown={handleKeyDown}
	role="region"
	tabindex="-1"
	aria-label="Monaco Editor"
>
	<div class="editor-container" bind:this={panelContainer}></div>

	<div class="editor-toolbar" class:editor-toolbar--panel={panelChrome}>
		<div class="toolbar-left">
			<span class="language-badge" class:language-badge--panel={panelChrome}>{language}</span>
		</div>
		<div class="toolbar-right">
			{#if toolbarExtra}<div class="monaco-toolbar-slot">{@render toolbarExtra()}</div>{/if}
			{#if !viewOnly}
				<button type="button" class="toolbar-btn" onclick={handleReset} title="Reset to current">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
						<path d="M3 3v5h5" />
					</svg>
					<span>Reset</span>
				</button>
				<button
					type="button"
					class="toolbar-btn toolbar-btn--accent"
					onclick={handleApply}
					title="Apply changes (Ctrl+S)"
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<path d="M5 12l5 5L20 7" />
					</svg>
					<span>Apply</span>
				</button>
			{/if}
			<button
				type="button"
				class="toolbar-btn icon-only toolbar-btn-fs"
				onclick={toggleFullscreen}
				title="Fullscreen"
				aria-label="Fullscreen"
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
				</svg>
			</button>
		</div>
	</div>
</div>

<dialog
	class="monaco-editor-dialog"
	bind:this={fullscreenDialog}
	onkeydown={handleKeyDown}
	onclose={handleDialogClose}
>
	<div
		class="monaco-editor-overlay"
		class:monaco-editor-overlay--panel={panelChrome}
		role="region"
		aria-label="Monaco Editor Fullscreen"
	>
		<button
			type="button"
			class="fullscreen-exit"
			class:fullscreen-exit--panel={panelChrome}
			onclick={toggleFullscreen}
			aria-label="Exit fullscreen"
			title="Exit fullscreen"
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<path d="M18 6L6 18M6 6l12 12" />
			</svg>
		</button>
		<div class="editor-container overlay-container" bind:this={fullscreenContainer}></div>
		<div class="editor-toolbar fullscreen-toolbar" class:editor-toolbar--panel={panelChrome}>
			<div class="toolbar-left">
				<span class="language-badge" class:language-badge--panel={panelChrome}>{language}</span>
			</div>
			<div class="toolbar-right">
				{#if toolbarExtra}<div class="monaco-toolbar-slot">{@render toolbarExtra()}</div>{/if}
				{#if !viewOnly}
					<button type="button" class="toolbar-btn" onclick={handleReset} title="Reset to current">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
							<path d="M3 3v5h5" />
						</svg>
						<span>Reset</span>
					</button>
					<button type="button" class="toolbar-btn toolbar-btn--accent" onclick={handleApply} title="Apply changes (Ctrl+S)">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M5 12l5 5L20 7" />
						</svg>
						<span>Apply</span>
					</button>
				{/if}
				<button
					type="button"
					class="toolbar-btn icon-only toolbar-btn-fs"
					onclick={toggleFullscreen}
					title="Exit fullscreen"
					aria-label="Exit fullscreen"
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
					</svg>
				</button>
			</div>
		</div>
	</div>
</dialog>

<style>
	.monaco-editor-wrapper {
		display: flex;
		flex-direction: column;
		border-radius: 12px;
		border: 1px solid rgba(0, 0, 0, 0.12);
		background: #0d1117;
		overflow: hidden;
		position: relative;
	}

	.monaco-editor-wrapper--panel {
		background: #f4f5f7;
		border: 1px solid rgba(0, 0, 0, 0.08);
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
	}

	.monaco-editor-dialog {
		padding: 0;
		border: none;
		max-width: none;
		max-height: none;
		width: 100vw;
		height: 100vh;
		margin: 0;
		background: transparent;
	}

	.monaco-editor-dialog::backdrop {
		background: rgba(0, 0, 0, 0.75);
	}

	.monaco-editor-overlay {
		height: 100%;
		display: flex;
		flex-direction: column;
		background: #0d1117;
	}

	.monaco-editor-overlay--panel {
		background: #f4f5f7;
	}

	.editor-container {
		flex: 1 1 auto;
		min-height: 200px;
		min-width: 0;
	}

	.overlay-container {
		flex: 1 1 auto;
		min-height: 0;
	}

	.editor-toolbar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 12px;
		background: rgba(255, 255, 255, 0.03);
		border-top: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
	}

	.editor-toolbar--panel {
		background: #ececef;
		border-top: 1px solid rgba(0, 0, 0, 0.08);
	}

	.fullscreen-toolbar {
		border-top: 1px solid rgba(255, 255, 255, 0.08);
	}

	.monaco-editor-overlay--panel .fullscreen-toolbar {
		border-top: 1px solid rgba(0, 0, 0, 0.08);
	}

	.toolbar-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.toolbar-right {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		justify-content: flex-end;
	}

	.monaco-toolbar-slot {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.language-badge {
		font-size: 11px;
		font-weight: 600;
		color: rgba(255, 255, 255, 0.5);
		background: rgba(255, 255, 255, 0.06);
		padding: 4px 8px;
		border-radius: 4px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.language-badge--panel {
		color: #444;
		background: rgba(255, 255, 255, 0.65);
		border: 1px solid rgba(0, 0, 0, 0.06);
	}

	.toolbar-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 12px;
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 6px;
		background: transparent;
		color: rgba(255, 255, 255, 0.7);
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
	}

	.editor-toolbar--panel .toolbar-btn:not(.toolbar-btn--accent):not(.toolbar-btn-fs) {
		border-color: rgba(0, 0, 0, 0.1);
		color: #333;
		background: rgba(255, 255, 255, 0.55);
	}

	.editor-toolbar--panel .toolbar-btn:not(.toolbar-btn--accent):not(.toolbar-btn-fs):hover {
		background: rgba(0, 0, 0, 0.06);
		border-color: rgba(0, 0, 0, 0.14);
	}

	.toolbar-btn:hover {
		background: rgba(255, 255, 255, 0.06);
		border-color: rgba(255, 255, 255, 0.2);
		color: #fff;
	}

	.toolbar-btn.icon-only {
		padding: 6px;
	}

	.toolbar-btn svg {
		width: 14px;
		height: 14px;
	}

	.toolbar-btn--accent {
		background: #0000eb;
		border-color: #0000eb;
		color: #fff;
	}

	.toolbar-btn--accent:hover {
		background: #0000c0;
		border-color: #0000c0;
	}

	.editor-toolbar--panel .toolbar-btn-fs {
		border-color: rgba(0, 0, 0, 0.1);
		color: #333;
		background: rgba(255, 255, 255, 0.55);
	}

	.editor-toolbar--panel .toolbar-btn-fs:hover {
		border-color: #0000eb;
		color: #0000eb;
		background: rgba(0, 0, 235, 0.06);
	}

	.fullscreen-exit {
		position: absolute;
		top: 16px;
		right: 16px;
		z-index: 2;
		width: 40px;
		height: 40px;
		border: none;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.1);
		color: white;
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		transition: all 0.2s;
	}

	.fullscreen-exit--panel {
		background: rgba(255, 255, 255, 0.9);
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.1);
	}

	.fullscreen-exit:hover {
		background: rgba(255, 255, 255, 0.2);
		transform: scale(1.05);
	}

	.fullscreen-exit--panel:hover {
		background: #fff;
		border-color: #0000eb;
		color: #0000eb;
	}

	.fullscreen-exit svg {
		width: 20px;
		height: 20px;
	}

	:global(body.monaco-fullscreen-open) {
		overflow: hidden;
	}
</style>
