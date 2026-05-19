import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	DEFAULT_LIVE_OBJ_MODEL,
	requestLiveObjPartFromLlm,
	streamLiveObjPartFromLlm
} from '$lib/server/llm/liveObjChat';
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

function addUsageStep(usages: TokenUsage[], usage: TokenUsage | undefined) {
	if (!usage) return;
	usages.push(usage);
}

function countObjVertices(objText: string): number {
	return objText.split('\n').filter((line) => /^\s*v\s+/.test(line)).length;
}

function validationRepairPrompt(
	userMessage: string,
	rawPart: string,
	validationErrors: string[]
): string {
	return [
		userMessage,
		'',
		'Repair instruction for this part:',
		'Your previous OBJ part streamed into the preview but failed validation.',
		`Validation errors: ${validationErrors.join('; ')}`,
		'Return the same requested part again as valid OBJ/Live OBJ only.',
		'Use a unique object name, include vertices, and ensure all visible raw mesh objects include faces.',
		'Every raw mesh object/group with vertices must include faces. Vertices without f lines are invisible and are not acceptable.',
		'If you model a body shell, connect section rings with side faces and cap the ends.',
		'Previous invalid output:',
		rawPart
	].join('\n');
}

function appendRepairPrompt(userMessage: string, rawPart: string, appendError: string): string {
	return [
		userMessage,
		'',
		'Repair instruction for this part:',
		'Your previous streamed response could not be appended as OBJ.',
		`Append error: ${appendError}`,
		'Return the same requested part again as valid OBJ/Live OBJ only.',
		'The response must contain at least one OBJ object line like `o main_body` before any mesh vertices.',
		'Use local face indices starting at 1 for this returned part.',
		'Every visible raw mesh object/group with vertices must include faces.',
		'Previous invalid output:',
		rawPart
	].join('\n');
}

function offsetFaceLine(line: string, vertexOffset: number): string {
	if (vertexOffset <= 0 || !/^\s*f\s+/.test(line)) return line;
	return line.replace(/^(\s*f\s+)(.*)$/, (_match, prefix: string, rest: string) => {
		const tokens = rest.split(/\s+/).filter(Boolean);
		return `${prefix}${tokens
			.map((token) => {
				const [vertexIndex, ...suffix] = token.split('/');
				const index = Number(vertexIndex);
				if (!Number.isFinite(index) || index <= 0) return token;
				return [String(index + vertexOffset), ...suffix].join('/');
			})
			.join(' ')}`;
	});
}

