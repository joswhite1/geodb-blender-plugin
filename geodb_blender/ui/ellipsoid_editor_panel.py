"""
Ellipsoid Editor Panel for interactive RBF interpolation setup.

This module provides a persistent UI panel for creating, editing, and
applying search ellipsoid parameters for anisotropic RBF interpolation.

Workflow:
1. User clicks "Create Ellipsoid Widget" to spawn an interactive 3D ellipsoid
2. User transforms the ellipsoid in the viewport (rotate, scale)
3. Panel shows live rotation/scale values as user manipulates
4. User adjusts RBF settings in the panel
5. Optionally add control points to constrain interpolation boundaries
6. User clicks "Apply Interpolation" to run RBF with current settings

Control Points:
- Control points act as additional data points with user-defined values
- Typically set to 0 or threshold minimum to create "boundary" constraints
- Prevents RBF from extrapolating into empty space
- Add at 3D cursor position, then move with G key
"""

import bpy
import math
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import (
    StringProperty, FloatProperty, IntProperty,
    EnumProperty, BoolProperty, PointerProperty, CollectionProperty
)
from mathutils import Vector

from ..core.interpolation import (
    SCIPY_AVAILABLE, SearchEllipsoid,
    create_ellipsoid_visualization, update_ellipsoid_from_object,
    interpolate_from_cache, extract_assay_data_from_cache,
    get_available_elements
)
from ..core.data_cache import DrillDataCache


# =============================================================================
# Property Group for Control Points
# =============================================================================

class GeoDBControlPointItem(PropertyGroup):
    """A single control point for RBF boundary constraint."""

    object_name: StringProperty(
        name="Object Name",
        description="Name of the control point marker object",
        default="",
    )

    value: FloatProperty(
        name="Value",
        description="Constraint value at this point (typically 0 for boundary)",
        default=0.0,
    )


# =============================================================================
# Property Group for Ellipsoid Editor Settings
# =============================================================================

class GeoDBEllipsoidEditorProperties(PropertyGroup):
    """Properties for the ellipsoid editor panel."""

    # Track if we have an active ellipsoid widget
    has_active_widget: BoolProperty(
        name="Has Active Widget",
        description="Whether an ellipsoid widget is currently active",
        default=False,
    )

    active_widget_name: StringProperty(
        name="Active Widget Name",
        description="Name of the active ellipsoid widget object",
        default="",
    )

    # Control Points
    control_points: CollectionProperty(
        type=GeoDBControlPointItem,
        name="Control Points",
        description="Boundary constraint points for RBF interpolation",
    )

    active_control_point_index: IntProperty(
        name="Active Control Point",
        description="Index of the currently selected control point",
        default=0,
    )

    control_point_value: FloatProperty(
        name="Control Point Value",
        description="Value to assign to new control points (0 = boundary)",
        default=0.0,
        min=-1000.0,
        max=1000.0,
    )

    use_control_points: BoolProperty(
        name="Use Control Points",
        description="Include control points as boundary constraints in interpolation",
        default=True,
    )

    control_point_size: FloatProperty(
        name="Marker Size",
        description="Visual size of control point markers",
        default=2.0,
        min=0.5,
        max=10.0,
    )

    # RBF Settings (mirrored from main RBF operator for convenience)
    element: EnumProperty(
        name="Element",
        description="Element to interpolate",
        items=lambda self, context: get_element_items(self, context),
    )

    kernel: EnumProperty(
        name="Kernel",
        description="RBF kernel function",
        items=[
            ('linear', "Linear", "Linear kernel"),
            ('thin_plate_spline', "Thin Plate Spline", "Thin plate spline kernel (recommended)"),
            ('cubic', "Cubic", "Cubic kernel"),
            ('quintic', "Quintic", "Quintic kernel"),
            ('multiquadric', "Multiquadric", "Multiquadric kernel"),
            ('inverse_multiquadric', "Inverse Multiquadric", "Inverse multiquadric kernel"),
            ('inverse_quadratic', "Inverse Quadratic", "Inverse quadratic kernel"),
            ('gaussian', "Gaussian", "Gaussian kernel"),
        ],
        default='thin_plate_spline',
    )

    epsilon: FloatProperty(
        name="Epsilon",
        description="Shape parameter for RBF (ignored for some kernels)",
        default=1.0,
        min=0.001,
        max=100.0,
    )

    smoothing: FloatProperty(
        name="Smoothing",
        description="Smoothing parameter (0 = exact interpolation)",
        default=0.0,
        min=0.0,
        max=10.0,
    )

    grid_resolution: IntProperty(
        name="Grid Resolution",
        description="Resolution of interpolation grid per axis",
        default=50,
        min=10,
        max=200,
    )

    output_type: EnumProperty(
        name="Output Type",
        description="Type of output geometry",
        items=[
            ('POINTS', "Point Cloud", "Generate point cloud"),
            ('MESH', "Volume Mesh", "Generate volume mesh"),
        ],
        default='MESH',
    )

    use_threshold: BoolProperty(
        name="Use Thresholds",
        description="Filter interpolated values by threshold",
        default=True,
    )

    threshold_min: FloatProperty(
        name="Cutoff Grade",
        description="Minimum value (cutoff grade) for isosurface",
        default=0.1,
    )

    threshold_max: FloatProperty(
        name="Max Threshold",
        description="Maximum value to display",
        default=100.0,
    )

    # Distance Decay Settings (prevents grade extrapolation into empty space)
    use_distance_decay: BoolProperty(
        name="Use Distance Decay",
        description="Apply distance-based decay to prevent grade extrapolation far from samples. "
                    "Grades will diminish toward background value as distance from samples increases",
        default=False,
    )

    decay_distance: FloatProperty(
        name="Decay Distance",
        description="Distance (in scene units) beyond which grades decay to background. "
                    "This should be based on expected geological continuity",
        default=50.0,
        min=1.0,
        max=1000.0,
    )

    background_value: FloatProperty(
        name="Background Value",
        description="Grade value at infinite distance from samples (typically 0 or very low). "
                    "Interpolated values will decay toward this value",
        default=0.0,
        min=0.0,
        max=100.0,
    )

    decay_function: EnumProperty(
        name="Decay Function",
        description="Mathematical function controlling how grades diminish with distance",
        items=[
            ('linear', "Linear", "Linear decay: grade decreases proportionally with distance"),
            ('smooth', "Smooth (Smoothstep)", "Smooth S-curve decay: gradual near samples, faster at mid-range, gradual at edge (recommended)"),
            ('gaussian', "Gaussian", "Gaussian/bell curve decay: very gradual falloff, natural-looking"),
        ],
        default='smooth',
    )

    # Scale increment for +/- buttons
    scale_increment: FloatProperty(
        name="Scale Step",
        description="Amount to add/subtract when using +/- buttons",
        default=5.0,
        min=0.1,
        max=100.0,
    )


