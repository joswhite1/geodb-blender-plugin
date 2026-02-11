"""
RBF interpolation module for the geoDB Blender add-on.

This module provides Radial Basis Function interpolation functionality
for creating 3D models from drill hole sample data.
"""

import bpy
import bmesh
import numpy as np
from typing import List, Dict, Tuple, Optional, Any, Union
from mathutils import Vector, Matrix
from dataclasses import dataclass
import math

try:
    from scipy.interpolate import RBFInterpolator
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


# Default number of neighbors for local RBF interpolation
# Setting to None uses global RBF (exact but slow for large datasets)
# Setting to a number (e.g., 50-100) uses local RBF (faster, approximate)
DEFAULT_RBF_NEIGHBORS = None

# Threshold for auto-enabling local RBF (number of sample points)
AUTO_LOCAL_RBF_THRESHOLD = 1000


@dataclass
class SearchEllipsoid:
    """
    Anisotropic search ellipsoid for geological interpolation.

    Defines the search volume and orientation for constraining RBF extrapolation
    based on geological continuity directions (strike, dip, plunge).

    Attributes:
        radius_major: Search distance along major axis (typically along strike)
        radius_semi: Search distance along semi-major axis (typically down-dip)
        radius_minor: Search distance along minor axis (typically across strike)
        azimuth: Rotation around Z axis (0-360°, 0=North, clockwise)
        dip: Rotation around rotated X axis (0-90°, 0=horizontal)
        plunge: Rotation around rotated Y axis (-90 to 90°)
    """
    radius_major: float = 50.0   # Along strike
    radius_semi: float = 30.0    # Down dip
    radius_minor: float = 10.0   # Across strike (narrowest)
    azimuth: float = 0.0         # Degrees, 0=North, clockwise
    dip: float = 0.0             # Degrees, 0=horizontal
    plunge: float = 0.0          # Degrees

    def get_rotation_matrix(self) -> np.ndarray:
        """
        Calculate the 3x3 rotation matrix for the ellipsoid orientation.

        Uses ZXY Euler rotation order (azimuth -> dip -> plunge).

        Returns:
            3x3 numpy rotation matrix
        """
        # Convert to radians
        az = math.radians(self.azimuth)
        dp = math.radians(self.dip)
        pl = math.radians(self.plunge)

        # Rotation matrices
        # Azimuth: rotation around Z (vertical axis)
        Rz = np.array([
            [math.cos(az), -math.sin(az), 0],
            [math.sin(az),  math.cos(az), 0],
            [0,             0,            1]
        ])

        # Dip: rotation around X axis
        Rx = np.array([
            [1, 0,             0],
            [0, math.cos(dp), -math.sin(dp)],
            [0, math.sin(dp),  math.cos(dp)]
        ])

        # Plunge: rotation around Y axis
        Ry = np.array([
            [math.cos(pl),  0, math.sin(pl)],
            [0,             1, 0],
            [-math.sin(pl), 0, math.cos(pl)]
        ])

        # Combined rotation: ZXY order (azimuth first, then dip, then plunge)
        # Matrix multiplication is right-to-left, so Ry @ Rx @ Rz applies Z first
        return Ry @ Rx @ Rz

    def get_transform_matrix(self) -> np.ndarray:
        """
        Get the full transformation matrix that converts world coordinates
        to normalized ellipsoid space where the unit sphere represents the
        search boundary.

        The transform is applied as: points @ T.T
        We want: (1) rotate points to ellipsoid-local axes, (2) scale by 1/radii

        Returns:
            3x3 transformation matrix
        """
        # Scale matrix (normalize by radii)
        S = np.diag([1.0/self.radius_major, 1.0/self.radius_semi, 1.0/self.radius_minor])

        # Inverse rotation matrix to rotate world coords into ellipsoid-local coords
        # For orthogonal rotation matrices, inverse = transpose
        R_inv = self.get_rotation_matrix().T

        # We apply as: points @ T.T
        # So T.T should be: R_inv @ S (rotate first, then scale)
        # Therefore T = (R_inv @ S).T = S.T @ R_inv.T = S @ R
        R = self.get_rotation_matrix()
        return S @ R

    def transform_points(self, points: np.ndarray, center: np.ndarray) -> np.ndarray:
        """
        Transform points from world space to normalized ellipsoid space.

        In ellipsoid space, distance of 1.0 from origin = on ellipsoid surface.

        Args:
            points: Nx3 array of world coordinates
            center: 3-element center point (typically sample location)

        Returns:
            Nx3 array of transformed coordinates
        """
        # Translate to origin at center
        translated = points - center

        # Apply transformation
        T = self.get_transform_matrix()
        return translated @ T.T

    def anisotropic_distance(self, points: np.ndarray, center: np.ndarray) -> np.ndarray:
        """
        Calculate anisotropic distance from center to each point.

        Distance of 1.0 = on ellipsoid surface.
        Distance < 1.0 = inside ellipsoid.
        Distance > 1.0 = outside ellipsoid.

        Args:
            points: Nx3 array of world coordinates
            center: 3-element center point

        Returns:
            N array of anisotropic distances
        """
        transformed = self.transform_points(points, center)
        return np.linalg.norm(transformed, axis=1)

    def get_blender_matrix(self) -> Matrix:
        """
        Get Blender Matrix for visualization positioning.

        Returns:
            4x4 Blender Matrix with rotation and scale
        """
        R = self.get_rotation_matrix()

        # Convert to 4x4 matrix
        mat = Matrix.Identity(4)
        for i in range(3):
            for j in range(3):
                mat[i][j] = R[i, j]

        # Apply scale
        scale_mat = Matrix.Diagonal((self.radius_major, self.radius_semi, self.radius_minor, 1.0))

        return mat @ scale_mat

    def __repr__(self):
        return (f"SearchEllipsoid(radii=({self.radius_major}, {self.radius_semi}, {self.radius_minor}), "
                f"azimuth={self.azimuth}°, dip={self.dip}°, plunge={self.plunge}°)")


