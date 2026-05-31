import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const DEFAULT_GOOGLE_VIDEO_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta';
const DEFAULT_OPENROUTER_VIDEO_URL = 'https://openrouter.ai/api/v1/videos';

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

type OpenRouterVideoJob = {
	id?: string;
	polling_url?: string;
	status?: string;
	error?: string;
	unsigned_urls?: string[];
	generation_id?: string;
};

function googleBaseUrl(videoUrl?: string): string {
	const trimmed = videoUrl?.trim() || DEFAULT_GOOGLE_VIDEO_BASE_URL;
	if (trimmed.includes(':predictLongRunning')) {
		return trimmed.replace(/\/models\/[^/]+:predictLongRunning.*$/, '');
	}
	return trimmed.replace(/\/$/, '');
}

function normalizeOpenRouterUrl(url: string): string {
	return new URL(url, 'https://openrouter.ai').toString();
}

function openRouterJobUrl(videoUrl: string | undefined, jobId: string): string {
	const base = (videoUrl?.trim() || DEFAULT_OPENROUTER_VIDEO_URL).replace(/\/$/, '');
	return `${base}/${encodeURIComponent(jobId)}`;
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
	if (provider !== 'google' && provider !== 'openrouter') {
		throw error(400, 'Video status currently supports Google and OpenRouter.');
	}
	if (!apiKey) throw error(500, 'API key is required');
	if (!jobId) throw error(400, 'jobId is required');

	if (provider === 'openrouter') {
		const response = await fetch(openRouterJobUrl(body.videoUrl, jobId), {
			headers: {
				Authorization: `Bearer ${apiKey}`,
				'X-OpenRouter-Title': 'Spellshape'
			}
		});
		const job = (await response.json().catch(() => ({}))) as OpenRouterVideoJob;
		if (!response.ok) throw error(response.status, job.error || 'Video polling failed');
		if (job.error) throw error(502, job.error);

		const status = job.status ?? 'pending';
		const videoUri =
			status === 'completed'
				? (job.unsigned_urls?.[0] ??
					`${DEFAULT_OPENROUTER_VIDEO_URL}/${encodeURIComponent(job.id ?? jobId)}/content?index=0`)
				: '';

		return json({
			status,
			jobId: job.id ?? jobId,
			generationId: job.generation_id,
			pollingUrl: job.polling_url ? normalizeOpenRouterUrl(job.polling_url) : '',
			videoUri: videoUri ? normalizeOpenRouterUrl(videoUri) : ''
		});
	}

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
