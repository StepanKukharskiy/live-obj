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

function meshToken(line: string): string {
	return /^(\S+)/.exec(line.trim())?.[1]?.toLowerCase() ?? '';
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
			current = { name: objectMatch[1], lines: [line], v: [], vt: [], vn: [], vp: [], otherMesh: [], faces: [] };
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
				if (!v || v.block !== current || (vt && vt.block !== current) || (vn && vn.block !== current)) {
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

function appendBlock(out: string[], block: MeshBlock, offsets: { v: number; vt: number; vn: number }) {
	if (out.length > 0 && out[out.length - 1].trim() !== '') out.push('');
	out.push(...trimTrailingBlankLines(block.lines));
	out.push(...block.v, ...block.vt, ...block.vn, ...block.vp, ...block.otherMesh);
	for (const face of block.faces) {
		out.push(`f ${face.map((ref) => faceRef(ref, offsets)).join(' ')}`);
	}
}

function spliceEnhancedObjectScene(originalScene: string, targetObjectId: string, enhancedObject: string): string {
	const original = parseObjForReindex(originalScene);
	const enhanced = parseObjForReindex(enhancedObject);
	const replacement = enhanced.blocks.find((block) => block.name === targetObjectId) ?? enhanced.blocks[0];
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

export const POST: RequestHandler = async ({ request }) => {
	const body = (await request.json().catch(() => null)) as {
		liveObj?: string;
		targetObjectId?: string;
		heightBmpDataUrl?: string;
		diffusePngDataUrl?: string;
		diffuseBmpDataUrl?: string;
		amount?: number;
		shade?: 'smooth' | 'flat';
		mode?: 'displace' | 'map-remesh';
	} | null;
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
		let liveObj = result.executedObj;
		liveObj = liveObj.replace(/\bpath=[^\s]*diffuse\.png\b/g, `path=${artifacts.diffuseUrl}`);
		liveObj = liveObj.replace(/\bpath=[^\s]*height-tile\.png\b/g, `path=${artifacts.heightUrl}`);
		liveObj = liveObj.replace(/\bpath=[^\s]*source-uv\.png\b/g, `path=${artifacts.sourceUvUrl}`);
		liveObj = liveObj.replace(/\bpath=[^\s]*final-uv\.png\b/g, `path=${artifacts.finalUvUrl}`);
		liveObj = spliceEnhancedObjectScene(body.liveObj, body.targetObjectId.trim(), liveObj);
		return json({
			liveObj,
			executedObj: liveObj,
			artifacts,
			expiresInSeconds: 15 * 60,
			warnings: result.warnings
		});
	} catch (err) {
		throw error(400, err instanceof Error ? err.message : 'Unable to apply UV dream enhancement');
	}
};
