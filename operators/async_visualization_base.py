"""
Extended async operator base for visualization with multi-stage progress tracking.

This module provides GeoDBAsyncVisualizationOperator, which extends GeoDBAsyncOperator
with support for multi-stage progress reporting. This is useful for visualization
operators that have distinct phases like:
1. Fetching collars
2. Fetching samples/intervals
3. Fetching traces
4. Creating Blender objects

Progress Format:
    "Stage 2/4: Fetching samples... 1,500/3,000"
"""

import threading
import bpy
from bpy.types import Operator


class GeoDBAsyncVisualizationOperator(Operator):
    """
    Extended async operator with multi-stage progress tracking.

    Subclasses must override:
    - download_data(): Runs in background thread (network calls, data processing)
    - finish_in_main_thread(): Runs in main thread (create Blender objects)

    Progress tracking:
    - Define _stages as list of (name, weight) tuples
    - Use set_stage() to move to next stage
    - Use update_stage_progress() for within-stage progress

    Example:
        class GEODB_OT_MyVisualization(GeoDBAsyncVisualizationOperator):
            bl_idname = "geodb.my_visualization"
            bl_label = "My Visualization"

            _stages = [
                ('Validating', 0.05),      # 5% of total
                ('Fetching samples', 0.40), # 40% of total
                ('Fetching traces', 0.40),  # 40% of total
                ('Processing', 0.15),       # 15% of total
            ]

            def download_data(self):
                self.set_stage(0)  # "Stage 1/4: Validating..."
                # validation code

                self.set_stage(1)  # "Stage 2/4: Fetching samples..."
                for i, sample in enumerate(samples):
                    self.update_stage_progress(i, len(samples))
                    # fetch sample

                self.set_stage(2)  # "Stage 3/4: Fetching traces..."
                # etc.
    """

    # Class variables for tracking async operation state
    _timer = None
    _thread = None
    _progress = 0.0
    _status = ""
    _data = None
    _error = None
    _cancelled = False

    # Multi-stage progress tracking
    # Override in subclass: [('Stage Name', weight), ...]
    # Weights should sum to 1.0
    _stages = [('Processing', 1.0)]
    _current_stage = 0
    _stage_items_done = 0
    _stage_items_total = 0

    def set_stage(self, index: int, name: str = None):
        """
        Move to a specific stage and update status.

        Args:
            index: Stage index (0-based)
            name: Optional custom name override (uses _stages[index][0] by default)
        """
        self.__class__._current_stage = index
        self.__class__._stage_items_done = 0
        self.__class__._stage_items_total = 0

        # Calculate base progress from completed stages
        base_progress = sum(
            self._stages[i][1] for i in range(index)
        ) if index > 0 else 0.0

        self.__class__._progress = base_progress

        # Get stage name
        if name is None and index < len(self._stages):
            name = self._stages[index][0]
        elif name is None:
            name = f"Stage {index + 1}"

        total_stages = len(self._stages)
        self.__class__._status = f"Stage {index + 1}/{total_stages}: {name}..."

    def update_stage_progress(self, done: int, total: int):
        """
        Update progress within current stage.

        Args:
            done: Number of items completed
            total: Total number of items in this stage
        """
        self.__class__._stage_items_done = done
        self.__class__._stage_items_total = total

        if total <= 0:
            return

        # Calculate stage weight
        if self._current_stage < len(self._stages):
            stage_weight = self._stages[self._current_stage][1]
            stage_name = self._stages[self._current_stage][0]
        else:
            stage_weight = 0.0
            stage_name = "Processing"

        # Calculate base progress from completed stages
        base_progress = sum(
            self._stages[i][1] for i in range(self._current_stage)
        ) if self._current_stage > 0 else 0.0

        # Add progress within current stage
        stage_progress = (done / total) * stage_weight
        self.__class__._progress = base_progress + stage_progress

        # Update status with count
        total_stages = len(self._stages)
        done_formatted = f"{done:,}"
        total_formatted = f"{total:,}"
        self.__class__._status = (
            f"Stage {self._current_stage + 1}/{total_stages}: "
            f"{stage_name}... {done_formatted}/{total_formatted}"
        )

    def is_cancelled(self) -> bool:
        """
        Check if operation was cancelled by user.

        Call this in download_data() loops to support ESC cancellation.

        Returns:
            True if user pressed ESC
        """
        return self.__class__._cancelled

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
            self.__class__._cancelled = True
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
                if self._cancelled:
                    # User cancelled
                    self.cleanup(context)
                    return {'CANCELLED'}
                elif self._error:
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
        self.__class__._cancelled = False
        self.__class__._current_stage = 0
        self.__class__._stage_items_done = 0
        self.__class__._stage_items_total = 0

        # Start background thread
        self.__class__._thread = threading.Thread(target=self._run_download_with_error_handling)
        self.__class__._thread.start()

        # Start modal timer (checks every 0.1 seconds)
        wm = context.window_manager
        self.__class__._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def _run_download_with_error_handling(self):
        """Wrapper to catch exceptions in download_data."""
        try:
            self.download_data()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.__class__._error = str(e)

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

        Multi-stage progress:
            self.set_stage(0)  # Move to stage 0
            for i, item in enumerate(items):
                if self.is_cancelled():
                    return
                self.update_stage_progress(i, len(items))
                # process item

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
        self.__class__._cancelled = True
        self.cleanup(context)
        self.report({'INFO'}, "Operation cancelled by user")
