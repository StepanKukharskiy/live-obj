import { describe, expect, it } from 'vitest';
import { validateRawPostSource } from '$lib/liveObj/rawPostValidation';
import {
	addDefaultRawObjControls,
	appendGeneratedPart,
	normalizeGeneratedPartMetadata,
	parseJsonObject,
	rawObjControlIssues,
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

	it('repairs common generated raw-post metadata omissions', () => {
		const part = [
			'o fabric_roof',
			'#@material white_fabric',
			'#@post subdivide levels=2',
			'v 0 0 0',
			'v 1 0 0',
			'v 1 1 0',
			'v 0 1 0',
			'f 1 2 3 4'
		].join('\n');

		const normalized = normalizeGeneratedPartMetadata(part);
		const validation = validateRawPostSource(normalized);

		expect(normalized).toContain('#@source: llm_mesh');
		expect(normalized).toContain('#@semantic: fabric roof');
		expect(normalized).toContain('#@post:\n#@ - material name=white_fabric');
		expect(normalized).toContain('#@post:\n#@ - subdivide level=2');
		expect(validation.valid).toBe(true);
		expect(validation.warnings).toEqual([]);
	});

	it('normalizes raw-post tag name aliases to value syntax', () => {
		const part = [
			'o glazing',
			'#@source: llm_mesh',
			'#@semantic: flat glass panels',
			'#@post:',
			'#@ - tag name=glass_tint',
			'#@post tag id=window_group',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 1 2 3'
		].join('\n');

		const normalized = normalizeGeneratedPartMetadata(part);

		expect(normalized).toContain('#@ - tag value=glass_tint');
		expect(normalized).toContain('#@post:\n#@ - tag value=window_group');
		expect(normalized).not.toContain('tag name=');
		expect(normalized).not.toContain('tag id=');
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

	it('parses JSON embedded in extra model text', () => {
		const parsed = parseJsonObject<{ parts: Array<{ id: string }> }>(
			'Here is the plan:\n{"parts":[{"id":"tower_core"}]}\nDone.'
		);

		expect(parsed.parts[0].id).toBe('tower_core');
	});

	it('explains likely truncated JSON responses', () => {
		expect(() =>
			parseJsonObject('{"parts":[{"id":"fluid_tower_shell","prompt":"build a flowing')
		).toThrow(/incomplete JSON.*output\/completion token cap/i);
	});

	it('explains non-JSON model responses', () => {
		expect(() => parseJsonObject('I cannot create that plan.')).toThrow(
			/Model did not return a JSON object/
		);
	});

	it('allows visible raw OBJ objects without controls', () => {
		const source = [
			'o body',
			'#@source: llm_mesh',
			'#@semantic: main body',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 1 2 3',
			'',
			'o tuned_roof',
			'#@source: llm_mesh',
			'#@params: roof_scale=1',
			'#@controls:',
			'#@ - slider key=roof_scale label=Roof_scale min=0.5 max=2 step=0.05',
			'#@post:',
			'#@ - transform scale=[roof_scale,1,roof_scale]',
			'v 0 0 1',
			'v 1 0 1',
			'v 0 1 1',
			'f 4 5 6'
		].join('\n');

		expect(rawObjControlIssues(source)).toEqual([]);
	});

	it('can add neutral fallback controls to visible raw OBJ objects', () => {
		const source = [
			'o bag_base_cup',
			'#@source: llm_mesh',
			'#@semantic: tulip handbag base cup',
			'v 0 0 0',
			'v 1 0 0',
			'v 0 1 0',
			'f 1 2 3'
		].join('\n');

		const repaired = addDefaultRawObjControls(source);

		expect(rawObjControlIssues(repaired)).toEqual([]);
		expect(repaired).toContain('#@controls:');
		expect(repaired).toContain('#@ - transform scale=[control_scale,control_scale,control_scale]');
		expect(validateRawPostSource(repaired).valid).toBe(true);
	});
});
