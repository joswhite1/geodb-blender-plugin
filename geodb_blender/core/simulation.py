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
            # Ensure last survey depth doesn't exceed max_depth due to floating-point precision
            depth = min(depth, max_depth)
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

    # Typical porphyry lithology types (from intrusive core to wall rock)
    LITHOLOGY_TYPES = [
        'Quartz Monzonite Porphyry',  # Core intrusive
        'Monzonite Porphyry',
        'Diorite Porphyry',
        'Hornfelsed Sediments',  # Contact aureole
        'Metasediments',  # Wall rock
        'Limestone',
        'Sandstone',
    ]

    # Typical porphyry alteration types (from core to periphery)
    ALTERATION_TYPES = [
        'Potassic',  # Core - K-feldspar + biotite
        'Phyllic',  # Sericite-quartz-pyrite
        'Argillic',  # Clay alteration
        'Propylitic',  # Chlorite-epidote-carbonate (peripheral)
        'Fresh',  # Unaltered
    ]

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

    def _get_lithology_at_position(self, position: Tuple[float, float, float],
                                    collar_z: float) -> str:
        """
        Determine lithology based on position relative to orebody.

        Porphyry systems have concentric lithology zones around the intrusive core.
        """
        x, y, z = position
        cx, cy, cz = self.orebody_center

        # Calculate distance from orebody center
        dist = np.sqrt((x - cx)**2 + (y - cy)**2 + (z - cz)**2)

        # Normalize by orebody size
        normalized_dist = dist / self.orebody_size

        # Add some noise/variability
        noise = self.rng.normal(0, 0.15)
        normalized_dist += noise

        # Assign lithology based on distance zones
        if normalized_dist < 0.3:
            return self.rng.choice(['Quartz Monzonite Porphyry', 'Monzonite Porphyry'])
        elif normalized_dist < 0.6:
            return self.rng.choice(['Diorite Porphyry', 'Monzonite Porphyry'])
        elif normalized_dist < 1.0:
            return self.rng.choice(['Hornfelsed Sediments', 'Diorite Porphyry'])
        elif normalized_dist < 1.5:
            return self.rng.choice(['Metasediments', 'Hornfelsed Sediments'])
        else:
            # Background wall rock varies with depth
            depth = collar_z - z
            if depth < 100:
                return self.rng.choice(['Sandstone', 'Metasediments'])
            else:
                return self.rng.choice(['Limestone', 'Sandstone', 'Metasediments'])

    def _get_alteration_at_position(self, position: Tuple[float, float, float]) -> str:
        """
        Determine alteration based on position relative to orebody.

        Porphyry alteration zones: Potassic (core) -> Phyllic -> Argillic -> Propylitic (edge)
        """
        x, y, z = position
        cx, cy, cz = self.orebody_center

        # Calculate distance from orebody center
        dist = np.sqrt((x - cx)**2 + (y - cy)**2 + (z - cz)**2)

        # Normalize by orebody size (alteration halo is larger than mineralization)
        normalized_dist = dist / (self.orebody_size * 1.5)

        # Add noise for irregular boundaries
        noise = self.rng.normal(0, 0.1)
        normalized_dist += noise

        # Assign alteration based on distance zones
        if normalized_dist < 0.25:
            return 'Potassic'
        elif normalized_dist < 0.5:
            return self.rng.choice(['Potassic', 'Phyllic'], p=[0.3, 0.7])
        elif normalized_dist < 0.75:
            return self.rng.choice(['Phyllic', 'Argillic'], p=[0.6, 0.4])
        elif normalized_dist < 1.0:
            return self.rng.choice(['Argillic', 'Propylitic'], p=[0.4, 0.6])
        elif normalized_dist < 1.5:
            return 'Propylitic'
        else:
            return 'Fresh'

    def _get_grade_multiplier_for_lithology(self, lithology: str) -> float:
        """
        Get grade multiplier based on lithology.

        In porphyry systems, Cu-Au mineralization is hosted primarily in:
        - Porphyry intrusives (best host)
        - Hornfelsed/altered sediments (moderate host)
        - Wall rock sediments (poor host, only fracture-controlled)
        """
        multipliers = {
            'Quartz Monzonite Porphyry': 1.0,   # Best host - primary Cu-Au carrier
            'Monzonite Porphyry': 0.95,         # Excellent host
            'Diorite Porphyry': 0.85,           # Good host
            'Hornfelsed Sediments': 0.5,        # Moderate - skarn/contact mineralization
            'Metasediments': 0.15,              # Poor - only fracture-hosted
            'Limestone': 0.3,                   # Moderate - can host skarn
            'Sandstone': 0.1,                   # Poor host
        }
        return multipliers.get(lithology, 0.1)

    def _get_grade_multiplier_for_alteration(self, alteration: str) -> float:
        """
        Get grade multiplier based on alteration.

        In porphyry systems, Cu-Au grades correlate strongly with alteration:
        - Potassic: Best grades (hypogene Cu, bornite-chalcopyrite)
        - Phyllic: Good grades (chalcopyrite-pyrite zone)
        - Argillic: Lower grades (supergene or peripheral)
        - Propylitic: Background grades (distal, weak mineralization)
        - Fresh: No significant mineralization
        """
        multipliers = {
            'Potassic': 1.0,     # Highest grades - core Cu-Au zone
            'Phyllic': 0.7,      # Good grades - pyrite-chalcopyrite shell
            'Argillic': 0.25,    # Low grades - clay zone, supergene
            'Propylitic': 0.08,  # Near-background - distal halo
            'Fresh': 0.02,       # Background only
        }
        return multipliers.get(alteration, 0.02)
    
    def generate_drill_holes(self, num_holes: int, area_size: float,
                            max_depth: float, samples_per_hole: int) -> List[Dict]:
        """Generate porphyry copper drill hole data with lithology and alteration."""
        from ..utils.desurvey import DrillholeDesurvey

        # Set default orebody center if not provided
        # Position at 1/3 of max_depth to place mineralization in the middle of typical holes
        # (holes are 70-100% of max_depth, so -max_depth/3 puts center around 40-50% down the hole)
        if self.orebody_center is None:
            self.orebody_center = (area_size / 2, area_size / 2, -max_depth / 3)

        print(f"[Simulation] Orebody center: {self.orebody_center}")
        print(f"[Simulation] Orebody size (radius): {self.orebody_size}")
        print(f"[Simulation] Area size: {area_size}, Max depth: {max_depth}")

        # Debug: will print first hole's sample z-coordinates
        debug_first_hole = True

        drill_holes = []

        for hole_id in range(num_holes):
            # Generate collar
            collar_x, collar_y, collar_z = self._generate_collar(area_size)

            # Generate samples along the hole
            samples = []
            lithology_intervals = []
            alteration_intervals = []
            actual_depth = self.rng.uniform(max_depth * 0.7, max_depth)

            # Generate surveys based on actual_depth (must not exceed collar total_depth)
            surveys = self._generate_surveys(actual_depth, vertical=True)

            # Create desurvey object for proper coordinate calculation along curved path
            collar = (collar_x, collar_y, collar_z, actual_depth)
            desurvey = DrillholeDesurvey(collar, surveys)

            # Track current lithology and alteration for interval creation
            current_lithology = None
            current_alteration = None
            lith_interval_start = 0.0
            alt_interval_start = 0.0

            sample_interval = actual_depth / samples_per_hole
            for i in range(samples_per_hole):
                # Position along hole
                depth_from = i * sample_interval
                depth_to = min((i + 1) * sample_interval, actual_depth)
                depth = (depth_from + depth_to) / 2  # midpoint for grade calculation

                # Calculate 3D positions using proper desurvey (follows curved path)
                coords = desurvey.desurvey_batch([depth_from, depth, depth_to])
                xyz_from = coords[0]
                xyz_mid = coords[1]
                xyz_to = coords[2]

                x, y, z = xyz_mid  # Use midpoint for grade calculation

                # Debug first hole
                if debug_first_hole and hole_id == 0 and i < 5:
                    print(f"[Debug] Sample {i}: depth={depth:.1f}, xyz_mid=({x:.1f}, {y:.1f}, {z:.1f})")

                # Determine lithology and alteration FIRST (grades depend on these)
                lithology = self._get_lithology_at_position((x, y, z), collar_z)
                alteration = self._get_alteration_at_position((x, y, z))

                # Get base grade from position (distance-based)
                base_cu_grade = self._calculate_grade(
                    (x, y, z), self.orebody_center, self.orebody_size,
                    self.cu_max, self.cu_background, self.noise_level
                )

                # Apply lithology and alteration controls to grades
                # These are multiplicative but with stochastic variation to avoid perfect correlation
                lith_mult = self._get_grade_multiplier_for_lithology(lithology)
                alt_mult = self._get_grade_multiplier_for_alteration(alteration)

                # Add random variation to multipliers (±30% variance) for realistic imperfect correlation
                # Sometimes you get good grades in "wrong" rock, or low grades in "right" rock
                lith_mult *= self.rng.uniform(0.7, 1.3)
                alt_mult *= self.rng.uniform(0.7, 1.3)

                # Combined geology factor (geometric mean to avoid extreme values)
                # Weight alteration more heavily - it's a stronger grade control in porphyries
                geology_factor = (lith_mult ** 0.4) * (alt_mult ** 0.6)

                # Apply geology factor to the grade above background
                cu_grade = self.cu_background + (base_cu_grade - self.cu_background) * geology_factor

                # Calculate Au grade (correlated with Cu but with additional variation)
                # Gold distribution is more erratic than copper in porphyries
                au_position_factor = np.exp(-((x - self.orebody_center[0])**2 +
                                             (y - self.orebody_center[1])**2 +
                                             (z - self.orebody_center[2])**2) /
                                            (self.orebody_size * 1.2)**2)

                base_au_grade = (self.au_background +
                                (self.au_max - self.au_background) * au_position_factor)

                # Au also controlled by geology but with more noise (gold is nuggety)
                au_geology_factor = geology_factor * self.rng.uniform(0.5, 1.5)
                au_grade = self.au_background + (base_au_grade - self.au_background) * au_geology_factor
                au_noise = self.rng.normal(0, self.noise_level * au_grade)
                au_grade = max(self.au_background * 0.1, au_grade + au_noise)

                # Add occasional high-grade zones (stockwork veining) - only in favorable host rocks
                favorable_lith = lithology in ['Quartz Monzonite Porphyry', 'Monzonite Porphyry', 'Diorite Porphyry']
                favorable_alt = alteration in ['Potassic', 'Phyllic']
                if self.rng.random() < 0.08 and favorable_lith and favorable_alt:
                    cu_grade *= self.rng.uniform(1.3, 2.0)
                    au_grade *= self.rng.uniform(1.5, 3.0)

                # Track lithology intervals (merge consecutive same lithology)
                if lithology != current_lithology:
                    if current_lithology is not None:
                        lithology_intervals.append({
                            'id': hole_id * 1000 + len(lithology_intervals),
                            'bhid': hole_id,
                            'depth_from': lith_interval_start,
                            'depth_to': depth_from,
                            'lithology': current_lithology,
                            'xyz_from': desurvey.desurvey_batch([lith_interval_start])[0].tolist(),
                            'xyz_to': xyz_from.tolist(),
                        })
                    current_lithology = lithology
                    lith_interval_start = depth_from

                # Track alteration intervals (merge consecutive same alteration)
                if alteration != current_alteration:
                    if current_alteration is not None:
                        alteration_intervals.append({
                            'id': hole_id * 1000 + len(alteration_intervals),
                            'bhid': hole_id,
                            'depth_from': alt_interval_start,
                            'depth_to': depth_from,
                            'alteration': current_alteration,
                            'xyz_from': desurvey.desurvey_batch([alt_interval_start])[0].tolist(),
                            'xyz_to': xyz_from.tolist(),
                        })
                    current_alteration = alteration
                    alt_interval_start = depth_from

                samples.append({
                    'id': hole_id * 1000 + i,  # Unique sample ID
                    'bhid': hole_id,  # Reference to drill hole
                    'depth_from': depth_from,
                    'depth_to': depth_to,
                    'name': f"DH{hole_id:03d}_S{i:03d}",
                    'assay': {
                        'elements': [
                            {'element': 'Cu_pct', 'value': cu_grade},
                            {'element': 'Au_ppm', 'value': au_grade},
                        ]
                    },
                    'xyz_from': xyz_from.tolist(),
                    'xyz_to': xyz_to.tolist(),
                })

            # Close final lithology interval
            if current_lithology is not None:
                lithology_intervals.append({
                    'id': hole_id * 1000 + len(lithology_intervals),
                    'bhid': hole_id,
                    'depth_from': lith_interval_start,
                    'depth_to': actual_depth,
                    'lithology': current_lithology,
                    'xyz_from': desurvey.desurvey_batch([lith_interval_start])[0].tolist(),
                    'xyz_to': desurvey.desurvey_batch([actual_depth])[0].tolist(),
                })

            # Close final alteration interval
            if current_alteration is not None:
                alteration_intervals.append({
                    'id': hole_id * 1000 + len(alteration_intervals),
                    'bhid': hole_id,
                    'depth_from': alt_interval_start,
                    'depth_to': actual_depth,
                    'alteration': current_alteration,
                    'xyz_from': desurvey.desurvey_batch([alt_interval_start])[0].tolist(),
                    'xyz_to': desurvey.desurvey_batch([actual_depth])[0].tolist(),
                })

            drill_holes.append({
                'id': hole_id,
                'name': f"DH{hole_id:03d}",
                'collar': (collar_x, collar_y, collar_z, actual_depth),
                'surveys': surveys,
                'samples': samples,
                'lithology': lithology_intervals,
                'alteration': alteration_intervals,
            })

        return drill_holes


