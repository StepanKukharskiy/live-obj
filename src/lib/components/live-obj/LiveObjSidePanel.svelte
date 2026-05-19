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
			textModel: 'gpt-5.5',
			imageModel: 'gpt-image-1.5',
			rememberMe: false
		}),
		onSend,
		onCaptureSceneScreenshot,
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
			textModel: string;
			imageModel: string;
			rememberMe: boolean;
		};
		onSend?: (payload: SendPayload) => void;
		onCaptureSceneScreenshot?: () => string;
		onLaunchObjExample?: (liveObj: string) => void;
		onOpenLiveObj?: (sourceText: string) => void | Promise<void>;
		kernelDefault?: 'auto' | 'cadquery';
	} = $props();

	let activeTab = $state<PanelTab>('chat');
	let chatInput = $state('');
	let chatFeedbackLoop = $state(false);
	let chatFeedbackPasses = $state(3);
	let chatAttachedDataUrl = $state<string | undefined>(undefined);
	let renderPrompt = $state('');
	let renderScreenshotDataUrl = $state('');
	let renderGeneratedImageDataUrl = $state('');
	let renderBusy = $state(false);
	let renderErrorLine = $state<string | null>(null);
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
					{onLaunchObjExample}
					bind:input={chatInput}
					bind:targetObjectId={selectedTargetObjectId}
					{targetObjectOptions}
					bind:feedbackLoop={chatFeedbackLoop}
					bind:feedbackPasses={chatFeedbackPasses}
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
					{onOpenLiveObj}
				/>
			{:else}
				<LiveObjRenderTab
					{liveObjText}
					{providerSettings}
					{onCaptureSceneScreenshot}
					bind:prompt={renderPrompt}
					bind:screenshotDataUrl={renderScreenshotDataUrl}
					bind:generatedImageDataUrl={renderGeneratedImageDataUrl}
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
