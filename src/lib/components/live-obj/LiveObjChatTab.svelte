<script lang="ts">
	import { tick } from 'svelte';

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

	const MODEL_OPTIONS = [
		{ value: 'gpt-5.5', label: 'GPT-5.5' },
		{ value: 'gpt-5.4', label: 'GPT-5.4' },
		{ value: 'gpt-4o', label: 'GPT-4o' }
	] as const;

	const PROMPT_EXAMPLES = [
		{
			text: 'Create a fluid sculptural vase as raw OBJ with width, depth, and height controls',
			category: 'Raw + Post'
		},
		{
			text: 'Create a parametric pavilion with raw OBJ triangular frames whose peaks follow a sine wave',
			category: 'Raw + Post'
		},
		{
			text: 'Make a sculptural vase mesh and expose post-transform scale controls',
			category: 'Controls'
		},
		{
			text: 'Make a pavilion with sine-wave roof peaks and expose frame count, wave, spacing, span, and height controls',
			category: 'Controls'
		},
		{
			text: 'Refine the current mesh with #@post simplify, center_origin, and snap_to_ground',
			category: 'Cleanup'
		}
	];

	const OBJ_EXAMPLES = [
		{
			name: 'Fluid Sculptural Vase',
			liveObj: `#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: basic_clay color=#e6e4dd roughness=0.82 metalness=0.0

o fluid_sculptural_vase
#@source: llm_mesh
#@semantic: fluid asymmetric sculptural vase
#@bbox min=[-0.48,-0.46,0] max=[0.52,0.48,1.8]
#@params: width=1.0, depth=1.0, height=1.0
#@controls:
#@ - slider key=width label=Width min=0.6 max=1.6 step=0.05
#@ - slider key=depth label=Depth min=0.6 max=1.6 step=0.05
#@ - slider key=height label=Height min=0.7 max=1.8 step=0.05
#@post:
#@ - smooth iterations=2 strength=0.35
#@ - transform scale=[width,depth,height]
#@ - center_origin axes=xz
#@ - snap_to_ground axis=z
#@ - material name=basic_clay
v 0.38 0.00 0.00
v 0.25 0.32 0.00
v -0.16 0.36 0.00
v -0.34 0.08 0.00
v -0.22 -0.30 0.00
v 0.22 -0.34 0.00
v 0.52 0.02 0.42
v 0.29 0.42 0.42
v -0.20 0.39 0.42
v -0.44 0.05 0.42
v -0.27 -0.38 0.42
v 0.26 -0.42 0.42
v 0.42 0.05 0.92
v 0.18 0.32 0.92
v -0.24 0.26 0.92
v -0.36 -0.04 0.92
v -0.13 -0.30 0.92
v 0.32 -0.24 0.92
v 0.30 0.00 1.34
v 0.12 0.24 1.34
v -0.18 0.21 1.34
v -0.28 -0.02 1.34
v -0.10 -0.23 1.34
v 0.22 -0.18 1.34
v 0.22 0.03 1.80
v 0.08 0.17 1.80
v -0.10 0.15 1.80
v -0.18 -0.01 1.80
v -0.08 -0.15 1.80
v 0.16 -0.12 1.80
f 1 2 8 7
f 2 3 9 8
f 3 4 10 9
f 4 5 11 10
f 5 6 12 11
f 6 1 7 12
f 7 8 14 13
f 8 9 15 14
f 9 10 16 15
f 10 11 17 16
f 11 12 18 17
f 12 7 13 18
f 13 14 20 19
f 14 15 21 20
f 15 16 22 21
f 16 17 23 22
f 17 18 24 23
f 18 13 19 24
f 19 20 26 25
f 20 21 27 26
f 21 22 28 27
f 22 23 29 28
f 23 24 30 29
f 24 19 25 30
f 1 6 5 4 3 2`
		},
		{
			name: 'Parametric Pavilion',
			liveObj: `#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@workflow: raw_post
#@material_preset: basic_clay color=#e6e4dd roughness=0.82 metalness=0.0

o pavilion_sine_frame
#@source: llm_mesh
#@semantic: parametric pavilion triangular frame module with expression-driven sine array
#@bbox min=[-0.08,-0.8,0] max=[0.08,0.8,1.5]
#@params: frame_count=7, bay_spacing=0.42, pavilion_width=1.0, pavilion_height=1.0, wave_amount=0.10
#@controls:
#@ - slider key=frame_count label=Frames min=2 max=14 step=1
#@ - slider key=bay_spacing label=Bay spacing min=0.22 max=0.8 step=0.02
#@ - slider key=pavilion_width label=Span min=0.7 max=1.6 step=0.05
#@ - slider key=pavilion_height label=Height min=0.6 max=1.5 step=0.05
#@ - slider key=wave_amount label=Wave min=0.0 max=0.28 step=0.01
#@post:
#@ - transform scale=[1,pavilion_width,pavilion_height]
#@ - array count=frame_count offset=[bay_spacing,0,0] centered=true
#@ - deform position=[x,y+(w*w*sin(u*tau)*wave_amount),z]
#@ - center_origin axes=xz
#@ - snap_to_ground axis=z
#@ - material name=basic_clay
#@ - tag value=architectural
v -0.060 -0.740 0.120
v -0.060 -0.740 0.000
v -0.060 0.740 0.000
v -0.060 0.740 0.120
v 0.060 -0.740 0.120
v 0.060 -0.740 0.000
v 0.060 0.740 0.000
v 0.060 0.740 0.120
v -0.060 -0.744 0.104
v -0.060 -0.656 0.056
v -0.060 0.044 1.356
v -0.060 -0.044 1.404
v 0.060 -0.744 0.104
v 0.060 -0.656 0.056
v 0.060 0.044 1.356
v 0.060 -0.044 1.404
v -0.060 0.044 1.404
v -0.060 -0.044 1.356
v -0.060 0.656 0.056
v -0.060 0.744 0.104
v 0.060 0.044 1.404
v 0.060 -0.044 1.356
v 0.060 0.656 0.056
v 0.060 0.744 0.104
f 1 2 3 4
f 5 8 7 6
f 1 5 6 2
f 2 6 7 3
f 3 7 8 4
f 4 8 5 1
f 9 10 11 12
f 13 16 15 14
f 9 13 14 10
f 10 14 15 11
f 11 15 16 12
f 12 16 13 9
f 17 18 19 20
f 21 24 23 22
f 17 21 22 18
f 18 22 23 19
f 19 23 24 20
f 20 24 21 17`
		}
	];

	let {
		msgs = [],
		busy = false,
		statusLine = null,
		onSend,
		onStop,
		onLaunchObjExample,
		input = $bindable(''),
		targetObjectId = $bindable(''),
		targetObjectOptions = [],
		feedbackLoop = $bindable(false),
		feedbackPasses = $bindable(3),
		attachedDataUrl = $bindable<string | undefined>(undefined)
	}: {
		msgs?: ChatMsg[];
		busy?: boolean;
		statusLine?: string | null;
		onSend?: (payload: SendPayload) => void;
		onStop?: () => void;
		onLaunchObjExample?: (liveObj: string) => void;
		input?: string;
		targetObjectId?: string;
		targetObjectOptions?: string[];
		feedbackLoop?: boolean;
		feedbackPasses?: number;
		attachedDataUrl?: string | undefined;
	} = $props();

	let fileInputEl: HTMLInputElement | undefined = $state();
	let threadEl: HTMLDivElement | undefined = $state();
	let hasInitializedThreadScroll = false;
	let lastAutoScrolledMessageCount = 0;

	function estimateDataUrlBytes(dataUrl: string): number {
		const base64Payload = dataUrl.split(',')[1] ?? '';
		return Math.floor((base64Payload.length * 3) / 4);
	}

	function loadImage(dataUrl: string): Promise<HTMLImageElement> {
		return new Promise((resolve, reject) => {
			const img = new Image();
			img.onload = () => resolve(img);
			img.onerror = () => reject(new Error('Unable to load image attachment'));
			img.src = dataUrl;
		});
	}

	async function compressImageDataUrl(dataUrl: string): Promise<string> {
		const img = await loadImage(dataUrl);
		const maxDimension = 1024;
		const maxBytes = 750_000;
		const scale = Math.min(1, maxDimension / Math.max(img.naturalWidth, img.naturalHeight, 1));
		let width = Math.max(1, Math.round(img.naturalWidth * scale));
		let height = Math.max(1, Math.round(img.naturalHeight * scale));
		let quality = 0.82;

		const encode = () => {
			const canvas = document.createElement('canvas');
			canvas.width = width;
			canvas.height = height;
			const ctx = canvas.getContext('2d');
			if (!ctx) return dataUrl;
			ctx.drawImage(img, 0, 0, width, height);
			return canvas.toDataURL('image/jpeg', quality);
		};

		let out = encode();
		let attempts = 0;
		while (estimateDataUrlBytes(out) > maxBytes && attempts < 7) {
			if (quality > 0.55) {
				quality = Math.max(0.55, quality - 0.08);
			} else {
				width = Math.max(1, Math.round(width * 0.85));
				height = Math.max(1, Math.round(height * 0.85));
			}
			out = encode();
			attempts += 1;
		}
		return out;
	}

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
		reader.onload = async () => {
			const r = reader.result;
			if (typeof r !== 'string') {
				attachedDataUrl = undefined;
				return;
			}
			try {
				attachedDataUrl = await compressImageDataUrl(r);
			} catch {
				attachedDataUrl = r;
			}
		};
		reader.readAsDataURL(file);
	}

	function submit() {
		const text = input.trim();
		const img = attachedDataUrl;
		if ((!text && !img) || busy) return;
		onSend?.({
			text,
			useProcedural: false,
			...(targetObjectId ? { targetObjectId } : {}),
			imageDataUrl: img,
			feedbackLoop,
			feedbackPasses
		});
		input = '';
		clearAttachment();
	}

	let canSend = $derived(Boolean((input.trim() || attachedDataUrl) && !busy));

	function usePrompt(example: { text: string; category: string }) {
		input = example.text;
	}

	function launchObjExample(example: { name: string; liveObj: string }) {
		onLaunchObjExample?.(example.liveObj);
	}

	function formatTokens(value: number | undefined): string {
		return typeof value === 'number' ? value.toLocaleString() : 'n/a';
	}

	function tokenUsageLine(usage: TokenUsageSummary): string {
		const parts = [
			`tokens ${formatTokens(usage.totalTokens)}`,
			`in ${formatTokens(usage.promptTokens)}`,
			`out ${formatTokens(usage.completionTokens)}`
		];
		if (usage.reasoningTokens != null)
			parts.push(`reasoning ${formatTokens(usage.reasoningTokens)}`);
		if (usage.cachedTokens != null) parts.push(`cached ${formatTokens(usage.cachedTokens)}`);
		return parts.join(' · ');
	}

	function displayMessageContent(content: string): string {
		return content.trim();
	}

	$effect(() => {
		const messageCount = msgs.length;
		if (!threadEl) return;
		if (!hasInitializedThreadScroll) {
			hasInitializedThreadScroll = true;
			lastAutoScrolledMessageCount = messageCount;
			return;
		}
		if (messageCount === 0 || messageCount <= lastAutoScrolledMessageCount) {
			lastAutoScrolledMessageCount = messageCount;
			return;
		}
		lastAutoScrolledMessageCount = messageCount;
		tick().then(() => {
			if (threadEl) threadEl.scrollTop = threadEl.scrollHeight;
		});
	});
