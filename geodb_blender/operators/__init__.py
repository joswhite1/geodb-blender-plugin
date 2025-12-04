"""
Operators module for geoDB Blender add-on.

This module contains operator classes for various geoDB operations.
"""

import bpy
from .async_base import GeoDBAsyncOperator
from .terrain_import import GEODB_OT_ImportTerrain

__all__ = [
    'GeoDBAsyncOperator',
    'GEODB_OT_ImportTerrain',
]

# Operator classes to register
classes = (
    GEODB_OT_ImportTerrain,
)


def register():
    """Register all operator classes"""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister all operator classes"""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