class GoldVeinSimulator(DepositSimulator):
    """Simulator for gold vein deposits."""

    # Typical epithermal/orogenic vein lithology types
    LITHOLOGY_TYPES = [
        'Quartz Vein',  # The vein itself
        'Stockwork Zone',  # Fractured zone with veinlets
        'Silicified Host',  # Silicified wall rock
        'Andesite',  # Volcanic host rock
        'Dacite',
        'Rhyolite',
        'Tuff',
        'Metasediments',
    ]

    # Typical vein-style alteration types
    ALTERATION_TYPES = [
        'Silicic',  # Core silicification
        'Quartz-Sericite',  # Phyllic alteration
        'Quartz-Adularia',  # Low-sulfidation epithermal
        'Argillic',  # Clay alteration
        'Propylitic',  # Chlorite-epidote (distal)
        'Fresh',  # Unaltered
    ]

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

    def _get_lithology_at_position(self, position: Tuple[float, float, float],
                                    collar_z: float) -> str:
        """
        Determine lithology based on distance from vein.

        Vein systems have lithology controlled by proximity to the vein structure.
        """
        perp_dist, strike_dist = self._distance_to_vein(position)

        # Add noise
        noise = self.rng.normal(0, self.vein_thickness * 0.3)
        perp_dist_noisy = perp_dist + abs(noise)

        # Determine lithology based on distance from vein
        if perp_dist < self.vein_thickness * 0.5:
            return 'Quartz Vein'
        elif perp_dist < self.vein_thickness * 1.5:
            return self.rng.choice(['Stockwork Zone', 'Quartz Vein'], p=[0.7, 0.3])
        elif perp_dist < self.vein_thickness * 3:
            return self.rng.choice(['Silicified Host', 'Stockwork Zone'], p=[0.7, 0.3])
        else:
            # Background host rock (varies by depth)
            depth = collar_z - position[2]
            if depth < 50:
                return self.rng.choice(['Andesite', 'Tuff', 'Dacite'])
            elif depth < 150:
                return self.rng.choice(['Andesite', 'Dacite', 'Rhyolite'])
            else:
                return self.rng.choice(['Metasediments', 'Andesite'])

    def _get_alteration_at_position(self, position: Tuple[float, float, float]) -> str:
        """
        Determine alteration based on distance from vein.

        Vein alteration is controlled by proximity to the vein and fluid pathways.
        """
        perp_dist, strike_dist = self._distance_to_vein(position)

        # Add noise for irregular alteration halos
        noise = self.rng.normal(0, self.vein_thickness * 0.2)
        perp_dist_noisy = perp_dist + abs(noise)

        # Determine alteration based on distance from vein
        if perp_dist < self.vein_thickness * 0.5:
            return 'Silicic'
        elif perp_dist < self.vein_thickness * 1.5:
            return self.rng.choice(['Silicic', 'Quartz-Sericite'], p=[0.3, 0.7])
        elif perp_dist < self.vein_thickness * 3:
            return self.rng.choice(['Quartz-Sericite', 'Quartz-Adularia'], p=[0.6, 0.4])
        elif perp_dist < self.vein_thickness * 5:
            return self.rng.choice(['Argillic', 'Quartz-Adularia'], p=[0.6, 0.4])
        elif perp_dist < self.vein_thickness * 10:
            return self.rng.choice(['Propylitic', 'Argillic'], p=[0.7, 0.3])
        else:
            return 'Fresh'

    def _get_grade_multiplier_for_lithology(self, lithology: str) -> float:
        """
        Get grade multiplier based on lithology for vein deposits.

        In vein systems, Au-Ag is concentrated in:
        - Quartz veins (primary ore host)
        - Stockwork zones (disseminated mineralization)
        - Silicified host rock (fluid pathway alteration)
        """
        multipliers = {
            'Quartz Vein': 1.0,          # Primary ore host
            'Stockwork Zone': 0.6,        # Disseminated veining
            'Silicified Host': 0.25,      # Weak mineralization in altered rock
            'Andesite': 0.05,             # Background in unaltered host
            'Dacite': 0.05,
            'Rhyolite': 0.04,
            'Tuff': 0.03,
            'Metasediments': 0.03,
        }
        return multipliers.get(lithology, 0.03)

    def _get_grade_multiplier_for_alteration(self, alteration: str) -> float:
        """
        Get grade multiplier based on alteration for vein deposits.

        In epithermal/orogenic systems:
        - Silicic: Intense silicification = high grades
        - Quartz-Sericite: Phyllic halo = moderate grades
        - Quartz-Adularia: Low-sulfidation indicator = good grades
        - Argillic: Clay = low grades
        - Propylitic/Fresh: Background
        """
        multipliers = {
            'Silicic': 1.0,           # Best grades - silica flooding
            'Quartz-Sericite': 0.6,   # Good grades - phyllic alteration
            'Quartz-Adularia': 0.7,   # Good grades - epithermal indicator
            'Argillic': 0.15,         # Low grades - clay zone
            'Propylitic': 0.05,       # Background
            'Fresh': 0.02,            # No mineralization
        }
        return multipliers.get(alteration, 0.02)
    
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
        """Generate gold vein drill hole data with lithology and alteration."""
        from ..utils.desurvey import DrillholeDesurvey

        # Set default vein center if not provided
        if self.vein_center is None:
            self.vein_center = (area_size / 2, area_size / 2, -max_depth / 3)

        drill_holes = []

        for hole_id in range(num_holes):
            # Generate collar (try to drill across the vein)
            collar_x, collar_y, collar_z = self._generate_collar(area_size)

            # Generate samples along the hole
            samples = []
            lithology_intervals = []
            alteration_intervals = []
            actual_depth = self.rng.uniform(max_depth * 0.7, max_depth)

            # Generate surveys based on actual_depth (must not exceed collar total_depth)
            surveys = self._generate_surveys(actual_depth, vertical=False)

            # Create desurvey object for proper coordinate calculation along curved path
            collar = (collar_x, collar_y, collar_z, actual_depth)
            desurvey = DrillholeDesurvey(collar, surveys)

            # Track current lithology and alteration for interval creation
            current_lithology = None
            current_alteration = None
            lith_interval_start = 0.0
            alt_interval_start = 0.0

            sample_interval = actual_depth / samples_per_hole
            for i in range(samples_per_hole):
                # Position along hole
                depth_from = i * sample_interval
                depth_to = min((i + 1) * sample_interval, actual_depth)
                depth = (depth_from + depth_to) / 2  # midpoint for grade calculation

                # Calculate 3D positions using proper desurvey (follows curved path)
                coords = desurvey.desurvey_batch([depth_from, depth, depth_to])
                xyz_from = coords[0]
                xyz_mid = coords[1]
                xyz_to = coords[2]

                x, y, z = xyz_mid  # Use midpoint for grade calculation

                # Determine lithology and alteration FIRST (grades depend on these)
                lithology = self._get_lithology_at_position((x, y, z), collar_z)
                alteration = self._get_alteration_at_position((x, y, z))

                # Calculate base Au and Ag grades from vein geometry
                base_au_grade = self._calculate_vein_grade(
                    (x, y, z), self.au_max, self.au_background
                )
                base_ag_grade = self._calculate_vein_grade(
                    (x, y, z), self.ag_max, self.ag_background
                )

                # Apply lithology and alteration controls with stochastic variation
                lith_mult = self._get_grade_multiplier_for_lithology(lithology)
                alt_mult = self._get_grade_multiplier_for_alteration(alteration)

                # Add random variation (±35% variance) - vein deposits are more variable
                lith_mult *= self.rng.uniform(0.65, 1.35)
                alt_mult *= self.rng.uniform(0.65, 1.35)

                # For veins, lithology is the primary control (quartz vein = ore)
                # Alteration is secondary but still important
                geology_factor = (lith_mult ** 0.6) * (alt_mult ** 0.4)

                # Apply geology factor to grades above background
                au_grade = self.au_background + (base_au_grade - self.au_background) * geology_factor
                ag_grade = self.ag_background + (base_ag_grade - self.ag_background) * geology_factor

                # Add occasional bonanza grades (nugget effect) - only in favorable geology
                perp_dist, _ = self._distance_to_vein((x, y, z))
                favorable_lith = lithology in ['Quartz Vein', 'Stockwork Zone']
                favorable_alt = alteration in ['Silicic', 'Quartz-Sericite', 'Quartz-Adularia']
                if self.rng.random() < 0.05 and favorable_lith and favorable_alt:
                    # Bonanza grades in vein - gold is very nuggety
                    au_grade *= self.rng.uniform(3, 15)
                    ag_grade *= self.rng.uniform(2, 8)

                # Track lithology intervals (merge consecutive same lithology)
                if lithology != current_lithology:
                    if current_lithology is not None:
                        lithology_intervals.append({
                            'id': hole_id * 1000 + len(lithology_intervals),
                            'bhid': hole_id,
                            'depth_from': lith_interval_start,
                            'depth_to': depth_from,
                            'lithology': current_lithology,
                            'xyz_from': desurvey.desurvey_batch([lith_interval_start])[0].tolist(),
                            'xyz_to': xyz_from.tolist(),
                        })
                    current_lithology = lithology
                    lith_interval_start = depth_from

                # Track alteration intervals (merge consecutive same alteration)
                if alteration != current_alteration:
                    if current_alteration is not None:
                        alteration_intervals.append({
                            'id': hole_id * 1000 + len(alteration_intervals),
                            'bhid': hole_id,
                            'depth_from': alt_interval_start,
                            'depth_to': depth_from,
                            'alteration': current_alteration,
                            'xyz_from': desurvey.desurvey_batch([alt_interval_start])[0].tolist(),
                            'xyz_to': xyz_from.tolist(),
                        })
                    current_alteration = alteration
                    alt_interval_start = depth_from

                samples.append({
                    'id': hole_id * 1000 + i,  # Unique sample ID
                    'bhid': hole_id,  # Reference to drill hole
                    'depth_from': depth_from,
                    'depth_to': depth_to,
                    'name': f"DH{hole_id:03d}_S{i:03d}",
                    'assay': {
                        'elements': [
                            {'element': 'Au_ppm', 'value': au_grade},
                            {'element': 'Ag_ppm', 'value': ag_grade},
                        ]
                    },
                    'xyz_from': xyz_from.tolist(),
                    'xyz_to': xyz_to.tolist(),
                })

            # Close final lithology interval
            if current_lithology is not None:
                lithology_intervals.append({
                    'id': hole_id * 1000 + len(lithology_intervals),
                    'bhid': hole_id,
                    'depth_from': lith_interval_start,
                    'depth_to': actual_depth,
                    'lithology': current_lithology,
                    'xyz_from': desurvey.desurvey_batch([lith_interval_start])[0].tolist(),
                    'xyz_to': desurvey.desurvey_batch([actual_depth])[0].tolist(),
                })

            # Close final alteration interval
            if current_alteration is not None:
                alteration_intervals.append({
                    'id': hole_id * 1000 + len(alteration_intervals),
                    'bhid': hole_id,
                    'depth_from': alt_interval_start,
                    'depth_to': actual_depth,
                    'alteration': current_alteration,
                    'xyz_from': desurvey.desurvey_batch([alt_interval_start])[0].tolist(),
                    'xyz_to': desurvey.desurvey_batch([actual_depth])[0].tolist(),
                })

            drill_holes.append({
                'id': hole_id,
                'name': f"DH{hole_id:03d}",
                'collar': (collar_x, collar_y, collar_z, actual_depth),
                'surveys': surveys,
                'samples': samples,
                'lithology': lithology_intervals,
                'alteration': alteration_intervals,
            })

        return drill_holes


