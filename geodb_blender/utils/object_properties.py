"""
Object property management for geoDB Blender plugin.

This module provides utilities for tagging Blender objects created by the plugin
with comprehensive metadata for inspection and management.
"""

import bpy
from typing import Dict, Any, Optional


class GeoDBObjectProperties:
    """Manager for geoDB custom properties on Blender objects."""
    
    # Property keys
    MARKER_KEY = "geodb_object_type"  # Main identifier for geoDB objects
    
    # Object types
    TYPE_DRILL_TRACE = "drill_trace"
    TYPE_DRILL_SAMPLE = "drill_sample"
    TYPE_COLLAR_MARKER = "collar_marker"
    TYPE_LEGEND = "legend"
    TYPE_LEGEND_TEXT = "legend_text"
    TYPE_INTERPOLATION = "interpolation"
    
    @staticmethod
    def is_geodb_object(obj: bpy.types.Object) -> bool:
        """Check if an object was created by the geoDB plugin.
        
        Args:
            obj: Blender object to check
            
        Returns:
            True if object has geoDB marker property
        """
        return obj is not None and GeoDBObjectProperties.MARKER_KEY in obj
    
    @staticmethod
    def get_object_type(obj: bpy.types.Object) -> Optional[str]:
        """Get the geoDB object type.
        
        Args:
            obj: Blender object
            
        Returns:
            Object type string or None if not a geoDB object
        """
        if not GeoDBObjectProperties.is_geodb_object(obj):
            return None
        return obj.get(GeoDBObjectProperties.MARKER_KEY)
    
    @staticmethod
    def tag_drill_trace(obj: bpy.types.Object, properties: Dict[str, Any]):
        """Tag a drill trace object with comprehensive metadata.
        
        Args:
            obj: Blender object (drill trace curve/mesh)
            properties: Dictionary with metadata:
                - bhid: Drill hole ID (required)
                - hole_name: Display name (required)
                - project_id: Project ID
                - project_name: Project name
                - company_name: Company name
                - collar_x, collar_y, collar_z: Collar coordinates
                - total_depth: Total depth of hole
                - survey_count: Number of survey points
                - validation_status: 'valid', 'warning', 'error'
                - validation_messages: List of validation messages
                - desurvey_method: Method used (e.g., 'minimum_curvature')
                - created_date: Date hole was created
                - Any additional custom properties
        """
        # Set marker
        obj[GeoDBObjectProperties.MARKER_KEY] = GeoDBObjectProperties.TYPE_DRILL_TRACE
        
        # Set required properties
        obj["geodb_bhid"] = properties.get("bhid", "UNKNOWN")
        obj["geodb_hole_name"] = properties.get("hole_name", "UNKNOWN")
        
        # Set optional properties (only if provided)
        optional_props = {
            "geodb_project_id": properties.get("project_id"),
            "geodb_project_name": properties.get("project_name"),
            "geodb_company_name": properties.get("company_name"),
            "geodb_collar_x": properties.get("collar_x"),
            "geodb_collar_y": properties.get("collar_y"),
            "geodb_collar_z": properties.get("collar_z"),
            "geodb_total_depth": properties.get("total_depth"),
            "geodb_survey_count": properties.get("survey_count"),
            "geodb_validation_status": properties.get("validation_status"),
            "geodb_desurvey_method": properties.get("desurvey_method", "minimum_curvature"),
            "geodb_created_date": properties.get("created_date"),
        }
        
        for key, value in optional_props.items():
            if value is not None:
                obj[key] = value
        
        # Store validation messages as a JSON-like string if provided
        if "validation_messages" in properties and properties["validation_messages"]:
            messages = properties["validation_messages"]
            if isinstance(messages, list):
                obj["geodb_validation_messages"] = " | ".join(messages)
            else:
                obj["geodb_validation_messages"] = str(messages)
    
    @staticmethod
    def tag_drill_sample(obj: bpy.types.Object, properties: Dict[str, Any]):
        """Tag a drill sample interval object with metadata.
        
        Args:
            obj: Blender object (sample cylinder/mesh)
            properties: Dictionary with metadata:
                - bhid: Drill hole ID (required)
                - hole_name: Display name (required)
                - sample_id: Sample ID
                - depth_from: Start depth
                - depth_to: End depth
                - sample_type: Type of sample (core, RC, etc.)
                - lithology: Rock type
                - alteration: Alteration type
                - assay data: Any element values (e.g., cu_pct, au_ppm)
        """
        # Set marker
        obj[GeoDBObjectProperties.MARKER_KEY] = GeoDBObjectProperties.TYPE_DRILL_SAMPLE
        
        # Set required properties
        obj["geodb_bhid"] = properties.get("bhid", "UNKNOWN")
        obj["geodb_hole_name"] = properties.get("hole_name", "UNKNOWN")
        
        # Set sample-specific properties
        optional_props = {
            "geodb_sample_id": properties.get("sample_id"),
            "geodb_depth_from": properties.get("depth_from"),
            "geodb_depth_to": properties.get("depth_to"),
            "geodb_sample_type": properties.get("sample_type"),
            "geodb_lithology": properties.get("lithology"),
            "geodb_alteration": properties.get("alteration"),
        }
        
        for key, value in optional_props.items():
            if value is not None:
                obj[key] = value
        
        # Add any assay data (dynamic properties)
        # Look for any keys that don't match standard properties
        standard_keys = {
            "bhid", "hole_name", "sample_id", "depth_from", "depth_to",
            "sample_type", "lithology", "alteration"
        }
        
        for key, value in properties.items():
            if key not in standard_keys and value is not None:
                # Store assay values with geodb_ prefix
                obj[f"geodb_{key}"] = value
    
    @staticmethod
    def tag_collar_marker(obj: bpy.types.Object, properties: Dict[str, Any]):
        """Tag a collar marker object with metadata.
        
        Args:
            obj: Blender object (collar marker)
            properties: Dictionary with collar metadata
        """
        obj[GeoDBObjectProperties.MARKER_KEY] = GeoDBObjectProperties.TYPE_COLLAR_MARKER
        obj["geodb_bhid"] = properties.get("bhid", "UNKNOWN")
        obj["geodb_hole_name"] = properties.get("hole_name", "UNKNOWN")
        
        for key, value in properties.items():
            if key not in ["bhid", "hole_name"] and value is not None:
                obj[f"geodb_{key}"] = value
    
    @staticmethod
    def get_properties(obj: bpy.types.Object) -> Dict[str, Any]:
        """Get all geoDB properties from an object.
        
        Args:
            obj: Blender object
            
        Returns:
            Dictionary of all geodb_* properties
        """
        if not GeoDBObjectProperties.is_geodb_object(obj):
            return {}
        
        props = {}
        for key in obj.keys():
            if key.startswith("geodb_"):
                props[key] = obj[key]
        
        return props
    
    @staticmethod
    def get_display_properties(obj: bpy.types.Object) -> Dict[str, tuple]:
        """Get formatted properties for UI display.
        
        Returns:
            Dictionary with {section: [(label, value), ...]}
        """
        if not GeoDBObjectProperties.is_geodb_object(obj):
            return {}
        
        obj_type = GeoDBObjectProperties.get_object_type(obj)
        display = {}
        
        # General section (all object types)
        general = []
        general.append(("Type", obj_type.replace("_", " ").title()))
        
        if "geodb_hole_name" in obj:
            general.append(("Hole Name", obj["geodb_hole_name"]))
        if "geodb_bhid" in obj:
            general.append(("BHID", str(obj["geodb_bhid"])))
        
        display["General"] = general
        
        # Project info section
        project = []
        if "geodb_project_name" in obj:
            project.append(("Project", obj["geodb_project_name"]))
        if "geodb_company_name" in obj:
            project.append(("Company", obj["geodb_company_name"]))
        if "geodb_project_id" in obj:
            project.append(("Project ID", str(obj["geodb_project_id"])))
        
        if project:
            display["Project"] = project
        
        # Location section (for drill traces and collars)
        if obj_type in [GeoDBObjectProperties.TYPE_DRILL_TRACE, 
                       GeoDBObjectProperties.TYPE_COLLAR_MARKER]:
            location = []
            if "geodb_collar_x" in obj:
                location.append(("Collar X", f"{obj['geodb_collar_x']:.2f}"))
            if "geodb_collar_y" in obj:
                location.append(("Collar Y", f"{obj['geodb_collar_y']:.2f}"))
            if "geodb_collar_z" in obj:
                location.append(("Collar Z", f"{obj['geodb_collar_z']:.2f}"))
            
            if location:
                display["Location"] = location
        
        # Drill hole info section (for traces)
        if obj_type == GeoDBObjectProperties.TYPE_DRILL_TRACE:
            drill_info = []
            if "geodb_total_depth" in obj:
                drill_info.append(("Total Depth", f"{obj['geodb_total_depth']:.2f} m"))
            if "geodb_survey_count" in obj:
                drill_info.append(("Survey Points", str(obj["geodb_survey_count"])))
            if "geodb_desurvey_method" in obj:
                drill_info.append(("Desurvey Method", obj["geodb_desurvey_method"]))
            if "geodb_created_date" in obj:
                drill_info.append(("Created", obj["geodb_created_date"]))
            
            if drill_info:
                display["Drill Hole Info"] = drill_info
        
        # Sample info section (for samples)
        if obj_type == GeoDBObjectProperties.TYPE_DRILL_SAMPLE:
            sample_info = []
            if "geodb_sample_id" in obj:
                sample_info.append(("Sample ID", obj["geodb_sample_id"]))
            if "geodb_depth_from" in obj and "geodb_depth_to" in obj:
                sample_info.append(("Interval", 
                    f"{obj['geodb_depth_from']:.2f} - {obj['geodb_depth_to']:.2f} m"))
            if "geodb_sample_type" in obj:
                sample_info.append(("Sample Type", obj["geodb_sample_type"]))
            if "geodb_lithology" in obj:
                sample_info.append(("Lithology", obj["geodb_lithology"]))
            if "geodb_alteration" in obj:
                sample_info.append(("Alteration", obj["geodb_alteration"]))
            
            if sample_info:
                display["Sample Info"] = sample_info
            
            # Assay data section
            assays = []
            for key in obj.keys():
                if key.startswith("geodb_") and key not in [
                    "geodb_object_type", "geodb_bhid", "geodb_hole_name",
                    "geodb_sample_id", "geodb_depth_from", "geodb_depth_to",
                    "geodb_sample_type", "geodb_lithology", "geodb_alteration"
                ]:
                    # Format assay names nicely (e.g., cu_pct -> Cu (%))
                    display_name = key.replace("geodb_", "").replace("_", " ").title()
                    value = obj[key]
                    if isinstance(value, (int, float)):
                        assays.append((display_name, f"{value:.4f}"))
                    else:
                        assays.append((display_name, str(value)))
            
            if assays:
                display["Assay Data"] = assays
        
        # Validation section
        if "geodb_validation_status" in obj:
            validation = []
            status = obj["geodb_validation_status"]
            validation.append(("Status", status.upper()))
            
            if "geodb_validation_messages" in obj:
                validation.append(("Messages", obj["geodb_validation_messages"]))
            
            display["Validation"] = validation
        
        return display


def clear_geodb_objects(object_type: Optional[str] = None):
    """Remove all geoDB objects from the scene.
    
    Args:
        object_type: If specified, only remove objects of this type
    """
    to_remove = []
    
    for obj in bpy.data.objects:
        if GeoDBObjectProperties.is_geodb_object(obj):
            if object_type is None or GeoDBObjectProperties.get_object_type(obj) == object_type:
                to_remove.append(obj)
    
    for obj in to_remove:
        bpy.data.objects.remove(obj, do_unlink=True)
    
    return len(to_remove)