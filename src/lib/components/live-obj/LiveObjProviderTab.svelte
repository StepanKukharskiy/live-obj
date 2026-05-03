<script lang="ts">
	type ProviderSettings = {
		provider: string;
		apiKey: string;
		apiUrl: string;
		textModel: string;
		imageModel: string;
		rememberMe: boolean;
	};
	const TEXT_MODELS = ['gpt-5.5', 'gpt-5.4-mini'];
	const IMAGE_MODELS = ['gpt-image-1.5'];
	const CUSTOM = '__custom__';
	let { settings = $bindable<ProviderSettings>({ provider: 'openai', apiKey: '', apiUrl: '', textModel: 'gpt-5.5', imageModel: 'gpt-image-1.5', rememberMe: false }), busy = false }: { settings?: ProviderSettings; busy?: boolean } = $props();

	let textModelChoice = $derived(TEXT_MODELS.includes(settings.textModel) ? settings.textModel : CUSTOM);
	let imageModelChoice = $derived(IMAGE_MODELS.includes(settings.imageModel) ? settings.imageModel : CUSTOM);

	function chooseTextModel(v: string) {
		settings.textModel = v === CUSTOM ? '' : v;
	}
	function chooseImageModel(v: string) {
		settings.imageModel = v === CUSTOM ? '' : v;
	}
</script>

<div class="provider-tab">
	<p class="provider-note">Bring your own key. Settings apply to server-side requests.</p>
	<label>Provider
		<select bind:value={settings.provider} disabled={busy}>
			<option value="openai">OpenAI</option>
			<option value="custom">Custom (OpenAI-compatible)</option>
		</select>
	</label>
	<label class="provider-remember">
		<input type="checkbox" bind:checked={settings.rememberMe} disabled={busy} />
		<span>Remember me on this device</span>
	</label>
	<label>API Key
		<input type="password" bind:value={settings.apiKey} autocomplete="off" placeholder="sk-..." disabled={busy} />
	</label>
	<label>API URL (optional)
		<input type="text" bind:value={settings.apiUrl} placeholder="https://.../v1/chat/completions" disabled={busy} />
	</label>

	<label>Text Model
		<select value={textModelChoice} onchange={(e) => chooseTextModel((e.currentTarget as HTMLSelectElement).value)} disabled={busy}>
			{#each TEXT_MODELS as model (model)}
				<option value={model}>{model}</option>
			{/each}
			<option value={CUSTOM}>Custom…</option>
		</select>
	</label>
	{#if textModelChoice === CUSTOM}
		<label>Custom Text Model
			<input type="text" bind:value={settings.textModel} placeholder="enter model id" disabled={busy} />
		</label>
	{/if}

	<label>Image Model
		<select value={imageModelChoice} onchange={(e) => chooseImageModel((e.currentTarget as HTMLSelectElement).value)} disabled={busy}>
			{#each IMAGE_MODELS as model (model)}
				<option value={model}>{model}</option>
			{/each}
			<option value={CUSTOM}>Custom…</option>
		</select>
	</label>
	{#if imageModelChoice === CUSTOM}
		<label>Custom Image Model
			<input type="text" bind:value={settings.imageModel} placeholder="enter model id" disabled={busy} />
		</label>
	{/if}
</div>

<style>
	.provider-tab { display: grid; gap: 10px; padding: 12px 2px; }
	label { display: grid; gap: 6px; font-size: 12px; color: #334155; }
	input, select { border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; font-size: 13px; }
	.provider-note { margin: 0; font-size: 12px; color: #64748b; }
	.provider-remember { grid-template-columns: auto 1fr; align-items: center; gap: 8px; }
</style>
