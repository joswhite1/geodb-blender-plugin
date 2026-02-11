"""
Data caching system for geoDB drill hole data.

This module provides centralized caching for all project drill data,
reducing API calls and improving performance.

Includes:
- DrillDataCache: Heavy data like samples for RBF interpolation
- TraceCache: Trace details for interval visualization (separate cache)
"""

import bpy
import json
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
import os


class TraceCache:
    """
    Cache for drill hole trace details to avoid repeated API calls.

    Trace fetching is expensive (one API call per hole) and traces don't
    change during a visualization session. This cache stores trace details
    so they can be reused across lithology/alteration/mineralization
    visualizations within the same project.

    Cache is project-scoped and invalidated when project changes.
    """

    _cache = {
        'project_id': None,
        'traces': {},  # hole_id -> trace_detail dict
        'timestamp': None,
    }

    _lock = threading.Lock()

    # Cache TTL in seconds (30 minutes - traces rarely change)
    CACHE_TTL = 1800

    @classmethod
    def is_valid(cls, project_id: int) -> bool:
        """Check if cache is valid for the given project."""
        with cls._lock:
            if cls._cache['project_id'] != project_id:
                return False
            if cls._cache['timestamp'] is None:
                return False
            age = time.time() - cls._cache['timestamp']
            return age <= cls.CACHE_TTL

    @classmethod
    def get_trace(cls, hole_id: int) -> Optional[Dict]:
        """
        Get cached trace detail for a hole.

        Args:
            hole_id: The hole ID to get trace for

        Returns:
            Trace detail dict or None if not cached
        """
        with cls._lock:
            return cls._cache['traces'].get(hole_id)

    @classmethod
    def set_trace(cls, project_id: int, hole_id: int, trace_detail: Dict):
        """
        Cache a trace detail for a hole.

        Args:
            project_id: Project ID (used for validation)
            hole_id: Hole ID this trace belongs to
            trace_detail: The trace detail dict from API
        """
        with cls._lock:
            # Clear cache if project changed
            if cls._cache['project_id'] != project_id:
                cls._cache = {
                    'project_id': project_id,
                    'traces': {},
                    'timestamp': time.time(),
                }

            cls._cache['traces'][hole_id] = trace_detail
            cls._cache['timestamp'] = time.time()

    @classmethod
    def set_traces_bulk(cls, project_id: int, traces: Dict):
        """
        Set multiple traces at once.

        Args:
            project_id: Project ID
            traces: Dict mapping hole_id -> trace_detail
        """
        with cls._lock:
            cls._cache = {
                'project_id': project_id,
                'traces': traces.copy(),
                'timestamp': time.time(),
            }

    @classmethod
    def get_all_traces(cls) -> Dict:
        """Get all cached traces."""
        with cls._lock:
            return cls._cache['traces'].copy()

    @classmethod
    def invalidate(cls):
        """Clear all cached trace data."""
        with cls._lock:
            cls._cache = {
                'project_id': None,
                'traces': {},
                'timestamp': None,
            }

    @classmethod
    def get_cache_summary(cls) -> Dict[str, Any]:
        """Get summary for debugging."""
        with cls._lock:
            age = None
            if cls._cache['timestamp']:
                age = time.time() - cls._cache['timestamp']
            return {
                'project_id': cls._cache['project_id'],
                'traces_count': len(cls._cache['traces']),
                'age_seconds': age,
                'is_expired': age > cls.CACHE_TTL if age else True,
            }


