import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const OPENAI_IMAGES_API_URL = 'https://api.openai.com/v1/images/edits';
const OPENAI_IMAGE_MODEL = 'gpt-image-2';

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
	if (!apiKey) throw error(500, 'OPENAI_API_KEY is not configured');

	const sceneMetadata = metadataFromLiveObj(liveObjText);
	const fullPrompt = `${prompt}\n\nUse this scene metadata as a hard constraint for objects, materials, and structure:\n${sceneMetadata || '(no #@ metadata found)'}`;

	const form = new FormData();
	form.append('model', OPENAI_IMAGE_MODEL);
	form.append('prompt', fullPrompt);
	form.append('size', '1024x1024');
	form.append('image', dataUrlToBlob(screenshotDataUrl), 'scene-screenshot.jpg');

	const response = await fetch(OPENAI_IMAGES_API_URL, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${apiKey}`
		},
		body: form
	});

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
		return json({ imageDataUrl: await urlToDataUrl(first.url) });
	}

	throw error(502, 'Provider response did not include image content');
};
