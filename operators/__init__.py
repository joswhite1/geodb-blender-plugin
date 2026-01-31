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
    GEODB_OT_SyncPlannedHoles,
    GEODB_OT_UpdateHoleFromMesh,
    GEODB_OT_RefreshHoleStatistics,
    register_handlers as register_drillhole_handlers,
    unregister_handlers as unregister_drillhole_handlers,
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
    'GEODB_OT_SyncPlannedHoles',
    'GEODB_OT_UpdateHoleFromMesh',
    'GEODB_OT_RefreshHoleStatistics',
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
    GEODB_OT_SyncPlannedHoles,
    GEODB_OT_UpdateHoleFromMesh,
    GEODB_OT_RefreshHoleStatistics,
)


def register():
    """Register all operator classes and handlers"""
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register app handlers for drillhole planning
    register_drillhole_handlers()


def unregister():
    """Unregister all operator classes and handlers"""
    # Unregister app handlers for drillhole planning
    unregister_drillhole_handlers()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
