import os
import asyncio
import time

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Downloader:
    def __init__(self, temp_base: str = None, task_queue=None, task_id=None):
        self.temp_base = temp_base if temp_base else os.path.join(_SRC_DIR, "bin", "tmp")
        self.task_queue = task_queue
        self.task_id = task_id
        self._last_time = None
        self._last_bytes = 0
        self._start_time = None

        os.makedirs(self.temp_base, exist_ok=True)

        self.download_progress = {
            "total_size": 0,
            "downloaded": 0,
            "percentage": 0,
            "speed": 0,
            "eta": 0,
            "elapsed": 0,
            "status": "idle",
        }

    async def download(self, client, task_data: dict) -> str:
        task_id = task_data["task_id"]
        file_id = task_data["file_id"]
        original_file_name = task_data.get("original_file_name") or f"video_{task_id}.mkv"
        self.task_id = task_id

        task_folder = os.path.join(self.temp_base, task_id)
        os.makedirs(task_folder, exist_ok=True)

        desired_path = os.path.join(task_folder, original_file_name)

        self._reset_progress()
        self.download_progress["status"] = "downloading"
        self._start_time = time.time()

        print(f"[Downloader] Saving to: {desired_path}")

        try:
            actual_path = await client.download_media(
                file_id,
                file_name=desired_path,
                progress=self._progress_callback,
            )

            if not actual_path:
                raise Exception("download_media returned None — download may have been cancelled")

            actual_path = os.path.abspath(actual_path)

            if not os.path.exists(actual_path):
                raise Exception(f"File not found after download: {actual_path}")

            if os.path.getsize(actual_path) == 0:
                raise Exception(f"Downloaded file is empty: {actual_path}")

            desired_abs = os.path.abspath(desired_path)
            if actual_path != desired_abs:
                print(f"[Downloader] Moving {actual_path} → {desired_abs}")
                os.replace(actual_path, desired_abs)
                actual_path = desired_abs

            print(f"[Downloader] Done: {actual_path} ({os.path.getsize(actual_path):,} bytes)")
            self.download_progress["status"] = "completed"
            return actual_path

        except asyncio.CancelledError:
            self.download_progress["status"] = "cancelled"
            raise
        except Exception as e:
            self.download_progress["status"] = "failed"
            raise Exception(f"Download failed: {e}")

    # ── Progress callback ─────────────────────────────────────────────────────

    async def _progress_callback(self, current: int, total: int):
        now = time.time()

        if self.download_progress["total_size"] == 0 and total:
            self.download_progress["total_size"] = total

        if self._last_time is None:
            self._last_time = now
            self._last_bytes = current
            return

        elapsed_interval = now - self._last_time
        speed = (current - self._last_bytes) / elapsed_interval if elapsed_interval > 0 else 0

        self._last_time = now
        self._last_bytes = current

        percentage = (current / total * 100) if total > 0 else 0
        eta = ((total - current) / speed) if speed > 0 else 0
        total_elapsed = (now - self._start_time) if self._start_time else 0

        self.download_progress.update(
            {
                "downloaded": current,
                "percentage": round(percentage, 2),
                "speed": round(speed, 2),
                "eta": int(eta),
                "elapsed": int(total_elapsed),
                "status": "downloading",
            }
        )

        if self.task_queue and self.task_id:
            self.task_queue.update_status(
                self.task_id, "downloading", round(percentage, 2)
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _reset_progress(self):
        self.download_progress = {
            "total_size": 0,
            "downloaded": 0,
            "percentage": 0,
            "speed": 0,
            "eta": 0,
            "elapsed": 0,
            "status": "idle",
        }
        self._last_time = None
        self._last_bytes = 0
        self._start_time = None

    def get_progress(self) -> dict:
        return self.download_progress.copy()