"""
geoDB Blender Add-on

This add-on integrates the geoDB API with Blender, allowing users to
visualize drill hole data, samples, and perform geological modeling.
"""

import os
import sys
import importlib
from pathlib import Path

import bpy
from bpy.props import StringProperty, BoolProperty, PointerProperty, EnumProperty, IntProperty, FloatProperty
from bpy.types import PropertyGroup, AddonPreferences

bl_info = {
    "name": "geoDB Integration",
    "author": "Aqua Terra Geoscientists",
    "description": "Visualize and analyze geological data from geoDB",
    "blender": (3, 0, 0),
    "version": (0, 1, 0),
    "location": "View3D > Sidebar > geoDB",
    "warning": "Development Version",
    "category": "3D View",
    "doc_url": "https://geodb.io/docs/blender-addon",
}

# Add-on modules
modules = [
    "api",
    "operators",
    "ui",
    "core",
    "utils",
]

# Ensure dependencies are installed
def ensure_dependencies():
    """Ensure that all required dependencies are installed."""
    # Get the addon's directory
    addon_dir = Path(__file__).parent
    libs_dir = addon_dir / "libs"
    
    # Add libs directory to path if it exists
    if libs_dir.exists() and str(libs_dir) not in sys.path:
        sys.path.insert(0, str(libs_dir))
        print(f"geoDB Add-on: Added {libs_dir} to sys.path")
    
    # Also try user site-packages as fallback
    import site
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)
        print(f"geoDB Add-on: Added {user_site} to sys.path")
    
    # Try to import dependencies
    try:
        import requests
        import cryptography
        import numpy
        print("geoDB Add-on: All dependencies are available")
        return True
    except ImportError as e:
        print(f"geoDB Add-on: Missing dependency: {e}")
    
    # If we get here, dependencies are missing - try to install them
    print("geoDB Add-on: Attempting to install missing dependencies...")
    print(f"geoDB Add-on: Installing to {libs_dir}")
    
    # Create libs directory if it doesn't exist
    libs_dir.mkdir(exist_ok=True)
    
    # Get Python executable
    python_exe = sys.executable
    
    # Install dependencies
    try:
        import subprocess
        
        # Install required packages to the libs directory
        packages = ["requests", "cryptography", "numpy"]
        for package in packages:
            print(f"Installing {package} to addon directory...")
            subprocess.check_call([
                python_exe, "-m", "pip", "install", 
                "--target", str(libs_dir),
                "--upgrade", package
            ])
        
        print("geoDB Add-on: Dependencies installed successfully")
        
        # Add libs directory to path
        if str(libs_dir) not in sys.path:
            sys.path.insert(0, str(libs_dir))
        
        # Force reload of site-packages to pick up newly installed modules
        import importlib
        importlib.invalidate_caches()
        
        # Verify installation
        try:
            import requests
            import cryptography
            import numpy
            print("geoDB Add-on: Dependencies verified and ready to use")
            return True
        except ImportError as e:
            print(f"geoDB Add-on: Dependencies installed but import still failed: {e}")
            print(f"geoDB Add-on: libs_dir: {libs_dir}")
            print(f"geoDB Add-on: sys.path[0]: {sys.path[0]}")
            print("Please restart Blender to complete the installation.")
            return False
            
    except Exception as e:
        print(f"geoDB Add-on: Failed to install dependencies: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_scipy():
    """Check if scipy is installed (optional dependency for RBF interpolation)."""
    try:
        import scipy
        return True
    except ImportError:
        return False

# Scene properties
class GeoDBProperties(PropertyGroup):
    """Properties for the geoDB add-on."""
    
    is_logged_in: BoolProperty(
        name="Logged In",
        description="Whether the user is logged in to the geoDB API",
        default=False,
    )
    
    username: StringProperty(
        name="Username",
        description="The username of the logged-in user",
        default="",
    )
    
    # Data selection properties
    selected_company_id: StringProperty(
        name="Selected Company ID",
        description="ID of the selected company",
        default="",
    )
    
    selected_company_name: StringProperty(
        name="Selected Company",
        description="Name of the selected company",
        default="",
    )
    
    selected_project_id: StringProperty(
        name="Selected Project ID",
        description="ID of the selected project",
        default="",
    )

    selected_project_code: StringProperty(
        name="Selected Project Code",
        description="Code of the selected project",
        default="",
    )

    selected_project_name: StringProperty(
        name="Selected Project",
        description="Name of the selected project",
        default="",
    )
    
    selected_drill_hole_id: StringProperty(
        name="Selected Drill Hole ID",
        description="ID of the selected drill hole",
        default="",
    )
    
    selected_drill_hole_name: StringProperty(
        name="Selected Drill Hole",
        description="Name of the selected drill hole",
        default="",
    )
    
    # Visualization properties
    show_drill_traces: BoolProperty(
        name="Show Drill Traces",
        description="Show drill hole traces in the 3D view",
        default=True,
    )
    
    show_samples: BoolProperty(
        name="Show Samples",
        description="Show sample intervals in the 3D view",
        default=True,
    )
    
    selected_assay_element: StringProperty(
        name="Selected Element",
        description="Element to use for sample coloring",
        default="",
    )

    # Assay visualization properties
    selected_assay_config_id: IntProperty(
        name="Selected Assay Config ID",
        description="ID of the selected assay range configuration",
        default=-1,
    )

    selected_assay_config_name: StringProperty(
        name="Selected Assay Config Name",
        description="Name of the selected assay range configuration",
        default="",
    )

    selected_assay_units: StringProperty(
        name="Selected Assay Units",
        description="Units for the selected assay configuration",
        default="",
    )

    selected_assay_default_color: StringProperty(
        name="Selected Assay Default Color",
        description="Default color for the selected assay configuration",
        default="#CCCCCC",
    )

    selected_assay_ranges: StringProperty(
        name="Selected Assay Ranges",
        description="JSON string of the selected assay ranges",
        default="",
    )

    assay_diameter_overrides: StringProperty(
        name="Assay Diameter Overrides",
        description="JSON string of diameter overrides per config and range (persisted in .blend file)",
        default="{}",
    )

    lithology_diameter_overrides: StringProperty(
        name="Lithology Diameter Overrides",
        description="JSON string of diameter overrides per set and lithology type (persisted in .blend file)",
        default="{}",
    )

    alteration_diameter_overrides: StringProperty(
        name="Alteration Diameter Overrides",
        description="JSON string of diameter overrides per set and alteration type (persisted in .blend file)",
        default="{}",
    )

    mineralization_diameter_overrides: StringProperty(
        name="Mineralization Diameter Overrides",
        description="JSON string of diameter overrides per set and mineralization type (persisted in .blend file)",
        default="{}",
    )

    # Selected set IDs for interval visualizations
    selected_lithology_set_id: IntProperty(
        name="Selected Lithology Set ID",
        description="ID of the selected lithology set",
        default=-1,
    )

    selected_lithology_set_name: StringProperty(
        name="Selected Lithology Set Name",
        description="Name of the selected lithology set",
        default="",
    )

    selected_alteration_set_id: IntProperty(
        name="Selected Alteration Set ID",
        description="ID of the selected alteration set",
        default=-1,
    )

    selected_alteration_set_name: StringProperty(
        name="Selected Alteration Set Name",
        description="Name of the selected alteration set",
        default="",
    )

    selected_mineralization_set_id: IntProperty(
        name="Selected Mineralization Set ID",
        description="ID of the selected mineralization set",
        default=-1,
    )

    selected_mineralization_set_name: StringProperty(
        name="Selected Mineralization Set Name",
        description="Name of the selected mineralization set",
        default="",
    )

    trace_segments: StringProperty(
        name="Trace Segments",
        description="Number of segments to use for drill traces",
        default="100",
    )
    
    # ========================================================================
    # DEPRECATED: Bulk Import Properties (Not Currently Used)
    # ========================================================================
    # TODO: Remove these if bulk import feature is never implemented
    # or implement bulk import operator if needed

    # validation_results: StringProperty(
    #     name="Validation Results",
    #     description="Validation results from bulk validation operation",
    #     default="",
    # )

    # validation_log_path: StringProperty(
    #     name="Validation Log",
    #     description="Path to save drill hole validation report",
    #     default="",
    #     subtype='FILE_PATH',
    # )

    # bulk_import_mode: EnumProperty(
    #     name="Import Mode",
    #     description="Choose which drill holes to import",
    #     items=[
    #         ('ALL', "All Holes", "Import all drill holes in the project"),
    #         ('VALID_ONLY', "Valid Only", "Import only holes that pass validation"),
    #         ('RANGE', "Range", "Import a range of holes by index"),
    #     ],
    #     default='ALL',
    # )

    # bulk_start_index: IntProperty(
    #     name="Start Index",
    #     description="Start index for range import (0-based)",
    #     default=0,
    #     min=0,
    # )

    # bulk_end_index: IntProperty(
    #     name="End Index",
    #     description="End index for range import (0-based, inclusive)",
    #     default=10,
    #     min=0,
    # )

    # bulk_skip_on_error: BoolProperty(
    #     name="Skip on Error",
    #     description="Skip drill holes that have errors and continue with others",
    #     default=True,
    # )

    # bulk_create_straight_holes: BoolProperty(
    #     name="Create Straight Holes",
    #     description="Create straight holes for collars without survey data",
    #     default=True,
    # )
    
    # ========================================================================
    # NEW: Drill Visualization Workflow Properties
    # ========================================================================
    
    drill_viz_data_imported: BoolProperty(
        name="Data Imported",
        description="Whether drill data has been imported from API",
        default=False,
    )
    
    drill_viz_data_validated: BoolProperty(
        name="Data Validated",
        description="Whether imported data has been validated",
        default=False,
    )
    
    drill_viz_show_traces: BoolProperty(
        name="Show Traces",
        description="Display drill hole traces",
        default=True,
    )
    
    drill_viz_show_assays: BoolProperty(
        name="Show Assays",
        description="Display assay intervals with color coding",
        default=False,
    )
    
    drill_viz_show_lithology: BoolProperty(
        name="Show Lithology",
        description="Display lithology intervals",
        default=False,
    )
    
    drill_viz_show_alteration: BoolProperty(
        name="Show Alteration",
        description="Display alteration intervals",
        default=False,
    )
    
    drill_viz_selected_element: StringProperty(
        name="Element",
        description="Selected element for assay visualization",
        default="",
    )
    
    drill_viz_selected_config_id: IntProperty(
        name="Config ID",
        description="Selected assay range configuration ID",
        default=-1,
    )

    # ========================================================================
    # Background Operation Progress Properties
    # ========================================================================

    import_active: BoolProperty(
        name="Import Active",
        description="Whether an import operation is currently running",
        default=False,
    )

    import_progress: FloatProperty(
        name="Import Progress",
        description="Progress of current import operation (0.0 to 1.0)",
        default=0.0,
        min=0.0,
        max=1.0,
    )

    import_status: StringProperty(
        name="Import Status",
        description="Status message for current import operation",
        default="",
    )

# Add-on preferences
class GeoDBPreferences(AddonPreferences):
    """Preferences for the geoDB add-on."""
    
    bl_idname = __name__
    
    use_dev_server: BoolProperty(
        name="Use Development Server",
        description="Connect to the local development server instead of the production server",
        default=False,
    )
    
    def draw(self, context):
        layout = self.layout
        
        # Server settings
        box = layout.box()
        box.label(text="Server Settings")
        box.prop(self, "use_dev_server")
        
        if self.use_dev_server:
            box.label(text="Using development server: http://localhost:8000/api/v1/", icon='INFO')
        else:
            box.label(text="Using production server: https://geodb.io/api/v1/", icon='WORLD')
        
        # Dependencies
        box = layout.box()
        box.label(text="Dependencies")
        
        # Check if dependencies are installed
        if ensure_dependencies():
            box.label(text="Required dependencies are installed", icon='CHECKMARK')
        else:
            box.label(text="Some required dependencies are missing", icon='ERROR')
            box.operator("geodb.install_dependencies", icon='PACKAGE')
        
        # Check scipy (optional)
        if check_scipy():
            box.label(text="scipy: Installed (RBF interpolation available)", icon='CHECKMARK')
        else:
            box.label(text="scipy: Not installed (RBF interpolation disabled)", icon='INFO')
            box.label(text="Install scipy for RBF interpolation support")

# Operator to install dependencies
class GEODB_OT_InstallDependencies(bpy.types.Operator):
    """Install required dependencies for the geoDB add-on"""
    bl_idname = "geodb.install_dependencies"
    bl_label = "Install Dependencies"
    bl_description = "Install required Python packages for the geoDB add-on"
    
    def execute(self, context):
        if ensure_dependencies():
            self.report({'INFO'}, "Dependencies installed successfully. Please restart Blender or reload the add-on.")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to install dependencies. Please check the console for details.")
            return {'CANCELLED'}

# Registration
def register():
    # Register preferences first (needed for UI)
    bpy.utils.register_class(GeoDBPreferences)

    # Register properties
    bpy.utils.register_class(GeoDBProperties)
    bpy.types.Scene.geodb = PointerProperty(type=GeoDBProperties)

    # Register cache property BEFORE modules (needed by data_cache module)
    if not hasattr(bpy.types.Scene, 'geodb_data_cache'):
        bpy.types.Scene.geodb_data_cache = bpy.props.StringProperty(
            name="geoDB Data Cache",
            description="Cached drill hole data (JSON)",
            default=""
        )

    # Register dependency installer
    bpy.utils.register_class(GEODB_OT_InstallDependencies)

    # Check and install dependencies before importing modules
    if not ensure_dependencies():
        print("geoDB Add-on: Failed to install dependencies automatically.")
        print("Please install dependencies manually using the button in Add-on Preferences.")
        print("Then disable and re-enable the add-on.")
        return

    # Register modules only after dependencies are confirmed
    try:
        for module_name in modules:
            module = importlib.import_module(f".{module_name}", package=__name__)
            if hasattr(module, "register"):
                module.register()
    except ImportError as e:
        print(f"geoDB Add-on: Failed to import modules: {e}")
        print("Dependencies may have been just installed. Please disable and re-enable the add-on.")
        # Don't fail completely - user can still access preferences to install deps
        return

def unregister():
    # Unregister modules in reverse order
    try:
        for module_name in reversed(modules):
            try:
                module = importlib.import_module(f".{module_name}", package=__name__)
                if hasattr(module, "unregister"):
                    module.unregister()
            except ImportError:
                # Module wasn't loaded, skip it
                pass
    except Exception as e:
        print(f"geoDB Add-on: Error during module unregistration: {e}")
    
    # Unregister dependency installer
    bpy.utils.unregister_class(GEODB_OT_InstallDependencies)

    # Unregister cache property
    if hasattr(bpy.types.Scene, 'geodb_data_cache'):
        del bpy.types.Scene.geodb_data_cache

    # Unregister properties
    del bpy.types.Scene.geodb
    bpy.utils.unregister_class(GeoDBProperties)

    # Unregister preferences
    bpy.utils.unregister_class(GeoDBPreferences)

# Allow running the script directly from Blender's Text editor
if __name__ == "__main__":
    register()