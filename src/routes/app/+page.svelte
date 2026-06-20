<script lang="ts">
	import * as THREE from 'three';
	import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
	import Canvas3D from '$lib/components/Canvas3D.svelte';
	import LiveObjSidePanel from '$lib/components/live-obj/LiveObjSidePanel.svelte';
	import type { SourceTab } from '$lib/components/live-obj/LiveObjOutputTab.svelte';
	import { stripLiveObjMeshLines } from '$lib/liveObj/stripLiveObjMeshLines';
	import { hasProceduralLiveSources, normalizeRawPostHeader } from '$lib/liveObj/rawPostHeader';
	import { browser } from '$app/environment';
	import { onMount, tick } from 'svelte';

	type ChatMsg = {
		role: 'user' | 'assistant';
		content: string;
		imageDataUrl?: string;
		historyContent?: string;
		meta?: string;
		tokenUsage?: TokenUsageSummary;
		transient?: boolean;
		excludeFromHistory?: boolean;
	};

	type IterativePartSpec = {
		id: string;
		role?: string;
		prompt?: string;
		dependencies?: string[];
		method?: string;
		postProcess?: IterativePartPostProcess;
		priority?: number;
		validationHints?: string[];
		cameraFocus?: string[];
	};

	type IterativePartPostProcess = {
		type?: string;
		targetObjectId?: string;
		prompt?: string;
		mode?: string;
		amount?: number;
	};

	type IterativeScenePlan = {
		scene?: string;
		units?: string;
		up?: string;
		visual?: {
			backgroundColor?: string;
			ambientLightIntensity?: number;
			directionalLightIntensity?: number;
			cameraFov?: number;
			toneMappingExposure?: number;
			canvasAspectRatio?: string;
			cameraView?: string;
			cameraFocus?: string[];
		};
		materials?: Array<{
			id: string;
			color?: string;
			roughness?: number;
			metalness?: number;
			role?: string;
		}>;
		parts: IterativePartSpec[];
		notes?: string[];
	};

	type TokenUsageSummary = {
		promptTokens?: number;
		completionTokens?: number;
		totalTokens?: number;
		reasoningTokens?: number;
		cachedTokens?: number;
	};

	type SendPromptPayload = {
		text: string;
		useProcedural?: boolean;
		targetObjectId?: string;
		imageDataUrl?: string;
		imageDataUrls?: string[];
		feedbackLoop?: boolean;
		feedbackPasses?: number;
	};

	type CanvasAspectRatio =
		| 'fill'
		| '1:1'
		| '4:3'
		| '16:9'
		| '9:16'
		| '4:5'
		| '3:2'
		| '2:3'
		| '21:9';

	type CameraSnapshot = {
		projection?: string;
		position?: number[];
		target?: number[];
		up?: number[];
		fov?: number | null;
		zoom?: number | null;
	} | null;

	type FrameAsset = {
		id: string;
		label: string;
		source: 'screenshot' | 'generated';
		imageDataUrl: string;
		camera: CameraSnapshot;
		capturedAt: number;
	};

	type ShotFrame = {
		imageDataUrl: string;
		camera: CameraSnapshot;
		capturedAt: number;
	};

	type GeneratedClip = {
		id: string;
		status: string;
		label?: string;
		videoUrl?: string;
		jobId?: string;
		error?: string;
	};

	type VideoShot = {
		start?: ShotFrame;
		middle?: ShotFrame;
		end?: ShotFrame;
		transitionPrompts?: Partial<Record<'startToMiddle' | 'middleToEnd', string>>;
		clips: GeneratedClip[];
	};

	type ProcessImageAsset = {
		label: string;
		meta?: string;
		imageDataUrl: string;
	};
	type ModelUsage = {
		role: string;
		provider: string;
		model: string;
		usedAt: number;
	};

	type LiveObjApiPayload = {
		message?: string;
		liveObj?: string;
		rawLlm?: string;
		executedObj?: string;
		executorWarning?: string;
		editMode?: 'surgical' | 'rewrite';
		surgicalEditSummary?: string;
		assistantMessage?: string;
		llmUsage?: TokenUsageSummary;
	};

	type IterativePlanPayload = {
		message?: string;
		plan?: IterativeScenePlan;
		rawLlm?: string;
		llmUsage?: TokenUsageSummary;
	};

	type IterativePlanSuccessPayload = IterativePlanPayload & {
		plan: IterativeScenePlan;
	};

	type IterativePlanStreamEvent =
		| { type: 'status'; message?: string }
		| ({ type: 'final' } & IterativePlanPayload)
		| { type: 'error'; message?: string };

	type IterativeAppendPayload = {
		message?: string;
		liveObj?: string;
		partObj?: string;
		rawLlm?: string;
		executedObj?: string;
		validation?: {
			valid: boolean;
			errors: string[];
			warnings: string[];
			objectNames: string[];
			addedObjectNames: string[];
		};
		executorWarnings?: string[];
		llmUsage?: TokenUsageSummary;
	};

	type IterativeAppendStreamEvent =
		| { type: 'status'; message?: string }
		| { type: 'preview_line'; line: string }
		| ({ type: 'final' } & IterativeAppendPayload)
		| { type: 'error'; message?: string };

	type DreamMap = { width: number; height: number; rows: string[] };

	type DreamRebuildPayload = {
		message?: string;
		liveObj?: string;
		executedObj?: string;
		dream?: {
			status?: string;
			warnings?: string[];
		};
	};

	type UvDreamPayload = {
		message?: string;
		liveObj?: string;
		executedObj?: string;
		sourceUvUrl?: string;
		sourceGuideUrl?: string;
		artifacts?: Record<string, string>;
		warnings?: string[];
	};

	let showPanel = $state(true);
	let msgs = $state<ChatMsg[]>([]);
	let busy = $state(false);
	let statusLine = $state<string | null>(null);
	let iterativeGenerationActive = $state(false);
	let feedbackLoopActive = $state(false);
	let activeGenerationAbortController = $state<AbortController | null>(null);

	let sourceTab = $state<SourceTab>('executed');
	let liveObjText = $state(`#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@workflow: raw_post
o cube
v -0.5 -0.5 0.2
v 0.5 -0.5 0.2
v 0.5 0.5 0.2
v -0.5 0.5 0.2
v -0.5 -0.5 1.2
v 0.5 -0.5 1.2
v 0.5 0.5 1.2
v -0.5 0.5 1.2
f 1 2 3
f 1 3 4
f 5 8 7
f 5 7 6
f 1 5 6
f 1 6 2
f 2 6 7
f 2 7 3
f 3 7 8
f 3 8 4
f 4 8 5
f 4 5 1
`);
	let currentSceneMode = $state<'live_obj' | 'raw_obj'>('raw_obj');
	let selectedTargetObjectId = $state('');
	const targetObjectOptions = $derived(objectNamesFromLiveObj(liveObjText));
	let rawLlmText = $state('');
	let executedObjText = $state('');
	let sceneEpoch = $state(0);
	let sourceApplyBusy = $state(false);
	let kernelDefault = $state<'auto' | 'cadquery'>('cadquery');
	let renderingMode = $state<'standard' | 'outline' | 'toon'>('standard');
	let outlineThickness = $state(1);
	let outlineDepthSensitivity = $state(1);
	let outlineNormalSensitivity = $state(1);
	let toonSteps = $state<2 | 3 | 4 | 5>(3);
	let toonOutline = $state(true);
	let renderObject = $state<THREE.Object3D | null>(null);

	const DEFAULT_CANVAS_BACKGROUND = '#3a3a36';
	const DEFAULT_CLAY_MATERIAL = {
		color: '#e6e4dd',
		metalness: 0,
		roughness: 0.82
	};
	const PART_FALLBACK_PALETTE = [
		'#e6e4dd',
		'#d6d9d8',
		'#aeb7bd',
		'#575c63',
		'#d6d3e6',
		'#cfdccf',
		'#e5dcba'
	];
	const CANVAS_ASPECT_RATIOS: Record<
		Exclude<CanvasAspectRatio, 'fill'>,
		{ css: string; value: number }
	> = {
		'1:1': { css: '1 / 1', value: 1 },
		'4:3': { css: '4 / 3', value: 4 / 3 },
		'16:9': { css: '16 / 9', value: 16 / 9 },
		'9:16': { css: '9 / 16', value: 9 / 16 },
		'4:5': { css: '4 / 5', value: 4 / 5 },
		'3:2': { css: '3 / 2', value: 3 / 2 },
		'2:3': { css: '2 / 3', value: 2 / 3 },
		'21:9': { css: '21 / 9', value: 21 / 9 }
	};

	let backgroundColor = $state(DEFAULT_CANVAS_BACKGROUND);
	let canvasAspectRatio = $state<CanvasAspectRatio>('fill');
	let canvasFrameAspectRatio = $derived(
		canvasAspectRatio === 'fill' ? '' : CANVAS_ASPECT_RATIOS[canvasAspectRatio].css
	);
	let canvasFrameAspectValue = $derived(
		canvasAspectRatio === 'fill' ? 1 : CANVAS_ASPECT_RATIOS[canvasAspectRatio].value
	);
	let showGrid = $state(false);
	let showAxes = $state(false);
	let ambientLightIntensity = $state(1);
	let directionalLightIntensity = $state(1.5);
	let wireframe = $state(false);
	let enableShadows = $state(true);
	let fogEnabled = $state(false);
	let fogNear = $state(10);
	let fogFar = $state(50);
	let fogColor = $state('#f8fafc');
	let cameraFov = $state(50);
	let toneMappingExposure = $state(1);
	let planCameraDirection = $state<[number, number, number] | undefined>(undefined);
	let planCameraFocus = $state<string[]>([]);

	let objectColor = $state(DEFAULT_CLAY_MATERIAL.color);
	let objectScale = $state(1);
	let objectPosX = $state(0);
	let objectPosY = $state(0);
	let objectPosZ = $state(0);
	let objectRotYDeg = $state(0);
	let preserveObjMaterials = $state(false);
	let canvasRef = $state<Canvas3D | null>(null);
	let renderFrameAssets = $state<FrameAsset[]>([]);
	let renderVideoShot = $state<VideoShot>({ clips: [] });
	let renderTurntableFrameAssets = $state<FrameAsset[]>([]);
	let renderModelUsage = $state<ModelUsage[]>([]);
	let projectProcessImages = $state<ProcessImageAsset[]>([]);

	function providerLabel(value: string): string {
		const normalized = value.trim().toLowerCase();
		if (normalized === 'openai') return 'OpenAI';
		if (normalized === 'google') return 'Google';
		if (normalized === 'openrouter') return 'OpenRouter';
		return value.trim() || 'Provider';
	}

	function recordRenderModelUsage(role: string, providerValue: string, model: string | undefined) {
		const cleanModel = model?.trim();
		if (!cleanModel) return;
		const provider = providerLabel(providerValue);
		const existingIndex = renderModelUsage.findIndex(
			(item) => item.role === role && item.provider === provider && item.model === cleanModel
		);
		const entry = { role, provider, model: cleanModel, usedAt: Date.now() };
		renderModelUsage =
			existingIndex >= 0
				? renderModelUsage.map((item, index) => (index === existingIndex ? entry : item))
				: [...renderModelUsage, entry].slice(-8);
	}

	function materialColorFromName(name: string): THREE.Color {
		let hash = 0;
		for (let i = 0; i < name.length; i += 1) {
			hash = (hash << 5) - hash + name.charCodeAt(i);
			hash |= 0;
		}
		const index = Math.abs(hash) % PART_FALLBACK_PALETTE.length;
		return new THREE.Color(PART_FALLBACK_PALETTE[index]);
	}

	type MaterialPreset = {
		color?: string;
		metalness?: number;
		roughness?: number;
		shadeSmooth?: boolean;
	};

	type TextureTags = {
		diffuse?: string;
		height?: string;
	};

	type ParsedTextureTags = {
		byObject: Map<string, TextureTags>;
		global: TextureTags;
	};

	const UV_ATLAS_SIZE = 1024;
	const UV_ATLAS_ASPECT_RATIO = '1:1';
	const textureCache = new Map<string, THREE.Texture>();
	const MAX_MODEL_HISTORY_CHARS = 60_000;

	function stripDreamVertexCacheLines(text: string): string {
		return text
			.split(/\r?\n/)
			.filter((line) => !/^#@dream_(?:base|delta)_v\b/i.test(line.trim()))
			.join('\n');
	}

	function modelHistoryContent(content: string): string {
		const stripped = stripDreamVertexCacheLines(content);
		if (stripped.length <= MAX_MODEL_HISTORY_CHARS) return stripped;
		const compact = stripLiveObjMeshLines(stripped);
		if (compact.length <= MAX_MODEL_HISTORY_CHARS) {
			return `${compact}\n#@note: mesh cache omitted from chat history for token budget`;
		}
		return `${compact.slice(0, MAX_MODEL_HISTORY_CHARS)}\n#@note: chat history truncated for token budget`;
	}

	function parsePresetBool(value: string | undefined): boolean | undefined {
		if (value == null) return undefined;
		const normalized = value.trim().toLowerCase();
		if (['1', 'true', 'yes', 'on', 'smooth'].includes(normalized)) return true;
		if (['0', 'false', 'no', 'off', 'flat'].includes(normalized)) return false;
		return undefined;
	}

	function parseMaterialPresets(sourceText: string): Map<string, MaterialPreset> {
		const presets = new Map<string, MaterialPreset>();
		for (const rawLine of sourceText.split(/\r?\n/)) {
			const lineMatch = rawLine.match(/^\s*#@material_preset:\s*([a-zA-Z0-9_\-.]+)\s*(.*)$/);
			if (!lineMatch) continue;
			const name = lineMatch[1].trim();
			const tail = lineMatch[2] ?? '';
			const preset: MaterialPreset = {};
			const colorMatch = tail.match(/color=([#a-zA-Z0-9_\-.]+)/);
			if (colorMatch) preset.color = colorMatch[1];
			const metalnessMatch = tail.match(/metalness=([-+]?\d*\.?\d+)/);
			if (metalnessMatch) preset.metalness = Number(metalnessMatch[1]);
			const roughnessMatch = tail.match(/roughness=([-+]?\d*\.?\d+)/);
			if (roughnessMatch) preset.roughness = Number(roughnessMatch[1]);
			const shadeSmoothMatch = tail.match(/shade_smooth=([a-zA-Z0-9_\-.]+)/);
			const flatShadingMatch = tail.match(/flat_shading=([a-zA-Z0-9_\-.]+)/);
			const shadeSmooth = parsePresetBool(shadeSmoothMatch?.[1]);
			const flatShading = parsePresetBool(flatShadingMatch?.[1]);
			if (shadeSmooth !== undefined) preset.shadeSmooth = shadeSmooth;
			if (flatShading !== undefined) preset.shadeSmooth = !flatShading;
			presets.set(name, preset);
		}
		return presets;
	}

	function parseObjectMaterialTags(sourceText: string): Map<string, string> {
		const byObject = new Map<string, string>();
		let currentObject: string | null = null;
		const tokenValue = (raw: string, key: string): string | undefined => {
			const match = raw.match(new RegExp(`(?:^|\\s)${key}=([a-zA-Z0-9_\\-.]+)`));
			return match?.[1];
		};
		for (const line of sourceText.split(/\r?\n/)) {
			const objectMatch = line.match(/^\s*[og]\s+([^\s#]+)/);
			if (objectMatch) {
				currentObject = objectMatch[1];
				continue;
			}
			if (!currentObject) continue;
			const opListMaterialMatch = line.match(/^\s*#@\s*-\s*material\s+name=([a-zA-Z0-9_\-.]+)\s*$/);
			if (opListMaterialMatch) {
				byObject.set(currentObject, opListMaterialMatch[1]);
				continue;
			}
			const inlineMaterialMatch = line.match(/^\s*#@material:\s*(?:name=)?([a-zA-Z0-9_\-.]+)\s*$/);
			if (inlineMaterialMatch) byObject.set(currentObject, inlineMaterialMatch[1]);
			const inlinePostMaterialMatch = line.match(/^\s*#@post\s+material\s+(.+)$/);
			if (inlinePostMaterialMatch) {
				const rest = inlinePostMaterialMatch[1];
				const materialName = tokenValue(rest, 'name') ?? tokenValue(rest, 'id');
				const target = tokenValue(rest, 'target') ?? currentObject;
				if (materialName && target) byObject.set(target, materialName);
			}
		}
		return byObject;
	}

	function parseMetadataToken(raw: string, key: string): string | undefined {
		const match = raw.match(new RegExp(`(?:^|\\s)${key}=("[^"]+"|'[^']+'|\\S+)`));
		return match?.[1]?.replace(/^['"]|['"]$/g, '');
	}

	function parseObjectTextureTags(sourceText: string): ParsedTextureTags {
		const byObject = new Map<string, TextureTags>();
		const global: TextureTags = {};
		let currentObject: string | null = null;
		const setTexture = (target: TextureTags, kind: string, path: string) => {
			const normalizedKind = kind.toLowerCase();
			if (
				normalizedKind === 'diffuse' ||
				normalizedKind === 'albedo' ||
				normalizedKind === 'color'
			) {
				target.diffuse = path;
			} else if (normalizedKind === 'height' || normalizedKind === 'depth') {
				target.height = path;
			}
		};
		for (const line of sourceText.split(/\r?\n/)) {
			const objectMatch = line.match(/^\s*[og]\s+([^\s#]+)/);
			if (objectMatch) {
				currentObject = objectMatch[1];
				continue;
			}
			const textureMatch = line.match(/^\s*#@texture:\s*(.+)$/);
			if (!textureMatch) continue;
			const rest = textureMatch[1];
			const path = parseMetadataToken(rest, 'path') ?? parseMetadataToken(rest, 'src');
			if (!path) continue;
			const kind = parseMetadataToken(rest, 'kind') ?? rest.trim().split(/\s+/)[0] ?? 'diffuse';
			const target = currentObject ? (byObject.get(currentObject) ?? {}) : global;
			setTexture(target, kind, path);
			if (currentObject) byObject.set(currentObject, target);
		}
		return { byObject, global };
	}

	function hasTextureTags(tags: ParsedTextureTags): boolean {
		return Boolean(tags.global.diffuse || tags.global.height || tags.byObject.size > 0);
	}

	function resolveTextureUrl(path: string, version = sceneEpoch): string {
		const trimmed = path.trim();
		if (/^(data:|blob:|https?:\/\/)/i.test(trimmed)) return trimmed;
		if (/^\/api\//i.test(trimmed)) return trimmed;
		const projectFileMatch = trimmed.match(/(?:^|[/\\])(project_live_obj_files[/\\].+)$/);
		if (projectFileMatch) {
			return `/api/project-file?path=${encodeURIComponent(projectFileMatch[1].replace(/\\/g, '/'))}&v=${version}`;
		}
		return `/api/project-file?path=${encodeURIComponent(trimmed)}&v=${version}`;
	}

	function textureForPath(path: string | undefined): THREE.Texture | null {
		if (!browser || !path) return null;
		const url = resolveTextureUrl(path);
		const cached = textureCache.get(url);
		if (cached) return cached;
		const texture = new THREE.TextureLoader().load(
			url,
			(loadedTexture) => {
				loadedTexture.needsUpdate = true;
			},
			undefined,
			() => {
				console.warn(`Failed to load Live OBJ texture: ${url}`);
			}
		);
		// OBJ texture coordinates are authored from a bottom-left UV origin; Three's
		// default image upload flip keeps the top-left PNG rows aligned with those vt values.
		texture.flipY = true;
		texture.colorSpace = THREE.SRGBColorSpace;
		texture.wrapS = THREE.RepeatWrapping;
		texture.wrapT = THREE.ClampToEdgeWrapping;
		textureCache.set(url, texture);
		return texture;
	}

	function hasAuthoredUvTextureMesh(sourceText: string): boolean {
		return /^\s*#@texture:\s*/im.test(sourceText) && /^\s*vt\s+/im.test(sourceText);
	}

	type ObjRef = { v: number; vt?: number; vn?: number };
	type ObjBlock = {
		name: string;
		lines: string[];
		v: string[];
		vt: string[];
		vn: string[];
		vp: string[];
		otherMesh: string[];
		faces: ObjRef[][];
	};

	function objToken(line: string): string {
		return /^(\S+)/.exec(line.trim())?.[1]?.toLowerCase() ?? '';
	}

	function objIndex(raw: string | undefined, total: number): number | undefined {
		if (!raw) return undefined;
		const parsed = Number(raw);
		if (!Number.isInteger(parsed) || parsed === 0) return undefined;
		return parsed < 0 ? total + parsed + 1 : parsed;
	}

	function parseObjForDisplay(text: string): { header: string[]; blocks: ObjBlock[] } {
		const header: string[] = [];
		const blocks: ObjBlock[] = [];
		let current: ObjBlock | null = null;
		let totalV = 0;
		let totalVt = 0;
		let totalVn = 0;
		const vOwner = new Map<number, { block: ObjBlock; local: number }>();
		const vtOwner = new Map<number, { block: ObjBlock; local: number }>();
		const vnOwner = new Map<number, { block: ObjBlock; local: number }>();
		for (const line of text.split(/\r?\n/)) {
			const objectMatch = line.match(/^\s*o\s+([^\s#]+)/);
			if (objectMatch) {
				current = {
					name: objectMatch[1],
					lines: [line],
					v: [],
					vt: [],
					vn: [],
					vp: [],
					otherMesh: [],
					faces: []
				};
				blocks.push(current);
				continue;
			}
			if (!current) {
				header.push(line);
				continue;
			}
			const token = objToken(line);
			if (token === 'v') {
				current.v.push(line);
				totalV += 1;
				vOwner.set(totalV, { block: current, local: current.v.length });
			} else if (token === 'vt') {
				current.vt.push(line);
				totalVt += 1;
				vtOwner.set(totalVt, { block: current, local: current.vt.length });
			} else if (token === 'vn') {
				current.vn.push(line);
				totalVn += 1;
				vnOwner.set(totalVn, { block: current, local: current.vn.length });
			} else if (token === 'vp') {
				current.vp.push(line);
			} else if (token === 'f') {
				const refs: ObjRef[] = [];
				let valid = true;
				for (const rawRef of line.trim().split(/\s+/).slice(1)) {
					const [vRaw, vtRaw, vnRaw] = rawRef.split('/');
					const vIndex = objIndex(vRaw, totalV);
					const vtIndex = objIndex(vtRaw, totalVt);
					const vnIndex = objIndex(vnRaw, totalVn);
					const v = vIndex ? vOwner.get(vIndex) : undefined;
					const vt = vtIndex ? vtOwner.get(vtIndex) : undefined;
					const vn = vnIndex ? vnOwner.get(vnIndex) : undefined;
					if (
						!v ||
						v.block !== current ||
						(vt && vt.block !== current) ||
						(vn && vn.block !== current)
					) {
						valid = false;
						break;
					}
					refs.push({
						v: v.local,
						...(vt ? { vt: vt.local } : {}),
						...(vn ? { vn: vn.local } : {})
					});
				}
				if (valid && refs.length >= 3) current.faces.push(refs);
				else current.otherMesh.push(line);
			} else if (token === 'fo' || token === 'l') {
				current.otherMesh.push(line);
			} else {
				current.lines.push(line);
			}
		}
		return { header, blocks };
	}

	function refText(ref: ObjRef, offsets: { v: number; vt: number; vn: number }): string {
		const v = ref.v + offsets.v;
		if (ref.vt != null && ref.vn != null)
			return `${v}/${ref.vt + offsets.vt}/${ref.vn + offsets.vn}`;
		if (ref.vt != null) return `${v}/${ref.vt + offsets.vt}`;
		if (ref.vn != null) return `${v}//${ref.vn + offsets.vn}`;
		return String(v);
	}

	function appendObjBlock(
		out: string[],
		block: ObjBlock,
		offsets: { v: number; vt: number; vn: number }
	) {
		if (out.length > 0 && out[out.length - 1].trim() !== '') out.push('');
		out.push(...block.lines.filter((line) => line.trim()));
		out.push(...block.v, ...block.vt, ...block.vn, ...block.vp, ...block.otherMesh);
		for (const face of block.faces) {
			out.push(`f ${face.map((ref) => refText(ref, offsets)).join(' ')}`);
		}
	}

	function uvDreamObjectNames(sourceText: string): Set<string> {
		const names = new Set<string>();
		for (const block of sourceText.split(/(?=^\s*o\s+)/gm)) {
			const name = block.match(/^\s*o\s+([^\s#]+)/m)?.[1];
			if (
				name &&
				/^\s*#@workflow_step:\s*uv_dream_enhance\b/im.test(block) &&
				/^\s*vt\s+/im.test(block)
			) {
				names.add(name);
			}
		}
		return names;
	}

	function displayObjWithAuthoredUvBlocks(sourceText: string, executedText: string): string {
		const replaceNames = uvDreamObjectNames(sourceText);
		if (replaceNames.size === 0) return executedText;
		const source = parseObjForDisplay(sourceText);
		const executed = parseObjForDisplay(executedText);
		const sourceByName = new Map(source.blocks.map((block) => [block.name, block]));
		const out = executed.header.filter((line) => line.trim());
		const existingHeader = new Set(out.map((line) => line.trim()));
		for (const line of source.header) {
			const trimmed = line.trim();
			if (trimmed.startsWith('#@material_preset:') && !existingHeader.has(trimmed)) {
				out.push(line);
				existingHeader.add(trimmed);
			}
		}
		let offsets = { v: 0, vt: 0, vn: 0 };
		const emitted = new Set<string>();
		for (const executedBlock of executed.blocks) {
			const block =
				replaceNames.has(executedBlock.name) && sourceByName.has(executedBlock.name)
					? sourceByName.get(executedBlock.name)!
					: executedBlock;
			appendObjBlock(out, block, offsets);
			emitted.add(block.name);
			offsets = {
				v: offsets.v + block.v.length,
				vt: offsets.vt + block.vt.length,
				vn: offsets.vn + block.vn.length
			};
		}
		for (const name of replaceNames) {
			const block = sourceByName.get(name);
			if (!block || emitted.has(name)) continue;
			appendObjBlock(out, block, offsets);
			offsets = {
				v: offsets.v + block.v.length,
				vt: offsets.vt + block.vt.length,
				vn: offsets.vn + block.vn.length
			};
		}
		return `${out.join('\n').trimEnd()}\n`;
	}

	function displayObjForSource(
		sourceText: string,
		executedText: string | undefined | null
	): string {
		const executed = String(executedText ?? '');
		if (hasAuthoredUvTextureMesh(sourceText) && executed.trim()) {
			return displayObjWithAuthoredUvBlocks(sourceText, executed);
		}
		if (hasAuthoredUvTextureMesh(sourceText)) return sourceText;
		return String(executedText ?? sourceText);
	}

	function getLiveObjUpAxis(objText: string): 'x' | 'y' | 'z' {
		const m = objText.match(/^\s*#@up:\s*([xyz])\s*$/im);
		const axis = (m?.[1] ?? 'y').toLowerCase();
		return axis === 'x' || axis === 'z' ? axis : 'y';
	}

	function objectNamesFromLiveObj(sourceText: string): string[] {
		const names = [...sourceText.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1]);
		return [...new Set(names)];
	}

	function readableObjectName(name: string): string {
		return name.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
	}

	function summarizeObjectNames(names: string[], max = 4): string {
		const readable = names.map(readableObjectName).filter(Boolean);
		if (readable.length <= max) return readable.join(', ');
		return `${readable.slice(0, max).join(', ')} and ${readable.length - max} more parts`;
	}

	function editVerbFromPrompt(promptText: string): string {
		const lower = promptText.toLowerCase();
		if (/\b(add|insert|create|make|put|include|attach)\b/.test(lower)) return 'Added';
		if (/\b(remove|delete|erase|drop|hide)\b/.test(lower)) return 'Removed';
		if (
			/\b(bigger|smaller|scale|resize|move|rotate|reposition|color|material|detail|adjust|change|modify|update|edit)\b/.test(
				lower
			)
		)
			return 'Adjusted';
		return 'Updated';
	}

	const SUMMARY_STOP_WORDS = new Set([
		'add',
		'insert',
		'create',
		'make',
		'put',
		'include',
		'attach',
		'remove',
		'delete',
		'erase',
		'drop',
		'hide',
		'bigger',
		'smaller',
		'scale',
		'resize',
		'move',
		'rotate',
		'reposition',
		'color',
		'material',
		'detail',
		'detailed',
		'adjust',
		'change',
		'modify',
		'update',
		'edit',
		'the',
		'and',
		'with',
		'nearby',
		'next',
		'from',
		'into',
		'more',
		'less',
		'can',
		'you',
		'please',
		'part',
		'parts',
		'scene',
		'object',
		'objects',
		'robot',
		'droid'
	]);

	function promptSummaryTerms(promptText: string): string[] {
		return [...new Set(promptText.toLowerCase().match(/[a-z0-9]+/g) ?? [])].filter(
			(term) => term.length > 2 && !SUMMARY_STOP_WORDS.has(term)
		);
	}

	function namesMatchingPrompt(names: string[], promptText: string): string[] {
		const terms = promptSummaryTerms(promptText);
		if (terms.length === 0) return [];
		return names.filter((name) => {
			const readable = readableObjectName(name).toLowerCase();
			return terms.some((term) => readable.includes(term));
		});
	}

	function parsePatchEdits(rawPatch: string): Array<{ find: string; replace: string }> {
		const cleaned = rawPatch
			.replace(/^```[a-z]*\n?/i, '')
			.replace(/\n?```$/i, '')
			.trim();
		const candidates = [cleaned];
		const start = cleaned.indexOf('{');
		const end = cleaned.lastIndexOf('}');
		if (start >= 0 && end > start) candidates.push(cleaned.slice(start, end + 1));
		for (const candidate of candidates) {
			try {
				const parsed = JSON.parse(candidate) as { edits?: unknown };
				if (!Array.isArray(parsed.edits)) continue;
				return parsed.edits.filter((edit): edit is { find: string; replace: string } => {
					if (!edit || typeof edit !== 'object') return false;
					const e = edit as { find?: unknown; replace?: unknown };
					return typeof e.find === 'string' && typeof e.replace === 'string';
				});
			} catch {}
		}
		return [];
	}

	function objectNameForSnippet(sceneText: string, snippet: string): string | null {
		const index = sceneText.indexOf(snippet);
		if (index < 0) return null;
		let current: string | null = null;
		for (const match of sceneText.matchAll(/^\s*o\s+([^\s#]+)/gm)) {
			const matchIndex = match.index ?? 0;
			if (matchIndex > index) break;
			current = match[1];
		}
		return current;
	}

	function patchTouchedObjectNames(
		rawPatch: string,
		previousLiveObj: string,
		nextLiveObj: string
	): string[] {
		const touched: string[] = [];
		for (const edit of parsePatchEdits(rawPatch)) {
			const fromFind = objectNameForSnippet(previousLiveObj, edit.find);
			if (fromFind) touched.push(fromFind);
			for (const name of objectNamesFromLiveObj(edit.replace)) touched.push(name);
			const fromReplace = objectNameForSnippet(nextLiveObj, edit.replace);
			if (fromReplace) touched.push(fromReplace);
		}
		return [...new Set(touched)];
	}

	function summarizeAssistantResult(args: {
		promptText: string;
		previousLiveObj: string;
		nextLiveObj: string;
		rawLlm: string;
		isIterativeEdit: boolean;
		editMode?: 'surgical' | 'rewrite';
		surgicalEditSummary?: string;
	}): string {
		const nextNames = objectNamesFromLiveObj(args.nextLiveObj);
		if (!args.isIterativeEdit && args.editMode !== 'surgical') {
			const sceneParts = summarizeObjectNames(nextNames);
			return sceneParts ? `Created scene with ${sceneParts}.` : 'Created scene from prompt.';
		}

		const previousNames = objectNamesFromLiveObj(args.previousLiveObj);
		const previousSet = new Set(previousNames);
		const nextSet = new Set(nextNames);
		const added = nextNames.filter((name) => !previousSet.has(name));
		const removed = previousNames.filter((name) => !nextSet.has(name));
		const changed = nextNames.filter((name) => previousSet.has(name));
		const touched = patchTouchedObjectNames(args.rawLlm, args.previousLiveObj, args.nextLiveObj);
		const verb = editVerbFromPrompt(args.promptText);
		const promptMatchedAdded = namesMatchingPrompt(added, args.promptText);
		const promptMatchedTouched = namesMatchingPrompt(touched, args.promptText);

		if (promptMatchedAdded.length > 0)
			return `${verb} ${summarizeObjectNames(promptMatchedAdded)}.`;
		if (added.length > 0) return `${verb} ${summarizeObjectNames(added)}.`;
		if (removed.length > 0) return `${verb} ${summarizeObjectNames(removed)}.`;
		if (promptMatchedTouched.length > 0)
			return `${verb} ${summarizeObjectNames(promptMatchedTouched)}.`;
		if (touched.length > 0) return `${verb} ${summarizeObjectNames(touched)}.`;
		if (args.surgicalEditSummary?.trim()) return args.surgicalEditSummary.trim();
		if (changed.length > 0) return `${verb} ${summarizeObjectNames(changed)}.`;
		return `${verb} scene.`;
	}

	function applyObjectControls() {
		if (!renderObject) return;
		renderObject.position.set(objectPosX, objectPosY, objectPosZ);
		renderObject.scale.setScalar(objectScale);
		renderObject.rotation.y = (objectRotYDeg * Math.PI) / 180;
	}

	function smoothNormalsBySharedPosition(geometry: THREE.BufferGeometry) {
		const position = geometry.getAttribute('position');
		if (!(position instanceof THREE.BufferAttribute) || position.count < 3) return;
		const normal = new Float32Array(position.count * 3);
		const sums = new Map<string, THREE.Vector3>();
		const keys: string[] = [];
		const keyFor = (index: number) =>
			`${position.getX(index).toFixed(5)},${position.getY(index).toFixed(5)},${position.getZ(index).toFixed(5)}`;
		for (let i = 0; i < position.count; i += 3) {
			const a = new THREE.Vector3(position.getX(i), position.getY(i), position.getZ(i));
			const b = new THREE.Vector3(position.getX(i + 1), position.getY(i + 1), position.getZ(i + 1));
			const c = new THREE.Vector3(position.getX(i + 2), position.getY(i + 2), position.getZ(i + 2));
			const faceNormal = new THREE.Vector3()
				.subVectors(b, a)
				.cross(new THREE.Vector3().subVectors(c, a));
			if (faceNormal.lengthSq() > 1e-12) faceNormal.normalize();
			for (let j = 0; j < 3; j += 1) {
				const key = keyFor(i + j);
				keys[i + j] = key;
				const sum = sums.get(key) ?? new THREE.Vector3();
				sum.add(faceNormal);
				sums.set(key, sum);
			}
		}
		for (let i = 0; i < position.count; i += 1) {
			const n = (sums.get(keys[i]) ?? new THREE.Vector3(0, 1, 0)).clone();
			if (n.lengthSq() > 1e-12) n.normalize();
			normal[i * 3] = n.x;
			normal[i * 3 + 1] = n.y;
			normal[i * 3 + 2] = n.z;
		}
		geometry.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
		geometry.attributes.normal.needsUpdate = true;
	}

	$effect(() => {
		objectScale;
		objectPosX;
		objectPosY;
		objectPosZ;
		objectRotYDeg;
		applyObjectControls();
	});

	function applyObjString(objText: string, sourceTextForMetadata: string = objText) {
		const loader = new OBJLoader();
		const group = loader.parse(objText);
		const upAxis = getLiveObjUpAxis(objText);
		const hasPerObjectMaterials = /^\s*usemtl\s+/im.test(objText);
		const materialTagsByObject = parseObjectMaterialTags(sourceTextForMetadata);
		const materialPresets = parseMaterialPresets(sourceTextForMetadata);
		const textureTags = parseObjectTextureTags(sourceTextForMetadata);
		const hasMetadataMaterialTags = materialTagsByObject.size > 0;
		const hasMetadataTextureTags = hasTextureTags(textureTags);
		const objectDefinitions = new Set(
			[...sourceTextForMetadata.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1])
		);
		const objectNameSet = new Set<string>();
		group.traverse((o: THREE.Object3D) => {
			if (o instanceof THREE.Mesh && o.name) objectNameSet.add(o.name);
		});
		const hasMultipleNamedObjects = Math.max(objectNameSet.size, objectDefinitions.size) > 1;
		preserveObjMaterials =
			hasPerObjectMaterials ||
			hasMultipleNamedObjects ||
			hasMetadataMaterialTags ||
			hasMetadataTextureTags;
		const soleObjectTexture =
			textureTags.byObject.size === 1 ? [...textureTags.byObject.values()][0] : undefined;
		const candidateObjectNamesForMesh = (mesh: THREE.Mesh, material?: THREE.Material): string[] => {
			const names: string[] = [];
			if (mesh.name) names.push(mesh.name);
			const materialName = (material as (THREE.Material & { name?: string }) | undefined)?.name;
			if (materialName) names.push(materialName);
			let parent = mesh.parent;
			while (parent) {
				if (parent.name) names.push(parent.name);
				parent = parent.parent;
			}
			return [...new Set(names.filter(Boolean))];
		};
		const textureTagsForMesh = (mesh: THREE.Mesh, material?: THREE.Material): TextureTags => {
			for (const name of candidateObjectNamesForMesh(mesh, material)) {
				if (textureTags.byObject.has(name)) return textureTags.byObject.get(name)!;
			}
			if (soleObjectTexture && hasAuthoredUvTextureMesh(sourceTextForMetadata))
				return soleObjectTexture;
			return textureTags.global;
		};
		const globalDiffuseTexture = textureForPath(textureTags.global.diffuse);
		const fallbackMat = new THREE.MeshStandardMaterial({
			color: globalDiffuseTexture ? '#ffffff' : objectColor || DEFAULT_CLAY_MATERIAL.color,
			...(globalDiffuseTexture ? { map: globalDiffuseTexture } : {}),
			metalness: DEFAULT_CLAY_MATERIAL.metalness,
			roughness: DEFAULT_CLAY_MATERIAL.roughness,
			side: THREE.DoubleSide,
			flatShading: false,
			wireframe
		});
		group.traverse((o: THREE.Object3D) => {
			if (!(o instanceof THREE.Mesh)) return;
			if (
				!hasPerObjectMaterials &&
				!hasMultipleNamedObjects &&
				!hasMetadataMaterialTags &&
				!hasMetadataTextureTags
			) {
				o.material = fallbackMat;
				if (o.geometry) smoothNormalsBySharedPosition(o.geometry);
				return;
			}
			const materialToStandard = (material: THREE.Material): THREE.MeshStandardMaterial => {
				const base = material as THREE.MeshPhongMaterial & { name?: string };
				const names = candidateObjectNamesForMesh(o, material);
				const taggedMaterial =
					names.map((name) => materialTagsByObject.get(name)).find(Boolean) ?? null;
				const taggedPreset = taggedMaterial ? materialPresets.get(taggedMaterial) : undefined;
				const useMtlPreset =
					hasPerObjectMaterials && base.name ? materialPresets.get(base.name) : undefined;
				const preset = taggedPreset ?? useMtlPreset;
				const colorName = taggedMaterial ?? (hasPerObjectMaterials ? base.name : o.name);
				const colorValue = preset?.color;
				const color = colorValue
					? new THREE.Color(colorValue)
					: colorName
						? materialColorFromName(colorName)
						: new THREE.Color(objectColor);
				const diffuseTexture = textureForPath(textureTagsForMesh(o, material).diffuse);
				return new THREE.MeshStandardMaterial({
					color: diffuseTexture ? new THREE.Color('#ffffff') : color,
					...(diffuseTexture ? { map: diffuseTexture } : {}),
					metalness: preset?.metalness ?? DEFAULT_CLAY_MATERIAL.metalness,
					roughness: preset?.roughness ?? DEFAULT_CLAY_MATERIAL.roughness,
					side: THREE.DoubleSide,
					flatShading: preset?.shadeSmooth === false,
					wireframe
				});
			};
			if (Array.isArray(o.material)) {
				o.material = o.material.map((material) => materialToStandard(material));
			} else {
				o.material = materialToStandard(o.material);
			}
			const materials = Array.isArray(o.material) ? o.material : [o.material];
			const wantsSmoothNormals = materials.some(
				(material) => !(material as THREE.MeshStandardMaterial).flatShading
			);
			if (wantsSmoothNormals && o.geometry) smoothNormalsBySharedPosition(o.geometry);
			else if (o.geometry) o.geometry.computeVertexNormals();
		});
		if (upAxis === 'z') group.rotation.x = -Math.PI / 2;
		else if (upAxis === 'x') group.rotation.z = Math.PI / 2;
		renderObject = group;
		applyObjectControls();
	}

	function countObjFaceLines(objText: string): number {
		return objText.split('\n').filter((line) => /^\s*f\s+/.test(line)).length;
	}

	function countObjVertexLines(objText: string): number {
		return objText.split('\n').filter((line) => /^\s*v\s+/.test(line)).length;
	}

	function hasObjMeshGeometry(objText: string): boolean {
		return countObjVertexLines(objText) > 0 && countObjFaceLines(objText) > 0;
	}

	function hasExecutableRawPostOps(sourceText: string): boolean {
		const lines = sourceText.split(/\r?\n/);
		let inPostBlock = false;
		for (const rawLine of lines) {
			const trimmed = rawLine.trim();
			if (!trimmed.startsWith('#@')) continue;
			const body = trimmed.slice(2).trim();
			if (/^post\s+\S+/i.test(body)) return true;
			if (/^post:\s*$/i.test(body)) {
				inPostBlock = true;
				continue;
			}
			if (inPostBlock && body.startsWith('-')) return true;
			if (inPostBlock && /:\s*$/.test(body) && !body.startsWith('-')) inPostBlock = false;
		}
		return false;
	}

	function tokenParam(sourceText: string, key: string): string | null {
		const match = sourceText.match(new RegExp(`(?:^|[\\s,])${key}=([^\\s,]+)`));
		return match?.[1] ?? null;
	}

	function metadataValue(raw: string, key: string): string | undefined {
		return raw
			.match(new RegExp(`(?:^|\\s)${key}=("[^"]+"|'[^']+'|\\S+)`))?.[1]
			?.replace(/^['"]|['"]$/g, '');
	}

	function metadataImageUrl(path: string): string {
		const trimmed = path.trim();
		if (/^(data:|blob:|https?:\/\/)/i.test(trimmed)) return trimmed;
		if (/^\/api\//i.test(trimmed)) return trimmed;
		const projectFileMatch = trimmed.match(/(?:^|[/\\])(project_live_obj_files[/\\].+)$/);
		if (projectFileMatch) {
			return `/api/project-file?path=${encodeURIComponent(projectFileMatch[1].replace(/\\/g, '/'))}`;
		}
		return `/api/project-file?path=${encodeURIComponent(trimmed)}`;
	}

	function metadataImageMessages(sourceText: string): ChatMsg[] {
		const messages: ChatMsg[] = [];
		const seen = new Set<string>();
		for (const line of sourceText.split(/\r?\n/)) {
			const match = line.match(/^\s*#@(texture|debug_image):\s*(.+)$/);
			if (!match) continue;
			const type = match[1];
			const raw = match[2];
			const path = metadataValue(raw, 'path') ?? metadataValue(raw, 'src');
			if (!path || !/\.(png|jpe?g|webp|svg)(?:$|[?#])/i.test(path)) continue;
			const kind = (metadataValue(raw, 'kind') ?? type).replace(/[_-]+/g, ' ');
			const key = `${type}:${kind}:${path}`;
			if (seen.has(key)) continue;
			seen.add(key);
			messages.push({
				role: 'assistant',
				content: `${kind} map`,
				imageDataUrl: metadataImageUrl(path),
				meta: type === 'texture' ? 'texture artifact' : 'uv debug artifact',
				excludeFromHistory: true
			});
		}
		return messages;
	}

	function appendMetadataImageMessages(sourceText: string) {
		const artifactMessages = metadataImageMessages(sourceText);
		if (artifactMessages.length > 0) msgs = [...msgs, ...artifactMessages];
	}

	function applyDreamDisplacementControls(sourceText: string): string {
		if (!/#@workflow_step:\s*uv_dream_enhance\b/i.test(sourceText)) return sourceText;
		const amount = Number(tokenParam(sourceText, 'dream_displacement_amount') ?? '1');
		const displacementAmount = Number.isFinite(amount) ? amount : 1;
		const shadeValue = (tokenParam(sourceText, 'dream_shade') ?? 'smooth').toLowerCase();
		const shade = shadeValue === 'flat' ? 'flat' : 'smooth';
		const parseTriple = (line: string): [number, number, number] | null => {
			const parts = line.trim().split(/\s+/).slice(1, 4).map(Number);
			return parts.length === 3 && parts.every(Number.isFinite)
				? [parts[0], parts[1], parts[2]]
				: null;
		};

		const rewriteBlock = (blockLines: string[]): string[] => {
			if (!blockLines.some((line) => /^\s*#@workflow_step:\s*uv_dream_enhance\b/i.test(line))) {
				return blockLines;
			}
			const bases: Array<[number, number, number]> = [];
			const deltas: Array<[number, number, number]> = [];
			for (const line of blockLines) {
				if (/^\s*#@dream_base_v\s+/.test(line)) {
					const parsed = parseTriple(line.replace(/^\s*#@dream_base_v/, 'dream_base_v'));
					if (parsed) bases.push(parsed);
				}
				if (/^\s*#@dream_delta_v\s+/.test(line)) {
					const parsed = parseTriple(line.replace(/^\s*#@dream_delta_v/, 'dream_delta_v'));
					if (parsed) deltas.push(parsed);
				}
			}
			if (bases.length === 0 || bases.length !== deltas.length) return blockLines;
			let vertexIndex = 0;
			return blockLines.map((line) => {
				if (/^\s*#@shade:\s*/.test(line)) return `#@shade: ${shade}`;
				if (!/^\s*v\s+/.test(line)) return line;
				if (vertexIndex >= bases.length) return line;
				const base = bases[vertexIndex];
				const delta = deltas[vertexIndex];
				vertexIndex += 1;
				return `v ${(base[0] + delta[0] * displacementAmount).toFixed(6)} ${(base[1] + delta[1] * displacementAmount).toFixed(6)} ${(base[2] + delta[2] * displacementAmount).toFixed(6)}`;
			});
		};

		const out: string[] = [];
		let blockLines: string[] | null = null;
		for (const line of sourceText.split(/\r?\n/)) {
			if (/^\s*o\s+/.test(line)) {
				if (blockLines) out.push(...rewriteBlock(blockLines));
				blockLines = [line];
				continue;
			}
			if (blockLines) {
				blockLines.push(line);
				continue;
			}
			if (/^\s*#@material_preset:\s+/.test(line)) {
				if (/\bshade_smooth=/.test(line)) {
					out.push(line.replace(/\bshade_smooth=[^\s]+/, `shade_smooth=${shade === 'smooth'}`));
					continue;
				}
				out.push(`${line} shade_smooth=${shade === 'smooth'}`);
				continue;
			}
			out.push(line);
		}
		if (blockLines) out.push(...rewriteBlock(blockLines));
		return out.join('\n');
	}

	function objMeshLine(line: string): boolean {
		return /^\s*(v|vn|vt|vp|f|fo|l)\s+/.test(line);
	}

	function objectBlocksByName(sourceText: string): Map<string, string> {
		const blocks = new Map<string, string>();
		for (const block of sourceText.split(/(?=^\s*o\s+)/gm)) {
			const name = block.match(/^\s*o\s+([^\s#]+)/m)?.[1];
			if (name) blocks.set(name, block);
		}
		return blocks;
	}

	function mergeMetadataOnlyEdit(fullSource: string, editedSource: string): string {
		if (hasObjMeshGeometry(editedSource) || !hasObjMeshGeometry(fullSource)) return editedSource;
		const editedBlocks = objectBlocksByName(editedSource);
		if (editedBlocks.size === 0) return editedSource;
		const fullNames = objectNamesFromLiveObj(fullSource);
		const editedNames = objectNamesFromLiveObj(editedSource);
		if (!fullNames.every((name) => editedNames.includes(name))) return editedSource;

		const editedHeader = editedSource.split(/(?=^\s*o\s+)/gm)[0] ?? '';
		const mergedBlocks = fullSource
			.split(/(?=^\s*o\s+)/gm)
			.filter((block) => /^\s*o\s+/.test(block))
			.map((fullBlock) => {
				const name = fullBlock.match(/^\s*o\s+([^\s#]+)/m)?.[1];
				const editedBlock = name ? editedBlocks.get(name) : undefined;
				if (!editedBlock) return fullBlock;
				const fullLines = fullBlock.split(/\r?\n/);
				const editedLines = editedBlock.split(/\r?\n/);
				const fullMeshAt = fullLines.findIndex(objMeshLine);
				if (fullMeshAt < 0) return editedBlock;
				const editedPrefix = editedLines.filter((line) => !objMeshLine(line));
				const editedPrefixText = new Set(editedPrefix.map((line) => line.trim()));
				const hiddenDreamCache = fullLines
					.slice(0, fullMeshAt)
					.filter(
						(line) =>
							/^#@dream_(?:base|delta)_v\b/i.test(line.trim()) && !editedPrefixText.has(line.trim())
					);
				const meshSuffix = fullLines.slice(fullMeshAt);
				return [...editedPrefix, ...hiddenDreamCache, ...meshSuffix].join('\n');
			});
		return `${editedHeader.trimEnd()}\n${mergedBlocks.join('\n').trimEnd()}\n`;
	}

	function objElementRefs(line: string): number[] {
		if (!/^\s*[fl]\s+/.test(line)) return [];
		return line
			.trim()
			.split(/\s+/)
			.slice(1)
			.map((token) => Number(token.split('/')[0]))
			.filter((n) => Number.isInteger(n) && n > 0);
	}

	function remapPreviewPartLines(partLines: string[], vertexOffset: number): string[] | null {
		const localVertexCount = partLines.filter((line) => /^\s*v\s+/.test(line)).length;
		const refs = partLines.flatMap(objElementRefs);
		if (refs.length === 0) return partLines;
		const maxRef = Math.max(...refs);
		const minRef = Math.min(...refs);
		const localIndexOffset =
			maxRef > localVertexCount &&
			minRef > 1 &&
			refs.every((ref) => ref - (minRef - 1) >= 1 && ref - (minRef - 1) <= localVertexCount)
				? minRef - 1
				: 0;
		if (maxRef - localIndexOffset > localVertexCount) return null;
		return partLines.map((line) => {
			if (!/^\s*[fl]\s+/.test(line)) return line;
			const [head, ...tokens] = line.trim().split(/\s+/);
			return [
				head,
				...tokens.map((token) => {
					const pieces = token.split('/');
					const n = Number(pieces[0]);
					if (!Number.isInteger(n) || n <= 0) return token;
					pieces[0] = String(n - localIndexOffset + vertexOffset);
					return pieces.join('/');
				})
			].join(' ');
		});
	}

	function tryApplyObjString(objText: string, sourceTextForMetadata: string = objText): boolean {
		try {
			applyObjString(objText, sourceTextForMetadata);
			return true;
		} catch {
			return false;
		}
	}

	async function regenerateFromMetadata(updatedLiveObj: string) {
		const text = mergeMetadataOnlyEdit(liveObjText, String(updatedLiveObj ?? ''));
		if (!text.trim()) return;
		statusLine = null;
		const hasLiveSources = hasProceduralLiveSources(text);
		const isRawCachedMesh =
			currentSceneMode === 'raw_obj' &&
			!hasLiveSources &&
			hasObjMeshGeometry(text) &&
			!hasExecutableRawPostOps(text);
		const preparedRawPostText = applyDreamDisplacementControls(normalizeRawPostHeader(text));
		if (isRawCachedMesh) {
			const resolved = preparedRawPostText;
			liveObjText = resolved;
			executedObjText = resolved;
			sourceTab = 'executed';
			sceneEpoch += 1;
			applyObjString(resolved, resolved);
			return;
		}
		const useRawPostExecutor = currentSceneMode === 'raw_obj' && !hasLiveSources;
		const sceneWithKernel = useRawPostExecutor
			? preparedRawPostText
			: applyKernelDefaultHeader(text);
		try {
			const res = await fetch(
				useRawPostExecutor ? '/api/raw-obj/execute' : '/api/live-obj/execute',
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(
						useRawPostExecutor ? { rawObj: sceneWithKernel } : { liveObj: sceneWithKernel }
					)
				}
			);
			const payload = await res.json();
			if (!res.ok)
				throw new Error(
					payload.detail || payload.message || res.statusText || 'Metadata regeneration failed'
				);
			liveObjText = useRawPostExecutor
				? sceneWithKernel
				: String(payload.liveObj ?? payload.rawObj ?? sceneWithKernel);
			currentSceneMode = hasProceduralLiveSources(liveObjText) ? 'live_obj' : currentSceneMode;
			executedObjText = displayObjForSource(
				liveObjText,
				typeof payload.executedObj === 'string'
					? payload.executedObj
					: String(payload.executedObj ?? '')
			);
			sourceTab = 'executed';
			sceneEpoch += 1;
			applyObjString(executedObjText || liveObjText, liveObjText);
		} catch (e) {
			const m = e instanceof Error ? e.message : String(e);
			statusLine = `Metadata regenerate failed: ${m}`;
			liveObjText = sceneWithKernel;
		}
	}

	function applyKernelDefaultHeader(sceneText: string): string {
		const raw = sceneText.trim();
		if (!raw) return sceneText;
		if (kernelDefault !== 'cadquery') return sceneText;
		const lines = raw.split('\n');
		const idx = lines.findIndex((l) => l.trim().startsWith('#@kernel_default:'));
		if (idx >= 0) {
			lines[idx] = '#@kernel_default: cadquery';
			return `${lines.join('\n')}\n`;
		}
		const headerIdx = lines.findIndex((l) => l.trim().startsWith('#@live_obj_version:'));
		if (headerIdx >= 0) {
			lines.splice(headerIdx + 1, 0, '#@kernel_default: cadquery');
			return `${lines.join('\n')}\n`;
		}
		return `#@kernel_default: cadquery\n${raw}\n`;
	}

	async function launchObjExample(liveObj: string) {
		if (!liveObj.trim()) return;
		busy = true;
		try {
			currentSceneMode = hasProceduralLiveSources(liveObj) ? 'live_obj' : 'raw_obj';
			await regenerateFromMetadata(liveObj);
		} finally {
			busy = false;
		}
	}

	const PROVIDER_SETTINGS_KEY = 'live-obj-provider-settings-v1';
	let providerSettings = $state({
		provider: 'openai',
		apiKey: '',
		apiUrl: 'https://api.openai.com/v1/chat/completions',
		imageUrl: 'https://api.openai.com/v1/images/edits',
		videoUrl: '',
		textModel: 'gpt-5.5',
		imageModel: 'gpt-image-1.5',
		videoModel: '',
		rememberMe: false
	});
	let initialSceneBuilt = $state(false);

	onMount(() => {
		if (!browser) return;
		try {
			const raw = localStorage.getItem(PROVIDER_SETTINGS_KEY);
			if (!raw) return;
			const parsed = JSON.parse(raw) as typeof providerSettings;
			providerSettings = { ...providerSettings, ...parsed, rememberMe: true };
		} catch {}
	});

	// Build initial scene from Live OBJ code when canvas is ready
	$effect(() => {
		if (canvasRef && liveObjText && !initialSceneBuilt) {
			initialSceneBuilt = true;
			regenerateFromMetadata(liveObjText);
		}
	});

	$effect(() => {
		if (selectedTargetObjectId && !targetObjectOptions.includes(selectedTargetObjectId)) {
			selectedTargetObjectId = '';
		}
	});

	$effect(() => {
		if (!browser) return;
		if (providerSettings.rememberMe) {
			localStorage.setItem(PROVIDER_SETTINGS_KEY, JSON.stringify(providerSettings));
		} else {
			localStorage.removeItem(PROVIDER_SETTINGS_KEY);
		}
	});

	function buildChatHistory(priorMsgs: ChatMsg[], includeImages = true) {
		return priorMsgs
			.filter((m) => !m.transient && !m.excludeFromHistory)
			.map((m) => ({
				role: m.role,
				content:
					m.role === 'assistant'
						? modelHistoryContent(m.historyContent ?? m.content)
						: (m.historyContent ?? m.content),
				...(includeImages && m.imageDataUrl ? { imageUrl: m.imageDataUrl } : {})
			}))
			.filter((m) => m.content.trim() || 'imageUrl' in m);
	}

	function appendProgressMessage(content: string, meta?: string) {
		msgs = [...msgs, { role: 'assistant', content, historyContent: '', ...(meta ? { meta } : {}) }];
	}

	function showThinkingMessage(content: string) {
		msgs = [
			...msgs.filter((message) => !message.transient),
			{ role: 'assistant', content, historyContent: '', transient: true }
		];
	}

	function clearThinkingMessage() {
		msgs = msgs.filter((message) => !message.transient);
	}

	function partLabel(part: IterativePartSpec, index: number): string {
		return readableObjectName(part.role || part.id || `part ${index + 1}`);
	}

	function planPartsMessage(plan: IterativeScenePlan): string {
		const lines = plan.parts.map((part, index) => {
			const method = part.method?.trim() ? ` [${part.method.trim()}]` : '';
			const post = plannedUvPostProcess(part) ? ' + UV dream' : '';
			const prompt = part.prompt?.trim() ? ` — ${part.prompt.trim()}` : '';
			return `${index + 1}. ${partLabel(part, index)}${method}${post}${prompt}`;
		});
		return `Parts:\n${lines.join('\n')}`;
	}

	function clampVisualNumber(value: unknown, min: number, max: number): number | undefined {
		const numberValue = typeof value === 'number' ? value : Number(value);
		if (!Number.isFinite(numberValue)) return undefined;
		return Math.min(max, Math.max(min, numberValue));
	}

	function normalizePlanAspectRatio(value: unknown): CanvasAspectRatio | undefined {
		if (typeof value !== 'string') return undefined;
		const trimmed = value.trim() as CanvasAspectRatio;
		return trimmed === 'fill' || trimmed in CANVAS_ASPECT_RATIOS ? trimmed : undefined;
	}

	function cameraDirectionFromView(value: unknown): [number, number, number] | undefined {
		if (typeof value !== 'string') return undefined;
		switch (value.trim().toLowerCase()) {
			case 'front_right_high':
				return [1, 0.65, -1];
			case 'low_front':
				return [-1, 0.22, -1];
			case 'side':
				return [1, 0.35, 0];
			case 'top':
				return [0.05, 1, -0.05];
			case 'isometric':
				return [-1, 1, -1];
			case 'front_left_high':
			default:
				return [-1, 0.65, -1];
		}
	}

	function normalizedFocusIds(value: unknown): string[] {
		if (!Array.isArray(value)) return [];
		return [
			...new Set(
				value
					.map((item) => (typeof item === 'string' ? item.trim() : ''))
					.filter((item) => /^[A-Za-z_][\w.-]*$/.test(item))
			)
		];
	}

	function applyPlanVisualSettings(plan: IterativeScenePlan) {
		const visual = plan.visual;
		if (!visual || typeof visual !== 'object') return;
		if (
			typeof visual.backgroundColor === 'string' &&
			/^#[0-9a-fA-F]{6}$/.test(visual.backgroundColor.trim())
		) {
			backgroundColor = visual.backgroundColor.trim();
		}
		const nextAspectRatio = normalizePlanAspectRatio(visual.canvasAspectRatio);
		if (nextAspectRatio) canvasAspectRatio = nextAspectRatio;
		ambientLightIntensity =
			clampVisualNumber(visual.ambientLightIntensity, 0, 4) ?? ambientLightIntensity;
		directionalLightIntensity =
			clampVisualNumber(visual.directionalLightIntensity, 0, 6) ?? directionalLightIntensity;
		cameraFov = clampVisualNumber(visual.cameraFov, 20, 85) ?? cameraFov;
		toneMappingExposure =
			clampVisualNumber(visual.toneMappingExposure, 0.25, 3) ?? toneMappingExposure;
		planCameraDirection = cameraDirectionFromView(visual.cameraView) ?? planCameraDirection;
		planCameraFocus = normalizedFocusIds(visual.cameraFocus);
	}

	function cameraFocusForPart(part: IterativePartSpec): string[] {
		const explicitFocus = normalizedFocusIds(part.cameraFocus);
		if (explicitFocus.length > 0) return explicitFocus;
		return [
			...new Set([part.id, ...(part.dependencies ?? []), ...planCameraFocus].filter(Boolean))
		];
	}

	async function appendBuiltPartScreenshot(
		label: string,
		partNumber: number,
		partCount: number,
		frameObjectIds: string[] = [],
		xrayFocusObjectIds: string[] = [],
		xraySupportObjectIds: string[] = []
	): Promise<string> {
		await waitForSceneCaptureFrame();
		const screenshot = captureSceneScreenshot({
			frameObjectIds,
			xrayFocusObjectIds,
			xraySupportObjectIds
		});
		if (!screenshot) return '';
		const processScreenshot = captureSceneScreenshot({ frameObjectIds }) || screenshot;
		projectProcessImages = [
			...projectProcessImages,
			{
				label: `Build ${partNumber}/${partCount}: ${label}`,
				meta: 'build step screenshot',
				imageDataUrl: processScreenshot
			}
		].slice(-MAX_PROJECT_PROCESS_IMAGES);
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: `Built ${partNumber}/${partCount}: ${label}.`,
				meta: 'x-ray scene screenshot',
				imageDataUrl: screenshot,
				historyContent: '',
				excludeFromHistory: true
			}
		];
		return screenshot;
	}

	async function runPartFeedbackPass(args: {
		text: string;
		initialImageUrls: string[];
		useProcedural: boolean;
		part: IterativePartSpec;
		label: string;
		partNumber: number;
		partCount: number;
		screenshot: string;
		signal?: AbortSignal;
	}) {
		if (!args.screenshot) return;
		throwIfAborted(args.signal);
		const feedbackStartedAt = performance.now();
		const priorBeforeFeedback = [...msgs];
		msgs = [
			...msgs,
			{
				role: 'user',
				content: `Part check ${args.partNumber}/${args.partCount}: ${args.label}.`,
				imageDataUrl: args.screenshot,
				excludeFromHistory: true
			}
		];
		statusLine = `Part check ${args.partNumber}/${args.partCount}: reviewing ${args.label}.`;
		feedbackLoopActive = true;
		try {
			await requestSceneUpdateTurn({
				text: partFeedbackPrompt({
					originalText: args.text,
					label: args.label,
					part: args.part,
					partNumber: args.partNumber,
					partCount: args.partCount,
					hasReferenceImage: args.initialImageUrls.length > 0
				}),
				useProcedural: args.useProcedural,
				targetObjectId: args.part.id,
				imageDataUrls: [...args.initialImageUrls, args.screenshot],
				priorMsgs: priorBeforeFeedback,
				includeHistoryImages: false,
				forceCurrentScene: true,
				signal: args.signal
			});
			appendProgressMessage(
				`Part check ${args.partNumber}/${args.partCount} finished.`,
				`time ${formatDuration(performance.now() - feedbackStartedAt)}`
			);
		} finally {
			feedbackLoopActive = false;
		}
	}

	function emptyIterativeLiveObj(useProcedural: boolean): string {
		const empty = `#@live_obj_version: 0.1
#@up: y
`;
		return useProcedural ? applyKernelDefaultHeader(empty) : normalizeRawPostHeader(empty);
	}

	function planMaterialPresetLines(plan: IterativeScenePlan): string[] {
		return (plan.materials ?? [])
			.filter((material) => material?.id?.trim())
			.map((material) => {
				const id = material.id.trim().replace(/[^a-zA-Z0-9_\-.]/g, '_');
				const color = material.color?.trim().match(/^#[0-9a-fA-F]{6}$/)
					? material.color.trim()
					: '#c8c8c8';
				const roughness =
					typeof material.roughness === 'number' && Number.isFinite(material.roughness)
						? Math.max(0, Math.min(1, material.roughness))
						: 0.55;
				const metalness =
					typeof material.metalness === 'number' && Number.isFinite(material.metalness)
						? Math.max(0, Math.min(1, material.metalness))
						: 0;
				return `#@material_preset: ${id} color=${color} roughness=${roughness} metalness=${metalness}`;
			});
	}

	function applyPlanMaterialsToHeader(liveObj: string, plan: IterativeScenePlan): string {
		const presetLines = planMaterialPresetLines(plan);
		if (presetLines.length === 0) return liveObj;
		const existing = new Set(
			[...liveObj.matchAll(/^\s*#@material_preset:\s+([^\s]+)/gm)].map((match) => match[1])
		);
		const additions = presetLines.filter((line) => {
			const id = line.match(/^\s*#@material_preset:\s+([^\s]+)/)?.[1];
			return id && !existing.has(id);
		});
		if (additions.length === 0) return liveObj;
		const lines = liveObj.trimEnd().split('\n');
		const firstObject = lines.findIndex((line) => /^\s*o\s+/.test(line));
		const insertAt = firstObject >= 0 ? firstObject : lines.length;
		lines.splice(insertAt, 0, ...additions);
		return `${lines.join('\n')}\n`;
	}

	function mergeTokenUsage(
		a: TokenUsageSummary | undefined,
		b: TokenUsageSummary | undefined
	): TokenUsageSummary | undefined {
		if (!a && !b) return undefined;
		return {
			promptTokens: (a?.promptTokens ?? 0) + (b?.promptTokens ?? 0) || undefined,
			completionTokens: (a?.completionTokens ?? 0) + (b?.completionTokens ?? 0) || undefined,
			totalTokens: (a?.totalTokens ?? 0) + (b?.totalTokens ?? 0) || undefined,
			reasoningTokens: (a?.reasoningTokens ?? 0) + (b?.reasoningTokens ?? 0) || undefined,
			cachedTokens: (a?.cachedTokens ?? 0) + (b?.cachedTokens ?? 0) || undefined
		};
	}

	function shortDelay(ms: number) {
		return new Promise<void>((resolve) => setTimeout(resolve, ms));
	}

	function isAbortError(errorValue: unknown): boolean {
		return (
			(errorValue instanceof DOMException && errorValue.name === 'AbortError') ||
			(errorValue instanceof Error && errorValue.name === 'AbortError')
		);
	}

	function throwIfAborted(signal?: AbortSignal) {
		if (!signal?.aborted) return;
		throw new DOMException('Generation stopped.', 'AbortError');
	}

	function stopGeneration() {
		if (!activeGenerationAbortController) return;
		activeGenerationAbortController.abort();
		statusLine = 'Stopping generation.';
		clearThinkingMessage();
	}

	function formatDuration(ms: number): string {
		const seconds = Math.max(0, Math.round(ms / 1000));
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		const rest = seconds % 60;
		return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
	}

	function looksLikeTargetedEdit(promptText: string): boolean {
		return /\b(add|remove|delete|erase|drop|hide|make|change|adjust|modify|edit|move|rotate|scale|resize|recolor|color|material|fix|repair|refine|improve|replace)\b/i.test(
			promptText
		);
	}

	function looksLikeAdditiveGeometryRequest(promptText: string): boolean {
		const lower = promptText.toLowerCase();
		if (!/\b(add|insert|include|attach|place|put)\b/.test(lower)) return false;
		return !/\b(color|recolor|material|shader|texture|smooth|scale|resize|move|rotate|delete|remove|replace|rebuild|rename|convert)\b/.test(
			lower
		);
	}

	function shouldUseIterativeGeneration(args: {
		text: string;
		useProcedural: boolean;
		isIterativeEdit: boolean;
		hasImages: boolean;
	}): boolean {
		if (!args.isIterativeEdit) return true;
		if (looksLikeAdditiveGeometryRequest(args.text)) return true;
		if (looksLikeTargetedEdit(args.text)) return false;
		return Boolean(args.text.trim() || args.hasImages);
	}

	const DREAM_VIEWS = ['top', 'bottom', 'left', 'right', 'front', 'back'] as const;
	const DREAM_VIEW_DIRECTIONS: Record<(typeof DREAM_VIEWS)[number], [number, number, number]> = {
		top: [0, 1, 0],
		bottom: [0, -1, 0],
		left: [-1, 0, 0],
		right: [1, 0, 0],
		front: [0, 0, 1],
		back: [0, 0, -1]
	};

	function looksLikeDreamRebuildRequest(promptText: string): boolean {
		return /\b(dream|tsdf|depth|depth\s*map|reconstruct|rebuild)\b/i.test(promptText);
	}

	function looksLikeUvDreamRequest(promptText: string): boolean {
		return /\b(uv|unwrap|atlas|displace|displacement|height\s*map|texture\s*map)\b/i.test(
			promptText
		);
	}

	function uvDreamModeFromPrompt(promptText: string): 'displace' | 'map-remesh' {
		return /\b(map[-\s]?remesh|clean\s+topology|exact\s+map|quad\s+grid)\b/i.test(promptText)
			? 'map-remesh'
			: 'displace';
	}

	function targetObjectIdFromDreamPrompt(promptText: string): string {
		const explicit =
			promptText.match(/\b(?:object|part|target)\s+([A-Za-z_][\w.-]*)\b/i)?.[1] ??
			promptText.match(/\b([A-Za-z_][\w.-]*)\s+(?:as|with)\s+(?:folded|dream|tsdf|depth)/i)?.[1] ??
			'';
		if (explicit && objectNamesFromLiveObj(liveObjText).includes(explicit)) return explicit;
		if (selectedTargetObjectId) return selectedTargetObjectId;
		const names = objectNamesFromLiveObj(liveObjText);
		if (names.length === 1) return names[0];
		return names.includes('folded_roof') ? 'folded_roof' : '';
	}

	function clamp01(value: number): number {
		return Math.max(0, Math.min(1, value));
	}

	function syntheticDreamMaskRows(width: number, height: number, view: string): string[] {
		void view;
		const rows: string[] = [];
		for (let y = 0; y < height; y += 1) {
			rows.push('1'.repeat(width));
		}
		return rows;
	}

	function syntheticDreamDepthRows(width: number, height: number, view: string): string[] {
		const rows: string[] = [];
		for (let y = 0; y < height; y += 1) {
			let row = '';
			for (let x = 0; x < width; x += 1) {
				const u = width <= 1 ? 0 : x / (width - 1);
				const v = height <= 1 ? 0 : y / (height - 1);
				let value = 1;
				if (view === 'top') {
					value =
						0.58 + 0.28 * Math.sin(u * Math.PI * 6) + 0.13 * Math.sin((v + u * 0.35) * Math.PI * 4);
				}
				row += Math.round(clamp01(value) * 255)
					.toString(16)
					.padStart(2, '0');
			}
			rows.push(row);
		}
		return rows;
	}

	function syntheticDreamMaps(size = 72): {
		viewMasks: Record<string, DreamMap>;
		viewDepthMaps: Record<string, DreamMap>;
	} {
		const viewMasks: Record<string, DreamMap> = {};
		const viewDepthMaps: Record<string, DreamMap> = {};
		for (const view of DREAM_VIEWS) {
			viewMasks[view] = {
				width: size,
				height: size,
				rows: syntheticDreamMaskRows(size, size, view)
			};
			viewDepthMaps[view] = {
				width: size,
				height: size,
				rows: syntheticDreamDepthRows(size, size, view)
			};
		}
		return { viewMasks, viewDepthMaps };
	}

	function dreamMapSheetDataUrl(
		viewMasks: Record<string, DreamMap>,
		viewDepthMaps: Record<string, DreamMap>
	) {
		const tile = 92;
		const gap = 10;
		const labelH = 18;
		const width = 2 * tile + 3 * gap;
		const height = DREAM_VIEWS.length * (tile + labelH + gap) + gap;
		const rects: string[] = [];
		const cellRects = (map: DreamMap, ox: number, oy: number, isDepth: boolean) => {
			const sx = tile / map.width;
			const sy = tile / map.height;
			for (let y = 0; y < map.height; y += 1) {
				for (let x = 0; x < map.width; x += 1) {
					const row = map.rows[y] ?? '';
					const usesByteDepth = isDepth && row.length >= map.width * 2;
					const ch = usesByteDepth ? row.slice(x * 2, x * 2 + 2) : (row[x] ?? '0');
					const level = isDepth
						? usesByteDepth
							? Math.round(((parseInt(ch, 16) || 0) / 255) * 15)
							: parseInt(ch, 16) || 0
						: ch === '1'
							? 15
							: 0;
					if (level <= 0) continue;
					const g = level.toString(16).repeat(2);
					rects.push(
						`<rect x="${(ox + x * sx).toFixed(2)}" y="${(oy + y * sy).toFixed(2)}" width="${sx.toFixed(2)}" height="${sy.toFixed(2)}" fill="#${g}${g}${g}"/>`
					);
				}
			}
		};
		DREAM_VIEWS.forEach((view, index) => {
			const y = gap + index * (tile + labelH + gap);
			rects.push(
				`<text x="${gap}" y="${y + 12}" fill="#dbe5ef" font-size="11" font-family="Arial">${view} mask</text>`,
				`<text x="${2 * gap + tile}" y="${y + 12}" fill="#dbe5ef" font-size="11" font-family="Arial">${view} depth</text>`,
				`<rect x="${gap}" y="${y + labelH}" width="${tile}" height="${tile}" fill="#020617" stroke="#334155"/>`,
				`<rect x="${2 * gap + tile}" y="${y + labelH}" width="${tile}" height="${tile}" fill="#020617" stroke="#334155"/>`
			);
			cellRects(viewMasks[view], gap, y + labelH, false);
			cellRects(viewDepthMaps[view], 2 * gap + tile, y + labelH, true);
		});
		const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#0f172a"/>${rects.join('')}</svg>`;
		return `data:image/svg+xml;base64,${btoa(svg)}`;
	}

	function loadImageDataUrl(imageDataUrl: string): Promise<HTMLImageElement> {
		return new Promise((resolve, reject) => {
			const img = new Image();
			img.onload = () => resolve(img);
			img.onerror = () => reject(new Error('Unable to load generated dream map image'));
			img.src = imageDataUrl;
		});
	}

	async function captureDreamReferenceSheet(targetObjectId: string): Promise<string> {
		const shots: HTMLImageElement[] = [];
		for (const view of DREAM_VIEWS) {
			canvasRef?.frameScene?.(1.04, DREAM_VIEW_DIRECTIONS[view], [targetObjectId]);
			await waitForSceneCaptureFrame();
			const imageDataUrl =
				canvasRef?.captureScreenshot({
					maxWidth: 512,
					format: 'image/png',
					autoFrame: true,
					framePadding: 1.04,
					viewDirection: DREAM_VIEW_DIRECTIONS[view],
					focusObjectNames: [targetObjectId]
				}) ?? '';
			if (!imageDataUrl) throw new Error(`Unable to capture ${view} reference view`);
			shots.push(await loadImageDataUrl(imageDataUrl));
		}

		const tile = 512;
		const canvas = document.createElement('canvas');
		canvas.width = tile;
		canvas.height = tile * DREAM_VIEWS.length;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('Unable to compose dream reference sheet');
		ctx.fillStyle = '#ffffff';
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		for (const [index, img] of shots.entries()) {
			const scale = Math.min(tile / img.width, tile / img.height);
			const width = img.width * scale;
			const height = img.height * scale;
			const x = (tile - width) * 0.5;
			const y = index * tile + (tile - height) * 0.5;
			ctx.drawImage(img, x, y, width, height);
		}
		return canvas.toDataURL('image/png');
	}

	function grayscaleAt(data: Uint8ClampedArray, index: number): number {
		return Math.round((data[index] + data[index + 1] + data[index + 2]) / 3);
	}

	async function parseDreamMapSheetImage(
		imageDataUrl: string,
		size = 72
	): Promise<{ viewMasks: Record<string, DreamMap>; viewDepthMaps: Record<string, DreamMap> }> {
		const img = await loadImageDataUrl(imageDataUrl);
		const canvas = document.createElement('canvas');
		canvas.width = img.naturalWidth || img.width;
		canvas.height = img.naturalHeight || img.height;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('Unable to read generated dream map image');
		ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
		const viewMasks: Record<string, DreamMap> = {};
		const viewDepthMaps: Record<string, DreamMap> = {};
		const cellW = canvas.width / 2;
		const cellH = canvas.height / DREAM_VIEWS.length;

		for (const [rowIndex, view] of DREAM_VIEWS.entries()) {
			const maskRows: string[] = [];
			const depthRows: string[] = [];
			for (let y = 0; y < size; y += 1) {
				let maskRow = '';
				let depthRow = '';
				for (let x = 0; x < size; x += 1) {
					const sx = Math.min(canvas.width - 1, Math.floor((x + 0.5) * (cellW / size)));
					const sy = Math.min(
						canvas.height - 1,
						Math.floor(rowIndex * cellH + (y + 0.5) * (cellH / size))
					);
					const maskPixel = ctx.getImageData(sx, sy, 1, 1).data;
					const depthPixel = ctx.getImageData(
						Math.min(canvas.width - 1, sx + cellW),
						sy,
						1,
						1
					).data;
					maskRow += grayscaleAt(maskPixel, 0) > 96 ? '1' : '0';
					depthRow += grayscaleAt(depthPixel, 0).toString(16).padStart(2, '0');
				}
				maskRows.push(maskRow);
				depthRows.push(depthRow);
			}
			const filled = maskRows.join('').replace(/0/g, '').length;
			if (filled < size * size * 0.05) {
				throw new Error(`Generated ${view} mask is almost empty`);
			}
			viewMasks[view] = { width: size, height: size, rows: maskRows };
			viewDepthMaps[view] = { width: size, height: size, rows: depthRows };
		}
		return { viewMasks, viewDepthMaps };
	}

	function dreamMapImagePrompt(args: { text: string; targetObjectId: string }): string {
		const isSurface = /\b(roof|canopy|cloth|fabric|terrain|surface|panel|skin)\b/i.test(args.text);
		return [
			`Generate a machine-readable orthographic geometry map sheet for object ${args.targetObjectId}.`,
			`Design intent: ${args.text}`,
			'The attached reference image is a six-row orthographic source sheet of the existing OBJ. Its rows are top, bottom, left, right, front, back.',
			'Treat the attached source sheet as the hard geometry constraint. Preserve its silhouette, proportions, rim/base widths, centerline, and row-by-row view correspondence.',
			'Do not invent a new base form. Add only residual surface relief such as folds, ridges, and ceramic undulations inside the original source silhouettes.',
			'Output exactly a 2 column by 6 row grid. No labels, no text, no margins, no shadows.',
			'Rows, top to bottom: top, bottom, left, right, front, back.',
			'Left column: binary silhouette mask, white object on pure black background.',
			'Right column: grayscale depth map aligned pixel-perfectly to the mask.',
			'Depth convention: white means closest visible surface to that camera; black means farthest visible surface inside the same object bounds.',
			'Use smooth continuous grayscale values, not posterized steps.',
			'Keep every row consistent with the attached source sheet. Preserve original object height, base width, rim width, center position, and overall bounding box.',
			isSurface
				? 'For a surface-like part, put the expressive folds primarily in the top/depth view and keep side views broad and consistent.'
				: 'For a vase/object, keep front/back/left/right silhouettes vase-like and coherent; do not let top/bottom depth maps redesign the whole body.',
			'Make the surface spatially expressive with folds, carved ridges, and ceramic undulations while keeping it a single continuous object.'
		].join('\n');
	}

	async function requestGeneratedDreamMaps(args: {
		text: string;
		targetObjectId: string;
		screenshotDataUrl: string;
	}): Promise<{
		imageDataUrl: string;
		viewMasks: Record<string, DreamMap>;
		viewDepthMaps: Record<string, DreamMap>;
	}> {
		const imageProvider = providerSettings.provider;
		const imageModel = providerSettings.imageModel?.trim() || undefined;
		const res = await fetch('/api/render-image', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				prompt: dreamMapImagePrompt(args),
				screenshotDataUrl: args.screenshotDataUrl,
				liveObjText,
				provider: imageProvider,
				apiKey: providerSettings.apiKey?.trim() || undefined,
				imageUrl: providerSettings.imageUrl?.trim() || undefined,
				imageModel
			})
		});
		const payload = (await res.json().catch(() => ({}))) as {
			imageDataUrl?: string;
			message?: string;
		};
		if (!res.ok || !payload.imageDataUrl) {
			throw new Error(payload.message || res.statusText || 'Dream map image generation failed');
		}
		recordRenderModelUsage('Image texture', imageProvider, imageModel);
		const maps = await parseDreamMapSheetImage(payload.imageDataUrl);
		return { imageDataUrl: payload.imageDataUrl, ...maps };
	}

	function bytesToBase64(bytes: Uint8Array): string {
		let binary = '';
		const chunkSize = 0x8000;
		for (let i = 0; i < bytes.length; i += chunkSize) {
			binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
		}
		return btoa(binary);
	}

	async function imageToPngDataUrl(
		imageUrl: string,
		width?: number,
		height?: number
	): Promise<string> {
		const img = await loadImageDataUrl(imageUrl);
		const canvas = document.createElement('canvas');
		canvas.width = width ?? (img.naturalWidth || img.width);
		canvas.height = height ?? (img.naturalHeight || img.height);
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('Unable to convert image');
		ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
		return canvas.toDataURL('image/png');
	}

	async function imageToBmpDataUrl(
		imageUrl: string,
		width = UV_ATLAS_SIZE,
		height = UV_ATLAS_SIZE
	): Promise<string> {
		const img = await loadImageDataUrl(imageUrl);
		const canvas = document.createElement('canvas');
		canvas.width = width;
		canvas.height = height;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('Unable to convert height map');
		ctx.drawImage(img, 0, 0, width, height);
		const rgba = ctx.getImageData(0, 0, width, height).data;
		const rowStride = Math.ceil((width * 3) / 4) * 4;
		const pixelOffset = 54;
		const fileSize = pixelOffset + rowStride * height;
		const bytes = new Uint8Array(fileSize);
		const view = new DataView(bytes.buffer);
		bytes[0] = 0x42;
		bytes[1] = 0x4d;
		view.setUint32(2, fileSize, true);
		view.setUint32(10, pixelOffset, true);
		view.setUint32(14, 40, true);
		view.setInt32(18, width, true);
		view.setInt32(22, height, true);
		view.setUint16(26, 1, true);
		view.setUint16(28, 24, true);
		view.setUint32(34, rowStride * height, true);
		for (let y = 0; y < height; y += 1) {
			const sourceY = height - 1 - y;
			const rowOffset = pixelOffset + y * rowStride;
			for (let x = 0; x < width; x += 1) {
				const sourceIndex = (sourceY * width + x) * 4;
				const targetIndex = rowOffset + x * 3;
				const gray = Math.round(
					(rgba[sourceIndex] + rgba[sourceIndex + 1] + rgba[sourceIndex + 2]) / 3
				);
				bytes[targetIndex] = gray;
				bytes[targetIndex + 1] = gray;
				bytes[targetIndex + 2] = gray;
			}
		}
		return `data:image/bmp;base64,${bytesToBase64(bytes)}`;
	}

	async function imageToColorBmpDataUrl(
		imageUrl: string,
		width = UV_ATLAS_SIZE,
		height = UV_ATLAS_SIZE
	): Promise<string> {
		const img = await loadImageDataUrl(imageUrl);
		const canvas = document.createElement('canvas');
		canvas.width = width;
		canvas.height = height;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('Unable to convert diffuse map');
		ctx.drawImage(img, 0, 0, width, height);
		const rgba = ctx.getImageData(0, 0, width, height).data;
		const rowStride = Math.ceil((width * 3) / 4) * 4;
		const pixelOffset = 54;
		const fileSize = pixelOffset + rowStride * height;
		const bytes = new Uint8Array(fileSize);
		const view = new DataView(bytes.buffer);
		bytes[0] = 0x42;
		bytes[1] = 0x4d;
		view.setUint32(2, fileSize, true);
		view.setUint32(10, pixelOffset, true);
		view.setUint32(14, 40, true);
		view.setInt32(18, width, true);
		view.setInt32(22, height, true);
		view.setUint16(26, 1, true);
		view.setUint16(28, 24, true);
		view.setUint32(34, rowStride * height, true);
		for (let y = 0; y < height; y += 1) {
			const sourceY = height - 1 - y;
			const rowOffset = pixelOffset + y * rowStride;
			for (let x = 0; x < width; x += 1) {
				const sourceIndex = (sourceY * width + x) * 4;
				const targetIndex = rowOffset + x * 3;
				bytes[targetIndex] = rgba[sourceIndex + 2];
				bytes[targetIndex + 1] = rgba[sourceIndex + 1];
				bytes[targetIndex + 2] = rgba[sourceIndex];
			}
		}
		return `data:image/bmp;base64,${bytesToBase64(bytes)}`;
	}

	function uvHeightMapPrompt(args: { text: string; targetObjectId: string }): string {
		return [
			`Generate a machine-readable grayscale UV height map for object ${args.targetObjectId}.`,
			`Design intent: ${args.text}`,
			'The attached image is a clean UV island guide for the existing mesh.',
			'Output exactly one square grayscale height map in the same atlas layout, dimensions, island positions, and margins.',
			'Treat the full square image as a fixed UV document. Do not crop, pad, stretch, letterbox, recenter, or change the aspect ratio.',
			'Do not move, resize, rotate, or regroup UV islands. Preserve every island boundary.',
			'Use pure black outside UV islands. Inside islands, use smooth continuous grayscale relief.',
			'Do not copy guide colors, borders, outlines, seams, diagonal marks, or debug annotations into the output.',
			'White means raised surface. Black means recessed surface. Mid gray means neutral base surface.',
			'Create controlled smooth pleats, ribs, folds, grooves, or surface relief according to the design intent.',
			'Make features align across island borders where connected surfaces meet.',
			'No labels, no text, no shadows, no perspective render, no colored material preview.'
		].join('\n');
	}

	async function requestGeneratedUvHeightMap(args: {
		text: string;
		targetObjectId: string;
		sourceUvDataUrl: string;
	}): Promise<string> {
		const imageProvider = providerSettings.provider;
		const imageModel = providerSettings.imageModel?.trim() || undefined;
		const res = await fetch('/api/render-image', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				prompt: uvHeightMapPrompt(args),
				screenshotDataUrl: args.sourceUvDataUrl,
				provider: imageProvider,
				apiKey: providerSettings.apiKey?.trim() || undefined,
				imageUrl: providerSettings.imageUrl?.trim() || undefined,
				imageModel,
				targetAspectRatio: UV_ATLAS_ASPECT_RATIO,
				targetWidth: UV_ATLAS_SIZE,
				targetHeight: UV_ATLAS_SIZE
			})
		});
		const payload = (await res.json().catch(() => ({}))) as {
			imageDataUrl?: string;
			message?: string;
		};
		if (!res.ok || !payload.imageDataUrl) {
			throw new Error(payload.message || res.statusText || 'UV height map generation failed');
		}
		recordRenderModelUsage('Image texture', imageProvider, imageModel);
		return payload.imageDataUrl;
	}

	function uvDiffuseMapPrompt(args: { text: string; targetObjectId: string }): string {
		return [
			`Generate a machine-readable diffuse color UV atlas for object ${args.targetObjectId}.`,
			`Design intent: ${args.text}`,
			'The attached image is the grayscale UV height/depth map for the same object.',
			'Use the height map as the exact square atlas canvas, layout, and relief guide. Preserve all island positions, dimensions, borders, and black outside-island background.',
			'Treat the full square image as a fixed UV document. Do not crop, pad, stretch, letterbox, recenter, or change the aspect ratio.',
			'Create an albedo/diffuse color texture that follows the relief: raised ridges, recessed valleys, folds, and smooth transitions should line up with the grayscale map.',
			'Do not change the UV layout. Do not add labels, text, shadows, lighting highlights, perspective, or a rendered object view.',
			'Keep the texture usable as a flat material color map, not a beauty render.'
		].join('\n');
	}

	async function requestGeneratedUvDiffuseMap(args: {
		text: string;
		targetObjectId: string;
		heightMapDataUrl: string;
	}): Promise<string> {
		const imageProvider = providerSettings.provider;
		const imageModel = providerSettings.imageModel?.trim() || undefined;
		const res = await fetch('/api/render-image', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				prompt: uvDiffuseMapPrompt(args),
				screenshotDataUrl: args.heightMapDataUrl,
				provider: imageProvider,
				apiKey: providerSettings.apiKey?.trim() || undefined,
				imageUrl: providerSettings.imageUrl?.trim() || undefined,
				imageModel,
				targetAspectRatio: UV_ATLAS_ASPECT_RATIO,
				targetWidth: UV_ATLAS_SIZE,
				targetHeight: UV_ATLAS_SIZE
			})
		});
		const payload = (await res.json().catch(() => ({}))) as {
			imageDataUrl?: string;
			message?: string;
		};
		if (!res.ok || !payload.imageDataUrl) {
			throw new Error(payload.message || res.statusText || 'UV diffuse map generation failed');
		}
		recordRenderModelUsage('Image texture', imageProvider, imageModel);
		return payload.imageDataUrl;
	}

	async function runUvDreamEnhanceTurn(args: {
		text: string;
		targetObjectId: string;
		mode?: 'displace' | 'map-remesh';
		amount?: number;
		signal?: AbortSignal;
	}) {
		const mode = args.mode ?? uvDreamModeFromPrompt(args.text);
		const amount = Number.isFinite(args.amount) ? Math.max(0, Math.min(2, args.amount ?? 1)) : 1;
		throwIfAborted(args.signal);
		statusLine = `Unwrapping ${args.targetObjectId} into a UV atlas.`;
		appendProgressMessage(`UV dream: unwrapping ${args.targetObjectId}.`, 'building source atlas');
		const unwrapRes = await fetch('/api/live-obj/uv-dream-unwrap', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			signal: args.signal,
			body: JSON.stringify({
				liveObj: liveObjText.trim(),
				targetObjectId: args.targetObjectId
			})
		});
		const unwrapPayload = (await unwrapRes.json().catch(() => ({}))) as UvDreamPayload;
		throwIfAborted(args.signal);
		if (!unwrapRes.ok || !unwrapPayload.sourceUvUrl) {
			throw new Error(unwrapPayload.message || unwrapRes.statusText || 'UV unwrap failed');
		}
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: `Unwrapped ${args.targetObjectId} into a UV atlas.`,
				imageDataUrl: unwrapPayload.sourceUvUrl,
				meta: 'source uv unwrap',
				excludeFromHistory: true
			}
		];

		if (!providerSettings.apiKey?.trim()) {
			throw new Error(
				'UV dream enhancement needs an image provider key to generate the height map.'
			);
		}
		statusLine = `Generating UV height map for ${args.targetObjectId}.`;
		appendProgressMessage(
			`UV dream: preparing ${args.targetObjectId} unwrap for the image model.`,
			'texture generation input'
		);
		const sourceUvDataUrl = await imageToPngDataUrl(
			unwrapPayload.sourceGuideUrl ?? unwrapPayload.sourceUvUrl,
			UV_ATLAS_SIZE,
			UV_ATLAS_SIZE
		);
		appendProgressMessage(
			'UV dream: asking the image model for a grayscale height map.',
			'texture generation'
		);
		const generatedHeightDataUrl = await imageToPngDataUrl(
			await requestGeneratedUvHeightMap({
				text: args.text,
				targetObjectId: args.targetObjectId,
				sourceUvDataUrl
			}),
			UV_ATLAS_SIZE,
			UV_ATLAS_SIZE
		);
		throwIfAborted(args.signal);
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: `Generated UV height map for ${args.targetObjectId}.`,
				imageDataUrl: generatedHeightDataUrl,
				meta: 'generated uv height',
				excludeFromHistory: true
			}
		];
		statusLine = `Generating UV diffuse map for ${args.targetObjectId}.`;
		appendProgressMessage(
			'UV dream: asking the image model for a diffuse color map based on the height map.',
			'diffuse texture generation'
		);
		let diffusePngDataUrl: string | undefined;
		let diffuseBmpDataUrl: string | undefined;
		try {
			const generatedDiffuseDataUrl = await requestGeneratedUvDiffuseMap({
				text: args.text,
				targetObjectId: args.targetObjectId,
				heightMapDataUrl: generatedHeightDataUrl
			});
			throwIfAborted(args.signal);
			diffusePngDataUrl = await imageToPngDataUrl(
				generatedDiffuseDataUrl,
				UV_ATLAS_SIZE,
				UV_ATLAS_SIZE
			);
			diffuseBmpDataUrl = await imageToColorBmpDataUrl(diffusePngDataUrl);
			msgs = [
				...msgs,
				{
					role: 'assistant',
					content: `Generated UV diffuse map for ${args.targetObjectId}.`,
					imageDataUrl: diffusePngDataUrl,
					meta: 'generated uv diffuse',
					excludeFromHistory: true
				}
			];
		} catch (err) {
			throwIfAborted(args.signal);
			appendProgressMessage(
				'UV diffuse map generation failed; using deterministic texture fallback.',
				err instanceof Error ? err.message : String(err)
			);
		}

		statusLine = `Applying UV displacement to ${args.targetObjectId}.`;
		appendProgressMessage(
			'UV dream: converting the height map into displacement data.',
			'height map conversion'
		);
		const heightBmpDataUrl = await imageToBmpDataUrl(generatedHeightDataUrl);
		appendProgressMessage(
			`UV dream: applying displacement back onto ${args.targetObjectId}.`,
			'mesh update'
		);
		showThinkingMessage(`Applying UV height map to ${args.targetObjectId}...`);
		const enhanceRes = await fetch('/api/live-obj/uv-dream-enhance', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			signal: args.signal,
			body: JSON.stringify({
				liveObj: liveObjText.trim(),
				targetObjectId: args.targetObjectId,
				heightBmpDataUrl,
				diffusePngDataUrl,
				diffuseBmpDataUrl,
				mode,
				amount,
				shade: 'smooth'
			})
		});
		const payload = (await enhanceRes.json().catch(() => ({}))) as UvDreamPayload;
		throwIfAborted(args.signal);
		if (!enhanceRes.ok || !payload.liveObj) {
			throw new Error(payload.message || enhanceRes.statusText || 'UV dream enhancement failed');
		}
		clearThinkingMessage();
		liveObjText = String(payload.liveObj);
		executedObjText = displayObjForSource(
			liveObjText,
			String(payload.executedObj ?? payload.liveObj)
		);
		rawLlmText = JSON.stringify(
			{
				workflow: 'uv_dream_enhance',
				targetObjectId: args.targetObjectId,
				mode,
				artifacts: payload.artifacts ?? {},
				warnings: payload.warnings ?? []
			},
			null,
			2
		);
		currentSceneMode = 'raw_obj';
		sourceTab = 'executed';
		sceneEpoch += 1;
		applyObjString(executedObjText, liveObjText);
		appendProgressMessage(
			'UV dream: loading generated texture and debug maps.',
			'artifact preview'
		);
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: `UV dream enhanced ${args.targetObjectId} from its unwrap atlas.`,
				historyContent: liveObjText
			}
		];
		appendMetadataImageMessages(liveObjText);
		statusLine = payload.warnings?.[0] ?? null;
	}

	function plannedUvPostProcess(part: IterativePartSpec): IterativePartPostProcess | null {
		const postProcess = part.postProcess;
		const type = postProcess?.type
			?.trim()
			.toLowerCase()
			.replace(/[-\s]+/g, '_');
		return type === 'uv_dream' ? (postProcess ?? { type: 'uv_dream' }) : null;
	}

	function plannedPostProcessTarget(part: IterativePartSpec, addedObjectNames: string[]): string {
		const plannedTarget = part.postProcess?.targetObjectId?.trim();
		const liveNames = objectNamesFromLiveObj(liveObjText);
		if (plannedTarget && liveNames.includes(plannedTarget)) return plannedTarget;
		if (addedObjectNames.length === 1) return addedObjectNames[0];
		if (addedObjectNames.includes(part.id)) return part.id;
		if (liveNames.includes(part.id)) return part.id;
		return addedObjectNames[0] ?? '';
	}

	async function runPlannedPartPostProcess(args: {
		text: string;
		part: IterativePartSpec;
		addedObjectNames: string[];
		label: string;
		signal?: AbortSignal;
	}) {
		const postProcess = plannedUvPostProcess(args.part);
		if (!postProcess) return;
		const target = plannedPostProcessTarget(args.part, args.addedObjectNames);
		if (!target) {
			appendProgressMessage(
				`Planned UV dream for ${args.label}, but no generated object target was found.`,
				'planned post-process skipped'
			);
			return;
		}
		if (!providerSettings.apiKey?.trim()) {
			appendProgressMessage(
				`Planner selected UV dream for ${target}. Add an image provider key to run it.`,
				'planned post-process skipped'
			);
			return;
		}
		const mode =
			postProcess.mode
				?.trim()
				.toLowerCase()
				.replace(/[-\s]+/g, '-') === 'map-remesh'
				? 'map-remesh'
				: 'displace';
		const detailPrompt = [args.text, args.part.prompt, postProcess.prompt]
			.map((value) => value?.trim())
			.filter(Boolean)
			.join('\n\n');
		appendProgressMessage(
			`Planner selected UV dream for ${target}.`,
			`planned post-process: ${mode}`
		);
		await runUvDreamEnhanceTurn({
			text: detailPrompt || args.text,
			targetObjectId: target,
			mode,
			amount: postProcess.amount,
			signal: args.signal
		});
	}

	async function runDreamRebuildTurn(args: {
		text: string;
		targetObjectId: string;
		signal?: AbortSignal;
	}) {
		throwIfAborted(args.signal);
		statusLine = `Capturing six source views for ${args.targetObjectId}.`;
		const referenceSheetDataUrl = await captureDreamReferenceSheet(args.targetObjectId);
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: `Captured six-view source sheet for ${args.targetObjectId}.`,
				imageDataUrl: referenceSheetDataUrl,
				meta: 'dream source sheet',
				excludeFromHistory: true
			}
		];
		let maps: { viewMasks: Record<string, DreamMap>; viewDepthMaps: Record<string, DreamMap> };
		let sheet = '';
		let usedGeneratedSheet = false;
		if (referenceSheetDataUrl && providerSettings.apiKey?.trim()) {
			try {
				statusLine = `Generating six-view depth maps for ${args.targetObjectId}.`;
				const generated = await requestGeneratedDreamMaps({
					text: args.text,
					targetObjectId: args.targetObjectId,
					screenshotDataUrl: referenceSheetDataUrl
				});
				maps = { viewMasks: generated.viewMasks, viewDepthMaps: generated.viewDepthMaps };
				sheet = generated.imageDataUrl;
				usedGeneratedSheet = true;
			} catch (err) {
				appendProgressMessage(
					'Image depth-map generation failed; using deterministic map fallback.',
					err instanceof Error ? err.message : String(err)
				);
				maps = syntheticDreamMaps();
				sheet = dreamMapSheetDataUrl(maps.viewMasks, maps.viewDepthMaps);
			}
		} else {
			appendProgressMessage('No image provider key available; using deterministic map fallback.');
			maps = syntheticDreamMaps();
			sheet = dreamMapSheetDataUrl(maps.viewMasks, maps.viewDepthMaps);
		}
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: `${usedGeneratedSheet ? 'Generated' : 'Prepared'} six-view mask/depth sheet for ${args.targetObjectId}.`,
				imageDataUrl: sheet,
				meta: 'dream map sheet',
				excludeFromHistory: true
			}
		];
		statusLine = `Dream rebuilding ${args.targetObjectId}.`;
		showThinkingMessage(`Reconstructing ${args.targetObjectId} from depth maps...`);
		const res = await fetch('/api/live-obj/dream-rebuild', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			signal: args.signal,
			body: JSON.stringify({
				liveObj: liveObjText.trim(),
				targetObjectId: args.targetObjectId,
				prompt: args.text,
				reconstruction: 'tsdf',
				mode: /\b(from scratch|new topology|complex spatial|reconstruct from scratch)\b/i.test(
					args.text
				)
					? 'replace'
					: 'enhance',
				profile: /\b(roof|canopy|cloth|fabric|terrain|surface|panel|skin)\b/i.test(args.text)
					? 'surface'
					: 'object',
				resolution: 38,
				...maps
			})
		});
		const payload = (await res.json().catch(() => ({}))) as DreamRebuildPayload;
		throwIfAborted(args.signal);
		if (!res.ok || !payload.liveObj) {
			throw new Error(payload.message || res.statusText || 'Dream rebuild failed');
		}
		clearThinkingMessage();
		liveObjText = String(payload.liveObj);
		executedObjText = displayObjForSource(
			liveObjText,
			String(payload.executedObj ?? payload.liveObj)
		);
		rawLlmText = JSON.stringify(payload.dream ?? {}, null, 2);
		currentSceneMode = 'raw_obj';
		sourceTab = 'executed';
		sceneEpoch += 1;
		applyObjString(executedObjText, liveObjText);
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: `Dream rebuilt ${args.targetObjectId} from six depth maps.`,
				historyContent: liveObjText
			}
		];
		appendMetadataImageMessages(liveObjText);
		statusLine = payload.dream?.warnings?.[0] ?? null;
	}

	async function waitForSceneCaptureFrame() {
		await tick();
		await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
		await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
	}

	const AUTO_FINAL_RENDER_VIEWS: Array<{ label: string; direction: [number, number, number] }> = [
		{ label: 'Hero', direction: [-1, 0.65, -1] },
		{ label: 'Front', direction: [0, 0.45, -1] },
		{ label: 'Right', direction: [1, 0.45, -0.2] },
		{ label: 'Back', direction: [0.25, 0.45, 1] },
		{ label: 'Left', direction: [-1, 0.45, 0.2] },
		{ label: 'High three-quarter', direction: [-0.45, 1.15, -0.7] },
		{ label: 'Top', direction: [-0.2, 1.35, 0.25] },
		{ label: 'Low reveal', direction: [0.65, 0.2, -1] }
	];
	const MAX_RENDER_FRAME_ASSETS = 96;
	const MAX_PROJECT_PROCESS_IMAGES = 64;

	const REEL_TURNTABLE_VIEWS: Array<{ label: string; direction: [number, number, number] }> = [
		{ label: 'Orbit front', direction: [0, 0.42, -1] },
		{ label: 'Orbit front right', direction: [0.72, 0.42, -0.72] },
		{ label: 'Orbit right', direction: [1, 0.42, 0] },
		{ label: 'Orbit back right', direction: [0.72, 0.42, 0.72] },
		{ label: 'Orbit back', direction: [0, 0.42, 1] },
		{ label: 'Orbit back left', direction: [-0.72, 0.42, 0.72] },
		{ label: 'Orbit left', direction: [-1, 0.42, 0] },
		{ label: 'Orbit front left', direction: [-0.72, 0.42, -0.72] }
	];

	function makeRenderFrameId(): string {
		return typeof crypto !== 'undefined' && 'randomUUID' in crypto
			? crypto.randomUUID()
			: `${Date.now()}-${Math.random().toString(16).slice(2)}`;
	}

	async function captureFinalRenderGalleryFrames() {
		if (!canvasRef || !renderObject) return;
		const originalCamera = canvasRef.captureCameraSnapshot?.() ?? null;
		const capturedAt = Date.now();
		const nextAssets: FrameAsset[] = [];
		await waitForSceneCaptureFrame();
		for (const [index, view] of AUTO_FINAL_RENDER_VIEWS.entries()) {
			const imageDataUrl =
				canvasRef.captureScreenshot?.({
					maxWidth: 1280,
					format: 'image/jpeg',
					quality: 0.9,
					autoFrame: true,
					framePadding: 1.08,
					viewDirection: view.direction
				}) ?? '';
			if (!imageDataUrl) continue;
			nextAssets.push({
				id: makeRenderFrameId(),
				label: `Final ${view.label}`,
				source: 'screenshot',
				imageDataUrl,
				camera: canvasRef.captureCameraSnapshot?.() ?? null,
				capturedAt: capturedAt + index
			});
		}
		canvasRef.restoreCameraSnapshot?.(originalCamera);
		if (nextAssets.length === 0) return;
		renderFrameAssets = [...nextAssets, ...renderFrameAssets].slice(0, MAX_RENDER_FRAME_ASSETS);
		renderVideoShot = {
			start: nextAssets[0],
			middle: nextAssets[1],
			end: nextAssets[2],
			transitionPrompts: renderVideoShot.transitionPrompts,
			clips: []
		};
	}

	async function captureReelTurntableFrames(): Promise<FrameAsset[]> {
		if (!canvasRef || !renderObject) return [];
		const originalCamera = canvasRef.captureCameraSnapshot?.() ?? null;
		const capturedAt = Date.now();
		const nextAssets: FrameAsset[] = [];
		await waitForSceneCaptureFrame();
		for (const [index, view] of REEL_TURNTABLE_VIEWS.entries()) {
			const imageDataUrl =
				canvasRef.captureScreenshot?.({
					maxWidth: 1280,
					format: 'image/jpeg',
					quality: 0.9,
					autoFrame: true,
					framePadding: 1.06,
					viewDirection: view.direction
				}) ?? '';
			if (!imageDataUrl) continue;
			nextAssets.push({
				id: makeRenderFrameId(),
				label: view.label,
				source: 'screenshot',
				imageDataUrl,
				camera: canvasRef.captureCameraSnapshot?.() ?? null,
				capturedAt: capturedAt + index
			});
		}
		canvasRef.restoreCameraSnapshot?.(originalCamera);
		if (nextAssets.length) renderTurntableFrameAssets = nextAssets;
		return nextAssets;
	}

	function captureFeedbackScreenshot() {
		return (
			canvasRef?.captureScreenshot({
				maxWidth: 768,
				format: 'image/jpeg',
				quality: 0.82,
				maxBytes: 900_000,
				autoFrame: true,
				framePadding: 1.02
			}) ?? ''
		);
	}

	function feedbackPrompt(
		originalText: string,
		pass: number,
		total: number,
		hasReferenceImage: boolean
	): string {
		return [
			`Visual repair pass ${pass} of ${total}.`,
			hasReferenceImage
				? 'Compare the attached images: first is the original reference image, last is the current rendered 3D scene screenshot.'
				: 'Review the attached rendered screenshot of the current 3D scene against the original user request.',
			`Original user request: ${originalText || 'Use the attached image/request context.'}`,
			'First diagnose visible geometry problems: intersections, floating parts, occluded openings, roof/panel collisions, misplaced glass, wrong scale, and parts that contradict the source request.',
			'Also inspect the mesh for accidental holes or missing polygon spans. Treat holes as errors only when they contradict the part intent; do not close deliberate openings such as lampshade rims, windows, doorways, hollow vessels, frames, tubes, lattices, or intentionally open ends.',
			'Use both the screenshot and the current Live OBJ coordinates to find conflicts. The screenshot shows what is visible; the OBJ coordinates show whether objects overlap in 3D.',
			'Repair existing objects before adding any new detail. If glass intersects a roof/shell, move, trim, lower, narrow, or remove the glass panels instead of adding decorative elements.',
			'If there is no clear visible geometry problem, make no changes. For a surgical patch, return {"summary":"No visible repair needed","edits":[]}.',
			'Patch only the specific named objects that need repair. Do not replace the whole scene or simplify successful parts.',
			'Do not add new decorative objects unless the current screenshot has no obvious geometry conflicts.',
			'Preserve successful object IDs and proportions. Return an updated OBJ scene.'
		].join('\n');
	}

	function partFeedbackPrompt(args: {
		originalText: string;
		label: string;
		part: IterativePartSpec;
		partNumber: number;
		partCount: number;
		hasReferenceImage: boolean;
	}): string {
		const dependencies = args.part.dependencies?.length
			? args.part.dependencies.join(', ')
			: 'no declared dependencies';
		return [
			`Targeted visual repair for part ${args.partNumber} of ${args.partCount}: ${args.label}.`,
			args.hasReferenceImage
				? 'Compare the attached images: reference image(s) first, current rendered scene screenshot last.'
				: 'Review the attached rendered screenshot of the current 3D scene against the original user request.',
			`Original user request: ${args.originalText || 'Use the attached image/request context.'}`,
			`Newly added part id: ${args.part.id}.`,
			`Declared dependencies/contact context: ${dependencies}.`,
			'Focus only on visible problems involving the newly added part and directly touching/supporting objects: intersections, floating geometry, hidden openings, wrong contact, wrong scale, or occlusion caused by this addition.',
			'The screenshot is an x-ray diagnostic view: cyan wireframe objects are the newly added part, amber objects are direct dependencies/focus context, and transparent gray objects are surrounding scene geometry that may still occlude or collide.',
			'Check the cyan wireframe for accidental missing faces, broken caps, or incomplete side panels. Only repair holes that are not intentional; preserve deliberate openings such as lampshade rims, windows, doorways, hollow vessels, frames, tubes, lattices, and open-ended structural members.',
			'If a wall, roof, slab, glass panel, or support intersects another major part, repair the smaller/newly added offender first. Patch a directly touching dependency only when that is the minimal fix.',
			'If the new part is visibly acceptable, make no changes. For a surgical patch, return {"summary":"No visible repair needed","edits":[]}.',
			'Do not redesign the whole scene. Do not replace unrelated successful objects. Return an updated OBJ scene.'
		].join('\n');
	}

	async function appendPartWithStreamingPreview(args: {
		text: string;
		initialImageUrls: string[];
		workingLiveObj: string;
		plan: IterativeScenePlan;
		part: IterativePartSpec;
		model: string;
		label: string;
		signal?: AbortSignal;
	}) {
		const { text, initialImageUrls, workingLiveObj, plan, part, model, label, signal } = args;
		throwIfAborted(signal);
		showThinkingMessage(`Thinking about ${label}...`);
		const res = await fetch('/api/live-obj/append-part/stream', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			signal,
			body: JSON.stringify({
				userMessage: text,
				...(initialImageUrls.length === 1 ? { imageUrl: initialImageUrls[0] } : {}),
				...(initialImageUrls.length > 1 ? { imageUrls: initialImageUrls } : {}),
				currentLiveObj: workingLiveObj,
				plan,
				part,
				model,
				useProcedural: false,
				apiKey: providerSettings.apiKey?.trim() || undefined,
				apiUrl: providerSettings.apiUrl?.trim() || undefined
			})
		});
		if (!res.ok) {
			const payload = (await res.json().catch(() => ({}))) as IterativeAppendPayload;
			throw new Error(payload.message || res.statusText || `Streamed part ${label} failed`);
		}
		if (!res.body) throw new Error(`Streamed part ${label} failed: response had no body`);

		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		const previewLines: string[] = [];
		let buffer = '';
		let finalPayload: IterativeAppendPayload | null = null;
		let lastPreviewAt = 0;
		let faceLinesSincePreview = 0;
		const baseFaceCount = countObjFaceLines(workingLiveObj);
		const baseVertexCount = countObjVertexLines(workingLiveObj);
		const flushPreview = (force = false) => {
			if (previewLines.length === 0) return;
			const now = performance.now();
			if (!force && faceLinesSincePreview < 4 && now - lastPreviewAt < 220) return;
			const remappedPreviewLines = remapPreviewPartLines(previewLines, baseVertexCount);
			if (!remappedPreviewLines) return;
			const previewObj = `${workingLiveObj.trimEnd()}\n${remappedPreviewLines.join('\n')}\n`;
			if (countObjFaceLines(previewObj) <= baseFaceCount) return;
			if (!tryApplyObjString(previewObj, previewObj)) return;
			lastPreviewAt = now;
			faceLinesSincePreview = 0;
		};

		for (;;) {
			throwIfAborted(signal);
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			const lines = buffer.split(/\r?\n/);
			buffer = lines.pop() ?? '';
			for (const line of lines) {
				if (!line.trim()) continue;
				const event = JSON.parse(line) as IterativeAppendStreamEvent;
				if (event.type === 'status') {
					statusLine = event.message ?? `Building ${label}.`;
				} else if (event.type === 'preview_line') {
					previewLines.push(event.line);
					if (/^\s*f\s+/.test(event.line)) faceLinesSincePreview += 1;
					if (faceLinesSincePreview > 0) clearThinkingMessage();
					flushPreview(false);
				} else if (event.type === 'final') {
					clearThinkingMessage();
					finalPayload = event;
				} else if (event.type === 'error') {
					clearThinkingMessage();
					throw new Error(event.message || `Streamed part ${label} failed`);
				}
			}
		}
		if (buffer.trim()) {
			const event = JSON.parse(buffer) as IterativeAppendStreamEvent;
			if (event.type === 'status') {
				statusLine = event.message ?? `Building ${label}.`;
			} else if (event.type === 'final') {
				clearThinkingMessage();
				finalPayload = event;
			} else if (event.type === 'error') {
				clearThinkingMessage();
				throw new Error(event.message || `Streamed part ${label} failed`);
			}
		}
		if (!finalPayload) throw new Error(`Streamed part ${label} finished without a final scene`);
		if (finalPayload.validation && !finalPayload.validation.valid) {
			throw new Error(finalPayload.validation.errors.join('; ') || `Streamed part ${label} failed`);
		}
		flushPreview(true);
		return finalPayload;
	}

	async function requestIterativePlanWithStreaming(args: {
		text: string;
		initialImageUrls: string[];
		model: string;
		useProcedural: boolean;
		currentLiveObj?: string;
		signal?: AbortSignal;
	}): Promise<IterativePlanSuccessPayload> {
		const { text, initialImageUrls, model, useProcedural, currentLiveObj = '', signal } = args;
		throwIfAborted(signal);
		const res = await fetch('/api/live-obj/plan/stream', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			signal,
			body: JSON.stringify({
				userMessage: text,
				...(initialImageUrls.length === 1 ? { imageUrl: initialImageUrls[0] } : {}),
				...(initialImageUrls.length > 1 ? { imageUrls: initialImageUrls } : {}),
				currentLiveObj,
				model,
				useProcedural,
				apiKey: providerSettings.apiKey?.trim() || undefined,
				apiUrl: providerSettings.apiUrl?.trim() || undefined
			})
		});
		if (!res.ok) {
			const payload = (await res.json().catch(() => ({}))) as IterativePlanPayload;
			throw new Error(payload.message || res.statusText || 'Part planning failed');
		}
		if (!res.body) throw new Error('Part planning failed: response had no body');

		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buffer = '';
		let finalPayload: IterativePlanPayload | null = null;

		for (;;) {
			throwIfAborted(signal);
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			const lines = buffer.split(/\r?\n/);
			buffer = lines.pop() ?? '';
			for (const line of lines) {
				if (!line.trim()) continue;
				const event = JSON.parse(line) as IterativePlanStreamEvent;
				if (event.type === 'status') {
					statusLine = event.message ?? 'Planning scene parts.';
				} else if (event.type === 'final') {
					finalPayload = event;
				} else if (event.type === 'error') {
					throw new Error(event.message || 'Part planning failed');
				}
			}
		}
		if (buffer.trim()) {
			const event = JSON.parse(buffer) as IterativePlanStreamEvent;
			if (event.type === 'final') {
				finalPayload = event;
			} else if (event.type === 'error') {
				throw new Error(event.message || 'Part planning failed');
			}
		}
		if (!finalPayload?.plan?.parts?.length) {
			throw new Error(finalPayload?.message || 'Part planning failed');
		}
		return finalPayload as IterativePlanSuccessPayload;
	}

	async function appendPartWithoutStreaming(args: {
		text: string;
		initialImageUrls: string[];
		workingLiveObj: string;
		plan: IterativeScenePlan;
		part: IterativePartSpec;
		model: string;
		useProcedural: boolean;
		partNumber: number;
		signal?: AbortSignal;
	}) {
		const {
			text,
			initialImageUrls,
			workingLiveObj,
			plan,
			part,
			model,
			useProcedural,
			partNumber,
			signal
		} = args;
		throwIfAborted(signal);
		const label = partLabel(part, partNumber - 1);
		showThinkingMessage(`Thinking about ${label}...`);
		const appendRes = await fetch('/api/live-obj/append-part', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			signal,
			body: JSON.stringify({
				userMessage: text,
				...(initialImageUrls.length === 1 ? { imageUrl: initialImageUrls[0] } : {}),
				...(initialImageUrls.length > 1 ? { imageUrls: initialImageUrls } : {}),
				currentLiveObj: workingLiveObj,
				plan,
				part,
				model,
				useProcedural,
				apiKey: providerSettings.apiKey?.trim() || undefined,
				apiUrl: providerSettings.apiUrl?.trim() || undefined
			})
		});
		const payload = (await appendRes.json().catch(() => ({}))) as IterativeAppendPayload;
		if (!appendRes.ok || !payload.liveObj) {
			const validationErrors = payload.validation?.errors?.join('; ');
			throw new Error(
				validationErrors || payload.message || appendRes.statusText || `Part ${partNumber} failed`
			);
		}
		clearThinkingMessage();
		return payload;
	}

	async function runIterativeSceneGeneration(args: {
		text: string;
		initialImageUrls: string[];
		model: string;
		useProcedural: boolean;
		baseLiveObj?: string;
		partFeedback?: boolean;
		signal?: AbortSignal;
	}) {
		const {
			text,
			initialImageUrls,
			model,
			useProcedural,
			baseLiveObj = '',
			partFeedback = false,
			signal
		} = args;
		throwIfAborted(signal);
		let accumulatedUsage: TokenUsageSummary | undefined;
		const appendToCurrentScene = Boolean(baseLiveObj.trim());
		let workingLiveObj = appendToCurrentScene
			? baseLiveObj.trim()
			: emptyIterativeLiveObj(useProcedural);
		let combinedRaw = '';
		if (!appendToCurrentScene) {
			planCameraDirection = undefined;
			planCameraFocus = [];
		}

		iterativeGenerationActive = true;
		try {
			const planStartedAt = performance.now();
			statusLine = appendToCurrentScene ? 'Planning additions.' : 'Planning scene parts.';
			appendProgressMessage(
				appendToCurrentScene
					? 'Planning additions as separate buildable parts...'
					: 'Planning the scene as separate buildable parts...'
			);
			showThinkingMessage(
				appendToCurrentScene ? 'Thinking through additions...' : 'Thinking through scene parts...'
			);
			const planPayload = await requestIterativePlanWithStreaming({
				text,
				initialImageUrls,
				model,
				useProcedural,
				currentLiveObj: appendToCurrentScene ? workingLiveObj : '',
				signal
			});
			clearThinkingMessage();

			const plan = planPayload.plan;
			applyPlanVisualSettings(plan);
			workingLiveObj = applyPlanMaterialsToHeader(workingLiveObj, plan);
			liveObjText = workingLiveObj;
			accumulatedUsage = mergeTokenUsage(accumulatedUsage, planPayload.llmUsage);
			combinedRaw = String(planPayload.rawLlm ?? '');
			rawLlmText = combinedRaw;
			const partCount = plan.parts.length;
			appendProgressMessage(
				`Plan ready: ${partCount} part${partCount === 1 ? '' : 's'}.`,
				`time ${formatDuration(performance.now() - planStartedAt)}`
			);
			appendProgressMessage(planPartsMessage(plan));

			for (const [index, part] of plan.parts.entries()) {
				throwIfAborted(signal);
				const label = partLabel(part, index);
				const partStartedAt = performance.now();
				statusLine = `Building part ${index + 1}/${partCount}: ${label}.`;
				appendProgressMessage(`Building ${index + 1}/${partCount}: ${label}.`);
				const appendPayload = useProcedural
					? await appendPartWithoutStreaming({
							text,
							initialImageUrls,
							workingLiveObj,
							plan,
							part,
							model,
							useProcedural,
							partNumber: index + 1,
							signal
						})
					: await appendPartWithStreamingPreview({
							text,
							initialImageUrls,
							workingLiveObj,
							plan,
							part,
							model,
							label,
							signal
						}).catch(async (streamError) => {
							if (isAbortError(streamError)) throw streamError;
							tryApplyObjString(executedObjText || workingLiveObj, workingLiveObj);
							appendProgressMessage(
								`Streaming preview for ${label} failed; retrying with stable append.`,
								streamError instanceof Error ? streamError.message : String(streamError)
							);
							return appendPartWithoutStreaming({
								text,
								initialImageUrls,
								workingLiveObj,
								plan,
								part,
								model,
								useProcedural,
								partNumber: index + 1,
								signal
							});
						});
				if (!appendPayload.liveObj) throw new Error(`Part ${index + 1} failed`);
				if (appendPayload.validation && !appendPayload.validation.valid) {
					throw new Error(
						appendPayload.validation.errors.join('; ') || `Part ${index + 1} failed validation`
					);
				}

				workingLiveObj = String(appendPayload.liveObj);
				liveObjText = workingLiveObj;
				currentSceneMode = useProcedural ? 'live_obj' : 'raw_obj';
				executedObjText = displayObjForSource(
					workingLiveObj,
					String(appendPayload.executedObj ?? appendPayload.liveObj ?? '')
				);
				combinedRaw = [
					combinedRaw,
					`# --- part ${index + 1}: ${label} ---`,
					String(appendPayload.rawLlm ?? '')
				]
					.filter((chunk) => chunk.trim())
					.join('\n\n');
				rawLlmText = combinedRaw;
				sourceTab = 'executed';
				sceneEpoch += 1;
				applyObjString(executedObjText || workingLiveObj, workingLiveObj);
				await waitForSceneCaptureFrame();
				const focusObjectIds = cameraFocusForPart(part);
				const xrayFocusObjectIds = appendPayload.validation?.addedObjectNames?.length
					? appendPayload.validation.addedObjectNames
					: [part.id];
				const xraySupportObjectIds = focusObjectIds.filter(
					(objectId) => !xrayFocusObjectIds.includes(objectId)
				);
				canvasRef?.frameScene?.(1.05, planCameraDirection, focusObjectIds);
				const partScreenshot = await appendBuiltPartScreenshot(
					label,
					index + 1,
					partCount,
					focusObjectIds,
					xrayFocusObjectIds,
					xraySupportObjectIds
				);
				accumulatedUsage = mergeTokenUsage(accumulatedUsage, appendPayload.llmUsage);

				const warnings = [
					...(appendPayload.validation?.warnings ?? []),
					...(appendPayload.executorWarnings ?? [])
				].filter(Boolean);
				if (warnings.length > 0) statusLine = `Part ${index + 1}/${partCount}: ${warnings[0]}`;
				appendProgressMessage(
					`Added ${label}.`,
					`time ${formatDuration(performance.now() - partStartedAt)}`
				);
				if (partFeedback) {
					await runPartFeedbackPass({
						text,
						initialImageUrls,
						useProcedural,
						part,
						label,
						partNumber: index + 1,
						partCount,
						screenshot: partScreenshot,
						signal
					});
					workingLiveObj = liveObjText.trim() || workingLiveObj;
					executedObjText = executedObjText || workingLiveObj;
					combinedRaw = rawLlmText || combinedRaw;
				}
				await runPlannedPartPostProcess({
					text,
					part,
					addedObjectNames: appendPayload.validation?.addedObjectNames ?? [],
					label,
					signal
				});
				workingLiveObj = liveObjText.trim() || workingLiveObj;
				executedObjText = executedObjText || workingLiveObj;
				throwIfAborted(signal);
				await shortDelay(650);
			}

			statusLine = null;
			const names = objectNamesFromLiveObj(workingLiveObj);
			msgs = [
				...msgs,
				{
					role: 'assistant',
					content: appendToCurrentScene
						? `Added ${partCount} part${partCount === 1 ? '' : 's'} to the scene: ${summarizeObjectNames(names)}.`
						: `Built the scene in ${partCount} part${partCount === 1 ? '' : 's'}: ${summarizeObjectNames(names)}.`,
					historyContent: workingLiveObj,
					...(accumulatedUsage ? { tokenUsage: accumulatedUsage } : {})
				}
			];
			appendMetadataImageMessages(workingLiveObj);
		} finally {
			clearThinkingMessage();
			iterativeGenerationActive = false;
		}
	}

	async function requestSceneUpdateTurn(args: {
		text: string;
		useProcedural: boolean;
		targetObjectId?: string;
		imageDataUrl?: string;
		imageDataUrls?: string[];
		priorMsgs: ChatMsg[];
		includeHistoryImages?: boolean;
		forceCurrentScene?: boolean;
		signal?: AbortSignal;
	}) {
		const {
			text,
			useProcedural,
			targetObjectId,
			imageDataUrl,
			imageDataUrls = [],
			priorMsgs,
			includeHistoryImages = true,
			forceCurrentScene = false,
			signal
		} = args;
		throwIfAborted(signal);
		const requestImageUrls = [
			...new Set(
				[...imageDataUrls, ...(imageDataUrl ? [imageDataUrl] : [])]
					.map((url) => url.trim())
					.filter(Boolean)
			)
		];
		const modelProvider = providerSettings.provider;
		const model = providerSettings.textModel?.trim() || 'gpt-5.5';
		const history = buildChatHistory(priorMsgs, includeHistoryImages);
		const latestHistoryContent = [...priorMsgs]
			.reverse()
			.find((m) => m.role === 'assistant' && (m.historyContent ?? '').trim())?.historyContent;
		const isIterativeEdit = forceCurrentScene || Boolean(latestHistoryContent?.trim());
		const currentLiveObj = liveObjText.trim();
		const previousLiveObj = currentLiveObj;
		const previousSceneMode = currentSceneMode;
		if (
			isIterativeEdit &&
			currentLiveObj &&
			currentLiveObj !== (latestHistoryContent ?? '').trim()
		) {
			history.push({ role: 'assistant', content: modelHistoryContent(currentLiveObj) });
		}

		showThinkingMessage(
			isIterativeEdit ? 'Thinking about the edit...' : 'Thinking about the scene...'
		);
		const res = await fetch('/api/live-obj', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			signal,
			body: JSON.stringify({
				userMessage: text,
				...(requestImageUrls.length === 1 ? { imageUrl: requestImageUrls[0] } : {}),
				...(requestImageUrls.length > 1 ? { imageUrls: requestImageUrls } : {}),
				history,
				model,
				provider: modelProvider,
				apiKey: providerSettings.apiKey?.trim() || undefined,
				apiUrl: providerSettings.apiUrl?.trim() || undefined,
				useProcedural,
				...(targetObjectId ? { targetObjectId } : {}),
				...(isIterativeEdit
					? { currentLiveObj, isIterativeEdit, currentSceneMode: previousSceneMode }
					: {}),
				kernelDefault
			})
		});
		const payload = (await res.json().catch(() => ({}))) as LiveObjApiPayload;
		throwIfAborted(signal);
		if (!res.ok) throw new Error(payload.message || res.statusText || 'Request failed');
		clearThinkingMessage();
		recordRenderModelUsage('Scene generation', modelProvider, model);

		liveObjText = String(payload.liveObj ?? '');
		currentSceneMode = useProcedural ? 'live_obj' : 'raw_obj';
		rawLlmText = String(payload.rawLlm ?? '');
		executedObjText = displayObjForSource(
			liveObjText,
			typeof payload.executedObj === 'string'
				? payload.executedObj
				: String(payload.executedObj ?? '')
		);
		applyObjString(executedObjText || liveObjText, liveObjText || executedObjText);
		sourceTab = 'executed';
		sceneEpoch += 1;

		if (payload.executorWarning) {
			statusLine = `Executor: ${payload.executorWarning}`;
		}
		const assistantMessage = summarizeAssistantResult({
			promptText: text,
			previousLiveObj,
			nextLiveObj: String(payload.liveObj ?? payload.executedObj ?? ''),
			rawLlm: String(payload.rawLlm ?? ''),
			isIterativeEdit,
			editMode: payload.editMode,
			surgicalEditSummary: payload.surgicalEditSummary
		});

		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: payload.executorWarning
					? 'Received model output. Executor had issues; check status and the Adjust tab.'
					: payload.assistantMessage?.trim() || assistantMessage,
				historyContent: payload.liveObj ?? payload.executedObj ?? '',
				...(payload.llmUsage ? { tokenUsage: payload.llmUsage } : {})
			}
		];
		appendMetadataImageMessages(String(payload.liveObj ?? payload.executedObj ?? ''));
	}

	async function sendPrompt(payload: SendPromptPayload) {
		const { text, useProcedural = false, targetObjectId, imageDataUrl } = payload;
		const initialImageUrls = [
			...new Set(
				[...(payload.imageDataUrls ?? []), ...(imageDataUrl ? [imageDataUrl] : [])]
					.map((url) => url.trim())
					.filter(Boolean)
			)
		];
		const modelProvider = providerSettings.provider;
		const model = providerSettings.textModel?.trim() || 'gpt-5.5';
		const feedbackPasses = payload.feedbackLoop ? 1 : 0;
		if ((!text.trim() && initialImageUrls.length === 0) || busy) return;

		// Validate API key and model before generation
		if (!providerSettings.apiKey?.trim() && !providerSettings.textModel?.trim()) {
			statusLine = 'Please provide an API key and select a provider';
			return;
		}

		statusLine = null;
		busy = true;
		const generationAbortController = new AbortController();
		activeGenerationAbortController = generationAbortController;
		const { signal } = generationAbortController;

		const priorMsgs = [...msgs];
		const userLine: ChatMsg = {
			role: 'user',
			content: text,
			...(imageDataUrl ? { imageDataUrl } : {})
		};
		msgs = [...priorMsgs, userLine];
		const history = buildChatHistory(priorMsgs);
		const latestHistoryContent = [...priorMsgs]
			.reverse()
			.find((m) => m.role === 'assistant' && (m.historyContent ?? '').trim())?.historyContent;
		const isIterativeEdit = Boolean(latestHistoryContent?.trim());
		const currentLiveObj = liveObjText.trim();
		const previousLiveObj = currentLiveObj;
		const previousSceneMode = currentSceneMode;
		let usedIterativeGeneration = false;
		if (!isIterativeEdit) projectProcessImages = [];
		if (
			isIterativeEdit &&
			currentLiveObj &&
			currentLiveObj !== (latestHistoryContent ?? '').trim()
		) {
			history.push({ role: 'assistant', content: modelHistoryContent(currentLiveObj) });
		}

		try {
			if (currentLiveObj && looksLikeUvDreamRequest(text)) {
				const uvTargetObjectId = targetObjectId || targetObjectIdFromDreamPrompt(text);
				if (!uvTargetObjectId) {
					throw new Error(
						'UV dream enhancement needs a target object. Select one in the target dropdown or include `object <id>` in the prompt.'
					);
				}
				await runUvDreamEnhanceTurn({
					text,
					targetObjectId: uvTargetObjectId,
					signal
				});
				return;
			}

			if (currentLiveObj && looksLikeDreamRebuildRequest(text)) {
				const dreamTargetObjectId = targetObjectId || targetObjectIdFromDreamPrompt(text);
				if (!dreamTargetObjectId) {
					throw new Error(
						'Dream rebuild needs a target object. Select one in the target dropdown or include `object <id>` in the prompt.'
					);
				}
				await runDreamRebuildTurn({
					text,
					targetObjectId: dreamTargetObjectId,
					signal
				});
				return;
			}

			if (
				shouldUseIterativeGeneration({
					text,
					useProcedural,
					isIterativeEdit,
					hasImages: initialImageUrls.length > 0
				})
			) {
				usedIterativeGeneration = true;
				await runIterativeSceneGeneration({
					text,
					initialImageUrls,
					model,
					useProcedural,
					baseLiveObj: isIterativeEdit ? currentLiveObj : '',
					partFeedback: feedbackPasses > 0,
					signal
				});
				recordRenderModelUsage('Scene generation', modelProvider, model);
				await captureFinalRenderGalleryFrames();
			} else {
				appendProgressMessage(
					isIterativeEdit
						? 'Applying a surgical edit to the current scene...'
						: 'Generating the scene in one model pass...'
				);
				const generationStartedAt = performance.now();
				showThinkingMessage(
					isIterativeEdit ? 'Thinking about the edit...' : 'Thinking about the scene...'
				);
				const res = await fetch('/api/live-obj', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					signal,
					body: JSON.stringify({
						userMessage: text,
						...(initialImageUrls.length === 1 ? { imageUrl: initialImageUrls[0] } : {}),
						...(initialImageUrls.length > 1 ? { imageUrls: initialImageUrls } : {}),
						history,
						model,
						provider: modelProvider,
						apiKey: providerSettings.apiKey?.trim() || undefined,
						apiUrl: providerSettings.apiUrl?.trim() || undefined,
						useProcedural,
						...(targetObjectId ? { targetObjectId } : {}),
						...(isIterativeEdit
							? { currentLiveObj, isIterativeEdit, currentSceneMode: previousSceneMode }
							: {}),
						kernelDefault
					})
				});
				const payload = (await res.json().catch(() => ({}))) as LiveObjApiPayload;
				throwIfAborted(signal);
				if (!res.ok) throw new Error(payload.message || res.statusText || 'Request failed');
				clearThinkingMessage();
				recordRenderModelUsage('Scene generation', modelProvider, model);

				liveObjText = String(payload.liveObj ?? '');
				currentSceneMode = useProcedural ? 'live_obj' : 'raw_obj';
				rawLlmText = String(payload.rawLlm ?? '');
				executedObjText = displayObjForSource(
					liveObjText,
					typeof payload.executedObj === 'string'
						? payload.executedObj
						: String(payload.executedObj ?? '')
				);
				applyObjString(executedObjText || liveObjText, liveObjText || executedObjText);
				sourceTab = 'executed';
				sceneEpoch += 1;

				if (payload.executorWarning) {
					statusLine = `Executor: ${payload.executorWarning}`;
				}
				const assistantMessage = summarizeAssistantResult({
					promptText: text,
					previousLiveObj,
					nextLiveObj: String(payload.liveObj ?? payload.executedObj ?? ''),
					rawLlm: String(payload.rawLlm ?? ''),
					isIterativeEdit,
					editMode: payload.editMode,
					surgicalEditSummary: payload.surgicalEditSummary
				});

				msgs = [
					...msgs,
					{
						role: 'assistant',
						content: payload.executorWarning
							? 'Received model output. Executor had issues; check status and the Adjust tab.'
							: payload.assistantMessage?.trim() || assistantMessage,
						historyContent: payload.liveObj ?? payload.executedObj ?? '',
						...(payload.llmUsage ? { tokenUsage: payload.llmUsage } : {})
					}
				];
				appendMetadataImageMessages(String(payload.liveObj ?? payload.executedObj ?? ''));
				appendProgressMessage(
					'Model pass finished.',
					`time ${formatDuration(performance.now() - generationStartedAt)}`
				);
			}

			feedbackLoopActive = feedbackPasses > 0 && !usedIterativeGeneration;
			for (let pass = 1; !usedIterativeGeneration && pass <= feedbackPasses; pass += 1) {
				throwIfAborted(signal);
				const feedbackStartedAt = performance.now();
				statusLine = `Feedback loop ${pass}/${feedbackPasses}: capturing rendered scene.`;
				await waitForSceneCaptureFrame();
				const screenshot = captureFeedbackScreenshot();
				if (!screenshot) {
					statusLine = 'Feedback loop stopped: unable to capture rendered scene screenshot.';
					break;
				}

				const screenshotLine: ChatMsg = {
					role: 'user',
					content: `Feedback loop ${pass}/${feedbackPasses}: rendered scene screenshot.`,
					imageDataUrl: screenshot
				};
				const priorBeforeFeedback = [...msgs];
				msgs = [...msgs, screenshotLine];
				statusLine = `Feedback loop ${pass}/${feedbackPasses}: asking the model to refine the scene.`;
				await requestSceneUpdateTurn({
					text: feedbackPrompt(text, pass, feedbackPasses, initialImageUrls.length > 0),
					useProcedural,
					targetObjectId,
					imageDataUrls: [...initialImageUrls, screenshot],
					priorMsgs: priorBeforeFeedback,
					includeHistoryImages: false,
					signal
				});
				appendProgressMessage(
					`Feedback loop ${pass}/${feedbackPasses} finished.`,
					`time ${formatDuration(performance.now() - feedbackStartedAt)}`
				);
			}
			if (feedbackPasses > 0 && statusLine?.startsWith('Feedback loop')) {
				statusLine = null;
			}
			feedbackLoopActive = false;
		} catch (e) {
			clearThinkingMessage();
			if (isAbortError(e)) {
				statusLine = 'Generation stopped.';
				if (liveObjText.trim() || executedObjText.trim()) {
					tryApplyObjString(executedObjText || liveObjText, liveObjText || executedObjText);
				}
				msgs = [...msgs, { role: 'assistant', content: 'Generation stopped.' }];
				return;
			}
			const m = e instanceof Error ? e.message : String(e);
			statusLine = m;
			msgs = [...msgs, { role: 'assistant', content: `Error: ${m}` }];
		} finally {
			clearThinkingMessage();
			feedbackLoopActive = false;
			busy = false;
			if (activeGenerationAbortController === generationAbortController) {
				activeGenerationAbortController = null;
			}
		}
	}

	async function applyEditedSource(sceneText: string) {
		if (!sceneText.trim()) return;
		sourceApplyBusy = true;
		statusLine = null;
		try {
			await regenerateFromMetadata(sceneText);
		} finally {
			sourceApplyBusy = false;
		}
	}

	async function openLiveObj(sceneText: string) {
		const text = String(sceneText ?? '').trim();
		if (!text) return;
		const isProceduralLiveObj = hasProceduralLiveSources(text);
		const isRawCachedMesh =
			!isProceduralLiveObj && hasObjMeshGeometry(text) && !hasExecutableRawPostOps(text);
		const nextSource = isProceduralLiveObj ? `${text}\n` : normalizeRawPostHeader(text);
		currentSceneMode = isProceduralLiveObj ? 'live_obj' : 'raw_obj';
		rawLlmText = '';
		msgs = [
			...msgs,
			{
				role: 'assistant',
				content: 'Opened Live OBJ.',
				historyContent: nextSource
			}
		];
		if (isRawCachedMesh) {
			const resolved = applyDreamDisplacementControls(nextSource);
			liveObjText = resolved;
			executedObjText = resolved;
			sourceTab = 'executed';
			sceneEpoch += 1;
			statusLine = null;
			applyObjString(resolved, resolved);
			return;
		}
		await applyEditedSource(nextSource);
	}

	function captureSceneScreenshot(
		options:
			| string[]
			| {
					frameObjectIds?: string[];
					xrayFocusObjectIds?: string[];
					xraySupportObjectIds?: string[];
			  } = []
	) {
		const normalizedOptions = Array.isArray(options) ? { frameObjectIds: options } : options;
		return (
			canvasRef?.captureScreenshot({
				maxWidth: 1280,
				format: 'image/jpeg',
				quality: 0.9,
				focusObjectNames: normalizedOptions.frameObjectIds ?? [],
				xrayFocusObjectNames: normalizedOptions.xrayFocusObjectIds ?? [],
				xraySupportObjectNames: normalizedOptions.xraySupportObjectIds ?? []
			}) ?? ''
		);
	}

	function captureSceneCameraSnapshot() {
		return canvasRef?.captureCameraSnapshot() ?? null;
	}
</script>

<div class="app-root">
	<div
		class="canvas-layer"
		class:canvas-layer--fixed-aspect={canvasAspectRatio !== 'fill'}
		style={`--canvas-matte: ${backgroundColor};`}
	>
		<div
			class="canvas-frame"
			class:canvas-frame--fixed-aspect={canvasAspectRatio !== 'fill'}
			style={canvasFrameAspectRatio
				? `aspect-ratio: ${canvasFrameAspectRatio}; --canvas-aspect: ${canvasFrameAspectValue};`
				: ''}
		>
			<Canvas3D
				bind:this={canvasRef}
				className="app-canvas"
				{backgroundColor}
				{renderObject}
				{objectColor}
				renderMode={renderingMode}
				{outlineThickness}
				{outlineDepthSensitivity}
				{outlineNormalSensitivity}
				{toonSteps}
				{toonOutline}
				respectObjectMaterials={preserveObjMaterials}
				{showGrid}
				{showAxes}
				{ambientLightIntensity}
				{directionalLightIntensity}
				showWireframe={wireframe}
				{enableShadows}
				{fogEnabled}
				{fogNear}
				{fogFar}
				{fogColor}
				{cameraFov}
				{toneMappingExposure}
				autoFrameOnObjectChange={true}
			/>
			{#if (busy && !iterativeGenerationActive && !feedbackLoopActive) || sourceApplyBusy}
				<div class="canvas-loading-overlay" aria-live="polite" aria-busy="true">
					<div class="canvas-loading-spinner"></div>
				</div>
			{/if}
		</div>
	</div>

	<LiveObjSidePanel
		bind:showPanel
		{msgs}
		{busy}
		{statusLine}
		bind:sourceTab
		{liveObjText}
		{rawLlmText}
		{executedObjText}
		{sceneEpoch}
		{sourceApplyBusy}
		bind:backgroundColor
		bind:canvasAspectRatio
		bind:showGrid
		bind:showAxes
		bind:wireframe
		bind:renderingMode
		bind:outlineThickness
		bind:outlineDepthSensitivity
		bind:outlineNormalSensitivity
		bind:toonSteps
		bind:toonOutline
		bind:selectedTargetObjectId
		{targetObjectOptions}
		bind:objectColor
		bind:objectScale
		bind:objectPosX
		bind:objectPosY
		bind:objectPosZ
		bind:objectRotYDeg
		bind:ambientLightIntensity
		bind:directionalLightIntensity
		bind:enableShadows
		bind:fogEnabled
		bind:fogNear
		bind:fogFar
		bind:fogColor
		bind:cameraFov
		bind:toneMappingExposure
		onLiveObjMetadataChange={async (updatedText) => {
			sourceApplyBusy = true;
			statusLine = null;
			try {
				await regenerateFromMetadata(updatedText);
			} finally {
				sourceApplyBusy = false;
			}
		}}
		onApplyEditedSource={(text) => void applyEditedSource(text)}
		onOpenLiveObj={(text) => void openLiveObj(text)}
		bind:providerSettings
		onSend={(p) => void sendPrompt(p)}
		onStopGeneration={stopGeneration}
		onCaptureSceneScreenshot={captureSceneScreenshot}
		onCaptureSceneCameraSnapshot={captureSceneCameraSnapshot}
		onCaptureReelTurntableFrames={captureReelTurntableFrames}
		bind:renderFrameAssets
		bind:renderVideoShot
		bind:renderTurntableFrameAssets
		bind:renderModelUsage
		{projectProcessImages}
		onLaunchObjExample={launchObjExample}
		bind:kernelDefault
	/>
</div>

<style>
	.app-root {
		position: fixed;
		inset: 0;
		overflow: hidden;
	}
	.canvas-layer {
		position: absolute;
		inset: 0;
		z-index: 0;
	}
	.canvas-layer--fixed-aspect {
		display: grid;
		place-items: center;
		padding: 16px;
		background:
			linear-gradient(rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0.18)), var(--canvas-matte);
	}
	.canvas-frame {
		position: relative;
		width: 100%;
		height: 100%;
	}
	.canvas-frame--fixed-aspect {
		width: min(calc(100vw - 32px), calc((100vh - 32px) * var(--canvas-aspect)));
		height: auto;
		max-width: calc(100vw - 32px);
		max-height: calc(100vh - 32px);
		overflow: hidden;
		border: 1px solid var(--spell-border-soft);
		border-radius: var(--spell-radius-lg);
		background: var(--spell-surface-soft);
		box-shadow:
			0 34px 92px rgba(8, 8, 22, 0.2),
			0 12px 32px rgba(8, 8, 22, 0.12),
			0 1px 0 rgba(255, 255, 255, 0.72) inset;
	}
	:global(.app-canvas) {
		width: 100%;
		height: 100%;
	}
	:global(.app-canvas canvas) {
		border-radius: 0;
		box-shadow: none;
	}
	.canvas-frame--fixed-aspect :global(.app-canvas canvas) {
		border-radius: inherit;
	}
	.canvas-loading-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(255, 255, 255, 0.28);
		backdrop-filter: blur(1px);
		z-index: 2;
		pointer-events: none;
	}
	.canvas-loading-spinner {
		width: 36px;
		height: 36px;
		border: 3px solid rgba(15, 23, 42, 0.15);
		border-top-color: rgba(15, 23, 42, 0.82);
		border-radius: 999px;
		animation: canvasSpin 0.8s linear infinite;
	}
	@keyframes canvasSpin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
