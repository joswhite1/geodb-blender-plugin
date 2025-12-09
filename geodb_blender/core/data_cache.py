"""
Data caching system for geoDB drill hole data.

This module provides centralized caching for all project drill data,
reducing API calls and improving performance.
"""

import bpy
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
import os


class DrillDataCache:
    """Manager for drill hole data caching."""
    
    CACHE_VERSION = "1.1.0"  # Updated for assay range configurations support
    
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
    Create an empty cache structure (v1.1).
    
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
        'assay_range_configs': [],  # NEW: Assay Range Configurations from API
        'available_elements': [],  # NEW: List of available assay elements
        'available_lithologies': [],  # NEW: List of available lithology types
        'available_alterations': [],  # NEW: List of available alteration types
        'validation_report': None,
        'desurveyed_traces': None,  # Borehole traces (XYZ coordinates)
        'desurveyed_intervals': None  # Sample/lithology/alteration intervals (XYZ)
    }


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