import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { expandLiveObjWithExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';

export const POST: RequestHandler = async ({ request }) => {
	try {
		const { liveObj } = await request.json();
		if (!liveObj) {
			return json({ detail: 'Missing liveObj in request body' }, { status: 400 });
		}
		const liveObjClean = stripCodeFences(liveObj);
		const result = await expandLiveObjWithExecutor(liveObjClean);
		return json({ executedObj: result.executedObj, liveObj: liveObjClean });
	} catch (error) {
		console.error('[live-obj/execute] Error:', error);
		return json(
			{ detail: error instanceof Error ? error.message : 'Unknown error' },
			{ status: 500 }
		);
	}
};
