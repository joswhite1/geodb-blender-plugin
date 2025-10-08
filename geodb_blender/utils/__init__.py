"""
Utilities module for the geoDB Blender add-on.

This module provides utility functions and classes for the add-on,
including data conversion, file handling, and other helper functions.
"""

import bpy
from . import desurvey

# Export utility functions and classes
from .desurvey import (
    desurvey_minimum_curvature,
    DrillholeDesurvey,
    create_drill_trace_mesh,
    create_drill_sample_meshes,
)

from .object_properties import (
    GeoDBObjectProperties,
    clear_geodb_objects,
)

__all__ = [
    'desurvey_minimum_curvature',
    'DrillholeDesurvey',
    'create_drill_trace_mesh',
    'create_drill_sample_meshes',
    'GeoDBObjectProperties',
    'clear_geodb_objects',
]

# Registration
def register():
    pass

def unregister():
    pass