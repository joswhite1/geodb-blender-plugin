"""
Authentication module for the geoDB Blender add-on.

This module handles user authentication with the geoDB API,
including login, token management, secure credential storage,
and two-factor authentication (2FA).
"""

import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator, Panel

from .client import GeoDBAPIClient
from .. import is_dev_mode_enabled
from ..utils.logging import logger

# Global state for 2FA flow
_pending_2fa_has_recovery_email = False

# Global API client instance
api_client = None

def get_addon_name():
    """Get the addon name for preferences lookup.

    When installed as a Blender 4.2+ extension, the addon name includes
    the extension path prefix (e.g., 'bl_ext.user_default.geodb_blender').
    This function returns the correct name for the current installation.
    """
    # __name__ for this module is something like 'geodb_blender.api.auth'
    # or 'bl_ext.user_default.geodb_blender.api.auth'
    # We need the root package name
    return __name__.rsplit('.', 2)[0]  # Remove '.api.auth' suffix


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
        addon_name = get_addon_name()
        addon_prefs = bpy.context.preferences.addons.get(addon_name)
        preferences = addon_prefs.preferences if addon_prefs else None
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
        global _pending_2fa_has_recovery_email

        # Validate inputs
        if not self.username or not self.password:
            logger.error("Email and password are required")
            self.report({'ERROR'}, "Email and password are required")
            return {'CANCELLED'}

        if self.save_credentials and not self.token_password:
            logger.error("Encryption password is required when saving credentials")
            self.report({'ERROR'}, "Encryption password is required when saving credentials")
            return {'CANCELLED'}

        if self.save_credentials and self.token_password and len(self.token_password) < 8:
            self.report({'ERROR'}, "Token encryption password must be at least 8 characters.")
            return {'CANCELLED'}

        # Get API client
        try:
            client = get_api_client()
        except Exception as e:
            logger.error("Failed to get API client: %s", type(e).__name__)
            logger.debug("API client initialization failed", exc_info=True)
            self.report({'ERROR'}, f"Failed to initialize API client: {str(e)}")
            return {'CANCELLED'}

        # Attempt login
        try:
            success, message, extra_data = client.login(
                username=self.username,
                password=self.password,
                save_token=self.save_credentials,
                token_password=self.token_password if self.save_credentials else None,
            )
        except Exception as e:
            logger.error("Exception during login: %s", type(e).__name__)
            logger.debug("Login exception details", exc_info=True)
            self.report({'ERROR'}, f"Login error: {str(e)}")
            return {'CANCELLED'}

        # Check if 2FA is required
        if extra_data and extra_data.get('requires_2fa'):
            logger.debug("2FA required")
            # Store whether recovery email is available
            _pending_2fa_has_recovery_email = extra_data.get('has_recovery_email', False)

            # Overwrite credential strings before clearing
            self.username = "\x00" * max(len(self.username), 1)
            self.password = "\x00" * max(len(self.password), 1)
            self.token_password = "\x00" * max(len(self.token_password), 1)
            self.username = ""
            self.password = ""
            self.token_password = ""

            # Open 2FA verification dialog
            self.report({'INFO'}, "Two-factor authentication required")
            bpy.ops.geodb.verify_2fa('INVOKE_DEFAULT')
            return {'FINISHED'}

        if success:
            logger.debug("Login successful")
            # Store user info in scene properties
            context.scene.geodb.is_logged_in = True
            user_info = client.get_user_info()
            if user_info:
                context.scene.geodb.username = user_info.get('username', '')

            # Overwrite credential strings before clearing
            self.username = "\x00" * max(len(self.username), 1)
            self.password = "\x00" * max(len(self.password), 1)
            self.token_password = "\x00" * max(len(self.token_password), 1)
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
            logger.debug("Login failed")
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
                if user_info:
                    # Check both 'username' and 'email' fields
                    username = user_info.get('username') or user_info.get('email', '')
                    context.scene.geodb.username = username
                else:
                    logger.warning("No user info available after token unlock")

                # Clear sensitive data
                self.token_password = "\x00" * max(len(self.token_password), 1)
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

