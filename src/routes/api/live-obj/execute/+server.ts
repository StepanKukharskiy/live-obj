import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { expandLiveObjWithExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';

type Body = {
	liveObj?: string;
};

export const POST: RequestHandler = async ({ request }) => {
	let body: Body;
	try {
		body = (await request.json()) as Body;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const liveObj = stripCodeFences(body.liveObj?.trim() ?? '');
	if (!liveObj) throw error(400, 'liveObj is required');

	try {
		const { executedObj, warnings } = await expandLiveObjWithExecutor(liveObj);
		return json({
			liveObj,
			executedObj,
			...(warnings.length > 0 ? { executorWarnings: warnings } : {})
		});
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		const stack = e instanceof Error ? e.stack : undefined;
		console.error('[live-obj/execute] Executor failed', {
			message,
			stack,
			preview: liveObj.slice(0, 800)
		});
		return json({ error: 'Executor failed', detail: message }, { status: 500 });
	}
};
