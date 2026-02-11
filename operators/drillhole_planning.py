"""
Drillhole planning operators.

Operators for importing drill pads, creating planned holes,
and sending planned holes to the server.
"""

import re

import bpy
from bpy.types import Operator

from .async_base import GeoDBAsyncOperator
from ..api.data import GeoDBData
from ..utils.logging import logger
from ..utils.drillpad_mesh import (
    create_drillpad_mesh,
    update_drillpad_mesh,
    find_existing_drillpad,
    calculate_hole_geometry,
    create_planned_hole_preview,
    get_pad_centroid,
    extract_hole_endpoints,
    update_hole_mesh_from_geometry
)


class GEODB_OT_ImportDrillPads(GeoDBAsyncOperator):
    """Import drill pads from geoDB API"""
    bl_idname = "geodb.import_drill_pads"
    bl_label = "Import Drill Pads"
    bl_description = "Import drill pads as 3D extruded meshes"
    bl_options = {'REGISTER', 'UNDO'}

    _pads_data = None

    def download_data(self):
        """Background thread - fetch pad data from API"""
        try:
            self.__class__._status = "Fetching drill pads..."
            self.__class__._progress = 0.2

            scene = bpy.context.scene
            project_id = scene.geodb.selected_project_id

            if not project_id:
                self.__class__._error = "No project selected"
                return

            success, pads = GeoDBData.get_drill_pads_blender(int(project_id))

            if not success:
                self.__class__._error = "Failed to fetch drill pads from API"
                return

            if not pads:
                self.__class__._error = "No drill pads found for this project"
                return

            self.__class__._pads_data = pads
            self.__class__._progress = 1.0
            self.__class__._status = f"Fetched {len(pads)} pads"

        except Exception as e:
            self.__class__._error = str(e)
            logger.debug("Error fetching drill pads", exc_info=True)

    def finish_in_main_thread(self, context):
        """Main thread - create or update Blender objects"""
        pads = self.__class__._pads_data
        if not pads:
            return

        # Create or get collection for pads
        collection_name = "Drill Pads"
        if collection_name in bpy.data.collections:
            collection = bpy.data.collections[collection_name]
        else:
            collection = bpy.data.collections.new(collection_name)
            context.scene.collection.children.link(collection)

        created_count = 0
        updated_count = 0
        affected_objects = []

        for pad in pads:
            name = pad.get('name', 'Pad')
            pad_id = pad.get('id')
            local_grid = pad.get('local_grid', {})
            vertices_2d = local_grid.get('vertices_2d', [])
            centroid = local_grid.get('centroid', [])

            # Determine elevation: prefer centroid Z, then pad elevation field, then 0
            if len(centroid) >= 3 and centroid[2] is not None:
                elevation = centroid[2]
            else:
                elevation = pad.get('elevation', 0.0) or 0.0

            # Ensure centroid has 3 values
            if len(centroid) < 3:
                centroid = [centroid[0] if len(centroid) > 0 else 0,
                           centroid[1] if len(centroid) > 1 else 0,
                           elevation]

            logger.debug("Pad %s: elevation=%s, centroid=%s", name, elevation, centroid)
            if vertices_2d:
                logger.debug("  First vertex: %s, Last vertex: %s", vertices_2d[0], vertices_2d[-1])

            if not vertices_2d or len(vertices_2d) < 3:
                logger.debug("Skipping pad %s: insufficient vertices", name)
                continue

            try:
                # Check if this pad already exists in the scene
                existing_obj = find_existing_drillpad(pad_id)

                if existing_obj:
                    # Update existing pad geometry
                    logger.debug("Updating pad: %s", name)
                    update_drillpad_mesh(
                        obj=existing_obj,
                        vertices_2d=vertices_2d,
                        elevation=elevation,
                        extrusion_height=10.0,
                        centroid=tuple(centroid) if centroid else None
                    )

                    # Update metadata in case it changed
                    existing_obj['geodb_pad_name'] = name
                    existing_obj['geodb_elevation'] = elevation
                    existing_obj['geodb_centroid_x'] = centroid[0] if len(centroid) > 0 else 0
                    existing_obj['geodb_centroid_y'] = centroid[1] if len(centroid) > 1 else 0
                    existing_obj['geodb_centroid_z'] = centroid[2] if len(centroid) > 2 else elevation

                    affected_objects.append(existing_obj)
                    updated_count += 1
                else:
                    # Create new extruded pad mesh
                    logger.debug("Creating pad: %s", name)
                    obj = create_drillpad_mesh(
                        name=f"Pad_{name}",
                        vertices_2d=vertices_2d,
                        elevation=elevation,
                        extrusion_height=10.0,
                        color_hex="#4CAF50",
                        centroid=tuple(centroid) if centroid else None
                    )

                    # Move to collection
                    for coll in obj.users_collection:
                        coll.objects.unlink(obj)
                    collection.objects.link(obj)

                    # Store metadata
                    obj['geodb_object_type'] = 'drill_pad'
                    obj['geodb_pad_id'] = pad_id
                    obj['geodb_pad_name'] = name
                    obj['geodb_elevation'] = elevation
                    obj['geodb_centroid_x'] = centroid[0] if len(centroid) > 0 else 0
                    obj['geodb_centroid_y'] = centroid[1] if len(centroid) > 1 else 0
                    obj['geodb_centroid_z'] = centroid[2] if len(centroid) > 2 else elevation

                    affected_objects.append(obj)
                    created_count += 1

            except Exception as e:
                logger.error("Error processing pad %s: %s", name, e)
                logger.debug("Pad error details", exc_info=True)

        # Adjust view to show pads
        if affected_objects:
            from ..ui.drill_visualization_panel import adjust_view_to_objects
            adjust_view_to_objects(context, affected_objects)

        # Report what happened
        if updated_count > 0 and created_count > 0:
            self.report({'INFO'}, f"Created {created_count} new pads, updated {updated_count} existing pads")
        elif updated_count > 0:
            self.report({'INFO'}, f"Updated {updated_count} existing drill pads")
        else:
            self.report({'INFO'}, f"Imported {created_count} drill pads")


