import asyncio
import copy
import os
import shutil
from datetime import datetime


class Worker:
    def __init__(self, task_queue, user_settings_getter, ffmpeg, client):
        self.task_queue = task_queue
        self.user_settings_getter = user_settings_getter
        self.ffmpeg = ffmpeg
        self.client = client
        self.temp_base = "./src/bin/tmp"
        self.thumbnails_dir = "./src/bin/thumbnails"
        self.running = False
        self.current_task = None
        self.current_task_id = None
        self.processing_task = None

        os.makedirs(self.temp_base, exist_ok=True)
        os.makedirs(self.thumbnails_dir, exist_ok=True)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self.running = True
        while self.running:
            try:
                if not self.current_task_id and not self.task_queue.is_processing():
                    next_task = self.task_queue.get_next_task()
                    if next_task:
                        self.current_task_id = next_task["task_id"]
                        self.current_task = next_task
                        self.task_queue.set_processing(True)
                        self.task_queue.update_status(self.current_task_id, "queued", 0)

                        self.processing_task = asyncio.create_task(
                            self.process_task(self.current_task)
                        )

                await asyncio.sleep(1)

            except Exception as e:
                print(f"Worker loop error: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        self.running = False
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except Exception:
                pass

    async def cancel_task(self, task_id: str):
        try:
            if self.current_task_id == task_id and self.processing_task:
                self.processing_task.cancel()
                try:
                    await self.processing_task
                except asyncio.CancelledError:
                    print(f"Task {task_id} cancelled")
                except Exception as e:
                    print(f"Error during cancellation: {e}")

                self.current_task_id = None
                self.current_task = None
                self.task_queue.set_processing(False)
                self.task_queue.update_status(task_id, "cancelled", 0)

            if task_id in self.task_queue.queue:
                task = self.task_queue.get_task(task_id)
                if task:
                    try:
                        await self.client.send_message(
                            task["user_id"],
                            f"Task `{task_id[:8]}` has been cancelled.",
                        )
                    except Exception:
                        pass
                self.task_queue.queue.remove(task_id)

            if task_id in self.task_queue.tasks:
                del self.task_queue.tasks[task_id]

            task_folder = os.path.join(self.temp_base, task_id)
            if os.path.exists(task_folder):
                try:
                    shutil.rmtree(task_folder)
                except Exception as e:
                    print(f"Cleanup failed for {task_id}: {e}")

        except Exception as e:
            print(f"cancel_task error: {e}")

    # ── Stage tracker helper ──────────────────────────────────────────────────

    def _set_stage(self, task: dict, stage: str, progress: int = None):
        """
        Update both the in-memory task dict and the queue's status tracker.
        ``stage`` should be one of:
            queued | downloading | encoding | uploading
        """
        task["current_stage"] = stage
        self.task_queue.update_status(
            task["task_id"], stage, progress if progress is not None else task.get("progress", 0)
        )

    # ── Main processor ────────────────────────────────────────────────────────

    async def process_task(self, task: dict):
        """
        Sequential pipeline for one task (one source file, N resolution jobs):

            Download source
            For each job (HDRip → 1080p → 720p → 480p):
                Encode  (or copy+metadata for HDRip)
                Upload
            Cleanup
        """
        task_id = task["task_id"]
        task_folder = os.path.join(self.temp_base, task_id)

        downloaded_path = None
        encoded_paths: list[str] = []

        try:
            task["started_at"] = datetime.utcnow().isoformat()

            # ── 1. Download ───────────────────────────────────────────────────
            self._set_stage(task, "downloading", 5)

            from src.services.downloader import Downloader

            downloader = Downloader(self.temp_base, self.task_queue, task_id)
            downloaded_path = await downloader.download(client=self.client, task_data=task)

            if not downloaded_path or not os.path.exists(downloaded_path):
                raise Exception("Download failed: file not found after download")

            # Probe once; share across all jobs
            task["media_info"] = await self.ffmpeg.probe_media(downloaded_path)

            # ── 2. Build jobs (fallback for older tasks without "jobs" key) ───
            jobs = task.get("jobs") or [
                {
                    "resolution": task.get("resolution", "1080p"),
                    "output_filename": task["output_filename"],
                    "processing_mode": (
                        "metadata_only"
                        if task.get("resolution") == "HDRip"
                        else "encode"
                    ),
                    "crf": task.get("crf", 28),
                    "preset": task.get("preset", "medium"),
                    "codec": task.get("codec", "libx264"),
                    "audio_bitrate": task.get("audio_bitrate", "128k"),
                    "metadata": task.get("metadata", {}),
                    "thumbnail_path": task.get("thumbnail_path", ""),
                    "send_type": task.get("send_type", "media"),
                }
            ]

            total_jobs = len(jobs)
            task["total_jobs"] = total_jobs

            from src.services.encoder import Encoder
            from src.services.uploader import Uploader

            encoder = Encoder(self.ffmpeg)

            # ── 3. Sequential: encode → upload per resolution ─────────────────
            for job_index, job in enumerate(jobs, start=1):
                resolution = job["resolution"]
                output_filename = job["output_filename"]
                processing_mode = job.get("processing_mode", "encode")

                # Update task fields so /status can display the active resolution
                task["current_job"] = job_index
                task["resolution"] = resolution
                task["output_filename"] = output_filename
                task["current_job_mode"] = processing_mode

                # ── 3a. Encode / copy ─────────────────────────────────────────
                self._set_stage(task, "encoding", _encode_progress_base(job_index, total_jobs))

                job_settings = {
                    "resolution":      resolution,
                    "processing_mode": processing_mode,
                    "crf":             job.get("crf"),
                    "preset":          job.get("preset"),
                    "codec":           job.get("codec"),
                    "audio_bitrate":   job.get("audio_bitrate"),
                    "metadata":        job.get("metadata", {}),
                    "thumbnail_path":  job.get("thumbnail_path", ""),
                    "send_type":       job.get("send_type", "media"),
                    "media_info":      task.get("media_info", {}),
                    # Watermark is skipped automatically by FFmpeg for HDRip/metadata_only
                    "watermark":       task.get("watermark"),
                }

                encoded_path = await encoder.encode(
                    task_data=task,
                    input_path=downloaded_path,
                    settings=job_settings,
                )
                encoded_paths.append(encoded_path)

                if not encoded_path or not os.path.exists(encoded_path):
                    raise Exception(
                        f"Encoding failed for {resolution}: output file not found"
                    )

                # ── 3b. Upload ────────────────────────────────────────────────
                self._set_stage(task, "uploading", _upload_progress_base(job_index, total_jobs))

                task["upload_file_path"] = encoded_path
                task["thumbnail_path"] = job.get("thumbnail_path", "")
                task["send_type"] = job.get("send_type", "media")

                uploader = Uploader(self.client, task, self.task_queue)
                await uploader.upload()

                # Clean up encoded file immediately after upload
                task.pop("upload_file_path", None)
                if os.path.exists(encoded_path):
                    try:
                        os.remove(encoded_path)
                    except Exception:
                        pass
                encoded_paths = [p for p in encoded_paths if p != encoded_path]

            # ── 4. Done ───────────────────────────────────────────────────────
            self.task_queue.remove_task(task_id)

            res_list = " · ".join(job["resolution"] for job in jobs)
            await self.notify_user(
                task["user_id"],
                f"✅ Task `{task_id[:8]}` completed.\n"
                f"Resolutions: {res_list}  ({total_jobs} file{'s' if total_jobs > 1 else ''})",
            )

        except asyncio.CancelledError:
            await self.notify_user(
                task["user_id"], f"🚫 Task `{task_id[:8]}` was cancelled."
            )
            self.task_queue.remove_task(task_id)

        except Exception as e:
            error_msg = str(e)
            print(f"Task {task_id} failed: {error_msg}")
            await self.notify_user(
                task["user_id"],
                f"❌ Task `{task_id[:8]}` failed.\nError: {error_msg[:200]}",
            )
            self.task_queue.remove_task(task_id)

        finally:
            # Remove any encoded files that weren't cleaned up mid-loop
            for file_path in encoded_paths:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

            # Remove downloaded source
            if downloaded_path and os.path.exists(downloaded_path):
                try:
                    os.remove(downloaded_path)
                except Exception:
                    pass

            # Remove entire task temp folder
            if os.path.exists(task_folder):
                try:
                    shutil.rmtree(task_folder)
                except Exception as e:
                    print(f"Cleanup error for {task_folder}: {e}")

            self.current_task_id = None
            self.current_task = None
            self.task_queue.set_processing(False)

    # ── Utilities ─────────────────────────────────────────────────────────────

    async def notify_user(self, user_id: int, message: str):
        try:
            await self.client.send_message(user_id, message)
        except Exception as e:
            print(f"Failed to notify user {user_id}: {e}")


# ── Progress helpers ──────────────────────────────────────────────────────────

def _encode_progress_base(job_index: int, total_jobs: int) -> int:
    """
    Map job index to an approximate overall progress percentage.
    Download occupies 0-20 %, encode+upload share 20-100 % evenly across jobs.
    """
    per_job = 80 // total_jobs
    return 20 + (job_index - 1) * per_job


def _upload_progress_base(job_index: int, total_jobs: int) -> int:
    per_job = 80 // total_jobs
    return 20 + (job_index - 1) * per_job + (per_job // 2)