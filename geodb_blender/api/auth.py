"""
Authentication module for the geoDB Blender add-on.

This module handles user authentication with the geoDB API,
including login, token management, and secure credential storage.
"""

import bpy
from bpy.props import StringProperty, BoolProperty
from bpy.types import Operator, Panel

from .client import GeoDBAPIClient
from .. import is_dev_mode_enabled

# Global API client instance
api_client = None

def get_api_client(use_dev_server=False):
    """Get the global API client instance.
    
    Args:
        use_dev_server: Whether to use the development server.
        
    Returns:
        The API client instance.
    """
    global api_client
    
    if api_client is None:
        # Get development server preference
        preferences = bpy.context.preferences.addons["geodb_blender"].preferences
        use_dev = preferences.use_dev_server if preferences else use_dev_server
        
        # Create API client
        api_client = GeoDBAPIClient(use_dev_server=use_dev)
    
    return api_client

def reset_api_client():
    """Reset the global API client instance."""
    global api_client
    api_client = None

class GEODB_OT_Login(Operator):
    """Log in to the geoDB API"""
    bl_idname = "geodb.login"
    bl_label = "Log In"
    bl_description = "Log in to the geoDB API with your email and password"
    
    username: StringProperty(
        name="Email",
        description="Your geoDB email address",
    )
    
    password: StringProperty(
        name="Password",
        description="Your geoDB password",
        subtype='PASSWORD',
    )
    
    save_credentials: BoolProperty(
        name="Remember Me",
        description="Save your login token securely for future sessions",
        default=False,
    )
    
    token_password: StringProperty(
        name="Encryption Password",
        description="Password to encrypt your saved token (required if Remember Me is checked)",
        subtype='PASSWORD',
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        
        # Username and password fields
        layout.prop(self, "username")
        layout.prop(self, "password")
        
        # Save credentials option
        layout.prop(self, "save_credentials")
        
        # Token password field (only shown if save_credentials is checked)
        if self.save_credentials:
            layout.prop(self, "token_password")
            layout.label(text="This password will be required to unlock your saved token", icon='INFO')
            layout.label(text="in future sessions. It is not sent to the server.")
    
    def execute(self, context):
        # Validate inputs
        if not self.username or not self.password:
            print("ERROR: Email and password are required")
            self.report({'ERROR'}, "Email and password are required")
            return {'CANCELLED'}
        
        if self.save_credentials and not self.token_password:
            print("ERROR: Encryption password is required when saving credentials")
            self.report({'ERROR'}, "Encryption password is required when saving credentials")
            return {'CANCELLED'}
        
        # Get API client
        try:
            client = get_api_client()
            print(f"API client obtained: {client}")
        except Exception as e:
            print(f"ERROR: Failed to get API client: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Failed to initialize API client: {str(e)}")
            return {'CANCELLED'}
        
        # Attempt login
        try:
            success, message = client.login(
                username=self.username,
                password=self.password,
                save_token=self.save_credentials,
                token_password=self.token_password if self.save_credentials else None,
            )
        except Exception as e:
            print(f"ERROR: Exception during login: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Login error: {str(e)}")
            return {'CANCELLED'}
        
        if success:
            print(f"SUCCESS: {message}")
            # Store user info in scene properties
            context.scene.geodb.is_logged_in = True
            user_info = client.get_user_info()
            if user_info:
                context.scene.geodb.username = user_info.get('username', '')
            
            # Clear sensitive data
            self.username = ""
            self.password = ""
            self.token_password = ""
            
            # Force UI redraw to show login status immediately
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            
            self.report({'INFO'}, message)
            return {'FINISHED'}
        else:
            print(f"ERROR: {message}")
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

class GEODB_OT_Logout(Operator):
    """Log out from the geoDB API"""
    bl_idname = "geodb.logout"
    bl_label = "Log Out"
    bl_description = "Log out from the geoDB API and clear your saved token"
    
    def execute(self, context):
        # Get API client
        client = get_api_client()
        
        # Attempt logout
        success, message = client.logout()
        
        # Update scene properties
        context.scene.geodb.is_logged_in = False
        context.scene.geodb.username = ""
        
        # Force UI redraw to show logout status immediately
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        
        if success:
            self.report({'INFO'}, message)
        else:
            self.report({'WARNING'}, message)
        
        return {'FINISHED'}

class GEODB_OT_UnlockToken(Operator):
    """Unlock saved token"""
    bl_idname = "geodb.unlock_token"
    bl_label = "Unlock Saved Token"
    bl_description = "Unlock your saved token with your encryption password"
    
    token_password: StringProperty(
        name="Encryption Password",
        description="Password used to encrypt your saved token",
        subtype='PASSWORD',
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "token_password")
        layout.label(text="Enter the password you used to encrypt your token", icon='INFO')
    
    def execute(self, context):
        # Validate inputs
        if not self.token_password:
            self.report({'ERROR'}, "Encryption password is required")
            return {'CANCELLED'}
        
        # Get API client
        client = get_api_client()
        
        # Attempt to unlock token
        success = client.unlock_saved_token(self.token_password)
        
        if success:
            # Check if token is still valid
            valid, _ = client.check_token()
            
            if valid:
                # Update scene properties
                context.scene.geodb.is_logged_in = True
                user_info = client.get_user_info()
                print(f"DEBUG: user_info after unlock: {user_info}")
                if user_info:
                    # Check both 'username' and 'email' fields
                    username = user_info.get('username') or user_info.get('email', '')
                    print(f"DEBUG: Setting username to: {username}")
                    context.scene.geodb.username = username
                else:
                    print(f"WARNING: No user_info available after token unlock")
                
                # Clear sensitive data
                self.token_password = ""
                
                # Force UI redraw to show login status immediately
                for window in context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()
                
                self.report({'INFO'}, "Token unlocked successfully")
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "Token is no longer valid. Please log in again.")
                return {'CANCELLED'}
        else:
            self.report({'ERROR'}, "Failed to unlock token. Incorrect password or token is corrupted.")
            return {'CANCELLED'}

