import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { storeVideoFrame } from '$lib/server/videoFrameStore';

const DEFAULT_OPENROUTER_VIDEO_URL = 'https://openrouter.ai/api/v1/videos';
const DEFAULT_GOOGLE_VIDEO_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta';
const VIDEO_POLL_INTERVAL_MS = 12_000;
const VIDEO_POLL_ATTEMPTS = 12;
const MAX_INLINE_VIDEO_BYTES = 40 * 1024 * 1024;
const GOOGLE_VIDEO_MODEL_ALIASES: Record<string, string> = {
	'veo-3.1-lite-generate-001': 'veo-3.1-lite-generate-preview'
};
const GOOGLE_IMAGE_VIDEO_MODELS = new Set([
	'veo-3.1-generate-preview',
	'veo-3.1-fast-generate-preview'
]);

type VideoJob = {
	id?: string;
	polling_url?: string;
	status?: string;
	error?: string;
	unsigned_urls?: string[];
	generation_id?: string;
};

type GoogleOperation = {
	name?: string;
	done?: boolean;
	error?: { message?: string };
	response?: {
		generateVideoResponse?: {
			generatedSamples?: Array<{ video?: { uri?: string; mimeType?: string } }>;
		};
		generatedVideos?: Array<{ video?: { uri?: string; mimeType?: string } }>;
	};
};

type OpenRouterVideoModel = {
	id?: string;
	canonical_slug?: string;
	supported_durations?: number[] | null;
	supported_frame_images?: string[] | null;
	supported_aspect_ratios?: string[] | null;
	supported_resolutions?: string[] | null;
	supported_sizes?: string[] | null;
};

type OpenRouterVideoCapabilities = {
	supportsFirstFrame: boolean;
	supportsLastFrame: boolean;
	supportedDurations?: number[];
	supportedAspectRatios?: string[];
	supportedSizes?: string[];
	aspectRatio?: string;
	resolution?: string;
	size?: string;
};

type RenderVideoBody = {
	prompt?: string;
	liveObjText?: string;
	provider?: string;
	apiKey?: string;
	videoUrl?: string;
	videoModel?: string;
	startFrameDataUrl?: string;
	endFrameDataUrl?: string;
	durationSeconds?: number;
	aspectRatio?: string;
};
type InlineImage = { mimeType: string; data: string };
type ParsedRenderVideoBody = RenderVideoBody & {
	startFrameImage?: InlineImage;
	endFrameImage?: InlineImage;
};
type FormFileLike = {
	size: number;
	type?: string;
	arrayBuffer: () => Promise<ArrayBuffer>;
};

const MAX_SCENE_METADATA_CHARS = 12_000;

