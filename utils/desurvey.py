"""
Drill hole desurvey utilities for the geoDB Blender add-on.

This module provides functions and classes for desurvey calculations
using the minimum curvature method to compute 3D coordinates along
drill holes.
"""

import numpy as np
import bpy
from mathutils import Vector

def desurvey_minimum_curvature(collar, surveys, target_depth):
    """
    Desurvey a drillhole using the minimum curvature method to compute XYZ at a single target depth.
    
    Args:
        collar: tuple (x, y, z, total_depth)
            - x, y, z: float, collar coordinates (e.g., easting, northing, elevation in meters)
            - total_depth: float, maximum depth of the hole (meters)
            - Example: (1000.0, 1000.0, 0.0, 200.0)
        surveys: list of tuples [(azimuth, dip, depth), ...]
            - azimuth: float, degrees (0-360, 0 = north, 90 = east)
            - dip: float, degrees (0 = vertical, -90 = straight down, positive = upward)
            - depth: float, measured depth along hole (meters, increasing)
            - Example: [(0.0, 0.0, 50.0), (45.0, -10.0, 100.0), (45.0, -20.0, 150.0)]
        target_depth: float, depth to compute XYZ (meters, 0 to total_depth)
            - Example: 75.0
    
    Returns:
        tuple (x, y, z): Coordinates at target depth
    """
    x0, y0, z0, _ = collar
    
    def to_radians(deg):
        return np.radians(deg)
    
    survey_depths = [0.0] + [s[2] for s in surveys]
    azimuths = [to_radians(s[0]) for s in surveys]
    dips = [to_radians(90 + s[1]) for s in surveys]
    
    max_depth = survey_depths[-1]
    if target_depth < 0 or target_depth > max_depth:
        raise ValueError(f"Target depth {target_depth} outside valid range [0, {max_depth}]")
    
    for i in range(len(survey_depths) - 1):
        if survey_depths[i] <= target_depth <= survey_depths[i + 1]:
            depth1, depth2 = survey_depths[i], survey_depths[i + 1]
            if i == 0:
                az1, dip1 = azimuths[0], dips[0]
                az2, dip2 = azimuths[0], dips[0]
            else:
                az1, dip1 = azimuths[i - 1], dips[i - 1]
                az2, dip2 = azimuths[i], dips[i]
            break
    else:
        depth1, depth2 = survey_depths[-2], survey_depths[-1]
        az1, dip1 = azimuths[-2], dips[-2]
        az2, dip2 = azimuths[-1], dips[-1]
    
    interval_length = depth2 - depth1
    if interval_length == 0:
        raise ValueError("Survey depths must be distinct")
    beta = (target_depth - depth1) / interval_length
    
    cos_dl = np.sin(dip1) * np.sin(dip2) * np.cos(az1 - az2) + np.cos(dip1) * np.cos(dip2)
    cos_dl = np.clip(cos_dl, -1.0, 1.0)
    dl = np.arccos(cos_dl)
    rf = 1.0 if dl == 0 else 2.0 * np.tan(dl / 2.0) / dl
    
    dx1 = np.sin(dip1) * np.sin(az1)
    dy1 = np.sin(dip1) * np.cos(az1)
    dz1 = -np.cos(dip1)  # Negate so drilling down produces negative z
    dx2 = np.sin(dip2) * np.sin(az2)
    dy2 = np.sin(dip2) * np.cos(az2)
    dz2 = -np.cos(dip2)  # Negate so drilling down produces negative z

    disp = interval_length * rf / 2.0
    dx = disp * ((1 - beta) * dx1 + beta * dx2)
    dy = disp * ((1 - beta) * dy1 + beta * dy2)
    dz = disp * ((1 - beta) * dz1 + beta * dz2)

    x, y, z = x0, y0, z0
    for j in range(i):
        d1, d2 = survey_depths[j], survey_depths[j + 1]
        az1, dip1 = azimuths[j], dips[j]
        az2, dip2 = azimuths[j], dips[j]
        if j > 0:
            az1, dip1 = azimuths[j - 1], dips[j - 1]

        cos_dl = np.sin(dip1) * np.sin(dip2) * np.cos(az1 - az2) + np.cos(dip1) * np.cos(dip2)
        cos_dl = np.clip(cos_dl, -1.0, 1.0)
        dl = np.arccos(cos_dl)
        rf = 1.0 if dl == 0 else 2.0 * np.tan(dl / 2.0) / dl

        dx1 = np.sin(dip1) * np.sin(az1)
        dy1 = np.sin(dip1) * np.cos(az1)
        dz1 = -np.cos(dip1)  # Negate so drilling down produces negative z
        dx2 = np.sin(dip2) * np.sin(az2)
        dy2 = np.sin(dip2) * np.cos(az2)
        dz2 = -np.cos(dip2)  # Negate so drilling down produces negative z

        disp = (d2 - d1) * rf / 2.0
        x += disp * (dx1 + dx2)
        y += disp * (dy1 + dy2)
        z += disp * (dz1 + dz2)
    
    x += dx
    y += dy
    z += dz
    
    return x, y, z

