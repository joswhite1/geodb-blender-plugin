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
from ..utils.interval_visualization import (
    create_interval_tube,
    apply_material_to_interval,
    get_color_for_lithology,
    get_color_for_alteration
)
from ..utils.cylinder_mesh import create_sample_cylinder_mesh, hex_to_rgb
from ..utils.object_properties import GeoDBObjectProperties


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_lithology_sets_enum(self, context):
    """Dynamic enum callback for lithology sets"""
    items = [('0', 'All Sets', 'Visualize all lithology sets combined', 0)]

    scene = context.scene
    if not hasattr(scene, 'geodb') or not scene.geodb.selected_project_id:
        return items

    try:
        project_id = int(scene.geodb.selected_project_id)
        success, sets = GeoDBData.get_lithology_sets(project_id)

        if success and sets:
            for idx, lith_set in enumerate(sets):
                set_id = str(lith_set.get('id', idx))
                set_name = lith_set.get('name', f'Set {idx + 1}')
                items.append((set_id, set_name, f'Visualize {set_name}', idx + 1))
    except Exception as e:
        print(f"Error fetching lithology sets: {e}")

    return items


def get_alteration_sets_enum(self, context):
    """Dynamic enum callback for alteration sets"""
    items = [('0', 'All Sets', 'Visualize all alteration sets combined', 0)]

    scene = context.scene
    if not hasattr(scene, 'geodb') or not scene.geodb.selected_project_id:
        return items

    try:
        project_id = int(scene.geodb.selected_project_id)
        success, sets = GeoDBData.get_alteration_sets(project_id)

        if success and sets:
            for idx, alt_set in enumerate(sets):
                set_id = str(alt_set.get('id', idx))
                set_name = alt_set.get('name', f'Set {idx + 1}')
                items.append((set_id, set_name, f'Visualize {set_name}', idx + 1))
    except Exception as e:
        print(f"Error fetching alteration sets: {e}")

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

        # Fetch config details
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
        # Get set name from the cached data
        project_id = int(props.selected_project_id)
        success, sets = GeoDBData.get_lithology_sets(project_id)
        if success and sets:
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
            # Get set name from the cached data
            project_id = int(props.selected_project_id)
            success, sets = GeoDBData.get_alteration_sets(project_id)
            if success and sets:
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
            # Get set name from the cached data
            project_id = int(props.selected_project_id)
            success, sets = GeoDBData.get_mineralization_sets(project_id)
            if success and sets:
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
        # COPIED FROM OLD WORKING CODE (modal_assay_visualization.py)
        scene = context.scene
        props = scene.geodb

        # Validate selection
        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        if not hasattr(props, 'selected_assay_config_id') or props.selected_assay_config_id <= 0:
            self.report({'ERROR'}, "No assay configuration loaded. Please load a configuration first.")
            return {'CANCELLED'}

        try:
            project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        selected_config_id = props.selected_assay_config_id
        project_name = props.selected_project_name or f"Project_{project_id}"

        # Fetch assay configuration details
        print(f"\n=== Plotting Assay Data for {project_name} ===")
        success, configs = GeoDBData.get_assay_range_configurations(project_id)
        if not success:
            self.report({'ERROR'}, "Failed to fetch assay configurations")
            return {'CANCELLED'}

        config = next((c for c in configs if c.get('id') == selected_config_id), None)
        if not config:
            self.report({'ERROR'}, f"Configuration ID {selected_config_id} not found")
            return {'CANCELLED'}

        config_name = config.get('name', 'Assay')
        element = config.get('element', 'Unknown')
        units = config.get('units_display', config.get('units', ''))
        ranges = config.get('ranges', [])
        default_color = config.get('default_color', '#CCCCCC')

        print(f"Configuration: {config_name} ({element} in {units})")
        print(f"Ranges: {len(ranges)}")

        # Load diameter overrides from persistent storage
        import json
        try:
            diameter_overrides = json.loads(props.assay_diameter_overrides)
            print(f"Loaded {len(diameter_overrides)} diameter overrides from .blend file")
        except (json.JSONDecodeError, AttributeError):
            diameter_overrides = {}
            print("No diameter overrides found, using API defaults")

        # Fetch drill samples with desurveyed coordinates
        # v1.4: Pass assay_config_id so server applies the configuration
        print(f"Fetching drill samples...")
        success, samples_by_hole = GeoDBData.get_all_samples_for_project(project_id, assay_config_id=selected_config_id)
        if not success or not samples_by_hole:
            self.report({'WARNING'}, "No drill samples found for project")
            return {'CANCELLED'}

        total_samples = sum(len(v) for v in samples_by_hole.values())
        print(f"Fetched {total_samples} samples across {len(samples_by_hole)} holes")

        # Create master collection
        master_collection = bpy.data.collections.new(config_name)
        bpy.context.scene.collection.children.link(master_collection)

        total_meshes_created = 0
        total_skipped = 0
        holes_with_meshes = 0

        all_holes_data = []

        # Process each drill hole
        for hole_id, hole_samples in samples_by_hole.items():
            if not hole_samples:
                continue

            hole_name = None
            sample = hole_samples[0]
            bhid = sample.get('bhid')

            if isinstance(bhid, dict):
                hole_name = bhid.get('hole_id') or bhid.get('name')
            elif isinstance(bhid, str):
                hole_name = bhid

            if not hole_name:
                hole_name = f'Hole_{hole_id}'

            print(f"\nProcessing {hole_name}: {len(hole_samples)} samples")

            hole_collection = bpy.data.collections.new(hole_name)
            master_collection.children.link(hole_collection)

            hole_meshes = []

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
                            "element": elem_name,
                            "value": elem.get('value'),
                            "units": method_unit.get('units') if isinstance(method_unit, dict) else None,
                            "method_name": method_unit.get('method') if isinstance(method_unit, dict) else None,
                            "detection_limit": method_unit.get('detection_limit') if isinstance(method_unit, dict) else None,
                            "upper_limit": method_unit.get('upper_limit') if isinstance(method_unit, dict) else None,
                        }

                if assay_value is None:
                    total_skipped += 1
                    if total_skipped == 1:
                        print(f"  Debug: First sample elements: {elements[:1] if elements else 'No elements'}")
                        print(f"  Debug: Looking for element: {element}")
                    continue

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
                    size = matching_range.get('size', 2)  # API default
                    label = matching_range.get('label', '')

                    # Check for diameter override (persisted in .blend file)
                    override_key = f"config_{selected_config_id}_range_{matching_range_idx}"
                    if override_key in diameter_overrides:
                        size = diameter_overrides[override_key]

                xyz_from = sample.get('xyz_from')
                xyz_to = sample.get('xyz_to')
                from_depth = sample.get('from_depth', 0)
                to_depth = sample.get('to_depth', 0)

                if not xyz_from or not xyz_to:
                    print(f"  Warning: Sample {sample.get('id')} missing desurveyed coordinates")
                    total_skipped += 1
                    continue

                try:
                    mesh_name = f"{hole_name}_{from_depth:.1f}-{to_depth:.1f}_{element}_{assay_value:.2f}{assay_unit}"

                    assay_metadata = {
                        'active_assay_name': assay_name,
                        'active_config_name': config_name,
                        'active_assay_element': element,
                        'active_assay_value': assay_value,
                        'active_assay_unit': assay_unit,
                        'all_elements': all_assay_data,
                        'sample_id': sample.get('id'),
                    }

                    mesh_obj = create_sample_cylinder_mesh(
                        xyz_from=tuple(xyz_from) if isinstance(xyz_from, (list, tuple)) else xyz_from,
                        xyz_to=tuple(xyz_to) if isinstance(xyz_to, (list, tuple)) else xyz_to,
                        diameter=float(size),
                        color_hex=color_hex,
                        name=mesh_name,
                        material_name=f"Assay_{element}_{label}",
                        assay_metadata=assay_metadata
                    )

                    hole_meshes.append({
                        'obj': mesh_obj,
                        'hole_name': hole_name,
                        'hole_id': hole_id,
                        'element': element,
                        'assay_value': assay_value,
                        'assay_unit': assay_unit,
                        'label': label,
                        'from_depth': from_depth,
                        'to_depth': to_depth,
                    })

                except Exception as e:
                    print(f"  Error creating mesh for sample: {e}")
                    import traceback
                    traceback.print_exc()
                    total_skipped += 1
                    continue

            if hole_meshes:
                all_holes_data.append({
                    'hole_name': hole_name,
                    'hole_collection': hole_collection,
                    'meshes': hole_meshes,
                })
                holes_with_meshes += 1
                total_meshes_created += len(hole_meshes)
                print(f"  Prepared {len(hole_meshes)} meshes for {hole_name}")

        if total_meshes_created == 0:
            self.report(
                {'ERROR'},
                f"No meshes created. No samples with {element} data. (Skipped: {total_skipped})"
            )
            return {'CANCELLED'}

        print(f"\nBatch linking and processing {total_meshes_created} meshes...")

        for hole_data in all_holes_data:
            hole_collection = hole_data['hole_collection']
            for mesh_data in hole_data['meshes']:
                mesh_obj = mesh_data['obj']

                for coll in mesh_obj.users_collection:
                    coll.objects.unlink(mesh_obj)
                hole_collection.objects.link(mesh_obj)

                mesh_obj['geodb_visualization'] = True
                mesh_obj['geodb_type'] = 'assay_sample'
                mesh_obj['hole_name'] = mesh_data['hole_name']
                mesh_obj['active_range_label'] = mesh_data['label']

        self.report(
            {'INFO'},
            f"Created {total_meshes_created} meshes in {holes_with_meshes} holes (Skipped: {total_skipped})"
        )

        return {'FINISHED'}


