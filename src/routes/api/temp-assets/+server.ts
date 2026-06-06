import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { storeTempAsset } from '$lib/server/tempAssetStore';

function dataUrlToBytes(dataUrl: string): { bytes: Uint8Array; mimeType: string } {
	const match = dataUrl.match(/^data:([^;]+);base64,(.+)$/);
	if (!match) throw error(400, 'Invalid data URL');
	return {
		bytes: new Uint8Array(Buffer.from(match[2], 'base64')),
		mimeType: match[1]
	};
}

export const POST: RequestHandler = async ({ request }) => {
	const body = (await request.json().catch(() => null)) as {
		dataUrl?: string;
		base64?: string;
		mimeType?: string;
		filename?: string;
	} | null;
	if (!body) throw error(400, 'Invalid JSON');

	const payload = body.dataUrl
		? dataUrlToBytes(body.dataUrl)
		: body.base64 && body.mimeType
			? { bytes: new Uint8Array(Buffer.from(body.base64, 'base64')), mimeType: body.mimeType }
			: null;
	if (!payload) throw error(400, 'Expected dataUrl or base64 + mimeType');

	const id = storeTempAsset(payload.bytes, payload.mimeType, body.filename);
	return json({
		id,
		url: `/api/temp-assets/${id}`,
		expiresInSeconds: 15 * 60
	});
};
