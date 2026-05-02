<script lang="ts">
	type ChatMsg = { role: 'user' | 'assistant'; content: string; imageDataUrl?: string };

	const MODEL_OPTIONS = [
		{ value: 'gpt-5.5', label: 'GPT-5.5' },
		{ value: 'gpt-5.4', label: 'GPT-5.4' },
		{ value: 'gpt-4o', label: 'GPT-4o' }
	] as const;

	const PROCEDURAL_EXAMPLES = [
		{ text: 'Create a box at position [0,0,0] with size [1,1,1]', category: 'Primitives' },
		{ text: 'Create a sphere with radius 0.5 at origin', category: 'Primitives' },
		{ text: 'Extrude a rectangular profile to create a wall', category: 'Profile' },
		{ text: 'Revolve a profile around the z-axis to create a vase', category: 'Profile' },
		{ text: 'Subtract a cylinder from a box to create a hole', category: 'Boolean' },
		{ text: 'Union two spheres to create a merged shape', category: 'Boolean' },
		{ text: 'Scale the object by factor 2.0', category: 'Transform' },
		{ text: 'Rotate the object 45 degrees around the z-axis', category: 'Transform' },
		{ text: 'Apply a taper deformation along the z-axis', category: 'Deformation' },
		{ text: 'Add a bevel with 0.05 distance to all edges', category: 'Modifiers' },
		{ text: 'Generate a cellular automata coral structure', category: 'Simulation' },
		{ text: 'Create a differential growth pattern', category: 'Simulation' }
	];

	const LLM_ONLY_EXAMPLES = [
		{ text: 'Create a simple cube with 8 vertices and 12 triangular faces', category: 'Basic Shapes' },
		{ text: 'Create a pyramid with a square base and triangular sides', category: 'Basic Shapes' },
		{ text: 'Create a low-poly sphere with approximately 100 vertices', category: 'Basic Shapes' },
		{ text: 'Create a torus (donut shape) with tube radius 0.2 and ring radius 1.0', category: 'Basic Shapes' },
		{ text: 'Create a simple chair with seat, back, and 4 legs', category: 'Objects' },
		{ text: 'Create a table with a rectangular top and 4 cylindrical legs', category: 'Objects' },
		{ text: 'Create a simple lamp with a base, stem, and shade', category: 'Objects' },
		{ text: 'Create a low-poly tree trunk and foliage', category: 'Organic' },
		{ text: 'Create a simple flower with petals and stem', category: 'Organic' },
		{ text: 'Create a simple house with walls, roof, and door', category: 'Architecture' },
		{ text: 'Create a simple car body with wheels', category: 'Objects' },
		{ text: 'Create a rock formation with irregular geometry', category: 'Organic' }
	];

	const OBJ_EXAMPLES = [
		{
			name: 'Wall Arch with Hole',
			liveObj: `#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@kernel_default: cadquery

o wall_arch_profile_hole
#@source: procedural
#@type: extrude
#@params: kernel=cadquery, profile=[[0,0,0],[4.0,0,0],[4.0,0,3.0],[0,0,3.0],[0,0,0],None,[1.0,0,0],[3.0,0,0],[3.0,0,1.8],[2.97,0,2.0],[2.88,0,2.2],[2.75,0,2.37],[2.57,0,2.55],[2.4,0,2.68],[2.2,0,2.77],[2.0,0,2.8],[1.8,0,2.77],[1.6,0,2.68],[1.43,0,2.55],[1.25,0,2.37],[1.12,0,2.2],[1.03,0,2.0],[1.0,0,1.8],[1.0,0,0]], height=0.25, segments=32`
		}
	];

	let {
		msgs = [],
		busy = false,
		statusLine = null,
		onSend,
		onLaunchObjExample
	}: {
		msgs?: ChatMsg[];
		busy?: boolean;
		statusLine?: string | null;
		onSend?: (payload: { text: string; model: string; useProcedural?: boolean; imageDataUrl?: string }) => void;
		onLaunchObjExample?: (liveObj: string) => void;
	} = $props();

	let input = $state('');
	let selectedModel = $state<string>('gpt-5.5');
	let useProcedural = $state<boolean>(true);
	let attachedDataUrl = $state<string | undefined>(undefined);
	let fileInputEl: HTMLInputElement | undefined = $state();

	function clearAttachment() {
		attachedDataUrl = undefined;
		if (fileInputEl) fileInputEl.value = '';
	}

	function onPickImage(e: Event) {
		const inputEl = e.currentTarget as HTMLInputElement;
		const file = inputEl.files?.[0];
		if (!file || !file.type.startsWith('image/')) {
			clearAttachment();
			return;
		}
		const reader = new FileReader();
		reader.onload = () => {
			const r = reader.result;
			attachedDataUrl = typeof r === 'string' ? r : undefined;
		};
		reader.readAsDataURL(file);
	}

	function submit() {
		const text = input.trim();
		const img = attachedDataUrl;
		if ((!text && !img) || busy) return;
		onSend?.({ text, model: selectedModel, useProcedural, imageDataUrl: img });
		input = '';
		clearAttachment();
	}

	let canSend = $derived(Boolean((input.trim() || attachedDataUrl) && !busy));
	let promptExamples = $derived(useProcedural ? PROCEDURAL_EXAMPLES : LLM_ONLY_EXAMPLES);

	function usePrompt(example: { text: string; category: string }) {
		input = example.text;
	}

	function launchObjExample(example: { name: string; liveObj: string }) {
		onLaunchObjExample?.(example.liveObj);
	}
