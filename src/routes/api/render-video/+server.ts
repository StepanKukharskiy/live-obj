import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

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

function metadataFromLiveObj(liveObjText: string): string {
	return liveObjText
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter((line) => line.startsWith('#@'))
		.join('\n');
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

function dataUrlToInlineImage(dataUrl: string): { mimeType: string; data: string } {
	const match = dataUrl.match(/^data:(.+?);base64,(.+)$/);
	if (!match) throw error(400, 'Invalid image data URL');
	return { mimeType: match[1], data: match[2] };
}

function googleImagePayload(image: { mimeType: string; data: string }) {
	return {
		mimeType: image.mimeType,
		bytesBase64Encoded: image.data
	};
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

async function openRouterModelSupportsEndFrame(
	videoUrl: string | undefined,
	apiKey: string,
	model: string
): Promise<boolean> {
	const modelsUrl = new URL('./models', bodyVideoUrlBase(videoUrl)).toString();
	try {
		const response = await fetch(modelsUrl, {
			headers: {
				...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
				'X-OpenRouter-Title': 'Spellshape'
			}
		});
		if (!response.ok) return knownModelSupportsEndFrame('openrouter', model);
		const payload = (await response.json().catch(() => ({}))) as {
			data?: Array<{ id?: string; supported_frame_images?: string[] }>;
		};
		const match = payload.data?.find((entry) => entry.id === model);
		if (!match) return knownModelSupportsEndFrame('openrouter', model);
		return match.supported_frame_images?.includes('last_frame') ?? false;
	} catch {
		return knownModelSupportsEndFrame('openrouter', model);
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

export const POST: RequestHandler = async ({ request }) => {
	let body: RenderVideoBody;
	try {
		body = (await request.json()) as RenderVideoBody;
	} catch {
		throw error(400, 'Invalid JSON');
	}

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
	const durationSeconds = Math.max(1, Math.min(10, Math.round(body.durationSeconds ?? 5)));
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
	if (!startFrameDataUrl) throw error(400, 'startFrameDataUrl is required');
	assertImageDataUrl(startFrameDataUrl, 'startFrameDataUrl');
	if (requestedEndFrameDataUrl) assertImageDataUrl(requestedEndFrameDataUrl, 'endFrameDataUrl');
	const supportsEndFrame =
		provider === 'openrouter'
			? await openRouterModelSupportsEndFrame(body.videoUrl, apiKey, videoModel)
			: knownModelSupportsEndFrame(provider, videoModel);
	const endFrameDataUrl = supportsEndFrame ? requestedEndFrameDataUrl : '';

	const sceneMetadata = metadataFromLiveObj(body.liveObjText ?? '');
	const fullPrompt = `${prompt}

Preserve the scene layout, object count, relative positions, silhouette, and camera intent from the supplied frame image${endFrameDataUrl ? 's' : ''}. Use hard continuity over invention.

Live OBJ metadata:
${sceneMetadata || '(no #@ metadata found)'}`;

	if (provider === 'google') {
		const firstImage = dataUrlToInlineImage(startFrameDataUrl);
		const lastImage = endFrameDataUrl ? dataUrlToInlineImage(endFrameDataUrl) : undefined;
		const googleDuration = lastImage ? 8 : 4;
		const submitUrl = googleSubmitUrl(body.videoUrl, videoModel);
		const baseUrl = googleBaseUrl(body.videoUrl);
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

		const completed = await pollGoogleOperation(submitted, apiKey, baseUrl);
		const videoUri =
			completed.response?.generateVideoResponse?.generatedSamples?.[0]?.video?.uri ??
			completed.response?.generatedVideos?.[0]?.video?.uri ??
			'';
		const videoDataUrl = videoUri ? await fetchGoogleVideoDataUrl(videoUri, apiKey) : '';

		return json({
			status: completed.done ? 'completed' : 'pending',
			jobId: completed.name ?? submitted.name,
			videoUrl: '',
			videoDataUrl
		});
	}

	const frameImages = [
		{
			type: 'image_url',
			image_url: { url: startFrameDataUrl },
			frame_type: 'first_frame'
		},
		...(endFrameDataUrl
			? [
					{
						type: 'image_url',
						image_url: { url: endFrameDataUrl },
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
				duration: durationSeconds,
				resolution: '720p',
				aspect_ratio: aspectRatio,
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

	const completed = await pollOpenRouterJob(submitted, apiKey);
	const unsignedUrl = completed.unsigned_urls?.[0] ?? '';
	const contentUrl =
		completed.status === 'completed' && completed.id
			? `${DEFAULT_OPENROUTER_VIDEO_URL}/${completed.id}/content?index=0`
			: '';
	const videoDataUrl = !unsignedUrl && contentUrl ? await fetchVideoDataUrl(contentUrl, apiKey) : '';

	return json({
		status: completed.status ?? submitted.status ?? 'pending',
		jobId: completed.id ?? submitted.id,
		generationId: completed.generation_id ?? submitted.generation_id,
		pollingUrl: completed.polling_url ?? submitted.polling_url,
		videoUrl: unsignedUrl ? normalizeOpenRouterUrl(unsignedUrl) : '',
		videoDataUrl
	});
};