class DrillDataCache:
    """Manager for drill hole data caching."""

    CACHE_VERSION = "1.2.0"  # Updated for deletion sync support (sync_timestamps)
    
    @staticmethod
    def get_cache_property():
        """Get the scene property used for cache storage."""
        # Property should already be registered during addon registration
        # Don't try to create it dynamically - that causes readonly errors
        return bpy.context.scene.geodb_data_cache
    
    @staticmethod
    def set_cache_property(value: str):
        """Set the scene property used for cache storage."""
        bpy.context.scene.geodb_data_cache = value
    
    @staticmethod
    def get_cache() -> Optional[Dict[str, Any]]:
        """
        Retrieve cached data for the current project.
        
        Returns:
            Dictionary containing cached data, or None if cache is invalid/empty
        """
        try:
            cache_json = DrillDataCache.get_cache_property()
            if not cache_json:
                return None
            
            cache_data = json.loads(cache_json)
            
            # Validate cache version
            if cache_data.get('version') != DrillDataCache.CACHE_VERSION:
                print(f"Cache version mismatch. Expected {DrillDataCache.CACHE_VERSION}, "
                      f"got {cache_data.get('version')}")
                return None
            
            return cache_data
        
        except json.JSONDecodeError as e:
            print(f"Error decoding cache JSON: {e}")
            return None
        except Exception as e:
            print(f"Error retrieving cache: {e}")
            return None
    
    @staticmethod
    def set_cache(data: Dict[str, Any]):
        """
        Store cached data.
        
        Args:
            data: Dictionary containing all project data
        """
        try:
            # Add metadata
            cache_data = {
                'version': DrillDataCache.CACHE_VERSION,
                'timestamp': datetime.now().isoformat(),
                **data
            }
            
            # Serialize to JSON
            cache_json = json.dumps(cache_data, default=str)
            
            # Store in scene property
            DrillDataCache.set_cache_property(cache_json)
            
            print(f"Cache updated successfully at {cache_data['timestamp']}")
            
        except Exception as e:
            print(f"Error setting cache: {e}")
            raise
    
    @staticmethod
    def clear_cache():
        """Invalidate and clear the cache."""
        DrillDataCache.set_cache_property("")
        print("Cache cleared")
    
    @staticmethod
    def is_cache_valid(project_id: int, company_id: int) -> bool:
        """
        Check if cache exists and is for the current project.
        
        Args:
            project_id: Current project ID
            company_id: Current company ID
            
        Returns:
            True if cache is valid for this project
        """
        cache = DrillDataCache.get_cache()
        if cache is None:
            return False
        
        return (cache.get('project_id') == project_id and 
                cache.get('company_id') == company_id)
    
    @staticmethod
    def get_cache_summary() -> Dict[str, Any]:
        """
        Get a summary of cached data for UI display.

        Returns:
            Dictionary with cache statistics
        """
        cache = DrillDataCache.get_cache()
        if cache is None:
            return {
                'valid': False,
                'message': 'No cache available'
            }

        try:
            timestamp = datetime.fromisoformat(cache.get('timestamp', ''))
            time_str = timestamp.strftime('%I:%M %p')
        except:
            time_str = 'Unknown'

        collars = cache.get('collars', [])
        surveys = cache.get('surveys', {})
        samples = cache.get('samples', {})
        lithology = cache.get('lithology', {})
        alteration = cache.get('alteration', {})
        desurveyed_traces = cache.get('desurveyed_traces', {})
        assay_configs = cache.get('assay_range_configs', [])

        # Count total intervals
        total_samples = sum(len(v) for v in samples.values()) if isinstance(samples, dict) else 0
        total_lithology = sum(len(v) for v in lithology.values()) if isinstance(lithology, dict) else 0
        total_alteration = sum(len(v) for v in alteration.values()) if isinstance(alteration, dict) else 0

        # Check coordinate system
        proj_meta = cache.get('project_metadata', {})
        has_proj4 = bool(proj_meta.get('proj4_string'))

        # Get available elements and types
        available_elements = cache.get('available_elements', [])
        available_lithologies = cache.get('available_lithologies', [])
        available_alterations = cache.get('available_alterations', [])

        return {
            'valid': True,
            'timestamp': time_str,
            'project_id': cache.get('project_id'),
            'company_id': cache.get('company_id'),
            'project_name': cache.get('project_name'),
            'company_name': cache.get('company_name'),
            'collar_count': len(collars),
            'survey_hole_count': len(surveys),
            'sample_count': total_samples,
            'lithology_count': total_lithology,
            'alteration_count': total_alteration,
            'assay_config_count': len(assay_configs),
            'available_elements': available_elements,
            'available_lithologies': available_lithologies,
            'available_alterations': available_alterations,
            'has_validation': 'validation_report' in cache and cache.get('validation_report') is not None,
            'has_desurveyed_traces': desurveyed_traces is not None and len(desurveyed_traces) > 0,
            'has_desurveyed_intervals': 'desurveyed_intervals' in cache and cache.get('desurveyed_intervals') is not None,
            'desurveyed_hole_count': len(desurveyed_traces) if desurveyed_traces else 0,
            'has_proj4_coords': has_proj4
        }

    @staticmethod
    def get_sync_timestamp(entity_type: str) -> Optional[str]:
        """
        Get the last sync timestamp for an entity type.

        Used for incremental deletion sync - pass this value as 'deleted_since'
        parameter to only get recently deleted record IDs.

        Args:
            entity_type: Entity type (e.g., 'drill_collars', 'drill_surveys')

        Returns:
            ISO 8601 timestamp string, or None if never synced
        """
        cache = DrillDataCache.get_cache()
        if cache is None:
            return None

        sync_timestamps = cache.get('sync_timestamps', {})
        return sync_timestamps.get(entity_type)

    @staticmethod
    def set_sync_timestamp(entity_type: str, timestamp: str):
        """
        Store the sync timestamp for an entity type.

        Called after successful sync to record the server's sync_timestamp
        for use in the next incremental sync.

        Args:
            entity_type: Entity type (e.g., 'drill_collars', 'drill_surveys')
            timestamp: ISO 8601 timestamp from server's sync_timestamp field
        """
        cache = DrillDataCache.get_cache()
        if cache is None:
            print(f"WARNING: Cannot set sync timestamp - no cache exists")
            return

        # Get or create sync_timestamps dict
        sync_timestamps = cache.get('sync_timestamps', {})
        sync_timestamps[entity_type] = timestamp

        # Update cache
        cache['sync_timestamps'] = sync_timestamps
        DrillDataCache.set_cache(cache)
        print(f"[SyncTimestamp] Set {entity_type} = {timestamp}")

    @staticmethod
    def clear_sync_timestamps():
        """
        Clear all sync timestamps (forces full sync on next refresh).

        Called when project changes or when user explicitly requests full refresh.
        """
        cache = DrillDataCache.get_cache()
        if cache is None:
            return

        cache['sync_timestamps'] = {}
        DrillDataCache.set_cache(cache)
        print("[SyncTimestamp] Cleared all sync timestamps")
    
    @staticmethod
    def save_cache_to_file(filepath: Optional[str] = None):
        """
        Save cache to an external JSON file.
        
        Args:
            filepath: Path to save file. If None, saves next to blend file.
        """
        cache = DrillDataCache.get_cache()
        if cache is None:
            raise ValueError("No cache to save")
        
        # Determine filepath
        if filepath is None:
            blend_path = bpy.data.filepath
            if not blend_path:
                raise ValueError("Blend file must be saved before exporting cache")
            
            blend_dir = os.path.dirname(blend_path)
            project_name = cache.get('project_name', 'unknown')
            filepath = os.path.join(blend_dir, f"{project_name}_cache.json")
        
        # Write to file
        with open(filepath, 'w') as f:
            json.dump(cache, f, indent=2, default=str)
        
        print(f"Cache saved to: {filepath}")
        return filepath
    
    @staticmethod
    def load_cache_from_file(filepath: str):
        """
        Load cache from an external JSON file.
        
        Args:
            filepath: Path to cache file
        """
        with open(filepath, 'r') as f:
            cache_data = json.load(f)
        
        # Validate version
        if cache_data.get('version') != DrillDataCache.CACHE_VERSION:
            raise ValueError(f"Cache file version mismatch. Expected {DrillDataCache.CACHE_VERSION}")
        
        DrillDataCache.set_cache(cache_data)
        print(f"Cache loaded from: {filepath}")