class GEODB_OT_ResetAPIClient(Operator):
    """Toggle between development and production server"""
    bl_idname = "geodb.reset_api_client"
    bl_label = "Switch Server"
    bl_description = "Toggle between local development and production server"
    
    def execute(self, context):
        # Get addon preferences
        preferences = context.preferences.addons.get("geodb_blender")
        if preferences:
            # Toggle the server setting
            preferences.preferences.use_dev_server = not preferences.preferences.use_dev_server
            
            # Reset the API client to use the new server
            reset_api_client()
            
            # Clear login status since we're switching servers
            context.scene.geodb.is_logged_in = False
            context.scene.geodb.username = ""
            
            server_name = "Local Development (localhost:8000)" if preferences.preferences.use_dev_server else "Production (geodb.io)"
            self.report({'INFO'}, f"Switched to {server_name}. Please log in again.")
        else:
            self.report({'ERROR'}, "Could not access addon preferences")
            return {'CANCELLED'}
        
        # Force UI refresh to show updated server status
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        
        return {'FINISHED'}

class GEODB_PT_Authentication(Panel):
    """Authentication panel for the geoDB add-on"""
    bl_label = "Authentication"
    bl_idname = "GEODB_PT_Authentication"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'geoDB'
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Show server status (only in development mode)
        if is_dev_mode_enabled():
            preferences = context.preferences.addons.get("geodb_blender")
            if preferences:
                box = layout.box()
                if preferences.preferences.use_dev_server:
                    box.label(text="Server: Local Development", icon='CONSOLE')
                    box.label(text="http://localhost:8000/api/v1/")
                else:
                    box.label(text="Server: Production", icon='WORLD')
                    box.label(text="https://geodb.io/api/v1/")

                # Show reset button to apply server changes
                global api_client
                if api_client is not None:
                    box.operator("geodb.reset_api_client", text="Switch Server", icon='FILE_REFRESH')

            layout.separator()
        
        # Check if user is logged in
        if scene.geodb.is_logged_in:
            # Show logged in status
            row = layout.row()
            row.label(text=f"Logged in as: {scene.geodb.username}")
            
            # Show logout button
            layout.operator("geodb.logout", icon='X')
        else:
            # Check if there's a saved token
            client = get_api_client()
            
            if client.has_saved_token():
                # Show unlock token button
                layout.operator("geodb.unlock_token", icon='UNLOCKED')
                layout.label(text="or")
            
            # Show login button
            layout.operator("geodb.login", icon='USER')

def register():
    bpy.utils.register_class(GEODB_OT_Login)
    bpy.utils.register_class(GEODB_OT_Logout)
    bpy.utils.register_class(GEODB_OT_UnlockToken)
    bpy.utils.register_class(GEODB_OT_ResetAPIClient)
    bpy.utils.register_class(GEODB_PT_Authentication)

def unregister():
    bpy.utils.unregister_class(GEODB_PT_Authentication)
    bpy.utils.unregister_class(GEODB_OT_ResetAPIClient)
    bpy.utils.unregister_class(GEODB_OT_UnlockToken)
    bpy.utils.unregister_class(GEODB_OT_Logout)
    bpy.utils.unregister_class(GEODB_OT_Login)