def get_element_items(self, context):
    """Get available elements from cached assay data."""
    elements = get_available_elements()
    if elements:
        return [(e, e, f"Interpolate {e} values") for e in sorted(elements)]
    else:
        return [("", "No elements available", "")]


# =============================================================================
# Operators
# =============================================================================

class GEODB_OT_CreateEllipsoidWidget(Operator):
    """Create an interactive ellipsoid widget for setting search parameters"""
    bl_idname = "geodb.create_ellipsoid_widget"
    bl_label = "Create Ellipsoid Widget"
    bl_description = "Create a 3D ellipsoid widget that you can rotate and scale to define the search volume"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not SCIPY_AVAILABLE:
            self.report({'ERROR'}, "scipy is required for RBF interpolation")
            return {'CANCELLED'}

        # Check if we have cached data
        cache = DrillDataCache.get_cache()
        if cache is None:
            self.report({'ERROR'}, "No drill data imported. Please import data first.")
            return {'CANCELLED'}

        elements = get_available_elements()
        if not elements:
            self.report({'ERROR'}, "No assay elements found in imported data.")
            return {'CANCELLED'}

        # Get sample positions to calculate centroid
        props = context.scene.geodb_ellipsoid_editor
        element = props.element if props.element else elements[0]

        try:
            positions, _ = extract_assay_data_from_cache(element)
            centroid = positions.mean(axis=0)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Calculate reasonable default radii based on data extent
        x_range = positions[:, 0].max() - positions[:, 0].min()
        y_range = positions[:, 1].max() - positions[:, 1].min()
        z_range = positions[:, 2].max() - positions[:, 2].min()
        avg_range = (x_range + y_range + z_range) / 3.0

        # Default ellipsoid: elongated along strike (X), medium down-dip (Y), narrow across (Z)
        default_major = avg_range * 0.3
        default_semi = avg_range * 0.2
        default_minor = avg_range * 0.1

        # Create ellipsoid
        ellipsoid = SearchEllipsoid(
            radius_major=default_major,
            radius_semi=default_semi,
            radius_minor=default_minor,
            azimuth=0.0,
            dip=0.0,
            plunge=0.0
        )

        # Delete existing widget if present
        if props.has_active_widget and props.active_widget_name:
            old_obj = bpy.data.objects.get(props.active_widget_name)
            if old_obj:
                bpy.data.objects.remove(old_obj, do_unlink=True)

        # Create the visualization
        widget_name = "RBF_Ellipsoid_Widget"
        obj = create_ellipsoid_visualization(
            ellipsoid,
            location=tuple(centroid),
            name=widget_name,
            wireframe=False,  # Solid for better visibility during editing
            color=(0.2, 0.6, 1.0, 0.25)  # Blue, semi-transparent
        )

        # Mark as editable widget
        obj['geodb_widget'] = True
        obj['geodb_widget_type'] = 'ellipsoid_editor'

        # Select the widget
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # Update properties
        props.has_active_widget = True
        props.active_widget_name = obj.name

        self.report({'INFO'}, f"Created ellipsoid widget at sample centroid. Use R to rotate, S to scale.")
        return {'FINISHED'}


class GEODB_OT_SelectEllipsoidWidget(Operator):
    """Select the active ellipsoid widget"""
    bl_idname = "geodb.select_ellipsoid_widget"
    bl_label = "Select Widget"
    bl_description = "Select the ellipsoid widget in the viewport"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        if not props.has_active_widget or not props.active_widget_name:
            self.report({'WARNING'}, "No active ellipsoid widget")
            return {'CANCELLED'}

        obj = bpy.data.objects.get(props.active_widget_name)
        if not obj:
            props.has_active_widget = False
            props.active_widget_name = ""
            self.report({'WARNING'}, "Widget no longer exists")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        return {'FINISHED'}


