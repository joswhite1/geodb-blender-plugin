"""
Drillpad mesh creation utilities.

Creates 3D extruded meshes from 2D polygon + elevation data,
and provides utilities for calculating drill hole geometry.
"""

import bpy
import bmesh
import numpy as np
from typing import List, Tuple, Dict, Any, Optional


def create_drillpad_mesh(
    name: str,
    vertices_2d: List[List[float]],
    elevation: float,
    extrusion_height: float = 10.0,
    color_hex: str = "#4CAF50"
) -> bpy.types.Object:
    """
    Create a 3D extruded mesh from a 2D polygon.

    Args:
        name: Object name
        vertices_2d: List of [x, y] vertices defining the polygon boundary
        elevation: Center elevation in meters
        extrusion_height: Total height of extrusion (default 10m)
        color_hex: Material color

    Returns:
        bpy.types.Object: The created mesh object
    """
    # Calculate Z bounds (centered on elevation)
    z_bottom = elevation - (extrusion_height / 2)
    z_top = elevation + (extrusion_height / 2)

    # Create mesh using bmesh for extrusion
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # Create bottom face vertices
    bottom_verts = []
    for x, y in vertices_2d:
        v = bm.verts.new((x, y, z_bottom))
        bottom_verts.append(v)

    bm.verts.ensure_lookup_table()

    # Create bottom face
    if len(bottom_verts) >= 3:
        try:
            bottom_face = bm.faces.new(bottom_verts)
        except ValueError:
            # Vertices may need to be reversed
            bottom_verts.reverse()
            bottom_face = bm.faces.new(bottom_verts)

        # Extrude to create 3D shape
        result = bmesh.ops.extrude_face_region(bm, geom=[bottom_face])
        extruded_verts = [v for v in result['geom'] if isinstance(v, bmesh.types.BMVert)]

        # Move extruded vertices to top
        bmesh.ops.translate(bm, vec=(0, 0, extrusion_height), verts=extruded_verts)

        # Recalculate normals
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # Transfer to mesh
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    # Create object
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    # Create material
    mat = bpy.data.materials.new(name=f"DrillPad_{name}")
    mat.use_nodes = True

    # Set color
    hex_color = color_hex.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    mat.diffuse_color = (r, g, b, 0.8)

    # Set up nodes for transparency
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Alpha"].default_value = 0.8

    mat.blend_method = 'BLEND'
    obj.data.materials.append(mat)

    return obj


def calculate_hole_geometry(
    pad_center: Tuple[float, float, float],
    target_point: Tuple[float, float, float]
) -> Tuple[float, float, float]:
    """
    Calculate azimuth, dip, and length from pad center to target point.

    Args:
        pad_center: (x, y, z) of pad centroid
        target_point: (x, y, z) of target (e.g., 3D cursor)

    Returns:
        Tuple[azimuth, dip, length]:
            - azimuth: 0-360 degrees (0=North, 90=East)
            - dip: -90 to 0 degrees (negative = downward)
            - length: Distance in meters
    """
    dx = target_point[0] - pad_center[0]
    dy = target_point[1] - pad_center[1]
    dz = target_point[2] - pad_center[2]

    # Calculate horizontal distance
    horizontal_dist = np.sqrt(dx**2 + dy**2)

    # Calculate total length
    length = np.sqrt(dx**2 + dy**2 + dz**2)

    if length < 0.01:
        return 0.0, -90.0, 0.0  # Vertical hole

    # Calculate azimuth (0 = North, 90 = East)
    # atan2(x, y) gives angle from Y-axis (North)
    azimuth = np.degrees(np.arctan2(dx, dy))
    if azimuth < 0:
        azimuth += 360.0

    # Calculate dip (angle from horizontal, negative = down)
    if horizontal_dist > 0.001:
        dip = np.degrees(np.arctan2(dz, horizontal_dist))
    else:
        dip = -90.0 if dz < 0 else 90.0

    # Ensure dip is in valid range for drilling (typically downward)
    dip = min(0.0, dip)  # Clamp to negative (downward)

    return azimuth, dip, length


