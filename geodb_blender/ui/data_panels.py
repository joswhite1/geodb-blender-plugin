"""
Data selection and visualization panels for the geoDB Blender add-on.

This module provides UI panels for selecting companies, projects, and drill holes,
as well as visualizing the selected data.
"""

import bpy
import traceback
from bpy.types import Panel, Operator, UIList
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty, FloatProperty

from ..api.data import GeoDBData
from ..core.visualization import DrillHoleVisualizer
from ..core.validation import DrillHoleValidator, DrillHoleValidationError
from ..utils.object_properties import GeoDBObjectProperties

# Global cache for dropdown data to prevent UI freezing
_dropdown_cache = {
    'companies': None,
    'projects': {},  # keyed by company_id
    'drill_holes': {},  # keyed by project_id
}

# Company selection operator
class GEODB_OT_SelectCompany(Operator):
    """Select a company to work with"""
    bl_idname = "geodb.select_company"
    bl_label = "Select Company"
    bl_description = "Select a company to work with"
    
    def get_companies(self, context):
        """Get the list of companies for the enum property (from cache only)."""
        import time
        start_time = time.time()
        print("\n=== Building Company Dropdown (Cache Only) ===")
        
        # Check cache first - NEVER make API calls here
        global _dropdown_cache
        if _dropdown_cache['companies'] is not None:
            print(f"CACHE HIT! Returning cached companies")
            elapsed_time = time.time() - start_time
            print(f"Total time (cached): {elapsed_time:.3f}s")
            return _dropdown_cache['companies']
        
        # If cache is empty, try to get from client.companies (already loaded during login)
        from ..api.auth import get_api_client
        client = get_api_client()
        if client.companies:
            print(f"Using companies from client cache: {len(client.companies)}")
            items = []
            for c in client.companies:
                desc = c.get('description')
                if desc is None:
                    desc = ''
                items.append((str(c['id']), c['name'], desc))
            _dropdown_cache['companies'] = items
            elapsed_time = time.time() - start_time
            print(f"Total time (from client): {elapsed_time:.3f}s")
            return items
        
        print("WARNING: No companies in cache - returning placeholder")
        elapsed_time = time.time() - start_time
        print(f"Total time: {elapsed_time:.3f}s")
        return [("0", "Loading companies...", "Please wait")]
    
    company_id: EnumProperty(
        name="Company",
        description="Select a company",
        items=get_companies,
    )
    
    def invoke(self, context, event):
        # Pre-load companies into cache before opening dialog
        print("\n=== Pre-loading companies before dialog ===")
        global _dropdown_cache
        
        if _dropdown_cache['companies'] is None:
            # Try to get from client first
            from ..api.auth import get_api_client
            client = get_api_client()
            if client.companies:
                items = []
                for c in client.companies:
                    desc = c.get('description')
                    if desc is None:
                        desc = ''
                    items.append((str(c['id']), c['name'], desc))
                _dropdown_cache['companies'] = items
                print(f"Pre-loaded {len(items)} companies from client")
            else:
                # Fetch from API
                print("Fetching companies from API...")
                success, companies = GeoDBData.get_companies()
                if success and companies:
                    items = []
                    for c in companies:
                        desc = c.get('description')
                        if desc is None:
                            desc = ''
                        items.append((str(c['id']), c['name'], desc))
                    _dropdown_cache['companies'] = items
                    print(f"Pre-loaded {len(items)} companies from API")
                else:
                    print("ERROR: Failed to pre-load companies")
                    self.report({'ERROR'}, "Failed to load companies")
                    return {'CANCELLED'}
        
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "company_id")
    
    def execute(self, context):
        # Store selected company in scene properties
        context.scene.geodb.selected_company_id = self.company_id
        
        # Get company name from cache (DO NOT make API calls here!)
        global _dropdown_cache
        if _dropdown_cache['companies']:
            for comp_id, comp_name, comp_desc in _dropdown_cache['companies']:
                if comp_id == self.company_id:
                    context.scene.geodb.selected_company_name = comp_name
                    print(f"Set company name to: {comp_name} (from cache)")
                    break
        else:
            print("WARNING: No cached companies found for name lookup")
        
        # Clear project and drill hole selection
        context.scene.geodb.selected_project_id = ""
        context.scene.geodb.selected_project_name = ""
        context.scene.geodb.selected_drill_hole_id = ""
        context.scene.geodb.selected_drill_hole_name = ""
        
        # Do NOT pre-load projects here - it blocks the UI!
        # Projects will be loaded when user clicks "Select Project" button
        print(f"Company selected. Projects will be loaded when needed.")
        
        # Force UI redraw
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        
        self.report({'INFO'}, f"Selected company: {context.scene.geodb.selected_company_name}")
        return {'FINISHED'}

# Project selection operator with async loading
class GEODB_OT_LoadProjects(Operator):
    """Load projects for the selected company (async)"""
    bl_idname = "geodb.load_projects"
    bl_label = "Load Projects"
    bl_description = "Load projects for the selected company"
    
    _timer = None
    _thread = None
    _result = None
    _error = None
    _loading = False
    
    def modal(self, context, event):
        if event.type == 'TIMER':
            # Check if background thread is done
            if not self._loading:
                # Clean up
                context.window_manager.event_timer_remove(self._timer)
                
                if self._error:
                    self.report({'ERROR'}, self._error)
                    return {'CANCELLED'}
                
                if self._result:
                    success, projects, company_id_int = self._result
                    if success and projects:
                        # Build and cache dropdown items
                        global _dropdown_cache
                        items = []
                        for p in projects:
                            desc = p.get('description')
                            if desc is None:
                                desc = ''
                            items.append((str(p['id']), p['name'], desc))
                        _dropdown_cache['projects'][company_id_int] = items
                        print(f"Cached {len(items)} projects for company {company_id_int}")
                        
                        self.report({'INFO'}, f"Loaded {len(projects)} projects")
                        # Now show the selection dialog
                        bpy.ops.geodb.select_project('INVOKE_DEFAULT')
                    else:
                        self.report({'WARNING'}, "No projects found for this company")
                
                return {'FINISHED'}
        
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        # Check if company is selected
        company_id = context.scene.geodb.selected_company_id
        if not company_id:
            self.report({'ERROR'}, "No company selected")
            return {'CANCELLED'}
        
        try:
            company_id_int = int(company_id)
        except ValueError:
            self.report({'ERROR'}, "Invalid company ID")
            return {'CANCELLED'}
        
        # Clear cache for this company to force refresh
        global _dropdown_cache
        if company_id_int in _dropdown_cache['projects']:
            del _dropdown_cache['projects'][company_id_int]
            print(f"Cleared cache for company {company_id_int}")
        
        # Start background thread
        self._loading = True
        self._result = None
        self._error = None
        
        def load_in_background():
            try:
                success, projects = GeoDBData.get_projects(company_id_int)
                self._result = (success, projects, company_id_int)
            except Exception as e:
                self._error = f"Failed to load projects: {str(e)}"
            finally:
                self._loading = False
        
        import threading
        self._thread = threading.Thread(target=load_in_background, daemon=True)
        self._thread.start()
        
        # Set up modal timer
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        
        return {'RUNNING_MODAL'}


