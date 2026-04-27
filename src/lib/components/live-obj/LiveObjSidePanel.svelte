<script lang="ts">
	import LiveObjChatTab from './LiveObjChatTab.svelte';
	import LiveObjOutputTab from './LiveObjOutputTab.svelte';
	import LiveObjControlsTab from './LiveObjControlsTab.svelte';
	import type { SourceTab } from './LiveObjOutputTab.svelte';

	type ChatMsg = { role: 'user' | 'assistant'; content: string };
	type PanelTab = 'chat' | 'output' | 'controls';

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
		onSend?: (text: string) => void;
	} = $props();

	let activeTab = $state<PanelTab>('chat');
</script>

{#if showPanel}
	<aside class="side-panel" aria-label="Live OBJ chat">
		<header class="panel-head">
			<h1 class="title">Live OBJ</h1>
			<button type="button" class="icon-btn" onclick={() => (showPanel = false)} title="Close panel">✕</button>
		</header>
		<div class="panel-tabs" role="tablist" aria-label="Panel tabs">
			<button type="button" class:active={activeTab === 'chat'} onclick={() => (activeTab = 'chat')}>Chat</button>
			<button type="button" class:active={activeTab === 'output'} onclick={() => (activeTab = 'output')}>Live OBJ Output</button>
			<button type="button" class:active={activeTab === 'controls'} onclick={() => (activeTab = 'controls')}>Controls</button>
		</div>
		<div class="panel-content">
			{#if activeTab === 'chat'}
				<LiveObjChatTab {msgs} {busy} {statusLine} {onSend} />
			{:else if activeTab === 'output'}
				<LiveObjOutputTab bind:sourceTab {liveObjText} {rawLlmText} {executedObjText} />
			{:else}
				<LiveObjControlsTab
					bind:backgroundColor
					bind:showGrid
					bind:showAxes
					bind:wireframe
					bind:objectColor
					bind:objectScale
					bind:objectPosX
					bind:objectPosY
					bind:objectPosZ
					bind:objectRotYDeg
					bind:ambientLightIntensity
					bind:directionalLightIntensity
				/>
			{/if}
		</div>
	</aside>
{:else}
	<button type="button" class="reopen" onclick={() => (showPanel = true)} title="Open panel">☰</button>
{/if}

<style>
	.side-panel { position: absolute; z-index: 10; top: 16px; left: 16px; width: min(520px, calc(100vw - 32px)); height: min(86vh, 780px); display: flex; flex-direction: column; background: rgba(255, 255, 255, 0.55); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border: 1px solid rgba(255, 255, 255, 0.5); border-radius: 16px; padding: 14px 16px 16px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08); }
	.panel-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
	.title { margin: 0; font-size: 1.1rem; font-weight: 600; color: #1a1a1a; }
	.icon-btn, .reopen { border: none; background: rgba(0, 0, 0, 0.06); border-radius: 8px; width: 32px; height: 32px; cursor: pointer; color: #333; }
	.reopen { position: absolute; z-index: 10; top: 16px; left: 16px; width: 44px; height: 44px; font-size: 18px; }
	.panel-tabs { display: flex; gap: 6px; margin-bottom: 10px; }
	.panel-tabs button { border: 1px solid rgba(0, 0, 0, 0.1); background: rgba(255, 255, 255, 0.7); border-radius: 8px; padding: 6px 10px; font-size: 12px; cursor: pointer; }
	.panel-tabs button.active { border-color: #0000eb; background: rgba(0, 0, 235, 0.08); color: #0000a8; font-weight: 600; }
	.panel-content { flex: 1; min-height: 0; }
</style>
