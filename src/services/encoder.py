import asyncio
import os


class Encoder:
    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg

    async def encode(
        self,
        task_data:  dict,
        input_path: str,
        settings:   dict,
        task_queue=None,
    ) -> str:
        output_file_name  = task_data["output_filename"]
        task_folder       = os.path.dirname(input_path)
        resolution        = task_data.get("resolution", "1080p")
        task_id           = task_data.get("task_id", "enc")

        base_name, ext    = os.path.splitext(output_file_name)
        task_id_short     = task_id[:8]
        safe_ext          = ext if ext else ".mp4"
        temp_output_name  = f"_tmp_{task_id_short}_{resolution}{safe_ext}"
        temp_output_path  = os.path.join(task_folder, temp_output_name)
        final_output_path = os.path.join(task_folder, output_file_name)

        if not os.path.exists(input_path):
            raise Exception(f"Input file not found: {input_path}")

        cmd = self.ffmpeg.build_command(input_path, temp_output_path, settings)

        # Probe duration directly from the file — no dependency on task media_info
        duration_secs = 0.0
        try:
            media_info = await self.ffmpeg.probe_media(input_path)
            duration_secs = float(media_info.get("format", {}).get("duration", 0))
            # Pass to build_command settings for watermark timing (if watermark uses it)
            settings.setdefault("media_info", media_info)
        except Exception:
            pass

        if duration_secs == 0.0:
            print(f"[Encoder] [{task_id_short}] No duration — progress will jump 0→100% on completion")

        # ── Progress callback ─────────────────────────────────────────────────
        async def _progress_cb(pct: float):
            if task_queue is None:
                return
            task = task_queue.tasks.get(task_id)
            if task is not None:
                task["encode_progress"] = {"percentage": round(pct, 1)}
                # 🔧 CRITICAL FIX: Update task["progress"] so status command shows it
                task["progress"] = round(pct, 1)
                # Also call update_status without progress arg to avoid overwriting
                # (since update_status sets task["progress"] if progress arg is provided)
                task_queue.update_status(task_id, "encoding")

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
                task["progress"] = 100.0
                task_queue.update_status(task_id, "encoding")

        return final_output_path

    def get_progress(self) -> dict:
        return {}