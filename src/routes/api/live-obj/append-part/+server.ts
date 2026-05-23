import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { DEFAULT_LIVE_OBJ_MODEL, requestLiveObjPartFromLlm } from '$lib/server/llm/liveObjChat';
import { withLlmRequestOverrides } from '$lib/server/llm/chat';
import type { TokenUsage } from '$lib/server/llm/chat';
import {
	expandLiveObjWithExecutor,
	expandRawObjWithPostExecutor,
	stripCodeFences
} from '$lib/server/liveObj/pipeline';
import {
	appendGeneratedPart,
	summarizeLiveObjForPlanning,
	validateLiveObj,
	type IterativePartSpec,
	type IterativeScenePlan
} from '$lib/server/liveObj/iterative';
import { validateRawPostSource } from '$lib/liveObj/rawPostValidation';

type Body = {
	userMessage?: string;
	imageUrl?: string;
	imageUrls?: string[];
	currentLiveObj?: string;
	plan?: IterativeScenePlan;
	part?: IterativePartSpec;
	partId?: string;
	model?: string;
	apiKey?: string;
	apiUrl?: string;
	useProcedural?: boolean;
};

function normalizeImageUrls(...groups: Array<string | string[] | undefined>): string[] {
	const urls = groups
		.flatMap((group) => (Array.isArray(group) ? group : group ? [group] : []))
		.map((url) => url.trim())
		.filter(Boolean);
	return [...new Set(urls)];
}

function resolvePart(body: Body): IterativePartSpec {
	if (body.part) return body.part;
	const id = body.partId?.trim();
	if (!id || !body.plan?.parts) throw new Error('part or partId with plan.parts is required');
	const part = body.plan.parts.find((candidate) => candidate.id === id);
	if (!part) throw new Error(`No part with id '${id}' found in plan`);
	return part;
}

function summarizeTokenUsage(usages: TokenUsage[]): TokenUsage | undefined {
	if (usages.length === 0) return undefined;
	const sum = (key: keyof TokenUsage) => {
		const values = usages
			.map((usage) => usage[key])
			.filter((value): value is number => typeof value === 'number');
		return values.length ? values.reduce((a, b) => a + b, 0) : undefined;
	};
	return {
		...(sum('promptTokens') != null ? { promptTokens: sum('promptTokens') } : {}),
		...(sum('completionTokens') != null ? { completionTokens: sum('completionTokens') } : {}),
		...(sum('totalTokens') != null ? { totalTokens: sum('totalTokens') } : {}),
		...(sum('reasoningTokens') != null ? { reasoningTokens: sum('reasoningTokens') } : {}),
		...(sum('cachedTokens') != null ? { cachedTokens: sum('cachedTokens') } : {})
	};
}

function applyRawPostPartValidation(
	validation: ReturnType<typeof validateLiveObj>,
	rawPart: string,
	useProcedural: boolean
): ReturnType<typeof validateLiveObj> {
	if (useProcedural) return validation;
	const rawPostValidation = validateRawPostSource(rawPart);
	validation.errors.push(
		...rawPostValidation.errors.map((message) => `raw-post validation error: ${message}`)
	);
	validation.warnings.push(
		...rawPostValidation.warnings.map((message) => `raw-post validation warning: ${message}`)
	);
	validation.valid = validation.errors.length === 0;
	return validation;
}

