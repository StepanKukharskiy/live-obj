import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { getVideoFrame } from '$lib/server/videoFrameStore';

export const GET: RequestHandler = async ({ params }) => {
	const frame = getVideoFrame(params.id);
	if (!frame) throw error(404, 'Video frame expired');

	return new Response(frame.bytes, {
		headers: {
			'Content-Type': frame.mimeType,
			'Cache-Control': 'no-store'
		}
	});
};