# DEPRECATED: This operator is not currently used. The active lithology visualization
# operator is in interval_visualization_panel.py. This code is kept for reference only.
class GEODB_OT_VisualizeLithology(Operator):
    """DEPRECATED - Visualize lithology intervals as curved tubes (use interval_visualization_panel.py instead)"""
    bl_idname = "geodb.visualize_lithology_deprecated"
    bl_label = "Visualize Lithology (Deprecated)"
    bl_description = "DEPRECATED - Use the operator in interval_visualization_panel.py instead"
    bl_options = {'REGISTER', 'UNDO'}

    set_selection: EnumProperty(
        name="Lithology Set",
        description="Select lithology set to visualize",
        items=get_lithology_sets_enum
    )

    tube_radius: FloatProperty(
        name="Tube Radius",
        description="Radius of the lithology tubes",
        default=0.15,
        min=0.01,
        max=2.0
    )

    tube_resolution: IntProperty(
        name="Resolution",
        description="Number of vertices around tube circumference",
        default=8,
        min=3,
        max=32
    )

    def execute(self, context):
        scene = context.scene
        print("DEBUG: ========== GEODB_OT_VisualizeLithology.execute() CALLED ==========")
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        project_id = int(props.selected_project_id)
        selected_set_id = int(self.set_selection)

        # Load diameter overrides from persistent storage
        import json
        try:
            diameter_overrides = json.loads(props.lithology_diameter_overrides)
        except (json.JSONDecodeError, AttributeError):
            diameter_overrides = {}

        if selected_set_id > 0:
            use_set_id = selected_set_id
            set_name = f"set_{selected_set_id}"

            success, lith_sets = GeoDBData.get_lithology_sets(project_id)
            if success and lith_sets:
                for lith_set in lith_sets:
                    if lith_set.get('id') == selected_set_id:
                        set_name = lith_set.get('name', set_name)
                        break
        else:
            set_name = 'all'
            use_set_id = None

        # Fetch data
        success, collars = GeoDBData.get_drill_holes(project_id)
        if not success or not collars:
            self.report({'ERROR'}, "Failed to fetch drill collars")
            return {'CANCELLED'}

        success, lithology_data = GeoDBData.get_lithologies_for_project(project_id, use_set_id)
        if not success or not lithology_data:
            self.report({'ERROR'}, "Failed to fetch lithology data")
            return {'CANCELLED'}

        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)
        if not success:
            self.report({'ERROR'}, "Failed to fetch drill traces")
            return {'CANCELLED'}

        # Create main collection
        main_collection_name = f"lithology_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            for obj in main_collection.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        total_intervals = 0
        lithology_collections = {}

        # Build name-to-ID mapping
        collar_id_by_name = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_id_by_name[hole_name] = hole_id

        # Process each hole
        for hole_name, hole_lithologies in lithology_data.items():
            if not hole_lithologies:
                continue

            hole_id = collar_id_by_name.get(hole_name)
            if not hole_id:
                continue

            trace_summary = traces_by_hole.get(hole_id)
            if not trace_summary:
                continue

            trace_id = trace_summary.get('id')
            success, trace_detail = GeoDBData.get_drill_trace_detail(trace_id)
            if not success:
                continue

            trace_data = trace_detail.get('trace_data', {})
            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                continue

            # Create tubes for intervals
            for lith_interval in hole_lithologies:
                depth_from = lith_interval.get('depth_from')
                depth_to = lith_interval.get('depth_to')

                if depth_from is None or depth_to is None:
                    continue

                lithology = lith_interval.get('lithology', {})
                if isinstance(lithology, dict):
                    lith_name = lithology.get('name', 'Unknown')
                    lith_color = lithology.get('color', '#CCCCCC')
                    print(f"DEBUG: Lithology={lith_name}, Color={lith_color}, Full dict={lithology}")
                elif isinstance(lithology, str):
                    lith_name = lithology
                    lith_color = '#CCCCCC'
                    print(f"DEBUG: Lithology string={lith_name}, using default color")
                else:
                    lith_name = 'Unknown'
                    lith_color = '#CCCCCC'
                    print(f"DEBUG: Unknown lithology type={type(lithology)}")

                if lith_name not in lithology_collections:
                    lith_collection = bpy.data.collections.new(lith_name)
                    main_collection.children.link(lith_collection)
                    lithology_collections[lith_name] = lith_collection
                else:
                    lith_collection = lithology_collections[lith_name]

                # Get diameter override for this lithology type
                override_key = f"set_{selected_set_id}_lith_{lith_name}"
                tube_radius = diameter_overrides.get(override_key, self.tube_radius)

                tube_name = f"{hole_name}_{lith_name}_{depth_from}_{depth_to}"
                tube_obj = create_interval_tube(
                    trace_depths=trace_depths,
                    trace_coords=trace_coords,
                    depth_from=depth_from,
                    depth_to=depth_to,
                    radius=tube_radius,
                    resolution=self.tube_resolution,
                    name=tube_name
                )

                if tube_obj:
                    lith_collection.objects.link(tube_obj)

                    # Use API color instead of hash-based color
                    color = hex_to_rgba(lith_color)
                    print(f"DEBUG: Applying color {color} (from hex {lith_color}) to tube {tube_name}")
                    print(f"DEBUG: BEFORE apply_material_to_interval - tube_obj={tube_obj}, tube_obj.data={tube_obj.data if tube_obj else 'N/A'}")
                    apply_material_to_interval(tube_obj, color)
                    print(f"DEBUG: AFTER apply_material_to_interval - completed successfully")

                    interval_props = {
                        "bhid": hole_id,
                        "hole_name": hole_name,
                        "depth_from": depth_from,
                        "depth_to": depth_to,
                        "lithology": lith_name,
                        "lithology_set": set_name,
                        "notes": lith_interval.get('notes', ''),
                    }

                    GeoDBObjectProperties.tag_drill_sample(tube_obj, interval_props)

                    tube_obj['geodb_visualization'] = True
                    tube_obj['geodb_type'] = 'lithology_interval'
                    tube_obj['geodb_hole_name'] = hole_name
                    tube_obj['geodb_lithology'] = lith_name

                    total_intervals += 1

        self.report({'INFO'}, f"Created {total_intervals} lithology intervals in {len(lithology_collections)} types")
        return {'FINISHED'}