def generate_default_assay_range_config(element: str,
                                        min_value: float,
                                        max_value: float,
                                        config_id: int = 1) -> Dict:
    """
    Generate a default assay range configuration for an element.

    Creates grade ranges typically used in mining (background, low, medium, high, bonanza).

    Args:
        element: Element name (e.g., 'Cu_pct', 'Au_ppm')
        min_value: Minimum value in the dataset
        max_value: Maximum value in the dataset
        config_id: ID for this configuration

    Returns:
        Dictionary matching the AssayRangeConfiguration structure from the API
    """
    # Determine units from element name
    if '_pct' in element.lower() or '%' in element:
        units = '%'
    elif '_ppm' in element.lower():
        units = 'ppm'
    elif '_ppb' in element.lower():
        units = 'ppb'
    else:
        units = ''

    # Calculate grade cutoffs based on value distribution
    # Typical grade ranges: background, low-grade, medium, high-grade, bonanza
    value_range = max_value - min_value

    # For most elements, the distribution is log-normal
    # Use percentile-like divisions
    cutoff_1 = min_value + value_range * 0.1   # ~10th percentile (background cutoff)
    cutoff_2 = min_value + value_range * 0.3   # ~30th percentile (low grade)
    cutoff_3 = min_value + value_range * 0.6   # ~60th percentile (medium grade)
    cutoff_4 = min_value + value_range * 0.85  # ~85th percentile (high grade)

    ranges = [
        {
            'from_value': 0,
            'to_value': cutoff_1,
            'color': '#4A4A4A',  # Dark gray - background/waste
            'label': 'Background'
        },
        {
            'from_value': cutoff_1,
            'to_value': cutoff_2,
            'color': '#0066CC',  # Blue - low grade
            'label': 'Low Grade'
        },
        {
            'from_value': cutoff_2,
            'to_value': cutoff_3,
            'color': '#00CC66',  # Green - medium grade
            'label': 'Medium Grade'
        },
        {
            'from_value': cutoff_3,
            'to_value': cutoff_4,
            'color': '#FFCC00',  # Yellow/Gold - high grade
            'label': 'High Grade'
        },
        {
            'from_value': cutoff_4,
            'to_value': float('inf'),
            'color': '#FF3300',  # Red - bonanza/very high grade
            'label': 'Bonanza'
        }
    ]

    return {
        'id': config_id,
        'name': f'{element} Default Ranges',
        'element': element,
        'units': units,
        'ranges': ranges,
        'default_color': '#808080'  # Gray for any out-of-range values
    }


