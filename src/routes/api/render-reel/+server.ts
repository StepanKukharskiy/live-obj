import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { randomUUID } from 'node:crypto';
import { execFile as execFileCallback } from 'node:child_process';
import { existsSync } from 'node:fs';
import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';

const execFile = promisify(execFileCallback);
const MAX_ASSET_BYTES = 120 * 1024 * 1024;
const MAX_TEXT_LENGTH = 520;
const MAX_PROCESS_IMAGES = 9;
const MAX_TEXTURE_IMAGES = 8;
const MAX_GALLERY_IMAGES = 8;
const MAX_REEL_LINE_LENGTH = 92;

type ReelAspectRatio = '16:9' | '9:16';
type ReelImage = {
	label?: string;
	meta?: string;
	imageDataUrl?: string;
};
type ReelClip = {
	label?: string;
	videoDataUrl?: string;
};
type ReelAgentMetrics = {
	processCaptures?: number;
	galleryFrames?: number;
	animationClips?: number;
	buildEvents?: number;
	elapsedMs?: number;
	totalTokens?: number;
	reasoningTokens?: number;
	promptTokens?: number;
	completionTokens?: number;
};
type ReelModel = {
	role?: string;
	provider?: string;
	model?: string;
};
type ReelBody = {
	aspectRatio?: ReelAspectRatio;
	liveObjText?: string;
	creativeDirectionJson?: string;
	renderPrompt?: string;
	videoPrompt?: string;
	galleryFrames?: ReelImage[];
	timelineFrames?: ReelImage[];
	turntableFrames?: ReelImage[];
	sourceFrames?: ReelImage[];
	processImages?: ReelImage[];
	textureImages?: ReelImage[];
	projectStructure?: string[];
	finalClips?: ReelClip[];
	finalClip?: ReelClip;
	agentMetrics?: ReelAgentMetrics;
	modelsUsed?: ReelModel[];
};
type WrittenAsset = {
	label: string;
	meta?: string;
	file: string;
	kind: 'image' | 'video';
	durationSeconds?: number;
};
type FfmpegToolPaths = {
	ffmpegPath: string;
	ffprobePath?: string;
	binaryDirs: string[];
};

let ffmpegToolPathsPromise: Promise<FfmpegToolPaths> | null = null;
let hyperframesBrowserPathPromise: Promise<string | undefined> | null = null;

function shortText(value: unknown, fallback: string): string {
	const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : '';
	if (!text) return fallback;
	return text.length > MAX_TEXT_LENGTH ? `${text.slice(0, MAX_TEXT_LENGTH - 1)}...` : text;
}

function publicReelText(value: unknown, fallback: string): string {
	const raw = shortText(value, fallback);
	const cleaned = raw
		.replace(/\bLive\s+OBJ\b/gi, 'the model')
		.replace(/\bOBJ\b/g, 'model')
		.replace(/#@[a-z0-9_:-]+/gi, '')
		.replace(/\bmetadata\b/gi, 'design system')
		.replace(/\bprompt\b/gi, 'direction')
		.replace(/\s+/g, ' ')
		.trim();
	return cleaned || fallback;
}

function compactReelText(
	value: unknown,
	fallback: string,
	maxLength = MAX_REEL_LINE_LENGTH
): string {
	const text = publicReelText(value, fallback);
	const firstSentence = text.match(/[^.!?]+[.!?]?/)?.[0]?.trim() ?? text;
	const compact =
		firstSentence.length > maxLength
			? `${firstSentence.slice(0, maxLength - 1).trim()}...`
			: firstSentence;
	return compact || fallback;
}

function compactReelTitle(value: unknown, fallback: string, maxLength = 74): string {
	const text = publicReelText(value, fallback);
	if (text.length <= maxLength) return text || fallback;
	const boundary = text.lastIndexOf(' ', maxLength - 1);
	const cut = boundary > Math.floor(maxLength * 0.55) ? boundary : maxLength - 1;
	return `${text.slice(0, cut).trim()}...`;
}

function reelSentence(value: unknown, fallback: string): string {
	const text = publicReelText(value, fallback);
	return text.match(/[^.!?]+[.!?]?/)?.[0]?.trim() || text || fallback;
}

function fittingReelSentence(value: unknown, fallback: string, maxLength: number): string {
	const sentence = reelSentence(value, fallback);
	return sentence.length <= maxLength ? sentence : fallback;
}

function compactReelList(
	value: unknown,
	fallback: string[],
	maxItems: number,
	maxLength: number
): string[] {
	const source = Array.isArray(value) ? value : fallback;
	return source
		.map((item) => compactReelText(item, '', maxLength))
		.filter(Boolean)
		.slice(0, maxItems);
}

function escapeHtml(value: string): string {
	return value
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#39;');
}

function sanitizeFilename(value: string, fallback: string): string {
	const clean = value
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9_.-]+/g, '-')
		.replace(/^-+|-+$/g, '');
	return clean || fallback;
}

function structureEntries(value: unknown): string[] {
	if (!Array.isArray(value)) return [];
	const seen = new Set<string>();
	const entries: string[] = [];
	for (const item of value) {
		if (typeof item !== 'string') continue;
		const clean = item.trim().replace(/\\/g, '/').replace(/^\/+/, '').replace(/\s+/g, ' ');
		if (!clean || seen.has(clean)) continue;
		seen.add(clean);
		entries.push(clean);
	}
	return entries.slice(0, 24);
}