# Project selection operator
class GEODB_OT_SelectProject(Operator):
    """Select a project to work with"""
    bl_idname = "geodb.select_project"
    bl_label = "Select Project"
    bl_description = "Select a project to work with"
    
    def get_projects(self, context):
        """Get the list of projects for the enum property (cache only - no API calls)."""
        import time
        start_time = time.time()
        print("\n=== Building Project Dropdown (Cache Only) ===")
        company_id = context.scene.geodb.selected_company_id
        print(f"Selected company_id from context: '{company_id}'")
        
        if not company_id:
            print("ERROR: No company selected")
            return [("0", "No company selected", "")]
        
        try:
            company_id_int = int(company_id)
            print(f"Company ID as int: {company_id_int}")
        except ValueError as e:
            print(f"ERROR: Cannot convert company_id to int: {e}")
            return [("0", "Invalid company ID", "")]
        
        # Check cache - NEVER make API calls here
        global _dropdown_cache
        if company_id_int in _dropdown_cache['projects']:
            print(f"CACHE HIT! Returning cached projects for company {company_id_int}")
            elapsed_time = time.time() - start_time
            print(f"Total get_projects() time (cached): {elapsed_time:.3f}s")
            return _dropdown_cache['projects'][company_id_int]
        
        # Cache miss - return placeholder (should have been pre-loaded)
        print(f"WARNING: No projects in cache for company {company_id_int}")
        elapsed_time = time.time() - start_time
        print(f"Total get_projects() time: {elapsed_time:.3f}s")
        return [("0", "Loading projects...", "Please wait")]
    
    project_id: EnumProperty(
        name="Project",
        description="Select a project",
        items=get_projects,
    )
    
    def invoke(self, context, event):
        print("\n=== SelectProject Operator Invoked ===")
        
        # Verify company is selected
        if not context.scene.geodb.selected_company_id:
            self.report({'ERROR'}, "Please select a company first")
            return {'CANCELLED'}
        
        try:
            result = context.window_manager.invoke_props_dialog(self, width=400)
            print(f"invoke_props_dialog returned: {result}")
            return result
        except Exception as e:
            print(f"ERROR in SelectProject.invoke: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Failed to open dialog: {str(e)}")
            return {'CANCELLED'}
    
    def draw(self, context):
        layout = self.layout
        
        # Show loading message if no company selected
        if not context.scene.geodb.selected_company_id:
            layout.label(text="Please select a company first", icon='ERROR')
            return
        
        layout.prop(self, "project_id")
    
    def execute(self, context):
        print(f"\n=== SelectProject Operator Execute ===")
        print(f"Selected project_id: {self.project_id}")
        
        if self.project_id == "0":
            self.report({'WARNING'}, "No valid project selected")
            return {'CANCELLED'}
        
        try:
            # Store selected project in scene properties
            context.scene.geodb.selected_project_id = self.project_id
            print(f"Stored project_id in scene properties")
            
            # Get project name from cache (DO NOT make API calls here!)
            company_id = context.scene.geodb.selected_company_id
            print(f"Company ID from scene: {company_id}")
            
            # Look up project name from cache only
            global _dropdown_cache
            company_id_int = int(company_id)
            if company_id_int in _dropdown_cache['projects']:
                for proj_id, proj_name, proj_desc in _dropdown_cache['projects'][company_id_int]:
                    if proj_id == self.project_id:
                        context.scene.geodb.selected_project_name = proj_name
                        print(f"Set project name to: {proj_name} (from cache)")
                        break
            else:
                print("WARNING: No cached projects found for name lookup")
            
            # Clear drill hole selection
            context.scene.geodb.selected_drill_hole_id = ""
            context.scene.geodb.selected_drill_hole_name = ""
            print("Cleared drill hole selection")
            
            # Do NOT pre-load drill holes here - it blocks the UI!
            # Drill holes will be loaded when user clicks "Select Drill Hole" button
            print("Drill holes will be loaded when needed")
            
            # Force UI redraw
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            
            print("Execute completed successfully")
            self.report({'INFO'}, f"Selected project: {context.scene.geodb.selected_project_name}")
            return {'FINISHED'}
        except Exception as e:
            print(f"ERROR in SelectProject.execute: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Failed to select project: {str(e)}")
            return {'CANCELLED'}

# Drill hole selection operator with async loading
class GEODB_OT_LoadDrillHoles(Operator):
    """Load drill holes for the selected project (async)"""
    bl_idname = "geodb.load_drill_holes"
    bl_label = "Load Drill Holes"
    bl_description = "Load drill holes for the selected project"
    
    _timer = None
    _thread = None
    _result = None
    _error = None
    _loading = False
    
    def modal(self, context, event):
        if event.type == 'TIMER':
            # Check if background thread is done
            if not self._loading:
                # Clean up
                context.window_manager.event_timer_remove(self._timer)
                
                if self._error:
                    self.report({'ERROR'}, self._error)
                    return {'CANCELLED'}
                
                if self._result:
                    success, drill_holes, project_id_int = self._result
                    if success and drill_holes:
                        # Build and cache dropdown items
                        global _dropdown_cache
                        items = []
                        for d in drill_holes:
                            desc = d.get('description')
                            if desc is None:
                                desc = ''
                            items.append((str(d['id']), d['name'], desc))
                        _dropdown_cache['drill_holes'][project_id_int] = items
                        print(f"Cached {len(items)} drill holes for project {project_id_int}")
                        
                        self.report({'INFO'}, f"Loaded {len(drill_holes)} drill holes")
                        # Now show the selection dialog
                        bpy.ops.geodb.select_drill_hole('INVOKE_DEFAULT')
                    else:
                        self.report({'WARNING'}, "No drill holes found for this project")
                
                return {'FINISHED'}
        
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        # Check if project is selected
        project_id = context.scene.geodb.selected_project_id
        if not project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}
        
        try:
            project_id_int = int(project_id)
        except ValueError:
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}
        
        # Clear cache for this project to force refresh
        global _dropdown_cache
        if project_id_int in _dropdown_cache['drill_holes']:
            del _dropdown_cache['drill_holes'][project_id_int]
            print(f"Cleared cache for project {project_id_int}")
        
        # Start background thread
        self._loading = True
        self._result = None
        self._error = None
        
        def load_in_background():
            try:
                success, drill_holes = GeoDBData.get_drill_holes(project_id_int)
                self._result = (success, drill_holes, project_id_int)
            except Exception as e:
                self._error = f"Failed to load drill holes: {str(e)}"
            finally:
                self._loading = False
        
        import threading
        self._thread = threading.Thread(target=load_in_background, daemon=True)
        self._thread.start()
        
        # Set up modal timer
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        
        return {'RUNNING_MODAL'}


