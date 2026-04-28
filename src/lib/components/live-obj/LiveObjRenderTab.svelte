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
		</div>
	{/if}

	{#if generatedImageDataUrl}
		<div class="planner-render-preview">
			<div class="planner-render-title">Generated image</div>
			<img src={generatedImageDataUrl} alt="Generated render result" />
		</div>
	{/if}

	{#if errorLine}
		<div class="planner-status" role="status">{errorLine}</div>
	{/if}
</div>

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
</style>
