"""
UI module for the geoDB Blender add-on.

This module provides the user interface for the add-on, including
panels, operators, and menus.
"""

import bpy
from bpy.types import Panel

from .data_panels import (
    GEODB_PT_DataSelection,
    GEODB_PT_Visualization,
    GEODB_OT_SelectCompany,
    GEODB_OT_LoadProjects,
    GEODB_OT_SelectProject,
    GEODB_OT_LoadDrillHoles,
    GEODB_OT_SelectDrillHole,
    GEODB_OT_VisualizeDrillHole,
    GEODB_OT_ApplyColorMapping,
    GEODB_OT_ClearVisualizations,
)

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
    
    # Register drill visualization panel (new comprehensive workflow)
    from .drill_visualization_panel import register as register_drill_viz
    register_drill_viz()

def unregister():
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