def generate_assay_configs_from_drill_holes(drill_holes: List[Dict]) -> List[Dict]:
    """
    Generate default assay range configurations from drill hole data.

    Analyzes the value distribution of each element and creates appropriate
    grade range configurations.

    Args:
        drill_holes: List of drill hole dictionaries from simulator

    Returns:
        List of AssayRangeConfiguration dictionaries
    """
    # Collect all values by element
    element_values = {}

    for hole in drill_holes:
        for sample in hole.get('samples', []):
            assay = sample.get('assay', {})
            for elem in assay.get('elements', []):
                element = elem.get('element')
                value = elem.get('value', 0)

                if element:
                    if element not in element_values:
                        element_values[element] = []
                    element_values[element].append(value)

    # Generate configs for each element
    configs = []
    for i, (element, values) in enumerate(sorted(element_values.items())):
        if values:
            min_val = min(values)
            max_val = max(values)
            config = generate_default_assay_range_config(element, min_val, max_val, config_id=i+1)
            configs.append(config)

    return configs


def simulated_data_to_cache_format(drill_holes: List[Dict],
                                   project_name: str = "Simulated Project") -> Dict:
    """
    Convert simulated drill hole data to the cache format used by the RBF interpolator.

    This allows simulated data to be used directly with extract_assay_data_from_cache()
    and the RBF interpolation pipeline.

    Args:
        drill_holes: List of drill hole dictionaries from simulator
        project_name: Name for the simulated project

    Returns:
        Dictionary in cache format compatible with DrillDataCache
    """
    from datetime import datetime

    # Extract available elements from the first hole's samples
    available_elements = set()
    for hole in drill_holes:
        for sample in hole.get('samples', []):
            assay = sample.get('assay', {})
            for elem in assay.get('elements', []):
                available_elements.add(elem.get('element'))

    available_elements = sorted(list(available_elements))

    # Extract available lithologies and alterations
    available_lithologies = set()
    available_alterations = set()
    for hole in drill_holes:
        for lith in hole.get('lithology', []):
            lith_name = lith.get('lithology')
            if lith_name:
                available_lithologies.add(lith_name)
        for alt in hole.get('alteration', []):
            alt_name = alt.get('alteration')
            if alt_name:
                available_alterations.add(alt_name)

    available_lithologies = sorted(list(available_lithologies))
    available_alterations = sorted(list(available_alterations))

    # Build collars list
    collars = []
    for hole in drill_holes:
        collar = hole.get('collar', (0, 0, 0, 0))
        collars.append({
            'id': hole['id'],
            'name': hole['name'],
            'proj4_easting': collar[0],
            'proj4_northing': collar[1],
            'proj4_elevation': collar[2],
            'total_depth': collar[3] if len(collar) > 3 else 0,
        })

    # Build surveys dict (keyed by hole ID)
    surveys = {}
    for hole in drill_holes:
        hole_surveys = []
        for azimuth, dip, depth in hole.get('surveys', []):
            hole_surveys.append({
                'bhid': hole['id'],
                'azimuth': azimuth,
                'dip': dip,
                'depth': depth,
            })
        surveys[hole['id']] = hole_surveys

    # Build samples dict (keyed by hole ID)
    samples = {}
    for hole in drill_holes:
        samples[hole['id']] = hole.get('samples', [])

    # Build lithology dict (keyed by hole ID)
    lithology = {}
    for hole in drill_holes:
        lithology[hole['id']] = hole.get('lithology', [])

    # Build alteration dict (keyed by hole ID)
    alteration = {}
    for hole in drill_holes:
        alteration[hole['id']] = hole.get('alteration', [])

    # Build assay range configs from available elements
    assay_range_configs = []
    for i, element in enumerate(available_elements):
        # Determine units from element name
        if '_pct' in element.lower():
            units = '%'
        elif '_ppm' in element.lower():
            units = 'ppm'
        elif '_ppb' in element.lower():
            units = 'ppb'
        else:
            units = ''

        assay_range_configs.append({
            'id': i + 1,
            'name': element,
            'element': element,
            'units': units,
        })

    # Build the cache structure
    cache = {
        'version': '1.1.0',
        'timestamp': datetime.now().isoformat(),
        'project_id': 0,
        'company_id': 0,
        'project_name': project_name,
        'company_name': 'Simulated',
        'hole_ids': [h['id'] for h in drill_holes],
        'project_metadata': {
            'proj4_string': '+proj=longlat +datum=WGS84 +no_defs',
            'blender_origin_x': 0.0,
            'blender_origin_y': 0.0,
            'blender_rotation_degrees': 0.0,
        },
        'collars': collars,
        'surveys': surveys,
        'samples': samples,
        'lithology': lithology,
        'alteration': alteration,
        'assay_range_configs': assay_range_configs,
        'available_elements': available_elements,
        'available_lithologies': available_lithologies,
        'available_alterations': available_alterations,
        'desurveyed_traces': {},
        'validation_report': None,
        'desurveyed_intervals': None,
    }

    return cache


