"""
Cylinder mesh creation utilities for drill sample visualization.

This module provides functions to create cylinder meshes representing
drill sample intervals with proper rotation, coloring, and metadata storage.
"""

import bpy
import numpy as np
import json
from typing import Tuple, Dict, Any


def hex_to_rgb(hex_color: str) -> Tuple[float, float, float, float]:
    """Convert hex color to RGBA tuple (0-1 range).

    Args:
        hex_color: Hex color string (#RRGGBB)

    Returns:
        Tuple of (R, G, B, A) in 0-1 range
    """
    hex_color = hex_color.lstrip('#')

    if len(hex_color) == 6:
        r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        return (r, g, b, 1.0)
    else:
        return (1.0, 1.0, 1.0, 1.0)


# Alias for consistency with other modules
hex_to_rgba = hex_to_rgb


def create_sample_cylinder_mesh(xyz_from: Tuple[float, float, float],
                                 xyz_to: Tuple[float, float, float],
                                 diameter: float = 2.0,
                                 color_hex: str = "#FFFFFF",
                                 name: str = "Sample",
                                 material_name: str = "AssayMaterial",
                                 assay_metadata: Dict[str, Any] = None) -> bpy.types.Object:
    """
    Create a cylinder mesh representing a drill sample interval.

    Args:
        xyz_from: (x, y, z) start point (shallow depth, higher Z elevation)
        xyz_to: (x, y, z) end point (deeper depth, lower Z elevation)
        diameter: Cylinder diameter in meters (represents size from config)
        color_hex: Hex color code (#RRGGBB)
        name: Name for the mesh object
        material_name: Name for the material
        assay_metadata: Dict containing all assay data to store on the object

    Returns:
        bpy.types.Object: The created cylinder object
    """
    xyz_from = np.array(xyz_from)
    xyz_to = np.array(xyz_to)

    # Calculate cylinder properties
    # Vector points from bottom (deeper) to top (shallower)
    vector = xyz_from - xyz_to
    length = np.linalg.norm(vector)

    if length < 0.001:
        raise ValueError(f"Sample interval too short: {length}m")

    radius = diameter / 2.0

    # Calculate rotation matrix to align with vector
    z_axis = np.array([0, 0, 1])
    normalized_vector = vector / length

    # Build rotation matrix using Rodrigues' rotation formula
    if np.allclose(normalized_vector, z_axis):
        rotation_matrix = np.eye(3)
        rotation_quat = [1, 0, 0, 0]
    elif np.allclose(normalized_vector, -z_axis):
        rotation_matrix = np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1]])
        rotation_quat = [0, 1, 0, 0]
    else:
        rotation_axis = np.cross(z_axis, normalized_vector)
        rotation_axis = rotation_axis / np.linalg.norm(rotation_axis)
        rotation_angle = np.arccos(np.dot(z_axis, normalized_vector))

        K = np.array([
            [0, -rotation_axis[2], rotation_axis[1]],
            [rotation_axis[2], 0, -rotation_axis[0]],
            [-rotation_axis[1], rotation_axis[0], 0]
        ])
        rotation_matrix = np.eye(3) + np.sin(rotation_angle) * K + (1 - np.cos(rotation_angle)) * np.dot(K, K)

        half_angle = rotation_angle / 2
        sin_half = np.sin(half_angle)
        rotation_quat = [
            np.cos(half_angle),
            rotation_axis[0] * sin_half,
            rotation_axis[1] * sin_half,
            rotation_axis[2] * sin_half
        ]

    # Create vertices for cylinder in local space
    vertices = []
    faces = []
    sides = 8

    # Create cylinder vertices in local space (Z-axis from 0 to length)
    for i in range(sides):
        angle = (2 * np.pi * i) / sides
        x = radius * np.cos(angle)
        y = radius * np.sin(angle)
        vertices.append([x, y, 0])

    for i in range(sides):
        angle = (2 * np.pi * i) / sides
        x = radius * np.cos(angle)
        y = radius * np.sin(angle)
        vertices.append([x, y, length])

    vertices.append([0, 0, 0])
    bottom_center_idx = len(vertices) - 1

    vertices.append([0, 0, length])
    top_center_idx = len(vertices) - 1

    # Create faces
    for i in range(sides):
        next_i = (i + 1) % sides
        faces.append([bottom_center_idx, next_i, i])

    for i in range(sides):
        next_i = (i + 1) % sides
        faces.append([top_center_idx, sides + i, sides + next_i])

    for i in range(sides):
        next_i = (i + 1) % sides
        faces.append([i, next_i, sides + next_i, sides + i])

    # Transform vertices to world space
    transformed_vertices = []
    for v in vertices:
        local_point = np.array(v)
        rotated = np.dot(rotation_matrix, local_point)
        world_point = rotated + xyz_to
        transformed_vertices.append(world_point.tolist())

    # Create mesh with transformed vertices
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(transformed_vertices, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Object is at world origin with no rotation since vertices are already in world space
    obj.location = (0, 0, 0)
    obj.rotation_quaternion = (1, 0, 0, 0)

    # Create and assign material
    mat = bpy.data.materials.new(name=material_name)
    mat.diffuse_color = hex_to_rgb(color_hex)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'

    obj.data.materials.append(mat)

    # Store all metadata as custom properties on the object
    if assay_metadata:
        for key, value in assay_metadata.items():
            if value is not None:
                if isinstance(value, dict):
                    if key == 'all_elements':
                        # Store each element as separate properties
                        for elem_key, elem_val in value.items():
                            # elem_val is a dict like: {"element": "Ag", "value": 1.8, "units": "ppm", "method_name": "AQ202", ...}
                            # Store each field as a separate property
                            if isinstance(elem_val, dict):
                                for field_name, field_value in elem_val.items():
                                    # Create property name like: element_Ag_value, element_Ag_units, element_Ag_method_name
                                    prop_name = f"{elem_key}_{field_name}"
                                    try:
                                        if field_value is not None:
                                            obj[prop_name] = field_value
                                    except (TypeError, ValueError):
                                        obj[prop_name] = str(field_value)
                    else:
                        obj[key] = json.dumps(value)
                else:
                    try:
                        obj[key] = value
                    except (TypeError, ValueError):
                        obj[key] = str(value)

    # Always store cylinder endpoints
    obj['cylinder_top'] = [float(xyz_from[0]), float(xyz_from[1]), float(xyz_from[2])]
    obj['cylinder_bottom'] = [float(xyz_to[0]), float(xyz_to[1]), float(xyz_to[2])]

    return obj
