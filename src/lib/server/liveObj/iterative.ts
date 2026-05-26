import { stripCodeFences } from '$lib/liveObj/stripCodeFences';

export type IterativePartSpec = {
	id: string;
	role?: string;
	prompt?: string;
	dependencies?: string[];
	method?: string;
	priority?: number;
	validationHints?: string[];
	controls?: IterativeControlSpec[];
	controlPostOps?: string[];
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
	vertexCount: number;
	faceCount: number;
	bbox?: { min: [number, number, number]; max: [number, number, number] };
};

const DEFAULT_HEADER = ['#@scene', '#@units: meters', '#@up: y', '#@live_obj_version: 0.1'];

export function parseJsonObject<T = unknown>(raw: string): T {
	const clean = stripCodeFences(raw).trim();
	try {
		return JSON.parse(clean) as T;
	} catch {
		const start = clean.indexOf('{');
		const end = clean.lastIndexOf('}');
		if (start >= 0 && end > start) {
			return JSON.parse(clean.slice(start, end + 1)) as T;
		}
		throw new Error('Model did not return a JSON object');
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

export function rawObjControlIssues(sourceText: string): string[] {
	const blocks = String(sourceText ?? '')
		.split(/(?=^\s*o\s+)/gm)
		.filter((block) => /^\s*o\s+/.test(block));
	const issues: string[] = [];
	for (const block of blocks) {
		const name = block.match(/^\s*o\s+([^\s#]+)/m)?.[1] ?? 'unnamed';
		if (countVertices(block) > 0 && !hasControlsMetadata(block)) {
			issues.push(`Object '${name}' is missing required #@controls metadata`);
		}
	}
	return issues;
}

function defaultControlLines(): string[] {
	return [
		'#@params: control_width=1, control_height=1, control_depth=1',
		'#@controls:',
		'#@ - slider key=control_width label=Width min=0.5 max=1.8 step=0.05',
		'#@ - slider key=control_height label=Height min=0.5 max=1.8 step=0.05',
		'#@ - slider key=control_depth label=Depth min=0.5 max=1.8 step=0.05',
		'#@post:',
		'#@ - transform scale=[control_width,control_height,control_depth] pivot=[0,0,0]'
	];
}

function addDefaultControlsToObjectBlock(block: string): string {
	if (countVertices(block) === 0 || hasControlsMetadata(block)) return block;
	const lines = block.split('\n');
	const insertAt = lines.findIndex((line, index) => index > 0 && /^\s*(v|vn|vt|f|l)\s+/.test(line));
	if (insertAt < 0) return block;
	lines.splice(insertAt, 0, ...defaultControlLines());
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

export function normalizeGeneratedPartMetadata(rawPart: string): string {
	return stripCodeFences(rawPart)
		.split('\n')
		.flatMap((line) => normalizeMaterialPostLine(line) ?? [line])
		.join('\n');
}

function remapFaceToken(token: string, vertexOffset: number, localIndexOffset = 0): string {
	const parts = token.split('/');
	const n = Number(parts[0]);
	if (!Number.isInteger(n) || n <= 0) return token;
	parts[0] = String(n - localIndexOffset + vertexOffset);
	return parts.join('/');
}

function remapLocalFaceIndices(objectText: string, vertexOffset: number): string {
	const localVertexCount = countVertices(objectText);
	const refs = objectText.split('\n').flatMap(elementVertexRefs);
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
	return objectText
		.split('\n')
		.map((line) => {
			if (!/^\s*[fl]\s+/.test(line)) return line;
			const [head, ...tokens] = line.trim().split(/\s+/);
			return [
				head,
				...tokens.map((token) => remapFaceToken(token, vertexOffset, localIndexOffset))
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
			return `- ${obj.name}: source=${obj.source || 'unknown'} v=${obj.vertexCount} f=${obj.faceCount}${bbox}${obj.semantic ? ` semantic="${obj.semantic}"` : ''}`;
		})
		.join('\n');
}

function summarizeObjects(liveObj: string): ObjectSummary[] {
	const blocks = liveObj.split(/(?=^\s*o\s+)/gm).filter((block) => /^\s*o\s+/.test(block));
	return blocks.map((block) => {
		const name = block.match(/^\s*o\s+([^\s#]+)/m)?.[1] ?? 'unnamed';
		const source = block.match(/^\s*#@source:\s*([^\s]+)/m)?.[1];
		const semantic = block.match(/^\s*#@semantic:\s*(.+)$/m)?.[1]?.trim();
		return {
			name,
			source,
			semantic,
			vertexCount: countVertices(block),
			faceCount: countFaces(block),
			bbox: bboxFromText(block)
		};
	});
}
