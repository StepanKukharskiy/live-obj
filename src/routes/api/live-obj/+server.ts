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
	useProcedural?: boolean;
	kernelDefault?: 'auto' | 'cadquery';
};

const KNOWN_OPS = new Set([
	'transform', 'mirror', 'array', 'radial_array', 'bevel', 'smooth', 'subdivide', 'remesh', 'simplify',
	'displace', 'bend', 'twist', 'taper', 'sweep', 'thicken', 'skin', 'loft',
	'boolean', 'mesh_from_sdf', 'collision', 'snap', 'anchor', 'attach', 'constraint', 'material', 'tag',
	'trace_paths', 'sdf_tubes', 'voxelize', 'mesh_from_volume', 'tread',
	'union', 'subtract', 'intersect', 'chamfer', 'shell', 'offset'
]);
// Ops valid inside `#@sdf:` blocks. SDF primitive/modifier ops are disjoint
// from top-level `#@ops:` ops, so we must not flag them when encountered under
// a `#@sdf:` section.
const KNOWN_SDF_OPS = new Set([
	'sphere', 'box', 'cylinder', 'capsule', 'torus', 'cone', 'plane',
	'union', 'subtract', 'intersect', 'smooth_union',
	'repeat', 'twist', 'bend', 'displace', 'noise_displace',
	'mesh_from_sdf'
]);
const KNOWN_SOURCES = new Set(['procedural', 'llm_mesh', 'assembly', 'sdf', 'simulation']);
const KNOWN_TYPES = new Set([
	'box', 'cylinder', 'surface_grid', 'heightfield', 'curve', 'sweep', 'mesh',
	'extrude', 'revolve', 'lathe', 'loft', 'cone', 'sphere'
]);
const KNOWN_SIMS = new Set(['cellular_automata', 'differential_growth', 'boids']);

function unknownOpsInLiveObj(liveObj: string): string[] {
	const unknown = new Set<string>();
	// Track which `#@` block the current `#@ - …` line belongs to so SDF ops
	// don't get flagged as if they were top-level mesh ops.
	let block: 'ops' | 'sdf' | 'anchors' | 'params' | 'placement' | 'other' = 'other';
	for (const rawLine of liveObj.split('\n')) {
		const line = rawLine.trim();
		if (!line.startsWith('#@')) {
			// A non-`#@` line (e.g. `o foo`, blank line, `v`/`f`) terminates any
			// continuation block.
			if (line.length === 0 || !line.startsWith('#')) block = 'other';
			continue;
		}
		const body = line.slice(2).trim();
		if (body.startsWith('ops:')) { block = 'ops'; continue; }
		if (body.startsWith('sdf:')) { block = 'sdf'; continue; }
		if (body.startsWith('anchors:')) { block = 'anchors'; continue; }
		if (body.startsWith('params:')) { block = 'params'; continue; }
		if (body.startsWith('placement:')) { block = 'placement'; continue; }
		if (body.startsWith('-')) {
			if (block === 'anchors' || block === 'params' || block === 'placement') continue;
			const opToken = body.slice(1).trim().split(/\s+/)[0] ?? '';
			if (!opToken) continue;
			const op = opToken.toLowerCase();
			if (block === 'sdf') {
				if (!KNOWN_SDF_OPS.has(op)) unknown.add(`sdf:${op}`);
			} else {
				if (!KNOWN_OPS.has(op)) unknown.add(op);
			}
			continue;
		}
		if (body.startsWith('op:')) {
			const opToken = body.slice(3).trim().split(/\s+/)[0] ?? '';
			if (!opToken) continue;
			const op = opToken.toLowerCase();
			if (!KNOWN_OPS.has(op)) unknown.add(op);
			block = 'other';
			continue;
		}
		// Any other `#@key: value` header ends the previous block.
		if (body.includes(':')) block = 'other';
	}
	return [...unknown];
}