class GEODB_OT_SelectDrillPad(Operator):
    """Select a drill pad for planning"""
    bl_idname = "geodb.select_drill_pad"
    bl_label = "Select Drill Pad"
    bl_description = "Select a drill pad from the scene for hole planning"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object

        if not obj or obj.get('geodb_object_type') != 'drill_pad':
            self.report({'ERROR'}, "Please select a drill pad object")
            return {'CANCELLED'}

        props = context.scene.geodb
        props.planning_selected_pad_id = obj.get('geodb_pad_id', -1)
        props.planning_selected_pad_name = obj.get('geodb_pad_name', '')

        self.report({'INFO'}, f"Selected pad: {props.planning_selected_pad_name}")
        return {'FINISHED'}


class GEODB_OT_CalculateFromCursor(Operator):
    """Calculate azimuth/dip/length from 3D cursor"""
    bl_idname = "geodb.calculate_from_cursor"
    bl_label = "Calculate from 3D Cursor"
    bl_description = "Calculate drill hole geometry from pad center to 3D cursor position"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb

        # Find selected pad
        pad_obj = None
        for obj in bpy.data.objects:
            if (obj.get('geodb_object_type') == 'drill_pad' and
                obj.get('geodb_pad_id') == props.planning_selected_pad_id):
                pad_obj = obj
                break

        if not pad_obj:
            self.report({'ERROR'}, "No drill pad selected")
            return {'CANCELLED'}

        # Get pad centroid with optional elevation override
        elevation_override = None
        if props.planning_use_manual_elevation:
            elevation_override = props.planning_collar_elevation

        pad_center = get_pad_centroid(pad_obj, elevation_override)
        if not pad_center:
            self.report({'ERROR'}, "Could not get pad centroid")
            return {'CANCELLED'}

        # Get 3D cursor position
        cursor = context.scene.cursor.location
        target = (cursor.x, cursor.y, cursor.z)

        # Calculate geometry
        azimuth, dip, length = calculate_hole_geometry(pad_center, target)

        # Update properties
        props.planning_azimuth = azimuth
        props.planning_dip = dip
        props.planning_length = length

        self.report({'INFO'},
            f"Calculated: Az={azimuth:.1f}, Dip={dip:.1f}, Length={length:.1f}m (collar Z={pad_center[2]:.1f})")
        return {'FINISHED'}


