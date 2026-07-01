import { hasProceduralLiveSources } from './rawPostHeader';

const SUPPORTED_RAW_POST_OPS = new Set([
	'transform',
	'symmetrize',
	'mirror',
	'array',
	'scatter',
	'surface_snap',
	'conform',
	'path_array',
	'surface_array',
	'orient',
	'clip',
	'deform',
	'subdivide',
	'smooth',
	'simplify',
	'face_lattice',
	'skin_edges',
	'build_glazed_openings',
	'snap_to_ground',
	'center_origin',
	'material',
	'tag'
]);

const SUPPORTED_RAW_POST_ATTRIBUTES: Record<string, Set<string>> = {
	transform: new Set(['selection', 'group', 'position', 'translate', 'rotation', 'scale', 'pivot']),
	symmetrize: new Set(['axis', 'side', 'tolerance']),
	mirror: new Set(['axis']),
	array: new Set(['count', 'offset', 'centered', 'center', 'scale', 'position', 'pivot']),
	scatter: new Set([
		'count',
		'width',
		'depth',
		'area',
		'size',
		'axes',
		'plane',
		'target',
		'surface',
		'on',
		'center',
		'seed',
		'min_distance',
		'spacing',
		'jitter',
		'attempts',
		'mode',
		'align_to_normal',
		'normal_offset',
		'surface_offset',
		'height_offset',
		'scale',
		'scale_min',
		'scale_max',
		'min_scale',
		'max_scale',
		'uniform_scale',
		'position',
		'rotation',
		'rotation_x',
		'rotation_y',
		'rotation_z',
		'pivot',
		'height_min',
		'height_max',
		'slope_min',
		'slope_max',
		'avoid',
		'clearance',
		'cluster_count',
		'clusters',
		'cluster_radius'
	]),
	surface_snap: new Set([
		'target',
		'surface',
		'on',
		'axes',
		'plane',
		'pivot',
		'normal_offset',
		'surface_offset',
		'height_offset',
		'align_to_normal',
		'mode'
	]),
	conform: new Set([
		'target',
		'surface',
		'on',
		'axes',
		'plane',
		'strength',
		'normal_offset',
		'surface_offset',
		'height_offset'
	]),
	path_array: new Set([
		'path',
		'target',
		'curve',
		'count',
		'spacing',
		'closed',
		'rotation_mode',
		'rotation',
		'rotation_x',
		'rotation_y',
		'rotation_z',
		'scale',
		'scale_min',
		'scale_max',
		'min_scale',
		'max_scale',
		'uniform_scale',
		'position',
		'pivot',
		'seed'
	]),
	surface_array: new Set([
		'target',
		'surface',
		'on',
		'count',
		'spacing',
		'pattern',
		'axes',
		'plane',
		'normal_offset',
		'surface_offset',
		'height_offset',
		'align_to_normal',
		'rotation',
		'rotation_x',
		'rotation_y',
		'rotation_z',
		'scale',
		'scale_min',
		'scale_max',
		'min_scale',
		'max_scale',
		'uniform_scale',
		'position',
		'pivot',
		'seed'
	]),
	orient: new Set(['mode', 'target', 'point', 'pivot', 'axis', 'up', 'rotation']),
	clip: new Set(['axis', 'min', 'max', 'below', 'above', 'center', 'size', 'invert']),
	deform: new Set(['selection', 'group', 'position', 'expr', 'xyz']),
	subdivide: new Set(['level']),
	smooth: new Set(['iterations', 'strength']),
	simplify: new Set(['ratio']),
	face_lattice: new Set([
		'inset',
		'thickness',
		'weld',
		'guide_subdivide',
		'guide_smooth',
		'subdivide',
		'smooth',
		'smooth_strength',
		'mode'
	]),
	skin_edges: new Set(['radius', 'resolution', 'edges', 'angle', 'mode', 'padding']),
	build_glazed_openings: new Set([
		'ids',
		'role',
		'type',
		'frame_width',
		'frame_depth',
		'panel_inset',
		'panel_recess',
		'panel_thickness',
		'mode'
	]),
	snap_to_ground: new Set(['axis']),
	center_origin: new Set(['axes']),
	material: new Set(['name']),
	tag: new Set(['value'])
};

const RAW_POST_SEMANTIC_META_KEYS = new Set([
	'bbox',
	'lock',
	'part',
	'opening',
	'anchor',
	'constraint',
	'variant'
]);

type PostSyntaxIssue = {
	message: string;
};

type PostOpScan = {
	cmd: string;
	body: string;
};

type RawPostObjectSummary = {
	name: string;
	vertexCount: number;
	faceCount: number;
	metaLines: string[];
};

export type RawPostValidationResult = {
	valid: boolean;
	errors: string[];
	warnings: string[];
	objectNames: string[];
};

