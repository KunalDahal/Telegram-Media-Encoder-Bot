import asyncio
import copy
import json
import math
import os
import random

_DEFAULT_FONT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "default.ttf",
)


def _resolve_font(path: str) -> str:
    if path and os.path.isfile(path):
        return os.path.abspath(path)
    if os.path.isfile(_DEFAULT_FONT):
        return os.path.abspath(_DEFAULT_FONT)
    return ""


def _fontfile_expr(font_path: str) -> str:
    if not font_path:
        return ""
    p = font_path.replace("\\", "/")
    drive, rest = os.path.splitdrive(p)
    p_escaped = drive.replace(":", "\\:") + rest
    return f"fontfile='{p_escaped}':"


def _extract_ffmpeg_error(stderr_text: str, max_len: int = 600) -> str:
    lines = stderr_text.strip().splitlines()
    error_lines = [
        ln for ln in lines
        if any(ln.lstrip().lower().startswith(kw)
               for kw in ("error", "invalid", "no such", "cannot", "failed",
                          "fontconfig", "unable", "could not", "assertion",
                          "parsed_"))
    ]
    if error_lines:
        return "\n".join(error_lines)[:max_len]
    return stderr_text.strip()[-max_len:]


def _wm_position_expr(position: str, pad: float) -> str:
    p  = pad
    p1 = 1.0 - pad
    exprs = {
        "top_left":  f"x=W*{p}:y=H*{p}",
        "top_mid":   f"x=(W-text_w)/2:y=H*{p}",
        "top_right": f"x=W*{p1}-text_w:y=H*{p}",
        "mid_left":  f"x=W*{p}:y=(H-text_h)/2",
        "mid_right": f"x=W*{p1}-text_w:y=(H-text_h)/2",
        "bot_left":  f"x=W*{p}:y=H*{p1}-text_h",
        "bot_right": f"x=W*{p1}-text_w:y=H*{p1}-text_h",
    }
    return exprs.get(position, exprs["bot_right"])


def _build_random_intervals(
    video_duration: float,
    repeat_count: int,
    per_duration: float,
) -> list[tuple[float, float]]:
    """Return a list of (start, end) tuples for non-overlapping watermark windows.

    Strategy
    --------
    1.  Clamp inputs so the request is physically feasible:
        - per_duration can be at most video_duration / repeat_count  (so all
          appearances fit end-to-end with no overlap).
        - repeat_count is reduced to at most floor(video_duration / per_duration)
          if per_duration × repeat_count > video_duration.
    2.  Divide the (clamped) video timeline into `repeat_count` equal sections.
    3.  Inside each section, place the window randomly, ensuring:
        - The window starts at least 0 s into the section (no negative offset).
        - The window ends before the section boundary.
        - A small jitter around the section midpoint is used for natural placement.
    """
    if video_duration <= 0 or repeat_count <= 0 or per_duration <= 0:
        return []

    # ── Feasibility clamp ─────────────────────────────────────────────────────
    max_fits = max(1, int(video_duration / per_duration))
    repeat_count = min(repeat_count, max_fits)

    # Also clamp per_duration so it fits inside one equal section
    section_len = video_duration / repeat_count
    per_duration = min(per_duration, section_len)

    intervals: list[tuple[float, float]] = []
    for i in range(repeat_count):
        sec_start = i * section_len
        sec_end   = sec_start + section_len

        # Available start range inside this section
        latest_start = sec_end - per_duration
        if latest_start < sec_start:
            # Section too short — just start at section begin
            start = sec_start
        else:
            # Jitter: pick randomly between sec_start and latest_start,
            # biased toward the middle third for a natural look.
            mid_lo = sec_start + (section_len - per_duration) * 0.25
            mid_hi = sec_start + (section_len - per_duration) * 0.75
            mid_lo = max(sec_start, min(mid_lo, latest_start))
            mid_hi = max(mid_lo,    min(mid_hi, latest_start))
            start = random.uniform(mid_lo, mid_hi)

        end = start + per_duration
        intervals.append((round(start, 3), round(end, 3)))

    return intervals


