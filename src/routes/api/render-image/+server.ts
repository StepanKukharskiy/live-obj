import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const DEFAULT_OPENAI_IMAGES_API_URL = 'https://api.openai.com/v1/images/edits';
const OPENAI_IMAGE_MODEL = 'gpt-image-2';
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

export const POST: RequestHandler = async ({ request }) => {
	let body: { prompt?: string; screenshotDataUrl?: string; liveObjText?: string };
	try {
		body = (await request.json()) as { prompt?: string; screenshotDataUrl?: string; liveObjText?: string };
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const prompt = body.prompt?.trim() ?? '';
	const screenshotDataUrl = body.screenshotDataUrl?.trim() ?? '';
	const liveObjText = body.liveObjText ?? '';

	if (!prompt) throw error(400, 'prompt is required');
	if (!screenshotDataUrl.startsWith('data:image/')) throw error(400, 'screenshotDataUrl must be an image data URL');

	const { env } = await import('$env/dynamic/private');
	const apiKey = pickString(process.env.OPENAI_API_KEY, env.OPENAI_API_KEY, process.env.DEFAULT_OPENAI_API_KEY, env.DEFAULT_OPENAI_API_KEY);
	const imagesApiUrl = pickString(process.env.OPENAI_IMAGES_API_URL, env.OPENAI_IMAGES_API_URL, process.env.OPENAI_API_URL, env.OPENAI_API_URL, DEFAULT_OPENAI_IMAGES_API_URL);
	if (!apiKey) throw error(500, 'OPENAI_API_KEY is not configured');

	const sceneMetadata = metadataFromLiveObj(liveObjText);
	const fullPrompt = `${prompt}\n\nUse this scene metadata as a hard constraint for objects, materials, and structure:\n${sceneMetadata || '(no #@ metadata found)'}`;

	const form = new FormData();
	form.append('model', OPENAI_IMAGE_MODEL);
	form.append('prompt', fullPrompt);
	form.append('size', '1024x1024');
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

	const payload = (await response.json().catch(() => ({}))) as {
		error?: { message?: string };
		data?: Array<{ b64_json?: string; url?: string }>;
	};

	if (!response.ok) {
		throw error(response.status, payload.error?.message ?? 'Image generation failed');
	}

	const first = payload.data?.[0];
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