class GEODB_OT_PreviewPlannedHole(Operator):
    """Create a preview of the planned drill hole"""
    bl_idname = "geodb.preview_planned_hole"
    bl_label = "Preview Hole"
    bl_description = "Show preview of planned drill hole trajectory"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb

        # Find selected pad
        pad_obj = None
        for obj in bpy.data.objects:
            if (obj.get('geodb_object_type') == 'drill_pad' and
                obj.get('geodb_pad_id') == props.planning_selected_pad_id):
                pad_obj = obj
                break

        if not pad_obj:
            self.report({'ERROR'}, "No drill pad selected")
            return {'CANCELLED'}

        # Get pad centroid as collar with optional elevation override
        elevation_override = None
        if props.planning_use_manual_elevation:
            elevation_override = props.planning_collar_elevation

        collar = get_pad_centroid(pad_obj, elevation_override)
        if not collar:
            self.report({'ERROR'}, "Could not get pad centroid")
            return {'CANCELLED'}

        # Remove existing preview
        preview_name = f"Preview_{props.planning_hole_name}"
        if preview_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[preview_name], do_unlink=True)

        # Create preview
        preview_obj = create_planned_hole_preview(
            name=preview_name,
            collar=collar,
            azimuth=props.planning_azimuth,
            dip=props.planning_dip,
            length=props.planning_length,
            color_hex="#FF5722",
            tube_radius=1.0
        )

        # Tag as preview
        preview_obj['geodb_object_type'] = 'planned_hole_preview'
        preview_obj['geodb_is_preview'] = True

        self.report({'INFO'}, f"Created preview for {props.planning_hole_name} (collar Z={collar[2]:.1f})")
        return {'FINISHED'}


class GEODB_OT_ClearPreviews(Operator):
    """Clear all planned hole previews from the scene"""
    bl_idname = "geodb.clear_planned_previews"
    bl_label = "Clear Previews"
    bl_description = "Remove all planned hole preview objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = 0
        for obj in list(bpy.data.objects):
            if obj.get('geodb_object_type') == 'planned_hole_preview':
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1

        self.report({'INFO'}, f"Removed {removed} preview objects")
        return {'FINISHED'}


def set_hole_material_color(obj, color_hex: str):
    """Update the material color of a planned hole object.

    Args:
        obj: Blender object with material
        color_hex: Hex color string (e.g., "#FFC107")
    """
    if not obj or not obj.data.materials:
        return

    mat = obj.data.materials[0]
    hex_color = color_hex.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0

    mat.diffuse_color = (r, g, b, 0.9)

    if mat.use_nodes:
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)


# Color constants for sync state
COLOR_NEEDS_SYNC = "#FFC107"  # Amber - local only or modified
COLOR_SYNCED = "#2196F3"      # Blue - synced with server
COLOR_PREVIEW = "#FF5722"     # Orange - preview


