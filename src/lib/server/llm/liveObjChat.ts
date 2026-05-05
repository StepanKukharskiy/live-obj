import type { ChatCompletionMessage, ChatContentPart, ChatMessageContent } from './chat';
import { requestChatCompletion } from './chat';
import { LIVE_OBJ_SYSTEM_PROMPT, LLM_ONLY_SYSTEM_PROMPT } from './liveObjSystemPrompt';

const DEFAULT_LIVE_OBJ_MODEL = 'gpt-5.5';

const IMAGE_ONLY_USER_HINT = 'Generate or update the Live OBJ scene from this reference image.';
const SURGICAL_HISTORY_ASSISTANT_PLACEHOLDER =
	'Previous Live OBJ revision was applied. The current Live OBJ in the latest user message is the source of truth.';

const LIVE_OBJ_SURGICAL_EDIT_SYSTEM_PROMPT = `You are a surgical editor for Live OBJ files.

Live OBJ is OBJ plus #@ metadata. The #@ metadata is the editable source of truth; v/f mesh lines are cache output.

Your job:
- Read the current Live OBJ exactly as provided.
- Satisfy the user request with the smallest useful text edits.
- Preserve all unrelated text byte-for-byte.
- Edit #@ metadata first. Do not add or regenerate v/f cache lines for procedural, SDF, assembly, or simulation objects.
- Keep existing object IDs, units, up axis, kernel settings, params, materials, anchors, and comments unless the user asked to change them.
- For modifications, replace the smallest exact line or object block that contains the change.
- For additions, insert a new object block near the relevant object or append it after the last object by replacing a unique nearby exact snippet with itself plus the new block.
- For removals, replace only the relevant object block with an empty string. If removing a material preset that is no longer used, remove only that preset line.
- If an assembly child list or parent relationship must change, update the smallest relevant #@children/#@parent/#@params lines too.
- When the user asks to mirror/duplicate an existing object to create a second one in the scene, create a distinct nearby instance with new object IDs and a transform/offset. Do not rely only on #@ops mirror unless the user explicitly wants symmetric geometry inside the same object.
- Use only supported Live OBJ metadata patterns already present in the file, plus common supported sources: procedural, llm_mesh, assembly, sdf, simulation.
- Use #@ops: lists, not #@op: lines.

Return only JSON with this exact shape:
{
  "summary": "short edit summary",
  "edits": [
    {
      "find": "exact text from the current Live OBJ",
      "replace": "replacement text"
    }
  ]
}

Rules for JSON edits:
- Every find string must appear exactly once in the current Live OBJ at the moment that edit is applied.
- The replace string may contain the find string when inserting before or after it.
- Use \\n for newlines inside JSON strings.
- Do not include Markdown, code fences, comments, or explanations outside the JSON.`;

const LIVE_OBJ_CHAT_MESSAGE_SYSTEM_PROMPT = `You write short, specific assistant chat messages for a 3D authoring app.

The 3D source has already been created or edited. Your job is only to describe what changed.

Rules:
- Write one concise sentence.
- Mention the concrete object or parts created/changed when the data makes that clear.
- For iterative edits, emphasize the requested addition/removal/adjustment and do not imply unrelated existing objects were recreated.
- Do not mention Live OBJ, JSON, patches, metadata, executor, source files, or implementation details.
- Do not apologize.
- Do not add a follow-up question.
- Output plain text only.`;

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

function surgicalHistoryMessages(history: ChatCompletionMessage[]): ChatCompletionMessage[] {
	return history.slice(-8).map((message) => {
		if (message.role === 'assistant') {
			return { role: 'assistant', content: SURGICAL_HISTORY_ASSISTANT_PLACEHOLDER };
		}
		return message;
	});
}

function surgicalEditUserContent(
	userMessage: string,
	currentLiveObj: string,
	imageDataUrl?: string
): ChatMessageContent {
	const request = userMessage.trim() || IMAGE_ONLY_USER_HINT;
	const text = [
		'User request:',
		request,
		'',
		'Current Live OBJ:',
		'```obj',
		currentLiveObj,
		'```',
		'',
		'Return a surgical JSON patch against the Current Live OBJ. Do not return a full Live OBJ file.'
	].join('\n');
	return userMessageContent(text, imageDataUrl);
}

