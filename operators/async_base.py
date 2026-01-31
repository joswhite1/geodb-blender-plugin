"""
Base class for async operators with background thread data fetching.

This module provides GeoDBAsyncOperator, a base class for all operators
that need to perform long-running operations (like API calls, file downloads)
without freezing the Blender UI.

Key Features:
- Background thread for network operations
- Progress bar feedback in UI
- ESC key cancellation support
- Thread-safe Blender object creation in main thread
"""

import threading
import bpy
from bpy.types import Operator


class GeoDBAsyncOperator(Operator):
    """
    Base class for operators with background data fetching.

    Subclasses must override:
    - download_data(): Runs in background thread (network calls, JSON processing)
    - finish_in_main_thread(): Runs in main thread (create Blender objects)

    Usage:
        class GEODB_OT_MyOperator(GeoDBAsyncOperator):
            bl_idname = "geodb.my_operator"
            bl_label = "My Operator"

            def download_data(self):
                self._status = "Downloading..."
                self._progress = 0.5
                self._data = fetch_from_api()
                self._progress = 1.0

            def finish_in_main_thread(self, context):
                create_blender_objects(self._data)
    """

    # Class variables for tracking async operation state
    _timer = None
    _thread = None
    _progress = 0.0
    _status = ""
    _data = None
    _error = None

    def modal(self, context, event):
        """
        Called repeatedly while operation runs.

        Handles:
        - ESC key cancellation
        - Progress display updates
        - Thread completion detection
        - Error handling
        """
        # Handle cancellation
        if event.type == 'ESC':
            self.cancel(context)
            return {'CANCELLED'}

        # Check timer tick
        if event.type == 'TIMER':
            # Update progress display in UI
            context.scene.geodb.import_progress = self._progress
            context.scene.geodb.import_status = self._status
            context.area.tag_redraw()

            # Check if thread finished
            if self._thread and not self._thread.is_alive():
                if self._error:
                    # Thread failed - show error
                    self.report({'ERROR'}, self._error)
                    self.cleanup(context)
                    return {'CANCELLED'}
                else:
                    # Thread succeeded - create Blender objects NOW (main thread)
                    try:
                        self.finish_in_main_thread(context)
                        self.cleanup(context)
                        return {'FINISHED'}
                    except Exception as e:
                        self.report({'ERROR'}, f"Error creating objects: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        self.cleanup(context)
                        return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        """
        Start the async operation.

        Called once when user clicks the button.
        Sets up background thread and modal timer.
        """
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
        self.__class__._thread = threading.Thread(target=self.download_data)
        self.__class__._thread.start()

        # Start modal timer (checks every 0.1 seconds)
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def download_data(self):
        """
        Override this method in subclasses.

        Runs in BACKGROUND THREAD - can do:
        ✅ Network API calls
        ✅ File downloads
        ✅ JSON parsing
        ✅ Data processing

        Cannot do:
        ❌ Create Blender meshes
        ❌ Create materials
        ❌ Modify scene

        Update progress:
            self._status = "Downloading mesh..."
            self._progress = 0.5  # 0.0 to 1.0

        Store results:
            self._data = downloaded_data

        Report errors:
            self._error = "Failed to download"
        """
        raise NotImplementedError("Subclass must implement download_data()")

    def finish_in_main_thread(self, context):
        """
        Override this method in subclasses.

        Runs in MAIN THREAD after download completes - can do:
        ✅ Create Blender meshes
        ✅ Create materials
        ✅ Link objects to scene
        ✅ Apply textures

        Access downloaded data:
            mesh_data = self._data
        """
        raise NotImplementedError("Subclass must implement finish_in_main_thread()")

    def cleanup(self, context):
        """
        Clean up timer and mark operation complete.

        Called after operation finishes (success or cancel).
        """
        wm = context.window_manager
        if self.__class__._timer:
            wm.event_timer_remove(self.__class__._timer)
            self.__class__._timer = None

        context.scene.geodb.import_active = False
        context.scene.geodb.import_progress = 0.0
        context.scene.geodb.import_status = ""
        context.area.tag_redraw()

    def cancel(self, context):
        """
        User cancelled with ESC key.

        Sets error and triggers cleanup.
        """
        self.__class__._error = "Operation cancelled by user"
        self.cleanup(context)
        self.report({'INFO'}, "Import cancelled by user")
