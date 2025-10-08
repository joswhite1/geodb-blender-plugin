"""
Visualization module for the geoDB Blender add-on.

This module provides functionality for visualizing drill hole data in Blender,
including drill traces, samples, and assay values.
"""

import bpy
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import colorsys

from ..utils.desurvey import create_drill_trace_mesh, create_drill_sample_meshes
from ..utils.object_properties import GeoDBObjectProperties

class DrillHoleVisualizer:
    """Class for visualizing drill hole data in Blender."""
    
    @staticmethod
    def clear_visualizations():
        """Clear all drill hole visualizations from the scene."""
        # Remove all objects with the geodb_visualization tag
        for obj in bpy.data.objects:
            if 'geodb_visualization' in obj:
                bpy.data.objects.remove(obj, do_unlink=True)
    
    @staticmethod
    def visualize_drill_hole(collar: Tuple, surveys: List[Tuple], 
                            samples: Optional[List[Dict]] = None,
                            hole_name: str = "DrillHole",
                            show_trace: bool = True,
                            show_samples: bool = True,
                            trace_segments: int = 100,
                            metadata: Optional[Dict[str, Any]] = None):
        """Visualize a drill hole in Blender.
        
        Args:
            collar: Tuple (x, y, z, total_depth) with collar coordinates and total depth
            surveys: List of tuples [(azimuth, dip, depth), ...] with survey data
            samples: Optional list of sample dictionaries with depth_from, depth_to, and values
            hole_name: Name for the drill hole objects
            show_trace: Whether to show the drill trace
            show_samples: Whether to show sample intervals
            trace_segments: Number of segments to use for the drill trace
            metadata: Optional dictionary with additional metadata (project info, validation, etc.)
        
        Returns:
            List of created objects
        """
        created_objects = []
        
        # Prepare metadata for tagging
        if metadata is None:
            metadata = {}
        
        # Create drill trace if requested
        if show_trace:
            if not surveys:
                print("WARNING: Cannot create drill trace - no survey data available")
            else:
                trace_obj = create_drill_trace_mesh(
                    collar=collar,
                    surveys=surveys,
                    segments=trace_segments,
                    name=f"{hole_name}_Trace"
                )
                
                # Tag with comprehensive metadata using new property system
                trace_props = {
                    "bhid": metadata.get("bhid", hole_name),
                    "hole_name": hole_name,
                    "project_id": metadata.get("project_id"),
                    "project_name": metadata.get("project_name"),
                    "company_name": metadata.get("company_name"),
                    "collar_x": collar[0],
                    "collar_y": collar[1],
                    "collar_z": collar[2],
                    "total_depth": collar[3] if len(collar) > 3 else None,
                    "survey_count": len(surveys),
                    "validation_status": metadata.get("validation_status", "unknown"),
                    "validation_messages": metadata.get("validation_messages"),
                    "desurvey_method": "minimum_curvature",
                    "created_date": metadata.get("created_date"),
                }
                
                GeoDBObjectProperties.tag_drill_trace(trace_obj, trace_props)
                
                # Maintain backward compatibility with old tagging system
                trace_obj['geodb_visualization'] = True
                trace_obj['geodb_type'] = 'drill_trace'
                trace_obj['geodb_hole_name'] = hole_name
                
                # Set display properties
                trace_obj.display_type = 'WIRE'
                
                created_objects.append(trace_obj)
        
        # Create sample visualizations if requested and samples are provided
        if show_samples and samples:
            sample_objs = create_drill_sample_meshes(
                collar=collar,
                surveys=surveys,
                samples=samples,
                name_prefix=f"{hole_name}_Sample"
            )
            
            # Tag as geodb visualization and set display properties
            for i, obj in enumerate(sample_objs):
                # Get corresponding sample data
                sample = samples[i] if i < len(samples) else {}
                
                # Tag with comprehensive metadata
                sample_props = {
                    "bhid": metadata.get("bhid", hole_name),
                    "hole_name": hole_name,
                    "sample_id": sample.get("id") or sample.get("name"),
                    "depth_from": sample.get("depth_from"),
                    "depth_to": sample.get("depth_to"),
                    "sample_type": sample.get("sample_type"),
                    "lithology": sample.get("lithology"),
                    "alteration": sample.get("alteration"),
                }
                
                # Add any assay/value data
                if "values" in sample:
                    for key, value in sample["values"].items():
                        sample_props[key] = value
                
                GeoDBObjectProperties.tag_drill_sample(obj, sample_props)
                
                # Maintain backward compatibility
                obj['geodb_visualization'] = True
                obj['geodb_type'] = 'sample'
                obj['geodb_hole_name'] = hole_name
                
                # Set display properties
                obj.display_type = 'SOLID'
                
                created_objects.append(obj)
        
        return created_objects
    
    @staticmethod
    def apply_color_mapping(objects: List[bpy.types.Object], element: str, 
                           min_value: float = None, max_value: float = None,
                           color_map: str = 'RAINBOW'):
        """Apply color mapping to sample objects based on element values.
        
        Args:
            objects: List of sample objects to color
            element: Element name to use for coloring
            min_value: Minimum value for color mapping (auto-detected if None)
            max_value: Maximum value for color mapping (auto-detected if None)
            color_map: Color map to use ('RAINBOW', 'VIRIDIS', 'PLASMA', 'MAGMA')
        """
        # Filter objects to only include samples with the specified element
        valid_objects = []
        values = []
        
        for obj in objects:
            if 'geodb_type' in obj and obj['geodb_type'] == 'sample':
                value_key = f'value_{element}'
                if value_key in obj:
                    valid_objects.append(obj)
                    values.append(obj[value_key])
        
        if not valid_objects:
            return
        
        # Determine min and max values if not provided
        if min_value is None:
            min_value = min(values)
        if max_value is None:
            max_value = max(values)
        
        # Avoid division by zero
        value_range = max_value - min_value
        if value_range == 0:
            value_range = 1.0
        
        # Create materials for each object
        for obj, value in zip(valid_objects, values):
            # Normalize value to 0-1 range
            normalized = (value - min_value) / value_range
            
            # Create material if it doesn't exist
            mat_name = f"Sample_{element}_{value:.2f}"
            mat = bpy.data.materials.get(mat_name)
            
            if mat is None:
                mat = bpy.data.materials.new(mat_name)
                mat.use_nodes = True
                
                # Get material nodes
                nodes = mat.node_tree.nodes
                
                # Clear default nodes
                nodes.clear()
                
                # Create emission shader for better visibility
                emission = nodes.new(type='ShaderNodeEmission')
                
                # Set color based on color map
                if color_map == 'RAINBOW':
                    # Rainbow: hue from 0 (red) to 0.66 (blue)
                    hue = 0.66 * (1.0 - normalized)
                    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                elif color_map == 'VIRIDIS':
                    # Approximate Viridis colormap
                    r = 0.267 * (1 - normalized) + 0.000 * normalized
                    g = 0.005 * (1 - normalized) + 0.520 * normalized
                    b = 0.329 * (1 - normalized) + 0.294 * normalized
                elif color_map == 'PLASMA':
                    # Approximate Plasma colormap
                    r = 0.050 * (1 - normalized) + 0.940 * normalized
                    g = 0.030 * (1 - normalized) + 0.150 * normalized
                    b = 0.550 * (1 - normalized) + 0.060 * normalized
                elif color_map == 'MAGMA':
                    # Approximate Magma colormap
                    r = 0.001 * (1 - normalized) + 0.988 * normalized
                    g = 0.000 * (1 - normalized) + 0.155 * normalized
                    b = 0.014 * (1 - normalized) + 0.367 * normalized
                else:
                    # Default to grayscale
                    r = g = b = normalized
                
                emission.inputs[0].default_value = (r, g, b, 1.0)
                
                # Set emission strength based on value
                emission.inputs[1].default_value = 1.0
                
                # Create output node
                output = nodes.new(type='ShaderNodeOutputMaterial')
                
                # Link nodes
                links = mat.node_tree.links
                links.new(emission.outputs[0], output.inputs[0])
            
            # Assign material to object
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)
    
    @staticmethod
    def create_legend(element: str, min_value: float, max_value: float, 
                     position: Tuple[float, float, float] = (0, 0, 0),
                     size: float = 1.0, color_map: str = 'RAINBOW'):
        """Create a color legend for the specified element.
        
        Args:
            element: Element name for the legend
            min_value: Minimum value
            max_value: Maximum value
            position: Position for the legend
            size: Size of the legend
            color_map: Color map to use
            
        Returns:
            The created legend object
        """
        # Create a plane for the legend
        bpy.ops.mesh.primitive_plane_add(size=size, location=position)
        legend = bpy.context.active_object
        legend.name = f"Legend_{element}"
        
        # Tag as geodb visualization
        legend['geodb_visualization'] = True
        legend['geodb_type'] = 'legend'
        legend['geodb_element'] = element
        legend['geodb_min_value'] = min_value
        legend['geodb_max_value'] = max_value
        
        # Create a material for the legend
        mat = bpy.data.materials.new(f"Legend_{element}")
        mat.use_nodes = True
        
        # Get material nodes
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        
        # Clear default nodes
        nodes.clear()
        
        # Create gradient texture
        tex_coord = nodes.new(type='ShaderNodeTexCoord')
        mapping = nodes.new(type='ShaderNodeMapping')
        gradient = nodes.new(type='ShaderNodeTexGradient')
        
        # Create color ramp
        color_ramp = nodes.new(type='ShaderNodeValToRGB')
        color_ramp.color_ramp.interpolation = 'LINEAR'
        
        # Set color ramp colors based on color map
        if color_map == 'RAINBOW':
            # Rainbow: red to blue
            color_ramp.color_ramp.elements[0].color = (0.0, 0.0, 1.0, 1.0)  # Blue (low)
            color_ramp.color_ramp.elements[1].color = (1.0, 0.0, 0.0, 1.0)  # Red (high)
        elif color_map == 'VIRIDIS':
            color_ramp.color_ramp.elements[0].color = (0.267, 0.005, 0.329, 1.0)  # Low
            color_ramp.color_ramp.elements[1].color = (0.000, 0.520, 0.294, 1.0)  # High
        elif color_map == 'PLASMA':
            color_ramp.color_ramp.elements[0].color = (0.050, 0.030, 0.550, 1.0)  # Low
            color_ramp.color_ramp.elements[1].color = (0.940, 0.150, 0.060, 1.0)  # High
        elif color_map == 'MAGMA':
            color_ramp.color_ramp.elements[0].color = (0.001, 0.000, 0.014, 1.0)  # Low
            color_ramp.color_ramp.elements[1].color = (0.988, 0.155, 0.367, 1.0)  # High
        
        # Create emission shader
        emission = nodes.new(type='ShaderNodeEmission')
        
        # Create output node
        output = nodes.new(type='ShaderNodeOutputMaterial')
        
        # Link nodes
        links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
        links.new(mapping.outputs['Vector'], gradient.inputs['Vector'])
        links.new(gradient.outputs['Color'], color_ramp.inputs['Fac'])
        links.new(color_ramp.outputs['Color'], emission.inputs['Color'])
        links.new(emission.outputs['Emission'], output.inputs['Surface'])
        
        # Assign material to legend
        legend.data.materials.append(mat)
        
        # Add text for min and max values
        font_curve = bpy.data.curves.new(type="FONT", name=f"Legend_Text_{element}")
        font_obj = bpy.data.objects.new(f"Legend_Text_{element}", font_curve)
        font_obj.data.body = f"{element}: {min_value:.2f} - {max_value:.2f}"
        
        # Position text above legend
        font_obj.location = (position[0], position[1], position[2] + size/2 + 0.1)
        
        # Add to scene
        bpy.context.collection.objects.link(font_obj)
        
        # Tag as geodb visualization
        font_obj['geodb_visualization'] = True
        font_obj['geodb_type'] = 'legend_text'
        
        return legend


