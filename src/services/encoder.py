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

        # ── Probe video duration for progress % calculation ───────────────────
        duration_secs = 0.0
        try:
            mi = (
                task_data.get("media_info")
                or settings.get("media_info")
                or {}
            )
            duration_secs = float(mi.get("format", {}).get("duration", 0))
        except (TypeError, ValueError):
            duration_secs = 0.0

        # ── Progress callback → writes to task["encode_progress"] ─────────────
        async def _progress_cb(pct: float):
            if task_queue is None:
                return
            task = task_queue.tasks.get(task_id)
            if task is not None:
                task["encode_progress"] = {"percentage": round(pct, 1)}

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

        return final_output_path

    def get_progress(self) -> dict:
        return {}