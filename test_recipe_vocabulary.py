#!/usr/bin/env python3
"""Executable examples for scene-local recipe vocabulary.

Run:
    python3 test_recipe_vocabulary.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "routes", "api", "executor"))

from live_obj_executor_v02 import execute_scene, parse_obj, serialize_scene


BENCH_INFILL_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: printed_concrete color=#e5e1d8 roughness=0.9 metalness=0

o bench_body
#@source: procedural
#@type: box
#@params: size=[3.65,1.22,0.72], center=[0,0,0.36]
#@ops:
#@ - bevel amount=0.18 segments=10
#@ - material name=printed_concrete

o bench_seat_infill
#@source: recipe
#@recipe:
#@ - boundary id=seat kind=capsule length=3.35 depth=0.92 radius=0.46 center=[0,0] segments=72
#@ - offset id=cavity from=seat amount=-0.10
#@ - path_formula id=paths inside=cavity rows=8 samples=96 x=min_x+width*u y=row_y+sin(tau*(3*u+v*0.8))*0.065+noise(u*8,row,7)*0.018 z=0.78
#@ - emit_tubes paths=paths radius=0.026 segments=8 material=printed_concrete
"""


PAVILION_RIBBON_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: pavilion_white color=#f7f7f2 roughness=0.82 metalness=0

o curled_pavilion_ribbon_A
#@source: recipe
#@recipe:
#@ - surface_formula id=sheet u_segments=72 v_segments=16 radius=1.55 width=0.82 height=2.4 twist=1.35 curl=0.42 phase=0 x=cos(tau*(0.82*u+twist*(v-0.5)))*(radius+width*(v-0.5)) y=sin(tau*(0.82*u+twist*(v-0.5)))*(radius+width*(v-0.5)) z=height*(v-0.5)+curl*sin(tau*(1.4*u)+phase)
#@ - perforate_surface id=sheet_holes from=sheet condition=sin(tau*u*24)*sin(tau*v*10)>0.72 keep_border=true
#@ - emit_surface surface=sheet_holes rim_radius=0.018 rim_segments=8 material=pavilion_white

o curled_pavilion_ribbon_B
#@source: recipe
#@recipe:
#@ - surface_formula id=sheet u_segments=72 v_segments=14 radius=1.2 width=0.7 height=1.8 twist=-1.1 curl=0.38 phase=1.7 x=cos(tau*(0.9*u+twist*(v-0.5))+1.25)*(radius+width*(v-0.5)) y=sin(tau*(0.9*u+twist*(v-0.5))+1.25)*(radius+width*(v-0.5)) z=0.25+height*(v-0.5)+curl*sin(tau*(1.2*u)+phase)
#@ - perforate_surface id=sheet_holes from=sheet u_every=5 v_every=3 keep_border=true
#@ - emit_surface surface=sheet_holes rim_radius=0.018 rim_segments=8 material=pavilion_white
"""


GROWTH_ITERATE_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: growth_white color=#fafaf4 roughness=0.86 metalness=0

o recipe_growth_loop
#@source: recipe
#@recipe:
#@ - curve id=seed kind=circle radius=0.45 points=24 z=0
#@ - iterate id=grown target=seed rule=differential_growth steps=24 split_distance=0.08 repel_radius=0.12 repulsion=0.012 attraction=0.025 max_points=180 smooth_iterations=1
#@ - emit_tubes from=grown radius=0.015 segments=6 closed=true material=growth_white
"""


CELLULAR_AUTOMATA_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: ca_mint color=#b9efe5 roughness=0.72 metalness=0

o recipe_cellular_volume
#@source: recipe
#@recipe:
#@ - grid id=cells size=[14,14,8] cell=0.08 init=seed_cluster seed=7 seed_count=12 seed_radius=2 seed_z_span=1
#@ - iterate id=grown target=cells rule=cellular_automata mode=growth steps=4 birth=1,2,3 max_fill=0.24
#@ - emit_volume from=grown method=voxels material=ca_mint
"""


PANELIZED_SURFACE_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: panel_lime color=#d8ef65 roughness=0.68 metalness=0.05

o recipe_panelized_shell
#@source: recipe
#@recipe:
#@ - surface_formula id=shell u_segments=18 v_segments=8 radius=1.2 width=0.7 height=1.6 twist=0.55 x=cos(tau*u)*(radius+width*(v-0.5)) y=sin(tau*u)*(radius+width*(v-0.5)) z=height*v+0.18*sin(tau*(u*2+v))
#@ - panelize_surface id=panels from=shell scale=0.72 offset=0.018 thickness=0.01
#@ - emit_panels from=panels material=panel_lime
"""


