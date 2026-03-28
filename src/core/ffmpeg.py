import asyncio
import json
import os
import random

# FFmpeg drawtext position expressions (relative, safe-padded at ~7% from edges)
_WM_POSITION_EXPR = {
    "top_left":  "x=W*0.07:y=H*0.07",
    "top_mid":   "x=(W-text_w)/2:y=H*0.07",
    "top_right": "x=W*0.93-text_w:y=H*0.07",
    "mid_left":  "x=W*0.07:y=(H-text_h)/2",
    "mid_right": "x=W*0.93-text_w:y=(H-text_h)/2",
    "bot_left":  "x=W*0.07:y=H*0.93-text_h",
    "bot_right": "x=W*0.93-text_w:y=H*0.93-text_h",
}


class FFmpeg:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path  = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.encode_progress = 0
        self.current_stage   = ""
        self.current_process = None

    # ── Internal helpers ──────────────────────────────────────────────────────

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
        )

        color    = wm.get("color", "white")
        if color not in ("white", "black"):
            color = "white"

        position = wm.get("position", "bot_right")
        pos_expr = _WM_POSITION_EXPR.get(position, _WM_POSITION_EXPR["bot_right"])

        font_path = wm.get("font_path", "")
        if font_path and os.path.exists(font_path):
            fp = font_path.replace("\\", "/").replace(":", "\\:")
            font_part = f"fontfile='{fp}'"
        else:
            font_part = ""

        font_size_expr = "h*0.07"

        timing_mode = wm.get("timing_mode", "range")
        video_duration = 0.0
        try:
            fmt = media_info.get("format", {})
            video_duration = float(fmt.get("duration", 0))
        except (TypeError, ValueError):
            video_duration = 0.0

        if timing_mode == "random_duration":
            duration = max(1, int(wm.get("duration", 30)))
            if video_duration > 0 and duration < video_duration:
                max_start = int(video_duration - duration)
                start_sec = random.randint(0, max_start)
            else:
                start_sec = 0
            end_sec = start_sec + duration
        else:
            start_sec = max(0, int(wm.get("start", 0)))
            end_sec   = int(wm.get("end", 0))
            if end_sec <= start_sec:
                end_sec = int(video_duration) if video_duration > 0 else 0

        if start_sec == 0 and end_sec == 0:
            enable_expr = ""
        else:
            enable_expr = f":enable='between(t,{start_sec},{end_sec})'"

        parts = [f"text='{text_escaped}'"]
        if font_part:
            parts.append(font_part)
        parts += [
            f"fontcolor={color}",
            f"fontsize={font_size_expr}",
            pos_expr,
        ]
        if enable_expr:
            parts.append(enable_expr.lstrip(":"))

        return "drawtext=" + ":".join(parts)

    # ── Public API ────────────────────────────────────────────────────────────

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

        # ── Full encode ───────────────────────────────────────────────────────
        dimensions = self._get_resolution_dimensions(resolution_str)
        width, height = dimensions.split("x")

        codec = settings.get("codec", "libx264")
        if codec not in ("libx264", "libx265", "h264", "h265"):
            codec = "libx264"

        sub_codec = self._subtitle_codec(output_path)

        scale_pad = (
            f"scale={dimensions}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )

        wm_filter = self._build_watermark_filter(watermark, media_info) if watermark else ""
        vf = f"{scale_pad},{wm_filter}" if wm_filter else scale_pad

        cmd = [
            self.ffmpeg_path,
            "-i", input_path,
            "-map", "0",
            "-c", "copy",
            "-c:v", codec,
            "-preset", settings.get("preset", "medium"),
            "-crf", str(settings.get("crf", 23)),
            "-vf", vf,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", settings.get("audio_bitrate", "128k"),
            "-c:s", sub_codec,
            "-map_metadata", "0",
        ]

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
            )
            self.current_process = process

            try:
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode("utf-8", errors="ignore")
                    print(f"[FFmpeg] Exit code {process.returncode}\n{error_msg}")
                    trimmed = error_msg.strip()[-800:] if len(error_msg) > 800 else error_msg.strip()
                    return False, f"FFmpeg error (code {process.returncode}): {trimmed}"

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

        except FileNotFoundError:
            return False, (
                f"FFmpeg binary not found: '{self.ffmpeg_path}'. "
                "Add it to your PATH or pass the full path when constructing FFmpeg()."
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return False, f"Unexpected error: {e}"
        finally:
            self.current_process = None