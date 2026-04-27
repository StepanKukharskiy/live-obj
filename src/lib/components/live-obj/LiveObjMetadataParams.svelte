<script lang="ts">
	type MetaObject = {
		id: string;
		params: Record<string, string>;
	};

	let {
		liveObjText = '',
		onLiveObjMetadataChange
	}: {
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
