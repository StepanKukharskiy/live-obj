<script lang="ts">
	import * as THREE from 'three';
	import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
	import Canvas3D from '$lib/components/Canvas3D.svelte';
	import LiveObjSidePanel from '$lib/components/live-obj/LiveObjSidePanel.svelte';
	import type { SourceTab } from '$lib/components/live-obj/LiveObjOutputTab.svelte';
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
	};

	type IterativePartSpec = {
		id: string;
		role?: string;
		prompt?: string;
		dependencies?: string[];
		method?: string;
		priority?: number;
		validationHints?: string[];
	};

	type IterativeScenePlan = {
		scene?: string;
		units?: string;
		up?: string;
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
		| { type: 'preview_line'; line: string }
		| ({ type: 'final' } & IterativeAppendPayload)
		| { type: 'error'; message?: string };

	let showPanel = $state(true);
	let msgs = $state<ChatMsg[]>([]);
	let busy = $state(false);
	let statusLine = $state<string | null>(null);
	let iterativeGenerationActive = $state(false);

	let sourceTab = $state<SourceTab>('executed');
	let liveObjText = $state(`#@live_obj_version: 0.1
o cube
#@source: procedural
#@type: box
#@params: center=[0,0,0], size=[1,1,1]
#@transform: rotation=[30,30,0]
`);
	let currentSceneMode = $state<'live_obj' | 'raw_obj'>('live_obj');
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

	let backgroundColor = $state('#e8ebf2');
	let showGrid = $state(true);
	let showAxes = $state(true);
	let ambientLightIntensity = $state(1);
	let directionalLightIntensity = $state(1.5);
	let wireframe = $state(false);
	let enableShadows = $state(false);
	let fogEnabled = $state(false);
	let fogNear = $state(10);
	let fogFar = $state(50);
	let fogColor = $state('#f8fafc');
	let cameraFov = $state(50);
	let toneMappingExposure = $state(1);

	let objectColor = $state('#0000eb');
	let objectScale = $state(1);
	let objectPosX = $state(0);
	let objectPosY = $state(0);
	let objectPosZ = $state(0);
	let objectRotYDeg = $state(0);
	let preserveObjMaterials = $state(false);
	let canvasRef = $state<Canvas3D | null>(null);

	function materialColorFromName(name: string): THREE.Color {
		let hash = 0;
		for (let i = 0; i < name.length; i += 1) {
			hash = (hash << 5) - hash + name.charCodeAt(i);
			hash |= 0;
		}
		const hue = ((hash % 360) + 360) % 360;
		return new THREE.Color().setHSL(hue / 360, 0.45, 0.56);
	}

	type MaterialPreset = {
		color?: string;
		metalness?: number;
		roughness?: number;
		shadeSmooth?: boolean;
	};

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
		const hasMetadataMaterialTags = materialTagsByObject.size > 0;
		const objectDefinitions = new Set(
			[...sourceTextForMetadata.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1])
		);
		const objectNameSet = new Set<string>();
		group.traverse((o: THREE.Object3D) => {
			if (o instanceof THREE.Mesh && o.name) objectNameSet.add(o.name);
		});
		const hasMultipleNamedObjects = Math.max(objectNameSet.size, objectDefinitions.size) > 1;
		preserveObjMaterials =
			hasPerObjectMaterials || hasMultipleNamedObjects || hasMetadataMaterialTags;
		const fallbackMat = new THREE.MeshStandardMaterial({
			color: objectColor,
			metalness: 0.12,
			roughness: 0.48,
			side: THREE.DoubleSide,
			flatShading: false,
			wireframe
		});
		group.traverse((o: THREE.Object3D) => {
			if (!(o instanceof THREE.Mesh)) return;
			if (!hasPerObjectMaterials && !hasMultipleNamedObjects && !hasMetadataMaterialTags) {
				o.material = fallbackMat;
				if (o.geometry) o.geometry.computeVertexNormals();
				return;
			}
			const materialToStandard = (material: THREE.Material): THREE.MeshStandardMaterial => {
				const base = material as THREE.MeshPhongMaterial & { name?: string };
				const taggedMaterial = o.name ? materialTagsByObject.get(o.name) : null;
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
				return new THREE.MeshStandardMaterial({
					color,
					metalness: preset?.metalness ?? 0.12,
					roughness: preset?.roughness ?? 0.48,
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
			if (wantsSmoothNormals && o.geometry) o.geometry.computeVertexNormals();
		});
		if (upAxis === 'z') group.rotation.x = -Math.PI / 2;
		else if (upAxis === 'x') group.rotation.z = Math.PI / 2;
		renderObject = group;
		applyObjectControls();
	}

	function countObjFaceLines(objText: string): number {
		return objText.split('\n').filter((line) => /^\s*f\s+/.test(line)).length;
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
		const text = String(updatedLiveObj ?? '');
		if (!text.trim()) return;
		statusLine = null;
		const hasLiveSources = hasProceduralLiveSources(text);
		const useRawPostExecutor = currentSceneMode === 'raw_obj' && !hasLiveSources;
		const sceneWithKernel = useRawPostExecutor ? normalizeRawPostHeader(text) : applyKernelDefaultHeader(text);
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
			liveObjText = String(payload.liveObj ?? payload.rawObj ?? sceneWithKernel);
			currentSceneMode = hasProceduralLiveSources(liveObjText)
				? 'live_obj'
				: currentSceneMode;
			executedObjText =
				typeof payload.executedObj === 'string'
					? payload.executedObj
					: String(payload.executedObj ?? '');
			sourceTab = 'executed';
			sceneEpoch += 1;
			if (payload.executedObj)
				applyObjString(
					typeof payload.executedObj === 'string'
						? payload.executedObj
						: String(payload.executedObj),
					String(payload.liveObj ?? sceneWithKernel)
				);
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
		textModel: 'gpt-5.5',
		imageModel: 'gpt-image-1.5',
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
			.map((m) => ({
				role: m.role,
				content: m.historyContent ?? m.content,
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
			const prompt = part.prompt?.trim() ? ` — ${part.prompt.trim()}` : '';
			return `${index + 1}. ${partLabel(part, index)}${method}${prompt}`;
		});
		return `Parts:\n${lines.join('\n')}`;
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

	function shouldUseIterativeGeneration(args: {
		text: string;
		useProcedural: boolean;
		isIterativeEdit: boolean;
		hasImages: boolean;
	}): boolean {
		if (!args.isIterativeEdit) return true;
		if (looksLikeTargetedEdit(args.text)) return false;
		return Boolean(args.text.trim() || args.hasImages);
	}

	async function waitForSceneCaptureFrame() {
		await tick();
		await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
		await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
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
			'Use both the screenshot and the current Live OBJ coordinates to find conflicts. The screenshot shows what is visible; the OBJ coordinates show whether objects overlap in 3D.',
			'Repair existing objects before adding any new detail. If glass intersects a roof/shell, move, trim, lower, narrow, or remove the glass panels instead of adding decorative elements.',
			'Patch only the specific named objects that need repair. Do not replace the whole scene or simplify successful parts.',
			'Do not add new decorative objects unless the current screenshot has no obvious geometry conflicts.',
			'Preserve successful object IDs and proportions. Return an updated OBJ scene.'
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
	}) {
		const { text, initialImageUrls, workingLiveObj, plan, part, model, label } = args;
		showThinkingMessage(`Thinking about ${label}...`);
		const res = await fetch('/api/live-obj/append-part/stream', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
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
		const flushPreview = (force = false) => {
			if (previewLines.length === 0) return;
			const now = performance.now();
			if (!force && faceLinesSincePreview < 4 && now - lastPreviewAt < 220) return;
			const previewObj = `${workingLiveObj.trimEnd()}\n${previewLines.join('\n')}\n`;
			if (countObjFaceLines(previewObj) <= baseFaceCount) return;
			if (!tryApplyObjString(previewObj, previewObj)) return;
			lastPreviewAt = now;
			faceLinesSincePreview = 0;
		};

		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			const lines = buffer.split(/\r?\n/);
			buffer = lines.pop() ?? '';
			for (const line of lines) {
				if (!line.trim()) continue;
				const event = JSON.parse(line) as IterativeAppendStreamEvent;
				if (event.type === 'preview_line') {
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
			if (event.type === 'final') {
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

	async function appendPartWithoutStreaming(args: {
		text: string;
		initialImageUrls: string[];
		workingLiveObj: string;
		plan: IterativeScenePlan;
		part: IterativePartSpec;
		model: string;
		useProcedural: boolean;
		partNumber: number;
	}) {
		const { text, initialImageUrls, workingLiveObj, plan, part, model, useProcedural, partNumber } =
			args;
		const label = partLabel(part, partNumber - 1);
		showThinkingMessage(`Thinking about ${label}...`);
		const appendRes = await fetch('/api/live-obj/append-part', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
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
	}) {
		const { text, initialImageUrls, model, useProcedural } = args;
		let accumulatedUsage: TokenUsageSummary | undefined;
		let workingLiveObj = emptyIterativeLiveObj(useProcedural);
		let combinedRaw = '';

		iterativeGenerationActive = true;
		try {
			const planStartedAt = performance.now();
			statusLine = 'Planning scene parts.';
			appendProgressMessage('Planning the scene as separate buildable parts...');
			showThinkingMessage('Thinking through scene parts...');
			const planRes = await fetch('/api/live-obj/plan', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					userMessage: text,
					...(initialImageUrls.length === 1 ? { imageUrl: initialImageUrls[0] } : {}),
					...(initialImageUrls.length > 1 ? { imageUrls: initialImageUrls } : {}),
					currentLiveObj: '',
					model,
					useProcedural,
					apiKey: providerSettings.apiKey?.trim() || undefined,
					apiUrl: providerSettings.apiUrl?.trim() || undefined
				})
			});
			const planPayload = (await planRes.json().catch(() => ({}))) as IterativePlanPayload;
			if (!planRes.ok || !planPayload.plan?.parts?.length) {
				throw new Error(planPayload.message || planRes.statusText || 'Part planning failed');
			}
			clearThinkingMessage();

			const plan = planPayload.plan;
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
							partNumber: index + 1
						})
					: await appendPartWithStreamingPreview({
							text,
							initialImageUrls,
							workingLiveObj,
							plan,
							part,
							model,
							label
						}).catch(async (streamError) => {
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
								partNumber: index + 1
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
				executedObjText = String(appendPayload.executedObj ?? appendPayload.liveObj ?? '');
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
				canvasRef?.frameScene?.(1.05);
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
				await shortDelay(650);
			}

			statusLine = null;
			const names = objectNamesFromLiveObj(workingLiveObj);
			msgs = [
				...msgs,
				{
					role: 'assistant',
					content: `Built the scene in ${partCount} part${partCount === 1 ? '' : 's'}: ${summarizeObjectNames(names)}.`,
					historyContent: workingLiveObj,
					...(accumulatedUsage ? { tokenUsage: accumulatedUsage } : {})
				}
			];
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
	}) {
		const {
			text,
			useProcedural,
			targetObjectId,
			imageDataUrl,
			imageDataUrls = [],
			priorMsgs,
			includeHistoryImages = true
		} = args;
		const requestImageUrls = [
			...new Set(
				[...imageDataUrls, ...(imageDataUrl ? [imageDataUrl] : [])]
					.map((url) => url.trim())
					.filter(Boolean)
			)
		];
		const model = providerSettings.textModel?.trim() || 'gpt-5.5';
		const history = buildChatHistory(priorMsgs, includeHistoryImages);
		const latestHistoryContent = [...priorMsgs]
			.reverse()
			.find((m) => m.role === 'assistant' && (m.historyContent ?? '').trim())?.historyContent;
		const isIterativeEdit = Boolean(latestHistoryContent?.trim());
		const currentLiveObj = liveObjText.trim();
		const previousLiveObj = currentLiveObj;
		const previousSceneMode = currentSceneMode;
		if (
			isIterativeEdit &&
			currentLiveObj &&
			currentLiveObj !== (latestHistoryContent ?? '').trim()
		) {
			history.push({ role: 'assistant', content: currentLiveObj });
		}

		showThinkingMessage(
			isIterativeEdit ? 'Thinking about the edit...' : 'Thinking about the scene...'
		);
		const res = await fetch('/api/live-obj', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				userMessage: text,
				...(requestImageUrls.length === 1 ? { imageUrl: requestImageUrls[0] } : {}),
				...(requestImageUrls.length > 1 ? { imageUrls: requestImageUrls } : {}),
				history,
				model,
				provider: providerSettings.provider,
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
		if (!res.ok) throw new Error(payload.message || res.statusText || 'Request failed');
		clearThinkingMessage();

		liveObjText = String(payload.liveObj ?? '');
		currentSceneMode = useProcedural ? 'live_obj' : 'raw_obj';
		rawLlmText = String(payload.rawLlm ?? '');
		executedObjText =
			typeof payload.executedObj === 'string'
				? payload.executedObj
				: String(payload.executedObj ?? '');
		if (payload.executedObj)
			applyObjString(
				typeof payload.executedObj === 'string'
					? payload.executedObj
					: String(payload.liveObj ?? payload.executedObj)
			);
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
		const model = providerSettings.textModel?.trim() || 'gpt-5.5';
		const feedbackPasses = payload.feedbackLoop
			? Math.max(1, Math.min(5, Math.round(payload.feedbackPasses ?? 3)))
			: 0;
		if ((!text.trim() && initialImageUrls.length === 0) || busy) return;

		// Validate API key and model before generation
		if (!providerSettings.apiKey?.trim() && !providerSettings.textModel?.trim()) {
			statusLine = 'Please provide an API key and select a provider';
			return;
		}

		statusLine = null;
		busy = true;

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
		if (
			isIterativeEdit &&
			currentLiveObj &&
			currentLiveObj !== (latestHistoryContent ?? '').trim()
		) {
			history.push({ role: 'assistant', content: currentLiveObj });
		}

		try {
			if (
				shouldUseIterativeGeneration({
					text,
					useProcedural,
					isIterativeEdit,
					hasImages: initialImageUrls.length > 0
				})
			) {
				await runIterativeSceneGeneration({ text, initialImageUrls, model, useProcedural });
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
					body: JSON.stringify({
						userMessage: text,
						...(initialImageUrls.length === 1 ? { imageUrl: initialImageUrls[0] } : {}),
						...(initialImageUrls.length > 1 ? { imageUrls: initialImageUrls } : {}),
						history,
						model,
						provider: providerSettings.provider,
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
				if (!res.ok) throw new Error(payload.message || res.statusText || 'Request failed');
				clearThinkingMessage();

				liveObjText = String(payload.liveObj ?? '');
				currentSceneMode = useProcedural ? 'live_obj' : 'raw_obj';
				rawLlmText = String(payload.rawLlm ?? '');
				executedObjText =
					typeof payload.executedObj === 'string'
						? payload.executedObj
						: String(payload.executedObj ?? '');
				if (payload.executedObj)
					applyObjString(
						typeof payload.executedObj === 'string'
							? payload.executedObj
							: String(payload.executedObj),
						String(payload.liveObj ?? payload.executedObj)
					);
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
				appendProgressMessage(
					'Model pass finished.',
					`time ${formatDuration(performance.now() - generationStartedAt)}`
				);
			}

			for (let pass = 1; pass <= feedbackPasses; pass += 1) {
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
					includeHistoryImages: false
				});
				appendProgressMessage(
					`Feedback loop ${pass}/${feedbackPasses} finished.`,
					`time ${formatDuration(performance.now() - feedbackStartedAt)}`
				);
			}
			if (feedbackPasses > 0 && statusLine?.startsWith('Feedback loop')) {
				statusLine = null;
			}
		} catch (e) {
			clearThinkingMessage();
			const m = e instanceof Error ? e.message : String(e);
			statusLine = m;
			msgs = [...msgs, { role: 'assistant', content: `Error: ${m}` }];
		} finally {
			clearThinkingMessage();
			busy = false;
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
		await applyEditedSource(nextSource);
	}

	function captureSceneScreenshot() {
		return (
			canvasRef?.captureScreenshot({
				maxWidth: 1280,
				format: 'image/jpeg',
				quality: 0.9
			}) ?? ''
		);
	}
</script>

<div class="app-root">
	<div class="canvas-layer">
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
		{#if (busy && !iterativeGenerationActive) || sourceApplyBusy}
			<div class="canvas-loading-overlay" aria-live="polite" aria-busy="true">
				<div class="canvas-loading-spinner"></div>
			</div>
		{/if}
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
		onCaptureSceneScreenshot={captureSceneScreenshot}
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
	:global(.app-canvas) {
		width: 100%;
		height: 100%;
	}
	:global(.app-canvas canvas) {
		border-radius: 0;
		box-shadow: none;
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
