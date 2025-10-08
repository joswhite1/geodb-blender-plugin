"""
RBF interpolation module for the geoDB Blender add-on.

This module provides Radial Basis Function interpolation functionality
for creating 3D models from drill hole sample data.
"""

import bpy
import bmesh
import numpy as np
from typing import List, Dict, Tuple, Optional
from mathutils import Vector

try:
    from scipy.interpolate import RBFInterpolator
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class RBFInterpolator3D:
    """3D Radial Basis Function interpolator for geological data."""
    
    def __init__(self, kernel: str = 'thin_plate_spline',
                 epsilon: float = 1.0,
                 smoothing: float = 0.0):
        """
        Initialize the RBF interpolator.
        
        Args:
            kernel: RBF kernel function to use
            epsilon: Shape parameter for RBF
            smoothing: Smoothing parameter (0 = exact interpolation)
        """
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy is required for RBF interpolation")
        
        self.kernel = kernel
        self.epsilon = epsilon
        self.smoothing = smoothing
        self.interpolator = None
        self.data_min = None
        self.data_max = None
    
    def fit(self, points: np.ndarray, values: np.ndarray):
        """
        Fit the RBF interpolator to the data.
        
        Args:
            points: Nx3 array of (x, y, z) coordinates
            values: N array of values at those coordinates
        """
        self.data_min = values.min()
        self.data_max = values.max()
        
        # Create RBF interpolator
        self.interpolator = RBFInterpolator(
            points,
            values,
            kernel=self.kernel,
            epsilon=self.epsilon,
            smoothing=self.smoothing
        )
    
    def predict(self, points: np.ndarray) -> np.ndarray:
        """
        Predict values at new points.
        
        Args:
            points: Mx3 array of (x, y, z) coordinates
            
        Returns:
            M array of predicted values
        """
        if self.interpolator is None:
            raise ValueError("Interpolator must be fit before prediction")
        
        return self.interpolator(points)
    
    def create_grid(self, bounds: Tuple[float, float, float, float, float, float],
                   resolution: int = 50) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a regular grid and predict values.
        
        Args:
            bounds: (xmin, xmax, ymin, ymax, zmin, zmax)
            resolution: Grid resolution per axis
            
        Returns:
            Tuple of (grid_points, grid_values)
        """
        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        
        # Create grid
        x = np.linspace(xmin, xmax, resolution)
        y = np.linspace(ymin, ymax, resolution)
        z = np.linspace(zmin, zmax, resolution)
        
        xx, yy, zz = np.meshgrid(x, y, z, indexing='ij')
        grid_points = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
        
        # Predict values
        grid_values = self.predict(grid_points)
        
        return grid_points, grid_values


def extract_sample_data(sample_objects: List[bpy.types.Object],
                       element: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Extract sample positions and element values from Blender objects.
    
    Args:
        sample_objects: List of sample objects
        element: Element name (e.g., 'Cu_pct', 'Au_ppm')
        
    Returns:
        Tuple of (positions array Nx3, values array N)
    """
    positions = []
    values = []
    
    for obj in sample_objects:
        if 'geodb_type' in obj and obj['geodb_type'] == 'sample':
            value_key = f'value_{element}'
            if value_key in obj:
                # Get object center position
                pos = obj.location
                positions.append([pos.x, pos.y, pos.z])
                values.append(obj[value_key])
    
    if not positions:
        raise ValueError(f"No sample objects found with {element} values")
    
    return np.array(positions), np.array(values)


def create_point_cloud(points: np.ndarray, values: np.ndarray,
                      name: str = "PointCloud",
                      threshold_min: Optional[float] = None,
                      threshold_max: Optional[float] = None,
                      point_size: float = 0.1) -> bpy.types.Object:
    """
    Create a point cloud visualization in Blender.
    
    Args:
        points: Nx3 array of point positions
        values: N array of values
        name: Name for the object
        threshold_min: Minimum threshold for filtering
        threshold_max: Maximum threshold for filtering
        point_size: Size of points
        
    Returns:
        Created point cloud object
    """
    # Apply thresholds if specified
    if threshold_min is not None or threshold_max is not None:
        mask = np.ones(len(values), dtype=bool)
        if threshold_min is not None:
            mask &= values >= threshold_min
        if threshold_max is not None:
            mask &= values <= threshold_max
        
        points = points[mask]
        values = values[mask]
    
    # Create mesh
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    
    # Add vertices
    vertices = [Vector(p) for p in points]
    mesh.from_pydata(vertices, [], [])
    mesh.update()
    
    # Add to scene
    bpy.context.collection.objects.link(obj)
    
    # Set display as points
    obj.display_type = 'WIRE'
    
    # Store values as vertex colors
    if not mesh.vertex_colors:
        mesh.vertex_colors.new()
    
    # Tag as geodb visualization
    obj['geodb_visualization'] = True
    obj['geodb_type'] = 'point_cloud'
    
    return obj