function previewableObjLine(rawLine: string): string | null {
	const line = rawLine.trimEnd();
	const trimmed = line.trim();
	if (!trimmed || trimmed.startsWith('```')) return null;
	if (/^(#|o\s+|g\s+|usemtl\s+|mtllib\s+|s\s+|v\s+|vn\s+|vt\s+|f\s+)/.test(trimmed)) {
		return line;
	}
	return null;
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

	const encoder = new TextEncoder();

	return new Response(
		new ReadableStream({
			async start(controller) {
				let closed = false;
				const emit = (payload: Record<string, unknown>) => {
					if (closed) return false;
					try {
						controller.enqueue(encoder.encode(`${JSON.stringify(payload)}\n`));
						return true;
					} catch {
						closed = true;
						return false;
					}
				};
				const heartbeat = setInterval(() => {
					emit({
						type: 'status',
						message: `Still building ${part.id}.`
					});
				}, 10_000);

				const currentLiveObjSummary = summarizeLiveObjForPlanning(currentLiveObj);
				const vertexOffset = countObjVertices(currentLiveObj);
				let lineBuffer = '';
				try {
					emit({
						type: 'status',
						message: `Building ${part.id}.`,
						padding: ' '.repeat(2048)
					});
					const rawAttempts: string[] = [];
					const usages: TokenUsage[] = [];
					const llmResult = await withLlmRequestOverrides(
						reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
						() =>
							streamLiveObjPartFromLlm(
								{
									userMessage,
									part,
									plan: body.plan,
									currentLiveObjSummary
								},
								model,
								{ imageDataUrls: imageUrls, useProcedural },
								(delta) => {
									lineBuffer += delta;
									const lines = lineBuffer.split(/\r?\n/);
									lineBuffer = lines.pop() ?? '';
									for (const rawLine of lines) {
										const line = previewableObjLine(rawLine);
										if (!line) continue;
										emit({
											type: 'preview_line',
											line: offsetFaceLine(line, vertexOffset)
										});
									}
								}
							)
					);
					addUsageStep(usages, llmResult.usage);
					rawAttempts.push(llmResult.content);
					const trailingLine = previewableObjLine(lineBuffer);
					if (trailingLine) {
						emit({
							type: 'preview_line',
							line: offsetFaceLine(trailingLine, vertexOffset)
						});
					}

					let rawPart = stripCodeFences(llmResult.content);
					let appended: ReturnType<typeof appendGeneratedPart>;
					try {
						appended = appendGeneratedPart(currentLiveObj, rawPart);
					} catch (appendError) {
						emit({
							type: 'status',
							message: `Repairing ${part.id}.`
						});
						const repairResult = await withLlmRequestOverrides(
							reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
							() =>
								requestLiveObjPartFromLlm(
									{
										userMessage: appendRepairPrompt(
											userMessage,
											rawPart,
											appendError instanceof Error ? appendError.message : String(appendError)
										),
										part,
										plan: body.plan,
										currentLiveObjSummary
									},
									model,
									{ imageDataUrls: imageUrls, useProcedural }
								)
						);
						addUsageStep(usages, repairResult.usage);
						rawAttempts.push(repairResult.content);
						rawPart = stripCodeFences(repairResult.content);
						appended = appendGeneratedPart(currentLiveObj, rawPart);
					}
					let validation = validateLiveObj(appended.liveObj, currentLiveObj);
					if (!validation.valid) {
						emit({
							type: 'status',
							message: `Repairing ${part.id}.`
						});
						const repairResult = await withLlmRequestOverrides(
							reqApiKey || reqApiUrl ? { apiKey: reqApiKey, apiUrl: reqApiUrl } : undefined,
							() =>
								requestLiveObjPartFromLlm(
									{
										userMessage: validationRepairPrompt(userMessage, rawPart, validation.errors),
										part,
										plan: body.plan,
										currentLiveObjSummary
									},
									model,
									{ imageDataUrls: imageUrls, useProcedural }
								)
						);
						addUsageStep(usages, repairResult.usage);
						rawAttempts.push(repairResult.content);
						rawPart = stripCodeFences(repairResult.content);
						appended = appendGeneratedPart(currentLiveObj, rawPart);
						validation = validateLiveObj(appended.liveObj, currentLiveObj);
					}
					if (!validation.valid) {
						throw new Error(validation.errors.join('; ') || 'Streamed part failed validation');
					}
					let executedObj = appended.liveObj;
					let executorWarnings: string[] = [];
					try {
						emit({
							type: 'status',
							message: `Executing ${part.id}.`
						});
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
					emit({
						type: 'final',
						liveObj: appended.liveObj,
						partObj: appended.normalizedPart,
						rawLlm: rawAttempts.join('\n\n# --- repair attempt ---\n\n'),
						executedObj,
						validation,
						executorWarnings,
						...(summarizeTokenUsage(usages) ? { llmUsage: summarizeTokenUsage(usages) } : {}),
						currentLiveObjSummary
					});
				} catch (e) {
					emit({
						type: 'error',
						message: e instanceof Error ? e.message : String(e)
					});
				} finally {
					closed = true;
					clearInterval(heartbeat);
					try {
						controller.close();
					} catch {
						// The client may have already closed the stream.
					}
				}
			}
		}),
		{
			headers: {
				'Content-Type': 'application/x-ndjson; charset=utf-8',
				'Cache-Control': 'no-cache, no-transform',
				'X-Accel-Buffering': 'no'
			}
		}
	);
};
