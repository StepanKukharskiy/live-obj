<script lang="ts">
	type ProviderSettings = {
		provider: string;
		apiKey: string;
		apiUrl: string;
		textModel: string;
		imageModel: string;
	};
	let { settings = $bindable<ProviderSettings>({ provider: 'openai', apiKey: '', apiUrl: '', textModel: 'gpt-5.5', imageModel: 'gpt-image-1.5' }), busy = false }: { settings?: ProviderSettings; busy?: boolean } = $props();
</script>

<div class="provider-tab">
	<p class="provider-note">Bring your own key. Settings apply to server-side requests for this session.</p>
	<label>Provider
		<select bind:value={settings.provider} disabled={busy}>
			<option value="openai">OpenAI</option>
			<option value="custom">Custom (OpenAI-compatible)</option>
		</select>
	</label>
	<label>API Key
		<input type="password" bind:value={settings.apiKey} autocomplete="off" placeholder="sk-..." disabled={busy} />
	</label>
	<label>API URL (optional)
		<input type="text" bind:value={settings.apiUrl} placeholder="https://.../v1/chat/completions" disabled={busy} />
	</label>
	<label>Text Model
		<input type="text" bind:value={settings.textModel} placeholder="gpt-5.5" disabled={busy} />
	</label>
	<label>Image Model
		<input type="text" bind:value={settings.imageModel} placeholder="gpt-image-1.5" disabled={busy} />
	</label>
</div>

<style>
	.provider-tab { display: grid; gap: 10px; padding: 12px 2px; }
	label { display: grid; gap: 6px; font-size: 12px; color: #334155; }
	input, select { border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; font-size: 13px; }
	.provider-note { margin: 0; font-size: 12px; color: #64748b; }
</style>
