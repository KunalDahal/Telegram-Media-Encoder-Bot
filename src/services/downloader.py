# services/downloader.py
import os
import asyncio
import time

class Downloader:
    def __init__(self, temp_base: str, task_queue=None, task_id=None):
        self.temp_base = temp_base
        self.task_queue = task_queue
        self.task_id = task_id
        self._last_time = None
        self._last_bytes = 0
        os.makedirs(self.temp_base, exist_ok=True)
        self.download_progress = {
            "total_size": 0,
            "downloaded": 0,
            "percentage": 0,
            "speed": 0,
            "eta": 0,
            "elapsed": 0,
            "status": "idle"
        }
        self._start_time = None

    async def download(self, client, task_data: dict) -> str:
        task_id = task_data["task_id"]
        file_id = task_data["file_id"]
        original_file_name = task_data["original_file_name"]
        self.task_id = task_id
        
        task_folder = os.path.join(self.temp_base, task_id)
        os.makedirs(task_folder, exist_ok=True)
        
        file_path = os.path.join(task_folder, original_file_name)
        
        try:
            self._reset_progress()
            self.download_progress["status"] = "downloading"
            self._start_time = time.time()
            
            print(f"Downloading to: {file_path}")
            
            await client.download_media(
                file_id, 
                file_name=file_path,
                progress=self._progress_callback
            )
            
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise Exception("Downloaded file not found or empty")
            
            print(f"Download completed: {file_path} ({os.path.getsize(file_path)} bytes)")
            
            self.download_progress["status"] = "completed"
            return file_path
                
        except Exception as e:
            self.download_progress["status"] = "failed"
            raise Exception(f"Download failed: {str(e)}")

    def _reset_progress(self):
        self.download_progress = {
            "total_size": 0,
            "downloaded": 0,
            "percentage": 0,
            "speed": 0,
            "eta": 0,
            "elapsed": 0,
            "status": "idle"
        }
        self._last_time = None
        self._last_bytes = 0
        self._start_time = None

    async def _progress_callback(self, current, total):
        now = time.time()
        
        if self.download_progress["total_size"] == 0:
            self.download_progress["total_size"] = total

        if self._last_time is None:
            self._last_time = now
            self._last_bytes = current
            return

        elapsed = now - self._last_time
        speed = (current - self._last_bytes) / elapsed if elapsed > 0 else 0

        self._last_time = now
        self._last_bytes = current

        percentage = (current / total) * 100 if total > 0 else 0
        remaining = total - current
        eta = remaining / speed if speed > 0 else 0
        total_elapsed = now - self._start_time if self._start_time else 0

        self.download_progress.update({
            "downloaded": current,
            "percentage": round(percentage, 2),
            "speed": round(speed, 2),
            "eta": int(eta),
            "elapsed": int(total_elapsed),
            "status": "downloading"
        })
        
        if self.task_queue and self.task_id:
            if hasattr(self.task_queue, 'update_status'):
                self.task_queue.update_status(
                    self.task_id, 
                    "downloading", 
                    round(percentage, 2)
                )

    def get_progress(self) -> dict:
        return self.download_progress.copy()