def create_empty_cache(project_id: int, company_id: int,
                       project_name: str, company_name: str, hole_ids: List[int]) -> Dict[str, Any]:
    """
    Create an empty cache structure (v1.2).

    Args:
        project_id: Project ID
        company_id: Company ID
        project_name: Project name
        company_name: Company name
        hole_ids: List of drill hole IDs

    Returns:
        Empty cache dictionary
    """
    return {
        'project_id': project_id,
        'company_id': company_id,
        'project_name': project_name,
        'company_name': company_name,
        'hole_ids': hole_ids,
        'project_metadata': {},  # Coordinate system info (API Phase 2B)
        'collars': [],
        'surveys': {},
        'samples': {},
        'lithology': {},
        'alteration': {},
        'assay_range_configs': [],  # Assay Range Configurations from API
        'available_elements': [],  # List of available assay elements
        'available_lithologies': [],  # List of available lithology types
        'available_alterations': [],  # List of available alteration types
        'validation_report': None,
        'desurveyed_traces': None,  # Borehole traces (XYZ coordinates)
        'desurveyed_intervals': None,  # Sample/lithology/alteration intervals (XYZ)
        'sync_timestamps': {},  # v1.2: Per-entity sync timestamps for incremental deletion sync
    }


def process_deleted_collar_ids(deleted_ids: List[int], project_id: int) -> Dict[str, Any]:
    """
    Process deleted drill collar IDs from the server.

    Removes deleted collars from the cache and from the Blender scene.
    Also cleans up associated data (surveys, samples, etc.) for deleted collars.

    Args:
        deleted_ids: List of server collar IDs that were soft-deleted
        project_id: Current project ID (for validation)

    Returns:
        Dict with:
            - removed_from_cache: Number of collars removed from cache
            - removed_from_scene: Number of objects removed from scene
            - orphaned_data_cleaned: Dict of cleaned child data counts
    """
    result = {
        'removed_from_cache': 0,
        'removed_from_scene': 0,
        'orphaned_data_cleaned': {
            'surveys': 0,
            'samples': 0,
            'lithology': 0,
            'alteration': 0,
        }
    }

    if not deleted_ids:
        return result

    print(f"\n=== Processing {len(deleted_ids)} Deleted Collar IDs ===")

    deleted_ids_set = set(deleted_ids)

    # 1. Remove from cache
    cache = DrillDataCache.get_cache()
    if cache and cache.get('project_id') == project_id:
        collars = cache.get('collars', [])
        original_count = len(collars)

        # Filter out deleted collars
        remaining_collars = [c for c in collars if c.get('id') not in deleted_ids_set]
        removed_collar_count = original_count - len(remaining_collars)
        result['removed_from_cache'] = removed_collar_count

        if removed_collar_count > 0:
            cache['collars'] = remaining_collars

            # Also remove hole_ids
            hole_ids = cache.get('hole_ids', [])
            cache['hole_ids'] = [hid for hid in hole_ids if hid not in deleted_ids_set]

            # Clean up child data for deleted collars
            for data_key in ['surveys', 'samples', 'lithology', 'alteration']:
                data_dict = cache.get(data_key, {})
                if isinstance(data_dict, dict):
                    cleaned_count = 0
                    # Keys can be int IDs or "name:XXX" strings
                    keys_to_remove = []
                    for key in data_dict.keys():
                        if isinstance(key, int) and key in deleted_ids_set:
                            keys_to_remove.append(key)
                            cleaned_count += len(data_dict.get(key, []))
                    for key in keys_to_remove:
                        del data_dict[key]
                    result['orphaned_data_cleaned'][data_key] = cleaned_count

            # Update cache
            DrillDataCache.set_cache(cache)
            print(f"[DeleteSync] Removed {removed_collar_count} collars from cache")

    # 2. Remove from Blender scene
    scene_removed = _remove_deleted_holes_from_scene(deleted_ids_set)
    result['removed_from_scene'] = scene_removed

    print(f"[DeleteSync] Summary: cache={result['removed_from_cache']}, "
          f"scene={result['removed_from_scene']}, "
          f"orphaned_surveys={result['orphaned_data_cleaned']['surveys']}, "
          f"orphaned_samples={result['orphaned_data_cleaned']['samples']}")

    return result


