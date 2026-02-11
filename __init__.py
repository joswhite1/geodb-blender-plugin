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
from bpy.app.handlers import persistent

# Import logger with fallback for early loading before package is fully available
try:
    from .utils.logging import logger, set_debug_mode
except ImportError:
    import logging
    logger = logging.getLogger('geodb')
    def set_debug_mode(enabled): pass


def is_dev_mode_enabled():
    """Check if development mode is enabled.

    Development mode is enabled when a file called 'dev_mode.md' exists
    in the add-on's directory. This file is gitignored, so it will
    only be present in development environments.

    Returns:
        bool: True if dev_mode.md exists, False otherwise.
    """
    addon_dir = Path(__file__).parent
    dev_mode_file = addon_dir / "dev_mode.md"
    return dev_mode_file.exists()


bl_info = {
    "name": "geoDB Integration",
    "author": "Aqua Terra Geoscientists",
    "description": "Visualize and analyze geological data from geoDB",
    "blender": (3, 0, 0),
    "version": (0, 2, 0),
    "location": "View3D > Sidebar > geoDB",
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
    # Add user site-packages to path if not already present
    import site
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)
        logger.debug("Added user site-packages to path")

    # Try to import dependencies
    try:
        import requests
        import cryptography
        import numpy
        import scipy
        import skimage
        logger.debug("All dependencies available")
        return True
    except ImportError as e:
        logger.warning("Missing dependency: %s", e)

    # If we get here, dependencies are missing - try to install them
    logger.info("Installing missing dependencies...")

    # Get Python executable
    python_exe = sys.executable

    # Install dependencies
    try:
        import subprocess

        # Install required packages directly to Blender's Python
        packages = [
            "requests==2.31.0",
            "cryptography==42.0.5",
            "numpy==1.26.4",
            "scipy==1.12.0",
            "scikit-image==0.22.0",
        ]
        for package in packages:
            logger.info("Installing %s...", package)
            subprocess.check_call([
                python_exe, "-m", "pip", "install",
                "--no-cache-dir",
                "--disable-pip-version-check",
                package
            ])

        logger.info("Dependencies installed successfully")

        # Force reload of site-packages to pick up newly installed modules
        import importlib
        importlib.invalidate_caches()

        # Verify installation
        try:
            import requests
            import cryptography
            import numpy
            import scipy
            import skimage
            logger.info("Dependencies verified and ready to use")
            return True
        except ImportError as e:
            logger.warning("Dependencies installed but import still failed: %s", e)
            logger.info("Please restart Blender to complete the installation.")
            return False

    except Exception as e:
        logger.error("Failed to install dependencies: %s", e)
        logger.debug("Dependency installation error details", exc_info=True)
        return False

def check_scipy():
    """Check if scipy is installed (optional dependency for RBF interpolation)."""
    try:
        import scipy
        return True
    except ImportError:
        return False


