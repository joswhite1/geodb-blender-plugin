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
from ..core.config_cache import ConfigCache
from ..core.data_cache import DrillDataCache, sync_deletions_from_fetch_result
from ..utils.interval_visualization import (
    create_interval_tube,
    apply_material_to_interval,
    get_color_for_lithology,
    get_color_for_alteration
)
from ..utils.object_properties import GeoDBObjectProperties
from .drill_visualization_panel import adjust_view_to_objects


def get_lithology_sets_enum(self, context):
    """
    Dynamic enum callback for lithology sets.

    Uses ConfigCache to avoid API calls during UI draw.
    Returns placeholder if cache is empty - user must load config first.
    """
    items = [('-1', 'All Sets', 'Visualize all lithology sets', 0)]

    scene = context.scene
    if not hasattr(scene, 'geodb') or not scene.geodb.selected_project_id:
        return items

    try:
        project_id = int(scene.geodb.selected_project_id)

        # Use cached data - NO API CALL
        sets = ConfigCache.get_lithology_sets()

        # Check if cache is valid for this project
        if not ConfigCache.is_valid(project_id) or not sets:
            # Return placeholder - user needs to load config first
            return [('-1', 'Load config first...', 'Click Load Configuration to populate this list', 0)]

        for idx, lith_set in enumerate(sets):
            set_id = str(lith_set.get('id', idx))
            set_name = lith_set.get('name', f'Set {idx + 1}')
            items.append((set_id, set_name, f'Visualize {set_name}', idx + 1))
    except Exception as e:
        print(f"Error in lithology enum callback: {e}")

    return items


def get_alteration_sets_enum(self, context):
    """
    Dynamic enum callback for alteration sets.

    Uses ConfigCache to avoid API calls during UI draw.
    Returns placeholder if cache is empty - user must load config first.
    """
    items = [('-1', 'All Sets', 'Visualize all alteration sets', 0)]

    scene = context.scene
    if not hasattr(scene, 'geodb') or not scene.geodb.selected_project_id:
        return items

    try:
        project_id = int(scene.geodb.selected_project_id)

        # Use cached data - NO API CALL
        sets = ConfigCache.get_alteration_sets()

        # Check if cache is valid for this project
        if not ConfigCache.is_valid(project_id) or not sets:
            # Return placeholder - user needs to load config first
            return [('-1', 'Load config first...', 'Click Load Configuration to populate this list', 0)]

        for idx, alt_set in enumerate(sets):
            set_id = str(alt_set.get('id', idx))
            set_name = alt_set.get('name', f'Set {idx + 1}')
            items.append((set_id, set_name, f'Visualize {set_name}', idx + 1))
    except Exception as e:
        print(f"Error in alteration enum callback: {e}")

    return items


def get_mineralization_sets_enum(self, context):
    """
    Dynamic enum callback for mineralization sets.

    Uses ConfigCache to avoid API calls during UI draw.
    Returns placeholder if cache is empty - user must load config first.
    """
    items = [('-1', 'All Sets', 'Visualize all mineralization sets', 0)]

    scene = context.scene
    if not hasattr(scene, 'geodb') or not scene.geodb.selected_project_id:
        return items

    try:
        project_id = int(scene.geodb.selected_project_id)

        # Use cached data - NO API CALL
        sets = ConfigCache.get_mineralization_sets()

        # Check if cache is valid for this project
        if not ConfigCache.is_valid(project_id) or not sets:
            # Return placeholder - user needs to load config first
            return [('-1', 'Load config first...', 'Click Load Configuration to populate this list', 0)]

        for idx, min_set in enumerate(sets):
            set_id = str(min_set.get('id', idx))
            set_name = min_set.get('name', f'Set {idx + 1}')
            items.append((set_id, set_name, f'Visualize {set_name}', idx + 1))
    except Exception as e:
        print(f"Error in mineralization enum callback: {e}")

    return items


