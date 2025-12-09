"""
Terrain mesh import operator with background loading and progress feedback.

This operator imports terrain/DEM meshes from the geoDB API using the async pattern
to prevent UI freezing during large downloads.
"""

import bpy
import json
import os
import tempfile
from bpy.props import EnumProperty, StringProperty
from typing import Dict, Any, List, Tuple

from .async_base import GeoDBAsyncOperator
from ..api.data import GeoDBData
from ..api.client import GeoDBAPIClient
from ..ui.drill_visualization_panel import adjust_view_to_objects


# Global cache for available textures (populated before dialog is shown)
_available_textures_cache: List[Dict[str, Any]] = []


def _get_texture_enum_items(self, context) -> List[Tuple[str, str, str]]:
    """
    Dynamic callback to populate texture dropdown from cached available textures.

    This function is called by Blender to get the enum items for the texture selector.
    It uses the global cache that's populated before the dialog is shown.
    """
    global _available_textures_cache

    items = []

    # Add items from cached available textures
    for tex in _available_textures_cache:
        tex_id = str(tex.get('id', ''))
        tex_name = tex.get('name', 'Unknown Texture')
        tex_type = tex.get('type', 'unknown')
        description = f"{tex_name} ({tex_type})"

        items.append((tex_id, tex_name, description))

    # Always add a "No Texture" option at the end
    items.append(('none', 'No Texture', 'Plain mesh without texture'))

    # If no textures found, add a placeholder
    if len(items) == 1:  # Only the "none" option
        items.insert(0, ('unavailable', 'No Textures Available', 'No textures found for this project'))

    return items


