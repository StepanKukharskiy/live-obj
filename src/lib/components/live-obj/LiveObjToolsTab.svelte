<script lang="ts">
	interface OpParam {
		name: string;
		type: string;
		description: string;
		default?: string;
	}

	interface Operation {
		name: string;
		category: string;
		description: string;
		params: OpParam[];
		example?: string;
	}

	interface Category {
		name: string;
		operations: Operation[];
	}

	let expandedCategories = $state(new Set(['profile', 'primitives', 'boolean', 'sdf', 'transform', 'deformation', 'modifiers', 'other', 'simulations']));

	const categories: Category[] = [
		{
			name: 'profile',
			operations: [
				{
					name: 'extrude',
					category: 'Profile operations',
					description: 'Extrude 2D profile to 3D',
					params: [
						{ name: 'profile', type: 'list', description: 'List of 2D/3D points defining the profile' },
						{ name: 'height', type: 'float', description: 'Extrusion height', default: '1.0' },
						{ name: 'axis', type: 'string', description: 'Extrusion axis (x, y, or z)', default: 'z' }
					],
					example: 'o wall\n#@source: procedural\n#@type: extrude\n#@params: kernel=cadquery, profile=[[0,0,0],[4,0,0],[4,0,3],[0,0,3]], height=0.2'
				},
				{
					name: 'loft',
					category: 'Profile operations',
					description: 'Loft between multiple profiles',
					params: [
						{ name: 'sections', type: 'list', description: 'List of profile sections' }
					],
					example: 'o lofted_shape\n#@source: procedural\n#@type: loft\n#@params: sections=[[[0,0,0],[1,0,0],[1,1,0],[0,1,0]], [[0,0,2],[1.5,0,2],[1.5,1.5,2],[0,1.5,2]]]'
				},
				{
					name: 'sweep',
					category: 'Profile operations',
					description: 'Sweep profile along curve',
					params: [
						{ name: 'rail', type: 'list', description: 'Rail curve points' },
						{ name: 'profile', type: 'list', description: 'Profile curve points' }
					],
					example: 'o swept_pipe\n#@source: procedural\n#@type: sweep\n#@params: kernel=cadquery, profile=[[0,0,0],[0.1,0,0],[0.1,0.1,0],[0,0.1,0]], along=[[0,0,0],[0,0,1],[0,1,2],[1,2,2]]'
				},
				{
					name: 'revolve / lathe',
					category: 'Profile operations',
					description: 'Revolve profile around axis',
					params: [
						{ name: 'profile', type: 'list', description: 'Profile points' },
						{ name: 'axis', type: 'string', description: 'Rotation axis (x, y, or z)', default: 'y' },
						{ name: 'angle', type: 'float', description: 'Rotation angle in degrees', default: '360' }
					],
					example: 'o vase\n#@source: procedural\n#@type: revolve\n#@params: kernel=cadquery, profile=[[0,0,0],[0.1,0,0.2],[0.05,0,0.4],[0,0,0.8]], axis=z, angle=360'
				}
			]
		},
		{
			name: 'primitives',
			operations: [
				{
					name: 'box',
					category: 'Primitives',
					description: 'Box/cube primitive',
					params: [
						{ name: 'center', type: 'vec3', description: 'Center position', default: '[0,0,0]' },
						{ name: 'size', type: 'vec3', description: 'Dimensions [width, depth, height]', default: '[1,1,1]' },
						{ name: 'segments', type: 'int', description: 'Subdivision segments', default: '1' }
					],
					example: 'o cube\n#@source: procedural\n#@type: box\n#@params: center=[0,0,0], size=[1,1,1]'
				},
				{
					name: 'sphere',
					category: 'Primitives',
					description: 'Sphere primitive',
					params: [
						{ name: 'center', type: 'vec3', description: 'Center position', default: '[0,0,0]' },
						{ name: 'radius', type: 'float', description: 'Sphere radius', default: '0.5' },
						{ name: 'segments', type: 'int', description: 'Radial/latitudinal segments', default: '16' }
					],
					example: 'o ball\n#@source: procedural\n#@type: sphere\n#@params: center=[0,0,0], radius=0.5'
				},
				{
					name: 'cylinder',
					category: 'Primitives',
					description: 'Cylinder primitive',
					params: [
						{ name: 'center', type: 'vec3', description: 'Center position', default: '[0,0,0]' },
						{ name: 'radius', type: 'float', description: 'Cylinder radius', default: '0.5' },
						{ name: 'depth/height', type: 'float', description: 'Cylinder height', default: '1.0' },
						{ name: 'axis', type: 'string', description: 'Cylinder axis (x, y, or z)', default: 'z' },
						{ name: 'segments', type: 'int', description: 'Radial segments', default: '16' }
					],
					example: 'o column\n#@source: procedural\n#@type: cylinder\n#@params: center=[0,0,0], radius=0.5, height=1.0, axis=z'
				},
				{
					name: 'cone',
					category: 'Primitives',
					description: 'Cone primitive',
					params: [
						{ name: 'center', type: 'vec3', description: 'Center position', default: '[0,0,0]' },
						{ name: 'radius', type: 'float', description: 'Base radius', default: '0.5' },
						{ name: 'height', type: 'float', description: 'Cone height', default: '1.0' },
						{ name: 'axis', type: 'string', description: 'Cone axis (x, y, or z)', default: 'z' }
					],
					example: 'o roof_cone\n#@source: procedural\n#@type: cone\n#@params: center=[0,0,1], radius=0.5, height=0.8, axis=z'
				},
				{
					name: 'capsule',
					category: 'Primitives (SDF)',
					description: 'Capsule primitive (SDF only)',
					params: [
						{ name: 'a', type: 'vec3', description: 'Start point [x,y,z]' },
						{ name: 'b', type: 'vec3', description: 'End point [x,y,z]' },
						{ name: 'radius', type: 'float', description: 'Capsule radius' }
					],
					example: 'o capsule\n#@source: sdf\n#@sdf:\n#@ - capsule id=capsule a=[0,0,0] b=[0,0,1] radius=0.2'
				},
				{
					name: 'torus',
					category: 'Primitives (SDF)',
					description: 'Torus primitive (SDF only)',
					params: [
						{ name: 'center', type: 'vec3', description: 'Center position', default: '[0,0,0]' },
						{ name: 'major', type: 'float', description: 'Major radius (ring radius)' },
						{ name: 'minor', type: 'float', description: 'Minor radius (tube radius)' }
					],
					example: 'o ring\n#@source: sdf\n#@sdf:\n#@ - torus id=ring center=[0,0,0] major=1.0 minor=0.2'
				},
				{
					name: 'polyline',
					category: 'Primitives',
					description: 'Polyline curve',
					params: [
						{ name: 'points', type: 'list', description: 'List of 3D points' }
					],
					example: 'o line\n#@source: procedural\n#@type: polyline\n#@params: points=[[0,0,0],[1,0,0],[1,1,0]]'
				}
			]
		},
		{
			name: 'boolean',
			operations: [
				{
					name: 'union',
					category: 'Boolean operations',
					description: 'Combine objects (A ∪ B)',
					params: [
						{ name: 'target', type: 'string', description: 'Target object name for boolean' },
						{ name: 'ids', type: 'string', description: 'Comma-separated object IDs (SDF)' }
					],
					example: '#@sdf:\n#@ - box id=a center=[0,0,0] size=[1,1,1]\n#@ - sphere id=b center=[0.5,0.5,0.5] radius=0.5\n#@ - union a b'
				},
				{
					name: 'subtract',
					category: 'Boolean operations',
					description: 'Subtract B from A (A - B)',
					params: [
						{ name: 'target', type: 'string', description: 'Target object to subtract from' },
						{ name: 'ids', type: 'string', description: 'Comma-separated object IDs (SDF)' }
					],
					example: '#@sdf:\n#@ - box id=base center=[0,0,0] size=[2,2,2]\n#@ - sphere id=cut center=[0.6,0.6,0.6] radius=0.8\n#@ - subtract base cut'
				},
				{
					name: 'intersect',
					category: 'Boolean operations',
					description: 'Intersection of objects (A ∩ B)',
					params: [
						{ name: 'ids', type: 'string', description: 'Comma-separated object IDs (SDF)' }
					],
					example: '#@sdf:\n#@ - box id=a center=[0,0,0] size=[1,1,1]\n#@ - sphere id=b center=[0,0,0] radius=0.6\n#@ - intersect a b'
				},
				{
					name: 'smooth_union',
					category: 'Boolean operations',
					description: 'Smooth blend between objects (SDF)',
					params: [
						{ name: 'radius', type: 'float', description: 'Blend radius', default: '0.1' },
						{ name: 'ids', type: 'string', description: 'Comma-separated object IDs' }
					],
					example: '#@sdf:\n#@ - box id=a center=[0,0,0] size=[1,1,1]\n#@ - box id=b center=[0.5,0,0] size=[1,1,1]\n#@ - smooth_union radius=0.2 a b'
				}
			]
		},
		{
			name: 'sdf',
			operations: [
				{
					name: 'repeat',
					category: 'SDF operations',
					description: 'Repeat SDF pattern in grid',
					params: [
						{ name: 'cell', type: 'vec3', description: 'Grid cell size [x,y,z]' }
					],
					example: '#@sdf:\n#@ - sphere id=s center=[0,0,0] radius=0.3\n#@ - repeat cell=[1,1,1]'
				}
			]
		},
		{
			name: 'transform',
			operations: [
				{
					name: 'move / offset',
					category: 'Transform operations',
					description: 'Translate object',
					params: [
						{ name: 'offset', type: 'vec3', description: 'Translation vector [x,y,z]', default: '[0,0,0]' }
					],
					example: '#@ops:\n#@ - move offset=[1,0,0]'
				},
				{
					name: 'scale',
					category: 'Transform operations',
					description: 'Scale object',
					params: [
						{ name: 'factor', type: 'float', description: 'Scale factor', default: '1.0' }
					],
					example: '#@ops:\n#@ - scale factor=2.0'
				},
				{
					name: 'rotate',
					category: 'Transform operations',
					description: 'Rotate object',
					params: [
						{ name: 'angle', type: 'float', description: 'Rotation angle in degrees' },
						{ name: 'axis', type: 'string', description: 'Rotation axis (x, y, or z)' }
					],
					example: '#@ops:\n#@ - rotate angle=45 axis=z'
				},
				{
					name: 'mirror',
					category: 'Transform operations',
					description: 'Mirror object across plane',
					params: [
						{ name: 'axis', type: 'string', description: 'Mirror axis (x, y, or z)', default: 'x' }
					],
					example: '#@ops:\n#@ - mirror axis=x'
				},
				{
					name: 'array',
					category: 'Transform operations',
					description: 'Linear array of copies',
					params: [
						{ name: 'count', type: 'int', description: 'Number of copies', default: '2' },
						{ name: 'offset', type: 'vec3', description: 'Offset between copies', default: '[1,0,0]' }
					],
					example: '#@ops:\n#@ - array count=5 offset=[0.5,0,0]'
				},
				{
					name: 'array_linear',
					category: 'Transform operations',
					description: 'Linear array (alias for array)',
					params: [
						{ name: 'count', type: 'int', description: 'Number of copies' },
						{ name: 'offset', type: 'vec3', description: 'Offset between copies' }
					],
					example: '#@ops:\n#@ - array_linear count=3 offset=[0,0.3,0]'
				},
				{
					name: 'radial_array',
					category: 'Transform operations',
					description: 'Radial/circular array',
					params: [
						{ name: 'count', type: 'int', description: 'Number of copies', default: '6' },
						{ name: 'axis', type: 'string', description: 'Rotation axis', default: 'z' },
						{ name: 'radius', type: 'float', description: 'Array radius', default: '0.0' }
					],
					example: '#@ops:\n#@ - radial_array count=8 axis=z radius=1.0'
				}
			]
		},
		{
			name: 'deformation',
			operations: [
				{
					name: 'taper',
					category: 'Deformations',
					description: 'Taper mesh along axis',
					params: [
						{ name: 'axis', type: 'string', description: 'Taper axis (x, y, or z)', default: 'z' },
						{ name: 'amount', type: 'float', description: 'Taper amount', default: '0.0' }
					],
					example: '#@ops:\n#@ - taper axis=z amount=0.5'
				},
				{
					name: 'twist',
					category: 'Deformations',
					description: 'Twist mesh along axis',
					params: [
						{ name: 'axis', type: 'string', description: 'Twist axis (x, y, or z)', default: 'z' },
						{ name: 'angle_deg', type: 'float', description: 'Twist angle in degrees', default: '0.0' }
					],
					example: '#@ops:\n#@ - twist axis=z angle_deg=45'
				},
				{
					name: 'bend',
					category: 'Deformations',
					description: 'Bend mesh',
					params: [
						{ name: 'axis', type: 'string', description: 'Bend axis (x, y, or z)', default: 'x' },
						{ name: 'angle_deg', type: 'float', description: 'Bend angle in degrees', default: '0.0' }
					],
					example: '#@ops:\n#@ - bend axis=x angle_deg=30'
				},
				{
					name: 'displace',
					category: 'Deformations',
					description: 'Displace vertices with field',
					params: [
						{ name: 'field', type: 'string', description: 'Displacement field (wave, noise)', default: 'wave' },
						{ name: 'axis', type: 'string', description: 'Displacement axis', default: 'z' },
						{ name: 'amplitude/strength', type: 'float', description: 'Displacement strength', default: '0.1' }
					],
					example: '#@ops:\n#@ - displace field=wave axis=z amplitude=0.15'
				},
				{
					name: 'noise_displace',
					category: 'Deformations',
					description: 'Noise-based displacement (SDF)',
					params: [
						{ name: 'strength', type: 'float', description: 'Noise strength', default: '0.15' },
						{ name: 'frequency', type: 'float', description: 'Noise frequency', default: '4.0' },
						{ name: 'seed', type: 'int', description: 'Random seed', default: '0' }
					],
					example: '#@sdf:\n#@ - box id=base center=[0,0,0] size=[2,2,2]\n#@ - noise_displace strength=0.15 frequency=4 seed=3'
				},
				{
					name: 'subdivide',
					category: 'Deformations',
					description: 'Subdivide mesh faces',
					params: [
						{ name: 'level', type: 'int', description: 'Subdivision levels', default: '1' }
					],
					example: '#@ops:\n#@ - subdivide level=2'
				},
				{
					name: 'smooth',
					category: 'Deformations',
					description: 'Laplacian smoothing',
					params: [
						{ name: 'iterations', type: 'int', description: 'Smoothing iterations', default: '1' },
						{ name: 'strength', type: 'float', description: 'Smoothing strength', default: '0.5' }
					],
					example: '#@ops:\n#@ - smooth iterations=3 strength=0.5'
				},
				{
					name: 'simplify',
					category: 'Deformations',
					description: 'Reduce mesh complexity',
					params: [
						{ name: 'ratio', type: 'float', description: 'Face retention ratio (0-1)', default: '1.0' }
					],
					example: '#@ops:\n#@ - simplify ratio=0.5'
				},
				{
					name: 'remesh',
					category: 'Deformations',
					description: 'Remesh topology (not implemented)',
					params: [],
					example: '#@ops:\n#@ - remesh'
				}
			]
		},
		{
			name: 'modifiers',
			operations: [
				{
					name: 'bevel',
					category: 'Modifiers',
					description: 'Bevel edges',
					params: [
						{ name: 'amount/distance', type: 'float', description: 'Bevel distance', default: '0.05' },
						{ name: 'segments', type: 'int', description: 'Bevel segments', default: '1' }
					],
					example: '#@ops:\n#@ - bevel amount=0.05 segments=2'
				},
				{
					name: 'chamfer',
					category: 'Modifiers',
					description: 'Chamfer edges',
					params: [
						{ name: 'distance', type: 'float', description: 'Chamfer distance', default: '0.2' }
					],
					example: '#@ops:\n#@ - chamfer distance=0.1'
				},
				{
					name: 'shell',
					category: 'Modifiers',
					description: 'Create hollow shell',
					params: [
						{ name: 'thickness', type: 'float', description: 'Shell thickness', default: '0.05' }
					],
					example: '#@ops:\n#@ - shell thickness=0.02'
				},
				{
					name: 'thicken',
					category: 'Modifiers',
					description: 'Thicken surface (alias for shell)',
					params: [
						{ name: 'thickness', type: 'float', description: 'Thickness amount' }
					],
					example: '#@ops:\n#@ - thicken thickness=0.03'
				},
				{
					name: 'offset',
					category: 'Modifiers',
					description: 'Offset surface',
					params: [
						{ name: 'thickness/amount', type: 'float', description: 'Offset distance' }
					],
					example: '#@ops:\n#@ - offset amount=0.05'
				},
				{
					name: 'trace_paths',
					category: 'Modifiers',
					description: 'Extract path curves from mesh',
					params: [
						{ name: 'sample_every', type: 'int', description: 'Vertex sampling interval', default: '1' }
					],
					example: '#@ops:\n#@ - trace_paths sample_every=2'
				},
				{
					name: 'sdf_tubes',
					category: 'Modifiers',
					description: 'Generate tubes along mesh paths',
					params: [
						{ name: 'radius', type: 'float', description: 'Tube radius', default: '0.03' },
						{ name: 'sample_every', type: 'int', description: 'Sampling interval', default: '1' }
					],
					example: '#@ops:\n#@ - trace_paths sample_every=1\n#@ - sdf_tubes radius=0.03'
				}
			]
		},
		{
			name: 'other',
			operations: [
				{
					name: 'surface_grid',
					category: 'Other',
					description: 'Grid surface from points',
					params: [
						{ name: 'points', type: 'list', description: 'Grid of 3D points' }
					],
					example: 'o grid\n#@source: procedural\n#@type: surface_grid\n#@params: width=10, depth=10, resolution=20'
				},
				{
					name: 'heightfield',
					category: 'Other',
					description: 'Terrain from height map',
					params: [
						{ name: 'heights', type: 'list', description: '2D height values' },
						{ name: 'size', type: 'vec3', description: 'Grid dimensions' }
					],
					example: 'o terrain\n#@source: procedural\n#@type: heightfield\n#@params: width=20, depth=20, resolution=30'
				},
				{
					name: 'mesh',
					category: 'Other',
					description: 'Custom mesh from vertices/faces',
					params: [
						{ name: 'vertices', type: 'list', description: 'Vertex positions' },
						{ name: 'faces', type: 'list', description: 'Face indices' }
					],
					example: 'o custom\n#@source: procedural\n#@type: mesh\n#@params: generator=spiral_treads, count=12, total_height=3'
				},
				{
					name: 'curve',
					category: 'Other',
					description: 'Curve from points',
					params: [
						{ name: 'points', type: 'list', description: 'Curve control points' }
					],
					example: 'o path\n#@source: procedural\n#@type: curve\n#@params: points=[[0,0,0],[1,0,0.5],[2,0,1]]'
				},
				{
					name: 'voxelize',
					category: 'Other',
					description: 'Convert mesh to voxels',
					params: [
						{ name: 'resolution', type: 'float', description: 'Voxel cell size', default: '0.1' }
					],
					example: '#@ops:\n#@ - voxelize resolution=0.1'
				},
				{
					name: 'mesh_from_volume',
					category: 'Other',
					description: 'Generate mesh from voxel volume',
					params: [
						{ name: 'resolution', type: 'float', description: 'Mesh resolution' }
					],
					example: '#@ops:\n#@ - mesh_from_volume resolution=0.15'
				},
				{
					name: 'tread',
					category: 'Other',
					description: 'Add tread pattern',
					params: [
						{ name: 'count', type: 'int', description: 'Number of treads', default: '12' },
						{ name: 'depth', type: 'float', description: 'Tread depth', default: '0.035' }
					],
					example: 'o stairs\n#@source: procedural\n#@type: mesh\n#@params: generator=spiral_treads, count=12, total_height=3'
				},
				{
					name: 'mesh_from_sdf',
					category: 'Other',
					description: 'Convert SDF to mesh',
					params: [
						{ name: 'resolution', type: 'float', description: 'Voxel resolution' },
						{ name: 'method', type: 'string', description: 'Meshing method (voxel/marching_cubes)' }
					],
					example: '#@sdf:\n#@ - sphere id=s center=[0,0,0] radius=0.5\n#@ - mesh_from_sdf resolution=0.1'
				}
			]
		},
		{
			name: 'simulations',
			operations: [
				{
					name: 'cellular_automata',
					category: 'Simulations',
					description: 'Cellular automata growth (e.g., coral)',
					params: [
						{ name: 'grid', type: 'vec3', description: 'Grid dimensions [x,y,z]', default: '[32,32,32]' },
						{ name: 'cell', type: 'float', description: 'Cell size', default: '0.08' },
						{ name: 'steps', type: 'int', description: 'Simulation steps', default: '45' },
						{ name: 'seed', type: 'int', description: 'Random seed', default: '8' },
						{ name: 'mode', type: 'string', description: 'Growth mode', default: 'coral' }
					],
					example: 'o coral\n#@source: simulation\n#@sim: cellular_automata\n#@params: grid=[32,32,32], cell=0.08, steps=45, seed=8, mode=coral'
				},
				{
					name: 'differential_growth',
					category: 'Simulations',
					description: 'Differential growth curves',
					params: [
						{ name: 'radius', type: 'float', description: 'Initial radius', default: '1.0' },
						{ name: 'points', type: 'int', description: 'Initial point count', default: '40' },
						{ name: 'steps', type: 'int', description: 'Growth steps', default: '180' },
						{ name: 'split_distance', type: 'float', description: 'Edge split threshold', default: '0.18' },
						{ name: 'repel_radius', type: 'float', description: 'Repulsion radius', default: '0.25' },
						{ name: 'thickness', type: 'float', description: 'Tube thickness', default: '0.035' },
						{ name: 'seed', type: 'int', description: 'Random seed', default: '2' }
					],
					example: 'o growth\n#@source: simulation\n#@sim: differential_growth\n#@params: radius=1.0, points=40, steps=180, split_distance=0.18, repel_radius=0.25, thickness=0.035, seed=2'
				},
				{
					name: 'boids',
					category: 'Simulations',
					description: 'Boids flocking simulation',
					params: [
						{ name: 'agents', type: 'int', description: 'Number of boids', default: '40' },
						{ name: 'steps', type: 'int', description: 'Simulation steps', default: '160' },
						{ name: 'bounds', type: 'vec3', description: 'Simulation bounds', default: '[8,5,5]' },
						{ name: 'seed', type: 'int', description: 'Random seed', default: '4' },
						{ name: 'trace_radius', type: 'float', description: 'Path trace tube radius', default: '0.035' }
					],
					example: 'o boids_sim\n#@source: simulation\n#@sim: boids\n#@params: agents=40, steps=160, bounds=[8,5,5], seed=4, trace_radius=0.035'
				}
			]
		}
	];

	function toggleCategory(categoryName: string) {
		const newSet = new Set(expandedCategories);
		if (newSet.has(categoryName)) {
			newSet.delete(categoryName);
		} else {
			newSet.add(categoryName);
		}
		expandedCategories = newSet;
	}

	function expandAll() {
		expandedCategories = new Set(categories.map((c) => c.name));
	}

	function collapseAll() {
		expandedCategories = new Set<string>();
	}

	async function copyToClipboard(text: string) {
		try {
			await navigator.clipboard.writeText(text);
		} catch (err) {
			console.error('Failed to copy:', err);
		}
	}
