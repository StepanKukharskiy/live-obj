import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

type DownloadBody = {
	provider?: string;
	apiKey?: string;
	videoUri?: string;
};

export const POST: RequestHandler = async ({ request }) => {
	let body: DownloadBody;
	try {
		body = (await request.json()) as DownloadBody;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const provider = body.provider?.trim().toLowerCase() ?? '';
	const apiKey = body.apiKey?.trim() ?? '';
	const videoUri = body.videoUri?.trim() ?? '';
	if (provider !== 'google' && provider !== 'openrouter') {
		throw error(400, 'Video download currently supports Google and OpenRouter.');
	}
	if (!apiKey) throw error(500, 'API key is required');
	if (!videoUri.startsWith('https://')) throw error(400, 'videoUri must be an HTTPS URL');

	const response = await fetch(videoUri, {
		headers:
			provider === 'google'
				? { 'x-goog-api-key': apiKey }
				: videoUri.includes('openrouter.ai')
					? { Authorization: `Bearer ${apiKey}` }
					: {}
	});
	if (!response.ok) {
		throw error(response.status, 'Video completed, but content download failed');
	}

	return new Response(response.body, {
		headers: {
			'Content-Type': response.headers.get('content-type') || 'video/mp4',
			'Cache-Control': 'no-store'
		}
	});
};