class GEODB_OT_CreatePlannedHole(Operator):
    """Create a planned drill hole locally (not sent to server until sync)"""
    bl_idname = "geodb.create_planned_hole"
    bl_label = "Create Planned Hole"
    bl_description = "Create planned drill hole locally. Use 'Sync' to push to server"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.geodb

        # Validate inputs
        if not props.planning_selected_pad_name:
            self.report({'ERROR'}, "No drill pad selected")
            return {'CANCELLED'}

        if not props.planning_hole_name:
            self.report({'ERROR'}, "No hole name specified")
            return {'CANCELLED'}

        hole_name = props.planning_hole_name

        # Validate hole name
        hole_name = hole_name.strip()
        if not hole_name or len(hole_name) > 100:
            self.report({'ERROR'}, "Hole name must be 1-100 characters.")
            return {'CANCELLED'}

        if not re.match(r'^[A-Za-z0-9\-_. ]+$', hole_name):
            self.report({'ERROR'}, "Hole name contains invalid characters.")
            return {'CANCELLED'}

        # Check if hole with this name already exists
        existing_name = f"PlannedHole_{hole_name}"
        if existing_name in bpy.data.objects:
            self.report({'ERROR'}, f"Hole '{hole_name}' already exists")
            return {'CANCELLED'}

        # Get elevation override if set
        elevation_override = None
        if props.planning_use_manual_elevation:
            elevation_override = props.planning_collar_elevation

        # Find pad to get collar coordinates
        pad_obj = None
        for obj in bpy.data.objects:
            if (obj.get('geodb_object_type') == 'drill_pad' and
                obj.get('geodb_pad_id') == props.planning_selected_pad_id):
                pad_obj = obj
                break

        if not pad_obj:
            self.report({'ERROR'}, "Could not find selected drill pad")
            return {'CANCELLED'}

        collar = get_pad_centroid(pad_obj, elevation_override)
        if not collar:
            self.report({'ERROR'}, "Could not get pad centroid")
            return {'CANCELLED'}

        # Remove preview if exists
        preview_name = f"Preview_{hole_name}"
        if preview_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[preview_name], do_unlink=True)

        # Create the hole visualization (amber color = needs sync)
        hole_obj = create_planned_hole_preview(
            name=f"PlannedHole_{hole_name}",
            collar=collar,
            azimuth=props.planning_azimuth,
            dip=props.planning_dip,
            length=props.planning_length,
            color_hex=COLOR_NEEDS_SYNC,
            tube_radius=1.0
        )

        # Tag with all metadata
        hole_obj['geodb_object_type'] = 'planned_hole'
        hole_obj['geodb_hole_id'] = None  # Not yet on server
        hole_obj['geodb_hole_name'] = hole_name
        hole_obj['geodb_is_preview'] = False
        hole_obj['geodb_needs_sync'] = True  # Needs to be pushed
        hole_obj['geodb_azimuth'] = props.planning_azimuth
        hole_obj['geodb_dip'] = props.planning_dip
        hole_obj['geodb_length'] = props.planning_length
        hole_obj['geodb_hole_type'] = props.planning_hole_type
        hole_obj['geodb_pad_name'] = props.planning_selected_pad_name
        hole_obj['geodb_pad_id'] = props.planning_selected_pad_id
        # Store collar coordinates for reference
        hole_obj['geodb_collar_x'] = collar[0]
        hole_obj['geodb_collar_y'] = collar[1]
        hole_obj['geodb_collar_z'] = collar[2]

        self.report({'INFO'}, f"Created planned hole: {hole_name} (not yet synced)")
        return {'FINISHED'}


