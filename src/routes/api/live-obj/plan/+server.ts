import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { DEFAULT_LIVE_OBJ_MODEL, requestLiveObjPartPlanFromLlm } from '$lib/server/llm/liveObjChat';
import { withLlmRequestOverrides } from '$lib/server/llm/chat';
import {
	parseJsonObject,
	summarizeLiveObjForPlanning,
	type IterativeScenePlan
} from '$lib/server/liveObj/iterative';
import { stripCodeFences } from '$lib/server/liveObj/pipeline';

type Body = {
	userMessage?: string;
	imageUrl?: string;
	imageUrls?: string[];
	currentLiveObj?: string;
	model?: string;
	apiKey?: string;
	apiUrl?: string;
};

function normalizeImageUrls(...groups: Array<string | string[] | undefined>): string[] {
	const urls = groups
		.flatMap((group) => (Array.isArray(group) ? group : group ? [group] : []))
		.map((url) => url.trim())
		.filter(Boolean);
	return [...new Set(urls)];
}

function validatePlan(plan: IterativeScenePlan): void {
	if (!plan || typeof plan !== 'object') throw new Error('Plan must be a JSON object');
	if (!Array.isArray(plan.parts) || plan.parts.length === 0) {
		throw new Error('Plan must include a non-empty parts array');
	}
	const ids = new Set<string>();
	for (const [index, part] of plan.parts.entries()) {
		if (!part || typeof part !== 'object') throw new Error(`Part ${index + 1} is invalid`);
		if (!part.id || typeof part.id !== 'string') {
			throw new Error(`Part ${index + 1} is missing a string id`);
		}
		if (ids.has(part.id)) throw new Error(`Duplicate part id: ${part.id}`);
		ids.add(part.id);
	}
}

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

	const model = body.model?.trim() || DEFAULT_LIVE_OBJ_MODEL;
	const currentLiveObj = stripCodeFences(body.currentLiveObj ?? '');
	const currentLiveObjSummary = summarizeLiveObjForPlanning(currentLiveObj);
	const reqApiKey = body.apiKey?.trim() || undefined;
	const reqApiUrl = body.apiUrl?.trim() || undefined;

	try {
		const llmResult = await withLlmRequestOverrides(
			reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
			() =>
				requestLiveObjPartPlanFromLlm(userMessage, model, {
					imageDataUrls: imageUrls,
					currentLiveObjSummary
				})
		);
		const plan = parseJsonObject<IterativeScenePlan>(llmResult.content);
		validatePlan(plan);
		return json({
			plan,
			rawLlm: llmResult.content,
			...(llmResult.usage ? { llmUsage: llmResult.usage } : {}),
			currentLiveObjSummary
		});
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `Iterative plan failed: ${message}`);
	}
};
