import type { ChatCompletionMessage } from './chat';
import { requestChatCompletion } from './chat';
import { LIVE_OBJ_SYSTEM_PROMPT } from './liveObjSystemPrompt';

const DEFAULT_LIVE_OBJ_MODEL = 'gpt-5.5';

/**
 * Asks the configured LLM for a Live OBJ file using the same system prompt as `src/routes/api/llm`.
 * `history` should be prior user/assistant turns; assistant content should be the previous Live OBJ text.
 */
export async function requestLiveObjFromLlm(
	userMessage: string,
	history: ChatCompletionMessage[],
	model: string = DEFAULT_LIVE_OBJ_MODEL
): Promise<string> {
	const messages: ChatCompletionMessage[] = [
		{ role: 'system', content: LIVE_OBJ_SYSTEM_PROMPT },
		...history,
		{ role: 'user', content: userMessage }
	];
	const { content } = await requestChatCompletion({
		messages,
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-llm',
		maxTokens: 16000
	});
	return content;
}

export { DEFAULT_LIVE_OBJ_MODEL };