class GEODB_OT_ImportTerrain(GeoDBAsyncOperator):
    """Import terrain mesh from geoDB with progress feedback"""
    bl_idname = "geodb.import_terrain"
    bl_label = "Import Terrain Mesh"
    bl_description = "Import DEM terrain mesh with textures from geoDB (runs in background)"
    bl_options = {'REGISTER', 'UNDO'}

    resolution: EnumProperty(
        name="Resolution",
        description="Mesh detail level",
        items=[
            ('very_low', 'Very Low (Fast)', '~62k vertices - Fast preview, mobile'),
            ('low', 'Low (Recommended)', '~250k vertices - Balanced quality/performance'),
            ('medium', 'Medium (High Detail)', '~1M vertices - High quality, desktop'),
        ],
        default='low'
    )

    # Dynamic texture selection - populated from available_textures API
    selected_texture: EnumProperty(
        name="Texture",
        description="Texture overlay to apply to terrain",
        items=_get_texture_enum_items
    )

    # Fallback for legacy texture type (satellite/topo/none)
    texture_type: StringProperty(
        name="Texture Type",
        description="Type of the selected texture",
        default='none'
    )

    def invoke(self, context, event):
        """Show dialog with import options, then start async operation."""
        global _available_textures_cache

        scene = context.scene

        # Check if a project is selected
        if not scene.geodb.selected_project_id:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        # Fetch available textures from elevation API before showing dialog
        # This populates the cache used by the dynamic enum callback
        project_code = scene.geodb.selected_project_code
        if not project_code:
            self.report({'ERROR'}, "No project code available")
            return {'CANCELLED'}

        print(f"Fetching available textures for project code: {project_code}")

        success, textures_data = GeoDBData.get_terrain_textures(project_code, self.resolution)

        if success:
            _available_textures_cache = textures_data.get('available_textures', [])
            print(f"Cached {len(_available_textures_cache)} textures for dialog")
        else:
            # Clear cache - no textures available
            _available_textures_cache = []
            print(f"No textures available: {textures_data.get('error', 'Unknown error')}")

        # Show options dialog - execute() will be called when user clicks OK
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        """Draw the import options dialog."""
        global _available_textures_cache

        layout = self.layout

        layout.label(text="Terrain Import Options", icon='MESH_GRID')
        layout.separator()

        layout.prop(self, "resolution")
        layout.prop(self, "selected_texture")

        layout.separator()
        box = layout.box()
        box.label(text="Resolution Info:", icon='INFO')
        if self.resolution == 'very_low':
            box.label(text="~62k vertices - Fast preview")
        elif self.resolution == 'low':
            box.label(text="~250k vertices - Balanced")
        else:
            box.label(text="~1M vertices - High detail")

        # Show texture count
        if _available_textures_cache:
            box.label(text=f"Available Textures: {len(_available_textures_cache)}")

    def execute(self, context):
        """Called when user clicks OK on dialog. Start the async operation."""
        # Check if another operation is already running
        if context.scene.geodb.import_active:
            self.report({'WARNING'}, "Another import operation is already running")
            return {'CANCELLED'}

        # Mark operation as active
        context.scene.geodb.import_active = True
        context.scene.geodb.import_progress = 0.0
        context.scene.geodb.import_status = "Initializing..."

        # Reset state
        self.__class__._progress = 0.0
        self.__class__._status = "Initializing..."
        self.__class__._data = None
        self.__class__._error = None

        # Start background thread
        import threading
        self.__class__._thread = threading.Thread(target=self.download_data)
        self.__class__._thread.start()

        # Start modal timer (checks every 0.1 seconds)
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def download_data(self):
        """
        Download terrain mesh and textures in background thread.

        This runs in a BACKGROUND THREAD - safe operations:
        ✅ API calls
        ✅ File downloads
        ✅ JSON processing

        Unsafe operations (DO NOT DO HERE):
        ❌ Creating Blender meshes
        ❌ Creating materials
        ❌ Modifying scene
        """
        global _available_textures_cache

        try:
            # Get project code from scene (thread-safe read)
            scene = bpy.context.scene

            # First check if a project is selected at all
            if not scene.geodb.selected_project_id:
                self._error = "No project selected"
                return

            # Then check if the project has a code (required for terrain API)
            if not scene.geodb.selected_project_code:
                project_name = scene.geodb.selected_project_name or "Selected project"
                self._error = f"{project_name} does not have a project code. Please configure a project code in geoDB to use terrain visualization."
                return

            project_code = scene.geodb.selected_project_code

            # Step 1: Fetch terrain mesh data from API
            self._status = f"Fetching {self.resolution} resolution terrain mesh..."
            self._progress = 0.1

            success, mesh_data = GeoDBData.get_terrain_mesh(project_code, self.resolution)

            if not success:
                error_msg = mesh_data.get('error', 'Unknown error') if isinstance(mesh_data, dict) else str(mesh_data)
                self._error = f"Failed to fetch terrain mesh: {error_msg}"
                return

            self._progress = 0.4

            # Step 2: Download selected texture if available
            texture_path = None
            texture_url = None
            texture_name = None
            texture_type = 'none'

            # Find selected texture from cache
            if self.selected_texture and self.selected_texture not in ('none', 'unavailable'):
                for tex in _available_textures_cache:
                    if str(tex.get('id', '')) == self.selected_texture:
                        texture_url = tex.get('url')
                        texture_name = tex.get('name', 'Unknown')
                        texture_type = tex.get('type', 'custom')
                        self._status = f"Downloading {texture_name}..."
                        break

            if not texture_url and self.selected_texture not in ('none', 'unavailable'):
                print(f"Warning: Selected texture ID {self.selected_texture} not found in cache")

            if texture_url:
                try:
                    # Download texture to temp file
                    texture_path = self._download_texture(texture_url)
                    mesh_data['texture_local_path'] = texture_path
                    mesh_data['active_texture_type'] = texture_type
                    mesh_data['active_texture_name'] = texture_name
                    mesh_data['active_texture_id'] = self.selected_texture
                except Exception as e:
                    print(f"Warning: Failed to download texture: {e}")
                    # Continue without texture - not a fatal error
            else:
                self._status = "Skipping texture (none selected)..."
                mesh_data['active_texture_type'] = 'none'

            self._progress = 0.7

            # Step 3: Store available textures in mesh_data for later use
            self._status = "Processing mesh metadata..."
            mesh_data['available_textures'] = _available_textures_cache.copy()

            print(f"Terrain mesh ready: {len(mesh_data['positions']) // 3} vertices")
            print(f"Available textures: {len(_available_textures_cache)}")
            if texture_name:
                print(f"Selected texture: {texture_name} ({texture_type})")

            self._data = mesh_data
            self._progress = 1.0
            self._status = "Download complete"

        except Exception as e:
            self._error = f"Error downloading terrain: {str(e)}"
            import traceback
            traceback.print_exc()

    def _download_texture(self, url: str) -> str:
        """
        Download texture image to temp file.

        Args:
            url: Texture URL (may be relative or absolute, or pre-signed S3/CDN URL)

        Returns:
            str: Path to downloaded temp file
        """
        import requests

        # Check if this is a pre-signed URL (contains AWS signature params)
        # Pre-signed URLs already have authentication baked in
        is_presigned = 'AWSAccessKeyId=' in url or 'Signature=' in url or 'X-Amz-Signature=' in url

        # If relative URL, prepend base URL and use authentication
        if url.startswith('/'):
            from ..api.auth import get_api_client
            client = get_api_client()
            base_url = client.base_url.rstrip('/api/v1/')
            url = base_url + url
            # Use authenticated request for relative URLs
            headers = client._get_headers()
        elif is_presigned:
            # Pre-signed URLs don't need authentication headers
            headers = {}
        else:
            # For other absolute URLs, try with authentication
            from ..api.auth import get_api_client
            client = get_api_client()
            headers = client._get_headers()

        print(f"Downloading texture from: {url}")
        print(f"Using authentication: {bool(headers)}")

        # Download texture
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()

        # Save to temp file
        suffix = '.jpg'  # Most terrain textures are JPEG
        if '.png' in url.lower():
            suffix = '.png'

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        temp_file.close()

        print(f"Texture downloaded to: {temp_file.name}")
        return temp_file.name

    def finish_in_main_thread(self, context):
        """
        Create Blender mesh and apply texture in main thread.

        This runs in the MAIN THREAD - safe operations:
        ✅ Creating meshes
        ✅ Creating materials
        ✅ Linking to scene
        ✅ Applying textures
        """
        self._status = "Creating mesh in Blender..."

        try:
            # Extract mesh data
            positions = self._data['positions']
            indices = self._data['indices']
            bounds = self._data.get('bounds', {})

            # Create Blender mesh
            mesh_name = f"Terrain_{self.resolution}"
            mesh = bpy.data.meshes.new(name=mesh_name)

            # Convert flat arrays to vertex/face lists
            # Positions: [x1, y1, z1, x2, y2, z2, ...] -> [(x1,y1,z1), (x2,y2,z2), ...]
            vertices = [(positions[i], positions[i+1], positions[i+2])
                       for i in range(0, len(positions), 3)]

            # Indices: [i1, i2, i3, ...] -> [(i1,i2,i3), ...]
            faces = [(indices[i], indices[i+1], indices[i+2])
                    for i in range(0, len(indices), 3)]

            # Create mesh from data
            mesh.from_pydata(vertices, [], faces)
            mesh.update()

            # Generate UV coordinates for texture mapping
            # Use planar projection based on XY extent (top-down view)
            self._generate_terrain_uvs(mesh, vertices, bounds)

            # Calculate normals for proper shading
            # Note: calc_normals() was removed in Blender 4.1+
            # Use update() which now handles normals automatically, or use calc_normals_split() for custom normals
            if hasattr(mesh, 'calc_normals'):
                mesh.calc_normals()
            # For Blender 4.1+, normals are calculated automatically by update()

            # Create object and link to scene
            obj = bpy.data.objects.new(mesh_name, mesh)
            context.collection.objects.link(obj)

            # Store metadata in object custom properties
            obj['geodb_terrain_resolution'] = self.resolution
            if bounds:
                obj['geodb_terrain_bounds'] = json.dumps(bounds)

            # Store available textures for texture switching
            available_textures = self._data.get('available_textures', [])
            if available_textures:
                obj['geodb_available_textures'] = json.dumps(available_textures)
                print(f"Stored {len(available_textures)} available textures on mesh object")

            # Store legacy texture URLs for backward compatibility
            if self._data.get('satellite_texture_url'):
                obj['geodb_satellite_texture_url'] = self._data['satellite_texture_url']
            if self._data.get('topo_texture_url'):
                obj['geodb_topo_texture_url'] = self._data['topo_texture_url']

            # Store the active texture info
            obj['geodb_active_texture'] = self._data.get('active_texture_type', 'none')
            if self._data.get('active_texture_id'):
                obj['geodb_active_texture_id'] = self._data['active_texture_id']
            if self._data.get('active_texture_name'):
                obj['geodb_active_texture_name'] = self._data['active_texture_name']

            # Apply texture if downloaded
            texture_path = self._data.get('texture_local_path')
            if texture_path and os.path.exists(texture_path):
                self._apply_terrain_texture(obj, texture_path)

                # Set viewport shading to Solid with Texture color type
                # This makes the texture visible without user having to change settings
                self._set_viewport_texture_display(context)

            # Select the new terrain object
            obj.select_set(True)
            context.view_layer.objects.active = obj

            # Auto-adjust view to the terrain mesh
            adjust_view_to_objects(context, [obj])

            # Report success
            num_verts = len(vertices)
            num_faces = len(faces)
            self.report({'INFO'},
                       f"Imported terrain: {num_verts:,} vertices, {num_faces:,} triangles")

        except Exception as e:
            raise Exception(f"Error creating Blender mesh: {str(e)}")

    def _generate_terrain_uvs(self, mesh: bpy.types.Mesh, vertices: list, bounds: dict):
        """
        Generate UV coordinates for terrain mesh using planar projection.

        Maps the XY extent of the terrain to UV space (0-1, 0-1) so the
        satellite/topo texture aligns correctly with the geographic extent.

        Args:
            mesh: Blender mesh object
            vertices: List of (x, y, z) vertex tuples
            bounds: Optional bounds dict with minX, maxX, minY, maxY
        """
        # Calculate bounds from vertices if not provided
        if bounds and 'minX' in bounds:
            min_x = bounds['minX']
            max_x = bounds['maxX']
            min_y = bounds['minY']
            max_y = bounds['maxY']
        else:
            # Calculate from vertices
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

        # Avoid division by zero
        range_x = max_x - min_x if max_x != min_x else 1.0
        range_y = max_y - min_y if max_y != min_y else 1.0

        print(f"Generating UVs for terrain: X({min_x:.2f} to {max_x:.2f}), Y({min_y:.2f} to {max_y:.2f})")

        # Create UV layer
        uv_layer = mesh.uv_layers.new(name='UVMap')

        # Map each vertex to UV space based on XY position
        # In Blender, UV.x corresponds to X and UV.y corresponds to Y
        for face in mesh.polygons:
            for loop_idx in face.loop_indices:
                vertex_idx = mesh.loops[loop_idx].vertex_index
                vertex = vertices[vertex_idx]

                # Normalize X,Y to 0-1 range for UV coordinates
                u = (vertex[0] - min_x) / range_x
                v = (vertex[1] - min_y) / range_y

                uv_layer.data[loop_idx].uv = (u, v)

        print(f"Generated UV coordinates for {len(mesh.polygons)} faces")

    def _set_viewport_texture_display(self, context):
        """
        Set viewport shading to display textures in Solid mode.

        Configures the 3D viewport to use Solid shading with Texture color type,
        so the terrain texture is visible immediately after import.
        """
        # Find all 3D viewports and set their shading
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        # Set to Solid shading mode
                        space.shading.type = 'SOLID'
                        # Set color type to Texture so materials with textures display
                        space.shading.color_type = 'TEXTURE'
                        print("Set viewport shading to Solid with Texture display")
                        return  # Only need to set the first/active viewport

    def _apply_terrain_texture(self, obj: bpy.types.Object, texture_path: str):
        """
        Create material with texture and apply to terrain mesh.

        Args:
            obj: Terrain mesh object
            texture_path: Path to texture image file
        """
        # Load texture image
        img = bpy.data.images.load(texture_path)
        img.pack()  # Embed in .blend file

        # Create material with shader nodes
        mat = bpy.data.materials.new(name=f"Terrain_Material_{self.resolution}")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Clear default nodes
        nodes.clear()

        # Create shader nodes
        node_tex_coord = nodes.new(type='ShaderNodeTexCoord')
        node_image = nodes.new(type='ShaderNodeTexImage')
        node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
        node_output = nodes.new(type='ShaderNodeOutputMaterial')

        # Set image
        node_image.image = img

        # Position nodes
        node_tex_coord.location = (-600, 0)
        node_image.location = (-300, 0)
        node_bsdf.location = (0, 0)
        node_output.location = (300, 0)

        # Link nodes: UV -> Image -> BSDF -> Output
        links.new(node_tex_coord.outputs['UV'], node_image.inputs['Vector'])
        links.new(node_image.outputs['Color'], node_bsdf.inputs['Base Color'])
        links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])

        # Apply material to mesh
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

        print(f"Applied texture material to terrain: {img.name}")


