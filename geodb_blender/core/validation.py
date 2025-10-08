"""
Data validation module for the geoDB Blender add-on.

This module provides comprehensive validation for drill hole data,
checking for common errors and inconsistencies before visualization.
"""

from typing import List, Dict, Any, Tuple, Optional
import numpy as np


class DrillHoleValidationError:
    """Represents a validation error for a drill hole."""
    
    ERROR_TYPES = {
        'MISSING_SURVEYS': 'No survey data available',
        'MISSING_COLLAR_ORIENTATION': 'No survey data and missing collar azimuth/dip',
        'DEPTH_MISMATCH': 'Max depth mismatch between collar, surveys, and samples',
        'OVERLAPPING_INTERVALS': 'Overlapping intervals detected',
        'INVALID_DEPTH_ORDER': 'Invalid depth ordering (from >= to)',
        'SURVEY_DEPTH_EXCEEDED': 'Survey depths exceed collar total depth',
        'SAMPLE_DEPTH_EXCEEDED': 'Sample depths exceed collar total depth',
        'NEGATIVE_DEPTH': 'Negative depth values detected',
        'DUPLICATE_SURVEY_DEPTHS': 'Duplicate survey depths found',
        'MISSING_COLLAR_DATA': 'Missing required collar data (coordinates/depth)',
        'INVALID_AZIMUTH': 'Invalid azimuth value (should be 0-360)',
        'INVALID_DIP': 'Invalid dip value (should be -90 to 90)',
        'EMPTY_INTERVALS': 'Empty intervals detected (from == to)',
        'GAP_IN_INTERVALS': 'Gaps detected between intervals',
    }
    
    def __init__(self, error_type: str, message: str, severity: str = 'ERROR'):
        """
        Initialize a validation error.
        
        Args:
            error_type: Type of error from ERROR_TYPES
            message: Detailed error message
            severity: 'ERROR', 'WARNING', or 'INFO'
        """
        self.error_type = error_type
        self.message = message
        self.severity = severity
    
    def __str__(self):
        return f"[{self.severity}] {self.error_type}: {self.message}"


