<script lang="ts">
	type ProviderSettings = {
		provider: string;
		apiKey: string;
		apiUrl: string;
		imageUrl: string;
		textModel: string;
		imageModel: string;
		rememberMe: boolean;
	};

	const PROVIDER_MODELS = {
		openai: {
			text: ['gpt-5.5', 'gpt-4o'],
			image: ['gpt-image-2', 'gpt-image-1.5']
		},
		together: {
			text: ['deepseek-ai/DeepSeek-V4-Pro', 'MiniMaxAI/MiniMax-M2.7', 'moonshotai/Kimi-K2.6', 'zai-org/GLM-5.1', 'openai/gpt-oss-120b'],
			image: ['black-forest-labs/FLUX.2-pro', 'Qwen/Qwen-Image-2.0']
		}
	};

	const PROVIDER_DEFAULT_URLS = {
		openai: {
			text: 'https://api.openai.com/v1/chat/completions',
			image: 'https://api.openai.com/v1/images/edits'
		},
		together: {
			text: 'https://api.together.xyz/v1/chat/completions',
			image: 'https://api.together.xyz/v1/images/edits'
		}
	};

	const CUSTOM = '__custom__';

	let { settings = $bindable<ProviderSettings>({ provider: 'openai', apiKey: '', apiUrl: 'https://api.openai.com/v1/chat/completions', imageUrl: 'https://api.openai.com/v1/images/edits', textModel: 'gpt-5.5', imageModel: 'gpt-image-1.5', rememberMe: false }), busy = false }: { settings?: ProviderSettings; busy?: boolean } = $props();

	let textModels = $derived(PROVIDER_MODELS[settings.provider as keyof typeof PROVIDER_MODELS]?.text || []);
	let imageModels = $derived(PROVIDER_MODELS[settings.provider as keyof typeof PROVIDER_MODELS]?.image || []);

	let textModelChoice = $derived(textModels.includes(settings.textModel) ? settings.textModel : CUSTOM);
	let imageModelChoice = $derived(imageModels.includes(settings.imageModel) ? settings.imageModel : CUSTOM);

	// Auto-update apiUrl, imageUrl, and models when provider changes
	$effect(() => {
		if (settings.provider && PROVIDER_DEFAULT_URLS[settings.provider as keyof typeof PROVIDER_DEFAULT_URLS]) {
			const defaults = PROVIDER_DEFAULT_URLS[settings.provider as keyof typeof PROVIDER_DEFAULT_URLS];
			const models = PROVIDER_MODELS[settings.provider as keyof typeof PROVIDER_MODELS];
			if (!settings.apiUrl || settings.apiUrl === PROVIDER_DEFAULT_URLS.openai.text || settings.apiUrl === PROVIDER_DEFAULT_URLS.together.text) {
				settings.apiUrl = defaults.text;
			}
			if (!settings.imageUrl || settings.imageUrl === PROVIDER_DEFAULT_URLS.openai.image || settings.imageUrl === PROVIDER_DEFAULT_URLS.together.image) {
				settings.imageUrl = defaults.image;
			}
			// Set model to first in list if current model is not in the new provider's model list
			if (models && models.text && models.text.length > 0) {
				if (!models.text.includes(settings.textModel)) {
					settings.textModel = models.text[0];
				}
			}
			if (models && models.image && models.image.length > 0) {
				if (!models.image.includes(settings.imageModel)) {
					settings.imageModel = models.image[0];
				}
			}
		}
	});

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
			<option value="together">Together</option>
		</select>
	</label>
	<label class="provider-remember">
		<input type="checkbox" bind:checked={settings.rememberMe} disabled={busy} />
		<span>Remember me on this device</span>
	</label>
	<label>API Key
		<input type="password" bind:value={settings.apiKey} autocomplete="off" placeholder="YOUR API KEY" disabled={busy} />
	</label>

	<label>Text Model
		<select value={textModelChoice} onchange={(e) => chooseTextModel((e.currentTarget as HTMLSelectElement).value)} disabled={busy}>
			{#each textModels as model (model)}
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
			{#each imageModels as model (model)}
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
