"""
UI module for the geoDB Blender add-on.

This module provides the user interface for the add-on, including
panels, operators, and menus.
"""

import bpy
from bpy.types import Panel

class GEODB_PT_MainPanel(Panel):
    """Main panel for the geoDB add-on"""
    bl_label = "geoDB"
    bl_idname = "GEODB_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Check if user is logged in
        if not scene.geodb.is_logged_in:
            layout.label(text="Please log in to access geoDB", icon='INFO')
            return
        
        # Welcome message
        layout.label(text=f"Welcome, {scene.geodb.username}!")

# Registration
def register():
    bpy.utils.register_class(GEODB_PT_MainPanel)

    # Register data panels
    from .data_panels import register as register_data_panels
    register_data_panels()

    # Register simulation panels
    from .simulation_panels import register as register_simulation_panels
    register_simulation_panels()

    # Register drill visualization panel (assays only)
    from .drill_visualization_panel import register as register_drill_viz
    register_drill_viz()

    # Register interval visualization panel (lithology and alteration)
    from .interval_visualization_panel import register as register_interval_viz
    register_interval_viz()

def unregister():
    # Unregister interval visualization panel
    from .interval_visualization_panel import unregister as unregister_interval_viz
    unregister_interval_viz()

    # Unregister drill visualization panel
    from .drill_visualization_panel import unregister as unregister_drill_viz
    unregister_drill_viz()

    # Unregister simulation panels
    from .simulation_panels import unregister as unregister_simulation_panels
    unregister_simulation_panels()

    # Unregister data panels
    from .data_panels import unregister as unregister_data_panels
    unregister_data_panels()

    bpy.utils.unregister_class(GEODB_PT_MainPanel)