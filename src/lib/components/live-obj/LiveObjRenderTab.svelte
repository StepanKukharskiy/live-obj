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
	let isFullscreen = $state(false);
	let fullscreenImageDataUrl = $state('');

	function openFullscreen(imageDataUrl: string) {
		fullscreenImageDataUrl = imageDataUrl;
		isFullscreen = true;
	}

	function closeFullscreen() {
		isFullscreen = false;
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
				<button type="button" class="send-button" onclick={() => downloadImage(screenshotDataUrl, 'scene-screenshot')}>Download</button>
				<button type="button" class="send-button" onclick={() => openFullscreen(screenshotDataUrl)}>Fullscreen</button>
			</div>
		</div>
	{/if}

	{#if generatedImageDataUrl}
		<div class="planner-render-preview">
			<div class="planner-render-title">Generated image</div>
			<img src={generatedImageDataUrl} alt="Generated render result" />
			<div class="planner-render-image-actions">
				<button type="button" class="send-button" onclick={() => downloadImage(generatedImageDataUrl, 'rendered-image')}>Download</button>
				<button type="button" class="send-button" onclick={() => openFullscreen(generatedImageDataUrl)}>Fullscreen</button>
			</div>
		</div>
	{/if}

	{#if errorLine}
		<div class="planner-status" role="status">{errorLine}</div>
	{/if}
</div>

{#if isFullscreen && fullscreenImageDataUrl}
	<div class="live-obj-render-fullscreen" onclick={closeFullscreen}>
		<div class="live-obj-render-fullscreen-inner" onclick={(e) => e.stopPropagation()}>
			<img src={fullscreenImageDataUrl} alt="Fullscreen render preview" />
			<button type="button" class="send-button live-obj-render-fullscreen-close" onclick={closeFullscreen}>Close</button>
		</div>
	</div>
{/if}

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
	.live-obj-render-fullscreen {
		position: fixed;
		inset: 0;
		z-index: 1100;
		display: grid;
		place-items: center;
		background: rgba(0, 0, 0, 0.72);
		padding: 20px;
	}
	.live-obj-render-fullscreen-inner {
		max-width: min(1200px, 95vw);
		max-height: 95vh;
		display: flex;
		flex-direction: column;
		gap: 10px;
		align-items: stretch;
	}
	.live-obj-render-fullscreen-inner img {
		max-width: 100%;
		max-height: calc(95vh - 56px);
		object-fit: contain;
		border-radius: 10px;
		background: #111;
	}
	.live-obj-render-fullscreen-close {
		align-self: flex-end;
	}
</style>