class GEODB_OT_VisualizeLithology(Operator):
    """Visualize lithology intervals as curved tubes (async with progress)"""
    bl_idname = "geodb.visualize_lithology"
    bl_label = "Visualize Lithology"
    bl_description = "Create curved tube visualization of lithology intervals along drill holes"
    bl_options = {'REGISTER', 'UNDO'}

    # Multi-stage progress tracking
    _stages = [
        ('Fetching collars', 0.10),
        ('Fetching lithology', 0.30),
        ('Fetching traces', 0.45),
        ('Creating meshes', 0.15),
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
    _deletion_sync_result = None  # For processing deleted collars

    # Parameters captured from scene props
    _project_id = None
    _set_id = None
    _set_name = None
    _tube_radius = 0.15
    _tube_resolution = 8

    def invoke(self, context, event):
        """Start the async visualization operation."""
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        if props.import_active:
            self.report({'WARNING'}, "Another import operation is already running")
            return {'CANCELLED'}

        try:
            self.__class__._project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        # Get set from scene property (set by Load Config operator)
        self.__class__._set_id = props.selected_lithology_set_id if props.selected_lithology_set_id > 0 else None
        self.__class__._set_name = props.selected_lithology_set_name or 'all'
        self.__class__._tube_radius = 0.15
        self.__class__._tube_resolution = 8

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
        self.__class__._deletion_sync_result = None

        # Start background thread
        import threading
        self.__class__._thread = threading.Thread(target=self._download_data_wrapper)
        self.__class__._thread.start()

        # Start modal timer
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def _download_data_wrapper(self):
        try:
            self.download_data()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.__class__._error = str(e)

    def _set_stage(self, index, name=None):
        self.__class__._current_stage = index
        base_progress = sum(self._stages[i][1] for i in range(index)) if index > 0 else 0.0
        self.__class__._progress = base_progress
        if name is None and index < len(self._stages):
            name = self._stages[index][0]
        self.__class__._status = f"Stage {index + 1}/{len(self._stages)}: {name}..."

    def _update_stage_progress(self, done, total, stage_name=None):
        if total <= 0:
            return
        stage_weight = self._stages[self._current_stage][1] if self._current_stage < len(self._stages) else 0.0
        base_progress = sum(self._stages[i][1] for i in range(self._current_stage)) if self._current_stage > 0 else 0.0
        self.__class__._progress = base_progress + (done / total) * stage_weight
        if stage_name is None and self._current_stage < len(self._stages):
            stage_name = self._stages[self._current_stage][0]
        self.__class__._status = f"Stage {self._current_stage + 1}/{len(self._stages)}: {stage_name}... {done:,}/{total:,}"

    def download_data(self):
        """Background thread: Fetch all data from API."""
        project_id = self._project_id
        set_id = self._set_id
        set_name = self._set_name

        print(f"\n=== Async Lithology Visualization ===")

        # Stage 1: Fetch collars (with deletion sync)
        self._set_stage(0, "Fetching collars")

        # Get last sync timestamp for incremental sync
        deleted_since = DrillDataCache.get_sync_timestamp('drill_collars')

        success, collar_result = GeoDBData.get_drill_holes_with_sync(
            project_id,
            deleted_since=deleted_since
        )
        if self._cancelled:
            return
        if not success:
            self.__class__._error = "Failed to fetch drill collars"
            return

        collars = collar_result.get('results', [])
        if not collars:
            self.__class__._error = "No drill collars found for project"
            return

        # Process deletion sync (store result for main thread to handle scene cleanup)
        self.__class__._deletion_sync_result = {
            'deleted_collar_ids': collar_result.get('deleted_ids', []),
            'sync_timestamp': collar_result.get('sync_timestamp'),
            'project_id': project_id,
        }

        # Build name-to-ID mapping
        collar_id_by_name = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_id_by_name[hole_name] = hole_id

        # Stage 2: Fetch lithology data
        self._set_stage(1, "Fetching lithology data")
        success, lithology_data = GeoDBData.get_lithologies_for_project(project_id, set_id)
        if self._cancelled:
            return
        if not success or not lithology_data:
            self.__class__._error = "No lithology data available"
            return

        # Stage 3: Fetch traces
        self._set_stage(2, "Fetching traces")
        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)
        if self._cancelled:
            return
        if not success:
            self.__class__._error = "Failed to fetch drill traces"
            return

        # Fetch trace details for each hole with lithology data
        holes_needing_traces = set()
        for hole_name in lithology_data.keys():
            hole_id = collar_id_by_name.get(hole_name)
            if hole_id:
                holes_needing_traces.add(hole_id)

        trace_details = {}
        total_traces = len(holes_needing_traces)
        for idx, hole_id in enumerate(holes_needing_traces):
            if self._cancelled:
                return
            self._update_stage_progress(idx, total_traces, "Fetching trace details")

            trace_summary = traces_by_hole.get(hole_id)
            if trace_summary:
                trace_id = trace_summary.get('id')
                success, trace_detail = GeoDBData.get_drill_trace_detail(trace_id)
                if success:
                    trace_details[hole_id] = trace_detail

        # Process and prepare mesh data
        processed_intervals = []
        for hole_name, hole_lithologies in lithology_data.items():
            if not hole_lithologies:
                continue

            hole_id = collar_id_by_name.get(hole_name)
            if not hole_id:
                continue

            trace_detail = trace_details.get(hole_id)
            if not trace_detail:
                continue

            trace_data = trace_detail.get('trace_data', {})
            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                continue

            for lith_interval in hole_lithologies:
                depth_from = lith_interval.get('depth_from')
                depth_to = lith_interval.get('depth_to')
                if depth_from is None or depth_to is None:
                    continue

                lithology = lith_interval.get('lithology', {})
                if isinstance(lithology, dict):
                    lith_name = lithology.get('name', 'Unknown')
                    lith_color = lithology.get('color', '#CCCCCC')
                else:
                    lith_name = str(lithology) if lithology else 'Unknown'
                    lith_color = '#CCCCCC'

                processed_intervals.append({
                    'hole_name': hole_name,
                    'hole_id': hole_id,
                    'depth_from': depth_from,
                    'depth_to': depth_to,
                    'lith_name': lith_name,
                    'lith_color': lith_color,
                    'trace_depths': trace_depths,
                    'trace_coords': trace_coords,
                    'notes': lith_interval.get('notes', ''),
                })

        self.__class__._data = {
            'set_name': set_name,
            'processed_intervals': processed_intervals,
        }
        print(f"Data ready: {len(processed_intervals)} intervals to create")

    def modal(self, context, event):
        if event.type == 'ESC':
            self.__class__._cancelled = True
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            context.scene.geodb.import_progress = self._progress
            context.scene.geodb.import_status = self._status
            context.area.tag_redraw()

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
        """Main thread: Create Blender meshes."""
        from ..utils.cylinder_mesh import hex_to_rgba

        # Process deletion sync first (removes deleted holes from scene/cache)
        if self._deletion_sync_result:
            sync_result = sync_deletions_from_fetch_result(self._deletion_sync_result)
            if sync_result.get('removed_from_scene', 0) > 0:
                print(f"[DeleteSync] Removed {sync_result['removed_from_scene']} deleted holes from scene")

        data = self._data
        if not data:
            return

        self._set_stage(3, "Creating meshes")

        set_name = data['set_name']
        intervals = data['processed_intervals']

        # Create/get main collection
        main_collection_name = f"lithology_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            for obj in list(main_collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        lithology_collections = {}
        created_objects = []
        total_intervals = len(intervals)

        for idx, interval in enumerate(intervals):
            self._update_stage_progress(idx, total_intervals, "Creating meshes")

            lith_name = interval['lith_name']

            # Get or create collection for this lithology type
            if lith_name not in lithology_collections:
                lith_collection = bpy.data.collections.new(lith_name)
                main_collection.children.link(lith_collection)
                lithology_collections[lith_name] = lith_collection
            else:
                lith_collection = lithology_collections[lith_name]

            try:
                tube_name = f"{interval['hole_name']}_{lith_name}_{interval['depth_from']}_{interval['depth_to']}"
                tube_obj = create_interval_tube(
                    trace_depths=interval['trace_depths'],
                    trace_coords=interval['trace_coords'],
                    depth_from=interval['depth_from'],
                    depth_to=interval['depth_to'],
                    radius=self._tube_radius,
                    resolution=self._tube_resolution,
                    name=tube_name
                )

                if tube_obj:
                    lith_collection.objects.link(tube_obj)
                    color = hex_to_rgba(interval['lith_color'])
                    apply_material_to_interval(tube_obj, color, material_name=lith_name)

                    GeoDBObjectProperties.tag_drill_sample(tube_obj, {
                        "bhid": interval['hole_id'],
                        "hole_name": interval['hole_name'],
                        "depth_from": interval['depth_from'],
                        "depth_to": interval['depth_to'],
                        "lithology": lith_name,
                        "lithology_set": set_name,
                        "notes": interval['notes'],
                    })

                    tube_obj['geodb_visualization'] = True
                    tube_obj['geodb_type'] = 'lithology_interval'
                    tube_obj['geodb_hole_name'] = interval['hole_name']
                    tube_obj['geodb_lithology'] = lith_name

                    created_objects.append(tube_obj)
            except Exception as e:
                print(f"Error creating interval: {e}")

        adjust_view_to_objects(context, created_objects)
        self.report({'INFO'}, f"Created {len(created_objects)} lithology intervals in {len(lithology_collections)} types")

    def cleanup(self, context):
        wm = context.window_manager
        if self.__class__._timer:
            wm.event_timer_remove(self.__class__._timer)
            self.__class__._timer = None
        context.scene.geodb.import_active = False
        context.scene.geodb.import_progress = 0.0
        context.scene.geodb.import_status = ""
        context.area.tag_redraw()

    def cancel(self, context):
        self.__class__._cancelled = True
        self.cleanup(context)
        self.report({'INFO'}, "Operation cancelled by user")


