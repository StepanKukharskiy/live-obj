import { describe, expect, it } from 'vitest';
import { appendGeneratedPart, parseJsonObject, validateLiveObj } from './iterative';

describe('iterative Live OBJ helpers', () => {
	it('remaps local part face indices when appending', () => {
		const current = [
			'#@scene',
			'#@units: meters',
			'#@up: z',
			'#@live_obj_version: 0.1',
			'',
			'o base',
			'#@source: llm_mesh',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 1 2 3'
		].join('\n');
		const part = [
			'o canopy',
			'#@source: llm_mesh',
			'v 0 0 1',
			'v 1 0 1',
			'v 0 1 1',
			'f 1 2 3'
		].join('\n');

		const appended = appendGeneratedPart(current, part);

		expect(appended.normalizedPart).toContain('f 4 5 6');
		const validation = validateLiveObj(appended.liveObj, current);
		expect(validation.valid).toBe(true);
		expect(validation.addedObjectNames).toEqual(['canopy']);
	});

	it('rejects part faces outside local vertex range', () => {
		const part = ['o bad_part', '#@source: llm_mesh', 'v 0 0 0', 'v 1 0 0', 'f 1 2 3'].join('\n');

		expect(() => appendGeneratedPart('', part)).toThrow(/only defines 2 vertices/);
	});

	it('normalizes offset local face indices before appending', () => {
		const part = [
			'o offset_part',
			'#@source: llm_mesh',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 5 6 7'
		].join('\n');

		const appended = appendGeneratedPart('', part);

		expect(appended.normalizedPart).toContain('f 1 2 3');
		expect(validateLiveObj(appended.liveObj).valid).toBe(true);
	});

	it('remaps local line indices when appending', () => {
		const current = [
			'#@live_obj_version: 0.1',
			'o base',
			'#@source: llm_mesh',
			'v 0 0 0',
			'v 1 0 0',
			'f 1 2 1'
		].join('\n');
		const part = ['o seams', '#@source: llm_mesh', 'v 0 0 1', 'v 1 0 1', 'l 1 2'].join('\n');

		const appended = appendGeneratedPart(current, part);

		expect(appended.normalizedPart).toContain('l 3 4');
	});

	it('parses fenced JSON model output', () => {
		const parsed = parseJsonObject<{ parts: Array<{ id: string }> }>(
			'```json\n{"parts":[{"id":"deck"}]}\n```'
		);
		expect(parsed.parts[0].id).toBe('deck');
	});
});
