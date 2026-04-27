<script>
	import { isGenerating, currentStage } from '$lib/stores/generation.js';
	import { addLog, clearLogs as clearLogsStore } from '$lib/stores/ui.js';
	import { generateScene } from '$lib/scene/generator.js';
	
	let prompt = '';
	let textarea;
	
	async function handleGenerate() {
		if (!prompt.trim()) {
			addLog('Please enter a prompt', 'warning');
			return;
		}
		
		clearLogsStore();
		isGenerating.set(true);
		
		try {
			await generateScene(prompt);
		} catch (error) {
			addLog(`Generation failed: ${error.message}`, 'error');
			console.error('Generation error:', error);
		} finally {
			isGenerating.set(false);
		}
	}
	
	function handleKeyPress(e) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleGenerate();
		}
	}
	
	function handleInput(e) {
		const target = e.target;
		target.style.height = 'auto';
		target.style.height = Math.min(target.scrollHeight, 120) + 'px';
	}
</script>



<!-- Central Chat Panel -->
<div class="chat-panel">
<!-- Stage Status (floats above prompt) -->
{#if $isGenerating && $currentStage}
	<div class="stage-status">{$currentStage}</div>
{/if}
	<textarea
		bind:this={textarea}
		bind:value={prompt}
		on:keypress={handleKeyPress}
		on:input={handleInput}
		rows="1"
		placeholder="Describe your 3D scene..."
		disabled={$isGenerating}
	></textarea>
	
	{#if $isGenerating}
		<div class="loading-indicator">
			<div class="spinner"></div>
		</div>
	
	{:else}
	<button class="send-btn" on:click={handleGenerate} disabled={$isGenerating} title="Generate">
		<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
	</button>
	{/if}
</div>

<style>
	.stage-status {
		position: fixed;
		bottom: 84px;
		left: 50%;
		transform: translateX(-50%);
		font-size: 11px;
		color: #0000eb;
		pointer-events: none;
		white-space: nowrap;
		z-index: 1001;
	}
	
	.chat-panel {
		position: fixed;
		bottom: 24px;
		left: 50%;
		transform: translateX(-50%);
		background: rgba(255, 255, 255, 0.95);
		border: 1px solid #ddd;
		border-radius: 28px;
		padding: 6px 6px 6px 12px;
		color: #1a1a1a;
		width: 560px;
		max-width: 90vw;
		backdrop-filter: blur(12px);
		z-index: 1000;
		box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
		display: flex;
		align-items: center;
		gap: 8px;
	}
	
	textarea {
		flex: 1;
		padding: 10px 0;
		background: transparent;
		border: none;
		color: #1a1a1a;
		font-size: 14px;
		margin: 0;
		box-sizing: border-box;
		resize: none;
		font-family: inherit;
		line-height: 1.4;
		max-height: 120px;
		overflow-y: auto;
		outline: none;
	}
	
	textarea::placeholder {
		color: #aaa;
	}
	
	textarea:disabled {
		opacity: 0.5;
	}
	
	.loading-indicator {
		display: flex;
		align-items: center;
		gap: 8px;
		color: #888;
		font-size: 12px;
	}
	
	.spinner {
		width: 30px;
		height: 30px;
		border: 2px solid #ddd;
		border-top-color: #0000eb;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	
	@keyframes spin {
		to { transform: rotate(360deg); }
	}
	
	.send-btn {
		width: 40px;
		height: 40px;
		min-width: 40px;
		border-radius: 50%;
		background: #0000eb;
		border: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		margin: 0;
		transition: background 0.15s, transform 0.1s;
		flex-shrink: 0;
	}
	
	.send-btn:hover:not(:disabled) {
		background: #0000c0;
	}
	
	.send-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	
	.send-btn svg {
		width: 18px;
		height: 18px;
		fill: #fff;
	}
</style>