class GEODB_OT_VisualizeAlteration(Operator):
    """Visualize alteration intervals as curved tubes (async with progress)"""
    bl_idname = "geodb.visualize_alteration"
    bl_label = "Visualize Alteration"
    bl_description = "Create curved tube visualization of alteration intervals along drill holes"
    bl_options = {'REGISTER', 'UNDO'}

    # Multi-stage progress tracking
    _stages = [
        ('Fetching collars', 0.10),
        ('Fetching alteration', 0.30),
        ('Fetching traces', 0.45),
        ('Creating meshes', 0.15),
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
    _deletion_sync_result = None  # For processing deleted collars

    # Parameters captured from scene props
    _project_id = None
    _set_id = None
    _set_name = None
    _tube_radius = 0.12
    _tube_resolution = 8

    def invoke(self, context, event):
        """Start the async visualization operation."""
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        if props.import_active:
            self.report({'WARNING'}, "Another import operation is already running")
            return {'CANCELLED'}

        try:
            self.__class__._project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        # Get set from scene property
        self.__class__._set_id = props.selected_alteration_set_id if props.selected_alteration_set_id > 0 else None
        self.__class__._set_name = props.selected_alteration_set_name or 'all'
        self.__class__._tube_radius = 0.12
        self.__class__._tube_resolution = 8

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
        self.__class__._deletion_sync_result = None

        # Start background thread
        import threading
        self.__class__._thread = threading.Thread(target=self._download_data_wrapper)
        self.__class__._thread.start()

        # Start modal timer
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def _download_data_wrapper(self):
        try:
            self.download_data()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.__class__._error = str(e)

    def _set_stage(self, index, name=None):
        self.__class__._current_stage = index
        base_progress = sum(self._stages[i][1] for i in range(index)) if index > 0 else 0.0
        self.__class__._progress = base_progress
        if name is None and index < len(self._stages):
            name = self._stages[index][0]
        self.__class__._status = f"Stage {index + 1}/{len(self._stages)}: {name}..."

    def _update_stage_progress(self, done, total, stage_name=None):
        if total <= 0:
            return
        stage_weight = self._stages[self._current_stage][1] if self._current_stage < len(self._stages) else 0.0
        base_progress = sum(self._stages[i][1] for i in range(self._current_stage)) if self._current_stage > 0 else 0.0
        self.__class__._progress = base_progress + (done / total) * stage_weight
        if stage_name is None and self._current_stage < len(self._stages):
            stage_name = self._stages[self._current_stage][0]
        self.__class__._status = f"Stage {self._current_stage + 1}/{len(self._stages)}: {stage_name}... {done:,}/{total:,}"

    def download_data(self):
        """Background thread: Fetch all data from API."""
        project_id = self._project_id
        set_id = self._set_id
        set_name = self._set_name

        print(f"\n=== Async Alteration Visualization ===")

        # Stage 1: Fetch collars (with deletion sync)
        self._set_stage(0, "Fetching collars")

        # Get last sync timestamp for incremental sync
        deleted_since = DrillDataCache.get_sync_timestamp('drill_collars')

        success, collar_result = GeoDBData.get_drill_holes_with_sync(
            project_id,
            deleted_since=deleted_since
        )
        if self._cancelled:
            return
        if not success:
            self.__class__._error = "Failed to fetch drill collars"
            return

        collars = collar_result.get('results', [])
        if not collars:
            self.__class__._error = "No drill collars found for project"
            return

        # Process deletion sync (store result for main thread to handle scene cleanup)
        self.__class__._deletion_sync_result = {
            'deleted_collar_ids': collar_result.get('deleted_ids', []),
            'sync_timestamp': collar_result.get('sync_timestamp'),
            'project_id': project_id,
        }

        collar_id_by_name = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_id_by_name[hole_name] = hole_id

        # Stage 2: Fetch alteration data
        self._set_stage(1, "Fetching alteration data")
        success, alteration_data = GeoDBData.get_alterations_for_project(project_id, set_id)
        if self._cancelled:
            return
        if not success or not alteration_data:
            self.__class__._error = "No alteration data available"
            return

        # Stage 3: Fetch traces
        self._set_stage(2, "Fetching traces")
        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)
        if self._cancelled:
            return
        if not success:
            self.__class__._error = "Failed to fetch drill traces"
            return

        # Fetch trace details
        holes_needing_traces = set()
        for hole_name in alteration_data.keys():
            hole_id = collar_id_by_name.get(hole_name)
            if hole_id:
                holes_needing_traces.add(hole_id)

        trace_details = {}
        total_traces = len(holes_needing_traces)
        for idx, hole_id in enumerate(holes_needing_traces):
            if self._cancelled:
                return
            self._update_stage_progress(idx, total_traces, "Fetching trace details")

            trace_summary = traces_by_hole.get(hole_id)
            if trace_summary:
                trace_id = trace_summary.get('id')
                success, trace_detail = GeoDBData.get_drill_trace_detail(trace_id)
                if success:
                    trace_details[hole_id] = trace_detail

        # Process and prepare mesh data
        processed_intervals = []
        for hole_name, hole_alterations in alteration_data.items():
            if not hole_alterations:
                continue

            hole_id = collar_id_by_name.get(hole_name)
            if not hole_id:
                continue

            trace_detail = trace_details.get(hole_id)
            if not trace_detail:
                continue

            trace_data = trace_detail.get('trace_data', {})
            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                continue

            for alt_interval in hole_alterations:
                depth_from = alt_interval.get('depth_from')
                depth_to = alt_interval.get('depth_to')
                if depth_from is None or depth_to is None:
                    continue

                alteration = alt_interval.get('alteration', {})
                if isinstance(alteration, dict):
                    alt_name = alteration.get('name', 'Unknown')
                    alt_color = alteration.get('color', '#CCCCCC')
                else:
                    alt_name = str(alteration) if alteration else 'Unknown'
                    alt_color = '#CCCCCC'

                processed_intervals.append({
                    'hole_name': hole_name,
                    'hole_id': hole_id,
                    'depth_from': depth_from,
                    'depth_to': depth_to,
                    'alt_name': alt_name,
                    'alt_color': alt_color,
                    'trace_depths': trace_depths,
                    'trace_coords': trace_coords,
                    'notes': alt_interval.get('notes', ''),
                })

        self.__class__._data = {
            'set_name': set_name,
            'processed_intervals': processed_intervals,
        }
        print(f"Data ready: {len(processed_intervals)} intervals to create")

    def modal(self, context, event):
        if event.type == 'ESC':
            self.__class__._cancelled = True
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            context.scene.geodb.import_progress = self._progress
            context.scene.geodb.import_status = self._status
            context.area.tag_redraw()

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
        """Main thread: Create Blender meshes."""
        from ..utils.cylinder_mesh import hex_to_rgba

        # Process deletion sync first (removes deleted holes from scene/cache)
        if self._deletion_sync_result:
            sync_result = sync_deletions_from_fetch_result(self._deletion_sync_result)
            if sync_result.get('removed_from_scene', 0) > 0:
                print(f"[DeleteSync] Removed {sync_result['removed_from_scene']} deleted holes from scene")

        data = self._data
        if not data:
            return

        self._set_stage(3, "Creating meshes")

        set_name = data['set_name']
        intervals = data['processed_intervals']

        main_collection_name = f"alteration_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            for obj in list(main_collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        alteration_collections = {}
        created_objects = []
        total_intervals = len(intervals)

        for idx, interval in enumerate(intervals):
            self._update_stage_progress(idx, total_intervals, "Creating meshes")

            alt_name = interval['alt_name']

            if alt_name not in alteration_collections:
                alt_collection = bpy.data.collections.new(alt_name)
                main_collection.children.link(alt_collection)
                alteration_collections[alt_name] = alt_collection
            else:
                alt_collection = alteration_collections[alt_name]

            try:
                tube_name = f"{interval['hole_name']}_{alt_name}_{interval['depth_from']}_{interval['depth_to']}"
                tube_obj = create_interval_tube(
                    trace_depths=interval['trace_depths'],
                    trace_coords=interval['trace_coords'],
                    depth_from=interval['depth_from'],
                    depth_to=interval['depth_to'],
                    radius=self._tube_radius,
                    resolution=self._tube_resolution,
                    name=tube_name
                )

                if tube_obj:
                    alt_collection.objects.link(tube_obj)
                    color = hex_to_rgba(interval['alt_color'])
                    apply_material_to_interval(tube_obj, color, material_name=alt_name, material_prefix="Alteration")

                    GeoDBObjectProperties.tag_drill_sample(tube_obj, {
                        "bhid": interval['hole_id'],
                        "hole_name": interval['hole_name'],
                        "depth_from": interval['depth_from'],
                        "depth_to": interval['depth_to'],
                        "alteration": alt_name,
                        "alteration_set": set_name,
                        "notes": interval['notes'],
                    })

                    tube_obj['geodb_visualization'] = True
                    tube_obj['geodb_type'] = 'alteration_interval'
                    tube_obj['geodb_hole_name'] = interval['hole_name']
                    tube_obj['geodb_alteration'] = alt_name

                    created_objects.append(tube_obj)
            except Exception as e:
                print(f"Error creating interval: {e}")

        adjust_view_to_objects(context, created_objects)
        self.report({'INFO'}, f"Created {len(created_objects)} alteration intervals in {len(alteration_collections)} types")

    def cleanup(self, context):
        wm = context.window_manager
        if self.__class__._timer:
            wm.event_timer_remove(self.__class__._timer)
            self.__class__._timer = None
        context.scene.geodb.import_active = False
        context.scene.geodb.import_progress = 0.0
        context.scene.geodb.import_status = ""
        context.area.tag_redraw()

    def cancel(self, context):
        self.__class__._cancelled = True
        self.cleanup(context)
        self.report({'INFO'}, "Operation cancelled by user")