def create_planned_hole_preview(
    name: str,
    collar: Tuple[float, float, float],
    azimuth: float,
    dip: float,
    length: float,
    color_hex: str = "#FF5722",
    tube_radius: float = 1.0
) -> bpy.types.Object:
    """
    Create a preview cylinder for a planned drill hole.

    Args:
        name: Object name
        collar: (x, y, z) collar position
        azimuth: Azimuth in degrees (0-360)
        dip: Dip in degrees (-90 to 0)
        length: Hole length in meters
        color_hex: Preview color
        tube_radius: Radius of the preview tube

    Returns:
        bpy.types.Object: Preview mesh object
    """
    # Calculate end point
    az_rad = np.radians(azimuth)
    dip_rad = np.radians(dip)

    # Direction vector
    dx = length * np.cos(dip_rad) * np.sin(az_rad)
    dy = length * np.cos(dip_rad) * np.cos(az_rad)
    dz = length * np.sin(dip_rad)  # Negative dip = negative dz

    end_point = (
        collar[0] + dx,
        collar[1] + dy,
        collar[2] + dz
    )

    # Create cylinder mesh using bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # Calculate rotation to align cylinder with hole direction
    direction = np.array([dx, dy, dz])
    direction_norm = direction / np.linalg.norm(direction)

    # Create cylinder along Z-axis first, then rotate
    segments = 8

    # Create vertices for top and bottom circles
    bottom_verts = []
    top_verts = []

    for i in range(segments):
        angle = (2 * np.pi * i) / segments
        x = tube_radius * np.cos(angle)
        y = tube_radius * np.sin(angle)

        # Bottom circle at collar
        bottom_verts.append(bm.verts.new((x, y, 0)))
        # Top circle at length
        top_verts.append(bm.verts.new((x, y, length)))

    bm.verts.ensure_lookup_table()

    # Create faces
    # Bottom cap
    bm.faces.new(bottom_verts)
    # Top cap
    bm.faces.new(top_verts[::-1])  # Reverse for correct normal

    # Side faces
    for i in range(segments):
        next_i = (i + 1) % segments
        bm.faces.new([
            bottom_verts[i],
            bottom_verts[next_i],
            top_verts[next_i],
            top_verts[i]
        ])

    # Calculate rotation matrix
    z_axis = np.array([0, 0, 1])

    if np.allclose(direction_norm, z_axis):
        rotation_matrix = np.eye(3)
    elif np.allclose(direction_norm, -z_axis):
        rotation_matrix = np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1]])
    else:
        rotation_axis = np.cross(z_axis, direction_norm)
        rotation_axis = rotation_axis / np.linalg.norm(rotation_axis)
        rotation_angle = np.arccos(np.dot(z_axis, direction_norm))

        K = np.array([
            [0, -rotation_axis[2], rotation_axis[1]],
            [rotation_axis[2], 0, -rotation_axis[0]],
            [-rotation_axis[1], rotation_axis[0], 0]
        ])
        rotation_matrix = np.eye(3) + np.sin(rotation_angle) * K + (1 - np.cos(rotation_angle)) * np.dot(K, K)

    # Transform vertices to world space
    for v in bm.verts:
        local_point = np.array([v.co.x, v.co.y, v.co.z])
        rotated = np.dot(rotation_matrix, local_point)
        v.co.x = rotated[0] + collar[0]
        v.co.y = rotated[1] + collar[1]
        v.co.z = rotated[2] + collar[2]

    # Recalculate normals
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # Transfer to mesh
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    # Create object
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    # Create material
    mat = bpy.data.materials.new(name=f"PlannedHole_{name}")
    mat.use_nodes = True

    # Set color
    hex_color = color_hex.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    mat.diffuse_color = (r, g, b, 0.9)

    # Set up nodes
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Alpha"].default_value = 0.9

    mat.blend_method = 'BLEND'
    obj.data.materials.append(mat)

    # Set display properties
    obj.show_in_front = True

    return obj


def update_drillpad_mesh(
    obj: bpy.types.Object,
    vertices_2d: List[List[float]],
    elevation: float,
    extrusion_height: float = 10.0
) -> None:
    """
    Update an existing drillpad mesh object with new geometry.

    Args:
        obj: Existing Blender mesh object to update
        vertices_2d: List of [x, y] vertices defining the polygon boundary
        elevation: Center elevation in meters
        extrusion_height: Total height of extrusion (default 10m)
    """
    # Calculate Z bounds (centered on elevation)
    z_bottom = elevation - (extrusion_height / 2)
    z_top = elevation + (extrusion_height / 2)

    # Get the mesh data
    mesh = obj.data

    # Create new geometry using bmesh
    bm = bmesh.new()

    # Create bottom face vertices
    bottom_verts = []
    for x, y in vertices_2d:
        v = bm.verts.new((x, y, z_bottom))
        bottom_verts.append(v)

    bm.verts.ensure_lookup_table()

    # Create bottom face
    if len(bottom_verts) >= 3:
        try:
            bottom_face = bm.faces.new(bottom_verts)
        except ValueError:
            # Vertices may need to be reversed
            bottom_verts.reverse()
            bottom_face = bm.faces.new(bottom_verts)

        # Extrude to create 3D shape
        result = bmesh.ops.extrude_face_region(bm, geom=[bottom_face])
        extruded_verts = [v for v in result['geom'] if isinstance(v, bmesh.types.BMVert)]

        # Move extruded vertices to top
        bmesh.ops.translate(bm, vec=(0, 0, extrusion_height), verts=extruded_verts)

        # Recalculate normals
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # Clear existing mesh data and transfer new geometry
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def find_existing_drillpad(pad_id: int) -> Optional[bpy.types.Object]:
    """
    Find an existing drillpad object by its geoDB pad ID.

    Args:
        pad_id: The geoDB pad ID to search for

    Returns:
        The Blender object if found, None otherwise
    """
    for obj in bpy.data.objects:
        if (obj.get('geodb_object_type') == 'drill_pad' and
            obj.get('geodb_pad_id') == pad_id):
            return obj
    return None


def get_pad_centroid(pad_obj: bpy.types.Object, elevation_override: float = None) -> Optional[Tuple[float, float, float]]:
    """
    Get the centroid coordinates from a drill pad object.

    Args:
        pad_obj: Blender object tagged as a drill pad
        elevation_override: Optional manual elevation to use instead of stored Z

    Returns:
        Tuple (x, y, z) or None if not a valid pad
    """
    if not pad_obj:
        return None

    if pad_obj.get('geodb_object_type') != 'drill_pad':
        return None

    z_value = pad_obj.get('geodb_centroid_z', 0)

    # Use elevation override if provided
    if elevation_override is not None:
        z_value = elevation_override

    return (
        pad_obj.get('geodb_centroid_x', 0),
        pad_obj.get('geodb_centroid_y', 0),
        z_value
    )