def _remove_deleted_holes_from_scene(deleted_ids: set) -> int:
    """
    Remove Blender objects for deleted drill holes from the scene.

    Finds objects tagged with geodb_hole_id matching deleted IDs and removes them.

    Args:
        deleted_ids: Set of deleted collar IDs

    Returns:
        Number of objects removed
    """
    removed_count = 0

    # Find and remove matching objects
    objects_to_remove = []
    for obj in bpy.data.objects:
        hole_id = obj.get('geodb_hole_id')
        if hole_id is not None and hole_id in deleted_ids:
            objects_to_remove.append(obj)

    # Remove objects (must be done outside iteration)
    for obj in objects_to_remove:
        hole_name = obj.get('geodb_hole_name', obj.name)
        print(f"[DeleteSync] Removing deleted hole from scene: {hole_name} (ID: {obj.get('geodb_hole_id')})")

        # Unlink from all collections first
        for collection in obj.users_collection:
            collection.objects.unlink(obj)

        # Remove the object data (mesh, etc.)
        if obj.data:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            # Remove orphaned mesh data
            if hasattr(bpy.data, 'meshes') and data.name in bpy.data.meshes:
                if data.users == 0:
                    bpy.data.meshes.remove(data)
        else:
            bpy.data.objects.remove(obj, do_unlink=True)

        removed_count += 1

    if removed_count > 0:
        print(f"[DeleteSync] Removed {removed_count} drill hole objects from scene")

    return removed_count


