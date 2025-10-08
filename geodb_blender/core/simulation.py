"""
Drill hole data simulation module for the geoDB Blender add-on.

This module provides functionality for simulating realistic drill hole data
for different deposit types including porphyry copper and gold vein systems.
"""

import numpy as np
from typing import List, Dict, Tuple
import bpy
from mathutils import Vector


class DepositSimulator:
    """Base class for deposit simulation."""
    
    def __init__(self, seed: int = 42):
        """Initialize the simulator with a random seed."""
        self.rng = np.random.default_rng(seed)
        np.random.seed(seed)
    
    def generate_drill_holes(self, num_holes: int, area_size: float,
                            max_depth: float, samples_per_hole: int) -> List[Dict]:
        """
        Generate drill hole data.
        
        Args:
            num_holes: Number of drill holes to generate
            area_size: Size of the exploration area
            max_depth: Maximum drill hole depth
            samples_per_hole: Number of samples per drill hole
            
        Returns:
            List of drill hole dictionaries with collar, surveys, and samples
        """
        raise NotImplementedError("Subclasses must implement generate_drill_holes")
    
    def _generate_collar(self, area_size: float) -> Tuple[float, float, float]:
        """Generate a random collar position."""
        x = self.rng.uniform(0, area_size)
        y = self.rng.uniform(0, area_size)
        z = 0.0  # Surface
        return x, y, z
    
    def _generate_surveys(self, max_depth: float, 
                         vertical: bool = True) -> List[Tuple[float, float, float]]:
        """
        Generate survey data for a drill hole.
        
        Args:
            max_depth: Maximum depth of the hole
            vertical: If True, generate mostly vertical holes
            
        Returns:
            List of (azimuth, dip, depth) tuples
        """
        if vertical:
            # Mostly vertical holes with slight deviation
            angle_deviation = self.rng.uniform(-15, 15)
            azimuth = self.rng.uniform(0, 360)
            dip = -90 + angle_deviation
        else:
            # More varied orientations
            dip = self.rng.uniform(-90, -45)
            azimuth = self.rng.uniform(0, 360)
        
        # Create surveys at intervals
        surveys = []
        num_surveys = max(3, int(max_depth / 50))
        for i in range(num_surveys):
            depth = (i + 1) * (max_depth / num_surveys)
            # Add slight variation to angle
            current_dip = dip + self.rng.uniform(-5, 5)
            current_azimuth = azimuth + self.rng.uniform(-10, 10)
            surveys.append((current_azimuth, current_dip, depth))
        
        return surveys
    
    def _calculate_grade(self, position: Tuple[float, float, float],
                        orebody_center: Tuple[float, float, float],
                        orebody_size: float, max_grade: float,
                        background_grade: float, noise_level: float) -> float:
        """
        Calculate grade based on distance from orebody center.
        
        Args:
            position: (x, y, z) position
            orebody_center: (x, y, z) center of orebody
            orebody_size: Size of the orebody
            max_grade: Maximum grade
            background_grade: Background grade
            noise_level: Amount of noise to add
            
        Returns:
            Calculated grade
        """
        x, y, z = position
        cx, cy, cz = orebody_center
        
        # Calculate distance to orebody
        dist = np.sqrt((x - cx)**2 + (y - cy)**2 + (z - cz)**2)
        
        # Gaussian-like grade distribution
        grade_factor = np.exp(-(dist / orebody_size)**2)
        
        # Calculate base grade
        grade = background_grade + (max_grade - background_grade) * grade_factor
        
        # Add noise
        noise = self.rng.normal(0, noise_level * grade)
        grade = max(background_grade * 0.1, grade + noise)
        
        return grade


