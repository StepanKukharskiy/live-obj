import type { ChatCompletionMessage, ChatContentPart, ChatMessageContent } from './chat';
import { requestChatCompletion } from './chat';
import { LIVE_OBJ_SYSTEM_PROMPT, LLM_ONLY_SYSTEM_PROMPT } from './liveObjSystemPrompt';

const DEFAULT_LIVE_OBJ_MODEL = 'gpt-5.5';

const IMAGE_ONLY_USER_HINT = 'Generate or update the Live OBJ scene from this reference image.';

function userMessageContent(text: string, imageDataUrl?: string): ChatMessageContent {
	const t = text.trim();
	const img = imageDataUrl?.trim();
	if (!img) return t;
	const parts: ChatContentPart[] = [
		{ type: 'text', text: t || IMAGE_ONLY_USER_HINT },
		{ type: 'image_url', image_url: { url: img } }
	];
	return parts;
}

/**
 * Asks the configured LLM for a Live OBJ file using the same system prompt as `src/routes/api/llm`.
 * `history` should be prior user/assistant turns; assistant content should be the previous Live OBJ text.
 */
export async function requestLiveObjFromLlm(
	userMessage: string,
	history: ChatCompletionMessage[],
	model: string = DEFAULT_LIVE_OBJ_MODEL,
	options?: { imageDataUrl?: string; useProcedural?: boolean }
): Promise<string> {
	const useProcedural = options?.useProcedural !== false;
	const systemPrompt = useProcedural ? LIVE_OBJ_SYSTEM_PROMPT : LLM_ONLY_SYSTEM_PROMPT;
	const messages: ChatCompletionMessage[] = [
		{ role: 'system', content: systemPrompt },
		...history,
		{ role: 'user', content: userMessageContent(userMessage, options?.imageDataUrl) }
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
