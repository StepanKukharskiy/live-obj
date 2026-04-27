import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { LIVE_OBJ_SYSTEM_PROMPT } from '$lib/server/llm/liveObjSystemPrompt';
import { requestChatCompletion, type ChatCompletionMessage } from '$lib/server/llm/chat';

const DEFAULT_MODEL = 'gpt-5.5';

/**
 * Chat completions using the Live OBJ system prompt from this route (same as `LIVE_OBJ_SYSTEM_PROMPT` in `src/lib/server/llm/liveObjSystemPrompt.ts`).
 * For end-to-end mesh expansion, prefer `POST /api/live-obj` instead.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: { messages?: ChatCompletionMessage[]; model?: string };
	try {
		body = (await request.json()) as { messages?: ChatCompletionMessage[]; model?: string };
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const incoming = body.messages;
	if (!Array.isArray(incoming) || incoming.length === 0) {
		throw error(400, 'messages array is required');
	}

	const model = (body.model?.trim() || DEFAULT_MODEL) as string;
	const messages: ChatCompletionMessage[] = [
		{ role: 'system', content: LIVE_OBJ_SYSTEM_PROMPT },
		...incoming.filter((m) => m && m.role !== 'system' && typeof m.content === 'string')
	];

	try {
		const { content, data } = await requestChatCompletion({
			messages,
			model,
			label: 'api-llm-post',
			maxTokens: 16000
		});
		return json({ content, data });
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, message);
	}
};
