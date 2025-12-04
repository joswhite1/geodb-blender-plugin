"""
****************************************************************************
*                             DEPRECATED                                   *
****************************************************************************
* This file is no longer used and has been deprecated.                    *
*                                                                          *
* All functionality has been consolidated into:                           *
*   drill_visualization_panel.py                                          *
*                                                                          *
* This file is kept for reference only and should NOT be imported or used.*
* Do not modify this code - refer to drill_visualization_panel.py instead.*
****************************************************************************

Assay visualization panel for the geoDB Blender add-on.

This module provides UI and operators for visualizing drill sample assay data
as curved tubes along desurveyed drill hole paths, colored by AssayRangeConfiguration.
"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import EnumProperty, FloatProperty, IntProperty, StringProperty

from ..api.data import GeoDBData
from ..utils.interval_visualization import (
    create_interval_tube,
    apply_material_to_interval
)
from ..utils.object_properties import GeoDBObjectProperties


def get_assay_configs_enum(self, context):
    """Dynamic enum callback for assay range configurations"""
    items = []

    scene = context.scene
    if not hasattr(scene, 'geodb') or not scene.geodb.selected_project_id:
        return [('0', 'No Project Selected', 'Select a project first', 0)]

    try:
        project_id = int(scene.geodb.selected_project_id)
        success, configs = GeoDBData.get_assay_range_configurations(project_id)

        if success and configs:
            for idx, config in enumerate(configs):
                config_id = str(config.get('id', idx))
                element = config.get('element', 'Unknown')
                name = config.get('name', f'Config {idx + 1}')
                display_name = f"{element} - {name}"
                items.append((config_id, display_name, f'Visualize {display_name}', idx))
        else:
            return [('0', 'No Configs Available', 'No assay configurations found', 0)]
    except Exception as e:
        print(f"Error fetching assay configs: {e}")
        return [('0', 'Error Loading Configs', str(e), 0)]

    if not items:
        return [('0', 'No Configs Available', 'No assay configurations found', 0)]

    return items


def hex_to_rgba(hex_color):
    """Convert hex color string to RGBA tuple (0-1 range)."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return (r, g, b, 1.0)
    return (0.5, 0.5, 0.5, 1.0)


def get_color_for_assay_value(value, ranges, default_color='#CCCCCC'):
    """Get color for an assay value based on range configuration.

    Args:
        value: Assay value to color
        ranges: List of range dicts with from_value, to_value, color
        default_color: Hex color if value doesn't match any range

    Returns:
        RGBA tuple (0-1 range)
    """
    for range_item in ranges:
        from_val = float(range_item.get('from_value', 0))
        to_val = float(range_item.get('to_value', float('inf')))

        if from_val <= value < to_val:
            hex_color = range_item.get('color', default_color)
            return hex_to_rgba(hex_color)

    return hex_to_rgba(default_color)


class GEODB_OT_LoadAssayConfig(Operator):
    """Load and display an AssayRangeConfiguration for review"""
    bl_idname = "geodb.load_assay_config"
    bl_label = "Load Configuration"
    bl_description = "Load and display the selected assay configuration details"
    bl_options = {'REGISTER', 'UNDO'}

    config_selection: EnumProperty(
        name="Assay Configuration",
        description="Select assay range configuration to load",
        items=get_assay_configs_enum
    )

    def invoke(self, context, event):
        """Show dialog to select configuration"""
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        """Draw the configuration selection dialog"""
        layout = self.layout
        layout.prop(self, "config_selection")

    def execute(self, context):
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        project_id = int(props.selected_project_id)

        # Get selected config
        selected_config_id = int(self.config_selection)
        if selected_config_id <= 0:
            self.report({'ERROR'}, "Please select a valid assay configuration")
            return {'CANCELLED'}

        # Fetch config details
        self.report({'INFO'}, "Fetching assay configuration...")
        success, configs = GeoDBData.get_assay_range_configurations(project_id)
        if not success or not configs:
            self.report({'ERROR'}, "Failed to fetch assay configurations")
            return {'CANCELLED'}

        config = next((c for c in configs if c.get('id') == selected_config_id), None)
        if not config:
            self.report({'ERROR'}, f"Configuration ID {selected_config_id} not found")
            return {'CANCELLED'}

        # Store selected config in scene properties
        props.selected_assay_config_id = selected_config_id
        props.selected_assay_config_name = config.get('name', 'Assay')
        props.selected_assay_element = config.get('element', 'Unknown')
        props.selected_assay_units = config.get('units', '')
        props.selected_assay_default_color = config.get('default_color', '#CCCCCC')

        # Store ranges as JSON string for display
        import json
        ranges = config.get('ranges', [])
        props.selected_assay_ranges = json.dumps(ranges)

        self.report({'INFO'}, f"Loaded config: {props.selected_assay_element} - {props.selected_assay_config_name}")
        return {'FINISHED'}