class FFmpeg:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path     = ffmpeg_path
        self.ffprobe_path    = ffprobe_path
        self.encode_progress = 0
        self.current_stage   = ""
        self.current_process = None
        self._env            = self._build_env()

    def _build_env(self) -> dict:
        return copy.copy(os.environ)

    def _get_resolution_dimensions(self, resolution_str: str) -> str:
        resolution_map = {
            "1080p": "1920x1080",
            "720p":  "1280x720",
            "480p":  "854x480",
            "360p":  "640x360",
        }
        clean = resolution_str.lower().strip()
        if not clean.endswith("p"):
            clean += "p"
        return resolution_map.get(clean, "1920x1080")

    def _is_mkv(self, path: str) -> bool:
        return os.path.splitext(path)[1].lower() == ".mkv"

    def _subtitle_codec(self, output_path: str) -> str:
        return "copy" if self._is_mkv(output_path) else "mov_text"

    def _container_flags(self, output_path: str) -> list:
        if self._is_mkv(output_path):
            return []
        return ["-movflags", "+faststart"]

    def _append_metadata(self, cmd: list, metadata: dict) -> list:
        if metadata.get("title") and metadata["title"].strip():
            cmd.extend(["-metadata", f"title={metadata['title'].strip()}"])
        if metadata.get("author") and metadata["author"].strip():
            cmd.extend(["-metadata", f"artist={metadata['author'].strip()}"])
        if metadata.get("encoder") and metadata["encoder"].strip():
            cmd.extend(["-metadata", f"encoder={metadata['encoder'].strip()}"])
        return cmd

    def _build_watermark_filter(self, wm: dict, media_info: dict) -> str:
        if not wm or not wm.get("enabled"):
            return ""

        text = wm.get("text", "").strip()
        if not text:
            return ""

        text_escaped = (
            text
            .replace("\\", "\\\\")
            .replace("'",  "\\'")
            .replace(":",  "\\:")
            .replace("[",  "\\[")
            .replace("]",  "\\]")
        )

        color = wm.get("color", "white")
        if color not in ("white", "black", "red", "green", "blue", "yellow"):
            color = "white"

        position = wm.get("position", "bot_right")
        pad_pct  = max(1, min(25, int(wm.get("padding", 7))))
        pos_expr = _wm_position_expr(position, pad_pct / 100.0)

        resolved  = _resolve_font(wm.get("font_path", ""))
        font_part = _fontfile_expr(resolved)

        font_size_expr = str(wm.get("font_size", 24))

        timing_mode    = wm.get("timing_mode", "range")
        video_duration = 0.0
        try:
            video_duration = float(media_info.get("format", {}).get("duration", 0))
        except (TypeError, ValueError):
            video_duration = 0.0

        # ── Build enable= expression ──────────────────────────────────────────
        enable_expr = ""  # empty → always visible

        if timing_mode == "full":
            # No enable= needed — visible for the entire video
            enable_expr = ""

        elif timing_mode == "range":
            # start/end are stored as integer seconds
            start_sec = max(0, int(wm.get("start", 0)))
            end_sec   = int(wm.get("end", 0))
            if end_sec <= start_sec:
                # Degenerate range → fall back to full duration
                end_sec = int(video_duration) if video_duration > 0 else 0
            if not (start_sec == 0 and end_sec == 0):
                enable_expr = f"between(t,{start_sec},{end_sec})"

        elif timing_mode == "random_duration":
            # Multi-appearance: divide video into sections, place one window
            # per section at a random (middle-biased) position.
            per_duration = max(1, int(wm.get("duration", 30)))
            repeat_count = max(1, int(wm.get("repeat_count", 1)))

            intervals = _build_random_intervals(video_duration, repeat_count, per_duration)

            if intervals:
                # FFmpeg enable= uses '+' for boolean OR between conditions
                clauses = [f"between(t,{s},{e})" for s, e in intervals]
                enable_expr = "+".join(clauses)
            else:
                # Fallback: show for full duration if we couldn't compute intervals
                enable_expr = ""

        # ── Assemble drawtext filter ──────────────────────────────────────────
        parts = [f"{font_part}text='{text_escaped}'"]
        parts += [
            f"fontcolor={color}",
            f"fontsize={font_size_expr}",
            pos_expr,
        ]
        if enable_expr:
            parts.append(f"enable='{enable_expr}'")

        return "drawtext=" + ":".join(parts)

    async def probe_media(self, input_path: str) -> dict:
        try:
            process = await asyncio.create_subprocess_exec(
                self.ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                input_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
            stdout, _ = await process.communicate()
            if process.returncode != 0:
                return {}
            return json.loads(stdout.decode("utf-8", errors="ignore") or "{}")
        except Exception:
            return {}

    def build_command(self, input_path: str, output_path: str, settings: dict) -> list:
        input_path  = os.path.abspath(input_path)
        output_path = os.path.abspath(output_path)

        if input_path == output_path:
            raise ValueError("Input and output paths cannot be the same")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        resolution_str  = settings.get("resolution", "1080p")
        metadata        = settings.get("metadata", {})
        processing_mode = settings.get("processing_mode", "encode")
        watermark       = settings.get("watermark")
        media_info      = settings.get("media_info", {})
        audio_codec     = settings.get("audio_codec", "aac")
        audio_bitrate   = settings.get("audio_bitrate", "128k")

        if processing_mode == "metadata_only" or resolution_str == "HDRip":
            cmd = [
                self.ffmpeg_path,
                "-i", input_path,
                "-map", "0",
                "-c", "copy",
                "-map_metadata", "0",
            ]
            cmd.extend(self._container_flags(output_path))
            self._append_metadata(cmd, metadata)
            cmd.extend(["-y", output_path])
            return cmd

        if processing_mode == "rename":
            cmd = [
                self.ffmpeg_path,
                "-i", input_path,
                "-map", "0",
                "-c", "copy",
                "-map_metadata", "0",
            ]
            cmd.extend(self._container_flags(output_path))
            self._append_metadata(cmd, metadata)
            cmd.extend(["-y", output_path])
            return cmd

        dimensions = self._get_resolution_dimensions(resolution_str)
        width, height = dimensions.split("x")

        video_codec = settings.get("codec", "libx264")
        if video_codec not in ("libx264", "libx265", "h264", "h265"):
            video_codec = "libx264"

        # Never upscale: cap each dimension at the source value.
        # The trailing scale ensures even dimensions required by yuv420p.
        scale_pad = (
            f"scale='min({width},iw)':'min({height},ih)'"
            f":force_original_aspect_ratio=decrease"
            f",scale=trunc(iw/2)*2:trunc(ih/2)*2"
        )

        wm_filter = self._build_watermark_filter(watermark, media_info) if watermark else ""
        vf = f"{scale_pad},{wm_filter}" if wm_filter else scale_pad

        cmd = [
            self.ffmpeg_path,
            "-i", input_path,
            "-map", "0:v",  # Map all video streams
            "-map", "0:a",  # Map all audio streams
            "-map", "0:s?", # Map all subtitle streams (if present)
            "-map", "0:d?", # Map all data streams (if present)
            "-map", "0:t?", # Map all attachment streams (if present)
        ]

        # Apply audio settings to ALL audio streams
        if audio_codec == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", audio_codec, "-b:a", audio_bitrate])

        cmd.extend([
            "-c:s", "copy", 
            "-c:d", "copy",
            "-c:t", "copy",  
        ])

        cmd.extend([
            "-c:v", video_codec,
            "-preset", settings.get("preset", "medium"),
            "-crf", str(settings.get("crf", 23)),
            "-vf", vf,
            "-pix_fmt", "yuv420p",
            "-map_metadata", "0",
        ])
        
        if video_codec in ("libx264", "h264"):
            cmd.extend(["-x264-params", "threads=3:lookahead_threads=1:sliced_threads=0"])
        elif video_codec in ("libx265", "h265"):
            cmd.extend(["-x265-params", "pools=3:lookahead-slices=1"])

        cmd.extend(self._container_flags(output_path))
        self._append_metadata(cmd, metadata)
        cmd.extend(["-y", output_path])
        return cmd

    # ── Execute ───────────────────────────────────────────────────────────────

    async def execute(
        self,
        cmd:           list,
        duration_secs: float = 0.0,
        progress_cb=None,
    ) -> tuple[bool, str | None]:
        use_progress = bool(progress_cb and duration_secs > 0.5)

        if use_progress:
            out_file = cmd[-1]
            cmd_run  = list(cmd[:-1]) + ["-progress", "pipe:1", "-nostats", out_file]
        else:
            cmd_run = list(cmd)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_run,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
            self.current_process = process

            try:
                if use_progress:
                    return await self._execute_with_progress(
                        process, cmd, duration_secs, progress_cb
                    )
                else:
                    return await self._execute_simple(process, cmd)

            except asyncio.CancelledError:
                await self._kill_process(process)
                raise

        except (FileNotFoundError, PermissionError, OSError) as e:
            return False, (
                f"Cannot launch FFmpeg ('{self.ffmpeg_path}'): {e}\n"
                "Make sure ffmpeg is on your PATH or in the project bin/ folder."
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return False, f"Unexpected error: {e}"
        finally:
            self.current_process = None

    async def _execute_with_progress(
        self, process, cmd: list, duration_secs: float, progress_cb
    ) -> tuple[bool, str | None]:

        stderr_chunks: list[bytes] = []

        async def _read_stdout():
            try:
                async for raw in process.stdout:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    if key == "out_time_us":
                        try:
                            elapsed_secs = int(val) / 1_000_000
                            pct = min(99.9, elapsed_secs / duration_secs * 100)
                            await progress_cb(pct)
                        except (ValueError, ZeroDivisionError):
                            pass
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        async def _read_stderr():
            try:
                async for raw in process.stderr:
                    stderr_chunks.append(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        t_out = asyncio.create_task(_read_stdout())
        t_err = asyncio.create_task(_read_stderr())

        try:
            await asyncio.gather(t_out, t_err)
        except asyncio.CancelledError:
            t_out.cancel()
            t_err.cancel()
            await asyncio.gather(t_out, t_err, return_exceptions=True)
            raise

        await process.wait()

        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="ignore")
        output_file = cmd[-1]

        if process.returncode != 0:
            print(f"[FFmpeg] Exit code {process.returncode}\n{stderr_text}")
            return False, (
                f"FFmpeg error (code {process.returncode}): "
                f"{_extract_ffmpeg_error(stderr_text)}"
            )

        if not os.path.exists(output_file):
            return False, f"Output file not created: {output_file}"
        if os.path.getsize(output_file) == 0:
            return False, f"Output file is empty: {output_file}"
        try:
            await progress_cb(100.0)
        except Exception:
            pass

        return True, None

    async def _execute_simple(
        self, process, cmd: list
    ) -> tuple[bool, str | None]:
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="ignore")
            print(f"[FFmpeg] Exit code {process.returncode}\n{error_msg}")
            return False, (
                f"FFmpeg error (code {process.returncode}): "
                f"{_extract_ffmpeg_error(error_msg)}"
            )

        output_file = cmd[-1]
        if not os.path.exists(output_file):
            return False, f"Output file not created: {output_file}"
        if os.path.getsize(output_file) == 0:
            return False, f"Output file is empty: {output_file}"

        return True, None

    @staticmethod
    async def _kill_process(process):
        if process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.sleep(0.4)
            if process.returncode is None:
                process.kill()
            await process.wait()
        except Exception:
            pass