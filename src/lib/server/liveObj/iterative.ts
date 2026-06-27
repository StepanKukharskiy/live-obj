import { stripCodeFences } from '$lib/liveObj/stripCodeFences';

export type IterativePartSpec = {
	id: string;
	role?: string;
	prompt?: string;
	subparts?: IterativeSubpartSpec[];
	dependencies?: string[];
	method?: string;
	postProcess?: IterativePartPostProcess;
	priority?: number;
	validationHints?: string[];
	cameraFocus?: string[];
	controls?: IterativeControlSpec[];
	controlPostOps?: string[];
};

export type IterativeSubpartSpec = {
	id: string;
	role?: string;
	prompt?: string;
	dependencies?: string[];
	validationHints?: string[];
};

export type IterativePartPostProcess = {
	type?: string;
	targetObjectId?: string;
	prompt?: string;
	mode?: string;
	amount?: number;
};

export type IterativeControlSpec = {
	key: string;
	label?: string;
	kind?: 'slider' | 'number' | 'seed' | 'toggle' | 'checkbox' | 'select' | 'enum' | string;
	default?: string | number | boolean;
	min?: string | number;
	max?: string | number;
	step?: string | number;
	options?: string[];
};

export type IterativeScenePlan = {
	scene?: string;
	units?: string;
	up?: 'x' | 'y' | 'z' | string;
	visual?: {
		backgroundColor?: string;
		ambientLightIntensity?: number;
		directionalLightIntensity?: number;
		cameraFov?: number;
		toneMappingExposure?: number;
		canvasAspectRatio?: string;
		cameraView?: string;
		cameraFocus?: string[];
	};
	materials?: Array<{
		id: string;
		color?: string;
		roughness?: number;
		metalness?: number;
		role?: string;
	}>;
	parts: IterativePartSpec[];
	notes?: string[];
};

export type LiveObjValidationResult = {
	valid: boolean;
	errors: string[];
	warnings: string[];
	objectNames: string[];
	addedObjectNames: string[];
	vertexCount: number;
	faceCount: number;
	bbox?: { min: [number, number, number]; max: [number, number, number] };
};

type ObjectSummary = {
	name: string;
	source?: string;
	semantic?: string;
	openings: string[];
	vertexCount: number;
	faceCount: number;
	bbox?: { min: [number, number, number]; max: [number, number, number] };
};

const DEFAULT_HEADER = ['#@scene', '#@units: meters', '#@up: y', '#@live_obj_version: 0.1'];

function extractBalancedJsonSlice(content: string): string | null {
	const start = [...content].findIndex((char) => char === '{' || char === '[');
	if (start < 0) return null;
	const stack: string[] = [];
	let inString = false;
	let escaped = false;
	for (let index = start; index < content.length; index += 1) {
		const char = content[index];
		if (inString) {
			if (escaped) {
				escaped = false;
				continue;
			}
			if (char === '\\') {
				escaped = true;
				continue;
			}
			if (char === '"') inString = false;
			continue;
		}
		if (char === '"') {
			inString = true;
			continue;
		}
		if (char === '{') stack.push('}');
		else if (char === '[') stack.push(']');
		else if (char === '}' || char === ']') {
			if (stack.at(-1) !== char) break;
			stack.pop();
			if (stack.length === 0) return content.slice(start, index + 1);
		}
	}
	return null;
}

function analyzeJsonTail(content: string): {
	hasStart: boolean;
	inString: boolean;
	stack: string[];
} {
	const start = [...content].findIndex((char) => char === '{' || char === '[');
	if (start < 0) return { hasStart: false, inString: false, stack: [] };
	const stack: string[] = [];
	let inString = false;
	let escaped = false;
	for (let index = start; index < content.length; index += 1) {
		const char = content[index];
		if (inString) {
			if (escaped) {
				escaped = false;
				continue;
			}
			if (char === '\\') {
				escaped = true;
				continue;
			}
			if (char === '"') inString = false;
			continue;
		}
		if (char === '"') {
			inString = true;
			continue;
		}
		if (char === '{') stack.push('}');
		else if (char === '[') stack.push(']');
		else if (char === '}' || char === ']') {
			if (stack.at(-1) !== char) break;
			stack.pop();
		}
	}
	return { hasStart: true, inString, stack };
}