function metadataFromLiveObj(liveObjText: string): string {
	const metadata = liveObjText
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter((line) => line.startsWith('#@'))
		.filter((line) => !/^#@dream_(?:base|delta)_v\b/i.test(line))
		.join('\n');
	if (metadata.length <= MAX_SCENE_METADATA_CHARS) return metadata;
	return `${metadata.slice(0, MAX_SCENE_METADATA_CHARS)}\n#@note: scene metadata truncated for video prompt`;
}

function networkErrorMessage(err: unknown): string {
	if (err instanceof Error) return err.message;
	return String(err);
}

function wait(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeOpenRouterUrl(url: string): string {
	return new URL(url, 'https://openrouter.ai').toString();
}

function dataUrlToInlineImage(dataUrl: string): InlineImage {
	const match = dataUrl.match(/^data:(.+?);base64,(.+)$/);
	if (!match) throw error(400, 'Invalid image data URL');
	return { mimeType: match[1], data: match[2] };
}

function cleanProviderField(value: string | undefined): string | undefined {
	const cleaned = value?.replace(/[^\t\x20-\xff]/g, '').trim();
	return cleaned || undefined;
}

function isFormFileLike(value: FormDataEntryValue | null): value is FormDataEntryValue & FormFileLike {
	return (
		typeof value === 'object' &&
		value !== null &&
		typeof (value as Partial<FormFileLike>).size === 'number' &&
		typeof (value as FormFileLike).arrayBuffer === 'function'
	);
}

async function blobToInlineImage(
	value: FormDataEntryValue | null,
	label: string
): Promise<InlineImage | undefined> {
	if (!isFormFileLike(value) || !value.size) return undefined;
	const mimeType = value.type || 'image/png';
	if (!mimeType.startsWith('image/')) throw error(400, `${label} must be an image file`);
	const arrayBuffer = await value.arrayBuffer();
	return { mimeType, data: Buffer.from(arrayBuffer).toString('base64') };
}

function formString(form: FormData, key: string): string | undefined {
	const value = form.get(key);
	return typeof value === 'string' ? value : undefined;
}

async function parseRenderVideoRequest(request: Request): Promise<ParsedRenderVideoBody> {
	const contentType = request.headers.get('content-type') ?? '';
	if (contentType.includes('multipart/form-data')) {
		let form: FormData;
		try {
			form = await request.formData();
		} catch (err) {
			throw error(400, `Invalid multipart form data: ${networkErrorMessage(err)}`);
		}
		return {
			prompt: formString(form, 'prompt'),
			liveObjText: formString(form, 'liveObjText'),
			provider: formString(form, 'provider'),
			apiKey: cleanProviderField(formString(form, 'apiKey')),
			videoUrl: cleanProviderField(formString(form, 'videoUrl')),
			videoModel: cleanProviderField(formString(form, 'videoModel')),
			aspectRatio: formString(form, 'aspectRatio'),
			startFrameImage: await blobToInlineImage(form.get('startFrame'), 'startFrame'),
			endFrameImage: await blobToInlineImage(form.get('endFrame'), 'endFrame')
		};
	}
	try {
		return (await request.json()) as RenderVideoBody;
	} catch {
		throw error(400, 'Invalid JSON');
	}
}

function googleImagePayload(image: { mimeType: string; data: string }) {
	return {
		mimeType: image.mimeType,
		bytesBase64Encoded: image.data
	};
}

function publicVideoFrameUrl(requestUrl: URL, image: InlineImage): string {
	const id = storeVideoFrame(Buffer.from(image.data, 'base64'), image.mimeType);
	return new URL(`/api/render-video/frame/${id}`, requestUrl).toString();
}

function assertPublicHttpsOrigin(requestUrl: URL) {
	const hostname = requestUrl.hostname.toLowerCase();
	const isLocalhost = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
	const isPrivateIp =
		/^10\./.test(hostname) ||
		/^192\.168\./.test(hostname) ||
		/^172\.(1[6-9]|2\d|3[0-1])\./.test(hostname);
	if (requestUrl.protocol !== 'https:' || isLocalhost || isPrivateIp) {
		throw error(
			400,
			'OpenRouter frame video needs public HTTPS frame URLs. Test OpenRouter video from the deployed app or a public HTTPS tunnel; use Google for localhost.'
		);
	}
}

function normalizeGoogleVideoModel(model: string): string {
	return GOOGLE_VIDEO_MODEL_ALIASES[model] ?? model;
}

function googleBaseUrl(videoUrl?: string): string {
	const trimmed = videoUrl?.trim() || DEFAULT_GOOGLE_VIDEO_BASE_URL;
	if (trimmed.includes(':predictLongRunning')) {
		return trimmed.replace(/\/models\/[^/]+:predictLongRunning.*$/, '');
	}
	return trimmed.replace(/\/$/, '');
}

function googleSubmitUrl(videoUrl: string | undefined, model: string): string {
	const trimmed = videoUrl?.trim() || '';
	if (trimmed.includes(':predictLongRunning')) {
		return trimmed.replace(
			/\/models\/[^/]+:predictLongRunning/,
			`/models/${encodeURIComponent(model)}:predictLongRunning`
		);
	}
	return `${googleBaseUrl(videoUrl)}/models/${encodeURIComponent(model)}:predictLongRunning`;
}

async function fetchVideoDataUrl(url: string, apiKey: string): Promise<string> {
	const response = await fetch(normalizeOpenRouterUrl(url), {
		headers: { Authorization: `Bearer ${apiKey}` }
	});
	if (!response.ok) {
		throw error(response.status, 'Video completed, but content download failed');
	}
	const arrayBuffer = await response.arrayBuffer();
	if (arrayBuffer.byteLength > MAX_INLINE_VIDEO_BYTES) {
		throw error(502, 'Video completed, but the clip is too large to inline for preview');
	}
	const mimeType = response.headers.get('content-type') || 'video/mp4';
	return `data:${mimeType};base64,${Buffer.from(arrayBuffer).toString('base64')}`;
}

async function fetchGoogleVideoDataUrl(url: string, apiKey: string): Promise<string> {
	const response = await fetch(url, {
		headers: { 'x-goog-api-key': apiKey }
	});
	if (!response.ok) {
		throw error(response.status, 'Video completed, but content download failed');
	}
	const arrayBuffer = await response.arrayBuffer();
	if (arrayBuffer.byteLength > MAX_INLINE_VIDEO_BYTES) {
		throw error(502, 'Video completed, but the clip is too large to inline for preview');
	}
	const mimeType = response.headers.get('content-type') || 'video/mp4';
	return `data:${mimeType};base64,${Buffer.from(arrayBuffer).toString('base64')}`;
}

function assertImageDataUrl(value: string, label: string) {
	if (!value.startsWith('data:image/')) {
		throw error(400, `${label} must be an image data URL`);
	}
}

function knownModelSupportsEndFrame(provider: string, model: string): boolean {
	const normalizedProvider = provider.trim().toLowerCase();
	const normalizedModel = model.trim().toLowerCase();
	if (!normalizedModel) return false;
	if (normalizedProvider === 'google') return normalizedModel.startsWith('veo-3.1');
	if (normalizedProvider === 'openrouter') {
		return (
			normalizedModel.includes('veo-3.1') ||
			normalizedModel.includes('wan') ||
			normalizedModel.includes('seedance')
		);
	}
	return false;
}

function openRouterFallbackCapabilities(model: string, requestedAspectRatio: string): OpenRouterVideoCapabilities {
	const supportsLastFrame = knownModelSupportsEndFrame('openrouter', model);
	const supportedDurations = model.trim().toLowerCase().includes('veo-3.1') ? [4, 6, 8] : [5, 8];
	return {
		supportsFirstFrame: true,
		supportsLastFrame,
		supportedDurations,
		supportedAspectRatios: undefined,
		supportedSizes: undefined,
		aspectRatio: requestedAspectRatio,
		resolution: '720p'
	};
}

function chooseOpenRouterDuration(supportedDurations: number[] | null | undefined, hasEndFrame: boolean): number {
	const durations = [...(supportedDurations ?? [])]
		.filter((duration) => Number.isFinite(duration) && duration > 0)
		.sort((a, b) => a - b);
	if (!durations.length) return hasEndFrame ? 8 : 5;
	if (hasEndFrame) return durations.find((duration) => duration >= 8) ?? durations.at(-1) ?? 8;
	return (
		durations.find((duration) => duration === 5) ??
		durations.find((duration) => duration === 4) ??
		durations[0]
	);
}

function chooseOpenRouterAspectRatio(
	supportedAspectRatios: string[] | null | undefined,
	requestedAspectRatio: string
): string | undefined {
	if (!supportedAspectRatios?.length) return requestedAspectRatio;
	if (supportedAspectRatios.includes(requestedAspectRatio)) return requestedAspectRatio;
	return undefined;
}

function chooseOpenRouterResolution(
	supportedResolutions: string[] | null | undefined
): string | undefined {
	if (!supportedResolutions?.length) return '720p';
	if (supportedResolutions.includes('720p')) return '720p';
	return supportedResolutions[0];
}

function ratioFromAspectRatio(aspectRatio: string): number | null {
	const [width, height] = aspectRatio.split(':').map((part) => Number(part));
	if (!Number.isFinite(width) || !Number.isFinite(height) || height <= 0) return null;
	return width / height;
}

function ratioFromSize(size: string): number | null {
	const match = size.match(/(\d+)\s*x\s*(\d+)/i);
	if (!match) return null;
	const width = Number(match[1]);
	const height = Number(match[2]);
	if (!Number.isFinite(width) || !Number.isFinite(height) || height <= 0) return null;
	return width / height;
}

function chooseOpenRouterSize(
	supportedSizes: string[] | null | undefined,
	requestedAspectRatio: string
): string | undefined {
	if (!supportedSizes?.length) return undefined;
	const targetRatio = ratioFromAspectRatio(requestedAspectRatio);
	if (!targetRatio) return undefined;
	return supportedSizes.find((size) => {
		const sizeRatio = ratioFromSize(size);
		return sizeRatio ? Math.abs(Math.log(sizeRatio / targetRatio)) < 0.04 : false;
	});
}

async function openRouterVideoCapabilities(
	videoUrl: string | undefined,
	apiKey: string,
	model: string,
	requestedAspectRatio: string
): Promise<OpenRouterVideoCapabilities> {
	const modelsUrl = new URL('./models', bodyVideoUrlBase(videoUrl)).toString();
	try {
		const response = await fetch(modelsUrl, {
			headers: {
				...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
				'X-OpenRouter-Title': 'Spellshape'
			}
		});
		if (!response.ok) return openRouterFallbackCapabilities(model, requestedAspectRatio);
		const payload = (await response.json().catch(() => ({}))) as {
			data?: OpenRouterVideoModel[];
		};
		const match = payload.data?.find((entry) => entry.id === model || entry.canonical_slug === model);
		if (!match) return openRouterFallbackCapabilities(model, requestedAspectRatio);
		const supportedFrames = match.supported_frame_images;
		const supportsLastFrame = supportedFrames?.includes('last_frame') ?? false;
		return {
			supportsFirstFrame: !supportedFrames || supportedFrames.includes('first_frame'),
			supportsLastFrame,
			supportedDurations: match.supported_durations ?? undefined,
			supportedAspectRatios: match.supported_aspect_ratios ?? undefined,
			supportedSizes: match.supported_sizes ?? undefined,
			aspectRatio: chooseOpenRouterAspectRatio(match.supported_aspect_ratios, requestedAspectRatio),
			resolution: chooseOpenRouterResolution(match.supported_resolutions),
			size: chooseOpenRouterSize(match.supported_sizes, requestedAspectRatio)
		};
	} catch {
		return openRouterFallbackCapabilities(model, requestedAspectRatio);
	}
}

function bodyVideoUrlBase(videoUrl?: string): string {
	const url = videoUrl?.trim() || DEFAULT_OPENROUTER_VIDEO_URL;
	return url.endsWith('/') ? url : `${url}/`;
}

async function pollOpenRouterJob(job: VideoJob, apiKey: string): Promise<VideoJob> {
	let current = job;
	for (let attempt = 0; attempt < VIDEO_POLL_ATTEMPTS; attempt += 1) {
		if (current.status === 'completed') return current;
		if (['failed', 'cancelled', 'expired'].includes(current.status ?? '')) {
			throw error(502, current.error || `Video generation ${current.status}`);
		}
		if (!current.polling_url) break;
		await wait(VIDEO_POLL_INTERVAL_MS);
		const response = await fetch(normalizeOpenRouterUrl(current.polling_url), {
			headers: { Authorization: `Bearer ${apiKey}` }
		});
		const payload = (await response.json().catch(() => ({}))) as VideoJob;
		if (!response.ok) {
			throw error(response.status, payload.error || 'Video polling failed');
		}
		current = payload;
	}
	return current;
}

async function pollGoogleOperation(
	operation: GoogleOperation,
	apiKey: string,
	baseUrl: string
): Promise<GoogleOperation> {
	let current = operation;
	for (let attempt = 0; attempt < VIDEO_POLL_ATTEMPTS; attempt += 1) {
		if (current.done) return current;
		if (current.error?.message) throw error(502, current.error.message);
		if (!current.name) break;
		await wait(VIDEO_POLL_INTERVAL_MS);
		const response = await fetch(`${baseUrl}/${current.name}`, {
			headers: { 'x-goog-api-key': apiKey }
		});
		const payload = (await response.json().catch(() => ({}))) as GoogleOperation;
		if (!response.ok) {
			throw error(response.status, payload.error?.message || 'Video polling failed');
		}
		current = payload;
	}
	return current;
}

async function submitGoogleVideo(
	submitUrl: string,
	apiKey: string,
	payload: Record<string, unknown>
): Promise<{ response: Response; body: GoogleOperation }> {
	let response: Response;
	try {
		response = await fetch(submitUrl, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				'x-goog-api-key': apiKey
			},
			body: JSON.stringify(payload)
		});
	} catch (err) {
		throw error(502, `Unable to reach video provider: ${networkErrorMessage(err)}`);
	}
	return { response, body: (await response.json().catch(() => ({}))) as GoogleOperation };
}