function postOpsFromMetaLines(metaLines: string[]): {
	ops: PostOpScan[];
	issues: PostSyntaxIssue[];
} {
	const ops: PostOpScan[] = [];
	const issues: PostSyntaxIssue[] = [];
	let block: 'post' | 'ops' | 'other' = 'other';
	for (const rawLine of metaLines) {
		const line = rawLine.trim();
		if (!line.startsWith('#@')) continue;
		const body = line.slice(2).trim();
		if (body === 'post:') {
			block = 'post';
			continue;
		}
		if (/^post:\s+\S/i.test(body)) {
			issues.push({
				message: 'malformed #@post block syntax; use #@post: followed by #@ - op lines'
			});
			block = 'other';
			continue;
		}
		if (body === 'ops:') {
			block = 'ops';
			continue;
		}
		if (body.endsWith(':') && !body.startsWith('-')) {
			block = 'other';
			continue;
		}
		if (body.startsWith('post ')) {
			const opBody = body.slice('post '.length).trim();
			ops.push({ cmd: (opBody.split(/\s+/)[0] ?? '').toLowerCase(), body: opBody });
			block = 'other';
			continue;
		}
		if (body.startsWith('-') && block === 'post') {
			const opBody = body.slice(1).trim();
			ops.push({ cmd: (opBody.split(/\s+/)[0] ?? '').toLowerCase(), body: opBody });
		}
		if (body.startsWith('-') && block === 'ops') {
			const opBody = body.slice(1).trim();
			ops.push({ cmd: `#@ops:${(opBody.split(/\s+/)[0] ?? '').toLowerCase()}`, body: opBody });
		}
	}
	return { ops: ops.filter((op) => op.cmd), issues };
}

function metaBody(line: string): string | undefined {
	const trimmed = line.trim();
	return trimmed.startsWith('#@') ? trimmed.slice(2).trim() : undefined;
}

function semanticMetaKey(line: string): string | undefined {
	const body = metaBody(line);
	const key = body?.match(/^([A-Za-z_][\w-]*)(?:\s*:|\s+)/)?.[1]?.toLowerCase();
	return key && RAW_POST_SEMANTIC_META_KEYS.has(key) ? key : undefined;
}

function hasVec3Attribute(body: string, key: string): boolean {
	return new RegExp(`\\b${key}\\s*=\\s*(?:\\[[^\\]]+\\]|\\([^\\)]+\\))`, 'i').test(body);
}

function hasIdAttribute(body: string): boolean {
	return /\bid\s*=\s*("[^"]+"|'[^']+'|[A-Za-z_][\w-]*)/i.test(body);
}

function hasLoopAttribute(body: string): boolean {
	return /\bloop\s*=\s*\[\s*\[[\s\S]*\]\s*\]/i.test(body);
}

function hasAttribute(body: string, key: string): boolean {
	return new RegExp(`\\b${key}\\s*=`, 'i').test(body);
}

function attributeNames(body: string): string[] {
	return [...body.matchAll(/\b([A-Za-z_][\w-]*)\s*=/g)].map((match) => match[1].toLowerCase());
}

function faceRefs(line: string, vertexCount: number): number[] {
	return line
		.trim()
		.split(/\s+/)
		.slice(1)
		.map((token) => Number(token.split('/')[0]))
		.filter((n) => Number.isFinite(n))
		.map((n) => (n < 0 ? vertexCount + n + 1 : n));
}

