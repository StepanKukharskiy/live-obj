<script lang="ts">
	import * as THREE from 'three';
	import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
	import Canvas3D from '$lib/components/Canvas3D.svelte';
	import LiveObjSidePanel from '$lib/components/live-obj/LiveObjSidePanel.svelte';
	import type { SourceTab } from '$lib/components/live-obj/LiveObjOutputTab.svelte';
	import { browser } from '$app/environment';
	import { onMount } from 'svelte';

	type ChatMsg = {
		role: 'user' | 'assistant';
		content: string;
		imageDataUrl?: string;
		historyContent?: string;
	};

	let showPanel = $state(true);
	let msgs = $state<ChatMsg[]>([]);
	let busy = $state(false);
	let statusLine = $state<string | null>(null);

	let sourceTab = $state<SourceTab>('executed');
	let liveObjText = $state(`#@live_obj_version: 0.1
o cube
#@source: procedural
#@type: box
#@params: center=[0,0,0], size=[1,1,1]
#@transform: rotation=[30,30,0]
`);
	let currentSceneMode = $state<'live_obj' | 'raw_obj'>('live_obj');
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
	};

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
			presets.set(name, preset);
		}
		return presets;
	}

	function parseObjectMaterialTags(sourceText: string): Map<string, string> {
		const byObject = new Map<string, string>();
		let currentObject: string | null = null;
		for (const line of sourceText.split(/\r?\n/)) {
			const objectMatch = line.match(/^\s*o\s+([^\s#]+)/);
			if (objectMatch) {
				currentObject = objectMatch[1];
				continue;
			}
			if (!currentObject) continue;
			const opListMaterialMatch = line.match(
				/^\s*#@\s*-\s*material\s+name=([a-zA-Z0-9_\-.]+)\s*$/
			);
			if (opListMaterialMatch) {
				byObject.set(currentObject, opListMaterialMatch[1]);
				continue;
			}
			const inlineMaterialMatch = line.match(
				/^\s*#@material:\s*(?:name=)?([a-zA-Z0-9_\-.]+)\s*$/
			);
			if (inlineMaterialMatch) byObject.set(currentObject, inlineMaterialMatch[1]);
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
		if (/\b(bigger|smaller|scale|resize|move|rotate|reposition|color|material|detail|adjust|change|modify|update|edit)\b/.test(lower)) return 'Adjusted';
		return 'Updated';
	}

	const SUMMARY_STOP_WORDS = new Set([
		'add', 'insert', 'create', 'make', 'put', 'include', 'attach',
		'remove', 'delete', 'erase', 'drop', 'hide',
		'bigger', 'smaller', 'scale', 'resize', 'move', 'rotate', 'reposition',
		'color', 'material', 'detail', 'detailed', 'adjust', 'change', 'modify', 'update', 'edit',
		'the', 'and', 'with', 'nearby', 'next', 'from', 'into', 'more', 'less', 'can', 'you',
		'please', 'part', 'parts', 'scene', 'object', 'objects', 'robot', 'droid'
	]);

	function promptSummaryTerms(promptText: string): string[] {
		return [...new Set(promptText.toLowerCase().match(/[a-z0-9]+/g) ?? [])]
			.filter((term) => term.length > 2 && !SUMMARY_STOP_WORDS.has(term));
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
		const cleaned = rawPatch.replace(/^```[a-z]*\n?/i, '').replace(/\n?```$/i, '').trim();
		const candidates = [cleaned];
		const start = cleaned.indexOf('{');
		const end = cleaned.lastIndexOf('}');
		if (start >= 0 && end > start) candidates.push(cleaned.slice(start, end + 1));
		for (const candidate of candidates) {
			try {
				const parsed = JSON.parse(candidate) as { edits?: unknown };
				if (!Array.isArray(parsed.edits)) continue;
				return parsed.edits
					.filter((edit): edit is { find: string; replace: string } => {
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

	function patchTouchedObjectNames(rawPatch: string, previousLiveObj: string, nextLiveObj: string): string[] {
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
			return sceneParts
				? `Created scene with ${sceneParts}.`
				: 'Created scene from prompt.';
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

		if (promptMatchedAdded.length > 0) return `${verb} ${summarizeObjectNames(promptMatchedAdded)}.`;
		if (added.length > 0) return `${verb} ${summarizeObjectNames(added)}.`;
		if (removed.length > 0) return `${verb} ${summarizeObjectNames(removed)}.`;
		if (promptMatchedTouched.length > 0) return `${verb} ${summarizeObjectNames(promptMatchedTouched)}.`;
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
		preserveObjMaterials = hasPerObjectMaterials || hasMultipleNamedObjects || hasMetadataMaterialTags;
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
				return;
			}
			const materialToStandard = (material: THREE.Material): THREE.MeshStandardMaterial => {
				const base = material as THREE.MeshPhongMaterial & { name?: string };
				const taggedMaterial = o.name ? materialTagsByObject.get(o.name) : null;
				const colorName = hasPerObjectMaterials ? base.name : o.name;
				const taggedPreset = taggedMaterial ? materialPresets.get(taggedMaterial) : undefined;
				const colorValue = taggedPreset?.color;
				const color = colorValue
					? new THREE.Color(colorValue)
					: colorName
						? materialColorFromName(colorName)
						: new THREE.Color(objectColor);
				return new THREE.MeshStandardMaterial({
					color,
					metalness: taggedPreset?.metalness ?? 0.12,
					roughness: taggedPreset?.roughness ?? 0.48,
					side: THREE.DoubleSide,
					flatShading: false,
					wireframe
				});
			};
			if (Array.isArray(o.material)) {
				o.material = o.material.map((material) => materialToStandard(material));
				return;
			}
			o.material = materialToStandard(o.material);
		});
		if (upAxis === 'z') group.rotation.x = -Math.PI / 2;
		else if (upAxis === 'x') group.rotation.z = Math.PI / 2;
		renderObject = group;
		applyObjectControls();
	}


	async function regenerateFromMetadata(updatedLiveObj: string) {
		const text = String(updatedLiveObj ?? '');
		if (!text.trim()) return;
		statusLine = null;
		const sceneWithKernel = applyKernelDefaultHeader(text);
		try {
			const res = await fetch('/api/live-obj/execute', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ liveObj: sceneWithKernel })
			});
			const payload = await res.json();
			if (!res.ok) throw new Error(payload.detail || payload.message || res.statusText || 'Metadata regeneration failed');
			liveObjText = String(payload.liveObj ?? sceneWithKernel);
			currentSceneMode = /#@source:\s*(procedural|assembly|sdf|simulation)/i.test(liveObjText) ? 'live_obj' : currentSceneMode;
			executedObjText = typeof payload.executedObj === 'string' ? payload.executedObj : String(payload.executedObj ?? '');
			sourceTab = 'executed';
			sceneEpoch += 1;
			if (payload.executedObj) applyObjString(typeof payload.executedObj === 'string' ? payload.executedObj : String(payload.executedObj), String(payload.liveObj ?? sceneWithKernel));
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
	let providerSettings = $state({ provider: 'openai', apiKey: '', apiUrl: 'https://api.openai.com/v1/chat/completions', imageUrl: 'https://api.openai.com/v1/images/edits', textModel: 'gpt-5.5', imageModel: 'gpt-image-1.5', rememberMe: false });
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
		if (!browser) return;
		if (providerSettings.rememberMe) {
			localStorage.setItem(PROVIDER_SETTINGS_KEY, JSON.stringify(providerSettings));
		} else {
			localStorage.removeItem(PROVIDER_SETTINGS_KEY);
		}
	});

	async function sendPrompt(payload: { text: string; useProcedural?: boolean; imageDataUrl?: string }) {
		const { text, useProcedural = true, imageDataUrl } = payload;
		const model = providerSettings.textModel?.trim() || 'gpt-5.5';
		if ((!text.trim() && !imageDataUrl) || busy) return;

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
		const history = priorMsgs.map((m) => ({
			role: m.role,
			content: m.historyContent ?? m.content,
			...(m.imageDataUrl ? { imageUrl: m.imageDataUrl } : {})
		}));
		const latestHistoryContent = [...priorMsgs]
			.reverse()
			.find((m) => m.role === 'assistant' && (m.historyContent ?? '').trim())?.historyContent;
		const isIterativeEdit = Boolean(latestHistoryContent?.trim());
		const currentLiveObj = liveObjText.trim();
		const previousLiveObj = currentLiveObj;
		const previousSceneMode = currentSceneMode;
		if (isIterativeEdit && currentLiveObj && currentLiveObj !== (latestHistoryContent ?? '').trim()) {
			history.push({ role: 'assistant', content: currentLiveObj });
		}

		try {
			const res = await fetch('/api/live-obj', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					userMessage: text,
					...(imageDataUrl ? { imageUrl: imageDataUrl } : {}),
					history,
					model,
					provider: providerSettings.provider,
					apiKey: providerSettings.apiKey?.trim() || undefined,
					apiUrl: providerSettings.apiUrl?.trim() || undefined,
					useProcedural,
					...(isIterativeEdit ? { currentLiveObj, isIterativeEdit, currentSceneMode: previousSceneMode } : {}),
					kernelDefault
				})
			});
			const payload = (await res.json().catch(() => ({}))) as {
				message?: string;
				liveObj?: string;
				rawLlm?: string;
				executedObj?: string;
				executorWarning?: string;
				editMode?: 'surgical' | 'rewrite';
				surgicalEditSummary?: string;
				assistantMessage?: string;
			};
			if (!res.ok) throw new Error(payload.message || res.statusText || 'Request failed');

			liveObjText = String(payload.liveObj ?? '');
			currentSceneMode = useProcedural ? 'live_obj' : 'raw_obj';
			rawLlmText = String(payload.rawLlm ?? '');
			executedObjText = typeof payload.executedObj === 'string' ? payload.executedObj : String(payload.executedObj ?? '');
			if (payload.executedObj) applyObjString(typeof payload.executedObj === 'string' ? payload.executedObj : String(payload.executedObj), String(payload.liveObj ?? payload.executedObj));
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
					historyContent: payload.liveObj ?? payload.executedObj ?? ''
				}
			];
		} catch (e) {
			const m = e instanceof Error ? e.message : String(e);
			statusLine = m;
			msgs = [...msgs, { role: 'assistant', content: `Error: ${m}` }];
		} finally {
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
			outlineThickness={outlineThickness}
			outlineDepthSensitivity={outlineDepthSensitivity}
			outlineNormalSensitivity={outlineNormalSensitivity}
			toonSteps={toonSteps}
			toonOutline={toonOutline}
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
		/>
		{#if busy || sourceApplyBusy}
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
		to { transform: rotate(360deg); }
	}
</style>