function jsonPreview(text: string, fromEnd = false): string {
	const compact = text.replace(/\s+/g, ' ').trim();
	const preview = fromEnd ? compact.slice(-180) : compact.slice(0, 180);
	return preview || '(empty)';
}

function jsonParseMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function describeJsonParseFailure(content: string, error: unknown): string {
	const analysis = analyzeJsonTail(content);
	if (!analysis.hasStart) {
		return `Model did not return a JSON object (response length ${content.length} chars; preview: ${JSON.stringify(jsonPreview(content))})`;
	}
	if (analysis.inString || analysis.stack.length > 0) {
		const unclosed = [
			analysis.inString ? 'string' : '',
			...analysis.stack
				.slice()
				.reverse()
				.map((closer) => (closer === '}' ? 'object' : 'array'))
		].filter(Boolean);
		return `Model returned incomplete JSON; likely cut off before the closing ${analysis.stack.at(-1) ?? 'quote'} (response length ${content.length} chars; unclosed ${unclosed.join(', ')}; tail: ${JSON.stringify(jsonPreview(content, true))}). This usually means the plan response hit its output/completion token cap or the provider stream ended early.`;
	}
	return `Model returned invalid JSON: ${jsonParseMessage(error)} (response length ${content.length} chars; tail: ${JSON.stringify(jsonPreview(content, true))})`;
}

export function parseJsonObject<T = unknown>(raw: string): T {
	const clean = stripCodeFences(raw).trim();
	try {
		return JSON.parse(clean) as T;
	} catch (error) {
		const extracted = extractBalancedJsonSlice(clean);
		if (extracted) {
			try {
				return JSON.parse(extracted) as T;
			} catch {
				// Fall through to a diagnostic based on the original response.
			}
		}
		throw new Error(describeJsonParseFailure(clean, error));
	}
}

export function objectNamesFromLiveObj(sourceText: string): string[] {
	const names = [...sourceText.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1]);
	return [...new Set(names)];
}