class GEODB_OT_SyncPlannedHoles(GeoDBAsyncOperator):
    """Synchronize planned holes with the server"""
    bl_idname = "geodb.sync_planned_holes"
    bl_label = "Sync Planned Holes"
    bl_description = "Synchronize all planned holes with geoDB server"
    bl_options = {'REGISTER', 'UNDO'}

    _server_holes = None
    _local_holes_data = None
    _sync_results = None

    def download_data(self):
        """Background thread - perform sync with server"""
        try:
            self.__class__._status = "Fetching server data..."
            self.__class__._progress = 0.1

            scene = bpy.context.scene
            props = scene.geodb

            if not props.selected_project_id:
                self.__class__._error = "No project selected"
                return

            project_id = int(props.selected_project_id)

            # Fetch planned holes from server
            success, server_holes = GeoDBData.get_planned_holes(project_id)
            if not success:
                self.__class__._error = "Failed to fetch planned holes from server"
                return

            self.__class__._server_holes = {h['id']: h for h in server_holes}
            self.__class__._progress = 0.3

            # Gather local hole data (can't access bpy.data.objects in thread,
            # so we stored the data in invoke())
            local_holes = self.__class__._local_holes_data or {}

            sync_results = {
                'pushed_new': [],
                'pushed_updates': [],
                'pull_updates': [],
                'delete_local': [],
                'create_local': [],
                'errors': []
            }

            self.__class__._status = "Syncing..."
            self.__class__._progress = 0.4

            # Process local holes
            for obj_name, hole_data in local_holes.items():
                hole_id = hole_data.get('geodb_hole_id')
                needs_sync = hole_data.get('geodb_needs_sync', False)

                # Build pad reference - API requires name-based lookup (natural key)
                pad_ref = {
                    "name": hole_data['geodb_pad_name'],
                    "project": {
                        "name": props.selected_project_name,
                        "company": props.selected_company_name
                    }
                }

                # Build API data - omit coordinates to let server use pad centroid
                # (avoids needing coordinate_system_metadata)
                api_data = {
                    "name": hole_data['geodb_hole_name'],
                    "project": {
                        "name": props.selected_project_name,
                        "company": props.selected_company_name
                    },
                    "pad": pad_ref,
                    "hole_status": "PL",
                    "hole_type": hole_data.get('geodb_hole_type', 'DD'),
                    "total_depth": hole_data['geodb_length'],
                    "azimuth": hole_data['geodb_azimuth'],
                    "dip": hole_data['geodb_dip'],
                    "length_units": "M",
                }

                if hole_id is None:
                    # New hole - push to server
                    self.__class__._status = f"Pushing new hole: {hole_data['geodb_hole_name']}"

                    success, result = GeoDBData.create_planned_drill_hole(api_data)
                    if success:
                        sync_results['pushed_new'].append({
                            'obj_name': obj_name,
                            'new_id': result.get('id'),
                            'hole_name': hole_data['geodb_hole_name']
                        })
                    else:
                        sync_results['errors'].append(f"Failed to push {hole_data['geodb_hole_name']}")

                elif needs_sync:
                    # Existing hole with local changes - push update via upsert (POST with natural keys)
                    self.__class__._status = f"Updating hole: {hole_data['geodb_hole_name']}"

                    success, result = GeoDBData.update_planned_hole(api_data)
                    if success:
                        sync_results['pushed_updates'].append({
                            'obj_name': obj_name,
                            'hole_id': hole_id,
                            'hole_name': hole_data['geodb_hole_name']
                        })
                    else:
                        sync_results['errors'].append(f"Failed to update {hole_data['geodb_hole_name']}")

                else:
                    # Check if server version differs - pull if so
                    server_hole = self.__class__._server_holes.get(hole_id)
                    if server_hole:
                        # Compare values
                        server_az = server_hole.get('azimuth', 0)
                        server_dip = server_hole.get('dip', 0)
                        server_depth = server_hole.get('total_depth', 0)

                        local_az = hole_data['geodb_azimuth']
                        local_dip = hole_data['geodb_dip']
                        local_depth = hole_data['geodb_length']

                        if (abs(server_az - local_az) > 0.01 or
                            abs(server_dip - local_dip) > 0.01 or
                            abs(server_depth - local_depth) > 0.01):
                            # Server has different values - pull
                            sync_results['pull_updates'].append({
                                'obj_name': obj_name,
                                'server_data': server_hole
                            })

            self.__class__._progress = 0.7

            # Check for holes on server that don't exist locally
            local_ids = {h.get('geodb_hole_id') for h in local_holes.values() if h.get('geodb_hole_id')}
            for server_id, server_hole in self.__class__._server_holes.items():
                if server_id not in local_ids:
                    # Server hole not in local - create locally
                    sync_results['create_local'].append(server_hole)

            # Check for local holes whose server ID no longer exists
            for obj_name, hole_data in local_holes.items():
                hole_id = hole_data.get('geodb_hole_id')
                if hole_id is not None and hole_id not in self.__class__._server_holes:
                    # Server deleted this hole
                    sync_results['delete_local'].append(obj_name)

            self.__class__._sync_results = sync_results
            self.__class__._progress = 1.0
            self.__class__._status = "Sync complete"

        except Exception as e:
            self.__class__._error = str(e)
            logger.debug("Sync error details", exc_info=True)

    def invoke(self, context, event):
        # Gather local hole data before starting thread
        # (can't access bpy.data.objects in background thread)
        local_holes = {}
        for obj in bpy.data.objects:
            if obj.get('geodb_object_type') == 'planned_hole':
                local_holes[obj.name] = {
                    'geodb_hole_id': obj.get('geodb_hole_id'),
                    'geodb_hole_name': obj.get('geodb_hole_name'),
                    'geodb_needs_sync': obj.get('geodb_needs_sync', False),
                    'geodb_azimuth': obj.get('geodb_azimuth', 0),
                    'geodb_dip': obj.get('geodb_dip', 0),
                    'geodb_length': obj.get('geodb_length', 0),
                    'geodb_hole_type': obj.get('geodb_hole_type', 'DD'),
                    'geodb_pad_name': obj.get('geodb_pad_name', ''),
                    'geodb_pad_id': obj.get('geodb_pad_id'),
                    'geodb_collar_x': obj.get('geodb_collar_x', 0),
                    'geodb_collar_y': obj.get('geodb_collar_y', 0),
                    'geodb_collar_z': obj.get('geodb_collar_z', 0),
                }
        self.__class__._local_holes_data = local_holes

        return super().invoke(context, event)

    def finish_in_main_thread(self, context):
        """Main thread - apply sync results to Blender objects"""
        results = self.__class__._sync_results
        if not results:
            return

        props = context.scene.geodb

        # Apply pushed new holes - update their IDs and color
        for item in results['pushed_new']:
            obj_name = item['obj_name']
            if obj_name in bpy.data.objects:
                obj = bpy.data.objects[obj_name]
                obj['geodb_hole_id'] = item['new_id']
                obj['geodb_needs_sync'] = False
                set_hole_material_color(obj, COLOR_SYNCED)

        # Apply pushed updates - clear sync flag and update color
        for item in results['pushed_updates']:
            obj_name = item['obj_name']
            if obj_name in bpy.data.objects:
                obj = bpy.data.objects[obj_name]
                obj['geodb_needs_sync'] = False
                set_hole_material_color(obj, COLOR_SYNCED)

        # Apply pull updates - update local geometry from server
        for item in results['pull_updates']:
            obj_name = item['obj_name']
            server_data = item['server_data']
            if obj_name in bpy.data.objects:
                obj = bpy.data.objects[obj_name]

                # Update properties
                obj['geodb_azimuth'] = server_data.get('azimuth', 0)
                obj['geodb_dip'] = server_data.get('dip', 0)
                obj['geodb_length'] = server_data.get('total_depth', 0)
                obj['geodb_needs_sync'] = False

                # Regenerate mesh with new geometry
                collar = (
                    obj.get('geodb_collar_x', 0),
                    obj.get('geodb_collar_y', 0),
                    obj.get('geodb_collar_z', 0)
                )
                update_hole_mesh_from_geometry(
                    obj, collar,
                    server_data.get('azimuth', 0),
                    server_data.get('dip', 0),
                    server_data.get('total_depth', 0)
                )
                set_hole_material_color(obj, COLOR_SYNCED)

        # Delete local holes that were deleted on server
        for obj_name in results['delete_local']:
            if obj_name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[obj_name], do_unlink=True)

        # Create local holes from server data
        for server_hole in results['create_local']:
            hole_name = server_hole.get('name', 'Unknown')
            obj_name = f"PlannedHole_{hole_name}"

            # Skip if already exists
            if obj_name in bpy.data.objects:
                continue

            # Get pad info
            pad_data = server_hole.get('pad')
            pad_name = pad_data.get('name', '') if pad_data else ''

            # Try to get collar position - prefer finding matching pad in scene
            # (which has local coordinates), otherwise use server coordinates
            collar = None
            for obj in bpy.data.objects:
                if (obj.get('geodb_object_type') == 'drill_pad' and
                    obj.get('geodb_pad_name') == pad_name):
                    collar = get_pad_centroid(obj)
                    break

            if not collar:
                # No matching pad in scene - check if server has coordinates
                # Server uses WGS84 (lat/long) which won't match local coords,
                # so we can only create if we have matching pads imported
                logger.warning("Could not find pad '%s' in scene for hole %s. "
                               "Import the pad first to pull this hole.", pad_name, hole_name)
                continue

            # Create the hole
            hole_obj = create_planned_hole_preview(
                name=obj_name,
                collar=collar,
                azimuth=server_hole.get('azimuth', 0),
                dip=server_hole.get('dip', 0),
                length=server_hole.get('total_depth', 100),
                color_hex=COLOR_SYNCED,
                tube_radius=1.0
            )

            # Set properties
            hole_obj['geodb_object_type'] = 'planned_hole'
            hole_obj['geodb_hole_id'] = server_hole.get('id')
            hole_obj['geodb_hole_name'] = hole_name
            hole_obj['geodb_is_preview'] = False
            hole_obj['geodb_needs_sync'] = False
            hole_obj['geodb_azimuth'] = server_hole.get('azimuth', 0)
            hole_obj['geodb_dip'] = server_hole.get('dip', 0)
            hole_obj['geodb_length'] = server_hole.get('total_depth', 100)
            hole_obj['geodb_hole_type'] = server_hole.get('hole_type', 'DD')
            hole_obj['geodb_pad_name'] = pad_name
            hole_obj['geodb_collar_x'] = collar[0]
            hole_obj['geodb_collar_y'] = collar[1]
            hole_obj['geodb_collar_z'] = collar[2]

        # Report summary
        summary_parts = []
        if results['pushed_new']:
            summary_parts.append(f"pushed {len(results['pushed_new'])} new")
        if results['pushed_updates']:
            summary_parts.append(f"updated {len(results['pushed_updates'])}")
        if results['pull_updates']:
            summary_parts.append(f"pulled {len(results['pull_updates'])}")
        if results['delete_local']:
            summary_parts.append(f"deleted {len(results['delete_local'])}")
        if results['create_local']:
            summary_parts.append(f"created {len(results['create_local'])} from server")
        if results['errors']:
            summary_parts.append(f"{len(results['errors'])} errors")

        if summary_parts:
            self.report({'INFO'}, f"Sync complete: {', '.join(summary_parts)}")
        else:
            self.report({'INFO'}, "Sync complete: no changes")


