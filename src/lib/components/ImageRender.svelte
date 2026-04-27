<script>
	import { chatHistory, currentChain, generatedImageUrl, screenshotPreviewUrl, imagePromptText, isRenderingImage, imageErrorMessage } from '$lib/stores/ui.js';
	import { get } from 'svelte/store';
	import { browser } from '$app/environment';
	import VideoRender from './VideoRender.svelte';

	export let addLog = (message, type = 'info') => {};

	let promptText = '';
	let isFullscreen = false;
	let fullscreenImage = '';
	let isGeneratingPrompts = false;
	let promptGenError = null;

	const MAX_WIDTH = 1200;
	const MODEL_NAME = 'google/flash-image-2.5';

	// Initialize stores only in browser
	$: if (browser && !$imagePromptText) {
		// Stores are ready
	}

	// Generate prompt from first user message when tab becomes active
	export function generatePromptFromHistory() {
		const history = get(chatHistory);
		const firstUserMessage = history.find(m => m.role === 'user');
		if (firstUserMessage) {
			// Create an enhanced prompt based on the user's initial request
			const baseRequest = firstUserMessage.content;
			const enhancedPrompt = `Transform this 3D scene into a high quality rendered image. IMPORTANT: Maintain the exact same composition, camera angle, and object placement from the provided screenshot. The scene shows: ${baseRequest}. Professional lighting, clean studio background, photorealistic, detailed textures, product photography style, soft shadows. Keep the same layout and perspective as the reference image.`;
			promptText = enhancedPrompt;
			imagePromptText.set(enhancedPrompt);
		} else {
			const defaultPrompt = `Transform this 3D scene into a high quality rendered image. IMPORTANT: Maintain the exact same composition, camera angle, and object placement from the provided screenshot. Professional lighting, clean studio background, photorealistic, detailed textures, product photography style, soft shadows. Keep the same layout and perspective as the reference image.`;
			promptText = defaultPrompt;
			imagePromptText.set(defaultPrompt);
		}
	}

	function openFullscreen(imageUrl) {
		fullscreenImage = imageUrl;
		isFullscreen = true;
	}

	function closeFullscreen() {
		isFullscreen = false;
		fullscreenImage = '';
	}

	// Handle ESC key to close fullscreen
	function handleKeydown(e) {
		if (e.key === 'Escape' && isFullscreen) {
			closeFullscreen();
		}
	}

	// Capture screenshot from Three.js canvas
	function captureScreenshot() {
		if (!browser || !window.SceneCore?.renderer) {
			throw new Error('Renderer not available');
		}

		const renderer = window.SceneCore.renderer;
		const canvas = renderer.domElement;
		
		// Render the scene first to ensure it's up to date
		if (window.SceneCore.scene && window.SceneCore.camera) {
			renderer.render(window.SceneCore.scene, window.SceneCore.camera);
		}

		// Calculate dimensions while maintaining aspect ratio
		let width = canvas.width;
		let height = canvas.height;

		if (width > MAX_WIDTH) {
			const ratio = MAX_WIDTH / width;
			width = MAX_WIDTH;
			height = Math.round(height * ratio);
		}

		// Create a temporary canvas to resize the image
		const tempCanvas = document.createElement('canvas');
		tempCanvas.width = width;
		tempCanvas.height = height;
		const ctx = tempCanvas.getContext('2d');

		// Draw the original canvas onto the resized canvas
		ctx.drawImage(canvas, 0, 0, width, height);

		// Get base64 data URL (JPEG for smaller size)
		return tempCanvas.toDataURL('image/jpeg', 0.9);
	}

	// Capture and show screenshot preview
	function captureAndShowScreenshot() {
		try {
			const dataUrl = captureScreenshot();
			screenshotPreviewUrl.set(dataUrl);
			console.log('[ImageRender] Screenshot captured:', dataUrl.substring(0, 100) + '...');
			addLog('Screenshot captured for preview');
		} catch (err) {
			console.error('[ImageRender] Screenshot capture failed:', err);
			imageErrorMessage.set('Failed to capture screenshot: ' + err.message);
		}
	}

	// Download screenshot for debugging
	function downloadScreenshot() {
		if (!$screenshotPreviewUrl) return;
		const link = document.createElement('a');
		link.href = $screenshotPreviewUrl;
		link.download = `screenshot-${Date.now()}.jpg`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		addLog('Screenshot downloaded', 'success');
	}

	// Call Together AI API for image generation
	async function generateImage() {
		if (!promptText.trim()) {
			imageErrorMessage.set('Please enter a prompt');
			return;
		}

		isRenderingImage.set(true);
		imageErrorMessage.set(null);
		generatedImageUrl.set(null);

		try {
			addLog('Capturing 3D scene screenshot...');
			const screenshotDataUrl = captureScreenshot();
			
			// Show preview of what we're sending
			screenshotPreviewUrl.set(screenshotDataUrl);
			console.log('[ImageRender] Screenshot preview:', screenshotDataUrl.substring(0, 100) + '...');
			
			const base64Image = screenshotDataUrl.split(',')[1];

			addLog('Sending to AI service for image generation...');

			// Use the image generations API endpoint through our proxy
			const response = await fetch('/api/images', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({
					model: MODEL_NAME,
					prompt: promptText,
					image: base64Image
				})
			});

			if (!response.ok) {
				const errorText = await response.text();
				throw new Error(`API error: ${response.status} - ${errorText}`);
			}

			const data = await response.json();

			// Together AI image generations API returns data.data array with b64_json or url
			if (data.data && data.data[0]) {
				const imageData = data.data[0];
				if (imageData.b64_json) {
					generatedImageUrl.set(`data:image/png;base64,${imageData.b64_json}`);
					addLog('Image generated successfully!');
				} else if (imageData.url) {
					generatedImageUrl.set(imageData.url);
					addLog('Image generated successfully!');
				} else {
					throw new Error('Unexpected response format from API');
				}
			} else {
				throw new Error('No image data in API response');
			}
		} catch (error) {
			console.error('Image generation failed:', error);
			imageErrorMessage.set(error.message);
			addLog(`Image generation failed: ${error.message}`);
		} finally {
			isRenderingImage.set(false);
		}
	}

	async function generatePrompts() {
		isGeneratingPrompts = true;
		promptGenError = null;
		try {
			const chain = get(currentChain);
			const history = get(chatHistory);
			const userRequest = history.find(m => m.role === 'user')?.content || '';

			addLog('Generating AI prompts from scene graph...');
			const response = await fetch('/api/generate-prompt', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ sceneGraph: chain, userRequest })
			});

			if (!response.ok) {
				const errText = await response.text();
				throw new Error(`API error: ${response.status} - ${errText}`);
			}

			const { imagePrompt } = await response.json();

			if (imagePrompt) {
				promptText = imagePrompt;
				imagePromptText.set(imagePrompt);
				addLog('Image prompt generated', 'success');
			}
		} catch (err) {
			promptGenError = err.message;
			addLog('Prompt generation failed: ' + err.message, 'error');
		} finally {
			isGeneratingPrompts = false;
		}
	}

	async function downloadImage() {
		if (!$generatedImageUrl) return;

		try {
			// Use proxy endpoint to avoid CORS
			const proxyUrl = `/api/image-proxy?url=${encodeURIComponent($generatedImageUrl)}`;
			const response = await fetch(proxyUrl);
			const blob = await response.blob();

			// Try to use File System Access API for folder picker
			if ('showSaveFilePicker' in window) {
				const suggestedName = `render-${Date.now()}.png`;
				// @ts-ignore - File System Access API may not be typed
				const fileHandle = await window.showSaveFilePicker({
					suggestedName: suggestedName,
					types: [
						{
							description: 'PNG Image',
							accept: { 'image/png': ['.png'] }
						}
					]
				});
				const writableStream = await fileHandle.createWritable();
				await writableStream.write(blob);
				await writableStream.close();
				addLog('Image saved to selected folder');
			} else {
				// Fallback for browsers that don't support File System Access API
				const link = document.createElement('a');
				link.href = URL.createObjectURL(blob);
				link.download = `render-${Date.now()}.png`;
				document.body.appendChild(link);
				link.click();
				document.body.removeChild(link);
				URL.revokeObjectURL(link.href);
				addLog('Image downloaded');
			}
		} catch (error) {
			if (error.name === 'AbortError') {
				// User cancelled the save dialog
				return;
			}
			console.error('Download failed:', error);
			addLog('Download failed: ' + error.message);
		}
	}