def extract_assay_data_from_cache(element: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Extract assay data from the drill data cache for RBF interpolation.

    Args:
        element: Element name to extract (e.g., 'Au', 'Cu', 'Ag')

    Returns:
        Tuple of (positions array Nx3, values array N)
        - positions: XYZ coordinates at the midpoint of each assay interval
        - values: Assay values for the specified element

    Raises:
        ValueError: If cache is empty or no data found for element
    """
    from .data_cache import DrillDataCache

    cache = DrillDataCache.get_cache()
    if cache is None:
        raise ValueError("No drill data cache available. Please import data first.")

    samples_by_hole = cache.get('samples', {})
    if not samples_by_hole:
        raise ValueError("No sample data in cache. Please import drill data first.")

    positions = []
    values = []

    for hole_id, samples in samples_by_hole.items():
        for sample in samples:
            # Get XYZ coordinates (desurveyed from API)
            xyz_from = sample.get('xyz_from')
            xyz_to = sample.get('xyz_to')

            if xyz_from is None or xyz_to is None:
                # Skip samples without coordinates
                continue

            # Calculate midpoint of interval
            mid_x = (xyz_from[0] + xyz_to[0]) / 2.0
            mid_y = (xyz_from[1] + xyz_to[1]) / 2.0
            mid_z = (xyz_from[2] + xyz_to[2]) / 2.0

            # Get assay value for the element
            assay = sample.get('assay')
            if assay is None:
                continue
            elements = assay.get('elements', []) if isinstance(assay, dict) else []

            assay_value = None
            for elem in elements:
                if elem.get('element') == element:
                    try:
                        assay_value = float(elem.get('value', 0))
                    except (ValueError, TypeError):
                        assay_value = None
                    break

            if assay_value is not None:
                positions.append([mid_x, mid_y, mid_z])
                values.append(assay_value)

    if not positions:
        raise ValueError(f"No assay data found for element '{element}'. "
                        f"Make sure data is imported and the element exists.")

    return np.array(positions, dtype=np.float64), np.array(values, dtype=np.float64)


def get_available_assay_configs() -> List[Dict[str, Any]]:
    """
    Get available assay range configurations from the cache.

    Returns:
        List of assay config dictionaries with id, name, element, units
    """
    from .data_cache import DrillDataCache

    cache = DrillDataCache.get_cache()
    if cache is None:
        return []

    return cache.get('assay_range_configs', [])


def get_available_elements() -> List[str]:
    """
    Get list of available elements from the cache.

    Returns:
        List of element names (e.g., ['Au', 'Ag', 'Cu'])
    """
    from .data_cache import DrillDataCache

    cache = DrillDataCache.get_cache()
    if cache is None:
        return []

    return cache.get('available_elements', [])


def interpolate_from_cache(element: str,
                           kernel: str = 'thin_plate_spline',
                           epsilon: float = 1.0,
                           smoothing: float = 0.0,
                           resolution: int = 50,
                           output_type: str = 'POINTS',
                           threshold_min: Optional[float] = None,
                           threshold_max: Optional[float] = None,
                           use_threshold: bool = False,
                           padding: float = 0.1,
                           max_extrapolation_distance: Optional[float] = None,
                           control_points: Optional[List[Tuple[float, float, float, float]]] = None,
                           neighbors: Optional[int] = None,
                           use_distance_decay: bool = False,
                           decay_distance: Optional[float] = None,
                           background_value: float = 0.0,
                           decay_function: str = 'smooth') -> bpy.types.Object:
    """
    Create RBF interpolation from cached assay data.

    Args:
        element: Element to interpolate (e.g., 'Au', 'Cu')
        kernel: RBF kernel function
        epsilon: Shape parameter
        smoothing: Smoothing parameter
        resolution: Grid resolution per axis
        output_type: 'POINTS' or 'MESH'
        threshold_min: Minimum threshold for isosurface (cutoff grade)
        threshold_max: Maximum threshold for filtering output
        use_threshold: Whether to apply thresholds
        padding: Padding factor for bounds (0.1 = 10%)
        max_extrapolation_distance: Maximum distance from samples to extrapolate.
            If None, auto-calculated based on sample spacing.
        control_points: Optional list of (x, y, z, value) tuples for boundary constraints.
            These are additional points with fixed values that constrain the RBF.
            Typically used to prevent extrapolation into empty space.
        neighbors: Number of nearest neighbors for local RBF (faster for large datasets).
            - None: Global RBF (exact, slower)
            - int (e.g., 50-100): Local RBF (approximate, much faster)
            - 'auto': Auto-enable for datasets > 1000 points
        use_distance_decay: If True, apply smooth decay toward background value
            as distance from samples increases. This is more geologically realistic
            than hard cutoffs - grades diminish gradually into unmineralized rock.
        decay_distance: Distance at which values fully decay to background.
            If None, auto-calculated as 3x average sample spacing.
        background_value: Value to decay toward (typically 0 or detection limit).
            Default is 0.0.
        decay_function: Type of decay curve ('linear', 'smooth', 'gaussian').
            - 'linear': Simple linear decay
            - 'smooth': S-curve with no sharp transitions (default, recommended)
            - 'gaussian': Exponential decay (common geostatistical assumption)

    Returns:
        Created visualization object
    """
    # Extract data from cache
    positions, element_values = extract_assay_data_from_cache(element)

    # Store original sample positions for distance masking (before adding control points)
    original_sample_positions = positions.copy()

    print(f"\n{'='*60}")
    print(f"RBF Interpolation for {element}")
    print(f"{'='*60}")
    print(f"INPUT DATA:")
    print(f"  Sample count: {len(positions)}")
    print(f"  Sample value range: {element_values.min():.4f} to {element_values.max():.4f}")
    print(f"  Sample value mean: {element_values.mean():.4f}")
    print(f"  Sample value median: {np.median(element_values):.4f}")

    # Show spatial extent of samples
    print(f"  Sample X range: {positions[:, 0].min():.1f} to {positions[:, 0].max():.1f}")
    print(f"  Sample Y range: {positions[:, 1].min():.1f} to {positions[:, 1].max():.1f}")
    print(f"  Sample Z range: {positions[:, 2].min():.1f} to {positions[:, 2].max():.1f}")

    # Add control points as additional data points for RBF fitting
    if control_points and len(control_points) > 0:
        print(f"\nCONTROL POINTS:")
        print(f"  Number of control points: {len(control_points)}")

        cp_positions = []
        cp_values = []
        for cp in control_points:
            x, y, z, value = cp
            cp_positions.append([x, y, z])
            cp_values.append(value)
            print(f"    Point at ({x:.1f}, {y:.1f}, {z:.1f}) = {value:.4f}")

        cp_positions = np.array(cp_positions, dtype=np.float64)
        cp_values = np.array(cp_values, dtype=np.float64)

        # Concatenate control points with sample data
        positions = np.vstack([positions, cp_positions])
        element_values = np.concatenate([element_values, cp_values])

        print(f"  Total points for RBF: {len(positions)} (samples + control points)")

    # Create and fit interpolator
    interpolator = RBFInterpolator3D(
        kernel=kernel,
        epsilon=epsilon,
        smoothing=smoothing,
        neighbors=neighbors
    )
    interpolator.fit(positions, element_values)

    # Determine bounds from data
    bounds = (
        positions[:, 0].min(), positions[:, 0].max(),
        positions[:, 1].min(), positions[:, 1].max(),
        positions[:, 2].min(), positions[:, 2].max()
    )

    # Add padding
    x_range = bounds[1] - bounds[0]
    y_range = bounds[3] - bounds[2]
    z_range = bounds[5] - bounds[4]

    bounds = (
        bounds[0] - padding * x_range, bounds[1] + padding * x_range,
        bounds[2] - padding * y_range, bounds[3] + padding * y_range,
        bounds[4] - padding * z_range, bounds[5] + padding * z_range
    )

    print(f"\nGRID SETUP:")
    print(f"  Resolution: {resolution}^3 = {resolution**3} points")
    print(f"  Padded bounds: X({bounds[0]:.1f}, {bounds[1]:.1f}) "
          f"Y({bounds[2]:.1f}, {bounds[3]:.1f}) Z({bounds[4]:.1f}, {bounds[5]:.1f})")

    # Create grid and predict
    grid_points, grid_values = interpolator.create_grid(bounds, resolution)

    print(f"\nINTERPOLATED GRID (before decay):")
    print(f"  Grid value range: {grid_values.min():.4f} to {grid_values.max():.4f}")
    print(f"  Grid value mean: {grid_values.mean():.4f}")

    # Apply distance decay if enabled
    # This smoothly blends interpolated values toward background as distance increases
    if use_distance_decay:
        # Auto-calculate decay distance if not provided
        if decay_distance is None:
            from scipy.spatial import cKDTree
            tree = cKDTree(original_sample_positions)
            distances, _ = tree.query(original_sample_positions, k=2)
            avg_spacing = np.mean(distances[:, 1])
            decay_distance = avg_spacing * 3.0
            print(f"\nDISTANCE DECAY (auto):")
            print(f"  Average sample spacing: {avg_spacing:.1f}")
            print(f"  Auto decay distance: {decay_distance:.1f} (3x spacing)")
        else:
            print(f"\nDISTANCE DECAY (user-specified):")
            print(f"  Decay distance: {decay_distance:.1f}")

        # Reshape grid_values for the decay function
        grid_values_3d = grid_values.reshape((resolution, resolution, resolution))

        # Apply the decay
        grid_values_3d = _apply_distance_decay(
            grid_points=grid_points,
            grid_values=grid_values_3d,
            resolution=resolution,
            sample_positions=original_sample_positions,
            decay_distance=decay_distance,
            background_value=background_value,
            decay_function=decay_function
        )

        # Flatten back
        grid_values = grid_values_3d.ravel()

        print(f"\nINTERPOLATED GRID (after decay):")
        print(f"  Grid value range: {grid_values.min():.4f} to {grid_values.max():.4f}")
        print(f"  Grid value mean: {grid_values.mean():.4f}")

    # Show distribution of interpolated values
    percentiles = [10, 25, 50, 75, 90]
    pct_values = np.percentile(grid_values, percentiles)
    print(f"  Grid percentiles: " + ", ".join([f"P{p}={v:.4f}" for p, v in zip(percentiles, pct_values)]))

    # Determine effective threshold for mesh generation
    if output_type == 'MESH':
        if use_threshold and threshold_min is not None:
            effective_threshold = threshold_min
        else:
            # Default: use median of sample values as cutoff
            # This creates an isosurface that roughly divides high/low grade
            effective_threshold = np.median(element_values)
            print(f"\n  WARNING: No threshold specified for MESH output.")
            print(f"  Using median sample value as default cutoff: {effective_threshold:.4f}")
            print(f"  For better results, set 'Use Threshold' and specify a cutoff grade.")

        # Count how many grid points are above threshold
        above_threshold = np.sum(grid_values >= effective_threshold)
        pct_above = 100.0 * above_threshold / len(grid_values)
        print(f"\nISOSURFACE THRESHOLD:")
        print(f"  Threshold (cutoff): {effective_threshold:.4f}")
        print(f"  Grid points >= threshold: {above_threshold} ({pct_above:.1f}%)")

        if pct_above > 90:
            print(f"  WARNING: {pct_above:.0f}% of grid is above threshold - mesh will be very large!")
            print(f"  Consider using a higher threshold value.")
        elif pct_above < 1:
            print(f"  WARNING: Only {pct_above:.1f}% of grid is above threshold - mesh may be very small or empty!")
            print(f"  Consider using a lower threshold value.")
    else:
        effective_threshold = threshold_min

    # Apply thresholds
    if use_threshold:
        if threshold_min is None:
            threshold_min = effective_threshold
        if threshold_max is None:
            threshold_max = interpolator.data_max

    # Calculate extrapolation distance if not provided
    # Default: use average nearest-neighbor distance * 3 as max extrapolation
    # If inf, skip distance limiting entirely
    # If SearchEllipsoid, use anisotropic search
    # NOTE: We use original_sample_positions (not including control points) for distance masking
    # This ensures distance masking is based on actual sample locations
    if output_type == 'MESH':
        if isinstance(max_extrapolation_distance, SearchEllipsoid):
            # Anisotropic search ellipsoid provided
            print(f"\nEXTRAPOLATION CONTROL (Anisotropic):")
            print(f"  Using search ellipsoid for geological continuity")
            print(f"  {max_extrapolation_distance}")
            positions_for_mesh = original_sample_positions
            # max_extrapolation_distance already is the ellipsoid
        elif max_extrapolation_distance is not None and isinstance(max_extrapolation_distance, (int, float)) and np.isinf(max_extrapolation_distance):
            print(f"\nEXTRAPOLATION CONTROL:")
            print(f"  Distance limiting DISABLED - mesh may extend to grid boundaries")
            max_extrapolation_distance = None  # Will skip distance masking in create_volume_mesh
            # Also set sample_positions to None to skip masking
            positions_for_mesh = None
        elif max_extrapolation_distance is None:
            from scipy.spatial import cKDTree
            tree = cKDTree(original_sample_positions)
            # Get distance to 2nd nearest neighbor (1st is itself if k=1, so use k=2)
            distances, _ = tree.query(original_sample_positions, k=2)
            avg_spacing = np.mean(distances[:, 1])  # Second column is distance to nearest neighbor
            max_extrapolation_distance = avg_spacing * 3.0
            print(f"\nEXTRAPOLATION CONTROL (Isotropic):")
            print(f"  Average sample spacing: {avg_spacing:.1f}")
            print(f"  Auto max extrapolation distance: {max_extrapolation_distance:.1f} (3x spacing)")
            positions_for_mesh = original_sample_positions
        else:
            print(f"\nEXTRAPOLATION CONTROL (Isotropic):")
            print(f"  User-specified max extrapolation distance: {max_extrapolation_distance:.1f}")
            positions_for_mesh = original_sample_positions
    else:
        positions_for_mesh = None

    # Create visualization
    if output_type == 'POINTS':
        obj = create_point_cloud(
            grid_points,
            grid_values,
            name=f"RBF_{element}",
            threshold_min=threshold_min if use_threshold else None,
            threshold_max=threshold_max if use_threshold else None
        )
    else:  # MESH
        obj = create_volume_mesh(
            grid_points,
            grid_values,
            resolution,
            effective_threshold,
            threshold_max if threshold_max is not None else interpolator.data_max,
            name=f"RBF_{element}",
            sample_positions=positions_for_mesh,
            max_extrapolation_distance=max_extrapolation_distance
        )

    # Store metadata on the object
    obj['rbf_element'] = element
    obj['rbf_kernel'] = kernel
    obj['rbf_resolution'] = resolution
    obj['rbf_sample_count'] = len(original_sample_positions)
    obj['rbf_control_point_count'] = len(control_points) if control_points else 0

    # Store extrapolation settings
    if isinstance(max_extrapolation_distance, SearchEllipsoid):
        obj['rbf_search_type'] = 'anisotropic'
        obj['rbf_ellipsoid_major'] = max_extrapolation_distance.radius_major
        obj['rbf_ellipsoid_semi'] = max_extrapolation_distance.radius_semi
        obj['rbf_ellipsoid_minor'] = max_extrapolation_distance.radius_minor
        obj['rbf_ellipsoid_azimuth'] = max_extrapolation_distance.azimuth
        obj['rbf_ellipsoid_dip'] = max_extrapolation_distance.dip
        obj['rbf_ellipsoid_plunge'] = max_extrapolation_distance.plunge
    elif max_extrapolation_distance is not None:
        obj['rbf_search_type'] = 'isotropic'
        obj['rbf_max_extrapolation'] = max_extrapolation_distance
    else:
        obj['rbf_search_type'] = 'none'

    print(f"\n{'='*60}")
    print(f"RBF Interpolation complete")
    print(f"{'='*60}\n")

    return obj


class RBFInterpolator3D:
    """
    3D Radial Basis Function interpolator for geological data.

    For datasets > 1000 points, consider using the neighbors parameter
    (e.g., neighbors=50) for local RBF approximation which is much faster.
    """

    def __init__(self, kernel: str = 'thin_plate_spline',
                 epsilon: float = 1.0,
                 smoothing: float = 0.0,
                 neighbors: Optional[int] = None):
        """
        Initialize the RBF interpolator.

        Args:
            kernel: RBF kernel function to use. Options:
                - 'thin_plate_spline' (default, recommended)
                - 'linear', 'cubic', 'quintic'
                - 'multiquadric', 'inverse_multiquadric', 'inverse_quadratic'
                - 'gaussian'
            epsilon: Shape parameter for RBF (used by some kernels)
            smoothing: Smoothing parameter (0 = exact interpolation)
            neighbors: Number of nearest neighbors for local RBF interpolation.
                - None: Global RBF (exact, O(n³) complexity)
                - int (e.g., 50-100): Local RBF using only nearest neighbors
                  (approximate but much faster for large datasets)
                - 'auto': Automatically enable local RBF for datasets > 1000 points
        """
        self.kernel = kernel
        self.epsilon = epsilon
        self.smoothing = smoothing
        self.neighbors = neighbors
        self.interpolator = None
        self.data_min = None
        self.data_max = None

    def _get_neighbors(self, n_points: int) -> Optional[int]:
        """Determine the neighbors parameter to use."""
        if self.neighbors == 'auto':
            if n_points > AUTO_LOCAL_RBF_THRESHOLD:
                # Use ~5% of points or 100, whichever is larger
                return max(100, n_points // 20)
            return None
        return self.neighbors

    def fit(self, points: np.ndarray, values: np.ndarray):
        """
        Fit the RBF interpolator to the data.

        Args:
            points: Nx3 array of (x, y, z) coordinates
            values: N array of values at those coordinates
        """
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy is required for RBF interpolation")

        self.data_min = values.min()
        self.data_max = values.max()
        n_points = len(points)

        neighbors = self._get_neighbors(n_points)

        # Build kwargs for RBFInterpolator
        kwargs = {
            'kernel': self.kernel,
            'epsilon': self.epsilon,
            'smoothing': self.smoothing
        }

        # Add neighbors parameter if specified (enables local RBF)
        if neighbors is not None:
            kwargs['neighbors'] = neighbors
            print(f"  Using local RBF with {neighbors} neighbors (faster approximation)")
        else:
            print(f"  Using global RBF (exact interpolation)")

        print(f"  {n_points} sample points")

        self.interpolator = RBFInterpolator(points, values, **kwargs)

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
    
    # Scale vertices from grid indices to actual coordinates
    # marching_cubes outputs vertices in grid index space (0 to resolution-1)
    verts[:, 0] = points_reshaped[0, 0, 0, 0] + verts[:, 0] * x_range / (resolution - 1)
    verts[:, 1] = points_reshaped[0, 0, 0, 1] + verts[:, 1] * y_range / (resolution - 1)
    verts[:, 2] = points_reshaped[0, 0, 0, 2] + verts[:, 2] * z_range / (resolution - 1)
    
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
                      name: str = "Volume",
                      ensure_watertight: bool = True,
                      sample_positions: Optional[np.ndarray] = None,
                      max_extrapolation_distance: Optional[float] = None) -> bpy.types.Object:
    """
    Create a watertight volume mesh using marching cubes isosurface.

    This creates an enclosed 3D mesh that defines the boundary where values
    equal threshold_min. The mesh is watertight (closed) by padding the grid
    with values below the threshold, ensuring the isosurface closes before
    reaching the grid boundary.

    This is similar to how Leapfrog and other implicit modeling software
    generate mineral domain surfaces.

    Args:
        points: Nx3 array of grid points
        values: N array of values
        resolution: Grid resolution
        threshold_min: Threshold value for the isosurface (values >= this are inside)
        threshold_max: Maximum threshold (used for metadata)
        name: Name for the object
        ensure_watertight: If True, pad grid to ensure closed mesh (default True)
        sample_positions: Optional Nx3 array of original sample positions for distance masking
        max_extrapolation_distance: If provided with sample_positions, mask out grid points
            further than this distance from any sample (constrains extrapolation)

    Returns:
        Created mesh object
    """
    try:
        from skimage import measure
    except ImportError:
        raise ImportError("scikit-image is required for volume mesh generation. "
                         "Install it with: pip install scikit-image")

    print(f"\nMESH GENERATION:")
    print(f"  Grid resolution: {resolution}^3")
    print(f"  Threshold (cutoff grade): {threshold_min:.4f}")

    # Reshape values to 3D grid
    grid_values = values.reshape((resolution, resolution, resolution))

    # Check if the threshold intersects the data range
    val_min, val_max = values.min(), values.max()
    print(f"  Grid value range: {val_min:.4f} to {val_max:.4f}")

    if threshold_min > val_max:
        # Cutoff is above all data - no mesh should be generated
        raise ValueError(
            f"Cannot generate mesh: Cutoff grade ({threshold_min:.4f}) is above all interpolated values.\n"
            f"  Data range: {val_min:.4f} to {val_max:.4f}\n"
            f"  Suggested threshold range: {val_min:.4f} to {val_max:.4f}\n"
            f"  Try lowering your cutoff grade to a value within this range."
        )
    elif threshold_min < val_min:
        # Cutoff is below all data - entire volume would be "ore"
        print(f"  WARNING: Threshold ({threshold_min:.4f}) is below all data values.")
        print(f"  The entire interpolated volume will be enclosed in the mesh.")
        print(f"  Suggested threshold range: {val_min:.4f} to {val_max:.4f}")

    # Apply distance-based masking if sample positions provided
    if sample_positions is not None and max_extrapolation_distance is not None:
        if isinstance(max_extrapolation_distance, SearchEllipsoid):
            print(f"  Applying anisotropic distance mask: {max_extrapolation_distance}")
        else:
            print(f"  Applying distance mask (max extrapolation: {max_extrapolation_distance:.1f})")
        grid_values = _apply_distance_mask(
            points, grid_values, resolution,
            sample_positions, max_extrapolation_distance,
            mask_value=val_min - abs(val_max - val_min)  # Set masked areas below threshold
        )
        # Recalculate stats after masking
        masked_above = np.sum(grid_values >= threshold_min)
        print(f"  Grid points >= threshold after masking: {masked_above} ({100*masked_above/grid_values.size:.1f}%)")

    # Get coordinate bounds from the original grid
    points_reshaped = points.reshape((resolution, resolution, resolution, 3))
    x_min, x_max = points_reshaped[0, 0, 0, 0], points_reshaped[-1, 0, 0, 0]
    y_min, y_max = points_reshaped[0, 0, 0, 1], points_reshaped[0, -1, 0, 1]
    z_min, z_max = points_reshaped[0, 0, 0, 2], points_reshaped[0, 0, -1, 2]

    print(f"  Grid bounds: X({x_min:.1f} to {x_max:.1f}), Y({y_min:.1f} to {y_max:.1f}), Z({z_min:.1f} to {z_max:.1f})")

    if ensure_watertight:
        # Pad the grid with values below threshold to ensure watertight mesh.
        # This ensures the isosurface closes before hitting the grid boundary,
        # creating an enclosed volume rather than an open surface.
        pad_value = val_min - abs(val_max - val_min) * 0.5  # Value well below threshold
        print(f"  Padding grid for watertight mesh (pad value: {pad_value:.4f})")

        grid_values_padded = np.pad(
            grid_values,
            pad_width=1,
            mode='constant',
            constant_values=pad_value
        )
        padded_resolution = resolution + 2

        # Adjust coordinate bounds to account for padding
        # Each pad cell extends the grid by one cell width
        x_step = (x_max - x_min) / (resolution - 1) if resolution > 1 else 1.0
        y_step = (y_max - y_min) / (resolution - 1) if resolution > 1 else 1.0
        z_step = (z_max - z_min) / (resolution - 1) if resolution > 1 else 1.0

        x_min_padded = x_min - x_step
        x_max_padded = x_max + x_step
        y_min_padded = y_min - y_step
        y_max_padded = y_max + y_step
        z_min_padded = z_min - z_step
        z_max_padded = z_max + z_step

        work_grid = grid_values_padded
        work_resolution = padded_resolution
        work_bounds = (x_min_padded, x_max_padded, y_min_padded, y_max_padded, z_min_padded, z_max_padded)
    else:
        work_grid = grid_values
        work_resolution = resolution
        work_bounds = (x_min, x_max, y_min, y_max, z_min, z_max)

    # Debug: Check how much of the working grid is above threshold
    work_above = np.sum(work_grid >= threshold_min)
    work_total = work_grid.size
    print(f"  Working grid: {work_above}/{work_total} points >= threshold ({100*work_above/work_total:.1f}%)")

    # Generate isosurface using marching cubes
    try:
        verts, faces, normals, _ = measure.marching_cubes(
            work_grid,
            level=threshold_min,
            spacing=(1.0, 1.0, 1.0)
        )
    except Exception as e:
        raise ValueError(f"Failed to generate isosurface at threshold {threshold_min}: {str(e)}. "
                        f"Data range is [{val_min:.4f}, {val_max:.4f}]")

    if len(verts) == 0:
        raise ValueError(f"No surface generated at threshold {threshold_min}. "
                        f"Try adjusting the threshold within data range [{val_min:.4f}, {val_max:.4f}]")

    # Scale vertices to actual coordinates
    x_min_w, x_max_w, y_min_w, y_max_w, z_min_w, z_max_w = work_bounds
    x_range = x_max_w - x_min_w
    y_range = y_max_w - y_min_w
    z_range = z_max_w - z_min_w

    # Scale vertices from grid indices to actual coordinates
    # marching_cubes outputs vertices in grid index space (0 to resolution-1)
    verts_scaled = np.zeros_like(verts)
    verts_scaled[:, 0] = x_min_w + verts[:, 0] * x_range / (work_resolution - 1)
    verts_scaled[:, 1] = y_min_w + verts[:, 1] * y_range / (work_resolution - 1)
    verts_scaled[:, 2] = z_min_w + verts[:, 2] * z_range / (work_resolution - 1)

    # Create mesh
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)

    # Add geometry
    # NOTE: marching_cubes returns faces with normals pointing from high values toward low values.
    # This is correct for geological grade shells - the surface encloses high-grade zones
    # with normals pointing outward (toward lower grades).
    vertices = [Vector(v) for v in verts_scaled]
    mesh.from_pydata(vertices, [], faces.tolist())
    mesh.update()

    # Add to scene
    bpy.context.collection.objects.link(obj)

    # Add smooth shading
    for poly in mesh.polygons:
        poly.use_smooth = True

    # Check if mesh is watertight (for informational purposes)
    is_watertight = _check_mesh_watertight(mesh)

    # Tag as geodb visualization
    obj['geodb_visualization'] = True
    obj['geodb_type'] = 'volume_mesh'
    obj['geodb_threshold_min'] = threshold_min
    obj['geodb_threshold_max'] = threshold_max
    obj['geodb_vertex_count'] = len(verts)
    obj['geodb_face_count'] = len(faces)
    obj['geodb_watertight'] = is_watertight

    status = "watertight" if is_watertight else "open (has boundary edges)"
    print(f"  Created volume mesh: {len(verts)} vertices, {len(faces)} faces - {status}")

    return obj


def _apply_distance_mask(grid_points: np.ndarray,
                         grid_values: np.ndarray,
                         resolution: int,
                         sample_positions: np.ndarray,
                         max_distance: Union[float, SearchEllipsoid],
                         mask_value: float) -> np.ndarray:
    """
    Mask grid values that are too far from any sample point.

    This constrains the RBF extrapolation to stay within a reasonable
    distance of the actual data, preventing runaway values in areas
    with no samples.

    Supports both isotropic (spherical) and anisotropic (ellipsoidal) search.

    Args:
        grid_points: Nx3 array of grid points (flat)
        grid_values: 3D array of grid values (resolution^3)
        resolution: Grid resolution
        sample_positions: Mx3 array of sample positions
        max_distance: Either a float for isotropic distance, or a SearchEllipsoid
            for anisotropic search. For ellipsoid, distance of 1.0 = on surface.
        mask_value: Value to assign to masked grid points

    Returns:
        Modified grid_values array with distant points masked
    """
    grid_values_flat = grid_values.ravel().copy()

    if isinstance(max_distance, SearchEllipsoid):
        # Anisotropic search using ellipsoid
        ellipsoid = max_distance
        print(f"    Using anisotropic search ellipsoid:")
        print(f"      Radii: major={ellipsoid.radius_major}, semi={ellipsoid.radius_semi}, minor={ellipsoid.radius_minor}")
        print(f"      Orientation: azimuth={ellipsoid.azimuth}°, dip={ellipsoid.dip}°, plunge={ellipsoid.plunge}°")

        # For each grid point, find minimum anisotropic distance to any sample
        min_distances = _compute_anisotropic_distances(grid_points, sample_positions, ellipsoid)

        # Mask points where minimum distance > 1.0 (outside all sample ellipsoids)
        mask = min_distances > 1.0

    else:
        # Isotropic search using KD-tree (faster)
        from scipy.spatial import cKDTree

        # Build KD-tree of sample positions for fast nearest-neighbor lookup
        tree = cKDTree(sample_positions)

        # Find distance to nearest sample for each grid point
        distances, _ = tree.query(grid_points, k=1)

        # Create mask for points beyond max distance
        mask = distances > max_distance

    # Apply mask to grid values
    grid_values_flat[mask] = mask_value

    masked_count = np.sum(mask)
    print(f"    Distance mask: {masked_count}/{len(mask)} points masked ({100*masked_count/len(mask):.1f}%)")

    return grid_values_flat.reshape((resolution, resolution, resolution))


def _compute_anisotropic_distances(grid_points: np.ndarray,
                                    sample_positions: np.ndarray,
                                    ellipsoid: SearchEllipsoid) -> np.ndarray:
    """
    Compute minimum anisotropic distance from each grid point to any sample.

    For each grid point, we check if it falls within an ellipsoid centered
    at any sample point. The ellipsoid shape/orientation is defined by the
    SearchEllipsoid, and its radii define the search distance in each direction.

    Args:
        grid_points: Nx3 array of grid points
        sample_positions: Mx3 array of sample positions
        ellipsoid: Search ellipsoid defining anisotropy

    Returns:
        N array of minimum anisotropic distances (1.0 = on ellipsoid surface)
    """
    from scipy.spatial import cKDTree

    # Get transformation matrix (rotation only, no scaling)
    # We want to rotate points to align with ellipsoid axes
    R_inv = ellipsoid.get_rotation_matrix().T  # Inverse rotation

    # Scale factors for each axis (to normalize ellipsoid to unit sphere)
    scale = np.array([1.0/ellipsoid.radius_major,
                      1.0/ellipsoid.radius_semi,
                      1.0/ellipsoid.radius_minor])

    # Transform sample positions: rotate to ellipsoid-aligned space, then scale
    samples_rotated = sample_positions @ R_inv.T
    samples_transformed = samples_rotated * scale

    # Transform grid points the same way
    grid_rotated = grid_points @ R_inv.T
    grid_transformed = grid_rotated * scale

    # Build KD-tree in transformed space
    tree = cKDTree(samples_transformed)

    # Find distance to nearest sample in transformed space
    # In this space, distance of 1.0 = on original ellipsoid surface
    distances, _ = tree.query(grid_transformed, k=1)

    return distances


def _apply_distance_decay(grid_points: np.ndarray,
                          grid_values: np.ndarray,
                          resolution: int,
                          sample_positions: np.ndarray,
                          decay_distance: float,
                          background_value: float = 0.0,
                          decay_function: str = 'linear') -> np.ndarray:
    """
    Apply smooth distance-based decay toward a background value.

    Unlike hard masking, this smoothly blends interpolated values toward
    a background value as distance from samples increases. This is more
    geologically realistic - grades should diminish away from mineralized
    zones rather than abruptly cut off.

    The decay formula is:
        final_value = background + (interpolated - background) * decay_factor

    Where decay_factor transitions from 1.0 (at samples) to 0.0 (at decay_distance).

    Args:
        grid_points: Nx3 array of grid points (flat)
        grid_values: 3D array of interpolated grid values (resolution^3)
        resolution: Grid resolution
        sample_positions: Mx3 array of sample positions
        decay_distance: Distance at which values fully decay to background.
            - At distance 0: decay_factor = 1.0 (full interpolated value)
            - At distance >= decay_distance: decay_factor = 0.0 (background value)
        background_value: The value to decay toward (typically 0 or detection limit)
        decay_function: Type of decay curve:
            - 'linear': Linear decay (simple, fast)
            - 'smooth': Smooth cosine-based decay (no sharp transitions)
            - 'gaussian': Gaussian decay (geologically common assumption)

    Returns:
        Modified grid_values array with distance decay applied

    Example:
        If a grid point is at distance d from the nearest sample:
        - d = 0: value unchanged
        - d = decay_distance/2: value halfway between interpolated and background
        - d >= decay_distance: value = background_value

    Note:
        This is an improvement over commercial software like Leapfrog which
        typically uses hard spatial cutoffs. Smooth decay better represents
        the geological reality that mineralization grades diminish gradually
        into unmineralized host rock.
    """
    from scipy.spatial import cKDTree

    grid_values_flat = grid_values.ravel().copy()

    # Build KD-tree of sample positions for fast nearest-neighbor lookup
    tree = cKDTree(sample_positions)

    # Find distance to nearest sample for each grid point
    distances, _ = tree.query(grid_points, k=1)

    # Calculate decay factor based on distance
    # Normalized distance: 0 at sample, 1 at decay_distance
    normalized_dist = np.clip(distances / decay_distance, 0.0, 1.0)

    if decay_function == 'linear':
        # Linear decay: factor goes from 1 to 0 linearly
        decay_factor = 1.0 - normalized_dist

    elif decay_function == 'smooth':
        # Smooth cosine-based decay (S-curve, no sharp transitions)
        # Uses smoothstep-like function: 3x² - 2x³
        # This has zero derivative at both ends for smooth transitions
        decay_factor = 1.0 - (3 * normalized_dist**2 - 2 * normalized_dist**3)

    elif decay_function == 'gaussian':
        # Gaussian decay: exponential falloff (common in geostatistics)
        # At normalized_dist = 1, factor ≈ 0.05 (not quite zero)
        # Scale so that at decay_distance, we're at ~5% of original
        decay_factor = np.exp(-3.0 * normalized_dist**2)

    else:
        raise ValueError(f"Unknown decay function: {decay_function}. "
                        f"Use 'linear', 'smooth', or 'gaussian'.")

    # Apply decay: blend interpolated values toward background
    # final = background + (interpolated - background) * decay_factor
    grid_values_flat = background_value + (grid_values_flat - background_value) * decay_factor

    # Statistics for logging
    fully_decayed = np.sum(normalized_dist >= 1.0)
    partially_decayed = np.sum((normalized_dist > 0) & (normalized_dist < 1.0))
    print(f"    Distance decay ({decay_function}):")
    print(f"      Decay distance: {decay_distance:.1f}")
    print(f"      Background value: {background_value:.4f}")
    print(f"      Grid points at full value: {len(distances) - fully_decayed - partially_decayed}")
    print(f"      Grid points partially decayed: {partially_decayed}")
    print(f"      Grid points at background: {fully_decayed}")

    return grid_values_flat.reshape((resolution, resolution, resolution))


def _check_mesh_watertight(mesh: bpy.types.Mesh) -> bool:
    """
    Check if a mesh is watertight (has no boundary edges).

    A watertight mesh has every edge shared by exactly 2 faces.

    Args:
        mesh: Blender mesh to check

    Returns:
        True if watertight, False if has open edges
    """
    # Use bmesh for edge analysis
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.edges.ensure_lookup_table()

    # Check for boundary edges (edges with only one adjacent face)
    boundary_edges = [e for e in bm.edges if e.is_boundary]
    is_watertight = len(boundary_edges) == 0

    bm.free()
    return is_watertight


def create_ellipsoid_visualization(ellipsoid: SearchEllipsoid,
                                   location: Tuple[float, float, float] = (0, 0, 0),
                                   name: str = "SearchEllipsoid",
                                   segments: int = 32,
                                   rings: int = 16,
                                   wireframe: bool = True,
                                   color: Tuple[float, float, float, float] = (0.2, 0.8, 0.2, 0.3)) -> bpy.types.Object:
    """
    Create a visual representation of the search ellipsoid in Blender.

    This helps users visualize and adjust the anisotropic search parameters.
    The ellipsoid can be positioned at any location (e.g., centroid of samples).

    Args:
        ellipsoid: SearchEllipsoid defining the shape and orientation
        location: Center location (x, y, z) for the ellipsoid
        name: Name for the Blender object
        segments: Number of segments around the circumference
        rings: Number of rings from pole to pole
        wireframe: If True, display as wireframe; if False, display as solid
        color: RGBA color for the visualization material

    Returns:
        Created Blender object
    """
    # Create UV sphere mesh
    bm = bmesh.new()

    # Generate sphere vertices and faces
    bmesh.ops.create_uvsphere(
        bm,
        u_segments=segments,
        v_segments=rings,
        radius=1.0
    )

    # Create mesh and object
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)

    # Apply ellipsoid transformation (scale by radii, then rotate)
    # First set location
    obj.location = Vector(location)

    # Apply scale (radii)
    obj.scale = (ellipsoid.radius_major, ellipsoid.radius_semi, ellipsoid.radius_minor)

    # Apply rotation (convert degrees to radians)
    obj.rotation_euler = (
        math.radians(ellipsoid.dip),      # X rotation (dip)
        math.radians(ellipsoid.plunge),   # Y rotation (plunge)
        math.radians(ellipsoid.azimuth)   # Z rotation (azimuth)
    )
    obj.rotation_mode = 'ZXY'  # Match our rotation order

    # Add to scene
    bpy.context.collection.objects.link(obj)

    # Create material for visualization
    mat_name = f"{name}_Material"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    mat.use_nodes = True
    mat.blend_method = 'BLEND'

    # Set up material nodes for transparency
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Create shader nodes
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')

    # Set color and transparency
    bsdf_node.inputs['Base Color'].default_value = color[:3] + (1.0,)
    bsdf_node.inputs['Alpha'].default_value = color[3]

    # Link nodes
    links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])

    # Position nodes
    output_node.location = (300, 0)
    bsdf_node.location = (0, 0)

    # Assign material to object
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    # Set display mode
    if wireframe:
        obj.display_type = 'WIRE'
    else:
        obj.display_type = 'SOLID'

    # Tag as geodb visualization
    obj['geodb_visualization'] = True
    obj['geodb_type'] = 'search_ellipsoid'
    obj['ellipsoid_radius_major'] = ellipsoid.radius_major
    obj['ellipsoid_radius_semi'] = ellipsoid.radius_semi
    obj['ellipsoid_radius_minor'] = ellipsoid.radius_minor
    obj['ellipsoid_azimuth'] = ellipsoid.azimuth
    obj['ellipsoid_dip'] = ellipsoid.dip
    obj['ellipsoid_plunge'] = ellipsoid.plunge

    print(f"  Created search ellipsoid visualization: {name}")
    print(f"    Location: ({location[0]:.1f}, {location[1]:.1f}, {location[2]:.1f})")
    print(f"    Radii: major={ellipsoid.radius_major}, semi={ellipsoid.radius_semi}, minor={ellipsoid.radius_minor}")
    print(f"    Orientation: azimuth={ellipsoid.azimuth}°, dip={ellipsoid.dip}°, plunge={ellipsoid.plunge}°")

    return obj


def update_ellipsoid_from_object(obj: bpy.types.Object) -> Optional[SearchEllipsoid]:
    """
    Extract SearchEllipsoid parameters from a Blender ellipsoid visualization object.

    This allows users to interactively adjust the ellipsoid in the viewport
    and then use those parameters for interpolation.

    Args:
        obj: Blender object (should be a search ellipsoid visualization)

    Returns:
        SearchEllipsoid with parameters from the object, or None if invalid
    """
    if obj.get('geodb_type') != 'search_ellipsoid':
        return None

    # Get radii from scale
    radius_major = obj.scale[0]
    radius_semi = obj.scale[1]
    radius_minor = obj.scale[2]

    # Get rotation (convert radians to degrees)
    # Note: rotation_euler order should match our ZXY convention
    obj.rotation_mode = 'ZXY'
    azimuth = math.degrees(obj.rotation_euler[2])
    dip = math.degrees(obj.rotation_euler[0])
    plunge = math.degrees(obj.rotation_euler[1])

    return SearchEllipsoid(
        radius_major=radius_major,
        radius_semi=radius_semi,
        radius_minor=radius_minor,
        azimuth=azimuth,
        dip=dip,
        plunge=plunge
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