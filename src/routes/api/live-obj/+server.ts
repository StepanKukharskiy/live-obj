import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import type { ChatCompletionMessage } from '$lib/server/llm/chat';
import {
	DEFAULT_LIVE_OBJ_MODEL,
	requestLiveObjAssistantMessageFromLlm,
	requestLiveObjFromLlm,
	requestLiveObjSurgicalPatchFromLlm
} from '$lib/server/llm/liveObjChat';
import { withLlmRequestOverrides } from '$lib/server/llm/chat';
import { expandLiveObjWithExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';
import {
	applyLiveObjSurgicalPatch,
	parseLiveObjSurgicalPatch
} from '$lib/server/liveObj/surgicalPatch';

type WireHistoryItem = {
	role: string;
	content: string;
	imageUrl?: string;
};

type Body = {
	userMessage?: string;
	imageUrl?: string;
	history?: WireHistoryItem[];
	currentLiveObj?: string;
	isIterativeEdit?: boolean;
	currentSceneMode?: 'live_obj' | 'raw_obj';
	model?: string;
	apiKey?: string;
	apiUrl?: string;
	provider?: string;
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
const KNOWN_SIMS = new Set(['cellular_automata', 'cellular_automata_instances', 'differential_growth', 'boids']);

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

function latestAssistantLiveObj(items: WireHistoryItem[]): string {
	for (const item of [...items].reverse()) {
		if (item.role !== 'assistant') continue;
		const content = item.content?.trim();
		if (content) return content;
	}
	return '';
}

function objectNamesFromLiveObj(sourceText: string): string[] {
	const names = [...sourceText.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1]);
	return [...new Set(names)];
}

function allowsExistingObjectRemoval(userMessage: string): boolean {
	return /\b(remove|delete|erase|drop|replace|rebuild|rename|convert|turn\s+.+\s+into)\b/i.test(userMessage);
}

function assertSurgicalPatchPreservesExistingObjects(
	userMessage: string,
	beforeLiveObj: string,
	afterLiveObj: string
): void {
	if (allowsExistingObjectRemoval(userMessage)) return;
	const afterNames = new Set(objectNamesFromLiveObj(afterLiveObj));
	const missing = objectNamesFromLiveObj(beforeLiveObj).filter((name) => !afterNames.has(name));
	if (missing.length === 0) return;
	throw new Error(
		`Surgical edit removed or renamed existing object IDs (${missing.slice(0, 8).join(', ')}). Preserve existing object IDs and add new objects with new IDs.`
	);
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
	const currentLiveObj = stripCodeFences(body.currentLiveObj ?? latestAssistantLiveObj(rawHistory) ?? '');
	const useSurgicalEdit =
		useProcedural && body.isIterativeEdit === true && currentLiveObj.trim().length > 0;

	let rawLlm: string;
	let correctedLiveObj: string;
	let editMode: 'surgical' | 'rewrite' = useSurgicalEdit ? 'surgical' : 'rewrite';
	let surgicalEditSummary: string | undefined;
	let surgicalEditCount: number | undefined;
	const reqApiKey = body.apiKey?.trim() || undefined;
	const reqApiUrl = body.apiUrl?.trim() || undefined;
	try {
		if (useSurgicalEdit) {
			const baseLiveObj = applyKernelDefaultHeader(currentLiveObj, kernelDefault);
			const patchResult = await requestAndApplySurgicalPatch({
				userMessage,
				baseLiveObj,
				history,
				model,
				currentSceneMode: body.currentSceneMode === 'raw_obj' ? 'raw_obj' : 'live_obj',
				imageUrl,
				reqApiKey,
				reqApiUrl
			});
			rawLlm = patchResult.rawPatch;
			correctedLiveObj = patchResult.liveObj;
			surgicalEditSummary = patchResult.summary;
			surgicalEditCount = patchResult.appliedEdits;
		} else {
			rawLlm = await withLlmRequestOverrides(
				reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
				() =>
					requestLiveObjFromLlm(userMessage, history, model, {
						imageDataUrl: imageUrl,
						useProcedural
					})
			);
			correctedLiveObj = stripCodeFences(rawLlm);
			correctedLiveObj = applyKernelDefaultHeader(correctedLiveObj, kernelDefault);
		}
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `${useSurgicalEdit ? 'Surgical edit' : 'LLM'} failed: ${message}`);
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
		if (useSurgicalEdit) {
			try {
				const correctionPatch = await requestAndApplySurgicalPatch({
					userMessage: buildSurgicalCorrectionPrompt(issues),
					baseLiveObj: correctedLiveObj,
					history,
					model,
					currentSceneMode: body.currentSceneMode === 'raw_obj' ? 'raw_obj' : 'live_obj',
					reqApiKey,
					reqApiUrl
				});
				const retryResult = await expandLiveObjWithExecutor(correctionPatch.liveObj);
				const assistantMessage = await requestAssistantChatMessage({
					userMessage,
					previousLiveObj: currentLiveObj,
					nextLiveObj: correctionPatch.liveObj,
					editMode,
					surgicalEditSummary: correctionPatch.summary ?? surgicalEditSummary,
					rawLlm: correctionPatch.rawPatch,
					model,
					reqApiKey,
					reqApiUrl
				});
				return json({
					liveObj: correctionPatch.liveObj,
					rawLlm: correctionPatch.rawPatch,
					executedObj: retryResult.executedObj,
					editMode,
					surgicalEditSummary: correctionPatch.summary ?? surgicalEditSummary,
					surgicalEditCount: (surgicalEditCount ?? 0) + correctionPatch.appliedEdits,
					...(assistantMessage ? { assistantMessage } : {}),
					executorWarning: `Auto-corrected with a surgical patch after first pass:\n- ${issues.join('\n- ')}`,
					executorWarnings: retryResult.warnings
				});
			} catch (retryErr) {
				// Retry execution or correction patch failed; fall through with first-pass output.
				executorError = retryErr instanceof Error ? retryErr.message : String(retryErr);
			}
		} else {
			const correctionPrompt = buildCorrectionPrompt(issues);
			try {
				const correctedRaw = await withLlmRequestOverrides(
					reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
					() =>
						requestLiveObjFromLlm(
							correctionPrompt,
							[...history, { role: 'assistant', content: correctedLiveObj }],
							model
						)
				);
				const retryLiveObj = stripCodeFences(correctedRaw);
				try {
					const retryResult = await expandLiveObjWithExecutor(retryLiveObj);
					const assistantMessage = await requestAssistantChatMessage({
						userMessage,
						previousLiveObj: currentLiveObj,
						nextLiveObj: retryLiveObj,
						editMode,
						rawLlm,
						model,
						reqApiKey,
						reqApiUrl
					});
					return json({
						liveObj: retryLiveObj,
						rawLlm,
						executedObj: retryResult.executedObj,
						editMode,
						...(assistantMessage ? { assistantMessage } : {}),
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
	}

	const firstPassBanner =
		issues.length > 0 ? `First-pass issues:\n- ${issues.join('\n- ')}` : undefined;
	const assistantMessage = await requestAssistantChatMessage({
		userMessage,
		previousLiveObj: currentLiveObj,
		nextLiveObj: correctedLiveObj,
		editMode,
		surgicalEditSummary,
		rawLlm,
		model,
		reqApiKey,
		reqApiUrl
	});
	return json({
		liveObj: correctedLiveObj,
		rawLlm,
		executedObj,
		editMode,
		...(surgicalEditSummary ? { surgicalEditSummary } : {}),
		...(surgicalEditCount != null ? { surgicalEditCount } : {}),
		...(assistantMessage ? { assistantMessage } : {}),
		...(executorError || firstPassBanner
			? { executorWarning: [executorError, firstPassBanner].filter(Boolean).join('\n\n') }
			: {}),
		...(executorWarnings.length > 0 ? { executorWarnings } : {})
	});
};

async function requestAndApplySurgicalPatch(args: {
	userMessage: string;
	baseLiveObj: string;
	history: ChatCompletionMessage[];
	model: string;
	currentSceneMode?: 'live_obj' | 'raw_obj';
	imageUrl?: string;
	reqApiKey?: string;
	reqApiUrl?: string;
}): Promise<{ liveObj: string; rawPatch: string; appliedEdits: number; summary?: string }> {
	const rawPatch = await withLlmRequestOverrides(
		args.reqApiKey || args.reqApiUrl
			? { apiKey: args.reqApiKey, apiUrl: args.reqApiUrl }
			: undefined,
		() =>
			requestLiveObjSurgicalPatchFromLlm(
				args.userMessage,
				args.baseLiveObj,
				args.history,
				args.model,
				{
					imageDataUrl: args.imageUrl,
					currentSceneMode: args.currentSceneMode
				}
			)
	);
	try {
		const applied = applyLiveObjSurgicalPatch(
			args.baseLiveObj,
			parseLiveObjSurgicalPatch(rawPatch)
		);
		assertSurgicalPatchPreservesExistingObjects(args.userMessage, args.baseLiveObj, applied.liveObj);
		return {
			liveObj: applied.liveObj,
			rawPatch,
			appliedEdits: applied.appliedEdits,
			summary: applied.summary
		};
	} catch (firstError) {
		const repairPrompt = buildPatchRepairPrompt(args.userMessage, rawPatch, firstError);
		const repairedRawPatch = await withLlmRequestOverrides(
			args.reqApiKey || args.reqApiUrl
				? { apiKey: args.reqApiKey, apiUrl: args.reqApiUrl }
				: undefined,
			() =>
				requestLiveObjSurgicalPatchFromLlm(
					repairPrompt,
					args.baseLiveObj,
					args.history,
					args.model,
					{
						imageDataUrl: args.imageUrl,
						currentSceneMode: args.currentSceneMode
					}
				)
		);
		const repaired = applyLiveObjSurgicalPatch(
			args.baseLiveObj,
			parseLiveObjSurgicalPatch(repairedRawPatch)
		);
		assertSurgicalPatchPreservesExistingObjects(args.userMessage, args.baseLiveObj, repaired.liveObj);
		return {
			liveObj: repaired.liveObj,
			rawPatch: repairedRawPatch,
			appliedEdits: repaired.appliedEdits,
			summary: repaired.summary
		};
	}
}

async function requestAssistantChatMessage(args: {
	userMessage: string;
	previousLiveObj?: string;
	nextLiveObj: string;
	editMode: 'surgical' | 'rewrite';
	surgicalEditSummary?: string;
	rawLlm?: string;
	model: string;
	reqApiKey?: string;
	reqApiUrl?: string;
}): Promise<string | undefined> {
	try {
		const message = await withLlmRequestOverrides(
			args.reqApiKey || args.reqApiUrl
				? { apiKey: args.reqApiKey, apiUrl: args.reqApiUrl }
				: undefined,
			() =>
				requestLiveObjAssistantMessageFromLlm(
					{
						userMessage: args.userMessage,
						previousLiveObj: args.previousLiveObj,
						nextLiveObj: args.nextLiveObj,
						editMode: args.editMode,
						surgicalEditSummary: args.surgicalEditSummary,
						rawLlm: args.rawLlm
					},
					args.model
				)
		);
		return message || undefined;
	} catch {
		return undefined;
	}
}

function applyKernelDefaultHeader(sceneText: string, kernelDefault: 'auto' | 'cadquery'): string {
	if (kernelDefault !== 'cadquery') return sceneText;
	const raw = sceneText.trim();
	if (!raw) return sceneText;
	const lines = raw.split('\n');
	const idx = lines.findIndex((l) => l.trim().startsWith('#@kernel_default:'));
	if (idx >= 0) {
		lines[idx] = '#@kernel_default: cadquery';
		return `${lines.join('\n')}\n`;
	}
	const headerIdx = lines.findIndex((l) => l.trim().startsWith('#@live_obj_version:'));
	if (headerIdx >= 0) lines.splice(headerIdx + 1, 0, '#@kernel_default: cadquery');
	else lines.unshift('#@kernel_default: cadquery');
	return `${lines.join('\n')}\n`;
}

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

function buildSurgicalCorrectionPrompt(issues: string[]): string {
	return [
		'Apply a surgical correction patch to the current Live OBJ so the executor runs cleanly.',
		'Preserve unrelated text exactly. Fix every issue listed below in the smallest exact edits possible.',
		'Use only supported ops. Use #@ops: lists, never #@op: or #@op_experimental.',
		'If a missing anchor is reported, either add a valid #@anchors entry on the referenced assembly or replace the anchor() reference with concrete coordinates.',
		'',
		'Issues to fix:',
		...issues.map((i) => `- ${i}`)
	].join('\n');
}

function buildPatchRepairPrompt(
	originalRequest: string,
	failedPatch: string,
	failure: unknown
): string {
	const message = failure instanceof Error ? failure.message : String(failure);
	return [
		'Your previous surgical JSON patch could not be applied to the current Live OBJ.',
		`Apply the original user request with a corrected surgical JSON patch: ${originalRequest}`,
		'',
		`Patch failure: ${message}`,
		'',
		'Previous failed patch:',
		failedPatch,
		'',
		'Return only a corrected JSON patch. Every find string must match exactly once.'
	].join('\n');
}