# DEPRECATED: This operator is not currently used. The active alteration visualization
# operator is in interval_visualization_panel.py. This code is kept for reference only.
class GEODB_OT_VisualizeAlteration(Operator):
    """DEPRECATED - Visualize alteration intervals as curved tubes (use interval_visualization_panel.py instead)"""
    bl_idname = "geodb.visualize_alteration_deprecated"
    bl_label = "Visualize Alteration (Deprecated)"
    bl_description = "DEPRECATED - Use the operator in interval_visualization_panel.py instead"
    bl_options = {'REGISTER', 'UNDO'}

    set_selection: EnumProperty(
        name="Alteration Set",
        description="Select alteration set to visualize",
        items=get_alteration_sets_enum
    )

    tube_radius: FloatProperty(
        name="Tube Radius",
        description="Radius of the alteration tubes",
        default=0.12,
        min=0.01,
        max=2.0
    )

    tube_resolution: IntProperty(
        name="Resolution",
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

        project_id = int(props.selected_project_id)
        selected_set_id = int(self.set_selection)

        if selected_set_id > 0:
            use_set_id = selected_set_id
            set_name = f"set_{selected_set_id}"

            success, alt_sets = GeoDBData.get_alteration_sets(project_id)
            if success and alt_sets:
                for alt_set in alt_sets:
                    if alt_set.get('id') == selected_set_id:
                        set_name = alt_set.get('name', set_name)
                        break
        else:
            set_name = 'all'
            use_set_id = None

        # Fetch data
        success, collars = GeoDBData.get_drill_holes(project_id)
        if not success or not collars:
            self.report({'ERROR'}, "Failed to fetch drill collars")
            return {'CANCELLED'}

        success, alteration_data = GeoDBData.get_alterations_for_project(project_id, use_set_id)
        if not success or not alteration_data:
            self.report({'ERROR'}, "Failed to fetch alteration data")
            return {'CANCELLED'}

        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)
        if not success:
            self.report({'ERROR'}, "Failed to fetch drill traces")
            return {'CANCELLED'}

        # Create main collection
        main_collection_name = f"alteration_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            for obj in main_collection.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        total_intervals = 0
        alteration_collections = {}

        # Build name-to-ID mapping
        collar_id_by_name = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_id_by_name[hole_name] = hole_id

        # Process each hole
        for hole_name, hole_alterations in alteration_data.items():
            if not hole_alterations:
                continue

            hole_id = collar_id_by_name.get(hole_name)
            if not hole_id:
                continue

            trace_summary = traces_by_hole.get(hole_id)
            if not trace_summary:
                continue

            trace_id = trace_summary.get('id')
            success, trace_detail = GeoDBData.get_drill_trace_detail(trace_id)
            if not success:
                continue

            trace_data = trace_detail.get('trace_data', {})
            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                continue

            # Create tubes for intervals
            for alt_interval in hole_alterations:
                depth_from = alt_interval.get('depth_from')
                depth_to = alt_interval.get('depth_to')

                if depth_from is None or depth_to is None:
                    continue

                alteration = alt_interval.get('alteration', {})
                if isinstance(alteration, dict):
                    alt_name = alteration.get('name', 'Unknown')
                elif isinstance(alteration, str):
                    alt_name = alteration
                else:
                    alt_name = 'Unknown'

                if alt_name not in alteration_collections:
                    alt_collection = bpy.data.collections.new(alt_name)
                    main_collection.children.link(alt_collection)
                    alteration_collections[alt_name] = alt_collection
                else:
                    alt_collection = alteration_collections[alt_name]

                tube_name = f"{hole_name}_{alt_name}_{depth_from}_{depth_to}"
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
                    alt_collection.objects.link(tube_obj)

                    color = get_color_for_alteration(alt_name)
                    apply_material_to_interval(tube_obj, color)

                    interval_props = {
                        "bhid": hole_id,
                        "hole_name": hole_name,
                        "depth_from": depth_from,
                        "depth_to": depth_to,
                        "alteration": alt_name,
                        "alteration_set": set_name,
                        "notes": alt_interval.get('notes', ''),
                    }

                    GeoDBObjectProperties.tag_drill_sample(tube_obj, interval_props)

                    tube_obj['geodb_visualization'] = True
                    tube_obj['geodb_type'] = 'alteration_interval'
                    tube_obj['geodb_hole_name'] = hole_name
                    tube_obj['geodb_alteration'] = alt_name

                    total_intervals += 1

        self.report({'INFO'}, f"Created {total_intervals} alteration intervals in {len(alteration_collections)} types")
        return {'FINISHED'}