# Cache for switch texture operator (populated from mesh object properties)
_switch_textures_cache: List[Dict[str, Any]] = []


def _get_switch_texture_enum_items(self, context) -> List[Tuple[str, str, str]]:
    """
    Dynamic callback to populate texture dropdown for texture switching.

    This function reads from _switch_textures_cache which is populated from
    the mesh object's stored available_textures property.
    """
    global _switch_textures_cache

    items = []

    # Add items from cached available textures
    for tex in _switch_textures_cache:
        tex_id = str(tex.get('id', ''))
        tex_name = tex.get('name', 'Unknown Texture')
        tex_type = tex.get('type', 'unknown')
        description = f"{tex_name} ({tex_type})"

        items.append((tex_id, tex_name, description))

    # Always add a "No Texture" option at the end
    items.append(('none', 'No Texture', 'Plain mesh without texture'))

    # If no textures found, add a placeholder
    if len(items) == 1:  # Only the "none" option
        items.insert(0, ('unavailable', 'No Textures Available', 'No textures stored on this terrain'))

    return items


class GEODB_OT_SwitchTerrainTexture(GeoDBAsyncOperator):
    """Switch texture on existing terrain mesh"""
    bl_idname = "geodb.switch_terrain_texture"
    bl_label = "Switch Terrain Texture"
    bl_description = "Change the texture overlay on an existing terrain mesh"
    bl_options = {'REGISTER', 'UNDO'}

    # Dynamic texture selection from mesh object's stored textures
    selected_texture: EnumProperty(
        name="Texture",
        description="Texture overlay to apply to terrain",
        items=_get_switch_texture_enum_items
    )

    _target_object_name = None  # Stores object name for thread access

    @classmethod
    def poll(cls, context):
        """Only enable when a terrain mesh is selected"""
        obj = context.active_object
        if obj is None:
            return False
        return obj.get('geodb_terrain_resolution') is not None

    def invoke(self, context, event):
        """Show dialog with texture options"""
        global _switch_textures_cache

        obj = context.active_object

        # Load available textures from mesh object properties
        available_textures_json = obj.get('geodb_available_textures')
        if available_textures_json:
            try:
                _switch_textures_cache = json.loads(available_textures_json)
                print(f"Loaded {len(_switch_textures_cache)} textures from mesh object")
            except json.JSONDecodeError:
                _switch_textures_cache = []
                print("Failed to parse available_textures JSON from mesh object")
        else:
            _switch_textures_cache = []
            print("No available_textures stored on mesh object")

        # Pre-select current texture
        current_texture_id = obj.get('geodb_active_texture_id')
        if current_texture_id:
            self.selected_texture = str(current_texture_id)

        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        global _switch_textures_cache

        layout = self.layout
        obj = context.active_object

        layout.prop(self, "selected_texture")

        # Show texture count and current texture
        box = layout.box()
        box.label(text="Texture Info:", icon='INFO')

        current_name = obj.get('geodb_active_texture_name', 'None')
        box.label(text=f"Current: {current_name}")
        box.label(text=f"Available: {len(_switch_textures_cache)} textures")

    def execute(self, context):
        """Called when user clicks OK on dialog. Start the async operation."""
        # Check if another operation is already running
        if context.scene.geodb.import_active:
            self.report({'WARNING'}, "Another import operation is already running")
            return {'CANCELLED'}

        # Mark operation as active
        context.scene.geodb.import_active = True
        context.scene.geodb.import_progress = 0.0
        context.scene.geodb.import_status = "Initializing..."

        # Reset state
        self.__class__._progress = 0.0
        self.__class__._status = "Initializing..."
        self.__class__._data = None
        self.__class__._error = None

        # Store object name for thread access (context not available in threads)
        self.__class__._target_object_name = context.active_object.name

        # Start background thread
        import threading
        self.__class__._thread = threading.Thread(target=self.download_data)
        self.__class__._thread.start()

        # Start modal timer (checks every 0.1 seconds)
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def download_data(self):
        """Download the selected texture in background thread."""
        global _switch_textures_cache

        try:
            # Get object by name (context not available in threads)
            obj = bpy.data.objects.get(self._target_object_name)

            if obj is None or obj.get('geodb_terrain_resolution') is None:
                self._error = "No terrain mesh selected"
                return

            # Handle "none" selection - remove texture
            if self.selected_texture in ('none', 'unavailable'):
                self._status = "Removing texture..."
                self._data = {
                    'texture_type': 'none',
                    'object_name': obj.name,
                    'texture_id': None,
                    'texture_name': None
                }
                self._progress = 1.0
                return

            # Find selected texture from cache
            texture_url = None
            texture_name = None
            texture_type = 'custom'

            for tex in _switch_textures_cache:
                if str(tex.get('id', '')) == self.selected_texture:
                    texture_url = tex.get('url')
                    texture_name = tex.get('name', 'Unknown')
                    texture_type = tex.get('type', 'custom')
                    self._status = f"Downloading {texture_name}..."
                    break

            if not texture_url:
                self._error = f"Selected texture not found in available textures"
                return

            self._progress = 0.3

            # Download texture
            try:
                texture_path = self._download_texture(texture_url)
                self._data = {
                    'texture_type': texture_type,
                    'texture_path': texture_path,
                    'texture_id': self.selected_texture,
                    'texture_name': texture_name,
                    'object_name': obj.name
                }
                self._progress = 1.0
                self._status = "Download complete"
            except Exception as e:
                self._error = f"Failed to download texture: {str(e)}"

        except Exception as e:
            self._error = f"Error: {str(e)}"
            import traceback
            traceback.print_exc()

    def _download_texture(self, url: str) -> str:
        """Download texture image to temp file."""
        import requests

        # Check if this is a pre-signed URL (contains AWS signature params)
        # Pre-signed URLs already have authentication baked in
        is_presigned = 'AWSAccessKeyId=' in url or 'Signature=' in url or 'X-Amz-Signature=' in url

        # If relative URL, prepend base URL and use authentication
        if url.startswith('/'):
            from ..api.auth import get_api_client
            client = get_api_client()
            base_url = client.base_url.rstrip('/api/v1/')
            url = base_url + url
            # Use authenticated request for relative URLs
            headers = client._get_headers()
        elif is_presigned:
            # Pre-signed URLs don't need authentication headers
            headers = {}
        else:
            # For other absolute URLs, try with authentication
            from ..api.auth import get_api_client
            client = get_api_client()
            headers = client._get_headers()

        print(f"Downloading texture from: {url}")
        print(f"Using authentication: {bool(headers)}")

        # Download texture
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()

        # Save to temp file
        suffix = '.jpg'
        if '.png' in url.lower():
            suffix = '.png'

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        temp_file.close()

        print(f"Texture downloaded to: {temp_file.name}")
        return temp_file.name

    def finish_in_main_thread(self, context):
        """Apply the new texture in main thread."""
        self._status = "Applying texture..."

        try:
            # Find the terrain object by name
            obj_name = self._data.get('object_name')
            obj = bpy.data.objects.get(obj_name)

            if obj is None:
                raise Exception(f"Terrain object '{obj_name}' not found")

            texture_type = self._data.get('texture_type')
            texture_path = self._data.get('texture_path')
            texture_id = self._data.get('texture_id')
            texture_name = self._data.get('texture_name')

            if texture_type == 'none':
                # Remove texture - apply plain material
                self._apply_plain_material(obj)
                obj['geodb_active_texture'] = 'none'
                obj['geodb_active_texture_id'] = ''
                obj['geodb_active_texture_name'] = ''
                self.report({'INFO'}, "Removed texture from terrain")
            else:
                # Apply new texture
                self._apply_texture_material(obj, texture_path, texture_type)
                obj['geodb_active_texture'] = texture_type
                if texture_id:
                    obj['geodb_active_texture_id'] = texture_id
                if texture_name:
                    obj['geodb_active_texture_name'] = texture_name
                self.report({'INFO'}, f"Applied {texture_name or texture_type} texture to terrain")

        except Exception as e:
            raise Exception(f"Error applying texture: {str(e)}")

    def _apply_plain_material(self, obj: bpy.types.Object):
        """Apply a plain material without texture."""
        # Create or reuse plain material
        mat_name = "Terrain_Material_Plain"
        mat = bpy.data.materials.get(mat_name)

        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            # Clear default nodes
            nodes.clear()

            # Create shader nodes
            node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            node_output = nodes.new(type='ShaderNodeOutputMaterial')

            # Set terrain color (brownish-gray)
            node_bsdf.inputs['Base Color'].default_value = (0.545, 0.451, 0.333, 1.0)
            node_bsdf.inputs['Roughness'].default_value = 0.8

            # Position nodes
            node_bsdf.location = (0, 0)
            node_output.location = (300, 0)

            # Link nodes
            links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])

        # Apply material to mesh
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

        print("Applied plain material to terrain")

    def _ensure_terrain_uvs(self, obj: bpy.types.Object):
        """
        Ensure terrain mesh has UV coordinates for texture mapping.

        If the mesh doesn't have a UV layer, generates one using planar projection
        based on the XY extent. This handles terrains imported before UV generation
        was added.

        Args:
            obj: Terrain mesh object
        """
        mesh = obj.data

        # Check if UV layer already exists
        if mesh.uv_layers:
            print(f"Terrain already has UV layer: {mesh.uv_layers[0].name}")
            return

        print("Terrain missing UV layer - generating planar projection UVs...")

        # Get vertices
        vertices = [(v.co.x, v.co.y, v.co.z) for v in mesh.vertices]

        # Calculate bounds from vertices
        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        # Avoid division by zero
        range_x = max_x - min_x if max_x != min_x else 1.0
        range_y = max_y - min_y if max_y != min_y else 1.0

        print(f"Generating UVs for terrain: X({min_x:.2f} to {max_x:.2f}), Y({min_y:.2f} to {max_y:.2f})")

        # Create UV layer
        uv_layer = mesh.uv_layers.new(name='UVMap')

        # Map each vertex to UV space based on XY position
        for face in mesh.polygons:
            for loop_idx in face.loop_indices:
                vertex_idx = mesh.loops[loop_idx].vertex_index
                vertex = vertices[vertex_idx]

                # Normalize X,Y to 0-1 range for UV coordinates
                u = (vertex[0] - min_x) / range_x
                v = (vertex[1] - min_y) / range_y

                uv_layer.data[loop_idx].uv = (u, v)

        print(f"Generated UV coordinates for {len(mesh.polygons)} faces")

    def _apply_texture_material(self, obj: bpy.types.Object, texture_path: str, texture_type: str):
        """Apply a textured material to terrain."""
        # Ensure UV coordinates exist for texture mapping
        self._ensure_terrain_uvs(obj)

        # Load texture image
        img = bpy.data.images.load(texture_path)
        img.pack()  # Embed in .blend file

        # Create material with shader nodes
        mat_name = f"Terrain_Material_{texture_type}"
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Clear default nodes
        nodes.clear()

        # Create shader nodes
        node_tex_coord = nodes.new(type='ShaderNodeTexCoord')
        node_image = nodes.new(type='ShaderNodeTexImage')
        node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
        node_output = nodes.new(type='ShaderNodeOutputMaterial')

        # Set image
        node_image.image = img

        # Position nodes
        node_tex_coord.location = (-600, 0)
        node_image.location = (-300, 0)
        node_bsdf.location = (0, 0)
        node_output.location = (300, 0)

        # Link nodes: UV -> Image -> BSDF -> Output
        links.new(node_tex_coord.outputs['UV'], node_image.inputs['Vector'])
        links.new(node_image.outputs['Color'], node_bsdf.inputs['Base Color'])
        links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])

        # Apply material to mesh
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

        print(f"Applied {texture_type} texture material to terrain: {img.name}")