class DrillholeDesurvey:
    """
    Desurvey a drillhole using minimum curvature for multiple depths efficiently.
    
    Args:
        collar: tuple (x, y, z, total_depth)
            - x, y, z: float, collar coordinates (e.g., easting, northing, elevation in meters)
            - total_depth: float, maximum depth of the hole (meters)
            - Example: (1000.0, 1000.0, 0.0, 200.0)
        surveys: list of tuples [(azimuth, dip, depth), ...]
            - azimuth: float, degrees (0-360, 0 = north, 90 = east)
            - dip: float, degrees (0 = vertical, -90 = straight down, positive = upward)
            - depth: float, measured depth along hole (meters, increasing)
            - Example: [(0.0, 0.0, 50.0), (45.0, -10.0, 100.0), (45.0, -20.0, 150.0)]
    """
    def __init__(self, collar, surveys):
        self.x0, self.y0, self.z0, self.max_depth = collar
        self.surveys = np.array(surveys, dtype=float)
        
        self.survey_depths = np.concatenate(([0.0], self.surveys[:, 2]))
        if not np.all(np.diff(self.survey_depths) > 0):
            raise ValueError("Survey depths must be strictly increasing")
        if self.max_depth < self.survey_depths[-1]:
            raise ValueError("Collar total depth must be >= maximum survey depth")
        
        self.n_surveys = len(surveys)
        self.azimuths = np.radians(self.surveys[:, 0])
        self.dips = np.radians(90 + self.surveys[:, 1])
        
        self.dx = np.sin(self.dips) * np.sin(self.azimuths)
        self.dy = np.sin(self.dips) * np.cos(self.azimuths)
        # Negate dz so that drilling down (negative dip) produces negative z
        self.dz = -np.cos(self.dips)
        
        self.doglegs = np.zeros(self.n_surveys)
        self.rf = np.ones(self.n_surveys)
        self.interval_lengths = np.diff(self.survey_depths)
        
        for i in range(self.n_surveys):
            dx1, dy1, dz1 = (self.dx[0], self.dy[0], self.dz[0]) if i == 0 else (self.dx[i-1], self.dy[i-1], self.dz[i-1])
            dx2, dy2, dz2 = self.dx[i], self.dy[i], self.dz[i]
            
            cos_dl = dx1 * dx2 + dy1 * dy2 + dz1 * dz2
            cos_dl = np.clip(cos_dl, -1.0, 1.0)
            dl = np.arccos(cos_dl)
            self.doglegs[i] = dl
            self.rf[i] = 1.0 if dl == 0 else 2.0 * np.tan(dl / 2.0) / dl
    
    def desurvey_batch(self, target_depths, method="minimum_curvature"):
        """
        Compute XYZ coordinates for multiple target depths using specified method.
        
        Args:
            target_depths: array-like of floats, depths to compute XYZ
                - Example: np.linspace(0, 150, 40000) or [10.0, 20.0, 30.0]
            method: Desurvey method to use:
                - "minimum_curvature": Industry standard (default)
                - "tangential": Tangential method
                - "average_angle": Average angle method
                - "radius_curvature": Radius of curvature method
        
        Returns:
            np.ndarray: Shape (len(target_depths), 3) with [x, y, z] coordinates
        """
        valid_methods = {"minimum_curvature", "tangential", "average_angle", "radius_curvature"}
        if method not in valid_methods:
            raise ValueError(f"Method must be one of {valid_methods}")
        
        target_depths = np.asarray(target_depths, dtype=float)
        if np.any((target_depths < 0) | (target_depths > self.max_depth)):
            raise ValueError(f"Target depths must be in [0, {self.max_depth}]")
        
        coords = np.zeros((len(target_depths), 3))
        coords[:, 0] = self.x0
        coords[:, 1] = self.y0
        coords[:, 2] = self.z0
        
        intervals = np.searchsorted(self.survey_depths, target_depths, side='right') - 1
        intervals = np.clip(intervals, 0, self.n_surveys - 1)
        
        depth1 = self.survey_depths[intervals]
        depth2 = self.survey_depths[intervals + 1]
        beta = (target_depths - depth1) / (depth2 - depth1)
        
        mask = target_depths == depth2
        beta[mask] = 1.0
        
        if method == "minimum_curvature":
            cum_dx = np.zeros(self.n_surveys)
            cum_dy = np.zeros(self.n_surveys)
            cum_dz = np.zeros(self.n_surveys)
            
            for i in range(self.n_surveys):
                dx1 = self.dx[0] if i == 0 else self.dx[i-1]
                dy1 = self.dy[0] if i == 0 else self.dy[i-1]
                dz1 = self.dz[0] if i == 0 else self.dz[i-1]
                dx2, dy2, dz2 = self.dx[i], self.dy[i], self.dz[i]
                
                disp = self.interval_lengths[i] * self.rf[i] / 2.0
                cum_dx[i] = disp * (dx1 + dx2)
                cum_dy[i] = disp * (dy1 + dy2)
                cum_dz[i] = disp * (dz1 + dz2)
            
            cum_sums = np.cumsum(np.vstack([cum_dx, cum_dy, cum_dz]), axis=1).T
            
            valid_intervals = intervals[intervals > 0]
            coords[intervals > 0] += cum_sums[valid_intervals - 1]
            
            for i in range(len(target_depths)):
                idx = intervals[i]
                dx1 = self.dx[0] if idx == 0 else self.dx[idx-1]
                dy1 = self.dy[0] if idx == 0 else self.dy[idx-1]
                dz1 = self.dz[0] if idx == 0 else self.dz[idx-1]
                dx2, dy2, dz2 = self.dx[idx], self.dy[idx], self.dz[idx]
                
                disp = self.interval_lengths[idx] * self.rf[idx] * beta[i] / 2.0
                coords[i, 0] += disp * (dx1 + dx2)
                coords[i, 1] += disp * (dy1 + dy2)
                coords[i, 2] += disp * (dz1 + dz2)
        
        elif method == "tangential":
            for i in range(len(target_depths)):
                idx = intervals[i]
                # Use orientation of upper survey (or first survey for collar)
                dx = self.dx[0] if idx == 0 else self.dx[idx-1]
                dy = self.dy[0] if idx == 0 else self.dy[idx-1]
                dz = self.dz[0] if idx == 0 else self.dz[idx-1]
                
                # Displacement from collar to depth1
                for j in range(idx):
                    dx_j = self.dx[0] if j == 0 else self.dx[j-1]
                    dy_j = self.dy[0] if j == 0 else self.dy[j-1]
                    dz_j = self.dz[0] if j == 0 else self.dz[j-1]
                    disp = self.interval_lengths[j]
                    coords[i, 0] += disp * dx_j
                    coords[i, 1] += disp * dy_j
                    coords[i, 2] += disp * dz_j
                
                # Displacement within current interval
                disp = (target_depths[i] - depth1[i])
                coords[i, 0] += disp * dx
                coords[i, 1] += disp * dy
                coords[i, 2] += disp * dz
        
        elif method == "average_angle":
            for i in range(len(target_depths)):
                idx = intervals[i]
                # Average orientations (use first survey for collar)
                az1 = self.azimuths[0] if idx == 0 else self.azimuths[idx-1]
                dip1 = self.dips[0] if idx == 0 else self.dips[idx-1]
                az2 = self.azimuths[idx]
                dip2 = self.dips[idx]
                
                avg_az = (az1 + az2) / 2.0
                avg_dip = (dip1 + dip2) / 2.0
                
                dx = np.sin(avg_dip) * np.sin(avg_az)
                dy = np.sin(avg_dip) * np.cos(avg_az)
                dz = np.cos(avg_dip)
                
                # Displacement from collar to depth1
                for j in range(idx):
                    az1_j = self.azimuths[0] if j == 0 else self.azimuths[j-1]
                    dip1_j = self.dips[0] if j == 0 else self.dips[j-1]
                    az2_j = self.azimuths[j]
                    dip2_j = self.dips[j]
                    
                    avg_az_j = (az1_j + az2_j) / 2.0
                    avg_dip_j = (dip1_j + dip2_j) / 2.0
                    
                    dx_j = np.sin(avg_dip_j) * np.sin(avg_az_j)
                    dy_j = np.sin(avg_dip_j) * np.cos(avg_az_j)
                    dz_j = np.cos(avg_dip_j)
                    
                    disp = self.interval_lengths[j]
                    coords[i, 0] += disp * dx_j
                    coords[i, 1] += disp * dy_j
                    coords[i, 2] += disp * dz_j
                
                # Displacement within current interval
                disp = (target_depths[i] - depth1[i])
                coords[i, 0] += disp * dx
                coords[i, 1] += disp * dy
                coords[i, 2] += disp * dz
        
        elif method == "radius_curvature":
            for i in range(len(target_depths)):
                idx = intervals[i]
                az1 = self.azimuths[0] if idx == 0 else self.azimuths[idx-1]
                dip1 = self.dips[0] if idx == 0 else self.dips[idx-1]
                az2 = self.azimuths[idx]
                dip2 = self.dips[idx]
                
                # Cumulative displacement
                x, y, z = 0.0, 0.0, 0.0
                for j in range(idx):
                    az1_j = self.azimuths[0] if j == 0 else self.azimuths[j-1]
                    dip1_j = self.dips[0] if j == 0 else self.dips[j-1]
                    az2_j = self.azimuths[j]
                    dip2_j = self.dips[j]
                    
                    delta_depth = self.interval_lengths[j]
                    delta_dip = dip2_j - dip1_j
                    
                    if abs(delta_dip) > 1e-6:
                        R_dip = delta_depth / delta_dip
                        x += R_dip * (np.cos(dip1_j) - np.cos(dip2_j)) * np.sin(az1_j)
                        y += R_dip * (np.cos(dip1_j) - np.cos(dip2_j)) * np.cos(az1_j)
                        z += R_dip * (np.sin(dip2_j) - np.sin(dip1_j))
                    else:
                        dx = np.sin(dip1_j) * np.sin(az1_j)
                        dy = np.sin(dip1_j) * np.cos(az1_j)
                        dz = np.cos(dip1_j)
                        x += delta_depth * dx
                        y += delta_depth * dy
                        z += delta_depth * dz
                
                # Within current interval
                delta_depth = target_depths[i] - depth1[i]
                delta_dip = dip2 - dip1
                if abs(delta_dip) > 1e-6:
                    R_dip = delta_depth / delta_dip
                    dip_interp = dip1 + beta[i] * delta_dip
                    x += R_dip * (np.cos(dip1) - np.cos(dip_interp)) * np.sin(az1)
                    y += R_dip * (np.cos(dip1) - np.cos(dip_interp)) * np.cos(az1)
                    z += R_dip * (np.sin(dip_interp) - np.sin(dip1))
                else:
                    dx = np.sin(dip1) * np.sin(az1)
                    dy = np.sin(dip1) * np.cos(az1)
                    dz = np.cos(dip1)
                    x += delta_depth * dx
                    y += delta_depth * dy
                    z += delta_depth * dz
                
                coords[i, 0] += x
                coords[i, 1] += y
                coords[i, 2] += z
        
        return coords