</script>

<div class="planner-chat-shell">
	<div class="planner-chat-thread" role="log" bind:this={threadEl}>
		{#if msgs.length === 0}
			<div class="planner-chat-welcome">
				{#if OBJ_EXAMPLES.length > 0}
					<div class="planner-obj-examples">
						<h3 class="planner-obj-examples-title">Launch Raw OBJ Examples</h3>
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
					<h3 class="planner-prompt-examples-title">Raw OBJ Prompts</h3>
					<div class="planner-prompt-grid">
						{#each PROMPT_EXAMPLES as example (example.text)}
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
					<div class="planner-chat-bubble" class:planner-chat-thinking={m.transient}>
						<div class="planner-chat-content">
							{#if m.imageDataUrl}
								<img class="planner-chat-msg-image" src={m.imageDataUrl} alt="" />
							{/if}
							{#if m.content}
								<div class="planner-chat-msg-text">{displayMessageContent(m.content)}</div>
							{/if}
							{#if m.transient}
								<span class="planner-thinking-dots" aria-hidden="true">
									<span></span>
									<span></span>
									<span></span>
								</span>
							{/if}
							{#if m.role === 'assistant' && m.meta}
								<div class="planner-chat-token-usage">{m.meta}</div>
							{/if}
							{#if m.role === 'assistant' && m.tokenUsage}
								<div class="planner-chat-token-usage">{tokenUsageLine(m.tokenUsage)}</div>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		{/if}
	</div>

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
			placeholder="Ask for raw OBJ generation or a #@post edit..."
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
				{#if targetObjectOptions.length > 0}
					<label class="planner-chat-procedural-label planner-chat-target-label">
						<span class="planner-chat-procedural-text">Target</span>
						<select class="planner-chat-target-select" bind:value={targetObjectId} disabled={busy}>
							<option value="">Scene</option>
							{#each targetObjectOptions as objectId}
								<option value={objectId}>{objectId}</option>
							{/each}
						</select>
					</label>
				{/if}
				<label class="planner-chat-procedural-label">
					<input
						type="checkbox"
						bind:checked={feedbackLoop}
						disabled={busy}
						class="planner-chat-procedural-checkbox"
					/>
					<span class="planner-chat-procedural-text">Vision loop</span>
				</label>
				{#if feedbackLoop}
					<label class="planner-chat-loop-count" title="Feedback loop generations">
						<span>×</span>
						<select bind:value={feedbackPasses} disabled={busy}>
							<option value={1}>1</option>
							<option value={2}>2</option>
							<option value={3}>3</option>
							<option value={4}>4</option>
							<option value={5}>5</option>
						</select>
					</label>
				{/if}
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
			{#if busy}
				<button type="button" class="stop-button" onclick={() => onStop?.()}>Stop</button>
			{:else}
				<button type="button" class="send-button" disabled={!canSend} onclick={submit}>Send</button>
			{/if}
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

	.planner-chat-token-usage {
		margin-top: 4px;
		font-size: 11px;
		line-height: 1.3;
		color: #64748b;
	}

	.planner-chat-thinking .planner-chat-content {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		color: #475569;
	}

	.planner-thinking-dots {
		display: inline-flex;
		gap: 3px;
		align-items: center;
	}

	.planner-thinking-dots span {
		width: 4px;
		height: 4px;
		border-radius: 999px;
		background: #64748b;
		animation: planner-thinking-pulse 1s infinite ease-in-out;
	}

	.planner-thinking-dots span:nth-child(2) {
		animation-delay: 0.14s;
	}

	.planner-thinking-dots span:nth-child(3) {
		animation-delay: 0.28s;
	}

	@keyframes planner-thinking-pulse {
		0%,
		80%,
		100% {
			opacity: 0.35;
			transform: translateY(0);
		}
		40% {
			opacity: 1;
			transform: translateY(-2px);
		}
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
		align-items: flex-end;
		justify-content: space-between;
		gap: 10px;
		flex-wrap: wrap;
	}

	.planner-chat-toolbar-left {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		min-width: 0;
		flex: 1;
		max-width: 100%;
	}

	.planner-chat-input-toolbar > .send-button {
		flex: 0 0 auto;
		margin-left: auto;
	}

	.planner-chat-input-toolbar > .stop-button {
		flex: 0 0 auto;
		margin-left: auto;
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

	.planner-chat-target-label {
		flex: 1 1 100%;
		min-width: 0;
		max-width: 100%;
	}

	.planner-chat-target-select {
		box-sizing: border-box;
		min-width: 0;
		max-width: 100%;
		flex: 1 1 auto;
		height: 32px;
		font-family: inherit;
		font-size: 13px;
		font-weight: 600;
		color: #111827;
		border: 1px solid rgba(0, 0, 0, 0.16);
		border-radius: 8px;
		padding: 0 30px 0 10px;
		background: rgba(255, 255, 255, 0.95);
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

	.planner-chat-loop-count {
		margin: 0;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		white-space: nowrap;
	}

	.planner-chat-loop-count select {
		box-sizing: border-box;
		height: 28px;
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		color: #333;
		border: 1px solid rgba(0, 0, 0, 0.12);
		border-radius: 999px;
		padding: 0 8px;
		background: rgba(255, 255, 255, 0.95);
		cursor: pointer;
	}

	.planner-chat-loop-count select:disabled {
		opacity: 0.65;
		cursor: not-allowed;
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

	.stop-button {
		box-sizing: border-box;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 72px;
		height: 36px;
		padding: 0 14px;
		border-radius: 999px;
		border: 1px solid rgba(0, 0, 235, 0.22);
		background: rgba(0, 0, 235, 0.06);
		color: #0000eb;
		font-family: inherit;
		font-size: 13px;
		font-weight: 700;
		cursor: pointer;
	}

	.stop-button:hover {
		background: rgba(0, 0, 235, 0.1);
		border-color: rgba(0, 0, 235, 0.34);
	}
</style>
