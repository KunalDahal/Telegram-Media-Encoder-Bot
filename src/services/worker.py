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
        self.task_queue           = task_queue
        self.user_settings_getter = user_settings_getter
        self.ffmpeg               = ffmpeg
        self.client               = client
        self.config               = config
        self.temp_base            = config.paths.tmp
        self.thumbnails_dir       = config.paths.thumbnails
        self.running              = False
        self._active_tasks: dict[str, asyncio.Task] = {}

        os.makedirs(self.temp_base,      exist_ok=True)
        os.makedirs(self.thumbnails_dir, exist_ok=True)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self.running = True
        await asyncio.gather(
            self._download_loop(),
            self._process_loop(),
        )

    async def stop(self):
        self.running = False
        tasks = list(self._active_tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── Queue helpers ─────────────────────────────────────────────────────────

    def _next_with_status(self, status: str):
        for task_id in self.task_queue.queue:
            task = self.task_queue.get_task(task_id)
            if task and task.get("status") == status:
                return task
        return None

    def _count_with_status(self, status: str) -> int:
        return sum(
            1 for t in self.task_queue.tasks.values()
            if t.get("status") == status
        )

    # ── Download loop ─────────────────────────────────────────────────────────

    async def _download_loop(self):
        while self.running:
            try:
                if self._count_with_status("ready") >= 1:
                    await asyncio.sleep(0.5)
                    continue

                task = self._next_with_status("queued")
                if not task:
                    await asyncio.sleep(1)
                    continue

                task_id = task["task_id"]
                self.task_queue.update_status(task_id, "starting", 0)

                coro = self._run_download(task)
                t    = asyncio.create_task(coro, name=f"dl-{task_id}")
                self._active_tasks[task_id] = t
                await t

            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[Worker] _download_loop error: {e}")
                await asyncio.sleep(2)

    # ── Process loop ──────────────────────────────────────────────────────────

    async def _process_loop(self):
        while self.running:
            try:
                task = self._next_with_status("ready")
                if not task:
                    await asyncio.sleep(0.5)
                    continue

                task_id = task["task_id"]
                coro = self._run_encode_upload(task)
                t    = asyncio.create_task(coro, name=f"proc-{task_id}")
                self._active_tasks[task_id] = t
                await t

            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[Worker] _process_loop error: {e}")
                await asyncio.sleep(2)

    # ── Download stage ────────────────────────────────────────────────────────

    async def _run_download(self, task: dict):
        task_id = task["task_id"]
        try:
            task["user_is_premium"] = await self._get_user_premium(task["user_id"])

            self._clear_progress_details(task)
            self._set_stage(task, "downloading", 0)

            from src.services.downloader import Downloader
            downloader = Downloader(self.temp_base, self.task_queue, task_id)
            path       = await downloader.download(client=self.client, task_data=task)

            if not path or not os.path.exists(path):
                raise Exception("Download returned no file")

            task["media_info"]       = await self.ffmpeg.probe_media(path)
            task["_downloaded_path"] = path
            self.task_queue.update_status(task_id, "ready", 0)

        except asyncio.CancelledError:
            await self.notify_user(task["user_id"], f"Task `{task_id[:8]}` was cancelled.")
            self.task_queue.remove_task(task_id)
            self._cleanup_task_folder(task_id)
            raise

        except Exception as e:
            print(f"[Worker] Download failed for {task_id}: {e}")
            await self.notify_user(
                task["user_id"],
                f"Task `{task_id[:8]}` failed.\nError: {str(e)[:200]}",
            )
            self.task_queue.remove_task(task_id)
            self._cleanup_task_folder(task_id)

        finally:
            self._active_tasks.pop(task_id, None)

    # ── Encode + upload stage ─────────────────────────────────────────────────

    async def _run_encode_upload(self, task: dict):
        task_id         = task["task_id"]
        downloaded_path = task.get("_downloaded_path")
        encoded_paths: list[str] = []

        try:
            if not downloaded_path or not os.path.exists(downloaded_path):
                raise Exception("Downloaded file missing — cannot encode")

            jobs       = task.get("jobs") or [self._legacy_job(task)]
            total_jobs = len(jobs)
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

                # ── Encode ────────────────────────────────────────────────────
                self._clear_progress_details(task)
                self._set_stage(
                    task, "encoding",
                    _encode_progress_base(job_index, total_jobs),
                )

                encoded_path = await encoder.encode(
                    task_data=task,
                    input_path=downloaded_path,
                    settings=job_settings,
                    task_queue=self.task_queue,
                )

                if not encoded_path or not os.path.exists(encoded_path):
                    raise Exception(f"Encoding failed for {resolution}: output not found")

                encoded_paths.append(encoded_path)
                task["encoded_size"] = os.path.getsize(encoded_path)

                # ── Upload ────────────────────────────────────────────────────
                self._clear_progress_details(task)
                self._set_stage(
                    task, "uploading",
                    _upload_progress_base(job_index, total_jobs),
                )
                task["upload_file_path"] = encoded_path
                task["thumbnail_path"]   = job.get("thumbnail_path", "")
                task["send_type"]        = job.get("send_type", "media")

                uploader = Uploader(
                    self.client,
                    task,
                    self.task_queue,
                    tmp_dir=self.temp_base,
                    ffmpeg=self.ffmpeg,
                    user_is_premium=task.get("user_is_premium", False),
                )
                await uploader.upload()
                task.pop("upload_file_path", None)
                if os.path.exists(encoded_path):
                    try:
                        os.remove(encoded_path)
                    except Exception:
                        pass
                encoded_paths = [p for p in encoded_paths if p != encoded_path]

            # ── All jobs done ─────────────────────────────────────────────────
            self.task_queue.remove_task(task_id)
            await self.notify_user(task["user_id"], f"✅ Task `{task_id[:8]}` completed.")

        except asyncio.CancelledError:
            await self.notify_user(task["user_id"], f"Task `{task_id[:8]}` was cancelled.")
            self.task_queue.remove_task(task_id)

        except Exception as e:
            print(f"[Worker] Task {task_id} failed: {e}")
            await self.notify_user(
                task["user_id"],
                f"Task `{task_id[:8]}` failed.\nError: {str(e)[:200]}",
            )
            self.task_queue.remove_task(task_id)

        finally:
            self._active_tasks.pop(task_id, None)

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

            self._cleanup_task_folder(task_id)

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
                        await self.notify_user(
                            task["user_id"],
                            f"Task `{task_id[:8]}` has been cancelled.",
                        )
                    except Exception:
                        pass
                self.task_queue.remove_task(task_id)
                self._cleanup_task_folder(task_id)

        except Exception as e:
            print(f"[Worker] cancel_task error for {task_id}: {e}")

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _set_stage(self, task: dict, stage: str, progress: int = None):
        task["current_stage"] = stage
        self.task_queue.update_status(
            task["task_id"],
            stage,
            progress if progress is not None else task.get("progress", 0),
        )

    def _clear_progress_details(self, task: dict):
        task.pop("progress_details", None)
        task.pop("upload_progress",  None)
        task.pop("encode_progress",  None)

    def _cleanup_task_folder(self, task_id: str):
        task_folder = os.path.join(self.temp_base, task_id)
        if os.path.exists(task_folder):
            shutil.rmtree(task_folder, ignore_errors=True)

    async def _get_user_premium(self, user_id: int) -> bool:
        try:
            tg_user = await self.client.get_users(user_id)
            return bool(getattr(tg_user, "is_premium", False))
        except Exception:
            return False

    def _legacy_job(self, task: dict) -> dict:
        resolution = task.get("resolution", "1080p")
        return {
            "resolution":      resolution,
            "output_filename": task["output_filename"],
            "processing_mode": "metadata_only" if resolution == "HDRip" else "encode",
            "crf":             task.get("crf", 28),
            "preset":          task.get("preset", "medium"),
            "codec":           task.get("codec", "libx264"),
            "audio_bitrate":   task.get("audio_bitrate", "128k"),
            "metadata":        task.get("metadata", {}),
            "thumbnail_path":  task.get("thumbnail_path", ""),
            "send_type":       task.get("send_type", "media"),
        }

    async def notify_user(self, user_id: int, message: str):
        try:
            await self.client.send_message(user_id, message)
        except Exception as e:
            print(f"[Worker] Failed to notify user {user_id}: {e}")