def calculate_drill_trace_coords(collar, surveys, segments=100):
    """
    Calculate drill hole trace coordinates (background-thread safe).
    
    This function does NOT access Blender API and can run in background threads.
    
    Args:
        collar: tuple (x, y, z, total_depth)
        surveys: list of tuples [(azimuth, dip, depth), ...]
        segments: int, number of segments to use for the trace
    
    Returns:
        numpy.ndarray: Nx3 array of (x, y, z) coordinates
    """
    # Validate surveys
    if not surveys:
        raise ValueError("No survey data provided. Cannot create drill trace without survey data.")
    
    # Get the maximum depth from surveys
    max_depth = max(s[2] for s in surveys)
    
    # Create desurvey object
    desurvey = DrillholeDesurvey(collar, surveys)
    
    # Generate depths
    depths = np.linspace(0, max_depth, segments)
    
    # Calculate and return coordinates
    return desurvey.desurvey_batch(depths)

def create_drill_trace_mesh_from_coords(coords, name="DrillTrace"):
    """
    Create a Blender mesh from pre-calculated coordinates (main thread only).
    
    This function MUST run on the main thread as it accesses Blender API.
    
    Args:
        coords: numpy.ndarray, Nx3 array of (x, y, z) coordinates
        name: str, name for the created mesh object
    
    Returns:
        bpy.types.Object: The created mesh object
    """
    # Create mesh
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    
    # Create vertices and edges
    vertices = [Vector((x, y, z)) for x, y, z in coords]
    edges = [(i, i+1) for i in range(len(vertices)-1)]
    
    # Set mesh data
    mesh.from_pydata(vertices, edges, [])
    mesh.update()
    
    # Add object to scene
    bpy.context.collection.objects.link(obj)
    
    return obj

