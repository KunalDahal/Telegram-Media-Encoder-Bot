import asyncio
import os
import shutil
import time
from datetime import datetime

from pyrogram.errors import FloodWait

from src.services.downloader import Downloader
from src.services.encoder import Encoder
from src.services.uploader import Uploader


class Worker:
    JOB_COOLDOWN: int = 0
    TASK_COOLDOWN: int = 0
    PREENCODE_COOLDOWN: int = 5

    def __init__(self, task_queue, user_settings_getter, ffmpeg, client, config):
        self.task_queue = task_queue
        self.user_settings_getter = user_settings_getter
        self.ffmpeg = ffmpeg
        self.client = client
        self.config = config
        self.temp_base = config.paths.tmp
        self.thumbnails_dir = config.paths.thumbnails
        self.running = False
        self._current_task_id = None
        self._current_asyncio_task: asyncio.Task | None = None
        self._prefetch_task: asyncio.Task | None = None
        self._prefetch_task_id: str | None = None
        self._preencode_task: asyncio.Task | None = None
        self._preencode_task_id: str | None = None

        os.makedirs(self.temp_base, exist_ok=True)
        os.makedirs(self.thumbnails_dir, exist_ok=True)

    async def start(self):
        self.running = True
        await self._startup_cleanup()
        await self._worker_loop()

    async def stop(self):
        self.running = False
        if self._current_task_id:
            await self.cancel_task(self._current_task_id)

    async def _startup_cleanup(self):
        self.task_queue.purge_stale_tasks()
        if os.path.exists(self.temp_base):
            active_ids = set(self.task_queue.queue)
            for name in os.listdir(self.temp_base):
                folder = os.path.join(self.temp_base, name)
                if os.path.isdir(folder) and name not in active_ids:
                    shutil.rmtree(folder, ignore_errors=True)

    async def _worker_loop(self):
        while self.running:
            task = self._next_queued_task()
            if not task:
                await asyncio.sleep(1)
                continue

            self._current_task_id = task["task_id"]
            self.task_queue.current_task = task["task_id"]
            try:
                self._current_asyncio_task = asyncio.create_task(self._run_task(task))
                await self._current_asyncio_task
            except asyncio.CancelledError:
                await self._notify_user(task["user_id"], f"⚠️ Task `{task['task_id'][:8]}` was cancelled.")
                self.task_queue.remove_task(task["task_id"])
                self._cleanup_task_folder(task["task_id"])
            except Exception as e:
                print(f"[Worker] Task {task['task_id']} failed: {e}")
                await self._notify_user(
                    task["user_id"],
                    f"❌ Task `{task['task_id'][:8]}` failed.\nError: {str(e)[:200]}",
                )
                self.task_queue.remove_task(task["task_id"])
                self._cleanup_task_folder(task["task_id"])
            finally:
                self._current_asyncio_task = None
                self._current_task_id = None
                if self.task_queue.current_task == task["task_id"]:
                    self.task_queue.current_task = None

            if self.running and self._next_queued_task() and self.TASK_COOLDOWN > 0:
                print(f"[Worker] Cooling down for {self.TASK_COOLDOWN}s before next task.")
                await asyncio.sleep(self.TASK_COOLDOWN)

    def _next_queued_task(self):
        for task_id in self.task_queue.queue:
            task = self.task_queue.get_task(task_id)
            if task and task.get("status") in ("queued", "ready"):
                return task
        return None

    async def _run_task(self, task: dict):
        task_id = task["task_id"]
        task["_start_time"] = time.time()
        self.task_queue.update_status(task_id, "starting", 0)

        await self._snapshot_thumbnail(task)

        downloaded_path = await self._download(task)
        if not downloaded_path:
            raise Exception("Download produced no file")

        asyncio.create_task(self._maybe_prefetch_next(task_id))

        jobs = task.get("jobs") or [self._legacy_job(task)]
        task["total_jobs"] = len(jobs)

        encoded_jobs = self._get_preencoded_jobs(task)
        if encoded_jobs:
            print(f"[Worker] Using pre-encoded outputs for {task_id[:8]}")
            task["_allow_next_preencode"] = True
            for idx, (job, encoded_path) in enumerate(encoded_jobs, start=1):
                task["current_job"] = idx
                task["resolution"] = job["resolution"]
                task["output_filename"] = job["output_filename"]
                task["current_job_mode"] = job.get("processing_mode", "encode")

                await self._upload(task, encoded_path, job)
                await self._send_completion_to_group(task, job, encoded_path)

                if os.path.exists(encoded_path):
                    os.remove(encoded_path)

        elif self._can_encode_jobs_together(jobs):
            encoded_jobs = await self._encode_many(task, downloaded_path, jobs)
            task["_allow_next_preencode"] = True
            for idx, (job, encoded_path) in enumerate(encoded_jobs, start=1):
                task["current_job"] = idx
                task["resolution"] = job["resolution"]
                task["output_filename"] = job["output_filename"]
                task["current_job_mode"] = job.get("processing_mode", "encode")

                await self._upload(task, encoded_path, job)
                await self._send_completion_to_group(task, job, encoded_path)

                if os.path.exists(encoded_path):
                    os.remove(encoded_path)
        else:
            for idx, job in enumerate(jobs, start=1):
                task["current_job"] = idx
                task["resolution"] = job["resolution"]
                task["output_filename"] = job["output_filename"]
                task["current_job_mode"] = job.get("processing_mode", "encode")

                if idx > 1 and self.JOB_COOLDOWN > 0:
                    print(f"[Worker] Job cooldown {self.JOB_COOLDOWN}s before job {idx}/{len(jobs)}")
                    await asyncio.sleep(self.JOB_COOLDOWN)

                encoded_path = await self._encode(task, downloaded_path, job)
                task["_allow_next_preencode"] = idx == len(jobs)
                await self._upload(task, encoded_path, job)
                await self._send_completion_to_group(task, job, encoded_path)

                if os.path.exists(encoded_path):
                    os.remove(encoded_path)

        self.task_queue.remove_task(task_id)
        await self._notify_user(task["user_id"], f"✅ Task `{task_id[:8]}` completed successfully.")
        self._cleanup_task_folder(task_id)

    async def _send_completion_to_group(self, task: dict, job: dict, file_path: str):
        try:
            source_chat_id = task.get("source_chat_id")
            if not source_chat_id:
                return

            file_size_bytes = os.path.getsize(file_path)
            if file_size_bytes >= 1024 * 1024 * 1024:
                size_str = f"{file_size_bytes / (1024**3):.2f} GB"
            elif file_size_bytes >= 1024 * 1024:
                size_str = f"{file_size_bytes / (1024**2):.2f} MB"
            else:
                size_str = f"{file_size_bytes / 1024:.2f} KB"

            elapsed_seconds = int(time.time() - task.get("_start_time", time.time()))
            if elapsed_seconds < 60:
                elapsed_str = f"{elapsed_seconds}s"
            elif elapsed_seconds < 3600:
                minutes, seconds = divmod(elapsed_seconds, 60)
                elapsed_str = f"{minutes}m {seconds}s"
            else:
                hours, remainder = divmod(elapsed_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                elapsed_str = f"{hours}h {minutes}m {seconds}s"

            quality = job.get("resolution", "1080p")

            message = (
                f"`{job['output_filename']}`\n"
                f"┠ **Elapsed:** {elapsed_str}\n"
                f"➲ File has been Sent to Bot PM (Private)"
            )

            await self.client.send_message(
                chat_id=source_chat_id,
                text=message,
                disable_web_page_preview=True
            )
            print(f"[Worker] Sent completion message to group {source_chat_id} for task {task['task_id'][:8]}")

        except FloodWait as e:
            print(f"[Worker] FloodWait in completion message: {e.value}s")
            await asyncio.sleep(e.value)
            try:
                await self.client.send_message(
                    chat_id=source_chat_id,
                    text=message,
                    disable_web_page_preview=True
                )
            except Exception as retry_e:
                print(f"[Worker] Failed to send completion message after FloodWait: {retry_e}")
        except Exception as e:
            print(f"[Worker] Failed to send completion message to group: {e}")

    async def _download(self, task: dict) -> str:
        task_id = task["task_id"]

        prefetched = task.get("_downloaded_path", "")
        if prefetched and os.path.exists(prefetched):
            print(f"[Worker] Using prefetched file for {task_id[:8]}")
            task.setdefault("download_completed_at", datetime.utcnow().isoformat())
            self.task_queue.update_status(task_id, "ready", 0)
            return prefetched

        if self._prefetch_task_id == task_id and self._prefetch_task and not self._prefetch_task.done():
            print(f"[Worker] Waiting for prefetch to finish for {task_id[:8]}")
            try:
                await self._prefetch_task
            except Exception:
                pass
            prefetched = task.get("_downloaded_path", "")
            if prefetched and os.path.exists(prefetched):
                task.setdefault("download_completed_at", datetime.utcnow().isoformat())
                self.task_queue.update_status(task_id, "ready", 0)
                return prefetched

        self.task_queue.update_status(task_id, "downloading", 0)
        task["user_is_premium"] = await self._get_user_premium(task["user_id"])

        downloader = Downloader(self.temp_base, self.task_queue, task_id)
        path = await downloader.download(client=self.client, task_data=task)

        if not path or not os.path.exists(path):
            raise Exception("Download returned no valid file path")

        task["_downloaded_path"] = path
        task["download_completed_at"] = datetime.utcnow().isoformat()
        self.task_queue.update_status(task_id, "ready", 0)
        return path

    async def _maybe_prefetch_next(self, current_task_id: str):
        if self._prefetch_task and not self._prefetch_task.done():
            return

        next_task = None
        for tid in self.task_queue.queue:
            if tid == current_task_id:
                continue
            t = self.task_queue.get_task(tid)
            if t and t.get("status") == "queued":
                next_task = t
                break

        if not next_task:
            return

        next_id = next_task["task_id"]
        print(f"[Worker] Prefetching task {next_id[:8]}")
        await self._snapshot_thumbnail(next_task)
        self._prefetch_task_id = next_id
        self._prefetch_task = asyncio.create_task(self._bg_download(next_task))

    async def _bg_download(self, task: dict):
        task_id = task["task_id"]
        try:
            task["user_is_premium"] = await self._get_user_premium(task["user_id"])
            downloader = Downloader(self.temp_base, self.task_queue, task_id)
            path = await downloader.download(client=self.client, task_data=task)
            if path and os.path.exists(path):
                task["_downloaded_path"] = path
                task["download_completed_at"] = datetime.utcnow().isoformat()
                self.task_queue.update_status(task_id, "ready", 0)
                print(f"[Worker] Prefetch done for {task_id[:8]}")
            else:
                self.task_queue.update_status(task_id, "queued", 0)
        except asyncio.CancelledError:
            self.task_queue.update_status(task_id, "queued", 0)
            raise
        except Exception as e:
            print(f"[Worker] Prefetch failed for {task_id[:8]}: {e}")
            self.task_queue.update_status(task_id, "queued", 0)
        finally:
            if self._prefetch_task_id == task_id:
                self._prefetch_task_id = None
                self._prefetch_task = None

    async def _maybe_preencode_next(self, current_task_id: str):
        if self._preencode_task and not self._preencode_task.done():
            return

        next_task = None
        for tid in self.task_queue.queue:
            if tid == current_task_id:
                continue
            t = self.task_queue.get_task(tid)
            if not t or t.get("status") != "ready":
                continue
            downloaded = t.get("_downloaded_path", "")
            if downloaded and os.path.exists(downloaded) and not self._get_preencoded_jobs(t):
                next_task = t
                break

        if not next_task:
            return

        next_id = next_task["task_id"]
        if self.PREENCODE_COOLDOWN > 0:
            print(f"[Worker] Waiting {self.PREENCODE_COOLDOWN}s before pre-encoding {next_id[:8]}")
            await asyncio.sleep(self.PREENCODE_COOLDOWN)
            if self._preencode_task and not self._preencode_task.done():
                return
            if not self.running or current_task_id != self._current_task_id:
                return
            if next_task.get("status") != "ready":
                return
            downloaded = next_task.get("_downloaded_path", "")
            if not downloaded or not os.path.exists(downloaded):
                return

        print(f"[Worker] Pre-encoding ready task {next_id[:8]} while current task uploads")
        await self._snapshot_thumbnail(next_task)
        self._preencode_task_id = next_id
        self._preencode_task = asyncio.create_task(self._bg_preencode(next_task))

    async def _bg_preencode(self, task: dict):
        task_id = task["task_id"]
        try:
            downloaded_path = task.get("_downloaded_path", "")
            if not downloaded_path or not os.path.exists(downloaded_path):
                return

            jobs = task.get("jobs") or [self._legacy_job(task)]
            task["total_jobs"] = len(jobs)

            if self._can_encode_jobs_together(jobs):
                encoded_jobs = await self._encode_many(task, downloaded_path, jobs)
            else:
                encoded_jobs = []
                for idx, job in enumerate(jobs, start=1):
                    task["current_job"] = idx
                    task["resolution"] = job["resolution"]
                    task["output_filename"] = job["output_filename"]
                    task["current_job_mode"] = job.get("processing_mode", "encode")
                    encoded_jobs.append((job, await self._encode(task, downloaded_path, job)))

            task["_encoded_jobs"] = encoded_jobs
            self.task_queue.update_status(task_id, "ready", 100)
            print(f"[Worker] Pre-encode done for {task_id[:8]}")
        except asyncio.CancelledError:
            self.task_queue.update_status(task_id, "ready", 0)
            raise
        except Exception as e:
            print(f"[Worker] Pre-encode failed for {task_id[:8]}: {e}")
            task.pop("_encoded_jobs", None)
            self.task_queue.update_status(task_id, "ready", 0)
        finally:
            if self._preencode_task_id == task_id:
                self._preencode_task_id = None
                self._preencode_task = None

    async def _encode(self, task: dict, input_path: str, job: dict) -> str:
        task_id = task["task_id"]
        task["encode_started_at"] = datetime.utcnow().isoformat()
        self.task_queue.update_status(task_id, "encoding", 0)
        task["encode_progress"] = {"percentage": 0.0}

        settings = self._settings_for_job(task, job)

        encoder = Encoder(self.ffmpeg)
        encoded_path = await encoder.encode(
            task_data=task,
            input_path=input_path,
            settings=settings,
            task_queue=self.task_queue,
        )
        if not encoded_path:
            raise Exception(f"Encoder returned no path for {job['resolution']}")
        return encoded_path

    async def _encode_many(self, task: dict, input_path: str, jobs: list[dict]) -> list[tuple[dict, str]]:
        task_id = task["task_id"]
        task["encode_started_at"] = datetime.utcnow().isoformat()
        task["current_job"] = 0
        task["current_job_mode"] = "encode"
        task["resolution"] = " / ".join(job.get("resolution", "?") for job in jobs)
        task["output_filename"] = jobs[0]["output_filename"]
        task["encode_progress"] = {"percentage": 0.0}
        self.task_queue.update_status(task_id, "encoding", 0)

        encoder = Encoder(self.ffmpeg)
        encoded_jobs = await encoder.encode_many(
            task_data=task,
            input_path=input_path,
            jobs=jobs,
            settings_list=[self._settings_for_job(task, job) for job in jobs],
            task_queue=self.task_queue,
        )
        if not encoded_jobs:
            raise Exception("Encoder returned no paths")
        return encoded_jobs

    def _settings_for_job(self, task: dict, job: dict) -> dict:
        settings = {
            "resolution":      job["resolution"],
            "processing_mode": job.get("processing_mode", "encode"),
            "crf":             job.get("crf"),
            "preset":          job.get("preset"),
            "codec":           job.get("codec"),
            "audio_bitrate":   job.get("audio_bitrate"),
            "metadata":        job.get("metadata", {}),
            "watermark":       task.get("watermark"),
        }
        return settings

    @staticmethod
    def _can_encode_jobs_together(jobs: list[dict]) -> bool:
        return (
            len(jobs) > 1
            and all(job.get("processing_mode", "encode") == "encode" for job in jobs)
        )

    async def _upload(self, task: dict, file_path: str, job: dict):
        task_id = task["task_id"]
        self.task_queue.update_status(task_id, "uploading", 0)
        task["upload_progress"] = {"percentage": 0.0}
        if task.get("_allow_next_preencode"):
            await self._maybe_preencode_next(task_id)

        upload_data = {**task,
            "upload_file_path": file_path,
            "output_filename":  job["output_filename"],
            "send_type":        job.get("send_type", "media"),
            "thumbnail_path":   await self._resolve_thumbnail(task, job),
        }

        uploader = Uploader(
            self.client,
            upload_data,
            self.task_queue,
            tmp_dir=self.temp_base,
            ffmpeg=self.ffmpeg,
            user_is_premium=task.get("user_is_premium", False),
        )
        await uploader.upload()

    async def _snapshot_thumbnail(self, task: dict):
        src = task.get("thumbnail_path", "")
        if not src or not os.path.exists(src):
            return
        task_folder = os.path.join(self.temp_base, task["task_id"])
        frozen_path = os.path.join(task_folder, f"thumbnail_{task['task_id']}.jpg")
        if os.path.abspath(src) == os.path.abspath(frozen_path):
            return
        os.makedirs(task_folder, exist_ok=True)
        try:
            shutil.copy2(src, frozen_path)
            task["thumbnail_path"] = frozen_path
        except Exception as e:
            print(f"[Worker] Thumbnail snapshot failed for {task['task_id'][:8]}: {e}")

    async def _resolve_thumbnail(self, task: dict, job: dict) -> str | None:
        auto_detect = bool(task.get("auto_detect_thumb", False))
        user_thumb  = task.get("thumbnail_path") or job.get("thumbnail_path") or ""
        task_folder = os.path.join(self.temp_base, task["task_id"])

        if not auto_detect:
            return user_thumb if user_thumb and os.path.exists(user_thumb) else None

        source_thumb_id = task.get("source_thumbnail_file_id", "")
        if source_thumb_id:
            dest = os.path.join(task_folder, "_source_thumb.jpg")
            try:
                downloaded = await self.client.download_media(source_thumb_id, file_name=dest)
                if downloaded and os.path.exists(downloaded):
                    return os.path.abspath(downloaded)
            except Exception:
                pass

        return user_thumb if user_thumb and os.path.exists(user_thumb) else None

    def _cleanup_task_folder(self, task_id: str):
        folder = os.path.join(self.temp_base, task_id)
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)

    @staticmethod
    def _get_preencoded_jobs(task: dict) -> list[tuple[dict, str]]:
        encoded_jobs = task.get("_encoded_jobs") or []
        if not encoded_jobs:
            return []
        for _, path in encoded_jobs:
            if not path or not os.path.exists(path):
                return []
        return encoded_jobs

    async def _get_user_premium(self, user_id: int) -> bool:
        try:
            user = await self.client.get_users(user_id)
            return bool(getattr(user, "is_premium", False))
        except Exception:
            return False

    def _legacy_job(self, task: dict) -> dict:
        resolution = task.get("resolution", "1080p")
        return {
            "resolution":      resolution,
            "output_filename": task["output_filename"],
            "processing_mode": "encode",
            "crf":             task.get("crf", 28),
            "preset":          task.get("preset", "medium"),
            "codec":           task.get("codec", "libx264"),
            "audio_bitrate":   task.get("audio_bitrate", "128k"),
            "metadata":        task.get("metadata", {}),
            "thumbnail_path":  task.get("thumbnail_path", ""),
            "send_type":       task.get("send_type", "media"),
        }

    async def _notify_user(self, user_id: int, message: str):
        try:
            await self.client.send_message(user_id, message)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await self.client.send_message(user_id, message)
            except Exception as e2:
                print(f"[Worker] Notify failed for {user_id} after FloodWait: {e2}")
        except Exception as e:
            print(f"[Worker] Notify failed for {user_id}: {e}")

    async def cancel_task(self, task_id: str):
        if self._preencode_task_id == task_id and self._preencode_task and not self._preencode_task.done():
            self._preencode_task.cancel()
            try:
                await self._preencode_task
            except (asyncio.CancelledError, Exception):
                pass
            self._preencode_task = None
            self._preencode_task_id = None

        if self._prefetch_task_id == task_id and self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()
            try:
                await self._prefetch_task
            except (asyncio.CancelledError, Exception):
                pass
            self._prefetch_task = None
            self._prefetch_task_id = None

        task = self.task_queue.get_task(task_id)

        if task_id == self._current_task_id:
            if self._current_asyncio_task and not self._current_asyncio_task.done():
                self._current_asyncio_task.cancel()
        else:
            if task:
                self.task_queue.remove_task(task_id)
                self._cleanup_task_folder(task_id)
                await self._notify_user(task["user_id"], f"⚠️ Task `{task_id[:8]}` cancelled.")
