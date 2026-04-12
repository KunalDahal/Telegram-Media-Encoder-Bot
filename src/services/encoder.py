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
        print(f"[Encoder] {task_id[:8]} duration_secs={duration_secs:.2f}")

        try:
            settings["media_info"] = await self.ffmpeg.probe_media(input_path)
        except Exception:
            settings["media_info"] = {}

        # ── Build and run command ─────────────────────────────────────────────
        cmd = self.ffmpeg.build_command(input_path, temp_output_path, settings)

        def _make_progress_cb(tq, tid):
            async def _cb(pct: float):
                if tq is None:
                    return
                live_task = tq.tasks.get(tid)
                if live_task is not None:
                    pct_r = round(pct, 1)
                    live_task["encode_progress"] = {"percentage": pct_r}
                    print(f"[Encoder] {tid[:8]} progress={pct_r}%")
                else:
                    print(f"[Encoder] WARNING: tid={tid} not found in tq.tasks (keys={list(tq.tasks.keys())[:3]})")

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

        if os.path.exists(final_output_path):
            os.remove(final_output_path)
        os.rename(temp_output_path, final_output_path)

        if task_queue:
            live_task = task_queue.tasks.get(task_id)
            if live_task is not None:
                live_task["encode_progress"] = {"percentage": 100.0}
            task_queue.update_status(task_id, "encoding", 100)

        return final_output_path

    async def _probe_duration(self, input_path: str) -> float:
        try:
            info = await self.ffmpeg.probe_media(input_path)
            d = float(info.get("format", {}).get("duration", 0) or 0)
            if d > 0:
                return d
            for stream in info.get("streams", []):
                d = float(stream.get("duration", 0) or 0)
                if d > 0:
                    return d
        except Exception:
            pass

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

        try:
            proc = await asyncio.create_subprocess_exec(
                self.ffmpeg.ffprobe_path,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                raw = stdout.decode().strip().splitlines()[0]
                if raw and raw.lower() not in ("n/a", ""):
                    return float(raw)
        except Exception:
            pass
        try:
            proc = await asyncio.create_subprocess_exec(
                self.ffmpeg.ffprobe_path,
                "-v", "error",
                "-select_streams", "v:0",
                "-count_packets",
                "-show_entries", "stream=nb_read_packets,r_frame_rate",
                "-of", "json",
                input_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                import json as _json
                data = _json.loads(stdout.decode())
                streams = data.get("streams", [])
                if streams:
                    s = streams[0]
                    n_packets = int(s.get("nb_read_packets", 0) or 0)
                    fps_raw = s.get("r_frame_rate", "0/1")
                    num, _, den = fps_raw.partition("/")
                    fps = float(num) / float(den) if float(den) else 0.0
                    if n_packets > 0 and fps > 0:
                        return n_packets / fps
        except Exception:
            pass

        return 0.0