</script>

{#if browser}
<div class="image-render-tab">
	<details class="obj-block" open>
		<summary class="obj-header">
			<span class="obj-name">Image Generation</span>
			<span class="obj-badge">AI Render</span>
		</summary>
		
		<div class="vars-grid">
			<div class="var-row prompt-header-row">
				<label class="var-key">Image Prompt</label>
				<button
					class="gen-prompt-btn"
					on:click={generatePrompts}
					disabled={isGeneratingPrompts || $isRenderingImage}
					title="Generate prompts from scene graph using AI"
				>
					{#if isGeneratingPrompts}
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
					class="pi pi-str"
					bind:value={promptText}
					placeholder="Describe the image you want to generate..."
					rows="4"
					disabled={$isRenderingImage}
				></textarea>
			</div>
		</div>

		<details class="section-block" open>
			<summary class="section-header">Actions</summary>
			<div class="actions-list">
				<div class="button-group">
					<button
						class="render-btn"
						on:click={generateImage}
						disabled={$isRenderingImage || !promptText.trim()}
					>
						{#if $isRenderingImage}
							<span class="spinner"></span>
							Rendering...
						{:else}
							<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
								<circle cx="8.5" cy="8.5" r="1.5"/>
								<polyline points="21 15 16 10 5 21"/>
							</svg>
							Render Image
						{/if}
					</button>
					<button
						class="preview-btn"
						on:click={captureAndShowScreenshot}
						disabled={$isRenderingImage}
					>
						Preview Screenshot
					</button>
				</div>
			</div>
		</details>

		{#if $screenshotPreviewUrl}
			<details class="section-block" open>
				<summary class="section-header">Screenshot Preview <span class="count-badge">API Input</span></summary>
				<div class="vars-grid">
					<div class="image-container">
						<img src={$screenshotPreviewUrl} alt="Screenshot preview" class="generated-image" />
					</div>
					<button class="download-btn" on:click={downloadScreenshot}>
						<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
							<polyline points="7 10 12 15 17 10"/>
							<line x1="12" y1="15" x2="12" y2="3"/>
						</svg>
						Download Screenshot
					</button>
				</div>
			</details>
		{/if}

		{#if $generatedImageUrl}
			<details class="section-block" open>
				<summary class="section-header">Generated Image <span class="count-badge">Result</span></summary>
				<div class="vars-grid">
					<div class="image-container">
						<img src={$generatedImageUrl} alt="Generated render" class="generated-image" />
					</div>
					<div class="button-group">
						<button class="download-btn" on:click={downloadImage}>
							<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
								<polyline points="7 10 12 15 17 10"/>
								<line x1="12" y1="15" x2="12" y2="3"/>
							</svg>
							Download
						</button>
						<button class="fullscreen-btn" on:click={() => openFullscreen($generatedImageUrl)}>
							<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
							</svg>
							Fullscreen
						</button>
					</div>
				</div>
			</details>
		{/if}
	</details>

	<!-- Video Generation Section -->
	{#if $generatedImageUrl}
		<VideoRender {addLog} generatedImageUrl={$generatedImageUrl} />
	{/if}

	{#if $imageErrorMessage}
		<div class="error-message">
			<svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<circle cx="12" cy="12" r="10"/>
				<line x1="12" y1="8" x2="12" y2="12"/>
				<line x1="12" y1="16" x2="12.01" y2="16"/>
			</svg>
			{$imageErrorMessage}
		</div>
	{/if}
</div>

<!-- Fullscreen Modal -->
{#if isFullscreen}
	<div class="fullscreen-overlay" on:click={closeFullscreen} on:keydown={handleKeydown}>
		<div class="fullscreen-container" on:click|stopPropagation>
			<img src={fullscreenImage} alt="Full screen render" class="fullscreen-image" />
			<button class="fullscreen-close" on:click={closeFullscreen}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<line x1="18" y1="6" x2="6" y2="18"/>
					<line x1="6" y1="6" x2="18" y2="18"/>
				</svg>
			</button>
		</div>
	</div>
{/if}
{/if}

<style>
	.image-render-tab {
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
		min-height: 80px;
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
		background: #0000c0;
		transform: translateY(-1px);
		box-shadow: 0 4px 12px rgba(0, 0, 235, 0.3);
	}

	.render-btn:disabled {
		background: #ccc;
		cursor: not-allowed;
	}

	.preview-btn {
		padding: 12px 16px;
		background: rgba(0, 0, 0, 0.06);
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 10px;
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
		flex-shrink: 0;
	}

	.preview-btn:hover:not(:disabled) {
		background: rgba(0, 0, 235, 0.1);
		border-color: rgba(0, 0, 235, 0.2);
		color: #0000eb;
	}

	.preview-btn:disabled {
		opacity: 0.6;
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

	/* Image container */
	.image-container {
		border-radius: 10px;
		overflow: hidden;
		background: rgba(0, 0, 0, 0.05);
		border: 1px solid rgba(0, 0, 0, 0.06);
		margin-bottom: 8px;
	}

	.generated-image {
		width: 100%;
		height: auto;
		display: block;
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
		background: rgba(0, 0, 235, 0.1);
		border-color: rgba(0, 0, 235, 0.2);
		color: #0000eb;
	}

	.fullscreen-btn {
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

	.fullscreen-btn:hover {
		background: rgba(0, 0, 0, 0.1);
		border-color: rgba(0, 0, 0, 0.2);
		color: #000;
	}

	/* Fullscreen modal */
	.fullscreen-overlay {
		position: fixed !important;
		top: 0 !important;
		left: 0 !important;
		right: 0 !important;
		bottom: 0 !important;
		width: 100vw !important;
		height: 100vh !important;
		background: rgba(0, 0, 0, 0.9);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 9999;
		padding: 20px;
		box-sizing: border-box;
	}

	.fullscreen-container {
		position: relative;
		max-width: 100%;
		max-height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.fullscreen-image {
		max-width: 100%;
		max-height: 100%;
		object-fit: contain;
		border-radius: 8px;
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
	}

	.fullscreen-close {
		position: absolute;
		top: 16px;
		right: 16px;
		background: rgba(255, 255, 255, 0.9);
		border: none;
		width: 40px;
		height: 40px;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		transition: all 0.2s;
		color: #333;
	}

	.fullscreen-close:hover {
		background: white;
		transform: scale(1.1);
	}

	.fullscreen-close svg {
		width: 20px;
		height: 20px;
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
