import { describe, expect, it } from 'vitest';
import { mergeMetadataWithMesh } from './mergeMetadataWithMesh';

describe('mergeMetadataWithMesh', () => {
	it('preserves mesh lines for edited metadata-only object blocks', () => {
		const fullObj = `#@live_obj_version: 0.1
o flower_center
#@source: llm_mesh
#@transform: position=[0,0,0],rotation=[0,0,0],scale=[1,1,1]
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`;

		const editedMetadata = `#@live_obj_version: 0.1
o flower_center
#@source: llm_mesh
#@transform: position=[0,0,0],rotation=[90,0,0],scale=[1,1,1]
`;

		expect(mergeMetadataWithMesh(editedMetadata, fullObj)).toBe(`#@live_obj_version: 0.1
o flower_center
#@source: llm_mesh
#@transform: position=[0,0,0],rotation=[90,0,0],scale=[1,1,1]
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
`);
	});

	it('drops mesh for object blocks removed from the metadata-only edit', () => {
		const fullObj = `o keep
#@source: llm_mesh
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3

o remove
#@source: llm_mesh
v 0 0 0
v -1 0 0
v 0 -1 0
f 4 5 6
`;

		const editedMetadata = `o keep
#@source: llm_mesh
`;

		expect(mergeMetadataWithMesh(editedMetadata, fullObj)).not.toContain('o remove');
		expect(mergeMetadataWithMesh(editedMetadata, fullObj)).not.toContain('f 4 5 6');
	});

	it('renumbers preserved faces when an earlier object block is removed', () => {
		const fullObj = `o remove
#@source: llm_mesh
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3

o keep
#@source: llm_mesh
v 0 0 1
v 1 0 1
v 0 1 1
f 4 5 6
`;

		const editedMetadata = `o keep
#@source: llm_mesh
`;

		expect(mergeMetadataWithMesh(editedMetadata, fullObj)).toBe(`o keep
#@source: llm_mesh
v 0 0 1
v 1 0 1
v 0 1 1
f 1 2 3
`);
	});
});