export const POST: RequestHandler = async ({ request }) => {
	let body: Body;
	try {
		body = (await request.json()) as Body;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const currentLiveObj = stripCodeFences(body.currentLiveObj ?? '');
	const userMessage = body.userMessage?.trim() || body.plan?.scene || 'Generate the requested part';
	const imageUrls = normalizeImageUrls(body.imageUrls, body.imageUrl);
	const model = body.model?.trim() || DEFAULT_LIVE_OBJ_MODEL;
	const reqApiKey = body.apiKey?.trim() || undefined;
	const reqApiUrl = body.apiUrl?.trim() || undefined;
	const useProcedural = body.useProcedural !== false;
	let part: IterativePartSpec;
	try {
		part = resolvePart(body);
	} catch (e) {
		throw error(400, e instanceof Error ? e.message : String(e));
	}

	const currentLiveObjSummary = summarizeLiveObjForPlanning(currentLiveObj);
	try {
		const usages: TokenUsage[] = [];
		const rawAttempts: string[] = [];
		const requestPart = async (repairHint = '') => {
			const llmResult = await withLlmRequestOverrides(
				reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
				() =>
					requestLiveObjPartFromLlm(
						{
							userMessage: repairHint
								? `${userMessage}\n\nRepair instruction for this part:\n${repairHint}`
								: userMessage,
							part,
							plan: body.plan,
							currentLiveObjSummary
						},
						model,
						{ imageDataUrls: imageUrls, useProcedural }
					)
			);
			if (llmResult.usage) usages.push(llmResult.usage);
			rawAttempts.push(llmResult.content);
			return stripCodeFences(llmResult.content);
		};

		let rawPart = await requestPart();
		let appended: ReturnType<typeof appendGeneratedPart>;
		try {
			appended = appendGeneratedPart(currentLiveObj, rawPart);
		} catch (firstError) {
			rawPart = await requestPart(
				[
					'Your previous OBJ part was invalid and could not be appended.',
					`Append error: ${firstError instanceof Error ? firstError.message : String(firstError)}`,
					'Return the same requested part again, but fix OBJ face indices.',
					'Every f line must use local indices that reference vertices in this returned part only.',
					'If a face references vertex 60, this returned part must define at least 60 local vertices; otherwise renumber faces to the local vertex range.',
					'Previous invalid output:',
					rawPart
				].join('\n')
			);
			appended = appendGeneratedPart(currentLiveObj, rawPart);
		}

		let validation = applyRawPostPartValidation(
			validateLiveObj(appended.liveObj, currentLiveObj),
			rawPart,
			useProcedural
		);
		if (!validation.valid) {
			rawPart = await requestPart(
				[
					'Your previous OBJ part appended but failed validation.',
					`Validation errors: ${validation.errors.join('; ')}`,
					'Return the same requested part again as valid OBJ/Live OBJ only.',
					'Use a unique object name, include vertices, and ensure all faces reference existing local vertices.',
					'Every raw mesh object/group with vertices must include faces. Do not emit vertices-only logs, rings, supports, lattices, or usemtl-only groups.',
					'If you model logs or beams as rings/sections, connect each adjacent section with side faces and cap the ends.',
					'Previous invalid output:',
					rawPart
				].join('\n')
			);
			appended = appendGeneratedPart(currentLiveObj, rawPart);
			validation = applyRawPostPartValidation(
				validateLiveObj(appended.liveObj, currentLiveObj),
				rawPart,
				useProcedural
			);
		}
		if (!validation.valid) {
			return json(
				{
					liveObj: appended.liveObj,
					partObj: appended.normalizedPart,
					rawLlm: rawAttempts.join('\n\n# --- repair attempt ---\n\n'),
					validation,
					currentLiveObjSummary,
					...(summarizeTokenUsage(usages) ? { llmUsage: summarizeTokenUsage(usages) } : {})
				},
				{ status: 422 }
			);
		}

		let executedObj = appended.liveObj;
		let executorWarnings: string[] = [];
		try {
			const executed = useProcedural
				? await expandLiveObjWithExecutor(appended.liveObj)
				: await expandRawObjWithPostExecutor(appended.liveObj);
			executedObj = executed.executedObj;
			executorWarnings = executed.warnings;
		} catch (e) {
			validation.warnings.push(
				`Executor failed after append: ${e instanceof Error ? e.message : String(e)}`
			);
		}

		return json({
			liveObj: appended.liveObj,
			partObj: appended.normalizedPart,
			rawLlm: rawAttempts.join('\n\n# --- repair attempt ---\n\n'),
			executedObj,
			validation,
			executorWarnings,
			currentLiveObjSummary,
			...(summarizeTokenUsage(usages) ? { llmUsage: summarizeTokenUsage(usages) } : {})
		});
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `Append part failed: ${message}`);
	}
};
