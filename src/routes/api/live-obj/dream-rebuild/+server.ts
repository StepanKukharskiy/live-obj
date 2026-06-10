import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { reconstructDreamRebuildWithExecutor, stripCodeFences } from '$lib/server/liveObj/pipeline';
import {
	addDreamMetadataToLiveObj,
	computeDreamRebuildAlignment,
	DREAM_REBUILD_VIEW_NAMES,
	missingDreamRebuildDepthMaps,
	missingDreamRebuildMasks,
	type DreamRebuildDepthMap,
	type DreamRebuildMask,
	type DreamRebuildViewName
} from '$lib/server/liveObj/dreamRebuild';

type Body = {
	liveObj?: string;
	targetObjectId?: string;
	prompt?: string;
	reconstruction?: 'tsdf';
	profile?: 'object' | 'surface';
	mode?: 'enhance' | 'replace';
	resolution?: number;
	viewMasks?: Partial<Record<DreamRebuildViewName, DreamRebuildMask>>;
	viewDepthMaps?: Partial<Record<DreamRebuildViewName, DreamRebuildDepthMap>>;
};

function parseBody(raw: unknown): Body {
	if (!raw || typeof raw !== 'object') return {};
	return raw as Body;
}

function degenerateAxisWarnings(size: [number, number, number]): string[] {
	return size.flatMap((value, axis) =>
		Math.abs(value) < 1e-6
			? [
					`Target bounds have near-zero ${['x', 'y', 'z'][axis]} size; TSDF should inflate that axis before reconstruction.`
				]
			: []
	);
}

export const POST: RequestHandler = async ({ request }) => {
	let body: Body;
	try {
		body = parseBody(await request.json());
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const liveObj = stripCodeFences(body.liveObj ?? '').trim();
	const prompt = body.prompt?.trim() ?? '';
	const targetObjectId = body.targetObjectId?.trim() || undefined;
	const reconstruction = body.reconstruction ?? 'tsdf';
	const profile =
		body.profile ??
		(/\b(roof|canopy|terrain|cloth|fabric|surface|panel|skin)\b/i.test(prompt) ? 'surface' : 'object');
	const mode =
		body.mode ?? (/\b(from scratch|new topology|complex spatial|reconstruct from scratch)\b/i.test(prompt) ? 'replace' : 'enhance');
	const resolution = body.resolution;
	const viewMasks = body.viewMasks ?? {};
	const viewDepthMaps = body.viewDepthMaps ?? {};

	if (!liveObj) throw error(400, 'liveObj is required');
	if (!prompt) throw error(400, 'prompt is required');
	if (!targetObjectId) throw error(400, 'targetObjectId is required');
	if (reconstruction !== 'tsdf') throw error(400, 'Only reconstruction="tsdf" is supported');

	const missingMasks = missingDreamRebuildMasks(viewMasks);
	if (missingMasks.length > 0) {
		throw error(400, `Missing six-view masks: ${missingMasks.join(', ')}`);
	}
	const missingDepthMaps = missingDreamRebuildDepthMaps(viewDepthMaps);
	if (missingDepthMaps.length > 0) {
		throw error(400, `Missing six-view depth maps: ${missingDepthMaps.join(', ')}`);
	}

	try {
		const alignment = computeDreamRebuildAlignment(liveObj, targetObjectId);
		const annotatedLiveObj = addDreamMetadataToLiveObj({
			liveObj,
			targetObjectId,
			prompt,
			reconstruction,
			alignment
		});
		const result = await reconstructDreamRebuildWithExecutor({
			liveObj: annotatedLiveObj,
			targetObjectId,
			...(resolution ? { resolution } : {}),
			profile,
			mode,
			viewMasks: viewMasks as Record<DreamRebuildViewName, DreamRebuildMask>,
			viewDepthMaps: viewDepthMaps as Record<DreamRebuildViewName, DreamRebuildDepthMap>
		});
		const warnings = [...degenerateAxisWarnings(alignment.bounds.size), ...result.warnings];

		return json({
			liveObj: result.executedObj,
			executedObj: result.executedObj,
			dream: {
				status: 'reconstructed',
				reconstruction,
				profile,
				mode,
				targetObjectId,
				views: DREAM_REBUILD_VIEW_NAMES.map((name) => ({ name, present: true })),
				alignment,
				warnings
			}
		});
	} catch (err) {
		throw error(400, err instanceof Error ? err.message : 'Unable to prepare dream rebuild');
	}
};
