import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const DEFAULT_OPENAI_IMAGES_API_URL = 'https://api.openai.com/v1/images/edits';
const OPENAI_IMAGE_MODEL = 'gpt-image-1.5';
const OPENAI_IMAGES_TIMEOUT_MS = 90_000;

function pickString(...candidates: Array<string | undefined>): string {
	for (const c of candidates) {
		if (c != null && String(c).trim() !== '') return String(c).trim();
	}
	return '';
}

function metadataFromLiveObj(liveObjText: string): string {
	return liveObjText
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter((line) => line.startsWith('#@'))
		.join('\n');
}

function dataUrlToBlob(dataUrl: string): Blob {
	const m = dataUrl.match(/^data:(.+?);base64,(.+)$/);
	if (!m) {
		throw new Error('Invalid data URL payload');
	}
	const mime = m[1];
	const bytes = Buffer.from(m[2], 'base64');
	return new Blob([bytes], { type: mime });
}

function dataUrlToBase64Payload(dataUrl: string): string {
	const m = dataUrl.match(/^data:.+;base64,(.+)$/);
	if (!m) throw new Error('Invalid data URL payload');
	return m[1];
}

async function urlToDataUrl(url: string): Promise<string> {
	const proxyRes = await fetch(url);
	if (!proxyRes.ok) throw new Error(`Image proxy fetch failed: ${proxyRes.status}`);
	const mimeType = proxyRes.headers.get('content-type') || 'image/png';
	const arrayBuffer = await proxyRes.arrayBuffer();
	return `data:${mimeType};base64,${Buffer.from(arrayBuffer).toString('base64')}`;
}

function networkErrorMessage(err: unknown): string {
	if (err instanceof Error) return err.message;
	return String(err);
}

function deriveImagesApiUrl(
	explicitImagesApiUrl: string,
	fallbackApiUrl: string
): string {
	if (explicitImagesApiUrl) return explicitImagesApiUrl;
	if (!fallbackApiUrl) return DEFAULT_OPENAI_IMAGES_API_URL;
	return fallbackApiUrl.replace(
		/(\/v1\/(?:chat\/completions|responses))\/?$/i,
		'/v1/images/edits'
	);
}

export const POST: RequestHandler = async ({ request }) => {
	let body: { prompt?: string; screenshotDataUrl?: string; liveObjText?: string; apiKey?: string; apiUrl?: string; imageModel?: string };
	try {
		body = (await request.json()) as { prompt?: string; screenshotDataUrl?: string; liveObjText?: string; apiKey?: string; apiUrl?: string; imageModel?: string };
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const prompt = body.prompt?.trim() ?? '';
	const screenshotDataUrl = body.screenshotDataUrl?.trim() ?? '';
	const liveObjText = body.liveObjText ?? '';

	if (!prompt) throw error(400, 'prompt is required');
	if (!screenshotDataUrl.startsWith('data:image/')) throw error(400, 'screenshotDataUrl must be an image data URL');

	const { env } = await import('$env/dynamic/private');
	const requestApiKey = body.apiKey?.trim() ?? '';
	const requestApiUrl = body.apiUrl?.trim() ?? '';
	const imageModel = body.imageModel?.trim() || OPENAI_IMAGE_MODEL;
	const apiKey = pickString(requestApiKey, process.env.OPENAI_API_KEY, env.OPENAI_API_KEY, process.env.DEFAULT_OPENAI_API_KEY, env.DEFAULT_OPENAI_API_KEY);
	const imagesApiUrl = deriveImagesApiUrl(
		pickString(process.env.OPENAI_IMAGES_API_URL, env.OPENAI_IMAGES_API_URL),
		pickString(requestApiUrl, process.env.OPENAI_API_URL, env.OPENAI_API_URL)
	);
	if (!apiKey) throw error(500, 'OPENAI_API_KEY is not configured');

	const sceneMetadata = metadataFromLiveObj(liveObjText);
	const fullPrompt = `${prompt}\n\nUse this scene metadata as a hard constraint for objects, materials, and structure:\n${sceneMetadata || '(no #@ metadata found)'}`;

	const form = new FormData();
	form.append('model', imageModel);
	form.append('prompt', fullPrompt);
	form.append('image', dataUrlToBlob(screenshotDataUrl), 'scene-screenshot.jpg');

	const abortController = new AbortController();
	const timeout = setTimeout(() => abortController.abort(), OPENAI_IMAGES_TIMEOUT_MS);
	let response: Response;
	try {
		response = await fetch(imagesApiUrl, {
			method: 'POST',
			headers: {
				Authorization: `Bearer ${apiKey}`
			},
			body: form,
			signal: abortController.signal
		});
	} catch (err) {
		const message =
			err instanceof Error && err.name === 'AbortError'
				? `Image provider request timed out after ${Math.round(OPENAI_IMAGES_TIMEOUT_MS / 1000)}s`
				: `Unable to reach image provider (${imagesApiUrl}): ${networkErrorMessage(err)}`;
		throw error(502, message);
	} finally {
		clearTimeout(timeout);
	}

	const initialPayload = (await response.json().catch(() => ({}))) as {
		error?: { message?: string };
		detail?: unknown;
		data?: Array<{ b64_json?: string; url?: string }>;
	};

	const providerMessage = initialPayload.error?.message ?? JSON.stringify(initialPayload.detail ?? '');

	// Some OpenAI-compatible providers validate as JSON-only and reject multipart with:
	// [{'type': 'dict_type', 'loc': ('body',), 'msg': 'Input should be a valid dictionary'}]
	// Retry with JSON body in that case.
	const shouldRetryAsJson =
		!response.ok &&
		(response.status === 400 || response.status === 422) &&
		providerMessage.includes('dict_type');

	if (shouldRetryAsJson) {
		try {
			response = await fetch(imagesApiUrl, {
				method: 'POST',
				headers: {
					Authorization: `Bearer ${apiKey}`,
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({
					model: imageModel,
					prompt: fullPrompt,
					image: dataUrlToBase64Payload(screenshotDataUrl)
				})
			});
		} catch (err) {
			throw error(502, `Unable to reach image provider (${imagesApiUrl}) on JSON fallback: ${networkErrorMessage(err)}`);
		}
	}

	let finalPayload = initialPayload;
	if (shouldRetryAsJson) {
		finalPayload = (await response.json().catch(() => ({}))) as {
			error?: { message?: string };
			detail?: unknown;
			data?: Array<{ b64_json?: string; url?: string }>;
		};
	}

	if (!response.ok) {
		const message =
			finalPayload.error?.message ??
			(typeof finalPayload.detail === 'string' ? finalPayload.detail : JSON.stringify(finalPayload.detail ?? '')) ??
			'Image generation failed';
		throw error(response.status, message);
	}

	const first = finalPayload.data?.[0];
	if (!first) throw error(502, 'No image returned by provider');

	if (first.b64_json) {
		return json({ imageDataUrl: `data:image/png;base64,${first.b64_json}` });
	}

	if (first.url) {
		try {
			return json({ imageDataUrl: await urlToDataUrl(first.url) });
		} catch (err) {
			throw error(502, `Image provider returned URL but proxy fetch failed: ${networkErrorMessage(err)}`);
		}
	}

	throw error(502, 'Provider response did not include image content');
};
