"""
Async operations wrapper for Blender addon.

This module provides thread-safe async operations for API calls to prevent
UI freezing. Uses Python threading + Blender timers for safe background execution.

IMPORTANT: Blender's UI and data access MUST happen on the main thread.
This module handles thread synchronization automatically.
"""

import threading
import queue
import time
import traceback
from typing import Callable, Any, Optional, Tuple
from enum import Enum

import bpy


class AsyncTaskStatus(Enum):
    """Status of an async task."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class AsyncTask:
    """Represents an async task that runs in a background thread."""
    
    def __init__(self, func: Callable, *args, **kwargs):
        """Initialize async task.
        
        Args:
            func: The function to run in background thread
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
        """
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.status = AsyncTaskStatus.PENDING
        self.result = None
        self.error = None
        self.progress = 0.0
        self.message = ""
        self._thread = None
        self._cancelled = False
    
    def start(self):
        """Start the task in a background thread."""
        if self.status != AsyncTaskStatus.PENDING:
            return
        
        self.status = AsyncTaskStatus.RUNNING
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def _run(self):
        """Internal method to run the task (executes in background thread)."""
        try:
            if self._cancelled:
                self.status = AsyncTaskStatus.CANCELLED
                return
            
            # Execute the function
            self.result = self.func(*self.args, **self.kwargs)
            
            if self._cancelled:
                self.status = AsyncTaskStatus.CANCELLED
            else:
                self.status = AsyncTaskStatus.SUCCESS
                
        except Exception as e:
            self.status = AsyncTaskStatus.ERROR
            self.error = str(e)
            self.traceback = traceback.format_exc()
            print(f"AsyncTask error: {self.error}")
            print(self.traceback)
    
    def cancel(self):
        """Cancel the task (may not stop immediately)."""
        self._cancelled = True
        self.status = AsyncTaskStatus.CANCELLED
    
    def is_done(self) -> bool:
        """Check if task is complete (success or error)."""
        return self.status in (AsyncTaskStatus.SUCCESS, AsyncTaskStatus.ERROR, AsyncTaskStatus.CANCELLED)
    
    def is_running(self) -> bool:
        """Check if task is currently running."""
        return self.status == AsyncTaskStatus.RUNNING
    
    def update_progress(self, progress: float, message: str = ""):
        """Update task progress (thread-safe).
        
        Args:
            progress: Progress value between 0.0 and 1.0
            message: Optional progress message
        """
        self.progress = max(0.0, min(1.0, progress))
        self.message = message


class AsyncOperator(bpy.types.Operator):
    """Base class for operators that run async tasks.
    
    Subclasses should implement:
    - async_execute(): Returns the result of the background operation
    - on_complete(result): Called on main thread when task succeeds
    - on_error(error): Called on main thread when task fails
    """
    
    # Timer interval for checking task status (seconds)
    _timer_interval = 0.1
    
    def __init__(self):
        super().__init__()
        self._task: Optional[AsyncTask] = None
        self._timer = None
    
    def start_async_task(self, context) -> AsyncTask:
        """Create and start the async task.
        
        Subclasses should override async_execute() instead of this method.
        """
        # Create task that calls async_execute
        task = AsyncTask(self.async_execute, context)
        task.start()
        return task
    
    def async_execute(self, context) -> Any:
        """Override this method with the actual async work.
        
        This runs in a BACKGROUND THREAD - do NOT access Blender data here!
        Only call API functions and process data.
        
        Returns:
            The result to pass to on_complete()
        """
        raise NotImplementedError("Subclasses must implement async_execute()")
    
    def on_complete(self, context, result: Any):
        """Called on main thread when task completes successfully.
        
        Args:
            context: Blender context (safe to access)
            result: The result from async_execute()
        """
        pass
    
    def on_error(self, context, error: str):
        """Called on main thread when task fails.
        
        Args:
            context: Blender context (safe to access)
            error: Error message
        """
        self.report({'ERROR'}, f"Operation failed: {error}")
    
    def on_progress(self, context, progress: float, message: str):
        """Called periodically on main thread to update progress.
        
        Args:
            context: Blender context (safe to access)
            progress: Progress value between 0.0 and 1.0
            message: Progress message
        """
        pass
    
    def modal(self, context, event):
        """Modal execution - checks task status periodically."""
        if event.type == 'ESC':
            # User cancelled
            if self._task:
                self._task.cancel()
            return self.cleanup(context, cancelled=True)
        
        if event.type == 'TIMER':
            if not self._task:
                return self.cleanup(context)
            
            # Update progress
            if self._task.progress > 0:
                self.on_progress(context, self._task.progress, self._task.message)
            
            # Check if task is done
            if self._task.is_done():
                if self._task.status == AsyncTaskStatus.SUCCESS:
                    try:
                        self.on_complete(context, self._task.result)
                    except Exception as e:
                        self.report({'ERROR'}, f"Error processing result: {str(e)}")
                        print(f"on_complete error: {traceback.format_exc()}")
                    return self.cleanup(context, success=True)
                    
                elif self._task.status == AsyncTaskStatus.ERROR:
                    self.on_error(context, self._task.error)
                    return self.cleanup(context)
                    
                elif self._task.status == AsyncTaskStatus.CANCELLED:
                    self.report({'WARNING'}, "Operation cancelled")
                    return self.cleanup(context, cancelled=True)
        
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        """Start the async operation."""
        # Start the async task
        self._task = self.start_async_task(context)
        
        # Register modal handler and timer
        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(
            self._timer_interval,
            window=context.window
        )
        
        return {'RUNNING_MODAL'}
    
    def cleanup(self, context, success=False, cancelled=False):
        """Clean up resources."""
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        
        self._task = None
        
        if cancelled:
            return {'CANCELLED'}
        return {'FINISHED'}


class AsyncTaskManager:
    """Manages multiple async tasks for complex operations."""
    
    def __init__(self):
        self.tasks = []
        self._lock = threading.Lock()
    
    def add_task(self, func: Callable, *args, **kwargs) -> AsyncTask:
        """Add a new task.
        
        Args:
            func: Function to run in background
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            The created AsyncTask
        """
        task = AsyncTask(func, *args, **kwargs)
        with self._lock:
            self.tasks.append(task)
        return task
    
    def start_all(self):
        """Start all pending tasks."""
        with self._lock:
            for task in self.tasks:
                if task.status == AsyncTaskStatus.PENDING:
                    task.start()
    
    def wait_all(self, timeout: Optional[float] = None) -> bool:
        """Wait for all tasks to complete.
        
        Args:
            timeout: Maximum time to wait in seconds (None = infinite)
            
        Returns:
            True if all tasks completed, False if timeout
        """
        start_time = time.time()
        
        while True:
            with self._lock:
                all_done = all(task.is_done() for task in self.tasks)
            
            if all_done:
                return True
            
            if timeout and (time.time() - start_time) > timeout:
                return False
            
            time.sleep(0.05)
    
    def get_results(self) -> list:
        """Get results from all completed tasks.
        
        Returns:
            List of (task, result_or_error) tuples
        """
        results = []
        with self._lock:
            for task in self.tasks:
                if task.status == AsyncTaskStatus.SUCCESS:
                    results.append((task, task.result))
                elif task.status == AsyncTaskStatus.ERROR:
                    results.append((task, task.error))
        return results
    
    def cancel_all(self):
        """Cancel all running tasks."""
        with self._lock:
            for task in self.tasks:
                if task.is_running():
                    task.cancel()
    
    def clear(self):
        """Clear all tasks."""
        with self._lock:
            self.tasks.clear()


# Global task manager instance
_task_manager = AsyncTaskManager()


def get_task_manager() -> AsyncTaskManager:
    """Get the global task manager instance."""
    return _task_manager


def run_async(func: Callable, *args, **kwargs) -> AsyncTask:
    """Simple helper to run a function asynchronously.
    
    Args:
        func: Function to run in background
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func
        
    Returns:
        AsyncTask instance
        
    Example:
        def fetch_data():
            return requests.get("https://api.example.com/data").json()
        
        task = run_async(fetch_data)
        # Do other work...
        while not task.is_done():
            time.sleep(0.1)
        if task.status == AsyncTaskStatus.SUCCESS:
            print(task.result)
    """
    task = AsyncTask(func, *args, **kwargs)
    task.start()
    return task