FIELD_TRACE_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: trace_blue color=#7bdff2 roughness=0.7 metalness=0

o recipe_field_traces
#@source: recipe
#@recipe:
#@ - boundary id=seed_area kind=circle radius=0.55 center=[0,0] segments=48
#@ - points id=seeds inside=seed_area count=18 seed=5 z=0.06
#@ - field id=vortex kind=swirl center=[0,0,0.1] strength=1.0 upward=0.22 outward=0.08
#@ - trace_field id=traces from=seeds field=vortex steps=64 step_size=0.035 bounds=[[-1.2,-1.2,0],[1.2,1.2,1.2]]
#@ - emit_tubes from=traces radius=0.012 segments=6 material=trace_blue
"""


SCATTER_INSTANCE_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: timber color=#d4b06f roughness=0.76 metalness=0

o recipe_scattered_posts
#@source: recipe
#@recipe:
#@ - boundary id=yard kind=rounded_rect width=1.4 depth=0.8 radius=0.12 center=[0,0] segments=40
#@ - scatter id=posts inside=yard count=28 seed=11 min_distance=0.12 z=0 rotation=random rotation_step=45 scale_min=0.8 scale_max=1.2
#@ - instance from=posts primitive=box size=[0.035,0.035,0.25] anchor=base material=timber
"""


WFC_INSTANCE_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: map_block color=#d8d1c7 roughness=0.7 metalness=0

o recipe_wfc_blocks
#@source: recipe
#@recipe:
#@ - wfc id=layout size=[10,6,1] cell=0.16 origin=[-0.8,-0.48,0] tiles=void,floor,wall weights=0.10,0.65,0.25 rules=void:void,floor;floor:void,floor,wall;wall:floor,wall seed=4 skip=void
#@ - instance from=layout primitive=box floor_size=[0.14,0.14,0.035] wall_size=[0.14,0.14,0.28] anchor=base material=map_block
"""


WFC_MODULE_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: stone color=#c9bca8 roughness=0.82 metalness=0

o recipe_wfc_arch_modules
#@source: recipe
#@params: cols=9, rows=5, cell=0.18, wall_height=0.34
#@recipe:
#@ - module id=floor kind=box size=[cell*0.88,cell*0.88,0.025]
#@ - module id=wall kind=wall size=[cell*0.9,cell*0.16,wall_height]
#@ - module id=arch kind=arch_wall size=[cell*0.9,cell*0.16,wall_height] opening_width=cell*0.45 spring_height=wall_height*0.46 arch_thickness=cell*0.08 arch_segments=9
#@ - module id=column kind=column radius=cell*0.13 height=wall_height*1.1 segments=10
#@ - socket module=void accepts=void,floor
#@ - socket module=floor accepts=void,floor,wall,arch,column
#@ - socket module=wall accepts=floor,wall,arch,column
#@ - socket module=arch accepts=floor,wall,arch,column
#@ - socket module=column accepts=floor,wall,arch,column
#@ - wfc id=layout size=[cols,rows,1] cell=cell origin=[-cols*cell*0.5,-rows*cell*0.5,0] tiles=void,floor,wall,arch,column weights=0.05,0.42,0.25,0.18,0.10 seed=8 skip=void
#@ - instance from=layout module=tile material=stone
"""


WFC_TEMPLATE_MODULE_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: stone color=#c9bca8 roughness=0.82 metalness=0

o arch_wall_template
#@source: recipe
#@hidden: true
#@recipe:
#@ - module id=arch_shape kind=arch_wall size=[0.18,0.04,0.34] opening_width=0.08 spring_height=0.16 arch_thickness=0.018 arch_segments=9
#@ - scatter id=one count=1 width=0 depth=0 z=0
#@ - instance from=one module=arch_shape material=stone