# Drill hole selection operator
class GEODB_OT_SelectDrillHole(Operator):
    """Select a drill hole to work with"""
    bl_idname = "geodb.select_drill_hole"
    bl_label = "Select Drill Hole"
    bl_description = "Select a drill hole to work with"
    
    def get_drill_holes(self, context):
        """Get the list of drill holes for the enum property (cache only - no API calls)."""
        import time
        start_time = time.time()
        print("\n=== Building Drill Hole Dropdown (Cache Only) ===")
        project_id = context.scene.geodb.selected_project_id
        print(f"Selected project_id from context: '{project_id}'")
        
        if not project_id:
            print("ERROR: No project selected")
            return [("0", "No project selected", "")]
        
        try:
            project_id_int = int(project_id)
            print(f"Project ID as int: {project_id_int}")
        except ValueError as e:
            print(f"ERROR: Cannot convert project_id to int: {e}")
            return [("0", "Invalid project ID", "")]
        
        # Check cache - NEVER make API calls here
        global _dropdown_cache
        if project_id_int in _dropdown_cache['drill_holes']:
            print(f"CACHE HIT! Returning cached drill holes for project {project_id_int}")
            elapsed_time = time.time() - start_time
            print(f"Total get_drill_holes() time (cached): {elapsed_time:.3f}s")
            return _dropdown_cache['drill_holes'][project_id_int]
        
        # Cache miss - return placeholder (should have been pre-loaded)
        print(f"WARNING: No drill holes in cache for project {project_id_int}")
        elapsed_time = time.time() - start_time
        print(f"Total get_drill_holes() time: {elapsed_time:.3f}s")
        return [("0", "Loading drill holes...", "Please wait")]
    
    drill_hole_id: EnumProperty(
        name="Drill Hole",
        description="Select a drill hole",
        items=get_drill_holes,
    )
    
    def invoke(self, context, event):
        # Verify project is selected
        if not context.scene.geodb.selected_project_id:
            self.report({'ERROR'}, "Please select a project first")
            return {'CANCELLED'}
        
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        
        # Show message if no project selected
        if not context.scene.geodb.selected_project_id:
            layout.label(text="Please select a project first", icon='ERROR')
            return
        
        layout.prop(self, "drill_hole_id")
    
    def execute(self, context):
        if self.drill_hole_id == "0":
            self.report({'WARNING'}, "No valid drill hole selected")
            return {'CANCELLED'}
        
        # Store selected drill hole in scene properties
        context.scene.geodb.selected_drill_hole_id = self.drill_hole_id
        
        # Get drill hole name from cache (DO NOT make API calls here!)
        project_id = context.scene.geodb.selected_project_id
        
        # Look up drill hole name from cache only
        global _dropdown_cache
        project_id_int = int(project_id)
        if project_id_int in _dropdown_cache['drill_holes']:
            for dh_id, dh_name, dh_desc in _dropdown_cache['drill_holes'][project_id_int]:
                if dh_id == self.drill_hole_id:
                    context.scene.geodb.selected_drill_hole_name = dh_name
                    print(f"Set drill hole name to: {dh_name} (from cache)")
                    break
        else:
            print("WARNING: No cached drill holes found for name lookup")
        
        # Force UI redraw
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        
        self.report({'INFO'}, f"Selected drill hole: {context.scene.geodb.selected_drill_hole_name}")
        return {'FINISHED'}

# Visualization operator with async data loading
class GEODB_OT_VisualizeDrillHole(Operator):
    """Visualize the selected drill hole (async)"""
    bl_idname = "geodb.visualize_drill_hole"
    bl_label = "Visualize Drill Hole"
    bl_description = "Create a 3D visualization of the selected drill hole"
    
    show_trace: BoolProperty(
        name="Show Drill Trace",
        description="Show the drill hole trace",
        default=True,
    )
    
    show_samples: BoolProperty(
        name="Show Samples",
        description="Show sample intervals",
        default=True,
    )
    
    trace_segments: IntProperty(
        name="Trace Segments",
        description="Number of segments to use for the drill trace",
        default=100,
        min=10,
        max=1000,
    )
    
    # For async operation
    _timer = None
    _thread = None
    _result = None
    _error = None
    _loading = False
    _drill_hole_id = None
    
    def invoke(self, context, event):
        # Get current settings from scene properties
        self.show_trace = context.scene.geodb.show_drill_traces
        self.show_samples = context.scene.geodb.show_samples
        self.trace_segments = int(context.scene.geodb.trace_segments)
        
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "show_trace")
        layout.prop(self, "show_samples")
        layout.prop(self, "trace_segments")
    
    def modal(self, context, event):
        if event.type == 'TIMER':
            # Check if background thread is done
            if not self._loading:
                # Clean up timer
                context.window_manager.event_timer_remove(self._timer)
                context.workspace.status_text_set(None)
                
                if self._error:
                    self.report({'ERROR'}, self._error)
                    return {'CANCELLED'}
                
                if self._result:
                    # Create visualization on main thread from pre-calculated geometry
                    try:
                        from ..utils.desurvey import create_drill_trace_mesh_from_coords, create_drill_sample_meshes_from_coords
                        
                        hole_name = self._result['hole_name']
                        trace_coords = self._result['trace_coords']
                        sample_coords_data = self._result['sample_coords_data']
                        
                        # Clear existing visualizations
                        DrillHoleVisualizer.clear_visualizations()
                        
                        created_objects = []
                        
                        # Create trace mesh from pre-calculated coordinates (FAST!)
                        if trace_coords is not None:
                            print(f"Creating trace mesh on main thread...")
                            trace_obj = create_drill_trace_mesh_from_coords(trace_coords, f"{hole_name}_Trace")
                            
                            # Tag as geodb visualization
                            trace_obj['geodb_visualization'] = True
                            trace_obj['geodb_type'] = 'drill_trace'
                            trace_obj['geodb_hole_name'] = hole_name
                            trace_obj.display_type = 'WIRE'
                            
                            created_objects.append(trace_obj)
                            print(f"Trace mesh created")
                        
                        # Create sample meshes from pre-calculated coordinates (FAST!)
                        if sample_coords_data is not None:
                            print(f"Creating {len(sample_coords_data)} sample meshes on main thread...")
                            sample_objs = create_drill_sample_meshes_from_coords(
                                sample_coords_data,
                                f"{hole_name}_Sample"
                            )
                            
                            # Tag as geodb visualization
                            for obj in sample_objs:
                                obj['geodb_visualization'] = True
                                obj['geodb_type'] = 'sample'
                                obj['geodb_hole_name'] = hole_name
                                obj.display_type = 'SOLID'
                                created_objects.append(obj)
                            
                            print(f"Sample meshes created")
                        
                        # Apply color mapping if samples are shown and an element is selected
                        if sample_coords_data and context.scene.geodb.selected_assay_element:
                            element = context.scene.geodb.selected_assay_element
                            DrillHoleVisualizer.apply_color_mapping(created_objects, element)
                        
                        self.report({'INFO'}, f"Visualization created for {hole_name}")
                        
                    except Exception as e:
                        print(f"Error creating visualization: {traceback.format_exc()}")
                        self.report({'ERROR'}, f"Failed to create visualization: {str(e)}")
                        return {'CANCELLED'}
                
                return {'FINISHED'}
            else:
                # Update progress indicator while loading
                context.workspace.status_text_set("Loading drill hole data and calculating geometry...")
        
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        import traceback
        
        drill_hole_id = context.scene.geodb.selected_drill_hole_id
        if not drill_hole_id:
            self.report({'ERROR'}, "No drill hole selected")
            return {'CANCELLED'}
        
        # Save settings to scene properties
        context.scene.geodb.show_drill_traces = self.show_trace
        context.scene.geodb.show_samples = self.show_samples
        context.scene.geodb.trace_segments = str(self.trace_segments)
        
        self._drill_hole_id = int(drill_hole_id)
        
        # Start background thread to fetch data
        self._loading = True
        self._result = None
        self._error = None
        
        def load_in_background():
            """Fetch drill hole data and calculate geometry in background thread (NO Blender access!)"""
            try:
                from ..utils.desurvey import calculate_drill_trace_coords, calculate_drill_sample_coords
                
                # Get drill hole details
                success, drill_hole = GeoDBData.get_drill_hole_details(self._drill_hole_id)
                if not success:
                    self._error = "Failed to get drill hole details"
                    return
                
                # Get surveys
                success, surveys = GeoDBData.get_surveys(self._drill_hole_id)
                if not success:
                    self._error = "Failed to get survey data"
                    return
                
                # Get samples if needed
                samples = None
                if self.show_samples:
                    success, samples = GeoDBData.get_samples(self._drill_hole_id)
                    if not success:
                        print("Warning: Failed to get samples, continuing without them")
                        samples = None
                
                # Format data for processing
                formatted_surveys = GeoDBData.format_surveys_for_desurvey(surveys) if surveys else None
                formatted_samples = None
                if self.show_samples and samples:
                    formatted_samples = GeoDBData.format_samples_for_visualization(samples)
                
                # Create collar tuple
                collar = (
                    drill_hole.get('easting', 0.0),
                    drill_hole.get('northing', 0.0),
                    drill_hole.get('elevation', 0.0),
                    drill_hole.get('total_depth', 0.0)
                )
                
                # Calculate coordinates in background (THIS IS THE SLOW PART)
                trace_coords = None
                sample_coords_data = None
                
                if self.show_trace and formatted_surveys:
                    print(f"Calculating trace geometry with {self.trace_segments} segments...")
                    trace_coords = calculate_drill_trace_coords(collar, formatted_surveys, self.trace_segments)
                    print(f"Trace geometry calculated: {len(trace_coords)} points")
                
                if self.show_samples and formatted_samples and formatted_surveys:
                    print(f"Calculating sample geometry for {len(formatted_samples)} samples...")
                    sample_coords_data = calculate_drill_sample_coords(collar, formatted_surveys, formatted_samples)
                    print(f"Sample geometry calculated for {len(sample_coords_data)} samples")
                
                # Store results (pre-calculated coordinates ready for mesh creation)
                self._result = {
                    'hole_name': drill_hole.get('name', 'DrillHole'),
                    'collar': collar,
                    'trace_coords': trace_coords,
                    'sample_coords_data': sample_coords_data,
                }
                
            except Exception as e:
                self._error = f"Error loading data: {str(e)}"
                print(f"Background thread error: {traceback.format_exc()}")
            finally:
                self._loading = False
        
        import threading
        self._thread = threading.Thread(target=load_in_background, daemon=True)
        self._thread.start()
        
        # Set up modal timer
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        
        self.report({'INFO'}, "Loading drill hole data...")
        return {'RUNNING_MODAL'}

