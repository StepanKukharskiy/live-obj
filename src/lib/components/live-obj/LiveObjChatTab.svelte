<script lang="ts">
	type ChatMsg = { role: 'user' | 'assistant'; content: string };

	let {
		msgs = [],
		busy = false,
		statusLine = null,
		onSend
	}: {
		msgs?: ChatMsg[];
		busy?: boolean;
		statusLine?: string | null;
		onSend?: (text: string) => void;
	} = $props();

	let input = $state('');

	function submit() {
		const text = input.trim();
		if (!text || busy) return;
		onSend?.(text);
		input = '';
	}
</script>

<div class="planner-chat-shell">
	<div class="planner-chat-thread" role="log">
		{#if msgs.length === 0}
			<div class="planner-chat-welcome">
				<p class="planner-chat-guide-copy">
					Describe a scene or ask for edits like “add a lamp”, “remove the sphere”, or “make the table red”.
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
						<div class="planner-chat-content">{m.content}</div>
					</div>
				</div>
			{/each}
		{/if}
	</div>

	{#if statusLine}
		<div class="planner-status" role="status">{statusLine}</div>
	{/if}

	<div class="planner-chat-input-shell">
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
		<div class="planner-chat-input-actions">
			<button type="button" class="send-button" disabled={busy || !input.trim()} onclick={submit}>
				{busy ? '…' : 'Send'}
			</button>
		</div>
	</div>
</div>