def create_isosurface_mesh(points: np.ndarray, values: np.ndarray,
                          resolution: int,
                          threshold: float,
                          name: str = "Isosurface") -> bpy.types.Object:
    """
    Create an isosurface mesh from a 3D grid.
    
    Args:
        points: Nx3 array of grid points
        values: N array of values
        resolution: Grid resolution (assuming cubic grid)
        threshold: Threshold value for the isosurface
        name: Name for the object
        
    Returns:
        Created mesh object
    """
    try:
        from skimage import measure
    except ImportError:
        raise ImportError("scikit-image is required for isosurface generation")
    
    # Reshape values to 3D grid
    grid_values = values.reshape((resolution, resolution, resolution))
    
    # Generate isosurface using marching cubes
    try:
        verts, faces, normals, _ = measure.marching_cubes(
            grid_values,
            level=threshold,
            spacing=(1.0, 1.0, 1.0)
        )
    except Exception as e:
        raise ValueError(f"Failed to generate isosurface: {str(e)}")
    
    # Scale vertices to actual coordinates
    points_reshaped = points.reshape((resolution, resolution, resolution, 3))
    x_range = points_reshaped[-1, 0, 0, 0] - points_reshaped[0, 0, 0, 0]
    y_range = points_reshaped[0, -1, 0, 1] - points_reshaped[0, 0, 0, 1]
    z_range = points_reshaped[0, 0, -1, 2] - points_reshaped[0, 0, 0, 2]
    
    verts[:, 0] = points_reshaped[0, 0, 0, 0] + verts[:, 0] * x_range / resolution
    verts[:, 1] = points_reshaped[0, 0, 0, 1] + verts[:, 1] * y_range / resolution
    verts[:, 2] = points_reshaped[0, 0, 0, 2] + verts[:, 2] * z_range / resolution
    
    # Create mesh
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    
    # Add geometry
    vertices = [Vector(v) for v in verts]
    mesh.from_pydata(vertices, [], faces.tolist())
    mesh.update()
    
    # Calculate normals
    mesh.calc_normals()
    
    # Add to scene
    bpy.context.collection.objects.link(obj)
    
    # Tag as geodb visualization
    obj['geodb_visualization'] = True
    obj['geodb_type'] = 'isosurface'
    obj['geodb_threshold'] = threshold
    
    return obj


def create_volume_mesh(points: np.ndarray, values: np.ndarray,
                      resolution: int,
                      threshold_min: float,
                      threshold_max: float,
                      name: str = "Volume") -> bpy.types.Object:
    """
    Create a volume mesh with color mapping.
    
    Args:
        points: Nx3 array of grid points
        values: N array of values
        resolution: Grid resolution
        threshold_min: Minimum threshold
        threshold_max: Maximum threshold
        name: Name for the object
        
    Returns:
        Created mesh object
    """
    # Filter points by threshold
    mask = (values >= threshold_min) & (values <= threshold_max)
    filtered_points = points[mask]
    filtered_values = values[mask]
    
    if len(filtered_points) == 0:
        raise ValueError("No points within threshold range")
    
    # Create point cloud
    return create_point_cloud(
        filtered_points,
        filtered_values,
        name=name,
        threshold_min=threshold_min,
        threshold_max=threshold_max
    )


def interpolate_from_samples(element: str,
                            kernel: str = 'thin_plate_spline',
                            epsilon: float = 1.0,
                            smoothing: float = 0.0,
                            resolution: int = 50,
                            output_type: str = 'MESH',
                            threshold_min: Optional[float] = None,
                            threshold_max: Optional[float] = None,
                            use_threshold: bool = False) -> bpy.types.Object:
    """
    Create RBF interpolation from sample objects in the scene.
    
    Args:
        element: Element to interpolate
        kernel: RBF kernel function
        epsilon: Shape parameter
        smoothing: Smoothing parameter
        resolution: Grid resolution
        output_type: 'POINTS' or 'MESH'
        threshold_min: Minimum threshold
        threshold_max: Maximum threshold
        use_threshold: Whether to use thresholds
        
    Returns:
        Created visualization object
    """
    # Find all sample objects
    sample_objects = [obj for obj in bpy.data.objects 
                     if 'geodb_type' in obj and obj['geodb_type'] == 'sample']
    
    if not sample_objects:
        raise ValueError("No sample objects found in scene")
    
    # Extract data
    positions, element_values = extract_sample_data(sample_objects, element)
    
    # Create and fit interpolator
    interpolator = RBFInterpolator3D(kernel=kernel, epsilon=epsilon, smoothing=smoothing)
    interpolator.fit(positions, element_values)
    
    # Determine bounds
    bounds = (
        positions[:, 0].min(), positions[:, 0].max(),
        positions[:, 1].min(), positions[:, 1].max(),
        positions[:, 2].min(), positions[:, 2].max()
    )
    
    # Add padding
    padding = 0.1
    x_range = bounds[1] - bounds[0]
    y_range = bounds[3] - bounds[2]
    z_range = bounds[5] - bounds[4]
    
    bounds = (
        bounds[0] - padding * x_range, bounds[1] + padding * x_range,
        bounds[2] - padding * y_range, bounds[3] + padding * y_range,
        bounds[4] - padding * z_range, bounds[5] + padding * z_range
    )
    
    # Create grid and predict
    grid_points, grid_values = interpolator.create_grid(bounds, resolution)
    
    # Apply thresholds if requested
    if use_threshold:
        if threshold_min is None:
            threshold_min = interpolator.data_min
        if threshold_max is None:
            threshold_max = interpolator.data_max
    else:
        threshold_min = None
        threshold_max = None
    
    # Create visualization
    if output_type == 'POINTS':
        obj = create_point_cloud(
            grid_points,
            grid_values,
            name=f"RBF_{element}",
            threshold_min=threshold_min,
            threshold_max=threshold_max
        )
    else:  # MESH
        obj = create_volume_mesh(
            grid_points,
            grid_values,
            resolution,
            threshold_min if threshold_min is not None else interpolator.data_min,
            threshold_max if threshold_max is not None else interpolator.data_max,
            name=f"RBF_{element}"
        )
    
    return obj