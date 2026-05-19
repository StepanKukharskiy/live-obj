import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import type { ChatCompletionMessage, TokenUsage } from '$lib/server/llm/chat';
import {
	DEFAULT_LIVE_OBJ_MODEL,
	requestLiveObjAssistantMessageFromLlm,
	requestLiveObjFromLlm,
	requestLiveObjSurgicalPatchFromLlm
} from '$lib/server/llm/liveObjChat';
import { withLlmRequestOverrides } from '$lib/server/llm/chat';
import {
	expandLiveObjWithExecutor,
	expandRawObjWithPostExecutor,
	stripCodeFences
} from '$lib/server/liveObj/pipeline';
import {
	applyLiveObjSurgicalPatch,
	parseLiveObjSurgicalPatch
} from '$lib/server/liveObj/surgicalPatch';
import { normalizeRawPostHeader } from '$lib/liveObj/rawPostHeader';
import { rawPostValidationIssues, validateRawPostSource } from '$lib/liveObj/rawPostValidation';

type WireHistoryItem = {
	role: string;
	content: string;
	imageUrl?: string;
	imageUrls?: string[];
};

type Body = {
	userMessage?: string;
	imageUrl?: string;
	imageUrls?: string[];
	history?: WireHistoryItem[];
	currentLiveObj?: string;
	isIterativeEdit?: boolean;
	currentSceneMode?: 'live_obj' | 'raw_obj';
	model?: string;
	apiKey?: string;
	apiUrl?: string;
	provider?: string;
	useProcedural?: boolean;
	targetObjectId?: string;
	kernelDefault?: 'auto' | 'cadquery';
};

type TokenUsageSummary = {
	records: TokenUsage[];
	promptTokens?: number;
	completionTokens?: number;
	totalTokens?: number;
	reasoningTokens?: number;
	cachedTokens?: number;
};

const KNOWN_OPS = new Set([
	'transform',
	'mirror',
	'array',
	'radial_array',
	'bevel',
	'smooth',
	'subdivide',
	'remesh',
	'simplify',
	'displace',
	'bend',
	'twist',
	'taper',
	'sweep',
	'thicken',
	'skin',
	'loft',
	'boolean',
	'mesh_from_sdf',
	'collision',
	'snap',
	'anchor',
	'attach',
	'constraint',
	'material',
	'tag',
	'trace_paths',
	'sdf_tubes',
	'voxelize',
	'mesh_from_volume',
	'tread',
	'union',
	'subtract',
	'intersect',
	'chamfer',
	'shell',
	'offset'
]);
// Ops valid inside `#@sdf:` blocks. SDF primitive/modifier ops are disjoint
// from top-level `#@ops:` ops, so we must not flag them when encountered under
// a `#@sdf:` section.
const KNOWN_SDF_OPS = new Set([
	'sphere',
	'box',
	'cylinder',
	'capsule',
	'torus',
	'cone',
	'plane',
	'union',
	'subtract',
	'intersect',
	'smooth_union',
	'repeat',
	'twist',
	'bend',
	'displace',
	'noise_displace',
	'mesh_from_sdf'
]);
const KNOWN_RECIPE_OPS = new Set([
	'boundary',
	'offset',
	'infill',
	'path_formula',
	'formula_path',
	'path_field',
	'curve',
	'points',
	'field',
	'vector_field',
	'trace_field',
	'field_trace',
	'trace',
	'module',
	'socket',
	'grid',
	'scatter',
	'scatter_points',
	'wfc',
	'wave_function_collapse',
	'iterate',
	'surface_formula',
	'formula_surface',
	'ribbon_formula',
	'ribbon',
	'perforate_surface',
	'surface_perforation',
	'perforate',
	'panelize_surface',
	'panelize',
	'emit_surface',
	'surface',
	'emit_tubes',
	'tubes',
	'emit_volume',
	'volume',
	'instance',
	'instances',
	'emit_instances',
	'emit_mesh',
	'emit_panels'
]);
const KNOWN_POST_OPS = new Set([
	'transform',
	'symmetrize',
	'mirror',
	'array',
	'deform',
	'subdivide',
	'smooth',
	'simplify',
	'snap_to_ground',
	'center_origin',
	'material',
	'tag'
]);
const KNOWN_SOURCES = new Set([
	'procedural',
	'llm_mesh',
	'assembly',
	'sdf',
	'simulation',
	'recipe'
]);
const KNOWN_TYPES = new Set([
	'box',
	'cylinder',
	'surface_grid',
	'heightfield',
	'curve',
	'sweep',
	'mesh',
	'extrude',
	'revolve',
	'lathe',
	'loft',
	'cone',
	'sphere'
]);
const KNOWN_SIMS = new Set([
	'cellular_automata',
	'cellular_automata_instances',
	'differential_growth',
	'differential_growth_stack',
	'boids',
	'flow_field'
]);