function ineffectiveUsemtlWarnings(sourceText: string): string[] {
	const warnings: string[] = [];
	let currentObject = '(scene)';
	let activeMaterial: { name: string; line: number; objectName: string; used: boolean } | null =
		null;

	const flushMaterial = (reason: string) => {
		if (!activeMaterial || activeMaterial.used) return;
		warnings.push(
			`usemtl '${activeMaterial.name}' in object '${activeMaterial.objectName}' on line ${activeMaterial.line} has no following faces before ${reason}`
		);
	};

	for (const [lineIndex, rawLine] of sourceText.split(/\r?\n/).entries()) {
		const lineNumber = lineIndex + 1;
		const line = rawLine.trim();
		const objectMatch = line.match(/^o\s+([^\s#]+)/);
		if (objectMatch) {
			flushMaterial('the next object');
			activeMaterial = null;
			currentObject = objectMatch[1];
			continue;
		}
		const materialMatch = line.match(/^usemtl\s+(\S+)/);
		if (materialMatch) {
			flushMaterial('the next usemtl');
			activeMaterial = {
				name: materialMatch[1],
				line: lineNumber,
				objectName: currentObject,
				used: false
			};
			continue;
		}
		if (/^f\s+/.test(line) && activeMaterial) {
			activeMaterial.used = true;
		}
	}
	flushMaterial('end of file');
	return warnings;
}

export function summarizeRawPostObjects(sourceText: string): RawPostObjectSummary[] {
	const objects: RawPostObjectSummary[] = [];
	let current: RawPostObjectSummary | null = null;
	for (const rawLine of sourceText.split(/\r?\n/)) {
		const line = rawLine.trim();
		const objectMatch = line.match(/^o\s+([^\s#]+)/);
		if (objectMatch) {
			current = { name: objectMatch[1], vertexCount: 0, faceCount: 0, metaLines: [] };
			objects.push(current);
			continue;
		}
		if (!current) continue;
		if (line.startsWith('#@')) current.metaLines.push(rawLine);
		if (/^v\s+/.test(line)) current.vertexCount += 1;
		if (/^f\s+/.test(line)) current.faceCount += 1;
	}
	return objects;
}

export function validateRawPostSource(sourceText: string): RawPostValidationResult {
	const text = String(sourceText ?? '');
	const errors: string[] = [];
	const warnings: string[] = [];
	if (!text.trim()) {
		return { valid: true, errors, warnings, objectNames: [] };
	}
	if (hasProceduralLiveSources(text)) {
		errors.push(
			'Raw-post mode cannot execute procedural, assembly, SDF, simulation, or recipe sources'
		);
		return {
			valid: false,
			errors,
			warnings,
			objectNames: summarizeRawPostObjects(text).map((o) => o.name)
		};
	}

	const objects = summarizeRawPostObjects(text);
	const objectNames = objects.map((object) => object.name);
	if (objects.length === 0) errors.push('No OBJ objects found');
	warnings.push(...ineffectiveUsemtlWarnings(text));

	const duplicateNames = objectNames.filter((name, index) => objectNames.indexOf(name) !== index);
	if (duplicateNames.length > 0) {
		errors.push(`Duplicate object names: ${[...new Set(duplicateNames)].join(', ')}`);
	}

	const totalVertexCount = text.split(/\r?\n/).filter((line) => /^\s*v\s+/.test(line)).length;
	for (const [lineIndex, line] of text.split(/\r?\n/).entries()) {
		if (!/^\s*f\s+/.test(line)) continue;
		const refs = faceRefs(line, totalVertexCount);
		if (refs.length < 3) errors.push(`Face on line ${lineIndex + 1} has fewer than 3 vertices`);
		for (const ref of refs) {
			if (!Number.isInteger(ref) || ref <= 0 || ref > totalVertexCount) {
				errors.push(`Face on line ${lineIndex + 1} references missing vertex ${ref}`);
			}
		}
	}

	for (const object of objects) {
		if (object.vertexCount > 0 && object.faceCount === 0) {
			errors.push(`Object '${object.name}' defines vertices but no faces`);
		}
		if (!object.metaLines.some((line) => /^\s*#@source:\s*llm_mesh\b/i.test(line))) {
			warnings.push(`Object '${object.name}' is missing #@source: llm_mesh`);
		}
		if (!object.metaLines.some((line) => /^\s*#@semantic:\s*\S+/i.test(line))) {
			warnings.push(`Object '${object.name}' is missing #@semantic`);
		}
		for (const line of object.metaLines) {
			const key = semanticMetaKey(line);
			if (!key) continue;
			const body = metaBody(line) ?? '';
			if (key === 'bbox' && (!hasVec3Attribute(body, 'min') || !hasVec3Attribute(body, 'max'))) {
				errors.push(
					`Object '${object.name}' has malformed #@bbox; expected min=[x,y,z] max=[x,y,z]`
				);
			}
			if (key === 'anchor' && (!hasIdAttribute(body) || !hasVec3Attribute(body, 'at'))) {
				errors.push(`Object '${object.name}' has malformed #@anchor; expected id=name at=[x,y,z]`);
			}
			if (key === 'opening' && (!hasIdAttribute(body) || !hasLoopAttribute(body))) {
				errors.push(
					`Object '${object.name}' has malformed #@opening; expected id=name loop=[[x,y,z],...]`
				);
			}
		}
		const postScan = postOpsFromMetaLines(object.metaLines);
		for (const issue of postScan.issues) {
			errors.push(`Object '${object.name}' has ${issue.message}`);
		}
		for (const op of postScan.ops) {
			if (op.cmd.startsWith('#@ops:')) {
				errors.push(`Object '${object.name}' uses #@ops in raw-post mode; use #@post instead`);
				continue;
			}
			if (!SUPPORTED_RAW_POST_OPS.has(op.cmd)) {
				errors.push(`Object '${object.name}' has unsupported #@post op '${op.cmd}'`);
				continue;
			}
			const supportedAttributes = SUPPORTED_RAW_POST_ATTRIBUTES[op.cmd] ?? new Set<string>();
			for (const attr of attributeNames(op.body)) {
				if (!supportedAttributes.has(attr)) {
					errors.push(
						`Object '${object.name}' has unsupported #@post ${op.cmd} attribute '${attr}'`
					);
				}
			}
			if (
				op.cmd === 'deform' &&
				!hasAttribute(op.body, 'position') &&
				!hasAttribute(op.body, 'expr') &&
				!hasAttribute(op.body, 'xyz')
			) {
				errors.push(
					`Object '${object.name}' has malformed #@post deform; expected position=[x,y,z]`
				);
			}
		}
	}

	return {
		valid: errors.length === 0,
		errors,
		warnings,
		objectNames
	};
}

export function rawPostValidationIssues(result: RawPostValidationResult): string[] {
	return [
		...result.errors.map((message) => `raw-post validation error: ${message}`),
		...result.warnings.map((message) => `raw-post validation warning: ${message}`)
	];
}