# Color mapping operator
class GEODB_OT_ApplyColorMapping(Operator):
    """Apply color mapping to sample visualizations"""
    bl_idname = "geodb.apply_color_mapping"
    bl_label = "Apply Color Mapping"
    bl_description = "Apply color mapping to sample visualizations based on assay values"
    
    def get_elements(self, context):
        """Get the list of available elements for the enum property."""
        # Find all sample objects and collect unique elements
        elements = set()
        for obj in bpy.data.objects:
            if 'geodb_type' in obj and obj['geodb_type'] == 'sample':
                for key in obj.keys():
                    if key.startswith('value_'):
                        elements.add(key[6:])  # Remove 'value_' prefix
        
        if elements:
            return [(e, e, f"Use {e} values for coloring") for e in sorted(elements)]
        else:
            return [("", "No elements available", "")]
    
    element: EnumProperty(
        name="Element",
        description="Element to use for color mapping",
        items=get_elements,
    )
    
    min_value: FloatProperty(
        name="Min Value",
        description="Minimum value for color mapping",
        default=0.0,
    )
    
    max_value: FloatProperty(
        name="Max Value",
        description="Maximum value for color mapping",
        default=1.0,
    )
    
    auto_range: BoolProperty(
        name="Auto Range",
        description="Automatically determine min and max values",
        default=True,
    )
    
    color_map: EnumProperty(
        name="Color Map",
        description="Color map to use",
        items=[
            ('RAINBOW', "Rainbow", "Red to blue color map"),
            ('VIRIDIS', "Viridis", "Perceptually uniform color map"),
            ('PLASMA', "Plasma", "Perceptually uniform color map"),
            ('MAGMA', "Magma", "Perceptually uniform color map"),
        ],
        default='RAINBOW',
    )
    
    show_legend: BoolProperty(
        name="Show Legend",
        description="Show a color legend",
        default=True,
    )
    
    def invoke(self, context, event):
        # Get current element from scene properties
        if context.scene.geodb.selected_assay_element:
            self.element = context.scene.geodb.selected_assay_element
        
        # Calculate min and max values for the selected element
        if self.auto_range and self.element:
            values = []
            for obj in bpy.data.objects:
                if 'geodb_type' in obj and obj['geodb_type'] == 'sample':
                    value_key = f'value_{self.element}'
                    if value_key in obj:
                        values.append(obj[value_key])
            
            if values:
                self.min_value = min(values)
                self.max_value = max(values)
        
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "element")
        layout.prop(self, "color_map")
        layout.prop(self, "auto_range")
        
        if not self.auto_range:
            layout.prop(self, "min_value")
            layout.prop(self, "max_value")
        
        layout.prop(self, "show_legend")
    
    def execute(self, context):
        if not self.element:
            self.report({'ERROR'}, "No element selected")
            return {'CANCELLED'}
        
        # Save selected element to scene properties
        context.scene.geodb.selected_assay_element = self.element
        
        # Get all objects
        objects = list(bpy.data.objects)
        
        # Apply color mapping
        DrillHoleVisualizer.apply_color_mapping(
            objects=objects,
            element=self.element,
            min_value=self.min_value if not self.auto_range else None,
            max_value=self.max_value if not self.auto_range else None,
            color_map=self.color_map
        )
        
        # Create legend if requested
        if self.show_legend:
            # Remove existing legends
            for obj in bpy.data.objects:
                if 'geodb_type' in obj and obj['geodb_type'] in ('legend', 'legend_text'):
                    bpy.data.objects.remove(obj, do_unlink=True)
            
            # Create new legend
            DrillHoleVisualizer.create_legend(
                element=self.element,
                min_value=self.min_value,
                max_value=self.max_value,
                position=(0, 0, 0),
                size=1.0,
                color_map=self.color_map
            )
        
        self.report({'INFO'}, f"Applied {self.color_map} color mapping for {self.element}")
        return {'FINISHED'}

# Clear visualizations operator
class GEODB_OT_ClearVisualizations(Operator):
    """Clear all drill hole visualizations"""
    bl_idname = "geodb.clear_visualizations"
    bl_label = "Clear Visualizations"
    bl_description = "Remove all drill hole visualizations from the scene"
    
    def execute(self, context):
        DrillHoleVisualizer.clear_visualizations()
        self.report({'INFO'}, "Cleared all visualizations")
        return {'FINISHED'}