class GEODB_OT_VisualizeAssays(Operator):
    """Visualize assay intervals using the loaded configuration"""
    bl_idname = "geodb.visualize_assays"
    bl_label = "Visualize Assays"
    bl_description = "Create curved tube visualization of assay intervals along drill holes"
    bl_options = {'REGISTER', 'UNDO'}

    tube_radius: FloatProperty(
        name="Tube Radius",
        description="Radius of the assay tubes",
        default=0.1,
        min=0.01,
        max=2.0
    )

    tube_resolution: IntProperty(
        name="Tube Resolution",
        description="Number of vertices around tube circumference",
        default=8,
        min=3,
        max=32
    )

    def execute(self, context):
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        if not hasattr(props, 'selected_assay_config_id') or props.selected_assay_config_id <= 0:
            self.report({'ERROR'}, "No assay configuration loaded. Please load a configuration first.")
            return {'CANCELLED'}

        project_id = int(props.selected_project_id)
        selected_config_id = props.selected_assay_config_id

        print(f"\n=== ASSAY VISUALIZATION DEBUG ===")
        print(f"Project ID: {project_id}")
        print(f"Selected Config ID from props: {selected_config_id}")
        print(f"Type of selected_config_id: {type(selected_config_id)}")
        print("=" * 80)

        # Fetch config details again to get fresh data
        self.report({'INFO'}, "Fetching assay configuration...")
        success, configs = GeoDBData.get_assay_range_configurations(project_id)
        if not success or not configs:
            self.report({'ERROR'}, "Failed to fetch assay configurations")
            return {'CANCELLED'}

        config = next((c for c in configs if c.get('id') == selected_config_id), None)
        if not config:
            self.report({'ERROR'}, f"Configuration ID {selected_config_id} not found")
            return {'CANCELLED'}

        config_name = config.get('name', 'Assay')
        element = config.get('element', 'Unknown')
        ranges = config.get('ranges', [])
        default_color = config.get('default_color', '#CCCCCC')

        self.report({'INFO'}, f"Using config: {element} - {config_name}")

        # Fetch drill collars
        self.report({'INFO'}, "Fetching drill collars...")
        success, collars = GeoDBData.get_drill_holes(project_id)
        if not success or not collars:
            self.report({'ERROR'}, "Failed to fetch drill collars")
            return {'CANCELLED'}

        # Fetch samples with assay data (this is the slow part)
        # v1.4: Pass assay_config_id so server applies the configuration
        self.report({'INFO'}, "Fetching sample data (this may take a while)...")
        success, samples_by_hole = GeoDBData.get_all_samples_for_project(project_id, assay_config_id=selected_config_id)
        if not success:
            self.report({'ERROR'}, "Failed to fetch sample data")
            return {'CANCELLED'}

        if not samples_by_hole:
            self.report({'WARNING'}, "No sample data available")
            return {'CANCELLED'}

        # Fetch drill traces
        self.report({'INFO'}, "Fetching drill traces...")
        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)
        if not success:
            self.report({'ERROR'}, "Failed to fetch drill traces")
            return {'CANCELLED'}

        # Create main collection
        main_collection_name = f"Assays_{element}_{config_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            # Clear existing objects
            for obj in main_collection.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        total_intervals = 0
        hole_collections = {}

        # Build ID-to-name mapping for collars
        collar_name_by_id = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_name_by_id[hole_id] = hole_name

        # Process each drill hole
        for hole_id, hole_samples in samples_by_hole.items():
            if not hole_samples:
                continue

            hole_name = collar_name_by_id.get(hole_id, f"Hole_{hole_id}")

            # Get trace for this hole
            trace_summary = traces_by_hole.get(hole_id)
            if not trace_summary:
                print(f"WARNING: No trace found for hole {hole_name}")
                continue

            # Fetch full trace detail
            trace_id = trace_summary.get('id')
            success, trace_data = GeoDBData.get_drill_trace_detail(trace_id)
            if not success or not trace_data:
                print(f"WARNING: Failed to fetch trace detail for {hole_name}")
                continue

            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                print(f"WARNING: Empty trace data for {hole_name}")
                continue

            # Create hole collection
            if hole_name not in hole_collections:
                hole_collection = bpy.data.collections.new(hole_name)
                main_collection.children.link(hole_collection)
                hole_collections[hole_name] = hole_collection
            else:
                hole_collection = hole_collections[hole_name]

            # Process each sample
            for sample in hole_samples:
                depth_from = sample.get('from_depth')
                depth_to = sample.get('to_depth')

                if depth_from is None or depth_to is None:
                    continue

                # Extract assay value for this element
                assay_obj = sample.get('assay', {})
                elements = assay_obj.get('elements', []) if isinstance(assay_obj, dict) else []

                assay_value = None
                for elem in elements:
                    if elem.get('element') == element:
                        try:
                            assay_value = float(elem.get('value', 0))
                        except (ValueError, TypeError):
                            assay_value = None
                        break

                if assay_value is None:
                    continue

                # Create tube for this interval
                tube_name = f"{hole_name}_{depth_from:.1f}-{depth_to:.1f}m_{element}_{assay_value:.3f}"

                tube_obj = create_interval_tube(
                    trace_depths=trace_depths,
                    trace_coords=trace_coords,
                    depth_from=depth_from,
                    depth_to=depth_to,
                    radius=self.tube_radius,
                    resolution=self.tube_resolution,
                    name=tube_name
                )

                if tube_obj:
                    # Link to hole collection
                    hole_collection.objects.link(tube_obj)

                    # Apply color based on assay value
                    color = get_color_for_assay_value(assay_value, ranges, default_color)
                    apply_material_to_interval(tube_obj, color)

                    # Tag with metadata
                    interval_props = {
                        'geodb_type': 'assay_interval',
                        'hole_name': hole_name,
                        'hole_id': hole_id,
                        'config_id': selected_config_id,
                        'config_name': config_name,
                        'element': element,
                        'assay_value': assay_value,
                        'depth_from': depth_from,
                        'depth_to': depth_to,
                        'sample_id': sample.get('id'),
                    }

                    for key, value in interval_props.items():
                        tube_obj[key] = value

                    total_intervals += 1

        self.report({'INFO'}, f"Created {total_intervals} assay intervals in {len(hole_collections)} holes")
        return {'FINISHED'}


