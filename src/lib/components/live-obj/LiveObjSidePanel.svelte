<script lang="ts">
	import '$lib/styles/planner-panel.css';
	import LiveObjChatTab from './LiveObjChatTab.svelte';
	import LiveObjAdjustTab from './LiveObjAdjustTab.svelte';
	import LiveObjToolsTab from './LiveObjToolsTab.svelte';
	import LiveObjSceneTab from './LiveObjSceneTab.svelte';
	import LiveObjRenderTab from './LiveObjRenderTab.svelte';
	import LiveObjProviderTab from './LiveObjProviderTab.svelte';
	import type { SourceTab } from './LiveObjOutputTab.svelte';

	type TokenUsageSummary = {
		promptTokens?: number;
		completionTokens?: number;
		totalTokens?: number;
		reasoningTokens?: number;
		cachedTokens?: number;
	};
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
	type SendPayload = {
		text: string;
		useProcedural?: boolean;
		targetObjectId?: string;
		imageDataUrl?: string;
		imageDataUrls?: string[];
		feedbackLoop?: boolean;
		feedbackPasses?: number;
	};
	type PanelTab = 'chat' | 'provider' | 'adjust' | 'tools' | 'scene' | 'render';
	type RenderingMode = 'standard' | 'outline' | 'toon';
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
	type AgentMetrics = {
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
	type CaptureSceneScreenshotOptions = {
		frameObjectIds?: string[];
		xrayFocusObjectIds?: string[];
		xraySupportObjectIds?: string[];
		viewDirection?: [number, number, number];
		autoFrame?: boolean;
		framePadding?: number;
	};

	let {
		showPanel = $bindable(true),
		msgs = [],
		busy = false,
		statusLine = null,
		sourceTab = $bindable<SourceTab>('executed'),
		liveObjText = '',
		rawLlmText = '',
		executedObjText = '',
		sceneEpoch = 0,
		sourceApplyBusy = false,
		backgroundColor = $bindable('#3a3a36'),
		canvasAspectRatio = $bindable<CanvasAspectRatio>('fill'),
		showGrid = $bindable(false),
		showAxes = $bindable(false),
		wireframe = $bindable(false),
		objectColor = $bindable('#e6e4dd'),
		objectScale = $bindable(1),
		objectPosX = $bindable(0),
		objectPosY = $bindable(0),
		objectPosZ = $bindable(0),
		objectRotYDeg = $bindable(0),
		ambientLightIntensity = $bindable(1),
		directionalLightIntensity = $bindable(1.5),
		enableShadows = $bindable(true),
		fogEnabled = $bindable(false),
		fogNear = $bindable(10),
		fogFar = $bindable(50),
		fogColor = $bindable('#f8fafc'),
		cameraFov = $bindable(50),
		toneMappingExposure = $bindable(1),
		renderingMode = $bindable<RenderingMode>('standard'),
		outlineThickness = $bindable(1),
		outlineDepthSensitivity = $bindable(1),
		outlineNormalSensitivity = $bindable(1),
		toonSteps = $bindable<2 | 3 | 4 | 5>(3),
		toonOutline = $bindable(true),
		selectedTargetObjectId = $bindable(''),
		targetObjectOptions = [],
		onLiveObjMetadataChange,
		onApplyEditedSource,
		providerSettings = $bindable({
			provider: 'openai',
			apiKey: '',
			apiUrl: 'https://api.openai.com/v1/chat/completions',
			imageUrl: 'https://api.openai.com/v1/images/edits',
			videoUrl: '',
			textModel: 'gpt-5.5',
			imageModel: 'gpt-image-1.5',
			videoModel: '',
			rememberMe: false
		}),
		onSend,
		onStopGeneration,
		onCaptureSceneScreenshot,
		onCaptureSceneCameraSnapshot,
		onCaptureReelTurntableFrames,
		renderFrameAssets = $bindable<FrameAsset[]>([]),
		renderVideoShot = $bindable<VideoShot>({ clips: [] }),
		renderTurntableFrameAssets = $bindable<FrameAsset[]>([]),
		renderModelUsage = $bindable<ModelUsage[]>([]),
		projectProcessImages = [],
		onLaunchObjExample,
		onOpenLiveObj,
		kernelDefault = $bindable<'auto' | 'cadquery'>('cadquery')
	}: {
		showPanel?: boolean;
		msgs?: ChatMsg[];
		busy?: boolean;
		statusLine?: string | null;
		sourceTab?: SourceTab;
		liveObjText?: string;
		rawLlmText?: string;
		executedObjText?: string;
		sceneEpoch?: number;
		sourceApplyBusy?: boolean;
		backgroundColor?: string;
		canvasAspectRatio?: CanvasAspectRatio;
		showGrid?: boolean;
		showAxes?: boolean;
		wireframe?: boolean;
		objectColor?: string;
		objectScale?: number;
		objectPosX?: number;
		objectPosY?: number;
		objectPosZ?: number;
		objectRotYDeg?: number;
		ambientLightIntensity?: number;
		directionalLightIntensity?: number;
		enableShadows?: boolean;
		fogEnabled?: boolean;
		fogNear?: number;
		fogFar?: number;
		fogColor?: string;
		cameraFov?: number;
		toneMappingExposure?: number;
		renderingMode?: RenderingMode;
		outlineThickness?: number;
		outlineDepthSensitivity?: number;
		outlineNormalSensitivity?: number;
		toonSteps?: 2 | 3 | 4 | 5;
		toonOutline?: boolean;
		selectedTargetObjectId?: string;
		targetObjectOptions?: string[];
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
		onApplyEditedSource?: (sceneText: string) => void | Promise<void>;
		providerSettings?: {
			provider: string;
			apiKey: string;
			apiUrl: string;
			imageUrl: string;
			videoUrl?: string;
			textModel: string;
			imageModel: string;
			videoModel?: string;
			rememberMe: boolean;
		};
		onSend?: (payload: SendPayload) => void;
		onStopGeneration?: () => void;
		onCaptureSceneScreenshot?: (options?: CaptureSceneScreenshotOptions | string[]) => string;
		onCaptureSceneCameraSnapshot?: () => CameraSnapshot;
		onCaptureReelTurntableFrames?: () => Promise<FrameAsset[]>;
		renderFrameAssets?: FrameAsset[];
		renderVideoShot?: VideoShot;
		renderTurntableFrameAssets?: FrameAsset[];
		renderModelUsage?: ModelUsage[];
		projectProcessImages?: ProcessImageAsset[];
		onLaunchObjExample?: (liveObj: string) => void;
		onOpenLiveObj?: (sourceText: string) => void | Promise<void>;
		kernelDefault?: 'auto' | 'cadquery';
	} = $props();

	let activeTab = $state<PanelTab>('chat');
	let chatInput = $state('');
	let chatFeedbackLoop = $state(false);
	let chatAttachedDataUrl = $state<string | undefined>(undefined);
	let renderPrompt = $state('');
	let renderScreenshotDataUrl = $state('');
	let renderGeneratedImageDataUrl = $state('');
	let renderVideoBusy = $state(false);
	let renderGeneratedDirectionJson = $state('');
	let renderBusy = $state(false);
	let renderErrorLine = $state<string | null>(null);

	function isTextureOrAtlasChatImage(message: ChatMsg): boolean {
		const text = `${message.meta ?? ''} ${message.content ?? ''}`.toLowerCase();
		return (
			text.includes('texture artifact') ||
			text.includes('uv debug artifact') ||
			text.includes('source uv unwrap') ||
			text.includes('generated uv height') ||
			text.includes('generated uv diffuse') ||
			text.includes('dream source sheet') ||
			text.includes('dream map sheet')
		);
	}

	function isBuildStepChatImage(message: ChatMsg): boolean {
		const text = `${message.meta ?? ''} ${message.content ?? ''}`.toLowerCase();
		return text.includes('x-ray scene screenshot') || /^built\s+\d+\/\d+:/i.test(message.content);
	}

	function isBuildStepProcessImage(asset: ProcessImageAsset): boolean {
		const text = `${asset.meta ?? ''} ${asset.label ?? ''}`.toLowerCase();
		return text.includes('build step screenshot') || /^build\s+\d+\/\d+:/i.test(asset.label);
	}

	let chatProcessImageAssets = $derived.by(() => {
		const assets: ProcessImageAsset[] = [];
		for (const message of msgs) {
			if (!message.imageDataUrl) continue;
			if (!isTextureOrAtlasChatImage(message)) continue;
			assets.push({
				label: message.content || message.meta || 'Process image',
				...(message.meta ? { meta: message.meta } : {}),
				imageDataUrl: message.imageDataUrl
			});
		}
		return assets;
	});
	let chatBuildImageAssets = $derived.by(() => {
		const assets: ProcessImageAsset[] = [];
		for (const message of msgs) {
			if (!message.imageDataUrl) continue;
			if (!isBuildStepChatImage(message)) continue;
			assets.push({
				label: message.content || 'Build step',
				meta: 'build step screenshot',
				imageDataUrl: message.imageDataUrl
			});
		}
		return assets;
	});
	let packageProcessImages = $derived.by(() => {
		const seen = new Set<string>();
		const merged: ProcessImageAsset[] = [];
		const hasProjectBuildImages = projectProcessImages.some(isBuildStepProcessImage);
		const buildFallbackImages = hasProjectBuildImages ? [] : chatBuildImageAssets;
		for (const asset of [
			...projectProcessImages,
			...buildFallbackImages,
			...chatProcessImageAssets
		]) {
			const key = `${asset.meta ?? ''}|${asset.label}|${asset.imageDataUrl}`;
			if (!asset.imageDataUrl || seen.has(key)) continue;
			seen.add(key);
			merged.push(asset);
		}
		return merged;
	});

	function durationMetaMs(meta: string | undefined): number {
		const label = meta?.match(/\btime\s+(.+)$/i)?.[1]?.trim();
		if (!label) return 0;
		const minutes = Number(label.match(/(\d+(?:\.\d+)?)\s*m/i)?.[1] ?? 0);
		const seconds = Number(label.match(/(\d+(?:\.\d+)?)\s*s/i)?.[1] ?? 0);
		return Math.round((minutes * 60 + seconds) * 1000);
	}

	let agentMetrics = $derived.by(() => {
		const lastUserIndex = msgs.map((message) => message.role).lastIndexOf('user');
		const currentRunMessages = lastUserIndex >= 0 ? msgs.slice(lastUserIndex + 1) : msgs;
		const tokenMessages = currentRunMessages
			.map((message) => message.tokenUsage)
			.filter((usage): usage is TokenUsageSummary => !!usage);
		const sumTokenField = (field: keyof TokenUsageSummary) =>
			tokenMessages.reduce((sum, usage) => sum + (usage[field] ?? 0), 0);
		const elapsedMs = currentRunMessages.reduce(
			(sum, message) => sum + durationMetaMs(message.meta),
			0
		);
		const metrics: AgentMetrics = {
			processCaptures: packageProcessImages.length,
			galleryFrames: renderFrameAssets.length,
			animationClips: renderVideoShot.clips.filter((clip) => !!clip.videoUrl).length,
			buildEvents: currentRunMessages.filter((message) =>
				/\b(Built|Added|Plan ready|Model pass finished|UV dream)\b/i.test(message.content)
			).length,
			elapsedMs,
			totalTokens: sumTokenField('totalTokens'),
			reasoningTokens: sumTokenField('reasoningTokens'),
			promptTokens: sumTokenField('promptTokens'),
			completionTokens: sumTokenField('completionTokens')
		};
		return Object.fromEntries(
			Object.entries(metrics).filter(([, value]) => typeof value === 'number' && value > 0)
		) as AgentMetrics;
	});
</script>

{#if showPanel}
	<aside class="planner-panel live-obj-side-panel" aria-label="Spellshape">
		<div class="live-obj-side-panel-chrome">
			<header class="live-obj-panel-head">
				<h1 class="live-obj-panel-title live-obj-panel-title--wordmark">
					<img
						class="live-obj-panel-logo"
						src="/images/spellshape_text_logo.svg"
						alt="Spellshape"
						width="1494"
						height="193"
						draggable="false"
					/>
				</h1>
				<button
					type="button"
					class="live-obj-panel-close"
					onclick={() => (showPanel = false)}
					title="Close panel">✕</button
				>
			</header>
			<div class="planner-tabs" role="tablist" aria-label="Panel tabs">
				<button
					type="button"
					class:active={activeTab === 'chat'}
					onclick={() => (activeTab = 'chat')}>Chat</button
				>
				<button
					type="button"
					class:active={activeTab === 'adjust'}
					onclick={() => (activeTab = 'adjust')}>Adjust</button
				>
				<button
					type="button"
					class:active={activeTab === 'tools'}
					onclick={() => (activeTab = 'tools')}>Tools</button
				>
				<button
					type="button"
					class:active={activeTab === 'scene'}
					onclick={() => (activeTab = 'scene')}>Scene</button
				>
				<button
					type="button"
					class:active={activeTab === 'render'}
					onclick={() => (activeTab = 'render')}>Render</button
				>
				<button
					type="button"
					class:active={activeTab === 'provider'}
					onclick={() => (activeTab = 'provider')}>Provider</button
				>
			</div>
		</div>
		<div class="planner-tab-panel" class:chat-panel={activeTab === 'chat'}>
			{#if activeTab === 'chat'}
				<LiveObjChatTab
					{msgs}
					{busy}
					{statusLine}
					{onSend}
					onStop={onStopGeneration}
					{onLaunchObjExample}
					bind:input={chatInput}
					bind:targetObjectId={selectedTargetObjectId}
					{targetObjectOptions}
					bind:feedbackLoop={chatFeedbackLoop}
					bind:attachedDataUrl={chatAttachedDataUrl}
				/>
			{:else if activeTab === 'provider'}
				<LiveObjProviderTab bind:settings={providerSettings} {busy} />
			{:else if activeTab === 'adjust'}
				<LiveObjAdjustTab
					bind:sourceTab
					bind:objectColor
					bind:objectScale
					bind:objectPosX
					bind:objectPosY
					bind:objectPosZ
					bind:objectRotYDeg
					{liveObjText}
					{rawLlmText}
					{executedObjText}
					{sceneEpoch}
					{sourceApplyBusy}
					{onLiveObjMetadataChange}
					{onApplyEditedSource}
				/>
			{:else if activeTab === 'tools'}
				<LiveObjToolsTab />
			{:else if activeTab === 'scene'}
				<LiveObjSceneTab
					bind:backgroundColor
					bind:canvasAspectRatio
					bind:showGrid
					bind:showAxes
					bind:wireframe
					bind:ambientLightIntensity
					bind:directionalLightIntensity
					bind:enableShadows
					bind:fogEnabled
					bind:fogNear
					bind:fogFar
					bind:fogColor
					bind:cameraFov
					bind:toneMappingExposure
					bind:renderingMode
					bind:outlineThickness
					bind:outlineDepthSensitivity
					bind:outlineNormalSensitivity
					bind:toonSteps
					bind:toonOutline
					{liveObjText}
					frameAssets={renderFrameAssets}
					videoShot={renderVideoShot}
					generatedDirectionJson={renderGeneratedDirectionJson}
					processImages={packageProcessImages}
					{onOpenLiveObj}
				/>
			{:else if activeTab === 'render'}
				<LiveObjRenderTab
					{liveObjText}
					{providerSettings}
					{onCaptureSceneScreenshot}
					{onCaptureSceneCameraSnapshot}
					{onCaptureReelTurntableFrames}
					{canvasAspectRatio}
					bind:prompt={renderPrompt}
					bind:screenshotDataUrl={renderScreenshotDataUrl}
					bind:generatedImageDataUrl={renderGeneratedImageDataUrl}
					bind:frameAssets={renderFrameAssets}
					bind:videoShot={renderVideoShot}
					bind:turntableFrameAssets={renderTurntableFrameAssets}
					bind:modelUsage={renderModelUsage}
					processImages={packageProcessImages}
					{agentMetrics}
					bind:videoBusy={renderVideoBusy}
					bind:generatedDirectionJson={renderGeneratedDirectionJson}
					bind:busy={renderBusy}
					bind:errorLine={renderErrorLine}
				/>
			{/if}
		</div>
	</aside>
{:else}
	<button
		type="button"
		class="live-obj-reopen"
		onclick={() => (showPanel = true)}
		title="Open panel">☰</button
	>
{/if}

<style>
	.live-obj-panel-title--wordmark {
		min-width: 0;
		flex: 1;
		line-height: 0;
	}
	.live-obj-panel-logo {
		display: block;
		height: 24px;
		width: auto;
		max-width: 100%;
		object-fit: contain;
		object-position: left center;
	}
	:global(.live-obj-side-panel .planner-tab-panel.chat-panel) {
		overflow: hidden;
	}
	:global(.live-obj-side-panel .planner-tabs) {
		margin: 0 12px 10px 16px;
	}
	.live-obj-reopen {
		position: absolute;
		z-index: 10;
		top: 16px;
		left: 16px;
		width: 44px;
		height: 44px;
		font-size: 18px;
		border: none;
		background: rgba(0, 0, 0, 0.05);
		border-radius: 20px;
		cursor: pointer;
		color: #666;
	}
	.live-obj-reopen:hover {
		background: rgba(0, 0, 0, 0.1);
		color: #1a1a1a;
	}
</style>
