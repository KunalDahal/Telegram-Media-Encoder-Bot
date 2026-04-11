import asyncio
import os


class Encoder:
    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg

    async def encode(self, task_data: dict, input_path: str, settings: dict, task_queue=None) -> str:
        task_id         = task_data.get("task_id", "enc")
        output_filename = task_data["output_filename"]
        resolution      = task_data.get("resolution", "1080p")

        task_folder = os.path.dirname(input_path)
        base, ext   = os.path.splitext(output_filename)
        safe_ext    = ext or ".mp4"

        temp_output_path  = os.path.join(task_folder, f"_tmp_{task_id[:8]}_{resolution}{safe_ext}")
        final_output_path = os.path.join(task_folder, output_filename)

        if not os.path.exists(input_path):
            raise Exception(f"Input file not found: {input_path}")

        # ── Probe duration ────────────────────────────────────────────────────
        duration_secs = await self._probe_duration(input_path)

        if duration_secs <= 0.0:
            print(f"[Encoder] WARNING: Could not determine duration for {task_id[:8]} — "
                  "progress bar will be unavailable.")

        # Attach media_info to settings for watermark rendering
        try:
            settings["media_info"] = await self.ffmpeg.probe_media(input_path)
        except Exception:
            settings["media_info"] = {}

        # ── Build and run command ─────────────────────────────────────────────
        cmd = self.ffmpeg.build_command(input_path, temp_output_path, settings)

        def _make_progress_cb(tq, tid):
            """Return a closure that writes encode progress directly to the live task dict."""
            def _cb_sync(pct: float):
                if tq is None:
                    return
                live_task = tq.tasks.get(tid)
                if live_task is not None:
                    pct_r = round(pct, 1)
                    live_task["encode_progress"] = {"percentage": pct_r}
                    # update_status keeps status="encoding" and sets task["progress"]
                    tq.update_status(tid, "encoding", pct_r)

            async def _cb(pct: float):
                _cb_sync(pct)

            return _cb

        progress_cb = _make_progress_cb(task_queue, task_id) if task_queue else None

        success, error = await self.ffmpeg.execute(
            cmd,
            duration_secs=duration_secs,
            progress_cb=progress_cb,
        )

        if not success:
            raise Exception(f"Encoding failed: {error}")

        if not os.path.exists(temp_output_path):
            raise Exception("Output file was not created after encoding")
        if os.path.getsize(temp_output_path) == 0:
            raise Exception("Output file is empty after encoding")

        # Atomic rename to final name
        if os.path.exists(final_output_path):
            os.remove(final_output_path)
        os.rename(temp_output_path, final_output_path)

        # Mark 100 % on the live task
        if task_queue:
            live_task = task_queue.tasks.get(task_id)
            if live_task is not None:
                live_task["encode_progress"] = {"percentage": 100.0}
            task_queue.update_status(task_id, "encoding", 100)

        return final_output_path

    # ── Duration probe (tries multiple methods) ───────────────────────────────

    async def _probe_duration(self, input_path: str) -> float:
        # Method 1: ffprobe JSON
        try:
            info = await self.ffmpeg.probe_media(input_path)
            d = float(info.get("format", {}).get("duration", 0) or 0)
            if d > 0:
                return d
            # Fallback: check individual streams
            for stream in info.get("streams", []):
                d = float(stream.get("duration", 0) or 0)
                if d > 0:
                    return d
        except Exception:
            pass

        # Method 2: ffprobe raw output
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
                    return float(raw)
        except Exception:
            pass

        return 0.0