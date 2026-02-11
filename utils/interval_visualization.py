"""
Interval visualization utilities for lithology and alteration data.

This module provides functions to create curved tube geometries along
desurveyed drill hole paths for lithology and alteration intervals.
"""

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix
from typing import List, Dict, Any, Tuple, Optional


def interpolate_position_on_trace(depths: List[float], coords: List[List[float]],
                                   target_depth: float) -> Optional[Tuple[float, float, float]]:
    """Interpolate XYZ position at a target depth along a drill trace.

    Args:
        depths: List of depth values from trace_data['depths']
        coords: List of [x, y, z] coordinates from trace_data['coords']
        target_depth: Depth to interpolate position at

    Returns:
        Tuple (x, y, z) at target depth, or None if out of range
    """
    if not depths or not coords or len(depths) != len(coords):
        return None

    # Check if target is out of range
    if target_depth < depths[0] or target_depth > depths[-1]:
        return None

    # Find the two closest depth points
    for i in range(len(depths) - 1):
        if depths[i] <= target_depth <= depths[i + 1]:
            # Linear interpolation between the two points
            d1, d2 = depths[i], depths[i + 1]
            c1, c2 = coords[i], coords[i + 1]

            # Interpolation factor
            if d2 - d1 == 0:
                t = 0
            else:
                t = (target_depth - d1) / (d2 - d1)

            # Interpolate each coordinate
            x = c1[0] + t * (c2[0] - c1[0])
            y = c1[1] + t * (c2[1] - c1[1])
            z = c1[2] + t * (c2[2] - c1[2])

            return (x, y, z)

    # If exact match at end
    if target_depth == depths[-1]:
        c = coords[-1]
        return (c[0], c[1], c[2])

    return None


def extract_trace_segment(depths: List[float], coords: List[List[float]],
                          depth_from: float, depth_to: float) -> Tuple[List[float], List[List[float]]]:
    """Extract a segment of the drill trace between two depths.

    Args:
        depths: List of depth values from trace_data['depths']
        coords: List of [x, y, z] coordinates from trace_data['coords']
        depth_from: Start depth of interval
        depth_to: End depth of interval

    Returns:
        Tuple (segment_depths, segment_coords) for the interval
    """
    if not depths or not coords:
        return [], []

    segment_depths = []
    segment_coords = []

    # Add interpolated start point if needed
    if depth_from > depths[0]:
        start_pos = interpolate_position_on_trace(depths, coords, depth_from)
        if start_pos:
            segment_depths.append(depth_from)
            segment_coords.append(list(start_pos))

    # Add all intermediate points within the interval
    for i, d in enumerate(depths):
        if depth_from <= d <= depth_to:
            segment_depths.append(d)
            segment_coords.append(coords[i])

    # Add interpolated end point if needed
    if depth_to < depths[-1]:
        end_pos = interpolate_position_on_trace(depths, coords, depth_to)
        if end_pos:
            segment_depths.append(depth_to)
            segment_coords.append(list(end_pos))

    return segment_depths, segment_coords


def create_curved_tube_mesh(segment_coords: List[List[float]],
                            radius: float = 0.1,
                            resolution: int = 8,
                            name: str = "Tube") -> Optional[bpy.types.Object]:
    """Create a curved tube mesh following a path.

    Args:
        segment_coords: List of [x, y, z] coordinates defining the centerline
        radius: Tube radius
        resolution: Number of vertices around tube circumference
        name: Name for the mesh object

    Returns:
        Blender mesh object, or None if failed
    """
    if len(segment_coords) < 2:
        print(f"WARNING: Not enough points to create tube ({len(segment_coords)})")
        return None

    # Create mesh and object
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)

    # NOTE: Don't link to scene collection here - caller will link to appropriate collection

    # Create bmesh
    bm = bmesh.new()

    # Create tube vertices along path
    vertices = []
    for i, coord in enumerate(segment_coords):
        center = Vector(coord)

        # Calculate tangent direction
        if i == 0:
            # First point: use direction to next point
            tangent = Vector(segment_coords[i + 1]) - center
        elif i == len(segment_coords) - 1:
            # Last point: use direction from previous point
            tangent = center - Vector(segment_coords[i - 1])
        else:
            # Middle points: average of directions
            prev_dir = center - Vector(segment_coords[i - 1])
            next_dir = Vector(segment_coords[i + 1]) - center
            tangent = (prev_dir + next_dir).normalized()

        tangent.normalize()

        # Create perpendicular vectors for tube cross-section
        # Find a vector not parallel to tangent
        if abs(tangent.z) < 0.9:
            up = Vector((0, 0, 1))
        else:
            up = Vector((1, 0, 0))

        # Create orthonormal basis
        right = tangent.cross(up).normalized()
        up = right.cross(tangent).normalized()

        # Create ring of vertices
        ring_verts = []
        for j in range(resolution):
            angle = (2 * np.pi * j) / resolution
            offset = (right * np.cos(angle) + up * np.sin(angle)) * radius
            vert_pos = center + offset
            v = bm.verts.new(vert_pos)
            ring_verts.append(v)

        vertices.append(ring_verts)

    # Ensure lookup table is up to date
    bm.verts.ensure_lookup_table()

    # Create faces connecting rings
    for i in range(len(vertices) - 1):
        ring1 = vertices[i]
        ring2 = vertices[i + 1]

        for j in range(resolution):
            j_next = (j + 1) % resolution

            # Create quad face
            v1 = ring1[j]
            v2 = ring1[j_next]
            v3 = ring2[j_next]
            v4 = ring2[j]

            try:
                bm.faces.new([v1, v2, v3, v4])
            except ValueError:
                # Face already exists or invalid
                pass

    # Cap the ends
    if len(vertices) > 0:
        # Cap start
        try:
            bm.faces.new(vertices[0])
        except ValueError:
            pass

        # Cap end
        try:
            bm.faces.new(reversed(vertices[-1]))
        except ValueError:
            pass

    # Update mesh
    bm.to_mesh(mesh)
    bm.free()

    # Smooth shading
    for poly in mesh.polygons:
        poly.use_smooth = True

    return obj


