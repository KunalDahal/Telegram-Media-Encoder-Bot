import asyncio
import os
import shutil
from datetime import datetime


# ── Stage progress helpers ────────────────────────────────────────────────────

def _encode_progress_base(job_index: int, total_jobs: int) -> int:
    per_job = 80 // total_jobs
    return 20 + (job_index - 1) * per_job


def _upload_progress_base(job_index: int, total_jobs: int) -> int:
    per_job = 80 // total_jobs
    return 20 + (job_index - 1) * per_job + (per_job // 2)


# ── Worker ────────────────────────────────────────────────────────────────────

class Worker:

    def __init__(self, task_queue, user_settings_getter, ffmpeg, client, config):
        self.task_queue            = task_queue
        self.user_settings_getter  = user_settings_getter
        self.ffmpeg                = ffmpeg
        self.client                = client
        self.config                = config
        self.temp_base             = config.paths.tmp
        self.thumbnails_dir        = config.paths.thumbnails
        self.running               = False

        # ── One semaphore per pipeline stage ──────────────────────────────────
        self._download_sem = asyncio.Semaphore(1)
        self._encode_sem   = asyncio.Semaphore(1)
        self._upload_sem   = asyncio.Semaphore(1)

        # task_id → asyncio.Task  (for cancellation and lifecycle tracking)
        self._active_tasks: dict[str, asyncio.Task] = {}

        os.makedirs(self.temp_base,      exist_ok=True)
        os.makedirs(self.thumbnails_dir, exist_ok=True)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self.running = True
        while self.running:
            try:
                task = self.task_queue.get_next_task()
                if task:
                    task_id = task["task_id"]
                    self.task_queue.update_status(task_id, "starting", 0)

                    coro = self.process_task(task)
                    t    = asyncio.create_task(coro, name=f"task-{task_id}")
                    self._active_tasks[task_id] = t

                    t.add_done_callback(
                        lambda _fut, tid=task_id: self._active_tasks.pop(tid, None)
                    )

                await asyncio.sleep(1)

            except Exception as e:
                print(f"[Worker] Loop error: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        self.running = False
        tasks = list(self._active_tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── Cancellation ─────────────────────────────────────────────────────────

    async def cancel_task(self, task_id: str):
        try:
            t = self._active_tasks.get(task_id)
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            else:
                task = self.task_queue.get_task(task_id)
                if task:
                    try:
                        await self.client.send_message(
                            task["user_id"],
                            f"Task `{task_id[:8]}` has been cancelled.",
                        )
                    except Exception:
                        pass
                self.task_queue.remove_task(task_id)
                task_folder = os.path.join(self.temp_base, task_id)
                if os.path.exists(task_folder):
                    shutil.rmtree(task_folder, ignore_errors=True)

        except Exception as e:
            print(f"[Worker] cancel_task error for {task_id}: {e}")

    # ── Stage helper ──────────────────────────────────────────────────────────

    def _set_stage(self, task: dict, stage: str, progress: int = None):
        task["current_stage"] = stage
        self.task_queue.update_status(
            task["task_id"],
            stage,
            progress if progress is not None else task.get("progress", 0),
        )

    def _clear_progress_details(self, task: dict):
        """Clear stale per-stage progress so status.py doesn't show old data."""
        task.pop("progress_details", None)
        task.pop("upload_progress",  None)

    # ── Main processor ────────────────────────────────────────────────────────

    async def process_task(self, task: dict):
        task_id     = task["task_id"]
        task_folder = os.path.join(self.temp_base, task_id)

        downloaded_path: str       = None
        encoded_paths:   list[str] = []

        try:
            task["started_at"] = datetime.utcnow().isoformat()

            # ═══════════════════════════════════════════════════════════════════
            # STAGE 1 — Download  (one at a time across all tasks)
            # ═══════════════════════════════════════════════════════════════════
            async with self._download_sem:
                self._clear_progress_details(task)
                self._set_stage(task, "downloading", 0)

                from src.services.downloader import Downloader
                downloader      = Downloader(self.temp_base, self.task_queue, task_id)
                downloaded_path = await downloader.download(
                    client=self.client, task_data=task
                )

                if not downloaded_path or not os.path.exists(downloaded_path):
                    raise Exception("Download failed: file not found after download")

                task["media_info"] = await self.ffmpeg.probe_media(downloaded_path)

            # ── Build the list of encode/upload jobs ──────────────────────────
            jobs = task.get("jobs") or [
                {
                    "resolution":      task.get("resolution", "1080p"),
                    "output_filename": task["output_filename"],
                    "processing_mode": (
                        "metadata_only"
                        if task.get("resolution") == "HDRip"
                        else "encode"
                    ),
                    "crf":            task.get("crf", 28),
                    "preset":         task.get("preset", "medium"),
                    "codec":          task.get("codec", "libx264"),
                    "audio_bitrate":  task.get("audio_bitrate", "128k"),
                    "metadata":       task.get("metadata", {}),
                    "thumbnail_path": task.get("thumbnail_path", ""),
                    "send_type":      task.get("send_type", "media"),
                }
            ]

            total_jobs         = len(jobs)
            task["total_jobs"] = total_jobs

            from src.services.encoder import Encoder
            from src.services.uploader import Uploader

            encoder = Encoder(self.ffmpeg)

            for job_index, job in enumerate(jobs, start=1):
                resolution      = job["resolution"]
                output_filename = job["output_filename"]
                processing_mode = job.get("processing_mode", "encode")

                task["current_job"]      = job_index
                task["resolution"]       = resolution
                task["output_filename"]  = output_filename
                task["current_job_mode"] = processing_mode

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
                    "watermark":       task.get("watermark"),
                }

                # ═══════════════════════════════════════════════════════════════
                # STAGE 2 — Encode  (one FFmpeg process at a time)
                # ═══════════════════════════════════════════════════════════════
                async with self._encode_sem:
                    self._clear_progress_details(task)
                    self._set_stage(
                        task, "encoding",
                        _encode_progress_base(job_index, total_jobs),
                    )
                    encoded_path = await encoder.encode(
                        task_data=task,
                        input_path=downloaded_path,
                        settings=job_settings,
                    )

                    if not encoded_path or not os.path.exists(encoded_path):
                        raise Exception(
                            f"Encoding failed for {resolution}: output file not found"
                        )
                    encoded_paths.append(encoded_path)

                # ═══════════════════════════════════════════════════════════════
                # STAGE 3 — Upload  (one upload at a time)
                # ═══════════════════════════════════════════════════════════════
                async with self._upload_sem:
                    self._clear_progress_details(task)
                    self._set_stage(
                        task, "uploading",
                        _upload_progress_base(job_index, total_jobs),
                    )
                    task["upload_file_path"] = encoded_path
                    task["thumbnail_path"]   = job.get("thumbnail_path", "")
                    task["send_type"]        = job.get("send_type", "media")

                    uploader = Uploader(
                        self.client, task, self.task_queue,
                        tmp_dir=self.temp_base,
                    )
                    await uploader.upload()

                # Clean up this job's encoded file right after upload.
                task.pop("upload_file_path", None)
                if os.path.exists(encoded_path):
                    try:
                        os.remove(encoded_path)
                    except Exception:
                        pass
                encoded_paths = [p for p in encoded_paths if p != encoded_path]

            # ── All jobs done ─────────────────────────────────────────────────
            self.task_queue.remove_task(task_id)
            await self.notify_user(
                task["user_id"],
                f"✅ Task `{task_id[:8]}` completed.",
            )

        except asyncio.CancelledError:
            await self.notify_user(
                task["user_id"],
                f"Task `{task_id[:8]}` was cancelled.",
            )
            self.task_queue.remove_task(task_id)

        except Exception as e:
            error_msg = str(e)
            print(f"[Worker] Task {task_id} failed: {error_msg}")
            await self.notify_user(
                task["user_id"],
                f"❌ Task `{task_id[:8]}` failed.\nError: {error_msg[:200]}",
            )
            self.task_queue.remove_task(task_id)

        finally:
            for file_path in encoded_paths:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

            if downloaded_path and os.path.exists(downloaded_path):
                try:
                    os.remove(downloaded_path)
                except Exception:
                    pass

            if os.path.exists(task_folder):
                shutil.rmtree(task_folder, ignore_errors=True)

    # ── Utilities ─────────────────────────────────────────────────────────────

    async def notify_user(self, user_id: int, message: str):
        try:
            await self.client.send_message(user_id, message)
        except Exception as e:
            print(f"[Worker] Failed to notify user {user_id}: {e}")