export const DREAM_REBUILD_VIEW_NAMES = ['top', 'bottom', 'left', 'right', 'front', 'back'] as const;

export type DreamRebuildViewName = (typeof DREAM_REBUILD_VIEW_NAMES)[number];

export type Vec3 = [number, number, number];

export type Bounds3 = {
	min: Vec3;
	max: Vec3;
	center: Vec3;
	size: Vec3;
};

export type DreamRebuildAlignment = {
	targetObjectId?: string;
	bounds: Bounds3;
	canonicalBounds: {
		min: Vec3;
		max: Vec3;
	};
	worldFromCanonical: {
		translate: Vec3;
		scale: Vec3;
	};
};

export type DreamRebuildMask = {
	width: number;
	height: number;
	rows: string[];
};

export type DreamRebuildDepthMap = DreamRebuildMask;

const OBJECT_RE = /^\s*o\s+([^\s#]+)/;
const VERTEX_RE = /^\s*v\s+(.+)$/;
const FACE_RE = /^\s*f\s+(.+)$/;
const MESH_RE = /^\s*(v|vn|vt|vp|f|l)\s+/;

function vecAdd(a: Vec3, b: Vec3): Vec3 {
	return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

function vecSub(a: Vec3, b: Vec3): Vec3 {
	return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

function vecDiv(a: Vec3, n: number): Vec3 {
	return [a[0] / n, a[1] / n, a[2] / n];
}

function parseVertex(line: string): Vec3 | undefined {
	const match = VERTEX_RE.exec(line);
	if (!match) return undefined;
	const values = match[1].trim().split(/\s+/).slice(0, 3).map(Number);
	if (values.length < 3 || values.some((value) => !Number.isFinite(value))) return undefined;
	return [values[0], values[1], values[2]];
}

function parseFaceVertexRefs(line: string, vertexCount: number): number[] {
	const match = FACE_RE.exec(line);
	if (!match) return [];
	return match[1]
		.trim()
		.split(/\s+/)
		.map((token) => Number(token.split('/')[0]))
		.filter((index) => Number.isFinite(index) && index !== 0)
		.map((index) => (index < 0 ? vertexCount + index + 1 : index))
		.filter((index) => index >= 1 && index <= vertexCount);
}

function boundsFromVertices(vertices: Vec3[]): Bounds3 {
	if (vertices.length === 0) throw new Error('Target object has no vertices');
	const min: Vec3 = [...vertices[0]];
	const max: Vec3 = [...vertices[0]];
	for (const vertex of vertices.slice(1)) {
		for (let axis = 0; axis < 3; axis += 1) {
			min[axis] = Math.min(min[axis], vertex[axis]);
			max[axis] = Math.max(max[axis], vertex[axis]);
		}
	}
	const size = vecSub(max, min);
	const center = vecDiv(vecAdd(min, max), 2);
	return { min, max, center, size };
}

function fmtVec(vec: Vec3): string {
	return `[${vec.map((value) => Number(value.toFixed(6))).join(',')}]`;
}

function escapeMetadataValue(value: string): string {
	return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

export function computeDreamRebuildAlignment(
	liveObj: string,
	targetObjectId?: string
): DreamRebuildAlignment {
	const vertices: Vec3[] = [];
	const targetVertexIndices = new Set<number>();
	const targetFaceVertexIndices = new Set<number>();
	let currentObject: string | undefined;

	for (const line of liveObj.split(/\r?\n/)) {
		const objectMatch = OBJECT_RE.exec(line);
		if (objectMatch) {
			currentObject = objectMatch[1];
			continue;
		}

		const vertex = parseVertex(line);
		if (vertex) {
			vertices.push(vertex);
			if (!targetObjectId || currentObject === targetObjectId) {
				targetVertexIndices.add(vertices.length);
			}
			continue;
		}

		if (!targetObjectId || currentObject === targetObjectId) {
			for (const index of parseFaceVertexRefs(line, vertices.length)) {
				targetFaceVertexIndices.add(index);
			}
		}
	}

	if (vertices.length === 0) throw new Error('Live OBJ has no vertices to rebuild');
	const indices = targetFaceVertexIndices.size > 0 ? targetFaceVertexIndices : targetVertexIndices;
	if (indices.size === 0) {
		throw new Error(`Target object "${targetObjectId}" was not found or has no mesh vertices`);
	}
	const bounds = boundsFromVertices(
		[...indices].map((index) => vertices[index - 1]).filter((vertex): vertex is Vec3 => Boolean(vertex))
	);
	return {
		...(targetObjectId ? { targetObjectId } : {}),
		bounds,
		canonicalBounds: {
			min: [0, 0, 0],
			max: [1, 1, 1]
		},
		worldFromCanonical: {
			translate: bounds.min,
			scale: bounds.size
		}
	};
}

function stripExistingDreamBlock(lines: string[]): string[] {
	const out: string[] = [];
	let skippingDreamItems = false;
	for (const line of lines) {
		if (/^\s*#@dream\s*:/.test(line)) {
			skippingDreamItems = true;
			continue;
		}
		if (skippingDreamItems && /^\s*#@\s*-\s+/.test(line)) continue;
		skippingDreamItems = false;
		out.push(line);
	}
	return out;
}

function dreamMetadataLines(args: {
	prompt: string;
	reconstruction: string;
	alignment: DreamRebuildAlignment;
	views: DreamRebuildViewName[];
}): string[] {
	return [
		'#@dream:',
		`#@ - method=${args.reconstruction} prompt="${escapeMetadataValue(args.prompt)}" views=[${args.views.join(',')}] bbox_min=${fmtVec(args.alignment.bounds.min)} bbox_max=${fmtVec(args.alignment.bounds.max)} canonical_min=${fmtVec(args.alignment.canonicalBounds.min)} canonical_max=${fmtVec(args.alignment.canonicalBounds.max)} world_translate=${fmtVec(args.alignment.worldFromCanonical.translate)} world_scale=${fmtVec(args.alignment.worldFromCanonical.scale)}`
	];
}

export function addDreamMetadataToLiveObj(args: {
	liveObj: string;
	targetObjectId?: string;
	prompt: string;
	reconstruction?: string;
	views?: DreamRebuildViewName[];
	alignment?: DreamRebuildAlignment;
}): string {
	const alignment = args.alignment ?? computeDreamRebuildAlignment(args.liveObj, args.targetObjectId);
	const views = args.views ?? [...DREAM_REBUILD_VIEW_NAMES];
	const lines = args.liveObj.split(/\r?\n/);
	const out: string[] = [];
	let block: string[] = [];
	let currentObject: string | undefined;

	const flush = () => {
		if (block.length === 0) return;
		const shouldAnnotate =
			(!args.targetObjectId && currentObject != null) || currentObject === args.targetObjectId;
		if (!shouldAnnotate) {
			out.push(...block);
			block = [];
			return;
		}
		const cleanBlock = stripExistingDreamBlock(block);
		const insertAt = cleanBlock.findIndex((line, index) => index > 0 && MESH_RE.test(line));
		const metadata = dreamMetadataLines({
			prompt: args.prompt,
			reconstruction: args.reconstruction ?? 'tsdf',
			alignment,
			views
		});
		if (insertAt < 0) out.push(...cleanBlock, ...metadata);
		else out.push(...cleanBlock.slice(0, insertAt), ...metadata, ...cleanBlock.slice(insertAt));
		block = [];
	};

	for (const line of lines) {
		const objectMatch = OBJECT_RE.exec(line);
		if (objectMatch) {
			flush();
			currentObject = objectMatch[1];
			block = [line];
			continue;
		}
		if (block.length > 0) block.push(line);
		else out.push(line);
	}
	flush();

	if (args.targetObjectId && !out.some((line) => OBJECT_RE.exec(line)?.[1] === args.targetObjectId)) {
		throw new Error(`Target object "${args.targetObjectId}" was not found`);
	}

	return `${out.join('\n').replace(/\s+$/u, '')}\n`;
}

export function missingDreamRebuildViews(
	viewImageDataUrls: Partial<Record<DreamRebuildViewName, string>>
): DreamRebuildViewName[] {
	return DREAM_REBUILD_VIEW_NAMES.filter((name) => !viewImageDataUrls[name]?.startsWith('data:image/'));
}

export function missingDreamRebuildMasks(
	viewMasks: Partial<Record<DreamRebuildViewName, DreamRebuildMask>>
): DreamRebuildViewName[] {
	return DREAM_REBUILD_VIEW_NAMES.filter((name) => {
		const mask = viewMasks[name];
		return (
			!mask ||
			!Number.isFinite(mask.width) ||
			!Number.isFinite(mask.height) ||
			mask.width <= 0 ||
			mask.height <= 0 ||
			!Array.isArray(mask.rows) ||
			mask.rows.length !== mask.height
		);
	});
}

export function missingDreamRebuildDepthMaps(
	viewDepthMaps: Partial<Record<DreamRebuildViewName, DreamRebuildDepthMap>>
): DreamRebuildViewName[] {
	return missingDreamRebuildMasks(viewDepthMaps);
}
