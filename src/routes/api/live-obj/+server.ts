import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import type { ChatCompletionMessage } from '$lib/server/llm/chat';
import { DEFAULT_LIVE_OBJ_MODEL, requestLiveObjFromLlm } from '$lib/server/llm/liveObjChat';
import { expandLiveObjWithExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';

type WireHistoryItem = {
	role: string;
	content: string;
	imageUrl?: string;
};

type Body = {
	userMessage?: string;
	imageUrl?: string;
	history?: WireHistoryItem[];
	model?: string;
};

const KNOWN_OPS = new Set([
	'transform', 'mirror', 'array', 'radial_array', 'bevel', 'smooth', 'subdivide', 'remesh', 'simplify',
	'displace', 'bend', 'twist', 'taper', 'sweep', 'thicken', 'skin', 'loft',
	'boolean', 'mesh_from_sdf', 'collision', 'snap', 'anchor', 'attach', 'constraint', 'material', 'tag',
	'trace_paths', 'sdf_tubes', 'voxelize', 'mesh_from_volume', 'tread',
	'union', 'subtract', 'intersect', 'chamfer', 'shell', 'offset'
]);

function unknownOpsInLiveObj(liveObj: string): string[] {
	const unknown = new Set<string>();
	for (const rawLine of liveObj.split('\n')) {
		const line = rawLine.trim();
		if (!line.startsWith('#@')) continue;
		const body = line.slice(2).trim();
		let opToken = '';
		if (body.startsWith('op:')) {
			opToken = body.slice(3).trim().split(/\s+/)[0] ?? '';
		} else if (body.startsWith('-')) {
			opToken = body.slice(1).trim().split(/\s+/)[0] ?? '';
		}
		if (!opToken) continue;
		const op = opToken.toLowerCase();
		if (!KNOWN_OPS.has(op)) unknown.add(op);
	}
	return [...unknown];
}

function wireHistoryToMessages(items: WireHistoryItem[]): ChatCompletionMessage[] {
	return items
		.filter((m) => m.role === 'user' || m.role === 'assistant')
		.map((m) => {
			if (m.role === 'assistant') {
				return { role: 'assistant', content: m.content };
			}
			const img = m.imageUrl?.trim();
			if (img) {
				const text =
					m.content?.trim() ||
					'Generate or update the Live OBJ scene from this reference image.';
				return {
					role: 'user',
					content: [
						{ type: 'text', text },
						{ type: 'image_url', image_url: { url: img } }
					]
				};
			}
			return { role: 'user', content: m.content };
		});
}

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

	const userMessage = body.userMessage?.trim() ?? '';
	const imageUrl = body.imageUrl?.trim();
	if (!userMessage && !imageUrl) {
		throw error(400, 'userMessage or imageUrl is required');
	}

	const model = (body.model?.trim() || DEFAULT_LIVE_OBJ_MODEL) as string;
	const rawHistory = body.history ?? [];
	const history: ChatCompletionMessage[] = wireHistoryToMessages(rawHistory);

	let rawLlm: string;
	try {
		rawLlm = await requestLiveObjFromLlm(userMessage, history, model, { imageDataUrl: imageUrl });
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `LLM failed: ${message}`);
	}

	const liveObj = stripCodeFences(rawLlm);
	let correctedLiveObj = liveObj;
	const unknownOps = unknownOpsInLiveObj(liveObj);
	if (unknownOps.length > 0) {
		const correctionPrompt =
			`Rewrite the previous Live OBJ to use only supported ops. ` +
			`Unknown ops found: ${unknownOps.join(', ')}. ` +
			`Keep object IDs/anchors/params unless required for compatibility. ` +
			`Do not use #@op_experimental; use #@op: or #@ops: only.`;
		try {
			const correctedRaw = await requestLiveObjFromLlm(
				correctionPrompt,
				[...history, { role: 'assistant', content: liveObj }],
				model
			);
			correctedLiveObj = stripCodeFences(correctedRaw);
		} catch {
			// Keep first-pass output when correction pass fails.
		}
	}
	let executedObj: string;
	let executorWarning: string | undefined;
	try {
		executedObj = await expandLiveObjWithExecutor(correctedLiveObj);
	} catch (e) {
		executorWarning = e instanceof Error ? e.message : String(e);
		executedObj = correctedLiveObj;
	}

	return json({
		liveObj: correctedLiveObj,
		rawLlm,
		executedObj,
		...(executorWarning ? { executorWarning } : {})
	});
};