class GEODB_PT_AssayVisualizationPanel(Panel):
    """Panel for assay visualization"""
    bl_label = "Assay Visualization"
    bl_idname = "GEODB_PT_assay_visualization"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            layout.label(text="Please select a project", icon='INFO')
            return

        # Step 1: Load Configuration
        box = layout.box()
        box.label(text="1. Select Configuration", icon='PRESET')

        # Show available configs info
        try:
            project_id = int(props.selected_project_id)
            success, assay_configs = GeoDBData.get_assay_range_configurations(project_id)
            if success and assay_configs:
                box.label(text=f"Available configs: {len(assay_configs)}", icon='INFO')
        except:
            pass

        row = box.row()
        row.operator("geodb.load_assay_config", text="Load Configuration", icon='IMPORT')

        # Step 2: Review Configuration (only show if config is loaded)
        if hasattr(props, 'selected_assay_config_id') and props.selected_assay_config_id > 0:
            box = layout.box()
            box.label(text="2. Review Configuration", icon='VIEWZOOM')

            # Configuration details header
            col = box.column(align=True)
            col.label(text=f"Element: {props.selected_assay_element}", icon='ATOM')
            col.label(text=f"Config: {props.selected_assay_config_name}", icon='PRESET')

            # Units and default color
            if hasattr(props, 'selected_assay_units') and props.selected_assay_units:
                col.label(text=f"Units: {props.selected_assay_units}", icon='FONT_DATA')
            if hasattr(props, 'selected_assay_default_color'):
                col.label(text=f"Default: {props.selected_assay_default_color}", icon='NODE_MATERIAL')

            # Display ranges with color boxes
            if hasattr(props, 'selected_assay_ranges') and props.selected_assay_ranges:
                try:
                    import json
                    ranges = json.loads(props.selected_assay_ranges)

                    box.separator()
                    box.label(text=f"Color Ranges ({len(ranges)} ranges):", icon='COLOR')

                    # Get units for display
                    units = props.selected_assay_units if hasattr(props, 'selected_assay_units') else ''

                    # Table header
                    header_split = box.split(factor=0.2, align=True)
                    header_split.label(text="From", icon='TRIA_RIGHT')
                    header_split = header_split.split(factor=0.25, align=True)
                    header_split.label(text="To", icon='TRIA_RIGHT')
                    header_split = header_split.split(factor=0.4, align=True)
                    header_split.label(text="Label", icon='BOOKMARKS')
                    header_split.label(text="Color", icon='COLOR')

                    box.separator()

                    # Show all ranges with color visualization
                    for i, range_item in enumerate(ranges):
                        from_val = range_item.get('from_value', 0)
                        to_val = range_item.get('to_value')
                        label = range_item.get('label', f'Range {i+1}')
                        hex_color = range_item.get('color', '#CCCCCC')

                        # Convert to_value to string, handling infinity
                        if to_val is None or to_val == float('inf') or to_val > 1e15:
                            to_val_str = "∞"
                        else:
                            to_val_str = f"{to_val}"

                        # Create row for this range
                        range_split = box.split(factor=0.2, align=True)

                        # From value with units
                        range_split.label(text=f"{from_val} {units}")

                        range_split = range_split.split(factor=0.25, align=True)
                        # To value with units
                        range_split.label(text=f"{to_val_str}" if to_val_str == "∞" else f"{to_val_str} {units}")

                        range_split = range_split.split(factor=0.4, align=True)
                        # Label
                        range_split.label(text=label)

                        # Color hex code with visual indicator
                        color_row = range_split.row(align=True)

                        # Show a colored box (using label with colored background effect)
                        # We'll use alert/emboss to give visual feedback
                        color_label = color_row.label(text=hex_color)

                except Exception as e:
                    box.label(text=f"Error displaying ranges: {e}", icon='ERROR')
                    import traceback
                    traceback.print_exc()

            # Step 3: Visualize
            box = layout.box()
            box.label(text="3. Visualize", icon='MESH_DATA')
            row = box.row()
            row.scale_y = 1.5
            row.operator("geodb.visualize_assays", text="Create Visualization", icon='COLOR')

            info_col = box.column(align=True)
            info_col.label(text="This will fetch sample data", icon='INFO')
            info_col.label(text="and may take some time", icon='TIME')


# Registration
classes = (
    GEODB_OT_LoadAssayConfig,
    GEODB_OT_VisualizeAssays,
    GEODB_PT_AssayVisualizationPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
