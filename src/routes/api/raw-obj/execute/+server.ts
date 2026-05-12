import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { expandRawObjWithPostExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';

export const POST: RequestHandler = async ({ request }) => {
	try {
		const { rawObj } = await request.json();
		if (!rawObj) {
			return json({ detail: 'Missing rawObj in request body' }, { status: 400 });
		}
		const rawObjClean = stripCodeFences(rawObj);
		const result = await expandRawObjWithPostExecutor(rawObjClean);
		return json({
			executedObj: result.executedObj,
			rawObj: rawObjClean,
			warnings: result.warnings
		});
	} catch (error) {
		console.error('[raw-obj/execute] Error:', error);
		return json(
			{ detail: error instanceof Error ? error.message : 'Unknown error' },
			{ status: 500 }
		);
	}
};
