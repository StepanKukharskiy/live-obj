import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { normalizeRawPostHeader } from '$lib/liveObj/rawPostHeader';
import { validateRawPostSource } from '$lib/liveObj/rawPostValidation';
import { expandRawObjWithPostExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';

export const POST: RequestHandler = async ({ request }) => {
	try {
		const { rawObj } = await request.json();
		if (!rawObj) {
			return json({ detail: 'Missing rawObj in request body' }, { status: 400 });
		}
		const rawObjClean = normalizeRawPostHeader(stripCodeFences(rawObj));
		const validation = validateRawPostSource(rawObjClean);
		if (!validation.valid) {
			return json(
				{
					detail: validation.errors.join('; ') || 'Raw-post validation failed',
					rawObj: rawObjClean,
					validation
				},
				{ status: 400 }
			);
		}
		const result = await expandRawObjWithPostExecutor(rawObjClean);
		return json({
			executedObj: result.executedObj,
			rawObj: rawObjClean,
			warnings: [...validation.warnings, ...result.warnings],
			validation
		});
	} catch (error) {
		console.error('[raw-obj/execute] Error:', error);
		return json(
			{ detail: error instanceof Error ? error.message : 'Unknown error' },
			{ status: 500 }
		);
	}
};
