import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { getTempAsset } from '$lib/server/tempAssetStore';

export const GET: RequestHandler = async ({ params }) => {
	const asset = getTempAsset(params.id);
	if (!asset) throw error(404, 'Temporary asset expired');
	return new Response(asset.bytes, {
		headers: {
			'Cache-Control': 'no-store',
			'Content-Disposition': asset.filename ? `inline; filename="${asset.filename}"` : 'inline',
			'Content-Type': asset.mimeType
		}
	});
};