# DEPRECATED: Clear Visualizations Operator
# Commented out - not currently needed
# class GEODB_OT_ClearVisualizations(Operator):
#     """Clear all drill visualizations"""
#     bl_idname = "geodb.clear_visualizations"
#     bl_label = "Clear All"
#     bl_description = "Remove all drill hole visualizations from the scene"
#
#     def execute(self, context):
#         # Remove all geodb visualization objects
#         removed = 0
#         for obj in list(bpy.data.objects):
#             if 'geodb_visualization' in obj:
#                 bpy.data.objects.remove(obj, do_unlink=True)
#                 removed += 1
#
#         self.report({'INFO'}, f"Removed {removed} visualization objects")
#         return {'FINISHED'}


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

        # Terrain Visualization
        box = layout.box()
        box.label(text="Terrain Visualization", icon='MESH_GRID')

        # Resolution selector
        row = box.row()
        row.label(text="Resolution:")
        row = box.row(align=True)
        op = row.operator("geodb.import_terrain", text="Very Low (Fast)")
        op.resolution = 'very_low'
        op = row.operator("geodb.import_terrain", text="Low")
        op.resolution = 'low'
        op = row.operator("geodb.import_terrain", text="Medium")
        op.resolution = 'medium'

        box.label(text="Downloads DEM mesh with satellite texture", icon='INFO')

        # # Actions
        # box = layout.box()
        # box.label(text="Actions", icon='PLAY')
        # box.operator("geodb.clear_visualizations", icon='TRASH')


# ============================================================================
# REGISTRATION
# ============================================================================

classes = (
    GEODB_OT_LoadAssayConfig,
    GEODB_OT_LoadLithologyConfig,
    GEODB_OT_LoadAlterationConfig,
    GEODB_OT_LoadMineralizationConfig,
    GEODB_OT_VisualizeAssays,
    # GEODB_OT_VisualizeLithology,  # DEPRECATED - Registered in interval_visualization_panel.py instead
    # GEODB_OT_VisualizeAlteration,  # DEPRECATED - Registered in interval_visualization_panel.py instead
    # GEODB_OT_ClearVisualizations,  # DEPRECATED - Not currently needed
    GEODB_PT_DrillVisualizationPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)