function normalizeImageUrls(...groups: Array<string | string[] | undefined>): string[] {
	const urls = groups
		.flatMap((group) => (Array.isArray(group) ? group : group ? [group] : []))
		.map((url) => url.trim())
		.filter(Boolean);
	return [...new Set(urls)];
}

function summarizeTokenUsage(
	records: Array<TokenUsage | undefined>
): TokenUsageSummary | undefined {
	const clean = records.filter((record): record is TokenUsage => Boolean(record));
	if (clean.length === 0) return undefined;
	const sum = (key: keyof TokenUsage): number | undefined => {
		const total = clean.reduce((acc, record) => {
			const value = record[key];
			return typeof value === 'number' ? acc + value : acc;
		}, 0);
		return total > 0 ? total : undefined;
	};
	return {
		records: clean,
		...(sum('promptTokens') != null ? { promptTokens: sum('promptTokens') } : {}),
		...(sum('completionTokens') != null ? { completionTokens: sum('completionTokens') } : {}),
		...(sum('totalTokens') != null ? { totalTokens: sum('totalTokens') } : {}),
		...(sum('reasoningTokens') != null ? { reasoningTokens: sum('reasoningTokens') } : {}),
		...(sum('cachedTokens') != null ? { cachedTokens: sum('cachedTokens') } : {})
	};
}