export const POST: RequestHandler = async ({ request, url }) => {
	const body = await parseRenderVideoRequest(request);

	const provider = body.provider?.trim().toLowerCase() ?? '';
	if (provider !== 'openrouter' && provider !== 'google') {
		throw error(400, 'Video generation currently supports OpenRouter and Google.');
	}

	const prompt = body.prompt?.trim() ?? '';
	const apiKey = body.apiKey?.trim() ?? '';
	const requestedVideoModel = body.videoModel?.trim() ?? '';
	const videoModel = provider === 'google' ? normalizeGoogleVideoModel(requestedVideoModel) : requestedVideoModel;
	const startFrameDataUrl = body.startFrameDataUrl?.trim() ?? '';
	const requestedEndFrameDataUrl = body.endFrameDataUrl?.trim() ?? '';
	const aspectRatio = body.aspectRatio?.trim() || '16:9';

	if (!apiKey) throw error(500, 'API key is required');
	if (!videoModel) throw error(400, 'videoModel is required');
	if (provider === 'google' && !GOOGLE_IMAGE_VIDEO_MODELS.has(videoModel)) {
		throw error(
			400,
			'Google video with gallery frames requires a Veo image-to-video model. Choose veo-3.1-generate-preview or veo-3.1-fast-generate-preview.'
		);
	}
	if (!prompt) throw error(400, 'prompt is required');
	if (!startFrameDataUrl && !body.startFrameImage) throw error(400, 'startFrame is required');
	if (startFrameDataUrl) assertImageDataUrl(startFrameDataUrl, 'startFrameDataUrl');
	if (requestedEndFrameDataUrl) assertImageDataUrl(requestedEndFrameDataUrl, 'endFrameDataUrl');
	const openRouterCapabilities =
		provider === 'openrouter'
			? await openRouterVideoCapabilities(body.videoUrl, apiKey, videoModel, aspectRatio)
			: null;
	const supportsEndFrame =
		openRouterCapabilities?.supportsLastFrame ?? knownModelSupportsEndFrame(provider, videoModel);
	if (provider === 'openrouter' && !openRouterCapabilities?.supportsFirstFrame) {
		throw error(400, `${videoModel} does not support first-frame video input.`);
	}
	if (
		provider === 'openrouter' &&
		openRouterCapabilities?.supportedAspectRatios?.length &&
		!openRouterCapabilities.supportedAspectRatios.includes(aspectRatio)
	) {
		throw error(
			400,
			`${videoModel} does not support ${aspectRatio} video. Supported aspect ratios: ${openRouterCapabilities.supportedAspectRatios.join(', ')}.`
		);
	}
	if (
		provider === 'openrouter' &&
		openRouterCapabilities?.supportedSizes?.length &&
		!openRouterCapabilities.supportedAspectRatios?.length &&
		!openRouterCapabilities.size
	) {
		throw error(
			400,
			`${videoModel} does not support ${aspectRatio} video. Supported sizes: ${openRouterCapabilities.supportedSizes.join(', ')}.`
		);
	}
	const startFrameImage = body.startFrameImage ?? dataUrlToInlineImage(startFrameDataUrl);
	const endFrameImage =
		supportsEndFrame && (body.endFrameImage || requestedEndFrameDataUrl)
			? (body.endFrameImage ?? dataUrlToInlineImage(requestedEndFrameDataUrl))
			: undefined;

	const sceneMetadata = metadataFromLiveObj(body.liveObjText ?? '');
	const fullPrompt = `${prompt}

Preserve the scene layout, object count, relative positions, silhouette, and camera intent from the supplied frame image${endFrameImage ? 's' : ''}. Use hard continuity over invention.

Live OBJ metadata:
${sceneMetadata || '(no #@ metadata found)'}`;

	if (provider === 'google') {
		const firstImage = startFrameImage;
		const lastImage = endFrameImage;
		const googleDuration = lastImage ? 8 : 4;
		const submitUrl = googleSubmitUrl(undefined, videoModel);
		const buildPayload = () => ({
			instances: [
				{
					prompt: fullPrompt,
					image: googleImagePayload(firstImage),
					...(lastImage
						? {
								lastFrame: googleImagePayload(lastImage)
							}
						: {})
				}
			],
			parameters: {
				sampleCount: 1,
				durationSeconds: googleDuration,
				aspectRatio,
				resolution: '720p',
				personGeneration: 'allow_adult'
			}
		});

		let { response: submitResponse, body: submitted } = await submitGoogleVideo(
			submitUrl,
			apiKey,
			buildPayload()
		);
		if (!submitResponse.ok) {
			console.warn('Google video generation failed', {
				status: submitResponse.status,
				model: videoModel,
				message: submitted.error?.message
			});
			throw error(
				submitResponse.status,
				submitted.error?.message
					? `${submitted.error.message} Model: ${videoModel}.`
					: 'Video generation failed'
			);
		}

		return json({
			status: 'pending',
			jobId: submitted.name,
			videoUrl: '',
			videoDataUrl: ''
		});
	}

	if (provider === 'openrouter') {
		assertPublicHttpsOrigin(url);
		const firstFrameUrl = publicVideoFrameUrl(url, startFrameImage);
		const lastFrameUrl = endFrameImage ? publicVideoFrameUrl(url, endFrameImage) : '';
		const openRouterDuration = chooseOpenRouterDuration(
			openRouterCapabilities?.supportedDurations,
			!!lastFrameUrl
		);
		const frameImages = [
			{
				type: 'image_url',
				image_url: { url: firstFrameUrl },
				frame_type: 'first_frame'
			},
			...(lastFrameUrl
				? [
						{
							type: 'image_url',
							image_url: { url: lastFrameUrl },
							frame_type: 'last_frame'
						}
					]
				: [])
		];

		let submitResponse: Response;
		try {
			submitResponse = await fetch(body.videoUrl?.trim() || DEFAULT_OPENROUTER_VIDEO_URL, {
				method: 'POST',
				headers: {
					Authorization: `Bearer ${apiKey}`,
					'Content-Type': 'application/json',
					'X-OpenRouter-Title': 'Spellshape'
				},
				body: JSON.stringify({
					model: videoModel,
					prompt: fullPrompt,
					duration: openRouterDuration,
					...(openRouterCapabilities?.size
						? { size: openRouterCapabilities.size }
						: {
								resolution: openRouterCapabilities?.resolution ?? '720p',
								aspect_ratio: openRouterCapabilities?.aspectRatio ?? aspectRatio
							}),
					generate_audio: false,
					frame_images: frameImages
				})
			});
		} catch (err) {
			throw error(502, `Unable to reach video provider: ${networkErrorMessage(err)}`);
		}

		const submitted = (await submitResponse.json().catch(() => ({}))) as VideoJob;
		if (!submitResponse.ok) {
			throw error(submitResponse.status, submitted.error || 'Video generation failed');
		}

		const unsignedUrl = submitted.unsigned_urls?.[0] ?? '';
		return json({
			status: submitted.status ?? 'pending',
			jobId: submitted.id,
			generationId: submitted.generation_id,
			pollingUrl: submitted.polling_url,
			videoUrl: unsignedUrl ? normalizeOpenRouterUrl(unsignedUrl) : '',
			videoDataUrl: ''
		});
	}

	throw error(400, 'Video generation currently supports OpenRouter and Google.');
};
