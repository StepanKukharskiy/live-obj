import { describe, expect, it } from 'vitest';
import {
	addDreamMetadataToLiveObj,
	computeDreamRebuildAlignment,
	missingDreamRebuildDepthMaps,
	missingDreamRebuildMasks,
	missingDreamRebuildViews
} from './dreamRebuild';

describe('dream rebuild helpers', () => {
	it('computes target-object alignment from OBJ bounds', () => {
		const liveObj = [
			'o wall',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 1 2 3',
			'',
			'o roof',
			'v -2 10 4',
			'v 2 10 4',
			'v 2 14 7',
			'v -2 14 7',
			'f 4 5 6 7'
		].join('\n');

		const alignment = computeDreamRebuildAlignment(liveObj, 'roof');

		expect(alignment.bounds.min).toEqual([-2, 10, 4]);
		expect(alignment.bounds.max).toEqual([2, 14, 7]);
		expect(alignment.worldFromCanonical.translate).toEqual([-2, 10, 4]);
		expect(alignment.worldFromCanonical.scale).toEqual([4, 4, 3]);
	});

	it('adds dream metadata before target mesh cache lines', () => {
		const liveObj = [
			'o roof',
			'#@source: llm_mesh',
			'#@semantic: simple roof',
			'v -1 0 0',
			'v 1 0 0',
			'v 1 1 1',
			'f 1 2 3'
		].join('\n');

		const next = addDreamMetadataToLiveObj({
			liveObj,
			targetObjectId: 'roof',
			prompt: 'folded fabric roof'
		});

		expect(next).toContain('#@dream:\n#@ - method=tsdf prompt="folded fabric roof"');
		expect(next.indexOf('#@dream:')).toBeLessThan(next.indexOf('v -1 0 0'));
		expect(next).toContain('bbox_min=[-1,0,0]');
		expect(next).toContain('bbox_max=[1,1,1]');
	});

	it('reports missing six-view image inputs', () => {
		const dataUrl = 'data:image/png;base64,abc';
		expect(
			missingDreamRebuildViews({
				top: dataUrl,
				bottom: dataUrl,
				left: dataUrl,
				right: dataUrl,
				front: dataUrl
			})
		).toEqual(['back']);
	});

	it('reports missing six-view mask inputs', () => {
		const mask = { width: 2, height: 2, rows: ['11', '11'] };
		expect(
			missingDreamRebuildMasks({
				top: mask,
				bottom: mask,
				left: mask,
				right: mask,
				front: mask
			})
		).toEqual(['back']);
	});

	it('reports missing six-view depth map inputs', () => {
		const depth = { width: 2, height: 2, rows: ['ff', 'ff'] };
		expect(
			missingDreamRebuildDepthMaps({
				top: depth,
				bottom: depth,
				left: depth,
				right: depth,
				front: depth
			})
		).toEqual(['back']);
	});
});
