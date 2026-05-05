type ObjBlock = {
	key: string;
	lines: string[];
	mesh: ObjMesh;
};

const OBJECT_DECL_RE = /^\s*([og])\s+(.+?)\s*$/;

type FaceToken = {
	localVertexIndex: number;
	suffix: string;
};

type ObjMesh = {
	vertexLines: string[];
	otherMeshLines: string[];
	faceLines: FaceToken[][];
};

function isMeshLine(line: string): boolean {
	const token = /^(\S+)/.exec(line.trim())?.[1]?.toLowerCase();
	return token === 'v' || token === 'vn' || token === 'vt' || token === 'vp' || token === 'f' || token === 'fo' || token === 'l';
}

function emptyMesh(): ObjMesh {
	return { vertexLines: [], otherMeshLines: [], faceLines: [] };
}

function parseFaceVertexIndex(token: string): { index: number; suffix: string } | null {
	const match = /^(-?\d+)(.*)$/.exec(token);
	if (!match) return null;
	return { index: Number(match[1]), suffix: match[2] ?? '' };
}

function parseObjBlocks(text: string): { header: string[]; blocks: ObjBlock[] } {
	const header: string[] = [];
	const blocks: ObjBlock[] = [];
	let current: ObjBlock | null = null;
	let globalVertexCount = 0;
	const vertexOwner = new Map<number, { block: ObjBlock; localVertexIndex: number }>();

	for (const line of text.split(/\r?\n/)) {
		const decl = OBJECT_DECL_RE.exec(line);
		if (decl) {
			current = { key: `${decl[1]} ${decl[2].trim()}`, lines: [line], mesh: emptyMesh() };
			blocks.push(current);
			continue;
		}

		if (!current) {
			header.push(line);
			continue;
		}

		current.lines.push(line);
		const token = /^(\S+)/.exec(line.trim())?.[1]?.toLowerCase();
		if (token === 'v') {
			current.mesh.vertexLines.push(line);
			globalVertexCount += 1;
			vertexOwner.set(globalVertexCount, {
				block: current,
				localVertexIndex: current.mesh.vertexLines.length
			});
			continue;
		}
		if (token === 'f') {
			const faceTokens: FaceToken[] = [];
			for (const rawToken of line.trim().split(/\s+/).slice(1)) {
				const parsed = parseFaceVertexIndex(rawToken);
				if (!parsed) continue;
				const index = parsed.index < 0 ? globalVertexCount + parsed.index + 1 : parsed.index;
				const owner = vertexOwner.get(index);
				if (owner?.block === current) {
					faceTokens.push({
						localVertexIndex: owner.localVertexIndex,
						suffix: parsed.suffix
					});
				}
			}
			if (faceTokens.length >= 3) current.mesh.faceLines.push(faceTokens);
			continue;
		}
		if (isMeshLine(line)) current.mesh.otherMeshLines.push(line);
	}

	return { header, blocks };
}

function trimTrailingBlanks(lines: string[]): string[] {
	const out = [...lines];
	while (out.length && out[out.length - 1].trim() === '') out.pop();
	return out;
}

export function containsObjMeshLines(text: string): boolean {
	return text.split(/\r?\n/).some(isMeshLine);
}

export function mergeMetadataWithMesh(editedMetadataText: string, fullObjText: string): string {
	const edited = parseObjBlocks(editedMetadataText);
	const full = parseObjBlocks(fullObjText);
	const fullMeshByKey = new Map(full.blocks.map((block) => [block.key, block.mesh]));
	const out: string[] = trimTrailingBlanks(edited.header);
	let wroteBlock = false;
	let nextVertexIndex = 1;

	for (const block of edited.blocks) {
		if (wroteBlock && out.length && out[out.length - 1].trim() !== '') out.push('');
		out.push(...trimTrailingBlanks(block.lines));
		const mesh = fullMeshByKey.get(block.key);
		if (mesh) {
			out.push(...mesh.vertexLines);
			out.push(...mesh.otherMeshLines);
			for (const face of mesh.faceLines) {
				out.push(
					`f ${face
						.map((token) => `${nextVertexIndex + token.localVertexIndex - 1}${token.suffix}`)
						.join(' ')}`
				);
			}
			nextVertexIndex += mesh.vertexLines.length;
		}
		wroteBlock = true;
	}

	return `${trimTrailingBlanks(out).join('\n')}\n`;
}
