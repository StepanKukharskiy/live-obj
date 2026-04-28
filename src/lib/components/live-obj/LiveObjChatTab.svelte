<script lang="ts">
	type ChatMsg = { role: 'user' | 'assistant'; content: string; imageDataUrl?: string };

	const MODEL_OPTIONS = [
		{ value: 'gpt-5.5', label: 'GPT-5.5' },
		{ value: 'gpt-5.4', label: 'GPT-5.4' },
		{ value: 'gpt-4o', label: 'GPT-4o' }
	] as const;

	let {
		msgs = [],
		busy = false,
		statusLine = null,
		onSend
	}: {
		msgs?: ChatMsg[];
		busy?: boolean;
		statusLine?: string | null;
		onSend?: (payload: { text: string; model: string; imageDataUrl?: string }) => void;
	} = $props();

	let input = $state('');
	let selectedModel = $state<string>('gpt-5.5');
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
		onSend?.({ text, model: selectedModel, imageDataUrl: img });
		input = '';
		clearAttachment();
	}

	let canSend = $derived(Boolean((input.trim() || attachedDataUrl) && !busy));
</script>

<div class="planner-chat-shell">
	<div class="planner-chat-thread" role="log">
		{#if msgs.length === 0}
			<div class="planner-chat-welcome">
				<p class="planner-chat-guide-copy">
					Describe a scene or ask for edits like “add a lamp”, “remove the sphere”, or “make the table red”. You can
					attach a reference image instead of or in addition to text.
				</p>
			</div>
		{:else}
			{#each msgs as m}
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
						{#each MODEL_OPTIONS as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
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
</style>
