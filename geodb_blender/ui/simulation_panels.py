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
from ..core.interpolation import interpolate_from_samples, SCIPY_AVAILABLE


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
    
    def execute(self, context):
        try:
            # Create simulator based on deposit type
            if self.deposit_type == 'PORPHYRY_CU':
                simulator = PorphyryCopperSimulator(
                    seed=42,
                    orebody_center=(self.area_size / 2, self.area_size / 2, -self.max_depth / 2),
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
                    vein_center=(self.area_size / 2, self.area_size / 2, -self.max_depth / 3),
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
            
            # Visualize
            visualize_simulated_drill_holes(
                drill_holes,
                show_traces=self.show_traces,
                show_samples=self.show_samples,
                color_element=color_element
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


# RBF Interpolation operator
class GEODB_OT_RBFInterpolation(Operator):
    """Create RBF interpolation from sample data"""
    bl_idname = "geodb.rbf_interpolation"
    bl_label = "RBF Interpolation"
    bl_description = "Create a 3D interpolation from drill hole samples using Radial Basis Functions"
    bl_options = {'REGISTER', 'UNDO'}
    
    def get_elements(self, context):
        """Get available elements from sample objects."""
        elements = set()
        for obj in bpy.data.objects:
            if 'geodb_type' in obj and obj['geodb_type'] == 'sample':
                for key in obj.keys():
                    if key.startswith('value_'):
                        elements.add(key[6:])
        
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
    
    def invoke(self, context, event):
        # Check if scipy is available
        if not SCIPY_AVAILABLE:
            self.report({'ERROR'}, "scipy is required for RBF interpolation. Please install it.")
            return {'CANCELLED'}
        
        # Check if there are sample objects
        sample_objs = [obj for obj in bpy.data.objects 
                      if 'geodb_type' in obj and obj['geodb_type'] == 'sample']
        
        if not sample_objs:
            self.report({'ERROR'}, "No sample objects found in scene")
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
        
        box = layout.box()
        box.label(text="Output", icon='MESH_ICOSPHERE')
        box.prop(self, "output_type")
        box.prop(self, "use_threshold")
        
        if self.use_threshold:
            box.prop(self, "threshold_min")
            box.prop(self, "threshold_max")
    
    def execute(self, context):
        if not self.element:
            self.report({'ERROR'}, "No element selected")
            return {'CANCELLED'}
        
        try:
            self.report({'INFO'}, "Creating RBF interpolation...")
            
            obj = interpolate_from_samples(
                element=self.element,
                kernel=self.kernel,
                epsilon=self.epsilon,
                smoothing=self.smoothing,
                resolution=self.grid_resolution,
                output_type=self.output_type,
                threshold_min=self.threshold_min if self.use_threshold else None,
                threshold_max=self.threshold_max if self.use_threshold else None,
                use_threshold=self.use_threshold
            )
            
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


# RBF Interpolation panel
class GEODB_PT_InterpolationPanel(Panel):
    """Panel for RBF interpolation"""
    bl_label = "RBF Interpolation"
    bl_idname = "GEODB_PT_interpolation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_order = 4
    
    def draw(self, context):
        layout = self.layout
        
        if not SCIPY_AVAILABLE:
            box = layout.box()
            box.label(text="scipy not available", icon='ERROR')
            box.label(text="Install scipy to use RBF")
            box.label(text="interpolation features.")
            return
        
        # Check if there are sample objects
        sample_objs = [obj for obj in bpy.data.objects 
                      if 'geodb_type' in obj and obj['geodb_type'] == 'sample']
        
        if not sample_objs:
            box = layout.box()
            box.label(text="No sample data found", icon='INFO')
            box.label(text="Simulate or load drill data")
            box.label(text="before interpolating.")
            return
        
        box = layout.box()
        box.label(text="3D Interpolation", icon='MESH_ICOSPHERE')
        box.label(text="Create a 3D model from")
        box.label(text="drill hole sample data.")
        
        layout.operator("geodb.rbf_interpolation", icon='FORCE_MAGNETIC')
        
        # Show available elements
        elements = set()
        for obj in sample_objs:
            for key in obj.keys():
                if key.startswith('value_'):
                    elements.add(key[6:])
        
        if elements:
            box = layout.box()
            box.label(text="Available Elements:", icon='MATERIAL')
            for element in sorted(elements):
                box.label(text=f"• {element}")


# Registration
classes = (
    GEODB_OT_SimulateDrillData,
    GEODB_OT_RBFInterpolation,
    GEODB_PT_SimulationPanel,
    GEODB_PT_InterpolationPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)