class GEODB_OT_DeleteEllipsoidWidget(Operator):
    """Delete the ellipsoid widget"""
    bl_idname = "geodb.delete_ellipsoid_widget"
    bl_label = "Delete Widget"
    bl_description = "Delete the ellipsoid widget from the scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        if props.active_widget_name:
            obj = bpy.data.objects.get(props.active_widget_name)
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)

        props.has_active_widget = False
        props.active_widget_name = ""

        self.report({'INFO'}, "Deleted ellipsoid widget")
        return {'FINISHED'}


class GEODB_OT_ResetEllipsoidWidget(Operator):
    """Reset the ellipsoid widget to default orientation"""
    bl_idname = "geodb.reset_ellipsoid_widget"
    bl_label = "Reset Orientation"
    bl_description = "Reset the ellipsoid rotation to zero (no rotation)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        if not props.has_active_widget or not props.active_widget_name:
            self.report({'WARNING'}, "No active ellipsoid widget")
            return {'CANCELLED'}

        obj = bpy.data.objects.get(props.active_widget_name)
        if not obj:
            self.report({'WARNING'}, "Widget no longer exists")
            return {'CANCELLED'}

        obj.rotation_euler = (0, 0, 0)
        self.report({'INFO'}, "Reset ellipsoid orientation")
        return {'FINISHED'}


class GEODB_OT_AdjustEllipsoidScale(Operator):
    """Adjust ellipsoid scale on a specific axis"""
    bl_idname = "geodb.adjust_ellipsoid_scale"
    bl_label = "Adjust Scale"
    bl_description = "Increment or decrement the ellipsoid scale on a specific axis"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(
        name="Axis",
        items=[
            ('X', "X (Major)", "Major axis - along strike"),
            ('Y', "Y (Semi)", "Semi axis - down dip"),
            ('Z', "Z (Minor)", "Minor axis - across strike"),
        ],
        default='X',
    )

    direction: EnumProperty(
        name="Direction",
        items=[
            ('INCREASE', "Increase", "Increase scale"),
            ('DECREASE', "Decrease", "Decrease scale"),
        ],
        default='INCREASE',
    )

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        if not props.has_active_widget or not props.active_widget_name:
            self.report({'WARNING'}, "No active ellipsoid widget")
            return {'CANCELLED'}

        obj = bpy.data.objects.get(props.active_widget_name)
        if not obj:
            self.report({'WARNING'}, "Widget no longer exists")
            return {'CANCELLED'}

        increment = props.scale_increment
        if self.direction == 'DECREASE':
            increment = -increment

        axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[self.axis]
        new_scale = list(obj.scale)
        new_scale[axis_idx] = max(1.0, new_scale[axis_idx] + increment)  # Minimum scale of 1
        obj.scale = new_scale

        return {'FINISHED'}


