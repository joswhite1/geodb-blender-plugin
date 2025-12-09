"""
Operators module for geoDB Blender add-on.

This module contains operator classes for various geoDB operations.
"""

import bpy
from .async_base import GeoDBAsyncOperator
from .terrain_import import GEODB_OT_ImportTerrain, GEODB_OT_SwitchTerrainTexture
from .drillhole_planning import (
    GEODB_OT_ImportDrillPads,
    GEODB_OT_SelectDrillPad,
    GEODB_OT_CalculateFromCursor,
    GEODB_OT_PreviewPlannedHole,
    GEODB_OT_ClearPreviews,
    GEODB_OT_CreatePlannedHole,
)

__all__ = [
    'GeoDBAsyncOperator',
    'GEODB_OT_ImportTerrain',
    'GEODB_OT_SwitchTerrainTexture',
    'GEODB_OT_ImportDrillPads',
    'GEODB_OT_SelectDrillPad',
    'GEODB_OT_CalculateFromCursor',
    'GEODB_OT_PreviewPlannedHole',
    'GEODB_OT_ClearPreviews',
    'GEODB_OT_CreatePlannedHole',
]

# Operator classes to register
classes = (
    GEODB_OT_ImportTerrain,
    GEODB_OT_SwitchTerrainTexture,
    GEODB_OT_ImportDrillPads,
    GEODB_OT_SelectDrillPad,
    GEODB_OT_CalculateFromCursor,
    GEODB_OT_PreviewPlannedHole,
    GEODB_OT_ClearPreviews,
    GEODB_OT_CreatePlannedHole,
)


def register():
    """Register all operator classes"""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister all operator classes"""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
