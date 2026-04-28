import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ url }) => {
	const target = url.searchParams.get('url')?.trim();
	if (!target) throw error(400, 'url query param is required');

	let parsed: URL;
	try {
		parsed = new URL(target);
	} catch {
		throw error(400, 'Invalid url');
	}
	if (!['http:', 'https:'].includes(parsed.protocol)) {
		throw error(400, 'Only http/https URLs are allowed');
	}

	const res = await fetch(parsed.toString());
	if (!res.ok) throw error(res.status, `Failed to fetch image: ${res.statusText}`);
	const mimeType = res.headers.get('content-type') || 'application/octet-stream';
	const buffer = Buffer.from(await res.arrayBuffer());
	const dataUrl = `data:${mimeType};base64,${buffer.toString('base64')}`;
	return json({ dataUrl });
};