class GEODB_OT_ApplyEllipsoidInterpolation(Operator):
    """Apply RBF interpolation using the current ellipsoid settings"""
    bl_idname = "geodb.apply_ellipsoid_interpolation"
    bl_label = "Apply Interpolation"
    bl_description = "Run RBF interpolation using the current ellipsoid orientation and scale"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        if not SCIPY_AVAILABLE:
            self.report({'ERROR'}, "scipy is required for RBF interpolation")
            return {'CANCELLED'}

        if not props.element:
            self.report({'ERROR'}, "No element selected")
            return {'CANCELLED'}

        # Get ellipsoid parameters from widget
        if props.has_active_widget and props.active_widget_name:
            obj = bpy.data.objects.get(props.active_widget_name)
            if obj:
                ellipsoid = update_ellipsoid_from_object(obj)
                if ellipsoid is None:
                    # Fallback: read from object transforms directly
                    obj.rotation_mode = 'ZXY'
                    ellipsoid = SearchEllipsoid(
                        radius_major=obj.scale[0],
                        radius_semi=obj.scale[1],
                        radius_minor=obj.scale[2],
                        azimuth=math.degrees(obj.rotation_euler[2]),
                        dip=math.degrees(obj.rotation_euler[0]),
                        plunge=math.degrees(obj.rotation_euler[1])
                    )
            else:
                self.report({'ERROR'}, "Ellipsoid widget not found. Please create one first.")
                return {'CANCELLED'}
        else:
            self.report({'ERROR'}, "No ellipsoid widget. Please create one first.")
            return {'CANCELLED'}

        try:
            self.report({'INFO'}, f"Creating RBF interpolation for {props.element}...")

            # Get control points if enabled
            control_points = None
            if props.use_control_points and len(props.control_points) > 0:
                control_points = get_control_points_data(context)
                if control_points:
                    self.report({'INFO'}, f"Using {len(control_points)} control points as boundary constraints")

            # Run interpolation
            result_obj = interpolate_from_cache(
                element=props.element,
                kernel=props.kernel,
                epsilon=props.epsilon,
                smoothing=props.smoothing,
                resolution=props.grid_resolution,
                output_type=props.output_type,
                threshold_min=props.threshold_min if props.use_threshold else None,
                threshold_max=props.threshold_max if props.use_threshold else None,
                use_threshold=props.use_threshold,
                max_extrapolation_distance=ellipsoid,
                control_points=control_points,
                # Distance decay parameters (prevents grade extrapolation into empty space)
                use_distance_decay=props.use_distance_decay,
                decay_distance=props.decay_distance,
                background_value=props.background_value,
                decay_function=props.decay_function
            )

            self.report({'INFO'}, f"Created RBF interpolation: {result_obj.name}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Interpolation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class GEODB_OT_RecenterEllipsoidWidget(Operator):
    """Recenter the ellipsoid widget at the sample centroid"""
    bl_idname = "geodb.recenter_ellipsoid_widget"
    bl_label = "Recenter at Samples"
    bl_description = "Move the ellipsoid widget to the centroid of sample positions"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        if not props.has_active_widget or not props.active_widget_name:
            self.report({'WARNING'}, "No active ellipsoid widget")
            return {'CANCELLED'}

        obj = bpy.data.objects.get(props.active_widget_name)
        if not obj:
            self.report({'WARNING'}, "Widget no longer exists")
            return {'CANCELLED'}

        # Get element
        element = props.element
        if not element:
            elements = get_available_elements()
            if elements:
                element = elements[0]
            else:
                self.report({'ERROR'}, "No elements available")
                return {'CANCELLED'}

        try:
            positions, _ = extract_assay_data_from_cache(element)
            centroid = positions.mean(axis=0)
            obj.location = tuple(centroid)
            self.report({'INFO'}, f"Recentered at ({centroid[0]:.1f}, {centroid[1]:.1f}, {centroid[2]:.1f})")
            return {'FINISHED'}
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


# =============================================================================
# Control Point Operators
# =============================================================================

def create_control_point_marker(location: tuple, name: str, size: float = 2.0,
                                 color: tuple = (1.0, 0.3, 0.0, 0.8)) -> bpy.types.Object:
    """
    Create a visual marker for a control point.

    Args:
        location: (x, y, z) position
        name: Name for the object
        size: Visual size of the marker
        color: RGBA color tuple

    Returns:
        Created Blender object
    """
    # Create icosphere for the marker (looks like a control point)
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=size)

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    obj.location = Vector(location)

    # Add to scene
    bpy.context.collection.objects.link(obj)

    # Create material
    mat_name = f"{name}_Material"
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')

    bsdf_node.inputs['Base Color'].default_value = color[:3] + (1.0,)
    bsdf_node.inputs['Alpha'].default_value = color[3]
    bsdf_node.inputs['Emission Color'].default_value = color[:3] + (1.0,)
    bsdf_node.inputs['Emission Strength'].default_value = 0.5

    links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])

    output_node.location = (300, 0)
    bsdf_node.location = (0, 0)

    obj.data.materials.append(mat)

    # Tag as control point
    obj['geodb_control_point'] = True
    obj['geodb_type'] = 'rbf_control_point'

    return obj


class GEODB_OT_AddControlPoint(Operator):
    """Add a control point at the 3D cursor position"""
    bl_idname = "geodb.add_control_point"
    bl_label = "Add Control Point"
    bl_description = "Add a boundary constraint point at the 3D cursor. Use G to move it after creation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        # Get 3D cursor position
        cursor_loc = context.scene.cursor.location.copy()

        # Generate unique name
        index = len(props.control_points)
        name = f"RBF_ControlPoint_{index:03d}"

        # Ensure unique name
        while bpy.data.objects.get(name):
            index += 1
            name = f"RBF_ControlPoint_{index:03d}"

        # Create the marker
        obj = create_control_point_marker(
            location=tuple(cursor_loc),
            name=name,
            size=props.control_point_size,
            color=(1.0, 0.3, 0.0, 0.8)  # Orange for visibility
        )

        # Store the control point value on the object
        obj['control_point_value'] = props.control_point_value

        # Add to collection
        cp = props.control_points.add()
        cp.object_name = obj.name
        cp.value = props.control_point_value

        # Select the new control point
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # Update active index
        props.active_control_point_index = len(props.control_points) - 1

        self.report({'INFO'}, f"Added control point at cursor (value={props.control_point_value:.2f}). Use G to move.")
        return {'FINISHED'}


class GEODB_OT_DeleteControlPoint(Operator):
    """Delete the selected control point"""
    bl_idname = "geodb.delete_control_point"
    bl_label = "Delete Control Point"
    bl_description = "Delete the selected control point"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Index",
        description="Index of control point to delete",
        default=-1,
    )

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        # Determine which index to delete
        idx = self.index
        if idx < 0:
            idx = props.active_control_point_index

        if idx < 0 or idx >= len(props.control_points):
            self.report({'WARNING'}, "No control point selected")
            return {'CANCELLED'}

        # Get the control point
        cp = props.control_points[idx]

        # Delete the object
        obj = bpy.data.objects.get(cp.object_name)
        if obj:
            # Also delete the material
            if obj.data and obj.data.materials:
                for mat in obj.data.materials:
                    if mat:
                        bpy.data.materials.remove(mat)
            bpy.data.objects.remove(obj, do_unlink=True)

        # Remove from collection
        props.control_points.remove(idx)

        # Adjust active index
        if props.active_control_point_index >= len(props.control_points):
            props.active_control_point_index = max(0, len(props.control_points) - 1)

        self.report({'INFO'}, "Deleted control point")
        return {'FINISHED'}