class GEODB_OT_UpdateHoleFromMesh(Operator):
    """Update planned hole geometry from edited control points"""
    bl_idname = "geodb.update_hole_from_mesh"
    bl_label = "Update Hole Geometry"
    bl_description = "Recalculate azimuth, dip, and length from edited curve points"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object

        if not obj or obj.get('geodb_object_type') != 'planned_hole':
            self.report({'WARNING'}, "No planned hole selected")
            return {'CANCELLED'}

        # Extract endpoints from the edited mesh
        endpoints = extract_hole_endpoints(obj)
        if not endpoints:
            self.report({'ERROR'}, "Could not extract hole endpoints from mesh")
            return {'CANCELLED'}

        collar, toe = endpoints

        # Calculate new geometry
        azimuth, dip, length = calculate_hole_geometry(collar, toe)

        # Update object properties
        old_az = obj.get('geodb_azimuth', 0)
        old_dip = obj.get('geodb_dip', 0)
        old_length = obj.get('geodb_length', 0)

        obj['geodb_azimuth'] = azimuth
        obj['geodb_dip'] = dip
        obj['geodb_length'] = length
        obj['geodb_collar_x'] = collar[0]
        obj['geodb_collar_y'] = collar[1]
        obj['geodb_collar_z'] = collar[2]

        # Mark as needing sync if values changed
        if (abs(azimuth - old_az) > 0.01 or
            abs(dip - old_dip) > 0.01 or
            abs(length - old_length) > 0.01):
            obj['geodb_needs_sync'] = True
            set_hole_material_color(obj, COLOR_NEEDS_SYNC)

        # Regenerate clean tube mesh from calculated values
        update_hole_mesh_from_geometry(obj, collar, azimuth, dip, length)

        self.report({'INFO'},
            f"Updated: Az={azimuth:.1f}, Dip={dip:.1f}, Length={length:.1f}m")
        return {'FINISHED'}


