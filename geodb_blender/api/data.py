"""
Data retrieval module for the geoDB Blender add-on.

This module handles retrieving data from the geoDB API, including
companies, projects, drill holes, and samples.
"""

import bpy
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

from .client import GeoDBAPIClient
from .auth import get_api_client

class GeoDBData:
    """Class for retrieving and managing geoDB data."""
    
    @staticmethod
    def get_companies() -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the list of companies the user has access to.
        
        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of companies
        """
        print("\n=== Getting Companies ===")
        client = get_api_client()
        print(f"API client authenticated: {client.is_authenticated()}")
        
        if not client.is_authenticated():
            print("ERROR: Client is not authenticated")
            return False, []
        
        # First check if we already have companies from login
        if client.companies:
            print(f"Using cached companies from login: {len(client.companies)} companies")
            print(f"Companies: {[c.get('name', 'Unknown') for c in client.companies]}")
            return True, client.companies
        
        # Otherwise fetch from API with pagination limit
        print("Fetching companies from API endpoint...")
        success, data = client.make_request('GET', 'companies/', params={'page_size': 1000})
        print(f"API request success: {success}")
        if success:
            # API returns paginated response with 'results' field
            if isinstance(data, dict) and 'results' in data:
                companies = data['results']
                print(f"Received {len(companies)} companies from paginated response")
                print(f"Companies: {[c.get('name', 'Unknown') for c in companies]}")
                return True, companies
            elif isinstance(data, list):
                print(f"Received {len(data)} companies as direct list")
                print(f"Data: {data}")
                return True, data
            else:
                print(f"WARNING: Unexpected data format: {type(data)}")
                return True, []
        else:
            print(f"ERROR: Failed to fetch companies. Response: {data}")
            return False, []
    
    @staticmethod
    def get_projects(company_id: int) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the list of projects for a company.
        
        Args:
            company_id: The ID of the company
            
        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of projects
        """
        print(f"\n=== Getting Projects for Company ID: {company_id} ===")
        client = get_api_client()
        print(f"API client authenticated: {client.is_authenticated()}")
        
        if not client.is_authenticated():
            print("ERROR: Client is not authenticated")
            return False, []
        
        # Try method 1: Filter by company_id parameter
        endpoint = f'projects/'
        params = {'company_id': company_id, 'page_size': 1000}
        print(f"Method 1 - Requesting endpoint: {endpoint} with params: {params}")
        success, data = client.make_request('GET', endpoint, params=params)
        print(f"API request success: {success}")
        
        # If method 1 fails with server error, try getting all projects and filtering client-side
        if not success and "500" in str(data):
            print("Server returned 500 error. Trying fallback: Get all projects and filter client-side")
            
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
            
            print(f"Company name for ID {company_id}: {company_name}")
            
            if company_name:
                # Try filtering by company name instead
                print(f"Trying with company name filter: company={company_name}")
                success, data = client.make_request('GET', 'projects/', params={'company': company_name})
                
                if success:
                    projects = data.get('results', data if isinstance(data, list) else [])
                    print(f"Got {len(projects)} projects using company name filter")
                    if projects:
                        print(f"Project names: {[p.get('name', 'Unknown') for p in projects]}")
                    return True, projects
            else:
                # Last resort: get all projects and filter by company name in response
                print("Could not find company name, getting all projects")
                success, data = client.make_request('GET', 'projects/')
                
                if success and company_name:
                    all_projects = data.get('results', data if isinstance(data, list) else [])
                    projects = [p for p in all_projects if p.get('company') == company_name]
                    print(f"Filtered {len(projects)} projects from {len(all_projects)} total projects")
                    return True, projects
        
        if success:
            # API returns paginated response with 'results' field
            if isinstance(data, dict) and 'results' in data:
                projects = data['results']
                print(f"Received {len(projects)} projects from paginated response")
                print(f"Project names: {[p.get('name', 'Unknown') for p in projects]}")
                return True, projects
            elif isinstance(data, list):
                print(f"Received {len(data)} projects as direct list")
                print(f"Project names: {[p.get('name', 'Unknown') for p in data]}")
                return True, data
            else:
                print(f"WARNING: Unexpected data format: {type(data)}")
                return True, []
        else:
            print(f"ERROR: Failed to fetch projects. Response: {data}")
            return False, []
    
    @staticmethod
    def get_drill_holes(project_id: int) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the list of drill holes for a project.
        
        Args:
            project_id: The ID of the project
            
        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of drill holes
        """
        print(f"\n=== Getting Drill Holes for Project ID: {project_id} ===")
        client = get_api_client()
        print(f"API client authenticated: {client.is_authenticated()}")
        
        if not client.is_authenticated():
            print("ERROR: Client is not authenticated")
            return False, []
        
        # Use the correct API endpoint with query parameter
        endpoint = f'drill-collars/'
        params = {'project_id': project_id, 'page_size': 1000}
        print(f"Requesting endpoint: {endpoint} with params: {params}")
        success, data = client.make_request('GET', endpoint, params=params)
        print(f"API request success: {success}")
        
        if success:
            # API returns paginated response with 'results' field
            if isinstance(data, dict) and 'results' in data:
                drill_holes = data['results']
                print(f"Received {len(drill_holes)} drill holes from paginated response")
                print(f"Drill hole names: {[d.get('name', 'Unknown') for d in drill_holes]}")
                return True, drill_holes
            elif isinstance(data, list):
                print(f"Received {len(data)} drill holes as direct list")
                print(f"Drill hole names: {[d.get('name', 'Unknown') for d in data]}")
                return True, data
            else:
                print(f"WARNING: Unexpected data format: {type(data)}")
                return True, []
        else:
            print(f"ERROR: Failed to fetch drill holes. Response: {data}")
            return False, []
    
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
            return True, data
        else:
            return False, {}
    
    @staticmethod
    def get_surveys(drill_hole_id: int) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the surveys for a drill hole.
        
        Args:
            drill_hole_id: The ID of the drill collar
            
        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of surveys
        """
        client = get_api_client()
        if not client.is_authenticated():
            return False, []
        
        # Use correct drill-surveys endpoint with bhid filter
        endpoint = 'drill-surveys/'
        params = {'bhid': drill_hole_id, 'page_size': 1000}
        success, data = client.make_request('GET', endpoint, params=params)
        
        if success:
            # API returns paginated response with 'results' field
            if isinstance(data, dict) and 'results' in data:
                surveys = data['results']
                return True, surveys
            elif isinstance(data, list):
                return True, data
            else:
                return True, []
        else:
            return False, []
    
    @staticmethod
    def get_all_surveys_for_project(project_id: int) -> Tuple[bool, Dict[int, List[Dict[str, Any]]]]:
        """Get ALL surveys for a project in a single API call.
        
        This is much more efficient than calling get_surveys() for each drill hole.
        
        Args:
            project_id: The ID of the project
            
        Returns:
            Tuple[bool, Dict[hole_id, List[surveys]]]: Success flag and surveys grouped by drill hole ID
        """
        print(f"\n=== Bulk Fetching ALL Surveys for Project ID: {project_id} ===")
        client = get_api_client()
        if not client.is_authenticated():
            print("ERROR: Client is not authenticated")
            return False, {}
        
        # Fetch ALL surveys for the project in one call
        endpoint = 'drill-surveys/'
        params = {'project_id': project_id, 'page_size': 10000}  # Large page size
        print(f"Fetching from endpoint: {endpoint} with params: {params}")
        success, data = client.make_request('GET', endpoint, params=params)
        
        if not success:
            print(f"ERROR: Failed to fetch surveys. Response: {data}")
            return False, {}
        
        # Extract surveys from response
        surveys = []
        if isinstance(data, dict) and 'results' in data:
            surveys = data['results']
        elif isinstance(data, list):
            surveys = data
        
        print(f"Received {len(surveys)} total surveys for project")
        
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
                    print(f"WARNING: Survey missing bhid: {survey.get('id', 'unknown')}")
                    continue
            
            if hole_id:
                if hole_id not in surveys_by_hole:
                    surveys_by_hole[hole_id] = []
                surveys_by_hole[hole_id].append(survey)
        
        print(f"Grouped into {len(surveys_by_hole)} drill holes by ID")
        if surveys_by_name:
            print(f"Also found {len(surveys_by_name)} drill holes indexed by name (will need name-to-ID mapping)")
            print(f"Hole names: {list(surveys_by_name.keys())}")
        
        if surveys_by_hole:
            print(f"Drill hole IDs with surveys: {sorted(surveys_by_hole.keys())}")
        
        # Return surveys indexed by ID, and by name as a special key if needed
        # Store name-indexed surveys with string keys for later matching
        result = surveys_by_hole.copy()
        for name, surveys_list in surveys_by_name.items():
            result[f"name:{name}"] = surveys_list
        
        return True, result
    
    @staticmethod
    def get_samples(drill_hole_id: int) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get the samples for a drill hole.
        
        Note: Assay data is automatically included in the sample response.
        
        Args:
            drill_hole_id: The ID of the drill collar
            
        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of samples (with nested assay data)
        """
        client = get_api_client()
        if not client.is_authenticated():
            return False, []
        
        # Use correct drill-samples endpoint with bhid filter
        endpoint = 'drill-samples/'
        params = {'bhid': drill_hole_id, 'page_size': 1000}
        success, data = client.make_request('GET', endpoint, params=params)
        
        if success:
            # API returns paginated response with 'results' field
            if isinstance(data, dict) and 'results' in data:
                samples = data['results']
                return True, samples
            elif isinstance(data, list):
                return True, data
            else:
                return True, []
        else:
            return False, []
    
    @staticmethod
    def get_all_samples_for_project(project_id: int) -> Tuple[bool, Dict[int, List[Dict[str, Any]]]]:
        """Get ALL samples for a project in a single API call.
        
        This is much more efficient than calling get_samples() for each drill hole.
        
        Args:
            project_id: The ID of the project
            
        Returns:
            Tuple[bool, Dict[hole_id, List[samples]]]: Success flag and samples grouped by drill hole ID
        """
        print(f"\n=== Bulk Fetching ALL Samples for Project ID: {project_id} ===")
        client = get_api_client()
        if not client.is_authenticated():
            print("ERROR: Client is not authenticated")
            return False, {}
        
        # Fetch ALL samples for the project in one call
        endpoint = 'drill-samples/'
        params = {'project_id': project_id, 'page_size': 10000}  # Large page size
        print(f"Fetching from endpoint: {endpoint} with params: {params}")
        success, data = client.make_request('GET', endpoint, params=params)
        
        if not success:
            print(f"ERROR: Failed to fetch samples. Response: {data}")
            return False, {}
        
        # Extract samples from response
        samples = []
        if isinstance(data, dict) and 'results' in data:
            samples = data['results']
        elif isinstance(data, list):
            samples = data
        
        print(f"Received {len(samples)} total samples for project")
        
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
                    print(f"WARNING: Sample missing bhid: {sample.get('id', 'unknown')}")
                    continue
            
            if hole_id:
                if hole_id not in samples_by_hole:
                    samples_by_hole[hole_id] = []
                samples_by_hole[hole_id].append(sample)
        
        print(f"Grouped into {len(samples_by_hole)} drill holes by ID")
        if samples_by_name:
            print(f"Also found {len(samples_by_name)} drill holes indexed by name (will need name-to-ID mapping)")
            print(f"Hole names: {list(samples_by_name.keys())}")
        
        if samples_by_hole:
            print(f"Drill hole IDs with samples: {sorted(samples_by_hole.keys())}")
        
        # Return samples indexed by ID, and by name as a special key if needed
        # Store name-indexed samples with string keys for later matching
        result = samples_by_hole.copy()
        for name, samples_list in samples_by_name.items():
            result[f"name:{name}"] = samples_list
        
        return True, result
    
    # Note: get_assays method removed - assay data is now automatically included 
    # in the drill-samples response as nested data
    
    @staticmethod
    def get_assay_range_configurations(project_id: int) -> Tuple[bool, List[Dict[str, Any]]]:
        """Get assay range configurations for a project.
        
        Args:
            project_id: The ID of the project
            
        Returns:
            Tuple[bool, List[Dict]]: Success flag and list of assay range configurations
        """
        print(f"\n=== Getting Assay Range Configurations for Project ID: {project_id} ===")
        client = get_api_client()
        
        if not client.is_authenticated():
            print("ERROR: Client is not authenticated")
            return False, []
        
        endpoint = 'assay-range-configurations/'
        params = {'project_id': project_id, 'page_size': 1000}
        print(f"Requesting endpoint: {endpoint} with params: {params}")
        success, data = client.make_request('GET', endpoint, params=params)
        
        if success:
            # API returns paginated response with 'results' field
            if isinstance(data, dict) and 'results' in data:
                configs = data['results']
                print(f"Received {len(configs)} assay range configurations")
                return True, configs
            elif isinstance(data, list):
                print(f"Received {len(data)} assay range configurations")
                return True, data
            else:
                print(f"WARNING: Unexpected data format: {type(data)}")
                return True, []
        else:
            print(f"ERROR: Failed to fetch assay range configurations. Response: {data}")
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
            # ✨ IDEAL CASE: API provides local coordinates ready for Blender!
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
            # 1 degree latitude ≈ 111,320 meters
            # 1 degree longitude ≈ 111,320 * cos(latitude) meters
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
        print(f"WARNING: Collar {collar.get('name', 'unknown')} has no valid coordinates")
        return (0.0, 0.0, collar.get('elevation', 0.0), collar.get('total_depth', 0.0))


    @staticmethod
    def fetch_all_project_data(project_id: int, company_id: int, 
                                project_name: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Fetch all drill hole data for a project in a single batch.
        
        This function makes minimal API calls to retrieve all data:
        - 1 call for project details (coordinate system metadata)
        - 1 call for collars
        - 1 call for surveys
        - 1 call for samples
        - 1 call for lithology (if available)
        - 1 call for alteration (if available)
        
        Args:
            project_id: Project ID
            company_id: Company ID
            project_name: Project name
            
        Returns:
            Tuple of (success, data_dictionary)
            data_dictionary contains:
                - project_metadata: Project-level coordinate system info
                - collars: List of collar dictionaries
                - surveys: Dict[bhid, List] of survey data grouped by hole
                - samples: Dict[bhid, List] of sample data grouped by hole
                - lithology: Dict[bhid, List] of lithology data grouped by hole
                - alteration: Dict[bhid, List] of alteration data grouped by hole
        """
        print(f"\n=== Fetching All Project Data for {project_name} (ID: {project_id}) ===")
        
        client = get_api_client()
        if not client.is_authenticated():
            print("ERROR: Client is not authenticated")
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
            'alteration': {}
        }
        
        # 0. Fetch project details for coordinate system metadata
        print("\n[0/5] Fetching project metadata...")
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
                print(f"✓ Retrieved project metadata")
                if metadata.get('proj4_string'):
                    print(f"  - Proj4 coordinate system: {metadata['proj4_string'][:50]}...")
                    print(f"  - Blender origin: ({metadata.get('blender_origin_x')}, {metadata.get('blender_origin_y')})")
            else:
                print("WARNING: Could not fetch project metadata")
        except Exception as e:
            print(f"WARNING: Failed to fetch project metadata: {e}")
        
        # 1. Fetch all collars for the project
        print("\n[1/5] Fetching collars...")
        success, collars = GeoDBData.get_drill_holes(project_id)
        if not success:
            print("ERROR: Failed to fetch collars")
            return False, {}
        
        print(f"✓ Retrieved {len(collars)} collars")
        result_data['collars'] = collars
        
        # Extract hole IDs for reference
        hole_ids = [collar.get('id') for collar in collars if collar.get('id')]
        result_data['hole_ids'] = hole_ids
        
        # 2. Fetch all surveys for the project
        print("\n[2/5] Fetching surveys (bulk)...")
        success, surveys_by_hole = GeoDBData.get_all_surveys_for_project(project_id)
        if not success:
            print("WARNING: Failed to fetch surveys in bulk")
            result_data['surveys'] = {}
        else:
            print(f"✓ Retrieved surveys for {len(surveys_by_hole)} holes")
            result_data['surveys'] = surveys_by_hole
        
        # 3. Fetch all samples for the project
        print("\n[3/5] Fetching samples (bulk)...")
        success, samples_by_hole = GeoDBData.get_all_samples_for_project(project_id)
        if not success:
            print("WARNING: Failed to fetch samples in bulk")
            result_data['samples'] = {}
        else:
            total_samples = sum(len(v) for v in samples_by_hole.values())
            print(f"✓ Retrieved {total_samples} samples across {len(samples_by_hole)} holes")
            result_data['samples'] = samples_by_hole
        
        # 4. Fetch lithology data (if endpoint exists)
        print("\n[4/5] Fetching lithology...")
        try:
            success, lithology_data = client.make_request(
                'GET', 
                'lithology/', 
                params={'project': project_id, 'page_size': 10000}
            )
            
            if success and lithology_data:
                # Handle paginated response
                if isinstance(lithology_data, dict) and 'results' in lithology_data:
                    lithology_list = lithology_data['results']
                else:
                    lithology_list = lithology_data if isinstance(lithology_data, list) else []
                
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
                print(f"✓ Retrieved {total_lith} lithology intervals across {len(lithology_by_hole)} holes")
            else:
                print("No lithology data available")
        except Exception as e:
            print(f"WARNING: Failed to fetch lithology: {e}")
            result_data['lithology'] = {}
        
        # 5. Fetch assay range configurations
        print("\n[5/6] Fetching assay range configurations...")
        try:
            success, assay_configs = GeoDBData.get_assay_range_configurations(project_id)
            if success:
                result_data['assay_range_configs'] = assay_configs
                print(f"✓ Retrieved {len(assay_configs)} assay range configurations")
            else:
                print("No assay range configurations available")
                result_data['assay_range_configs'] = []
        except Exception as e:
            print(f"WARNING: Failed to fetch assay range configurations: {e}")
            result_data['assay_range_configs'] = []
        
        # 6. Fetch alteration data (if endpoint exists)
        print("\n[6/6] Fetching alteration...")
        try:
            success, alteration_data = client.make_request(
                'GET',
                'alteration/',
                params={'project': project_id, 'page_size': 10000}
            )
            
            if success and alteration_data:
                # Handle paginated response
                if isinstance(alteration_data, dict) and 'results' in alteration_data:
                    alteration_list = alteration_data['results']
                else:
                    alteration_list = alteration_data if isinstance(alteration_data, list) else []
                
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
                print(f"✓ Retrieved {total_alt} alteration intervals across {len(alteration_by_hole)} holes")
            else:
                print("No alteration data available")
        except Exception as e:
            print(f"WARNING: Failed to fetch alteration: {e}")
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
        
        print(f"\n=== Bulk Data Fetch Complete ===")
        print(f"Summary:")
        print(f"  - Collars: {len(result_data['collars'])}")
        print(f"  - Surveys: {len(result_data['surveys'])} holes")
        print(f"  - Samples: {len(result_data['samples'])} holes")
        print(f"  - Lithology: {len(result_data['lithology'])} holes")
        print(f"  - Alteration: {len(result_data['alteration'])} holes")
        print(f"  - Assay Configs: {len(result_data['assay_range_configs'])}")
        print(f"  - Available Elements: {', '.join(result_data['available_elements'][:5])}..." if len(result_data['available_elements']) > 5 else f"  - Available Elements: {', '.join(result_data['available_elements'])}")
        print(f"  - Available Lithologies: {len(result_data['available_lithologies'])}")
        print(f"  - Available Alterations: {len(result_data['available_alterations'])}")
        
        return True, result_data