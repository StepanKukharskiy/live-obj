<script lang="ts">
	import '$lib/styles/planner-panel.css';
	import LiveObjChatTab from './LiveObjChatTab.svelte';
	import LiveObjAdjustTab from './LiveObjAdjustTab.svelte';
	import LiveObjSceneTab from './LiveObjSceneTab.svelte';
	import type { SourceTab } from './LiveObjOutputTab.svelte';

	type ChatMsg = { role: 'user' | 'assistant'; content: string; imageDataUrl?: string };
	type PanelTab = 'chat' | 'adjust' | 'scene';

	let {
		showPanel = $bindable(true),
		msgs = [],
		busy = false,
		statusLine = null,
		sourceTab = $bindable<SourceTab>('executed'),
		liveObjText = '',
		rawLlmText = '',
		executedObjText = '',
		backgroundColor = $bindable('#e8ebf2'),
		showGrid = $bindable(true),
		showAxes = $bindable(true),
		wireframe = $bindable(false),
		objectColor = $bindable('#7185d4'),
		objectScale = $bindable(1),
		objectPosX = $bindable(0),
		objectPosY = $bindable(0),
		objectPosZ = $bindable(0),
		objectRotYDeg = $bindable(0),
		ambientLightIntensity = $bindable(1),
		directionalLightIntensity = $bindable(1.5),
		enableShadows = $bindable(false),
		fogEnabled = $bindable(false),
		fogNear = $bindable(10),
		fogFar = $bindable(50),
		fogColor = $bindable('#f8fafc'),
		cameraFov = $bindable(50),
		toneMappingExposure = $bindable(1),
		onLiveObjMetadataChange,
		onSend
	}: {
		showPanel?: boolean;
		msgs?: ChatMsg[];
		busy?: boolean;
		statusLine?: string | null;
		sourceTab?: SourceTab;
		liveObjText?: string;
		rawLlmText?: string;
		executedObjText?: string;
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
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
		onSend?: (payload: { text: string; model: string; imageDataUrl?: string }) => void;
	} = $props();

	let activeTab = $state<PanelTab>('chat');
</script>

{#if showPanel}
	<aside
		class="planner-panel live-obj-side-panel"
		aria-label="Spellshape"
	>
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
				<button type="button" class="live-obj-panel-close" onclick={() => (showPanel = false)} title="Close panel">✕</button>
			</header>
			<div class="planner-tabs" role="tablist" aria-label="Panel tabs">
				<button type="button" class:active={activeTab === 'chat'} onclick={() => (activeTab = 'chat')}>Chat</button>
				<button type="button" class:active={activeTab === 'adjust'} onclick={() => (activeTab = 'adjust')}>Adjust</button>
				<button type="button" class:active={activeTab === 'scene'} onclick={() => (activeTab = 'scene')}>Scene</button>
			</div>
		</div>
		<div
			class="planner-tab-panel"
			class:chat-panel={activeTab === 'chat'}
		>
			{#if activeTab === 'chat'}
				<LiveObjChatTab {msgs} {busy} {statusLine} {onSend} />
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
					onLiveObjMetadataChange={onLiveObjMetadataChange}
				/>
			{:else}
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
				/>
			{/if}
		</div>
	</aside>
{:else}
	<button type="button" class="live-obj-reopen" onclick={() => (showPanel = true)} title="Open panel">☰</button>
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
		padding: 0 12px 0 16px;
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
