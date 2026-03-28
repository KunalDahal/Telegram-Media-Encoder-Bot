import os
import shutil
import time

class Uploader:
    def __init__(self, client, task_data: dict, task_queue=None):
        self.client = client
        self.task_data = task_data
        self.task_queue = task_queue
        self._last_time = None
        self._last_bytes = 0
        self._start_time = None
        self.upload_progress = {
            "total_size": 0,
            "uploaded": 0,
            "percentage": 0,
            "speed": 0,
            "eta": 0,
            "elapsed": 0,
            "status": "idle"
        }

    async def upload(self):
        task_id = self.task_data["task_id"]
        user_id = self.task_data["user_id"]
        output_file_name = self.task_data["output_filename"]
        send_type = self.task_data.get("send_type", "media")
        thumbnail_path = self.task_data.get("thumbnail_path", "")

        task_folder = os.path.join("./src/bin/tmp", task_id)
        explicit_file_path = self.task_data.get("upload_file_path")

        if explicit_file_path and os.path.exists(explicit_file_path):
            final_file_path = explicit_file_path
        else:
            encoded_files = [f for f in os.listdir(task_folder) if f.endswith((".mp4", ".mkv", ".avi", ".mov", ".webm"))]
            if not encoded_files:
                raise Exception("No encoded file found in task folder")

            current_file = os.path.join(task_folder, encoded_files[0])
            final_file_path = os.path.join(task_folder, output_file_name)
            if current_file != final_file_path:
                shutil.move(current_file, final_file_path)

        if not os.path.exists(final_file_path):
            raise Exception("File not found after renaming")

        file_size = os.path.getsize(final_file_path)

        self.upload_progress["total_size"] = file_size
        self.upload_progress["status"] = "uploading"
        self._start_time = time.time()
        self._last_time = None
        self._last_bytes = 0

        try:
            caption = f"**{output_file_name}**\n"

            thumb = None
            if thumbnail_path and os.path.exists(thumbnail_path):
                thumb = thumbnail_path

            if send_type.lower() in ["doc", "document"]:
                result = await self.client.send_document(
                    chat_id=user_id,
                    document=final_file_path,
                    thumb=thumb,
                    caption=caption,
                    force_document=True,
                    file_name=output_file_name,
                    progress=self._progress_callback
                )
            else:
                result = await self.client.send_video(
                    chat_id=user_id,
                    video=final_file_path,
                    thumb=thumb,
                    caption=caption,
                    supports_streaming=True,
                    progress=self._progress_callback
                )

            self.upload_progress["status"] = "completed"
            return result

        except Exception as e:
            self.upload_progress["status"] = "failed"
            raise Exception(f"Upload failed: {str(e)}")

    async def _progress_callback(self, current, total):
        now = time.time()

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

        self.upload_progress.update({
            "uploaded": current,
            "percentage": round(percentage, 2),
            "speed": round(speed, 2),
            "eta": int(eta),
            "elapsed": int(total_elapsed),
            "status": "uploading"
        })

        if self.task_queue and hasattr(self.task_queue, "update_status"):
            self.task_queue.update_status(
                self.task_data["task_id"],
                "uploading",
                round(percentage, 2)
            )

    def get_progress(self) -> dict:
        return self.upload_progress.copy()