def create_drill_trace_mesh(collar, surveys, segments=100, name="DrillTrace"):
    """
    Create a Blender mesh object representing a drill hole trace.
    
    Args:
        collar: tuple (x, y, z, total_depth)
            - x, y, z: float, collar coordinates (e.g., easting, northing, elevation in meters)
            - total_depth: float, maximum depth of the hole (meters)
        surveys: list of tuples [(azimuth, dip, depth), ...]
            - azimuth: float, degrees (0-360, 0 = north, 90 = east)
            - dip: float, degrees (0 = vertical, -90 = straight down, positive = upward)
            - depth: float, measured depth along hole (meters, increasing)
        segments: int, number of segments to use for the trace
        name: str, name for the created mesh object
    
    Returns:
        bpy.types.Object: The created mesh object
    """
    coords = calculate_drill_trace_coords(collar, surveys, segments)
    return create_drill_trace_mesh_from_coords(coords, name)

def calculate_drill_sample_coords(collar, surveys, samples):
    """
    Calculate drill hole sample coordinates (background-thread safe).
    
    This function does NOT access Blender API and can run in background threads.
    
    Args:
        collar: tuple (x, y, z, total_depth)
        surveys: list of tuples [(azimuth, dip, depth), ...]
        samples: list of dicts with keys 'depth_from', 'depth_to', 'name', 'values'
    
    Returns:
        list of tuples: [(coords, sample_data), ...] where coords is Nx3 numpy array
    """
    # Create desurvey object
    desurvey = DrillholeDesurvey(collar, surveys)
    
    # List to store calculated data
    sample_data = []
    
    # Process each sample
    for i, sample in enumerate(samples):
        depth_from = sample['depth_from']
        depth_to = sample['depth_to']
        
        # Generate depths for this sample (10 segments per sample)
        segments = max(2, int((depth_to - depth_from) * 10))
        depths = np.linspace(depth_from, depth_to, segments)
        
        # Calculate coordinates
        coords = desurvey.desurvey_batch(depths)
        
        # Store coords and metadata
        sample_data.append((coords, sample))
    
    return sample_data

