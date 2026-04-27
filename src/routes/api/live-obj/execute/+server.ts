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
		const executedObj = await expandLiveObjWithExecutor(liveObj);
		return json({ liveObj, executedObj });
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(500, `Executor failed: ${message}`);
	}
};
