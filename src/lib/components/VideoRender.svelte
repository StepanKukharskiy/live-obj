<script>
	import { chatHistory, currentChain, generatedVideoUrl, videoPromptText, isRenderingVideo, videoErrorMessage, videoProgress } from '$lib/stores/ui.js';
	import { get } from 'svelte/store';
	import { browser } from '$app/environment';

	export let addLog = (message, type = 'info') => {};
	export let generatedImageUrl = null; // Input image from ImageRender component

	let videoPromptTextLocal = '';
	let isFullscreen = false;
	let fullscreenVideo = '';
	let isGeneratingPrompt = false;
	let promptGenError = null;

	const DEFAULT_VIDEO_MODEL = 'ByteDance/Seedance-1.0-lite';

	// Initialize stores only in browser
	$: if (browser && !$videoPromptText) {
		// Stores are ready
	}

	// Generate video prompt from image generation prompt when tab becomes active
	export function generateVideoPromptFromHistory() {
		const history = get(chatHistory);
		const firstUserMessage = history.find(m => m.role === 'user');
		if (firstUserMessage) {
			// Create a video-specific prompt based on the user's initial request
			const baseRequest = firstUserMessage.content;
			const enhancedPrompt = `Create a dynamic video animation of this 3D scene. The scene shows: ${baseRequest}. Smooth camera movement, subtle object animation, professional cinematic lighting, high quality render, 5 seconds duration. Maintain the same composition and object placement as the reference image.`;
			videoPromptTextLocal = enhancedPrompt;
			videoPromptText.set(enhancedPrompt);
		} else {
			const defaultPrompt = `Create a dynamic video animation of this 3D scene. Smooth camera movement, subtle object animation, professional cinematic lighting, high quality render, 5 seconds duration. Maintain the same composition and object placement as the reference image.`;
			videoPromptTextLocal = defaultPrompt;
			videoPromptText.set(defaultPrompt);
		}
	}

	async function generateVideoPrompt() {
		isGeneratingPrompt = true;
		promptGenError = null;
		try {
			const chain = get(currentChain);
			const history = get(chatHistory);
			const userRequest = history.find(m => m.role === 'user')?.content || '';

			addLog('Generating video prompt from scene graph...');
			const response = await fetch('/api/generate-prompt', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ sceneGraph: chain, userRequest })
			});

			if (!response.ok) {
				const errText = await response.text();
				throw new Error(`API error: ${response.status} - ${errText}`);
			}

			const { videoPrompt } = await response.json();
			if (videoPrompt) {
				videoPromptTextLocal = videoPrompt;
				videoPromptText.set(videoPrompt);
				addLog('Video prompt generated', 'success');
			}
		} catch (err) {
			promptGenError = err.message;
			addLog('Prompt generation failed: ' + err.message, 'error');
		} finally {
			isGeneratingPrompt = false;
		}
	}

	// Generate video using Together AI API
	async function generateVideo() {
		if (!videoPromptTextLocal.trim()) {
			videoErrorMessage.set('Please enter a prompt for the video');
			return;
		}

		if (!generatedImageUrl) {
			videoErrorMessage.set('Please generate an image first to use as input for the video');
			return;
		}

		isRenderingVideo.set(true);
		videoErrorMessage.set(null);
		generatedVideoUrl.set(null);
		videoProgress.set('Starting video generation...');

		try {
			addLog('Starting video generation from image');
			
			// Use the generated image URL as input
			const imageUrl = generatedImageUrl;
			
			addLog('Sending to AI service for video generation');

			// Use the video generation API endpoint
			const response = await fetch('/api/videos', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({
					model: DEFAULT_VIDEO_MODEL,
					prompt: videoPromptTextLocal,
					image: imageUrl, // Use the image URL directly
					width: 1440,
					height: 1440,
					seconds: 5,
					output_format: 'MP4'
				})
			});

			if (!response.ok) {
				const errorText = await response.text();
				throw new Error(`API error: ${response.status} - ${errorText}`);
			}

			const data = await response.json();

			// Together AI video API returns video URL in the response
			if (data.outputs && data.outputs.video_url) {
				generatedVideoUrl.set(data.outputs.video_url);
				addLog('Video generated successfully!');
				videoProgress.set('Video generation completed!');
			} else {
				throw new Error('No video URL in API response');
			}
		} catch (error) {
			console.error('Video generation failed:', error);
			videoErrorMessage.set(error.message);
			addLog(`Video generation failed: ${error.message}`);
			videoProgress.set('');
		} finally {
			isRenderingVideo.set(false);
		}
	}

	async function downloadVideo() {
		if (!$generatedVideoUrl) return;

		try {
			addLog('Downloading video');
			
			// Use proxy endpoint to avoid CORS issues if needed
			let downloadUrl;
			if ($generatedVideoUrl.startsWith('http')) {
				// If it's already a full URL, use proxy
				downloadUrl = `/api/video-proxy?url=${encodeURIComponent($generatedVideoUrl)}`;
			} else {
				// If it's a relative path or data URL, use directly
				downloadUrl = $generatedVideoUrl;
			}

			const response = await fetch(downloadUrl);
			if (!response.ok) {
				throw new Error(`Download failed: ${response.status}`);
			}
			
			const blob = await response.blob();

			// Try to use File System Access API for folder picker
			if ('showSaveFilePicker' in window) {
				const suggestedName = `video-${Date.now()}.mp4`;
				// @ts-ignore - File System Access API may not be typed
				const fileHandle = await window.showSaveFilePicker({
					suggestedName: suggestedName,
					types: [
						{
							description: 'MP4 Video',
							accept: { 'video/mp4': ['.mp4'] }
						}
					]
				});
				const writableStream = await fileHandle.createWritable();
				await writableStream.write(blob);
				await writableStream.close();
				addLog('Video saved to selected folder');
			} else {
				// Fallback for browsers that don't support File System Access API
				const link = document.createElement('a');
				link.href = URL.createObjectURL(blob);
				link.download = `video-${Date.now()}.mp4`;
				document.body.appendChild(link);
				link.click();
				document.body.removeChild(link);
				URL.revokeObjectURL(link.href);
				addLog('Video downloaded');
			}
		} catch (error) {
			if (error.name === 'AbortError') {
				// User cancelled the save dialog
				return;
			}
			console.error('Video download failed:', error);
			addLog('Video download failed: ' + error.message);
		}
	}

	// Update video prompt when image changes
	$: if (browser && generatedImageUrl && !videoPromptTextLocal) {
		generateVideoPromptFromHistory();
	}
