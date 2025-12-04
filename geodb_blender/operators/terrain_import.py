"""
Terrain mesh import operator with background loading and progress feedback.

This operator imports terrain/DEM meshes from the geoDB API using the async pattern
to prevent UI freezing during large downloads.
"""

import bpy
import json
import os
import tempfile
from bpy.props import EnumProperty
from typing import Dict, Any

from .async_base import GeoDBAsyncOperator
from ..api.data import GeoDBData
from ..api.client import GeoDBAPIClient


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
        try:
            # Get project code from scene (thread-safe read)
            scene = bpy.context.scene
            if not scene.geodb.selected_project_code:
                self._error = "No project selected"
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

            # Step 2: Download satellite texture if available
            self._status = "Downloading satellite texture..."

            satellite_url = mesh_data.get('satellite_texture_url')
            texture_path = None

            if satellite_url:
                try:
                    # Download texture to temp file
                    texture_path = self._download_texture(satellite_url)
                    mesh_data['texture_local_path'] = texture_path
                except Exception as e:
                    print(f"Warning: Failed to download texture: {e}")
                    # Continue without texture - not a fatal error

            self._progress = 0.7

            # Step 3: Process metadata
            self._status = "Processing mesh metadata..."

            # Store texture URLs for future use
            mesh_data['topo_texture_url'] = mesh_data.get('topo_texture_url')

            print(f"Terrain mesh ready: {len(mesh_data['positions']) // 3} vertices")
            if satellite_url:
                print(f"Satellite texture: {satellite_url}")
            if mesh_data.get('topo_texture_url'):
                print(f"Topo texture: {mesh_data['topo_texture_url']}")

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
            url: Texture URL (may be relative or absolute)

        Returns:
            str: Path to downloaded temp file
        """
        import requests

        # If relative URL, prepend base URL
        if url.startswith('/'):
            client = GeoDBAPIClient()
            base_url = client.base_url.rstrip('/api/v1/')
            url = base_url + url

        print(f"Downloading texture from: {url}")

        # Get API client for authenticated request
        from ..api.auth import get_api_client
        client = get_api_client()

        # Download with authentication
        response = requests.get(url, headers=client.headers, stream=True)
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

            # Calculate normals for proper shading
            mesh.calc_normals()

            # Create object and link to scene
            obj = bpy.data.objects.new(mesh_name, mesh)
            context.collection.objects.link(obj)

            # Store metadata in object custom properties
            obj['geodb_terrain_resolution'] = self.resolution
            if bounds:
                obj['geodb_terrain_bounds'] = json.dumps(bounds)

            # Store texture URLs for potential texture switching
            if self._data.get('satellite_texture_url'):
                obj['geodb_satellite_texture_url'] = self._data['satellite_texture_url']
            if self._data.get('topo_texture_url'):
                obj['geodb_topo_texture_url'] = self._data['topo_texture_url']

            # Apply texture if downloaded
            texture_path = self._data.get('texture_local_path')
            if texture_path and os.path.exists(texture_path):
                self._apply_terrain_texture(obj, texture_path)

            # Select the new terrain object
            obj.select_set(True)
            context.view_layer.objects.active = obj

            # Report success
            num_verts = len(vertices)
            num_faces = len(faces)
            self.report({'INFO'},
                       f"Imported terrain: {num_verts:,} vertices, {num_faces:,} triangles")

        except Exception as e:
            raise Exception(f"Error creating Blender mesh: {str(e)}")

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
