"""
Data selection and visualization panels for the geoDB Blender add-on.

This module provides UI panels for selecting companies, projects, and drill holes,
as well as visualizing the selected data.
"""

import bpy
from bpy.types import Panel, Operator, UIList
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty, FloatProperty

from ..api.data import GeoDBData
from ..utils.object_properties import GeoDBObjectProperties

# Global cache for dropdown data to prevent UI freezing
_dropdown_cache = {
    'companies': None,
    'projects': {},  # keyed by company_id - stores EnumProperty tuples
    'drill_holes': {},  # keyed by project_id
}

# Separate cache for full project data (including code)
_project_data_cache = {}  # keyed by project_id - stores full project dicts

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
        context.scene.geodb.selected_project_code = ""
        context.scene.geodb.selected_project_name = ""
        context.scene.geodb.selected_drill_hole_id = ""
        context.scene.geodb.selected_drill_hole_name = ""

        # Notify the server of the active company selection (like the QGIS plugin does)
        from ..api.auth import get_api_client
        client = get_api_client()
        try:
            company_id_int = int(self.company_id)
            success, msg = client.set_active_company(company_id_int)
            if success:
                print(f"Set active company on server: {company_id_int}")
            else:
                print(f"WARNING: Failed to set active company on server: {msg}")
        except (ValueError, Exception) as e:
            print(f"WARNING: Could not set active company on server: {e}")

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
                        global _dropdown_cache, _project_data_cache
                        items = []
                        for p in projects:
                            desc = p.get('description', '')
                            if desc is None:
                                desc = ''
                            code = p.get('code', '')
                            proj_id = str(p['id'])

                            # Store full project data in separate cache
                            _project_data_cache[proj_id] = p

                            # Store (id, name, description) tuple - Blender EnumProperty format
                            # Include code in description if available
                            if code:
                                full_desc = f"[{code}] {desc}" if desc else f"[{code}]"
                            else:
                                full_desc = desc
                            items.append((proj_id, p['name'], full_desc))
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
        global _dropdown_cache, _project_data_cache
        if company_id_int in _dropdown_cache['projects']:
            # Clear dropdown cache
            projects_list = _dropdown_cache['projects'][company_id_int]
            del _dropdown_cache['projects'][company_id_int]
            # Clear associated project data cache entries
            for proj_tuple in projects_list:
                proj_id = proj_tuple[0]
                if proj_id in _project_data_cache:
                    del _project_data_cache[proj_id]
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

            # Look up project name and code from cache only
            global _dropdown_cache, _project_data_cache
            company_id_int = int(company_id)
            if company_id_int in _dropdown_cache['projects']:
                for proj_data in _dropdown_cache['projects'][company_id_int]:
                    proj_id = proj_data[0]
                    proj_name = proj_data[1]
                    if proj_id == self.project_id:
                        context.scene.geodb.selected_project_name = proj_name
                        # Get project code from separate cache
                        if proj_id in _project_data_cache:
                            proj_code = _project_data_cache[proj_id].get('code', '')
                            context.scene.geodb.selected_project_code = proj_code
                            print(f"Set project name to: {proj_name}, code: {proj_code} (from cache)")
                        else:
                            context.scene.geodb.selected_project_code = ""
                            print(f"Set project name to: {proj_name}, code not in cache")
                        break
            else:
                print("WARNING: No cached projects found for name lookup")

            # Clear drill hole selection
            context.scene.geodb.selected_drill_hole_id = ""
            context.scene.geodb.selected_drill_hole_name = ""
            print("Cleared drill hole selection")

            # Notify the server of the active project selection (like the QGIS plugin does)
            from ..api.auth import get_api_client
            client = get_api_client()
            try:
                project_id_int = int(self.project_id)
                success, msg = client.set_active_project(project_id_int)
                if success:
                    print(f"Set active project on server: {project_id_int}")
                else:
                    print(f"WARNING: Failed to set active project on server: {msg}")
            except (ValueError, Exception) as e:
                print(f"WARNING: Could not set active project on server: {e}")

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