class PorphyryCopperSimulator(DepositSimulator):
    """Simulator for porphyry copper-gold deposits."""
    
    def __init__(self, seed: int = 42,
                 orebody_center: Tuple[float, float, float] = None,
                 orebody_size: float = 200.0,
                 cu_max: float = 1.5,  # percent
                 cu_background: float = 0.01,
                 au_max: float = 0.5,  # ppm
                 au_background: float = 0.005,
                 noise_level: float = 0.2):
        """
        Initialize porphyry copper simulator.
        
        Args:
            seed: Random seed for reproducibility
            orebody_center: Center of the orebody (x, y, z)
            orebody_size: Size/radius of the orebody
            cu_max: Maximum copper grade (percent)
            cu_background: Background copper grade (percent)
            au_max: Maximum gold grade (ppm)
            au_background: Background gold grade (ppm)
            noise_level: Amount of noise to add (0-1)
        """
        super().__init__(seed)
        self.orebody_center = orebody_center
        self.orebody_size = orebody_size
        self.cu_max = cu_max
        self.cu_background = cu_background
        self.au_max = au_max
        self.au_background = au_background
        self.noise_level = noise_level
    
    def generate_drill_holes(self, num_holes: int, area_size: float,
                            max_depth: float, samples_per_hole: int) -> List[Dict]:
        """Generate porphyry copper drill hole data."""
        
        # Set default orebody center if not provided
        if self.orebody_center is None:
            self.orebody_center = (area_size / 2, area_size / 2, -max_depth / 2)
        
        drill_holes = []
        
        for hole_id in range(num_holes):
            # Generate collar
            collar_x, collar_y, collar_z = self._generate_collar(area_size)
            
            # Generate surveys (mostly vertical for porphyry)
            surveys = self._generate_surveys(max_depth, vertical=True)
            
            # Calculate direction vector (simplified - use first survey)
            azimuth_rad = np.radians(surveys[0][0])
            dip_rad = np.radians(90 + surveys[0][1])
            
            dx = np.sin(dip_rad) * np.sin(azimuth_rad)
            dy = np.sin(dip_rad) * np.cos(azimuth_rad)
            dz = np.cos(dip_rad)
            
            # Generate samples along the hole
            samples = []
            actual_depth = self.rng.uniform(max_depth * 0.7, max_depth)
            
            for i in range(samples_per_hole):
                # Position along hole
                depth = (i / (samples_per_hole - 1)) * actual_depth
                depth_from = depth
                depth_to = depth + (actual_depth / samples_per_hole)
                
                # Calculate 3D position
                x = collar_x + dx * depth
                y = collar_y + dy * depth
                z = collar_z + dz * depth
                
                # Calculate Cu grade
                cu_grade = self._calculate_grade(
                    (x, y, z), self.orebody_center, self.orebody_size,
                    self.cu_max, self.cu_background, self.noise_level
                )
                
                # Calculate Au grade (correlated with Cu but with variation)
                # Gold typically has similar but not identical distribution
                au_position_factor = np.exp(-((x - self.orebody_center[0])**2 + 
                                             (y - self.orebody_center[1])**2 + 
                                             (z - self.orebody_center[2])**2) / 
                                            (self.orebody_size * 1.2)**2)
                
                au_grade = (self.au_background + 
                           (self.au_max - self.au_background) * au_position_factor)
                au_noise = self.rng.normal(0, self.noise_level * au_grade)
                au_grade = max(self.au_background * 0.1, au_grade + au_noise)
                
                # Add occasional high-grade zones (stockwork veining)
                if self.rng.random() < 0.05 and cu_grade > self.cu_max * 0.3:
                    cu_grade *= self.rng.uniform(1.5, 2.5)
                    au_grade *= self.rng.uniform(2, 4)
                
                samples.append({
                    'depth_from': depth_from,
                    'depth_to': depth_to,
                    'name': f"DH{hole_id:03d}_S{i:03d}",
                    'values': {
                        'Cu_pct': cu_grade,
                        'Au_ppm': au_grade,
                    }
                })
            
            drill_holes.append({
                'id': hole_id,
                'name': f"DH{hole_id:03d}",
                'collar': (collar_x, collar_y, collar_z, actual_depth),
                'surveys': surveys,
                'samples': samples
            })
        
        return drill_holes