o recipe_wfc_template_modules
#@source: recipe
#@recipe:
#@ - module id=floor kind=box size=[0.16,0.16,0.025]
#@ - module id=arch kind=object ref=arch_wall_template origin=center_bottom
#@ - wfc id=layout size=[6,3,1] cell=0.18 origin=[-0.54,-0.27,0] tiles=floor,arch weights=0.58,0.42 rules=floor:floor,arch;arch:floor,arch seed=3
#@ - instance from=layout module=tile material=stone
"""


WFC_DIRECTIONAL_CONTROLS_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1
#@material_preset: stone color=#c9bca8 roughness=0.82 metalness=0

o recipe_wfc_directional_facade
#@source: recipe
#@params: cols=7, rows=4, cell=0.22, seed=9, wall_height=0.48
#@controls:
#@ - slider key=cell label=Bay_size min=0.14 max=0.32 step=0.01
#@ - seed key=seed label=Layout_seed min=1 max=99 step=1
#@ - slider key=wall_height label=Wall_height min=0.2 max=0.6 step=0.02
#@recipe:
#@ - module id=floor kind=box size=[cell*0.9,cell*0.9,0.025]
#@ - module id=wall_x kind=wall size=[cell*0.92,cell*0.18,wall_height]
#@ - module id=wall_y kind=wall size=[cell*0.92,cell*0.18,wall_height]
#@ - module id=door_x kind=arch_wall size=[cell*0.92,cell*0.18,wall_height] opening_width=cell*0.46 spring_height=wall_height*0.42 arch_thickness=cell*0.08 arch_segments=10
#@ - module id=door_y kind=arch_wall size=[cell*0.92,cell*0.18,wall_height] opening_width=cell*0.46 spring_height=wall_height*0.42 arch_thickness=cell*0.08 arch_segments=10
#@ - module id=column kind=column radius=cell*0.16 height=wall_height*1.08 segments=12
#@ - socket module=floor north=floor,wall_x,wall_y,door_x,door_y,column south=floor,wall_x,wall_y,door_x,door_y,column east=floor,wall_x,wall_y,door_x,door_y,column west=floor,wall_x,wall_y,door_x,door_y,column
#@ - socket module=wall_x north=floor,wall_y,door_y,column south=floor,wall_y,door_y,column east=wall_x,door_x,column west=wall_x,door_x,column
#@ - socket module=wall_y north=wall_y,door_y,column south=wall_y,door_y,column east=floor,wall_x,door_x,column west=floor,wall_x,door_x,column
#@ - socket module=door_x north=floor,wall_y,column south=floor,wall_y,column east=wall_x,column west=wall_x,column
#@ - socket module=door_y north=wall_y,column south=wall_y,column east=floor,wall_x,column west=floor,wall_x,column
#@ - socket module=column north=floor,wall_x,wall_y,door_x,door_y,column south=floor,wall_x,wall_y,door_x,door_y,column east=floor,wall_x,wall_y,door_x,door_y,column west=floor,wall_x,wall_y,door_x,door_y,column
#@ - wfc id=layout size=[cols,rows,1] cell=cell origin=[-cols*cell*0.5,-rows*cell*0.5,0] tiles=floor,wall_x,wall_y,door_x,door_y,column weights=0.28,0.20,0.18,0.08,0.06,0.20 force=0,1:column;1,1:wall_x;2,1:door_x;3,1:wall_x;4,1:door_x;5,1:wall_x;6,1:column;0,2:column;2,2:wall_y;4,2:door_y;6,2:column wall_y_rotation=[0,0,90] door_y_rotation=[0,0,90] seed=seed
#@ - instance from=layout module=tile material=stone
"""


WFC_INVERSE_SOCKET_RECIPE = """#@scene
#@units: meters
#@up: z
#@live_obj_version: 0.1

o recipe_wfc_inverse_socket
#@source: recipe
#@recipe:
#@ - module id=a kind=box size=[0.12,0.12,0.10]
#@ - module id=b kind=box size=[0.12,0.12,0.16]
#@ - module id=c kind=box size=[0.12,0.12,0.44]
#@ - socket module=a east=b,c
#@ - socket module=b west=b
#@ - socket module=c west=a
#@ - wfc id=layout size=[2,1,1] cell=0.2 origin=[0,0,0] tiles=a,b,c weights=0,30,1 force=0,0:a seed=2
#@ - instance from=layout module=tile
"""


def execute_text(live_obj_text: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".obj", delete=False) as handle:
        handle.write(live_obj_text)
        path = handle.name
    try:
        scene = parse_obj(Path(path))
        execute_scene(scene)
        return serialize_scene(scene)
    finally:
        os.unlink(path)