class GEODB_OT_VisualizeMineralization(Operator):
    """Visualize mineralization intervals as curved tubes (async with progress)"""
    bl_idname = "geodb.visualize_mineralization"
    bl_label = "Visualize Mineralization"
    bl_description = "Create curved tube visualization of mineralization intervals along drill holes"
    bl_options = {'REGISTER', 'UNDO'}

    # Multi-stage progress tracking
    _stages = [
        ('Fetching collars', 0.10),
        ('Fetching mineralization', 0.30),
        ('Fetching traces', 0.45),
        ('Creating meshes', 0.15),
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
    _deletion_sync_result = None  # For processing deleted collars

    # Parameters captured from scene props
    _project_id = None
    _set_id = None
    _set_name = None
    _tube_radius = 0.18
    _tube_resolution = 8

    def invoke(self, context, event):
        """Start the async visualization operation."""
        scene = context.scene
        props = scene.geodb

        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        if props.import_active:
            self.report({'WARNING'}, "Another import operation is already running")
            return {'CANCELLED'}

        try:
            self.__class__._project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        # Get set from scene property
        self.__class__._set_id = props.selected_mineralization_set_id if props.selected_mineralization_set_id > 0 else None
        self.__class__._set_name = props.selected_mineralization_set_name or 'all'
        self.__class__._tube_radius = 0.18
        self.__class__._tube_resolution = 8

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
        self.__class__._deletion_sync_result = None

        # Start background thread
        import threading
        self.__class__._thread = threading.Thread(target=self._download_data_wrapper)
        self.__class__._thread.start()

        # Start modal timer
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def _download_data_wrapper(self):
        try:
            self.download_data()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.__class__._error = str(e)

    def _set_stage(self, index, name=None):
        self.__class__._current_stage = index
        base_progress = sum(self._stages[i][1] for i in range(index)) if index > 0 else 0.0
        self.__class__._progress = base_progress
        if name is None and index < len(self._stages):
            name = self._stages[index][0]
        self.__class__._status = f"Stage {index + 1}/{len(self._stages)}: {name}..."

    def _update_stage_progress(self, done, total, stage_name=None):
        if total <= 0:
            return
        stage_weight = self._stages[self._current_stage][1] if self._current_stage < len(self._stages) else 0.0
        base_progress = sum(self._stages[i][1] for i in range(self._current_stage)) if self._current_stage > 0 else 0.0
        self.__class__._progress = base_progress + (done / total) * stage_weight
        if stage_name is None and self._current_stage < len(self._stages):
            stage_name = self._stages[self._current_stage][0]
        self.__class__._status = f"Stage {self._current_stage + 1}/{len(self._stages)}: {stage_name}... {done:,}/{total:,}"

    def download_data(self):
        """Background thread: Fetch all data from API."""
        project_id = self._project_id
        set_id = self._set_id
        set_name = self._set_name

        print(f"\n=== Async Mineralization Visualization ===")

        # Stage 1: Fetch collars (with deletion sync)
        self._set_stage(0, "Fetching collars")

        # Get last sync timestamp for incremental sync
        deleted_since = DrillDataCache.get_sync_timestamp('drill_collars')

        success, collar_result = GeoDBData.get_drill_holes_with_sync(
            project_id,
            deleted_since=deleted_since
        )
        if self._cancelled:
            return
        if not success:
            self.__class__._error = "Failed to fetch drill collars"
            return

        collars = collar_result.get('results', [])
        if not collars:
            self.__class__._error = "No drill collars found for project"
            return

        # Process deletion sync (store result for main thread to handle scene cleanup)
        self.__class__._deletion_sync_result = {
            'deleted_collar_ids': collar_result.get('deleted_ids', []),
            'sync_timestamp': collar_result.get('sync_timestamp'),
            'project_id': project_id,
        }

        # Build mappings
        collar_id_by_name = {}
        collar_by_hole_id = {}
        for collar in collars:
            hole_id = collar.get('id')
            hole_name = collar.get('name', collar.get('hole_id', f"Hole_{hole_id}"))
            collar_id_by_name[hole_name] = hole_id
            collar_by_hole_id[collar.get('hole_id')] = collar

        # Stage 2: Fetch mineralization data
        self._set_stage(1, "Fetching mineralization data")
        success, mineralization_data = GeoDBData.get_mineralizations_for_project(project_id, set_id)
        if self._cancelled:
            return
        if not success or not mineralization_data:
            self.__class__._error = "No mineralization data available"
            return

        # Stage 3: Fetch traces
        self._set_stage(2, "Fetching traces")
        success, traces_by_hole = GeoDBData.get_drill_traces(project_id)
        if self._cancelled:
            return
        if not success:
            self.__class__._error = "Failed to fetch drill traces"
            return

        # Fetch trace details for holes with mineralization data
        holes_needing_traces = set()
        for hole_name in mineralization_data.keys():
            hole_id = collar_id_by_name.get(hole_name)
            if hole_id:
                holes_needing_traces.add(hole_id)

        trace_details = {}
        total_traces = len(holes_needing_traces)
        for idx, hole_id in enumerate(holes_needing_traces):
            if self._cancelled:
                return
            self._update_stage_progress(idx, total_traces, "Fetching trace details")

            trace_summary = traces_by_hole.get(hole_id)
            if trace_summary:
                trace_id = trace_summary.get('id')
                success, trace_detail = GeoDBData.get_drill_trace_detail(trace_id)
                if success:
                    trace_details[hole_id] = trace_detail

        # Process and prepare mesh data
        processed_intervals = []
        for hole_name, min_intervals in mineralization_data.items():
            if not min_intervals:
                continue

            hole_id = collar_id_by_name.get(hole_name)
            if not hole_id:
                continue

            trace_detail = trace_details.get(hole_id)
            if not trace_detail:
                continue

            trace_data = trace_detail.get('trace_data', {})
            trace_depths = trace_data.get('depths', [])
            trace_coords = trace_data.get('coords', [])

            if not trace_depths or not trace_coords:
                continue

            for min_interval in min_intervals:
                depth_from = min_interval.get('depth_from')
                depth_to = min_interval.get('depth_to')
                if depth_from is None or depth_to is None:
                    continue

                # Extract assemblage info (mineralization uses 'assemblage' not 'mineralization')
                assemblage = min_interval.get('assemblage', {})
                if isinstance(assemblage, dict):
                    min_name = assemblage.get('name', 'Unknown')
                    min_color = assemblage.get('color', '#808080')
                else:
                    min_name = 'Unknown'
                    min_color = '#808080'

                processed_intervals.append({
                    'hole_name': hole_name,
                    'hole_id': hole_id,
                    'depth_from': depth_from,
                    'depth_to': depth_to,
                    'min_name': min_name,
                    'min_color': min_color,
                    'trace_depths': trace_depths,
                    'trace_coords': trace_coords,
                    'notes': min_interval.get('notes', ''),
                })

        self.__class__._data = {
            'set_name': set_name,
            'processed_intervals': processed_intervals,
        }
        print(f"Data ready: {len(processed_intervals)} intervals to create")

    def modal(self, context, event):
        if event.type == 'ESC':
            self.__class__._cancelled = True
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            context.scene.geodb.import_progress = self._progress
            context.scene.geodb.import_status = self._status
            context.area.tag_redraw()

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
        """Main thread: Create Blender meshes."""
        from ..utils.cylinder_mesh import hex_to_rgba

        # Process deletion sync first (removes deleted holes from scene/cache)
        if self._deletion_sync_result:
            sync_result = sync_deletions_from_fetch_result(self._deletion_sync_result)
            if sync_result.get('removed_from_scene', 0) > 0:
                print(f"[DeleteSync] Removed {sync_result['removed_from_scene']} deleted holes from scene")

        data = self._data
        if not data:
            return

        self._set_stage(3, "Creating meshes")

        set_name = data['set_name']
        intervals = data['processed_intervals']

        main_collection_name = f"Mineralization_{set_name}"
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
            for obj in list(main_collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            bpy.context.scene.collection.children.link(main_collection)

        mineralization_collections = {}
        created_objects = []
        total_intervals = len(intervals)

        for idx, interval in enumerate(intervals):
            self._update_stage_progress(idx, total_intervals, "Creating meshes")

            min_name = interval['min_name']

            if min_name not in mineralization_collections:
                min_collection = bpy.data.collections.new(f"Mineralization_{min_name}")
                main_collection.children.link(min_collection)
                mineralization_collections[min_name] = min_collection
            else:
                min_collection = mineralization_collections[min_name]

            try:
                tube_name = f"{interval['hole_name']}_MIN_{interval['depth_from']}_{interval['depth_to']}_{min_name}"
                tube_obj = create_interval_tube(
                    trace_depths=interval['trace_depths'],
                    trace_coords=interval['trace_coords'],
                    depth_from=interval['depth_from'],
                    depth_to=interval['depth_to'],
                    radius=self._tube_radius,
                    resolution=self._tube_resolution,
                    name=tube_name
                )

                if tube_obj:
                    min_collection.objects.link(tube_obj)
                    color = hex_to_rgba(interval['min_color'])
                    apply_material_to_interval(tube_obj, color, material_name=min_name, material_prefix="Mineralization")

                    GeoDBObjectProperties.tag_drill_sample(tube_obj, {
                        "bhid": interval['hole_id'],
                        "hole_name": interval['hole_name'],
                        "depth_from": interval['depth_from'],
                        "depth_to": interval['depth_to'],
                        "mineralization": min_name,
                        "mineralization_set": set_name,
                        "notes": interval['notes'],
                    })

                    tube_obj['geodb_visualization'] = True
                    tube_obj['geodb_type'] = 'mineralization_interval'
                    tube_obj['geodb_hole_name'] = interval['hole_name']
                    tube_obj['geodb_mineralization'] = min_name

                    created_objects.append(tube_obj)
            except Exception as e:
                print(f"Error creating interval: {e}")

        adjust_view_to_objects(context, created_objects)
        self.report({'INFO'}, f"Created {len(created_objects)} mineralization intervals in {len(mineralization_collections)} types")

    def cleanup(self, context):
        wm = context.window_manager
        if self.__class__._timer:
            wm.event_timer_remove(self.__class__._timer)
            self.__class__._timer = None
        context.scene.geodb.import_active = False
        context.scene.geodb.import_progress = 0.0
        context.scene.geodb.import_status = ""
        context.area.tag_redraw()

    def cancel(self, context):
        self.__class__._cancelled = True
        self.cleanup(context)
        self.report({'INFO'}, "Operation cancelled by user")


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
