"""
Comprehensive Drill Visualization Panel for the geoDB Blender add-on.

This module implements visualization workflows for:
- Assay visualization with color ranges based on AssayRangeConfiguration
- Lithology visualization with interval tubes
- Alteration visualization with interval tubes
- Modal-based configuration selection
- Progressive disclosure UI pattern
- Hierarchical collection organization
"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import EnumProperty, FloatProperty, IntProperty

from ..api.data import GeoDBData
from ..core.data_cache import DrillDataCache
from ..core.config_cache import ConfigCache
from ..utils.interval_visualization import (
    create_interval_tube,
    apply_material_to_interval
)
from ..utils.cylinder_mesh import create_sample_cylinder_mesh, hex_to_rgb
from ..utils.object_properties import GeoDBObjectProperties


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def adjust_view_to_objects(context, objects):
    """
    Adjust the 3D viewport to frame the given objects.
    Sets orthographic view, clip end to 10000, and frames the objects.

    Args:
        context: Blender context
        objects: List of Blender objects to frame
    """
    if not objects:
        return

    # Check if auto-adjust is enabled
    if not context.scene.geodb.auto_adjust_view:
        return

    from mathutils import Vector, Euler
    import math

    # Calculate bounding box of all objects
    all_corners = []
    for obj in objects:
        if obj.type == 'MESH' and obj.data:
            all_corners.extend([obj.matrix_world @ Vector(corner) for corner in obj.bound_box])

    if not all_corners:
        return

    # Calculate center and size
    min_coord = Vector((min(c[i] for c in all_corners) for i in range(3)))
    max_coord = Vector((max(c[i] for c in all_corners) for i in range(3)))
    center = (min_coord + max_coord) / 2
    size = (max_coord - min_coord).length

    if size == 0:
        size = 100  # Default size if objects have no volume

    # Find and configure the 3D viewport
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces.active
            region_3d = space.region_3d

            # 1. Set to orthographic view
            region_3d.view_perspective = 'ORTHO'

            # 2. Set clip end to 50000
            space.clip_end = 50000

            # 3. Set view rotation (60 degrees down, 45 degrees rotated - nice 3/4 view)
            region_3d.view_rotation = Euler(
                (math.radians(60), 0, math.radians(45))
            ).to_quaternion()

            # 4. Set view location and distance
            region_3d.view_location = center
            region_3d.view_distance = size * 1.5

            break


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
    """Get color for an assay value based on range configuration."""
    for range_item in ranges:
        from_val = float(range_item.get('from_value', 0))
        to_val = float(range_item.get('to_value', float('inf')))

        if from_val <= value < to_val:
            hex_color = range_item.get('color', default_color)
            return hex_to_rgba(hex_color)

    return hex_to_rgba(default_color)


# ============================================================================
# OPERATORS
# ============================================================================

class GEODB_OT_LoadAssayConfig(Operator):
    """Load and display an AssayRangeConfiguration for review"""
    bl_idname = "geodb.load_assay_config"
    bl_label = "Select Assay Configuration"
    bl_description = "Load and display the selected assay configuration details"
    bl_options = {'REGISTER', 'UNDO'}

    # Cache configs to avoid repeated API calls in draw()
    _cached_configs = []

    def execute(self, context):
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        project_id = int(props.selected_project_id)

        # Get selected config from scene property
        if not hasattr(scene, 'geodb_assay_config_selection'):
            self.report({'ERROR'}, "No configuration selected - property not found")
            return {'CANCELLED'}

        try:
            selected_config_id = int(scene.geodb_assay_config_selection)
        except (ValueError, TypeError) as e:
            self.report({'ERROR'}, f"Invalid selection: {e}")
            return {'CANCELLED'}

        if selected_config_id <= 0:
            self.report({'ERROR'}, "Please select a valid assay configuration")
            return {'CANCELLED'}

        # Use cached configs from invoke() - no duplicate API call needed
        configs = self.__class__._cached_configs
        if not configs:
            # Fallback: fetch from API if cache is empty (shouldn't happen normally)
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

        # Save diameter overrides from Scene properties to persistent storage
        # Read current overrides
        try:
            diameter_overrides = json.loads(props.assay_diameter_overrides)
        except (json.JSONDecodeError, AttributeError):
            diameter_overrides = {}

        # Update with current values from Scene properties
        for range_idx in range(len(ranges)):
            override_key = f"config_{selected_config_id}_range_{range_idx}"
            prop_name = f"geodb_diameter_{override_key}"
            if hasattr(scene, prop_name):
                diameter_value = getattr(scene, prop_name)
                diameter_overrides[override_key] = diameter_value
                print(f"Saved diameter override: {override_key} = {diameter_value}m")

        # Save back to persistent storage
        props.assay_diameter_overrides = json.dumps(diameter_overrides)

        self.report({'INFO'}, f"Loaded config: {props.selected_assay_element} - {props.selected_assay_config_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        """Show dialog to select configuration"""
        scene = context.scene

        if not hasattr(scene.geodb, 'selected_project_id') or not scene.geodb.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        # Fetch configs and create dynamic enum property on Scene
        try:
            project_id = int(scene.geodb.selected_project_id)
            success, configs = GeoDBData.get_assay_range_configurations(project_id)

            if not success or not configs:
                self.report({'ERROR'}, "No assay configurations found for this project")
                return {'CANCELLED'}

            # CACHE configs to avoid repeated API calls in draw()
            self.__class__._cached_configs = configs

            # Also update ConfigCache for other components to use
            ConfigCache.set_assay_configs(project_id, configs)

            # Load existing diameter overrides from scene
            import json
            try:
                diameter_overrides = json.loads(scene.geodb.assay_diameter_overrides)
            except (json.JSONDecodeError, AttributeError):
                diameter_overrides = {}

            # PRE-CREATE default fallback material
            default_mat_name = "_preview_#CCCCCC"
            if default_mat_name not in bpy.data.materials:
                mat = bpy.data.materials.new(name=default_mat_name)
                mat.diffuse_color = hex_to_rgb('#CCCCCC')
                print(f"PRE-CREATED: {default_mat_name} (default fallback)")

            # PRE-CREATE all materials with colors (can't do this in draw()!)
            # AND pre-create FloatProperty for each range's diameter override
            from bpy.props import FloatProperty
            for config in configs:
                config_id = config.get('id')
                ranges = config.get('ranges', [])
                for range_idx, range_item in enumerate(ranges):
                    hex_color = range_item.get('color', '#CCCCCC')
                    mat_name = f"_preview_{hex_color}"

                    # Only create if doesn't exist
                    if mat_name not in bpy.data.materials:
                        mat = bpy.data.materials.new(name=mat_name)
                        rgba = hex_to_rgb(hex_color)
                        mat.diffuse_color = rgba
                        print(f"PRE-CREATED: {mat_name} with color {rgba}")

                    # Create FloatProperty for this range's diameter override
                    # Key format: "config_{config_id}_range_{range_idx}"
                    override_key = f"config_{config_id}_range_{range_idx}"
                    prop_name = f"geodb_diameter_{override_key}"

                    # Get default value: check override first, then API size, then fallback
                    api_size = float(range_item.get('size', 2.0))
                    default_diameter = diameter_overrides.get(override_key, api_size)

                    # Create property on Scene
                    setattr(bpy.types.Scene, prop_name, FloatProperty(
                        name="Diameter (m)",
                        description=f"Cylinder diameter in meters for this range",
                        default=default_diameter,
                        min=0.01,
                        max=100.0,
                        precision=3
                    ))

            # Build enum items list - format: (identifier, name, description, icon, number)
            enum_items = []
            for config in configs:
                config_id = str(config.get('id', 0))
                element = config.get('element', 'Unknown')
                name = config.get('name', '')
                units = config.get('units', '')

                # Format: ID - Element (Units) - Name
                display_name = f"{element}"
                if units:
                    display_name += f" ({units})"
                if name:
                    display_name += f" - {name}"

                enum_items.append((config_id, display_name, f"Config ID: {config_id}"))

            # Dynamically create the EnumProperty on the Scene (like BlenderDH pattern)
            bpy.types.Scene.geodb_assay_config_selection = EnumProperty(
                name="Configuration",
                description="Select assay range configuration to load",
                items=enum_items
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Error loading configurations: {str(e)}")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width=750)

    def draw(self, context):
        """Draw the configuration selection dialog"""
        layout = self.layout
        scene = context.scene

        layout.label(text="Choose Assay Range Configuration:")
        layout.separator()

        # Reference the Scene property, not self
        layout.prop(scene, "geodb_assay_config_selection", text="")

        layout.separator()
        layout.separator()

        # Show preview of selected config if available - USE CACHED DATA!
        if hasattr(scene, 'geodb_assay_config_selection') and self.__class__._cached_configs:
            try:
                selected_id = int(scene.geodb_assay_config_selection)

                # Use CACHED configs instead of making API call
                config = next((c for c in self.__class__._cached_configs if c.get('id') == selected_id), None)
                if config:
                    layout.label(text="Preview:", icon='VIEWZOOM')

                    box = layout.box()
                    box.label(text=f"Element: {config.get('element', 'Unknown')}")
                    box.label(text=f"Units: {config.get('units', '')}")

                    ranges = config.get('ranges', [])
                    if ranges:
                        box.separator()
                        box.label(text=f"{len(ranges)} Color Ranges:")

                        # Show ALL ranges (no limit) with diameter override fields
                        config_id = config.get('id')
                        for i, range_item in enumerate(ranges):
                            from_val = range_item.get('from_value', 0)
                            to_val = range_item.get('to_value')
                            label = range_item.get('label', f'Range {i+1}')
                            hex_color = range_item.get('color', '#CCCCCC')

                            # Convert to_value to string
                            if to_val is None or to_val == float('inf') or to_val > 1e15:
                                to_val_str = "∞"
                            else:
                                to_val_str = f"{to_val}"

                            # Create row with color
                            row = box.row(align=True)

                            # Get pre-created material for color display
                            mat_name = f"_preview_{hex_color}"
                            mat = bpy.data.materials.get(mat_name)
                            if not mat:
                                # Material should have been pre-created in invoke()
                                print(f"WARNING: Material {mat_name} not found - using default")
                                mat = bpy.data.materials.get("_preview_#CCCCCC")

                            # Color swatch (read-only display)
                            if mat:
                                col = row.column(align=True)
                                col.scale_x = 0.25
                                col.prop(mat, "diffuse_color", text="")
                            else:
                                # Fallback: just show a spacer if no material
                                col = row.column(align=True)
                                col.scale_x = 0.25

                            # Range info
                            col = row.column(align=True)
                            col.scale_x = 1.5
                            col.label(text=f"{from_val} - {to_val_str} | {label}")

                            # Diameter override field
                            override_key = f"config_{config_id}_range_{i}"
                            prop_name = f"geodb_diameter_{override_key}"
                            if hasattr(scene, prop_name):
                                col = row.column(align=True)
                                col.scale_x = 0.8
                                col.prop(scene, prop_name, text="Ø")
            except Exception as e:
                print(f"ERROR in draw: {e}")
                import traceback
                traceback.print_exc()




class GEODB_OT_LoadLithologyConfig(Operator):
    """Load and configure lithology types for a selected set"""
    bl_idname = "geodb.load_lithology_config"
    bl_label = "Configure Lithology Types"
    bl_description = "Select lithology set and configure diameter overrides for each lithology type"
    bl_options = {'REGISTER', 'UNDO'}

    # Cache lithology types to avoid repeated API calls in draw()
    _cached_lithology_types = []
    _cached_set_id = 0
    _cached_sets = []  # Cache the sets list from invoke()

    def execute(self, context):
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        # Get selected set from scene property
        if not hasattr(scene, 'geodb_lithology_set_selection'):
            self.report({'ERROR'}, "No lithology set selected")
            return {'CANCELLED'}

        try:
            selected_set_id = int(scene.geodb_lithology_set_selection)
        except (ValueError, TypeError) as e:
            self.report({'ERROR'}, f"Invalid selection: {e}")
            return {'CANCELLED'}

        if selected_set_id <= 0:
            self.report({'ERROR'}, "Please select a valid lithology set")
            return {'CANCELLED'}

        # Save diameter overrides from Scene properties to persistent storage
        import json
        try:
            diameter_overrides = json.loads(props.lithology_diameter_overrides)
        except (json.JSONDecodeError, AttributeError):
            diameter_overrides = {}

        # Update with current values from Scene properties
        for lith_idx, lith_type in enumerate(self.__class__._cached_lithology_types):
            lith_name = lith_type.get('name', '')
            override_key = f"set_{selected_set_id}_lith_{lith_name}"
            prop_name = f"geodb_lith_diameter_{override_key}"
            if hasattr(scene, prop_name):
                diameter_value = getattr(scene, prop_name)
                diameter_overrides[override_key] = diameter_value
                print(f"Saved lithology diameter override: {override_key} = {diameter_value}m")

        # Save back to persistent storage
        props.lithology_diameter_overrides = json.dumps(diameter_overrides)

        # Save selected set ID and name to scene properties
        props.selected_lithology_set_id = selected_set_id

        # Use cached sets from invoke() - no duplicate API call
        sets = self.__class__._cached_sets
        if sets:
            for lith_set in sets:
                if lith_set.get('id') == selected_set_id:
                    props.selected_lithology_set_name = lith_set.get('name', f'Set {selected_set_id}')
                    break

        self.report({'INFO'}, f"Loaded lithology set: {props.selected_lithology_set_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        """Show dialog to select set and configure lithology types"""
        scene = context.scene

        if not hasattr(scene.geodb, 'selected_project_id') or not scene.geodb.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        try:
            project_id = int(scene.geodb.selected_project_id)

            # Fetch lithology sets
            success, sets = GeoDBData.get_lithology_sets(project_id)
            if not success or not sets:
                self.report({'ERROR'}, "No lithology sets found for this project")
                return {'CANCELLED'}

            # Cache sets for execute() and update ConfigCache
            self.__class__._cached_sets = sets
            ConfigCache.set_lithology_sets(project_id, sets)

            # Build enum items for set selection
            enum_items = []
            for lith_set in sets:
                set_id = str(lith_set.get('id', 0))
                set_name = lith_set.get('name', 'Unnamed Set')
                enum_items.append((set_id, set_name, f"Set ID: {set_id}"))

            # Create property on Scene for set selection
            bpy.types.Scene.geodb_lithology_set_selection = EnumProperty(
                name="Lithology Set",
                description="Select lithology set to configure",
                items=enum_items
            )

            # Fetch lithology intervals for the first set to get unique types
            # User can change selection in the dialog, and we'll update in draw()
            first_set_id = int(enum_items[0][0]) if enum_items else 0

            if first_set_id > 0:
                self._load_lithology_types_for_set(context, project_id, first_set_id)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Error loading lithology sets: {str(e)}")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width=750)

    def _load_lithology_types_for_set(self, context, project_id, set_id):
        """Load unique lithology types for a given set"""
        scene = context.scene

        # Fetch lithology intervals for this set
        success, lithology_data = GeoDBData.get_lithologies_for_project(project_id, set_id)
        if not success or not lithology_data:
            print(f"No lithology data found for set {set_id}")
            self.__class__._cached_lithology_types = []
            self.__class__._cached_set_id = set_id
            return

        # Extract unique lithology types from intervals
        unique_lithologies = {}
        for hole_name, hole_lithologies in lithology_data.items():
            for lith_interval in hole_lithologies:
                lithology = lith_interval.get('lithology', {})
                if isinstance(lithology, dict):
                    lith_id = lithology.get('id')
                    lith_name = lithology.get('name', 'Unknown')
                    lith_color = lithology.get('color', '#CCCCCC')

                    if lith_id and lith_id not in unique_lithologies:
                        unique_lithologies[lith_id] = {
                            'id': lith_id,
                            'name': lith_name,
                            'color': lith_color,
                            'description': lithology.get('description', '')
                        }

        # Convert to list and sort by name
        lithology_types = sorted(unique_lithologies.values(), key=lambda x: x.get('name', ''))

        # Cache for draw()
        self.__class__._cached_lithology_types = lithology_types
        self.__class__._cached_set_id = set_id

        # Load existing diameter overrides
        import json
        try:
            diameter_overrides = json.loads(scene.geodb.lithology_diameter_overrides)
        except (json.JSONDecodeError, AttributeError):
            diameter_overrides = {}

        # PRE-CREATE all materials with colors (can't do this in draw()!)
        # AND pre-create FloatProperty for each lithology type's diameter
        from bpy.props import FloatProperty
        for lith_idx, lith_type in enumerate(lithology_types):
            lith_name = lith_type.get('name', 'Unknown')
            hex_color = lith_type.get('color', '#CCCCCC')
            mat_name = f"_preview_{hex_color}"

            # Only create material if doesn't exist
            if mat_name not in bpy.data.materials:
                mat = bpy.data.materials.new(name=mat_name)
                rgba = hex_to_rgb(hex_color)
                mat.diffuse_color = rgba
                print(f"PRE-CREATED: {mat_name} with color {rgba}")

            # Create FloatProperty for this lithology's diameter override
            # Key format: "set_{set_id}_lith_{lith_name}"
            override_key = f"set_{set_id}_lith_{lith_name}"
            prop_name = f"geodb_lith_diameter_{override_key}"

            # Get default value: check override first, else use 0.15m default
            default_diameter = diameter_overrides.get(override_key, 0.15)

            # Create property on Scene
            setattr(bpy.types.Scene, prop_name, FloatProperty(
                name="Diameter (m)",
                description=f"Tube diameter in meters for {lith_name}",
                default=default_diameter,
                min=0.01,
                max=100.0,
                precision=3
            ))

    def draw(self, context):
        """Draw the lithology configuration dialog"""
        layout = self.layout
        scene = context.scene

        layout.label(text="Configure Lithology Types:")
        layout.separator()

        # Lithology set selection
        layout.prop(scene, "geodb_lithology_set_selection", text="Set")

        # Check if user changed the set selection
        if hasattr(scene, 'geodb_lithology_set_selection'):
            try:
                selected_set_id = int(scene.geodb_lithology_set_selection)

                # If set changed, reload lithology types
                if selected_set_id != self.__class__._cached_set_id:
                    project_id = int(scene.geodb.selected_project_id)
                    self._load_lithology_types_for_set(context, project_id, selected_set_id)
            except (ValueError, TypeError):
                pass

        layout.separator()

        # Show lithology types with colors and diameter fields
        if self.__class__._cached_lithology_types:
            box = layout.box()
            box.label(text=f"{len(self.__class__._cached_lithology_types)} Lithology Types:", icon='COLOR')

            selected_set_id = self.__class__._cached_set_id

            for lith_idx, lith_type in enumerate(self.__class__._cached_lithology_types):
                lith_name = lith_type.get('name', 'Unknown')
                hex_color = lith_type.get('color', '#CCCCCC')
                description = lith_type.get('description', '')

                # Create row with color swatch, name, and diameter field
                row = box.row(align=True)

                # Color swatch
                mat_name = f"_preview_{hex_color}"
                mat = bpy.data.materials.get(mat_name)
                if mat:
                    col = row.column(align=True)
                    col.scale_x = 0.25
                    col.prop(mat, "diffuse_color", text="")
                else:
                    col = row.column(align=True)
                    col.scale_x = 0.25

                # Lithology name
                col = row.column(align=True)
                col.scale_x = 1.5
                display_text = lith_name
                if description:
                    display_text += f" - {description[:30]}"
                col.label(text=display_text)

                # Diameter override field
                override_key = f"set_{selected_set_id}_lith_{lith_name}"
                prop_name = f"geodb_lith_diameter_{override_key}"
                if hasattr(scene, prop_name):
                    col = row.column(align=True)
                    col.scale_x = 0.8
                    col.prop(scene, prop_name, text="Ø")
        else:
            layout.label(text="No lithology types found for this set", icon='INFO')


class GEODB_OT_LoadAlterationConfig(Operator):
    """Load and configure alteration types for a selected set"""
    bl_idname = "geodb.load_alteration_config"
    bl_label = "Configure Alteration Types"
    bl_description = "Load an alteration set and configure visualization options"
    bl_options = {'REGISTER', 'UNDO'}

    # Class variables to cache alteration types for the current set
    _cached_alteration_types = []
    _cached_set_id = None
    _cached_sets = []  # Cache the sets list from invoke()

    def execute(self, context):
        scene = context.scene
        props = scene.geodb

        try:
            # Get the selected set ID from the scene property
            selected_set_id = int(scene.geodb_alteration_set_selection)

            # Collect diameter overrides
            diameter_overrides = {}
            for alt_type in self.__class__._cached_alteration_types:
                alt_name = alt_type.get('name', 'Unknown')
                override_key = f"set_{selected_set_id}_alt_{alt_name}"
                prop_name = f"geodb_alt_diameter_{override_key}"

                if hasattr(scene, prop_name):
                    diameter_value = getattr(scene, prop_name)
                    diameter_overrides[override_key] = diameter_value

            # Save diameter overrides to scene property
            import json
            if diameter_overrides:
                props.alteration_diameter_overrides = json.dumps(diameter_overrides)

            # Save selected set ID and name to scene properties
            props.selected_alteration_set_id = selected_set_id

            # Use cached sets from invoke() - no duplicate API call
            sets = self.__class__._cached_sets
            if sets:
                for alt_set in sets:
                    if alt_set.get('id') == selected_set_id:
                        props.selected_alteration_set_name = alt_set.get('name', f'Set {selected_set_id}')
                        break

            self.report({'INFO'}, f"Loaded alteration set: {props.selected_alteration_set_name}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to load alteration configuration: {str(e)}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        scene = context.scene
        props = scene.geodb

        try:
            project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        # Fetch alteration sets
        success, sets = GeoDBData.get_alteration_sets(project_id)

        if not success or not sets:
            self.report({'ERROR'}, "Failed to fetch alteration sets or no sets available")
            return {'CANCELLED'}

        # Cache sets for execute() and update ConfigCache
        self.__class__._cached_sets = sets
        ConfigCache.set_alteration_sets(project_id, sets)

        # Create EnumProperty items for set selection
        set_items = [
            (str(alt_set.get('id', '')), alt_set.get('name', 'Unknown Set'), alt_set.get('description', ''))
            for alt_set in sets
        ]

        # Store the enum property on the scene
        bpy.types.Scene.geodb_alteration_set_selection = EnumProperty(
            name="Alteration Set",
            description="Select an alteration set",
            items=set_items
        )

        # Load alteration types for the first set by default
        first_set_id = sets[0].get('id')
        self._load_alteration_types_for_set(context, project_id, first_set_id)

        return context.window_manager.invoke_props_dialog(self, width=750)

    def _load_alteration_types_for_set(self, context, project_id, set_id):
        """Load and cache alteration types for the given set"""
        scene = context.scene

        # Fetch alteration intervals for this set
        success, alteration_data = GeoDBData.get_alterations_for_project(project_id, set_id)

        if not success or not alteration_data:
            print(f"No alteration data found for set {set_id}")
            self.__class__._cached_alteration_types = []
            self.__class__._cached_set_id = set_id
            return

        # Extract unique alteration types from intervals
        unique_alterations = {}
        for hole_name, hole_alterations in alteration_data.items():
            for alt_interval in hole_alterations:
                alteration = alt_interval.get('alteration', {})
                if isinstance(alteration, dict):
                    alt_id = alteration.get('id')
                    alt_name = alteration.get('name', 'Unknown')
                    alt_color = alteration.get('color', '#CCCCCC')

                    if alt_id and alt_id not in unique_alterations:
                        unique_alterations[alt_id] = {
                            'id': alt_id,
                            'name': alt_name,
                            'color': alt_color,
                            'description': alteration.get('description', '')
                        }

        # Convert to list and sort by name
        alteration_types = sorted(unique_alterations.values(), key=lambda x: x.get('name', ''))

        # Cache for draw()
        self.__class__._cached_alteration_types = alteration_types
        self.__class__._cached_set_id = set_id

        # Create preview materials for color swatches
        for alt_type in self.__class__._cached_alteration_types:
            hex_color = alt_type.get('color', '#CCCCCC')
            mat_name = f"_preview_{hex_color}"
            if mat_name not in bpy.data.materials:
                mat = bpy.data.materials.new(name=mat_name)
                mat.use_nodes = False
                # Convert hex to RGB
                hex_color = hex_color.lstrip('#')
                rgb = tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
                mat.diffuse_color = (*rgb, 1.0)

        # Create FloatProperty for each alteration type's diameter override
        for alt_type in self.__class__._cached_alteration_types:
            alt_name = alt_type.get('name', 'Unknown')
            override_key = f"set_{set_id}_alt_{alt_name}"
            prop_name = f"geodb_alt_diameter_{override_key}"

            # Check if we have a saved override value
            import json
            try:
                overrides = json.loads(scene.geodb.alteration_diameter_overrides)
                default_value = overrides.get(override_key, 1.0)
            except:
                default_value = 1.0

            # Create the property on the scene
            setattr(
                bpy.types.Scene,
                prop_name,
                FloatProperty(
                    name="Diameter",
                    description=f"Diameter multiplier for {alt_name}",
                    default=default_value,
                    min=0.1,
                    max=5.0
                )
            )

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Set selection dropdown
        if hasattr(scene, 'geodb_alteration_set_selection'):
            layout.prop(scene, 'geodb_alteration_set_selection', text="Alteration Set")

            # Reload if set changed
            try:
                selected_set_id = int(scene.geodb_alteration_set_selection)

                # If set changed, reload alteration types
                if selected_set_id != self.__class__._cached_set_id:
                    project_id = int(scene.geodb.selected_project_id)
                    self._load_alteration_types_for_set(context, project_id, selected_set_id)
            except (ValueError, TypeError):
                pass

        layout.separator()

        # Show alteration types with colors and diameter fields
        if self.__class__._cached_alteration_types:
            box = layout.box()
            box.label(text=f"{len(self.__class__._cached_alteration_types)} Alteration Types:", icon='COLOR')

            selected_set_id = self.__class__._cached_set_id

            for alt_type in self.__class__._cached_alteration_types:
                alt_name = alt_type.get('name', 'Unknown')
                hex_color = alt_type.get('color', '#CCCCCC')

                # Create row with color swatch, name, and diameter field
                row = box.row(align=True)

                # Color swatch
                mat_name = f"_preview_{hex_color}"
                mat = bpy.data.materials.get(mat_name)
                if mat:
                    col = row.column(align=True)
                    col.scale_x = 0.25
                    col.prop(mat, "diffuse_color", text="")
                else:
                    col = row.column(align=True)
                    col.scale_x = 0.25

                # Alteration name
                col = row.column(align=True)
                col.scale_x = 1.5
                col.label(text=alt_name)

                # Diameter override field
                override_key = f"set_{selected_set_id}_alt_{alt_name}"
                prop_name = f"geodb_alt_diameter_{override_key}"
                if hasattr(scene, prop_name):
                    col = row.column(align=True)
                    col.scale_x = 0.8
                    col.prop(scene, prop_name, text="Ø")
        else:
            layout.label(text="No alteration types found for this set", icon='INFO')


class GEODB_OT_LoadMineralizationConfig(Operator):
    """Load and configure mineralization types for a selected set"""
    bl_idname = "geodb.load_mineralization_config"
    bl_label = "Configure Mineralization Types"
    bl_description = "Load a mineralization set and configure visualization options"
    bl_options = {'REGISTER', 'UNDO'}

    # Class variables to cache mineralization types for the current set
    _cached_mineralization_types = []
    _cached_set_id = None
    _cached_sets = []  # Cache the sets list from invoke()

    def execute(self, context):
        scene = context.scene
        props = scene.geodb

        try:
            # Get the selected set ID from the scene property
            selected_set_id = int(scene.geodb_mineralization_set_selection)

            # Collect diameter overrides
            diameter_overrides = {}
            for min_type in self.__class__._cached_mineralization_types:
                min_name = min_type.get('name', 'Unknown')
                override_key = f"set_{selected_set_id}_min_{min_name}"
                prop_name = f"geodb_min_diameter_{override_key}"

                if hasattr(scene, prop_name):
                    diameter_value = getattr(scene, prop_name)
                    diameter_overrides[override_key] = diameter_value

            # Save diameter overrides to scene property
            import json
            if diameter_overrides:
                props.mineralization_diameter_overrides = json.dumps(diameter_overrides)

            # Save selected set ID and name to scene properties
            props.selected_mineralization_set_id = selected_set_id

            # Use cached sets from invoke() - no duplicate API call
            sets = self.__class__._cached_sets
            if sets:
                for min_set in sets:
                    if min_set.get('id') == selected_set_id:
                        props.selected_mineralization_set_name = min_set.get('name', f'Set {selected_set_id}')
                        break

            self.report({'INFO'}, f"Loaded mineralization set: {props.selected_mineralization_set_name}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to load mineralization configuration: {str(e)}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        scene = context.scene
        props = scene.geodb

        try:
            project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        # Fetch mineralization sets
        success, sets = GeoDBData.get_mineralization_sets(project_id)

        if not success or not sets:
            self.report({'ERROR'}, "Failed to fetch mineralization sets or no sets available")
            return {'CANCELLED'}

        # Cache sets for execute() and update ConfigCache
        self.__class__._cached_sets = sets
        ConfigCache.set_mineralization_sets(project_id, sets)

        # Create EnumProperty items for set selection
        set_items = [
            (str(min_set.get('id', '')), min_set.get('name', 'Unknown Set'), min_set.get('description', ''))
            for min_set in sets
        ]

        # Store the enum property on the scene
        bpy.types.Scene.geodb_mineralization_set_selection = EnumProperty(
            name="Mineralization Set",
            description="Select a mineralization set",
            items=set_items
        )

        # Load mineralization types for the first set by default
        first_set_id = sets[0].get('id')
        self._load_mineralization_types_for_set(context, project_id, first_set_id)

        return context.window_manager.invoke_props_dialog(self, width=750)

    def _load_mineralization_types_for_set(self, context, project_id, set_id):
        """Load and cache mineralization types for the given set"""
        scene = context.scene

        # Fetch mineralization intervals for this set
        success, mineralization_data = GeoDBData.get_mineralizations_for_project(project_id, set_id)

        if not success or not mineralization_data:
            print(f"No mineralization data found for set {set_id}")
            self.__class__._cached_mineralization_types = []
            self.__class__._cached_set_id = set_id
            return

        # Extract unique mineralization types from intervals
        # Note: DrillMineralization uses 'assemblage' field, not 'mineralization'
        unique_mineralizations = {}
        for hole_name, hole_mineralizations in mineralization_data.items():
            for min_interval in hole_mineralizations:
                assemblage = min_interval.get('assemblage', {})
                if isinstance(assemblage, dict):
                    min_id = assemblage.get('id')
                    min_name = assemblage.get('name', 'Unknown')
                    min_color = assemblage.get('color', '#CCCCCC')

                    if min_id and min_id not in unique_mineralizations:
                        unique_mineralizations[min_id] = {
                            'id': min_id,
                            'name': min_name,
                            'color': min_color,
                            'description': assemblage.get('description', '')
                        }

        # Convert to list and sort by name
        mineralization_types = sorted(unique_mineralizations.values(), key=lambda x: x.get('name', ''))

        # Cache for draw()
        self.__class__._cached_mineralization_types = mineralization_types
        self.__class__._cached_set_id = set_id

        # Create preview materials for color swatches
        for min_type in self.__class__._cached_mineralization_types:
            hex_color = min_type.get('color', '#CCCCCC')
            mat_name = f"_preview_{hex_color}"
            if mat_name not in bpy.data.materials:
                mat = bpy.data.materials.new(name=mat_name)
                mat.use_nodes = False
                # Convert hex to RGB
                hex_color = hex_color.lstrip('#')
                rgb = tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
                mat.diffuse_color = (*rgb, 1.0)

        # Create FloatProperty for each mineralization type's diameter override
        for min_type in self.__class__._cached_mineralization_types:
            min_name = min_type.get('name', 'Unknown')
            override_key = f"set_{set_id}_min_{min_name}"
            prop_name = f"geodb_min_diameter_{override_key}"

            # Check if we have a saved override value
            import json
            try:
                overrides = json.loads(scene.geodb.mineralization_diameter_overrides)
                default_value = overrides.get(override_key, 1.0)
            except:
                default_value = 1.0

            # Create the property on the scene
            setattr(
                bpy.types.Scene,
                prop_name,
                FloatProperty(
                    name="Diameter",
                    description=f"Diameter multiplier for {min_name}",
                    default=default_value,
                    min=0.1,
                    max=5.0
                )
            )

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Set selection dropdown
        if hasattr(scene, 'geodb_mineralization_set_selection'):
            layout.prop(scene, 'geodb_mineralization_set_selection', text="Mineralization Set")

            # Reload if set changed
            try:
                selected_set_id = int(scene.geodb_mineralization_set_selection)

                # If set changed, reload mineralization types
                if selected_set_id != self.__class__._cached_set_id:
                    project_id = int(scene.geodb.selected_project_id)
                    self._load_mineralization_types_for_set(context, project_id, selected_set_id)
            except (ValueError, TypeError):
                pass

        layout.separator()

        # Show mineralization types with colors and diameter fields
        if self.__class__._cached_mineralization_types:
            box = layout.box()
            box.label(text=f"{len(self.__class__._cached_mineralization_types)} Mineralization Types:", icon='COLOR')

            selected_set_id = self.__class__._cached_set_id

            for min_type in self.__class__._cached_mineralization_types:
                min_name = min_type.get('name', 'Unknown')
                hex_color = min_type.get('color', '#CCCCCC')

                # Create row with color swatch, name, and diameter field
                row = box.row(align=True)

                # Color swatch
                mat_name = f"_preview_{hex_color}"
                mat = bpy.data.materials.get(mat_name)
                if mat:
                    col = row.column(align=True)
                    col.scale_x = 0.25
                    col.prop(mat, "diffuse_color", text="")
                else:
                    col = row.column(align=True)
                    col.scale_x = 0.25

                # Mineralization name
                col = row.column(align=True)
                col.scale_x = 1.5
                col.label(text=min_name)

                # Diameter override field
                override_key = f"set_{selected_set_id}_min_{min_name}"
                prop_name = f"geodb_min_diameter_{override_key}"
                if hasattr(scene, prop_name):
                    col = row.column(align=True)
                    col.scale_x = 0.8
                    col.prop(scene, prop_name, text="Ø")
        else:
            layout.label(text="No mineralization types found for this set", icon='INFO')


class GEODB_OT_VisualizeAssays(Operator):
    """Visualize assay intervals using the loaded configuration (async with progress)"""
    bl_idname = "geodb.visualize_assays"
    bl_label = "Visualize Assays"
    bl_description = "Create curved tube visualization of assay intervals along drill holes"
    bl_options = {'REGISTER', 'UNDO'}

    # Multi-stage progress tracking
    _stages = [
        ('Validating', 0.05),      # 5% - validation and config lookup
        ('Fetching samples', 0.60), # 60% - main API call
        ('Processing data', 0.20),  # 20% - data processing
        ('Creating meshes', 0.15),  # 15% - mesh creation (main thread)
    ]

    # Async operation state
    _timer = None
    _thread = None
    _progress = 0.0
    _status = ""
    _data = None
    _error = None
    _cancelled = False
    _current_stage = 0

    # Store parameters captured from scene props (thread-safe access)
    _project_id = None
    _selected_config_id = None
    _project_name = None
    _company_id = None
    _company_name = None
    _diameter_overrides = {}

    def invoke(self, context, event):
        """Start the async visualization operation."""
        scene = context.scene
        props = scene.geodb

        # Validate before starting
        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        if not hasattr(props, 'selected_assay_config_id') or props.selected_assay_config_id <= 0:
            self.report({'ERROR'}, "No assay configuration loaded. Please load a configuration first.")
            return {'CANCELLED'}

        try:
            self.__class__._project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        # Check if another operation is already running
        if props.import_active:
            self.report({'WARNING'}, "Another import operation is already running")
            return {'CANCELLED'}

        # Capture parameters from scene props (thread-safe)
        self.__class__._selected_config_id = props.selected_assay_config_id
        self.__class__._project_name = props.selected_project_name or f"Project_{self._project_id}"
        self.__class__._company_id = int(props.selected_company_id) if hasattr(props, 'selected_company_id') and props.selected_company_id else 0
        self.__class__._company_name = props.selected_company_name if hasattr(props, 'selected_company_name') else ''

        # Load diameter overrides from persistent storage
        import json
        try:
            self.__class__._diameter_overrides = json.loads(props.assay_diameter_overrides)
        except (json.JSONDecodeError, AttributeError):
            self.__class__._diameter_overrides = {}

        # Mark operation as active
        props.import_active = True
        props.import_progress = 0.0
        props.import_status = "Initializing..."

        # Reset state
        self.__class__._progress = 0.0
        self.__class__._status = "Initializing..."
        self.__class__._data = None
        self.__class__._error = None
        self.__class__._cancelled = False
        self.__class__._current_stage = 0

        # Start background thread
        import threading
        self.__class__._thread = threading.Thread(target=self._download_data_wrapper)
        self.__class__._thread.start()

        # Start modal timer (checks every 0.1 seconds)
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def _download_data_wrapper(self):
        """Wrapper to catch exceptions in download_data."""
        try:
            self.download_data()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.__class__._error = str(e)

    def _set_stage(self, index, name=None):
        """Move to a specific stage and update status."""
        self.__class__._current_stage = index
        base_progress = sum(self._stages[i][1] for i in range(index)) if index > 0 else 0.0
        self.__class__._progress = base_progress
        if name is None and index < len(self._stages):
            name = self._stages[index][0]
        total_stages = len(self._stages)
        self.__class__._status = f"Stage {index + 1}/{total_stages}: {name}..."

    def _update_stage_progress(self, done, total, stage_name=None):
        """Update progress within current stage."""
        if total <= 0:
            return
        stage_weight = self._stages[self._current_stage][1] if self._current_stage < len(self._stages) else 0.0
        base_progress = sum(self._stages[i][1] for i in range(self._current_stage)) if self._current_stage > 0 else 0.0
        stage_progress = (done / total) * stage_weight
        self.__class__._progress = base_progress + stage_progress

        if stage_name is None and self._current_stage < len(self._stages):
            stage_name = self._stages[self._current_stage][0]
        total_stages = len(self._stages)
        self.__class__._status = f"Stage {self._current_stage + 1}/{total_stages}: {stage_name}... {done:,}/{total:,}"

    def download_data(self):
        """Background thread: Fetch data from API (no Blender API calls)."""
        import json

        # Stage 1: Validate and get config
        self._set_stage(0, "Validating configuration")

        project_id = self._project_id
        selected_config_id = self._selected_config_id
        project_name = self._project_name

        print(f"\n=== Async Assay Visualization for {project_name} ===")

        # Fetch assay configuration details
        success, configs = GeoDBData.get_assay_range_configurations(project_id)
        if self._cancelled:
            return

        if not success:
            self.__class__._error = "Failed to fetch assay configurations"
            return

        config = next((c for c in configs if c.get('id') == selected_config_id), None)
        if not config:
            self.__class__._error = f"Configuration ID {selected_config_id} not found"
            return

        config_name = config.get('name', 'Assay')
        element = config.get('element', 'Unknown')
        units = config.get('units_display', config.get('units', ''))
        ranges = config.get('ranges', [])
        default_color = config.get('default_color', '#CCCCCC')

        print(f"Configuration: {config_name} ({element} in {units})")
        print(f"Ranges: {len(ranges)}")

        # Stage 2: Fetch samples (the big one)
        self._set_stage(1, "Fetching samples")

        print(f"Fetching drill samples...")
        success, samples_by_hole = GeoDBData.get_all_samples_for_project(
            project_id,
            assay_config_id=selected_config_id
        )

        if self._cancelled:
            return

        if not success or not samples_by_hole:
            self.__class__._error = "No drill samples found for project"
            return

        total_samples = sum(len(v) for v in samples_by_hole.values())
        print(f"Fetched {total_samples} samples across {len(samples_by_hole)} holes")

        # Stage 3: Process data (prepare mesh parameters)
        self._set_stage(2, "Processing data")

        # Extract available elements
        available_elements = set()
        for hole_samples in samples_by_hole.values():
            for sample in hole_samples:
                assay = sample.get('assay')
                if assay and isinstance(assay, dict):
                    for elem in assay.get('elements', []):
                        if isinstance(elem, dict) and elem.get('element'):
                            available_elements.add(elem.get('element'))

        diameter_overrides = self._diameter_overrides

        # Process samples and prepare mesh data (no Blender API calls)
        processed_holes = []
        total_skipped = 0
        processed_count = 0
        total_to_process = len(samples_by_hole)

        for hole_id, hole_samples in samples_by_hole.items():
            if self._cancelled:
                return

            processed_count += 1
            self._update_stage_progress(processed_count, total_to_process, "Processing data")

            if not hole_samples:
                continue

            # Get hole name
            sample = hole_samples[0]
            bhid = sample.get('bhid')
            if isinstance(bhid, dict):
                hole_name = bhid.get('hole_id') or bhid.get('name')
            elif isinstance(bhid, str):
                hole_name = bhid
            else:
                hole_name = f'Hole_{hole_id}'

            hole_mesh_data = []

            for sample in hole_samples:
                assay_obj = sample.get('assay', {})
                assay_name = assay_obj.get('name', '') if isinstance(assay_obj, dict) else ''
                elements = assay_obj.get('elements', []) if isinstance(assay_obj, dict) else []

                assay_value = None
                assay_unit = None
                all_assay_data = {}

                for elem in elements:
                    elem_name = elem.get('element')
                    if elem_name == element:
                        try:
                            assay_value = float(elem.get('value', 0))
                        except (ValueError, TypeError):
                            assay_value = None
                        method_unit = elem.get('method_unit', {})
                        if isinstance(method_unit, dict):
                            assay_unit = method_unit.get('units', units)

                    if elem_name:
                        method_unit = elem.get('method_unit', {})
                        all_assay_data[f"element_{elem_name}"] = {
                            "value": elem.get('value'),
                            "units": method_unit.get('units') if isinstance(method_unit, dict) else None,
                            "method_name": method_unit.get('method') if isinstance(method_unit, dict) else None,
                            "detection_limit": method_unit.get('detection_limit') if isinstance(method_unit, dict) else None,
                            "upper_limit": method_unit.get('upper_limit') if isinstance(method_unit, dict) else None,
                        }

                if assay_value is None:
                    total_skipped += 1
                    continue

                # Find matching range
                matching_range = None
                matching_range_idx = None
                for range_idx, range_item in enumerate(ranges):
                    from_val = float(range_item.get('from_value', 0))
                    to_val = float(range_item.get('to_value', float('inf')))
                    if from_val <= assay_value < to_val:
                        matching_range = range_item
                        matching_range_idx = range_idx
                        break

                if not matching_range:
                    color_hex = default_color
                    size = 2
                    label = 'Out of Range'
                else:
                    color_hex = matching_range.get('color', '#FFFFFF')
                    size = matching_range.get('size', 2)
                    label = matching_range.get('label', '')
                    override_key = f"config_{selected_config_id}_range_{matching_range_idx}"
                    if override_key in diameter_overrides:
                        size = diameter_overrides[override_key]

                xyz_from = sample.get('xyz_from')
                xyz_to = sample.get('xyz_to')
                from_depth = sample.get('from_depth', 0)
                to_depth = sample.get('to_depth', 0)

                if not xyz_from or not xyz_to:
                    total_skipped += 1
                    continue

                # Store data for mesh creation in main thread
                hole_mesh_data.append({
                    'hole_name': hole_name,
                    'hole_id': hole_id,
                    'xyz_from': tuple(xyz_from) if isinstance(xyz_from, (list, tuple)) else xyz_from,
                    'xyz_to': tuple(xyz_to) if isinstance(xyz_to, (list, tuple)) else xyz_to,
                    'diameter': float(size),
                    'color_hex': color_hex,
                    'from_depth': from_depth,
                    'to_depth': to_depth,
                    'element': element,
                    'assay_value': assay_value,
                    'assay_unit': assay_unit,
                    'label': label,
                    'assay_name': assay_name,
                    'config_name': config_name,
                    'all_assay_data': all_assay_data,
                    'sample_id': sample.get('id'),
                })

            if hole_mesh_data:
                processed_holes.append({
                    'hole_name': hole_name,
                    'hole_id': hole_id,
                    'mesh_data': hole_mesh_data,
                })

        # Store all data for main thread
        self.__class__._data = {
            'config_name': config_name,
            'element': element,
            'units': units,
            'project_id': project_id,
            'project_name': project_name,
            'company_id': self._company_id,
            'company_name': self._company_name,
            'samples_by_hole': samples_by_hole,
            'available_elements': sorted(list(available_elements)),
            'configs': configs,
            'processed_holes': processed_holes,
            'total_skipped': total_skipped,
        }

        print(f"Data processing complete: {len(processed_holes)} holes ready for mesh creation")

    def modal(self, context, event):
        """Called repeatedly while operation runs."""
        if event.type == 'ESC':
            self.__class__._cancelled = True
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            # Update progress display in UI
            context.scene.geodb.import_progress = self._progress
            context.scene.geodb.import_status = self._status
            context.area.tag_redraw()

            # Check if thread finished
            if self._thread and not self._thread.is_alive():
                if self._cancelled:
                    self.cleanup(context)
                    return {'CANCELLED'}
                elif self._error:
                    self.report({'ERROR'}, self._error)
                    self.cleanup(context)
                    return {'CANCELLED'}
                else:
                    try:
                        self.finish_in_main_thread(context)
                        self.cleanup(context)
                        return {'FINISHED'}
                    except Exception as e:
                        self.report({'ERROR'}, f"Error creating objects: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        self.cleanup(context)
                        return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def finish_in_main_thread(self, context):
        """Main thread: Create Blender meshes and collections."""
        data = self._data
        if not data:
            return

        self._set_stage(3, "Creating meshes")

        config_name = data['config_name']
        element = data['element']
        processed_holes = data['processed_holes']
        total_skipped = data['total_skipped']

        # Update cache for RBF interpolation
        cache_data = {
            'project_id': data['project_id'],
            'company_id': data['company_id'],
            'project_name': data['project_name'],
            'company_name': data['company_name'],
            'samples': data['samples_by_hole'],
            'available_elements': data['available_elements'],
            'assay_range_configs': data['configs'],
        }
        DrillDataCache.set_cache(cache_data)

        # Create master collection
        master_collection = bpy.data.collections.new(config_name)
        bpy.context.scene.collection.children.link(master_collection)

        total_meshes_created = 0
        holes_with_meshes = 0
        created_objects = []

        total_holes = len(processed_holes)
        for hole_idx, hole_data in enumerate(processed_holes):
            self._update_stage_progress(hole_idx, total_holes, "Creating meshes")

            hole_name = hole_data['hole_name']
            mesh_data_list = hole_data['mesh_data']

            # Create collection for this hole
            hole_collection = bpy.data.collections.new(hole_name)
            master_collection.children.link(hole_collection)

            for mesh_params in mesh_data_list:
                try:
                    mesh_name = f"{mesh_params['hole_name']}_{mesh_params['from_depth']:.1f}-{mesh_params['to_depth']:.1f}_{element}_{mesh_params['assay_value']:.2f}{mesh_params['assay_unit']}"

                    assay_metadata = {
                        'active_assay_name': mesh_params['assay_name'],
                        'active_config_name': mesh_params['config_name'],
                        'active_assay_element': element,
                        'active_assay_value': mesh_params['assay_value'],
                        'active_assay_unit': mesh_params['assay_unit'],
                        'all_elements': mesh_params['all_assay_data'],
                        'sample_id': mesh_params['sample_id'],
                    }

                    mesh_obj = create_sample_cylinder_mesh(
                        xyz_from=mesh_params['xyz_from'],
                        xyz_to=mesh_params['xyz_to'],
                        diameter=mesh_params['diameter'],
                        color_hex=mesh_params['color_hex'],
                        name=mesh_name,
                        material_name=f"Assay_{element}_{mesh_params['label']}",
                        assay_metadata=assay_metadata
                    )

                    # Unlink from default and link to hole collection
                    for coll in mesh_obj.users_collection:
                        coll.objects.unlink(mesh_obj)
                    hole_collection.objects.link(mesh_obj)

                    # Tag with metadata
                    mesh_obj['geodb_visualization'] = True
                    mesh_obj['geodb_type'] = 'assay_sample'
                    mesh_obj['hole_name'] = mesh_params['hole_name']
                    mesh_obj['active_range_label'] = mesh_params['label']

                    created_objects.append(mesh_obj)
                    total_meshes_created += 1

                except Exception as e:
                    print(f"Error creating mesh: {e}")
                    total_skipped += 1

            holes_with_meshes += 1

        # Auto-adjust view
        adjust_view_to_objects(context, created_objects)

        if total_meshes_created == 0:
            self.report({'ERROR'}, f"No meshes created. No samples with {element} data. (Skipped: {total_skipped})")
        else:
            self.report({'INFO'}, f"Created {total_meshes_created} meshes in {holes_with_meshes} holes (Skipped: {total_skipped})")

    def cleanup(self, context):
        """Clean up timer and mark operation complete."""
        wm = context.window_manager
        if self.__class__._timer:
            wm.event_timer_remove(self.__class__._timer)
            self.__class__._timer = None

        context.scene.geodb.import_active = False
        context.scene.geodb.import_progress = 0.0
        context.scene.geodb.import_status = ""
        context.area.tag_redraw()

    def cancel(self, context):
        """User cancelled with ESC key."""
        self.__class__._cancelled = True
        self.cleanup(context)
        self.report({'INFO'}, "Operation cancelled by user")


# ============================================================================
# PANELS
# ============================================================================
# Note: Properties are defined in main __init__.py GeoDBProperties class

class GEODB_PT_DrillVisualizationPanel(Panel):
    """Main panel for drill data visualization workflow"""
    bl_label = "Drill Visualization"
    bl_idname = "GEODB_PT_drill_visualization"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        geodb = scene.geodb

        # Check if project is selected
        if not geodb.selected_project_id:
            layout.label(text="Please select a project first", icon='ERROR')
            return

        # View settings
        row = layout.row()
        row.prop(geodb, "auto_adjust_view", text="Auto-adjust view on import")
        layout.separator()

        # Show progress bar if operation is running
        if geodb.import_active:
            box = layout.box()
            box.label(text="Import in Progress...", icon='INFO')

            # Progress bar
            row = box.row()
            row.progress(
                factor=geodb.import_progress,
                type='BAR',
                text=geodb.import_status
            )

            box.label(text="Press ESC to cancel", icon='CANCEL')

            # Disable all import buttons while operation running
            layout.enabled = False

        # Assay Visualization
        box = layout.box()
        box.label(text="Assay Visualization", icon='MESH_CUBE')

        row = box.row()
        row.operator("geodb.load_assay_config", text="Load Configuration", icon='IMPORT')

        # Show loaded config summary if available (NO API CALLS - use cached data only!)
        if hasattr(geodb, 'selected_assay_config_id') and geodb.selected_assay_config_id > 0:
            col = box.column(align=True)
            col.label(text=f"Element: {geodb.selected_assay_element}")
            col.label(text=f"Config: {geodb.selected_assay_config_name}")
            col.label(text=f"Units: {geodb.selected_assay_units}")

            # Just show count, not full table
            if hasattr(geodb, 'selected_assay_ranges') and geodb.selected_assay_ranges:
                try:
                    import json
                    ranges = json.loads(geodb.selected_assay_ranges)
                    box.label(text=f"Ranges: {len(ranges)} configured", icon='COLOR')
                except:
                    pass

            row = box.row()
            row.scale_y = 1.5
            row.operator("geodb.visualize_assays", text="Create Visualization", icon='MESH_CYLINDER')

        # Lithology Visualization
        box = layout.box()
        box.label(text="Lithology Visualization", icon='MESH_TORUS')

        row = box.row()
        row.operator("geodb.load_lithology_config", text="Load Configuration", icon='IMPORT')

        # Show loaded config summary if available
        if hasattr(geodb, 'selected_lithology_set_id') and geodb.selected_lithology_set_id > 0:
            col = box.column(align=True)
            col.label(text=f"Set: {geodb.selected_lithology_set_name}")

            row = box.row()
            row.scale_y = 1.5
            row.operator("geodb.visualize_lithology", text="Create Visualization", icon='MESH_CYLINDER')

        # Alteration Visualization
        box = layout.box()
        box.label(text="Alteration Visualization", icon='SURFACE_DATA')

        row = box.row()
        row.operator("geodb.load_alteration_config", text="Load Configuration", icon='IMPORT')

        # Show loaded config summary if available
        if hasattr(geodb, 'selected_alteration_set_id') and geodb.selected_alteration_set_id > 0:
            col = box.column(align=True)
            col.label(text=f"Set: {geodb.selected_alteration_set_name}")

            row = box.row()
            row.scale_y = 1.5
            row.operator("geodb.visualize_alteration", text="Create Visualization", icon='MESH_CYLINDER')

        # Mineralization Visualization
        box = layout.box()
        box.label(text="Mineralization Visualization", icon='MESH_ICOSPHERE')

        row = box.row()
        row.operator("geodb.load_mineralization_config", text="Load Configuration", icon='IMPORT')

        # Show loaded config summary if available
        if hasattr(geodb, 'selected_mineralization_set_id') and geodb.selected_mineralization_set_id > 0:
            col = box.column(align=True)
            col.label(text=f"Set: {geodb.selected_mineralization_set_name}")

            row = box.row()
            row.scale_y = 1.5
            row.operator("geodb.visualize_mineralization", text="Create Visualization", icon='MESH_CYLINDER')


class GEODB_PT_TerrainVisualizationPanel(Panel):
    """Panel for terrain visualization"""
    bl_label = "Terrain Visualization"
    bl_idname = "GEODB_PT_terrain_visualization"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        geodb = scene.geodb

        # Check if project is selected
        if not geodb.selected_project_id:
            layout.label(text="Please select a project first", icon='ERROR')
            return

        # Show progress bar if operation is running
        if geodb.import_active:
            box = layout.box()
            box.label(text="Import in Progress...", icon='INFO')

            # Progress bar
            row = box.row()
            row.progress(
                factor=geodb.import_progress,
                type='BAR',
                text=geodb.import_status
            )

            box.label(text="Press ESC to cancel", icon='CANCEL')

            # Disable all import buttons while operation running
            layout.enabled = False

        # Import terrain button with options
        row = layout.row()
        row.operator("geodb.import_terrain", text="Import Terrain", icon='IMPORT')

        layout.label(text="Import DEM mesh with texture overlay", icon='INFO')

        # Check if terrain mesh is selected - show texture switching option
        obj = context.active_object
        if obj and obj.get('geodb_terrain_resolution'):
            layout.separator()
            col = layout.column(align=True)
            col.label(text="Selected Terrain:", icon='MESH_PLANE')
            col.label(text=f"  {obj.name}")

            # Show current texture
            current_texture = obj.get('geodb_active_texture', 'unknown')
            col.label(text=f"  Texture: {current_texture.title()}")

            # Show available textures
            has_satellite = obj.get('geodb_satellite_texture_url') is not None
            has_topo = obj.get('geodb_topo_texture_url') is not None

            if has_satellite or has_topo:
                row = col.row()
                row.operator("geodb.switch_terrain_texture", text="Change Texture", icon='TEXTURE')


# ============================================================================
# REGISTRATION
# ============================================================================

classes = (
    GEODB_OT_LoadAssayConfig,
    GEODB_OT_LoadLithologyConfig,
    GEODB_OT_LoadAlterationConfig,
    GEODB_OT_LoadMineralizationConfig,
    GEODB_OT_VisualizeAssays,
    GEODB_PT_DrillVisualizationPanel,
    GEODB_PT_TerrainVisualizationPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)