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


if __name__ == "__main__":
    unittest.main()