# Bulk validation operator
class GEODB_OT_ValidateDrillHoles(Operator):
    """Validate all drill holes in the selected project"""
    bl_idname = "geodb.validate_drill_holes"
    bl_label = "Validate Drill Holes"
    bl_description = "Check all drill holes for data errors and inconsistencies"
    
    _timer = None
    _thread = None
    _result = None
    _error = None
    _loading = False
    _progress = 0
    _total = 0
    _current_hole = ""
    
    def modal(self, context, event):
        if event.type == 'TIMER':
            # Update progress in UI
            context.area.tag_redraw()
            
            # Check if background thread is done
            if not self._loading:
                # Clean up timer
                context.window_manager.event_timer_remove(self._timer)
                
                if self._error:
                    self.report({'ERROR'}, self._error)
                    return {'CANCELLED'}
                
                if self._result:
                    # Display validation results
                    validation_results = self._result
                    
                    # Count errors and warnings
                    total_holes = len(validation_results)
                    valid_holes = sum(1 for is_valid, _ in validation_results.values() if is_valid)
                    invalid_holes = total_holes - valid_holes
                    
                    # Store results in scene properties for display
                    context.scene.geodb.validation_results = str(validation_results)
                    
                    # Build detailed report
                    report_lines = []
                    report_lines.append("=" * 60)
                    report_lines.append("DRILL HOLE VALIDATION REPORT")
                    report_lines.append("=" * 60)
                    report_lines.append(f"Total Holes: {total_holes}")
                    report_lines.append(f"Valid Holes: {valid_holes}")
                    report_lines.append(f"Holes with Issues: {invalid_holes}")
                    report_lines.append("=" * 60)
                    
                    for hole_name, (is_valid, errors) in validation_results.items():
                        if errors:
                            report_lines.append(DrillHoleValidator.format_validation_report(hole_name, errors))
                    
                    report_lines.append("=" * 60)
                    
                    report_text = "\n".join(report_lines)
                    
                    # Print to console
                    print("\n" + report_text)
                    
                    # Write to file
                    log_path = context.scene.geodb.validation_log_path
                    if log_path:
                        try:
                            with open(log_path, 'w', encoding='utf-8') as f:
                                f.write(report_text)
                            print(f"\nValidation report written to: {log_path}")
                        except Exception as e:
                            print(f"\nWARNING: Failed to write validation report to file: {e}")
                    
                    self.report({'INFO'}, f"Validation complete: {valid_holes}/{total_holes} holes valid")
                    
                    # Show popup with summary
                    def draw_validation_popup(self, context):
                        layout = self.layout
                        layout.label(text=f"Validation Complete", icon='INFO')
                        layout.separator()
                        layout.label(text=f"Total Holes: {total_holes}")
                        layout.label(text=f"Valid Holes: {valid_holes}", icon='CHECKMARK')
                        layout.label(text=f"Holes with Issues: {invalid_holes}", icon='ERROR' if invalid_holes > 0 else 'CHECKMARK')
                        layout.separator()
                        if log_path:
                            layout.label(text=f"Report saved to file")
                        layout.label(text="See console for detailed report")
                    
                    context.window_manager.popup_menu(draw_validation_popup, title="Validation Results", icon='INFO')
                
                return {'FINISHED'}
        
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        project_id = context.scene.geodb.selected_project_id
        if not project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}
        
        try:
            project_id_int = int(project_id)
        except ValueError:
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}
        
        # Start background thread
        self._loading = True
        self._result = None
        self._error = None
        self._progress = 0
        self._total = 0
        
        def validate_in_background():
            """Validate all drill holes in background thread"""
            try:
                # Get all drill holes
                success, drill_holes = GeoDBData.get_drill_holes(project_id_int)
                if not success or not drill_holes:
                    self._error = "Failed to load drill holes or no drill holes found"
                    return
                
                self._total = len(drill_holes)
                validation_results = {}
                
                for i, dh in enumerate(drill_holes):
                    hole_id = dh.get('id')
                    hole_name = dh.get('name', f'Hole_{hole_id}')
                    self._current_hole = hole_name
                    self._progress = i + 1
                    
                    # Get drill hole details
                    success, collar = GeoDBData.get_drill_hole_details(hole_id)
                    if not success:
                        validation_results[hole_name] = (False, [DrillHoleValidationError(
                            'MISSING_COLLAR_DATA',
                            'Failed to fetch collar data',
                            'ERROR'
                        )])
                        continue
                    
                    # Get surveys
                    success, surveys = GeoDBData.get_surveys(hole_id)
                    if not success:
                        surveys = []
                    
                    # Get samples
                    success, samples = GeoDBData.get_samples(hole_id)
                    if not success:
                        samples = []
                    
                    # Validate
                    is_valid, errors = DrillHoleValidator.validate_drill_hole(
                        collar, surveys, samples, 
                        check_lithology=True,
                        check_alteration=False
                    )
                    
                    validation_results[hole_name] = (is_valid, errors)
                
                self._result = validation_results
                
            except Exception as e:
                self._error = f"Validation error: {str(e)}"
                print(f"Background validation error: {traceback.format_exc()}")
            finally:
                self._loading = False
        
        import threading
        self._thread = threading.Thread(target=validate_in_background, daemon=True)
        self._thread.start()
        
        # Set up modal timer
        self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)
        
        self.report({'INFO'}, "Validating drill holes...")
        return {'RUNNING_MODAL'}

