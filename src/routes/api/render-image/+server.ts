import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const DEFAULT_OPENAI_IMAGES_API_URL = 'https://api.openai.com/v1/images/edits';
const OPENAI_IMAGE_MODEL = 'gpt-image-1.5';
const OPENAI_IMAGES_TIMEOUT_MS = 90_000;
const MAX_SCENE_METADATA_CHARS = 12_000;

function metadataFromLiveObj(liveObjText: string): string {
	const metadata = liveObjText
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter((line) => line.startsWith('#@'))
		.filter((line) => !/^#@dream_(?:base|delta)_v\b/i.test(line))
		.join('\n');
	if (metadata.length <= MAX_SCENE_METADATA_CHARS) return metadata;
	return `${metadata.slice(0, MAX_SCENE_METADATA_CHARS)}\n#@note: scene metadata truncated for image prompt`;
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

function dataUrlToInlineImage(dataUrl: string): { mimeType: string; data: string } {
	const m = dataUrl.match(/^data:(.+?);base64,(.+)$/);
	if (!m) {
		throw new Error('Invalid data URL payload');
	}
	return { mimeType: m[1], data: m[2] };
}

function isGoogleGenerateContentUrl(url: string): boolean {
	return url.includes('generativelanguage.googleapis.com') && url.includes(':generateContent');
}

function isOpenRouterUrl(url: string): boolean {
	return url.includes('openrouter.ai');
}

function googleGenerateContentUrlForModel(url: string, model: string): string {
	if (!isGoogleGenerateContentUrl(url)) return url;
	return url.replace(
		/\/models\/[^/:]+:generateContent/,
		`/models/${encodeURIComponent(model)}:generateContent`
	);
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

function openRouterOutputModalities(model: string): string[] {
	const imageOnlyPrefixes = [
		'black-forest-labs/',
		'bytedance-seed/',
		'sourceful/',
		'x-ai/grok-imagine'
	];
	return imageOnlyPrefixes.some((prefix) => model.startsWith(prefix))
		? ['image']
		: ['image', 'text'];
}

async function imageUrlToDataUrl(imageUrl: string): Promise<string> {
	if (imageUrl.startsWith('data:image/')) return imageUrl;
	return urlToDataUrl(imageUrl);
}

export const POST: RequestHandler = async ({ request }) => {
	let body: {
		prompt?: string;
		screenshotDataUrl?: string;
		liveObjText?: string;
		provider?: string;
		apiKey?: string;
		apiUrl?: string;
		imageUrl?: string;
		imageModel?: string;
	};
	try {
		body = (await request.json()) as {
			prompt?: string;
			screenshotDataUrl?: string;
			liveObjText?: string;
			provider?: string;
			apiKey?: string;
			apiUrl?: string;
			imageUrl?: string;
			imageModel?: string;
		};
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const prompt = body.prompt?.trim() ?? '';
	const screenshotDataUrl = body.screenshotDataUrl?.trim() ?? '';
	const liveObjText = body.liveObjText ?? '';

	if (!prompt) throw error(400, 'prompt is required');
	if (!screenshotDataUrl.startsWith('data:image/'))
		throw error(400, 'screenshotDataUrl must be an image data URL');

	const requestApiKey = body.apiKey?.trim() ?? '';
	const requestImageUrl = body.imageUrl?.trim() ?? '';
	const provider = body.provider?.trim().toLowerCase() ?? '';
	const imageModel = body.imageModel?.trim() || OPENAI_IMAGE_MODEL;
	const apiKey = requestApiKey;
	const imagesApiUrl = requestImageUrl || DEFAULT_OPENAI_IMAGES_API_URL;
	if (!apiKey) throw error(500, 'API key is required');

	const sceneMetadata = metadataFromLiveObj(liveObjText);
	const fullPrompt = `${prompt}

Do not redesign the object. Preserve exact silhouette, object count, relative position, camera angle, major outlines, and block proportions.

Use this scene metadata as a hard constraint for objects, materials, and structure:
${sceneMetadata || '(no #@ metadata found)'}`;

	if (provider === 'openrouter' || isOpenRouterUrl(imagesApiUrl)) {
		const abortController = new AbortController();
		const timeout = setTimeout(() => abortController.abort(), OPENAI_IMAGES_TIMEOUT_MS);
		let response: Response;
		try {
			response = await fetch(imagesApiUrl, {
				method: 'POST',
				headers: {
					Authorization: `Bearer ${apiKey}`,
					'Content-Type': 'application/json',
					'X-OpenRouter-Title': 'Spellshape'
				},
				body: JSON.stringify({
					model: imageModel,
					messages: [
						{
							role: 'user',
							content: [
								{ type: 'text', text: fullPrompt },
								{ type: 'image_url', image_url: { url: screenshotDataUrl } }
							]
						}
					],
					modalities: openRouterOutputModalities(imageModel),
					stream: false
				}),
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
			choices?: Array<{
				message?: {
					content?: unknown;
					images?: Array<{ image_url?: { url?: string }; imageUrl?: { url?: string } }>;
				};
			}>;
		};
		if (!response.ok) {
			throw error(response.status, payload.error?.message ?? 'Image generation failed');
		}

		const images = payload.choices?.[0]?.message?.images ?? [];
		const firstImageUrl = images[0]?.image_url?.url ?? images[0]?.imageUrl?.url ?? '';
		if (!firstImageUrl) throw error(502, 'No image returned by provider');
		return json({ imageDataUrl: await imageUrlToDataUrl(firstImageUrl) });
	}

	if (isGoogleGenerateContentUrl(imagesApiUrl)) {
		const image = dataUrlToInlineImage(screenshotDataUrl);
		const googleUrl = googleGenerateContentUrlForModel(imagesApiUrl, imageModel);
		const abortController = new AbortController();
		const timeout = setTimeout(() => abortController.abort(), OPENAI_IMAGES_TIMEOUT_MS);
		let response: Response;
		try {
			response = await fetch(googleUrl, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'x-goog-api-key': apiKey
				},
				body: JSON.stringify({
					contents: [
						{
							role: 'user',
							parts: [
								{ text: fullPrompt },
								{
									inline_data: {
										mime_type: image.mimeType,
										data: image.data
									}
								}
							]
						}
					],
					generationConfig: {
						responseModalities: ['TEXT', 'IMAGE']
					}
				}),
				signal: abortController.signal
			});
		} catch (err) {
			const message =
				err instanceof Error && err.name === 'AbortError'
					? `Image provider request timed out after ${Math.round(OPENAI_IMAGES_TIMEOUT_MS / 1000)}s`
					: `Unable to reach image provider (${googleUrl}): ${networkErrorMessage(err)}`;
			throw error(502, message);
		} finally {
			clearTimeout(timeout);
		}

		const payload = (await response.json().catch(() => ({}))) as {
			error?: { message?: string };
			candidates?: Array<{
				content?: {
					parts?: Array<{
						text?: string;
						inlineData?: { mimeType?: string; data?: string };
						inline_data?: { mime_type?: string; data?: string };
					}>;
				};
			}>;
		};
		if (!response.ok) {
			throw error(response.status, payload.error?.message ?? 'Image generation failed');
		}

		const parts = payload.candidates?.[0]?.content?.parts ?? [];
		const imagePart = parts.find((part) => part.inlineData?.data || part.inline_data?.data);
		const inlineImage = imagePart?.inlineData
			? { mimeType: imagePart.inlineData.mimeType, data: imagePart.inlineData.data }
			: imagePart?.inline_data
				? { mimeType: imagePart.inline_data.mime_type, data: imagePart.inline_data.data }
				: undefined;
		if (!inlineImage?.data) {
			const text = parts
				.map((part) => part.text)
				.filter(Boolean)
				.join(' ');
			throw error(502, text || 'No image returned by provider');
		}

		const mimeType = inlineImage.mimeType ?? 'image/png';
		return json({ imageDataUrl: `data:${mimeType};base64,${inlineImage.data}` });
	}

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

	const providerMessage =
		initialPayload.error?.message ?? JSON.stringify(initialPayload.detail ?? '');

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
			throw error(
				502,
				`Unable to reach image provider (${imagesApiUrl}) on JSON fallback: ${networkErrorMessage(err)}`
			);
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
			(typeof finalPayload.detail === 'string'
				? finalPayload.detail
				: JSON.stringify(finalPayload.detail ?? '')) ??
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
			throw error(
				502,
				`Image provider returned URL but proxy fetch failed: ${networkErrorMessage(err)}`
			);
		}
	}

	throw error(502, 'Provider response did not include image content');
};
