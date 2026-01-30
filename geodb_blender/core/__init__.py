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
from . import config_cache
from .config_cache import ConfigCache
from .data_cache import (
    TraceCache,
    DrillDataCache,
    process_deleted_collar_ids,
    sync_deletions_from_fetch_result,
)

__all__ = [
    'DrillHoleVisualizer',
    'PorphyryCopperSimulator',
    'GoldVeinSimulator',
    'visualize_simulated_drill_holes',
    'RBFInterpolator3D',
    'interpolate_from_samples',
    'SCIPY_AVAILABLE',
    'ConfigCache',
    'TraceCache',
    'DrillDataCache',
    'process_deleted_collar_ids',
    'sync_deletions_from_fetch_result',
]

# Registration
def register():
    """Register core module components."""
    data_cache.register()
    config_cache.register()

def unregister():
    """Unregister core module components."""
    config_cache.unregister()
    data_cache.unregister()