# Bulk visualization operator
class GEODB_OT_BulkVisualizeDrillHoles(Operator):
    """Visualize multiple drill holes at once"""
    bl_idname = "geodb.bulk_visualize_drill_holes"
    bl_label = "Bulk Visualize Drill Holes"
    bl_description = "Import and visualize multiple drill holes at once"
    
    import_mode: EnumProperty(
        name="Import Mode",
        description="Choose which drill holes to import",
        items=[
            ('ALL', "All Holes", "Import all drill holes in the project"),
            ('VALID_ONLY', "Valid Only", "Import only holes that pass validation"),
            ('RANGE', "Range", "Import a range of holes by index"),
        ],
        default='ALL',
    )
    
    start_index: IntProperty(
        name="Start Index",
        description="Start index for range import (0-based)",
        default=0,
        min=0,
    )
    
    end_index: IntProperty(
        name="End Index",
        description="End index for range import (0-based, inclusive)",
        default=10,
        min=0,
    )
    
    show_trace: BoolProperty(
        name="Show Drill Traces",
        description="Show the drill hole traces",
        default=True,
    )
    
    show_samples: BoolProperty(
        name="Show Samples",
        description="Show sample intervals",
        default=False,  # Default off for bulk to improve performance
    )
    
    trace_segments: IntProperty(
        name="Trace Segments",
        description="Number of segments to use for each drill trace",
        default=50,  # Lower default for bulk
        min=10,
        max=1000,
    )
    
    skip_on_error: BoolProperty(
        name="Skip on Error",
        description="Skip drill holes that have errors and continue with others",
        default=True,
    )
    
    create_straight_holes: BoolProperty(
        name="Create Straight Holes",
        description="Create straight holes for collars without survey data (using azimuth/dip)",
        default=True,
    )
    
    # For async operation
    _timer = None
    _thread = None
    _result = None
    _error = None
    _loading = False
    _progress = 0
    _total = 0
    _current_hole = ""
    _visualization_queue = []
    
    def invoke(self, context, event):
        # Get current settings from scene properties
        self.import_mode = context.scene.geodb.bulk_import_mode
        self.start_index = context.scene.geodb.bulk_start_index
        self.end_index = context.scene.geodb.bulk_end_index
        self.skip_on_error = context.scene.geodb.bulk_skip_on_error
        self.create_straight_holes = context.scene.geodb.bulk_create_straight_holes
        self.show_trace = context.scene.geodb.show_drill_traces
        self.show_samples = context.scene.geodb.show_samples
        self.trace_segments = int(context.scene.geodb.trace_segments) // 2  # Half for bulk
        
        # Call execute directly instead of showing modal dialog
        return self.execute(context)
    
    def draw(self, context):
        layout = self.layout
        
        layout.prop(self, "import_mode")
        
        if self.import_mode == 'RANGE':
            row = layout.row()
            row.prop(self, "start_index")
            row.prop(self, "end_index")
        
        layout.separator()
        layout.label(text="Visualization Options:")
        layout.prop(self, "show_trace")
        layout.prop(self, "show_samples")
        layout.prop(self, "trace_segments")
        
        layout.separator()
        layout.label(text="Error Handling:")
        layout.prop(self, "skip_on_error")
        layout.prop(self, "create_straight_holes")
        
        # Show warning for large imports
        if self.import_mode == 'ALL':
            box = layout.box()
            box.label(text="Warning: Importing all holes may take time", icon='ERROR')
    
    def modal(self, context, event):
        if event.type == 'TIMER':
            # Update progress in UI
            if self._total > 0:
                progress_pct = int((self._progress / self._total) * 100)
                context.workspace.status_text_set(f"Processing: {self._current_hole} ({self._progress}/{self._total} - {progress_pct}%)")
            
            context.area.tag_redraw()
            
            # Create visualizations from queue (on main thread for Blender API access)
            if self._visualization_queue:
                viz_data = self._visualization_queue.pop(0)
                self._create_single_visualization(context, viz_data)
            
            # Check if background thread is done
            if not self._loading and not self._visualization_queue:
                # Clean up timer
                context.window_manager.event_timer_remove(self._timer)
                context.workspace.status_text_set(None)
                
                if self._error:
                    self.report({'ERROR'}, self._error)
                    return {'CANCELLED'}
                
                if self._result:
                    success_count, error_count, skipped_count = self._result
                    
                    print("\n" + "="*60)
                    print("BULK IMPORT COMPLETE")
                    print("="*60)
                    print(f"Successfully imported: {success_count}")
                    print(f"Errors encountered: {error_count}")
                    print(f"Skipped: {skipped_count}")
                    print("="*60)
                    
                    self.report({'INFO'}, f"Imported {success_count} drill holes ({error_count} errors, {skipped_count} skipped)")
                
                return {'FINISHED'}
        
        return {'RUNNING_MODAL'}
    
    def _create_single_visualization(self, context, viz_data):
        """Create visualization for a single drill hole from pre-calculated coordinates (must run on main thread)"""
        try:
            from ..utils.desurvey import create_drill_trace_mesh_from_coords, create_drill_sample_meshes_from_coords
            
            hole_name = viz_data['hole_name']
            trace_coords = viz_data['trace_coords']
            sample_coords_data = viz_data['sample_coords_data']
            
            # Create trace mesh from pre-calculated coordinates (FAST!)
            if trace_coords is not None:
                trace_obj = create_drill_trace_mesh_from_coords(trace_coords, f"{hole_name}_Trace")
                
                # Tag as geodb visualization
                trace_obj['geodb_visualization'] = True
                trace_obj['geodb_type'] = 'drill_trace'
                trace_obj['geodb_hole_name'] = hole_name
                trace_obj.display_type = 'WIRE'
            
            # Create sample meshes from pre-calculated coordinates (FAST!)
            if sample_coords_data is not None:
                sample_objs = create_drill_sample_meshes_from_coords(
                    sample_coords_data,
                    f"{hole_name}_Sample"
                )
                
                # Tag as geodb visualization
                for obj in sample_objs:
                    obj['geodb_visualization'] = True
                    obj['geodb_type'] = 'sample'
                    obj['geodb_hole_name'] = hole_name
                    obj.display_type = 'SOLID'
            
        except Exception as e:
            print(f"Error creating visualization for {hole_name}: {str(e)}")
            traceback.print_exc()
    
    def execute(self, context):
        project_id = context.scene.geodb.selected_project_id
        if not project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}
        
        try:
            project_id_int = int(project_id)
        except ValueError:
            self.report({'ERROR'}, "Invalid project ID")
            return {'CANCELLED'}
        
        # Clear existing visualizations
        DrillHoleVisualizer.clear_visualizations()
        
        # Start background thread
        self._loading = True
        self._result = None
        self._error = None
        self._progress = 0
        self._total = 0
        self._visualization_queue = []
        
        def load_in_background():
            """Load and validate drill holes, calculate geometry in background thread"""
            try:
                from ..utils.desurvey import calculate_drill_trace_coords, calculate_drill_sample_coords
                
                print("\n" + "="*60)
                print("STARTING OPTIMIZED BULK IMPORT")
                print("="*60)
                
                # STEP 1: Fetch ALL data upfront with just 3 API calls! 🚀
                print("\n[1/4] Fetching all drill holes (collars)...")
                success, drill_holes = GeoDBData.get_drill_holes(project_id_int)
                if not success or not drill_holes:
                    self._error = "Failed to load drill holes or no drill holes found"
                    return
                print(f"✓ Fetched {len(drill_holes)} drill holes")
                
                print("\n[2/4] Bulk fetching ALL surveys for project...")
                success, surveys_by_hole = GeoDBData.get_all_surveys_for_project(project_id_int)
                if not success:
                    print("WARNING: Failed to bulk fetch surveys, will fetch individually")
                    surveys_by_hole = {}
                else:
                    print(f"✓ Bulk fetched surveys for {len(surveys_by_hole)} holes")
                
                print("\n[3/4] Bulk fetching ALL samples for project...")
                samples_by_hole = {}
                if self.show_samples:
                    success, samples_by_hole = GeoDBData.get_all_samples_for_project(project_id_int)
                    if not success:
                        print("WARNING: Failed to bulk fetch samples, will fetch individually")
                        samples_by_hole = {}
                    else:
                        print(f"✓ Bulk fetched samples for {len(samples_by_hole)} holes")
                else:
                    print("✓ Skipping samples (not requested)")
                
                print(f"\n[4/4] Processing {len(drill_holes)} drill holes...")
                print("="*60)
                
                # Filter based on import mode
                if self.import_mode == 'RANGE':
                    end_idx = min(self.end_index + 1, len(drill_holes))
                    drill_holes = drill_holes[self.start_index:end_idx]
                elif self.import_mode == 'VALID_ONLY':
                    # Will validate during processing
                    pass
                
                self._total = len(drill_holes)
                success_count = 0
                error_count = 0
                skipped_count = 0
                
                # STEP 2: Process each hole using pre-fetched data (NO MORE API CALLS!)
                for i, dh in enumerate(drill_holes):
                    hole_id = dh.get('id')
                    hole_name = dh.get('name', f'Hole_{hole_id}')
                    self._current_hole = hole_name
                    self._progress = i + 1
                    
                    try:
                        # Use collar data from drill_holes (already complete from get_drill_holes)
                        collar = dh
                        
                        # Get surveys from pre-fetched dict (NO API CALL!)
                        surveys = surveys_by_hole.get(hole_id, [])
                        if not surveys:
                            # Try matching by name if ID lookup failed
                            name_key = f"name:{hole_name}"
                            surveys = surveys_by_hole.get(name_key, [])
                            if surveys:
                                print(f"Matched surveys for {hole_name} by name")
                            else:
                                # Last resort: individual fetch if bulk fetch missed this hole
                                print(f"No bulk survey data for hole {hole_id} ({hole_name}), fetching individually")
                                success, surveys = GeoDBData.get_surveys(hole_id)
                                if not success:
                                    surveys = []
                        
                        # Get samples from pre-fetched dict (NO API CALL!)
                        samples = []
                        if self.show_samples:
                            samples = samples_by_hole.get(hole_id, [])
                            if not samples:
                                # Try matching by name if ID lookup failed
                                name_key = f"name:{hole_name}"
                                samples = samples_by_hole.get(name_key, [])
                                if samples:
                                    print(f"Matched samples for {hole_name} by name")
                                else:
                                    # Last resort: individual fetch if bulk fetch missed this hole
                                    print(f"No bulk sample data for hole {hole_id} ({hole_name}), fetching individually")
                                    success, samples = GeoDBData.get_samples(hole_id)
                                    if not success:
                                        samples = []
                        
                        # Validate
                        is_valid, errors = DrillHoleValidator.validate_drill_hole(
                            collar, surveys, samples,
                            check_lithology=True,
                            check_alteration=False
                        )
                        
                        # Check if we should skip based on validation
                        if self.import_mode == 'VALID_ONLY' and not is_valid:
                            print(f"Skipping {hole_name}: validation failed")
                            skipped_count += 1
                            continue
                        
                        # Handle missing surveys
                        if not surveys:
                            if self.create_straight_holes and DrillHoleValidator._can_create_straight_hole(collar):
                                # Create straight hole surveys
                                survey_tuples = DrillHoleValidator.create_straight_hole_surveys(collar)
                                surveys = [
                                    {'azimuth': az, 'dip': dip, 'depth': depth}
                                    for az, dip, depth in survey_tuples
                                ]
                                print(f"Created straight hole for {hole_name}")
                            else:
                                print(f"Skipping {hole_name}: no survey data and cannot create straight hole")
                                skipped_count += 1
                                continue
                        
                        # Format data for processing
                        formatted_surveys = GeoDBData.format_surveys_for_desurvey(surveys) if surveys else None
                        formatted_samples = None
                        if self.show_samples and samples:
                            formatted_samples = GeoDBData.format_samples_for_visualization(samples)
                        
                        # Extract collar coordinates (handles various coordinate formats)
                        collar_tuple = GeoDBData.extract_collar_coordinates(collar)
                        
                        # Calculate coordinates in background (THIS IS THE SLOW PART)
                        trace_coords = None
                        sample_coords_data = None
                        
                        if self.show_trace and formatted_surveys:
                            trace_coords = calculate_drill_trace_coords(collar_tuple, formatted_surveys, self.trace_segments)
                        
                        if self.show_samples and formatted_samples and formatted_surveys:
                            sample_coords_data = calculate_drill_sample_coords(collar_tuple, formatted_surveys, formatted_samples)
                        
                        # Queue pre-calculated geometry for visualization on main thread
                        self._visualization_queue.append({
                            'hole_name': hole_name,
                            'trace_coords': trace_coords,
                            'sample_coords_data': sample_coords_data,
                        })
                        success_count += 1
                        
                    except Exception as e:
                        print(f"Error processing {hole_name}: {str(e)}")
                        traceback.print_exc()
                        error_count += 1
                        if not self.skip_on_error:
                            self._error = f"Error processing {hole_name}: {str(e)}"
                            return
                
                self._result = (success_count, error_count, skipped_count)
                
            except Exception as e:
                self._error = f"Bulk import error: {str(e)}"
                print(f"Background bulk import error: {traceback.format_exc()}")
            finally:
                self._loading = False
        
        import threading
        self._thread = threading.Thread(target=load_in_background, daemon=True)
        self._thread.start()
        
        # Set up modal timer
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        
        self.report({'INFO'}, "Starting bulk import...")
        return {'RUNNING_MODAL'}

