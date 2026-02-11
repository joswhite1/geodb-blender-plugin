"""
Simulation and interpolation panels for the geoDB Blender add-on.

This module provides UI panels for simulating drill hole data and
performing RBF interpolation.
"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import (StringProperty, FloatProperty, IntProperty,
                       EnumProperty, BoolProperty)

from ..core.simulation import (PorphyryCopperSimulator, GoldVeinSimulator,
                               visualize_simulated_drill_holes)
from ..core.interpolation import (interpolate_from_samples, interpolate_from_cache,
                                  get_available_elements, get_available_assay_configs,
                                  SCIPY_AVAILABLE, SearchEllipsoid,
                                  create_ellipsoid_visualization, update_ellipsoid_from_object)
from ..core.data_cache import DrillDataCache
from ..api.data import GeoDBData


# Simulation operator
class GEODB_OT_SimulateDrillData(Operator):
    """Simulate drill hole data for testing"""
    bl_idname = "geodb.simulate_drill_data"
    bl_label = "Simulate Drill Data"
    bl_description = "Generate simulated drill hole data for different deposit types"
    bl_options = {'REGISTER', 'UNDO'}
    
    deposit_type: EnumProperty(
        name="Deposit Type",
        description="Type of mineral deposit to simulate",
        items=[
            ('PORPHYRY_CU', "Porphyry Copper-Gold", "Simulate a porphyry copper-gold deposit"),
            ('GOLD_VEIN', "Gold-Silver Vein", "Simulate a gold-silver vein deposit"),
        ],
        default='PORPHYRY_CU',
    )
    
    num_drillholes: IntProperty(
        name="Number of Drill Holes",
        description="Number of drill holes to simulate",
        default=10,
        min=1,
        max=100,
    )
    
    samples_per_hole: IntProperty(
        name="Samples per Hole",
        description="Number of samples along each drill hole",
        default=20,
        min=5,
        max=200,
    )
    
    area_size: FloatProperty(
        name="Area Size",
        description="Size of the exploration area (meters)",
        default=1000.0,
        min=10.0,
        max=10000.0,
    )
    
    max_depth: FloatProperty(
        name="Max Depth",
        description="Maximum drill hole depth (meters)",
        default=500.0,
        min=10.0,
        max=2000.0,
    )
    
    # Porphyry copper parameters
    cu_max: FloatProperty(
        name="Max Cu Grade (%)",
        description="Maximum copper grade (percent)",
        default=1.5,
        min=0.1,
        max=10.0,
    )
    
    cu_background: FloatProperty(
        name="Background Cu (%)",
        description="Background copper grade (percent)",
        default=0.01,
        min=0.0,
        max=1.0,
    )
    
    au_max_porphyry: FloatProperty(
        name="Max Au Grade (ppm)",
        description="Maximum gold grade in porphyry (ppm)",
        default=0.5,
        min=0.01,
        max=10.0,
    )
    
    au_background_porphyry: FloatProperty(
        name="Background Au (ppm)",
        description="Background gold grade in porphyry (ppm)",
        default=0.005,
        min=0.0,
        max=1.0,
    )
    
    # Gold vein parameters
    au_max_vein: FloatProperty(
        name="Max Au Grade (ppm)",
        description="Maximum gold grade in vein (ppm)",
        default=20.0,
        min=0.1,
        max=1000.0,
    )
    
    au_background_vein: FloatProperty(
        name="Background Au (ppm)",
        description="Background gold grade in vein (ppm)",
        default=0.01,
        min=0.0,
        max=1.0,
    )
    
    ag_max: FloatProperty(
        name="Max Ag Grade (ppm)",
        description="Maximum silver grade (ppm)",
        default=50.0,
        min=0.1,
        max=1000.0,
    )
    
    ag_background: FloatProperty(
        name="Background Ag (ppm)",
        description="Background silver grade (ppm)",
        default=0.05,
        min=0.0,
        max=1.0,
    )
    
    vein_strike: FloatProperty(
        name="Vein Strike",
        description="Strike direction of the vein (degrees)",
        default=45.0,
        min=0.0,
        max=360.0,
    )
    
    vein_dip: FloatProperty(
        name="Vein Dip",
        description="Dip angle of the vein (degrees)",
        default=70.0,
        min=0.0,
        max=90.0,
    )
    
    vein_thickness: FloatProperty(
        name="Vein Thickness",
        description="Thickness of the vein (meters)",
        default=5.0,
        min=0.1,
        max=50.0,
    )
    
    orebody_size: FloatProperty(
        name="Orebody Size",
        description="Size/radius of the orebody or vein length (meters)",
        default=200.0,
        min=10.0,
        max=1000.0,
    )

    # Custom orebody center
    use_custom_center: BoolProperty(
        name="Custom Orebody Center",
        description="Specify a custom orebody/vein center position instead of auto-calculating",
        default=False,
    )

    orebody_center_x: FloatProperty(
        name="Center X",
        description="X coordinate of orebody center (meters)",
        default=500.0,
        soft_min=0.0,
        soft_max=10000.0,
    )

    orebody_center_y: FloatProperty(
        name="Center Y",
        description="Y coordinate of orebody center (meters)",
        default=500.0,
        soft_min=0.0,
        soft_max=10000.0,
    )

    orebody_center_z: FloatProperty(
        name="Center Z (Depth)",
        description="Z coordinate of orebody center (negative = below surface, meters)",
        default=-150.0,
        soft_min=-2000.0,
        soft_max=0.0,
    )

    noise_level: FloatProperty(
        name="Noise Level",
        description="Amount of noise to add to grades (0-1)",
        default=0.2,
        min=0.0,
        max=1.0,
    )
    
    show_traces: BoolProperty(
        name="Show Drill Traces",
        description="Show drill hole traces",
        default=True,
    )
    
    show_samples: BoolProperty(
        name="Show Samples",
        description="Show sample intervals",
        default=True,
    )

    sample_radius: FloatProperty(
        name="Sample Radius",
        description="Radius of sample cylinders in meters (0 = thin lines)",
        default=5.0,
        min=0.0,
        max=50.0,
    )

    color_samples: BoolProperty(
        name="Color Samples",
        description="Apply color to samples based on assay values",
        default=True,
    )

    color_mode: EnumProperty(
        name="Color Mode",
        description="How to color the samples",
        items=[
            ('GRADIENT', "Gradient", "Smooth color gradient from low to high values"),
            ('RANGES', "Grade Ranges", "Discrete color ranges (like geologist color codes)"),
        ],
        default='GRADIENT',
    )

    color_map: EnumProperty(
        name="Color Map",
        description="Color map for gradient mode",
        items=[
            ('RAINBOW', "Rainbow", "Blue (low) to Red (high)"),
            ('VIRIDIS', "Viridis", "Scientific color map"),
            ('PLASMA', "Plasma", "Warm color map"),
            ('MAGMA', "Magma", "Dark to bright color map"),
        ],
        default='RAINBOW',
    )

    show_lithology: BoolProperty(
        name="Show Lithology",
        description="Display lithology intervals along drill holes",
        default=False,
    )

    show_alteration: BoolProperty(
        name="Show Alteration",
        description="Display alteration intervals along drill holes",
        default=False,
    )

    interval_radius: FloatProperty(
        name="Interval Radius",
        description="Radius of lithology/alteration interval tubes in meters",
        default=3.0,
        min=0.5,
        max=50.0,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=450)
    
    def draw(self, context):
        layout = self.layout
        
        layout.prop(self, "deposit_type")
        layout.separator()
        
        # General parameters
        box = layout.box()
        box.label(text="General Parameters", icon='PREFERENCES')
        box.prop(self, "num_drillholes")
        box.prop(self, "samples_per_hole")
        box.prop(self, "area_size")
        box.prop(self, "max_depth")
        box.prop(self, "orebody_size")
        box.prop(self, "noise_level")

        # Custom orebody center
        box.separator()
        box.prop(self, "use_custom_center")
        if self.use_custom_center:
            col = box.column(align=True)
            col.prop(self, "orebody_center_x")
            col.prop(self, "orebody_center_y")
            col.prop(self, "orebody_center_z")
        else:
            box.label(text=f"Auto: center at area/2, depth/3", icon='INFO')
        
        # Deposit-specific parameters
        box = layout.box()
        if self.deposit_type == 'PORPHYRY_CU':
            box.label(text="Porphyry Copper-Gold Parameters", icon='MATERIAL')
            box.prop(self, "cu_max")
            box.prop(self, "cu_background")
            box.prop(self, "au_max_porphyry")
            box.prop(self, "au_background_porphyry")
        else:  # GOLD_VEIN
            box.label(text="Gold-Silver Vein Parameters", icon='MATERIAL')
            box.prop(self, "au_max_vein")
            box.prop(self, "au_background_vein")
            box.prop(self, "ag_max")
            box.prop(self, "ag_background")
            box.prop(self, "vein_strike")
            box.prop(self, "vein_dip")
            box.prop(self, "vein_thickness")
        
        # Visualization options
        box = layout.box()
        box.label(text="Visualization", icon='VIEW3D')
        box.prop(self, "show_traces")
        box.prop(self, "show_samples")

        if self.show_samples:
            box.prop(self, "sample_radius")
            box.prop(self, "color_samples")
            if self.color_samples:
                box.prop(self, "color_mode")
                if self.color_mode == 'GRADIENT':
                    box.prop(self, "color_map")

        # Lithology and alteration visualization
        box.separator()
        box.label(text="Geological Intervals:", icon='MESH_CYLINDER')
        box.prop(self, "show_lithology")
        box.prop(self, "show_alteration")
        if self.show_lithology or self.show_alteration:
            box.prop(self, "interval_radius")
    
    def execute(self, context):
        try:
            # Determine orebody/vein center
            if self.use_custom_center:
                center = (self.orebody_center_x, self.orebody_center_y, self.orebody_center_z)
            else:
                # Auto-calculate: center of area, 1/3 depth for good grade distribution
                center = None  # Let simulator use its default

            # Create simulator based on deposit type
            if self.deposit_type == 'PORPHYRY_CU':
                simulator = PorphyryCopperSimulator(
                    seed=42,
                    orebody_center=center,
                    orebody_size=self.orebody_size,
                    cu_max=self.cu_max,
                    cu_background=self.cu_background,
                    au_max=self.au_max_porphyry,
                    au_background=self.au_background_porphyry,
                    noise_level=self.noise_level
                )
                color_element = 'Cu_pct'
            else:  # GOLD_VEIN
                simulator = GoldVeinSimulator(
                    seed=42,
                    vein_center=center,
                    vein_strike=self.vein_strike,
                    vein_dip=self.vein_dip,
                    vein_thickness=self.vein_thickness,
                    vein_length=self.orebody_size,
                    au_max=self.au_max_vein,
                    au_background=self.au_background_vein,
                    ag_max=self.ag_max,
                    ag_background=self.ag_background,
                    noise_level=self.noise_level
                )
                color_element = 'Au_ppm'
            
            # Generate drill holes
            self.report({'INFO'}, "Generating simulated drill data...")
            drill_holes = simulator.generate_drill_holes(
                self.num_drillholes,
                self.area_size,
                self.max_depth,
                self.samples_per_hole
            )

            # Store simulated data in cache so RBF interpolation can use it
            from ..core.data_cache import DrillDataCache
            from ..core.simulation import generate_assay_configs_from_drill_holes

            # Convert drill_holes to cache format (samples by hole ID)
            samples_by_hole = {}
            available_elements = set()

            for dh in drill_holes:
                hole_id = str(dh['id'])
                samples_by_hole[hole_id] = dh['samples']

                # Collect available elements
                for sample in dh['samples']:
                    assay = sample.get('assay', {})
                    for elem in assay.get('elements', []):
                        available_elements.add(elem.get('element'))

            # Generate default assay range configurations from the simulated data
            assay_range_configs = generate_assay_configs_from_drill_holes(drill_holes)

            # Build cache data
            cache_data = {
                'project_id': -1,  # Simulated data indicator
                'company_id': -1,
                'project_name': f'Simulated {self.deposit_type.replace("_", " ").title()}',
                'company_name': 'Simulation',
                'samples': samples_by_hole,
                'available_elements': sorted(list(available_elements)),
                'assay_range_configs': assay_range_configs,  # Include generated configs
                'is_simulated': True,  # Flag to indicate this is simulated data
            }

            DrillDataCache.set_cache(cache_data)
            self.report({'INFO'}, f"Cached {len(available_elements)} elements with grade range configs for RBF interpolation")

            # Visualize with color options
            visualize_simulated_drill_holes(
                drill_holes,
                show_traces=self.show_traces,
                show_samples=self.show_samples,
                show_lithology=self.show_lithology,
                show_alteration=self.show_alteration,
                color_element=color_element if self.color_samples else None,
                color_mode=self.color_mode,
                color_map=self.color_map,
                sample_radius=self.sample_radius,
                interval_radius=self.interval_radius,
            )

            total_samples = sum(len(dh['samples']) for dh in drill_holes)
            self.report({'INFO'},
                       f"Generated {len(drill_holes)} drill holes with {total_samples} samples")
            
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Simulation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


# RBF Interpolation operator (uses cached assay data from API)
class GEODB_OT_RBFInterpolation(Operator):
    """Create RBF interpolation from imported assay data"""
    bl_idname = "geodb.rbf_interpolation"
    bl_label = "RBF Interpolation"
    bl_description = "Create a 3D interpolation from imported drill hole assay data using Radial Basis Functions"
    bl_options = {'REGISTER', 'UNDO'}

    def get_elements(self, context):
        """Get available elements from cached assay data."""
        elements = get_available_elements()

        if elements:
            return [(e, e, f"Interpolate {e} values") for e in sorted(elements)]
        else:
            return [("", "No elements available", "")]

    element: EnumProperty(
        name="Element",
        description="Element to interpolate",
        items=get_elements,
    )

    kernel: EnumProperty(
        name="Kernel",
        description="RBF kernel function",
        items=[
            ('linear', "Linear", "Linear kernel"),
            ('thin_plate_spline', "Thin Plate Spline", "Thin plate spline kernel (recommended)"),
            ('cubic', "Cubic", "Cubic kernel"),
            ('quintic', "Quintic", "Quintic kernel"),
            ('multiquadric', "Multiquadric", "Multiquadric kernel"),
            ('inverse_multiquadric', "Inverse Multiquadric", "Inverse multiquadric kernel"),
            ('inverse_quadratic', "Inverse Quadratic", "Inverse quadratic kernel"),
            ('gaussian', "Gaussian", "Gaussian kernel"),
        ],
        default='thin_plate_spline',
    )

    epsilon: FloatProperty(
        name="Epsilon",
        description="Shape parameter for RBF (ignored for some kernels)",
        default=1.0,
        min=0.001,
        max=100.0,
    )

    smoothing: FloatProperty(
        name="Smoothing",
        description="Smoothing parameter (0 = exact interpolation)",
        default=0.0,
        min=0.0,
        max=10.0,
    )

    grid_resolution: IntProperty(
        name="Grid Resolution",
        description="Resolution of interpolation grid per axis",
        default=50,
        min=10,
        max=200,
    )

    output_type: EnumProperty(
        name="Output Type",
        description="Type of output geometry",
        items=[
            ('POINTS', "Point Cloud", "Generate point cloud"),
            ('MESH', "Volume Mesh", "Generate volume mesh"),
        ],
        default='POINTS',
    )

    use_threshold: BoolProperty(
        name="Use Thresholds",
        description="Filter interpolated values by threshold",
        default=False,
    )

    threshold_min: FloatProperty(
        name="Min Threshold",
        description="Minimum value to display",
        default=0.0,
    )

    threshold_max: FloatProperty(
        name="Max Threshold",
        description="Maximum value to display",
        default=1.0,
    )

    use_distance_limit: BoolProperty(
        name="Limit Extrapolation",
        description="Constrain interpolation to stay near sample locations (recommended for watertight meshes)",
        default=True,
    )

    extrapolation_distance: FloatProperty(
        name="Max Distance",
        description="Maximum distance from samples to extrapolate (0 = auto-calculate from sample spacing)",
        default=0.0,
        min=0.0,
        soft_max=500.0,
    )

    # Anisotropic search ellipsoid parameters
    use_anisotropic: BoolProperty(
        name="Anisotropic Search",
        description="Use an ellipsoidal search to respect geological continuity directions",
        default=False,
    )

    ellipsoid_major: FloatProperty(
        name="Major Axis (Strike)",
        description="Search distance along strike direction (longest axis)",
        default=50.0,
        min=1.0,
        soft_max=500.0,
    )

    ellipsoid_semi: FloatProperty(
        name="Semi Axis (Dip)",
        description="Search distance along dip direction",
        default=30.0,
        min=1.0,
        soft_max=500.0,
    )

    ellipsoid_minor: FloatProperty(
        name="Minor Axis (Width)",
        description="Search distance across strike (narrowest axis)",
        default=10.0,
        min=1.0,
        soft_max=500.0,
    )

    ellipsoid_azimuth: FloatProperty(
        name="Azimuth",
        description="Rotation around vertical axis (0=North, clockwise)",
        default=0.0,
        min=0.0,
        max=360.0,
        subtype='ANGLE',
    )

    ellipsoid_dip: FloatProperty(
        name="Dip",
        description="Rotation around horizontal axis (0=horizontal)",
        default=0.0,
        min=-90.0,
        max=90.0,
        subtype='ANGLE',
    )

    ellipsoid_plunge: FloatProperty(
        name="Plunge",
        description="Rotation around strike axis",
        default=0.0,
        min=-90.0,
        max=90.0,
        subtype='ANGLE',
    )

    show_ellipsoid: BoolProperty(
        name="Show Ellipsoid",
        description="Create a visualization of the search ellipsoid in the viewport",
        default=True,
    )

    # Performance options
    use_local_rbf: BoolProperty(
        name="Use Local RBF",
        description="Use local RBF with nearest neighbors (faster for large datasets, approximate)",
        default=False,
    )

    neighbors: IntProperty(
        name="Neighbors",
        description="Number of nearest neighbors for local RBF (50-100 recommended)",
        default=50,
        min=10,
        max=500,
    )

    # Distance decay options - smooth grade diminishment away from samples
    use_distance_decay: BoolProperty(
        name="Distance Decay",
        description="Smoothly decay interpolated values toward background as distance from samples increases. "
                    "This is more geologically realistic - grades should diminish gradually into unmineralized rock, "
                    "rather than extrapolating high values into empty space",
        default=True,
    )

    decay_distance: FloatProperty(
        name="Decay Distance",
        description="Distance at which values fully decay to background (0 = auto-calculate from sample spacing)",
        default=0.0,
        min=0.0,
        soft_max=500.0,
    )

    background_value: FloatProperty(
        name="Background Value",
        description="Value to decay toward (typically 0 or detection limit). "
                    "Grades will smoothly transition to this value away from samples",
        default=0.0,
        min=0.0,
        soft_max=1.0,
    )

    decay_function: EnumProperty(
        name="Decay Type",
        description="Shape of the decay curve",
        items=[
            ('linear', "Linear", "Simple linear decay - value decreases proportionally with distance"),
            ('smooth', "Smooth", "S-curve decay with no sharp transitions (recommended)"),
            ('gaussian', "Gaussian", "Exponential decay - common geostatistical assumption"),
        ],
        default='smooth',
    )

    def invoke(self, context, event):
        # Check if scipy is available
        if not SCIPY_AVAILABLE:
            self.report({'ERROR'}, "scipy is required for RBF interpolation. Please install it.")
            return {'CANCELLED'}

        # Check if we have cached data
        cache = DrillDataCache.get_cache()
        if cache is None:
            self.report({'ERROR'}, "No drill data imported. Please import data first.")
            return {'CANCELLED'}

        samples = cache.get('samples', {})
        if not samples:
            self.report({'ERROR'}, "No sample data in cache. Please import drill data first.")
            return {'CANCELLED'}

        elements = get_available_elements()
        if not elements:
            self.report({'ERROR'}, "No assay elements found in imported data.")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "element")
        layout.separator()

        box = layout.box()
        box.label(text="RBF Parameters", icon='PREFERENCES')
        box.prop(self, "kernel")
        box.prop(self, "epsilon")
        box.prop(self, "smoothing")
        box.prop(self, "grid_resolution")

        # Performance options
        box = layout.box()
        box.label(text="Performance", icon='TIME')
        box.prop(self, "use_local_rbf")
        if self.use_local_rbf:
            box.prop(self, "neighbors")

        box = layout.box()
        box.label(text="Output", icon='MESH_ICOSPHERE')
        box.prop(self, "output_type")

        # Threshold controls
        box.prop(self, "use_threshold")
        if self.use_threshold:
            box.prop(self, "threshold_min", text="Cutoff Grade (Min)")
            box.prop(self, "threshold_max", text="Max Threshold")

        # Distance limiting controls (only for MESH output)
        if self.output_type == 'MESH':
            box.separator()
            box.prop(self, "use_distance_limit")

            if self.use_distance_limit:
                # Anisotropic vs isotropic toggle
                box.prop(self, "use_anisotropic")

                if self.use_anisotropic:
                    # Ellipsoid parameters
                    ellipse_box = box.box()
                    ellipse_box.label(text="Search Ellipsoid", icon='MESH_UVSPHERE')

                    # Radii
                    col = ellipse_box.column(align=True)
                    col.prop(self, "ellipsoid_major")
                    col.prop(self, "ellipsoid_semi")
                    col.prop(self, "ellipsoid_minor")

                    ellipse_box.separator()

                    # Orientation
                    col = ellipse_box.column(align=True)
                    col.prop(self, "ellipsoid_azimuth")
                    col.prop(self, "ellipsoid_dip")
                    col.prop(self, "ellipsoid_plunge")

                    ellipse_box.separator()
                    ellipse_box.prop(self, "show_ellipsoid")
                else:
                    # Isotropic distance
                    row = box.row()
                    row.prop(self, "extrapolation_distance")
                    if self.extrapolation_distance == 0.0:
                        row.label(text="(auto)")
            else:
                box.label(text="Warning: May create large mesh!", icon='ERROR')

        # Distance decay controls - smooth grade diminishment
        # This is separate from distance limiting (hard cutoff)
        box = layout.box()
        box.label(text="Grade Decay", icon='FORCE_HARMONIC')
        box.prop(self, "use_distance_decay")

        if self.use_distance_decay:
            # Info text
            info_col = box.column()
            info_col.scale_y = 0.7
            info_col.label(text="Grades diminish toward background")
            info_col.label(text="away from samples (geologically realistic)")

            box.separator()

            # Decay parameters
            row = box.row()
            row.prop(self, "decay_distance")
            if self.decay_distance == 0.0:
                row.label(text="(auto)")

            box.prop(self, "background_value")
            box.prop(self, "decay_function")

    def execute(self, context):
        import math as exec_math

        if not self.element:
            self.report({'ERROR'}, "No element selected")
            return {'CANCELLED'}

        try:
            self.report({'INFO'}, f"Creating RBF interpolation for {self.element}...")

            # Determine extrapolation distance or ellipsoid
            # None = auto-calculate, inf = no limit, SearchEllipsoid = anisotropic
            search_ellipsoid = None

            if self.output_type == 'MESH':
                if self.use_distance_limit:
                    if self.use_anisotropic:
                        # Create search ellipsoid (convert angles from radians to degrees for display)
                        # Blender stores ANGLE subtype in radians internally
                        search_ellipsoid = SearchEllipsoid(
                            radius_major=self.ellipsoid_major,
                            radius_semi=self.ellipsoid_semi,
                            radius_minor=self.ellipsoid_minor,
                            azimuth=exec_math.degrees(self.ellipsoid_azimuth),
                            dip=exec_math.degrees(self.ellipsoid_dip),
                            plunge=exec_math.degrees(self.ellipsoid_plunge)
                        )
                        max_extrap = search_ellipsoid
                    else:
                        # Isotropic: 0 means auto-calculate, otherwise use specified value
                        max_extrap = None if self.extrapolation_distance == 0.0 else self.extrapolation_distance
                else:
                    # Disable distance limiting by setting to a very large value
                    max_extrap = float('inf')
            else:
                max_extrap = None

            # Determine neighbors parameter
            neighbors_param = self.neighbors if self.use_local_rbf else None

            # Determine decay parameters
            decay_dist = None if self.decay_distance == 0.0 else self.decay_distance

            obj = interpolate_from_cache(
                element=self.element,
                kernel=self.kernel,
                epsilon=self.epsilon,
                smoothing=self.smoothing,
                resolution=self.grid_resolution,
                output_type=self.output_type,
                threshold_min=self.threshold_min if self.use_threshold else None,
                threshold_max=self.threshold_max if self.use_threshold else None,
                use_threshold=self.use_threshold,
                max_extrapolation_distance=max_extrap,
                neighbors=neighbors_param,
                use_distance_decay=self.use_distance_decay,
                decay_distance=decay_dist,
                background_value=self.background_value,
                decay_function=self.decay_function
            )

            # Create ellipsoid visualization if requested
            if self.output_type == 'MESH' and self.use_distance_limit and self.use_anisotropic and self.show_ellipsoid:
                # Get sample centroid for ellipsoid placement
                from ..core.interpolation import extract_assay_data_from_cache
                positions, _ = extract_assay_data_from_cache(self.element)
                centroid = positions.mean(axis=0)

                ellipsoid_obj = create_ellipsoid_visualization(
                    search_ellipsoid,
                    location=tuple(centroid),
                    name=f"SearchEllipsoid_{self.element}"
                )
                self.report({'INFO'}, f"Created search ellipsoid visualization at sample centroid")

            self.report({'INFO'}, f"Created RBF interpolation: {obj.name}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Interpolation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


# Simulation panel
class GEODB_PT_SimulationPanel(Panel):
    """Panel for drill data simulation"""
    bl_label = "Simulation"
    bl_idname = "GEODB_PT_simulation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_order = 3
    
    def draw(self, context):
        layout = self.layout
        
        box = layout.box()
        box.label(text="Generate Test Data", icon='EXPERIMENTAL')
        box.label(text="Simulate realistic drill hole data")
        box.label(text="for testing and demonstration.")
        
        layout.operator("geodb.simulate_drill_data", icon='PLUS')
        
        # Show info about available deposit types
        box = layout.box()
        box.label(text="Deposit Types:", icon='INFO')
        box.label(text="• Porphyry Copper-Gold")
        box.label(text="• Gold-Silver Vein")


# Fetch drill data for RBF operator
class GEODB_OT_FetchDrillDataForRBF(Operator):
    """Fetch drill data from API for RBF interpolation"""
    bl_idname = "geodb.fetch_drill_data_for_rbf"
    bl_label = "Fetch Drill Data"
    bl_description = "Fetch drill hole sample data from the API for RBF interpolation"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        props = scene.geodb

        # Check if project is selected
        if not hasattr(props, 'selected_project_id') or not props.selected_project_id:
            self.report({'ERROR'}, "No project selected. Please select a project first.")
            return {'CANCELLED'}

        try:
            project_id = int(props.selected_project_id)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}

        project_name = props.selected_project_name or f"Project_{project_id}"

        self.report({'INFO'}, f"Fetching drill data for {project_name}...")

        # Fetch samples from API (without assay_config_id to get all data)
        success, samples_by_hole = GeoDBData.get_all_samples_for_project(project_id)
        if not success or not samples_by_hole:
            self.report({'ERROR'}, "No drill samples found for this project")
            return {'CANCELLED'}

        total_samples = sum(len(v) for v in samples_by_hole.values())
        print(f"Fetched {total_samples} samples across {len(samples_by_hole)} holes")

        # Extract available elements from the fetched samples
        available_elements = set()
        for hole_samples in samples_by_hole.values():
            for sample in hole_samples:
                assay = sample.get('assay')
                if assay and isinstance(assay, dict):
                    elements_list = assay.get('elements', [])
                    for elem in elements_list:
                        if isinstance(elem, dict):
                            elem_name = elem.get('element')
                            if elem_name:
                                available_elements.add(elem_name)

        # Fetch assay range configurations
        success_configs, configs = GeoDBData.get_assay_range_configurations(project_id)
        if not success_configs:
            configs = []

        # Save to cache
        cache_data = {
            'project_id': project_id,
            'company_id': int(props.selected_company_id) if hasattr(props, 'selected_company_id') and props.selected_company_id else 0,
            'project_name': project_name,
            'company_name': props.selected_company_name if hasattr(props, 'selected_company_name') else '',
            'samples': samples_by_hole,
            'available_elements': sorted(list(available_elements)),
            'assay_range_configs': configs,
        }
        DrillDataCache.set_cache(cache_data)

        self.report({'INFO'}, f"Fetched {total_samples} samples with {len(available_elements)} elements")

        # Force UI redraw
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'FINISHED'}


# Registration
classes = (
    GEODB_OT_SimulateDrillData,
    GEODB_OT_RBFInterpolation,
    GEODB_OT_FetchDrillDataForRBF,
    GEODB_PT_SimulationPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)