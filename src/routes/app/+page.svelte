<script lang="ts">
	import Canvas3D from '$lib/components/Canvas3D.svelte';
	import MonacoEditor from '$lib/components/MonacoEditor.svelte';
	import * as THREE from 'three';
	import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';

	const backgroundColor = '#e8ebf2';
	const showGrid = true;
	const showAxes = true;

	const emptySourceHint =
		'# Send a prompt below.\n# Live OBJ (model output), raw LLM text, and expanded v/f (executor) will show here.';

	type ChatMsg = { role: 'user' | 'assistant'; content: string };
	type SourceTab = 'live' | 'raw' | 'executed';

	let showPanel = $state(true);
	let input = $state('');
	let msgs = $state<ChatMsg[]>([]);
	let busy = $state(false);
	let statusLine = $state<string | null>(null);
	let renderObject = $state<THREE.Object3D | null>(null);

	let sourceTab = $state<SourceTab>('executed');
	let liveObjText = $state('');
	let rawLlmText = $state('');
	let executedObjText = $state('');

	const monacoValue = $derived.by(() => {
		const raw =
			sourceTab === 'live' ? liveObjText : sourceTab === 'raw' ? rawLlmText : executedObjText;
		return raw != null && raw.length > 0 ? raw : emptySourceHint;
	});

	function applyObjString(objText: string) {
		const loader = new OBJLoader();
		const group = loader.parse(objText);
		const mat = new THREE.MeshStandardMaterial({
			color: 0x7185d4,
			metalness: 0.12,
			roughness: 0.48,
			side: THREE.DoubleSide,
			flatShading: false
		});
		group.traverse((o: THREE.Object3D) => {
			if (o instanceof THREE.Mesh) o.material = mat;
		});
		renderObject = group;
	}

	async function send() {
		const text = input.trim();
		if (!text || busy) return;
		statusLine = null;
		busy = true;
		msgs = [...msgs, { role: 'user', content: text }];
		input = '';
		const history = msgs.slice(0, -1).map((m) => ({ role: m.role, content: m.content }));
		try {
			const res = await fetch('/api/live-obj', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ userMessage: text, history, model: 'gpt-5.5' })
			});
			const payload = (await res.json().catch(() => ({}))) as {
				message?: string;
				liveObj?: string;
				rawLlm?: string;
				executedObj?: string;
				executorWarning?: string;
			};
			if (!res.ok) {
				throw new Error(payload.message || res.statusText || 'Request failed');
			}
			liveObjText = payload.liveObj ?? '';
			rawLlmText = payload.rawLlm ?? '';
			executedObjText = payload.executedObj ?? '';
			if (payload.executedObj) {
				applyObjString(payload.executedObj);
			}
			if (payload.executorWarning) {
				statusLine = `Executor: ${payload.executorWarning}`;
			}
			msgs = [
				...msgs,
				{
					role: 'assistant',
					content: payload.executorWarning
						? 'Model returned a Live OBJ; mesh expansion had an issue (see status).'
						: 'Live OBJ received and mesh expanded. See the 3D view.'
				}
			];
		} catch (e) {
			const m = e instanceof Error ? e.message : String(e);
			statusLine = m;
			msgs = [...msgs, { role: 'assistant', content: `Error: ${m}` }];
		} finally {
			busy = false;
		}
	}
</script>

