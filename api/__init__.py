"""
geoDB API module for the Blender add-on.

This module provides functionality for interacting with the geoDB API,
including authentication, data retrieval, and data submission.
"""

from .auth import (
    get_api_client,
    reset_api_client,
    GEODB_OT_Login,
    GEODB_OT_Logout,
    GEODB_OT_UnlockToken,
    GEODB_PT_Authentication,
)

from .client import GeoDBAPIClient
from .data import GeoDBData

__all__ = [
    'get_api_client',
    'reset_api_client',
    'GeoDBAPIClient',
    'GeoDBData',
    'GEODB_OT_Login',
    'GEODB_OT_Logout',
    'GEODB_OT_UnlockToken',
    'GEODB_PT_Authentication',
]

# Registration function for Blender add-on
def register():
    from .auth import register as register_auth
    register_auth()

# Unregistration function for Blender add-on
def unregister():
    from .auth import unregister as unregister_auth
    unregister_auth()