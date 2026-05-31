<script lang="ts">
	type CameraSnapshot = {
		projection?: string;
		position?: number[];
		target?: number[];
		fov?: number | null;
		zoom?: number | null;
	} | null;
	type ShotFrame = {
		imageDataUrl: string;
		camera: CameraSnapshot;
		capturedAt: number;
	};
	type GeneratedClip = {
		id: string;
		status: string;
		videoUrl?: string;
		jobId?: string;
		error?: string;
	};
	type FrameAsset = ShotFrame & {
		id: string;
		label: string;
		source: 'screenshot' | 'generated';
	};
	type VideoShot = {
		start?: ShotFrame;
		end?: ShotFrame;
		clips: GeneratedClip[];
	};
	type CanvasAspectRatio =
		| 'fill'
		| '1:1'
		| '4:3'
		| '16:9'
		| '9:16'
		| '4:5'
		| '3:2'
		| '2:3'
		| '21:9';

	let {
		liveObjText = '',
		providerSettings = {
			provider: 'openai',
			apiKey: '',
			apiUrl: '',
			imageUrl: '',
			videoUrl: '',
			textModel: '',
			imageModel: '',
			videoModel: '',
			rememberMe: false
		},
		onCaptureSceneScreenshot,
		onCaptureSceneCameraSnapshot,
		canvasAspectRatio = 'fill',
		prompt = $bindable(''),
		videoPrompt = $bindable(''),
		screenshotDataUrl = $bindable(''),
		generatedImageDataUrl = $bindable(''),
		frameAssets = $bindable<FrameAsset[]>([]),
		videoShot = $bindable<VideoShot>({ clips: [] }),
		videoBusy = $bindable(false),
		generatedDirectionJson = $bindable(''),
		busy = $bindable(false),
		errorLine = $bindable<string | null>(null)
	}: {
		liveObjText?: string;
		providerSettings?: {
			provider: string;
			apiKey: string;
			apiUrl: string;
			imageUrl: string;
			videoUrl?: string;
			textModel: string;
			imageModel: string;
			videoModel?: string;
			rememberMe: boolean;
		};
		onCaptureSceneScreenshot?: () => string;
		onCaptureSceneCameraSnapshot?: () => CameraSnapshot;
		canvasAspectRatio?: CanvasAspectRatio;
		prompt?: string;
		videoPrompt?: string;
		screenshotDataUrl?: string;
		generatedImageDataUrl?: string;
		frameAssets?: FrameAsset[];
		videoShot?: VideoShot;
		videoBusy?: boolean;
		generatedDirectionJson?: string;
		busy?: boolean;
		errorLine?: string | null;
	} = $props();

	let fullscreenImageDataUrl = $state('');
	let fullscreenDialog: HTMLDialogElement | null = $state(null);
	let promptBusy = $state(false);

	let videoProviderReady = $derived(
		(providerSettings.provider === 'google' || providerSettings.provider === 'openrouter') &&
			!!providerSettings.apiKey?.trim() &&
			!!providerSettings.videoModel?.trim()
	);
	let videoProviderMessage = $derived(
		'Add an API key and choose a video model in Provider.'
	);
	let videoProviderLabel = $derived(
		providerSettings.provider === 'google'
			? 'Google Veo'
			: providerSettings.provider === 'openrouter'
				? 'OpenRouter video'
				: 'Video provider'
	);
	let videoAspectRatio = $derived(canvasAspectRatio === 'fill' ? '16:9' : canvasAspectRatio);
	let selectedVideoSupportsEndFrame = $derived(
		modelSupportsEndFrame(providerSettings.provider, providerSettings.videoModel ?? '')
	);

	function modelSupportsEndFrame(provider: string, model: string): boolean {
		const normalizedProvider = provider.trim().toLowerCase();
		const normalizedModel = model.trim().toLowerCase();
		if (!normalizedModel) return false;
		if (normalizedProvider === 'google') {
			return (
				normalizedModel === 'veo-3.1-generate-preview' ||
				normalizedModel === 'veo-3.1-fast-generate-preview'
			);
		}
		if (normalizedProvider === 'openrouter') {
			return (
				normalizedModel.includes('veo-3.1') ||
				normalizedModel.includes('wan') ||
				normalizedModel.includes('seedance')
			);
		}
		return false;
	}

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

	function downloadVideo(videoUrl: string, filenamePrefix: string) {
		if (!videoUrl) return;
		const link = document.createElement('a');
		link.href = videoUrl;
		link.download = `${filenamePrefix}-${Date.now()}.mp4`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	function generatedAnimationPrompt(): string {
		return animationPromptFromDirectionJson(generatedDirectionJson);
	}

	function animationPromptFromDirectionJson(directionJson: string): string {
		if (!directionJson) return '';
		try {
			const direction = JSON.parse(directionJson) as {
				story_for_image_and_3s_animation?: { animation_prompt?: string };
			};
			return direction.story_for_image_and_3s_animation?.animation_prompt?.trim() ?? '';
		} catch {
			return '';
		}
	}

	function promptForVideo(): string {
		return videoPrompt.trim();
	}

	async function loadImageFromDataUrl(dataUrl: string): Promise<HTMLImageElement> {
		const image = new Image();
		image.decoding = 'async';
		const loaded = new Promise<void>((resolve, reject) => {
			image.onload = () => resolve();
			image.onerror = () => reject(new Error('Invalid image data URL'));
		});
		image.src = dataUrl;
		await loaded;
		return image;
	}

	function aspectRatioLabel(width: number, height: number, fallback: string): string {
		const ratio = width / height;
		const options = [
			{ label: '1:1', ratio: 1 },
			{ label: '4:3', ratio: 4 / 3 },
			{ label: '16:9', ratio: 16 / 9 },
			{ label: '9:16', ratio: 9 / 16 },
			{ label: '4:5', ratio: 4 / 5 },
			{ label: '3:2', ratio: 3 / 2 },
			{ label: '2:3', ratio: 2 / 3 },
			{ label: '21:9', ratio: 21 / 9 }
		];
		return options.reduce((best, option) =>
			Math.abs(Math.log(option.ratio / ratio)) < Math.abs(Math.log(best.ratio / ratio))
				? option
				: best
		).label ?? fallback;
	}

	async function aspectRatioForVideo(dataUrl: string): Promise<string> {
		if (canvasAspectRatio !== 'fill') return canvasAspectRatio;
		const image = await loadImageFromDataUrl(dataUrl);
		return aspectRatioLabel(image.naturalWidth, image.naturalHeight, videoAspectRatio);
	}

	async function dataUrlToVideoFrameBlob(dataUrl: string): Promise<Blob> {
		const image = await loadImageFromDataUrl(dataUrl);
		const maxSide = 1280;
		const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
		const width = Math.max(1, Math.round(image.naturalWidth * scale));
		const height = Math.max(1, Math.round(image.naturalHeight * scale));
		const canvas = document.createElement('canvas');
		canvas.width = width;
		canvas.height = height;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('Unable to prepare video frame');
		ctx.drawImage(image, 0, 0, width, height);

		return new Promise<Blob>((resolve, reject) => {
			canvas.toBlob(
				(blob) => (blob ? resolve(blob) : reject(new Error('Unable to encode video frame'))),
				'image/jpeg',
				0.86
			);
		});
	}

	function wait(ms: number): Promise<void> {
		return new Promise((resolve) => setTimeout(resolve, ms));
	}

	function captureScreenshotDataUrl(addToGallery: boolean): string {
		errorLine = null;
		const dataUrl = onCaptureSceneScreenshot?.() ?? '';
		if (!dataUrl) {
			errorLine = 'Unable to capture screenshot from the 3D scene.';
			return '';
		}
		screenshotDataUrl = dataUrl;
		if (addToGallery) addFrameAsset(dataUrl, 'screenshot');
		return dataUrl;
	}

	function takeScreenshot() {
		captureScreenshotDataUrl(true);
	}

	function addFrameAsset(imageDataUrl: string, source: FrameAsset['source']) {
		const id =
			typeof crypto !== 'undefined' && 'randomUUID' in crypto
				? crypto.randomUUID()
				: `${Date.now()}-${Math.random().toString(16).slice(2)}`;
		const label = source === 'screenshot' ? `Shot ${frameAssets.length + 1}` : `Image ${frameAssets.length + 1}`;
		frameAssets = [
			{
				id,
				label,
				source,
				imageDataUrl,
				camera: onCaptureSceneCameraSnapshot?.() ?? null,
				capturedAt: Date.now()
			},
			...frameAssets
		].slice(0, 12);
	}

	function updateActiveVideoShot(patch: Partial<VideoShot>) {
		videoShot = { ...videoShot, ...patch };
	}

	function assignFrameAsset(frame: 'start' | 'end', asset: FrameAsset) {
		errorLine = null;
		updateActiveVideoShot({
			[frame]: {
				imageDataUrl: asset.imageDataUrl,
				camera: asset.camera,
				capturedAt: asset.capturedAt
			},
			clips: []
		});
	}

	function hasTimelineSpace(): boolean {
		return !videoShot.start || (selectedVideoSupportsEndFrame && !videoShot.end);
	}

	function addFrameAssetToTimeline(asset: FrameAsset) {
		if (videoBusy) return;
		if (!videoShot.start) {
			assignFrameAsset('start', asset);
			return;
		}
		if (selectedVideoSupportsEndFrame && !videoShot.end) {
			assignFrameAsset('end', asset);
			return;
		}
		errorLine = selectedVideoSupportsEndFrame
			? 'Clear a timeline frame before adding another.'
			: 'This video model uses one start frame.';
	}

	function clearTimelineFrame(frame: 'start' | 'end') {
		errorLine = null;
		updateActiveVideoShot({ [frame]: undefined, clips: [] });
	}

	function replaceClip(clips: GeneratedClip[], clipId: string, patch: Partial<GeneratedClip>) {
		return clips.map((clip) => (clip.id === clipId ? { ...clip, ...patch } : clip));
	}

	async function downloadProviderVideoUri(videoUri: string): Promise<string> {
		const response = await fetch('/api/render-video/download', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
					provider: providerSettings.provider,
					apiKey: providerSettings.apiKey?.trim() || undefined,
					videoUri
			})
		});
		if (!response.ok) {
			const payload = (await response.json().catch(() => ({}))) as { message?: string };
			throw new Error(payload.message || 'Video download failed');
		}
		return URL.createObjectURL(await response.blob());
	}

	async function pollVideoClip(clipId: string, jobId: string, clips: GeneratedClip[]) {
		let currentClips = clips;
		for (let attempt = 1; attempt <= 60; attempt += 1) {
			await wait(10_000);
			const response = await fetch('/api/render-video/status', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					provider: providerSettings.provider,
					apiKey: providerSettings.apiKey?.trim() || undefined,
					videoUrl: providerSettings.videoUrl?.trim() || undefined,
					jobId
				})
			});
			const payload = (await response.json().catch(() => ({}))) as {
				message?: string;
				status?: string;
				jobId?: string;
				videoUri?: string;
			};
			if (!response.ok) throw new Error(payload.message || 'Video polling failed');
			if (payload.status === 'completed' && payload.videoUri) {
				const videoUrl = await downloadProviderVideoUri(payload.videoUri);
				currentClips = replaceClip(currentClips, clipId, {
					status: 'Take 1: ready',
					videoUrl,
					jobId: payload.jobId ?? jobId
				});
				updateActiveVideoShot({ clips: currentClips });
				return currentClips;
			}
			currentClips = replaceClip(currentClips, clipId, {
				status: `Take 1: processing ${attempt}/60`,
				jobId: payload.jobId ?? jobId
			});
			updateActiveVideoShot({ clips: currentClips });
		}
		throw new Error('Video generation is still processing. Try again later.');
	}

	async function generateVideoClips() {
		if (videoBusy) return;
		errorLine = null;
		if (!videoShot.start?.imageDataUrl) {
			errorLine = 'Capture a start frame first.';
			return;
		}
		const videoPrompt = promptForVideo();
		if (!videoPrompt) {
			errorLine = 'Please enter a render prompt.';
			return;
		}
		if (providerSettings.provider !== 'openrouter' && providerSettings.provider !== 'google') {
			errorLine = 'Select Google in Provider.';
			return;
		}
		if (!videoProviderReady) {
			errorLine = videoProviderMessage;
			return;
		}

		videoBusy = true;
		const shot = videoShot;
		const startFrameDataUrl = shot.start?.imageDataUrl ?? '';
		const endFrameDataUrl = shot.end?.imageDataUrl ?? '';
		let clips: GeneratedClip[] = [];
		updateActiveVideoShot({ clips: [] });
		for (let take = 1; take <= 1; take += 1) {
			const clipId =
				typeof crypto !== 'undefined' && 'randomUUID' in crypto
					? crypto.randomUUID()
					: `${Date.now()}-${take}`;
			const runningClip: GeneratedClip = { id: clipId, status: `Take ${take}: running` };
			clips = [...clips, runningClip];
			updateActiveVideoShot({ clips });
			try {
				const formData = new FormData();
				formData.set('prompt', videoPrompt);
				formData.set('liveObjText', liveObjText);
				formData.set('provider', providerSettings.provider);
				formData.set('apiKey', providerSettings.apiKey?.trim() || '');
				formData.set('videoModel', providerSettings.videoModel ?? '');
				formData.set('videoUrl', providerSettings.videoUrl?.trim() || '');
				formData.set('aspectRatio', await aspectRatioForVideo(startFrameDataUrl));
				formData.set('startFrame', await dataUrlToVideoFrameBlob(startFrameDataUrl), 'start-frame.jpg');
				if (endFrameDataUrl) {
					formData.set('endFrame', await dataUrlToVideoFrameBlob(endFrameDataUrl), 'end-frame.jpg');
				}
				const response = await fetch('/api/render-video', {
					method: 'POST',
					body: formData
				});
				const payload = (await response.json().catch(() => ({}))) as {
					message?: string;
					status?: string;
					jobId?: string;
					videoUrl?: string;
					videoDataUrl?: string;
				};
				if (!response.ok) {
					throw new Error(payload.message || 'Video generation failed');
				}
				clips = replaceClip(clips, clipId, {
					status:
						payload.videoUrl || payload.videoDataUrl
							? `Take ${take}: ready`
							: `Take ${take}: ${payload.status ?? 'pending'}`,
					videoUrl: payload.videoUrl || payload.videoDataUrl,
					jobId: payload.jobId
				});
				updateActiveVideoShot({ clips });
				if (!payload.videoUrl && !payload.videoDataUrl && payload.jobId) {
					clips = await pollVideoClip(clipId, payload.jobId, clips);
				}
			} catch (e) {
				const failedClip: GeneratedClip = {
					id: clipId,
					status: `Take ${take}: failed`,
					error: e instanceof Error ? e.message : String(e)
				};
				clips = clips.map((clip) => (clip.id === clipId ? failedClip : clip));
				updateActiveVideoShot({ clips });
				errorLine = failedClip.error ?? 'Video generation failed';
				break;
			}
		}
		videoBusy = false;
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
			const directionJson = payload.direction ? JSON.stringify(payload.direction, null, 2) : '';
			generatedDirectionJson = directionJson;
			const animationPrompt = animationPromptFromDirectionJson(directionJson);
			if (animationPrompt) videoPrompt = animationPrompt;
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
		const renderScreenshotDataUrl = captureScreenshotDataUrl(false);
		if (!renderScreenshotDataUrl) return;
		busy = true;
		try {
			const response = await fetch('/api/render-image', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					prompt,
					screenshotDataUrl: renderScreenshotDataUrl,
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
			addFrameAsset(payload.imageDataUrl, 'generated');
		} catch (e) {
			errorLine = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="live-obj-render-tab">
	<section class="planner-render-card" aria-label="Image frame">
		<div class="planner-render-card-head">
			<div>
				<div class="planner-render-title">Image frame</div>
				<div class="planner-video-note">Capture the current scene or generate a polished frame.</div>
			</div>
		</div>
		<label class="planner-context-field planner-render-field">
			<span class="planner-label-inline">Image prompt</span>
			<textarea
				class="planner-text-input planner-render-prompt"
				rows="3"
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
				disabled={busy || promptBusy || videoBusy}>Take screenshot</button
			>
			<button
				type="button"
				class="send-button"
				onclick={generateImage}
				disabled={busy || promptBusy || videoBusy || !prompt.trim()}
			>
				{busy ? 'Generating…' : 'Generate image'}
			</button>
		</div>
	</section>

	<section class="planner-render-card" aria-label="Gallery">
		<div class="planner-render-card-head">
			<div>
				<div class="planner-render-title">Gallery</div>
				<div class="planner-video-note">Frames available for the video timeline.</div>
			</div>
			<span class="planner-video-provider-pill">
				{frameAssets.length ? `${frameAssets.length} frame${frameAssets.length === 1 ? '' : 's'}` : 'Empty'}
			</span>
		</div>
		{#if frameAssets.length}
			<div class="planner-frame-gallery" aria-label="Frame gallery">
				{#each frameAssets as asset (asset.id)}
					<div class="planner-frame-asset">
						<button
							type="button"
							class="planner-frame-thumb"
							onclick={() => openFullscreen(asset.imageDataUrl)}
							title="View frame"
							aria-label={`View ${asset.label}`}
						>
							<img src={asset.imageDataUrl} alt={asset.label} />
						</button>
						<div class="planner-frame-meta">
							<span>{asset.label}</span>
							<span>{asset.source === 'generated' ? 'Generated' : 'Screenshot'}</span>
						</div>
						<div class="planner-frame-actions">
							<button
								type="button"
								class="planner-frame-add-button"
								onclick={() => addFrameAssetToTimeline(asset)}
								disabled={videoBusy || !hasTimelineSpace()}>Add to timeline</button
							>
							<button
								type="button"
								class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
								title="View fullscreen"
								aria-label={`View ${asset.label} fullscreen`}
								onclick={() => openFullscreen(asset.imageDataUrl)}
							>
								<svg
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									width="14"
									height="14"
									aria-hidden="true"
								>
									<path
										d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"
									/>
								</svg>
							</button>
							<button
								type="button"
								class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
								title="Download frame"
								aria-label={`Download ${asset.label}`}
								onclick={() => downloadImage(asset.imageDataUrl, asset.label.toLowerCase().replaceAll(' ', '-'))}
							>
								<svg
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									width="14"
									height="14"
									aria-hidden="true"
								>
									<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
									<polyline points="7 10 12 15 17 10" />
									<line x1="12" y1="15" x2="12" y2="3" />
								</svg>
							</button>
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="planner-video-note">Take a screenshot or generate an image to add frames here.</div>
		{/if}
	</section>

	<section class="planner-video-sequence" aria-label="Video sequence">
		<div class="planner-video-head">
			<div>
				<div class="planner-render-title">Video shot</div>
				<div class="planner-video-note">
					Add gallery frames to the timeline, then generate a {videoAspectRatio} clip.
				</div>
			</div>
			<span class="planner-video-provider-pill">{videoProviderLabel}</span>
		</div>

		<section class="planner-render-subsection" aria-label="Timeline">
			<div class="planner-render-subhead">
				<span>Timeline</span>
				<span>Start + optional end</span>
			</div>
			<div class="planner-video-timeline" aria-label="Video timeline">
				<div class="planner-video-slot" class:filled={!!videoShot.start}>
					<div class="planner-video-slot-head">
						<span>Start</span>
						{#if videoShot.start}
							<button type="button" onclick={() => clearTimelineFrame('start')} disabled={videoBusy}
								>Clear</button
							>
						{/if}
					</div>
					{#if videoShot.start}
						<img src={videoShot.start.imageDataUrl} alt="Video start frame" />
					{:else}
						<div class="planner-video-slot-empty">Add first frame</div>
					{/if}
				</div>
				<div class="planner-video-slot" class:filled={!!videoShot.end} class:disabled={!selectedVideoSupportsEndFrame}>
					<div class="planner-video-slot-head">
						<span>End</span>
						{#if videoShot.end}
							<button type="button" onclick={() => clearTimelineFrame('end')} disabled={videoBusy}
								>Clear</button
							>
						{/if}
					</div>
					{#if videoShot.end}
						<img src={videoShot.end.imageDataUrl} alt="Video end frame" />
					{:else}
						<div class="planner-video-slot-empty">
							{selectedVideoSupportsEndFrame ? 'Add optional end frame' : 'Not used by model'}
						</div>
					{/if}
				</div>
			</div>
		</section>

		<div class="planner-video-controls">
			<label>
				<span class="planner-label-inline">Motion prompt</span>
				<textarea
					class="planner-text-input planner-render-prompt planner-video-prompt"
					rows="3"
					placeholder="Describe the motion or transformation for the clip..."
					bind:value={videoPrompt}
					disabled={videoBusy || promptBusy}
				></textarea>
			</label>
		</div>

		<div class="planner-video-actions">
			<button
				type="button"
				class="send-button"
				onclick={generateVideoClips}
				disabled={busy ||
					promptBusy ||
					videoBusy ||
					!promptForVideo() ||
					!videoShot.start?.imageDataUrl ||
					!videoProviderReady}
			>
				{videoBusy ? 'Generating…' : 'Generate clip'}
			</button>
		</div>

		{#if !videoProviderReady}
			<div class="planner-video-note">
				{videoProviderMessage}
			</div>
		{/if}

		{#if videoShot.clips.length}
			<div class="planner-video-clips">
				{#each videoShot.clips as clip (clip.id)}
					<div class="planner-video-clip">
						<div class="planner-video-clip-status">{clip.status}</div>
						{#if clip.videoUrl}
							<!-- svelte-ignore a11y_media_has_caption -->
							<video src={clip.videoUrl} controls playsinline></video>
							<div class="planner-video-clip-actions">
								<button
									type="button"
									class="planner-monaco-action-btn planner-monaco-action-btn--icon-only"
									title="Download clip"
									aria-label="Download clip"
									onclick={() => downloadVideo(clip.videoUrl ?? '', 'video-clip')}
								>
									<svg
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										width="14"
										height="14"
										aria-hidden="true"
									>
										<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
										<polyline points="7 10 12 15 17 10" />
										<line x1="12" y1="15" x2="12" y2="3" />
									</svg>
								</button>
							</div>
						{:else if clip.error}
							<div class="planner-status" role="status">{clip.error}</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</section>

	{#if generatedDirectionJson}
		<details class="planner-render-direction">
			<summary>Visual direction JSON</summary>
			<pre>{generatedDirectionJson}</pre>
		</details>
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
	.planner-render-card {
		display: flex;
		flex-direction: column;
		gap: 9px;
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-md);
		background: var(--spell-surface-faint);
		padding: 12px;
	}
	.planner-render-card-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
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
	.planner-render-title {
		font-size: 12px;
		font-weight: 600;
		color: #4a4a4a;
	}
	.planner-video-sequence {
		display: flex;
		flex-direction: column;
		gap: 9px;
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-md);
		background: var(--spell-surface-faint);
		padding: 12px;
	}
	.planner-video-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}
	.planner-video-provider-pill {
		flex: 0 0 auto;
		border: 1px solid rgba(0, 0, 235, 0.12);
		border-radius: var(--spell-radius-pill);
		background: var(--spell-blue-soft);
		color: var(--spell-blue);
		padding: 4px 8px;
		font-size: 10px;
		font-weight: 750;
		white-space: nowrap;
	}
	.planner-video-note {
		font-size: 11px;
		line-height: 1.4;
		color: #64748b;
	}
	.planner-video-controls {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 8px;
	}
	.planner-render-subsection {
		display: flex;
		flex-direction: column;
		gap: 7px;
	}
	.planner-render-subhead {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		font-size: 11px;
		font-weight: 750;
		color: #475569;
	}
	.planner-render-subhead span:last-child {
		font-size: 10px;
		font-weight: 650;
		color: #94a3b8;
	}
	.planner-video-timeline {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
	}
	.planner-video-slot {
		min-width: 0;
		border: 1px dashed var(--spell-border);
		border-radius: var(--spell-radius-sm);
		background: rgba(255, 255, 255, 0.42);
		padding: 7px;
	}
	.planner-video-slot.filled {
		border-style: solid;
		background: var(--spell-surface-soft);
	}
	.planner-video-slot.disabled {
		opacity: 0.58;
	}
	.planner-video-slot-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
		margin-bottom: 6px;
		font-size: 11px;
		font-weight: 750;
		color: #475569;
	}
	.planner-video-slot-head button {
		border: 0;
		background: transparent;
		color: var(--spell-blue);
		font: inherit;
		font-size: 10px;
		font-weight: 750;
		cursor: pointer;
		padding: 0;
	}
	.planner-video-slot-head button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}
	.planner-video-slot img,
	.planner-video-slot-empty {
		box-sizing: border-box;
		width: 100%;
		min-height: 52px;
		border-radius: var(--spell-radius-sm);
	}
	.planner-video-slot img {
		aspect-ratio: 16 / 9;
		display: block;
		object-fit: cover;
		border: 1px solid rgba(0, 0, 0, 0.1);
	}
	.planner-video-slot-empty {
		display: grid;
		place-items: center;
		border: 1px solid var(--spell-border-soft);
		background: rgba(255, 255, 255, 0.5);
		color: #94a3b8;
		font-size: 10px;
		font-weight: 650;
		line-height: 1.25;
		text-align: center;
		padding: 7px 5px;
		overflow-wrap: anywhere;
	}
	.planner-frame-gallery {
		display: flex;
		gap: 8px;
		overflow-x: auto;
		padding-bottom: 2px;
		scrollbar-width: thin;
	}
	.planner-frame-asset {
		flex: 0 0 118px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.planner-frame-thumb {
		display: block;
		width: 100%;
		aspect-ratio: 16 / 9;
		padding: 0;
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-sm);
		background: var(--spell-surface-soft);
		overflow: hidden;
		cursor: pointer;
	}
	.planner-frame-thumb img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.planner-frame-meta {
		display: flex;
		justify-content: space-between;
		gap: 6px;
		font-size: 10px;
		font-weight: 650;
		color: #64748b;
	}
	.planner-frame-meta span:first-child {
		color: #334155;
	}
	.planner-frame-actions {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 5px;
	}
	.planner-frame-add-button {
		border: 1px solid var(--spell-border);
		border-radius: var(--spell-radius-pill);
		background: var(--spell-surface-soft);
		color: var(--spell-muted);
		min-height: 24px;
		font: inherit;
		font-size: 10px;
		font-weight: 750;
		cursor: pointer;
	}
	.planner-frame-actions button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}
	.planner-frame-actions .planner-monaco-action-btn--icon-only {
		width: 26px;
		height: 26px;
		min-height: 26px;
		padding: 0;
		border-radius: var(--spell-radius-sm);
	}
	.planner-video-controls label {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
	}
	.planner-video-actions {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 8px;
	}
	.planner-video-actions > button {
		width: 100%;
		padding-inline: 8px;
		white-space: nowrap;
	}
	.planner-video-clips {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.planner-video-clip {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.planner-video-clip-status {
		font-size: 12px;
		font-weight: 700;
		color: #334155;
	}
	.planner-video-clip video {
		width: 100%;
		border-radius: 8px;
		background: #111;
	}
	.planner-video-clip-actions {
		display: flex;
		justify-content: flex-end;
		gap: 5px;
	}
	.planner-video-clip-actions .planner-monaco-action-btn--icon-only {
		width: 26px;
		height: 26px;
		min-height: 26px;
		padding: 0;
		border-radius: var(--spell-radius-sm);
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
