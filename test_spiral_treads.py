#!/usr/bin/env python3
"""Test script for spiral_treads_mesh to debug vertex coordinates and face connectivity."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'routes', 'api', 'executor'))

from live_obj_executor_v02 import spiral_treads_mesh

# Test parameters matching the Live OBJ example
params = {
    'count': 18,
    'turns': 1.5,
    'height': 3.2,
    'inner_radius': 0.18,
    'outer_radius': 1.15,
    'tread_thickness': 0.07,
    'tread_angle': 18,
    'tread_depth': 0.72
}

center = (0.0, 0.0, 0.0)

print("Testing spiral_treads_mesh with parameters:")
print(f"  count: {params['count']}")
print(f"  turns: {params['turns']}")
print(f"  height: {params['height']}")
print(f"  inner_radius: {params['inner_radius']}")
print(f"  outer_radius: {params['outer_radius']}")
print(f"  tread_thickness: {params['tread_thickness']}")
print(f"  tread_angle: {params['tread_angle']}")
print(f"  center: {center}")
print()

mesh = spiral_treads_mesh(params, center)

print(f"\nGenerated mesh:")
print(f"  Vertices: {len(mesh.vertices)}")
print(f"  Faces: {len(mesh.faces)}")

# Log first tread vertices and check face connectivity
print("\nFirst tread vertices (indices 0-7):")
for i in range(8):
    x, y, z = mesh.vertices[i]
    print(f"  Vertex {i}: ({x:.4f}, {y:.4f}, {z:.4f})")

# Check distances between vertices to verify box shape
print("\nFirst tread edge distances:")
def dist(v1, v2):
    return ((v1[0]-v2[0])**2 + (v1[1]-v2[1])**2 + (v1[2]-v2[2])**2)**0.5

# Bottom edges
print(f"  0-1: {dist(mesh.vertices[0], mesh.vertices[1]):.4f} (should be radial)")
print(f"  1-2: {dist(mesh.vertices[1], mesh.vertices[2]):.4f} (should be tangential)")
print(f"  2-3: {dist(mesh.vertices[2], mesh.vertices[3]):.4f} (should be radial)")
print(f"  3-0: {dist(mesh.vertices[3], mesh.vertices[0]):.4f} (should be tangential)")
# Vertical edges
print(f"  0-4: {dist(mesh.vertices[0], mesh.vertices[4]):.4f} (should be thickness)")
print(f"  1-5: {dist(mesh.vertices[1], mesh.vertices[5]):.4f} (should be thickness)")
print(f"  2-6: {dist(mesh.vertices[2], mesh.vertices[6]):.4f} (should be thickness)")
print(f"  3-7: {dist(mesh.vertices[3], mesh.vertices[7]):.4f} (should be thickness)")
# Top edges
print(f"  4-5: {dist(mesh.vertices[4], mesh.vertices[5]):.4f} (should be radial)")
print(f"  5-6: {dist(mesh.vertices[5], mesh.vertices[6]):.4f} (should be tangential)")
print(f"  6-7: {dist(mesh.vertices[6], mesh.vertices[7]):.4f} (should be radial)")
print(f"  7-4: {dist(mesh.vertices[7], mesh.vertices[4]):.4f} (should be tangential)")

# Log first tread faces
print("\nFirst tread faces (indices 0-5):")
for i in range(6):
    face = mesh.faces[i]
    print(f"  Face {i}: {face}")

# Check if vertices form a proper box by checking diagonal distances
print("\nFirst tread diagonal distances:")
print(f"  0-6: {dist(mesh.vertices[0], mesh.vertices[6]):.4f} (space diagonal)")
print(f"  1-7: {dist(mesh.vertices[1], mesh.vertices[7]):.4f} (space diagonal)")

# Test with different outer_radius
print("\n\nTesting with outer_radius=2.0:")
params2 = params.copy()
params2['outer_radius'] = 2.0
mesh2 = spiral_treads_mesh(params2, center)
print(f"  First tread vertices (indices 0-7):")
for i in range(8):
    x, y, z = mesh2.vertices[i]
    print(f"    Vertex {i}: ({x:.4f}, {y:.4f}, {z:.4f})")
print(f"  Edge 0-1: {dist(mesh2.vertices[0], mesh2.vertices[1]):.4f} (should be larger than before)")
