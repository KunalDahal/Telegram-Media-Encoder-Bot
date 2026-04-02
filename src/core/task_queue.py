import asyncio
import uuid
from datetime import datetime

_ACTIVE_STATUSES = frozenset({
    "starting", "queued", "downloading", "encoding", "uploading"
})

class TaskQueue:
    def __init__(self):
        self.queue:        list[str]       = []
        self.tasks:        dict[str, dict] = {}
        self.lock          = asyncio.Lock()
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

        if status in ("downloading", "encoding", "uploading") and not task.get("started_at"):
            task["started_at"] = datetime.utcnow().isoformat()

        self.processing = any(
            t.get("status") in _ACTIVE_STATUSES - {"queued"}
            for t in self.tasks.values()
        )

    # ── Queue navigation ──────────────────────────────────────────────────────

    def get_next_task(self) -> dict | None:
        for task_id in self.queue:
            task = self.tasks.get(task_id)
            if task and task.get("status") == "queued":
                self.current_task = task_id
                return task
        return None

    def get_queue_position(self, task_id: str) -> int:
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
        self.processing = any(
            t.get("status") in _ACTIVE_STATUSES - {"queued"}
            for t in self.tasks.values()
        )

    # ── Legacy helpers (kept for external compatibility) ──────────────────────

    def is_processing(self) -> bool:
        return self.processing

    def set_processing(self, status: bool):
        self.processing = status

    def get_current_task(self) -> dict | None:
        if self.current_task:
            return self.tasks.get(self.current_task)
        return None