class GEODB_OT_RefreshHoleStatistics(Operator):
    """Refresh planned hole statistics"""
    bl_idname = "geodb.refresh_hole_statistics"
    bl_label = "Refresh Statistics"
    bl_description = "Recalculate statistics for all planned holes in the scene"
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Count holes and calculate statistics
        total_holes = 0
        total_meterage = 0.0
        stats_by_pad = {}

        for obj in bpy.data.objects:
            if obj.get('geodb_object_type') == 'planned_hole':
                total_holes += 1
                length = obj.get('geodb_length', 0) or 0
                total_meterage += length

                pad_name = obj.get('geodb_pad_name', 'Unknown Pad')
                if pad_name not in stats_by_pad:
                    stats_by_pad[pad_name] = {'count': 0, 'meterage': 0.0}
                stats_by_pad[pad_name]['count'] += 1
                stats_by_pad[pad_name]['meterage'] += length

        # Force panel redraw
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        # Report summary
        if total_holes > 0:
            pad_summary = ", ".join(
                f"{name}: {s['count']} holes"
                for name, s in sorted(stats_by_pad.items())
            )
            self.report({'INFO'},
                f"Statistics: {total_holes} holes, {total_meterage:.1f}m total. By pad: {pad_summary}")
        else:
            self.report({'INFO'}, "No planned holes in scene")

        return {'FINISHED'}


