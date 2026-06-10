<script lang="ts">
	type CameraSnapshot = {
		projection?: string;
		position?: number[];
		target?: number[];
		up?: number[];
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
		label?: string;
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
		middle?: ShotFrame;
		end?: ShotFrame;
		clips: GeneratedClip[];
	};
	type ProcessImageAsset = {
		label: string;
		meta?: string;
		imageDataUrl: string;
	};
	type AgentMetrics = {
		processCaptures?: number;
		galleryFrames?: number;
		animationClips?: number;
		buildEvents?: number;
		elapsedMs?: number;
		totalTokens?: number;
		reasoningTokens?: number;
		promptTokens?: number;
		completionTokens?: number;
	};
	type ReelAspectRatio = '16:9' | '9:16';
	type ReelClipPayload = {
		label?: string;
		videoDataUrl: string;
	};
	type ReelImagePayload = {
		label?: string;
		meta?: string;
		imageDataUrl: string;
	};
	type CaptureSceneScreenshotOptions = {
		frameObjectIds?: string[];
		xrayFocusObjectIds?: string[];
		xraySupportObjectIds?: string[];
		viewDirection?: [number, number, number];
		autoFrame?: boolean;
		framePadding?: number;
	};
	type ShotPlanFrame = {
		label?: string;
		purpose?: string;
		view?: string;
		camera_direction?: number[];
		focus_objects?: string[];
		framing?: string;
	};
	type ShotPlanPairPrompt = {
		from?: number;
		to?: number;
		prompt?: string;
	};
	type ShotPlanDirection = {
		shot_plan?: {
			aspect_ratio?: string;
			frames?: ShotPlanFrame[];
			pair_prompts?: ShotPlanPairPrompt[];
		};
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
		processImages = [],
		agentMetrics = {},
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
		onCaptureSceneScreenshot?: (options?: CaptureSceneScreenshotOptions | string[]) => string;
		onCaptureSceneCameraSnapshot?: () => CameraSnapshot;
		canvasAspectRatio?: CanvasAspectRatio;
		prompt?: string;
		videoPrompt?: string;
		screenshotDataUrl?: string;
		generatedImageDataUrl?: string;
		frameAssets?: FrameAsset[];
		videoShot?: VideoShot;
		processImages?: ProcessImageAsset[];
		agentMetrics?: AgentMetrics;
		videoBusy?: boolean;
		generatedDirectionJson?: string;
		busy?: boolean;
		errorLine?: string | null;
	} = $props();

	let fullscreenImageDataUrl = $state('');
	let fullscreenDialog: HTMLDialogElement | null = $state(null);
	let promptBusy = $state(false);
	let reelBusy = $state(false);
	let reelAspectRatio = $state<ReelAspectRatio>('9:16');
	let reelVideoDataUrl = $state('');
	let reelFilename = $state('spellshape-reel.mp4');
	let renderSourceFrameId = $state('');

	let videoProviderReady = $derived(
		(providerSettings.provider === 'google' || providerSettings.provider === 'openrouter') &&
			!!providerSettings.apiKey?.trim() &&
			!!providerSettings.videoModel?.trim()
	);
	let videoProviderMessage = $derived('Add an API key and choose a video model in Provider.');
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
		downloadUrl(videoUrl, `${filenamePrefix}-${Date.now()}.mp4`);
	}

	function downloadUrl(url: string, filename: string) {
		if (!url) return;
		const link = document.createElement('a');
		link.href = url;
		link.download = filename;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	function blobToDataUrl(blob: Blob): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(String(reader.result ?? ''));
			reader.onerror = () => reject(reader.error ?? new Error('Unable to encode video'));
			reader.readAsDataURL(blob);
		});
	}

	async function mediaUrlToDataUrl(url: string): Promise<string> {
		if (!url) return '';
		if (url.startsWith('data:')) return url;
		const response = await fetch(url);
		if (!response.ok) throw new Error('Unable to load final clip for reel');
		return blobToDataUrl(await response.blob());
	}

	async function processImagePayloads(images: ProcessImageAsset[]): Promise<ReelImagePayload[]> {
		return (
			await Promise.all(
				images.map(async (asset): Promise<ReelImagePayload | null> => {
					if (!asset.imageDataUrl) return null;
					return {
						label: asset.label,
						...(asset.meta ? { meta: asset.meta } : {}),
						imageDataUrl: await mediaUrlToDataUrl(asset.imageDataUrl)
					};
				})
			)
		).filter((asset): asset is ReelImagePayload => !!asset?.imageDataUrl);
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

	function sanitizeProjectFilename(value: string, fallback: string): string {
		const clean = value
			.trim()
			.split(/[\\/]/)
			.pop()
			?.replace(/[^A-Za-z0-9_.-]+/g, '-')
			.replace(/^-+|-+$/g, '');
		return clean || fallback;
	}

	function ensureImageExtension(filename: string, ext: string): string {
		if (/\.(png|jpe?g|webp)$/i.test(filename)) return filename;
		return `${filename}.${ext}`;
	}

	function textureFilenamesFromLiveObj(sourceText: string): string[] {
		const filenames: string[] = [];
		for (const line of sourceText.split(/\r?\n/)) {
			const textureMatch = line.match(/^\s*#@texture:\s*(.+)$/);
			if (!textureMatch) continue;
			const path =
				textureMatch[1]
					.match(/(?:^|\s)path=("[^"]+"|'[^']+'|\S+)/)?.[1]
					?.replace(/^['"]|['"]$/g, '') ??
				textureMatch[1]
					.match(/(?:^|\s)src=("[^"]+"|'[^']+'|\S+)/)?.[1]
					?.replace(/^['"]|['"]$/g, '');
			if (!path) continue;
			const ext = path.match(/\.(png|jpe?g|webp)(?:$|[?#])/i)?.[1] ?? 'png';
			filenames.push(
				ensureImageExtension(sanitizeProjectFilename(path, `texture-${filenames.length + 1}`), ext)
			);
		}
		return [...new Set(filenames)];
	}

	function isTextureGalleryImage(asset: ProcessImageAsset): boolean {
		const text = `${asset.meta ?? ''} ${asset.label ?? ''}`.toLowerCase();
		return (
			text.includes('source uv unwrap') ||
			text.includes('generated uv height') ||
			text.includes('generated uv diffuse') ||
			text.includes('texture artifact') ||
			text.includes('uv debug artifact')
		);
	}

	function textureGalleryImages(): ProcessImageAsset[] {
		return processImages
			.filter((asset) => isTextureGalleryImage(asset))
			.slice(0, 6);
	}

	function projectStructureEntries(
		hasFinalClip: boolean,
		timeline: ReturnType<typeof timelineFrames>
	): string[] {
		const entries = ['spellshape-live.obj', 'spellshape-live.mtl', 'manifest.json'];
		const textures = textureFilenamesFromLiveObj(liveObjText);
		if (textures.length) {
			entries.push('textures/');
			entries.push(...textures.map((filename) => `textures/${filename}`));
		}
		if (frameAssets.length || processImages.length || timeline.length) entries.push('screenshots/');
		if (frameAssets.length) {
			entries.push('screenshots/gallery/');
			entries.push(
				...frameAssets.map((asset, index) => {
					const label = sanitizeProjectFilename(asset.label.toLowerCase(), `frame-${index + 1}`);
					return `screenshots/gallery/${String(index + 1).padStart(3, '0')}-${label}.png`;
				})
			);
		}
		if (processImages.length) {
			entries.push('screenshots/process/');
			entries.push(
				...processImages.map((image, index) => {
					const label = sanitizeProjectFilename(image.label.toLowerCase(), `process-${index + 1}`);
					return `screenshots/process/${String(index + 1).padStart(3, '0')}-${label}.png`;
				})
			);
		}
		if (timeline.length) {
			entries.push('screenshots/timeline/');
			entries.push(...timeline.map((item) => `screenshots/timeline/${item.key}.png`));
		}
		if (hasFinalClip) {
			entries.push('videos/');
			entries.push('videos/final-animation.mp4');
			entries.push('videos/project-reel.mp4');
		}
		return [...new Set(entries)];
	}

	function parseShotPlanDirection(directionJson: string): ShotPlanDirection | null {
		if (!directionJson.trim()) return null;
		try {
			return JSON.parse(directionJson) as ShotPlanDirection;
		} catch {
			return null;
		}
	}

	function shotPlanPairPrompts(): string[] {
		return [shotPlanPairPrompt(0, 1), shotPlanPairPrompt(1, 2)].filter(
			(prompt) => prompt.length > 0
		);
	}

	function shotPlanPairPrompt(from: number, to: number): string {
		const prompts = parseShotPlanDirection(generatedDirectionJson)?.shot_plan?.pair_prompts ?? [];
		const exact = prompts.find((pair) => pair.from === from && pair.to === to);
		const fallback = prompts.find((pair, index) => index === from);
		return (exact?.prompt ?? fallback?.prompt ?? '').trim();
	}

	function timelinePairPrompt(fromIndex: number, toIndex: number, label: string): string {
		const generated = shotPlanPairPrompt(fromIndex, toIndex);
		const manual = promptForVideo();
		if (generated) return generated;
		if (!manual) return '';
		return `${label}: ${manual}`;
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
		return (
			options.reduce((best, option) =>
				Math.abs(Math.log(option.ratio / ratio)) < Math.abs(Math.log(best.ratio / ratio))
					? option
					: best
			).label ?? fallback
		);
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

	function selectedRenderSourceFrame(): FrameAsset | undefined {
		return frameAssets.find((asset) => asset.id === renderSourceFrameId);
	}

	function useFrameForImage(asset: FrameAsset) {
		errorLine = null;
		renderSourceFrameId = asset.id;
		screenshotDataUrl = asset.imageDataUrl;
	}

	function useCurrentViewForImage() {
		errorLine = null;
		renderSourceFrameId = '';
	}

	function addFrameAsset(imageDataUrl: string, source: FrameAsset['source']) {
		const id =
			typeof crypto !== 'undefined' && 'randomUUID' in crypto
				? crypto.randomUUID()
				: `${Date.now()}-${Math.random().toString(16).slice(2)}`;
		const label =
			source === 'screenshot'
				? `Shot ${frameAssets.length + 1}`
				: `Image ${frameAssets.length + 1}`;
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

	function makeFrameAsset(
		imageDataUrl: string,
		label: string,
		source: FrameAsset['source'] = 'screenshot'
	): FrameAsset {
		const id =
			typeof crypto !== 'undefined' && 'randomUUID' in crypto
				? crypto.randomUUID()
				: `${Date.now()}-${Math.random().toString(16).slice(2)}`;
		return {
			id,
			label,
			source,
			imageDataUrl,
			camera: onCaptureSceneCameraSnapshot?.() ?? null,
			capturedAt: Date.now()
		};
	}

	function viewDirectionFromShot(frame: ShotPlanFrame, index: number): [number, number, number] {
		const explicit = frame.camera_direction;
		if (
			Array.isArray(explicit) &&
			explicit.length >= 3 &&
			explicit.slice(0, 3).every((value) => typeof value === 'number' && Number.isFinite(value))
		) {
			return [explicit[0], explicit[1], explicit[2]];
		}
		const view = frame.view?.trim().toLowerCase() ?? '';
		if (view.includes('low')) return [-1, 0.25, -1];
		if (view.includes('high') || view.includes('top')) return [-0.45, 1.15, 0.65];
		if (view.includes('side')) return [1, 0.4, -0.8];
		if (view.includes('back')) return [0.75, 0.55, 1];
		return [
			[-1, 0.6, -1],
			[1, 0.4, -0.8],
			[-0.45, 1.1, 0.65]
		][index] as [number, number, number];
	}

	function shotPlanLabel(frame: ShotPlanFrame, index: number): string {
		const label = frame.label?.trim();
		if (label) return label;
		return ['Hero frame', 'Detail frame', 'Final frame'][index] ?? `Frame ${index + 1}`;
	}

	function framePaddingFromShot(frame: ShotPlanFrame): number {
		const text = `${frame.view ?? ''} ${frame.framing ?? ''} ${frame.purpose ?? ''}`.toLowerCase();
		if (/\b(close|detail|belly|waist|brushwork|glaze|material)\b/.test(text)) return 0.58;
		if (/\b(upper|rim|neck|silhouette|crest)\b/.test(text)) return 0.78;
		if (/\b(negative space|full|establish|hero|monumental)\b/.test(text)) return 1.18;
		return 1.02;
	}

	async function captureShotPlanFrames(directionJson: string) {
		const frames = parseShotPlanDirection(directionJson)?.shot_plan?.frames?.slice(0, 3) ?? [];
		if (frames.length < 3 || !onCaptureSceneScreenshot) return;
		const assets: FrameAsset[] = [];
		for (const [index, frame] of frames.entries()) {
			await wait(120);
			const imageDataUrl = onCaptureSceneScreenshot({
				autoFrame: true,
				framePadding: framePaddingFromShot(frame),
				viewDirection: viewDirectionFromShot(frame, index),
				frameObjectIds: frame.focus_objects?.slice(0, 3) ?? []
			});
			if (!imageDataUrl) continue;
			assets.push(makeFrameAsset(imageDataUrl, shotPlanLabel(frame, index)));
		}
		if (assets.length < 3) return;
		frameAssets = [...assets, ...frameAssets].slice(0, 12);
		videoShot = {
			start: assets[0],
			middle: assets[1],
			end: assets[2],
			clips: []
		};
	}

	function updateActiveVideoShot(patch: Partial<VideoShot>) {
		videoShot = { ...videoShot, ...patch };
	}

	type TimelineFrameKey = 'start' | 'middle' | 'end';

	function assignFrameAsset(frame: TimelineFrameKey, asset: FrameAsset) {
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
		return !videoShot.start || !videoShot.middle || !videoShot.end;
	}

	function addFrameAssetToTimeline(asset: FrameAsset) {
		if (videoBusy) return;
		if (!videoShot.start) {
			assignFrameAsset('start', asset);
			return;
		}
		if (!videoShot.middle) {
			assignFrameAsset('middle', asset);
			return;
		}
		if (!videoShot.end) {
			assignFrameAsset('end', asset);
			return;
		}
		errorLine = 'Clear a timeline frame before adding another.';
	}

	function clearTimelineFrame(frame: TimelineFrameKey) {
		errorLine = null;
		updateActiveVideoShot({ [frame]: undefined, clips: [] });
	}

	function timelineFrames(): Array<{ key: TimelineFrameKey; label: string; frame: ShotFrame }> {
		const frames: Array<{ key: TimelineFrameKey; label: string; frame?: ShotFrame }> = [
			{ key: 'start', label: 'Start', frame: videoShot.start },
			{ key: 'middle', label: 'Middle', frame: videoShot.middle },
			{ key: 'end', label: 'End', frame: videoShot.end }
		];
		return frames.filter(
			(item): item is { key: TimelineFrameKey; label: string; frame: ShotFrame } => !!item.frame
		);
	}

	function timelinePairs() {
		const frames = timelineFrames();
		if (selectedVideoSupportsEndFrame && frames.length >= 2) {
			return frames.slice(0, -1).map((frame, index) => ({
				label: `${frame.label} -> ${frames[index + 1].label}`,
				start: frame.frame,
				end: frames[index + 1].frame,
				prompt: timelinePairPrompt(index, index + 1, `${frame.label} to ${frames[index + 1].label}`)
			}));
		}
		return frames.length
			? [
					{
						label: frames.length >= 3 ? 'Start sequence' : frames[0].label,
						start: frames[0].frame,
						end: undefined,
						prompt: shotPlanPairPrompt(0, 1) || promptForVideo()
					}
				]
			: [];
	}

	function timelinePairsWithPrompts() {
		return timelinePairs().filter((pair) => pair.prompt?.trim());
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

	async function pollVideoClip(
		clipId: string,
		jobId: string,
		clips: GeneratedClip[],
		label: string
	) {
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
					status: `${label}: ready`,
					videoUrl,
					jobId: payload.jobId ?? jobId
				});
				updateActiveVideoShot({ clips: currentClips });
				return currentClips;
			}
			currentClips = replaceClip(currentClips, clipId, {
				status: `${label}: processing ${attempt}/60`,
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
		if (!promptForVideo() && shotPlanPairPrompts().length === 0) {
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
		const pairs = timelinePairs();
		if (pairs.length === 0) {
			errorLine = 'Capture a start frame first.';
			return;
		}
		let clips: GeneratedClip[] = [];
		updateActiveVideoShot({ clips: [] });
		for (let take = 1; take <= pairs.length; take += 1) {
			const pair = pairs[take - 1];
			const clipId =
				typeof crypto !== 'undefined' && 'randomUUID' in crypto
					? crypto.randomUUID()
					: `${Date.now()}-${take}`;
			const runningClip: GeneratedClip = {
				id: clipId,
				label: pair.label,
				status: `${pair.label}: running`
			};
			clips = [...clips, runningClip];
			updateActiveVideoShot({ clips });
			try {
				const formData = new FormData();
				formData.set('prompt', pair.prompt || promptForVideo());
				formData.set('liveObjText', liveObjText);
				formData.set('provider', providerSettings.provider);
				formData.set('apiKey', providerSettings.apiKey?.trim() || '');
				formData.set('videoModel', providerSettings.videoModel ?? '');
				formData.set('videoUrl', providerSettings.videoUrl?.trim() || '');
				formData.set('aspectRatio', await aspectRatioForVideo(pair.start.imageDataUrl));
				formData.set(
					'startFrame',
					await dataUrlToVideoFrameBlob(pair.start.imageDataUrl),
					'start-frame.jpg'
				);
				if (pair.end?.imageDataUrl) {
					formData.set(
						'endFrame',
						await dataUrlToVideoFrameBlob(pair.end.imageDataUrl),
						'end-frame.jpg'
					);
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
							? `${pair.label}: ready`
							: `${pair.label}: ${payload.status ?? 'pending'}`,
					videoUrl: payload.videoUrl || payload.videoDataUrl,
					jobId: payload.jobId
				});
				updateActiveVideoShot({ clips });
				if (!payload.videoUrl && !payload.videoDataUrl && payload.jobId) {
					clips = await pollVideoClip(clipId, payload.jobId, clips, pair.label);
				}
			} catch (e) {
				const failedClip: GeneratedClip = {
					id: clipId,
					label: pair.label,
					status: `${pair.label}: failed`,
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

	async function generateReel() {
		if (reelBusy) return;
		errorLine = null;
		reelVideoDataUrl = '';
		const readyClips = videoShot.clips.filter((clip) => !!clip.videoUrl);
		const timeline = timelineFrames();
		if (
			readyClips.length === 0 &&
			frameAssets.length === 0 &&
			timeline.length === 0 &&
			processImages.length === 0
		) {
			errorLine =
				'Generate reel needs a final clip, timeline frame, gallery frame, or process screenshot.';
			return;
		}
		reelBusy = true;
		try {
			const finalModelScreenshots = frameAssets.filter((asset) => asset.source === 'screenshot').slice(0, 8);
			const generatedTextureImages = textureGalleryImages();
			const buildProcessImages = processImages.filter((asset) => !isTextureGalleryImage(asset));
			const processImagePayload = await processImagePayloads(buildProcessImages);
			const textureImagePayload = await processImagePayloads(generatedTextureImages);
			const finalClips = (
				await Promise.all(
					readyClips.map(async (clip): Promise<ReelClipPayload | null> => {
						if (!clip.videoUrl) return null;
						return {
							label: clip.label ?? 'Animation clip',
							videoDataUrl: await mediaUrlToDataUrl(clip.videoUrl)
						};
					})
				)
			).filter((clip): clip is ReelClipPayload => !!clip?.videoDataUrl);
			const hasFinalClip = finalClips.length > 0;
			const response = await fetch('/api/render-reel', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					aspectRatio: reelAspectRatio,
					liveObjText,
					creativeDirectionJson: generatedDirectionJson,
					renderPrompt: prompt,
					videoPrompt: promptForVideo() || generatedAnimationPrompt(),
					finalClips,
					timelineFrames: [],
					galleryFrames: finalModelScreenshots.map((asset) => ({
						label: asset.label,
						imageDataUrl: asset.imageDataUrl
					})),
					textureImages: textureImagePayload,
					processImages: processImagePayload,
					agentMetrics,
					projectStructure: projectStructureEntries(hasFinalClip, timeline)
				})
			});
			const payload = (await response.json().catch(() => ({}))) as {
				message?: string;
				filename?: string;
				videoDataUrl?: string;
			};
			if (!response.ok || !payload.videoDataUrl) {
				throw new Error(payload.message || 'Reel generation failed');
			}
			reelVideoDataUrl = payload.videoDataUrl;
			reelFilename = payload.filename ?? 'spellshape-reel.mp4';
			downloadUrl(reelVideoDataUrl, reelFilename);
		} catch (e) {
			errorLine = e instanceof Error ? e.message : String(e);
		} finally {
			reelBusy = false;
		}
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
			await captureShotPlanFrames(directionJson);
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
		const renderSourceFrame = selectedRenderSourceFrame();
		const renderScreenshotDataUrl =
			renderSourceFrame?.imageDataUrl ?? captureScreenshotDataUrl(false);
		const renderCameraSnapshot =
			renderSourceFrame?.camera ?? onCaptureSceneCameraSnapshot?.() ?? null;
		if (renderSourceFrame) screenshotDataUrl = renderSourceFrame.imageDataUrl;
		if (!renderScreenshotDataUrl) return;
		busy = true;
		try {
			const response = await fetch('/api/render-image', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					prompt,
					screenshotDataUrl: renderScreenshotDataUrl,
					cameraSnapshot: renderCameraSnapshot,
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
				<div class="planner-video-note">
					Capture the current scene or generate a polished frame.
				</div>
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
		<div class="planner-render-source">
			<span>Source: {selectedRenderSourceFrame()?.label ?? 'Current view'}</span>
			{#if selectedRenderSourceFrame()}
				<button type="button" onclick={useCurrentViewForImage} disabled={busy || promptBusy}>
					Use current view
				</button>
			{/if}
		</div>
		<div class="planner-render-actions planner-action-row">
			<div class="planner-secondary-actions">
				<button
					type="button"
					class="send-button planner-render-secondary-button"
					onclick={generatePrompt}
					disabled={busy || promptBusy || !liveObjText.trim()}
				>
					{promptBusy ? 'Directing…' : 'Create direction'}
				</button>
				<button
					type="button"
					class="send-button planner-render-secondary-button"
					onclick={takeScreenshot}
					disabled={busy || promptBusy || videoBusy}>Take screenshot</button
				>
			</div>
			<button
				type="button"
				class="send-button planner-primary-action"
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
				{frameAssets.length
					? `${frameAssets.length} frame${frameAssets.length === 1 ? '' : 's'}`
					: 'Empty'}
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
								onclick={() => useFrameForImage(asset)}
								disabled={busy || promptBusy}
								aria-pressed={renderSourceFrameId === asset.id}>Use for image</button
							>
							<div
								class="planner-frame-slot-actions"
								aria-label={`Timeline slots for ${asset.label}`}
							>
								<button
									type="button"
									onclick={() => assignFrameAsset('start', asset)}
									disabled={videoBusy}>Start</button
								>
								<button
									type="button"
									onclick={() => assignFrameAsset('middle', asset)}
									disabled={videoBusy}>Middle</button
								>
								<button
									type="button"
									onclick={() => assignFrameAsset('end', asset)}
									disabled={videoBusy}>End</button
								>
							</div>
							<button
								type="button"
								class="planner-frame-add-button planner-frame-add-button--compact"
								onclick={() => addFrameAssetToTimeline(asset)}
								disabled={videoBusy || !hasTimelineSpace()}>Next slot</button
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
								onclick={() =>
									downloadImage(asset.imageDataUrl, asset.label.toLowerCase().replaceAll(' ', '-'))}
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
			<div class="planner-video-note">
				Take a screenshot or generate an image to add frames here.
			</div>
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
				<span>3 frames</span>
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
				<div class="planner-video-slot" class:filled={!!videoShot.middle}>
					<div class="planner-video-slot-head">
						<span>Middle</span>
						{#if videoShot.middle}
							<button
								type="button"
								onclick={() => clearTimelineFrame('middle')}
								disabled={videoBusy}>Clear</button
							>
						{/if}
					</div>
					{#if videoShot.middle}
						<img src={videoShot.middle.imageDataUrl} alt="Video middle frame" />
					{:else}
						<div class="planner-video-slot-empty">Add middle frame</div>
					{/if}
				</div>
				<div class="planner-video-slot" class:filled={!!videoShot.end}>
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
						<div class="planner-video-slot-empty">Add end frame</div>
					{/if}
				</div>
			</div>
			{#if videoShot.middle && !selectedVideoSupportsEndFrame}
				<div class="planner-video-note">
					This model can use the 3-frame timeline as a sequence board, but pair clips need an
					end-frame video model.
				</div>
			{/if}
			{#if timelinePairsWithPrompts().length}
				<div class="planner-segment-prompts" aria-label="Segment animation prompts">
					<div class="planner-render-subhead">
						<span>Segment prompts</span>
						<span>{timelinePairsWithPrompts().length} clips</span>
					</div>
					{#each timelinePairsWithPrompts() as pair}
						<div class="planner-segment-prompt">
							<span>{pair.label}</span>
							<p>{pair.prompt}</p>
						</div>
					{/each}
				</div>
			{/if}
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

		<div class="planner-video-actions planner-action-row planner-action-row--end">
			<button
				type="button"
				class="send-button planner-primary-action"
				onclick={generateVideoClips}
				disabled={busy ||
					promptBusy ||
					videoBusy ||
					(!promptForVideo() && shotPlanPairPrompts().length === 0) ||
					!videoShot.start?.imageDataUrl ||
					!videoProviderReady}
			>
				{videoBusy
					? 'Generating…'
					: selectedVideoSupportsEndFrame && timelinePairs().length > 1
						? 'Generate pair clips'
						: 'Generate clip'}
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

	<section class="planner-reel-card" aria-label="Project reel">
		<div class="planner-render-card-head">
			<div>
				<div class="planner-render-title">Project reel</div>
				<div class="planner-video-note">
					Export a HyperFrames making-of reel with animation, references, build steps, and agent
					effort.
				</div>
			</div>
			<span class="planner-video-provider-pill">HyperFrames</span>
		</div>
		<div class="planner-reel-controls planner-action-row">
			<label class="planner-context-field rendering-mode">
				<span class="planner-label-inline">Format</span>
				<select bind:value={reelAspectRatio} disabled={reelBusy}>
					<option value="9:16">9:16 Reel</option>
					<option value="16:9">16:9 Film</option>
				</select>
			</label>
			<button
				type="button"
				class="send-button planner-primary-action"
				onclick={generateReel}
				disabled={reelBusy ||
					videoBusy ||
					promptBusy ||
					(!videoShot.clips.some((clip) => !!clip.videoUrl) &&
						frameAssets.length === 0 &&
						processImages.length === 0)}
			>
				{reelBusy ? 'Rendering reel…' : 'Generate reel'}
			</button>
		</div>
		<div class="planner-video-note">
			Uses all ready pair clips first, then concept, references, process captures, agent effort, and
			package structure.
		</div>
		{#if reelVideoDataUrl}
			<div class="planner-video-clip planner-reel-preview">
				<div class="planner-video-clip-status">{reelFilename}</div>
				<!-- svelte-ignore a11y_media_has_caption -->
				<video src={reelVideoDataUrl} controls playsinline></video>
				<div class="planner-video-clip-actions">
					<button
						type="button"
						class="planner-monaco-action-btn"
						onclick={() => downloadUrl(reelVideoDataUrl, reelFilename)}
					>
						Download reel
					</button>
				</div>
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
	.planner-action-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 148px;
		gap: 8px;
		align-items: end;
	}
	.planner-action-row--end > .planner-primary-action {
		grid-column: 2;
	}
	.planner-secondary-actions {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		min-width: 0;
	}
	.planner-primary-action {
		box-sizing: border-box;
		width: 100%;
		min-height: 32px;
		justify-content: center;
		padding-inline: 10px;
		white-space: nowrap;
	}
	.planner-render-source {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: var(--spell-radius-sm);
		background: rgba(255, 255, 255, 0.46);
		padding: 7px 8px;
		font-size: 11px;
		font-weight: 700;
		color: #475569;
	}
	.planner-render-source button {
		border: 0;
		background: transparent;
		color: var(--spell-blue);
		font: inherit;
		font-size: 10px;
		font-weight: 800;
		cursor: pointer;
		padding: 0;
	}
	.planner-render-source button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
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
	.planner-reel-card {
		display: flex;
		flex-direction: column;
		gap: 9px;
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-md);
		background: var(--spell-surface-faint);
		padding: 12px;
	}
	.planner-reel-controls {
		margin-top: 1px;
	}
	.planner-reel-preview {
		margin-top: 2px;
	}
	.rendering-mode select {
		box-sizing: border-box;
		max-width: 140px;
		height: 32px;
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.12);
		border-radius: 999px;
		padding: 0 10px;
		background: rgba(255, 255, 255, 0.95);
		cursor: pointer;
	}
	.rendering-mode select:disabled {
		cursor: not-allowed;
		opacity: 0.58;
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
	.planner-segment-prompts {
		display: grid;
		gap: 6px;
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-sm);
		background: rgba(255, 255, 255, 0.46);
		padding: 8px;
	}
	.planner-segment-prompt {
		display: grid;
		gap: 3px;
		min-width: 0;
	}
	.planner-segment-prompt span {
		font-size: 10px;
		font-weight: 800;
		color: #475569;
	}
	.planner-segment-prompt p {
		margin: 0;
		font-size: 11px;
		line-height: 1.35;
		color: #64748b;
		overflow-wrap: anywhere;
	}
	.planner-video-timeline {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
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
		display: flex;
		align-items: stretch;
		flex-wrap: wrap;
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
		padding: 0 8px;
	}
	.planner-frame-add-button[aria-pressed='true'] {
		border-color: rgba(0, 0, 235, 0.5);
		background: rgba(0, 0, 235, 0.08);
		color: var(--spell-blue);
	}
	.planner-frame-add-button--compact {
		flex: 1 1 72px;
	}
	.planner-frame-slot-actions {
		flex: 1 1 100%;
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 4px;
	}
	.planner-frame-slot-actions button {
		border: 1px solid var(--spell-border);
		border-radius: var(--spell-radius-sm);
		background: rgba(255, 255, 255, 0.55);
		color: #475569;
		min-height: 24px;
		font: inherit;
		font-size: 10px;
		font-weight: 750;
		cursor: pointer;
		padding: 0 4px;
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
		margin-top: 1px;
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
	@media (max-width: 380px) {
		.planner-action-row {
			grid-template-columns: minmax(0, 1fr);
		}
		.planner-action-row--end > .planner-primary-action {
			grid-column: auto;
		}
	}
</style>
