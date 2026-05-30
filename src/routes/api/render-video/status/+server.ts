import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const DEFAULT_GOOGLE_VIDEO_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta';

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

type StatusBody = {
	provider?: string;
	apiKey?: string;
	videoUrl?: string;
	jobId?: string;
};

function googleBaseUrl(videoUrl?: string): string {
	const trimmed = videoUrl?.trim() || DEFAULT_GOOGLE_VIDEO_BASE_URL;
	if (trimmed.includes(':predictLongRunning')) {
		return trimmed.replace(/\/models\/[^/]+:predictLongRunning.*$/, '');
	}
	return trimmed.replace(/\/$/, '');
}

export const POST: RequestHandler = async ({ request }) => {
	let body: StatusBody;
	try {
		body = (await request.json()) as StatusBody;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const provider = body.provider?.trim().toLowerCase() ?? '';
	const apiKey = body.apiKey?.trim() ?? '';
	const jobId = body.jobId?.trim() ?? '';
	if (provider !== 'google') throw error(400, 'Video status currently supports Google.');
	if (!apiKey) throw error(500, 'API key is required');
	if (!jobId) throw error(400, 'jobId is required');

	const response = await fetch(`${googleBaseUrl()}/${jobId}`, {
		headers: { 'x-goog-api-key': apiKey }
	});
	const operation = (await response.json().catch(() => ({}))) as GoogleOperation;
	if (!response.ok) {
		throw error(response.status, operation.error?.message || 'Video polling failed');
	}
	if (operation.error?.message) throw error(502, operation.error.message);

	const videoUri =
		operation.response?.generateVideoResponse?.generatedSamples?.[0]?.video?.uri ??
		operation.response?.generatedVideos?.[0]?.video?.uri ??
		'';
	if (operation.done && !videoUri) {
		throw error(502, 'Video completed, but no download URI was returned');
	}

	return json({
		status: operation.done ? 'completed' : 'pending',
		jobId: operation.name ?? jobId,
		videoUri
	});
};