class GEODB_OT_ClearControlPoints(Operator):
    """Clear all control points"""
    bl_idname = "geodb.clear_control_points"
    bl_label = "Clear All Control Points"
    bl_description = "Remove all control points from the scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        count = len(props.control_points)
        if count == 0:
            self.report({'INFO'}, "No control points to clear")
            return {'FINISHED'}

        # Delete all objects
        for cp in props.control_points:
            obj = bpy.data.objects.get(cp.object_name)
            if obj:
                if obj.data and obj.data.materials:
                    for mat in obj.data.materials:
                        if mat:
                            bpy.data.materials.remove(mat)
                bpy.data.objects.remove(obj, do_unlink=True)

        # Clear collection
        props.control_points.clear()
        props.active_control_point_index = 0

        self.report({'INFO'}, f"Cleared {count} control points")
        return {'FINISHED'}


class GEODB_OT_SelectControlPoint(Operator):
    """Select a control point in the viewport"""
    bl_idname = "geodb.select_control_point"
    bl_label = "Select Control Point"
    bl_description = "Select this control point in the 3D viewport"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Index",
        description="Index of control point to select",
        default=-1,
    )

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        idx = self.index
        if idx < 0:
            idx = props.active_control_point_index

        if idx < 0 or idx >= len(props.control_points):
            self.report({'WARNING'}, "Invalid control point index")
            return {'CANCELLED'}

        cp = props.control_points[idx]
        obj = bpy.data.objects.get(cp.object_name)

        if not obj:
            self.report({'WARNING'}, "Control point object not found")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        props.active_control_point_index = idx

        return {'FINISHED'}


class GEODB_OT_UpdateControlPointValue(Operator):
    """Update the value of a control point"""
    bl_idname = "geodb.update_control_point_value"
    bl_label = "Update Value"
    bl_description = "Update the constraint value for this control point"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Index",
        description="Index of control point to update",
        default=-1,
    )

    value: FloatProperty(
        name="Value",
        description="New constraint value",
        default=0.0,
    )

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        idx = self.index
        if idx < 0:
            idx = props.active_control_point_index

        if idx < 0 or idx >= len(props.control_points):
            self.report({'WARNING'}, "Invalid control point index")
            return {'CANCELLED'}

        cp = props.control_points[idx]
        cp.value = self.value

        # Also update on the object
        obj = bpy.data.objects.get(cp.object_name)
        if obj:
            obj['control_point_value'] = self.value

        self.report({'INFO'}, f"Updated control point value to {self.value:.2f}")
        return {'FINISHED'}


class GEODB_OT_SetValueFromThreshold(Operator):
    """Set control point value from the current threshold"""
    bl_idname = "geodb.set_cp_value_from_threshold"
    bl_label = "Use Threshold"
    bl_description = "Set the control point value to the current cutoff grade threshold"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb_ellipsoid_editor

        # Set to slightly below threshold to ensure it's outside the isosurface
        props.control_point_value = props.threshold_min * 0.5

        self.report({'INFO'}, f"Control point value set to {props.control_point_value:.4f} (below threshold)")
        return {'FINISHED'}