</script>

{#if browser}
<div class="video-render-tab">
	<details class="obj-block" open>
		<summary class="obj-header">
			<span class="obj-name">Video Generation</span>
			<span class="obj-badge">AI Animation</span>
		</summary>
		
		{#if !generatedImageUrl}
			<div class="info-message">
				<svg class="info-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<circle cx="12" cy="12" r="10"/>
					<line x1="12" y1="16" x2="12" y2="12"/>
					<line x1="12" y1="8" x2="12.01" y2="8"/>
				</svg>
				Generate an image first to use as input for video creation
			</div>
		{/if}

		<div class="vars-grid">
			<div class="var-row prompt-header-row">
				<label class="var-key" for="video-prompt">Video Prompt</label>
				<button
					class="gen-prompt-btn"
					on:click={generateVideoPrompt}
					disabled={isGeneratingPrompt || $isRenderingVideo}
					title="Generate video prompt from scene graph using AI"
				>
					{#if isGeneratingPrompt}
						<span class="spinner-sm"></span>
						Generating...
					{:else}
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13">
							<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
						</svg>
						AI Prompt
					{/if}
				</button>
			</div>
			{#if promptGenError}
				<div class="prompt-gen-error">{promptGenError}</div>
			{/if}
			<div class="var-row">
				<textarea
					id="video-prompt"
					class="pi pi-str"
					bind:value={$videoPromptText}
					placeholder="Describe the video animation you want to generate..."
					rows="3"
					disabled={$isRenderingVideo}
				></textarea>
			</div>
		</div>

		<details class="section-block" open>
			<summary class="section-header">Actions</summary>
			<div class="actions-list">
				<div class="button-group">
					<button
						class="render-btn"
						on:click={generateVideo}
						disabled={$isRenderingVideo || !$videoPromptText.trim() || !generatedImageUrl}
					>
						{#if $isRenderingVideo}
							<span class="spinner"></span>
							Generating Video...
						{:else}
							<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<polygon points="23 7 16 12 23 17 23 7"/>
								<rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
							</svg>
							Generate Video
						{/if}
					</button>
				</div>
			</div>
		</details>

		{#if $videoProgress}
			<div class="progress-message">
				<svg class="progress-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<circle cx="12" cy="12" r="10"/>
					<polyline points="12 6 12 12 16 14"/>
				</svg>
				{$videoProgress}
			</div>
		{/if}

		{#if $generatedVideoUrl}
			<details class="section-block" open>
				<summary class="section-header">Generated Video <span class="count-badge">Result</span></summary>
				<div class="vars-grid">
					<div class="video-container">
						<video controls autoplay muted loop class="generated-video">
							<source src={$generatedVideoUrl} type="video/mp4" />
							Your browser does not support the video tag.
						</video>
					</div>
					<div class="button-group">
						<button class="download-btn" on:click={downloadVideo}>
							<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
								<polyline points="7 10 12 15 17 10"/>
								<line x1="12" y1="15" x2="12" y2="3"/>
							</svg>
							Download Video
						</button>
					</div>
				</div>
			</details>
		{/if}
	</details>

	{#if $videoErrorMessage}
		<div class="error-message">
			<svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<circle cx="12" cy="12" r="10"/>
				<line x1="12" y1="8" x2="12" y2="12"/>
				<line x1="12" y1="16" x2="12.01" y2="16"/>
			</svg>
			{$videoErrorMessage}
		</div>
	{/if}
</div>
{/if}

<style>
	.video-render-tab {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 4px;
	}

	/* Main object block styling - matching params tab */
	.obj-block {
		background: rgba(255,255,255,0.6);
		border: 1px solid rgba(0,0,0,0.08);
		border-radius: 10px;
		margin-bottom: 10px;
		overflow: hidden;
	}

	.obj-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: 13px;
		font-weight: 600;
		color: #1a1a1a;
	}

	.obj-header::-webkit-details-marker { display: none; }
	.obj-name { flex: 1; }
	.obj-badge {
		background: rgba(0,0,235,0.08);
		color: #0000eb;
		font-size: 10px;
		font-weight: 500;
		padding: 2px 7px;
		border-radius: 10px;
	}

	/* Info message */
	.info-message {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px;
		background: rgba(0, 0, 235, 0.08);
		border: 1px solid rgba(0, 0, 235, 0.15);
		border-radius: 10px;
		color: #0000eb;
		font-size: 12px;
		margin: 10px;
	}

	.info-icon {
		width: 16px;
		height: 16px;
		flex-shrink: 0;
	}

	/* Progress message */
	.progress-message {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px;
		background: rgba(0, 0, 0, 0.06);
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 10px;
		color: #555;
		font-size: 12px;
		margin: 0 10px;
	}

	.progress-icon {
		width: 16px;
		height: 16px;
		flex-shrink: 0;
		animation: pulse 2s infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}

	/* Nested section blocks - matching params tab */
	.section-block {
		margin: 0 10px 8px;
		border: 1px solid rgba(0,0,0,0.06);
		border-radius: 7px;
		background: rgba(255,255,255,0.5);
		overflow: hidden;
	}

	.section-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 7px 10px;
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: 11px;
		font-weight: 600;
		color: #555;
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}

	.section-header::-webkit-details-marker { display: none; }
	.count-badge {
		background: rgba(0,0,0,0.06);
		color: #888;
		font-size: 10px;
		font-weight: 400;
		padding: 1px 5px;
		border-radius: 8px;
		text-transform: none;
		letter-spacing: 0;
	}

	/* Content grids - matching params tab */
	.vars-grid {
		padding: 2px 10px 8px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.var-row {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		font-size: 12px;
	}

	.var-key {
		color: #555;
		font-weight: 500;
		min-width: 110px;
		flex-shrink: 0;
		margin-top: 6px;
	}

	/* Input styling - matching params tab */
	.pi {
		background: rgba(255,255,255,0.8);
		border: 1px solid rgba(0,0,0,0.1);
		border-radius: 4px;
		padding: 6px 8px;
		font-size: 12px;
		color: #1a1a1a;
		font-family: inherit;
		flex: 1;
		resize: vertical;
		min-height: 60px;
		line-height: 1.4;
	}

	.pi:focus {
		outline: none;
		border-color: #0000eb;
		box-shadow: 0 0 0 2px rgba(0,0,235,0.1);
	}

	.pi:disabled {
		opacity: 0.6;
	}

	/* Actions list - matching params tab */
	.actions-list {
		padding: 2px 10px 8px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.button-group {
		display: flex;
		gap: 8px;
	}

	.prompt-header-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.gen-prompt-btn {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		background: rgba(0, 0, 235, 0.07);
		color: #0000eb;
		border: 1px solid rgba(0, 0, 235, 0.2);
		border-radius: 6px;
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.15s;
		white-space: nowrap;
	}

	.gen-prompt-btn:hover:not(:disabled) {
		background: rgba(0, 0, 235, 0.14);
		border-color: rgba(0, 0, 235, 0.4);
	}

	.gen-prompt-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.spinner-sm {
		display: inline-block;
		width: 10px;
		height: 10px;
		border: 2px solid rgba(0, 0, 235, 0.3);
		border-top-color: #0000eb;
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	.prompt-gen-error {
		font-size: 11px;
		color: #c00;
		padding: 4px 0;
	}

	.render-btn {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 12px 20px;
		background: #0000eb;
		color: white;
		border: none;
		border-radius: 10px;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
		transition: all 0.2s;
	}

	.render-btn:hover:not(:disabled) {
		background: #0000c9;
		transform: translateY(-1px);
		box-shadow: 0 4px 12px rgba(0, 0, 235, 0.3);
	}

	.render-btn:disabled {
		background: #ccc;
		cursor: not-allowed;
	}

	.btn-icon {
		width: 16px;
		height: 16px;
	}

	.spinner {
		width: 16px;
		height: 16px;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: white;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Video container */
	.video-container {
		border-radius: 10px;
		overflow: hidden;
		background: rgba(0, 0, 0, 0.05);
		border: 1px solid rgba(0, 0, 0, 0.06);
		margin-bottom: 8px;
	}

	.generated-video {
		width: 100%;
		height: auto;
		display: block;
		max-height: 400px;
		object-fit: contain;
	}

	.download-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 10px 16px;
		background: rgba(0, 0, 0, 0.06);
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 8px;
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
	}

	.download-btn:hover {
		background: rgba(204, 0, 0, 0.1);
		border-color: rgba(204, 0, 0, 0.2);
		color: #c00;
	}

	/* Error message */
	.error-message {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px;
		background: rgba(235, 0, 0, 0.08);
		border: 1px solid rgba(235, 0, 0, 0.15);
		border-radius: 10px;
		color: #c00;
		font-size: 12px;
	}

	.error-icon {
		width: 16px;
		height: 16px;
		flex-shrink: 0;
	}
</style>
