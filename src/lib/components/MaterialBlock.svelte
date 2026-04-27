<script lang="ts">
	import type { ScenePlanMaterial } from '$lib/spellshape/runtime/types.js';

	export let material: ScenePlanMaterial;
	export let materialIdx = 0;
	export let textureImage: string | undefined = undefined;
	export let isCollapsed = false;
	export let onToggleCollapse: () => void = () => {};
	export let onIdChange: (id: string) => void = () => {};
	export let onColorChange: (color: string) => void = () => {};
	export let onRoughnessChange: (roughness: number) => void = () => {};
	export let onMetalnessChange: (metalness: number) => void = () => {};
	export let onOpacityChange: (opacity: number) => void = () => {};
	export let onTransparentChange: (transparent: boolean) => void = () => {};
	export let onPatternChange: (pattern: string) => void = () => {};
	export let onTextureUpload: (event: Event) => void = () => {};
	export let onTextureGenerate: () => void = () => {};
	export let isGeneratingTexture = false;
	export let textureError = '';
	export let onTextureRemove: () => void = () => {};
	export let onRemove: (() => void) | undefined = undefined;
	export let onDescriptionChange: (description: string) => void = () => {};

	function handleIdChange(e: Event) {
		const target = e.target as HTMLInputElement;
		onIdChange(target.value);
	}

	function handleDescriptionChange(e: Event) {
		const target = e.target as HTMLTextAreaElement;
		onDescriptionChange(target.value);
	}
</script>

