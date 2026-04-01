import asyncio
import uuid
from datetime import datetime

# Statuses that mean "this task is alive and taking up a queue slot"
_ACTIVE_STATUSES = frozenset({
    "starting", "queued", "downloading", "encoding", "uploading"
})


class TaskQueue:
    """
    Thread-safe (asyncio) task queue for the pipeline worker.

    Lifecycle of a task status:
        queued → starting → downloading → encoding → uploading → (removed)

    "starting" is set by the Worker the instant it spawns a coroutine for
    the task.  This ensures get_next_task() won't return the same task twice
    even before the coroutine reaches the "downloading" stage.
    """

    def __init__(self):
        # Ordered list of task_ids (insertion order = queue order)
        self.queue:        list[str]       = []
        # Full task data keyed by task_id
        self.tasks:        dict[str, dict] = {}
        self.lock          = asyncio.Lock()

        # ── Legacy single-task fields (kept for external callers) ─────────────
        # With the pipeline worker these are no longer authoritative, but
        # external status handlers may still read them.
        self.processing    = False
        self.current_task  = None

    # ── Creation / retrieval ──────────────────────────────────────────────────

    def create_task(self, task_data: dict) -> str:
        task_id = str(uuid.uuid4())[:8]
        now     = datetime.utcnow().isoformat()
        task    = {
            "task_id":    task_id,
            "created_at": now,
            "started_at": None,
            "status":     "queued",
            "progress":   0,
        }
        task.update(task_data)

        self.tasks[task_id] = task
        self.queue.append(task_id)
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        return self.tasks.get(task_id)

    # ── Status updates ────────────────────────────────────────────────────────

    def update_status(self, task_id: str, status: str, progress: int = None):
        task = self.tasks.get(task_id)
        if task is None:
            return

        task["status"] = status

        if progress is not None:
            task["progress"] = progress

        # Record when the task first left the waiting state.
        if status in ("downloading", "encoding", "uploading") and not task.get("started_at"):
            task["started_at"] = datetime.utcnow().isoformat()

        # Keep legacy flag in sync: "processing" if any task is active.
        self.processing = any(
            t.get("status") in _ACTIVE_STATUSES - {"queued"}
            for t in self.tasks.values()
        )

    # ── Queue navigation ──────────────────────────────────────────────────────

    def get_next_task(self) -> dict | None:
        """
        Return the first task whose status is exactly "queued".
        Tasks in any other active status have already been picked up.
        """
        for task_id in self.queue:
            task = self.tasks.get(task_id)
            if task and task.get("status") == "queued":
                self.current_task = task_id   # legacy compat
                return task
        return None

    def get_queue_position(self, task_id: str) -> int:
        """
        1-based position among all active tasks (queued + in-pipeline).
        Returns 0 if the task is not found or already finished.
        """
        position = 1
        for tid in self.queue:
            task = self.tasks.get(tid)
            if task and task.get("status") in _ACTIVE_STATUSES:
                if tid == task_id:
                    return position
                position += 1
        return 0

    def remove_task(self, task_id: str):
        self.tasks.pop(task_id, None)
        try:
            self.queue.remove(task_id)
        except ValueError:
            pass
        if self.current_task == task_id:
            self.current_task = None
        # Refresh legacy processing flag.
        self.processing = any(
            t.get("status") in _ACTIVE_STATUSES - {"queued"}
            for t in self.tasks.values()
        )

    # ── Legacy helpers (kept for external compatibility) ──────────────────────

    def is_processing(self) -> bool:
        """True if at least one task is currently running (not just queued)."""
        return self.processing

    def set_processing(self, status: bool):
        """No-op in pipeline mode; kept so old call-sites don't break."""
        self.processing = status

    def get_current_task(self) -> dict | None:
        """Returns the most-recently-started task, or None."""
        if self.current_task:
            return self.tasks.get(self.current_task)
        return None