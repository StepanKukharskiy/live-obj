import { describe, expect, it } from 'vitest';
import { normalizeRawPostHeader } from './rawPostHeader';

describe('normalizeRawPostHeader', () => {
	it('normalizes the common raw_post workflow typo', () => {
		const normalized = normalizeRawPostHeader(`#@scene
#@workflow: raw_poast
#@live_obj_version: 0.1
#@up: y
o vase
#@source: llm_mesh
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(normalized).toContain('#@workflow: raw_post');
		expect(normalized).not.toContain('raw_poast');
	});
});
