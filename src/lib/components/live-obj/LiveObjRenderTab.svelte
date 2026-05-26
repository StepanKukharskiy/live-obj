<script lang="ts">
	let {
		liveObjText = '',
		providerSettings = {
			provider: 'openai',
			apiKey: '',
			apiUrl: '',
			imageUrl: '',
			textModel: '',
			imageModel: '',
			rememberMe: false
		},
		onCaptureSceneScreenshot,
		prompt = $bindable(''),
		screenshotDataUrl = $bindable(''),
		generatedImageDataUrl = $bindable(''),
		busy = $bindable(false),
		errorLine = $bindable<string | null>(null)
	}: {
		liveObjText?: string;
		providerSettings?: {
			provider: string;
			apiKey: string;
			apiUrl: string;
			imageUrl: string;
			textModel: string;
			imageModel: string;
			rememberMe: boolean;
		};
		onCaptureSceneScreenshot?: () => string;
		prompt?: string;
		screenshotDataUrl?: string;
		generatedImageDataUrl?: string;
		busy?: boolean;
		errorLine?: string | null;
	} = $props();

	let fullscreenImageDataUrl = $state('');
	let fullscreenDialog: HTMLDialogElement | null = $state(null);
	let promptBusy = $state(false);
	let generatedDirectionJson = $state('');

	function openFullscreen(imageDataUrl: string) {
		fullscreenImageDataUrl = imageDataUrl;
		if (!fullscreenDialog) return;
		if (typeof fullscreenDialog.showModal === 'function') {
			fullscreenDialog.showModal();
		}
	}

	function closeFullscreen() {
		if (fullscreenDialog?.open) fullscreenDialog.close();
		fullscreenImageDataUrl = '';
	}

	function downloadImage(imageDataUrl: string, filenamePrefix: string) {
		if (!imageDataUrl) return;
		const link = document.createElement('a');
		link.href = imageDataUrl;
		link.download = `${filenamePrefix}-${Date.now()}.png`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	function takeScreenshot() {
		errorLine = null;
		const dataUrl = onCaptureSceneScreenshot?.() ?? '';
		if (!dataUrl) {
			errorLine = 'Unable to capture screenshot from the 3D scene.';
			return;
		}
		screenshotDataUrl = dataUrl;
	}

	async function generatePrompt() {
		if (promptBusy || busy) return;
		errorLine = null;
		promptBusy = true;
		try {
			const response = await fetch('/api/render-prompt', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					liveObjText,
					currentPrompt: prompt,
					apiKey: providerSettings.apiKey?.trim() || undefined,
					apiUrl: providerSettings.apiUrl?.trim() || undefined,
					model: providerSettings.textModel
				})
			});
			const payload = (await response.json().catch(() => ({}))) as {
				message?: string;
				prompt?: string;
				direction?: unknown;
			};
			if (!response.ok || !payload.prompt) {
				throw new Error(payload.message || 'Prompt generation failed');
			}
			prompt = payload.prompt;
			generatedDirectionJson = payload.direction ? JSON.stringify(payload.direction, null, 2) : '';
		} catch (e) {
			errorLine = e instanceof Error ? e.message : String(e);
		} finally {
			promptBusy = false;
		}
	}

	async function generateImage() {
		if (busy) return;
		errorLine = null;
		generatedImageDataUrl = '';
		if (!prompt.trim()) {
			errorLine = 'Please enter a render prompt.';
			return;
		}
		if (!screenshotDataUrl) {
			errorLine = 'Take a screenshot first.';
			return;
		}
		busy = true;
		try {
			const response = await fetch('/api/render-image', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					prompt,
					screenshotDataUrl,
					liveObjText,
					provider: providerSettings.provider,
					apiKey: providerSettings.apiKey?.trim() || undefined,
					apiUrl: providerSettings.apiUrl?.trim() || undefined,
					imageUrl: providerSettings.imageUrl?.trim() || undefined,
					imageModel: providerSettings.imageModel
				})
			});
			const payload = (await response.json().catch(() => ({}))) as {
				message?: string;
				imageDataUrl?: string;
			};
			if (!response.ok || !payload.imageDataUrl) {
				throw new Error(payload.message || 'Image generation failed');
			}
			generatedImageDataUrl = payload.imageDataUrl;
		} catch (e) {
			errorLine = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="live-obj-render-tab">
	<label class="planner-context-field planner-render-field">
		<span class="planner-label-inline">Prompt</span>
		<textarea
			class="planner-text-input planner-render-prompt"
			rows="4"
			placeholder="Describe the final rendered image style and mood..."
			bind:value={prompt}
			disabled={busy || promptBusy}
		></textarea>
	</label>
	<div class="planner-render-actions">
		<button
			type="button"
			class="send-button planner-render-secondary-button"
			onclick={generatePrompt}
			disabled={busy || promptBusy || !liveObjText.trim()}
		>
			{promptBusy ? 'Directing…' : 'Generate prompt'}
		</button>
		<button
			type="button"
			class="send-button planner-render-secondary-button"
			onclick={takeScreenshot}
			disabled={busy || promptBusy}>Take screenshot</button
		>
		<button
			type="button"
			class="send-button"
			onclick={generateImage}
			disabled={busy || promptBusy || !prompt.trim() || !screenshotDataUrl}
		>
			{busy ? 'Generating…' : 'Generate image'}
		</button>
	</div>

	{#if generatedDirectionJson}
		<details class="planner-render-direction">
			<summary>Visual direction JSON</summary>
			<pre>{generatedDirectionJson}</pre>
		</details>
	{/if}

	{#if screenshotDataUrl}
		<div class="planner-render-preview">
			<div class="planner-render-title">Scene screenshot</div>
			<img src={screenshotDataUrl} alt="Scene capture preview" />
			<div class="planner-render-image-actions">
				<button
					type="button"
					class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
					title="Download screenshot"
					aria-label="Download screenshot"
					onclick={() => downloadImage(screenshotDataUrl, 'scene-screenshot')}
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						width="15"
						height="15"
						aria-hidden="true"
					>
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
						<polyline points="7 10 12 15 17 10" />
						<line x1="12" y1="15" x2="12" y2="3" />
					</svg>
				</button>
				<button
					type="button"
					class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
					title="View screenshot fullscreen"
					aria-label="View screenshot fullscreen"
					onclick={() => openFullscreen(screenshotDataUrl)}
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						width="15"
						height="15"
						aria-hidden="true"
					>
						<path
							d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"
						/>
					</svg>
				</button>
			</div>
		</div>
	{/if}

	{#if generatedImageDataUrl}
		<div class="planner-render-preview">
			<div class="planner-render-title">Generated image</div>
			<img src={generatedImageDataUrl} alt="Generated render result" />
			<div class="planner-render-image-actions">
				<button
					type="button"
					class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
					title="Download generated image"
					aria-label="Download generated image"
					onclick={() => downloadImage(generatedImageDataUrl, 'rendered-image')}
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						width="15"
						height="15"
						aria-hidden="true"
					>
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
						<polyline points="7 10 12 15 17 10" />
						<line x1="12" y1="15" x2="12" y2="3" />
					</svg>
				</button>
				<button
					type="button"
					class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
					title="View generated image fullscreen"
					aria-label="View generated image fullscreen"
					onclick={() => openFullscreen(generatedImageDataUrl)}
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						width="15"
						height="15"
						aria-hidden="true"
					>
						<path
							d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"
						/>
					</svg>
				</button>
			</div>
		</div>
	{/if}

	{#if errorLine}
		<div class="planner-status" role="status">{errorLine}</div>
	{/if}
</div>

<dialog
	bind:this={fullscreenDialog}
	class="live-obj-render-dialog"
	onclose={closeFullscreen}
	onclick={(e) => {
		if (e.target === fullscreenDialog) closeFullscreen();
	}}
>
	{#if fullscreenImageDataUrl}
		<div class="live-obj-render-fullscreen-inner">
			<img src={fullscreenImageDataUrl} alt="Fullscreen render preview" />
			<button
				type="button"
				class="send-button live-obj-render-fullscreen-close"
				onclick={closeFullscreen}>Close</button
			>
		</div>
	{/if}
</dialog>

<style>
	.live-obj-render-tab {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.planner-render-field {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.planner-render-prompt {
		width: 100%;
		resize: vertical;
		min-height: 88px;
	}
	.planner-render-actions {
		display: flex;
		gap: 10px;
		flex-wrap: wrap;
	}
	.planner-render-secondary-button {
		border: 1px solid rgba(0, 0, 235, 0.48);
		background: transparent;
		color: var(--spell-blue);
		box-shadow: none;
	}
	.planner-render-secondary-button:hover:not(:disabled) {
		border-color: var(--spell-blue);
		background: rgba(0, 0, 235, 0.05);
		color: var(--spell-blue-hover);
		box-shadow: none;
	}
	.planner-render-secondary-button:disabled {
		border-color: rgba(0, 0, 0, 0.14);
		background: transparent;
		color: rgba(0, 0, 0, 0.3);
		box-shadow: none;
	}
	.planner-render-direction {
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.45);
		padding: 9px 10px;
	}
	.planner-render-direction summary {
		cursor: pointer;
		font-size: 12px;
		font-weight: 600;
		color: #4a4a4a;
	}
	.planner-render-direction pre {
		margin: 10px 0 0;
		max-height: 260px;
		overflow: auto;
		white-space: pre-wrap;
		word-break: break-word;
		font-size: 11px;
		line-height: 1.45;
		color: #242424;
	}
	.planner-render-preview {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.planner-render-title {
		font-size: 12px;
		font-weight: 600;
		color: #4a4a4a;
	}
	.planner-render-preview img {
		width: 100%;
		border-radius: 10px;
		border: 1px solid rgba(0, 0, 0, 0.1);
		background: rgba(255, 255, 255, 0.4);
	}
	.planner-render-image-actions {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.planner-monaco-action-btn--icon-only {
		width: 32px;
		height: 32px;
		padding: 0;
		border-radius: 8px;
	}
	.live-obj-render-dialog {
		border: none;
		padding: 0;
		margin: auto;
		background: transparent;
		max-width: 95vw;
		max-height: 95vh;
	}
	.live-obj-render-dialog::backdrop {
		background: rgba(0, 0, 0, 0.72);
	}
	.live-obj-render-fullscreen-inner {
		max-width: min(1400px, 95vw);
		max-height: 95vh;
		display: flex;
		flex-direction: column;
		gap: 10px;
		align-items: stretch;
	}
	.live-obj-render-fullscreen-inner img {
		max-width: 100%;
		max-height: calc(95vh - 62px);
		object-fit: contain;
		border-radius: 10px;
		background: #111;
	}
	.live-obj-render-fullscreen-close {
		align-self: flex-end;
	}
</style>
