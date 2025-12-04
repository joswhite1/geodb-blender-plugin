"""
Core module for the geoDB Blender add-on.

This module provides the core functionality for the add-on, including
data processing, visualization, and analysis.
"""

import bpy
from .visualization import DrillHoleVisualizer
from .simulation import (PorphyryCopperSimulator, GoldVeinSimulator,
                        visualize_simulated_drill_holes)
from .interpolation import (RBFInterpolator3D, interpolate_from_samples,
                            SCIPY_AVAILABLE)
from . import data_cache

__all__ = [
    'DrillHoleVisualizer',
    'PorphyryCopperSimulator',
    'GoldVeinSimulator',
    'visualize_simulated_drill_holes',
    'RBFInterpolator3D',
    'interpolate_from_samples',
    'SCIPY_AVAILABLE',
]

# Registration
def register():
    """Register core module components."""
    data_cache.register()

def unregister():
    """Unregister core module components."""
    data_cache.unregister()