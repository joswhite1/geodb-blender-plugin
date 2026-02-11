"""
Data retrieval module for the geoDB Blender add-on.

This module handles retrieving data from the geoDB API, including
companies, projects, drill holes, and samples.
"""

import bpy
import numpy as np
from typing import List, Dict, Any, Tuple, Optional, Callable

from .client import GeoDBAPIClient
from .auth import get_api_client
from ..utils.logging import logger

class GeoDBData:
    """Class for retrieving and managing geoDB data."""

    @staticmethod
    def get_companies(progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the list of companies the user has access to.

        Args:
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of companies
        """
        logger.debug("Fetching companies")
        client = get_api_client()

        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # First check if we already have companies from login
        if client.companies:
            logger.debug("Using %d cached companies", len(client.companies))
            return True, client.companies

        # Otherwise fetch from API with pagination
        logger.debug("Fetching companies from API endpoint")
        success, companies = client.get_all_paginated(
            'companies/',
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Fetched %d companies", len(companies))
            return True, companies
        else:
            logger.error("Failed to fetch companies")
            return False, []

    @staticmethod
    def get_projects(company_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the list of projects for a company.

        Args:
            company_id: The ID of the company
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of projects
        """
        logger.debug("Fetching projects for company %d", company_id)
        client = get_api_client()

        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # Fetch projects with pagination
        success, projects = client.get_all_paginated(
            'projects/',
            params={'company_id': company_id},
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Fetched %d projects", len(projects))
            # Update authorized project scope
            project_ids = [p['id'] for p in projects if 'id' in p]
            client.add_authorized_projects(project_ids)
            return True, projects

        # Fallback: If server error, try getting all projects and filtering client-side
        logger.debug("Primary method failed, trying fallback with company name filter")

        # First, get the company name from the company ID
        company_name = None
        if client.companies:
            for comp in client.companies:
                if comp.get('id') == company_id or str(comp.get('id')) == str(company_id):
                    company_name = comp.get('name')
                    break

        if not company_name:
            # Try to fetch companies to get the name
            success_comp, companies = GeoDBData.get_companies()
            if success_comp:
                for comp in companies:
                    if comp.get('id') == company_id or str(comp.get('id')) == str(company_id):
                        company_name = comp.get('name')
                        break

        logger.debug("Resolved company name for ID %d", company_id)

        if company_name:
            # Try filtering by company name instead
            logger.debug("Trying with company name filter")
            success, projects = client.get_all_paginated(
                'projects/',
                params={'company': company_name},
                progress_callback=progress_callback
            )

            if success:
                logger.debug("Fetched %d projects using company name filter", len(projects))
                # Update authorized project scope
                project_ids = [p['id'] for p in projects if 'id' in p]
                client.add_authorized_projects(project_ids)
                return True, projects

        logger.error("Failed to fetch projects")
        return False, []

    @staticmethod
    def get_drill_holes(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the list of drill holes for a project.

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of drill holes
        """
        logger.debug("Fetching drill holes for project %d", project_id)
        client = get_api_client()

        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # Fetch drill holes with pagination
        success, drill_holes = client.get_all_paginated(
            'drill-collars/',
            params={'project_id': project_id},
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Fetched %d drill holes", len(drill_holes))
            return True, drill_holes
        else:
            logger.error("Failed to fetch drill holes")
            return False, []

    @staticmethod
    def get_drill_holes_with_sync(
        project_id: int,
        deleted_since: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """Get drill holes for a project with deletion sync support.

        This method returns both active drill holes and IDs of soft-deleted holes,
        enabling the client to remove deleted holes from local cache/scene.

        Args:
            project_id: The ID of the project
            deleted_since: ISO timestamp for incremental sync (from last sync_timestamp).
                          If None, returns all deleted IDs (for first sync).
            progress_callback: Optional callback(fetched_count, total_count) for progress

        Returns:
            Tuple[bool, Dict]: Success flag and dict containing:
                - results: List of active drill hole records
                - deleted_ids: List of soft-deleted drill hole IDs
                - sync_timestamp: ISO timestamp to use for next sync's deleted_since
        """
        logger.debug("Fetching drill holes with sync for project %d", project_id)
        if deleted_since:
            logger.debug("Incremental sync from: %s", deleted_since)

        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {'results': [], 'deleted_ids': [], 'sync_timestamp': None}

        # Build params
        params = {'project_id': project_id}
        if deleted_since:
            params['deleted_since'] = deleted_since

        # Fetch with sync metadata
        success, result = client.get_all_paginated_with_sync(
            'drill-collars/',
            params=params,
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Fetched %d drill holes, %d deleted IDs",
                         len(result['results']), len(result['deleted_ids']))
            return True, result
        else:
            logger.error("Failed to fetch drill holes")
            return False, result

    @staticmethod
    def get_drill_hole_details(drill_hole_id: int) -> Tuple[bool, Dict[str, Any]]:
        """Get the details of a drill hole (collar).

        Args:
            drill_hole_id: The ID of the drill collar

        Returns:
            Tuple[bool, Dict]: Success flag and drill collar details
        """
        client = get_api_client()
        if not client.is_authenticated():
            return False, {}

        # Use correct drill-collars endpoint
        success, data = client.make_request('GET', f'drill-collars/{drill_hole_id}/')
        if success:
            # Defense-in-depth: validate the returned resource belongs to authorized scope
            project_id = data.get('project_id') or (data.get('project', {}).get('id') if isinstance(data.get('project'), dict) else None)
            if project_id and not client.is_authorized_project(project_id):
                logger.warning("Received resource from unauthorized project %s", project_id)
                return False, {}
            return True, data
        return False, {}

    @staticmethod
    def get_surveys(drill_hole_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the surveys for a drill hole.

        Args:
            drill_hole_id: The ID of the drill collar
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of surveys
        """
        client = get_api_client()
        if not client.is_authenticated():
            return False, []

        # Fetch surveys with pagination
        return client.get_all_paginated(
            'drill-surveys/',
            params={'bhid': drill_hole_id},
            progress_callback=progress_callback
        )

    @staticmethod
    def get_all_surveys_for_project(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Dict[int, List[Dict[str, Any]]]]:
        """Get ALL surveys for a project in a single API call.

        This is much more efficient than calling get_surveys() for each drill hole.

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, Dict[hole_id, List[surveys]]]: Success flag and surveys grouped by drill hole ID
        """
        logger.debug("Bulk fetching all surveys for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        # Fetch ALL surveys for the project with pagination
        success, surveys = client.get_all_paginated(
            'drill-surveys/',
            params={'project_id': project_id},
            progress_callback=progress_callback,
            limit=500  # Use larger pages for bulk fetches
        )

        if not success:
            logger.error("Failed to fetch surveys")
            return False, {}

        logger.debug("Fetched %d surveys", len(surveys))

        # Group by drill hole ID (bhid)
        # Note: bhid can be either an integer ID or a nested object with metadata
        surveys_by_hole = {}
        surveys_by_name = {}  # Fallback index by hole name

        for survey in surveys:
            bhid = survey.get('bhid')
            hole_id = None
            hole_name = None

            # Extract the actual integer ID from bhid
            if isinstance(bhid, dict):
                # bhid is a nested object
                hole_id = bhid.get('id')  # Try to get integer ID
                hole_name = bhid.get('hole_id') or bhid.get('name')  # Get hole name

                if not hole_id:
                    # No ID in bhid object - we'll need to match by name later
                    if hole_name:
                        if hole_name not in surveys_by_name:
                            surveys_by_name[hole_name] = []
                        surveys_by_name[hole_name].append(survey)
                    continue
            elif isinstance(bhid, int):
                # bhid is already an integer ID
                hole_id = bhid
            else:
                # Try bhid_id as fallback
                hole_id = survey.get('bhid_id')
                if not hole_id:
                    logger.warning("Survey missing bhid: %s", survey.get('id', 'unknown'))
                    continue

            if hole_id:
                if hole_id not in surveys_by_hole:
                    surveys_by_hole[hole_id] = []
                surveys_by_hole[hole_id].append(survey)

        logger.debug("Grouped surveys into %d drill holes by ID", len(surveys_by_hole))
        if surveys_by_name:
            logger.debug("Found %d drill holes indexed by name (will need name-to-ID mapping)", len(surveys_by_name))

        # Return surveys indexed by ID, and by name as a special key if needed
        # Store name-indexed surveys with string keys for later matching
        result = surveys_by_hole.copy()
        for name, surveys_list in surveys_by_name.items():
            result[f"name:{name}"] = surveys_list

        return True, result

    @staticmethod
    def get_samples(drill_hole_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the samples for a drill hole.

        Note: Assay data is automatically included in the sample response.

        Args:
            drill_hole_id: The ID of the drill collar
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of samples (with nested assay data)
        """
        client = get_api_client()
        if not client.is_authenticated():
            return False, []

        # Fetch samples with pagination
        return client.get_all_paginated(
            'drill-samples/',
            params={'bhid': drill_hole_id},
            progress_callback=progress_callback
        )

    @staticmethod
    def get_all_samples_for_project(project_id: int, assay_config_id: int = None,
                                     progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Dict[int, List[Dict[str, Any]]]]:
        """Get ALL samples for a project in a single API call.

        This is much more efficient than calling get_samples() for each drill hole.

        Args:
            project_id: The ID of the project
            assay_config_id: (v1.4 REQUIRED) AssayRangeConfiguration ID for color/element selection
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, Dict[hole_id, List[samples]]]: Success flag and samples grouped by drill hole ID
        """
        logger.debug("Bulk fetching all samples for project %d", project_id)

        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        # Build params
        params = {'project_id': project_id}

        # v1.4: REQUIRED - Include assay_config_id for server-side config application
        if assay_config_id:
            params['assay_config_id'] = assay_config_id
            logger.debug("Using AssayRangeConfiguration ID: %s", assay_config_id)
        else:
            logger.warning("assay_config_id not provided, samples may lack assay configuration")

        # Fetch ALL samples for the project with pagination
        success, samples = client.get_all_paginated(
            'drill-samples/',
            params=params,
            progress_callback=progress_callback,
            limit=500  # Use larger pages for bulk fetches
        )

        if not success:
            logger.error("Failed to fetch samples")
            return False, {}

        logger.debug("Fetched %d samples", len(samples))

        # Group by drill hole ID (bhid)
        # Note: bhid can be either an integer ID or a nested object with metadata
        samples_by_hole = {}
        samples_by_name = {}  # Fallback index by hole name

        for sample in samples:
            bhid = sample.get('bhid')
            hole_id = None
            hole_name = None

            # Extract the actual integer ID from bhid
            if isinstance(bhid, dict):
                # bhid is a nested object
                hole_id = bhid.get('id')  # Try to get integer ID
                hole_name = bhid.get('hole_id') or bhid.get('name')  # Get hole name

                if not hole_id:
                    # No ID in bhid object - we'll need to match by name later
                    if hole_name:
                        if hole_name not in samples_by_name:
                            samples_by_name[hole_name] = []
                        samples_by_name[hole_name].append(sample)
                    continue
            elif isinstance(bhid, int):
                # bhid is already an integer ID
                hole_id = bhid
            else:
                # Try bhid_id as fallback
                hole_id = sample.get('bhid_id')
                if not hole_id:
                    logger.warning("Sample missing bhid: %s", sample.get('id', 'unknown'))
                    continue

            if hole_id:
                if hole_id not in samples_by_hole:
                    samples_by_hole[hole_id] = []
                samples_by_hole[hole_id].append(sample)

        logger.debug("Grouped samples into %d drill holes by ID", len(samples_by_hole))
        if samples_by_name:
            logger.debug("Found %d drill holes indexed by name (will need name-to-ID mapping)", len(samples_by_name))

        # Return samples indexed by ID, and by name as a special key if needed
        # Store name-indexed samples with string keys for later matching
        result = samples_by_hole.copy()
        for name, samples_list in samples_by_name.items():
            result[f"name:{name}"] = samples_list

        return True, result

    # Note: get_assays method removed - assay data is now automatically included
    # in the drill-samples response as nested data

    @staticmethod
    def get_assay_range_configurations(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get assay range configurations for a project.

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of assay range configurations
        """
        logger.debug("Fetching assay range configurations for project %d", project_id)
        client = get_api_client()

        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # Fetch assay range configurations with pagination
        success, configs = client.get_all_paginated(
            'assay-range-configurations/',
            params={'project_id': project_id},
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Fetched %d assay range configurations", len(configs))
            return True, configs
        else:
            logger.error("Failed to fetch assay range configurations")
            return False, []

    @staticmethod
    def format_surveys_for_desurvey(surveys: List[Dict[str, Any]]) -> List[Tuple[float, float, float]]:
        """Format survey data for use with the desurvey module.

        Args:
            surveys: List of survey dictionaries from the API

        Returns:
            List of tuples (azimuth, dip, depth) for desurvey calculations
        """
        formatted_surveys = []
        for survey in surveys:
            azimuth = survey.get('azimuth', 0.0)
            dip = survey.get('dip', -90.0)  # Default to vertical down
            depth = survey.get('depth', 0.0)
            formatted_surveys.append((azimuth, dip, depth))

        # Sort by depth
        formatted_surveys.sort(key=lambda x: x[2])

        return formatted_surveys

    @staticmethod
    def format_samples_for_visualization(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format sample data for visualization.

        Note: The API now returns samples with nested assay data, so we extract
        the element values from the assay.elements array.

        Args:
            samples: List of sample dictionaries from the API (with nested assay data)

        Returns:
            List of sample dictionaries with assay values included
        """
        formatted_samples = []
        for sample in samples:
            sample_id = sample.get('id')
            depth_from = sample.get('depth_from', 0.0)
            depth_to = sample.get('depth_to', 0.0)
            sample_name = sample.get('name', f"Sample_{sample_id}")

            # Extract assay data from nested structure
            # API returns: sample.assay.elements = [{"element": "Au", "value": 2.45}, ...]
            values = {}
            assay_data = sample.get('assay')
            if assay_data and isinstance(assay_data, dict):
                elements = assay_data.get('elements', [])
                for element_data in elements:
                    element = element_data.get('element', '')
                    value = element_data.get('value', 0.0)
                    if element:
                        values[element] = value

            formatted_sample = {
                'depth_from': depth_from,
                'depth_to': depth_to,
                'name': sample_name,
                'values': values
            }

            formatted_samples.append(formatted_sample)

        # Sort by depth
        formatted_samples.sort(key=lambda x: x['depth_from'])

        return formatted_samples

    @staticmethod
    def extract_collar_coordinates(collar: Dict[str, Any]) -> Tuple[float, float, float, float]:
        """Extract collar coordinates from API response.

        The API returns coordinates in multiple formats (API Phase 2B - Jan 2025):
        1. **Proj4 Local Grid** (PREFERRED FOR BLENDER):
           - proj4_easting, proj4_northing, proj4_elevation
           - Small positive numbers optimized for Blender viewport
           - Already transformed to local coordinate system
        2. Project EPSG: easting, northing, elevation, project_epsg
        3. WGS84: wgs84_latitude, wgs84_longitude
        4. Original Input: latitude, longitude (legacy format)

        Args:
            collar: Collar data dictionary from API

        Returns:
            Tuple of (x, y, z, total_depth) - coordinates in Blender's local space
        """
        # PRIORITY 1: Use proj4 local coordinates (API Phase 2B)
        # These are optimized for Blender and require NO client-side transformations
        proj4_easting = collar.get('proj4_easting')
        proj4_northing = collar.get('proj4_northing')
        proj4_elevation = collar.get('proj4_elevation')

        if proj4_easting is not None and proj4_northing is not None:
            # IDEAL CASE: API provides local coordinates ready for Blender!
            return (
                float(proj4_easting),
                float(proj4_northing),
                float(proj4_elevation if proj4_elevation is not None else collar.get('elevation', 0.0)),
                float(collar.get('total_depth', 0.0))
            )

        # PRIORITY 2: Try project EPSG coordinates
        easting = collar.get('easting')
        northing = collar.get('northing')

        if easting is not None and northing is not None:
            # Project CRS coordinates (may be large numbers)
            return (
                float(easting),
                float(northing),
                float(collar.get('elevation', 0.0)),
                float(collar.get('total_depth', 0.0))
            )

        # PRIORITY 3: Fallback to WGS84 lat/long (legacy support)
        # Note: This is approximate and won't preserve true distances
        wgs84_latitude = collar.get('wgs84_latitude') or collar.get('latitude')
        wgs84_longitude = collar.get('wgs84_longitude') or collar.get('longitude')

        if wgs84_latitude is not None and wgs84_longitude is not None:
            # Use simple scaling to pseudo-meters
            # 1 degree latitude ~ 111,320 meters
            # 1 degree longitude ~ 111,320 * cos(latitude) meters
            lat_scale = 111320.0
            lon_scale = 111320.0 * np.cos(np.radians(wgs84_latitude))

            easting = wgs84_longitude * lon_scale
            northing = wgs84_latitude * lat_scale

            return (
                float(easting),
                float(northing),
                float(collar.get('elevation', 0.0)),
                float(collar.get('total_depth', 0.0))
            )

        # Last resort - return zeros
        logger.warning("Collar has no valid coordinates")
        return (0.0, 0.0, collar.get('elevation', 0.0), collar.get('total_depth', 0.0))


    @staticmethod
    def fetch_all_project_data(project_id: int, company_id: int,
                                project_name: str,
                                deleted_since: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Fetch all drill hole data for a project in a single batch.

        This function makes minimal API calls to retrieve all data:
        - 1 call for project details (coordinate system metadata)
        - 1 call for collars (with deletion sync support)
        - 1 call for surveys
        - 1 call for samples
        - 1 call for lithology (if available)
        - 1 call for alteration (if available)

        Args:
            project_id: Project ID
            company_id: Company ID
            project_name: Project name
            deleted_since: Optional ISO timestamp for incremental deletion sync.
                          If provided, only returns deleted_ids for records deleted
                          after this time. Use the sync_timestamp from a previous
                          sync response.

        Returns:
            Tuple of (success, data_dictionary)
            data_dictionary contains:
                - project_metadata: Project-level coordinate system info
                - collars: List of collar dictionaries
                - surveys: Dict[bhid, List] of survey data grouped by hole
                - samples: Dict[bhid, List] of sample data grouped by hole
                - lithology: Dict[bhid, List] of lithology data grouped by hole
                - alteration: Dict[bhid, List] of alteration data grouped by hole
                - deleted_collar_ids: List of soft-deleted collar IDs (new)
                - sync_timestamp: ISO timestamp for next sync (new)
        """
        logger.debug("Fetching all project data for project %d", project_id)
        if deleted_since:
            logger.debug("Incremental deletion sync from: %s", deleted_since)

        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        result_data = {
            'project_id': project_id,
            'company_id': company_id,
            'project_name': project_name,
            'project_metadata': {},
            'collars': [],
            'surveys': {},
            'samples': {},
            'lithology': {},
            'alteration': {},
            'deleted_collar_ids': [],  # New: IDs of soft-deleted collars
            'sync_timestamp': None,  # New: Timestamp for next sync
        }

        # 0. Fetch project details for coordinate system metadata
        logger.debug("[0/5] Fetching project metadata")
        try:
            success, project_data = client.make_request('GET', f'projects/{project_id}/')
            if success and project_data:
                # Extract coordinate system metadata (API Phase 2B)
                metadata = {
                    'proj4_string': project_data.get('proj4_string'),
                    'blender_origin_x': project_data.get('blender_origin_x'),
                    'blender_origin_y': project_data.get('blender_origin_y'),
                    'blender_origin_epsg': project_data.get('blender_origin_epsg'),
                    'blender_rotation_degrees': project_data.get('blender_rotation_degrees'),
                    'project_epsg': project_data.get('project_epsg'),
                    'name': project_data.get('name'),
                    'description': project_data.get('description')
                }
                result_data['project_metadata'] = metadata
                logger.debug("Retrieved project metadata")
            else:
                logger.warning("Could not fetch project metadata")
        except Exception as e:
            logger.warning("Failed to fetch project metadata: %s", e)

        # 1. Fetch all collars for the project (with deletion sync)
        logger.debug("[1/5] Fetching collars (with deletion sync)")
        success, collar_result = GeoDBData.get_drill_holes_with_sync(
            project_id,
            deleted_since=deleted_since
        )
        if not success:
            logger.error("Failed to fetch collars")
            return False, {}

        collars = collar_result.get('results', [])
        deleted_ids = collar_result.get('deleted_ids', [])
        sync_timestamp = collar_result.get('sync_timestamp')

        logger.debug("Retrieved %d active collars", len(collars))
        if deleted_ids:
            logger.debug("Detected %d soft-deleted collars", len(deleted_ids))
        if sync_timestamp:
            logger.debug("Sync timestamp recorded for next sync")

        result_data['collars'] = collars
        result_data['deleted_collar_ids'] = deleted_ids
        result_data['sync_timestamp'] = sync_timestamp

        # Extract hole IDs for reference
        hole_ids = [collar.get('id') for collar in collars if collar.get('id')]
        result_data['hole_ids'] = hole_ids

        # 2. Fetch all surveys for the project
        logger.debug("[2/5] Fetching surveys (bulk)")
        success, surveys_by_hole = GeoDBData.get_all_surveys_for_project(project_id)
        if not success:
            logger.warning("Failed to fetch surveys in bulk")
            result_data['surveys'] = {}
        else:
            logger.debug("Retrieved surveys for %d holes", len(surveys_by_hole))
            result_data['surveys'] = surveys_by_hole

        # 3. Fetch all samples for the project
        logger.debug("[3/5] Fetching samples (bulk)")
        success, samples_by_hole = GeoDBData.get_all_samples_for_project(project_id)
        if not success:
            logger.warning("Failed to fetch samples in bulk")
            result_data['samples'] = {}
        else:
            total_samples = sum(len(v) for v in samples_by_hole.values())
            logger.debug("Retrieved %d samples across %d holes", total_samples, len(samples_by_hole))
            result_data['samples'] = samples_by_hole

        # 4. Fetch lithology data (if endpoint exists)
        logger.debug("[4/5] Fetching lithology")
        try:
            success, lithology_list = client.get_all_paginated(
                'lithology/',
                params={'project': project_id},
                limit=500
            )

            if success and lithology_list:
                # Group by bhid
                lithology_by_hole = {}
                for lith in lithology_list:
                    bhid = lith.get('bhid')

                    # Handle bhid as object or int
                    if isinstance(bhid, dict):
                        bhid_id = bhid.get('id')
                        bhid_name = bhid.get('hole_id')

                        if bhid_id:
                            if bhid_id not in lithology_by_hole:
                                lithology_by_hole[bhid_id] = []
                            lithology_by_hole[bhid_id].append(lith)

                        if bhid_name:
                            name_key = f"name:{bhid_name}"
                            if name_key not in lithology_by_hole:
                                lithology_by_hole[name_key] = []
                            lithology_by_hole[name_key].append(lith)
                    elif isinstance(bhid, (int, str)):
                        if bhid not in lithology_by_hole:
                            lithology_by_hole[bhid] = []
                        lithology_by_hole[bhid].append(lith)

                result_data['lithology'] = lithology_by_hole
                total_lith = sum(len(v) for v in lithology_by_hole.values())
                logger.debug("Retrieved %d lithology intervals across %d holes", total_lith, len(lithology_by_hole))
            else:
                logger.debug("No lithology data available")
        except Exception as e:
            logger.warning("Failed to fetch lithology: %s", e)
            result_data['lithology'] = {}

        # 5. Fetch assay range configurations
        logger.debug("[5/6] Fetching assay range configurations")
        try:
            success, assay_configs = GeoDBData.get_assay_range_configurations(project_id)
            if success:
                result_data['assay_range_configs'] = assay_configs
                logger.debug("Retrieved %d assay range configurations", len(assay_configs))
            else:
                logger.debug("No assay range configurations available")
                result_data['assay_range_configs'] = []
        except Exception as e:
            logger.warning("Failed to fetch assay range configurations: %s", e)
            result_data['assay_range_configs'] = []

        # 6. Fetch alteration data (if endpoint exists)
        logger.debug("[6/6] Fetching alteration")
        try:
            success, alteration_list = client.get_all_paginated(
                'alteration/',
                params={'project': project_id},
                limit=500
            )

            if success and alteration_list:
                # Group by bhid
                alteration_by_hole = {}
                for alt in alteration_list:
                    bhid = alt.get('bhid')

                    # Handle bhid as object or int
                    if isinstance(bhid, dict):
                        bhid_id = bhid.get('id')
                        bhid_name = bhid.get('hole_id')

                        if bhid_id:
                            if bhid_id not in alteration_by_hole:
                                alteration_by_hole[bhid_id] = []
                            alteration_by_hole[bhid_id].append(alt)

                        if bhid_name:
                            name_key = f"name:{bhid_name}"
                            if name_key not in alteration_by_hole:
                                alteration_by_hole[name_key] = []
                            alteration_by_hole[name_key].append(alt)
                    elif isinstance(bhid, (int, str)):
                        if bhid not in alteration_by_hole:
                            alteration_by_hole[bhid] = []
                        alteration_by_hole[bhid].append(alt)

                result_data['alteration'] = alteration_by_hole
                total_alt = sum(len(v) for v in alteration_by_hole.values())
                logger.debug("Retrieved %d alteration intervals across %d holes", total_alt, len(alteration_by_hole))
            else:
                logger.debug("No alteration data available")
        except Exception as e:
            logger.warning("Failed to fetch alteration: %s", e)
            result_data['alteration'] = {}

        # Extract available elements, lithologies, and alterations
        available_elements = set()
        available_lithologies = set()
        available_alterations = set()

        # Extract elements from samples
        for hole_samples in result_data['samples'].values():
            for sample in hole_samples:
                # Check if sample has assay data with elements
                assay = sample.get('assay')
                if assay and isinstance(assay, dict):
                    elements = assay.get('elements', [])
                    for element in elements:
                        if isinstance(element, dict):
                            elem_name = element.get('element')
                            if elem_name:
                                available_elements.add(elem_name)

        # Extract lithology types
        for hole_lith in result_data['lithology'].values():
            for lith in hole_lith:
                lith_type = lith.get('lithology') or lith.get('type')
                if lith_type:
                    available_lithologies.add(lith_type)

        # Extract alteration types
        for hole_alt in result_data['alteration'].values():
            for alt in hole_alt:
                alt_type = alt.get('alteration') or alt.get('type')
                if alt_type:
                    available_alterations.add(alt_type)

        result_data['available_elements'] = sorted(list(available_elements))
        result_data['available_lithologies'] = sorted(list(available_lithologies))
        result_data['available_alterations'] = sorted(list(available_alterations))

        logger.debug(
            "Bulk data fetch complete: collars=%d, surveys=%d holes, samples=%d holes, "
            "lithology=%d holes, alteration=%d holes, assay_configs=%d, "
            "elements=%d, lithologies=%d, alterations=%d",
            len(result_data['collars']),
            len(result_data['surveys']),
            len(result_data['samples']),
            len(result_data['lithology']),
            len(result_data['alteration']),
            len(result_data['assay_range_configs']),
            len(result_data['available_elements']),
            len(result_data['available_lithologies']),
            len(result_data['available_alterations'])
        )

        if result_data.get('deleted_collar_ids'):
            logger.debug("Deleted collar IDs count: %d", len(result_data['deleted_collar_ids']))
        if result_data.get('sync_timestamp'):
            logger.debug("Sync timestamp recorded")

        return True, result_data

    @staticmethod
    def get_drill_traces(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Dict[int, Dict[str, Any]]]:
        """Get drill traces (desurveyed paths) for all holes in a project.

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, Dict[hole_id, trace_data]]: Success flag and traces by hole ID
        """
        logger.debug("Fetching drill traces for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        # Fetch drill traces with pagination
        success, traces = client.get_all_paginated(
            'drill-traces/',
            params={'project_id': project_id},
            progress_callback=progress_callback
        )

        if not success:
            logger.error("Failed to fetch drill traces")
            return False, {}

        logger.debug("Fetched %d drill traces", len(traces))

        # Group by drill hole ID
        traces_by_hole = {}
        for trace in traces:
            bhid = trace.get('bhid')
            if isinstance(bhid, dict):
                hole_id = bhid.get('id')
            else:
                hole_id = bhid

            if hole_id:
                traces_by_hole[hole_id] = trace

        logger.debug("Organized %d traces by hole ID", len(traces_by_hole))
        return True, traces_by_hole

    @staticmethod
    def get_drill_trace_detail(trace_id: int) -> Tuple[bool, Dict[str, Any]]:
        """Get full drill trace detail including coordinate arrays.

        Args:
            trace_id: The ID of the drill trace

        Returns:
            Tuple[bool, Dict]: Success flag and full trace data with coordinates
        """
        logger.debug("Fetching drill trace detail %d", trace_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        endpoint = f'drill-traces/{trace_id}/'
        success, data = client.make_request('GET', endpoint)

        if not success:
            logger.error("Failed to fetch trace detail")
            return False, {}

        # Check if trace_data exists
        trace_data = data.get('trace_data', {})
        if trace_data:
            coords = trace_data.get('coords', [])
            depths = trace_data.get('depths', [])
            logger.debug("Retrieved trace with %d coordinate points", len(coords))
            logger.debug("Depth range: %s to %sm",
                         depths[0] if depths else 0,
                         depths[-1] if depths else 0)
        else:
            logger.warning("No trace_data in response")

        return True, data

    @staticmethod
    def get_lithology_sets(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get lithology sets for a project.

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of lithology sets
        """
        logger.debug("Fetching lithology sets for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # Fetch lithology sets with pagination (API uses 'project' not 'project_id')
        success, sets = client.get_all_paginated(
            'drill-lithology-sets/',
            params={'project': project_id},
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Retrieved %d lithology sets", len(sets))
            return True, sets
        else:
            logger.error("Failed to fetch lithology sets")
            return False, []

    @staticmethod
    def get_alteration_sets(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get alteration sets for a project.

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of alteration sets
        """
        logger.debug("Fetching alteration sets for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # Fetch alteration sets with pagination (API uses 'project' not 'project_id')
        success, sets = client.get_all_paginated(
            'drill-alteration-sets/',
            params={'project': project_id},
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Retrieved %d alteration sets", len(sets))
            return True, sets
        else:
            logger.error("Failed to fetch alteration sets")
            return False, []

    @staticmethod
    def get_mineralization_sets(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get mineralization sets for a project.

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of mineralization sets
        """
        logger.debug("Fetching mineralization sets for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # Fetch mineralization sets with pagination (API uses 'project' not 'project_id')
        success, sets = client.get_all_paginated(
            'drill-mineralization-sets/',
            params={'project': project_id},
            progress_callback=progress_callback
        )

        if success:
            logger.debug("Retrieved %d mineralization sets", len(sets))
            return True, sets
        else:
            logger.error("Failed to fetch mineralization sets")
            return False, []

    @staticmethod
    def get_lithologies_for_project(project_id: int, set_id: int = None,
                                     progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Dict[str, List[Dict[str, Any]]]]:
        """Get all lithology intervals for a project, grouped by drill hole name.

        Args:
            project_id: The ID of the project
            set_id: Optional lithology set ID to filter by
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, Dict[hole_name, List[intervals]]]: Success flag and lithologies by hole name
        """
        logger.debug("Fetching lithologies for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        # Build params
        params = {'project_id': project_id}
        if set_id is not None:
            params['drill_lithology_set'] = set_id  # API uses 'drill_lithology_set' parameter

        # Fetch lithologies with pagination
        success, lithologies = client.get_all_paginated(
            'drill-lithologies/',
            params=params,
            progress_callback=progress_callback,
            limit=500  # Use larger pages for bulk fetches
        )

        if not success:
            logger.error("Failed to fetch lithologies")
            return False, {}

        logger.debug("Fetched %d lithology intervals", len(lithologies))

        # Group by drill hole name (from bhid dict)
        lithologies_by_hole = {}
        for lith in lithologies:
            bhid = lith.get('bhid')
            hole_name = None

            if isinstance(bhid, dict):
                # bhid is a dict like {"hole_id": "AUX20-2", "project": "...", "company": "..."}
                hole_name = bhid.get('hole_id')
            elif isinstance(bhid, str):
                hole_name = bhid
            else:
                # Fallback to numeric ID if present
                hole_name = str(bhid) if bhid else None

            if hole_name:
                if hole_name not in lithologies_by_hole:
                    lithologies_by_hole[hole_name] = []
                lithologies_by_hole[hole_name].append(lith)

        logger.debug("Organized %d holes with lithology data", len(lithologies_by_hole))
        return True, lithologies_by_hole

    @staticmethod
    def get_alterations_for_project(project_id: int, set_id: int = None,
                                     progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Dict[str, List[Dict[str, Any]]]]:
        """Get all alteration intervals for a project, grouped by drill hole name.

        Args:
            project_id: The ID of the project
            set_id: Optional alteration set ID to filter by
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, Dict[hole_name, List[intervals]]]: Success flag and alterations by hole name
        """
        logger.debug("Fetching alterations for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        # Build params
        params = {'project_id': project_id}
        if set_id is not None:
            params['drill_alteration_set'] = set_id  # API uses 'drill_alteration_set' parameter

        # Fetch alterations with pagination
        success, alterations = client.get_all_paginated(
            'drill-alterations/',
            params=params,
            progress_callback=progress_callback,
            limit=500  # Use larger pages for bulk fetches
        )

        if not success:
            logger.error("Failed to fetch alterations")
            return False, {}

        logger.debug("Fetched %d alteration intervals", len(alterations))

        # Group by drill hole name (from bhid dict)
        alterations_by_hole = {}
        for alt in alterations:
            bhid = alt.get('bhid')
            hole_name = None

            if isinstance(bhid, dict):
                # bhid is a dict like {"hole_id": "AUX20-2", "project": "...", "company": "..."}
                hole_name = bhid.get('hole_id')
            elif isinstance(bhid, str):
                hole_name = bhid
            else:
                # Fallback to numeric ID if present
                hole_name = str(bhid) if bhid else None

            if hole_name:
                if hole_name not in alterations_by_hole:
                    alterations_by_hole[hole_name] = []
                alterations_by_hole[hole_name].append(alt)

        logger.debug("Organized %d holes with alteration data", len(alterations_by_hole))
        return True, alterations_by_hole

    @staticmethod
    def get_mineralizations_for_project(project_id: int, set_id: int = None,
                                         progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Dict[str, List[Dict[str, Any]]]]:
        """Get all mineralization intervals for a project, grouped by drill hole name.

        Args:
            project_id: The ID of the project
            set_id: Optional mineralization set ID to filter by
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, Dict[hole_name, List[intervals]]]: Success flag and mineralizations by hole name
        """
        logger.debug("Fetching mineralizations for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {}

        # Build params
        params = {'project_id': project_id}
        if set_id is not None:
            params['drill_mineralization_set'] = set_id  # API uses 'drill_mineralization_set' parameter

        # Fetch mineralizations with pagination
        success, mineralizations = client.get_all_paginated(
            'drill-mineralizations/',
            params=params,
            progress_callback=progress_callback,
            limit=500  # Use larger pages for bulk fetches
        )

        if not success:
            logger.error("Failed to fetch mineralizations")
            return False, {}

        logger.debug("Fetched %d mineralization intervals", len(mineralizations))

        # Group by drill hole name (from bhid dict)
        mineralizations_by_hole = {}
        for min_interval in mineralizations:
            bhid = min_interval.get('bhid')
            hole_name = None

            if isinstance(bhid, dict):
                # bhid is a dict like {"hole_id": "AUX20-2", "project": "...", "company": "..."}
                hole_name = bhid.get('hole_id')
            elif isinstance(bhid, str):
                hole_name = bhid
            else:
                # Fallback to numeric ID if present
                hole_name = str(bhid) if bhid else None

            if hole_name:
                if hole_name not in mineralizations_by_hole:
                    mineralizations_by_hole[hole_name] = []
                mineralizations_by_hole[hole_name].append(min_interval)

        logger.debug("Organized %d holes with mineralization data", len(mineralizations_by_hole))
        return True, mineralizations_by_hole

    @staticmethod
    def get_terrain_mesh(project_code: str, resolution: str = 'low') -> Tuple[bool, Dict[str, Any]]:
        """
        Get terrain mesh data with textures for a project.

        This method:
        1. Fetches latest elevation data from /api/v1/projects/{code}/elevation/latest/
        2. Extracts terrain_meshes CDN URLs from response
        3. Downloads mesh JSON directly from CDN
        4. Returns mesh data ready for Blender

        Args:
            project_code: The project code (e.g., 'PROJ001')
            resolution: Mesh resolution - 'very_low', 'low', or 'medium'
                       very_low: ~62k vertices (fast, mobile)
                       low: ~250k vertices (balanced, default)
                       medium: ~1M vertices (high detail)

        Returns:
            Tuple[bool, Dict]: Success flag and mesh data dict with:
                - positions: [x1, y1, z1, x2, y2, z2, ...] vertex coordinates
                - indices: [i1, i2, i3, ...] triangle indices
                - normals: [nx1, ny1, nz1, ...] vertex normals (optional)
                - uvs: [u1, v1, u2, v2, ...] texture coordinates (optional)
                - bounds: {minX, maxX, minY, maxY, minZ, maxZ}
                - satellite_texture_url: CDN URL for satellite imagery
                - topo_texture_url: CDN URL for topographic map
        """
        logger.debug("Fetching terrain mesh for project %s, resolution %s", project_code, resolution)

        import requests

        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {'error': 'Not authenticated'}

        # Validate resolution
        valid_resolutions = ['very_low', 'low', 'medium']
        if resolution not in valid_resolutions:
            logger.error("Invalid resolution '%s'. Must be one of: %s", resolution, valid_resolutions)
            return False, {'error': f"Invalid resolution. Must be one of: {', '.join(valid_resolutions)}"}

        # Step 1: Get latest elevation data
        elevation_endpoint = f'projects/{project_code}/elevation/latest/'
        logger.debug("Step 1: Requesting elevation data")

        success, elevation_data = client.make_request('GET', elevation_endpoint)

        if not success:
            error_msg = elevation_data.get('error', 'No elevation data available') if isinstance(elevation_data, dict) else str(elevation_data)
            logger.error("Failed to fetch elevation data: %s", error_msg)
            return False, {'error': error_msg}

        # Step 2: Extract terrain mesh URL
        terrain_meshes = elevation_data.get('terrain_meshes', {})
        if resolution not in terrain_meshes:
            error_msg = f"Terrain mesh resolution '{resolution}' not available"
            logger.error("%s", error_msg)
            logger.debug("Available resolutions: %s", list(terrain_meshes.keys()))
            return False, {'error': error_msg}

        mesh_url = terrain_meshes[resolution]
        logger.debug("Step 2: Mesh URL obtained")

        # Step 3: Download mesh JSON from CDN
        logger.debug("Step 3: Downloading mesh data from CDN")

        try:
            # The mesh URL is a pre-signed CDN URL that includes authentication
            # in query parameters, so no additional headers are needed
            response = requests.get(mesh_url, timeout=60)
            response.raise_for_status()
            mesh_data = response.json()
        except Exception as e:
            error_msg = f"Failed to download mesh: {str(e)}"
            logger.error("%s", error_msg)
            return False, {'error': error_msg}

        # Normalize field names - server may use 'vertices' instead of 'positions'
        if 'vertices' in mesh_data and 'positions' not in mesh_data:
            mesh_data['positions'] = mesh_data['vertices']
            logger.debug("Normalized 'vertices' to 'positions'")

        # Validate mesh structure
        required_fields = ['positions', 'indices']
        missing_fields = [f for f in required_fields if f not in mesh_data]
        if missing_fields:
            logger.debug("Mesh data keys received: %s", list(mesh_data.keys()))
            error_msg = f"Invalid mesh data: missing {missing_fields}"
            logger.error("%s", error_msg)
            return False, {'error': error_msg}

        # Add texture URLs from elevation data
        mesh_data['satellite_texture_url'] = elevation_data.get('satellite_imagery_url')
        mesh_data['topo_texture_url'] = elevation_data.get('topo_imagery_url')

        # Log stats
        num_vertices = len(mesh_data['positions']) // 3
        num_triangles = len(mesh_data['indices']) // 3
        logger.debug("Received terrain mesh: %d vertices, %d triangles", num_vertices, num_triangles)

        if 'bounds' in mesh_data:
            logger.debug("Terrain mesh bounds present")

        if mesh_data.get('satellite_texture_url'):
            logger.debug("Satellite texture available")
        if mesh_data.get('topo_texture_url'):
            logger.debug("Topo texture available")

        return True, mesh_data

    @staticmethod
    def get_terrain_textures(project_code: str, resolution: str = 'low') -> Tuple[bool, Dict[str, Any]]:
        """
        Get available terrain textures from the elevation API.

        This method calls the elevation/latest endpoint which returns texture URLs
        for satellite imagery, topographic maps, and any custom textures.

        Args:
            project_code: The project code (e.g., 'ECBSDT5')
            resolution: Mesh resolution for the request (not currently used for textures)

        Returns:
            Tuple[bool, Dict]: Success flag and textures dict with:
                - satellite: URL or None
                - topo: URL or None
                - available_textures: [
                    {'id': int, 'name': str, 'type': str, 'url': str, 'display_order': int},
                    ...
                  ]
        """
        logger.debug("Fetching terrain textures for project %s", project_code)

        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {'error': 'Not authenticated'}

        # Use the elevation/latest endpoint which supports token auth
        elevation_endpoint = f'projects/{project_code}/elevation/latest/'
        logger.debug("Requesting elevation endpoint")

        success, elevation_data = client.make_request('GET', elevation_endpoint)

        if not success:
            error_msg = elevation_data.get('error', 'No elevation data available') if isinstance(elevation_data, dict) else str(elevation_data)
            logger.error("Failed to fetch elevation data: %s", error_msg)
            return False, {'error': error_msg}

        # Extract texture URLs from elevation data
        satellite_url = elevation_data.get('satellite_imagery_url')
        topo_url = elevation_data.get('topo_imagery_url')

        # Check for available_textures directly in response (v1.4+ API)
        # This is the preferred source as it includes all texture types with their URLs
        available_textures = elevation_data.get('available_textures', [])

        # If available_textures is empty but we have legacy URLs, build the list manually
        if not available_textures:
            if satellite_url:
                available_textures.append({
                    'id': 1,
                    'name': 'Satellite Imagery',
                    'type': 'satellite',
                    'url': satellite_url,
                    'display_order': 1
                })

            if topo_url:
                available_textures.append({
                    'id': 2,
                    'name': 'Topographic Map',
                    'type': 'topo',
                    'url': topo_url,
                    'display_order': 2
                })

        logger.debug("Found %d available textures", len(available_textures))

        return True, {
            'satellite': satellite_url,
            'topo': topo_url,
            'available_textures': available_textures
        }

    @staticmethod
    def get_drill_pads_blender(project_id: int, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get drill pads with local grid coordinates for Blender visualization.

        Uses: GET /api/v2/drill-pads/blender/

        Args:
            project_id: The ID of the project
            progress_callback: Optional callback(fetched_count, total_count) for progress updates

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of drill pads with:
                - id: Pad ID
                - name: Pad name
                - elevation: Pad elevation (meters)
                - local_grid.vertices_2d: [[x, y], ...] polygon vertices
                - local_grid.centroid: [x, y, z] center point
                - location: GeoJSON Point (WGS84)
                - polygon: GeoJSON Polygon (WGS84)
        """
        logger.debug("Fetching drill pads (Blender) for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        # Fetch drill pads with pagination
        success, pads = client.get_all_paginated(
            'drill-pads/blender/',
            params={'project_id': project_id},
            progress_callback=progress_callback
        )

        if not success:
            logger.error("Failed to fetch drill pads")
            return False, []

        logger.debug("Retrieved %d drill pads", len(pads))

        return True, pads

    @staticmethod
    def create_planned_drill_hole(hole_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Create a planned drill hole via the API.

        Uses: POST /api/v1/drill-collars/

        Args:
            hole_data: Dictionary with:
                - name: Hole ID (e.g., "PLN-001")
                - project: {"name": "...", "company": "..."} (natural key)
                - pad: {"name": "...", "project": {...}} (natural key)
                - hole_status: "PL" (Planned)
                - hole_type: "DD", "RC", etc.
                - total_depth: Length in meters
                - azimuth: 0-360 degrees
                - dip: -90 to 90 degrees

        Returns:
            Tuple[bool, Dict]: Success flag and created collar data or error message
        """
        logger.debug("Creating planned drill hole")
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {'error': 'Not authenticated'}

        endpoint = 'drill-collars/'

        success, data = client.make_request('POST', endpoint, data=hole_data)

        if not success:
            error_msg = data.get('error', str(data)) if isinstance(data, dict) else str(data)
            logger.error("Failed to create drill hole: %s", error_msg)
            return False, {'error': error_msg}

        logger.debug("Created drill hole successfully")
        return True, data

    @staticmethod
    def get_planned_holes(project_id: int) -> Tuple[bool, List[Dict[str, Any]]]:
        """Fetch all planned holes (hole_status='PL') for a project.

        Uses: GET /api/v2/drill-collars/?project_id=X&hole_status=PL

        Args:
            project_id: The project ID to fetch planned holes for

        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of planned holes
        """
        logger.debug("Fetching planned holes for project %d", project_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, []

        success, holes = client.get_all_paginated(
            'drill-collars/',
            params={'project_id': project_id, 'hole_status': 'PL'}
        )

        if not success:
            logger.error("Failed to fetch planned holes")
            return False, []

        logger.debug("Retrieved %d planned holes", len(holes))
        return True, holes

    @staticmethod
    def update_planned_hole(hole_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Update an existing planned hole via the API using upsert (POST with natural keys).

        The API doesn't support PATCH by ID. Instead, use POST to the collection
        endpoint with natural keys for upsert operations.

        Uses: POST /api/v2/drill-collars/

        Args:
            hole_data: Dictionary with full hole data including natural keys
                       (name, project with name/company)

        Returns:
            Tuple[bool, Dict]: Success flag and updated hole data or error message
        """
        logger.debug("Updating planned hole (upsert)")
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {'error': 'Not authenticated'}

        endpoint = 'drill-collars/'

        success, data = client.make_request('POST', endpoint, data=hole_data)

        if not success:
            error_msg = data.get('error', str(data)) if isinstance(data, dict) else str(data)
            logger.error("Failed to update drill hole: %s", error_msg)
            return False, {'error': error_msg}

        logger.debug("Updated drill hole successfully")
        return True, data

    @staticmethod
    def delete_planned_hole(hole_id: int) -> Tuple[bool, Dict[str, Any]]:
        """Delete a planned hole from the server.

        Uses: DELETE /api/v2/drill-collars/{hole_id}/

        Args:
            hole_id: The ID of the hole to delete

        Returns:
            Tuple[bool, Dict]: Success flag and empty dict or error message
        """
        logger.debug("Deleting planned hole %d", hole_id)
        client = get_api_client()
        if not client.is_authenticated():
            logger.error("Client not authenticated")
            return False, {'error': 'Not authenticated'}

        endpoint = f'drill-collars/{hole_id}/'
        # Defense-in-depth: server validates ownership on DELETE
        logger.debug("Sending DELETE request")

        success, data = client.make_request('DELETE', endpoint)

        if not success:
            error_msg = data.get('error', str(data)) if isinstance(data, dict) else str(data)
            logger.error("Failed to delete drill hole: %s", error_msg)
            return False, {'error': error_msg}

        logger.debug("Deleted drill hole %d", hole_id)
        return True, {}
