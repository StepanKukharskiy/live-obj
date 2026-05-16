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


if __name__ == "__main__":
    unittest.main()