def create_interval_tube(trace_depths: List[float],
                        trace_coords: List[List[float]],
                        depth_from: float,
                        depth_to: float,
                        radius: float = 0.1,
                        resolution: int = 8,
                        name: str = "Interval") -> Optional[bpy.types.Object]:
    """Create a curved tube for a lithology/alteration interval along a drill trace.

    Args:
        trace_depths: Full trace depth array
        trace_coords: Full trace coordinate array
        depth_from: Start depth of interval
        depth_to: End depth of interval
        radius: Tube radius
        resolution: Tube cross-section resolution
        name: Object name

    Returns:
        Created mesh object or None if failed
    """
    # Extract the segment for this interval
    segment_depths, segment_coords = extract_trace_segment(
        trace_depths, trace_coords, depth_from, depth_to
    )

    if len(segment_coords) < 2:
        print(f"WARNING: Insufficient segment points for interval {depth_from}-{depth_to}m")
        return None

    # Create the tube mesh
    tube_obj = create_curved_tube_mesh(
        segment_coords=segment_coords,
        radius=radius,
        resolution=resolution,
        name=name
    )

    return tube_obj


def apply_material_to_interval(obj: bpy.types.Object,
                               color: Tuple[float, float, float, float] = (0.5, 0.5, 0.5, 1.0),
                               material_name: str = None,
                               material_prefix: str = "Lithology"):
    """Apply a colored material to an interval object.

    Args:
        obj: Blender object to apply material to
        color: RGBA color tuple (values 0-1)
        material_name: Optional name for the material (e.g., lithology type name)
        material_prefix: Prefix for the material name (e.g., "Lithology", "Alteration", "Mineralization")
    """
    if not obj or not obj.data:
        return

    # Create or get material
    if material_name:
        mat_name = f"{material_prefix}_{material_name}"
    else:
        mat_name = f"Interval_Mat_{int(color[0]*255)}_{int(color[1]*255)}_{int(color[2]*255)}"

    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True

        # Set viewport display color (shows in solid view)
        mat.diffuse_color = color

        # Get the principled BSDF node
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Metallic"].default_value = 0.0
            bsdf.inputs["Roughness"].default_value = 0.5

    # Assign material
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def get_color_for_lithology(lithology_name: str) -> Tuple[float, float, float, float]:
    """Get a color for a lithology type.

    Args:
        lithology_name: Name of the lithology

    Returns:
        RGBA color tuple
    """
    # Simple hash-based color generation
    # In production, this should use a lookup table or API-provided colors
    if not lithology_name:
        return (0.5, 0.5, 0.5, 1.0)

    # Hash the name to get consistent colors
    hash_val = hash(lithology_name.lower())

    # Generate RGB from hash
    r = ((hash_val & 0xFF0000) >> 16) / 255.0
    g = ((hash_val & 0x00FF00) >> 8) / 255.0
    b = (hash_val & 0x0000FF) / 255.0

    # Ensure colors are not too dark
    r = max(r, 0.3)
    g = max(g, 0.3)
    b = max(b, 0.3)

    return (r, g, b, 1.0)


def get_color_for_alteration(alteration_name: str) -> Tuple[float, float, float, float]:
    """Get a color for an alteration type.

    Args:
        alteration_name: Name of the alteration

    Returns:
        RGBA color tuple
    """
    # Similar to lithology, use hash-based coloring
    # Use different hash seed for variety
    if not alteration_name:
        return (0.7, 0.3, 0.3, 1.0)

    hash_val = hash((alteration_name.lower() + "_alt"))

    r = ((hash_val & 0xFF0000) >> 16) / 255.0
    g = ((hash_val & 0x00FF00) >> 8) / 255.0
    b = (hash_val & 0x0000FF) / 255.0

    # Shift towards warmer colors for alteration
    r = max(r, 0.4)
    g = max(g, 0.2)
    b = max(b, 0.2)

    return (r, g, b, 1.0)