function unknownMetaValues(liveObj: string): { badSources: string[]; badTypes: string[]; badSims: string[] } {
	const badSources = new Set<string>();
	const badTypes = new Set<string>();
	const badSims = new Set<string>();
	for (const rawLine of liveObj.split('\n')) {
		const line = rawLine.trim();
		if (!line.startsWith('#@')) continue;
		const body = line.slice(2).trim();
		if (body.startsWith('source:')) {
			const v = body.slice('source:'.length).trim().toLowerCase();
			if (v && !KNOWN_SOURCES.has(v)) badSources.add(v);
			continue;
		}
		if (body.startsWith('type:')) {
			const v = body.slice('type:'.length).trim().toLowerCase();
			if (v && !KNOWN_TYPES.has(v)) badTypes.add(v);
			continue;
		}
		if (body.startsWith('sim:')) {
			const v = body.slice('sim:'.length).trim().toLowerCase();
			if (v && !KNOWN_SIMS.has(v)) badSims.add(v);
		}
	}
	return {
		badSources: [...badSources],
		badTypes: [...badTypes],
		badSims: [...badSims]
	};
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
	const useProcedural = body.useProcedural !== false;
	const kernelDefault = body.kernelDefault === 'cadquery' ? 'cadquery' : 'auto';
	const rawHistory = body.history ?? [];
	const history: ChatCompletionMessage[] = wireHistoryToMessages(rawHistory);

	let rawLlm: string;
	try {
		rawLlm = await requestLiveObjFromLlm(userMessage, history, model, { imageDataUrl: imageUrl, useProcedural });
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `LLM failed: ${message}`);
	}

	const liveObj = stripCodeFences(rawLlm);
	let correctedLiveObj = liveObj;
	if (kernelDefault === 'cadquery') {
		const lines = correctedLiveObj.trim().split('\n');
		const idx = lines.findIndex((l) => l.trim().startsWith('#@kernel_default:'));
		if (idx >= 0) lines[idx] = '#@kernel_default: cadquery';
		else {
			const headerIdx = lines.findIndex((l) => l.trim().startsWith('#@live_obj_version:'));
			if (headerIdx >= 0) lines.splice(headerIdx + 1, 0, '#@kernel_default: cadquery');
			else lines.unshift('#@kernel_default: cadquery');
		}
		correctedLiveObj = `${lines.join('\n')}\n`;
	}
	// Collect every diagnostic from a single run (static lint + executor result)
	// into one list, then do at most one consolidated LLM correction pass.
	const unknownOps = unknownOpsInLiveObj(correctedLiveObj);
	const unknownMeta = unknownMetaValues(correctedLiveObj);

	let executedObj = correctedLiveObj;
	let executorWarnings: string[] = [];
	let executorError: string | undefined;
	try {
		const result = await expandLiveObjWithExecutor(correctedLiveObj);
		executedObj = result.executedObj;
		executorWarnings = result.warnings;
	} catch (e) {
		executorError = e instanceof Error ? e.message : String(e);
	}

	const issues = collectSceneIssues({
		unknownOps,
		unknownMeta,
		executorWarnings,
		executorError
	});

	if (issues.length > 0) {
		const correctionPrompt = buildCorrectionPrompt(issues);
		try {
			const correctedRaw = await requestLiveObjFromLlm(
				correctionPrompt,
				[...history, { role: 'assistant', content: correctedLiveObj }],
				model
			);
			const retryLiveObj = stripCodeFences(correctedRaw);
			try {
				const retryResult = await expandLiveObjWithExecutor(retryLiveObj);
				return json({
					liveObj: retryLiveObj,
					rawLlm,
					executedObj: retryResult.executedObj,
					executorWarning: `Auto-corrected after first pass:\n- ${issues.join('\n- ')}`,
					executorWarnings: retryResult.warnings
				});
			} catch (retryErr) {
				// Retry execution also failed; fall through with first-pass output.
				executorError = retryErr instanceof Error ? retryErr.message : String(retryErr);
			}
		} catch {
			// Correction LLM call failed; fall through with first-pass output.
		}
	}

	const firstPassBanner = issues.length > 0 ? `First-pass issues:\n- ${issues.join('\n- ')}` : undefined;
	return json({
		liveObj: correctedLiveObj,
		rawLlm,
		executedObj,
		...(executorError || firstPassBanner
			? { executorWarning: [executorError, firstPassBanner].filter(Boolean).join('\n\n') }
			: {}),
		...(executorWarnings.length > 0 ? { executorWarnings } : {})
	});
};

function collectSceneIssues(args: {
	unknownOps: string[];
	unknownMeta: { badSources: string[]; badTypes: string[]; badSims: string[] };
	executorWarnings: string[];
	executorError: string | undefined;
}): string[] {
	const issues: string[] = [];
	if (args.unknownOps.length > 0) issues.push(`unknown ops: ${args.unknownOps.join(', ')}`);
	if (args.unknownMeta.badSources.length > 0) issues.push(`unknown source values: ${args.unknownMeta.badSources.join(', ')}`);
	if (args.unknownMeta.badTypes.length > 0) issues.push(`unknown type values: ${args.unknownMeta.badTypes.join(', ')}`);
	if (args.unknownMeta.badSims.length > 0) issues.push(`unknown sim values: ${args.unknownMeta.badSims.join(', ')}`);
	for (const w of args.executorWarnings) issues.push(`executor warning: ${w}`);
	if (args.executorError) issues.push(`executor error: ${args.executorError.split('\n').slice(0, 8).join(' | ')}`);
	return issues;
}

function buildCorrectionPrompt(issues: string[]): string {
	return [
		'Rewrite the previous Live OBJ so the executor runs cleanly. Preserve intent, object IDs, and dimensions.',
		'Fix every issue listed below in a single revision. Do not introduce new objects unless required to resolve an issue.',
		'Use only supported ops. Use #@ops: (never #@op: or #@op_experimental).',
		'If a missing anchor is reported, either add a valid #@anchors block on the referenced assembly or replace the anchor() reference with concrete coordinates.',
		'If unsupported ops are reported, replace them with supported equivalents.',
		'',
		'Issues to fix:',
		...issues.map((i) => `- ${i}`)
	].join('\n');
}
