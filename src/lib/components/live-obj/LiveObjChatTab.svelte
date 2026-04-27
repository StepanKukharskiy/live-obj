<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	type ChatMsg = { role: 'user' | 'assistant'; content: string };

	export let msgs: ChatMsg[] = [];
	export let busy = false;
	export let statusLine: string | null = null;

	const dispatch = createEventDispatcher<{
		send: { text: string };
	}>();

	let input = '';

	function submit() {
		const text = input.trim();
		if (!text || busy) return;
		dispatch('send', { text });
		input = '';
	}
</script>

<div class="chat-tab">
	<div class="messages" role="log">
		{#if msgs.length === 0}
			<div class="welcome">
				Describe a scene or ask for edits like “add a lamp”, “remove the sphere”, or “make the table red”.
			</div>
		{:else}
			{#each msgs as m}
				<div class="bubble" class:user={m.role === 'user'}>
					{m.content}
				</div>
			{/each}
		{/if}
	</div>

	{#if statusLine}
		<div class="status" role="status">{statusLine}</div>
	{/if}

	<div class="composer">
		<textarea
			rows="2"
			placeholder="Ask for generation or iterative edits..."
			bind:value={input}
			disabled={busy}
			on:keydown={(e) => {
				if (e.key === 'Enter' && !e.shiftKey) {
					e.preventDefault();
					submit();
				}
			}}
		></textarea>
		<button type="button" class="send" disabled={busy || !input.trim()} on:click={submit}>
			{busy ? '…' : 'Send'}
		</button>
	</div>
</div>

<style>
	.chat-tab {
		display: flex;
		flex-direction: column;
		gap: 10px;
		height: 100%;
		min-height: 0;
	}
	.messages {
		flex: 1;
		min-height: 120px;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-size: 13px;
	}
	.welcome {
		padding: 12px;
		background: rgba(255, 255, 255, 0.7);
		border-radius: 10px;
		color: #555;
		line-height: 1.45;
	}
	.bubble {
		align-self: flex-start;
		max-width: 100%;
		padding: 8px 12px;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.9);
		color: #222;
		line-height: 1.4;
		white-space: pre-wrap;
	}
	.bubble.user {
		align-self: flex-end;
		background: rgba(0, 0, 235, 0.1);
	}
	.status {
		font-size: 11px;
		color: #a35b00;
	}
	.composer {
		display: flex;
		gap: 8px;
		align-items: flex-end;
	}
	.composer textarea {
		flex: 1;
		resize: none;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 10px;
		padding: 8px 10px;
		font: inherit;
		font-size: 13px;
	}
	.send {
		flex-shrink: 0;
		padding: 8px 14px;
		border: none;
		border-radius: 10px;
		background: #0000eb;
		color: #fff;
		font-weight: 600;
		cursor: pointer;
	}
	.send:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
