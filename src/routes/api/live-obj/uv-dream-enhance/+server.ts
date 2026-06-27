import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { storeTempAsset } from '$lib/server/tempAssetStore';
import { enhanceUvDreamWithExecutor } from '$lib/server/liveObj/pipeline';

function dataUrlBytes(dataUrl: string, expectedPrefix: string): Uint8Array {
	if (!dataUrl.startsWith(expectedPrefix)) throw error(400, `Expected ${expectedPrefix} data URL`);
	const match = dataUrl.match(/^data:[^;]+;base64,(.+)$/);
	if (!match) throw error(400, 'Invalid data URL');
	return new Uint8Array(Buffer.from(match[1], 'base64'));
}

function clampAmount(value: unknown): number {
	const parsed = Number(value ?? 1);
	if (!Number.isFinite(parsed)) return 1;
	return Math.max(0, Math.min(2, parsed));
}

function artifactUrl(bytes: Uint8Array, mimeType: string, filename: string): string {
	return `/api/temp-assets/${storeTempAsset(bytes, mimeType, filename)}`;
}

type MeshRef = { v: number; vt?: number; vn?: number };
type MeshBlock = {
	name: string;
	lines: string[];
	v: string[];
	vt: string[];
	vn: string[];
	vp: string[];
	otherMesh: string[];
	faces: MeshRef[][];
};

type Vec3 = [number, number, number];
type Bounds = { min: Vec3; max: Vec3; center: Vec3 };

function meshToken(line: string): string {
	return /^(\S+)/.exec(line.trim())?.[1]?.toLowerCase() ?? '';
}

function parseVertexLine(line: string): Vec3 | null {
	const parts = line.trim().split(/\s+/).slice(1, 4).map(Number);
	if (parts.length < 3 || parts.some((value) => !Number.isFinite(value))) return null;
	return [parts[0], parts[1], parts[2]];
}

function parseIndex(raw: string | undefined, total: number): number | undefined {
	if (!raw) return undefined;
	const parsed = Number(raw);
	if (!Number.isInteger(parsed) || parsed === 0) return undefined;
	return parsed < 0 ? total + parsed + 1 : parsed;
}

