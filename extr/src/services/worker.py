import asyncio
import os
import shutil

from src.services.downloader import Downloader
from src.services.encoder import Encoder
from src.services.uploader import Uploader

class Worker:
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
        self._current_uploader: "Uploader | None" = None
        self._bg_downloads: dict[str, asyncio.Task] = {}

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

    def _next_queued_task(self):
        for task_id in self.task_queue.queue:
            task = self.task_queue.get_task(task_id)
            if task and task.get("status") in ("queued", "ready"):
                return task
        return None

    async def _snapshot_thumbnail(self, task: dict):
        task_id = task["task_id"]
        src = task.get("thumbnail_path", "")

        if not src or not os.path.exists(src):
            return

        task_folder = os.path.join(self.temp_base, task_id)
        frozen_path = os.path.join(task_folder, f"thumbnail_{task_id}.jpg")

        if os.path.abspath(src) == os.path.abspath(frozen_path):
            return

        os.makedirs(task_folder, exist_ok=True)

        try:
            shutil.copy2(src, frozen_path)
        except Exception as e:
            print(f"[Worker] Could not snapshot thumbnail for {task_id}: {e}")
            return

        task["thumbnail_path"] = frozen_path

    async def _run_task(self, task: dict):
        task_id = task["task_id"]
        self.task_queue.update_status(task_id, "starting", 0)

        await self._snapshot_thumbnail(task)

        downloaded_path = await self._download(task)
        if not downloaded_path:
            raise Exception("Download failed")

        await self._prefetch_next_download(task_id)

        jobs = task.get("jobs") or [self._legacy_job(task)]
        total_jobs = len(jobs)
        task["total_jobs"] = total_jobs

        for idx, job in enumerate(jobs, start=1):
            task["current_job"] = idx
            task["resolution"] = job["resolution"]
            task["output_filename"] = job["output_filename"]
            task["current_job_mode"] = job.get("processing_mode", "encode")

            encoded_path = await self._encode(task, downloaded_path, job)
            if not encoded_path:
                raise Exception(f"Encoding failed for {job['resolution']}")

            await self._upload(task, encoded_path, job)

            if os.path.exists(encoded_path):
                os.remove(encoded_path)

        self.task_queue.remove_task(task_id)
        await self._notify_user(task["user_id"], f"✅ Task `{task_id[:8]}` completed successfully.")
        self._cleanup_task_folder(task_id)

    async def _download(self, task: dict) -> str | None:
        task_id = task["task_id"]

        # ── Case 1: prefetch already finished — file is on disk ──────────────
        existing = task.get("_downloaded_path", "")
        if existing and os.path.exists(existing):
            print(f"[Worker] Using prefetched file for task {task_id}")
            self.task_queue.update_status(task_id, "ready", 0)
            return existing

        # ── Case 2: prefetch is still in progress — wait for it ──────────────
        bg = self._bg_downloads.get(task_id)
        if bg and not bg.done():
            print(f"[Worker] Waiting for in-progress prefetch for task {task_id}")
            try:
                await bg
            except Exception:
                pass
            existing = task.get("_downloaded_path", "")
            if existing and os.path.exists(existing):
                self.task_queue.update_status(task_id, "ready", 0)
                return existing

        # ── Case 3: normal download ───────────────────────────────────────────
        self.task_queue.update_status(task_id, "downloading", 0)
        task["user_is_premium"] = await self._get_user_premium(task["user_id"])

        downloader = Downloader(self.temp_base, self.task_queue, task_id)
        path = await downloader.download(client=self.client, task_data=task)

        if not path or not os.path.exists(path):
            return None
        task["_downloaded_path"] = path
        self.task_queue.update_status(task_id, "ready", 0)
        return path

    async def _prefetch_next_download(self, current_task_id: str):

        if self._bg_downloads:
            return 

        next_task = None
        for task_id in self.task_queue.queue:
            if task_id == current_task_id:
                continue
            task = self.task_queue.get_task(task_id)
            if task and task.get("status") == "queued":
                next_task = task
                break

        if not next_task:
            return

        next_id = next_task["task_id"]
        print(f"[Worker] Starting prefetch download for task {next_id}")

        await self._snapshot_thumbnail(next_task)

        bg = asyncio.create_task(self._bg_download(next_task))
        self._bg_downloads[next_id] = bg

    async def _bg_download(self, task: dict):
        task_id = task["task_id"]
        try:
            task["user_is_premium"] = await self._get_user_premium(task["user_id"])
            downloader = Downloader(self.temp_base, self.task_queue, task_id)
            path = await downloader.download(client=self.client, task_data=task)
            if path and os.path.exists(path):
                task["_downloaded_path"] = path
                self.task_queue.update_status(task_id, "ready", 0)
                print(f"[Worker] Prefetch complete for task {task_id}")
            else:
                self.task_queue.update_status(task_id, "queued", 0)
        except asyncio.CancelledError:
            self.task_queue.update_status(task_id, "queued", 0)
            raise
        except Exception as e:
            print(f"[Worker] Prefetch download failed for {task_id}: {e}")
            self.task_queue.update_status(task_id, "queued", 0)
        finally:
            self._bg_downloads.pop(task_id, None)

    async def _encode(self, task: dict, input_path: str, job: dict) -> str | None:
        task_id = task["task_id"]
        self.task_queue.update_status(task_id, "encoding", 0)
        task["encode_progress"] = {"percentage": 0.0}
        task["progress"] = 0.0

        settings = {
            "resolution": job["resolution"],
            "processing_mode": job.get("processing_mode", "encode"),
            "crf": job.get("crf"),
            "preset": job.get("preset"),
            "codec": job.get("codec"),
            "audio_bitrate": job.get("audio_bitrate"),
            "metadata": job.get("metadata", {}),
            "watermark": task.get("watermark"),
        }

        encoder = Encoder(self.ffmpeg)
        encoded_path = await encoder.encode(
            task_data=task,
            input_path=input_path,
            settings=settings,
            task_queue=self.task_queue,
        )
        return encoded_path

    async def _upload(self, task: dict, file_path: str, job: dict):
        task_id = task["task_id"]
        self.task_queue.update_status(task_id, "uploading", 0)
        task["upload_progress"] = {"percentage": 0.0}
        task["progress"] = 0.0

        upload_data = task.copy()
        upload_data["upload_file_path"] = file_path
        upload_data["output_filename"] = job["output_filename"]
        upload_data["send_type"] = job.get("send_type", "media")
        upload_data["thumbnail_path"] = await self._resolve_thumbnail(task, job)

        uploader = Uploader(
            self.client,
            upload_data,
            self.task_queue,
            tmp_dir=self.temp_base,
            ffmpeg=self.ffmpeg,
            user_is_premium=task.get("user_is_premium", False),
        )
        self._current_uploader = uploader
        try:
            await uploader.upload()
        finally:
            self._current_uploader = None

    async def _resolve_thumbnail(self, task: dict, job: dict) -> str | None:
        auto_detect      = bool(task.get("auto_detect_thumb", False))
        source_thumb_id  = task.get("source_thumbnail_file_id", "")
        user_thumb = task.get("thumbnail_path") or job.get("thumbnail_path") or ""

        task_folder = os.path.join(self.temp_base, task["task_id"])

        if not auto_detect:
            if user_thumb and os.path.exists(user_thumb):
                return user_thumb
            return None
        if source_thumb_id:
            source_thumb_path = os.path.join(task_folder, "_source_thumb.jpg")
            try:
                downloaded = await self.client.download_media(
                    source_thumb_id,
                    file_name=source_thumb_path,
                )
                if downloaded and os.path.exists(downloaded):
                    return os.path.abspath(downloaded)
            except Exception:
                pass

        if user_thumb and os.path.exists(user_thumb):
            return user_thumb

        return None

    def _cleanup_task_folder(self, task_id: str):
        folder = os.path.join(self.temp_base, task_id)
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)

    async def _get_user_premium(self, user_id: int) -> bool:
        try:
            tg_user = await self.client.get_users(user_id)
            return bool(getattr(tg_user, "is_premium", False))
        except Exception:
            return False

    def _legacy_job(self, task: dict) -> dict:
        resolution = task.get("resolution", "1080p")
        return {
            "resolution": resolution,
            "output_filename": task["output_filename"],
            "processing_mode": "encode",
            "crf": task.get("crf", 28),
            "preset": task.get("preset", "medium"),
            "codec": task.get("codec", "libx264"),
            "audio_bitrate": task.get("audio_bitrate", "128k"),
            "metadata": task.get("metadata", {}),
            "thumbnail_path": task.get("thumbnail_path", ""),
            "send_type": task.get("send_type", "media"),
        }

    async def _notify_user(self, user_id: int, message: str):
        try:
            await self.client.send_message(user_id, message)
        except Exception as e:
            print(f"[Worker] Failed to notify user {user_id}: {e}")

    async def cancel_task(self, task_id: str):
        bg = self._bg_downloads.pop(task_id, None)
        if bg and not bg.done():
            bg.cancel()
            try:
                await bg
            except (asyncio.CancelledError, Exception):
                pass

        task = self.task_queue.get_task(task_id)

        if task_id == self._current_task_id:
            if self._current_uploader is not None:
                self._current_uploader.cancel()
            if self._current_asyncio_task and not self._current_asyncio_task.done():
                self._current_asyncio_task.cancel()
            else:
                if task:
                    self.task_queue.remove_task(task_id)
                    self._cleanup_task_folder(task_id)
                    await self._notify_user(task["user_id"], f"⚠️ Task `{task_id[:8]}` cancelled.")
        else:
            if task:
                self.task_queue.remove_task(task_id)
                self._cleanup_task_folder(task_id)
                await self._notify_user(task["user_id"], f"⚠️ Task `{task_id[:8]}` cancelled.")