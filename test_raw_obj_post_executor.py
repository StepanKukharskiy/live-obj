import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "routes", "api", "executor"))

from raw_obj_post_executor import execute_scene, parse_obj


class RawObjPostExecutorTest(unittest.TestCase):
    def parse_scene(self, source: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.obj"
            path.write_text(source, encoding="utf-8")
            return parse_obj(path)

    def boundary_edge_count(self, faces):
        edges = {}
        for face in faces:
            for i, a in enumerate(face):
                b = face[(i + 1) % len(face)]
                key = tuple(sorted((a, b)))
                edges[key] = edges.get(key, 0) + 1
        return sum(1 for count in edges.values() if count == 1)

    def test_transform_post_op_can_reference_params(self):
        source = """#@live_obj_version: 0.1
#@up: y
o roof_shell
#@source: llm_mesh
#@params: roof_lift=1.25, roof_scale=2
#@controls:
#@ - slider key=roof_lift label=Roof_lift min=-1 max=3 step=0.1
#@post:
#@ - transform position=[0,roof_lift,0] scale=[roof_scale,1,1]
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertEqual(mesh.vertices[0], (0.0, 1.25, 0.0))
        self.assertEqual(mesh.vertices[1], (2.0, 1.25, 0.0))
        self.assertEqual(mesh.vertices[2], (0.0, 2.25, 0.0))

    def test_transform_post_op_can_use_pivot(self):
        source = """#@live_obj_version: 0.1
#@up: y
o bar
#@source: llm_mesh
#@params: width=2
#@post:
#@ - transform scale=[width,1,1] pivot=[1,0,0]
v 1 0 0
v 2 0 0
v 1 1 0
f 1 2 3
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertEqual(mesh.vertices[0], (1.0, 0.0, 0.0))
        self.assertEqual(mesh.vertices[1], (3.0, 0.0, 0.0))
        self.assertEqual(mesh.vertices[2], (1.0, 1.0, 0.0))

    def test_array_can_be_centered_and_reference_scene_params(self):
        source = """#@live_obj_version: 0.1
#@up: y
#@params: frame_spacing=4
o side_frame
#@source: llm_mesh
#@post:
#@ - array count=2 offset=[frame_spacing,0,0] centered=true
v -1 0 0
v -0.5 0 0
v -1 1 0
f 1 2 3
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertEqual(mesh.vertices[0], (-3.0, 0.0, 0.0))
        self.assertEqual(mesh.vertices[1], (-2.5, 0.0, 0.0))
        self.assertEqual(mesh.vertices[3], (1.0, 0.0, 0.0))
        self.assertEqual(mesh.vertices[4], (1.5, 0.0, 0.0))

    def test_template_placeholder_vector_falls_back_to_default(self):
        source = """#@live_obj_version: 0.1
#@up: y
o block
#@source: llm_mesh
#@params: lift=2
#@post:
#@ - transform position=[0,lift,0] scale=[{bad_scale},1,1]
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertEqual(mesh.vertices[0], (0.0, 2.0, 0.0))
        self.assertEqual(mesh.vertices[1], (1.0, 2.0, 0.0))
        self.assertEqual(mesh.vertices[2], (0.0, 3.0, 0.0))

    def test_skin_edges_replaces_base_mesh_with_closed_surface(self):
        source = """#@live_obj_version: 0.1
#@up: y
o cube_cage
#@source: llm_mesh
#@params: exo_radius=0.12, exo_resolution=18
#@post:
#@ - skin_edges radius=exo_radius resolution=exo_resolution edges=feature angle=20 mode=replace
v -0.5 -0.5 -0.5
v 0.5 -0.5 -0.5
v 0.5 0.5 -0.5
v -0.5 0.5 -0.5
v -0.5 -0.5 0.5
v 0.5 -0.5 0.5
v 0.5 0.5 0.5
v -0.5 0.5 0.5
f 1 2 3 4
f 5 8 7 6
f 1 5 6 2
f 2 6 7 3
f 3 7 8 4
f 4 8 5 1
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertGreater(len(mesh.vertices), 8)
        self.assertGreater(len(mesh.faces), 6)
        self.assertEqual(self.boundary_edge_count(mesh.faces), 0)

    def test_skin_edges_append_keeps_base_mesh(self):
        source = """#@live_obj_version: 0.1
#@up: y
o pyramid_cage
#@source: llm_mesh
#@post:
#@ - skin_edges radius=0.1 resolution=14 edges=all mode=append
v 0 1 0
v -0.5 0 -0.5
v 0.5 0 -0.5
v 0.5 0 0.5
v -0.5 0 0.5
f 1 2 3
f 1 3 4
f 1 4 5
f 1 5 2
f 2 5 4 3
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertGreater(len(mesh.vertices), 5)
        self.assertGreater(len(mesh.faces), 5)
        self.assertEqual(mesh.vertices[:5], [
            (0.0, 1.0, 0.0),
            (-0.5, 0.0, -0.5),
            (0.5, 0.0, -0.5),
            (0.5, 0.0, 0.5),
            (-0.5, 0.0, 0.5),
        ])

    def test_face_lattice_replaces_single_face_with_closed_frame(self):
        source = """#@live_obj_version: 0.1
#@up: z
o panel
#@source: llm_mesh
#@params: frame_inset=0.35, frame_thickness=0.2
#@post:
#@ - face_lattice inset=frame_inset thickness=frame_thickness weld=0.001 mode=replace
v -1 -1 0
v 1 -1 0
v 1 1 0
v -1 1 0
f 1 2 3 4
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh
        zs = [v[2] for v in mesh.vertices]

        self.assertGreater(len(mesh.vertices), 4)
        self.assertGreater(len(mesh.faces), 1)
        self.assertAlmostEqual(min(zs), -0.1)
        self.assertAlmostEqual(max(zs), 0.1)
        self.assertEqual(self.boundary_edge_count(mesh.faces), 0)

    def test_face_lattice_append_keeps_guide_mesh(self):
        source = """#@live_obj_version: 0.1
#@up: z
o panel
#@source: llm_mesh
#@post:
#@ - face_lattice inset=0.3 thickness=0.1 mode=append
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
f 1 2 3 4
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertGreater(len(mesh.vertices), 4)
        self.assertGreater(len(mesh.faces), 1)
        self.assertEqual(mesh.vertices[:4], [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ])

    def test_face_lattice_welds_source_before_offsetting_shared_vertices(self):
        source = """#@live_obj_version: 0.1
#@up: z
o bent_panel
#@source: llm_mesh
#@post:
#@ - face_lattice inset=0.3 thickness=0.1 weld=0.001 mode=replace
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 1 0 0
v 1 0 1
v 1 1 1
v 1 1 0
f 1 2 3 4
f 5 6 7 8
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertEqual(len(mesh.vertices), 28)
        self.assertEqual(len(mesh.faces), 32)
        self.assertEqual(self.boundary_edge_count(mesh.faces), 0)

    def test_face_lattice_can_catmull_clark_subdivide(self):
        source = """#@live_obj_version: 0.1
#@up: z
o panel
#@source: llm_mesh
#@post:
#@ - face_lattice inset=0.35 thickness=0.2 weld=0.001 subdivide=1 mode=replace
v -1 -1 0
v 1 -1 0
v 1 1 0
v -1 1 0
f 1 2 3 4
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertGreater(len(mesh.vertices), 16)
        self.assertGreater(len(mesh.faces), 16)
        self.assertEqual(self.boundary_edge_count(mesh.faces), 0)

    def test_face_lattice_can_prefair_guide_before_lattice(self):
        source = """#@live_obj_version: 0.1
#@up: z
o uneven_panel
#@source: llm_mesh
#@post:
#@ - face_lattice inset=0.25 thickness=0.08 weld=0.001 guide_subdivide=1 guide_smooth=1 mode=replace
v 0 0 0
v 3 0 0
v 3 0.4 0
v 0 0.4 0
f 1 2 3 4
"""

        scene = execute_scene(self.parse_scene(source))
        mesh = scene.objects[0].mesh

        self.assertGreater(len(mesh.faces), 16)
        self.assertEqual(self.boundary_edge_count(mesh.faces), 0)


if __name__ == "__main__":
    unittest.main()
