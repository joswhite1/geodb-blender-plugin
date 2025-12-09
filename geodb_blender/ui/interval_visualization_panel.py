"""
UI panel for visualizing lithology and alteration intervals.

This module provides the UI for selecting lithology/alteration sets
and visualizing them as curved tubes along drill holes.
"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import EnumProperty, FloatProperty, IntProperty, BoolProperty

from ..api.data import GeoDBData
from ..api.auth import get_api_client
from ..utils.interval_visualization import (
    create_interval_tube,
    apply_material_to_interval,
    get_color_for_lithology,
    get_color_for_alteration
)
from ..utils.object_properties import GeoDBObjectProperties
from .drill_visualization_panel import adjust_view_to_objects


def get_lithology_sets_enum(self, context):
    """Dynamic enum callback for lithology sets"""
    items = [('-1', 'All Sets', 'Visualize all lithology sets', 0)]

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
    items = [('-1', 'All Sets', 'Visualize all alteration sets', 0)]

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


def get_mineralization_sets_enum(self, context):
    """Dynamic enum callback for mineralization sets"""
    items = [('-1', 'All Sets', 'Visualize all mineralization sets', 0)]

    scene = context.scene
    if not hasattr(scene, 'geodb') or not scene.geodb.selected_project_id:
        return items

    try:
        project_id = int(scene.geodb.selected_project_id)
        success, sets = GeoDBData.get_mineralization_sets(project_id)

        if success and sets:
            for idx, min_set in enumerate(sets):
                set_id = str(min_set.get('id', idx))
                set_name = min_set.get('name', f'Set {idx + 1}')
                items.append((set_id, set_name, f'Visualize {set_name}', idx + 1))
    except Exception as e:
        print(f"Error fetching mineralization sets: {e}")

    return items


class GEODB_OT_VisualizeLithology(Operator):
    """Visualize lithology intervals as curved tubes"""
    bl_idname = "geodb.visualize_lithology"
    bl_label = "Visualize Lithology"
    bl_description = "Create curved tube visualization of lithology intervals along drill holes"
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
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        project_id = int(props.selected_project_id)

        # Determine set to use based on selection
        selected_set_id = int(self.set_selection)

        if selected_set_id > 0:
            # User selected a specific set
            use_set_id = selected_set_id
            set_name = f"set_{selected_set_id}"

            # Try to get actual name
            success, lith_sets = GeoDBData.get_lithology_sets(project_id)
            if success and lith_sets:
                for lith_set in lith_sets:
                    if lith_set.get('id') == selected_set_id:
                        set_name = lith_set.get('name', set_name)
                        break
        else:
            # All sets
            set_name = 'all'
            use_set_id = None

        self.report({'INFO'}, f"Using lithology set: {set_name}")

        # Fetch drill collars
        self.report({'INFO'}, "Fetching drill collars...")
        success, collars = GeoDBData.get_drill_holes(project_id)

        if not success or not collars:
            self.report({'ERROR'}, "Failed to fetch drill collars")
            return {'CANCELLED'}

        # Fetch lithology data for all holes
        self.report({'INFO'}, "Fetching lithology data...")
        success, lithology_data = GeoDBData.get_lithologies_for_project(project_id, use_set_id)

        if not success:
            self.report({'ERROR'}, "Failed to fetch lithology data")
            return {'CANCELLED'}

        if not lithology_data:
            self.report({'WARNING'}, "No lithology data available")
            return {'CANCELLED'}


        # Fetch drill traces
        self.report({'INFO'}, "Fetching drill traces...")
        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)

        if not success:
            self.report({'ERROR'}, "Failed to fetch drill traces")
            return {'CANCELLED'}

        # Create main collection for this lithology set
        main_collection_name = f"lithology_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            # Clear existing objects
            for obj in main_collection.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        total_intervals = 0
        lithology_collections = {}
        created_objects = []  # Track created objects for view adjustment

        # Build name-to-ID mapping for collars
        collar_id_by_name = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_id_by_name[hole_name] = hole_id


        # Process each drill hole
        for hole_name, hole_lithologies in lithology_data.items():
            if not hole_lithologies:
                continue

            # Get collar ID from name
            hole_id = collar_id_by_name.get(hole_name)
            if not hole_id:
                print(f"WARNING: No collar found for hole name '{hole_name}'")
                continue

            # Get trace for this hole
            trace_summary = traces_by_hole.get(hole_id)
            if not trace_summary:
                print(f"WARNING: No trace found for hole {hole_name}")
                continue

            # Fetch full trace detail
            trace_id = trace_summary.get('id')
            success, trace_detail = GeoDBData.get_drill_trace_detail(trace_id)

            if not success:
                print(f"WARNING: Failed to fetch trace detail for hole {hole_name}")
                continue

            trace_data = trace_detail.get('trace_data', {})
            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                print(f"WARNING: No trace data for hole {hole_name}")
                continue

            # Create tubes for each lithology interval
            for lith_interval in hole_lithologies:
                try:
                    depth_from = lith_interval.get('depth_from')
                    depth_to = lith_interval.get('depth_to')

                    if depth_from is None or depth_to is None:
                        continue

                    # Get lithology type and color from API
                    lithology = lith_interval.get('lithology', {})
                    if isinstance(lithology, dict):
                        lith_name = lithology.get('name', 'Unknown')
                        lith_color = lithology.get('color', '#CCCCCC')
                    elif isinstance(lithology, str):
                        lith_name = lithology
                        lith_color = '#CCCCCC'
                    else:
                        lith_name = 'Unknown'
                        lith_color = '#CCCCCC'

                    # Create or get collection for this lithology type
                    if lith_name not in lithology_collections:
                        lith_collection = bpy.data.collections.new(lith_name)
                        main_collection.children.link(lith_collection)
                        lithology_collections[lith_name] = lith_collection
                    else:
                        lith_collection = lithology_collections[lith_name]

                    # Create tube for this interval
                    tube_name = f"{hole_name}_{lith_name}_{depth_from}_{depth_to}"
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
                        # Link directly to lithology collection (not scene collection)
                        lith_collection.objects.link(tube_obj)

                        # Apply color from API
                        from ..utils.cylinder_mesh import hex_to_rgba
                        color = hex_to_rgba(lith_color)
                        apply_material_to_interval(tube_obj, color, material_name=lith_name)

                        # Tag with metadata
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

                        # Backward compatibility tags
                        tube_obj['geodb_visualization'] = True
                        tube_obj['geodb_type'] = 'lithology_interval'
                        tube_obj['geodb_hole_name'] = hole_name
                        tube_obj['geodb_lithology'] = lith_name

                        created_objects.append(tube_obj)
                        total_intervals += 1

                except Exception as e:
                    print(f"ERROR creating lithology interval {depth_from}-{depth_to}m for {hole_name}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        # Auto-adjust view to newly created objects
        adjust_view_to_objects(context, created_objects)

        self.report({'INFO'}, f"Created {total_intervals} lithology interval tubes in {len(lithology_collections)} lithology types")
        return {'FINISHED'}


class GEODB_OT_VisualizeAlteration(Operator):
    """Visualize alteration intervals as curved tubes"""
    bl_idname = "geodb.visualize_alteration"
    bl_label = "Visualize Alteration"
    bl_description = "Create curved tube visualization of alteration intervals along drill holes"
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

        # Determine set to use based on selection
        selected_set_id = int(self.set_selection)

        if selected_set_id > 0:
            # User selected a specific set
            use_set_id = selected_set_id
            set_name = f"set_{selected_set_id}"

            # Try to get actual name
            success, alt_sets = GeoDBData.get_alteration_sets(project_id)
            if success and alt_sets:
                for alt_set in alt_sets:
                    if alt_set.get('id') == selected_set_id:
                        set_name = alt_set.get('name', set_name)
                        break
        else:
            # All sets
            set_name = 'all'
            use_set_id = None

        self.report({'INFO'}, f"Using alteration set: {set_name}")

        # Fetch drill collars
        self.report({'INFO'}, "Fetching drill collars...")
        success, collars = GeoDBData.get_drill_holes(project_id)

        if not success or not collars:
            self.report({'ERROR'}, "Failed to fetch drill collars")
            return {'CANCELLED'}

        # Fetch alteration data for all holes
        self.report({'INFO'}, "Fetching alteration data...")
        success, alteration_data = GeoDBData.get_alterations_for_project(project_id, use_set_id)

        if not success:
            self.report({'ERROR'}, "Failed to fetch alteration data")
            return {'CANCELLED'}

        if not alteration_data:
            self.report({'WARNING'}, "No alteration data available")
            return {'CANCELLED'}


        # Fetch drill traces
        self.report({'INFO'}, "Fetching drill traces...")
        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)

        if not success:
            self.report({'ERROR'}, "Failed to fetch drill traces")
            return {'CANCELLED'}

        # Create main collection for this alteration set
        main_collection_name = f"alteration_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            # Clear existing objects
            for obj in main_collection.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        total_intervals = 0
        alteration_collections = {}
        created_objects = []  # Track created objects for view adjustment

        # Build name-to-ID mapping for collars
        collar_id_by_name = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_id_by_name[hole_name] = hole_id


        # Process each drill hole
        for hole_name, hole_alterations in alteration_data.items():
            if not hole_alterations:
                continue

            # Get collar ID from name
            hole_id = collar_id_by_name.get(hole_name)
            if not hole_id:
                print(f"WARNING: No collar found for hole name '{hole_name}'")
                continue

            # Get trace for this hole
            trace_summary = traces_by_hole.get(hole_id)
            if not trace_summary:
                print(f"WARNING: No trace found for hole {hole_name}")
                continue

            # Fetch full trace detail
            trace_id = trace_summary.get('id')
            success, trace_detail = GeoDBData.get_drill_trace_detail(trace_id)

            if not success:
                print(f"WARNING: Failed to fetch trace detail for hole {hole_name}")
                continue

            trace_data = trace_detail.get('trace_data', {})
            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                print(f"WARNING: No trace data for hole {hole_name}")
                continue

            # Create tubes for each alteration interval
            for alt_interval in hole_alterations:
                try:
                    depth_from = alt_interval.get('depth_from')
                    depth_to = alt_interval.get('depth_to')

                    if depth_from is None or depth_to is None:
                        continue

                    # Get alteration type and color from API
                    alteration = alt_interval.get('alteration', {})
                    if isinstance(alteration, dict):
                        alt_name = alteration.get('name', 'Unknown')
                        alt_color = alteration.get('color', '#CCCCCC')
                    elif isinstance(alteration, str):
                        alt_name = alteration
                        alt_color = '#CCCCCC'
                    else:
                        alt_name = 'Unknown'
                        alt_color = '#CCCCCC'

                    # Create or get collection for this alteration type
                    if alt_name not in alteration_collections:
                        alt_collection = bpy.data.collections.new(alt_name)
                        main_collection.children.link(alt_collection)
                        alteration_collections[alt_name] = alt_collection
                    else:
                        alt_collection = alteration_collections[alt_name]

                    # Create tube for this interval
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
                        # Link directly to alteration collection (not scene collection)
                        alt_collection.objects.link(tube_obj)

                        # Apply color from API
                        from ..utils.cylinder_mesh import hex_to_rgba
                        color = hex_to_rgba(alt_color)
                        apply_material_to_interval(tube_obj, color, material_name=alt_name, material_prefix="Alteration")

                        # Tag with metadata
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

                        # Backward compatibility tags
                        tube_obj['geodb_visualization'] = True
                        tube_obj['geodb_type'] = 'alteration_interval'
                        tube_obj['geodb_hole_name'] = hole_name
                        tube_obj['geodb_alteration'] = alt_name

                        created_objects.append(tube_obj)
                        total_intervals += 1

                except Exception as e:
                    print(f"ERROR creating alteration interval {depth_from}-{depth_to}m for {hole_name}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        # Auto-adjust view to newly created objects
        adjust_view_to_objects(context, created_objects)

        self.report({'INFO'}, f"Created {total_intervals} alteration interval tubes in {len(alteration_collections)} alteration types")
        return {'FINISHED'}


class GEODB_OT_VisualizeMineralization(Operator):
    """Visualize mineralization intervals as curved tubes"""
    bl_idname = "geodb.visualize_mineralization"
    bl_label = "Visualize Mineralization"
    bl_description = "Create curved tube visualization of mineralization intervals along drill holes"
    bl_options = {'REGISTER', 'UNDO'}

    set_selection: EnumProperty(
        name="Mineralization Set",
        description="Select mineralization set to visualize",
        items=get_mineralization_sets_enum
    )

    tube_radius: FloatProperty(
        name="Tube Radius",
        description="Radius of the mineralization tubes",
        default=0.18,
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

        # Determine set to use based on selection
        selected_set_id = int(self.set_selection)

        if selected_set_id > 0:
            # User selected a specific set
            use_set_id = selected_set_id
            set_name = f"set_{selected_set_id}"

            # Try to get actual name
            success, min_sets = GeoDBData.get_mineralization_sets(project_id)
            if success and min_sets:
                for min_set in min_sets:
                    if min_set.get('id') == selected_set_id:
                        set_name = min_set.get('name', set_name)
                        break
        else:
            # All sets
            set_name = 'all'
            use_set_id = None

        self.report({'INFO'}, f"Using mineralization set: {set_name}")

        # Fetch drill collars
        self.report({'INFO'}, "Fetching drill collars...")
        success, collars = GeoDBData.get_drill_holes(project_id)

        if not success or not collars:
            self.report({'ERROR'}, "Failed to fetch drill collars")
            return {'CANCELLED'}

        # Fetch mineralization data for all holes
        self.report({'INFO'}, "Fetching mineralization data...")
        success, mineralization_data = GeoDBData.get_mineralizations_for_project(project_id, use_set_id)

        if not success:
            self.report({'ERROR'}, "Failed to fetch mineralization data")
            return {'CANCELLED'}

        if not mineralization_data:
            self.report({'WARNING'}, "No mineralization data available")
            return {'CANCELLED'}


        # Fetch drill traces
        self.report({'INFO'}, "Fetching drill traces...")
        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)

        if not success:
            self.report({'ERROR'}, "Failed to fetch drill traces")
            return {'CANCELLED'}

        # Create main collection for this mineralization set
        main_collection_name = f"Mineralization_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            context.scene.collection.children.link(main_collection)

        # Process each mineralization assemblage type
        mineralization_collections = {}
        total_intervals = 0
        created_objects = []  # Track created objects for view adjustment

        for hole_name, min_intervals in mineralization_data.items():
            print(f"Processing mineralization intervals for {hole_name}: {len(min_intervals)} intervals")

            # Get collar coordinates
            collar_coords = None
            collar_id = None
            for collar in collars:
                if collar.get('hole_id') == hole_name:
                    from ..api.data import extract_collar_coordinates
                    collar_coords = extract_collar_coordinates(collar)
                    collar_id = collar.get('id')
                    break

            if collar_coords is None:
                print(f"WARNING: No collar found for hole {hole_name}")
                continue

            # Get traces for this hole
            traces = traces_by_hole.get(hole_name)
            if not traces or len(traces) < 2:
                print(f"WARNING: Not enough trace points for hole {hole_name}")
                continue

            # Process each mineralization interval
            for min_interval in min_intervals:
                try:
                    depth_from = min_interval.get('depth_from')
                    depth_to = min_interval.get('depth_to')

                    if depth_from is None or depth_to is None:
                        print(f"WARNING: Missing depth data for interval in {hole_name}")
                        continue

                    # Extract assemblage info (contains color)
                    assemblage = min_interval.get('assemblage', {})
                    if isinstance(assemblage, dict):
                        min_name = assemblage.get('name', 'Unknown')
                        min_color = assemblage.get('color', '#808080')
                    else:
                        min_name = 'Unknown'
                        min_color = '#808080'

                    # Get or create collection for this mineralization type
                    if min_name not in mineralization_collections:
                        min_collection_name = f"Mineralization_{min_name}"
                        if min_collection_name in bpy.data.collections:
                            min_collection = bpy.data.collections[min_collection_name]
                        else:
                            min_collection = bpy.data.collections.new(min_collection_name)
                            main_collection.children.link(min_collection)
                        mineralization_collections[min_name] = min_collection
                    else:
                        min_collection = mineralization_collections[min_name]

                    # Create the interval tube
                    tube_obj = create_interval_tube(
                        traces=traces,
                        depth_from=depth_from,
                        depth_to=depth_to,
                        radius=self.tube_radius,
                        resolution=self.tube_resolution,
                        name=f"{hole_name}_MIN_{depth_from}_{depth_to}_{min_name}"
                    )

                    if tube_obj:
                        # Link to collection
                        min_collection.objects.link(tube_obj)

                        # Apply color from API
                        from ..utils.cylinder_mesh import hex_to_rgba
                        color = hex_to_rgba(min_color)
                        apply_material_to_interval(tube_obj, color, material_name=min_name, material_prefix="Mineralization")

                        # Tag with metadata
                        interval_props = {
                            "bhid": collar_id,
                            "hole_name": hole_name,
                            "depth_from": depth_from,
                            "depth_to": depth_to,
                            "mineralization": min_name,
                            "mineralization_set": set_name,
                            "notes": min_interval.get('notes', ''),
                        }

                        GeoDBObjectProperties.tag_drill_sample(tube_obj, interval_props)

                        # Backward compatibility tags
                        tube_obj['geodb_visualization'] = True
                        tube_obj['geodb_type'] = 'mineralization_interval'
                        tube_obj['geodb_hole_name'] = hole_name
                        tube_obj['geodb_mineralization'] = min_name

                        created_objects.append(tube_obj)
                        total_intervals += 1

                except Exception as e:
                    print(f"ERROR creating mineralization interval {depth_from}-{depth_to}m for {hole_name}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        # Auto-adjust view to newly created objects
        adjust_view_to_objects(context, created_objects)

        self.report({'INFO'}, f"Created {total_intervals} mineralization interval tubes in {len(mineralization_collections)} mineralization types")
        return {'FINISHED'}


# ============================================================================
# DEPRECATED: Interval Visualization Panel
# This panel is NOT used - all visualization is done through the Drill Visualization panel
# The operators above (Lithology, Alteration, Mineralization) ARE still used by Drill Visualization
# ============================================================================
# class GEODB_PT_IntervalVisualizationPanel(Panel):
#     """DEPRECATED - Panel for visualizing lithology and alteration intervals
#
#     This panel is not used. Use the Drill Visualization panel instead.
#     The operators (VisualizeLithology, VisualizeAlteration, VisualizeMineralization)
#     are still active and called by the Drill Visualization panel.
#     """
#     bl_label = "Interval Visualization (DEPRECATED)"
#     bl_idname = "GEODB_PT_interval_visualization"
#     bl_space_type = 'VIEW_3D'
#     bl_region_type = 'UI'
#     bl_category = 'geoDB'
#     bl_options = {'DEFAULT_CLOSED'}
#
#     def draw(self, context):
#         layout = self.layout
#         scene = context.scene
#
#         if not hasattr(scene, 'geodb'):
#             layout.label(text="geoDB not initialized", icon='ERROR')
#             return
#
#         props = scene.geodb
#
#         # Check if authenticated
#         client = get_api_client()
#         if not client or not client.is_authenticated():
#             layout.label(text="Please login first", icon='ERROR')
#             return
#
#         # Check if project is selected
#         if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
#             layout.label(text="Please select a project", icon='INFO')
#             return
#
#         # Lithology section
#         box = layout.box()
#         box.label(text="Lithology Visualization", icon='MESH_CUBE')
#
#         # Show available sets info
#         try:
#             project_id = int(props.selected_project_id)
#             success, lith_sets = GeoDBData.get_lithology_sets(project_id)
#             if success and lith_sets:
#                 box.label(text=f"Available sets: {len(lith_sets)}", icon='INFO')
#         except:
#             pass
#
#         row = box.row()
#         row.operator("geodb.visualize_lithology", text="Visualize Lithology", icon='MESH_CYLINDER')
#         box.label(text="Select set in operator dialog", icon='HAND')
#
#         # Alteration section
#         box = layout.box()
#         box.label(text="Alteration Visualization", icon='MESH_TORUS')
#
#         # Show available sets info
#         try:
#             project_id = int(props.selected_project_id)
#             success, alt_sets = GeoDBData.get_alteration_sets(project_id)
#             if success and alt_sets:
#                 box.label(text=f"Available sets: {len(alt_sets)}", icon='INFO')
#         except:
#             pass
#
#         row = box.row()
#         row.operator("geodb.visualize_alteration", text="Visualize Alteration", icon='MESH_CYLINDER')
#         box.label(text="Select set in operator dialog", icon='HAND')
#
#         # Mineralization section
#         box = layout.box()
#         box.label(text="Mineralization Visualization", icon='MESH_ICOSPHERE')
#
#         # Show available sets info
#         try:
#             project_id = int(props.selected_project_id)
#             success, min_sets = GeoDBData.get_mineralization_sets(project_id)
#             if success and min_sets:
#                 box.label(text=f"Available sets: {len(min_sets)}", icon='INFO')
#         except:
#             pass
#
#         row = box.row()
#         row.operator("geodb.visualize_mineralization", text="Visualize Mineralization", icon='MESH_CYLINDER')
#         box.label(text="Select set in operator dialog", icon='HAND')


# Registration
# NOTE: The operators are still registered and used by Drill Visualization panel
# Only the panel itself is commented out
classes = (
    GEODB_OT_VisualizeLithology,        # ACTIVE - Used by Drill Visualization panel
    GEODB_OT_VisualizeAlteration,       # ACTIVE - Used by Drill Visualization panel
    GEODB_OT_VisualizeMineralization,   # ACTIVE - Used by Drill Visualization panel
    # GEODB_PT_IntervalVisualizationPanel,  # DEPRECATED - Panel not used
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
