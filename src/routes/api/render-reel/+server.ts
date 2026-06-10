import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { randomUUID } from 'node:crypto';
import { execFile as execFileCallback } from 'node:child_process';
import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import ffmpegPath from 'ffmpeg-static';
import ffprobeStatic from 'ffprobe-static';

const execFile = promisify(execFileCallback);
const MAX_ASSET_BYTES = 120 * 1024 * 1024;
const MAX_TEXT_LENGTH = 520;
const MAX_PROCESS_IMAGES = 9;
const MAX_TEXTURE_IMAGES = 6;
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
type ReelBody = {
	aspectRatio?: ReelAspectRatio;
	liveObjText?: string;
	creativeDirectionJson?: string;
	renderPrompt?: string;
	videoPrompt?: string;
	galleryFrames?: ReelImage[];
	timelineFrames?: ReelImage[];
	processImages?: ReelImage[];
	textureImages?: ReelImage[];
	projectStructure?: string[];
	finalClips?: ReelClip[];
	finalClip?: ReelClip;
	agentMetrics?: ReelAgentMetrics;
};
type WrittenAsset = {
	label: string;
	meta?: string;
	file: string;
	kind: 'image' | 'video';
	durationSeconds?: number;
};

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

async function assertFfmpegAvailable() {
	const ffmpegBinary = ffmpegPath || 'ffmpeg';
	try {
		await execFile(ffmpegBinary, ['-version'], { timeout: 8_000 });
	} catch {
		throw error(
			501,
			'Generate reel uses HyperFrames MP4 export, but the server-side FFmpeg binary is unavailable. Reinstall dependencies, then try Generate reel again.'
		);
	}
}