class DrillHoleValidator:
    """Validates drill hole data and reports errors."""
    
    @staticmethod
    def validate_drill_hole(collar: Dict[str, Any], 
                           surveys: List[Dict[str, Any]], 
                           samples: List[Dict[str, Any]],
                           check_lithology: bool = True,
                           check_alteration: bool = False) -> Tuple[bool, List[DrillHoleValidationError]]:
        """
        Validate a single drill hole's data.
        
        Args:
            collar: Drill collar dictionary with coordinates and total_depth
            surveys: List of survey dictionaries
            samples: List of sample dictionaries
            check_lithology: Check for overlapping lithology intervals
            check_alteration: Check for overlapping alteration intervals (usually allowed)
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Validate collar data
        collar_errors = DrillHoleValidator._validate_collar(collar)
        errors.extend(collar_errors)
        
        # Validate surveys
        survey_errors = DrillHoleValidator._validate_surveys(collar, surveys)
        errors.extend(survey_errors)
        
        # Check if we can create a straight hole if no surveys
        if not surveys or len(surveys) == 0:
            can_create_straight = DrillHoleValidator._can_create_straight_hole(collar)
            if not can_create_straight:
                errors.append(DrillHoleValidationError(
                    'MISSING_COLLAR_ORIENTATION',
                    "Cannot create drill trace: No survey data and collar is missing azimuth/dip fields",
                    'ERROR'
                ))
            else:
                errors.append(DrillHoleValidationError(
                    'MISSING_SURVEYS',
                    "No survey data - will create straight hole using collar azimuth/dip",
                    'WARNING'
                ))
        
        # Validate samples
        if samples:
            sample_errors = DrillHoleValidator._validate_samples(collar, samples, check_lithology)
            errors.extend(sample_errors)
        
        # Check depth consistency across all data
        depth_errors = DrillHoleValidator._validate_depth_consistency(collar, surveys, samples)
        errors.extend(depth_errors)
        
        # Determine if valid (no ERROR severity issues)
        is_valid = not any(e.severity == 'ERROR' for e in errors)
        
        return is_valid, errors
    
    @staticmethod
    def _validate_collar(collar: Dict[str, Any]) -> List[DrillHoleValidationError]:
        """Validate collar data."""
        errors = []
        
        # Check for coordinate data (API Phase 2B - Multiple formats supported)
        # Priority 1: Proj4 local grid (preferred for Blender)
        has_proj4_coords = (collar.get('proj4_easting') is not None and 
                           collar.get('proj4_northing') is not None)
        # Priority 2: Project CRS coordinates
        has_local_coords = (collar.get('easting') is not None and 
                           collar.get('northing') is not None)
        # Priority 3: WGS84 geographic coordinates
        has_geo_coords = (collar.get('latitude') is not None and 
                         collar.get('longitude') is not None)
        
        if not has_proj4_coords and not has_local_coords and not has_geo_coords:
            errors.append(DrillHoleValidationError(
                'MISSING_COLLAR_DATA',
                "Missing coordinates: need either (proj4_easting, proj4_northing), (easting, northing), or (latitude, longitude)",
                'ERROR'
            ))
        
        # Check required fields
        if collar.get('total_depth') is None:
            errors.append(DrillHoleValidationError(
                'MISSING_COLLAR_DATA',
                "Missing required field: total_depth",
                'ERROR'
            ))
        
        # Check total_depth is positive
        total_depth = collar.get('total_depth')
        if total_depth is not None and total_depth <= 0:
            errors.append(DrillHoleValidationError(
                'NEGATIVE_DEPTH',
                f"Collar total_depth must be positive, got {total_depth}",
                'ERROR'
            ))
        
        # Check azimuth if present
        azimuth = collar.get('azimuth')
        if azimuth is not None and (azimuth < 0 or azimuth > 360):
            errors.append(DrillHoleValidationError(
                'INVALID_AZIMUTH',
                f"Collar azimuth should be 0-360, got {azimuth}",
                'WARNING'
            ))
        
        # Check dip if present
        dip = collar.get('dip')
        if dip is not None and (dip < -90 or dip > 90):
            errors.append(DrillHoleValidationError(
                'INVALID_DIP',
                f"Collar dip should be -90 to 90, got {dip}",
                'WARNING'
            ))
        
        return errors
    
    @staticmethod
    def _validate_surveys(collar: Dict[str, Any], surveys: List[Dict[str, Any]]) -> List[DrillHoleValidationError]:
        """Validate survey data."""
        errors = []
        
        if not surveys:
            return errors
        
        total_depth = collar.get('total_depth', 0)
        depths = []
        
        for i, survey in enumerate(surveys):
            depth = survey.get('depth')
            azimuth = survey.get('azimuth')
            dip = survey.get('dip')
            
            # Check required fields
            if depth is None:
                errors.append(DrillHoleValidationError(
                    'MISSING_COLLAR_DATA',
                    f"Survey {i} missing depth",
                    'ERROR'
                ))
                continue
            
            # Check negative depth
            if depth < 0:
                errors.append(DrillHoleValidationError(
                    'NEGATIVE_DEPTH',
                    f"Survey {i} has negative depth: {depth}",
                    'ERROR'
                ))
            
            # Check depth exceeds collar total_depth
            if total_depth > 0 and depth > total_depth:
                errors.append(DrillHoleValidationError(
                    'SURVEY_DEPTH_EXCEEDED',
                    f"Survey {i} depth ({depth}m) exceeds collar total_depth ({total_depth}m)",
                    'WARNING'
                ))
            
            # Check azimuth
            if azimuth is not None and (azimuth < 0 or azimuth > 360):
                errors.append(DrillHoleValidationError(
                    'INVALID_AZIMUTH',
                    f"Survey {i} azimuth should be 0-360, got {azimuth}",
                    'WARNING'
                ))
            
            # Check dip
            if dip is not None and (dip < -90 or dip > 90):
                errors.append(DrillHoleValidationError(
                    'INVALID_DIP',
                    f"Survey {i} dip should be -90 to 90, got {dip}",
                    'WARNING'
                ))
            
            depths.append(depth)
        
        # Check for duplicate depths
        if len(depths) != len(set(depths)):
            duplicates = [d for d in depths if depths.count(d) > 1]
            errors.append(DrillHoleValidationError(
                'DUPLICATE_SURVEY_DEPTHS',
                f"Duplicate survey depths found: {set(duplicates)}",
                'ERROR'
            ))
        
        # Check depths are increasing
        if depths and depths != sorted(depths):
            errors.append(DrillHoleValidationError(
                'INVALID_DEPTH_ORDER',
                "Survey depths are not in ascending order",
                'ERROR'
            ))
        
        return errors
    
    @staticmethod
    def _validate_samples(collar: Dict[str, Any], samples: List[Dict[str, Any]], 
                         check_lithology: bool = True) -> List[DrillHoleValidationError]:
        """Validate sample data."""
        errors = []
        
        if not samples:
            return errors
        
        total_depth = collar.get('total_depth', 0)
        intervals = []
        
        for i, sample in enumerate(samples):
            depth_from = sample.get('depth_from')
            depth_to = sample.get('depth_to')
            
            # Check required fields
            if depth_from is None or depth_to is None:
                errors.append(DrillHoleValidationError(
                    'MISSING_COLLAR_DATA',
                    f"Sample {i} missing depth_from or depth_to",
                    'ERROR'
                ))
                continue
            
            # Check negative depths
            if depth_from < 0 or depth_to < 0:
                errors.append(DrillHoleValidationError(
                    'NEGATIVE_DEPTH',
                    f"Sample {i} has negative depth: {depth_from} to {depth_to}",
                    'ERROR'
                ))
            
            # Check depth ordering
            if depth_from >= depth_to:
                if depth_from == depth_to:
                    errors.append(DrillHoleValidationError(
                        'EMPTY_INTERVALS',
                        f"Sample {i} has empty interval: {depth_from}",
                        'WARNING'
                    ))
                else:
                    errors.append(DrillHoleValidationError(
                        'INVALID_DEPTH_ORDER',
                        f"Sample {i} has invalid depth order: {depth_from} >= {depth_to}",
                        'ERROR'
                    ))
            
            # Check depth exceeds collar total_depth
            if total_depth > 0 and depth_to > total_depth:
                errors.append(DrillHoleValidationError(
                    'SAMPLE_DEPTH_EXCEEDED',
                    f"Sample {i} depth_to ({depth_to}m) exceeds collar total_depth ({total_depth}m)",
                    'WARNING'
                ))
            
            intervals.append((depth_from, depth_to, i))
        
        # Check for overlapping intervals (lithology/assays)
        if check_lithology and intervals:
            overlaps = DrillHoleValidator._find_overlapping_intervals(intervals)
            if overlaps:
                for (i1, i2) in overlaps:
                    errors.append(DrillHoleValidationError(
                        'OVERLAPPING_INTERVALS',
                        f"Samples {i1} and {i2} have overlapping intervals",
                        'WARNING'
                    ))
        
        # Check for gaps in coverage (optional - might be normal)
        if intervals and len(intervals) > 1:
            sorted_intervals = sorted(intervals, key=lambda x: x[0])
            for i in range(len(sorted_intervals) - 1):
                current_to = sorted_intervals[i][1]
                next_from = sorted_intervals[i + 1][0]
                if next_from > current_to + 0.01:  # Small tolerance for floating point
                    gap_size = next_from - current_to
                    if gap_size > 1.0:  # Only report gaps > 1m
                        errors.append(DrillHoleValidationError(
                            'GAP_IN_INTERVALS',
                            f"Gap of {gap_size:.2f}m between samples (from {current_to}m to {next_from}m)",
                            'INFO'
                        ))
        
        return errors
    
    @staticmethod
    def _find_overlapping_intervals(intervals: List[Tuple[float, float, int]]) -> List[Tuple[int, int]]:
        """Find overlapping intervals."""
        overlaps = []
        sorted_intervals = sorted(intervals, key=lambda x: x[0])
        
        for i in range(len(sorted_intervals)):
            for j in range(i + 1, len(sorted_intervals)):
                from1, to1, idx1 = sorted_intervals[i]
                from2, to2, idx2 = sorted_intervals[j]
                
                # Check if intervals overlap
                if from2 < to1:
                    overlaps.append((idx1, idx2))
        
        return overlaps
    
    @staticmethod
    def _validate_depth_consistency(collar: Dict[str, Any], 
                                   surveys: List[Dict[str, Any]], 
                                   samples: List[Dict[str, Any]]) -> List[DrillHoleValidationError]:
        """Validate depth consistency across collar, surveys, and samples."""
        errors = []
        
        collar_depth = collar.get('total_depth', 0)
        
        # Get max survey depth
        max_survey_depth = 0
        if surveys:
            survey_depths = [s.get('depth', 0) for s in surveys if s.get('depth') is not None]
            if survey_depths:
                max_survey_depth = max(survey_depths)
        
        # Get max sample depth
        max_sample_depth = 0
        if samples:
            sample_depths = [s.get('depth_to', 0) for s in samples if s.get('depth_to') is not None]
            if sample_depths:
                max_sample_depth = max(sample_depths)
        
        # Compare depths
        depths = {
            'collar': collar_depth,
            'surveys': max_survey_depth,
            'samples': max_sample_depth
        }
        
        # Remove zero values
        non_zero_depths = {k: v for k, v in depths.items() if v > 0}
        
        if len(non_zero_depths) > 1:
            max_depth = max(non_zero_depths.values())
            min_depth = min(non_zero_depths.values())
            
            # Allow 10% tolerance for depth mismatches
            tolerance = max_depth * 0.1
            if max_depth - min_depth > tolerance:
                depth_info = ', '.join([f"{k}: {v:.2f}m" for k, v in non_zero_depths.items()])
                errors.append(DrillHoleValidationError(
                    'DEPTH_MISMATCH',
                    f"Significant depth mismatch between data sources ({depth_info})",
                    'WARNING'
                ))
        
        return errors
    
    @staticmethod
    def _can_create_straight_hole(collar: Dict[str, Any]) -> bool:
        """Check if we can create a straight hole from collar data."""
        azimuth = collar.get('azimuth')
        dip = collar.get('dip')
        total_depth = collar.get('total_depth', 0)
        
        # Need azimuth, dip, and total_depth to create straight hole
        return azimuth is not None and dip is not None and total_depth > 0
    
    @staticmethod
    def create_straight_hole_surveys(collar: Dict[str, Any]) -> List[Tuple[float, float, float]]:
        """
        Create synthetic survey data for a straight hole from collar data.
        
        Args:
            collar: Drill collar dictionary with azimuth, dip, and total_depth
        
        Returns:
            List of tuples (azimuth, dip, depth) suitable for desurvey
        """
        azimuth = collar.get('azimuth', 0.0)
        dip = collar.get('dip', -90.0)
        total_depth = collar.get('total_depth', 0.0)
        
        # Create two survey points: at collar and at bottom
        surveys = [
            (azimuth, dip, 0.0),
            (azimuth, dip, total_depth)
        ]
        
        return surveys
    
    @staticmethod
    def format_validation_report(hole_name: str, errors: List[DrillHoleValidationError]) -> str:
        """Format validation errors into a readable report."""
        if not errors:
            return f"{hole_name}: OK"
        
        error_count = sum(1 for e in errors if e.severity == 'ERROR')
        warning_count = sum(1 for e in errors if e.severity == 'WARNING')
        info_count = sum(1 for e in errors if e.severity == 'INFO')
        
        lines = [f"\n{hole_name}:"]
        lines.append(f"  Errors: {error_count}, Warnings: {warning_count}, Info: {info_count}")
        
        for error in errors:
            lines.append(f"  - {error}")
        
        return '\n'.join(lines)


def validate_project_data(cached_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate entire project's cached drill hole data.
    
    Args:
        cached_data: Dictionary containing cached project data
        
    Returns:
        Validation report dictionary with summary and per-hole details
    """
    collars = cached_data.get('collars', [])
    surveys_by_hole = cached_data.get('surveys', {})
    samples_by_hole = cached_data.get('samples', {})
    lithology_by_hole = cached_data.get('lithology', {})
    
    # Build collar lookup by ID
    collar_dict = {}
    for collar in collars:
        bhid = collar.get('id')
        if bhid:
            collar_dict[bhid] = collar
        # Also try by name
        hole_id = collar.get('hole_id')
        if hole_id:
            collar_dict[f"name:{hole_id}"] = collar
    
    validation_results = {}
    total_holes = len(collars)
    valid_holes = 0
    total_errors = 0
    total_warnings = 0
    total_info = 0
    
    # Validate each drill hole
    for collar in collars:
        bhid = collar.get('id')
        hole_name = collar.get('hole_id', f'Hole_{bhid}')
        
        # Get surveys for this hole
        surveys = surveys_by_hole.get(bhid, [])
        if not surveys:
            # Try name-based lookup
            surveys = surveys_by_hole.get(f"name:{hole_name}", [])
        
        # Get samples for this hole
        samples = samples_by_hole.get(bhid, [])
        if not samples:
            samples = samples_by_hole.get(f"name:{hole_name}", [])
        
        # Validate
        is_valid, errors = DrillHoleValidator.validate_drill_hole(
            collar, surveys, samples
        )
        
        # Count severity
        error_count = sum(1 for e in errors if e.severity == 'ERROR')
        warning_count = sum(1 for e in errors if e.severity == 'WARNING')
        info_count = sum(1 for e in errors if e.severity == 'INFO')
        
        total_errors += error_count
        total_warnings += warning_count
        total_info += info_count
        
        if is_valid:
            valid_holes += 1
        
        # Store result
        validation_results[hole_name] = {
            'bhid': bhid,
            'status': 'PASS' if is_valid else 'FAIL',
            'errors': error_count,
            'warnings': warning_count,
            'info': info_count,
            'issues': [str(e) for e in errors if e.severity == 'ERROR'],
            'warnings_list': [str(e) for e in errors if e.severity == 'WARNING'],
            'info_list': [str(e) for e in errors if e.severity == 'INFO']
        }
    
    # Determine overall status
    if total_errors == 0 and total_warnings == 0:
        overall_status = 'PASS'
    elif total_errors == 0:
        overall_status = 'WARNING'
    else:
        overall_status = 'FAIL'
    
    return {
        'status': overall_status,
        'summary': {
            'total_holes': total_holes,
            'valid_holes': valid_holes,
            'errors': total_errors,
            'warnings': total_warnings,
            'info': total_info
        },
        'details': validation_results
    }


def format_validation_summary(report: Dict[str, Any]) -> str:
    """
    Format validation report summary for UI display.
    
    Args:
        report: Validation report from validate_project_data()
        
    Returns:
        Formatted summary string
    """
    if not report:
        return "No validation report available"
    
    summary = report.get('summary', {})
    status = report.get('status', 'UNKNOWN')
    
    lines = []
    lines.append(f"Status: {status}")
    lines.append(f"Total Holes: {summary.get('total_holes', 0)}")
    lines.append(f"Valid Holes: {summary.get('valid_holes', 0)}")
    
    errors = summary.get('errors', 0)
    warnings = summary.get('warnings', 0)
    info = summary.get('info', 0)
    
    if errors > 0:
        lines.append(f"Errors: {errors}")
    if warnings > 0:
        lines.append(f"Warnings: {warnings}")
    if info > 0:
        lines.append(f"Info: {info}")
    
    return " | ".join(lines)