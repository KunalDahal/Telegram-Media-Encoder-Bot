import asyncio
import os


class Encoder:
    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg

    async def encode(self, task_data: dict, input_path: str, settings: dict, task_queue=None) -> str:
        output_file_name = task_data["output_filename"]
        task_folder = os.path.dirname(input_path)
        resolution = task_data.get("resolution", "1080p")
        task_id = task_data.get("task_id", "enc")

        base_name, ext = os.path.splitext(output_file_name)
        task_id_short = task_id[:8]
        safe_ext = ext if ext else ".mp4"
        temp_output_name = f"_tmp_{task_id_short}_{resolution}{safe_ext}"
        temp_output_path = os.path.join(task_folder, temp_output_name)
        final_output_path = os.path.join(task_folder, output_file_name)

        if not os.path.exists(input_path):
            raise Exception(f"Input file not found: {input_path}")

        duration_secs = 0.0
        media_info: dict = {}

        try:
            media_info = await self.ffmpeg.probe_media(input_path)
            settings["media_info"] = media_info
            duration_secs = float(media_info.get("format", {}).get("duration", 0) or 0)
        except Exception:
            pass
        if duration_secs <= 0.0:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.ffmpeg.ffprobe_path,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    input_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and stdout:
                    raw = stdout.decode().strip()
                    if raw and raw.lower() not in ("n/a", ""):
                        duration_secs = float(raw)
            except Exception:
                pass
        if duration_secs <= 0.0 and media_info:
            for stream in media_info.get("streams", []):
                try:
                    d = float(stream.get("duration", 0) or 0)
                    if d > 0:
                        duration_secs = d
                        break
                except (TypeError, ValueError):
                    pass

        if duration_secs <= 0.0:
            print(f"[Encoder] WARNING: Could not determine duration for {task_id_short} — "
                  "progress reporting will be disabled for this task.")

        # ── Build command ─────────────────────────────────────────────────────
        cmd = self.ffmpeg.build_command(input_path, temp_output_path, settings)

        async def _progress_cb(pct: float):
            if task_queue is None:
                return
            task = task_queue.tasks.get(task_id)
            if task is not None:
                pct_rounded = round(pct, 1)
                task["encode_progress"] = {"percentage": pct_rounded}
                task_queue.update_status(task_id, "encoding", pct_rounded)

        success, error = await self.ffmpeg.execute(
            cmd,
            duration_secs=duration_secs,
            progress_cb=_progress_cb if task_queue else None,
        )

        if not success:
            raise Exception(f"Encoding failed: {error}")

        if not os.path.exists(temp_output_path):
            raise Exception("Output file not created after encoding")
        if os.path.getsize(temp_output_path) == 0:
            raise Exception("Output file is empty after encoding")

        if os.path.exists(final_output_path):
            os.remove(final_output_path)
        os.rename(temp_output_path, final_output_path)
        if task_queue:
            task = task_queue.tasks.get(task_id)
            if task is not None:
                task["encode_progress"] = {"percentage": 100.0}
                task_queue.update_status(task_id, "encoding", 100)

        return final_output_path

    def get_progress(self) -> dict:
        return {}