class GEODB_PT_ActiveObjectInspector(Panel):
    """Panel for inspecting geoDB object properties"""
    bl_label = "geoDB Object Inspector"
    bl_idname = "GEODB_PT_active_object_inspector"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    bl_order = 5
    
    @classmethod
    def poll(cls, context):
        """Only show panel when a geoDB object is selected"""
        obj = context.active_object
        return obj is not None and GeoDBObjectProperties.is_geodb_object(obj)
    
    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        
        if not GeoDBObjectProperties.is_geodb_object(obj):
            layout.label(text="No geoDB object selected", icon='INFO')
            return
        
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
            
            col = layout.column(align=True)
            col.label(text=section_name, icon='DOT')
            
            box = col.box()
            box_col = box.column(align=True)
            
            for label, value in properties:
                row = box_col.row(align=True)
                split = row.split(factor=0.4)
                split.label(text=f"{label}:")
                
                value_col = split.column(align=True)
                value_col.alignment = 'LEFT'
                
                if isinstance(value, str) and '|' in value:
                    for line in value.split('|'):
                        value_col.label(text=line.strip())
                else:
                    value_col.label(text=str(value))
            
            layout.separator(factor=0.5)
        
        layout.separator()
        col = layout.column(align=True)
        col.label(text="Actions", icon='MODIFIER')
        box = col.box()
        
        box.operator("geodb.select_similar_objects", text="Select Similar", icon='RESTRICT_SELECT_OFF')
        
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
        
        hole_name = active_obj.get("geodb_hole_name")
        if not hole_name:
            self.report({'ERROR'}, "Active object has no hole name")
            return {'CANCELLED'}
        
        bpy.ops.object.select_all(action='DESELECT')
        
        count = 0
        for obj in bpy.data.objects:
            if GeoDBObjectProperties.is_geodb_object(obj):
                if obj.get("geodb_hole_name") == hole_name:
                    obj.select_set(True)
                    count += 1
        
        if count > 0:
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
        
        hole_name = active_obj.get("geodb_hole_name")
        if not hole_name:
            self.report({'ERROR'}, "Active object has no hole name")
            return {'CANCELLED'}
        
        for obj in bpy.data.objects:
            if GeoDBObjectProperties.get_object_type(obj) == GeoDBObjectProperties.TYPE_DRILL_TRACE:
                if obj.get("geodb_hole_name") == hole_name:
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                    self.report({'INFO'}, f"Selected drill trace for '{hole_name}'")
                    return {'FINISHED'}
        
        self.report({'WARNING'}, f"No drill trace found for hole '{hole_name}'")
        return {'CANCELLED'}


def register():
    bpy.utils.register_class(GEODB_OT_SelectCompany)
    bpy.utils.register_class(GEODB_OT_LoadProjects)
    bpy.utils.register_class(GEODB_OT_SelectProject)
    bpy.utils.register_class(GEODB_OT_SelectSimilarObjects)
    bpy.utils.register_class(GEODB_OT_SelectDrillTrace)
    bpy.utils.register_class(GEODB_PT_DataSelection)
    bpy.utils.register_class(GEODB_PT_ActiveObjectInspector)


def unregister():
    bpy.utils.unregister_class(GEODB_PT_ActiveObjectInspector)
    bpy.utils.unregister_class(GEODB_PT_DataSelection)
    bpy.utils.unregister_class(GEODB_OT_SelectDrillTrace)
    bpy.utils.unregister_class(GEODB_OT_SelectSimilarObjects)
    bpy.utils.unregister_class(GEODB_OT_SelectProject)
    bpy.utils.unregister_class(GEODB_OT_LoadProjects)
    bpy.utils.unregister_class(GEODB_OT_SelectCompany)
