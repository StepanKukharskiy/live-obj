<script lang="ts">
	type ProviderSettings = {
		provider: string;
		apiKey: string;
		apiUrl: string;
		imageUrl: string;
		videoUrl?: string;
		textModel: string;
		imageModel: string;
		videoModel?: string;
		rememberMe: boolean;
	};
	type ProviderModelConfig = { text: string[]; image: string[]; video?: string[] };

	const PROVIDER_MODELS: Record<string, ProviderModelConfig> = {
		openai: {
			text: ['gpt-5.5', 'gpt-4o'],
			image: ['gpt-image-2', 'gpt-image-1.5']
		},
		claude: {
			text: ['claude-fable-5', 'claude-opus-4-8', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
			image: []
		},
		openrouter: {
			text: [
				'openai/gpt-5.5',
				'anthropic/claude-opus-4.8',
				'google/gemini-3.1-pro-preview',
				'anthropic/claude-sonnet-4.6',
				'openai/gpt-5.4-pro',
				'openai/gpt-5.4-mini',
				'google/gemini-3-flash-preview',
				'moonshotai/kimi-k2-thinking',
				'openrouter/auto'
			],
			image: [
				'google/gemini-3.1-flash-image-preview',
				'openai/gpt-5.4-image-2',
				'bytedance-seed/seedream-4.5',
				'google/gemini-3-pro-image-preview',
				'x-ai/grok-imagine-image-quality',
				'black-forest-labs/flux.2-pro',
				'black-forest-labs/flux.2-max',
				'openai/gpt-5-image-mini'
			],
			video: [
				'google/veo-3.1-lite',
				'google/veo-3.1',
				'openai/sora-2-pro',
				'bytedance-seed/seedance-2.0'
			]
		},
		google: {
			text: [
				'gemini-3.5-flash',
				'gemini-3-flash-preview',
				'gemini-3.1-pro-preview',
				'gemini-2.5-flash'
			],
			image: ['gemini-3.1-flash-image-preview'],
			video: ['veo-3.1-generate-preview', 'veo-3.1-fast-generate-preview']
		},
		together: {
			text: [
				'deepseek-ai/DeepSeek-V4-Pro',
				'MiniMaxAI/MiniMax-M2.7',
				'moonshotai/Kimi-K2.6',
				'zai-org/GLM-5.1',
				'google/gemma-4-31B-it',
				'openai/gpt-oss-120b'
			],
			image: ['black-forest-labs/FLUX.2-pro', 'Qwen/Qwen-Image-2.0']
		}
	};

	const PROVIDER_DEFAULT_URLS: Record<string, { text: string; image: string; video?: string }> = {
		openai: {
			text: 'https://api.openai.com/v1/chat/completions',
			image: 'https://api.openai.com/v1/images/edits'
		},
		claude: {
			text: 'https://api.anthropic.com/v1/messages',
			image: ''
		},
		openrouter: {
			text: 'https://openrouter.ai/api/v1/chat/completions',
			image: 'https://openrouter.ai/api/v1/chat/completions',
			video: 'https://openrouter.ai/api/v1/videos'
		},
		google: {
			text: 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
			image:
				'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent',
			video: 'https://generativelanguage.googleapis.com/v1beta'
		},
		together: {
			text: 'https://api.together.xyz/v1/chat/completions',
			image: 'https://api.together.xyz/v1/images/edits'
		}
	};

	const CUSTOM = '__custom__';
	const DEFAULT_TEXT_URLS = Object.values(PROVIDER_DEFAULT_URLS).map((defaults) => defaults.text);
	const DEFAULT_IMAGE_URLS = Object.values(PROVIDER_DEFAULT_URLS).map((defaults) => defaults.image);
	const DEFAULT_VIDEO_URLS = Object.values(PROVIDER_DEFAULT_URLS)
		.map((defaults) => defaults.video)
		.filter((url): url is string => !!url);

	let {
		settings = $bindable<ProviderSettings>({
			provider: 'openai',
			apiKey: '',
			apiUrl: 'https://api.openai.com/v1/chat/completions',
			imageUrl: 'https://api.openai.com/v1/images/edits',
			videoUrl: '',
			textModel: 'gpt-5.5',
			imageModel: 'gpt-image-1.5',
			videoModel: '',
			rememberMe: false
		}),
		busy = false
	}: { settings?: ProviderSettings; busy?: boolean } = $props();

	let textModels = $derived(
		PROVIDER_MODELS[settings.provider as keyof typeof PROVIDER_MODELS]?.text || []
	);
	let imageModels = $derived(
		PROVIDER_MODELS[settings.provider as keyof typeof PROVIDER_MODELS]?.image || []
	);
	let videoModels = $derived(
		PROVIDER_MODELS[settings.provider as keyof typeof PROVIDER_MODELS]?.video || []
	);
	let providerSupportsImage = $derived(imageModels.length > 0);
	let providerSupportsVideo = $derived(videoModels.length > 0);
	let providerImageUnavailableMessage = $derived(
		'Image generation is not available for this provider yet.'
	);
	let providerVideoUnavailableMessage = $derived(
		'Video generation is not available for this provider yet.'
	);

	let textModelChoice = $derived(
		textModels.includes(settings.textModel) ? settings.textModel : CUSTOM
	);
	let imageModelChoice = $derived(
		imageModels.includes(settings.imageModel) ? settings.imageModel : CUSTOM
	);
	let videoModelChoice = $derived(
		videoModels.includes(settings.videoModel ?? '') ? (settings.videoModel ?? '') : CUSTOM
	);

	// Auto-update apiUrl, imageUrl, and models when provider changes
	$effect(() => {
		if (
			settings.provider &&
			PROVIDER_DEFAULT_URLS[settings.provider as keyof typeof PROVIDER_DEFAULT_URLS]
		) {
			const defaults =
				PROVIDER_DEFAULT_URLS[settings.provider as keyof typeof PROVIDER_DEFAULT_URLS];
			const models = PROVIDER_MODELS[settings.provider as keyof typeof PROVIDER_MODELS];
			if (!settings.apiUrl || DEFAULT_TEXT_URLS.includes(settings.apiUrl)) {
				settings.apiUrl = defaults.text;
			}
			if (!settings.imageUrl || DEFAULT_IMAGE_URLS.includes(settings.imageUrl)) {
				settings.imageUrl = defaults.image;
			}
			if (!settings.videoUrl || DEFAULT_VIDEO_URLS.includes(settings.videoUrl)) {
				settings.videoUrl = defaults.video ?? '';
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
			if (models && models.video && models.video.length > 0) {
				if (!models.video.includes(settings.videoModel ?? '')) {
					settings.videoModel = models.video[0];
				}
			} else {
				settings.videoModel = '';
			}
		}
	});

	function chooseTextModel(v: string) {
		settings.textModel = v === CUSTOM ? '' : v;
	}
	function chooseImageModel(v: string) {
		settings.imageModel = v === CUSTOM ? '' : v;
	}
	function chooseVideoModel(v: string) {
		settings.videoModel = v === CUSTOM ? '' : v;
	}

	function clearProviderSettings() {
		settings.provider = 'openai';
		settings.apiKey = '';
		settings.apiUrl = PROVIDER_DEFAULT_URLS.openai.text;
		settings.imageUrl = PROVIDER_DEFAULT_URLS.openai.image;
		settings.videoUrl = '';
		settings.textModel = PROVIDER_MODELS.openai.text[0];
		settings.imageModel = PROVIDER_MODELS.openai.image[0];
		settings.videoModel = '';
		settings.rememberMe = false;
	}
</script>

<div class="provider-tab">
	<p class="provider-note">
		Bring your own key. Requests pass through Spellshape's server route and are forwarded to your
		selected provider. See <a href="/privacy" target="_blank" rel="noopener noreferrer">Privacy</a>
		and <a href="/terms" target="_blank" rel="noopener noreferrer">Terms</a>.
	</p>
	<label
		>Provider
		<select bind:value={settings.provider} disabled={busy}>
			<option value="openai">OpenAI</option>
			<option value="claude">Claude</option>
			<option value="openrouter">OpenRouter</option>
			<option value="google">Google</option>
			<option value="together">Together</option>
		</select>
	</label>
	<label class="provider-remember">
		<input type="checkbox" bind:checked={settings.rememberMe} disabled={busy} />
		<span>Remember provider settings on this device</span>
	</label>
	<label
		>API Key
		<input
			type="password"
			bind:value={settings.apiKey}
			autocomplete="off"
			placeholder="YOUR API KEY"
			disabled={busy}
		/>
	</label>

	<label
		>Text Model
		<select
			value={textModelChoice}
			onchange={(e) => chooseTextModel((e.currentTarget as HTMLSelectElement).value)}
			disabled={busy}
		>
			{#each textModels as model (model)}
				<option value={model}>{model}</option>
			{/each}
			<option value={CUSTOM}>Custom…</option>
		</select>
	</label>
	{#if textModelChoice === CUSTOM}
		<label
			>Custom Text Model
			<input
				type="text"
				bind:value={settings.textModel}
				placeholder="enter model id"
				disabled={busy}
			/>
		</label>
	{/if}

	{#if providerSupportsImage}
		<label
			>Image Model
			<select
				value={imageModelChoice}
				onchange={(e) => chooseImageModel((e.currentTarget as HTMLSelectElement).value)}
				disabled={busy}
			>
				{#each imageModels as model (model)}
					<option value={model}>{model}</option>
				{/each}
				<option value={CUSTOM}>Custom…</option>
			</select>
		</label>
		{#if imageModelChoice === CUSTOM}
			<label
				>Custom Image Model
				<input
					type="text"
					bind:value={settings.imageModel}
					placeholder="enter model id"
					disabled={busy}
				/>
			</label>
		{/if}
	{:else}
		<div class="provider-capability-note">{providerImageUnavailableMessage}</div>
	{/if}
	{#if providerSupportsVideo}
		<label
			>Video Model
			<select
				value={videoModelChoice}
				onchange={(e) => chooseVideoModel((e.currentTarget as HTMLSelectElement).value)}
				disabled={busy}
			>
				{#each videoModels as model (model)}
					<option value={model}>{model}</option>
				{/each}
				<option value={CUSTOM}>Custom…</option>
			</select>
		</label>
		{#if videoModelChoice === CUSTOM}
			<label
				>Custom Video Model
				<input
					type="text"
					bind:value={settings.videoModel}
					placeholder="enter video model id"
					disabled={busy}
				/>
			</label>
		{/if}
	{:else}
		<div class="provider-capability-note">{providerVideoUnavailableMessage}</div>
	{/if}
	<button type="button" class="provider-clear" onclick={clearProviderSettings} disabled={busy}>
		Clear provider settings
	</button>
</div>

<style>
	.provider-tab {
		display: grid;
		gap: 10px;
		padding: 12px 2px;
	}
	label {
		display: grid;
		gap: 6px;
		font-size: 12px;
		color: #334155;
	}
	input {
		border: 1px solid #cbd5e1;
		border-radius: 8px;
		padding: 8px 10px;
		font-size: 13px;
	}
	select {
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

	select:disabled {
		cursor: not-allowed;
		opacity: 0.65;
	}

	.provider-note {
		margin: 0;
		font-size: 12px;
		color: #64748b;
	}
	.provider-note a {
		color: #1d4ed8;
		text-decoration: none;
		font-weight: 700;
	}
	.provider-note a:hover {
		text-decoration: underline;
	}
	.provider-capability-note {
		font-size: 12px;
		line-height: 1.4;
		color: #64748b;
	}
	.provider-remember {
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: 8px;
	}
	.provider-clear {
		justify-self: start;
		border: 1px solid #cbd5e1;
		border-radius: 8px;
		background: #ffffff;
		color: #334155;
		padding: 8px 10px;
		font: inherit;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
	}
	.provider-clear:hover:not(:disabled) {
		border-color: #94a3b8;
		background: #f8fafc;
	}
	.provider-clear:disabled {
		cursor: not-allowed;
		opacity: 0.65;
	}
</style>