# Data selection panel
class GEODB_PT_DataSelection(Panel):
    """Data selection panel for the geoDB add-on"""
    bl_label = "Data Selection"
    bl_idname = "GEODB_PT_DataSelection"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_parent_id = "GEODB_PT_MainPanel"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Company selection
        box = layout.box()
        row = box.row()
        row.label(text="Company:")
        row = box.row()
        if scene.geodb.selected_company_name:
            row.label(text=scene.geodb.selected_company_name)
            row.operator("geodb.select_company", text="", icon='FILE_REFRESH')
        else:
            row.operator("geodb.select_company", icon='DOWNARROW_HLT')
        
        # Project selection (only shown if company is selected)
        if scene.geodb.selected_company_id:
            box = layout.box()
            row = box.row()
            row.label(text="Project:")
            row = box.row()
            if scene.geodb.selected_project_name:
                row.label(text=scene.geodb.selected_project_name)
                row.operator("geodb.load_projects", text="", icon='FILE_REFRESH')
            else:
                row.operator("geodb.load_projects", icon='DOWNARROW_HLT')
        
        # Drill hole selection (only shown if project is selected)
        if scene.geodb.selected_project_id:
            box = layout.box()
            row = box.row()
            row.label(text="Drill Hole:")
            row = box.row()
            if scene.geodb.selected_drill_hole_name:
                row.label(text=scene.geodb.selected_drill_hole_name)
                row.operator("geodb.load_drill_holes", text="", icon='FILE_REFRESH')
            else:
                row.operator("geodb.load_drill_holes", icon='DOWNARROW_HLT')

# Visualization panel
class GEODB_PT_Visualization(Panel):
    """Visualization panel for the geoDB add-on"""
    bl_label = "Visualization"
    bl_idname = "GEODB_PT_Visualization"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_parent_id = "GEODB_PT_MainPanel"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Only show if a drill hole is selected
        if not scene.geodb.selected_drill_hole_id:
            layout.label(text="Select a drill hole first", icon='INFO')
            return
        
        # Visualization options
        box = layout.box()
        box.label(text="Visualization Options:")
        row = box.row()
        row.prop(scene.geodb, "show_drill_traces", text="Show Traces")
        row.prop(scene.geodb, "show_samples", text="Show Samples")
        box.prop(scene.geodb, "trace_segments", text="Segments")
        
        # Visualization button
        layout.operator("geodb.visualize_drill_hole", icon='MESH_CYLINDER')
        
        # Color mapping (only if samples are shown)
        if scene.geodb.show_samples:
            box = layout.box()
            box.label(text="Color Mapping:")
            box.operator("geodb.apply_color_mapping", icon='COLOR')
        
        # Clear visualizations
        layout.operator("geodb.clear_visualizations", icon='X')

# Bulk operations panel
class GEODB_PT_BulkOperations(Panel):
    """Bulk operations panel for the geoDB add-on"""
    bl_label = "Bulk Operations"
    bl_idname = "GEODB_PT_BulkOperations"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_parent_id = "GEODB_PT_MainPanel"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Only show if a project is selected
        if not scene.geodb.selected_project_id:
            layout.label(text="Select a project first", icon='INFO')
            return
        
        # Initialize validation log path if empty
        if not scene.geodb.validation_log_path:
            import os
            # Use blend file directory if available, otherwise use user's documents
            if bpy.data.filepath:
                blend_dir = os.path.dirname(bpy.data.filepath)
                default_path = os.path.join(blend_dir, "drillhole_validation.txt")
            else:
                import pathlib
                docs_dir = pathlib.Path.home() / "Documents"
                default_path = str(docs_dir / "drillhole_validation.txt")
            scene.geodb.validation_log_path = default_path
        
        # Validation section
        box = layout.box()
        box.label(text="Data Validation:", icon='CHECKMARK')
        box.prop(scene.geodb, "validation_log_path", text="Log File")
        box.operator("geodb.validate_drill_holes", text="Validate Drill Holes", icon='FUND')
        
        layout.separator()
        
        # Bulk import section
        box = layout.box()
        box.label(text="Bulk Visualization:", icon='MESH_CYLINDER')
        
        # Import mode
        box.prop(scene.geodb, "bulk_import_mode", text="Mode")
        
        # Show range controls if range mode selected
        if scene.geodb.bulk_import_mode == 'RANGE':
            row = box.row()
            row.prop(scene.geodb, "bulk_start_index", text="Start")
            row.prop(scene.geodb, "bulk_end_index", text="End")
        
        # Error handling options
        row = box.row()
        row.prop(scene.geodb, "bulk_skip_on_error", text="Skip Errors")
        row.prop(scene.geodb, "bulk_create_straight_holes", text="Straight Holes")
        
        # Import button
        box.operator("geodb.bulk_visualize_drill_holes", text="Import Drill Holes", icon='IMPORT')