class DrillVisualizationManager:
    """Manager for comprehensive drill hole visualization with collections."""
    
    @staticmethod
    def get_or_create_collection(name: str, parent_collection=None) -> bpy.types.Collection:
        """Get existing collection or create new one.
        
        Args:
            name: Collection name
            parent_collection: Parent collection to nest under (optional)
            
        Returns:
            Collection object
        """
        # Check if collection already exists
        if name in bpy.data.collections:
            collection = bpy.data.collections[name]
        else:
            # Create new collection
            collection = bpy.data.collections.new(name)
            
            # Link to parent or scene
            if parent_collection:
                parent_collection.children.link(collection)
            else:
                bpy.context.scene.collection.children.link(collection)
        
        return collection
    
    @staticmethod
    def create_project_collection_hierarchy(project_name: str) -> Dict[str, bpy.types.Collection]:
        """Create hierarchical collection structure for project.
        
        Structure:
            Drill Holes [Project]
            ├── Traces
            ├── Assays
            ├── Lithology
            └── Alteration
        
        Args:
            project_name: Name of the project
            
        Returns:
            Dictionary with collection references
        """
        # Create root collection
        root_name = f"Drill Holes [{project_name}]"
        root_collection = DrillVisualizationManager.get_or_create_collection(root_name)
        
        # Create sub-collections
        traces_collection = DrillVisualizationManager.get_or_create_collection(
            "Traces", parent_collection=root_collection
        )
        assays_collection = DrillVisualizationManager.get_or_create_collection(
            "Assays", parent_collection=root_collection
        )
        lithology_collection = DrillVisualizationManager.get_or_create_collection(
            "Lithology", parent_collection=root_collection
        )
        alteration_collection = DrillVisualizationManager.get_or_create_collection(
            "Alteration", parent_collection=root_collection
        )
        
        return {
            'root': root_collection,
            'traces': traces_collection,
            'assays': assays_collection,
            'lithology': lithology_collection,
            'alteration': alteration_collection
        }
    
    @staticmethod
    def apply_assay_range_configuration(objects: List[bpy.types.Object], 
                                       element: str,
                                       assay_config: Dict[str, Any]) -> int:
        """Apply colors from Assay Range Configuration to objects.
        
        Args:
            objects: List of sample objects to color
            element: Element name (e.g., "Au", "Cu")
            assay_config: Assay Range Configuration dict from API
            
        Returns:
            Number of objects colored
        """
        if not assay_config or 'ranges' not in assay_config:
            print(f"ERROR: Invalid assay configuration")
            return 0
        
        ranges = assay_config['ranges']
        default_color = assay_config.get('default_color', '#CCCCCC')
        
        colored_count = 0
        
        for obj in objects:
            # Get element value from object
            value_key = f'value_{element}'
            if value_key not in obj:
                continue
            
            value = obj[value_key]
            
            # Find matching range
            matched_range = None
            for range_item in ranges:
                from_value = range_item.get('from_value', 0)
                to_value = range_item.get('to_value', float('inf'))
                
                if from_value <= value < to_value:
                    matched_range = range_item
                    break
            
            # Get color (use default if no match)
            if matched_range:
                color_hex = matched_range.get('color', default_color)
                label = matched_range.get('label', '')
            else:
                color_hex = default_color
                label = 'Out of range'
            
            # Convert hex to RGB
            rgb = DrillVisualizationManager.hex_to_rgb(color_hex)
            
            # Create or get material
            mat_name = f"{element}_{label}_{color_hex}"
            mat = bpy.data.materials.get(mat_name)
            
            if mat is None:
                mat = bpy.data.materials.new(mat_name)
                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                nodes.clear()
                
                # Create emission shader
                emission = nodes.new(type='ShaderNodeEmission')
                emission.inputs[0].default_value = (*rgb, 1.0)
                emission.inputs[1].default_value = 1.0
                
                # Create output
                output = nodes.new(type='ShaderNodeOutputMaterial')
                
                # Link
                mat.node_tree.links.new(emission.outputs[0], output.inputs[0])
            
            # Assign material to object
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)
            
            # Tag object with color range info
            obj['geodb_config_id'] = assay_config.get('id')
            obj['geodb_config_name'] = assay_config.get('name')
            obj['geodb_element'] = element
            obj['geodb_value'] = value
            obj['geodb_color_range_label'] = label
            
            colored_count += 1
        
        return colored_count
    
    @staticmethod
    def hex_to_rgb(hex_color: str) -> Tuple[float, float, float]:
        """Convert hex color to RGB tuple (0-1 range).
        
        Args:
            hex_color: Hex color string (e.g., "#FF0000")
            
        Returns:
            Tuple of (r, g, b) in 0-1 range
        """
        # Remove '#' if present
        hex_color = hex_color.lstrip('#')
        
        # Convert to RGB
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        
        return (r, g, b)
    
    @staticmethod
    def organize_objects_in_collection(objects: List[bpy.types.Object], 
                                      collection: bpy.types.Collection,
                                      clear_existing: bool = False):
        """Move objects into a collection.
        
        Args:
            objects: List of objects to organize
            collection: Target collection
            clear_existing: Whether to unlink from existing collections first
        """
        for obj in objects:
            # Unlink from existing collections if requested
            if clear_existing:
                for coll in obj.users_collection:
                    coll.objects.unlink(obj)
            
            # Link to target collection if not already linked
            if obj.name not in collection.objects:
                collection.objects.link(obj)
    
    @staticmethod
    def create_element_layer(project_collections: Dict, 
                            element: str, 
                            config_name: str,
                            sample_objects: List[bpy.types.Object],
                            assay_config: Dict[str, Any]) -> bpy.types.Collection:
        """Create a new assay visualization layer.
        
        Args:
            project_collections: Dict with project collection hierarchy
            element: Element name (e.g., "Au")
            config_name: Configuration name
            sample_objects: List of sample objects to color
            assay_config: Assay Range Configuration from API
            
        Returns:
            Collection for this layer
        """
        # Create sub-collection under Assays
        assays_collection = project_collections['assays']
        layer_name = f"{element} [{config_name}]"
        layer_collection = DrillVisualizationManager.get_or_create_collection(
            layer_name, parent_collection=assays_collection
        )
        
        # Apply colors
        colored_count = DrillVisualizationManager.apply_assay_range_configuration(
            sample_objects, element, assay_config
        )
        
        # Organize objects in collection
        DrillVisualizationManager.organize_objects_in_collection(
            sample_objects, layer_collection
        )
        
        print(f"Created layer: {layer_name} with {colored_count} colored objects")
        
        return layer_collection
    
    @staticmethod
    def create_lithology_layer(project_collections: Dict,
                              lithology_type: str,
                              interval_objects: List[bpy.types.Object]) -> bpy.types.Collection:
        """Create lithology visualization layer.
        
        Args:
            project_collections: Dict with project collection hierarchy
            lithology_type: Lithology type name
            interval_objects: List of lithology interval objects
            
        Returns:
            Collection for this layer
        """
        lithology_collection = project_collections['lithology']
        layer_name = lithology_type
        layer_collection = DrillVisualizationManager.get_or_create_collection(
            layer_name, parent_collection=lithology_collection
        )
        
        # Organize objects
        DrillVisualizationManager.organize_objects_in_collection(
            interval_objects, layer_collection
        )
        
        print(f"Created lithology layer: {layer_name} with {len(interval_objects)} objects")
        
        return layer_collection
    
    @staticmethod
    def create_alteration_layer(project_collections: Dict,
                               alteration_type: str,
                               interval_objects: List[bpy.types.Object]) -> bpy.types.Collection:
        """Create alteration visualization layer.
        
        Args:
            project_collections: Dict with project collection hierarchy
            alteration_type: Alteration type name
            interval_objects: List of alteration interval objects
            
        Returns:
            Collection for this layer
        """
        alteration_collection = project_collections['alteration']
        layer_name = alteration_type
        layer_collection = DrillVisualizationManager.get_or_create_collection(
            layer_name, parent_collection=alteration_collection
        )
        
        # Organize objects
        DrillVisualizationManager.organize_objects_in_collection(
            interval_objects, layer_collection
        )
        
        print(f"Created alteration layer: {layer_name} with {len(interval_objects)} objects")
        
        return layer_collection