async function videoDurationSeconds(filePath: string): Promise<number | undefined> {
	if (!ffprobeStatic.path) return undefined;
	try {
		const { stdout } = await execFile(
			ffprobeStatic.path,
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

function renderEnvironment(): NodeJS.ProcessEnv {
	const binaryDirs = [
		ffmpegPath ? path.dirname(ffmpegPath) : '',
		ffprobeStatic.path ? path.dirname(ffprobeStatic.path) : ''
	].filter(Boolean);
	return {
		...process.env,
		HYPERFRAMES_TELEMETRY_DISABLED: '1',
		PATH: [...binaryDirs, process.env.PATH ?? ''].filter(Boolean).join(path.delimiter)
	};
}

async function writeAsset(
	assetsDir: string,
	item: ReelImage | ReelClip,
	index: number,
	kind: 'image' | 'video',
	fallbackLabel: string
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
	const durationSeconds = kind === 'video' ? await videoDurationSeconds(absolutePath) : undefined;
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
	return compactReelText(
		copy.title ??
			direction.story_for_image_and_3s_animation?.story_title ??
			direction.primary_direction?.name ??
			direction.geometry_read?.main_character,
		'Spellshape project reel',
		38
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

function openingLabel(direction: Record<string, any>): string {
	const label = compactReelText(reelCopy(direction).opening_label, 'Project reveal', 28);
	return label.toLowerCase() === 'final animation' ? 'Project reveal' : label;
}

function referenceTitle(direction: Record<string, any>): string {
	return compactReelText(reelCopy(direction).references_title, 'Visual recipe', 34);
}

function referenceLine(direction: Record<string, any>): string {
	const fallback = 'References shape mood, material, and motion.';
	return fittingReelSentence(reelCopy(direction).reference_line, fallback, 126);
}

function referenceList(direction: Record<string, any>): string[] {
	const copyRefs = compactReelList(reelCopy(direction).references, [], 3, 48);
	if (copyRefs.length > 0) return copyRefs;
	const primary = direction.primary_direction ?? {};
	const refs = Array.isArray(primary.supporting_references)
		? primary.supporting_references
				.map((ref: unknown) => compactReelText(ref, '', 42))
				.filter(Boolean)
		: [];
	if (refs.length > 0) return refs.slice(0, 3);
	const name = compactReelText(primary.name, '', 42);
	const type = compactReelText(primary.type, '', 42);
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

function processCellStyle(index: number, total: number, portrait: boolean): string {
	const cols = portrait ? (total > 4 ? 3 : 2) : Math.min(4, Math.max(2, total));
	const gap = portrait ? 18 : 22;
	const gridWidth = portrait ? 960 : 1500;
	const gridTop = portrait ? 590 : 300;
	const gridLeft = portrait ? 60 : 210;
	const cellWidth = Math.floor((gridWidth - gap * (cols - 1)) / cols);
	const cellHeight = portrait ? Math.floor(cellWidth * 1.18) : Math.floor(cellWidth * 0.68);
	const col = index % cols;
	const row = Math.floor(index / cols);
	const left = gridLeft + col * (cellWidth + gap);
	const top = gridTop + row * (cellHeight + gap);
	return `left:${left}px;top:${top}px;width:${cellWidth}px;height:${cellHeight}px;`;
}

function assetGridCellStyle(index: number, total: number, portrait: boolean): string {
	return processCellStyle(index, total, portrait);
}

function buildCompositionHtml(args: {
	aspectRatio: ReelAspectRatio;
	title: string;
	openingLabel: string;
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
	projectStructure: string[];
	agentMetrics: ReelAgentMetrics;
}) {
	const width = args.aspectRatio === '9:16' ? 1080 : 1920;
	const height = args.aspectRatio === '9:16' ? 1920 : 1080;
	const clipDurations = args.finalClips.map((clip) => clip.durationSeconds ?? 8);
	const heroDuration = clipDurations.length
		? clipDurations.reduce((sum, duration) => sum + duration, 0)
		: 3.2;
	const directionStart = heroDuration;
	const directionDuration = 1.9;
	const referenceStart = directionStart + directionDuration;
	const referenceDuration = args.references.length
		? Math.max(2.4, args.references.length * 1.25)
		: 0;
	const processStart = referenceStart + referenceDuration;
	const processCards = args.processImages.slice(0, 9);
	const processDuration = processCards.length
		? Math.min(4.2, Math.max(2.4, 1.25 + processCards.length * 0.34))
		: 0;
	const processStep = processCards.length ? processDuration / (processCards.length + 1) : 0;
	const textureStart = processStart + processDuration;
	const textureCards = args.textureImages.slice(0, MAX_TEXTURE_IMAGES);
	const textureDuration = textureCards.length
		? Math.min(3.4, Math.max(2.1, 1.1 + textureCards.length * 0.42))
		: 0;
	const textureStep = textureCards.length ? textureDuration / (textureCards.length + 1) : 0;
	const galleryStart = textureStart + textureDuration;
	const galleryCards = args.galleryImages.slice(0, MAX_GALLERY_IMAGES);
	const galleryDuration = galleryCards.length
		? Math.min(3.8, Math.max(2.2, 1.2 + galleryCards.length * 0.4))
		: 0;
	const galleryStep = galleryCards.length ? galleryDuration / (galleryCards.length + 1) : 0;
	const effort = effortItems(args.agentMetrics);
	const effortStart = galleryStart + galleryDuration;
	const effortDuration = effort.length ? 1.85 : 0;
	const structureStart = effortStart + effortDuration;
	const structureDuration = 1.45;
	const totalDuration = structureStart + structureDuration;
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
	const conceptVisualHtml = media
		? `<figure class="concept-visual"><img src="${escapeHtml(media.file)}" alt="" /></figure>`
		: '';
	const processHtml = processCards
		.map((asset, index) => {
			const start = processStart + (index + 1) * processStep;
			const duration = processStart + processDuration - start;
			return `<figure class="clip process-cell" style="${processCellStyle(index, processCards.length, portrait)}" data-start="${start.toFixed(2)}" data-duration="${Math.max(0.35, duration).toFixed(2)}">
				<img src="${escapeHtml(asset.file)}" alt="" />
				<figcaption>
					<span class="kicker">Step ${index + 1}</span>
					<strong>${escapeHtml(args.processSteps[index] ?? compactReelText(asset.label, `Build ${index + 1}`, 34))}</strong>
				</figcaption>
			</figure>`;
		})
		.join('\n');
	const textureHtml = textureCards
		.map((asset, index) => {
			const start = textureStart + (index + 1) * textureStep;
			const duration = textureStart + textureDuration - start;
			return `<figure class="clip texture-cell" style="${assetGridCellStyle(index, textureCards.length, portrait)}" data-start="${start.toFixed(2)}" data-duration="${Math.max(0.45, duration).toFixed(2)}">
				<img src="${escapeHtml(asset.file)}" alt="" />
				<figcaption>
					<span class="kicker">Texture ${index + 1}</span>
					<strong>${escapeHtml(compactReelText(asset.label, `Generated texture ${index + 1}`, 34))}</strong>
				</figcaption>
			</figure>`;
		})
		.join('\n');
	const galleryHtml = galleryCards
		.map((asset, index) => {
			const start = galleryStart + (index + 1) * galleryStep;
			const duration = galleryStart + galleryDuration - start;
			return `<figure class="clip gallery-cell" style="${assetGridCellStyle(index, galleryCards.length, portrait)}" data-start="${start.toFixed(2)}" data-duration="${Math.max(0.45, duration).toFixed(2)}">
				<img src="${escapeHtml(asset.file)}" alt="" />
				<figcaption>
					<span class="kicker">View ${index + 1}</span>
					<strong>${escapeHtml(compactReelText(asset.label, `Final view ${index + 1}`, 34))}</strong>
				</figcaption>
			</figure>`;
		})
		.join('\n');
	const structureItems =
		args.projectStructure.length > 0
			? args.projectStructure
			: ['spellshape-live.obj', 'spellshape-live.mtl', 'manifest.json'];
	const structureTree = structureTreeText(structureItems);
	const referenceHtml = args.references
		.map((reference, index) => {
			const start = referenceStart + index * (referenceDuration / args.references.length);
			const duration = referenceStart + referenceDuration - start;
			return `<li class="clip reference-item reference-${index}" data-start="${start.toFixed(2)}" data-duration="${duration.toFixed(2)}"><span>0${index + 1}</span>${escapeHtml(reference)}</li>`;
		})
		.join('\n');
	const effortHtml = effort
		.map(
			(item, index) => `<div class="effort-item effort-${index}">
				<strong>${escapeHtml(item.value)}</strong>
				<span>${escapeHtml(item.label)}</span>
			</div>`
		)
		.join('\n');

	return `<!doctype html>
<html>
	<head>
		<meta charset="utf-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
		<title>${escapeHtml(args.title)}</title>
		<style>
			:root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
			html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #02020a; }
			#root { position: relative; width: ${width}px; height: ${height}px; overflow: hidden; background: #02020a; color: #f7f7fb; }
			.clip { position: absolute; box-sizing: border-box; }
			.scene-backdrop { inset: 0; background: #02020a; }
			.hero-media-full { inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
			.hero-dim { inset: 0; background: linear-gradient(90deg, rgba(2,2,10,.84) 0%, rgba(2,2,10,.38) 45%, rgba(2,2,10,.62) 100%), linear-gradient(0deg, rgba(2,2,10,.82) 0%, transparent 42%, rgba(2,2,10,.42) 100%); }
				.hero-copy { left: ${portrait ? '58px' : '82px'}; right: ${portrait ? '58px' : '800px'}; bottom: ${portrait ? '170px' : '92px'}; display: grid; gap: 16px; text-shadow: 0 16px 50px rgba(0,0,0,.58); }
				.eyebrow, .kicker { text-transform: uppercase; letter-spacing: .08em; font-size: ${portrait ? '28px' : '18px'}; font-weight: 860; color: #8ea0ff; }
				h1 { margin: 0; max-width: 100%; font-size: ${portrait ? '78px' : '72px'}; line-height: .98; letter-spacing: 0; color: #ffffff; text-wrap: balance; overflow-wrap: anywhere; hyphens: auto; }
				.hero-copy p { margin: 0; max-width: 720px; color: rgba(255,255,255,.74); font-size: ${portrait ? '32px' : '25px'}; line-height: 1.2; font-weight: 720; }
				.direction-card { left: ${portrait ? '58px' : '82px'}; right: ${portrait ? '58px' : '82px'}; top: ${portrait ? '360px' : '190px'}; display: grid; grid-template-columns: ${portrait ? '1fr' : '0.78fr 0.92fr'}; gap: ${portrait ? '30px' : '56px'}; align-items: center; color: #ffffff; text-shadow: 0 16px 50px rgba(0,0,0,.58); }
				.direction-copy { display: grid; gap: 20px; }
				.direction-card h2 { margin: 0; max-width: ${portrait ? '780px' : '980px'}; font-size: ${portrait ? '62px' : '56px'}; line-height: 1; letter-spacing: 0; text-wrap: balance; overflow-wrap: anywhere; hyphens: auto; }
				.direction-card p { margin: 0; max-width: ${portrait ? '780px' : '900px'}; font-size: ${portrait ? '36px' : '30px'}; line-height: 1.14; color: rgba(255,255,255,.78); font-weight: 740; }
				.concept-visual { margin: 0; min-height: 0; height: ${portrait ? '560px' : '650px'}; overflow: hidden; border-radius: 8px; box-shadow: 0 24px 80px rgba(0,0,0,.42); }
				.concept-visual img { width: 100%; height: 100%; object-fit: cover; display: block; }
				.references-card { left: ${portrait ? '58px' : '82px'}; right: ${portrait ? '58px' : '650px'}; top: ${portrait ? '390px' : '210px'}; display: grid; gap: ${portrait ? '28px' : '24px'}; color: #ffffff; text-shadow: 0 16px 50px rgba(0,0,0,.62); }
				.references-card h2 { margin: 0; font-size: ${portrait ? '72px' : '60px'}; line-height: .94; letter-spacing: 0; }
				.references-card p { margin: 0; max-width: ${portrait ? '900px' : '1180px'}; color: rgba(255,255,255,.76); font-size: ${portrait ? '34px' : '27px'}; line-height: 1.18; font-weight: 760; text-wrap: balance; overflow-wrap: anywhere; }
				.references-card ul { margin: ${portrait ? '28px' : '24px'} 0 0; padding: 0; list-style: none; }
				.reference-item { left: ${portrait ? '58px' : '1020px'}; right: ${portrait ? '58px' : '92px'}; min-height: ${portrait ? '108px' : '82px'}; display: flex; align-items: center; gap: 20px; padding: 0 0 0 ${portrait ? '0' : '26px'}; color: #ffffff; font-size: ${portrait ? '39px' : '30px'}; line-height: 1.06; font-weight: 850; text-shadow: 0 16px 50px rgba(0,0,0,.62); border-left: ${portrait ? '0' : '2px solid rgba(142,160,255,.74)'}; }
				.reference-0 { top: ${portrait ? '880px' : '300px'}; }
				.reference-1 { top: ${portrait ? '1030px' : '440px'}; }
				.reference-2 { top: ${portrait ? '1180px' : '580px'}; }
				.reference-item span { flex: 0 0 auto; color: #8ea0ff; font-size: ${portrait ? '25px' : '20px'}; font-weight: 900; }
			.process-heading { left: ${portrait ? '60px' : '210px'}; right: ${portrait ? '60px' : '210px'}; top: ${portrait ? '420px' : '150px'}; display: grid; gap: 8px; text-shadow: 0 16px 50px rgba(0,0,0,.62); }
			.process-heading h2 { margin: 0; color: #ffffff; font-size: ${portrait ? '62px' : '54px'}; line-height: .94; letter-spacing: 0; }
			.gallery-heading { left: ${portrait ? '60px' : '210px'}; right: ${portrait ? '60px' : '210px'}; top: ${portrait ? '420px' : '150px'}; display: grid; gap: 8px; text-shadow: 0 16px 50px rgba(0,0,0,.62); }
			.gallery-heading h2 { margin: 0; color: #ffffff; font-size: ${portrait ? '62px' : '54px'}; line-height: .94; letter-spacing: 0; }
			.process-cell, .texture-cell, .gallery-cell { margin: 0; overflow: hidden; border-radius: 8px; background: rgba(255,255,255,.1); box-shadow: 0 22px 70px rgba(0,0,0,.34); }
			.process-cell img, .texture-cell img, .gallery-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
				.process-cell figcaption, .texture-cell figcaption, .gallery-cell figcaption { position: absolute; left: 0; right: 0; bottom: 0; display: grid; gap: 4px; padding: ${portrait ? '16px' : '13px'}; background: linear-gradient(0deg, rgba(2,2,42,.82), rgba(2,2,42,0)); color: #ffffff; }
				.process-cell strong, .texture-cell strong, .gallery-cell strong { font-size: ${portrait ? '24px' : '20px'}; line-height: 1.03; color: #ffffff; }
				.effort-card { left: ${portrait ? '58px' : '180px'}; right: ${portrait ? '58px' : '180px'}; top: ${portrait ? '470px' : '230px'}; display: grid; gap: ${portrait ? '36px' : '30px'}; color: #ffffff; text-shadow: 0 16px 50px rgba(0,0,0,.62); }
				.effort-card h2 { margin: 0; max-width: ${portrait ? '820px' : '980px'}; font-size: ${portrait ? '76px' : '66px'}; line-height: .94; letter-spacing: 0; }
				.effort-grid { display: grid; grid-template-columns: repeat(${portrait ? 2 : 5}, minmax(0, 1fr)); gap: ${portrait ? '18px' : '20px'}; }
				.effort-item { min-height: ${portrait ? '168px' : '142px'}; display: grid; align-content: center; gap: 8px; border-top: 2px solid rgba(142,160,255,.72); }
				.effort-item strong { font-size: ${portrait ? '60px' : '54px'}; line-height: .92; color: #ffffff; }
				.effort-item span { color: rgba(255,255,255,.72); font-size: ${portrait ? '27px' : '22px'}; line-height: 1.08; font-weight: 850; text-transform: uppercase; letter-spacing: .08em; }
				.structure-card { left: ${portrait ? '58px' : '180px'}; right: ${portrait ? '58px' : '180px'}; top: ${portrait ? '360px' : '180px'}; bottom: ${portrait ? '310px' : '150px'}; display: grid; grid-template-columns: ${portrait ? '1fr' : '0.7fr 1.3fr'}; gap: ${portrait ? '28px' : '42px'}; align-items: start; color: #ffffff; text-shadow: 0 16px 50px rgba(0,0,0,.62); }
			.structure-card h2 { margin: 0; font-size: ${portrait ? '66px' : '56px'}; line-height: .96; letter-spacing: 0; }
			.structure-tree { margin: 0; max-height: 100%; overflow: hidden; white-space: pre; font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; color: rgba(255,255,255,.82); font-size: ${portrait ? '24px' : '24px'}; line-height: 1.22; font-weight: 760; }
		</style>
	</head>
	<body>
		<script src="./gsap.min.js"></script>
		<div id="root" data-composition-id="spellshape-reel" data-start="0" data-duration="${totalDuration.toFixed(2)}" data-width="${width}" data-height="${height}">
			<div class="scene-backdrop clip" data-start="0" data-duration="${totalDuration.toFixed(2)}"></div>
			${heroMediaHtml}
			<div class="hero-dim clip" data-start="0" data-duration="${heroDuration.toFixed(2)}"></div>
			<section class="hero-copy clip" data-start="0.15" data-duration="${(heroDuration - 0.25).toFixed(2)}">
				<div class="eyebrow">${escapeHtml(args.openingLabel)}</div>
				<h1>${escapeHtml(args.title)}</h1>
				<p>${escapeHtml(args.animation)}</p>
			</section>
			<section class="direction-card clip" data-start="${directionStart.toFixed(2)}" data-duration="${directionDuration.toFixed(2)}">
				<div class="direction-copy">
					<div class="eyebrow">Concept</div>
					<h2>${escapeHtml(args.title)}</h2>
					<p>${escapeHtml(args.direction)}</p>
				</div>
				${conceptVisualHtml}
			</section>
			${
				args.references.length
					? `<section class="references-card clip" data-start="${referenceStart.toFixed(2)}" data-duration="${referenceDuration.toFixed(2)}">
						<div>
							<div class="eyebrow">References</div>
							<h2>${escapeHtml(args.referenceTitle)}</h2>
							<p>${escapeHtml(args.referenceLine)}</p>
						</div>
					</section>`
					: ''
			}
			${referenceHtml}
			${
				processCards.length
					? `<section class="process-heading clip" data-start="${processStart.toFixed(2)}" data-duration="${processDuration.toFixed(2)}">
						<div class="eyebrow">Process</div>
						<h2>${escapeHtml(args.processTitle)}</h2>
					</section>`
					: ''
			}
			${processHtml}
			${
				textureCards.length
					? `<section class="gallery-heading clip" data-start="${textureStart.toFixed(2)}" data-duration="${textureDuration.toFixed(2)}">
						<div class="eyebrow">Generated textures</div>
						<h2>UV texture gallery</h2>
					</section>`
					: ''
			}
			${textureHtml}
			${
				galleryCards.length
					? `<section class="gallery-heading clip" data-start="${galleryStart.toFixed(2)}" data-duration="${galleryDuration.toFixed(2)}">
						<div class="eyebrow">Final model</div>
						<h2>Screenshot gallery</h2>
					</section>`
					: ''
			}
			${galleryHtml}
			${
				effort.length
					? `<section class="effort-card clip" data-start="${effortStart.toFixed(2)}" data-duration="${effortDuration.toFixed(2)}">
						<div>
							<div class="eyebrow">Agent effort</div>
							<h2>What it took to make the scene</h2>
						</div>
						<div class="effort-grid">${effortHtml}</div>
					</section>`
					: ''
			}
			<section class="structure-card clip" data-start="${structureStart.toFixed(2)}" data-duration="${structureDuration.toFixed(2)}">
				<div>
					<div class="eyebrow">Project package</div>
					<h2>${escapeHtml(args.structureTitle)}</h2>
				</div>
				<pre class="structure-tree">${escapeHtml(structureTree)}</pre>
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
	await assertFfmpegAvailable();
	let body: ReelBody;
	try {
		body = (await request.json()) as ReelBody;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const aspectRatio: ReelAspectRatio = body.aspectRatio === '16:9' ? '16:9' : '9:16';
	const direction = parseDirection(body.creativeDirectionJson);
	const title = projectTitle(direction);
	const heroLabel = openingLabel(direction);
	const animation = animationSummary(direction);
	const summary = directionSummary(direction, body.renderPrompt);
	const referencesTitle = referenceTitle(direction);
	const referencesLine = referenceLine(direction);
	const references = referenceList(direction);
	const buildTitle = processTitle(direction);
	const buildSteps = processSteps(direction);
	const packageTitle = structureTitle(direction);
	const projectStructure = structureEntries(body.projectStructure);
	const workspaceDir = path.join(tmpdir(), `spellshape-reel-${randomUUID()}`);
	const assetsDir = path.join(workspaceDir, 'assets');
	const outputPath = path.join(workspaceDir, 'spellshape-reel.mp4');

	try {
		await mkdir(assetsDir, { recursive: true });
		await copyFile(
			path.join(process.cwd(), 'node_modules', 'gsap', 'dist', 'gsap.min.js'),
			path.join(workspaceDir, 'gsap.min.js')
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
					.map((item, index) => writeAsset(assetsDir, item, index, 'video', `clip-${index + 1}`))
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const processImages = (
			await Promise.all(
				(body.processImages ?? [])
					.slice(0, MAX_PROCESS_IMAGES)
					.map((item, index) => writeAsset(assetsDir, item, index, 'image', `process-${index + 1}`))
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const textureImages = (
			await Promise.all(
				(body.textureImages ?? [])
					.slice(0, MAX_TEXTURE_IMAGES)
					.map((item, index) => writeAsset(assetsDir, item, index, 'image', `texture-${index + 1}`))
			)
		).filter((asset): asset is WrittenAsset => !!asset);
		const galleryImages = (
			await Promise.all(
				(body.galleryFrames ?? [])
					.slice(0, MAX_GALLERY_IMAGES)
					.map((item, index) => writeAsset(assetsDir, item, index, 'image', `frame-${index + 1}`))
			)
		).filter((asset): asset is WrittenAsset => !!asset);
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
				openingLabel: heroLabel,
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
				projectStructure,
				agentMetrics
			})
		);

		const cliPath = path.join(process.cwd(), 'node_modules', 'hyperframes', 'dist', 'cli.js');
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
				env: renderEnvironment()
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
