<script lang="ts">
	let {
		liveObjText = '',
		onCaptureSceneScreenshot
	}: {
		liveObjText?: string;
		onCaptureSceneScreenshot?: () => string;
	} = $props();

	let prompt = $state('');
	let screenshotDataUrl = $state('');
	let generatedImageDataUrl = $state('');
	let busy = $state(false);
	let errorLine = $state<string | null>(null);
	let fullscreenImageDataUrl = $state('');
	let fullscreenDialog: HTMLDialogElement | null = $state(null);

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
					liveObjText
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
			disabled={busy}
		></textarea>
	</label>
	<div class="planner-render-actions">
		<button type="button" class="send-button" onclick={takeScreenshot} disabled={busy}>Take screenshot</button>
		<button type="button" class="send-button" onclick={generateImage} disabled={busy || !prompt.trim() || !screenshotDataUrl}>
			{busy ? 'Generating…' : 'Generate image'}
		</button>
	</div>

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
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" aria-hidden="true">
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
						<polyline points="7 10 12 15 17 10"/>
						<line x1="12" y1="15" x2="12" y2="3"/>
					</svg>
				</button>
				<button
					type="button"
					class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
					title="View screenshot fullscreen"
					aria-label="View screenshot fullscreen"
					onclick={() => openFullscreen(screenshotDataUrl)}
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" aria-hidden="true">
						<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
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
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" aria-hidden="true">
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
						<polyline points="7 10 12 15 17 10"/>
						<line x1="12" y1="15" x2="12" y2="3"/>
					</svg>
				</button>
				<button
					type="button"
					class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
					title="View generated image fullscreen"
					aria-label="View generated image fullscreen"
					onclick={() => openFullscreen(generatedImageDataUrl)}
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" aria-hidden="true">
						<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
					</svg>
				</button>
			</div>
		</div>
	{/if}

	{#if errorLine}
		<div class="planner-status" role="status">{errorLine}</div>
	{/if}
</div>

<dialog bind:this={fullscreenDialog} class="live-obj-render-dialog" onclose={closeFullscreen} onclick={(e) => {
	if (e.target === fullscreenDialog) closeFullscreen();
}}>
	{#if fullscreenImageDataUrl}
		<div class="live-obj-render-fullscreen-inner">
			<img src={fullscreenImageDataUrl} alt="Fullscreen render preview" />
			<button type="button" class="send-button live-obj-render-fullscreen-close" onclick={closeFullscreen}>Close</button>
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
