<script lang="ts">
	type MetaObject = {
		id: string;
		params: Record<string, string>;
	};

	let {
		backgroundColor = $bindable('#e8ebf2'),
		showGrid = $bindable(true),
		showAxes = $bindable(true),
		wireframe = $bindable(false),
		objectColor = $bindable('#7185d4'),
		objectScale = $bindable(1),
		objectPosX = $bindable(0),
		objectPosY = $bindable(0),
		objectPosZ = $bindable(0),
		objectRotYDeg = $bindable(0),
		ambientLightIntensity = $bindable(1),
		directionalLightIntensity = $bindable(1.5),
		liveObjText = '',
		onLiveObjMetadataChange
	}: {
		backgroundColor?: string;
		showGrid?: boolean;
		showAxes?: boolean;
		wireframe?: boolean;
		objectColor?: string;
		objectScale?: number;
		objectPosX?: number;
		objectPosY?: number;
		objectPosZ?: number;
		objectRotYDeg?: number;
		ambientLightIntensity?: number;
		directionalLightIntensity?: number;
		liveObjText?: string;
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
	} = $props();

	const splitTopLevel = (raw: string): string[] => {
		const out: string[] = [];
		let buf = '';
		let depth = 0;
		for (const ch of raw) {
			if (ch === '[' || ch === '{' || ch === '(') depth += 1;
			if (ch === ']' || ch === '}' || ch === ')') depth = Math.max(0, depth - 1);
			if (ch === ',' && depth === 0) {
				if (buf.trim()) out.push(buf.trim());
				buf = '';
				continue;
			}
			buf += ch;
		}
		if (buf.trim()) out.push(buf.trim());
		return out;
	};

	const parseParams = (raw: string): Record<string, string> => {
		const map: Record<string, string> = {};
		for (const piece of splitTopLevel(raw)) {
			const eq = piece.indexOf('=');
			if (eq <= 0) continue;
			const key = piece.slice(0, eq).trim();
			const value = piece.slice(eq + 1).trim();
			if (!key) continue;
			map[key] = value;
		}
		return map;
	};

	const serializeParams = (params: Record<string, string>) =>
		Object.entries(params)
			.map(([k, v]) => `${k}=${v}`)
			.join(', ');

	const parseObjects = (text: string): MetaObject[] => {
		const lines = text.split(/\r?\n/);
		const objects: MetaObject[] = [];
		let activeObject: string | null = null;
		for (let i = 0; i < lines.length; i += 1) {
			const line = lines[i].trim();
			const objectMatch = line.match(/^o\s+(.+)$/);
			if (objectMatch) {
				activeObject = objectMatch[1].trim();
				continue;
			}
			if (!activeObject) continue;
			const paramsMatch = line.match(/^#@params:\s*(.+)$/);
			if (!paramsMatch) continue;
			objects.push({
				id: activeObject,
				params: parseParams(paramsMatch[1])
			});
		}
		return objects;
	};

	const rewriteParamInLiveObj = (text: string, objectId: string, key: string, value: string) => {
		const lines = text.split(/\r?\n/);
		let activeObject: string | null = null;
		for (let i = 0; i < lines.length; i += 1) {
			const rawLine = lines[i];
			const trimmed = rawLine.trim();
			const objectMatch = trimmed.match(/^o\s+(.+)$/);
			if (objectMatch) {
				activeObject = objectMatch[1].trim();
				continue;
			}
			if (activeObject !== objectId) continue;
			const paramsMatch = trimmed.match(/^#@params:\s*(.+)$/);
			if (!paramsMatch) continue;
			const parsed = parseParams(paramsMatch[1]);
			parsed[key] = value.trim();
			lines[i] = `#@params: ${serializeParams(parsed)}`;
			break;
		}
		return lines.join('\n');
	};

	const metaObjects = $derived(parseObjects(liveObjText));
	let selectedObjectId = $state<string | null>(null);
	let draftValues = $state<Record<string, string>>({});

	$effect(() => {
		if (!metaObjects.length) {
			selectedObjectId = null;
			draftValues = {};
			return;
		}
		if (!selectedObjectId || !metaObjects.some((o) => o.id === selectedObjectId)) {
			selectedObjectId = metaObjects[0].id;
		}
	});

	const selectedMetaObject = $derived(
		selectedObjectId ? metaObjects.find((o) => o.id === selectedObjectId) ?? null : null
	);

	function fieldValue(key: string, fallback: string) {
		const draftKey = `${selectedObjectId ?? ''}::${key}`;
		return draftValues[draftKey] ?? fallback;
	}

	function setDraftValue(key: string, value: string) {
		const draftKey = `${selectedObjectId ?? ''}::${key}`;
		draftValues = { ...draftValues, [draftKey]: value };
	}

	function commitValue(key: string, fallback: string) {
		if (!selectedMetaObject) return;
		const nextValue = fieldValue(key, fallback);
		const updated = rewriteParamInLiveObj(liveObjText, selectedMetaObject.id, key, nextValue);
		onLiveObjMetadataChange?.(updated);
	}
</script>

<div class="planner-panel-body">
	<div class="planner-object-section">
		<div class="planner-object-header">
			<div class="planner-object-title-stack">
				<strong>Scene Controls</strong>
			</div>
		</div>
		<div class="planner-chain">
			<label class="planner-context-field"><span class="planner-label-inline">Background</span><input class="planner-text-input" type="color" bind:value={backgroundColor} /></label>
			<label class="planner-context-field"><span class="planner-label-inline">Ambient</span><input class="planner-text-input" type="number" step="0.1" bind:value={ambientLightIntensity} /></label>
			<label class="planner-context-field"><span class="planner-label-inline">Directional</span><input class="planner-text-input" type="number" step="0.1" bind:value={directionalLightIntensity} /></label>
			<label class="planner-context-field planner-checkbox-row"><span class="planner-label-inline">Grid</span><input type="checkbox" bind:checked={showGrid} /></label>
			<label class="planner-context-field planner-checkbox-row"><span class="planner-label-inline">Axes</span><input type="checkbox" bind:checked={showAxes} /></label>
		</div>
	</div>

	<div class="planner-object-section">
		<div class="planner-object-header">
			<div class="planner-object-title-stack"><strong>Render Controls</strong></div>
		</div>
		<div class="planner-chain">
			<label class="planner-context-field"><span class="planner-label-inline">Color</span><input class="planner-text-input" type="color" bind:value={objectColor} /></label>
			<label class="planner-context-field"><span class="planner-label-inline">Scale</span><input class="planner-text-input" type="number" step="0.05" bind:value={objectScale} /></label>
			<label class="planner-context-field"><span class="planner-label-inline">Pos X</span><input class="planner-text-input" type="number" step="0.05" bind:value={objectPosX} /></label>
			<label class="planner-context-field"><span class="planner-label-inline">Pos Y</span><input class="planner-text-input" type="number" step="0.05" bind:value={objectPosY} /></label>
			<label class="planner-context-field"><span class="planner-label-inline">Pos Z</span><input class="planner-text-input" type="number" step="0.05" bind:value={objectPosZ} /></label>
			<label class="planner-context-field"><span class="planner-label-inline">Rotate Y</span><input class="planner-text-input" type="number" step="1" bind:value={objectRotYDeg} /></label>
			<label class="planner-context-field planner-checkbox-row"><span class="planner-label-inline">Wireframe</span><input type="checkbox" bind:checked={wireframe} /></label>
		</div>
	</div>

	<div class="planner-object-section">
		<div class="planner-object-header">
			<div class="planner-object-title-stack"><strong>Live OBJ Metadata Params</strong></div>
		</div>
		<div class="planner-chain">
			{#if metaObjects.length === 0}
				<p class="planner-structure-help">No editable <code>#@params</code> metadata found in current Live OBJ.</p>
			{:else}
				<label class="planner-context-field">
					<span class="planner-label-inline">Object</span>
					<select class="planner-text-input" bind:value={selectedObjectId}>
						{#each metaObjects as obj}
							<option value={obj.id}>{obj.id}</option>
						{/each}
					</select>
				</label>
				{#if selectedMetaObject}
					{#each Object.entries(selectedMetaObject.params) as [key, value]}
						<label class="planner-context-field">
							<span class="planner-label-inline">{key}</span>
							<input
								class="planner-text-input"
								type="text"
								value={fieldValue(key, value)}
								oninput={(e) => setDraftValue(key, (e.currentTarget as HTMLInputElement).value)}
								onblur={() => commitValue(key, value)}
								onkeydown={(e) => {
									if (e.key === 'Enter') {
										e.preventDefault();
										commitValue(key, value);
									}
								}}
							/>
						</label>
					{/each}
				{/if}
			{/if}
		</div>
	</div>
</div>

<style>
	.planner-panel-body { display: grid; gap: 12px; min-height: 0; overflow: auto; padding-right: 4px; }
	.planner-object-section { border: 1px solid rgba(0, 0, 0, 0.08); border-radius: 12px; background: rgba(255, 255, 255, 0.6); overflow: hidden; }
	.planner-object-header { display: flex; align-items: center; gap: 6px; padding: 8px 10px; background: rgba(0, 0, 0, 0.02); border-bottom: 1px solid rgba(0, 0, 0, 0.06); }
	.planner-object-title-stack { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; flex: 1; min-width: 0; }
	.planner-chain { display: grid; gap: 8px; padding: 8px 10px 10px; }
	.planner-context-field { display: flex; flex-direction: column; gap: 6px; padding: 8px; border-radius: 10px; background: rgba(255, 255, 255, 0.5); border: 1px solid rgba(0, 0, 0, 0.06); }
	.planner-checkbox-row { flex-direction: row; align-items: center; justify-content: space-between; }
	.planner-label-inline { font-size: 12px; font-weight: 500; color: #666; }
	.planner-text-input { width: 100%; box-sizing: border-box; border-radius: 12px; border: 1px solid rgba(0, 0, 0, 0.1); background: rgba(255, 255, 255, 0.8); color: #1a1a1a; padding: 8px 10px; font: inherit; font-size: 13px; }
	.planner-structure-help { margin: 0; font-size: 12px; color: #64748b; }
</style>