</script>

<div class="planner-chat-shell">
	<div class="planner-chat-thread" role="log">
		{#if msgs.length === 0}
			<div class="planner-chat-welcome">
				<p class="planner-chat-guide-copy">
					Describe a scene or ask for edits like "add a lamp", "remove the sphere", or "make the table red". You can
					attach a reference image instead of or in addition to text.
				</p>
				{#if OBJ_EXAMPLES.length > 0}
					<div class="planner-obj-examples">
						<h3 class="planner-obj-examples-title">Launch OBJ Examples</h3>
						<div class="planner-obj-grid">
							{#each OBJ_EXAMPLES as example (example.name)}
								<button
									type="button"
									class="planner-obj-chip"
									class:disabled={busy}
									disabled={busy}
									onclick={() => launchObjExample(example)}
								>
									<span class="planner-obj-chip-icon">📦</span>
									<span class="planner-obj-chip-name">{example.name}</span>
								</button>
							{/each}
						</div>
					</div>
				{/if}
				<div class="planner-prompt-examples">
					<h3 class="planner-prompt-examples-title">Quick Prompts</h3>
					<div class="planner-prompt-grid">
						{#each promptExamples as example (example.text)}
							<button
								type="button"
								class="planner-prompt-chip"
								class:disabled={busy}
								disabled={busy}
								onclick={() => usePrompt(example)}
							>
								<span class="planner-prompt-chip-category">{example.category}</span>
								<span class="planner-prompt-chip-text">{example.text}</span>
							</button>
						{/each}
					</div>
				</div>
			</div>
		{:else}
			{#each msgs as m (m)}
				<div
					class="planner-chat-row"
					class:assistant={m.role === 'assistant'}
					class:user={m.role === 'user'}
				>
					<div class="planner-chat-bubble">
						<div class="planner-chat-content">
							{#if m.imageDataUrl}
								<img
									class="planner-chat-msg-image"
									src={m.imageDataUrl}
									alt=""
								/>
							{/if}
							{#if m.content}
								<div class="planner-chat-msg-text">{m.content}</div>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		{/if}
	</div>

	{#if statusLine}
		<div class="planner-status" role="status">{statusLine}</div>
	{/if}

	<div class="planner-chat-input-shell">
		{#if attachedDataUrl}
			<div class="planner-chat-attach-strip">
				<img class="planner-chat-attach-thumb" src={attachedDataUrl} alt="" />
				<button
					type="button"
					class="planner-chat-attach-clear"
					onclick={clearAttachment}
					disabled={busy}
					title="Remove image"
				>
					✕
				</button>
			</div>
		{/if}
		<textarea
			rows="2"
			placeholder="Ask for generation or iterative edits..."
			bind:value={input}
			disabled={busy}
			onkeydown={(e) => {
				if (e.key === 'Enter' && !e.shiftKey) {
					e.preventDefault();
					submit();
				}
			}}
		></textarea>
		<div class="planner-chat-input-toolbar">
			<div class="planner-chat-toolbar-left">
				<label class="planner-chat-model-label">
					<span class="visually-hidden">Model</span>
					<select bind:value={selectedModel} disabled={busy} class="planner-chat-model-select">
						{#each MODEL_OPTIONS as opt (opt.value)}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
				</label>
				<label class="planner-chat-procedural-label">
					<input
						type="checkbox"
						bind:checked={useProcedural}
						disabled={busy}
						class="planner-chat-procedural-checkbox"
					/>
					<span class="planner-chat-procedural-text">Use tools</span>
				</label>
				<input
					bind:this={fileInputEl}
					type="file"
					accept="image/*"
					class="visually-hidden"
					id="live-obj-chat-image"
					onchange={onPickImage}
					disabled={busy}
				/>
				<label for="live-obj-chat-image" class="planner-chat-attach-label" title="Attach image">
					Attach
				</label>
			</div>
			<button type="button" class="send-button" disabled={!canSend} onclick={submit}>
				{busy ? '…' : 'Send'}
			</button>
		</div>
	</div>
</div>

<style>
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	.planner-chat-msg-image {
		display: block;
		max-width: 100%;
		max-height: 180px;
		border-radius: 10px;
		object-fit: contain;
		margin-bottom: 6px;
		background: rgba(0, 0, 0, 0.04);
	}

	.planner-chat-msg-text {
		white-space: pre-wrap;
		word-break: break-word;
	}

	.planner-chat-attach-strip {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}

	.planner-chat-attach-thumb {
		height: 48px;
		width: auto;
		max-width: 72px;
		border-radius: 8px;
		object-fit: cover;
		border: 1px solid rgba(0, 0, 0, 0.08);
	}

	.planner-chat-attach-clear {
		border: none;
		background: rgba(0, 0, 0, 0.06);
		border-radius: 999px;
		width: 28px;
		height: 28px;
		cursor: pointer;
		color: #666;
		font-size: 14px;
		line-height: 1;
		flex-shrink: 0;
	}

	.planner-chat-attach-clear:hover:not(:disabled) {
		background: rgba(0, 0, 0, 0.1);
		color: #1a1a1a;
	}

	.planner-chat-attach-clear:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.planner-chat-input-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		flex-wrap: wrap;
	}

	.planner-chat-toolbar-left {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		flex: 1;
	}

	.planner-chat-model-label {
		margin: 0;
		min-width: 0;
	}

	.planner-chat-model-select {
		box-sizing: border-box;
		max-width: 140px;
		height: 32px;
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.12);
		border-radius: 999px;
		padding: 0 10px;
		background: rgba(255, 255, 255, 0.95);
		cursor: pointer;
	}

	.planner-chat-model-select:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.planner-chat-procedural-label {
		margin: 0;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		cursor: pointer;
		user-select: none;
	}

	.planner-chat-procedural-checkbox {
		width: 16px;
		height: 16px;
		accent-color: #0000eb;
		cursor: pointer;
	}

	.planner-chat-procedural-checkbox:disabled {
		cursor: not-allowed;
	}

	.planner-chat-procedural-text {
		line-height: 1;
	}

	.planner-chat-attach-label {
		box-sizing: border-box;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 32px;
		padding: 0 10px;
		border-radius: 999px;
		border: 1px solid rgba(0, 0, 0, 0.12);
		background: rgba(0, 0, 0, 0.03);
		cursor: pointer;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		flex-shrink: 0;
		line-height: 1;
	}

	.planner-chat-attach-label:hover {
		background: rgba(0, 0, 0, 0.06);
	}

	.planner-prompt-examples {
		margin-top: 20px;
		padding-top: 20px;
		border-top: 1px solid rgba(0, 0, 0, 0.08);
	}

	.planner-prompt-examples-title {
		margin: 0 0 12px;
		font-size: 13px;
		font-weight: 600;
		color: #333;
	}

	.planner-prompt-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 8px;
	}

	.planner-prompt-chip {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		padding: 10px 12px;
		background: rgba(0, 0, 235, 0.03);
		border: 1px solid rgba(0, 0, 235, 0.12);
		border-radius: 8px;
		cursor: pointer;
		text-align: left;
		transition: all 0.15s;
	}

	.planner-prompt-chip:hover:not(.disabled) {
		background: rgba(0, 0, 235, 0.08);
		border-color: rgba(0, 0, 235, 0.2);
		transform: translateY(-1px);
	}

	.planner-prompt-chip:active:not(.disabled) {
		transform: translateY(0);
	}

	.planner-prompt-chip.disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.planner-prompt-chip-category {
		font-size: 10px;
		font-weight: 600;
		color: #0000eb;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		margin-bottom: 4px;
	}

	.planner-prompt-chip-text {
		font-size: 12px;
		color: #334155;
		line-height: 1.4;
	}

	.planner-obj-examples {
		margin-top: 20px;
		padding-top: 20px;
		border-top: 1px solid rgba(0, 0, 0, 0.08);
	}

	.planner-obj-examples-title {
		margin: 0 0 12px;
		font-size: 13px;
		font-weight: 600;
		color: #333;
	}

	.planner-obj-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 8px;
	}

	.planner-obj-chip {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 12px;
		background: rgba(0, 0, 235, 0.03);
		border: 1px solid rgba(0, 0, 235, 0.12);
		border-radius: 8px;
		cursor: pointer;
		text-align: left;
		transition: all 0.15s;
	}

	.planner-obj-chip:hover:not(.disabled) {
		background: rgba(0, 0, 235, 0.08);
		border-color: rgba(0, 0, 235, 0.2);
		transform: translateY(-1px);
	}

	.planner-obj-chip:active:not(.disabled) {
		transform: translateY(0);
	}

	.planner-obj-chip.disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.planner-obj-chip-icon {
		font-size: 16px;
		line-height: 1;
	}

	.planner-obj-chip-name {
		font-size: 12px;
		font-weight: 600;
		color: #0000eb;
		line-height: 1.4;
	}
</style>
