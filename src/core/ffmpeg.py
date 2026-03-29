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


def _cpu_thread_limit(max_cpu_pct: float = 75.0) -> int:
    """
    Return the number of FFmpeg threads that keeps total CPU usage at or
    below max_cpu_pct of all logical cores combined.

    Formula:  threads = floor(cpu_count * max_cpu_pct / 100)
    Always returns at least 1.
    """
    cpu_count = os.cpu_count() or 1
    threads   = math.floor(cpu_count * max_cpu_pct / 100.0)
    return max(1, threads)


# Pre-compute once at import time so there is no per-call overhead.
_FFMPEG_THREADS = _cpu_thread_limit(75.0)


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

        if timing_mode == "full":
            start_sec = 0
            end_sec   = 0
        elif timing_mode == "random_duration":
            duration  = max(1, int(wm.get("duration", 30)))
            if video_duration > 0 and duration < video_duration:
                start_sec = random.randint(0, int(video_duration - duration))
            else:
                start_sec = 0
            end_sec = start_sec + duration
        else:
            start_sec = max(0, int(wm.get("start", 0)))
            end_sec   = int(wm.get("end", 0))
            if end_sec <= start_sec:
                end_sec = int(video_duration) if video_duration > 0 else 0

        parts = [f"{font_part}text='{text_escaped}'"]
        parts += [
            f"fontcolor={color}",
            f"fontsize={font_size_expr}",
            pos_expr,
        ]
        if not (start_sec == 0 and end_sec == 0):
            parts.append(f"enable='between(t,{start_sec},{end_sec})'")

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
                "-threads", str(_FFMPEG_THREADS),
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
            wm_filter = self._build_watermark_filter(watermark, media_info) if watermark else ""
            if wm_filter:
                source_codec = "libx264"
                try:
                    for stream in media_info.get("streams", []):
                        if stream.get("codec_type") == "video":
                            cn = stream.get("codec_name", "")
                            source_codec = "libx265" if ("265" in cn or "hevc" in cn) else "libx264"
                            break
                except Exception:
                    source_codec = "libx264"

                sub_codec = self._subtitle_codec(output_path)
                cmd = [
                    self.ffmpeg_path,
                    "-threads", str(_FFMPEG_THREADS),
                    "-i", input_path,
                    "-map", "0:v",
                    "-map", "0:a",
                    "-map", "0:s?",
                    "-map", "0:t?",
                    "-c:a", "copy",
                    "-c:s", sub_codec,
                    "-c:t", "copy",
                    "-c:v", source_codec,
                    "-crf", "18",
                    "-preset", "medium",
                    "-threads", str(_FFMPEG_THREADS),
                    "-vf", wm_filter,
                    "-pix_fmt", "yuv420p",
                    "-map_metadata", "0",
                ]
            else:
                cmd = [
                    self.ffmpeg_path,
                    "-threads", str(_FFMPEG_THREADS),
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

        sub_codec = self._subtitle_codec(output_path)

        scale_pad = (
            f"scale={dimensions}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )

        wm_filter = self._build_watermark_filter(watermark, media_info) if watermark else ""
        vf = f"{scale_pad},{wm_filter}" if wm_filter else scale_pad

        cmd = [
            self.ffmpeg_path,
            "-threads", str(_FFMPEG_THREADS),
            "-i", input_path,
            "-map", "0:v",
            "-map", "0:a",
            "-map", "0:s?",
            "-map", "0:t?",
        ]

        if audio_codec == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", audio_codec, "-b:a", audio_bitrate])

        cmd.extend([
            "-c:v", video_codec,
            "-preset", settings.get("preset", "medium"),
            "-crf", str(settings.get("crf", 23)),
            "-threads", str(_FFMPEG_THREADS),
            "-vf", vf,
            "-pix_fmt", "yuv420p",
            "-c:s", sub_codec,
            "-c:t", "copy",
            "-map_metadata", "0",
        ])

        cmd.extend(self._container_flags(output_path))
        self._append_metadata(cmd, metadata)
        cmd.extend(["-y", output_path])
        return cmd

    async def execute(self, cmd: list):
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
            self.current_process = process

            try:
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode("utf-8", errors="ignore")
                    print(f"[FFmpeg] Exit code {process.returncode}\n{error_msg}")
                    return False, f"FFmpeg error (code {process.returncode}): {_extract_ffmpeg_error(error_msg)}"

                output_file = cmd[-1]
                if not os.path.exists(output_file):
                    return False, f"Output file not created: {output_file}"
                if os.path.getsize(output_file) == 0:
                    return False, f"Output file is empty: {output_file}"
                return True, None

            except asyncio.CancelledError:
                if self.current_process and self.current_process.returncode is None:
                    try:
                        self.current_process.terminate()
                        await asyncio.sleep(0.5)
                        if self.current_process.returncode is None:
                            self.current_process.kill()
                        await self.current_process.wait()
                    except Exception:
                        pass
                raise

        except (FileNotFoundError, PermissionError, OSError) as e:
            return False, (
                f"Cannot launch FFmpeg ('{self.ffmpeg_path}'): {e}\n"
                "Make sure ffmpeg is on your system PATH or in the project bin/ folder."
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return False, f"Unexpected error: {e}"
        finally:
            self.current_process = None