function unknownOpsInLiveObj(liveObj: string): string[] {
	const unknown = new Set<string>();
	// Track which `#@` block the current `#@ - …` line belongs to so SDF ops
	// don't get flagged as if they were top-level mesh ops.
	let block:
		| 'ops'
		| 'sdf'
		| 'recipe'
		| 'post'
		| 'anchors'
		| 'params'
		| 'placement'
		| 'controls'
		| 'other' = 'other';
	for (const rawLine of liveObj.split('\n')) {
		const line = rawLine.trim();
		if (!line.startsWith('#@')) {
			// A non-`#@` line (e.g. `o foo`, blank line, `v`/`f`) terminates any
			// continuation block.
			if (line.length === 0 || !line.startsWith('#')) block = 'other';
			continue;
		}
		const body = line.slice(2).trim();
		if (body.startsWith('ops:')) {
			block = 'ops';
			continue;
		}
		if (body.startsWith('sdf:')) {
			block = 'sdf';
			continue;
		}
		if (body.startsWith('recipe:')) {
			block = 'recipe';
			continue;
		}
		if (body.startsWith('post:')) {
			block = 'post';
			continue;
		}
		if (body.startsWith('post ')) {
			const opToken = body.slice('post '.length).trim().split(/\s+/)[0] ?? '';
			if (opToken) {
				const op = opToken.toLowerCase();
				if (!KNOWN_POST_OPS.has(op)) unknown.add(`post:${op}`);
			}
			block = 'other';
			continue;
		}
		if (body.startsWith('anchors:')) {
			block = 'anchors';
			continue;
		}
		if (body.startsWith('params:')) {
			block = 'params';
			continue;
		}
		if (body.startsWith('placement:')) {
			block = 'placement';
			continue;
		}
		if (body.startsWith('controls:')) {
			block = 'controls';
			continue;
		}
		if (body.startsWith('-')) {
			if (
				block === 'anchors' ||
				block === 'params' ||
				block === 'placement' ||
				block === 'controls'
			)
				continue;
			const opToken = body.slice(1).trim().split(/\s+/)[0] ?? '';
			if (!opToken) continue;
			const op = opToken.toLowerCase();
			if (block === 'sdf') {
				if (!KNOWN_SDF_OPS.has(op)) unknown.add(`sdf:${op}`);
			} else if (block === 'recipe') {
				if (!KNOWN_RECIPE_OPS.has(op)) unknown.add(`recipe:${op}`);
			} else if (block === 'post') {
				if (!KNOWN_POST_OPS.has(op)) unknown.add(`post:${op}`);
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

function unknownMetaValues(liveObj: string): {
	badSources: string[];
	badTypes: string[];
	badSims: string[];
} {
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
			const imgs = normalizeImageUrls(m.imageUrls, m.imageUrl);
			if (imgs.length > 0) {
				const text =
					m.content?.trim() || 'Generate or update the Live OBJ scene from this reference image.';
				return {
					role: 'user',
					content: [
						{ type: 'text', text },
						...imgs.map((url) => ({
							type: 'image_url' as const,
							image_url: { url, detail: 'low' as const }
						}))
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
	return /\b(remove|delete|erase|drop|replace|rebuild|rename|convert|turn\s+.+\s+into)\b/i.test(
		userMessage
	);
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
	const imageUrls = normalizeImageUrls(body.imageUrls, body.imageUrl);
	if (!userMessage && imageUrls.length === 0) {
		throw error(400, 'userMessage or imageUrl/imageUrls is required');
	}

	const model = (body.model?.trim() || DEFAULT_LIVE_OBJ_MODEL) as string;
	const useProcedural = body.useProcedural !== false;
	const kernelDefault = body.kernelDefault === 'cadquery' ? 'cadquery' : 'auto';
	const rawHistory = body.history ?? [];
	const history: ChatCompletionMessage[] = wireHistoryToMessages(rawHistory);
	const currentLiveObj = stripCodeFences(
		body.currentLiveObj ?? latestAssistantLiveObj(rawHistory) ?? ''
	);
	const useSurgicalEdit = body.isIterativeEdit === true && currentLiveObj.trim().length > 0;

	let rawLlm: string;
	let correctedLiveObj: string;
	const editMode: 'surgical' | 'rewrite' = useSurgicalEdit ? 'surgical' : 'rewrite';
	let surgicalEditSummary: string | undefined;
	let surgicalEditCount: number | undefined;
	const llmUsages: TokenUsage[] = [];
	const recordUsage = (usage: TokenUsage | undefined) => {
		if (!usage) return;
		llmUsages.push(usage);
	};
	const recordUsages = (usages: TokenUsage[]) => {
		for (const usage of usages) recordUsage(usage);
	};
	const reqApiKey = body.apiKey?.trim() || undefined;
	const reqApiUrl = body.apiUrl?.trim() || undefined;
	try {
		if (useSurgicalEdit) {
			const baseLiveObj = useProcedural
				? applyKernelDefaultHeader(currentLiveObj, kernelDefault)
				: currentLiveObj;
			const patchResult = await requestAndApplySurgicalPatch({
				userMessage,
				baseLiveObj,
				history,
				model,
				currentSceneMode: body.currentSceneMode === 'raw_obj' ? 'raw_obj' : 'live_obj',
				targetObjectId: body.targetObjectId,
				imageUrls,
				reqApiKey,
				reqApiUrl
			});
			rawLlm = patchResult.rawPatch;
			correctedLiveObj = useProcedural
				? patchResult.liveObj
				: normalizeRawPostHeader(patchResult.liveObj);
			surgicalEditSummary = patchResult.summary;
			surgicalEditCount = patchResult.appliedEdits;
			recordUsages(patchResult.usages);
		} else {
			const llmResult = await withLlmRequestOverrides(
				reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
				() =>
					requestLiveObjFromLlm(userMessage, history, model, {
						imageDataUrls: imageUrls,
						useProcedural
					})
			);
			rawLlm = llmResult.content;
			recordUsage(llmResult.usage);
			correctedLiveObj = stripCodeFences(rawLlm);
			correctedLiveObj = useProcedural
				? applyKernelDefaultHeader(correctedLiveObj, kernelDefault)
				: normalizeRawPostHeader(correctedLiveObj, { sourcePrompt: userMessage });
		}
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `${useSurgicalEdit ? 'Surgical edit' : 'LLM'} failed: ${message}`);
	}
	// Collect every diagnostic from a single run (static lint + executor result)
	// into one list, then do at most one consolidated LLM correction pass.
	const unknownOps = unknownOpsInLiveObj(correctedLiveObj);
	const unknownMeta = unknownMetaValues(correctedLiveObj);
	const rawPostValidation = useProcedural ? undefined : validateRawPostSource(correctedLiveObj);

	let executedObj = correctedLiveObj;
	let executorWarnings: string[] = [];
	let executorError: string | undefined;
	try {
		const result = useProcedural
			? await expandLiveObjWithExecutor(correctedLiveObj)
			: await expandRawObjWithPostExecutor(correctedLiveObj);
		executedObj = result.executedObj;
		executorWarnings = result.warnings;
	} catch (e) {
		executorError = e instanceof Error ? e.message : String(e);
	}

	const issues = collectSceneIssues({
		unknownOps,
		unknownMeta,
		rawPostValidationIssues: rawPostValidation ? rawPostValidationIssues(rawPostValidation) : [],
		executorWarnings,
		executorError
	});

	if (issues.length > 0) {
		if (useSurgicalEdit) {
			try {
				const correctionPatch = await requestAndApplySurgicalPatch({
					userMessage: buildSurgicalCorrectionPrompt(issues, useProcedural),
					baseLiveObj: correctedLiveObj,
					history,
					model,
					currentSceneMode: body.currentSceneMode === 'raw_obj' ? 'raw_obj' : 'live_obj',
					targetObjectId: body.targetObjectId,
					reqApiKey,
					reqApiUrl
				});
				recordUsages(correctionPatch.usages);
				const correctionLiveObj = useProcedural
					? correctionPatch.liveObj
					: normalizeRawPostHeader(correctionPatch.liveObj);
				const retryResult = useProcedural
					? await expandLiveObjWithExecutor(correctionLiveObj)
					: await expandRawObjWithPostExecutor(correctionLiveObj);
				const assistantMessage = await requestAssistantChatMessage({
					userMessage,
					previousLiveObj: currentLiveObj,
					nextLiveObj: correctionLiveObj,
					editMode,
					surgicalEditSummary: correctionPatch.summary ?? surgicalEditSummary,
					rawLlm: correctionPatch.rawPatch,
					model,
					reqApiKey,
					reqApiUrl
				});
				recordUsage(assistantMessage?.usage);
				return json({
					liveObj: correctionLiveObj,
					rawLlm: correctionPatch.rawPatch,
					executedObj: retryResult.executedObj,
					...(summarizeTokenUsage(llmUsages) ? { llmUsage: summarizeTokenUsage(llmUsages) } : {}),
					editMode,
					surgicalEditSummary: correctionPatch.summary ?? surgicalEditSummary,
					surgicalEditCount: (surgicalEditCount ?? 0) + correctionPatch.appliedEdits,
					...(assistantMessage?.content ? { assistantMessage: assistantMessage.content } : {}),
					executorWarning: `Auto-corrected with a surgical patch after first pass:\n- ${issues.join('\n- ')}`,
					executorWarnings: retryResult.warnings
				});
			} catch (retryErr) {
				// Retry execution or correction patch failed; fall through with first-pass output.
				executorError = retryErr instanceof Error ? retryErr.message : String(retryErr);
			}
		} else {
			const correctionPrompt = buildCorrectionPrompt(issues, useProcedural);
			try {
				const correctedResult = await withLlmRequestOverrides(
					reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
					() =>
						requestLiveObjFromLlm(
							correctionPrompt,
							[...history, { role: 'assistant', content: correctedLiveObj }],
							model,
							{ useProcedural }
						)
				);
				recordUsage(correctedResult.usage);
				const retryLiveObj = useProcedural
					? stripCodeFences(correctedResult.content)
					: normalizeRawPostHeader(stripCodeFences(correctedResult.content), {
							sourcePrompt: userMessage
						});
				try {
					const retryResult = useProcedural
						? await expandLiveObjWithExecutor(retryLiveObj)
						: await expandRawObjWithPostExecutor(retryLiveObj);
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
					recordUsage(assistantMessage?.usage);
					return json({
						liveObj: retryLiveObj,
						rawLlm,
						executedObj: retryResult.executedObj,
						...(summarizeTokenUsage(llmUsages) ? { llmUsage: summarizeTokenUsage(llmUsages) } : {}),
						editMode,
						...(assistantMessage?.content ? { assistantMessage: assistantMessage.content } : {}),
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
	recordUsage(assistantMessage?.usage);
	return json({
		liveObj: correctedLiveObj,
		rawLlm,
		executedObj,
		...(summarizeTokenUsage(llmUsages) ? { llmUsage: summarizeTokenUsage(llmUsages) } : {}),
		editMode,
		...(surgicalEditSummary ? { surgicalEditSummary } : {}),
		...(surgicalEditCount != null ? { surgicalEditCount } : {}),
		...(assistantMessage?.content ? { assistantMessage: assistantMessage.content } : {}),
		...(executorError || firstPassBanner
			? { executorWarning: [executorError, firstPassBanner].filter(Boolean).join('\n\n') }
			: {}),
		...(executorWarnings.length > 0 ? { executorWarnings } : {})
	});
};

function objectBlockByName(sourceText: string, objectId: string): string | undefined {
	const escaped = objectId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = sourceText.match(
		new RegExp(`^\\s*o\\s+${escaped}(?:\\s|$)[\\s\\S]*?(?=^\\s*o\\s+|\\s*$)`, 'm')
	);
	return match?.[0]?.trim();
}

function withTargetObjectContext(
	userMessage: string,
	currentLiveObj: string,
	targetObjectId?: string
): string {
	const target = targetObjectId?.trim();
	if (!target) return userMessage;
	const block = objectBlockByName(currentLiveObj, target);
	return [
		`Selected target object: ${target}`,
		'Apply the user request primarily to this object unless the request explicitly asks for a broader scene edit.',
		block ? `Current selected object block:\n\`\`\`obj\n${block}\n\`\`\`` : '',
		'',
		`User request: ${userMessage}`
	]
		.filter(Boolean)
		.join('\n');
}

async function requestAndApplySurgicalPatch(args: {
	userMessage: string;
	baseLiveObj: string;
	history: ChatCompletionMessage[];
	model: string;
	currentSceneMode?: 'live_obj' | 'raw_obj';
	targetObjectId?: string;
	imageUrl?: string;
	imageUrls?: string[];
	reqApiKey?: string;
	reqApiUrl?: string;
}): Promise<{
	liveObj: string;
	rawPatch: string;
	appliedEdits: number;
	summary?: string;
	usages: TokenUsage[];
}> {
	const imageUrls = normalizeImageUrls(args.imageUrls, args.imageUrl);
	const userMessage = withTargetObjectContext(
		args.userMessage,
		args.baseLiveObj,
		args.targetObjectId
	);
	const patchResult = await withLlmRequestOverrides(
		args.reqApiKey || args.reqApiUrl
			? { apiKey: args.reqApiKey, apiUrl: args.reqApiUrl }
			: undefined,
		() =>
			requestLiveObjSurgicalPatchFromLlm(userMessage, args.baseLiveObj, args.history, args.model, {
				imageDataUrls: imageUrls,
				currentSceneMode: args.currentSceneMode
			})
	);
	const rawPatch = patchResult.content;
	const usages = patchResult.usage ? [patchResult.usage] : [];
	try {
		const applied = applyLiveObjSurgicalPatch(
			args.baseLiveObj,
			parseLiveObjSurgicalPatch(rawPatch)
		);
		assertSurgicalPatchPreservesExistingObjects(userMessage, args.baseLiveObj, applied.liveObj);
		return {
			liveObj: applied.liveObj,
			rawPatch,
			appliedEdits: applied.appliedEdits,
			summary: applied.summary,
			usages
		};
	} catch (firstError) {
		const repairPrompt = buildPatchRepairPrompt(userMessage, rawPatch, firstError);
		const repairedPatchResult = await withLlmRequestOverrides(
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
						imageDataUrls: imageUrls,
						currentSceneMode: args.currentSceneMode
					}
				)
		);
		const repairedRawPatch = repairedPatchResult.content;
		if (repairedPatchResult.usage) usages.push(repairedPatchResult.usage);
		const repaired = applyLiveObjSurgicalPatch(
			args.baseLiveObj,
			parseLiveObjSurgicalPatch(repairedRawPatch)
		);
		assertSurgicalPatchPreservesExistingObjects(userMessage, args.baseLiveObj, repaired.liveObj);
		return {
			liveObj: repaired.liveObj,
			rawPatch: repairedRawPatch,
			appliedEdits: repaired.appliedEdits,
			summary: repaired.summary,
			usages
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
}): Promise<{ content?: string; usage?: TokenUsage } | undefined> {
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
		return {
			...(message.content ? { content: message.content } : {}),
			...(message.usage ? { usage: message.usage } : {})
		};
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
	rawPostValidationIssues?: string[];
	executorWarnings: string[];
	executorError: string | undefined;
}): string[] {
	const issues: string[] = [];
	if (args.unknownOps.length > 0) issues.push(`unknown ops: ${args.unknownOps.join(', ')}`);
	if (args.unknownMeta.badSources.length > 0)
		issues.push(`unknown source values: ${args.unknownMeta.badSources.join(', ')}`);
	if (args.unknownMeta.badTypes.length > 0)
		issues.push(`unknown type values: ${args.unknownMeta.badTypes.join(', ')}`);
	if (args.unknownMeta.badSims.length > 0)
		issues.push(`unknown sim values: ${args.unknownMeta.badSims.join(', ')}`);
	for (const issue of args.rawPostValidationIssues ?? []) issues.push(issue);
	for (const w of args.executorWarnings) issues.push(`executor warning: ${w}`);
	if (args.executorError)
		issues.push(`executor error: ${args.executorError.split('\n').slice(0, 8).join(' | ')}`);
	return issues;
}

function correctionOpInstruction(useProcedural: boolean): string {
	return useProcedural
		? 'Use only supported ops. Use #@ops: (never #@op: or #@op_experimental).'
		: 'For raw-post scenes, preserve raw v/f mesh as source geometry and use #@post: blocks for modifiers. Do not add #@ops or procedural sources.';
}

function buildCorrectionPrompt(issues: string[], useProcedural: boolean): string {
	return [
		'Rewrite the previous Live OBJ so the executor runs cleanly. Preserve intent, object IDs, and dimensions.',
		'Fix every issue listed below in a single revision. Do not introduce new objects unless required to resolve an issue.',
		correctionOpInstruction(useProcedural),
		'If a missing anchor is reported, either add a valid #@anchors block on the referenced assembly or replace the anchor() reference with concrete coordinates.',
		'If unsupported ops are reported, replace them with supported equivalents.',
		'',
		'Issues to fix:',
		...issues.map((i) => `- ${i}`)
	].join('\n');
}

function buildSurgicalCorrectionPrompt(issues: string[], useProcedural: boolean): string {
	return [
		'Apply a surgical correction patch to the current Live OBJ so the executor runs cleanly.',
		'Preserve unrelated text exactly. Fix every issue listed below in the smallest exact edits possible.',
		correctionOpInstruction(useProcedural),
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