function objectNamesFromLiveObj(sourceText: string): string[] {
	const names = [...sourceText.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1]);
	return [...new Set(names)];
}

function compactList(items: string[], max = 24): string {
	if (items.length <= max) return items.join(', ');
	return `${items.slice(0, max).join(', ')} and ${items.length - max} more`;
}

function chatMessagePrompt(input: {
	userMessage: string;
	previousLiveObj?: string;
	nextLiveObj: string;
	editMode: 'surgical' | 'rewrite';
	surgicalEditSummary?: string;
	rawLlm?: string;
}): string {
	const previousNames = objectNamesFromLiveObj(input.previousLiveObj ?? '');
	const nextNames = objectNamesFromLiveObj(input.nextLiveObj);
	const previousSet = new Set(previousNames);
	const nextSet = new Set(nextNames);
	const added = nextNames.filter((name) => !previousSet.has(name));
	const removed = previousNames.filter((name) => !nextSet.has(name));
	return [
		`User request: ${input.userMessage || IMAGE_ONLY_USER_HINT}`,
		`Mode: ${input.editMode}`,
		input.surgicalEditSummary ? `Model edit summary: ${input.surgicalEditSummary}` : '',
		`Previous object IDs: ${compactList(previousNames) || '(none)'}`,
		`Final object IDs: ${compactList(nextNames) || '(none)'}`,
		`Added object IDs: ${compactList(added) || '(none)'}`,
		`Removed object IDs: ${compactList(removed) || '(none)'}`,
		input.rawLlm && input.editMode === 'surgical'
			? `Raw surgical patch or summary:\n${input.rawLlm.slice(0, 3000)}`
			: '',
		'',
		'Write the assistant chat message now.'
	].filter(Boolean).join('\n');
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

/**
 * Asks the configured LLM for exact text edits against the current Live OBJ.
 * The server applies these edits locally, so unrelated source text stays untouched.
 */
export async function requestLiveObjSurgicalPatchFromLlm(
	userMessage: string,
	currentLiveObj: string,
	history: ChatCompletionMessage[],
	model: string = DEFAULT_LIVE_OBJ_MODEL,
	options?: { imageDataUrl?: string; currentSceneMode?: 'live_obj' | 'raw_obj' }
): Promise<string> {
	const modeHint =
		options?.currentSceneMode === 'raw_obj'
			? [
					'Current scene mode: raw OBJ / tools-off output.',
					'Important: existing v/f mesh blocks are source geometry, not disposable cache. Preserve existing mesh object blocks unless the user asks to replace them.',
					'For duplication/mirroring requests on raw OBJ scenes, prefer adding #@ops array/transform metadata to existing mesh objects or adding separate copied object blocks; do not convert the whole scene to procedural metadata.'
				].join('\n')
			: [
					'Current scene mode: Live OBJ / tools-on output.',
					'Important: #@ metadata is the editable source of truth; v/f mesh lines are cache output.'
				].join('\n');
	const messages: ChatCompletionMessage[] = [
		{ role: 'system', content: LIVE_OBJ_SURGICAL_EDIT_SYSTEM_PROMPT },
		...surgicalHistoryMessages(history),
		{
			role: 'user',
			content: surgicalEditUserContent(
				`${modeHint}\n\n${userMessage}`,
				currentLiveObj,
				options?.imageDataUrl
			)
		}
	];
	const { content } = await requestChatCompletion({
		messages,
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-surgical-edit',
		maxTokens: 8000
	});
	return content;
}

export async function requestLiveObjAssistantMessageFromLlm(
	input: {
		userMessage: string;
		previousLiveObj?: string;
		nextLiveObj: string;
		editMode: 'surgical' | 'rewrite';
		surgicalEditSummary?: string;
		rawLlm?: string;
	},
	model: string = DEFAULT_LIVE_OBJ_MODEL
): Promise<string> {
	const { content } = await requestChatCompletion({
		messages: [
			{ role: 'system', content: LIVE_OBJ_CHAT_MESSAGE_SYSTEM_PROMPT },
			{ role: 'user', content: chatMessagePrompt(input) }
		],
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-chat-message',
		maxTokens: 120
	});
	return content.replace(/^["'`]+|["'`]+$/g, '').trim();
}

export { DEFAULT_LIVE_OBJ_MODEL };
