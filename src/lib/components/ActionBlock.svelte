<script lang="ts">
	import ParamField from './ParamField.svelte';
	import { runtimeAssets } from '$lib/spellshape/runtime/assets.js';

	type ActionLike = {
		op: string;
		params?: Record<string, any>;
		as?: string;
	};

	type ParamsSchema = Record<string, any>;

	export let action: ActionLike;
	export let actionIdx = 0;
	export let isVisible = true;
	export let onVisibilityToggle = () => {};
	export let onParamChange: (key: string, val: unknown) => void = () => {};
	export let onAsChange: (val: string | undefined) => void = () => {};
	export let onInputsChange: (vals: string[]) => void = () => {};
	export let materialRef: string = '';
	export let onMaterialRefChange: (val: string) => void = () => {};
	export let availableMaterials: Array<{ id: string; label?: string }> = [];
	export let availableRefOptions: string[] = [];
	export let onRemove: (() => void) | undefined = undefined;

	let localIsVisible = true;

	const SG_GROUPS = [
		{
			label: 'Grid Layout',
			icon: '⊞',
			params: ['footprint', 'gridX', 'gridZ', 'columnInset', 'contour', 'density'],
			open: false
		},
		{ label: 'Foundation', icon: '▭', params: ['foundation'], open: false },
		{ label: 'Columns', icon: '▌', params: ['column'], open: false },
		{ label: 'Beams', icon: '═', params: ['beamX', 'beamZ', 'beamMode'], open: false },
		{ label: 'Brackets', icon: '⫘', params: ['brackets'], open: false },
		{ label: 'Roof', icon: '⌂', params: ['roof'], open: false },
		{ label: 'Appearance', icon: '◐', params: ['color'], open: false }
	];
	const CA_PRESETS = [
		{ id: 'balanced_default', label: 'Balanced (Default)', survive: '4-8', born: '5-7' },
		{ id: '3d_brain', label: '3D Brain', survive: '', born: '4' },
		{ id: '445', label: '445', survive: '4', born: '4' },
		{ id: 'architecture', label: 'Architecture', survive: '4-6', born: '3' },
		{ id: 'builder_1', label: 'Builder 1', survive: '2,6,9', born: '4,6,8-9' },
		{ id: 'builder_2', label: 'Builder 2', survive: '5-7', born: '1' },
		{ id: 'clouds_1', label: 'Clouds 1', survive: '13-26', born: '13-14,17-19' },
		{ id: 'clouds_2', label: 'Clouds 2', survive: '12-26', born: '13-14' },
		{ id: 'coral', label: 'Coral', survive: '5-8', born: '6-7,9,12' },
		{ id: 'pyroclastic', label: 'Pyroclastic', survive: '4-7', born: '6-8' },
		{ id: 'sample_1', label: 'Sample 1', survive: '10-26', born: '5,8-26' },
		{ id: 'slow_decay_1', label: 'Slow Decay 1', survive: '13-26', born: '10-26' },
		{
			id: 'spiky_growth',
			label: 'Spiky Growth',
			survive: '0-3,7-9,11-13,18,21-22,24,26',
			born: '13,17,20-26'
		},
		{ id: 'custom', label: 'Custom (manual)', survive: '', born: '' }
	] as const;
	const ADDITIVE_CA_PRESETS = [
		{ id: 'life', label: 'Conway Life', survive: '2-3', born: '3' },
		{ id: 'highlife', label: 'HighLife', survive: '2-3', born: '3,6' },
		{ id: 'maze', label: 'Maze', survive: '1-5', born: '3' },
		{ id: 'seeds', label: 'Seeds', survive: '', born: '2' },
		{ id: 'day_night', label: 'Day & Night', survive: '3,4,6-8', born: '3,6-8' },
		{ id: 'coral_2d', label: 'Coral 2D', survive: '4-8', born: '3' },
		{ id: 'custom', label: 'Custom (manual)', survive: '', born: '' }
	] as const;
	const CA_COLOR_PRESETS = [
		{
			id: 'neighbors_heat',
			label: 'Neighbors Heat',
			colorMode: 'neighbors',
			gradient: ['#1d4ed8', '#22c55e', '#f59e0b', '#ef4444']
		},
		{
			id: 'neighbors_viridis',
			label: 'Neighbors Viridis',
			colorMode: 'neighbors',
			gradient: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725']
		},
		{
			id: 'distance_ocean',
			label: 'Distance Ocean',
			colorMode: 'distance',
			gradient: ['#0f172a', '#1d4ed8', '#22d3ee', '#ecfeff']
		},
		{
			id: 'distance_terrain',
			label: 'Distance Terrain',
			colorMode: 'distance',
			gradient: ['#1f2937', '#166534', '#ca8a04', '#f8fafc']
		},
		{
			id: 'generation_fire',
			label: 'Generation Fire',
			colorMode: 'generation',
			gradient: ['#111827', '#7c2d12', '#ea580c', '#fde047']
		},
		{
			id: 'generation_neon',
			label: 'Generation Neon',
			colorMode: 'generation',
			gradient: ['#020617', '#7e22ce', '#2563eb', '#22c55e']
		},
		{ id: 'solid_slate', label: 'Solid Slate', colorMode: 'solid', gradient: ['#94a3b8'] },
		{ id: 'solid_white', label: 'Solid White', colorMode: 'solid', gradient: ['#ffffff'] },
		{ id: 'custom', label: 'Custom gradient', colorMode: 'solid', gradient: [] }
	] as const;
	const ADDITIVE_CA_COLOR_PRESETS = [
		{
			id: 'gen_terrain',
			label: 'Generation Terrain',
			colorMode: 'generation',
			gradient: ['#1f2937', '#166534', '#ca8a04', '#f8fafc']
		},
		{
			id: 'gen_sunset',
			label: 'Generation Sunset',
			colorMode: 'generation',
			gradient: ['#312e81', '#9333ea', '#f97316', '#fde68a']
		},
		{
			id: 'gen_ocean',
			label: 'Generation Ocean',
			colorMode: 'generation',
			gradient: ['#0f172a', '#1d4ed8', '#22d3ee', '#ecfeff']
		},
		{ id: 'solid_blueprint', label: 'Solid Blueprint', colorMode: 'solid', gradient: ['#1d4ed8'] },
		{ id: 'solid_sandstone', label: 'Solid Sandstone', colorMode: 'solid', gradient: ['#d6b48a'] },
		{ id: 'custom', label: 'Custom gradient', colorMode: 'solid', gradient: [] }
	] as const;

	function getReg(): any {
		return typeof window !== 'undefined' ? (window as any).ActionRegistry : null;
	}

	function buildMergedParams(schema: ParamsSchema = {}, actual: Record<string, any> = {}) {
		const out: Record<string, any> = {};
		// First, include all params from schema with their defaults
		for (const [k, def] of Object.entries(schema || {})) {
			if (def?.default !== undefined) out[k] = def.default;
			else if (def?.type === 'geometry') out[k] = '';
			else out[k] = undefined;
		}
		// Then override with actual values if provided
		for (const [k, v] of Object.entries(actual || {})) {
			if (k in schema) out[k] = v;
		}
		return out;
	}

	function isNestedActionArray(v: unknown): v is Array<ActionLike> {
		return (
			Array.isArray(v) &&
			v.length > 0 &&
			v.every((i) => i && typeof i === 'object' && 'op' in i && 'params' in i)
		);
	}

	function schemaForOp(op: string) {
		const regSchema = getReg()?.get?.(op)?.paramsSchema;
		if (regSchema && typeof regSchema === 'object') return regSchema;
		const card = runtimeAssets.operatorCards.find((entry) => entry.id === op);
		return (card?.parameterSchema as Record<string, unknown>) || {};
	}

	function getMergedNested(na: ActionLike) {
		return buildMergedParams(schemaForOp(na.op), na.params);
	}

	function expandRuleList(spec: string): number[] {
		if (!spec.trim()) return [];
		const out: number[] = [];
		for (const token of spec
			.split(',')
			.map((entry) => entry.trim())
			.filter(Boolean)) {
			if (token.includes('-')) {
				const [startRaw, endRaw] = token.split('-');
				const start = Number(startRaw);
				const end = Number(endRaw);
				if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
				const min = Math.min(start, end);
				const max = Math.max(start, end);
				for (let n = min; n <= max; n++) out.push(n);
			} else {
				const value = Number(token);
				if (Number.isFinite(value)) out.push(value);
			}
		}
		return Array.from(new Set(out)).sort((a, b) => a - b);
	}

	function parseRules(value: unknown): { survive: number[]; born: number[] } | null {
		try {
			const parsed = typeof value === 'string' ? JSON.parse(value) : value;
			if (!parsed || typeof parsed !== 'object') return null;
			const survive = Array.isArray((parsed as any).survive)
				? (parsed as any).survive.map(Number).filter(Number.isFinite)
				: [];
			const born = Array.isArray((parsed as any).born)
				? (parsed as any).born.map(Number).filter(Number.isFinite)
				: [];
			return {
				survive: [...new Set(survive)].sort((a, b) => a - b),
				born: [...new Set(born)].sort((a, b) => a - b)
			};
		} catch {
			return null;
		}
	}

	function arraysEqual(a: number[], b: number[]) {
		return a.length === b.length && a.every((value, index) => value === b[index]);
	}

	function matchPresetIdFromRules(
		value: unknown,
		presets: ReadonlyArray<{ id: string; survive: string; born: string }>
	) {
		const parsed = parseRules(value);
		if (!parsed) return 'custom';
		const preset = presets.find((entry) => {
			if (entry.id === 'custom') return false;
			const survive = expandRuleList(entry.survive);
			const born = expandRuleList(entry.born);
			return arraysEqual(parsed.survive, survive) && arraysEqual(parsed.born, born);
		});
		return preset?.id ?? 'custom';
	}

	function applyCAPreset(
		presetId: string,
		presets: ReadonlyArray<{ id: string; survive: string; born: string }>
	) {
		if (presetId === 'custom') return;
		const preset = presets.find((entry) => entry.id === presetId);
		if (!preset) return;
		const rules = {
			survive: expandRuleList(preset.survive),
			born: expandRuleList(preset.born)
		};
		onParamChange('rules', JSON.stringify(rules));
	}

	function normalizeHexColor(value: unknown) {
		if (typeof value !== 'string') return '#94a3b8';
		const trimmed = value.trim();
		return /^#[0-9a-fA-F]{6}$/.test(trimmed) ? trimmed : '#94a3b8';
	}

	function normalizeGradient(value: unknown): string[] {
		if (!Array.isArray(value)) return [];
		return value
			.filter(
				(entry): entry is string =>
					typeof entry === 'string' && /^#[0-9a-fA-F]{6}$/.test(entry.trim())
			)
			.map((entry) => entry.trim().toLowerCase());
	}

	function normalizeAlias(value: unknown) {
		if (typeof value !== 'string') return '';
		return value.trim().replace(/^@/, '');
	}

	function parseRefArray(value: unknown): string[] {
		if (Array.isArray(value)) {
			return Array.from(
				new Set(value.map((entry) => normalizeAlias(entry)).filter((entry) => entry.length > 0))
			);
		}
		if (typeof value === 'string') {
			return Array.from(
				new Set(
					value
						.split(',')
						.map((entry) => normalizeAlias(entry))
						.filter((entry) => entry.length > 0)
				)
			);
		}
		return [];
	}

	function asRefArray(values: string[]) {
		return values.map((value) => `@${normalizeAlias(value)}`).filter((value) => value !== '@');
	}

	function gradientsEqual(a: string[], b: string[]) {
		return a.length === b.length && a.every((value, idx) => value === b[idx]);
	}

	function gradientToCsv(value: unknown) {
		const gradient = normalizeGradient(value);
		return gradient.length > 0 ? gradient.join(', ') : '';
	}

	function parseGradientCsv(value: string) {
		return value
			.split(',')
			.map((entry) => entry.trim())
			.filter((entry) => /^#[0-9a-fA-F]{6}$/.test(entry));
	}

	function matchColorPresetId(
		mode: unknown,
		gradientValue: unknown,
		presets: ReadonlyArray<{ id: string; colorMode: string; gradient: string[] }>
	) {
		const normalizedMode = typeof mode === 'string' ? mode : 'solid';
		const normalizedGradient = normalizeGradient(gradientValue);
		const preset = presets.find((entry) => {
			if (entry.id === 'custom') return false;
			return (
				entry.colorMode === normalizedMode &&
				gradientsEqual(
					entry.gradient.map((v) => v.toLowerCase()),
					normalizedGradient
				)
			);
		});
		return preset?.id ?? 'custom';
	}

	function applyCAColorPreset(
		presetId: string,
		presets: ReadonlyArray<{ id: string; colorMode: string; gradient: string[] }>
	) {
		if (presetId === 'custom') return;
		const preset = presets.find((entry) => entry.id === presetId);
		if (!preset) return;
		onParamChange('colorMode', preset.colorMode);
		onParamChange('colorGradient', preset.gradient);
		onParamChange('color', preset.gradient[0] ?? '#94a3b8');
	}

	function updateNestedAction(
		nestedParamKey: string,
		nestedIdx: number,
		paramKey: string,
		paramVal: unknown
	) {
		const arr = [...((mergedParams[nestedParamKey] as Array<ActionLike>) || [])];
		arr[nestedIdx] = {
			...arr[nestedIdx],
			params: { ...arr[nestedIdx].params, [paramKey]: paramVal }
		};
		onParamChange(nestedParamKey, arr);
	}

	function toReadableLabel(value: unknown) {
		if (!value) return 'unknown';
		return String(value)
			.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
			.replace(/[-_.]+/g, ' ')
			.replace(/\s+/g, ' ')
			.trim()
			.replace(/^./, (char) => char.toUpperCase());
	}

	function handleVisibilityToggle() {
		localIsVisible = !localIsVisible;
		onVisibilityToggle();
	}

	function handleRemove() {
		if (onRemove) onRemove();
	}

	$: reg = getReg();
	$: regEntry = action ? reg?.get?.(action.op) || null : null;
	$: schema = schemaForOp(action?.op || '') as ParamsSchema;
	$: isSG = action?.op === 'structuralGrid';
	$: isFacadeAgent = action?.op === 'facadeAgent';
	$: isCellularAutomata =
		action?.op === 'cellularAutomata' || action?.op === 'cellularAutomataOnMesh';
	$: isAdditiveCellularAutomata = action?.op === 'additiveCellularAutomata';
	$: isAnyCellularAutomata = isCellularAutomata || isAdditiveCellularAutomata;
	$: isGroupingAction = action.op === 'group' || action.op === 'mergeGroup';
	$: activeRulePresets = isAdditiveCellularAutomata ? ADDITIVE_CA_PRESETS : CA_PRESETS;
	$: activeColorPresets = isAdditiveCellularAutomata ? ADDITIVE_CA_COLOR_PRESETS : CA_COLOR_PRESETS;
	$: mergedParams = action ? buildMergedParams(schema, action.params ?? {}) : {};
	const CELLULAR3D_CONTROL_KEYS = [
		'gridSize',
		'iterations',
		'surfaceMode',
		'outputMode',
		'seedMode',
		'seed',
		'seedDensity',
		'extent',
		'cumulative'
	];
	const ADDITIVE_CONTROL_KEYS = [
		'gridSize',
		'generations',
		'cellSize',
		'floorHeight',
		'outputMode',
		'seed',
		'initialDensity'
	];
	const CELLULAR_UI_KEYS = [
		'rules',
		'colorMode',
		'colorGradient',
		'color',
		...CELLULAR3D_CONTROL_KEYS,
		...ADDITIVE_CONTROL_KEYS
	];
	const CELLULAR_FALLBACK_SCHEMA: Record<string, any> = {
		gridSize: { type: 'number', default: 10, description: 'Grid size' },
		iterations: { type: 'number', default: 1, description: 'Simulation iterations' },
		generations: { type: 'number', default: 10, description: 'Simulation generations' },
		surfaceMode: { type: 'string', default: 'sharp', description: 'Surface mode: sharp or smooth' },
		outputMode: { type: 'string', default: 'surface', description: 'Output mode' },
		seedMode: { type: 'string', default: 'center', description: 'Seeding mode' },
		seed: { type: 'number', default: 12345, description: 'Random seed' },
		seedDensity: { type: 'number', default: 1, description: 'Seed density' },
		extent: { type: 'number', default: 5, description: 'Fallback extent' },
		cumulative: {
			type: 'boolean',
			default: false,
			description: 'Accumulate cells over iterations'
		},
		cellSize: { type: 'number', default: 2, description: 'Cell size' },
		floorHeight: { type: 'number', default: 3, description: 'Floor height' },
		initialDensity: { type: 'number', default: 0.3, description: 'Initial alive density' }
	};
	$: filteredMergedParams = Object.fromEntries(
		Object.entries(mergedParams).filter(
			([key]) =>
				!['roughness', 'metalness'].includes(key) &&
				!(isFacadeAgent && ['wallMaterial', 'glassMaterial'].includes(key)) &&
				!(isAnyCellularAutomata && CELLULAR_UI_KEYS.includes(key))
		)
	);
	$: selectedWallMaterial =
		typeof mergedParams.wallMaterial === 'string' ? mergedParams.wallMaterial : '';
	$: selectedGlassMaterial =
		typeof mergedParams.glassMaterial === 'string' ? mergedParams.glassMaterial : '';
	$: activeCAPreset = isAnyCellularAutomata
		? matchPresetIdFromRules(mergedParams.rules, activeRulePresets)
		: 'custom';
	$: activeCAColorPreset = isAnyCellularAutomata
		? matchColorPresetId(mergedParams.colorMode, mergedParams.colorGradient, activeColorPresets)
		: 'custom';
	$: activeCAColor = normalizeHexColor(mergedParams.color);
	$: activeCAGradientCsv = gradientToCsv(mergedParams.colorGradient);
	$: if (localIsVisible !== isVisible) {
		localIsVisible = isVisible;
	}
</script>

<details class="ab-block">
	<summary class="ab-summary">
		<div class="ab-header-line">
			<span class="ab-num">{actionIdx + 1}</span>
			<span class="ab-op">{action ? toReadableLabel(action.op) : 'unknown'}</span>
			{#if action?.sceneRole}
				<span class="ab-badge scene">{action.sceneRole}</span>
			{/if}
			{#if action?.objectRole}
				<span class="ab-badge object">{action.objectRole}</span>
			{/if}
			{#if action?.stage && action.stage !== 'hostGeneration'}
				<span class="ab-badge stage">{action.stage}</span>
			{/if}
		</div>
		<div class="ab-controls-line">
			{#if action?.as}
				<span class="ab-as">{action.as}</span>
			{/if}
			<div class="ab-buttons">
				<button
					type="button"
					class="ab-eye"
					class:visible={localIsVisible}
					on:click|preventDefault|stopPropagation={handleVisibilityToggle}
					title={localIsVisible ? 'Hide in 3D view' : 'Show in 3D view'}
				>
					{#if localIsVisible}
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
							<circle cx="12" cy="12" r="3" />
						</svg>
					{:else}
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path
								d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"
							/>
							<line x1="1" y1="1" x2="23" y2="23" />
						</svg>
					{/if}
				</button>
				{#if onRemove}
					<button
						type="button"
						class="ab-remove"
						on:click|preventDefault|stopPropagation={handleRemove}
						title="Remove action"
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<line x1="18" y1="6" x2="6" y2="18" />
							<line x1="6" y1="6" x2="18" y2="18" />
						</svg>
					</button>
				{/if}
			</div>
		</div>
	</summary>

	<div class="ab-body">
		<!-- Action Name (as) -->
		<div class="ab-as-field">
			<label class="ab-as-label" for="as-{actionIdx}">Layer name</label>
			<input
				id="as-{actionIdx}"
				class="ab-as-input"
				type="text"
				value={action?.as || ''}
				on:input={(e) => onAsChange((e.currentTarget as HTMLInputElement).value || undefined)}
				placeholder="Optional label"
			/>
		</div>
		<div class="ab-as-field">
			<label class="ab-as-label" for="inputs-{actionIdx}">Inputs</label>
			<input
				id="inputs-{actionIdx}"
				class="ab-as-input"
				type="text"
				value={Array.isArray(action?.inputs) ? action.inputs.join(', ') : ''}
				on:input={(e) => {
					const raw = (e.currentTarget as HTMLInputElement).value;
					const parsed = raw
						.split(/[,\n]/)
						.map((token) => token.trim())
						.filter(Boolean)
						.map((token) => (token.startsWith('@') ? token.slice(1) : token));
					onInputsChange(parsed);
				}}
				placeholder="aliasA, aliasB"
			/>
		</div>

		<!-- Parameters -->
		<div class="ab-params">
			{#if !isFacadeAgent}
				<div class="ab-material-ref">
					<label class="ab-ca-label" for="ab-material-ref-{actionIdx}">Material</label>
					<input
						id="ab-material-ref-{actionIdx}"
						class="ab-ca-gradient"
						type="text"
						value={materialRef}
						placeholder="material id (e.g. seat-wood)"
						on:change={(event) =>
							onMaterialRefChange((event.currentTarget as HTMLInputElement).value.trim())}
					/>
				</div>
			{/if}
			{#if isFacadeAgent}
				<div class="ab-facade-materials">
					<label class="ab-ca-label" for="ab-facade-wall-material-{actionIdx}">Wall material</label>
					<select
						id="ab-facade-wall-material-{actionIdx}"
						class="ab-ca-select"
						value={selectedWallMaterial}
						on:change={(event) =>
							onParamChange('wallMaterial', (event.currentTarget as HTMLSelectElement).value)}
					>
						<option value="">None</option>
						{#each availableMaterials as material}
							<option value={material.id}>{material.label ?? material.id}</option>
						{/each}
					</select>
					<label class="ab-ca-label" for="ab-facade-glass-material-{actionIdx}"
						>Glass material</label
					>
					<select
						id="ab-facade-glass-material-{actionIdx}"
						class="ab-ca-select"
						value={selectedGlassMaterial}
						on:change={(event) =>
							onParamChange('glassMaterial', (event.currentTarget as HTMLSelectElement).value)}
					>
						<option value="">None</option>
						{#each availableMaterials as material}
							<option value={material.id}>{material.label ?? material.id}</option>
						{/each}
					</select>
				</div>
			{/if}
			{#if isAnyCellularAutomata}
				<div class="ab-ca-preset">
					<label class="ab-ca-label">Simulation controls</label>
					{#each isCellularAutomata ? CELLULAR3D_CONTROL_KEYS : ADDITIVE_CONTROL_KEYS as caKey}
						<ParamField
							key={caKey}
							schemaDef={schema[caKey] || CELLULAR_FALLBACK_SCHEMA[caKey]}
							value={mergedParams[caKey] ?? CELLULAR_FALLBACK_SCHEMA[caKey]?.default}
							onChange={(v) => onParamChange(caKey, v)}
						/>
					{/each}
				</div>
				<div class="ab-ca-preset">
					<label class="ab-ca-label" for="ca-preset-{actionIdx}">Rule preset</label>
					<select
						id="ca-preset-{actionIdx}"
						class="ab-ca-select"
						value={activeCAPreset}
						on:change={(event) =>
							applyCAPreset((event.currentTarget as HTMLSelectElement).value, activeRulePresets)}
					>
						{#each activeRulePresets as preset}
							<option value={preset.id}>{preset.label}</option>
						{/each}
					</select>
				</div>
				<div class="ab-ca-preset">
					<label class="ab-ca-label" for="ca-color-preset-{actionIdx}">Color preset</label>
					<select
						id="ca-color-preset-{actionIdx}"
						class="ab-ca-select"
						value={activeCAColorPreset}
						on:change={(event) =>
							applyCAColorPreset(
								(event.currentTarget as HTMLSelectElement).value,
								activeColorPresets
							)}
					>
						{#each activeColorPresets as preset}
							<option value={preset.id}>{preset.label}</option>
						{/each}
					</select>
					<label class="ab-ca-label" for="ca-color-{actionIdx}">Cell color</label>
					<input
						id="ca-color-{actionIdx}"
						class="ab-ca-color"
						type="color"
						value={activeCAColor}
						on:input={(event) =>
							onParamChange('color', (event.currentTarget as HTMLInputElement).value)}
					/>
					<label class="ab-ca-label" for="ca-gradient-{actionIdx}">Gradient stops</label>
					<input
						id="ca-gradient-{actionIdx}"
						class="ab-ca-gradient"
						type="text"
						value={activeCAGradientCsv}
						placeholder="#1d4ed8, #22c55e, #f59e0b"
						on:change={(event) => {
							const parsed = parseGradientCsv((event.currentTarget as HTMLInputElement).value);
							if (parsed.length > 0) {
								onParamChange('colorGradient', parsed);
								onParamChange('color', parsed[0]);
							}
						}}
					/>
				</div>
			{/if}
			{#if isAdditiveCellularAutomata}
				<div class="ab-ca-preset">
					<label class="ab-ca-label">Additive CA outputs</label>
					<div class="ab-help">
						Use <code>outputMode: combined</code> to emit both the shell and contour lines.
					</div>
				</div>
			{/if}
			{#if isSG}
				{#each SG_GROUPS as grp}
					{#if grp.params.some((k) => k in mergedParams || k in schema)}
						<details class="ab-sg-grp" open={grp.open}>
							<summary class="ab-sg-sum">{grp.icon} {grp.label}</summary>
							<div class="ab-sg-body">
								{#each grp.params as pk}
									{#if pk in mergedParams || pk in schema}
										<ParamField
											key={pk}
											schemaDef={schema[pk]}
											value={mergedParams[pk]}
											onChange={(v) => onParamChange(pk, v)}
										/>
									{/if}
								{/each}
							</div>
						</details>
					{/if}
				{/each}
			{:else}
				{#each Object.entries(filteredMergedParams) as [pk, pv]}
					{#if isGroupingAction && pk === 'parts'}
						<div class="ab-group-refs">
							<span class="ab-ca-label">Include parts</span>
							{#if availableRefOptions.length === 0}
								<div class="ab-help">No refs available yet — run the chain or add parts first.</div>
							{:else}
								<ul class="ab-group-refs-list" role="group" aria-label="Parts to include">
									{#each availableRefOptions as ref}
										<li class="ab-group-refs-item">
											<label class="ab-group-refs-check-label">
												<input
													type="checkbox"
													class="ab-group-refs-checkbox"
													checked={parseRefArray(pv).includes(normalizeAlias(ref))}
													on:change={(event) => {
														const on = (event.currentTarget as HTMLInputElement).checked;
														const cur = new Set(parseRefArray(pv));
														if (on) cur.add(normalizeAlias(ref));
														else cur.delete(normalizeAlias(ref));
														onParamChange(pk, asRefArray([...cur]));
													}}
												/>
												<span class="ab-group-refs-check-text">{ref}</span>
											</label>
										</li>
									{/each}
								</ul>
							{/if}
						</div>
					{:else if isNestedActionArray(pv)}
						<div class="ab-nested-wrap">
							<div class="ab-nested-hdr">
								{toReadableLabel(pk)} <span class="ab-nested-count">({pv.length})</span>
							</div>
							<div class="ab-nested-list">
								{#each pv as na, ni}
									<details class="ab-nested-item" open={ni === 0}>
										<summary class="ab-nested-sum">
											<span class="ab-nested-num">{ni + 1}</span>
											<span class="ab-nested-op">{toReadableLabel(na.op || 'unknown')}</span>
											{#if na.as}<span class="ab-nested-as">{na.as}</span>{/if}
										</summary>
										<div class="ab-nested-body">
											{#each Object.entries(getMergedNested(na)) as [nk, nv]}
												{#if !isNestedActionArray(nv)}
													<ParamField
														key={nk}
														schemaDef={schemaForOp(na.op)?.[nk]}
														value={nv}
														onChange={(v) => updateNestedAction(pk, ni, nk, v)}
													/>
												{/if}
											{/each}
										</div>
									</details>
								{/each}
							</div>
						</div>
					{:else}
						<ParamField
							key={pk}
							schemaDef={schema[pk]}
							value={pv}
							onChange={(v) => onParamChange(pk, v)}
						/>
					{/if}
				{/each}
			{/if}
		</div>
	</div>
</details>

<style>
	.ab-block {
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.8);
		overflow: hidden;
	}
	.ab-summary {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 10px 12px;
		cursor: pointer;
		user-select: none;
		list-style: none;
		font-size: 14px;
	}
	.ab-summary::-webkit-details-marker {
		display: none;
	}

	.ab-header-line {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
	}

	.ab-controls-line {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-left: 26px;
		flex-shrink: 0;
	}

	.ab-buttons {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.ab-num {
		color: #bbb;
		font-size: 12px;
		min-width: 18px;
		font-weight: 500;
	}
	.ab-op {
		color: #1a1a1a;
		font-weight: 600;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ab-as {
		color: #0000eb;
		font-size: 12px;
		background: rgba(0, 0, 235, 0.06);
		border-radius: 100px;
		padding: 4px 10px;
		font-weight: 500;
		margin-right: auto;
		max-width: 100px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		flex-shrink: 1;
	}

	.ab-badge {
		font-size: 10px;
		padding: 2px 6px;
		border-radius: 4px;
		font-weight: 500;
		margin-left: 6px;
		text-transform: capitalize;
	}
	.ab-badge.scene {
		background: rgba(128, 0, 128, 0.1);
		color: #800080;
	}
	.ab-badge.object {
		background: rgba(0, 128, 0, 0.1);
		color: #008000;
	}
	.ab-badge.stage {
		background: rgba(128, 128, 128, 0.1);
		color: #666;
		font-size: 9px;
	}

	.ab-eye {
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
	.ab-eye:hover {
		opacity: 0.8;
	}
	.ab-eye.visible {
		opacity: 0.7;
	}
	.ab-eye.visible:hover {
		opacity: 1;
	}
	.ab-eye svg {
		width: 16px;
		height: 16px;
		stroke: #666;
	}
	.ab-eye.visible svg {
		stroke: #0000eb;
	}

	.ab-remove {
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
	.ab-remove:hover {
		opacity: 0.8;
	}
	.ab-remove svg {
		width: 14px;
		height: 14px;
		stroke: #c00;
	}

	.ab-body {
		display: flex;
		flex-direction: column;
	}

	/* Action Name (as) field */
	.ab-as-field {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 12px;
		background: rgba(255, 255, 255, 0.5);
		border-top: 1px solid rgba(0, 0, 0, 0.05);
	}
	.ab-as-label {
		font-size: 13px;
		font-weight: 500;
		color: #666;
		white-space: nowrap;
		min-width: fit-content;
	}
	.ab-as-input {
		flex: 1;
		padding: 6px 10px;
		font-size: 14px;
		border: 1px solid rgba(0, 0, 0, 0.1);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.8);
		color: #1a1a1a;
		font-family: inherit;
		transition: all 0.2s;
		max-width: 120px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.ab-as-input:focus {
		outline: none;
		border-color: rgba(0, 0, 235, 0.3);
		background: #fff;
	}
	.ab-as-input::placeholder {
		color: #999;
	}

	/* Params area */
	.ab-params {
		padding: 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		border-top: 1px solid rgba(0, 0, 0, 0.05);
		background: transparent;
	}
	.ab-ca-preset {
		display: grid;
		gap: 6px;
		padding: 8px 10px;
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.8);
	}
	.ab-material-ref {
		display: grid;
		gap: 6px;
		padding: 8px 10px;
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.8);
	}
	.ab-facade-materials {
		display: grid;
		gap: 8px;
		padding: 8px 10px;
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.8);
	}
	.ab-ca-label {
		font-size: 12px;
		font-weight: 600;
		color: #4b5563;
	}
	.ab-help {
		font-size: 12px;
		color: #4b5563;
	}
	.ab-ca-select {
		border: 1px solid rgba(0, 0, 0, 0.16);
		border-radius: 8px;
		padding: 8px 10px;
		font-size: 13px;
		background: #fff;
		color: #1f2937;
	}
	.ab-group-refs {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.ab-group-refs-list {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 220px;
		overflow: auto;
		border: 1px solid rgba(0, 0, 0, 0.12);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.9);
	}
	.ab-group-refs-item {
		margin: 0;
		border-bottom: 1px solid rgba(0, 0, 0, 0.06);
	}
	.ab-group-refs-item:last-child {
		border-bottom: none;
	}
	.ab-group-refs-check-label {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 8px 10px;
		cursor: pointer;
		font-size: 13px;
		color: #1f2937;
	}
	.ab-group-refs-checkbox {
		margin-top: 2px;
		flex-shrink: 0;
	}
	.ab-group-refs-check-text {
		word-break: break-all;
		line-height: 1.35;
	}
	.ab-ca-color {
		width: 100%;
		min-height: 36px;
		border: 1px solid rgba(0, 0, 0, 0.16);
		border-radius: 8px;
		background: #fff;
		padding: 4px;
	}
	.ab-ca-gradient {
		border: 1px solid rgba(0, 0, 0, 0.16);
		border-radius: 8px;
		padding: 8px 10px;
		font-size: 12px;
		background: #fff;
		color: #1f2937;
	}

	/* structuralGrid groups */
	.ab-sg-grp {
		margin: 2px 0;
		border: 1px solid rgba(0, 0, 0, 0.08);
		border-radius: 10px;
		overflow: hidden;
	}
	.ab-sg-sum {
		cursor: pointer;
		list-style: none;
		font-size: 13px;
		font-weight: 600;
		color: #444;
		padding: 10px 12px;
		background: rgba(255, 255, 255, 0.6);
		user-select: none;
	}
	.ab-sg-sum::-webkit-details-marker {
		display: none;
	}
	.ab-sg-body {
		padding: 8px 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		background: rgba(0, 0, 0, 0.02);
	}

	/* Nested actions */
	.ab-nested-wrap {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin: 4px 0;
	}
	.ab-nested-hdr {
		font-size: 13px;
		font-weight: 600;
		color: #666;
		background: transparent;
		padding: 0 4px;
	}
	.ab-nested-count {
		font-weight: 400;
		opacity: 0.7;
	}
	.ab-nested-list {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.ab-nested-item {
		border-radius: 10px;
		background: rgba(255, 255, 255, 0.6);
		border: 1px solid rgba(0, 0, 0, 0.08);
		overflow: hidden;
	}
	.ab-nested-sum {
		cursor: pointer;
		list-style: none;
		font-size: 13px;
		font-weight: 600;
		color: #444;
		background: transparent;
		padding: 10px 12px;
		display: flex;
		align-items: center;
		gap: 8px;
		border-bottom: 1px solid rgba(0, 0, 0, 0.06);
		user-select: none;
	}
	.ab-nested-sum::-webkit-details-marker {
		display: none;
	}
	.ab-nested-num {
		background: rgba(0, 0, 0, 0.1);
		color: #666;
		border-radius: 4px;
		padding: 2px 6px;
		font-size: 11px;
	}
	.ab-nested-op {
		flex: 1;
		color: #1a1a1a;
		font-weight: 600;
	}
	.ab-nested-as {
		color: #0000eb;
		font-size: 12px;
		background: rgba(0, 0, 235, 0.06);
		padding: 2px 8px;
		border-radius: 100px;
		font-weight: 500;
	}
	.ab-nested-body {
		padding: 8px 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		background: rgba(0, 0, 0, 0.02);
	}
</style>