function materialPresetIds(sourceText: string): Set<string> {
	return new Set([...sourceText.matchAll(/^\s*#@material_preset:\s+([^\s]+)/gm)].map((m) => m[1]));
}

function materialReferences(sourceText: string): string[] {
	return [
		...[...sourceText.matchAll(/^\s*#@\s*-\s*material\s+name=([^\s]+)/gm)].map((m) => m[1]),
		...[...sourceText.matchAll(/^\s*#@material:\s*([^\s]+)/gm)].map((m) => m[1]),
		...[...sourceText.matchAll(/^\s*#@post\s+material\s+(?:.*\s)?(?:name|id)=([^\s]+)/gm)].map(
			(m) => m[1]
		)
	];
}

function elementVertexRefs(line: string): number[] {
	if (!/^\s*[fl]\s+/.test(line)) return [];
	return line
		.trim()
		.split(/\s+/)
		.slice(1)
		.map((token) => Number(token.split('/')[0]))
		.filter((n) => Number.isFinite(n));
}

function vertexValues(line: string): [number, number, number] | undefined {
	if (!/^\s*v\s+/.test(line)) return undefined;
	const parts = line.trim().split(/\s+/).slice(1, 4).map(Number);
	if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return undefined;
	return [parts[0], parts[1], parts[2]];
}

function countVertices(sourceText: string): number {
	return sourceText.split('\n').filter((line) => /^\s*v\s+/.test(line)).length;
}

function countFaces(sourceText: string): number {
	return sourceText.split('\n').filter((line) => /^\s*f\s+/.test(line)).length;
}

export function hasControlsMetadata(sourceText: string): boolean {
	return /^\s*#@controls\s*:/m.test(String(sourceText ?? ''));
}

function objectBlocks(sourceText: string): string[] {
	return String(sourceText ?? '')
		.split(/(?=^\s*o\s+)/gm)
		.filter((block) => /^\s*o\s+/.test(block));
}

function objectNameFromBlock(block: string): string {
	return block.match(/^\s*o\s+([^\s#]+)/m)?.[1] ?? 'unnamed';
}

function controlKeysFromBlock(block: string): Set<string> {
	const keys = new Set<string>();
	let inControls = false;
	for (const rawLine of block.split('\n')) {
		const line = rawLine.trim();
		if (/^#@controls\s*:/.test(line)) {
			inControls = true;
			const inlineKey = line.match(/\b(?:key|param|name)=([A-Za-z_][A-Za-z0-9_]*)/)?.[1];
			if (inlineKey) keys.add(inlineKey);
			continue;
		}
		if (line.startsWith('#@') && line.endsWith(':') && !/^#@\s*-/.test(line)) {
			inControls = false;
			continue;
		}
		if (!inControls) continue;
		const key = line.match(/\b(?:key|param|name)=([A-Za-z_][A-Za-z0-9_]*)/)?.[1];
		if (key) keys.add(key);
	}
	return keys;
}

function paramKeysFromBlock(block: string): Set<string> {
	const keys = new Set<string>();
	for (const match of block.matchAll(/^\s*#@params:\s*(.+)$/gm)) {
		for (const paramMatch of match[1].matchAll(/\b([A-Za-z_][A-Za-z0-9_]*)\s*=/g)) {
			keys.add(paramMatch[1]);
		}
	}
	return keys;
}

function postBodiesFromBlock(block: string): string[] {
	const bodies: string[] = [];
	let inPost = false;
	for (const rawLine of block.split('\n')) {
		const line = rawLine.trim();
		if (line === '#@post:') {
			inPost = true;
			continue;
		}
		const inlinePost = line.match(/^#@post\s+(.+)$/);
		if (inlinePost) {
			bodies.push(inlinePost[1]);
			inPost = false;
			continue;
		}
		if (line.startsWith('#@') && line.endsWith(':') && line !== '#@post:') {
			inPost = false;
			continue;
		}
		if (inPost && line.startsWith('#@')) {
			const op = line.match(/^#@\s*-\s*(.+)$/)?.[1];
			if (op) bodies.push(op);
		}
	}
	return bodies;
}

const WORKFLOW_BACKED_CONTROL_KEYS = new Set(['dream_displacement_amount', 'dream_shade']);

function hasUvDreamWorkflow(block: string): boolean {
	return (
		/^\s*#@workflow_step:\s*uv_dream_enhance\b/m.test(block) ||
		/^\s*#@texture:\s*.*\bkind=height\b/m.test(block) ||
		/^\s*#@params:\s*.*\bdream_displacement_amount\s*=/m.test(block)
	);
}

function workflowBackedControlKeys(block: string, controlKeys: Set<string>): Set<string> {
	const keys = new Set<string>();
	if (!hasUvDreamWorkflow(block)) return keys;
	for (const key of controlKeys) {
		if (WORKFLOW_BACKED_CONTROL_KEYS.has(key)) keys.add(key);
	}
	return keys;
}

function hasDimensionalScaleControl(block: string, controlKeys = controlKeysFromBlock(block)): boolean {
	if (controlKeys.size === 0) return false;
	const keyPattern = [...controlKeys].map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
	if (!keyPattern) return false;
	const paramRef = new RegExp(`\\b(?:${keyPattern})\\b`);
	return postBodiesFromBlock(block).some(
		(body) => /\btransform\b/.test(body) && /\bscale\s*=/.test(body) && paramRef.test(body)
	);
}

export function rawObjControlIssues(sourceText: string): string[] {
	const issues: string[] = [];
	for (const block of objectBlocks(sourceText)) {
		if (countVertices(block) === 0 || countFaces(block) === 0) continue;
		const name = objectNameFromBlock(block);
		const controlKeys = controlKeysFromBlock(block);
		if (controlKeys.size === 0) {
			issues.push(
				`Object '${name}' has raw mesh geometry but no #@controls metadata; add editable size controls backed by executable #@post transform scale parameters.`
			);
			continue;
		}
		const paramKeys = paramKeysFromBlock(block);
		const postBodies = postBodiesFromBlock(block);
		const workflowKeys = workflowBackedControlKeys(block, controlKeys);
		const ordinaryControlKeys = new Set([...controlKeys].filter((key) => !workflowKeys.has(key)));
		for (const key of controlKeys) {
			if (!paramKeys.has(key)) {
				issues.push(`Object '${name}' control '${key}' is missing a default value in #@params.`);
			}
			if (
				!workflowKeys.has(key) &&
				!postBodies.some((body) => new RegExp(`\\b${key}\\b`).test(body))
			) {
				issues.push(
					`Object '${name}' control '${key}' is not referenced by executable #@post metadata.`
				);
			}
		}
		if (ordinaryControlKeys.size > 0 && !hasDimensionalScaleControl(block, ordinaryControlKeys)) {
			issues.push(
				`Object '${name}' has controls but no editable dimension/scale transform; add width, height, depth, or scale controls that drive #@post transform scale.`
			);
		}
	}
	return issues;
}

function defaultControlLines(): string[] {
	return [
		'#@params: control_scale=1, control_width=1, control_height=1, control_depth=1',
		...defaultControlUiLines(),
		...defaultControlPostLines()
	];
}

function defaultControlParamEntries(): Array<[string, string]> {
	return [
		['control_scale', '1'],
		['control_width', '1'],
		['control_height', '1'],
		['control_depth', '1']
	];
}

function defaultControlUiLines(): string[] {
	return [
		'#@controls:',
		'#@ - slider key=control_scale label=Scale min=0.5 max=1.8 step=0.05',
		'#@ - slider key=control_width label=Width min=0.5 max=2.5 step=0.05',
		'#@ - slider key=control_height label=Height min=0.5 max=2.5 step=0.05',
		'#@ - slider key=control_depth label=Depth min=0.5 max=2.5 step=0.05'
	];
}

function defaultControlPostLines(): string[] {
	return [
		'#@post:',
		'#@ - transform scale=[control_scale*control_width,control_scale*control_height,control_scale*control_depth] pivot=[0,0,0]'
	];
}

function addDefaultControlsToObjectBlock(block: string): string {
	if (countVertices(block) === 0 || rawObjControlIssues(block).length === 0) return block;
	const lines = block.split('\n');
	const insertAt = lines.findIndex((line, index) => index > 0 && /^\s*(v|vn|vt|f|l)\s+/.test(line));
	if (insertAt < 0) return block;
	const paramLineIndex = lines.findIndex(
		(line, index) => index < insertAt && /^\s*#@params:\s*/.test(line.trim())
	);
	const params = defaultControlParamEntries();
	if (paramLineIndex >= 0) {
		const existing = lines[paramLineIndex];
		const additions = params
			.filter(([key]) => !new RegExp(`\\b${key}\\s*=`).test(existing))
			.map(([key, value]) => `${key}=${value}`);
		if (additions.length > 0) {
			const separator = existing.trim().endsWith(':') ? ' ' : ', ';
			lines[paramLineIndex] = `${existing}${separator}${additions.join(', ')}`;
		}
		lines.splice(insertAt, 0, ...defaultControlUiLines(), ...defaultControlPostLines());
	} else {
		lines.splice(insertAt, 0, ...defaultControlLines());
	}
	return lines.join('\n');
}

export function addDefaultRawObjControls(sourceText: string): string {
	return String(sourceText ?? '')
		.split(/(?=^\s*o\s+)/gm)
		.map((block) => (/^\s*o\s+/.test(block) ? addDefaultControlsToObjectBlock(block) : block))
		.join('');
}

function objectGeometryCoverage(sourceText: string): Array<{
	name: string;
	vertexCount: number;
	faceCount: number;
	usedVertexCount: number;
}> {
	const blocks = sourceText.split(/(?=^\s*o\s+)/gm).filter((block) => /^\s*o\s+/.test(block));
	let globalVertexStart = 1;
	const out: Array<{
		name: string;
		vertexCount: number;
		faceCount: number;
		usedVertexCount: number;
	}> = [];
	for (const block of blocks) {
		const name = block.match(/^\s*o\s+([^\s#]+)/m)?.[1] ?? 'unnamed';
		const vertexCount = countVertices(block);
		const faceCount = countFaces(block);
		const localGlobalIndices = new Set(
			Array.from({ length: vertexCount }, (_, index) => globalVertexStart + index)
		);
		const used = new Set<number>();
		for (const ref of block.split('\n').flatMap(elementVertexRefs)) {
			if (localGlobalIndices.has(ref)) used.add(ref);
		}
		out.push({ name, vertexCount, faceCount, usedVertexCount: used.size });
		globalVertexStart += vertexCount;
	}
	return out;
}

function objectAllowsOpenBoundary(block: string): boolean {
	return /\b(open|opening|hollow|rim|window|door|doorway|shade|diffuser|frame|lattice|truss|tube|pipe|cord|wire|curve|ring|loop|vessel|bowl|cup|shell|membrane|panel|canopy|roof|fabric|cloth)\b/i.test(
		block
	);
}

function objectBoundaryWarnings(sourceText: string): string[] {
	const warnings: string[] = [];
	const blocks = sourceText.split(/(?=^\s*o\s+)/gm).filter((block) => /^\s*o\s+/.test(block));
	for (const block of blocks) {
		if (objectAllowsOpenBoundary(block)) continue;
		const name = block.match(/^\s*o\s+([^\s#]+)/m)?.[1] ?? 'unnamed';
		const edgeCounts = new Map<string, number>();
		let faceCount = 0;
		for (const line of block.split('\n')) {
			if (!/^\s*f\s+/.test(line)) continue;
			const refs = elementVertexRefs(line);
			if (refs.length < 3) continue;
			faceCount += 1;
			for (let i = 0; i < refs.length; i += 1) {
				const a = refs[i];
				const b = refs[(i + 1) % refs.length];
				const key = a < b ? `${a}:${b}` : `${b}:${a}`;
				edgeCounts.set(key, (edgeCounts.get(key) ?? 0) + 1);
			}
		}
		if (faceCount < 6) continue;
		const boundaryEdges = [...edgeCounts.values()].filter((count) => count === 1).length;
		if (boundaryEdges >= Math.max(8, Math.round(faceCount * 0.35))) {
			warnings.push(
				`Object '${name}' has ${boundaryEdges} open boundary edges; check for accidental missing faces unless this part is intentionally open.`
			);
		}
	}
	return warnings;
}

function bboxFromText(sourceText: string): LiveObjValidationResult['bbox'] {
	const vertices = sourceText
		.split('\n')
		.map(vertexValues)
		.filter((v): v is [number, number, number] => Boolean(v));
	if (vertices.length === 0) return undefined;
	const min: [number, number, number] = [...vertices[0]];
	const max: [number, number, number] = [...vertices[0]];
	for (const v of vertices.slice(1)) {
		for (let i = 0; i < 3; i += 1) {
			min[i] = Math.min(min[i], v[i]);
			max[i] = Math.max(max[i], v[i]);
		}
	}
	return { min, max };
}

function splitPartText(rawPart: string): { preambleLines: string[]; objectText: string } {
	const clean = normalizeGeneratedPartMetadata(rawPart).trim();
	const lines = clean.split('\n');
	const firstObject = lines.findIndex((line) => /^\s*o\s+/.test(line));
	if (firstObject < 0) {
		throw new Error('Generated part did not contain an OBJ object line (`o name`)');
	}
	const preambleLines = lines
		.slice(0, firstObject)
		.filter((line) => /^\s*#@material_preset:\s+/.test(line));
	const objectText = lines.slice(firstObject).join('\n').trim();
	return { preambleLines, objectText };
}

function firstPostAttributeValue(body: string, keys: string[]): string | undefined {
	for (const key of keys) {
		const match = body.match(new RegExp(`(?:^|\\s)${key}\\s*=\\s*("[^"]+"|'[^']+'|[^\\s]+)`, 'i'));
		const value = match?.[1]?.trim();
		if (!value) continue;
		return value.replace(/^["']|["']$/g, '');
	}
	return undefined;
}

function normalizeMaterialPostLine(rawLine: string): string[] | undefined {
	const blockMaterial = rawLine.match(/^(\s*)#@\s*-\s*material\b(.*)$/i);
	if (blockMaterial) {
		const materialName = firstPostAttributeValue(blockMaterial[2] ?? '', ['name', 'id']);
		if (!materialName) return undefined;
		return [`${blockMaterial[1]}#@ - material name=${materialName}`];
	}

	const objectMaterial = rawLine.match(/^(\s*)#@material\b:?\s*(.*)$/i);
	if (objectMaterial) {
		const rawBody = objectMaterial[2]?.trim() ?? '';
		const materialName =
			firstPostAttributeValue(rawBody, ['name', 'id']) ?? rawBody.split(/\s+/)[0]?.trim();
		if (!materialName) return undefined;
		return [
			`${objectMaterial[1]}#@post:`,
			`${objectMaterial[1]}#@ - material name=${materialName}`
		];
	}

	const inlineMaterial = rawLine.match(/^(\s*)#@post\s+material\b(.*)$/i);
	if (inlineMaterial) {
		const materialName = firstPostAttributeValue(inlineMaterial[2] ?? '', ['name', 'id']);
		if (!materialName) return undefined;
		return [
			`${inlineMaterial[1]}#@post:`,
			`${inlineMaterial[1]}#@ - material name=${materialName}`
		];
	}

	return undefined;
}

function normalizePostOpBody(rawBody: string): string {
	const [rawOp = '', ...restParts] = rawBody.trim().split(/\s+/);
	const op = rawOp.toLowerCase();
	let rest = restParts.join(' ').trim();
	if (op === 'subdivide') {
		rest = rest.replace(/\blevels\s*=/gi, 'level=');
	}
	return [op || rawOp, rest].filter(Boolean).join(' ');
}

function normalizeGenericPostLine(rawLine: string): string[] | undefined {
	const blockPost = rawLine.match(/^(\s*)#@\s*-\s*(\w+\b.*)$/i);
	if (blockPost) {
		const normalized = normalizePostOpBody(blockPost[2] ?? '');
		return normalized ? [`${blockPost[1]}#@ - ${normalized}`] : undefined;
	}

	const inlinePost = rawLine.match(/^(\s*)#@post\s+(\w+\b.*)$/i);
	if (inlinePost) {
		const normalized = normalizePostOpBody(inlinePost[2] ?? '');
		return normalized
			? [`${inlinePost[1]}#@post:`, `${inlinePost[1]}#@ - ${normalized}`]
			: undefined;
	}

	return undefined;
}

function normalizeTagPostLine(rawLine: string): string[] | undefined {
	const blockTag = rawLine.match(/^(\s*)#@\s*-\s*tag\b(.*)$/i);
	if (blockTag) {
		const tagValue = firstPostAttributeValue(blockTag[2] ?? '', ['value', 'name', 'id']);
		if (!tagValue) return undefined;
		return [`${blockTag[1]}#@ - tag value=${tagValue}`];
	}

	const inlineTag = rawLine.match(/^(\s*)#@post\s+tag\b(.*)$/i);
	if (inlineTag) {
		const tagValue = firstPostAttributeValue(inlineTag[2] ?? '', ['value', 'name', 'id']);
		if (!tagValue) return undefined;
		return [`${inlineTag[1]}#@post:`, `${inlineTag[1]}#@ - tag value=${tagValue}`];
	}

	return undefined;
}

function readableObjectName(name: string): string {
	return name.replace(/[_-]+/g, ' ').trim() || 'generated raw mesh part';
}

function ensureGeneratedObjectMetadata(sourceText: string): string {
	return sourceText
		.split(/(?=^\s*o\s+)/gm)
		.map((block) => {
			if (!/^\s*o\s+/m.test(block) || !/^\s*v\s+/m.test(block)) return block;
			const lines = block.split('\n');
			const objectName = lines[0]?.match(/^\s*o\s+([^\s#]+)/)?.[1] ?? '';
			const additions: string[] = [];
			if (!/^\s*#@source:\s*\S+/m.test(block)) additions.push('#@source: llm_mesh');
			if (!/^\s*#@semantic:\s*\S+/m.test(block)) {
				additions.push(`#@semantic: ${readableObjectName(objectName)}`);
			}
			if (additions.length === 0) return block;
			lines.splice(1, 0, ...additions);
			return lines.join('\n');
		})
		.join('');
}

export function normalizeGeneratedPartMetadata(rawPart: string): string {
	const normalized = stripCodeFences(rawPart)
		.split('\n')
		.flatMap(
			(line) =>
				normalizeMaterialPostLine(line) ??
				normalizeTagPostLine(line) ??
				normalizeGenericPostLine(line) ?? [line]
		)
		.join('\n');
	return ensureGeneratedObjectMetadata(normalized);
}

function remapFaceToken(
	token: string,
	vertexOffset: number,
	localIndexOffset = 0,
	localVerticesSeen?: number
): string {
	const parts = token.split('/');
	const n = Number(parts[0]);
	if (!Number.isInteger(n) || n === 0) return token;
	if (n < 0) {
		if (localVerticesSeen == null) return token;
		const localIndex = localVerticesSeen + n + 1;
		if (localIndex < 1 || localIndex > localVerticesSeen) {
			throw new Error(
				`Generated part uses relative face index ${n}, but only ${localVerticesSeen} vertices are available before that face. Return positive local face indices starting at 1.`
			);
		}
		parts[0] = String(localIndex + vertexOffset);
		return parts.join('/');
	}
	parts[0] = String(n - localIndexOffset + vertexOffset);
	return parts.join('/');
}

function remapLocalFaceIndices(objectText: string, vertexOffset: number): string {
	const localVertexCount = countVertices(objectText);
	const refs = objectText
		.split('\n')
		.flatMap(elementVertexRefs)
		.filter((ref) => ref > 0);
	const maxRef = refs.length ? Math.max(...refs) : 0;
	const minRef = refs.length ? Math.min(...refs) : 1;
	const localIndexOffset =
		maxRef > localVertexCount &&
		minRef > 1 &&
		refs.every((ref) => ref - (minRef - 1) >= 1 && ref - (minRef - 1) <= localVertexCount)
			? minRef - 1
			: 0;
	if (maxRef - localIndexOffset > localVertexCount) {
		throw new Error(
			`Generated part uses face index ${maxRef}, but only defines ${localVertexCount} vertices. Return local face indices starting at 1 for the part.`
		);
	}
	let localVerticesSeen = 0;
	return objectText
		.split('\n')
		.map((line) => {
			if (/^\s*v\s+/.test(line)) localVerticesSeen += 1;
			if (!/^\s*[fl]\s+/.test(line)) return line;
			const [head, ...tokens] = line.trim().split(/\s+/);
			return [
				head,
				...tokens.map((token) =>
					remapFaceToken(token, vertexOffset, localIndexOffset, localVerticesSeen)
				)
			].join(' ');
		})
		.join('\n');
}

function ensureHeader(currentLiveObj: string): string {
	const trimmed = currentLiveObj.trim();
	if (trimmed) return `${trimmed}\n`;
	return `${DEFAULT_HEADER.join('\n')}\n`;
}

function insertPreambleLines(currentLiveObj: string, preambleLines: string[]): string {
	if (preambleLines.length === 0) return currentLiveObj;
	const existingMaterials = materialPresetIds(currentLiveObj);
	const additions = preambleLines.filter((line) => {
		const id = line.match(/^\s*#@material_preset:\s+([^\s]+)/)?.[1];
		return id && !existingMaterials.has(id);
	});
	if (additions.length === 0) return currentLiveObj;
	const lines = currentLiveObj.split('\n');
	const firstObject = lines.findIndex((line) => /^\s*o\s+/.test(line));
	if (firstObject < 0) return `${currentLiveObj.trim()}\n${additions.join('\n')}\n`;
	lines.splice(firstObject, 0, ...additions);
	return lines.join('\n');
}

export function appendGeneratedPart(
	currentLiveObj: string,
	rawGeneratedPart: string
): { liveObj: string; normalizedPart: string } {
	const base = ensureHeader(currentLiveObj);
	const { preambleLines, objectText } = splitPartText(rawGeneratedPart);
	const normalizedPart = remapLocalFaceIndices(objectText, countVertices(base));
	const withPreamble = insertPreambleLines(base, preambleLines);
	return {
		liveObj: `${withPreamble.trim()}\n\n${normalizedPart}\n`,
		normalizedPart
	};
}

export function validateLiveObj(liveObj: string, previousLiveObj = ''): LiveObjValidationResult {
	const errors: string[] = [];
	const warnings: string[] = [];
	const objectNames = [...liveObj.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1]);
	const previousNames = new Set(objectNamesFromLiveObj(previousLiveObj));
	const addedObjectNames = objectNames.filter((name) => !previousNames.has(name));
	const duplicateNames = objectNames.filter((name, i) => objectNames.indexOf(name) !== i);
	if (duplicateNames.length > 0) {
		errors.push(`Duplicate object names: ${[...new Set(duplicateNames)].join(', ')}`);
	}
	if (previousLiveObj.trim() && addedObjectNames.length === 0) {
		warnings.push('No new object names were added');
	}

	const vertexCount = countVertices(liveObj);
	const faceCount = countFaces(liveObj);
	if (objectNames.length === 0) errors.push('No OBJ objects found');
	if (
		vertexCount === 0 &&
		!/#@source:\s*(procedural|sdf|simulation|recipe|assembly)/.test(liveObj)
	) {
		errors.push('No vertices found and no executable procedural source was declared');
	}
	for (const coverage of objectGeometryCoverage(liveObj)) {
		if (coverage.vertexCount > 0 && coverage.faceCount === 0) {
			errors.push(
				`Object '${coverage.name}' defines ${coverage.vertexCount} vertices but no faces, so it will not render.`
			);
			continue;
		}
		if (
			coverage.vertexCount >= 12 &&
			coverage.faceCount > 0 &&
			coverage.usedVertexCount / coverage.vertexCount < 0.5
		) {
			errors.push(
				`Object '${coverage.name}' only references ${coverage.usedVertexCount}/${coverage.vertexCount} vertices in faces. Add faces for the generated geometry instead of leaving vertices unused.`
			);
		}
	}
	warnings.push(...objectBoundaryWarnings(liveObj));

	for (const [i, line] of liveObj.split('\n').entries()) {
		if (!/^\s*f\s+/.test(line)) continue;
		const refs = elementVertexRefs(line);
		if (refs.length < 3) errors.push(`Face on line ${i + 1} has fewer than 3 vertices`);
		for (const ref of refs) {
			if (!Number.isInteger(ref) || ref <= 0 || ref > vertexCount) {
				errors.push(`Face on line ${i + 1} references missing vertex ${ref}`);
			}
		}
	}

	const presets = materialPresetIds(liveObj);
	for (const ref of materialReferences(liveObj)) {
		if (!presets.has(ref)) warnings.push(`Material '${ref}' is referenced but not preset`);
	}

	return {
		valid: errors.length === 0,
		errors,
		warnings,
		objectNames: [...new Set(objectNames)],
		addedObjectNames,
		vertexCount,
		faceCount,
		bbox: bboxFromText(liveObj)
	};
}

export function summarizeLiveObjForPlanning(liveObj: string): string {
	const summaries = summarizeObjects(liveObj);
	if (summaries.length === 0) return '(empty scene)';
	return summaries
		.map((obj) => {
			const bbox = obj.bbox
				? ` bbox=[${obj.bbox.min.map((n) => n.toFixed(3)).join(',')}..${obj.bbox.max.map((n) => n.toFixed(3)).join(',')}]`
				: '';
			const openings = obj.openings.length ? ` openings={${obj.openings.join('; ')}}` : '';
			return `- ${obj.name}: source=${obj.source || 'unknown'} v=${obj.vertexCount} f=${obj.faceCount}${bbox}${obj.semantic ? ` semantic="${obj.semantic}"` : ''}${openings}`;
		})
		.join('\n');
}

function summarizeObjects(liveObj: string): ObjectSummary[] {
	const blocks = liveObj.split(/(?=^\s*o\s+)/gm).filter((block) => /^\s*o\s+/.test(block));
	return blocks.map((block) => {
		const name = block.match(/^\s*o\s+([^\s#]+)/m)?.[1] ?? 'unnamed';
		const source = block.match(/^\s*#@source:\s*([^\s]+)/m)?.[1];
		const semantic = block.match(/^\s*#@semantic:\s*(.+)$/m)?.[1]?.trim();
		const openings = [...block.matchAll(/^\s*#@opening:?\s+(.+)$/gim)].map((match) =>
			match[1].trim()
		);
		return {
			name,
			source,
			semantic,
			openings,
			vertexCount: countVertices(block),
			faceCount: countFaces(block),
			bbox: bboxFromText(block)
		};
	});
}