class GEODB_PT_ActiveObjectInspector(Panel):
    """Panel for inspecting geoDB object properties"""
    bl_label = "geoDB Object Inspector"
    bl_idname = "GEODB_PT_active_object_inspector"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_order = 5  # Appears after other panels
    
    @classmethod
    def poll(cls, context):
        """Only show panel when a geoDB object is selected"""
        obj = context.active_object
        return obj is not None and GeoDBObjectProperties.is_geodb_object(obj)
    
    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        
        # Shouldn't happen due to poll, but safety check
        if not GeoDBObjectProperties.is_geodb_object(obj):
            layout.label(text="No geoDB object selected", icon='INFO')
            return
        
        # Get all properties organized by section
        display_props = GeoDBObjectProperties.get_display_properties(obj)
        
        if not display_props:
            layout.label(text="No properties to display", icon='INFO')
            return
        
        # Object name header
        box = layout.box()
        box.label(text=obj.name, icon='OBJECT_DATA')
        
        # Display each section
        for section_name, properties in display_props.items():
            if not properties:
                continue
            
            # Section header
            col = layout.column(align=True)
            col.label(text=section_name, icon='DOT')
            
            # Section properties box
            box = col.box()
            box_col = box.column(align=True)
            
            for label, value in properties:
                # Create row with label and value
                row = box_col.row(align=True)
                
                # Label (left-aligned)
                split = row.split(factor=0.4)
                split.label(text=f"{label}:")
                
                # Value (right-aligned)
                value_col = split.column(align=True)
                value_col.alignment = 'LEFT'
                
                # Handle multi-line values (like validation messages)
                if isinstance(value, str) and '|' in value:
                    # Split multi-line values
                    for line in value.split('|'):
                        value_col.label(text=line.strip())
                else:
                    value_col.label(text=str(value))
            
            # Add spacing between sections
            layout.separator(factor=0.5)
        
        # Add utility buttons at the bottom
        layout.separator()
        col = layout.column(align=True)
        col.label(text="Actions", icon='MODIFIER')
        box = col.box()
        
        # Copy properties to clipboard (future feature)
        # box.operator("geodb.copy_object_properties", text="Copy Properties", icon='COPYDOWN')
        
        # Select similar objects
        box.operator("geodb.select_similar_objects", text="Select Similar", icon='RESTRICT_SELECT_OFF')
        
        # Jump to related hole
        obj_type = GeoDBObjectProperties.get_object_type(obj)
        if obj_type == GeoDBObjectProperties.TYPE_DRILL_SAMPLE:
            box.operator("geodb.select_drill_trace", text="Select Drill Trace", icon='CURVE_DATA')


class GEODB_OT_SelectSimilarObjects(Operator):
    """Select all objects with the same hole name"""
    bl_idname = "geodb.select_similar_objects"
    bl_label = "Select Similar Objects"
    bl_description = "Select all geoDB objects from the same drill hole"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        active_obj = context.active_object
        
        if not GeoDBObjectProperties.is_geodb_object(active_obj):
            self.report({'ERROR'}, "Active object is not a geoDB object")
            return {'CANCELLED'}
        
        # Get hole name from active object
        hole_name = active_obj.get("geodb_hole_name")
        if not hole_name:
            self.report({'ERROR'}, "Active object has no hole name")
            return {'CANCELLED'}
        
        # Deselect all first
        bpy.ops.object.select_all(action='DESELECT')
        
        # Select all objects with matching hole name
        count = 0
        for obj in bpy.data.objects:
            if GeoDBObjectProperties.is_geodb_object(obj):
                if obj.get("geodb_hole_name") == hole_name:
                    obj.select_set(True)
                    count += 1
        
        if count > 0:
            # Keep active object active
            context.view_layer.objects.active = active_obj
            self.report({'INFO'}, f"Selected {count} objects from hole '{hole_name}'")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, f"No objects found for hole '{hole_name}'")
            return {'CANCELLED'}


class GEODB_OT_SelectDrillTrace(Operator):
    """Select the drill trace for this sample's hole"""
    bl_idname = "geodb.select_drill_trace"
    bl_label = "Select Drill Trace"
    bl_description = "Select the drill trace object for this sample's hole"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        active_obj = context.active_object
        
        if not GeoDBObjectProperties.is_geodb_object(active_obj):
            self.report({'ERROR'}, "Active object is not a geoDB object")
            return {'CANCELLED'}
        
        # Get hole name from active object
        hole_name = active_obj.get("geodb_hole_name")
        if not hole_name:
            self.report({'ERROR'}, "Active object has no hole name")
            return {'CANCELLED'}
        
        # Find drill trace with matching hole name
        for obj in bpy.data.objects:
            if GeoDBObjectProperties.get_object_type(obj) == GeoDBObjectProperties.TYPE_DRILL_TRACE:
                if obj.get("geodb_hole_name") == hole_name:
                    # Deselect all and select trace
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                    self.report({'INFO'}, f"Selected drill trace for '{hole_name}'")
                    return {'FINISHED'}
        
        self.report({'WARNING'}, f"No drill trace found for hole '{hole_name}'")
        return {'CANCELLED'}


# Registration
def register():
    bpy.utils.register_class(GEODB_OT_SelectCompany)
    bpy.utils.register_class(GEODB_OT_LoadProjects)
    bpy.utils.register_class(GEODB_OT_SelectProject)
    bpy.utils.register_class(GEODB_OT_LoadDrillHoles)
    bpy.utils.register_class(GEODB_OT_SelectDrillHole)
    bpy.utils.register_class(GEODB_OT_VisualizeDrillHole)
    bpy.utils.register_class(GEODB_OT_ApplyColorMapping)
    bpy.utils.register_class(GEODB_OT_ClearVisualizations)
    bpy.utils.register_class(GEODB_OT_ValidateDrillHoles)
    bpy.utils.register_class(GEODB_OT_BulkVisualizeDrillHoles)
    bpy.utils.register_class(GEODB_OT_SelectSimilarObjects)
    bpy.utils.register_class(GEODB_OT_SelectDrillTrace)
    bpy.utils.register_class(GEODB_PT_DataSelection)
    bpy.utils.register_class(GEODB_PT_Visualization)
    bpy.utils.register_class(GEODB_PT_BulkOperations)
    bpy.utils.register_class(GEODB_PT_ActiveObjectInspector)

def unregister():
    bpy.utils.unregister_class(GEODB_PT_ActiveObjectInspector)
    bpy.utils.unregister_class(GEODB_PT_BulkOperations)
    bpy.utils.unregister_class(GEODB_PT_Visualization)
    bpy.utils.unregister_class(GEODB_PT_DataSelection)
    bpy.utils.unregister_class(GEODB_OT_SelectDrillTrace)
    bpy.utils.unregister_class(GEODB_OT_SelectSimilarObjects)
    bpy.utils.unregister_class(GEODB_OT_BulkVisualizeDrillHoles)
    bpy.utils.unregister_class(GEODB_OT_ValidateDrillHoles)
    bpy.utils.unregister_class(GEODB_OT_ClearVisualizations)
    bpy.utils.unregister_class(GEODB_OT_ApplyColorMapping)
    bpy.utils.unregister_class(GEODB_OT_VisualizeDrillHole)
    bpy.utils.unregister_class(GEODB_OT_SelectDrillHole)
    bpy.utils.unregister_class(GEODB_OT_LoadDrillHoles)
    bpy.utils.unregister_class(GEODB_OT_SelectProject)
    bpy.utils.unregister_class(GEODB_OT_LoadProjects)
    bpy.utils.unregister_class(GEODB_OT_SelectCompany)