def sync_deletions_from_fetch_result(
    fetch_result: Dict[str, Any],
    entity_type: str = 'drill_collars'
) -> Dict[str, Any]:
    """
    Convenience function to process deletion sync after a data fetch.

    This function handles the complete deletion sync workflow:
    1. Processes deleted_ids from the fetch result
    2. Updates the sync timestamp for next incremental sync
    3. Returns a summary of what was removed

    Args:
        fetch_result: Result dict from fetch_all_project_data() or similar,
                     containing 'deleted_collar_ids', 'sync_timestamp', 'project_id'
        entity_type: The entity type being synced (default: 'drill_collars')

    Returns:
        Dict with sync summary including removed counts and any errors
    """
    summary = {
        'deleted_ids_received': 0,
        'removed_from_cache': 0,
        'removed_from_scene': 0,
        'sync_timestamp_updated': False,
        'errors': []
    }

    try:
        # Get deleted IDs based on entity type
        if entity_type == 'drill_collars':
            deleted_ids = fetch_result.get('deleted_collar_ids', [])
        else:
            deleted_ids = fetch_result.get(f'deleted_{entity_type}_ids', [])

        summary['deleted_ids_received'] = len(deleted_ids)

        # Process deletions
        if deleted_ids:
            project_id = fetch_result.get('project_id')
            if project_id:
                if entity_type == 'drill_collars':
                    result = process_deleted_collar_ids(deleted_ids, project_id)
                    summary['removed_from_cache'] = result.get('removed_from_cache', 0)
                    summary['removed_from_scene'] = result.get('removed_from_scene', 0)
                # Add other entity types here as needed

        # Update sync timestamp for next incremental sync
        sync_timestamp = fetch_result.get('sync_timestamp')
        if sync_timestamp:
            DrillDataCache.set_sync_timestamp(entity_type, sync_timestamp)
            summary['sync_timestamp_updated'] = True

    except Exception as e:
        summary['errors'].append(str(e))
        print(f"[DeleteSync] Error processing deletions: {e}")
        import traceback
        traceback.print_exc()

    return summary


def register():
    """Register cache property.

    Note: The cache property is now registered in the main __init__.py
    before modules are loaded. This function is kept for compatibility.
    """
    pass


def unregister():
    """Unregister cache property.

    Note: The cache property is now unregistered in the main __init__.py.
    This function is kept for compatibility.
    """
    pass