function modelIdText(value: unknown, maxLength = 82): string {
	const text =
		typeof value === 'string'
			? value.trim().replace(/\s+/g, ' ')
			: value == null
				? ''
				: String(value).trim().replace(/\s+/g, ' ');
	if (!text) return '';
	return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function modelEntries(value: unknown): ReelModel[] {
	if (!Array.isArray(value)) return [];
	const seen = new Set<string>();
	const entries: ReelModel[] = [];
	for (const item of value) {
		if (!item || typeof item !== 'object') continue;
		const source = item as Record<string, unknown>;
		const role = modelIdText(source.role, 32);
		const provider = modelIdText(source.provider, 32);
		const model = modelIdText(source.model);
		if (!model) continue;
		const key = `${role}|${provider}|${model}`.toLowerCase();
		if (seen.has(key)) continue;
		seen.add(key);
		entries.push({
			...(role ? { role } : {}),
			...(provider ? { provider } : {}),
			model
		});
	}
	return entries.slice(0, 6);
}

function dataUrlToBuffer(dataUrl: string): { bytes: Buffer; mimeType: string; ext: string } {
	const match = dataUrl.match(/^data:([^;]+);base64,(.+)$/);
	if (!match) throw error(400, 'Invalid reel asset data URL');
	const mimeType = match[1].toLowerCase();
	const bytes = Buffer.from(match[2], 'base64');
	if (bytes.byteLength > MAX_ASSET_BYTES) throw error(413, 'Reel asset is too large');
	const ext =
		mimeType === 'image/jpeg'
			? 'jpg'
			: mimeType === 'image/webp'
				? 'webp'
				: mimeType === 'image/png'
					? 'png'
					: mimeType === 'video/webm'
						? 'webm'
						: mimeType === 'video/quicktime'
							? 'mov'
							: mimeType === 'video/mp4'
								? 'mp4'
								: '';
	if (!ext) throw error(400, `Unsupported reel asset type: ${mimeType}`);
	return { bytes, mimeType, ext };
}

async function optionalImportModule<T>(specifier: string): Promise<T | null> {
	try {
		return (await import(/* @vite-ignore */ specifier)) as T;
	} catch {
		return null;
	}
}

async function commandWorks(command: string): Promise<boolean> {
	try {
		await execFile(command, ['-version'], { timeout: 8_000 });
		return true;
	} catch {
		return false;
	}
}

async function firstWorkingCommand(candidates: string[]): Promise<string | undefined> {
	for (const candidate of candidates) {
		if (await commandWorks(candidate)) return candidate;
	}
	return undefined;
}

async function resolveFfmpegToolPaths(): Promise<FfmpegToolPaths> {
	if (ffmpegToolPathsPromise) return ffmpegToolPathsPromise;
	ffmpegToolPathsPromise = (async () => {
		const ffmpegStatic = await optionalImportModule<{ default?: string | null }>('ffmpeg-static');
		const ffprobeStatic = await optionalImportModule<{
			default?: string | { path?: string } | null;
			path?: string;
		}>('ffprobe-static');
		const ffprobeDefault = ffprobeStatic?.default;
		const ffmpegPath =
			(await firstWorkingCommand([ffmpegStatic?.default || '', 'ffmpeg'])) || 'ffmpeg';
		const staticFfprobePath =
			(typeof ffprobeDefault === 'string'
				? ffprobeDefault
				: ffprobeDefault?.path || ffprobeStatic?.path) || 'ffprobe';
		const ffprobePath = await firstWorkingCommand([staticFfprobePath, 'ffprobe']);
		const binaryDirs = [
			ffmpegPath !== 'ffmpeg' ? path.dirname(ffmpegPath) : '',
			ffprobePath && ffprobePath !== 'ffprobe' ? path.dirname(ffprobePath) : ''
		].filter(Boolean);
		return { ffmpegPath, ...(ffprobePath ? { ffprobePath } : {}), binaryDirs };
	})();
	return ffmpegToolPathsPromise;
}

async function assertFfmpegAvailable(toolPaths: FfmpegToolPaths) {
	try {
		await execFile(toolPaths.ffmpegPath, ['-version'], { timeout: 8_000 });
	} catch {
		throw error(
			501,
			'Generate reel needs FFmpeg for MP4 export, but no FFmpeg binary is available. Reinstall dependencies so ffmpeg-static is present, or install ffmpeg on this machine, then try again.'
		);
	}
}

async function videoDurationSeconds(
	filePath: string,
	toolPaths: FfmpegToolPaths
): Promise<number | undefined> {
	if (!toolPaths.ffprobePath) return undefined;
	try {
		const { stdout } = await execFile(
			toolPaths.ffprobePath,
			[
				'-v',
				'error',
				'-show_entries',
				'format=duration',
				'-of',
				'default=noprint_wrappers=1:nokey=1',
				filePath
			],
			{ timeout: 12_000 }
		);
		const duration = Number(stdout.trim());
		if (!Number.isFinite(duration) || duration <= 0) return undefined;
		return Math.max(0.5, duration);
	} catch {
		return undefined;
	}
}

function hyperframesChromeCacheDir(): string {
	return path.join(homedir(), '.cache', 'hyperframes', 'chrome');
}

async function hyperframesBrowserPath(cliPath: string): Promise<string | undefined> {
	if (hyperframesBrowserPathPromise) return hyperframesBrowserPathPromise;
	hyperframesBrowserPathPromise = (async () => {
		const envPath =
			process.env.PRODUCER_HEADLESS_SHELL_PATH || process.env.HYPERFRAMES_BROWSER_PATH;
		if (envPath && existsSync(envPath)) return envPath;

		const readBrowserPath = async () => {
			try {
				const { stdout } = await execFile(process.execPath, [cliPath, 'browser', 'path'], {
					timeout: 45_000,
					env: { ...process.env, HYPERFRAMES_TELEMETRY_DISABLED: '1' }
				});
				return stdout.trim().split(/\r?\n/).findLast(Boolean);
			} catch {
				return undefined;
			}
		};

		const cachedPath = await readBrowserPath();
		if (cachedPath && existsSync(cachedPath)) return cachedPath;

		const cacheDir = hyperframesChromeCacheDir();
		if (cachedPath?.startsWith(cacheDir)) {
			await rm(cacheDir, { recursive: true, force: true }).catch(() => {});
		}

		try {
			await execFile(process.execPath, [cliPath, 'browser', 'ensure'], {
				timeout: 90_000,
				env: { ...process.env, HYPERFRAMES_TELEMETRY_DISABLED: '1' }
			});
		} catch {
			throw error(
				501,
				'Generate reel needs to repair the local HyperFrames render browser, but that repair did not finish. Run `npx hyperframes browser clear` and then `npx hyperframes browser ensure`, restart the dev server, and try exporting again.'
			);
		}

		const repairedPath = await readBrowserPath();
		if (repairedPath && existsSync(repairedPath)) return repairedPath;
		throw error(
			501,
			'Generate reel needs the HyperFrames render browser, but the browser executable is still missing after repair. Run `npx hyperframes browser clear` and then `npx hyperframes browser ensure`, restart the dev server, and try exporting again.'
		);
	})();
	hyperframesBrowserPathPromise.catch(() => {
		hyperframesBrowserPathPromise = null;
	});
	return hyperframesBrowserPathPromise;
}

function renderEnvironment(toolPaths: FfmpegToolPaths, browserPath?: string): NodeJS.ProcessEnv {
	return {
		...process.env,
		HYPERFRAMES_TELEMETRY_DISABLED: '1',
		...(browserPath
			? {
					HYPERFRAMES_BROWSER_PATH: browserPath,
					PRODUCER_HEADLESS_SHELL_PATH: browserPath
				}
			: {}),
		PATH: [...toolPaths.binaryDirs, process.env.PATH ?? ''].filter(Boolean).join(path.delimiter)
	};
}

async function writeAsset(
	assetsDir: string,
	item: ReelImage | ReelClip,
	index: number,
	kind: 'image' | 'video',
	fallbackLabel: string,
	toolPaths: FfmpegToolPaths
): Promise<WrittenAsset | null> {
	const dataUrl =
		kind === 'image' ? (item as ReelImage).imageDataUrl : (item as ReelClip).videoDataUrl;
	if (!dataUrl) return null;
	const payload = dataUrlToBuffer(dataUrl);
	const label = shortText(item.label, fallbackLabel);
	const meta = kind === 'image' ? (item as ReelImage).meta : undefined;
	const basename = `${String(index + 1).padStart(2, '0')}-${sanitizeFilename(label, fallbackLabel)}.${payload.ext}`;
	const absolutePath = path.join(assetsDir, basename);
	await writeFile(absolutePath, payload.bytes);
	const durationSeconds =
		kind === 'video' ? await videoDurationSeconds(absolutePath, toolPaths) : undefined;
	return {
		label,
		...(meta ? { meta: shortText(meta, '') } : {}),
		file: `assets/${basename}`,
		kind,
		...(durationSeconds ? { durationSeconds } : {})
	};
}

function parseDirection(raw: string | undefined): Record<string, any> {
	if (!raw?.trim()) return {};
	try {
		return JSON.parse(raw) as Record<string, any>;
	} catch {
		return {};
	}
}

function reelCopy(direction: Record<string, any>): Record<string, any> {
	const copy = direction.reel_copy;
	return copy && typeof copy === 'object' && !Array.isArray(copy) ? copy : {};
}

function projectTitle(direction: Record<string, any>): string {
	const copy = reelCopy(direction);
	return compactReelTitle(
		copy.title ??
			direction.story_for_image_and_3s_animation?.story_title ??
			direction.primary_direction?.name ??
			direction.geometry_read?.main_character,
		'Spellshape project reel'
	);
}

function directionSummary(
	direction: Record<string, any>,
	renderPrompt: string | undefined
): string {
	const copy = reelCopy(direction);
	const primary = direction.primary_direction ?? {};
	return compactReelText(
		copy.concept ??
			primary.visual_principle ??
			primary.scene_description ??
			primary.color_and_light ??
			primary.material_and_detail ??
			primary.prompt_ready_direction ??
			renderPrompt,
		'A clear visual world carried through image, motion, and build.',
		84
	);
}

function animationSummary(direction: Record<string, any>): string {
	const copy = reelCopy(direction);
	const story = direction.story_for_image_and_3s_animation ?? {};
	return compactReelText(
		copy.opening_line ??
			story.story_beat ??
			story.geometry_action ??
			story.emotional_beat ??
			story.atmosphere_action,
		'Final motion, concept, and build in one short reel.',
		78
	);
}

function referenceTitle(direction: Record<string, any>): string {
	return compactReelText(reelCopy(direction).references_title, 'Visual recipe', 34);
}

function referenceLine(direction: Record<string, any>): string {
	const fallback = 'References shape mood, material, and motion.';
	return fittingReelSentence(reelCopy(direction).reference_line, fallback, 126);
}

function referenceList(direction: Record<string, any>): string[] {
	const copySource = reelCopy(direction).references;
	const copyRefs = Array.isArray(copySource)
		? copySource
				.map((ref) => publicReelText(ref, ''))
				.filter(Boolean)
				.slice(0, 3)
		: [];
	if (copyRefs.length > 0) return copyRefs;
	const primary = direction.primary_direction ?? {};
	const refs = Array.isArray(primary.supporting_references)
		? primary.supporting_references.map((ref: unknown) => publicReelText(ref, '')).filter(Boolean)
		: [];
	if (refs.length > 0) return refs.slice(0, 3);
	const name = publicReelText(primary.name, '');
	const type = publicReelText(primary.type, '');
	return [name, type].filter(Boolean).slice(0, 3);
}

function processTitle(direction: Record<string, any>): string {
	return compactReelText(reelCopy(direction).process_title, 'Agent build', 34);
}

function processSteps(direction: Record<string, any>): string[] {
	return compactReelList(reelCopy(direction).process_steps, [], MAX_PROCESS_IMAGES, 34);
}

function structureTitle(direction: Record<string, any>): string {
	return compactReelText(reelCopy(direction).structure_title, 'Generated scene', 34);
}

function positiveNumber(value: unknown): number | undefined {
	const numberValue = typeof value === 'number' ? value : Number(value);
	if (!Number.isFinite(numberValue) || numberValue <= 0) return undefined;
	return Math.round(numberValue);
}

function formatCompactNumber(value: number): string {
	if (value >= 1_000_000) {
		const compact = value / 1_000_000;
		return `${compact >= 10 ? Math.round(compact) : compact.toFixed(1)}M`;
	}
	if (value >= 1_000) {
		const compact = value / 1_000;
		return `${compact >= 10 ? Math.round(compact) : compact.toFixed(1)}K`;
	}
	return String(value);
}

function formatElapsed(ms: number): string {
	const seconds = Math.max(1, Math.round(ms / 1000));
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	const rest = seconds % 60;
	return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

function normalizeAgentMetrics(
	metrics: ReelAgentMetrics | undefined,
	defaults: ReelAgentMetrics
): ReelAgentMetrics {
	return {
		processCaptures: positiveNumber(metrics?.processCaptures) ?? defaults.processCaptures,
		galleryFrames: positiveNumber(metrics?.galleryFrames) ?? defaults.galleryFrames,
		animationClips: positiveNumber(metrics?.animationClips) ?? defaults.animationClips,
		buildEvents: positiveNumber(metrics?.buildEvents) ?? defaults.buildEvents,
		elapsedMs: positiveNumber(metrics?.elapsedMs) ?? defaults.elapsedMs,
		totalTokens: positiveNumber(metrics?.totalTokens) ?? defaults.totalTokens,
		reasoningTokens: positiveNumber(metrics?.reasoningTokens) ?? defaults.reasoningTokens,
		promptTokens: positiveNumber(metrics?.promptTokens) ?? defaults.promptTokens,
		completionTokens: positiveNumber(metrics?.completionTokens) ?? defaults.completionTokens
	};
}

function effortItems(metrics: ReelAgentMetrics): Array<{ value: string; label: string }> {
	const items: Array<{ value: string; label: string }> = [];
	if (metrics.animationClips) {
		items.push({
			value: formatCompactNumber(metrics.animationClips),
			label: metrics.animationClips === 1 ? 'motion clip' : 'motion clips'
		});
	}
	if (metrics.processCaptures) {
		items.push({
			value: formatCompactNumber(metrics.processCaptures),
			label: 'build captures'
		});
	}
	if (metrics.galleryFrames) {
		items.push({
			value: formatCompactNumber(metrics.galleryFrames),
			label: 'render frames'
		});
	}
	if (metrics.totalTokens) {
		items.push({
			value: formatCompactNumber(metrics.totalTokens),
			label: 'tokens used'
		});
	}
	if (metrics.elapsedMs) {
		items.push({
			value: formatElapsed(metrics.elapsedMs),
			label: 'timed work'
		});
	}
	if (metrics.buildEvents && items.length < 5) {
		items.push({
			value: formatCompactNumber(metrics.buildEvents),
			label: 'agent beats'
		});
	}
	return items.slice(0, 5);
}

function modelRoleLabel(value: string | undefined, fallback: string): string {
	const normalized = (value ?? '').trim().toLowerCase();
	if (normalized === 'text') return 'Text planning';
	if (normalized === 'image') return 'Image render';
	if (normalized === 'video') return 'Video motion';
	return value?.trim() || fallback;
}

type TreeNode = {
	isFile: boolean;
	children: Map<string, TreeNode>;
};

function createTreeNode(isFile = false): TreeNode {
	return { isFile, children: new Map() };
}

function structureTreeText(entries: string[]): string {
	const source = entries.length
		? entries
		: ['geometry/spellshape-live.obj', 'materials/spellshape-live.mtl', 'manifest.json'];
	const root = createTreeNode();
	for (const entry of source) {
		const clean = entry.replace(/\\/g, '/').replace(/^\/+/, '').trim();
		const parts = clean.split('/').filter(Boolean);
		if (!parts.length) continue;
		let node = root;
		parts.forEach((part, index) => {
			const isLast = index === parts.length - 1;
			const isFile = isLast && !clean.endsWith('/');
			const child = node.children.get(part) ?? createTreeNode(isFile);
			child.isFile = child.isFile || isFile;
			node.children.set(part, child);
			node = child;
		});
	}

	const lines = ['project/'];
	function walk(node: TreeNode, prefix: string) {
		const children = [...node.children.entries()].sort((a, b) => {
			if (a[1].isFile !== b[1].isFile) return a[1].isFile ? 1 : -1;
			return a[0].localeCompare(b[0]);
		});
		children.forEach(([name, child], index) => {
			const last = index === children.length - 1;
			const connector = last ? '`-- ' : '|-- ';
			const childPrefix = last ? '    ' : '|   ';
			lines.push(`${prefix}${connector}${name}${child.isFile ? '' : '/'}`);
			if (child.children.size) walk(child, `${prefix}${childPrefix}`);
		});
	}
	walk(root, '');
	return lines.slice(0, 30).join('\n');
}

function buildCompositionHtml(args: {
	aspectRatio: ReelAspectRatio;
	title: string;
	direction: string;
	animation: string;
	referenceTitle: string;
	referenceLine: string;
	references: string[];
	processTitle: string;
	processSteps: string[];
	structureTitle: string;
	finalClips: WrittenAsset[];
	heroImage: WrittenAsset | null;
	processImages: WrittenAsset[];
	textureImages: WrittenAsset[];
	galleryImages: WrittenAsset[];
	sourceImages: WrittenAsset[];
	dataBackgroundImage: WrittenAsset | null;
	projectStructure: string[];
	agentMetrics: ReelAgentMetrics;
	modelsUsed: ReelModel[];
}) {
	const width = args.aspectRatio === '9:16' ? 1080 : 1920;
	const height = args.aspectRatio === '9:16' ? 1920 : 1080;
	const clipDurations = args.finalClips.map((clip) => clip.durationSeconds ?? 8);
	const heroDuration = clipDurations.length
		? clipDurations.reduce((sum, duration) => sum + duration, 0)
		: 3.2;
	const pipelineStart = heroDuration;
	const pipelineDuration = 1.1;
	const processStart = pipelineStart + pipelineDuration;
	const processCards = args.processImages.slice(0, 9);
	const sequenceFrameDuration = 0.5;
	const processDuration = processCards.length ? processCards.length * sequenceFrameDuration : 0;
	const galleryStart = processStart + processDuration;
	const galleryCards = args.galleryImages.slice(0, MAX_GALLERY_IMAGES);
	const galleryDuration = galleryCards.length ? galleryCards.length * sequenceFrameDuration : 0;
	const textureStart = galleryStart + galleryDuration;
	const textureCards = args.textureImages.slice(0, MAX_TEXTURE_IMAGES);
	const textureDuration = textureCards.length ? textureCards.length * sequenceFrameDuration : 0;
	const sourceStart = textureStart + textureDuration;
	const sourceCards = args.sourceImages.slice(0, MAX_GALLERY_IMAGES);
	const sourceDuration = sourceCards.length ? sourceCards.length * sequenceFrameDuration : 0;
	const effort = effortItems(args.agentMetrics);
	const models = args.modelsUsed;
	const dataStart = sourceStart + sourceDuration;
	const dataDuration = effort.length || models.length ? 2.25 : 0;
	const logoStart = dataStart + dataDuration;
	const logoDuration = 1.65;
	const totalDuration = logoStart + logoDuration;
	const portrait = args.aspectRatio === '9:16';
	const media = args.heroImage;
	const heroMediaHtml = args.finalClips.length
		? args.finalClips
				.map((clip, index) => {
					const start = clipDurations.slice(0, index).reduce((sum, duration) => sum + duration, 0);
					const duration = clipDurations[index] ?? 8;
					return `<video class="hero-media-full clip" src="${escapeHtml(clip.file)}" data-start="${start.toFixed(2)}" data-duration="${duration.toFixed(2)}" data-volume="0" muted playsinline></video>`;
				})
				.join('\n')
		: media
			? `<img class="hero-media-full clip" src="${escapeHtml(media.file)}" data-start="0" data-duration="${heroDuration.toFixed(2)}" alt="" />`
			: '';
	const pipelineHtml = portrait
		? `<div class="pipeline-stack" aria-label="Prompt to Scene to Image to Video">
				<strong>Prompt</strong>
				<span>↓</span>
				<strong>Scene</strong>
				<span>↓</span>
				<strong>Image</strong>
				<span>↓</span>
				<strong>Video</strong>
			</div>`
		: `<h2>Prompt <span>→</span> Scene <span>→</span> Image <span>→</span> Video</h2>`;
	const processHtml = processCards
		.map((asset, index) => {
			const start = processStart + index * sequenceFrameDuration;
			const tilt = [-1.4, 1.1, -0.7, 0.9][index % 4];
			const x = [-16, 14, 0, 10][index % 4];
			const y = [8, -10, 0, 12][index % 4];
			return `<figure class="clip sequence-shot process-shot" style="--tilt:${tilt}deg;--x:${x}px;--y:${y}px;" data-start="${start.toFixed(2)}" data-duration="${sequenceFrameDuration.toFixed(2)}">
				<div class="shot-stage"><img src="${escapeHtml(asset.file)}" alt="" /></div>
			</figure>`;
		})
		.join('\n');
	const textureHtml = textureCards
		.map((asset, index) => {
			const start = textureStart + index * sequenceFrameDuration;
			const tilt = [-0.6, 0.6, -0.35, 0.35][index % 4];
			return `<figure class="clip sequence-shot texture-shot" style="--tilt:${tilt}deg;--x:0px;--y:0px;" data-start="${start.toFixed(2)}" data-duration="${sequenceFrameDuration.toFixed(2)}">
				<div class="shot-stage"><img src="${escapeHtml(asset.file)}" alt="" /></div>
			</figure>`;
		})
		.join('\n');
	const galleryHtml = galleryCards
		.map((asset, index) => {
			const start = galleryStart + index * sequenceFrameDuration;
			return `<figure class="clip gallery-shot" data-start="${start.toFixed(2)}" data-duration="${sequenceFrameDuration.toFixed(2)}">
				<div class="shot-stage"><img src="${escapeHtml(asset.file)}" alt="" /></div>
			</figure>`;
		})
		.join('\n');
	const sourceHtml = sourceCards
		.map((asset, index) => {
			const start = sourceStart + index * sequenceFrameDuration;
			const tilt = [1.2, -1.0, 0.55, -0.45][index % 4];
			const x = [18, -14, 10, -8][index % 4];
			const y = [-8, 10, -12, 4][index % 4];
			return `<figure class="clip sequence-shot source-shot" style="--tilt:${tilt}deg;--x:${x}px;--y:${y}px;" data-start="${start.toFixed(2)}" data-duration="${sequenceFrameDuration.toFixed(2)}">
				<div class="shot-stage"><img src="${escapeHtml(asset.file)}" alt="" /></div>
			</figure>`;
		})
		.join('\n');
	const dataHeroTileStyle = args.dataBackgroundImage
		? ` style="--tile-bg:url('${escapeHtml(args.dataBackgroundImage.file)}')"`
		: '';
	const dataTileHtml = [
		...effort.map(
			(
				item,
				index
			) => `<div class="bento-tile stat-tile stat-tile-${index}${index === 0 && args.dataBackgroundImage ? ' has-bg' : ''}"${index === 0 ? dataHeroTileStyle : ''}>
				<strong>${escapeHtml(item.value)}</strong>
				<span>${escapeHtml(item.label)}</span>
			</div>`
		),
		...models.map(
			(item, index) => `<div class="bento-tile model-tile model-tile-${index}">
				<span>${escapeHtml(modelRoleLabel(item.role, 'Model'))}</span>
				<strong>${escapeHtml(item.model ?? '')}</strong>
			</div>`
		)
	].join('\n');

	return `<!doctype html>
<html>
	<head>
		<meta charset="utf-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
		<title>${escapeHtml(args.title)}</title>
		<style>
			:root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
			html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #ffffff; }
			#root { position: relative; width: ${width}px; height: ${height}px; overflow: hidden; background: #ffffff; color: #050505; }
			.clip { position: absolute; box-sizing: border-box; }
			.scene-backdrop { inset: 0; background: #ffffff; }
			.hero-media-full { inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
				.kicker { text-transform: uppercase; letter-spacing: .08em; font-size: ${portrait ? '22px' : '16px'}; font-weight: 860; color: #0000eb; }
				h1 { position: relative; margin: 0; max-width: 100%; font-size: ${portrait ? '54px' : '52px'}; line-height: 1.04; letter-spacing: 0; color: #050505; text-wrap: balance; overflow-wrap: normal; word-break: normal; hyphens: none; }
				@keyframes shotIn {
					from { opacity: .58; transform: translate3d(var(--x, 0px), calc(var(--y, 0px) + 18px), 0) scale(.982) rotate(var(--tilt, 0deg)); }
					to { opacity: 1; transform: translate3d(var(--x, 0px), var(--y, 0px), 0) scale(1) rotate(var(--tilt, 0deg)); }
				}
				.sequence-shot, .gallery-shot { inset: 0; margin: 0; overflow: hidden; display: grid; place-items: center; padding: ${portrait ? '96px 48px' : '58px 86px'}; background: linear-gradient(180deg, #ffffff 0%, #f7f8fa 100%); }
				.pipeline-card { inset: 0; display: grid; place-items: center; padding: ${portrait ? '88px 58px' : '70px 120px'}; background: #ffffff; color: #050505; }
				.pipeline-card h2 { margin: 0; font-size: ${portrait ? '58px' : '64px'}; line-height: 1; letter-spacing: 0; font-weight: 850; text-align: center; text-wrap: balance; }
				.pipeline-card span { color: #0000eb; }
				.pipeline-stack { display: grid; justify-items: center; gap: 16px; }
				.pipeline-stack strong { font-size: 74px; line-height: .94; letter-spacing: 0; font-weight: 860; }
				.pipeline-stack span { font-size: 44px; line-height: 1; color: #0000eb; font-weight: 760; }
				.shot-stage { position: relative; display: grid; place-items: center; width: fit-content; height: fit-content; max-width: 100%; max-height: 100%; padding: ${portrait ? '14px' : '12px'}; border: 1px solid rgba(0,0,0,.075); border-radius: ${portrait ? '24px' : '22px'}; background: rgba(255,255,255,.94); box-shadow: 0 34px 96px rgba(0,0,0,.14), 0 9px 30px rgba(0,0,0,.08), inset 0 1px 0 rgba(255,255,255,.96); backdrop-filter: blur(14px) saturate(1.05); -webkit-backdrop-filter: blur(14px) saturate(1.05); animation: shotIn .42s cubic-bezier(.2,.86,.2,1) both; }
				.texture-shot .shot-stage { box-shadow: 0 30px 84px rgba(0,0,0,.13), 0 8px 28px rgba(0,0,0,.07), inset 0 1px 0 rgba(255,255,255,.96); }
				.gallery-shot .shot-stage { animation-duration: .38s; }
				.shot-stage img { width: auto; height: auto; max-width: ${portrait ? '920px' : '1660px'}; max-height: ${portrait ? '1500px' : '870px'}; object-fit: contain; display: block; border-radius: ${portrait ? '14px' : '13px'}; }
				.data-card { inset: 0; display: grid; place-items: center; padding: ${portrait ? '104px 58px' : '82px 132px'}; background: linear-gradient(180deg, #ffffff 0%, #f7f8fa 100%); color: #050505; }
				.bento-grid { width: min(100%, ${portrait ? '860px' : '1420px'}); max-height: 100%; justify-self: center; align-self: center; display: grid; grid-template-columns: repeat(${portrait ? 2 : 6}, minmax(0, 1fr)); grid-auto-rows: ${portrait ? '156px' : '142px'}; gap: ${portrait ? '18px' : '20px'}; }
				.bento-tile { position: relative; min-width: 0; overflow: hidden; display: grid; align-content: end; gap: 10px; padding: ${portrait ? '22px' : '22px'}; border: 1px solid rgba(0,0,0,.075); border-radius: ${portrait ? '24px' : '22px'}; background: rgba(255,255,255,.9); box-shadow: 0 24px 70px rgba(0,0,0,.1), inset 0 1px 0 rgba(255,255,255,.96); }
				.bento-tile::before { content: ""; position: absolute; inset: 0; background: linear-gradient(135deg, rgba(0,0,235,.09), rgba(255,255,255,0) 46%); pointer-events: none; }
				.bento-tile strong, .bento-tile span { position: relative; min-width: 0; }
				.bento-tile.has-bg { background: #050505; border-color: rgba(0,0,0,.08); box-shadow: 0 26px 82px rgba(0,0,0,.16), inset 0 1px 0 rgba(255,255,255,.38); }
				.bento-tile.has-bg::before { background: linear-gradient(180deg, rgba(255,255,255,.42), rgba(255,255,255,.18) 38%, rgba(0,0,0,.4)), var(--tile-bg); background-size: cover; background-position: center; transform: scale(1.035); filter: saturate(1.05); }
				.bento-tile.has-bg::after { content: ""; position: absolute; inset: 0; background: linear-gradient(135deg, rgba(0,0,235,.16), rgba(255,255,255,0) 46%); pointer-events: none; }
				.stat-tile strong { color: #050505; font-size: ${portrait ? '54px' : '50px'}; line-height: .9; letter-spacing: 0; }
				.stat-tile span, .model-tile span { color: rgba(0,0,0,.58); font-size: ${portrait ? '22px' : '18px'}; line-height: 1.05; font-weight: 850; text-transform: uppercase; letter-spacing: .08em; }
				.stat-tile.has-bg strong { color: #ffffff; text-shadow: 0 10px 38px rgba(0,0,0,.34); }
				.stat-tile.has-bg span { color: rgba(255,255,255,.82); text-shadow: 0 8px 28px rgba(0,0,0,.28); }
				.model-tile { background: rgba(250,250,255,.92); }
				.model-tile span { color: #0000eb; }
				.model-tile strong { color: #050505; font-size: ${portrait ? '28px' : '24px'}; line-height: 1.05; overflow-wrap: anywhere; }
				.stat-tile-0 { grid-column: span ${portrait ? 2 : 2}; grid-row: span 2; }
				.stat-tile-0 strong { font-size: ${portrait ? '92px' : '88px'}; }
				.stat-tile-1, .stat-tile-2 { grid-column: span ${portrait ? 1 : 2}; }
				.stat-tile-3, .stat-tile-4, .model-tile { grid-column: span ${portrait ? 1 : 2}; }
				.model-tile-0 { grid-column: span ${portrait ? 2 : 2}; }
				.brand-end { inset: 0; display: grid; place-items: center; background: #ffffff; }
				.brand-end img { width: ${portrait ? '58%' : '34%'}; max-width: ${portrait ? '660px' : '720px'}; height: auto; display: block; }
		</style>
	</head>
	<body>
		<script src="./gsap.min.js"></script>
		<div id="root" data-composition-id="spellshape-reel" data-start="0" data-duration="${totalDuration.toFixed(2)}" data-width="${width}" data-height="${height}">
			<div class="scene-backdrop clip" data-start="0" data-duration="${totalDuration.toFixed(2)}"></div>
			${heroMediaHtml}
			<section class="pipeline-card clip" data-start="${pipelineStart.toFixed(2)}" data-duration="${pipelineDuration.toFixed(2)}">
				${pipelineHtml}
			</section>
			${processHtml}
			${galleryHtml}
			${textureHtml}
			${sourceHtml}
			${
				dataDuration
					? `<section class="data-card clip" data-start="${dataStart.toFixed(2)}" data-duration="${dataDuration.toFixed(2)}">
						<div class="bento-grid">${dataTileHtml}</div>
					</section>`
					: ''
			}
			<section class="brand-end clip" data-start="${logoStart.toFixed(2)}" data-duration="${logoDuration.toFixed(2)}">
				<img src="./spellshape_text_logo.svg" alt="Spellshape" />
			</section>
		</div>
		<script>
			const tl = gsap.timeline({ paused: true });
			tl.set("#root", { opacity: 1 }, 0);
			tl.to("#root", { opacity: 1, duration: ${totalDuration.toFixed(2)} }, 0);
			window.__timelines = window.__timelines || {};
			window.__timelines["spellshape-reel"] = tl;
		</script>
	</body>
</html>`;
}

export const POST: RequestHandler = async ({ request }) => {
	const toolPaths = await resolveFfmpegToolPaths();
	await assertFfmpegAvailable(toolPaths);
	let body: ReelBody;
	try {
		body = (await request.json()) as ReelBody;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const aspectRatio: ReelAspectRatio = body.aspectRatio === '16:9' ? '16:9' : '9:16';
	const direction = parseDirection(body.creativeDirectionJson);
	const title = projectTitle(direction);
	const animation = animationSummary(direction);
	const summary = directionSummary(direction, body.renderPrompt);
	const referencesTitle = referenceTitle(direction);
	const referencesLine = referenceLine(direction);
	const references = referenceList(direction);
	const buildTitle = processTitle(direction);
	const buildSteps = processSteps(direction);
	const packageTitle = structureTitle(direction);
	const projectStructure = structureEntries(body.projectStructure);
	const modelsUsed = modelEntries(body.modelsUsed);
	const workspaceDir = path.join(tmpdir(), `spellshape-reel-${randomUUID()}`);
	const assetsDir = path.join(workspaceDir, 'assets');
	const outputPath = path.join(workspaceDir, 'spellshape-reel.mp4');

	try {
		await mkdir(assetsDir, { recursive: true });
		await copyFile(
			path.join(process.cwd(), 'node_modules', 'gsap', 'dist', 'gsap.min.js'),
			path.join(workspaceDir, 'gsap.min.js')
		);
		await copyFile(
			path.join(process.cwd(), 'static', 'images', 'spellshape_text_logo.svg'),
			path.join(workspaceDir, 'spellshape_text_logo.svg')
		);
		const finalClipInputs =
			Array.isArray(body.finalClips) && body.finalClips.length > 0
				? body.finalClips
				: body.finalClip
					? [body.finalClip]
					: [];
		const finalClips = (
			await Promise.all(
				finalClipInputs
					.slice(0, 3)
					.map((item, index) =>
						writeAsset(assetsDir, item, index, 'video', `clip-${index + 1}`, toolPaths)
					)
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const processImages = (
			await Promise.all(
				(body.processImages ?? [])
					.slice(0, MAX_PROCESS_IMAGES)
					.map((item, index) =>
						writeAsset(assetsDir, item, index, 'image', `process-${index + 1}`, toolPaths)
					)
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const textureImages = (
			await Promise.all(
				(body.textureImages ?? [])
					.slice(0, MAX_TEXTURE_IMAGES)
					.map((item, index) =>
						writeAsset(assetsDir, item, index, 'image', `texture-${index + 1}`, toolPaths)
					)
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const galleryImages = (
			await Promise.all(
				[
					...(body.turntableFrames?.length ? body.turntableFrames : []),
					...(body.turntableFrames?.length ? [] : (body.timelineFrames ?? [])),
					...(body.turntableFrames?.length ? [] : (body.galleryFrames ?? []))
				]
					.slice(0, MAX_GALLERY_IMAGES)
					.map((item, index) =>
						writeAsset(assetsDir, item, index, 'image', `frame-${index + 1}`, toolPaths)
					)
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const sourceImages = (
			await Promise.all(
				(body.sourceFrames ?? [])
					.slice(0, MAX_GALLERY_IMAGES)
					.map((item, index) =>
						writeAsset(assetsDir, item, index, 'image', `source-${index + 1}`, toolPaths)
					)
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const timelineStartImage =
			body.timelineFrames?.[0] && body.timelineFrames[0].imageDataUrl
				? await writeAsset(
						assetsDir,
						body.timelineFrames[0],
						0,
						'image',
						'data-start-frame',
						toolPaths
					)
				: null;
		const heroImage = galleryImages[0] ?? processImages[0] ?? textureImages[0] ?? null;
		if (finalClips.length === 0 && !heroImage) {
			throw error(
				400,
				'Generate reel needs at least one final clip, gallery frame, or process image.'
			);
		}
		const agentMetrics = normalizeAgentMetrics(body.agentMetrics, {
			animationClips: finalClips.length,
			processCaptures: processImages.length,
			galleryFrames: galleryImages.length,
			buildEvents: processImages.length
		});

		await writeFile(
			path.join(workspaceDir, 'index.html'),
			buildCompositionHtml({
				aspectRatio,
				title,
				direction: summary,
				animation,
				referenceTitle: referencesTitle,
				referenceLine: referencesLine,
				references,
				processTitle: buildTitle,
				processSteps: buildSteps,
				structureTitle: packageTitle,
				finalClips,
				heroImage,
				processImages,
				textureImages,
				galleryImages,
				sourceImages,
				dataBackgroundImage: timelineStartImage ?? galleryImages[0] ?? sourceImages[0] ?? heroImage,
				projectStructure,
				agentMetrics,
				modelsUsed
			})
		);

		const cliPath = path.join(process.cwd(), 'node_modules', 'hyperframes', 'dist', 'cli.js');
		const browserPath = await hyperframesBrowserPath(cliPath);
		await execFile(
			process.execPath,
			[
				cliPath,
				'render',
				workspaceDir,
				'--output',
				outputPath,
				'--format',
				'mp4',
				'--resolution',
				aspectRatio === '9:16' ? 'portrait' : 'landscape',
				'--quality',
				'standard',
				'--fps',
				'30',
				'--quiet'
			],
			{
				cwd: workspaceDir,
				timeout: 10 * 60_000,
				env: renderEnvironment(toolPaths, browserPath)
			}
		);
		const videoBytes = await readFile(outputPath);
		return json({
			filename: `spellshape-reel-${aspectRatio === '9:16' ? 'portrait' : 'landscape'}.mp4`,
			videoDataUrl: `data:video/mp4;base64,${videoBytes.toString('base64')}`
		});
	} catch (err) {
		if (err && typeof err === 'object' && 'status' in err) throw err;
		const message = err instanceof Error ? err.message : String(err);
		throw error(500, message || 'Reel generation failed');
	} finally {
		await rm(workspaceDir, { recursive: true, force: true }).catch(() => {});
	}
};