def create_drill_sample_meshes_from_coords(sample_data, name_prefix="Sample"):
    """
    Create Blender meshes from pre-calculated sample coordinates (main thread only).
    
    This function MUST run on the main thread as it accesses Blender API.
    
    Args:
        sample_data: list of tuples [(coords, sample_dict), ...]
        name_prefix: str, prefix for the created mesh objects
    
    Returns:
        list: The created mesh objects
    """
    objects = []
    
    for i, (coords, sample) in enumerate(sample_data):
        depth_from = sample['depth_from']
        depth_to = sample['depth_to']
        sample_name = sample.get('name', f"{name_prefix}_{i}")
        
        # Create mesh
        mesh = bpy.data.meshes.new(sample_name)
        obj = bpy.data.objects.new(sample_name, mesh)
        
        # Create vertices and edges
        vertices = [Vector((x, y, z)) for x, y, z in coords]
        edges = [(i, i+1) for i in range(len(vertices)-1)]
        
        # Set mesh data
        mesh.from_pydata(vertices, edges, [])
        mesh.update()
        
        # Add object to scene
        bpy.context.collection.objects.link(obj)
        objects.append(obj)
        
        # Store sample data as custom properties
        obj['depth_from'] = depth_from
        obj['depth_to'] = depth_to
        obj['sample_name'] = sample_name
        
        # Store element values if available
        if 'values' in sample:
            for element, value in sample['values'].items():
                obj[f'value_{element}'] = value
    
    return objects

def create_drill_sample_meshes(collar, surveys, samples, name_prefix="Sample"):
    """
    Create Blender mesh objects representing drill hole samples.
    
    Args:
        collar: tuple (x, y, z, total_depth)
            - x, y, z: float, collar coordinates (e.g., easting, northing, elevation in meters)
            - total_depth: float, maximum depth of the hole (meters)
        surveys: list of tuples [(azimuth, dip, depth), ...]
            - azimuth: float, degrees (0-360, 0 = north, 90 = east)
            - dip: float, degrees (0 = vertical, -90 = straight down, positive = upward)
            - depth: float, measured depth along hole (meters, increasing)
        samples: list of dicts with keys:
            - 'depth_from': float, start depth of sample
            - 'depth_to': float, end depth of sample
            - 'name': str, sample name/ID
            - 'values': dict, optional element values for coloring
        name_prefix: str, prefix for the created mesh objects
    
    Returns:
        list: The created mesh objects
    """
    sample_data = calculate_drill_sample_coords(collar, surveys, samples)
    return create_drill_sample_meshes_from_coords(sample_data, name_prefix)