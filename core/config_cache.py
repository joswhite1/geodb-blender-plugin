"""
In-memory configuration cache for geoDB Blender add-on.

This module provides a lightweight cache for dropdown data (configs, sets)
to prevent API calls during UI draw cycles. The cache is separate from
DrillDataCache which stores heavy data like samples and traces.

Key Features:
- Thread-safe access with Lock
- 5-minute TTL with auto-refresh
- Project-aware caching (invalidates on project change)
- No API calls during UI draw - enum callbacks use cached data only
"""

import threading
import time
from typing import List, Dict, Any, Optional


class ConfigCache:
    """
    In-memory cache for lightweight configuration data.

    This cache stores:
    - Assay range configurations (for dropdown selection)
    - Lithology sets
    - Alteration sets
    - Mineralization sets

    Used by enum callbacks to populate dropdowns without making API calls.
    Cache is populated when user clicks "Load Configuration" buttons.
    """

    # Class-level cache storage
    _cache = {
        'project_id': None,
        'assay_configs': [],
        'lithology_sets': [],
        'alteration_sets': [],
        'mineralization_sets': [],
        'timestamp': None,
    }

    # Thread lock for safe concurrent access
    _lock = threading.Lock()

    # Cache time-to-live in seconds (5 minutes)
    CACHE_TTL = 300

    @classmethod
    def is_valid(cls, project_id: int) -> bool:
        """
        Check if cache is valid for the given project.

        Cache is invalid if:
        - Project ID doesn't match
        - Cache is empty (no timestamp)
        - Cache has expired (older than TTL)

        Args:
            project_id: Current project ID to validate against

        Returns:
            True if cache is valid and can be used
        """
        with cls._lock:
            if cls._cache['project_id'] != project_id:
                return False

            if cls._cache['timestamp'] is None:
                return False

            age = time.time() - cls._cache['timestamp']
            if age > cls.CACHE_TTL:
                return False

            return True

    @classmethod
    def get_assay_configs(cls) -> List[Dict[str, Any]]:
        """
        Get cached assay range configurations.

        Returns:
            List of assay config dictionaries, or empty list if not cached
        """
        with cls._lock:
            return cls._cache.get('assay_configs', []).copy()

    @classmethod
    def get_lithology_sets(cls) -> List[Dict[str, Any]]:
        """
        Get cached lithology sets.

        Returns:
            List of lithology set dictionaries, or empty list if not cached
        """
        with cls._lock:
            return cls._cache.get('lithology_sets', []).copy()

    @classmethod
    def get_alteration_sets(cls) -> List[Dict[str, Any]]:
        """
        Get cached alteration sets.

        Returns:
            List of alteration set dictionaries, or empty list if not cached
        """
        with cls._lock:
            return cls._cache.get('alteration_sets', []).copy()

    @classmethod
    def get_mineralization_sets(cls) -> List[Dict[str, Any]]:
        """
        Get cached mineralization sets.

        Returns:
            List of mineralization set dictionaries, or empty list if not cached
        """
        with cls._lock:
            return cls._cache.get('mineralization_sets', []).copy()

    @classmethod
    def get_project_id(cls) -> Optional[int]:
        """
        Get the project ID for which cache is valid.

        Returns:
            Project ID or None if cache is empty
        """
        with cls._lock:
            return cls._cache.get('project_id')

    @classmethod
    def set_assay_configs(cls, project_id: int, configs: List[Dict[str, Any]]):
        """
        Cache assay range configurations for a project.

        Args:
            project_id: Project ID these configs belong to
            configs: List of assay config dictionaries from API
        """
        with cls._lock:
            # If project changed, clear all cache
            if cls._cache['project_id'] != project_id:
                cls._clear_internal()
                cls._cache['project_id'] = project_id

            cls._cache['assay_configs'] = configs.copy() if configs else []
            cls._cache['timestamp'] = time.time()

    @classmethod
    def set_lithology_sets(cls, project_id: int, sets: List[Dict[str, Any]]):
        """
        Cache lithology sets for a project.

        Args:
            project_id: Project ID these sets belong to
            sets: List of lithology set dictionaries from API
        """
        with cls._lock:
            # If project changed, clear all cache
            if cls._cache['project_id'] != project_id:
                cls._clear_internal()
                cls._cache['project_id'] = project_id

            cls._cache['lithology_sets'] = sets.copy() if sets else []
            cls._cache['timestamp'] = time.time()

    @classmethod
    def set_alteration_sets(cls, project_id: int, sets: List[Dict[str, Any]]):
        """
        Cache alteration sets for a project.

        Args:
            project_id: Project ID these sets belong to
            sets: List of alteration set dictionaries from API
        """
        with cls._lock:
            # If project changed, clear all cache
            if cls._cache['project_id'] != project_id:
                cls._clear_internal()
                cls._cache['project_id'] = project_id

            cls._cache['alteration_sets'] = sets.copy() if sets else []
            cls._cache['timestamp'] = time.time()

    @classmethod
    def set_mineralization_sets(cls, project_id: int, sets: List[Dict[str, Any]]):
        """
        Cache mineralization sets for a project.

        Args:
            project_id: Project ID these sets belong to
            sets: List of mineralization set dictionaries from API
        """
        with cls._lock:
            # If project changed, clear all cache
            if cls._cache['project_id'] != project_id:
                cls._clear_internal()
                cls._cache['project_id'] = project_id

            cls._cache['mineralization_sets'] = sets.copy() if sets else []
            cls._cache['timestamp'] = time.time()

    @classmethod
    def set_all(cls, project_id: int,
                assay_configs: Optional[List[Dict]] = None,
                lithology_sets: Optional[List[Dict]] = None,
                alteration_sets: Optional[List[Dict]] = None,
                mineralization_sets: Optional[List[Dict]] = None):
        """
        Set all cache data at once for a project.

        This is more efficient than setting each type individually
        when populating the cache from API responses.

        Args:
            project_id: Project ID for all this data
            assay_configs: Optional list of assay configs
            lithology_sets: Optional list of lithology sets
            alteration_sets: Optional list of alteration sets
            mineralization_sets: Optional list of mineralization sets
        """
        with cls._lock:
            cls._cache = {
                'project_id': project_id,
                'assay_configs': assay_configs.copy() if assay_configs else [],
                'lithology_sets': lithology_sets.copy() if lithology_sets else [],
                'alteration_sets': alteration_sets.copy() if alteration_sets else [],
                'mineralization_sets': mineralization_sets.copy() if mineralization_sets else [],
                'timestamp': time.time(),
            }

    @classmethod
    def invalidate(cls):
        """
        Invalidate and clear all cached data.

        Call this when:
        - User logs out
        - User switches projects
        - Cache needs to be refreshed
        """
        with cls._lock:
            cls._clear_internal()

    @classmethod
    def _clear_internal(cls):
        """Internal method to clear cache (no lock - caller must hold lock)."""
        cls._cache = {
            'project_id': None,
            'assay_configs': [],
            'lithology_sets': [],
            'alteration_sets': [],
            'mineralization_sets': [],
            'timestamp': None,
        }

    @classmethod
    def get_cache_summary(cls) -> Dict[str, Any]:
        """
        Get a summary of current cache state for debugging.

        Returns:
            Dictionary with cache statistics
        """
        with cls._lock:
            age = None
            if cls._cache['timestamp']:
                age = time.time() - cls._cache['timestamp']

            return {
                'project_id': cls._cache['project_id'],
                'assay_configs_count': len(cls._cache.get('assay_configs', [])),
                'lithology_sets_count': len(cls._cache.get('lithology_sets', [])),
                'alteration_sets_count': len(cls._cache.get('alteration_sets', [])),
                'mineralization_sets_count': len(cls._cache.get('mineralization_sets', [])),
                'age_seconds': age,
                'is_expired': age > cls.CACHE_TTL if age else True,
            }


def register():
    """Register config cache module (no-op, class is static)."""
    pass


def unregister():
    """Unregister config cache module - clear cache on unload."""
    ConfigCache.invalidate()
