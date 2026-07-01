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

	it('accepts scatter post ops for raw mesh instancing', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
#@params: gate_count=100, field_width=30, field_depth=20, gate_spacing=1.2, scatter_seed=42
o torii_gate
#@source: llm_mesh
#@semantic: single sculpted torii gate used as scatter source
#@post:
#@ - scatter count=gate_count target=landscape width=field_width depth=field_depth axes=xz seed=scatter_seed min_distance=gate_spacing jitter=0.25 normal_offset=0.02 align_to_normal=false rotation=[0,rand*360,0] scale=[0.85,1.15] pivot=[0,0,0]
v -0.5 0 0
v 0.5 0 0
v 0 1 0
f 1 2 3
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
		expect(result.warnings).toEqual([]);
	});

	it('accepts universal raw placement post ops', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o terrain
#@source: llm_mesh
#@semantic: reusable placement surface
v -2 0 -2
v 2 0 -2
v 2 0.2 2
v -2 0.1 2
f 1 2 3 4

o path
#@source: llm_mesh
#@semantic: reusable placement path
v -1 0 -1
v 0 0 0
v 1 0 1
f 5 6 7

o module
#@source: llm_mesh
#@semantic: raw source module
#@post:
#@ - surface_snap target=terrain normal_offset=0.02 align_to_normal=false
#@ - conform target=terrain strength=0.5 normal_offset=0.01
#@ - path_array path=path spacing=0.5 rotation_mode=tangent scale=[0.9,1.1]
#@ - surface_array target=terrain spacing=1.0 pattern=hex count=8 normal_offset=0.02
#@ - orient mode=face target=terrain
#@ - clip axis=y min=0 max=2
v -0.1 0 0
v 0.1 0 0
v 0 0.4 0
f 8 9 10
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
		expect(result.warnings).toEqual([]);
	});

	it('accepts legacy translate alias and surface snapping after arrays', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o field_terrain
#@source: llm_mesh
#@semantic: sloped field terrain
v -2 0 -2
v 2 0.2 -2
v 2 0.5 2
v -2 0.1 2
f 1 2 3 4

o taiko_drum_stand
#@source: llm_mesh
#@semantic: taiko drum stand source arrayed on terrain
#@post:
#@ - array count=2 offset=[1.6,0,0]
#@ - array count=2 offset=[0,0,1.6]
#@ - transform translate=[-0.8,0,-0.8]
#@ - surface_snap target=field_terrain normal_offset=0.02
v -0.2 0 -0.2
v 0.2 0 -0.2
v 0.2 0 0.2
v -0.2 0 0.2
v -0.2 0.3 -0.2
v 0.2 0.3 -0.2
v 0.2 0.3 0.2
v -0.2 0.3 0.2
f 5 6 7 8
f 9 10 11 12
f 5 6 10 9
f 6 7 11 10
f 7 8 12 11
f 8 5 9 12
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
	});

	it('accepts selection-scoped post ops for named OBJ groups', () => {
		const result = validateRawPostSource(`#@scene
#@live_obj_version: 0.1
#@workflow: raw_post
#@up: y
o grouped_raw_mesh
#@source: llm_mesh
#@semantic: raw mesh with named editable subparts
#@params: lift=0.2, bulge=0.3
#@controls:
#@ - slider key=lift label=Lift min=0 max=1 step=0.05
#@ - slider key=bulge label=Bulge min=0 max=1 step=0.05
#@post:
#@ - transform selection=front_skin position=[0,lift,0] pivot=[0,0,0]
#@ - deform group=body position=[x,y+sin(u*pi)*bulge,z]
g body
v -1 0 0
v 0 0 0
v 0 1 0
v -1 1 0
f 1 2 3 4
g front_skin
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
f 5 6 7 8
`);

		expect(result.valid).toBe(true);
		expect(result.errors).toEqual([]);
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
		expect(result.warnings.join('\n')).toContain("usemtl 'tire_rubber' in object 'wheel'");
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