<div class="app-root">
	<div class="canvas-layer">
		<Canvas3D
			{backgroundColor}
			{renderObject}
			{showGrid}
			{showAxes}
			className="app-canvas"
		/>
	</div>

	{#if showPanel}
		<aside class="side-panel" aria-label="Live OBJ chat">
			<header class="panel-head">
				<h1 class="title">Live OBJ</h1>
				<button type="button" class="icon-btn" onclick={() => (showPanel = false)} title="Close panel"
					>✕</button
				>
			</header>
			<p class="sub">
				Prompts use the same system instructions as
				<code>src/routes/api/llm</code> (GPT-5.5), then
				<code>live_obj_executor_v02.py</code> fills <code>v</code> / <code>f</code> from metadata.
			</p>
			<div class="messages" role="log">
				{#if msgs.length === 0}
					<div class="welcome">
						Describe a 3D object. The model returns Live OBJ; Python expands the mesh for the canvas.
					</div>
				{:else}
					{#each msgs as m}
						<div class="bubble" class:user={m.role === 'user'}>
							{m.content}
						</div>
					{/each}
				{/if}
			</div>
			{#if statusLine}
				<div class="status" role="status">{statusLine}</div>
			{/if}

			<div class="source-block">
				<div class="source-head">
					<span class="source-label">Source</span>
					<div class="source-tabs" role="tablist" aria-label="Live OBJ source view">
						<button
							type="button"
							role="tab"
							aria-selected={sourceTab === 'executed'}
							class="source-tab"
							class:active={sourceTab === 'executed'}
							onclick={() => (sourceTab = 'executed')}>Expanded (v/f)</button
						>
						<button
							type="button"
							role="tab"
							aria-selected={sourceTab === 'live'}
							class="source-tab"
							class:active={sourceTab === 'live'}
							onclick={() => (sourceTab = 'live')}>Live OBJ</button
						>
						<button
							type="button"
							role="tab"
							aria-selected={sourceTab === 'raw'}
							class="source-tab"
							class:active={sourceTab === 'raw'}
							onclick={() => (sourceTab = 'raw')}>Raw LLM</button
						>
					</div>
				</div>
				<p class="source-hint">
					{sourceTab === 'executed'
						? 'Mesh after live_obj_executor (what the 3D view parses).'
						: sourceTab === 'live'
							? 'Live OBJ from the model (code fences stripped).'
							: 'Unmodified model output (use if debugging formatting).'}
				</p>
				<div class="source-monaco">
					<MonacoEditor
						language="plaintext"
						theme="vs"
						readOnly={true}
						viewOnly={true}
						value={monacoValue}
					/>
				</div>
			</div>

			<div class="composer">
				<textarea
					rows="2"
					placeholder="e.g. A simple box primitive on the ground, one meter wide…"
					bind:value={input}
					disabled={busy}
					onkeydown={(e) => {
						if (e.key === 'Enter' && !e.shiftKey) {
							e.preventDefault();
							void send();
						}
					}}
				></textarea>
				<button type="button" class="send" disabled={busy || !input.trim()} onclick={() => void send()}>
					{busy ? '…' : 'Send'}
				</button>
			</div>
		</aside>
	{:else}
		<button type="button" class="reopen" onclick={() => (showPanel = true)} title="Open panel">☰</button>
	{/if}
</div>

<style>
	.app-root {
		position: fixed;
		inset: 0;
		overflow: hidden;
	}
	.canvas-layer {
		position: absolute;
		inset: 0;
		z-index: 0;
	}
	:global(.app-canvas) {
		width: 100%;
		height: 100%;
	}
	:global(.app-canvas canvas) {
		border-radius: 0;
		box-shadow: none;
	}
	.side-panel {
		position: absolute;
		z-index: 10;
		top: 16px;
		left: 16px;
		width: min(520px, calc(100vw - 32px));
		max-height: calc(100vh - 32px);
		display: flex;
		flex-direction: column;
		background: rgba(255, 255, 255, 0.55);
		backdrop-filter: blur(20px);
		-webkit-backdrop-filter: blur(20px);
		border: 1px solid rgba(255, 255, 255, 0.5);
		border-radius: 16px;
		padding: 14px 16px 16px;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
	}
	.panel-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
	}
	.title {
		margin: 0;
		font-size: 1.1rem;
		font-weight: 600;
		color: #1a1a1a;
	}
	.sub {
		margin: 0 0 10px;
		font-size: 11px;
		line-height: 1.45;
		color: #555;
	}
	.sub code {
		font-size: 10px;
	}
	.icon-btn,
	.reopen {
		border: none;
		background: rgba(0, 0, 0, 0.06);
		border-radius: 8px;
		width: 32px;
		height: 32px;
		cursor: pointer;
		color: #333;
	}
	.reopen {
		position: absolute;
		z-index: 10;
		top: 16px;
		left: 16px;
		width: 44px;
		height: 44px;
		font-size: 18px;
	}
	.source-block {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
		gap: 6px;
		margin-bottom: 10px;
	}
	.source-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		flex-wrap: wrap;
	}
	.source-label {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #666;
	}
	.source-tabs {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.source-tab {
		border: 1px solid rgba(0, 0, 0, 0.1);
		background: rgba(255, 255, 255, 0.7);
		border-radius: 6px;
		padding: 4px 8px;
		font-size: 11px;
		cursor: pointer;
		color: #444;
	}
	.source-tab.active {
		border-color: #0000eb;
		background: rgba(0, 0, 235, 0.08);
		color: #0000a8;
		font-weight: 600;
	}
	.source-hint {
		margin: 0;
		font-size: 10px;
		line-height: 1.35;
		color: #777;
	}
	.source-monaco {
		flex: 1;
		min-height: 200px;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.source-monaco :global(.monaco-editor-wrapper) {
		flex: 1;
		min-height: 200px;
		display: flex;
		flex-direction: column;
		background: #fff;
		border: 1px solid rgba(0, 0, 0, 0.1);
	}
	.source-monaco :global(.editor-container) {
		flex: 1;
		min-height: 180px !important;
	}
	.source-monaco :global(.editor-toolbar) {
		background: rgba(0, 0, 0, 0.04);
		border-color: rgba(0, 0, 0, 0.08);
	}
	.source-monaco :global(.language-badge) {
		color: rgba(0, 0, 0, 0.5);
		background: rgba(0, 0, 0, 0.06);
	}
	.source-monaco :global(.toolbar-btn) {
		border-color: rgba(0, 0, 0, 0.12);
		color: rgba(0, 0, 0, 0.7);
	}
	.messages {
		flex: 0 1 auto;
		min-height: 80px;
		max-height: 28vh;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 10px;
		font-size: 13px;
	}
	.welcome {
		padding: 12px;
		background: rgba(255, 255, 255, 0.7);
		border-radius: 10px;
		color: #555;
		line-height: 1.45;
	}
	.bubble {
		align-self: flex-start;
		max-width: 100%;
		padding: 8px 12px;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.9);
		color: #222;
		line-height: 1.4;
		white-space: pre-wrap;
	}
	.bubble.user {
		align-self: flex-end;
		background: rgba(0, 0, 235, 0.1);
	}
	.status {
		font-size: 11px;
		color: #a35b00;
		margin-bottom: 8px;
	}
	.composer {
		display: flex;
		gap: 8px;
		align-items: flex-end;
	}
	.composer textarea {
		flex: 1;
		resize: none;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 10px;
		padding: 8px 10px;
		font: inherit;
		font-size: 13px;
	}
	.composer .send {
		flex-shrink: 0;
		padding: 8px 14px;
		border: none;
		border-radius: 10px;
		background: #0000eb;
		color: #fff;
		font-weight: 600;
		cursor: pointer;
	}
	.composer .send:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
