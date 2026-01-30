"""
Drillhole Planning UI Panel.

Panel for importing drill pads, planning new holes, and sending to server.
"""

import bpy
from bpy.types import Panel


class GEODB_PT_DrillholePlanningPanel(Panel):
    """Panel for drillhole planning workflow"""
    bl_label = "Drillhole Planning"
    bl_idname = "GEODB_PT_drillhole_planning"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.geodb

        # Check if logged in
        if not props.is_logged_in:
            layout.label(text="Please log in first", icon='ERROR')
            return

        # Check if project is selected
        if not props.selected_project_id:
            layout.label(text="Select a project first", icon='ERROR')
            return

        # Show progress if operation running
        if props.import_active:
            box = layout.box()
            box.label(text="Operation in Progress...", icon='INFO')
            box.progress(factor=props.import_progress, type='BAR', text=props.import_status)
            layout.enabled = False

        # =====================================================================
        # Section 1: Import Drill Pads
        # =====================================================================
        box = layout.box()
        row = box.row()
        row.label(text="1. Import Drill Pads", icon='IMPORT')

        row = box.row()
        row.scale_y = 1.3
        row.operator("geodb.import_drill_pads", text="Import Pads from API", icon='IMPORT')

        # Show count of pads in scene
        pad_count = sum(1 for obj in bpy.data.objects
                       if obj.get('geodb_object_type') == 'drill_pad')
        if pad_count > 0:
            box.label(text=f"{pad_count} drill pad(s) in scene", icon='CHECKMARK')

        # =====================================================================
        # Section 2: Select Pad
        # =====================================================================
        box = layout.box()
        row = box.row()
        row.label(text="2. Select Drill Pad", icon='RESTRICT_SELECT_OFF')

        # Show selected pad info
        if props.planning_selected_pad_id > 0:
            row = box.row()
            row.label(text=f"Selected: {props.planning_selected_pad_name}", icon='CHECKMARK')

            # Check if selected pad has valid elevation
            pad_obj = None
            for obj in bpy.data.objects:
                if (obj.get('geodb_object_type') == 'drill_pad' and
                    obj.get('geodb_pad_id') == props.planning_selected_pad_id):
                    pad_obj = obj
                    break

            if pad_obj:
                pad_elev = pad_obj.get('geodb_centroid_z', 0)
                if pad_elev == 0 or pad_elev is None:
                    # Warning: no elevation data
                    warn_box = box.box()
                    warn_box.alert = True
                    warn_box.label(text="Warning: Pad has no elevation data!", icon='ERROR')
                    warn_box.label(text="Set manual elevation for accurate dip calculation")
        else:
            row = box.row()
            row.label(text="No pad selected", icon='INFO')

        row = box.row()
        row.operator("geodb.select_drill_pad", text="Select Active Pad", icon='EYEDROPPER')

        sub = box.row()
        sub.label(text="(Select a pad object in viewport first)")
        sub.scale_y = 0.7

        # =====================================================================
        # Section 3: Plan Drill Hole
        # =====================================================================
        box = layout.box()
        row = box.row()
        row.label(text="3. Plan Drill Hole", icon='ORIENTATION_CURSOR')

        # Only show if pad is selected
        if props.planning_selected_pad_id <= 0:
            box.label(text="Select a pad first", icon='ERROR')
            box.enabled = False
        else:
            # Hole name
            row = box.row()
            row.prop(props, "planning_hole_name", text="Hole Name")

            # Hole type
            row = box.row()
            row.prop(props, "planning_hole_type", text="Type")

            box.separator()

            # Collar Elevation Override section
            sub = box.box()
            sub.label(text="Collar Elevation:", icon='EMPTY_SINGLE_ARROW')

            row = sub.row()
            row.prop(props, "planning_use_manual_elevation", text="Override Elevation")

            if props.planning_use_manual_elevation:
                row = sub.row()
                row.prop(props, "planning_collar_elevation", text="Elevation (m)")
            else:
                # Show current pad elevation
                pad_obj = None
                for obj in bpy.data.objects:
                    if (obj.get('geodb_object_type') == 'drill_pad' and
                        obj.get('geodb_pad_id') == props.planning_selected_pad_id):
                        pad_obj = obj
                        break
                if pad_obj:
                    current_z = pad_obj.get('geodb_centroid_z', 0)
                    row = sub.row()
                    row.label(text=f"Using pad elevation: {current_z:.1f}m")

            box.separator()

            # Method selection - Manual entry
            sub = box.box()
            sub.label(text="Manual Entry:", icon='GREASEPENCIL')

            row = sub.row(align=True)
            row.prop(props, "planning_azimuth", text="Azimuth")

            row = sub.row(align=True)
            row.prop(props, "planning_dip", text="Dip")

            row = sub.row(align=True)
            row.prop(props, "planning_length", text="Length (m)")

            box.separator()

            # Option 2: 3D Cursor
            sub = box.box()
            sub.label(text="Or Calculate from 3D Cursor:", icon='PIVOT_CURSOR')

            cursor = context.scene.cursor.location
            row = sub.row()
            row.label(text=f"Cursor: ({cursor.x:.1f}, {cursor.y:.1f}, {cursor.z:.1f})")

            row = sub.row()
            row.scale_y = 1.2
            row.operator("geodb.calculate_from_cursor",
                        text="Calculate from Cursor", icon='TRACKING')

            box.separator()

            # Preview button
            row = box.row(align=True)
            row.operator("geodb.preview_planned_hole", text="Preview", icon='HIDE_OFF')
            row.operator("geodb.clear_planned_previews", text="", icon='X')

        # =====================================================================
        # Section 4: Create Hole (Local)
        # =====================================================================
        box = layout.box()
        row = box.row()
        row.label(text="4. Create Hole", icon='ADD')

        # Only enable if all required data is set
        can_create = (
            props.planning_selected_pad_id > 0 and
            props.planning_hole_name and
            props.planning_length > 0
        )

        if not can_create:
            box.label(text="Complete steps above first", icon='INFO')

        row = box.row()
        row.scale_y = 1.3
        row.enabled = can_create
        row.operator("geodb.create_planned_hole",
                    text="Create Planned Hole", icon='ADD')

        # Summary of planned hole
        if can_create:
            sub = box.box()
            sub.scale_y = 0.8
            col = sub.column(align=True)
            col.label(text=f"Hole: {props.planning_hole_name}")
            col.label(text=f"Pad: {props.planning_selected_pad_name}")
            col.label(text=f"Az: {props.planning_azimuth:.1f} | Dip: {props.planning_dip:.1f} | Len: {props.planning_length:.1f}m")

        # =====================================================================
        # Section 5: Sync with Server
        # =====================================================================
        box = layout.box()
        row = box.row()
        row.label(text="5. Sync with Server", icon='FILE_REFRESH')

        # Count holes by sync status
        holes_new = 0  # No server ID
        holes_modified = 0  # Has server ID but needs sync
        holes_synced = 0  # Synced with server

        for obj in bpy.data.objects:
            if obj.get('geodb_object_type') == 'planned_hole':
                hole_id = obj.get('geodb_hole_id')
                needs_sync = obj.get('geodb_needs_sync', False)

                if hole_id is None:
                    holes_new += 1
                elif needs_sync:
                    holes_modified += 1
                else:
                    holes_synced += 1

        total_holes = holes_new + holes_modified + holes_synced

        # Show status
        if total_holes > 0:
            sub = box.box()
            sub.scale_y = 0.85
            col = sub.column(align=True)

            if holes_new > 0:
                col.label(text=f"{holes_new} new (not on server)", icon='PLUS')
            if holes_modified > 0:
                col.label(text=f"{holes_modified} modified locally", icon='GREASEPENCIL')
            if holes_synced > 0:
                col.label(text=f"{holes_synced} synced", icon='CHECKMARK')
        else:
            box.label(text="No planned holes in scene", icon='INFO')

        # Sync button
        row = box.row()
        row.scale_y = 1.5
        has_pending = holes_new > 0 or holes_modified > 0
        if has_pending:
            row.alert = True  # Highlight if there are pending changes
        row.operator("geodb.sync_planned_holes",
                    text="Sync All Planned Holes", icon='FILE_REFRESH')

        # Tip for editing
        if total_holes > 0:
            sub = box.row()
            sub.scale_y = 0.7
            sub.label(text="Tip: Edit holes in Edit Mode, then sync")

        # =====================================================================
        # Section 6: Statistics
        # =====================================================================
        if total_holes > 0:
            box = layout.box()
            row = box.row()
            row.label(text="6. Statistics", icon='GRAPH')

            # Refresh button
            row = box.row()
            row.operator("geodb.refresh_hole_statistics",
                        text="Refresh Statistics", icon='FILE_REFRESH')

            # Calculate statistics
            total_meterage = 0.0
            stats_by_pad = {}  # pad_name -> {'count': int, 'meterage': float}

            for obj in bpy.data.objects:
                if obj.get('geodb_object_type') == 'planned_hole':
                    length = obj.get('geodb_length', 0) or 0
                    total_meterage += length

                    # Get pad info
                    pad_id = obj.get('geodb_pad_id')
                    pad_name = obj.get('geodb_pad_name', 'Unknown Pad')

                    if pad_name not in stats_by_pad:
                        stats_by_pad[pad_name] = {'count': 0, 'meterage': 0.0}

                    stats_by_pad[pad_name]['count'] += 1
                    stats_by_pad[pad_name]['meterage'] += length

            # Total summary
            sub = box.box()
            sub.scale_y = 0.85
            col = sub.column(align=True)
            col.label(text=f"Total: {total_holes} holes, {total_meterage:.1f}m", icon='ASSET_MANAGER')

            # By pad breakdown
            if stats_by_pad:
                col.separator()
                col.label(text="By Pad:", icon='OUTLINER_OB_MESH')
                for pad_name, stats in sorted(stats_by_pad.items()):
                    col.label(text=f"  {pad_name}: {stats['count']} holes, {stats['meterage']:.1f}m")

        # =====================================================================
        # Section 7: Selected Hole Info (if a planned hole is selected)
        # =====================================================================
        obj = context.active_object
        if obj and obj.get('geodb_object_type') == 'planned_hole':
            box = layout.box()
            row = box.row()
            row.label(text="Selected Hole", icon='ORIENTATION_CURSOR')

            sub = box.box()
            sub.scale_y = 0.85
            col = sub.column(align=True)

            hole_name = obj.get('geodb_hole_name', 'Unknown')
            hole_id = obj.get('geodb_hole_id')
            needs_sync = obj.get('geodb_needs_sync', False)

            col.label(text=f"Name: {hole_name}")
            col.label(text=f"Az: {obj.get('geodb_azimuth', 0):.1f} | Dip: {obj.get('geodb_dip', 0):.1f} | Len: {obj.get('geodb_length', 0):.1f}m")

            # Sync status
            if hole_id is None:
                col.label(text="Status: New (not on server)", icon='PLUS')
            elif needs_sync:
                col.label(text="Status: Modified locally", icon='GREASEPENCIL')
            else:
                col.label(text="Status: Synced", icon='CHECKMARK')

            # Manual update button (in case auto-detection missed it)
            box.separator()
            row = box.row()
            row.scale_y = 1.2
            row.operator("geodb.update_hole_from_mesh",
                        text="Recalculate from Curve", icon='FILE_REFRESH')


# Registration
classes = (
    GEODB_PT_DrillholePlanningPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