class GEODB_OT_AutoSetInterpolationDefaults(Operator):
    """Analyze drill data and automatically set reasonable interpolation defaults"""
    bl_idname = "geodb.auto_set_interpolation_defaults"
    bl_label = "Auto-Set Defaults"
    bl_description = (
        "Analyze the available drill data and automatically configure interpolation "
        "settings for a reasonable initial result. Settings are based on data statistics "
        "and spatial distribution of samples"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        import numpy as np

        props = context.scene.geodb_ellipsoid_editor

        # Check if we have data
        cache = DrillDataCache.get_cache()
        if cache is None:
            self.report({'ERROR'}, "No drill data imported. Please import data first.")
            return {'CANCELLED'}

        # Get the selected element
        element = props.element
        if not element:
            elements = get_available_elements()
            if elements:
                element = elements[0]
            else:
                self.report({'ERROR'}, "No elements available in the data.")
                return {'CANCELLED'}

        # Extract assay data for analysis
        try:
            positions, values = extract_assay_data_from_cache(element)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Calculate data statistics
        n_samples = len(values)
        val_min = float(np.min(values))
        val_max = float(np.max(values))
        val_mean = float(np.mean(values))
        val_median = float(np.median(values))
        val_std = float(np.std(values))

        # Calculate percentiles for threshold suggestion
        p25 = float(np.percentile(values, 25))
        p50 = float(np.percentile(values, 50))
        p75 = float(np.percentile(values, 75))
        p90 = float(np.percentile(values, 90))

        # Calculate spatial statistics
        x_range = positions[:, 0].max() - positions[:, 0].min()
        y_range = positions[:, 1].max() - positions[:, 1].min()
        z_range = positions[:, 2].max() - positions[:, 2].min()
        avg_range = (x_range + y_range + z_range) / 3.0

        # Calculate average sample spacing using nearest neighbors
        try:
            from scipy.spatial import cKDTree
            tree = cKDTree(positions)
            distances, _ = tree.query(positions, k=2)
            avg_spacing = float(np.mean(distances[:, 1]))
            median_spacing = float(np.median(distances[:, 1]))
        except ImportError:
            # Fallback if scipy not available
            avg_spacing = avg_range / (n_samples ** (1/3))
            median_spacing = avg_spacing

        # =====================================================================
        # Set reasonable defaults based on data analysis
        # =====================================================================

        # 1. Kernel: thin_plate_spline is robust for geological data
        props.kernel = 'thin_plate_spline'

        # 2. Epsilon: Scale based on data extent (affects some kernels)
        #    For thin_plate_spline this is ignored, but set a reasonable value
        props.epsilon = max(1.0, avg_spacing / 10.0)

        # 3. Smoothing: Slight smoothing helps with noisy assay data
        #    Higher smoothing for more variable data
        cv = val_std / val_mean if val_mean > 0 else 1.0  # Coefficient of variation
        if cv > 2.0:
            props.smoothing = 0.5  # High variability, more smoothing
        elif cv > 1.0:
            props.smoothing = 0.2  # Moderate variability
        else:
            props.smoothing = 0.0  # Low variability, exact interpolation

        # 4. Grid Resolution: Based on data extent and sample count
        #    Higher resolution for denser data, but cap at practical limits
        # Target ~10-20 samples per grid cell on average
        ideal_cells = max(20, n_samples / 15)
        ideal_resolution = int(ideal_cells ** (1/3))
        props.grid_resolution = max(30, min(100, ideal_resolution))

        # 5. Output Type: Mesh is most useful
        props.output_type = 'MESH'

        # 6. Thresholds: Based on data distribution
        props.use_threshold = True

        # Cutoff grade: Use median or P25, whichever gives a reasonable shell
        # For most mineral deposits, P25-P50 is a good starting cutoff
        # If data is highly skewed (common for Au), use a lower percentile
        skewness = (val_mean - val_median) / val_std if val_std > 0 else 0
        if skewness > 1.0:
            # Highly right-skewed (e.g., gold) - use lower percentile
            props.threshold_min = max(val_min, p25)
        else:
            # More symmetric distribution - use median
            props.threshold_min = max(val_min, p50)

        # Max threshold: Use P90 or max, to exclude outliers
        props.threshold_max = min(val_max, p90 * 1.5)

        # 7. Distance Decay: Enable for cleaner results
        props.use_distance_decay = True

        # Decay distance: 2-3x average sample spacing is typical
        props.decay_distance = avg_spacing * 2.5

        # Background value: Use 0 or detection limit approximation
        props.background_value = 0.0

        # Decay function: Smooth is most geologically realistic
        props.decay_function = 'smooth'

        # 8. Control points: Keep existing setting
        # (user may have already set up control points)

        # Report the settings
        self.report(
            {'INFO'},
            f"Auto-configured for {element}: {n_samples} samples, "
            f"cutoff={props.threshold_min:.4f}, resolution={props.grid_resolution}"
        )

        # Print detailed analysis to console
        print(f"\n{'='*60}")
        print(f"AUTO-CONFIGURATION ANALYSIS: {element}")
        print(f"{'='*60}")
        print(f"\nDATA STATISTICS:")
        print(f"  Sample count: {n_samples}")
        print(f"  Value range: {val_min:.4f} to {val_max:.4f}")
        print(f"  Mean: {val_mean:.4f}, Median: {val_median:.4f}, Std: {val_std:.4f}")
        print(f"  Percentiles: P25={p25:.4f}, P50={p50:.4f}, P75={p75:.4f}, P90={p90:.4f}")
        print(f"  Skewness indicator: {skewness:.2f}")
        print(f"\nSPATIAL STATISTICS:")
        print(f"  X range: {x_range:.1f}")
        print(f"  Y range: {y_range:.1f}")
        print(f"  Z range: {z_range:.1f}")
        print(f"  Average sample spacing: {avg_spacing:.1f}")
        print(f"  Median sample spacing: {median_spacing:.1f}")
        print(f"\nCONFIGURED SETTINGS:")
        print(f"  Kernel: {props.kernel}")
        print(f"  Epsilon: {props.epsilon:.2f}")
        print(f"  Smoothing: {props.smoothing:.2f}")
        print(f"  Grid Resolution: {props.grid_resolution}")
        print(f"  Cutoff Grade: {props.threshold_min:.4f}")
        print(f"  Max Threshold: {props.threshold_max:.4f}")
        print(f"  Distance Decay: enabled")
        print(f"  Decay Distance: {props.decay_distance:.1f}")
        print(f"  Decay Function: {props.decay_function}")
        print(f"{'='*60}\n")

        return {'FINISHED'}


def get_control_points_data(context) -> list:
    """
    Extract control point positions and values for interpolation.

    Returns:
        List of tuples: [(x, y, z, value), ...]
    """
    props = context.scene.geodb_ellipsoid_editor
    data = []

    for cp in props.control_points:
        obj = bpy.data.objects.get(cp.object_name)
        if obj:
            # Get current position (user may have moved it)
            pos = obj.location
            # Get value from property or object
            value = cp.value
            if 'control_point_value' in obj:
                value = obj['control_point_value']
            data.append((pos.x, pos.y, pos.z, value))

    return data


# =============================================================================
# Panel
# =============================================================================

class GEODB_PT_EllipsoidEditorPanel(Panel):
    """Panel for interactive ellipsoid editing and RBF interpolation"""
    bl_label = "Implicit Surfaces"
    bl_idname = "GEODB_PT_ellipsoid_editor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # Only show if scipy is available
        return SCIPY_AVAILABLE

    def draw(self, context):
        layout = self.layout
        props = context.scene.geodb_ellipsoid_editor

        # Check if we have data
        cache = DrillDataCache.get_cache()
        has_data = cache is not None and cache.get('samples')

        if not has_data:
            box = layout.box()
            box.label(text="No drill data imported", icon='INFO')
            box.label(text="Import data first to use")
            box.label(text="the ellipsoid editor.")
            return

        # =================================================================
        # Widget Controls
        # =================================================================
        box = layout.box()
        box.label(text="Search Ellipsoid Widget", icon='MESH_UVSPHERE')

        if not props.has_active_widget or not props.active_widget_name:
            # No widget - show create button
            box.operator("geodb.create_ellipsoid_widget", icon='ADD', text="Create Ellipsoid Widget")
            box.label(text="Create a 3D widget to visually")
            box.label(text="define the search ellipsoid.")
        else:
            # Widget exists - check if it still exists in scene
            widget_obj = bpy.data.objects.get(props.active_widget_name)
            if not widget_obj:
                # Widget was deleted externally
                props.has_active_widget = False
                props.active_widget_name = ""
                box.operator("geodb.create_ellipsoid_widget", icon='ADD', text="Create Ellipsoid Widget")
            else:
                # Widget exists - show controls
                row = box.row(align=True)
                row.operator("geodb.select_ellipsoid_widget", icon='RESTRICT_SELECT_OFF', text="Select")
                row.operator("geodb.recenter_ellipsoid_widget", icon='PIVOT_CURSOR', text="Recenter")
                row.operator("geodb.delete_ellipsoid_widget", icon='X', text="")

                box.separator()

                # =============================================================
                # Live Transform Display
                # =============================================================
                # Note: rotation_mode is set when the widget is created
                # We read it here but can't modify in draw()

                # Scale (Radii)
                scale_box = box.box()
                scale_box.label(text="Scale (Search Radii)", icon='FULLSCREEN_ENTER')

                # Scale increment setting
                row = scale_box.row()
                row.prop(props, "scale_increment", text="Step")

                # Major axis (X)
                row = scale_box.row(align=True)
                row.label(text=f"Major (X):")
                row.label(text=f"{widget_obj.scale[0]:.1f}")
                op = row.operator("geodb.adjust_ellipsoid_scale", icon='REMOVE', text="")
                op.axis = 'X'
                op.direction = 'DECREASE'
                op = row.operator("geodb.adjust_ellipsoid_scale", icon='ADD', text="")
                op.axis = 'X'
                op.direction = 'INCREASE'

                # Semi axis (Y)
                row = scale_box.row(align=True)
                row.label(text=f"Semi (Y):")
                row.label(text=f"{widget_obj.scale[1]:.1f}")
                op = row.operator("geodb.adjust_ellipsoid_scale", icon='REMOVE', text="")
                op.axis = 'Y'
                op.direction = 'DECREASE'
                op = row.operator("geodb.adjust_ellipsoid_scale", icon='ADD', text="")
                op.axis = 'Y'
                op.direction = 'INCREASE'

                # Minor axis (Z)
                row = scale_box.row(align=True)
                row.label(text=f"Minor (Z):")
                row.label(text=f"{widget_obj.scale[2]:.1f}")
                op = row.operator("geodb.adjust_ellipsoid_scale", icon='REMOVE', text="")
                op.axis = 'Z'
                op.direction = 'DECREASE'
                op = row.operator("geodb.adjust_ellipsoid_scale", icon='ADD', text="")
                op.axis = 'Z'
                op.direction = 'INCREASE'

                # Rotation (Live Display)
                rot_box = box.box()
                rot_box.label(text="Rotation (Orientation)", icon='ORIENTATION_GIMBAL')

                col = rot_box.column(align=True)

                # Get rotation values - we expect ZXY mode for geological convention
                # Z = azimuth, X = dip, Y = plunge
                rot = widget_obj.rotation_euler
                azimuth = math.degrees(rot[2])
                dip = math.degrees(rot[0])
                plunge = math.degrees(rot[1])

                # Normalize azimuth to 0-360
                azimuth = azimuth % 360

                col.label(text=f"Azimuth (Z):  {azimuth:.1f}°")
                col.label(text=f"Dip (X):      {dip:.1f}°")
                col.label(text=f"Plunge (Y):   {plunge:.1f}°")

                # Show warning if rotation mode was changed
                if widget_obj.rotation_mode != 'ZXY':
                    col.label(text=f"Mode: {widget_obj.rotation_mode} (expected ZXY)", icon='ERROR')

                row = rot_box.row()
                row.operator("geodb.reset_ellipsoid_widget", icon='LOOP_BACK', text="Reset Rotation")

                # Tip for user
                tip_box = box.box()
                tip_box.label(text="Tip: Use R to rotate, S to scale", icon='INFO')
                tip_box.label(text="in the 3D viewport.")

        # =================================================================
        # RBF Settings
        # =================================================================
        layout.separator()
        box = layout.box()
        box.label(text="RBF Interpolation Settings", icon='PREFERENCES')

        # Element selection
        box.prop(props, "element")

        # Auto-set defaults button
        row = box.row()
        row.operator("geodb.auto_set_interpolation_defaults", icon='AUTO')

        # Kernel and parameters
        col = box.column(align=True)
        col.prop(props, "kernel")
        col.prop(props, "epsilon")
        col.prop(props, "smoothing")
        col.prop(props, "grid_resolution")

        # Output type
        box.separator()
        box.prop(props, "output_type")

        # Threshold settings
        box.prop(props, "use_threshold")
        if props.use_threshold:
            col = box.column(align=True)
            col.prop(props, "threshold_min", text="Cutoff Grade")
            col.prop(props, "threshold_max", text="Max Value")

        # =================================================================
        # Grade Decay Section (prevents extrapolation into empty space)
        # =================================================================
        layout.separator()
        decay_box = layout.box()
        row = decay_box.row()
        row.label(text="Grade Decay", icon='MOD_SMOOTH')
        row.prop(props, "use_distance_decay", text="")

        if props.use_distance_decay:
            col = decay_box.column(align=True)
            col.prop(props, "decay_distance")
            col.prop(props, "background_value")
            col.prop(props, "decay_function")

            # Help text
            help_box = decay_box.box()
            help_box.label(text="Grades diminish toward background", icon='INFO')
            help_box.label(text="as distance from samples increases.")
            help_box.label(text="Prevents high-grade extrapolation")
            help_box.label(text="into unmeasured areas.")

        # =================================================================
        # Control Points Section
        # =================================================================
        layout.separator()
        box = layout.box()
        row = box.row()
        row.label(text="Control Points", icon='PIVOT_CURSOR')
        row.prop(props, "use_control_points", text="")

        if props.use_control_points:
            # Add control point button
            row = box.row(align=True)
            row.operator("geodb.add_control_point", icon='ADD', text="Add at Cursor")
            row.operator("geodb.clear_control_points", icon='X', text="Clear All")

            # Control point value setting
            col = box.column(align=True)
            row = col.row(align=True)
            row.prop(props, "control_point_value", text="Value")
            row.operator("geodb.set_cp_value_from_threshold", icon='EYEDROPPER', text="")

            col.prop(props, "control_point_size", text="Marker Size")

            # List existing control points
            num_points = len(props.control_points)
            if num_points > 0:
                list_box = box.box()
                list_box.label(text=f"Active Points ({num_points}):", icon='OUTLINER_OB_EMPTY')

                # Show control points with their values and positions
                for idx, cp in enumerate(props.control_points):
                    obj = bpy.data.objects.get(cp.object_name)
                    if obj:
                        row = list_box.row(align=True)

                        # Highlight if selected
                        if idx == props.active_control_point_index:
                            row.alert = True

                        # Select button
                        op = row.operator("geodb.select_control_point", icon='RESTRICT_SELECT_OFF', text="")
                        op.index = idx

                        # Show position and value
                        pos = obj.location
                        row.label(text=f"({pos.x:.0f}, {pos.y:.0f}, {pos.z:.0f})")
                        row.label(text=f"v={cp.value:.2f}")

                        # Delete button
                        op = row.operator("geodb.delete_control_point", icon='X', text="")
                        op.index = idx

                # Tip
                tip_box = box.box()
                tip_box.label(text="Tip: Select point, then G to move", icon='INFO')
                tip_box.label(text="Points constrain RBF boundaries")
            else:
                box.label(text="No control points. Click 'Add at Cursor'")
                box.label(text="to place boundary constraints.")

        # =================================================================
        # Apply Button
        # =================================================================
        layout.separator()

        # Only enable if widget exists
        col = layout.column()
        col.enabled = props.has_active_widget and props.active_widget_name != ""
        col.scale_y = 1.5
        col.operator("geodb.apply_ellipsoid_interpolation", icon='PLAY', text="Apply Interpolation")

        if not props.has_active_widget:
            layout.label(text="Create an ellipsoid widget first", icon='ERROR')


# =============================================================================
# Registration
# =============================================================================

classes = (
    # Property groups must be registered first (GeoDBControlPointItem before GeoDBEllipsoidEditorProperties)
    GeoDBControlPointItem,
    GeoDBEllipsoidEditorProperties,
    # Ellipsoid operators
    GEODB_OT_CreateEllipsoidWidget,
    GEODB_OT_SelectEllipsoidWidget,
    GEODB_OT_DeleteEllipsoidWidget,
    GEODB_OT_ResetEllipsoidWidget,
    GEODB_OT_AdjustEllipsoidScale,
    GEODB_OT_RecenterEllipsoidWidget,
    GEODB_OT_ApplyEllipsoidInterpolation,
    # Control point operators
    GEODB_OT_AddControlPoint,
    GEODB_OT_DeleteControlPoint,
    GEODB_OT_ClearControlPoints,
    GEODB_OT_SelectControlPoint,
    GEODB_OT_UpdateControlPointValue,
    GEODB_OT_SetValueFromThreshold,
    # Auto-configuration operator
    GEODB_OT_AutoSetInterpolationDefaults,
    # Panel
    GEODB_PT_EllipsoidEditorPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register property group
    bpy.types.Scene.geodb_ellipsoid_editor = PointerProperty(type=GeoDBEllipsoidEditorProperties)


def unregister():
    # Unregister property group
    if hasattr(bpy.types.Scene, 'geodb_ellipsoid_editor'):
        del bpy.types.Scene.geodb_ellipsoid_editor

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
