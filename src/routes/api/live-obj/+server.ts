import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import type { ChatCompletionMessage } from '$lib/server/llm/chat';
import { DEFAULT_LIVE_OBJ_MODEL, requestLiveObjFromLlm } from '$lib/server/llm/liveObjChat';
import { expandLiveObjWithExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';

type Body = {
	userMessage?: string;
	history?: Array<{ role: string; content: string }>;
	model?: string;
};

/**
 * 1) LLM (via `requestChatCompletion` / same prompt as `api/llm`) → Live OBJ text
 * 2) Python executor refreshes v/f from #@ metadata
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Body;
	try {
		body = (await request.json()) as Body;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const userMessage = body.userMessage?.trim();
	if (!userMessage) {
		throw error(400, 'userMessage is required');
	}

	const model = (body.model?.trim() || DEFAULT_LIVE_OBJ_MODEL) as string;
	const rawHistory = body.history ?? [];
	const history: ChatCompletionMessage[] = rawHistory
		.filter(
			(m): m is ChatCompletionMessage =>
				(m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string'
		)
		.map((m) => ({ role: m.role, content: m.content }));

	let rawLlm: string;
	try {
		rawLlm = await requestLiveObjFromLlm(userMessage, history, model);
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `LLM failed: ${message}`);
	}

	const liveObj = stripCodeFences(rawLlm);
	let executedObj: string;
	let executorWarning: string | undefined;
	try {
		executedObj = await expandLiveObjWithExecutor(liveObj);
	} catch (e) {
		executorWarning = e instanceof Error ? e.message : String(e);
		executedObj = liveObj;
	}

	return json({
		liveObj,
		rawLlm,
		executedObj,
		...(executorWarning ? { executorWarning } : {})
	});
};
