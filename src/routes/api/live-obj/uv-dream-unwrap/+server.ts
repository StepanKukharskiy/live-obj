import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { storeTempAsset } from '$lib/server/tempAssetStore';
import { unwrapUvDreamSource } from '$lib/server/liveObj/pipeline';

export const POST: RequestHandler = async ({ request }) => {
	const body = (await request.json().catch(() => null)) as {
		liveObj?: string;
		targetObjectId?: string;
	} | null;
	if (!body?.liveObj?.trim()) throw error(400, 'liveObj is required');
	if (!body.targetObjectId?.trim()) throw error(400, 'targetObjectId is required');

	try {
		const result = await unwrapUvDreamSource({
			liveObj: body.liveObj,
			targetObjectId: body.targetObjectId.trim()
		});
		const id = storeTempAsset(result.sourceUvPng, 'image/png', 'source-uv.png');
		const guideId = storeTempAsset(result.sourceGuidePng, 'image/png', 'source-guide.png');
		return json({
			sourceUvUrl: `/api/temp-assets/${id}`,
			sourceGuideUrl: `/api/temp-assets/${guideId}`,
			expiresInSeconds: 15 * 60,
			warnings: result.warnings
		});
	} catch (err) {
		throw error(400, err instanceof Error ? err.message : 'Unable to unwrap UV source');
	}
};
