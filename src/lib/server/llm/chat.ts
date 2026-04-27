import { AsyncLocalStorage } from 'node:async_hooks';

const sveltekitPrivateEnvPromise: Promise<Record<string, string | undefined> | null> = import(
	'$env/dynamic/private'
)
	.then(({ env }) => env)
	.catch(() => null);

export interface ChatCompletionMessage {
	role: 'system' | 'user' | 'assistant';
	content: string;
}

export interface RequestChatCompletionOptions {
	messages: ChatCompletionMessage[];
	model?: string;
	temperature?: number;
	maxTokens?: number;
	label?: string;
	metadata?: Record<string, unknown>;
	timeoutMs?: number;
	switchModelOnTimeout?: boolean;
	onAttempt?: (attempt: ChatCompletionAttempt) => void;
}

export interface ChatCompletionResult {
	data: unknown;
	content: string;
}

export interface ChatCompletionAttempt {
	model: string;
	attempt: number;
	status: 'started' | 'succeeded' | 'failed';
	error?: string;
}

type CompletionPayload = {
	choices?: Array<{
		message?: { content?: unknown };
		text?: string | null;
	}>;
	output?: Array<{ content?: Array<{ text?: string | null }> }>;
	output_text?: string | null;
};

const REQUEST_TIMEOUT_MS = 120000;
const MAX_ATTEMPTS = 3;
const RETRIABLE_STATUS_CODES = new Set([408, 429, 500, 502, 503, 504]);
const RATE_LIMIT_STATUS_CODES = new Set([429, 503]);
const DEFAULT_OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions';
const DEFAULT_OPENAI_MODEL = 'gpt-5.4';

const llmRequestOverridesStorage = new AsyncLocalStorage<LlmRequestOverrides>();

type LlmRequestOverrides = {
	apiKey?: string;
	apiUrl?: string;
	model?: string;
};

// Fallback models for Together-compatible routing
const TOGETHER_FALLBACK_MODELS = [
	'Qwen/Qwen3.5-397B-A17B',
	'moonshotai/Kimi-K2.5',
	'meta-llama/Llama-3.3-70B-Instruct-Turbo',
	'mistralai/Mixtral-8x7B-Instruct-v0.1'
];
const INTER_REQUEST_DELAY_MS = 3000;
let llmRequestQueue: Promise<void> = Promise.resolve();
let lastLlmRequestFinishedAt = 0;

