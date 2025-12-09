"""
Drillhole planning operators.

Operators for importing drill pads, creating planned holes,
and sending planned holes to the server.
"""

import bpy
from bpy.types import Operator

from .async_base import GeoDBAsyncOperator
from ..api.data import GeoDBData
from ..utils.drillpad_mesh import (
    create_drillpad_mesh,
    update_drillpad_mesh,
    find_existing_drillpad,
    calculate_hole_geometry,
    create_planned_hole_preview,
    get_pad_centroid
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
            import traceback
            traceback.print_exc()

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

            print(f"Pad {name}: elevation={elevation}, centroid={centroid}")

            if not vertices_2d or len(vertices_2d) < 3:
                print(f"Skipping pad {name}: insufficient vertices")
                continue

            try:
                # Check if this pad already exists in the scene
                existing_obj = find_existing_drillpad(pad_id)

                if existing_obj:
                    # Update existing pad geometry
                    print(f"Updating existing pad: {name}")
                    update_drillpad_mesh(
                        obj=existing_obj,
                        vertices_2d=vertices_2d,
                        elevation=elevation,
                        extrusion_height=10.0
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
                    print(f"Creating new pad: {name}")
                    obj = create_drillpad_mesh(
                        name=f"Pad_{name}",
                        vertices_2d=vertices_2d,
                        elevation=elevation,
                        extrusion_height=10.0,
                        color_hex="#4CAF50"
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
                print(f"Error processing pad {name}: {e}")
                import traceback
                traceback.print_exc()

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


class GEODB_OT_CreatePlannedHole(GeoDBAsyncOperator):
    """Create a planned drill hole and send to server"""
    bl_idname = "geodb.create_planned_hole"
    bl_label = "Create Planned Hole"
    bl_description = "Create planned drill hole and send to geoDB server"
    bl_options = {'REGISTER', 'UNDO'}

    _result = None
    _hole_params = None

    def download_data(self):
        """Background thread - send to API"""
        try:
            self.__class__._status = "Preparing hole data..."
            self.__class__._progress = 0.2

            scene = bpy.context.scene
            props = scene.geodb

            # Validate inputs
            if not props.planning_selected_pad_name:
                self.__class__._error = "No drill pad selected"
                return

            if not props.planning_hole_name:
                self.__class__._error = "No hole name specified"
                return

            # Store params for main thread
            # Include elevation override info
            elevation_override = None
            if props.planning_use_manual_elevation:
                elevation_override = props.planning_collar_elevation

            self.__class__._hole_params = {
                'hole_name': props.planning_hole_name,
                'pad_name': props.planning_selected_pad_name,
                'pad_id': props.planning_selected_pad_id,
                'azimuth': props.planning_azimuth,
                'dip': props.planning_dip,
                'length': props.planning_length,
                'hole_type': props.planning_hole_type,
                'elevation_override': elevation_override,
            }

            self.__class__._status = "Sending to server..."
            self.__class__._progress = 0.4

            # Build hole data with natural keys
            hole_data = {
                "name": props.planning_hole_name,
                "project": {
                    "name": props.selected_project_name,
                    "company": props.selected_company_name
                },
                "pad": {
                    "name": props.planning_selected_pad_name,
                    "project": {
                        "name": props.selected_project_name,
                        "company": props.selected_company_name
                    }
                },
                "hole_status": "PL",
                "hole_type": props.planning_hole_type,
                "total_depth": props.planning_length,
                "azimuth": props.planning_azimuth,
                "dip": props.planning_dip
            }

            self.__class__._progress = 0.6

            success, result = GeoDBData.create_planned_drill_hole(hole_data)

            if not success:
                error_msg = result.get('error', str(result)) if isinstance(result, dict) else str(result)
                self.__class__._error = f"Failed to create hole: {error_msg}"
                return

            self.__class__._result = result
            self.__class__._progress = 1.0
            self.__class__._status = "Hole created successfully"

        except Exception as e:
            self.__class__._error = str(e)
            import traceback
            traceback.print_exc()

    def finish_in_main_thread(self, context):
        """Main thread - update UI and create visualization"""
        result = self.__class__._result
        params = self.__class__._hole_params

        if not result or not params:
            return

        hole_name = result.get('name', params['hole_name'])

        # Remove preview
        preview_name = f"Preview_{hole_name}"
        if preview_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[preview_name], do_unlink=True)

        # Find pad to get collar coordinates
        pad_obj = None
        for obj in bpy.data.objects:
            if (obj.get('geodb_object_type') == 'drill_pad' and
                obj.get('geodb_pad_id') == params['pad_id']):
                pad_obj = obj
                break

        if pad_obj:
            collar = get_pad_centroid(pad_obj, params.get('elevation_override'))

            if collar:
                # Create permanent visualization (blue for confirmed)
                hole_obj = create_planned_hole_preview(
                    name=f"PlannedHole_{hole_name}",
                    collar=collar,
                    azimuth=params['azimuth'],
                    dip=params['dip'],
                    length=params['length'],
                    color_hex="#2196F3",  # Blue for confirmed planned holes
                    tube_radius=1.0
                )

                # Tag as permanent planned hole
                hole_obj['geodb_object_type'] = 'planned_hole'
                hole_obj['geodb_hole_id'] = result.get('id')
                hole_obj['geodb_hole_name'] = hole_name
                hole_obj['geodb_is_preview'] = False
                hole_obj['geodb_azimuth'] = params['azimuth']
                hole_obj['geodb_dip'] = params['dip']
                hole_obj['geodb_length'] = params['length']
                hole_obj['geodb_hole_type'] = params['hole_type']
                hole_obj['geodb_pad_name'] = params['pad_name']

        self.report({'INFO'}, f"Created planned hole: {hole_name}")


# Registration
classes = (
    GEODB_OT_ImportDrillPads,
    GEODB_OT_SelectDrillPad,
    GEODB_OT_CalculateFromCursor,
    GEODB_OT_PreviewPlannedHole,
    GEODB_OT_ClearPreviews,
    GEODB_OT_CreatePlannedHole,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