function parseObjForReindex(text: string): { header: string[]; blocks: MeshBlock[] } {
	const header: string[] = [];
	const blocks: MeshBlock[] = [];
	let current: MeshBlock | null = null;
	let totalV = 0;
	let totalVt = 0;
	let totalVn = 0;
	const vOwner = new Map<number, { block: MeshBlock; local: number }>();
	const vtOwner = new Map<number, { block: MeshBlock; local: number }>();
	const vnOwner = new Map<number, { block: MeshBlock; local: number }>();

	for (const line of text.split(/\r?\n/)) {
		const objectMatch = line.match(/^\s*o\s+([^\s#]+)/);
		if (objectMatch) {
			current = {
				name: objectMatch[1],
				lines: [line],
				v: [],
				vt: [],
				vn: [],
				vp: [],
				otherMesh: [],
				faces: []
			};
			blocks.push(current);
			continue;
		}
		if (!current) {
			header.push(line);
			continue;
		}
		const token = meshToken(line);
		if (token === 'v') {
			current.v.push(line);
			totalV += 1;
			vOwner.set(totalV, { block: current, local: current.v.length });
		} else if (token === 'vt') {
			current.vt.push(line);
			totalVt += 1;
			vtOwner.set(totalVt, { block: current, local: current.vt.length });
		} else if (token === 'vn') {
			current.vn.push(line);
			totalVn += 1;
			vnOwner.set(totalVn, { block: current, local: current.vn.length });
		} else if (token === 'vp') {
			current.vp.push(line);
		} else if (token === 'f') {
			const refs: MeshRef[] = [];
			let valid = true;
			for (const rawRef of line.trim().split(/\s+/).slice(1)) {
				const [vRaw, vtRaw, vnRaw] = rawRef.split('/');
				const vIndex = parseIndex(vRaw, totalV);
				const vtIndex = parseIndex(vtRaw, totalVt);
				const vnIndex = parseIndex(vnRaw, totalVn);
				const v = vIndex ? vOwner.get(vIndex) : undefined;
				const vt = vtIndex ? vtOwner.get(vtIndex) : undefined;
				const vn = vnIndex ? vnOwner.get(vnIndex) : undefined;
				if (
					!v ||
					v.block !== current ||
					(vt && vt.block !== current) ||
					(vn && vn.block !== current)
				) {
					valid = false;
					break;
				}
				refs.push({ v: v.local, ...(vt ? { vt: vt.local } : {}), ...(vn ? { vn: vn.local } : {}) });
			}
			if (valid && refs.length >= 3) current.faces.push(refs);
			else current.otherMesh.push(line);
		} else if (token === 'fo' || token === 'l') {
			current.otherMesh.push(line);
		} else {
			current.lines.push(line);
		}
	}
	return { header, blocks };
}

function trimTrailingBlankLines(lines: string[]): string[] {
	const out = [...lines];
	while (out.length > 0 && out[out.length - 1].trim() === '') out.pop();
	return out;
}

function faceRef(ref: MeshRef, offsets: { v: number; vt: number; vn: number }): string {
	const v = ref.v + offsets.v;
	if (ref.vt != null && ref.vn != null) return `${v}/${ref.vt + offsets.vt}/${ref.vn + offsets.vn}`;
	if (ref.vt != null) return `${v}/${ref.vt + offsets.vt}`;
	if (ref.vn != null) return `${v}//${ref.vn + offsets.vn}`;
	return String(v);
}

function appendBlock(
	out: string[],
	block: MeshBlock,
	offsets: { v: number; vt: number; vn: number }
) {
	if (out.length > 0 && out[out.length - 1].trim() !== '') out.push('');
	out.push(...trimTrailingBlankLines(block.lines));
	out.push(...block.v, ...block.vt, ...block.vn, ...block.vp, ...block.otherMesh);
	for (const face of block.faces) {
		out.push(`f ${face.map((ref) => faceRef(ref, offsets)).join(' ')}`);
	}
}

function boundsForIndices(vertices: Vec3[], indices: Set<number>): Bounds | null {
	const points = [...indices]
		.map((index) => vertices[index - 1])
		.filter((point): point is Vec3 => !!point);
	if (!points.length) return null;
	const min: Vec3 = [...points[0]] as Vec3;
	const max: Vec3 = [...points[0]] as Vec3;
	for (const point of points.slice(1)) {
		for (let axis = 0; axis < 3; axis += 1) {
			min[axis] = Math.min(min[axis], point[axis]);
			max[axis] = Math.max(max[axis], point[axis]);
		}
	}
	return {
		min,
		max,
		center: [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2]
	};
}

function blockComponentBounds(block: MeshBlock): Bounds[] {
	const vertices = block.v.map(parseVertexLine);
	if (vertices.some((vertex) => !vertex)) return [];
	const typedVertices = vertices as Vec3[];
	const parent = new Map<number, number>();
	const find = (value: number): number => {
		const next = parent.get(value) ?? value;
		if (next === value) return value;
		const root = find(next);
		parent.set(value, root);
		return root;
	};
	const union = (a: number, b: number) => {
		const rootA = find(a);
		const rootB = find(b);
		if (rootA !== rootB) parent.set(rootB, rootA);
	};
	for (const face of block.faces) {
		const refs = face.map((ref) => ref.v).filter((index) => index >= 1 && index <= block.v.length);
		for (const index of refs) parent.set(index, parent.get(index) ?? index);
		for (const index of refs.slice(1)) union(refs[0], index);
	}
	const groups = new Map<number, Set<number>>();
	for (const index of parent.keys()) {
		const root = find(index);
		if (!groups.has(root)) groups.set(root, new Set());
		groups.get(root)?.add(index);
	}
	return [...groups.values()]
		.map((indices) => boundsForIndices(typedVertices, indices))
		.filter((bounds): bounds is Bounds => !!bounds);
}

function distance(a: Vec3, b: Vec3): number {
	return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function boundsDiagonal(bounds: Bounds): number {
	return distance(bounds.min, bounds.max);
}

function preservationIssue(
	originalScene: string,
	targetObjectId: string,
	enhancedScene: string
): string | null {
	const originalBlock = parseObjForReindex(originalScene).blocks.find(
		(block) => block.name === targetObjectId
	);
	const enhancedBlock = parseObjForReindex(enhancedScene).blocks.find(
		(block) => block.name === targetObjectId
	);
	if (!originalBlock || !enhancedBlock)
		return `target object '${targetObjectId}' missing after UV dream`;
	const originalComponents = blockComponentBounds(originalBlock);
	const enhancedComponents = blockComponentBounds(enhancedBlock);
	if (originalComponents.length >= 2 && enhancedComponents.length < originalComponents.length) {
		return `UV dream reduced '${targetObjectId}' from ${originalComponents.length} disconnected components to ${enhancedComponents.length}`;
	}
	if (originalComponents.length < 2 || enhancedComponents.length < originalComponents.length)
		return null;
	const originalBounds = boundsForIndices(
		originalBlock.v.map(parseVertexLine).filter((point): point is Vec3 => !!point),
		new Set(originalBlock.v.map((_, index) => index + 1))
	);
	const tolerance = Math.max(0.35 * (originalBounds ? boundsDiagonal(originalBounds) : 0), 0.35);
	const unmatched = [...enhancedComponents];
	for (const original of originalComponents) {
		let bestIndex = -1;
		let bestDistance = Number.POSITIVE_INFINITY;
		for (const [index, enhanced] of unmatched.entries()) {
			const candidateDistance = distance(original.center, enhanced.center);
			if (candidateDistance < bestDistance) {
				bestDistance = candidateDistance;
				bestIndex = index;
			}
		}
		if (bestIndex < 0 || bestDistance > tolerance) {
			return `UV dream moved part of '${targetObjectId}' too far from its original paired layout`;
		}
		unmatched.splice(bestIndex, 1);
	}
	return null;
}

function blockWithUvTextureMetadata(
	block: MeshBlock,
	args: {
		targetObjectId: string;
		diffuseUrl: string;
		heightUrl: string;
		sourceUvUrl: string;
		finalUvUrl: string;
		amount: number;
		shade: 'smooth' | 'flat';
	}
): MeshBlock {
	const materialName = `${args.targetObjectId}_uv_dream_mat`;
	const nextLines: string[] = [];
	let inserted = false;
	for (const [index, line] of block.lines.entries()) {
		const trimmed = line.trim();
		if (
			/^#@workflow_step:\s*uv_dream_enhance\b/i.test(trimmed) ||
			/^#@params:\s*dream_/i.test(trimmed) ||
			/^#@controls:\s*$/i.test(trimmed) ||
			/^#@\s*-\s*(?:slider|select)\s+key=dream_/i.test(trimmed) ||
			/^#@post:\s*$/i.test(trimmed) ||
			/^#@\s*-\s*material\s+name=.*_uv_dream_mat\b/i.test(trimmed) ||
			/^#@material:\s*.*_uv_dream_mat\b/i.test(trimmed) ||
			/^#@texture:\s*kind=(?:diffuse|height)\s+/i.test(trimmed) ||
			/^#@debug_image:\s*kind=(?:source_uv|final_uv)\s+/i.test(trimmed) ||
			/^#@shade:\s*/i.test(trimmed)
		) {
			continue;
		}
		nextLines.push(line);
		if (index === 0) {
			nextLines.push('#@workflow_step: uv_dream_enhance');
			nextLines.push(
				`#@params: dream_displacement_amount=${args.amount.toFixed(4)}, dream_shade=${args.shade}, dream_topology=texture_preserve`
			);
			nextLines.push('#@controls:');
			nextLines.push(
				'#@ - slider key=dream_displacement_amount label=Displacement min=0 max=2 step=0.05'
			);
			nextLines.push('#@ - select key=dream_shade label=Shading options=smooth|flat');
			nextLines.push('#@post:');
			nextLines.push(`#@ - material name=${materialName}`);
			nextLines.push(`#@texture: kind=diffuse path=${args.diffuseUrl}`);
			nextLines.push(`#@texture: kind=height path=${args.heightUrl}`);
			nextLines.push(`#@debug_image: kind=source_uv path=${args.sourceUvUrl}`);
			nextLines.push(`#@debug_image: kind=final_uv path=${args.finalUvUrl}`);
			nextLines.push(`#@shade: ${args.shade}`);
			inserted = true;
		}
	}
	return { ...block, lines: inserted ? nextLines : block.lines };
}

function spliceEnhancedObjectScene(
	originalScene: string,
	targetObjectId: string,
	enhancedObject: string
): string {
	const original = parseObjForReindex(originalScene);
	const enhanced = parseObjForReindex(enhancedObject);
	const replacement =
		enhanced.blocks.find((block) => block.name === targetObjectId) ?? enhanced.blocks[0];
	if (!replacement) return enhancedObject;
	const out = trimTrailingBlankLines(original.header);
	const existingHeader = new Set(out.map((line) => line.trim()));
	for (const line of enhanced.header) {
		const trimmed = line.trim();
		if (trimmed.startsWith('#@material_preset:') && !existingHeader.has(trimmed)) {
			out.push(line);
			existingHeader.add(trimmed);
		}
	}
	let offsets = { v: 0, vt: 0, vn: 0 };
	let replaced = false;
	for (const originalBlock of original.blocks) {
		const block = originalBlock.name === targetObjectId ? replacement : originalBlock;
		if (originalBlock.name === targetObjectId) replaced = true;
		appendBlock(out, block, offsets);
		offsets = {
			v: offsets.v + block.v.length,
			vt: offsets.vt + block.vt.length,
			vn: offsets.vn + block.vn.length
		};
	}
	if (!replaced) appendBlock(out, replacement, offsets);
	return `${trimTrailingBlankLines(out).join('\n')}\n`;
}

function spliceTexturePreservedObjectScene(
	originalScene: string,
	targetObjectId: string,
	args: {
		diffuseUrl: string;
		heightUrl: string;
		sourceUvUrl: string;
		finalUvUrl: string;
		amount: number;
		shade: 'smooth' | 'flat';
	}
): string {
	const original = parseObjForReindex(originalScene);
	const materialName = `${targetObjectId}_uv_dream_mat`;
	const out = trimTrailingBlankLines(
		original.header.filter((line) => !line.trim().startsWith(`#@material_preset: ${materialName} `))
	);
	out.push(
		`#@material_preset: ${materialName} color=#d8d1c4 roughness=0.82 metalness=0.0 shade_smooth=${args.shade === 'flat' ? 'false' : 'true'}`
	);
	let offsets = { v: 0, vt: 0, vn: 0 };
	for (const originalBlock of original.blocks) {
		const block =
			originalBlock.name === targetObjectId
				? blockWithUvTextureMetadata(originalBlock, { targetObjectId, ...args })
				: originalBlock;
		appendBlock(out, block, offsets);
		offsets = {
			v: offsets.v + block.v.length,
			vt: offsets.vt + block.vt.length,
			vn: offsets.vn + block.vn.length
		};
	}
	return `${trimTrailingBlankLines(out).join('\n')}\n`;
}

export const POST: RequestHandler = async ({ request }) => {
	let body: {
		liveObj?: string;
		targetObjectId?: string;
		heightBmpDataUrl?: string;
		diffuseBmpDataUrl?: string;
		amount?: number;
		shade?: 'smooth' | 'flat';
		mode?: 'displace' | 'map-remesh';
	} | null;
	try {
		body = (await request.json()) as typeof body;
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err);
		throw error(413, `Invalid or oversized UV dream enhancement request body: ${message}`);
	}
	if (!body?.liveObj?.trim()) throw error(400, 'liveObj is required');
	if (!body.targetObjectId?.trim()) throw error(400, 'targetObjectId is required');
	if (!body.heightBmpDataUrl?.trim()) throw error(400, 'heightBmpDataUrl is required');
	const generatedDiffuseBmp = body.diffuseBmpDataUrl?.trim()
		? dataUrlBytes(body.diffuseBmpDataUrl, 'data:image/bmp')
		: null;

	try {
		const result = await enhanceUvDreamWithExecutor({
			liveObj: body.liveObj,
			targetObjectId: body.targetObjectId.trim(),
			heightBmp: dataUrlBytes(body.heightBmpDataUrl, 'data:image/bmp'),
			diffuseBmp: generatedDiffuseBmp ?? undefined,
			amount: clampAmount(body.amount),
			shade: body.shade === 'flat' ? 'flat' : 'smooth',
			mode: body.mode === 'map-remesh' ? 'map-remesh' : 'displace'
		});
		const artifacts = {
			sourceUvUrl: artifactUrl(result.artifacts.sourceUvPng, 'image/png', 'source-uv.png'),
			finalUvUrl: artifactUrl(result.artifacts.finalUvPng, 'image/png', 'final-uv.png'),
			heightUrl: artifactUrl(result.artifacts.heightPng, 'image/png', 'height-tile.png'),
			diffuseUrl: artifactUrl(result.artifacts.diffusePng, 'image/png', 'diffuse.png'),
			manifestUrl: artifactUrl(
				new TextEncoder().encode(result.artifacts.manifestJson),
				'application/json',
				'uv-dream-manifest.json'
			)
		};
		const targetObjectId = body.targetObjectId.trim();
		let enhancedObj = result.executedObj;
		enhancedObj = enhancedObj.replace(
			/\bpath=[^\s]*diffuse\.png\b/g,
			`path=${artifacts.diffuseUrl}`
		);
		enhancedObj = enhancedObj.replace(
			/\bpath=[^\s]*height-tile\.png\b/g,
			`path=${artifacts.heightUrl}`
		);
		enhancedObj = enhancedObj.replace(
			/\bpath=[^\s]*source-uv\.png\b/g,
			`path=${artifacts.sourceUvUrl}`
		);
		enhancedObj = enhancedObj.replace(
			/\bpath=[^\s]*final-uv\.png\b/g,
			`path=${artifacts.finalUvUrl}`
		);
		const splicedLiveObj = spliceEnhancedObjectScene(body.liveObj, targetObjectId, enhancedObj);
		const warnings = [...result.warnings];
		const issue = preservationIssue(body.liveObj, targetObjectId, splicedLiveObj);
		const liveObj = issue
			? spliceTexturePreservedObjectScene(body.liveObj, targetObjectId, {
					diffuseUrl: artifacts.diffuseUrl,
					heightUrl: artifacts.heightUrl,
					sourceUvUrl: artifacts.sourceUvUrl,
					finalUvUrl: artifacts.finalUvUrl,
					amount: clampAmount(body.amount),
					shade: body.shade === 'flat' ? 'flat' : 'smooth'
				})
			: splicedLiveObj;
		if (issue) {
			warnings.push(`${issue}; preserved original geometry and applied UV texture metadata only.`);
		}
		return json({
			liveObj,
			executedObj: liveObj,
			artifacts,
			expiresInSeconds: 15 * 60,
			warnings
		});
	} catch (err) {
		throw error(400, err instanceof Error ? err.message : 'Unable to apply UV dream enhancement');
	}
};
