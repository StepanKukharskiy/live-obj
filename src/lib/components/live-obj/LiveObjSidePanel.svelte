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
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
		onSend?: (text: string) => void;
	} = $props();

	let activeTab = $state<PanelTab>('chat');
</script>

{#if showPanel}
	<aside class="side-panel planner-panel" aria-label="Live OBJ chat">
		<header class="panel-head">
			<h1 class="title">Live OBJ</h1>
			<button type="button" class="icon-btn" onclick={() => (showPanel = false)} title="Close panel">✕</button>
		</header>
		<div class="panel-tabs planner-tabs" role="tablist" aria-label="Panel tabs">
			<button type="button" class:active={activeTab === 'chat'} onclick={() => (activeTab = 'chat')}>Chat</button>
			<button type="button" class:active={activeTab === 'output'} onclick={() => (activeTab = 'output')}>Live OBJ Output</button>
			<button type="button" class:active={activeTab === 'controls'} onclick={() => (activeTab = 'controls')}>Controls</button>
		</div>
		<div class="panel-content planner-tab-panel">
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
					liveObjText={liveObjText}
					onLiveObjMetadataChange={onLiveObjMetadataChange}
				/>
			{/if}
		</div>
	</aside>
{:else}
	<button type="button" class="reopen" onclick={() => (showPanel = true)} title="Open panel">☰</button>
{/if}

<style>
	.side-panel { position: absolute; top: 16px; left: 16px; width: min(520px, calc(100vw - 32px)); height: calc(100vh - 32px); display: flex; flex-direction: column; overflow: hidden; border: 1px solid rgba(0, 0, 0, 0.08); border-radius: 16px; background: rgba(255, 255, 255, 0.95); color: #1a1a1a; backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px); box-shadow: 0 12px 48px rgba(0, 0, 0, 0.08), 0 4px 16px rgba(0, 0, 0, 0.04); z-index: 10; box-sizing: border-box; }
	.panel-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px 6px; }
	.title { margin: 0; font-size: 1rem; font-weight: 600; color: #1a1a1a; }
	.icon-btn, .reopen { border: none; background: rgba(0, 0, 0, 0.05); border-radius: 20px; width: 32px; height: 32px; cursor: pointer; color: #666; }
	.icon-btn:hover, .reopen:hover { background: rgba(0, 0, 0, 0.1); color: #1a1a1a; }
	.reopen { position: absolute; z-index: 10; top: 16px; left: 16px; width: 44px; height: 44px; font-size: 18px; }
	.panel-tabs { display: flex; gap: 6px; padding: 0 12px; overflow-x: auto; scrollbar-width: none; }
	.panel-tabs::-webkit-scrollbar { display: none; }
	.panel-tabs button { border: none; border-radius: 0; padding: 10px 12px; background: transparent; color: #666; font-size: 14px; font-weight: 500; cursor: pointer; position: relative; white-space: nowrap; }
	.panel-tabs button.active { color: #0000eb; font-weight: 600; }
	.panel-tabs button.active::after { content: ''; position: absolute; left: 12px; right: 12px; bottom: 0; height: 3px; background: #0000eb; border-radius: 999px; }
	.panel-content { flex: 1; min-height: 0; overflow: hidden; padding: 8px 12px 12px; }
</style>