# Track the last known mode per object to detect mode changes
_last_object_modes = {}


def on_mode_change_handler(scene, depsgraph):
    """Handler to detect when user exits Edit Mode on a planned hole."""
    global _last_object_modes

    # Check all objects for mode changes
    for obj in bpy.data.objects:
        if obj.get('geodb_object_type') != 'planned_hole':
            continue

        current_mode = obj.mode
        last_mode = _last_object_modes.get(obj.name, 'OBJECT')

        # Detect exit from Edit Mode
        if last_mode == 'EDIT' and current_mode == 'OBJECT':
            # User just exited Edit Mode on this planned hole
            # Trigger geometry update
            logger.debug("Detected Edit Mode exit for %s, updating geometry...", obj.name)

            # We can't call operator directly from handler, so we use a timer
            def delayed_update():
                try:
                    # Make sure the object is still valid and selected
                    if obj.name in bpy.data.objects:
                        bpy.context.view_layer.objects.active = obj
                        bpy.ops.geodb.update_hole_from_mesh()
                except Exception as e:
                    logger.error("Error updating hole geometry: %s", e)
                return None  # Don't repeat

            bpy.app.timers.register(delayed_update, first_interval=0.1)

        _last_object_modes[obj.name] = current_mode


# Handler registration (classes are registered by operators/__init__.py)
_handler_registered = False


def register_handlers():
    """Register app handlers for drillhole planning (called by operators/__init__.py)"""
    global _handler_registered

    # Register the mode change handler
    if not _handler_registered:
        bpy.app.handlers.depsgraph_update_post.append(on_mode_change_handler)
        _handler_registered = True


def unregister_handlers():
    """Unregister app handlers for drillhole planning (called by operators/__init__.py)"""
    global _handler_registered

    # Unregister the mode change handler
    if _handler_registered:
        if on_mode_change_handler in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(on_mode_change_handler)
        _handler_registered = False