<details class="mb-block" open={!isCollapsed}>
	<summary class="mb-summary" on:click|preventDefault={onToggleCollapse}>
		<div class="mb-header-line">
			<span class="mb-num">{materialIdx + 1}</span>
			<span class="mb-id">{material.id}</span>
			{#if textureImage || material.texture?.imageDataUrl}
				<div
					class="mb-texture-preview"
					style="background-image: url({textureImage || material.texture?.imageDataUrl})"
					title="Texture: Custom image"
				></div>
			{:else if material.texture?.pattern && material.texture.pattern !== 'none'}
				<span class="mb-texture-badge">{material.texture.pattern}</span>
			{/if}
			<div class="mb-buttons">
				{#if onRemove}
					<button
						type="button"
						class="mb-remove"
						on:click|stopPropagation={onRemove}
						title="Remove material"
					>
						<svg
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<line x1="18" y1="6" x2="6" y2="18"></line>
							<line x1="6" y1="6" x2="18" y2="18"></line>
						</svg>
					</button>
				{/if}
			</div>
		</div>
	</summary>

	<div class="mb-body">
		<div class="mb-field mb-description-field">
			<label class="mb-label">Description</label>
			<textarea
				class="mb-description-input"
				value={material.description ?? ''}
				on:input={handleDescriptionChange}
				placeholder="Material description for texture generation..."
				rows="2"
			></textarea>
		</div>
		<div class="mb-params">
			<div class="mb-field">
				<label class="mb-label">Id</label>
				<input type="text" class="mb-input" value={material.id} on:change={handleIdChange} />
			</div>

			<div class="mb-field">
				<label class="mb-label">Color</label>
				<input
					type="color"
					class="mb-color"
					value={material.color ?? '#94a3b8'}
					on:input={(e) => onColorChange(e.currentTarget.value)}
				/>
			</div>

			<div class="mb-field">
				<label class="mb-label">Roughness</label>
				<input
					type="number"
					class="mb-input"
					min="0"
					max="1"
					step="0.01"
					value={Number(material.roughness ?? 0.65)}
					on:input={(e) => onRoughnessChange(Number(e.currentTarget.value))}
				/>
			</div>

			<div class="mb-field">
				<label class="mb-label">Metalness</label>
				<input
					type="number"
					class="mb-input"
					min="0"
					max="1"
					step="0.01"
					value={Number(material.metalness ?? 0.1)}
					on:input={(e) => onMetalnessChange(Number(e.currentTarget.value))}
				/>
			</div>

			<div class="mb-field">
				<label class="mb-label">Transparent</label>
				<label class="mb-checkbox-row">
					<input
						type="checkbox"
						checked={Boolean(material.transparent) || Number(material.opacity ?? 1) < 1}
						on:change={(e) => onTransparentChange((e.currentTarget as HTMLInputElement).checked)}
					/>
					<span>Enable alpha blending</span>
				</label>
			</div>

			<div class="mb-field">
				<label class="mb-label">Opacity</label>
				<input
					type="number"
					class="mb-input"
					min="0"
					max="1"
					step="0.01"
					value={Number(material.opacity ?? 1)}
					on:input={(e) => onOpacityChange(Number(e.currentTarget.value))}
				/>
			</div>

			<div class="mb-field">
				<label class="mb-label">Texture Pattern</label>
				<select
					class="mb-select"
					value={material.texture?.pattern ?? 'none'}
					on:change={(e) => onPatternChange(e.currentTarget.value)}
				>
					<option value="none">none</option>
					<option value="checker">checker</option>
					<option value="stripes">stripes</option>
					<option value="dots">dots</option>
					<option value="noise">noise</option>
				</select>
			</div>

			<div class="mb-field">
				<label class="mb-label">Texture Image</label>
				<div class="mb-texture-actions">
					<button
						type="button"
						class="mb-generate-btn"
						on:click={onTextureGenerate}
						disabled={isGeneratingTexture}
					>
						{isGeneratingTexture ? 'Generating…' : 'Generate from description'}
					</button>
				</div>
				{#if textureImage || material.texture?.imageDataUrl}
					<div class="mb-texture-upload">
						<div
							class="mb-texture-image"
							style="background-image: url({textureImage || material.texture?.imageDataUrl})"
						>
							<button
								type="button"
								class="mb-remove-small"
								on:click={onTextureRemove}
								title="Remove texture image"
							>
								<svg
									width="10"
									height="10"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2.5"
									stroke-linecap="round"
									stroke-linejoin="round"
								>
									<line x1="18" y1="6" x2="6" y2="18"></line>
									<line x1="6" y1="6" x2="18" y2="18"></line>
								</svg>
							</button>
						</div>
					</div>
				{:else}
					<label class="mb-add-btn" title="Add texture image">
						<input
							type="file"
							class="mb-hidden-input"
							accept="image/*"
							on:change={onTextureUpload}
						/>
						<svg
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<line x1="12" y1="5" x2="12" y2="19"></line>
							<line x1="5" y1="12" x2="19" y2="12"></line>
						</svg>
					</label>
				{/if}
				{#if textureError}
					<p class="mb-error">{textureError}</p>
				{/if}
			</div>
		</div>
	</div>
</details>

<style>
	.mb-block {
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.8);
		overflow: hidden;
	}

	.mb-summary {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 10px 12px;
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: 14px;
	}

	.mb-summary::-webkit-details-marker {
		display: none;
	}

	.mb-header-line {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
	}

	.mb-num {
		color: #bbb;
		font-size: 12px;
		min-width: 18px;
		font-weight: 500;
	}

	.mb-id {
		color: #1a1a1a;
		font-weight: 600;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.mb-texture-preview {
		width: 24px;
		height: 24px;
		border-radius: 4px;
		background-size: cover;
		background-position: center;
		border: 1px solid rgba(0, 0, 0, 0.1);
	}

	.mb-texture-badge {
		font-size: 10px;
		padding: 2px 6px;
		background: rgba(0, 0, 235, 0.1);
		border-radius: 4px;
		color: #0000eb;
		font-weight: 500;
	}

	.mb-buttons {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.mb-remove {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		padding: 0;
		border: none;
		background: transparent;
		cursor: pointer;
		opacity: 0.4;
		transition: opacity 0.2s;
		flex-shrink: 0;
	}

	.mb-remove:hover {
		opacity: 0.8;
	}

	.mb-remove svg {
		width: 14px;
		height: 14px;
		stroke: #c00;
	}

	.mb-body {
		display: flex;
		flex-direction: column;
		border-top: 1px solid rgba(0, 0, 0, 0.05);
	}

	.mb-description-field {
		flex-direction: column;
		gap: 6px;
		padding: 10px 12px;
		background: rgba(0, 0, 0, 0.02);
		border-bottom: 1px solid rgba(0, 0, 0, 0.05);
	}

	.mb-description-input {
		width: 100%;
		padding: 8px 10px;
		font-size: 13px;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 6px;
		background: rgba(255, 255, 255, 0.8);
		color: #1a1a1a;
		font-family: inherit;
		resize: vertical;
		min-height: 50px;
		transition: all 0.2s;
	}

	.mb-description-input:focus {
		outline: none;
		border-color: rgba(0, 0, 235, 0.3);
		background: #fff;
	}

	.mb-description-input::placeholder {
		color: #999;
		font-style: italic;
	}

	.mb-params {
		padding: 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		background: transparent;
	}

	.mb-field {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.mb-label {
		font-size: 13px;
		font-weight: 500;
		color: #666;
		white-space: nowrap;
		min-width: 90px;
	}
	.mb-checkbox-row {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 13px;
		color: #334155;
	}

	.mb-input {
		flex: 1;
		padding: 6px 10px;
		font-size: 14px;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.8);
		color: #1a1a1a;
		font-family: inherit;
		transition: all 0.2s;
	}

	.mb-input:focus {
		outline: none;
		border-color: rgba(0, 0, 235, 0.3);
		background: #fff;
	}

	.mb-color {
		width: 40px;
		height: 32px;
		padding: 2px;
		border: 1px solid rgba(0, 0, 0, 0.16);
		border-radius: 8px;
		background: #fff;
		cursor: pointer;
	}

	.mb-select {
		flex: 1;
		padding: 6px 10px;
		font-size: 14px;
		border: 1px solid rgba(0, 0, 0, 0.16);
		border-radius: 8px;
		background: #fff;
		color: #1f2937;
		font-family: inherit;
	}

	.mb-texture-actions {
		display: flex;
		margin-bottom: 8px;
	}

	.mb-generate-btn {
		border: 1px solid #0000eb;
		background: #0000eb;
		color: #ffffff;
		border-radius: 100px;
		padding: 10px 16px;
		font-size: 13px;
		font-weight: 600;
		font-family: inherit;
		cursor: pointer;
		transition: all 0.2s;
	}

	.mb-generate-btn:disabled {
		opacity: 0.65;
		cursor: not-allowed;
	}

	.mb-generate-btn:hover:not(:disabled) {
		background: #0000c0;
		border-color: #0000c0;
	}

	.mb-texture-upload {
		display: flex;
		align-items: center;
	}

	.mb-texture-image {
		width: 40px;
		height: 40px;
		border-radius: 6px;
		background-size: cover;
		background-position: center;
		border: 1px solid rgba(0, 0, 0, 0.1);
		position: relative;
	}

	.mb-remove-small {
		position: absolute;
		top: -4px;
		right: -4px;
		width: 16px;
		height: 16px;
		padding: 0;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.95);
		color: #dc2626;
		display: flex;
		align-items: center;
		justify-content: center;
		border: none;
		cursor: pointer;
	}

	.mb-add-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: 1px dashed rgba(0, 0, 235, 0.3);
		border-radius: 50%;
		background: transparent;
		color: #0000eb;
		cursor: pointer;
		transition: all 0.2s;
	}

	.mb-add-btn:hover {
		background: rgba(0, 0, 235, 0.08);
		border-color: rgba(0, 0, 235, 0.5);
		transform: scale(1.1);
	}

	.mb-hidden-input {
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

	.mb-error {
		margin: 8px 0 0;
		font-size: 12px;
		color: #b91c1c;
	}
</style>
