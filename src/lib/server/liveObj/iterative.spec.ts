import { describe, expect, it } from 'vitest';
import { validateRawPostSource } from '$lib/liveObj/rawPostValidation';
import {
	appendGeneratedPart,
	normalizeGeneratedPartMetadata,
	parseJsonObject,
	validateLiveObj
} from './iterative';

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

	it('normalizes redundant raw-post material target attributes', () => {
		const part = [
			'#@material_preset: glow color=#88ccff roughness=0.25 metalness=0',
			'o fading_memory_core_glow',
			'#@source: llm_mesh',
			'#@semantic: soft internal glow',
			'#@post:',
			'#@ - material name=glow object=fading_memory_core_glow',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 1 2 3'
		].join('\n');

		const normalized = normalizeGeneratedPartMetadata(part);
		const appended = appendGeneratedPart('', part);

		expect(normalized).toContain('#@ - material name=glow');
		expect(normalized).not.toContain('object=fading_memory_core_glow');
		expect(validateRawPostSource(normalized).valid).toBe(true);
		expect(appended.normalizedPart).not.toContain('object=fading_memory_core_glow');
	});

	it('normalizes inline raw-post material id syntax to block syntax', () => {
		const part = [
			'o core',
			'#@source: llm_mesh',
			'#@semantic: glowing core',
			'#@post material id=glow target=core',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 1 2 3'
		].join('\n');

		const normalized = normalizeGeneratedPartMetadata(part);

		expect(normalized).toContain('#@post:\n#@ - material name=glow');
		expect(validateRawPostSource(normalized).valid).toBe(true);
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