function wait(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

async function acquireLlmRequestTurn(): Promise<() => void> {
	const previous = llmRequestQueue.catch(() => undefined);
	let release!: () => void;
	llmRequestQueue = new Promise<void>((resolve) => {
		release = resolve;
	});
	await previous;
	const waitMs = Math.max(0, lastLlmRequestFinishedAt + INTER_REQUEST_DELAY_MS - Date.now());
	if (waitMs > 0) {
		await wait(waitMs);
	}
	return () => {
		lastLlmRequestFinishedAt = Date.now();
		release();
	};
}

function isAbortError(error: unknown): boolean {
	return error instanceof Error && error.name === 'AbortError';
}

function isEmptyResponseError(error: unknown): boolean {
	return error instanceof Error && error.message === 'Empty response from model';
}

function isRetriableError(error: unknown): boolean {
	return isAbortError(error) || isEmptyResponseError(error) || error instanceof TypeError;
}

function isRateLimitError(error: unknown): boolean {
	if (error instanceof Error) {
		const message = error.message.toLowerCase();
		return message.includes('rate limit') || 
			   message.includes('rate_limit_exceeded') || 
			   message.includes('too many requests') ||
			   message.includes('quota exceeded') ||
			   message.includes('usage limit') ||
			   message.includes('model overloaded');
	}
	return false;
}

function isTimeoutError(error: unknown): boolean {
	return error instanceof Error && error.message.includes('timed out');
}

function isInputValidationError(status: number, body: string): boolean {
	return status === 400 && body.toLowerCase().includes('input validation error');
}

function isLengthTruncatedEmptyResponseError(error: unknown): boolean {
	return error instanceof Error && error.message === 'Model exhausted max_tokens before emitting final content';
}

export function withLlmRequestOverrides<T>(overrides: LlmRequestOverrides | undefined, callback: () => Promise<T>): Promise<T> {
	if (!overrides?.apiKey && !overrides?.apiUrl && !overrides?.model) {
		return callback();
	}
	return llmRequestOverridesStorage.run(overrides, callback);
}

function isOpenAiApiUrl(apiUrl: string): boolean {
	return apiUrl.includes('api.openai.com');
}

/**
 * Some OpenAI chat models (GPT-5 line, o-series) reject custom temperature; only the
 * default (1) is allowed. Typical API errors include "Only the default (1) value is
 * supported" or "Unsupported value: 'temperature' does not support 0.1...".
 */
function openAiModelRequiresDefaultTemperatureOnly(model: string): boolean {
	const m = model.trim();
	if (m.startsWith('gpt-5')) return true;
	if (/^o[0-9]/.test(m)) return true;
	return false;
}

function parseFallbackModelList(value: string | undefined): string[] {
	if (!value) return [];
	return value
		.split(',')
		.map((entry) => entry.trim())
		.filter(Boolean);
}

function buildCompletionRequestPayload(input: {
	apiUrl: string;
	model: string;
	messages: ChatCompletionMessage[];
	maxTokens: number;
	temperature: number;
}): Record<string, unknown> {
	const { apiUrl, model, messages, maxTokens, temperature: requested } = input;
	const temperature =
		isOpenAiApiUrl(apiUrl) && openAiModelRequiresDefaultTemperatureOnly(model) ? 1 : requested;
	if (isOpenAiApiUrl(apiUrl)) {
		return {
			model,
			messages,
			max_completion_tokens: maxTokens,
			temperature
		};
	}
	return {
		model,
		messages,
		max_tokens: maxTokens,
		temperature
	};
}

/**
 * Merge `process.env` and SvelteKit private env. Uses `||` so empty strings fall through
 * (SvelteKit populates `$env/dynamic/private` from `.env` even when `process.env` is unset).
 */
function pickString(...candidates: Array<string | undefined>): string {
	for (const c of candidates) {
		if (c != null && String(c).trim() !== '') return String(c).trim();
	}
	return '';
}

async function resolveProviderApiKeys(): Promise<{ togetherApiKey: string; openAiApiKey: string }> {
	const privateEnv = await sveltekitPrivateEnvPromise;
	return {
		togetherApiKey: pickString(process.env.API_KEY, privateEnv?.API_KEY),
		openAiApiKey: pickString(
			process.env.OPENAI_API_KEY,
			privateEnv?.OPENAI_API_KEY,
			process.env.DEFAULT_OPENAI_API_KEY,
			privateEnv?.DEFAULT_OPENAI_API_KEY
		)
	};
}

async function resolveDefaultLlmConfig(): Promise<Required<LlmRequestOverrides>> {
	const privateEnv = await sveltekitPrivateEnvPromise;
	const providerKeys = await resolveProviderApiKeys();
	return {
		apiKey: pickString(providerKeys.togetherApiKey, providerKeys.openAiApiKey),
		apiUrl: pickString(
			process.env.API_URL,
			process.env.OPENAI_API_URL,
			privateEnv?.API_URL,
			privateEnv?.OPENAI_API_URL,
			DEFAULT_OPENAI_API_URL
		),
		model: pickString(
			process.env.MODEL,
			process.env.OPENAI_MODEL,
			privateEnv?.MODEL,
			privateEnv?.OPENAI_MODEL,
			DEFAULT_OPENAI_MODEL
		)
	};
}

export async function hasConfiguredServerLlmAccess(overrides?: LlmRequestOverrides): Promise<boolean> {
	const defaults = await resolveDefaultLlmConfig();
	const apiUrl = overrides?.apiUrl ?? defaults.apiUrl;
	const providerKeys = await resolveProviderApiKeys();
	const apiKey =
		overrides?.apiKey ??
		(isOpenAiApiUrl(apiUrl)
			? providerKeys.openAiApiKey || providerKeys.togetherApiKey
			: providerKeys.togetherApiKey || providerKeys.openAiApiKey || defaults.apiKey);
	return Boolean(apiKey && apiUrl);
}

export async function requestChatCompletion({
	messages,
	model,
	temperature = 0.1,
	maxTokens = 12000,
	label = 'server-chat-completion',
	metadata,
	timeoutMs = REQUEST_TIMEOUT_MS,
	switchModelOnTimeout = false,
	onAttempt
}: RequestChatCompletionOptions): Promise<ChatCompletionResult> {
	const requestOverrides = llmRequestOverridesStorage.getStore();
	const defaultConfig = await resolveDefaultLlmConfig();
	const apiUrl = requestOverrides?.apiUrl ?? defaultConfig.apiUrl;
	const providerKeys = await resolveProviderApiKeys();
	const apiKey =
		requestOverrides?.apiKey ??
		(isOpenAiApiUrl(apiUrl)
			? providerKeys.openAiApiKey || providerKeys.togetherApiKey
			: providerKeys.togetherApiKey || providerKeys.openAiApiKey || defaultConfig.apiKey);
	const configuredModel = requestOverrides?.model ?? defaultConfig.model;
	if (!apiKey) {
		throw new Error(
			'No LLM API key on server. Set OPENAI_API_KEY (or API_KEY for non-OpenAI URLs) in `.env` with no spaces around `=`, and restart the dev server. For OpenAI, use OPENAI_API_KEY and OPENAI_API_URL (or rely on the default https://api.openai.com/v1/chat/completions).'
		);
	}
	if (!apiUrl) {
		throw new Error('API URL not configured (OPENAI_API_URL or API_URL)');
	}

	const fallbackModels = isOpenAiApiUrl(apiUrl)
		? parseFallbackModelList(process.env.OPENAI_FALLBACK_MODELS)
		: TOGETHER_FALLBACK_MODELS;

	let lastError: Error | null = null;
	const modelsToTry = Array.from(
		new Set(
			model
				? [model]
				: [configuredModel || DEFAULT_OPENAI_MODEL, ...fallbackModels]
		)
	);

	for (const currentModel of modelsToTry) {
		for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
			const releaseTurn = await acquireLlmRequestTurn();
			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
			const requestPayload = buildCompletionRequestPayload({
				apiUrl,
				model: currentModel,
				messages,
				maxTokens,
				temperature
			});
			onAttempt?.({
				model: currentModel,
				attempt,
				status: 'started'
			});

		try {
			const response = await fetch(apiUrl, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${apiKey}`
				},
				signal: controller.signal,
				body: JSON.stringify(requestPayload)
			});

			if (!response.ok) {
				const errBody = await response.text().catch(() => response.statusText);
				console.error('[LLM Response Error]', {
					label,
					attempt,
					status: response.status,
					metadata: metadata ?? null,
					body: errBody || response.statusText
				});
				lastError = new Error(`LLM API error (${response.status}): ${errBody || response.statusText}`);
				const hasMoreModels = modelsToTry.indexOf(currentModel) < modelsToTry.length - 1;
				if (attempt < MAX_ATTEMPTS && RETRIABLE_STATUS_CODES.has(response.status)) {
					await wait(200 * attempt);
					continue;
				}
				// If this is a rate limit and we have more models to try, break to next model
				if (RATE_LIMIT_STATUS_CODES.has(response.status) && hasMoreModels) {
					console.log('[LLM Model Fallback]', `Rate limited on ${currentModel}, trying next model`);
					break;
				}
				if (isInputValidationError(response.status, errBody || response.statusText) && hasMoreModels) {
					console.log('[LLM Model Fallback]', `Input validation error on ${currentModel}, trying next model`);
					break;
				}
				throw lastError;
			}

			const data = await response.json();
			const content = extractCompletionContent(data);
			if (!content) {
				console.error('[LLM Empty Response]', {
					label,
					attempt,
					model: currentModel,
					metadata: metadata ?? null,
					payloadSummary: summarizeCompletionPayload(data)
				});
				if (isLengthTruncatedEmptyResponsePayload(data)) {
					throw new Error('Model exhausted max_tokens before emitting final content');
				}
				throw new Error('Empty response from model');
			}
			onAttempt?.({
				model: currentModel,
				attempt,
				status: 'succeeded'
			});

			return { data, content };
		} catch (error) {
			lastError =
				isAbortError(error)
					? new Error(`LLM request timed out after ${timeoutMs}ms (attempt ${attempt}/${MAX_ATTEMPTS})`)
					: error instanceof Error
						? error
						: new Error(String(error));
			console.error('[LLM Request Failure]', {
				label,
				attempt,
				metadata: metadata ?? null,
				error: lastError.message
			});
			onAttempt?.({
				model: currentModel,
				attempt,
				status: 'failed',
				error: lastError.message
			});

			const hasMoreModels = modelsToTry.indexOf(currentModel) < modelsToTry.length - 1;

			if (isLengthTruncatedEmptyResponseError(lastError) && hasMoreModels) {
				console.log('[LLM Model Fallback]', `Truncated empty response on ${currentModel}, trying next model`);
				break;
			}

			if (attempt < MAX_ATTEMPTS && isRetriableError(error) && !(switchModelOnTimeout && isAbortError(error) && hasMoreModels)) {
				await wait(200 * attempt);
				continue;
			}

			if (isRateLimitError(error) && hasMoreModels) {
				console.log('[LLM Model Fallback]', `Rate limited on ${currentModel}, trying next model`);
				break;
			}

			if (isTimeoutError(lastError) && hasMoreModels && (switchModelOnTimeout || attempt === MAX_ATTEMPTS)) {
				console.log('[LLM Model Fallback]', `Timeout on ${currentModel}, trying next model`);
				break;
			}

			throw lastError;
		} finally {
			clearTimeout(timeoutId);
			releaseTurn();
		}
	}
	}

	throw lastError ?? new Error('LLM request failed');
}

function extractTextFromContentValue(value: unknown): string {
	if (typeof value === 'string') return value.trim();
	if (Array.isArray(value)) {
		return value
			.map((entry) => {
				if (typeof entry === 'string') return entry.trim();
				if (!entry || typeof entry !== 'object') return '';
				const candidate = entry as { text?: unknown; type?: unknown; content?: unknown };
				if (typeof candidate.text === 'string') return candidate.text.trim();
				if (candidate.content) return extractTextFromContentValue(candidate.content);
				return '';
			})
			.filter(Boolean)
			.join('\n')
			.trim();
	}
	if (value && typeof value === 'object') {
		const candidate = value as { text?: unknown; content?: unknown };
		if (typeof candidate.text === 'string') return candidate.text.trim();
		if (candidate.content) return extractTextFromContentValue(candidate.content);
	}
	return '';
}

export function extractCompletionContent(data: unknown): string {
	const payload = data as CompletionPayload;
	return (
		extractTextFromContentValue(payload?.choices?.[0]?.message?.content) ||
		payload?.choices?.[0]?.text?.trim() ||
		extractTextFromContentValue(payload?.output?.[0]?.content) ||
		payload?.output_text?.trim() ||
		''
	);
}

function isLengthTruncatedEmptyResponsePayload(data: unknown): boolean {
	const payload = (data && typeof data === 'object' ? data : {}) as {
		choices?: Array<{
			finish_reason?: unknown;
			message?: { content?: unknown; reasoning?: unknown };
		}>;
	};
	const firstChoice = payload.choices?.[0];
	if (!firstChoice) return false;
	const finishReason = typeof firstChoice.finish_reason === 'string' ? firstChoice.finish_reason : '';
	const content = extractTextFromContentValue(firstChoice.message?.content);
	const reasoning = extractTextFromContentValue(firstChoice.message?.reasoning);
	return finishReason === 'length' && !content && Boolean(reasoning);
}

function summarizeValueShape(value: unknown): Record<string, unknown> {
	if (typeof value === 'string') {
		return {
			type: 'string',
			length: value.length,
			preview: value.slice(0, 200)
		};
	}
	if (Array.isArray(value)) {
		return {
			type: 'array',
			length: value.length,
			itemTypes: value.slice(0, 5).map((entry) => typeof entry)
		};
	}
	if (value && typeof value === 'object') {
		return {
			type: 'object',
			keys: Object.keys(value as Record<string, unknown>).slice(0, 20)
		};
	}
	return {
		type: value === null ? 'null' : typeof value,
		value: value ?? null
	};
}

function summarizeCompletionPayload(data: unknown): Record<string, unknown> {
	const payload = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;
	const choices = Array.isArray(payload.choices) ? payload.choices : [];
	const firstChoice =
		choices[0] && typeof choices[0] === 'object' ? (choices[0] as Record<string, unknown>) : null;
	const message =
		firstChoice?.message && typeof firstChoice.message === 'object'
			? (firstChoice.message as Record<string, unknown>)
			: null;
	const output = Array.isArray(payload.output) ? payload.output : [];
	const firstOutput =
		output[0] && typeof output[0] === 'object' ? (output[0] as Record<string, unknown>) : null;

	return {
		topLevelKeys: Object.keys(payload).slice(0, 30),
		choicesCount: choices.length,
		firstChoiceKeys: firstChoice ? Object.keys(firstChoice).slice(0, 20) : [],
		firstChoiceFinishReason: firstChoice?.finish_reason ?? null,
		messageKeys: message ? Object.keys(message).slice(0, 20) : [],
		messageRole: typeof message?.role === 'string' ? message.role : null,
		messageContent: summarizeValueShape(message?.content),
		messageReasoning: summarizeValueShape(message?.reasoning),
		choiceText: summarizeValueShape(firstChoice?.text),
		outputCount: output.length,
		firstOutputKeys: firstOutput ? Object.keys(firstOutput).slice(0, 20) : [],
		firstOutputContent: summarizeValueShape(firstOutput?.content),
		outputText: summarizeValueShape(payload.output_text),
		usage: summarizeValueShape(payload.usage)
	};
}

function extractBalancedJsonSlice(content: string): string | null {
	const start = [...content].findIndex((char) => char === '{' || char === '[');
	if (start < 0) return null;
	const stack: string[] = [];
	let inString = false;
	let escaped = false;
	for (let index = start; index < content.length; index += 1) {
		const char = content[index];
		if (inString) {
			if (escaped) {
				escaped = false;
				continue;
			}
			if (char === '\\') {
				escaped = true;
				continue;
			}
			if (char === '"') inString = false;
			continue;
		}
		if (char === '"') {
			inString = true;
			continue;
		}
		if (char === '{') stack.push('}');
		else if (char === '[') stack.push(']');
		else if (char === '}' || char === ']') {
			if (stack.at(-1) !== char) break;
			stack.pop();
			if (stack.length === 0) return content.slice(start, index + 1);
		}
	}
	return null;
}

function extractJsonErrorPosition(error: unknown): number | null {
	if (!(error instanceof Error)) return null;
	const match = error.message.match(/position\s+(\d+)/i);
	if (!match) return null;
	const position = Number.parseInt(match[1], 10);
	return Number.isFinite(position) ? position : null;
}

function repairJsonTail(content: string, errorPosition?: number | null): string | null {
	const start = [...content].findIndex((char) => char === '{' || char === '[');
	if (start < 0) return null;
	const cutoff =
		typeof errorPosition === 'number' && errorPosition >= start
			? Math.min(content.length, errorPosition)
			: content.length;
	let candidate = content.slice(start, cutoff).trimEnd();
	if (!candidate) return null;

	const stack: string[] = [];
	let inString = false;
	let escaped = false;
	for (let index = 0; index < candidate.length; index += 1) {
		const char = candidate[index];
		if (inString) {
			if (escaped) {
				escaped = false;
				continue;
			}
			if (char === '\\') {
				escaped = true;
				continue;
			}
			if (char === '"') inString = false;
			continue;
		}
		if (char === '"') {
			inString = true;
			continue;
		}
		if (char === '{') stack.push('}');
		else if (char === '[') stack.push(']');
		else if (char === '}' || char === ']') {
			if (stack.at(-1) !== char) return null;
			stack.pop();
		}
	}

	if (inString) {
		candidate += '"';
	}

	while (candidate.length > 0 && /[\s,:]$/.test(candidate)) {
		candidate = candidate.slice(0, -1).trimEnd();
	}

	if (!candidate) return null;

	const lastChar = candidate.at(-1);
	if (lastChar === '{') {
		candidate += '}';
	} else if (lastChar === '[') {
		candidate += ']';
	} else if (lastChar === ',') {
		candidate = candidate.slice(0, -1).trimEnd();
	}

	while (stack.length > 0) {
		candidate += stack.pop();
	}

	return candidate;
}

export function parseStructuredJson<T>(content: string): T {
	const cleaned = content.replace(/^```[a-z]*\n?/i, '').replace(/\n?```$/i, '').trim();
	try {
		return JSON.parse(cleaned) as T;
	} catch (error) {
		const extracted = extractBalancedJsonSlice(cleaned);
		if (extracted) return JSON.parse(extracted) as T;

		const repaired = repairJsonTail(cleaned, extractJsonErrorPosition(error));
		if (!repaired) throw error;

		try {
			return JSON.parse(repaired) as T;
		} catch {
			throw error;
		}
	}
}