def load_simulated_data_to_cache(drill_holes: List[Dict],
                                  project_name: str = "Simulated Project") -> None:
    """
    Convert simulated drill hole data and load it into the DrillDataCache.

    This allows the simulated data to be used with the RBF interpolation
    pipeline via extract_assay_data_from_cache().

    Args:
        drill_holes: List of drill hole dictionaries from simulator
        project_name: Name for the simulated project
    """
    from .data_cache import DrillDataCache

    cache_data = simulated_data_to_cache_format(drill_holes, project_name)
    DrillDataCache.set_cache(cache_data)
    print(f"Loaded {len(drill_holes)} simulated drill holes into cache")
    print(f"Available elements: {cache_data['available_elements']}")
    print(f"Available lithologies: {cache_data['available_lithologies']}")
    print(f"Available alterations: {cache_data['available_alterations']}")


def visualize_simulated_drill_holes(drill_holes: List[Dict],
                                    show_traces: bool = True,
                                    show_samples: bool = True,
                                    show_lithology: bool = False,
                                    show_alteration: bool = False,
                                    color_element: str = None,
                                    color_mode: str = 'GRADIENT',
                                    color_map: str = 'RAINBOW',
                                    assay_config: Dict = None,
                                    sample_radius: float = 0.0,
                                    interval_radius: float = 0.0):
    """
    Visualize simulated drill holes in Blender.

    Creates a hierarchical collection structure similar to real data imports:
    - Master collection (Simulated Drill Data)
      - Traces/
      - Per-element collections (Cu_pct, Au_ppm, etc.)
        - Per-hole collections (DH001, DH002, etc.)
          - Cylinder objects for each sample
      - Lithology/
        - Per-lithology-type collections
          - Per-hole collections
      - Alteration/
        - Per-alteration-type collections
          - Per-hole collections

    Args:
        drill_holes: List of drill hole dictionaries
        show_traces: Whether to show drill traces
        show_samples: Whether to show samples (assay data)
        show_lithology: Whether to show lithology intervals
        show_alteration: Whether to show alteration intervals
        color_element: Element to use for coloring (e.g., 'Cu_pct', 'Au_ppm')
        color_mode: 'GRADIENT' for smooth color gradient, 'RANGES' for discrete grade ranges
        color_map: Color map to use for gradient mode ('RAINBOW', 'VIRIDIS', 'PLASMA', 'MAGMA')
        assay_config: AssayRangeConfiguration dict to use for RANGES mode (auto-generated if None)
        sample_radius: Radius of sample cylinders in meters (0 = thin lines)
        interval_radius: Radius of lithology/alteration interval tubes in meters (uses sample_radius if 0)
    """
    from ..core.visualization import DrillHoleVisualizer, DrillVisualizationManager

    # Clear existing visualizations
    DrillHoleVisualizer.clear_visualizations()

    all_objects = []

    # Collect all available elements from drill holes
    available_elements = set()
    for drill_hole in drill_holes:
        for sample in drill_hole.get('samples', []):
            assay = sample.get('assay', {})
            for elem in assay.get('elements', []):
                elem_name = elem.get('element')
                if elem_name:
                    available_elements.add(elem_name)

    available_elements = sorted(list(available_elements))
    print(f"Available elements for visualization: {available_elements}")

    # Generate assay configs for all elements
    all_assay_configs = generate_assay_configs_from_drill_holes(drill_holes)
    assay_configs_by_element = {c['element']: c for c in all_assay_configs}

    # Check if we should use cylinder visualization
    use_cylinders = sample_radius > 0 and show_samples

    if use_cylinders:
        # Use cylinder mesh for samples - provides better visibility at large scales
        from ..utils.cylinder_mesh import create_sample_cylinder_mesh
        import colorsys

        # Create master collection for simulated data
        master_collection = bpy.data.collections.new("Simulated Drill Data")
        bpy.context.scene.collection.children.link(master_collection)

        # Create traces collection if showing traces
        traces_collection = None
        if show_traces:
            traces_collection = bpy.data.collections.new("Traces")
            master_collection.children.link(traces_collection)

        # Create per-element collections
        element_collections = {}
        for element in available_elements:
            # Get units for element
            config = assay_configs_by_element.get(element)
            units = config.get('units', '') if config else ''
            collection_name = f"{element}" if not units else f"{element} ({units})"
            element_collection = bpy.data.collections.new(collection_name)
            master_collection.children.link(element_collection)
            element_collections[element] = {
                'collection': element_collection,
                'hole_collections': {},
                'config': config,
            }

        # Collect value ranges for gradient coloring per element
        element_value_ranges = {}
        for element in available_elements:
            all_values = []
            for drill_hole in drill_holes:
                for sample in drill_hole.get('samples', []):
                    assay = sample.get('assay', {})
                    for elem in assay.get('elements', []):
                        if elem.get('element') == element:
                            all_values.append(elem.get('value', 0))
            if all_values:
                element_value_ranges[element] = {
                    'min': min(all_values),
                    'max': max(all_values),
                    'range': max(all_values) - min(all_values) if max(all_values) > min(all_values) else 1.0
                }
            else:
                element_value_ranges[element] = {'min': 0, 'max': 1, 'range': 1}

        # Process each drill hole
        for drill_hole in drill_holes:
            hole_name = drill_hole['name']

            # Create trace if requested
            if show_traces and traces_collection:
                from ..utils.desurvey import create_drill_trace_mesh
                trace_obj = create_drill_trace_mesh(
                    collar=drill_hole['collar'],
                    surveys=drill_hole['surveys'],
                    segments=100,
                    name=f"{hole_name}_Trace"
                )
                trace_obj['geodb_visualization'] = True
                trace_obj['geodb_type'] = 'drill_trace'
                trace_obj['geodb_hole_name'] = hole_name
                trace_obj.display_type = 'WIRE'

                # Move trace to traces collection
                for coll in trace_obj.users_collection:
                    coll.objects.unlink(trace_obj)
                traces_collection.objects.link(trace_obj)
                all_objects.append(trace_obj)

            # Create sample cylinders for EACH element
            for element in available_elements:
                elem_data = element_collections[element]
                elem_collection = elem_data['collection']
                elem_config = elem_data['config']
                value_range_info = element_value_ranges[element]

                # Create per-hole collection under this element if it doesn't exist
                if hole_name not in elem_data['hole_collections']:
                    hole_collection = bpy.data.collections.new(hole_name)
                    elem_collection.children.link(hole_collection)
                    elem_data['hole_collections'][hole_name] = hole_collection
                else:
                    hole_collection = elem_data['hole_collections'][hole_name]

                # Process each sample for this element
                for i, sample in enumerate(drill_hole.get('samples', [])):
                    xyz_from = sample.get('xyz_from')
                    xyz_to = sample.get('xyz_to')
                    depth_from = sample.get('depth_from', 0)
                    depth_to = sample.get('depth_to', 0)

                    if not xyz_from or not xyz_to:
                        continue

                    # Get value for this element
                    value = None
                    assay = sample.get('assay', {})
                    for elem in assay.get('elements', []):
                        if elem.get('element') == element:
                            value = elem.get('value', 0)
                            break

                    if value is None:
                        continue

                    # Determine color and label for this sample
                    color_hex = '#808080'  # Default gray
                    label = 'Unknown'

                    if color_mode == 'RANGES' and elem_config:
                        # Use discrete range coloring
                        ranges = elem_config.get('ranges', [])
                        for range_item in ranges:
                            from_val = range_item.get('from_value', 0)
                            to_val = range_item.get('to_value', float('inf'))
                            if from_val <= value < to_val:
                                color_hex = range_item.get('color', '#808080')
                                label = range_item.get('label', 'Unknown')
                                break
                    else:
                        # Use gradient coloring
                        min_val = value_range_info['min']
                        val_range = value_range_info['range']
                        normalized = (value - min_val) / val_range
                        normalized = max(0, min(1, normalized))

                        if color_map == 'RAINBOW':
                            hue = 0.66 * (1.0 - normalized)
                            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                        elif color_map == 'VIRIDIS':
                            r = 0.267 * (1 - normalized) + 0.000 * normalized
                            g = 0.005 * (1 - normalized) + 0.520 * normalized
                            b = 0.329 * (1 - normalized) + 0.294 * normalized
                        elif color_map == 'PLASMA':
                            r = 0.050 * (1 - normalized) + 0.940 * normalized
                            g = 0.030 * (1 - normalized) + 0.150 * normalized
                            b = 0.550 * (1 - normalized) + 0.060 * normalized
                        elif color_map == 'MAGMA':
                            r = 0.001 * (1 - normalized) + 0.988 * normalized
                            g = 0.000 * (1 - normalized) + 0.155 * normalized
                            b = 0.014 * (1 - normalized) + 0.367 * normalized
                        else:
                            r = g = b = normalized

                        color_hex = '#{:02x}{:02x}{:02x}'.format(
                            int(r * 255), int(g * 255), int(b * 255))
                        label = 'Gradient'

                    # Get units for naming
                    units = elem_config.get('units', '') if elem_config else ''

                    # Create cylinder name
                    sample_name = f"{hole_name}_{depth_from:.1f}-{depth_to:.1f}_{element}_{value:.2f}{units}"

                    # Build metadata for the object
                    metadata = {
                        'depth_from': depth_from,
                        'depth_to': depth_to,
                        'active_assay_element': element,
                        'active_assay_value': value,
                        'active_assay_unit': units,
                        'active_range_label': label,
                    }
                    # Add all element values
                    for elem in assay.get('elements', []):
                        elem_name = elem.get('element')
                        elem_value = elem.get('value')
                        if elem_name and elem_value is not None:
                            metadata[f'element_{elem_name}_value'] = elem_value

                    try:
                        obj = create_sample_cylinder_mesh(
                            xyz_from=tuple(xyz_from),
                            xyz_to=tuple(xyz_to),
                            diameter=sample_radius * 2,
                            color_hex=color_hex,
                            name=sample_name,
                            material_name=f"Assay_{element}_{label}",
                            assay_metadata=metadata
                        )

                        # Tag the object
                        obj['geodb_visualization'] = True
                        obj['geodb_type'] = 'assay_sample'
                        obj['geodb_hole_name'] = hole_name
                        obj['geodb_element'] = element

                        # Move object to correct collection
                        for coll in obj.users_collection:
                            coll.objects.unlink(obj)
                        hole_collection.objects.link(obj)

                        all_objects.append(obj)
                    except ValueError as e:
                        print(f"Skipping sample {sample_name}: {e}")

        # ============================================
        # LITHOLOGY VISUALIZATION
        # ============================================
        if show_lithology:
            from ..utils.interval_visualization import (
                create_interval_tube, apply_material_to_interval, get_color_for_lithology
            )
            from ..utils.desurvey import DrillholeDesurvey

            # Collect all available lithology types
            available_lithologies = set()
            for drill_hole in drill_holes:
                for lith in drill_hole.get('lithology', []):
                    lith_name = lith.get('lithology')
                    if lith_name:
                        available_lithologies.add(lith_name)
            available_lithologies = sorted(list(available_lithologies))

            if available_lithologies:
                print(f"\nAvailable lithologies for visualization: {available_lithologies}")

                # Create Lithology master collection
                lithology_master = bpy.data.collections.new("Lithology")
                master_collection.children.link(lithology_master)

                # Create per-lithology-type collections
                lithology_collections = {}
                for lith_type in available_lithologies:
                    lith_collection = bpy.data.collections.new(lith_type)
                    lithology_master.children.link(lith_collection)
                    lithology_collections[lith_type] = {
                        'collection': lith_collection,
                        'hole_collections': {},
                    }

                # Use interval_radius or fall back to sample_radius
                lith_radius = interval_radius if interval_radius > 0 else sample_radius
                if lith_radius <= 0:
                    lith_radius = 1.0  # Default radius if none specified

                # Process each drill hole for lithology
                for drill_hole in drill_holes:
                    hole_name = drill_hole['name']
                    collar = drill_hole['collar']
                    surveys = drill_hole['surveys']

                    # Create desurvey for trace coordinates
                    desurvey = DrillholeDesurvey(collar, surveys)
                    max_depth = collar[3] if len(collar) > 3 else 300
                    num_points = max(50, int(max_depth / 2))
                    depths = [i * max_depth / num_points for i in range(num_points + 1)]
                    coords = desurvey.desurvey_batch(depths)

                    trace_depths = depths
                    trace_coords = [c.tolist() for c in coords]

                    for lith_interval in drill_hole.get('lithology', []):
                        lith_type = lith_interval.get('lithology')
                        if not lith_type:
                            continue

                        depth_from = lith_interval.get('depth_from', 0)
                        depth_to = lith_interval.get('depth_to', 0)

                        # Get or create per-hole collection under this lithology type
                        lith_data = lithology_collections[lith_type]
                        if hole_name not in lith_data['hole_collections']:
                            hole_collection = bpy.data.collections.new(hole_name)
                            lith_data['collection'].children.link(hole_collection)
                            lith_data['hole_collections'][hole_name] = hole_collection
                        else:
                            hole_collection = lith_data['hole_collections'][hole_name]

                        # Create interval tube
                        interval_name = f"{hole_name}_{depth_from:.1f}-{depth_to:.1f}_{lith_type}"
                        tube_obj = create_interval_tube(
                            trace_depths=trace_depths,
                            trace_coords=trace_coords,
                            depth_from=depth_from,
                            depth_to=depth_to,
                            radius=lith_radius,
                            resolution=8,
                            name=interval_name
                        )

                        if tube_obj:
                            # Apply color
                            color = get_color_for_lithology(lith_type)
                            apply_material_to_interval(
                                tube_obj, color,
                                material_name=lith_type,
                                material_prefix="Lithology"
                            )

                            # Tag the object
                            tube_obj['geodb_visualization'] = True
                            tube_obj['geodb_type'] = 'lithology_interval'
                            tube_obj['geodb_hole_name'] = hole_name
                            tube_obj['geodb_lithology'] = lith_type
                            tube_obj['depth_from'] = depth_from
                            tube_obj['depth_to'] = depth_to

                            # Link to collection
                            hole_collection.objects.link(tube_obj)
                            all_objects.append(tube_obj)

                # Print lithology summary
                total_lith = len([o for o in all_objects if o.get('geodb_type') == 'lithology_interval'])
                print(f"Created {len(available_lithologies)} lithology type collections:")
                for lith_type in available_lithologies:
                    lith_data = lithology_collections[lith_type]
                    hole_count = len(lith_data['hole_collections'])
                    print(f"  - {lith_type}: {hole_count} holes")
                print(f"Total lithology intervals created: {total_lith}")

        # ============================================
        # ALTERATION VISUALIZATION
        # ============================================
        if show_alteration:
            from ..utils.interval_visualization import (
                create_interval_tube, apply_material_to_interval, get_color_for_alteration
            )
            from ..utils.desurvey import DrillholeDesurvey

            # Collect all available alteration types
            available_alterations = set()
            for drill_hole in drill_holes:
                for alt in drill_hole.get('alteration', []):
                    alt_name = alt.get('alteration')
                    if alt_name:
                        available_alterations.add(alt_name)
            available_alterations = sorted(list(available_alterations))

            if available_alterations:
                print(f"\nAvailable alterations for visualization: {available_alterations}")

                # Create Alteration master collection
                alteration_master = bpy.data.collections.new("Alteration")
                master_collection.children.link(alteration_master)

                # Create per-alteration-type collections
                alteration_collections = {}
                for alt_type in available_alterations:
                    alt_collection = bpy.data.collections.new(alt_type)
                    alteration_master.children.link(alt_collection)
                    alteration_collections[alt_type] = {
                        'collection': alt_collection,
                        'hole_collections': {},
                    }

                # Use interval_radius or fall back to sample_radius
                alt_radius = interval_radius if interval_radius > 0 else sample_radius
                if alt_radius <= 0:
                    alt_radius = 1.0  # Default radius if none specified

                # Process each drill hole for alteration
                for drill_hole in drill_holes:
                    hole_name = drill_hole['name']
                    collar = drill_hole['collar']
                    surveys = drill_hole['surveys']

                    # Create desurvey for trace coordinates
                    desurvey = DrillholeDesurvey(collar, surveys)
                    max_depth = collar[3] if len(collar) > 3 else 300
                    num_points = max(50, int(max_depth / 2))
                    depths = [i * max_depth / num_points for i in range(num_points + 1)]
                    coords = desurvey.desurvey_batch(depths)

                    trace_depths = depths
                    trace_coords = [c.tolist() for c in coords]

                    for alt_interval in drill_hole.get('alteration', []):
                        alt_type = alt_interval.get('alteration')
                        if not alt_type:
                            continue

                        depth_from = alt_interval.get('depth_from', 0)
                        depth_to = alt_interval.get('depth_to', 0)

                        # Get or create per-hole collection under this alteration type
                        alt_data = alteration_collections[alt_type]
                        if hole_name not in alt_data['hole_collections']:
                            hole_collection = bpy.data.collections.new(hole_name)
                            alt_data['collection'].children.link(hole_collection)
                            alt_data['hole_collections'][hole_name] = hole_collection
                        else:
                            hole_collection = alt_data['hole_collections'][hole_name]

                        # Create interval tube
                        interval_name = f"{hole_name}_{depth_from:.1f}-{depth_to:.1f}_{alt_type}"
                        tube_obj = create_interval_tube(
                            trace_depths=trace_depths,
                            trace_coords=trace_coords,
                            depth_from=depth_from,
                            depth_to=depth_to,
                            radius=alt_radius,
                            resolution=8,
                            name=interval_name
                        )

                        if tube_obj:
                            # Apply color
                            color = get_color_for_alteration(alt_type)
                            apply_material_to_interval(
                                tube_obj, color,
                                material_name=alt_type,
                                material_prefix="Alteration"
                            )

                            # Tag the object
                            tube_obj['geodb_visualization'] = True
                            tube_obj['geodb_type'] = 'alteration_interval'
                            tube_obj['geodb_hole_name'] = hole_name
                            tube_obj['geodb_alteration'] = alt_type
                            tube_obj['depth_from'] = depth_from
                            tube_obj['depth_to'] = depth_to

                            # Link to collection
                            hole_collection.objects.link(tube_obj)
                            all_objects.append(tube_obj)

                # Print alteration summary
                total_alt = len([o for o in all_objects if o.get('geodb_type') == 'alteration_interval'])
                print(f"Created {len(available_alterations)} alteration type collections:")
                for alt_type in available_alterations:
                    alt_data = alteration_collections[alt_type]
                    hole_count = len(alt_data['hole_collections'])
                    print(f"  - {alt_type}: {hole_count} holes")
                print(f"Total alteration intervals created: {total_alt}")

        # Print summary
        total_meshes = len([o for o in all_objects if o.get('geodb_type') == 'assay_sample'])
        total_lith = len([o for o in all_objects if o.get('geodb_type') == 'lithology_interval'])
        total_alt = len([o for o in all_objects if o.get('geodb_type') == 'alteration_interval'])
        print(f"\n=== Simulation Visualization Summary ===")
        if show_samples:
            print(f"Created {len(available_elements)} element collections:")
            for element in available_elements:
                elem_data = element_collections[element]
                hole_count = len(elem_data['hole_collections'])
                print(f"  - {element}: {hole_count} holes")
            print(f"Total assay meshes created: {total_meshes}")
        if show_lithology:
            print(f"Total lithology intervals: {total_lith}")
        if show_alteration:
            print(f"Total alteration intervals: {total_alt}")
        print(f"Total objects: {len(all_objects)}")

    else:
        # Use standard line-based visualization (legacy mode)
        for drill_hole in drill_holes:
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

        # Apply color mapping for line-based samples
        if show_samples and color_element:
            if color_mode == 'GRADIENT':
                DrillHoleVisualizer.apply_color_mapping(all_objects, color_element, color_map=color_map)
            elif color_mode == 'RANGES' and assay_config:
                colored_count = DrillVisualizationManager.apply_assay_range_configuration(
                    all_objects, color_element, assay_config
                )
                print(f"Applied grade ranges to {colored_count} samples")
            elif color_mode == 'RANGES':
                print(f"No assay config for {color_element}, falling back to gradient")
                DrillHoleVisualizer.apply_color_mapping(all_objects, color_element, color_map=color_map)

    return all_objects