class RecipeVocabularyTests(unittest.TestCase):
    def test_bench_recipe_keeps_source_and_emits_mesh(self):
        out = execute_text(BENCH_INFILL_RECIPE)
        self.assertIn("#@source: recipe", out)
        self.assertIn("path_formula", out)
        self.assertGreater(out.count("\nv "), 1000)
        self.assertGreater(out.count("\nf "), 500)

    def test_pavilion_ribbon_recipe_emits_formula_surfaces(self):
        out = execute_text(PAVILION_RIBBON_RECIPE)
        self.assertIn("surface_formula", out)
        self.assertIn("perforate_surface", out)
        self.assertIn("emit_surface", out)
        self.assertGreater(out.count("\nv "), 1500)
        self.assertGreater(out.count("\nf "), 1000)

    def test_iterate_recipe_can_run_differential_growth(self):
        out = execute_text(GROWTH_ITERATE_RECIPE)
        self.assertIn("#@source: recipe", out)
        self.assertIn("curve id=seed", out)
        self.assertIn("iterate id=grown", out)
        self.assertGreater(out.count("\nv "), 300)
        self.assertGreater(out.count("\nf "), 150)

    def test_iterate_recipe_can_run_cellular_automata_grid(self):
        out = execute_text(CELLULAR_AUTOMATA_RECIPE)
        self.assertIn("grid id=cells", out)
        self.assertIn("rule=cellular_automata", out)
        self.assertIn("emit_volume", out)
        self.assertGreater(out.count("\nv "), 100)
        self.assertGreater(out.count("\nf "), 50)

    def test_recipe_can_panelize_formula_surface(self):
        out = execute_text(PANELIZED_SURFACE_RECIPE)
        self.assertIn("panelize_surface", out)
        self.assertIn("emit_panels", out)
        self.assertGreater(out.count("\nv "), 900)
        self.assertGreater(out.count("\nf "), 500)

    def test_recipe_can_trace_vector_field(self):
        out = execute_text(FIELD_TRACE_RECIPE)
        self.assertIn("field id=vortex", out)
        self.assertIn("trace_field id=traces", out)
        self.assertGreater(out.count("\nv "), 3000)
        self.assertGreater(out.count("\nf "), 1500)

    def test_recipe_can_scatter_instances(self):
        out = execute_text(SCATTER_INSTANCE_RECIPE)
        self.assertIn("scatter id=posts", out)
        self.assertIn("instance from=posts", out)
        self.assertGreater(out.count("\nv "), 150)
        self.assertGreater(out.count("\nf "), 100)

    def test_recipe_can_instance_wfc_layout(self):
        out = execute_text(WFC_INSTANCE_RECIPE)
        self.assertIn("wfc id=layout", out)
        self.assertIn("rules=void:void,floor;floor:void,floor,wall;wall:floor,wall", out)
        self.assertGreater(out.count("\nv "), 250)
        self.assertGreater(out.count("\nf "), 180)

    def test_recipe_can_instance_semantic_wfc_modules(self):
        out = execute_text(WFC_MODULE_RECIPE)
        self.assertIn("module id=arch", out)
        self.assertIn("socket module=wall", out)
        self.assertIn("instance from=layout module=tile", out)
        self.assertGreater(out.count("\nv "), 450)
        self.assertGreater(out.count("\nf "), 250)

    def test_recipe_can_instance_hidden_object_template_modules(self):
        out = execute_text(WFC_TEMPLATE_MODULE_RECIPE)
        self.assertIn("module id=arch kind=object ref=arch_wall_template origin=center_bottom", out)
        self.assertIn("#@hidden: true", out)
        self.assertGreater(out.count("\nv "), 250)
        self.assertGreater(out.count("\nf "), 140)

    def test_recipe_can_use_directional_wfc_sockets_and_controls(self):
        out = execute_text(WFC_DIRECTIONAL_CONTROLS_RECIPE)
        self.assertIn("#@controls:", out)
        self.assertIn("socket module=door_y north=wall_y,column", out)
        self.assertIn("wall_y_rotation=[0,0,90]", out)
        self.assertIn("force=0,1:column;1,1:wall_x;2,1:door_x", out)
        self.assertGreater(out.count("\nv "), 220)
        self.assertGreater(out.count("\nf "), 160)

    def test_directional_wfc_respects_inverse_socket_constraints(self):
        out = execute_text(WFC_INVERSE_SOCKET_RECIPE)
        z_values = [
            float(line.split()[3])
            for line in out.splitlines()
            if line.startswith("v ") and len(line.split()) >= 4
        ]
        self.assertGreater(max(z_values), 0.4)


if __name__ == "__main__":
    unittest.main()
