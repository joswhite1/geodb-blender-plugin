"""
Drillpad mesh creation utilities.

Creates 3D extruded meshes from 2D polygon + elevation data,
and provides utilities for calculating drill hole geometry.
"""

import bpy
import bmesh
import mathutils
import numpy as np
from typing import List, Tuple, Dict, Any, Optional


def create_drillpad_mesh(
    name: str,
    vertices_2d: List[List[float]],
    elevation: float,
    extrusion_height: float = 10.0,
    color_hex: str = "#4CAF50",
    centroid: Optional[Tuple[float, float, float]] = None
) -> bpy.types.Object:
    """
    Create a 3D extruded mesh from a 2D polygon.

    Args:
        name: Object name
        vertices_2d: List of [x, y] vertices defining the polygon boundary
        elevation: Center elevation in meters
        extrusion_height: Total height of extrusion (default 10m)
        color_hex: Material color
        centroid: Optional (x, y, z) centroid to offset vertices by.
                  If provided, vertices_2d are treated as relative to centroid.

    Returns:
        bpy.types.Object: The created mesh object
    """
    # Calculate Z bounds (centered on elevation)
    z_bottom = elevation - (extrusion_height / 2)
    z_top = elevation + (extrusion_height / 2)

    # Get centroid for origin placement
    # If centroid provided, use it; otherwise calculate from vertices
    if centroid and len(centroid) >= 2:
        origin_x = centroid[0]
        origin_y = centroid[1]
        origin_z = centroid[2] if len(centroid) > 2 else elevation
    else:
        # Calculate centroid from vertices
        origin_x = sum(v[0] for v in vertices_2d) / len(vertices_2d)
        origin_y = sum(v[1] for v in vertices_2d) / len(vertices_2d)
        origin_z = elevation

    # Create mesh using bmesh for extrusion
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # Create bottom face vertices (relative to origin so mesh is centered)
    bottom_verts = []
    for x, y in vertices_2d:
        v = bm.verts.new((x - origin_x, y - origin_y, z_bottom - origin_z))
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

    # Create object and set its location to the centroid
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (origin_x, origin_y, origin_z)
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
    Create a preview tube for a planned drill hole using a Bezier curve.

    Uses a curve with bevel for easy editing - just two control points
    (collar and toe) that can be moved in Edit Mode.

    Args:
        name: Object name
        collar: (x, y, z) collar position
        azimuth: Azimuth in degrees (0-360)
        dip: Dip in degrees (-90 to 0)
        length: Hole length in meters
        color_hex: Preview color
        tube_radius: Radius of the preview tube

    Returns:
        bpy.types.Object: Preview curve object
    """
    # Calculate end point (toe)
    az_rad = np.radians(azimuth)
    dip_rad = np.radians(dip)

    # Direction vector
    dx = length * np.cos(dip_rad) * np.sin(az_rad)
    dy = length * np.cos(dip_rad) * np.cos(az_rad)
    dz = length * np.sin(dip_rad)  # Negative dip = negative dz

    toe = (
        collar[0] + dx,
        collar[1] + dy,
        collar[2] + dz
    )

    # Create a new curve data block
    curve_data = bpy.data.curves.new(name=name, type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 12
    curve_data.fill_mode = 'FULL'

    # Set bevel for tube appearance
    curve_data.bevel_depth = tube_radius
    curve_data.bevel_resolution = 4  # Smoothness of the circular cross-section
    curve_data.use_fill_caps = True  # Cap the ends

    # Create a new spline in the curve
    spline = curve_data.splines.new(type='BEZIER')
    spline.bezier_points.add(1)  # We need 2 points total (1 default + 1 added)

    # Set the collar point (first point)
    collar_point = spline.bezier_points[0]
    collar_point.co = collar
    # Set handles to be straight (vector type) for a straight line
    collar_point.handle_left_type = 'VECTOR'
    collar_point.handle_right_type = 'VECTOR'

    # Set the toe point (second point)
    toe_point = spline.bezier_points[1]
    toe_point.co = toe
    toe_point.handle_left_type = 'VECTOR'
    toe_point.handle_right_type = 'VECTOR'

    # Create the object
    obj = bpy.data.objects.new(name, curve_data)
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
    extrusion_height: float = 10.0,
    centroid: Optional[Tuple[float, float, float]] = None
) -> None:
    """
    Update an existing drillpad mesh object with new geometry.

    Args:
        obj: Existing Blender mesh object to update
        vertices_2d: List of [x, y] vertices defining the polygon boundary
        elevation: Center elevation in meters
        extrusion_height: Total height of extrusion (default 10m)
        centroid: Optional (x, y, z) centroid to offset vertices by.
                  If provided, vertices_2d are treated as relative to centroid.
    """
    # Calculate Z bounds (centered on elevation)
    z_bottom = elevation - (extrusion_height / 2)
    z_top = elevation + (extrusion_height / 2)

    # Get centroid for origin placement
    # If centroid provided, use it; otherwise calculate from vertices
    if centroid and len(centroid) >= 2:
        origin_x = centroid[0]
        origin_y = centroid[1]
        origin_z = centroid[2] if len(centroid) > 2 else elevation
    else:
        # Calculate centroid from vertices
        origin_x = sum(v[0] for v in vertices_2d) / len(vertices_2d)
        origin_y = sum(v[1] for v in vertices_2d) / len(vertices_2d)
        origin_z = elevation

    # Get the mesh data
    mesh = obj.data

    # Create new geometry using bmesh
    bm = bmesh.new()

    # Create bottom face vertices (relative to origin so mesh is centered)
    bottom_verts = []
    for x, y in vertices_2d:
        v = bm.verts.new((x - origin_x, y - origin_y, z_bottom - origin_z))
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

    # Update object location to the new centroid
    obj.location = (origin_x, origin_y, origin_z)


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


def extract_hole_endpoints(obj: bpy.types.Object) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """
    Extract collar and toe positions from a planned hole curve.

    For Bezier curves, this extracts the two control point positions directly.
    The first point is the collar, the second is the toe.

    Args:
        obj: Blender curve object representing a planned hole

    Returns:
        Tuple of ((collar_x, collar_y, collar_z), (toe_x, toe_y, toe_z))
        or None if extraction fails
    """
    if not obj:
        return None

    # Handle curve objects (new format)
    if obj.type == 'CURVE':
        curve_data = obj.data
        if not curve_data.splines or len(curve_data.splines) == 0:
            return None

        spline = curve_data.splines[0]

        if spline.type == 'BEZIER':
            if len(spline.bezier_points) < 2:
                return None

            # Get world matrix for transformation
            world_matrix = obj.matrix_world

            # First point is collar
            collar_local = spline.bezier_points[0].co
            collar_world = world_matrix @ collar_local
            collar = (collar_world.x, collar_world.y, collar_world.z)

            # Second point is toe
            toe_local = spline.bezier_points[1].co
            toe_world = world_matrix @ toe_local
            toe = (toe_world.x, toe_world.y, toe_world.z)

            return (collar, toe)

        elif spline.type == 'POLY':
            if len(spline.points) < 2:
                return None

            world_matrix = obj.matrix_world

            # First point is collar
            collar_local = spline.points[0].co
            collar_world = world_matrix @ collar_local.to_3d()
            collar = (collar_world.x, collar_world.y, collar_world.z)

            # Last point is toe
            toe_local = spline.points[-1].co
            toe_world = world_matrix @ toe_local.to_3d()
            toe = (toe_world.x, toe_world.y, toe_world.z)

            return (collar, toe)

    # Handle mesh objects (legacy format for backwards compatibility)
    elif obj.type == 'MESH':
        mesh = obj.data

        if len(mesh.vertices) < 2:
            return None

        # Get all vertex positions in world space
        world_matrix = obj.matrix_world
        world_verts = []
        for v in mesh.vertices:
            world_co = world_matrix @ v.co
            world_verts.append((world_co.x, world_co.y, world_co.z))

        if not world_verts:
            return None

        # Find min and max Z to identify the two ends
        z_values = [v[2] for v in world_verts]
        z_min = min(z_values)
        z_max = max(z_values)

        z_range = z_max - z_min
        if z_range < 0.01:
            return None

        z_tolerance = z_range * 0.1

        # Group vertices by Z level
        bottom_verts = [v for v in world_verts if abs(v[2] - z_min) < z_tolerance]
        top_verts = [v for v in world_verts if abs(v[2] - z_max) < z_tolerance]

        if not bottom_verts or not top_verts:
            return None

        # Calculate centers of each group
        def center_of_points(points):
            n = len(points)
            return (
                sum(p[0] for p in points) / n,
                sum(p[1] for p in points) / n,
                sum(p[2] for p in points) / n
            )

        bottom_center = center_of_points(bottom_verts)
        top_center = center_of_points(top_verts)

        # Determine which is collar based on stored value or Z height
        stored_collar_z = obj.get('geodb_collar_z')

        if stored_collar_z is not None:
            if abs(bottom_center[2] - stored_collar_z) < abs(top_center[2] - stored_collar_z):
                collar = bottom_center
                toe = top_center
            else:
                collar = top_center
                toe = bottom_center
        else:
            # Default: higher Z is collar (drilling downward)
            if bottom_center[2] > top_center[2]:
                collar = bottom_center
                toe = top_center
            else:
                collar = top_center
                toe = bottom_center

        return (collar, toe)

    return None


def update_hole_mesh_from_geometry(
    obj: bpy.types.Object,
    collar: Tuple[float, float, float],
    azimuth: float,
    dip: float,
    length: float,
    tube_radius: float = 1.0
) -> None:
    """
    Update an existing planned hole curve with new geometry.

    Updates the Bezier curve control points based on new collar position and orientation.

    Args:
        obj: Existing Blender curve object to update
        collar: (x, y, z) collar position
        azimuth: Azimuth in degrees (0-360)
        dip: Dip in degrees (-90 to 0)
        length: Hole length in meters
        tube_radius: Radius of the tube (updates bevel_depth)
    """
    if not obj:
        return

    # Calculate toe position
    az_rad = np.radians(azimuth)
    dip_rad = np.radians(dip)

    dx = length * np.cos(dip_rad) * np.sin(az_rad)
    dy = length * np.cos(dip_rad) * np.cos(az_rad)
    dz = length * np.sin(dip_rad)

    toe = (
        collar[0] + dx,
        collar[1] + dy,
        collar[2] + dz
    )

    # Handle curve objects
    if obj.type == 'CURVE':
        curve_data = obj.data

        # Update bevel radius if needed
        curve_data.bevel_depth = tube_radius

        if curve_data.splines and len(curve_data.splines) > 0:
            spline = curve_data.splines[0]

            if spline.type == 'BEZIER' and len(spline.bezier_points) >= 2:
                # Get inverse world matrix to convert world coords to local
                world_matrix_inv = obj.matrix_world.inverted()

                # Convert world coordinates to local
                collar_local = world_matrix_inv @ mathutils.Vector(collar)
                toe_local = world_matrix_inv @ mathutils.Vector(toe)

                # Update collar point
                spline.bezier_points[0].co = collar_local
                spline.bezier_points[0].handle_left_type = 'VECTOR'
                spline.bezier_points[0].handle_right_type = 'VECTOR'

                # Update toe point
                spline.bezier_points[1].co = toe_local
                spline.bezier_points[1].handle_left_type = 'VECTOR'
                spline.bezier_points[1].handle_right_type = 'VECTOR'

    # Handle legacy mesh objects
    elif obj.type == 'MESH':
        direction = np.array([dx, dy, dz])
        direction_norm = direction / np.linalg.norm(direction)

        mesh = obj.data
        bm = bmesh.new()

        segments = 8

        bottom_verts = []
        top_verts = []

        for i in range(segments):
            angle = (2 * np.pi * i) / segments
            x = tube_radius * np.cos(angle)
            y = tube_radius * np.sin(angle)

            bottom_verts.append(bm.verts.new((x, y, 0)))
            top_verts.append(bm.verts.new((x, y, length)))

        bm.verts.ensure_lookup_table()

        bm.faces.new(bottom_verts)
        bm.faces.new(top_verts[::-1])

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

        for v in bm.verts:
            local_point = np.array([v.co.x, v.co.y, v.co.z])
            rotated = np.dot(rotation_matrix, local_point)
            v.co.x = rotated[0] + collar[0]
            v.co.y = rotated[1] + collar[1]
            v.co.z = rotated[2] + collar[2]

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        obj.location = (0, 0, 0)
        obj.rotation_euler = (0, 0, 0)
        obj.scale = (1, 1, 1)
