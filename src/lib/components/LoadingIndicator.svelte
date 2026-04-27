<script>
	import { currentStage, generationProgress } from '$lib/stores/generation.js';
</script>

<div class="loading-overlay">
	<div class="loading-content">
		<div class="spinner-large"></div>
		{#if $currentStage}
			<p class="stage">{$currentStage}</p>
		{/if}
		{#if $generationProgress > 0}
			<div class="progress-bar">
				<div class="progress-fill" style="width: {$generationProgress}%"></div>
			</div>
		{/if}
	</div>
</div>

<style>
	.loading-overlay {
		position: fixed;
		top: 0;
		left: 0;
		width: 100%;
		height: 100%;
		background: rgba(0, 0, 0, 0.7);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
		backdrop-filter: blur(4px);
	}
	
	.loading-content {
		text-align: center;
	}
	
	.spinner-large {
		width: 60px;
		height: 60px;
		border: 4px solid rgba(74, 158, 255, 0.2);
		border-top-color: #4a9eff;
		border-radius: 50%;
		animation: spin 1s linear infinite;
		margin: 0 auto 20px;
	}
	
	@keyframes spin {
		to { transform: rotate(360deg); }
	}
	
	.stage {
		color: #4a9eff;
		font-size: 16px;
		margin: 0 0 15px;
	}
	
	.progress-bar {
		width: 300px;
		height: 4px;
		background: rgba(255, 255, 255, 0.1);
		border-radius: 2px;
		overflow: hidden;
	}
	
	.progress-fill {
		height: 100%;
		background: linear-gradient(90deg, #4a9eff, #357abd);
		transition: width 0.3s ease;
	}
</style>