</script>

<div class="tools-tab">
	<div class="tools-header">
		<h2>CAD Operations Reference</h2>
		<div class="tools-actions">
			<button type="button" onclick={expandAll} class="tools-action-btn">Expand All</button>
			<button type="button" onclick={collapseAll} class="tools-action-btn">Collapse All</button>
		</div>
	</div>

	<div class="tools-categories">
		{#each categories as category (category.name)}
			<div class="tools-category">
				<button
					type="button"
					class="tools-category-header"
					class:expanded={expandedCategories.has(category.name)}
					onclick={() => toggleCategory(category.name)}
				>
					<span class="tools-category-title">{category.name}</span>
					<span class="tools-category-toggle">{expandedCategories.has(category.name) ? '▼' : '▶'}</span>
				</button>

				{#if expandedCategories.has(category.name)}
					<div class="tools-category-content">
						{#each category.operations as op (op.name)}
							<div class="tools-operation">
								<h3 class="tools-operation-name">{op.name}</h3>
								<p class="tools-operation-description">{op.description}</p>
								{#if op.params.length > 0}
									<div class="tools-params">
										<h4 class="tools-params-title">Parameters:</h4>
										{#each op.params as param (param.name)}
											<div class="tools-param">
												<code class="tools-param-name">{param.name}</code>
												<span class="tools-param-type">({param.type})</span>
												<span class="tools-param-desc">: {param.description}</span>
												{#if param.default}
													<span class="tools-param-default"> = {param.default}</span>
												{/if}
											</div>
										{/each}
									</div>
								{/if}
								{#if op.example}
									<div class="tools-example">
										<div class="tools-example-header">
											<h4 class="tools-example-title">Example:</h4>
											<button
												type="button"
												class="tools-copy-btn"
												onclick={() => copyToClipboard(op.example || '')}
												title="Copy to clipboard"
											>
												<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
													<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
													<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
												</svg>
											</button>
										</div>
										<pre class="tools-example-code">{op.example}</pre>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/each}
	</div>
</div>

<style>
	.tools-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.tools-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 12px 16px;
		border-bottom: 1px solid #e2e8f0;
		background: #f8fafc;
		flex-shrink: 0;
	}

	.tools-header h2 {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		color: #1e293b;
	}

	.tools-actions {
		display: flex;
		gap: 8px;
	}

	.tools-action-btn {
		padding: 4px 10px;
		font-size: 11px;
		border: 1px solid #cbd5e1;
		background: white;
		border-radius: 4px;
		cursor: pointer;
		color: #64748b;
		transition: all 0.15s;
	}

	.tools-action-btn:hover {
		background: #f1f5f9;
		border-color: #94a3b8;
		color: #334155;
	}

	.tools-categories {
		flex: 1;
		overflow-y: auto;
		padding: 8px;
	}

	.tools-category {
		margin-bottom: 4px;
		border: 1px solid #e2e8f0;
		border-radius: 6px;
		background: white;
	}

	.tools-category-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: 10px 12px;
		border: none;
		background: white;
		cursor: pointer;
		font-size: 12px;
		font-weight: 600;
		color: #334155;
		transition: background 0.15s;
	}

	.tools-category-header:hover {
		background: #f8fafc;
	}

	.tools-category-header.expanded {
		background: #f1f5f9;
		border-bottom: 1px solid #e2e8f0;
		border-radius: 6px 6px 0 0;
	}

	.tools-category-title {
		text-transform: capitalize;
	}

	.tools-category-toggle {
		color: #94a3b8;
		font-size: 10px;
	}

	.tools-category-content {
		padding: 8px 12px 12px;
	}

	.tools-operation {
		padding: 10px 0;
		border-bottom: 1px solid #f1f5f9;
	}

	.tools-operation:last-child {
		border-bottom: none;
		padding-bottom: 0;
	}

	.tools-operation-name {
		margin: 0 0 4px;
		font-size: 12px;
		font-weight: 600;
		color: #0f172a;
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
	}

	.tools-operation-description {
		margin: 0 0 8px;
		font-size: 11px;
		color: #64748b;
		line-height: 1.4;
	}

	.tools-params {
		margin-top: 8px;
		padding: 8px;
		background: #f8fafc;
		border-radius: 4px;
	}

	.tools-params-title {
		margin: 0 0 6px;
		font-size: 10px;
		font-weight: 600;
		color: #475569;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.tools-param {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 8px;
		margin-bottom: 4px;
		font-size: 11px;
		line-height: 1.5;
	}

	.tools-param:last-child {
		margin-bottom: 0;
	}

	.tools-param-name {
		color: #0000eb;
		background: rgba(0, 0, 235, 0.08);
		padding: 1px 5px;
		border-radius: 3px;
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
		font-size: 10px;
	}

	.tools-param-type {
		color: #64748b;
		font-style: italic;
	}

	.tools-param-desc {
		color: #475569;
		flex: 1;
		min-width: 120px;
	}

	.tools-param-default {
		color: #059669;
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
		font-size: 10px;
	}

	.tools-example {
		margin-top: 8px;
		padding: 8px;
		background: rgba(0, 0, 235, 0.03);
		border-radius: 4px;
		border: 1px solid rgba(0, 0, 235, 0.15);
	}

	.tools-example-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 6px;
	}

	.tools-example-title {
		margin: 0;
		font-size: 10px;
		font-weight: 600;
		color: #0000eb;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.tools-copy-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 4px;
		background: rgba(0, 0, 235, 0.08);
		border: 1px solid rgba(0, 0, 235, 0.2);
		border-radius: 4px;
		cursor: pointer;
		color: #0000eb;
		transition: all 0.15s;
	}

	.tools-copy-btn:hover {
		background: rgba(0, 0, 235, 0.15);
		border-color: rgba(0, 0, 235, 0.3);
	}

	.tools-copy-btn:active {
		background: rgba(0, 0, 235, 0.2);
	}

	.tools-example-code {
		margin: 0;
		padding: 8px;
		background: #fff;
		border-radius: 3px;
		font-size: 11px;
		color: #334155;
		font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
		white-space: pre-wrap;
		word-break: break-all;
		overflow-x: auto;
		line-height: 1.4;
	}
</style>