@persistent
def validate_auth_on_load(dummy):
    """Validate authentication state when a .blend file is loaded.

    This handler ensures that the UI login state matches the actual
    API authentication state. When a file is loaded, the is_logged_in
    property may be True (from saved state), but the API client won't
    have a valid token in memory.
    """
    try:
        # Import here to avoid circular imports during addon registration
        from .api.auth import get_api_client

        scene = bpy.context.scene
        if not hasattr(scene, 'geodb'):
            return

        # If the scene says we're logged in, verify actual auth state
        if scene.geodb.is_logged_in:
            client = get_api_client()

            # Check if the client actually has a token in memory
            if not client.is_authenticated():
                # Token is not in memory - check if there's a saved token to unlock
                if client.has_saved_token():
                    # There's a saved token - user needs to unlock it
                    # Reset the login state so the UI shows the unlock option
                    scene.geodb.is_logged_in = False
                    logger.info("Session expired. Please unlock your saved token to continue.")
                else:
                    # No saved token available - user needs to log in again
                    scene.geodb.is_logged_in = False
                    scene.geodb.username = ""
                    logger.info("Session expired. Please log in again.")
    except Exception as e:
        # Don't break file loading if there's an error
        logger.error("Error validating auth state: %s", e)


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
        maxlen=200,
    )

    # Data selection properties
    selected_company_id: StringProperty(
        name="Selected Company ID",
        description="ID of the selected company",
        default="",
        maxlen=200,
    )

    selected_company_name: StringProperty(
        name="Selected Company",
        description="Name of the selected company",
        default="",
        maxlen=200,
    )

    selected_project_id: StringProperty(
        name="Selected Project ID",
        description="ID of the selected project",
        default="",
        maxlen=200,
    )

    selected_project_code: StringProperty(
        name="Selected Project Code",
        description="Code of the selected project",
        default="",
        maxlen=200,
    )

    selected_project_name: StringProperty(
        name="Selected Project",
        description="Name of the selected project",
        default="",
        maxlen=200,
    )

    selected_drill_hole_id: StringProperty(
        name="Selected Drill Hole ID",
        description="ID of the selected drill hole",
        default="",
        maxlen=200,
    )

    selected_drill_hole_name: StringProperty(
        name="Selected Drill Hole",
        description="Name of the selected drill hole",
        default="",
        maxlen=200,
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

    auto_adjust_view: BoolProperty(
        name="Auto-Adjust View on Import",
        description="Automatically set orthographic view, increase clip distance, and frame imported data",
        default=True,
    )

    selected_assay_element: StringProperty(
        name="Selected Element",
        description="Element to use for sample coloring",
        default="",
        maxlen=200,
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
        maxlen=200,
    )

    selected_assay_units: StringProperty(
        name="Selected Assay Units",
        description="Units for the selected assay configuration",
        default="",
        maxlen=200,
    )

    selected_assay_default_color: StringProperty(
        name="Selected Assay Default Color",
        description="Default color for the selected assay configuration",
        default="#CCCCCC",
        maxlen=200,
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
        maxlen=200,
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
        maxlen=200,
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
        maxlen=200,
    )

    trace_segments: StringProperty(
        name="Trace Segments",
        description="Number of segments to use for drill traces",
        default="100",
        maxlen=200,
    )

    # ========================================================================
    # Drill Visualization Workflow Properties
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
        maxlen=200,
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
        maxlen=200,
    )

    # ========================================================================
    # Drillhole Planning Properties
    # ========================================================================

    planning_selected_pad_id: IntProperty(
        name="Selected Pad ID",
        description="ID of the selected drill pad for planning",
        default=-1,
    )

    planning_selected_pad_name: StringProperty(
        name="Selected Pad",
        description="Name of the selected drill pad",
        default="",
        maxlen=200,
    )

    planning_hole_name: StringProperty(
        name="Hole Name",
        description="Name for the planned drill hole (e.g., PLN-001)",
        default="PLN-001",
        maxlen=100,
    )

    planning_azimuth: FloatProperty(
        name="Azimuth",
        description="Drill hole azimuth (0-360 degrees, 0=North)",
        default=0.0,
        min=0.0,
        max=360.0,
        precision=1,
    )

    planning_dip: FloatProperty(
        name="Dip",
        description="Drill hole dip (-90 to 0 degrees, -90=vertical down)",
        default=-60.0,
        min=-90.0,
        max=0.0,
        precision=1,
    )

    planning_length: FloatProperty(
        name="Length",
        description="Planned hole length in meters",
        default=200.0,
        min=1.0,
        max=2000.0,
        precision=1,
    )

    planning_hole_type: EnumProperty(
        name="Hole Type",
        description="Type of drill hole",
        items=[
            ('DD', 'Diamond', 'Diamond core drilling'),
            ('RC', 'Reverse Circulation', 'RC drilling'),
            ('RAB', 'Rotary Air Blast', 'RAB drilling'),
        ],
        default='DD',
    )

    planning_collar_elevation: FloatProperty(
        name="Collar Elevation",
        description="Manual collar elevation override (meters). Set to 0 to use pad data.",
        default=0.0,
        precision=1,
    )

    planning_use_manual_elevation: BoolProperty(
        name="Use Manual Elevation",
        description="Override the pad elevation with a manual value",
        default=False,
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

    enable_debug_logging: BoolProperty(
        name="Enable Debug Logging",
        description="Log detailed debug information to the console (may contain sensitive data, use for troubleshooting only)",
        default=False,
        update=lambda self, context: set_debug_mode(self.enable_debug_logging),
    )

    def draw(self, context):
        layout = self.layout

        # Server settings (only shown in development mode)
        if is_dev_mode_enabled():
            box = layout.box()
            box.label(text="Server Settings (Dev Mode)", icon='CONSOLE')
            box.prop(self, "use_dev_server")

            if self.use_dev_server:
                box.label(text="Using development server: http://localhost:8000/api/v1/", icon='INFO')
            else:
                box.label(text="Using production server: https://geodb.io/api/v1/", icon='WORLD')

        # Logging settings
        box = layout.box()
        box.label(text="Logging", icon='TEXT')
        box.prop(self, "enable_debug_logging")
        if self.enable_debug_logging:
            box.label(text="Warning: Debug logs may contain sensitive information", icon='ERROR')

        # Dependencies
        box = layout.box()
        box.label(text="Dependencies")

        # Check if all dependencies (including scipy) are installed
        deps_ok = ensure_dependencies()
        scipy_ok = check_scipy()

        if deps_ok and scipy_ok:
            box.label(text="All dependencies installed", icon='CHECKMARK')
            box.label(text="RBF interpolation available", icon='CHECKMARK')
        else:
            if not deps_ok:
                box.label(text="Some required dependencies are missing", icon='ERROR')
            if not scipy_ok:
                box.label(text="scipy: Not installed (RBF interpolation disabled)", icon='X')
            box.operator("geodb.install_dependencies", text="Install All Dependencies", icon='PACKAGE')

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
        logger.warning("Failed to install dependencies automatically.")
        logger.info("Please install dependencies manually using the button in Add-on Preferences.")
        logger.info("Then disable and re-enable the add-on.")
        return

    # Register modules only after dependencies are confirmed
    try:
        for module_name in modules:
            module = importlib.import_module(f".{module_name}", package=__name__)
            if hasattr(module, "register"):
                module.register()
    except ImportError as e:
        logger.warning("Failed to import modules: %s", e)
        logger.info("Dependencies may have been just installed. Please disable and re-enable the add-on.")
        # Don't fail completely - user can still access preferences to install deps
        return

    # Register load_post handler to validate auth state when files are opened
    if validate_auth_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(validate_auth_on_load)

def unregister():
    # Unregister load_post handler
    if validate_auth_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(validate_auth_on_load)

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
        logger.error("Error during module unregistration: %s", e)

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
