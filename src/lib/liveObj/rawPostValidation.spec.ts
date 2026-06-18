import { describe, expect, it } from 'vitest';
import { validateRawPostSource } from './rawPostValidation';

describe('raw-post validation', () => {
	it('accepts a valid raw-post object with post metadata', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o roof
#@source: llm_mesh
#@semantic: heavy roof
#@post:
#@ - transform position=[0,1,0]
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
		expect(result.warnings).toEqual([]);
		expect(result.objectNames).toEqual(['roof']);
	});

	it('rejects unsupported raw-post ops and missing face indices', () => {
		const result = validateRawPostSource(`#@live_obj_version: 0.1
o wall
#@source: llm_mesh
#@semantic: wall
#@post:
#@ - inflate amount=1
v 0 0 0
v 1 0 0
f 1 2 3
`);

		expect(result.valid).toBe(false);
		expect(result.errors.join('\n')).toContain("unsupported #@post op 'inflate'");
		expect(result.errors.join('\n')).toContain('references missing vertex 3');
	});

	it('rejects inline colon post ops instead of ignoring them', () => {
		const result = validateRawPostSource(`#@live_obj_version: 0.1
o wall
#@source: llm_mesh
#@semantic: wall
#@post: frobnicate amount=1
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(false);
		expect(result.errors.join('\n')).toContain('malformed #@post block syntax');
	});

	it('rejects deform post ops without an executable expression', () => {
		const result = validateRawPostSource(`#@live_obj_version: 0.1
o wall
#@source: llm_mesh
#@semantic: wall
#@post:
#@ - deform mode=petal_ridges amount=1
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(false);
		expect(result.errors.join('\n')).toContain('malformed #@post deform');
	});

	it('rejects unsupported attributes on otherwise supported post ops', () => {
		const result = validateRawPostSource(`#@live_obj_version: 0.1
o wall
#@source: llm_mesh
#@semantic: wall
#@post:
#@ - smooth iterations=2 preserve_volume=true
#@ - snap_to_ground axis=y mode=min
#@ - tag name=decorative
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(false);
		expect(result.errors.join('\n')).toContain(
			"unsupported #@post smooth attribute 'preserve_volume'"
		);
		expect(result.errors.join('\n')).toContain(
			"unsupported #@post snap_to_ground attribute 'mode'"
		);
		expect(result.errors.join('\n')).toContain("unsupported #@post tag attribute 'name'");
	});

	it('accepts raw-post semantic edit metadata', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o roof
#@source: llm_mesh
#@semantic: heavy chapel roof
#@part: id=roof role=dominant_form edit=direct
#@bbox: min=[-4,2,-2] max=[4,5,2]
#@lock: silhouette, material
#@opening: id=front_window type=glazed role=glass loop=[[-1,0,0],[1,0,0],[1,2,0],[-1,2,0]] normal=[0,0,-1]
#@anchor: id=roof_left_edge at=[-4,2,0]
#@constraint: roof must_touch walls
#@variant: id=base name="Base"
#@post:
#@ - build_glazed_openings type=glazed frame_width=0.08 frame_depth=0.04 panel_recess=0.02 panel_thickness=0.01 mode=append
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
		expect(result.warnings).toEqual([]);
	});

	it('rejects malformed opening metadata', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o facade
#@source: llm_mesh
#@semantic: facade
#@opening: id=front_window normal=[0,0,-1]
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(false);
		expect(result.errors.join('\n')).toContain('malformed #@opening');
	});

	it('rejects malformed bbox and anchor metadata', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o roof
#@source: llm_mesh
#@semantic: heavy chapel roof
#@bbox: min=[-4,2,-2]
#@anchor: id=roof_left_edge
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(false);
		expect(result.errors.join('\n')).toContain('malformed #@bbox');
		expect(result.errors.join('\n')).toContain('malformed #@anchor');
	});

	it('validates legacy space-form bbox and anchor metadata', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o roof
#@source: llm_mesh
#@semantic: heavy chapel roof
#@bbox min=[-4,2,-2] max=[4,5,2]
#@anchor id=roof_left_edge at=[-4,2,0]
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
	});

	it('warns when usemtl directives are overwritten before any faces use them', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
o wheel
#@source: llm_mesh
#@semantic: wheel with intended tire and rim materials
usemtl tire_rubber
usemtl wheel_cover
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
		expect(result.warnings.join('\n')).toContain(
			"usemtl 'tire_rubber' in object 'wheel'"
		);
		expect(result.warnings.join('\n')).toContain('before the next usemtl');
	});

	it('accepts usemtl directives that each own a following face block', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
o two_material_panel
#@source: llm_mesh
#@semantic: panel with two face materials
v 0 0 0
v 1 0 0
v 0 1 0
v 1 1 0
usemtl first
f 1 2 3
usemtl second
f 2 4 3
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
		expect(result.warnings).toEqual([]);
	});
});