class GEODB_OT_Verify2FA(Operator):
    """Verify two-factor authentication code"""
    bl_idname = "geodb.verify_2fa"
    bl_label = "Two-Factor Authentication"
    bl_description = "Enter your 2FA code from your authenticator app"

    code: StringProperty(
        name="Authentication Code",
        description="Enter the 6-digit code from your authenticator app",
        maxlen=6,
    )

    verification_mode: EnumProperty(
        name="Verification Mode",
        items=[
            ('TOTP', "Authenticator App", "Use code from your authenticator app"),
            ('RECOVERY', "Recovery Email", "Request a code via your recovery email"),
        ],
        default='TOTP',
    )

    recovery_code: StringProperty(
        name="Recovery Code",
        description="Enter the 6-digit code sent to your recovery email",
        maxlen=6,
    )

    _recovery_email_masked: str = ""
    _recovery_requested: bool = False
    _error_message: str = ""

    def invoke(self, context, event):
        # Reset state
        self._recovery_email_masked = ""
        self._recovery_requested = False
        self._error_message = ""
        self.code = ""
        self.recovery_code = ""
        self.verification_mode = 'TOTP'
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        global _pending_2fa_has_recovery_email
        layout = self.layout

        # Show error message if any
        if self._error_message:
            box = layout.box()
            box.alert = True
            box.label(text=self._error_message, icon='ERROR')

        # Show verification mode selector only if recovery email is available
        if _pending_2fa_has_recovery_email:
            layout.prop(self, "verification_mode", expand=True)
            layout.separator()

        if self.verification_mode == 'TOTP':
            layout.label(text="Enter the 6-digit code from your authenticator app:")
            layout.prop(self, "code")
            layout.label(text="Open Google Authenticator, Authy, or similar app", icon='INFO')
        else:
            # Recovery mode
            if not self._recovery_requested:
                layout.label(text="Click 'Send Recovery Code' to receive a code via email.")
                layout.operator("geodb.request_2fa_recovery", text="Send Recovery Code", icon='EXPORT')
            else:
                if self._recovery_email_masked:
                    layout.label(text=f"Code sent to: {self._recovery_email_masked}", icon='CHECKMARK')
                layout.label(text="Enter the 6-digit code from your email:")
                layout.prop(self, "recovery_code")

        layout.separator()
        layout.operator("geodb.cancel_2fa", text="Cancel", icon='X')

    def execute(self, context):
        client = get_api_client()

        if self.verification_mode == 'TOTP':
            # Verify TOTP code
            if not self.code or len(self.code) != 6:
                self._error_message = "Please enter a 6-digit code"
                return context.window_manager.invoke_props_dialog(self, width=400)

            success, message = client.verify_2fa(self.code)
        else:
            # Verify recovery code
            if not self.recovery_code or len(self.recovery_code) != 6:
                self._error_message = "Please enter a 6-digit recovery code"
                return context.window_manager.invoke_props_dialog(self, width=400)

            success, message = client.verify_2fa_recovery(self.recovery_code)

        if success:
            # Login successful
            context.scene.geodb.is_logged_in = True
            user_info = client.get_user_info()
            if user_info:
                context.scene.geodb.username = user_info.get('username', '')

            # Force UI redraw
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()

            self.report({'INFO'}, message)
            return {'FINISHED'}
        else:
            # Verification failed - show error and let user retry
            self._error_message = message
            self.code = ""
            self.recovery_code = ""
            return context.window_manager.invoke_props_dialog(self, width=400)


class GEODB_OT_Request2FARecovery(Operator):
    """Request a 2FA recovery code via email"""
    bl_idname = "geodb.request_2fa_recovery"
    bl_label = "Send Recovery Code"
    bl_description = "Send a recovery code to your registered recovery email"

    def execute(self, context):
        client = get_api_client()
        success, message, masked_email = client.request_2fa_recovery()

        if success:
            # Update the verify dialog state
            # We need to re-invoke the dialog with updated state
            self.report({'INFO'}, f"Recovery code sent to {masked_email}")

            # Store the masked email for display
            GEODB_OT_Verify2FA._recovery_email_masked = masked_email or ""
            GEODB_OT_Verify2FA._recovery_requested = True
            GEODB_OT_Verify2FA._error_message = ""

            # Re-open the dialog
            bpy.ops.geodb.verify_2fa('INVOKE_DEFAULT')
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


class GEODB_OT_Cancel2FA(Operator):
    """Cancel the 2FA verification process"""
    bl_idname = "geodb.cancel_2fa"
    bl_label = "Cancel 2FA"
    bl_description = "Cancel the two-factor authentication process"

    def execute(self, context):
        client = get_api_client()
        client.cancel_2fa()

        # Reset global state
        global _pending_2fa_has_recovery_email
        _pending_2fa_has_recovery_email = False

        self.report({'INFO'}, "2FA verification cancelled")
        return {'FINISHED'}


class GEODB_OT_ResetAPIClient(Operator):
    """Toggle between development and production server"""
    bl_idname = "geodb.reset_api_client"
    bl_label = "Switch Server"
    bl_description = "Toggle between local development and production server"

    def execute(self, context):
        # Get addon preferences
        preferences = context.preferences.addons.get(get_addon_name())
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
            preferences = context.preferences.addons.get(get_addon_name())
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

            # Check if there's a pending 2FA verification
            if client.has_pending_2fa():
                box = layout.box()
                box.label(text="2FA Verification Required", icon='LOCKED')
                box.operator("geodb.verify_2fa", text="Enter 2FA Code", icon='KEY_HLT')
                box.operator("geodb.cancel_2fa", text="Cancel", icon='X')
            elif client.has_saved_token():
                # Show unlock token button
                layout.operator("geodb.unlock_token", icon='UNLOCKED')
                layout.label(text="or")
                # Show login button
                layout.operator("geodb.login", icon='USER')
            else:
                # Show login button
                layout.operator("geodb.login", icon='USER')

def register():
    bpy.utils.register_class(GEODB_OT_Login)
    bpy.utils.register_class(GEODB_OT_Logout)
    bpy.utils.register_class(GEODB_OT_UnlockToken)
    bpy.utils.register_class(GEODB_OT_Verify2FA)
    bpy.utils.register_class(GEODB_OT_Request2FARecovery)
    bpy.utils.register_class(GEODB_OT_Cancel2FA)
    bpy.utils.register_class(GEODB_OT_ResetAPIClient)
    bpy.utils.register_class(GEODB_PT_Authentication)

def unregister():
    bpy.utils.unregister_class(GEODB_PT_Authentication)
    bpy.utils.unregister_class(GEODB_OT_ResetAPIClient)
    bpy.utils.unregister_class(GEODB_OT_Cancel2FA)
    bpy.utils.unregister_class(GEODB_OT_Request2FARecovery)
    bpy.utils.unregister_class(GEODB_OT_Verify2FA)
    bpy.utils.unregister_class(GEODB_OT_UnlockToken)
    bpy.utils.unregister_class(GEODB_OT_Logout)
    bpy.utils.unregister_class(GEODB_OT_Login)
