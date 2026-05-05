import { describe, expect, it } from 'vitest';
import { applyLiveObjSurgicalPatch, parseLiveObjSurgicalPatch } from './surgicalPatch';

const scene = `#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
o cube
#@source: procedural
#@type: box
#@params: center=[0,0,0], size=[1,1,1]
`;

describe('Live OBJ surgical patches', () => {
	it('applies an exact line edit without touching surrounding text', () => {
		expect.assertions(1);
		const result = applyLiveObjSurgicalPatch(scene, {
			edits: [
				{
					find: '#@params: center=[0,0,0], size=[1,1,1]',
					replace: '#@params: center=[0,0,0], size=[2,1,1]'
				}
			]
		});

		expect(result.liveObj).toBe(scene.replace('size=[1,1,1]', 'size=[2,1,1]'));
	});

	it('can parse a fenced JSON patch', () => {
		expect.assertions(1);
		const patch = parseLiveObjSurgicalPatch(`\`\`\`json
{
  "summary": "Scale cube",
  "edits": [
    {
      "find": "#@params: center=[0,0,0], size=[1,1,1]",
      "replace": "#@params: center=[0,0,0], size=[1,2,1]"
    }
  ]
}
\`\`\``);

		expect(patch.edits[0].replace).toBe('#@params: center=[0,0,0], size=[1,2,1]');
	});

	it('rejects missing targets', () => {
		expect.assertions(1);
		expect(() =>
			applyLiveObjSurgicalPatch(scene, {
				edits: [{ find: 'o sphere', replace: 'o ball' }]
			})
		).toThrow('did not match');
	});

	it('rejects ambiguous targets', () => {
		expect.assertions(1);
		expect(() =>
			applyLiveObjSurgicalPatch(`${scene}\no cube_copy\n#@type: box\n`, {
				edits: [{ find: '#@type: box', replace: '#@type: sphere' }]
			})
		).toThrow('matched 2 locations');
	});
});