class GoldVeinSimulator(DepositSimulator):
    """Simulator for gold vein deposits."""
    
    def __init__(self, seed: int = 42,
                 vein_center: Tuple[float, float, float] = None,
                 vein_strike: float = 45.0,  # degrees
                 vein_dip: float = 70.0,  # degrees
                 vein_thickness: float = 5.0,  # meters
                 vein_length: float = 300.0,  # meters
                 au_max: float = 20.0,  # ppm
                 au_background: float = 0.01,
                 ag_max: float = 50.0,  # ppm
                 ag_background: float = 0.05,
                 noise_level: float = 0.3):
        """
        Initialize gold vein simulator.
        
        Args:
            seed: Random seed for reproducibility
            vein_center: Center of the vein (x, y, z)
            vein_strike: Strike direction of the vein (degrees)
            vein_dip: Dip angle of the vein (degrees)
            vein_thickness: Thickness of the vein (meters)
            vein_length: Length of the vein (meters)
            au_max: Maximum gold grade (ppm)
            au_background: Background gold grade (ppm)
            ag_max: Maximum silver grade (ppm)
            ag_background: Background silver grade (ppm)
            noise_level: Amount of noise to add (0-1)
        """
        super().__init__(seed)
        self.vein_center = vein_center
        self.vein_strike = vein_strike
        self.vein_dip = vein_dip
        self.vein_thickness = vein_thickness
        self.vein_length = vein_length
        self.au_max = au_max
        self.au_background = au_background
        self.ag_max = ag_max
        self.ag_background = ag_background
        self.noise_level = noise_level
        
        # Calculate vein orientation vectors
        strike_rad = np.radians(vein_strike)
        dip_rad = np.radians(vein_dip)
        
        # Vein strike vector (horizontal)
        self.vein_strike_vec = np.array([np.cos(strike_rad), np.sin(strike_rad), 0])
        
        # Vein dip vector (perpendicular to strike, dipping)
        self.vein_dip_vec = np.array([
            -np.sin(strike_rad) * np.cos(dip_rad),
            np.cos(strike_rad) * np.cos(dip_rad),
            -np.sin(dip_rad)
        ])
        
        # Vein normal vector (perpendicular to both)
        self.vein_normal = np.cross(self.vein_strike_vec, self.vein_dip_vec)
    
    def _distance_to_vein(self, position: Tuple[float, float, float]) -> Tuple[float, float]:
        """
        Calculate distance from a point to the vein.
        
        Returns:
            Tuple of (perpendicular distance to vein plane, along-strike distance)
        """
        x, y, z = position
        cx, cy, cz = self.vein_center
        
        # Vector from vein center to point
        vec = np.array([x - cx, y - cy, z - cz])
        
        # Distance perpendicular to vein plane (across thickness)
        perp_dist = abs(np.dot(vec, self.vein_normal))
        
        # Distance along strike
        strike_dist = np.dot(vec, self.vein_strike_vec)
        
        return perp_dist, strike_dist
    
    def _calculate_vein_grade(self, position: Tuple[float, float, float],
                             max_grade: float, background_grade: float) -> float:
        """Calculate grade based on distance from vein."""
        perp_dist, strike_dist = self._distance_to_vein(position)
        
        # Grade decreases exponentially from vein center
        thickness_factor = np.exp(-(perp_dist / (self.vein_thickness / 2))**2)
        
        # Grade also decreases along strike at the ends
        length_factor = 1.0
        if abs(strike_dist) > self.vein_length / 2:
            excess = abs(strike_dist) - self.vein_length / 2
            length_factor = np.exp(-(excess / (self.vein_length / 4))**2)
        
        # Combined factor
        grade_factor = thickness_factor * length_factor
        
        # Calculate grade
        grade = background_grade + (max_grade - background_grade) * grade_factor
        
        # Add noise
        noise = self.rng.normal(0, self.noise_level * grade)
        grade = max(background_grade * 0.1, grade + noise)
        
        return grade
    
    def generate_drill_holes(self, num_holes: int, area_size: float,
                            max_depth: float, samples_per_hole: int) -> List[Dict]:
        """Generate gold vein drill hole data."""
        
        # Set default vein center if not provided
        if self.vein_center is None:
            self.vein_center = (area_size / 2, area_size / 2, -max_depth / 3)
        
        drill_holes = []
        
        for hole_id in range(num_holes):
            # Generate collar (try to drill across the vein)
            collar_x, collar_y, collar_z = self._generate_collar(area_size)
            
            # Generate surveys (more varied for vein drilling)
            surveys = self._generate_surveys(max_depth, vertical=False)
            
            # Calculate direction vector (simplified - use first survey)
            azimuth_rad = np.radians(surveys[0][0])
            dip_rad = np.radians(90 + surveys[0][1])
            
            dx = np.sin(dip_rad) * np.sin(azimuth_rad)
            dy = np.sin(dip_rad) * np.cos(azimuth_rad)
            dz = np.cos(dip_rad)
            
            # Generate samples along the hole
            samples = []
            actual_depth = self.rng.uniform(max_depth * 0.7, max_depth)
            
            for i in range(samples_per_hole):
                # Position along hole
                depth = (i / (samples_per_hole - 1)) * actual_depth
                depth_from = depth
                depth_to = depth + (actual_depth / samples_per_hole)
                
                # Calculate 3D position
                x = collar_x + dx * depth
                y = collar_y + dy * depth
                z = collar_z + dz * depth
                
                # Calculate Au grade
                au_grade = self._calculate_vein_grade(
                    (x, y, z), self.au_max, self.au_background
                )
                
                # Calculate Ag grade (correlated with Au)
                ag_grade = self._calculate_vein_grade(
                    (x, y, z), self.ag_max, self.ag_background
                )
                
                # Add occasional bonanza grades (nugget effect)
                perp_dist, _ = self._distance_to_vein((x, y, z))
                if self.rng.random() < 0.03 and perp_dist < self.vein_thickness:
                    au_grade *= self.rng.uniform(5, 20)
                    ag_grade *= self.rng.uniform(3, 10)
                
                samples.append({
                    'depth_from': depth_from,
                    'depth_to': depth_to,
                    'name': f"DH{hole_id:03d}_S{i:03d}",
                    'values': {
                        'Au_ppm': au_grade,
                        'Ag_ppm': ag_grade,
                    }
                })
            
            drill_holes.append({
                'id': hole_id,
                'name': f"DH{hole_id:03d}",
                'collar': (collar_x, collar_y, collar_z, actual_depth),
                'surveys': surveys,
                'samples': samples
            })
        
        return drill_holes


def visualize_simulated_drill_holes(drill_holes: List[Dict], 
                                    show_traces: bool = True,
                                    show_samples: bool = True,
                                    color_element: str = None):
    """
    Visualize simulated drill holes in Blender.
    
    Args:
        drill_holes: List of drill hole dictionaries
        show_traces: Whether to show drill traces
        show_samples: Whether to show samples
        color_element: Element to use for coloring (e.g., 'Cu_pct', 'Au_ppm')
    """
    from ..core.visualization import DrillHoleVisualizer
    
    # Clear existing visualizations
    DrillHoleVisualizer.clear_visualizations()
    
    all_objects = []
    
    for drill_hole in drill_holes:
        # Visualize drill hole
        objects = DrillHoleVisualizer.visualize_drill_hole(
            collar=drill_hole['collar'],
            surveys=drill_hole['surveys'],
            samples=drill_hole['samples'] if show_samples else None,
            hole_name=drill_hole['name'],
            show_trace=show_traces,
            show_samples=show_samples,
            trace_segments=100
        )
        all_objects.extend(objects)
    
    # Apply color mapping if requested
    if show_samples and color_element:
        DrillHoleVisualizer.apply_color_mapping(all_objects, color_element)
    
    return all_objects