<script lang="ts">
	type MetaObject = {
		id: string;
		sim?: string;
		params: Record<string, string>;
		paramSources: Record<string, string>;
		controls: MetaControl[];
	};

	type MetaControl = {
		kind: string;
		key: string;
		label: string;
		min?: string;
		max?: string;
		step?: string;
		options?: string[];
	};

	let {
		liveObjText = '',
		onLiveObjMetadataChange
	}: {
		liveObjText?: string;
		onLiveObjMetadataChange?: (updatedLiveObjText: string) => void;
	} = $props();

	// Ensure liveObjText is always a string
	const safeLiveObjText = $derived(String(liveObjText ?? ''));

	const splitTopLevel = (raw: string): string[] => {
		if (typeof raw !== 'string') return [];
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
		if (typeof raw !== 'string') return {};
		const map: Record<string, string> = {};
		for (const piece of splitTopLevel(raw)) {
			if (typeof piece !== 'string') continue;
			const eq = String(piece).indexOf('=');
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

	const splitTopLevelWhitespace = (raw: string): string[] => {
		const out: string[] = [];
		let buf = '';
		let depth = 0;
		for (const ch of raw) {
			if (ch === '[' || ch === '{' || ch === '(') depth += 1;
			if (ch === ']' || ch === '}' || ch === ')') depth = Math.max(0, depth - 1);
			if (/\s/.test(ch) && depth === 0) {
				if (buf.trim()) out.push(buf.trim());
				buf = '';
				continue;
			}
			buf += ch;
		}
		if (buf.trim()) out.push(buf.trim());
		return out;
	};

	const parseTokenParams = (raw: string): Record<string, string> => {
		const map: Record<string, string> = {};
		for (const token of splitTopLevelWhitespace(raw)) {
			const eq = token.indexOf('=');
			if (eq <= 0) continue;
			const key = token.slice(0, eq).trim();
			const value = token.slice(eq + 1).trim();
			if (key) map[key] = value;
		}
		return map;
	};

	const serializeTokenParams = (params: Record<string, string>) =>
		Object.entries(params)
			.map(([k, v]) => `${k}=${v}`)
			.join(' ');

	const controlFromTokens = (kind: string, params: Record<string, string>): MetaControl | null => {
		const key = params.key ?? params.param ?? params.name;
		if (!key) return null;
		const label = (params.label ?? key).replaceAll('_', ' ');
		const rawOptions = params.options ?? params.values ?? '';
		const options = rawOptions
			? rawOptions
					.split(/[|,]/)
					.map((v) => v.trim())
					.filter(Boolean)
			: undefined;
		return {
			kind,
			key,
			label,
			...(params.min !== undefined ? { min: params.min } : {}),
			...(params.max !== undefined ? { max: params.max } : {}),
			...(params.step !== undefined ? { step: params.step } : {}),
			...(options && options.length > 0 ? { options } : {})
		};
	};

	const parseObjects = (text: string): MetaObject[] => {
		if (typeof text !== 'string') return [];
		try {
			const lines = text.split(/\r?\n/);
			const objects: MetaObject[] = [];
			let activeObject: string | null = null;
			let activeSim: string | undefined;
			let activeParams: Record<string, string> | null = null;
			let activeDerivedParams: Record<string, string> | null = null;
			let activeParamSources: Record<string, string> = {};
			let activeControls: MetaControl[] = [];
			let block: 'sdf' | 'recipe' | 'params' | 'anchors' | 'ops' | 'controls' | 'other' = 'other';
			let recipeIndex = 0;
			const flushActive = () => {
				if (!activeObject) return;
				const merged: Record<string, string> = {
					...(activeDerivedParams ?? {}),
					...(activeParams ?? {})
				};
				if (Object.keys(merged).length === 0 && activeControls.length === 0) return;
				const sources: Record<string, string> = {};
				for (const [key, source] of Object.entries(activeParamSources)) sources[key] = source;
				for (const key of Object.keys(activeParams ?? {})) sources[key] = 'params';
				objects.push({
					id: activeObject,
					sim: activeSim,
					params: merged,
					paramSources: sources,
					controls: activeControls
				});
			};
			for (let i = 0; i < lines.length; i += 1) {
				const line = lines[i].trim();
				const objectMatch = line.match(/^o\s+(.+)$/);
				if (objectMatch) {
					flushActive();
					activeObject = objectMatch[1]?.trim() ?? null;
					activeSim = undefined;
					activeParams = null;
					activeDerivedParams = null;
					activeParamSources = {};
					activeControls = [];
					block = 'other';
					recipeIndex = 0;
					continue;
				}
				if (!activeObject) continue;
				if (!line.startsWith('#@')) {
					if (line.length === 0) block = 'other';
					continue;
				}
				const simMatch = line.match(/^#@sim:\s*(.+)$/);
				if (simMatch && typeof simMatch[1] === 'string') {
					activeSim = simMatch[1].trim();
					continue;
				}
				if (line.match(/^#@sdf:\s*$/)) {
					block = 'sdf';
					continue;
				}
				if (line.match(/^#@recipe:\s*$/)) {
					block = 'recipe';
					continue;
				}
				if (line.match(/^#@controls:\s*$/)) {
					block = 'controls';
					continue;
				}
				if (line.match(/^#@ops:\s*$/)) {
					block = 'ops';
					continue;
				}
				if (line.match(/^#@anchors:\s*$/)) {
					block = 'anchors';
					continue;
				}
				const paramsMatch = line.match(/^#@params:\s*(.+)$/);
				if (paramsMatch && typeof paramsMatch[1] === 'string') {
					activeParams = parseParams(paramsMatch[1]);
					block = 'params';
					continue;
				}
				const opMatch = line.match(/^#@\s*-\s*([a-zA-Z0-9_]+)\s*(.*)$/);
				if (opMatch && typeof opMatch[1] === 'string') {
					const cmd = opMatch[1];
					const rest = typeof opMatch[2] === 'string' ? opMatch[2] : '';
					const parsed = parseTokenParams(rest);
					if (block === 'controls') {
						const control = controlFromTokens(cmd, parsed);
						if (control) activeControls.push(control);
						continue;
					}
					if (Object.keys(parsed).length > 0 && (block === 'sdf' || block === 'recipe')) {
						activeDerivedParams = { ...(activeDerivedParams ?? {}) };
						for (const [k, v] of Object.entries(parsed)) {
							if (block === 'recipe') {
								const key = `recipe.${recipeIndex}.${cmd}.${k}`;
								activeDerivedParams[key] = v;
								activeParamSources[key] = `recipe_op:${i}:${cmd}`;
							} else if (cmd === 'mesh_from_sdf') {
								activeDerivedParams[k] = v;
								activeParamSources[k] = 'sdf_mesh_from_sdf';
							} else {
								const key = `${cmd}.${k}`;
								activeDerivedParams[key] = v;
								activeParamSources[key] = `sdf_op:${cmd}`;
							}
						}
					}
					if (block === 'recipe') recipeIndex += 1;
				}
			}
			flushActive();
			return objects;
		} catch (e) {
			console.error('parseObjects error:', e);
			return [];
		}
	};

	const rewriteParamInLiveObj = (
		text: string,
		objectId: string,
		key: string,
		value: string,
		source: string
	) => {
		if (typeof text !== 'string') return text;
		const lines = text.split(/\r?\n/);
		let activeObject: string | null = null;
		let targetObjectLine = -1;
		let updatedExistingParam = false;
		for (let i = 0; i < lines.length; i += 1) {
			const rawLine = lines[i];
			const trimmed = rawLine.trim();
			const objectMatch = trimmed.match(/^o\s+(.+)$/);
			if (objectMatch) {
				activeObject = objectMatch[1].trim();
				if (activeObject === objectId) targetObjectLine = i;
				continue;
			}
			if (activeObject !== objectId) continue;
			if (source === 'params') {
				const paramsMatch = trimmed.match(/^#@params:\s*(.+)$/);
				if (!paramsMatch || typeof paramsMatch[1] !== 'string') continue;
				const parsed = parseParams(paramsMatch[1]);
				parsed[key] = value.trim();
				lines[i] = `#@params: ${serializeParams(parsed)}`;
				updatedExistingParam = true;
				break;
			}
			if (source === 'sdf_mesh_from_sdf') {
				const sdfMeshMatch = trimmed.match(/^#@\s*-\s*mesh_from_sdf\s+(.+)$/);
				if (!sdfMeshMatch || typeof sdfMeshMatch[1] !== 'string') continue;
				const parsed = parseTokenParams(sdfMeshMatch[1]);
				parsed[key] = value.trim();
				lines[i] = `#@ - mesh_from_sdf ${serializeTokenParams(parsed)}`;
				break;
			}
			if (source.startsWith('sdf_op:')) {
				const cmd = source.slice('sdf_op:'.length);
				if (typeof key !== 'string') continue;
				const dot = String(key).indexOf('.');
				const rawKey = dot > 0 ? key.slice(dot + 1) : key;
				const sdfCmdMatch = trimmed.match(/^#@\s*-\s*([a-zA-Z0-9_]+)\s+(.+)$/);
				if (!sdfCmdMatch || sdfCmdMatch[1] !== cmd || typeof sdfCmdMatch[2] !== 'string') continue;
				const parsed = parseTokenParams(sdfCmdMatch[2]);
				parsed[rawKey] = value.trim();
				lines[i] = `#@ - ${cmd} ${serializeTokenParams(parsed)}`;
				break;
			}
			if (source.startsWith('recipe_op:')) {
				const [, lineNumberRaw, cmd] = source.split(':');
				const lineNumber = Number(lineNumberRaw);
				if (!Number.isInteger(lineNumber) || lineNumber < 0 || lineNumber >= lines.length) continue;
				const targetLine = lines[lineNumber]?.trim() ?? '';
				const recipeCmdMatch = targetLine.match(/^#@\s*-\s*([a-zA-Z0-9_]+)\s*(.*)$/);
				if (!recipeCmdMatch || recipeCmdMatch[1] !== cmd || typeof recipeCmdMatch[2] !== 'string')
					continue;
				const rawKey = key.split('.').slice(3).join('.');
				if (!rawKey) continue;
				const parsed = parseTokenParams(recipeCmdMatch[2]);
				parsed[rawKey] = value.trim();
				lines[lineNumber] = `#@ - ${cmd} ${serializeTokenParams(parsed)}`;
				break;
			}
		}
		if (source === 'params' && targetObjectLine >= 0 && !updatedExistingParam) {
			lines.splice(targetObjectLine + 1, 0, `#@params: ${key}=${value.trim()}`);
		}
		return lines.join('\n');
	};

	const metaObjects = $derived(parseObjects(safeLiveObjText));
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
		selectedObjectId ? (metaObjects.find((o) => o.id === selectedObjectId) ?? null) : null
	);

	function fieldValue(key: string, fallback: string) {
		const draftKey = `${selectedObjectId ?? ''}::${key}`;
		return draftValues[draftKey] ?? fallback;
	}

	function displayParamKey(key: string) {
		const recipeMatch = key.match(/^recipe\.\d+\.([^.]+)\.(.+)$/);
		if (recipeMatch) return `${recipeMatch[1]}.${recipeMatch[2]}`;
		return key;
	}

	function controlValue(control: MetaControl) {
		return selectedMetaObject?.params[control.key] ?? control.options?.[0] ?? control.min ?? '';
	}

	function setDraftValue(key: string, value: string) {
		const draftKey = `${selectedObjectId ?? ''}::${key}`;
		draftValues = { ...draftValues, [draftKey]: value };
	}

	function commitValue(key: string, fallback: string) {
		if (!selectedMetaObject) return;
		const nextValue = fieldValue(key, fallback);
		if (nextValue === fallback) return;
		try {
			const updated = rewriteParamInLiveObj(
				safeLiveObjText,
				selectedMetaObject.id,
				key,
				nextValue,
				selectedMetaObject.paramSources[key] ??
					(key.includes('.') ? `sdf_op:${key.split('.', 1)[0]}` : 'params')
			);
			onLiveObjMetadataChange?.(updated);
		} catch (e) {
			console.error('commitValue error:', e);
			throw e;
		}
	}

	const friendlyNumber = (key: string, fallback: string) =>
		selectedMetaObject?.params[key] ?? fallback;

	const friendlyBool = (key: string, fallback = false) => {
		const value = selectedMetaObject?.params[key];
		if (value === undefined) return fallback;
		return !['0', 'false', 'no', 'off', ''].includes(String(value).trim().toLowerCase());
	};

	function commitFriendlyValue(key: string, value: string) {
		if (!selectedMetaObject) return;
		try {
			const updated = rewriteParamInLiveObj(
				safeLiveObjText,
				selectedMetaObject.id,
				key,
				value,
				'params'
			);
			onLiveObjMetadataChange?.(updated);
		} catch (e) {
			console.error('commitFriendlyValue error:', e);
			throw e;
		}
	}

	function friendlyCurveDetail() {
		return friendlyNumber(
			'curve_points',
			selectedMetaObject?.params.points ?? selectedMetaObject?.params.section_points ?? '300'
		);
	}
</script>

<div class="planner-object-section">
	<div class="planner-object-header">
		<div class="planner-object-title-stack"><strong>Live OBJ Metadata Params</strong></div>
	</div>
	<div class="planner-chain">
		{#if metaObjects.length === 0}
			<p class="planner-structure-help">
				No editable metadata parameters found in current Live OBJ.
			</p>
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
				{#if selectedMetaObject.controls.length > 0}
					<div class="growth-control-panel">
						<div class="growth-control-heading">
							<strong>Controls</strong>
							<span>Curated parameters for this recipe.</span>
						</div>
						{#each selectedMetaObject.controls as control}
							{#if control.kind === 'checkbox' || control.kind === 'toggle'}
								<label class="planner-context-field growth-checkbox-field">
									<span class="planner-label-inline">{control.label}</span>
									<input
										type="checkbox"
										checked={friendlyBool(control.key, false)}
										onchange={(e) =>
											commitFriendlyValue(
												control.key,
												(e.currentTarget as HTMLInputElement).checked ? 'true' : 'false'
											)}
									/>
								</label>
							{:else if control.kind === 'select' || control.kind === 'enum'}
								<label class="planner-context-field">
									<span class="planner-label-inline">{control.label}</span>
									<select
										class="planner-text-input"
										value={controlValue(control)}
										onchange={(e) =>
											commitFriendlyValue(
												control.key,
												(e.currentTarget as HTMLSelectElement).value
											)}
									>
										{#each control.options ?? [] as option}
											<option value={option}>{option}</option>
										{/each}
									</select>
								</label>
							{:else}
								<label class="planner-context-field">
									<span class="planner-label-inline">{control.label}</span>
									<input
										class={control.kind === 'slider' ||
										control.kind === 'range' ||
										control.kind === 'seed'
											? 'planner-range-input'
											: 'planner-text-input'}
										type={control.kind === 'slider' ||
										control.kind === 'range' ||
										control.kind === 'seed'
											? 'range'
											: 'number'}
										min={control.min}
										max={control.max}
										step={control.step ?? (control.kind === 'seed' ? '1' : undefined)}
										value={controlValue(control)}
										onchange={(e) =>
											commitFriendlyValue(control.key, (e.currentTarget as HTMLInputElement).value)}
									/>
									<span class="growth-value">{controlValue(control)}</span>
								</label>
							{/if}
						{/each}
					</div>
				{/if}
				{#if selectedMetaObject.sim === 'differential_growth_stack'}
					<div class="growth-control-panel">
						<div class="growth-control-heading">
							<strong>Growth column controls</strong>
							<span>Simple handles for the simulation.</span>
						</div>
						<label class="planner-context-field">
							<span class="planner-label-inline">Curve detail</span>
							<input
								class="planner-range-input"
								type="range"
								min="80"
								max="700"
								step="10"
								value={friendlyCurveDetail()}
								onchange={(e) =>
									commitFriendlyValue('curve_points', (e.currentTarget as HTMLInputElement).value)}
							/>
							<span class="growth-value">{friendlyCurveDetail()}</span>
						</label>
						<label class="planner-context-field">
							<span class="planner-label-inline">Smooth bottom</span>
							<input
								class="planner-range-input"
								type="range"
								min="0"
								max="8"
								step="1"
								value={friendlyNumber('seed_smooth', '3')}
								onchange={(e) =>
									commitFriendlyValue('seed_smooth', (e.currentTarget as HTMLInputElement).value)}
							/>
							<span class="growth-value">{friendlyNumber('seed_smooth', '3')}</span>
						</label>
						<label class="planner-context-field growth-checkbox-field">
							<span class="planner-label-inline">Show simple bottom curve</span>
							<input
								type="checkbox"
								checked={friendlyBool('show_seed_section', false)}
								onchange={(e) =>
									commitFriendlyValue(
										'show_seed_section',
										(e.currentTarget as HTMLInputElement).checked ? 'true' : 'false'
									)}
							/>
						</label>
						<label class="planner-context-field growth-checkbox-field">
							<span class="planner-label-inline">Keep same point count</span>
							<input
								type="checkbox"
								checked={friendlyBool('fixed_point_count', true)}
								onchange={(e) =>
									commitFriendlyValue(
										'fixed_point_count',
										(e.currentTarget as HTMLInputElement).checked ? 'true' : 'false'
									)}
							/>
						</label>
						<label class="planner-context-field">
							<span class="planner-label-inline">Growth ramp</span>
							<input
								class="planner-range-input"
								type="range"
								min="0"
								max="400"
								step="10"
								value={friendlyNumber('growth_ramp_steps', '120')}
								onchange={(e) =>
									commitFriendlyValue(
										'growth_ramp_steps',
										(e.currentTarget as HTMLInputElement).value
									)}
							/>
							<span class="growth-value">{friendlyNumber('growth_ramp_steps', '120')}</span>
						</label>
						<label class="planner-context-field">
							<span class="planner-label-inline">Curve spacing</span>
							<input
								class="planner-text-input"
								type="number"
								min="0.005"
								max="0.2"
								step="0.002"
								value={friendlyNumber('target_spacing', '0.034')}
								onchange={(e) =>
									commitFriendlyValue(
										'target_spacing',
										(e.currentTarget as HTMLInputElement).value
									)}
							/>
							<span class="growth-value">{friendlyNumber('target_spacing', '0.034')}</span>
						</label>
						<label class="planner-context-field">
							<span class="planner-label-inline">Growth strength</span>
							<input
								class="planner-text-input"
								type="number"
								min="0"
								max="0.05"
								step="0.0005"
								value={friendlyNumber('growth_pressure', '0.0055')}
								onchange={(e) =>
									commitFriendlyValue(
										'growth_pressure',
										(e.currentTarget as HTMLInputElement).value
									)}
							/>
							<span class="growth-value">{friendlyNumber('growth_pressure', '0.0055')}</span>
						</label>
						<label class="planner-context-field">
							<span class="planner-label-inline">Step size</span>
							<input
								class="planner-text-input"
								type="number"
								min="0.0002"
								max="0.02"
								step="0.0002"
								value={friendlyNumber('vector_step', '0.0018')}
								onchange={(e) =>
									commitFriendlyValue('vector_step', (e.currentTarget as HTMLInputElement).value)}
							/>
							<span class="growth-value">{friendlyNumber('vector_step', '0.0018')}</span>
						</label>
						<label class="planner-context-field">
							<span class="planner-label-inline">Start size</span>
							<input
								class="planner-range-input"
								type="range"
								min="0.05"
								max="0.98"
								step="0.01"
								value={friendlyNumber('seed_scale', '0.2')}
								onchange={(e) =>
									commitFriendlyValue('seed_scale', (e.currentTarget as HTMLInputElement).value)}
							/>
							<span class="growth-value">{friendlyNumber('seed_scale', '0.2')}</span>
						</label>
					</div>
					<details class="growth-advanced">
						<summary>Advanced metadata</summary>
						{#each Object.entries(selectedMetaObject.params) as [key, value]}
							<label class="planner-context-field">
								<span class="planner-label-inline">{displayParamKey(key)}</span>
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
					</details>
				{:else}
					{#each Object.entries(selectedMetaObject.params) as [key, value]}
						<label class="planner-context-field">
							<span class="planner-label-inline">{displayParamKey(key)}</span>
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
		{/if}
	</div>
</div>

<style>
	.growth-control-panel {
		display: grid;
		gap: 10px;
	}

	.growth-control-heading {
		display: grid;
		gap: 3px;
	}

	.growth-control-heading span {
		color: #666;
		font-size: 13px;
	}

	.planner-range-input {
		box-sizing: border-box;
		width: 100%;
		accent-color: #0000eb;
	}

	.growth-value {
		color: #666;
		font-size: 12px;
	}

	.growth-checkbox-field {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.growth-checkbox-field input {
		accent-color: #0000eb;
		width: 18px;
		height: 18px;
	}

	.growth-advanced {
		margin-top: 4px;
	}

	.growth-advanced summary {
		cursor: pointer;
		font-weight: 700;
		padding: 8px 0;
	}
</style>
