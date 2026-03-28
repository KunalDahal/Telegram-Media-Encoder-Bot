import asyncio
import json
import os


class FFmpeg:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        # Allow explicit binary paths for environments where ffmpeg is not on PATH
        # e.g. FFmpeg(ffmpeg_path=r"C:\ffmpeg\bin\ffmpeg.exe")
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.encode_progress = 0
        self.current_stage = ""
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
        """
        MKV supports most subtitle formats natively via stream copy.
        MP4 requires mov_text (only works with SRT/ASS converted subs).
        Using 'copy' for MKV and 'mov_text' for MP4 prevents codec mismatch errors.
        """
        return "copy" if self._is_mkv(output_path) else "mov_text"

    def _container_flags(self, output_path: str) -> list:
        """
        -movflags +faststart is an MP4-only optimisation.
        MKV does not support it and FFmpeg will error out if it is passed.
        """
        if self._is_mkv(output_path):
            return []
        return ["-movflags", "+faststart"]

    def _append_metadata(self, cmd: list, metadata: dict) -> list:
        if metadata.get("title") and metadata["title"].strip():
            title = metadata["title"].strip()
            cmd.extend(["-metadata", f"title={title}"])

        if metadata.get("author") and metadata["author"].strip():
            author = metadata["author"].strip()
            cmd.extend(["-metadata", f"artist={author}"])

        if metadata.get("encoder") and metadata["encoder"].strip():
            encoder = metadata["encoder"].strip()
            cmd.extend(["-metadata", f"encoder={encoder}"])

        return cmd

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

        resolution_str   = settings.get("resolution", "1080p")
        metadata         = settings.get("metadata", {})
        processing_mode  = settings.get("processing_mode", "encode")

        # ── HDRip / metadata-only: stream-copy, just rewrite tags ────────────
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
        dimensions  = self._get_resolution_dimensions(resolution_str)
        width, height = dimensions.split("x")

        codec = settings.get("codec", "libx264")
        if codec not in ("libx264", "libx265", "h264", "h265"):
            codec = "libx264"

        sub_codec = self._subtitle_codec(output_path)

        cmd = [
            self.ffmpeg_path,
            "-i", input_path,
            "-map", "0",
            "-c", "copy",           # default: copy all streams
            "-c:v", codec,          # override: re-encode video
            "-preset", settings.get("preset", "medium"),
            "-crf", str(settings.get("crf", 23)),
            "-vf", (
                f"scale={dimensions}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            ),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",          # override: re-encode audio to AAC
            "-b:a", settings.get("audio_bitrate", "128k"),
            "-c:s", sub_codec,      # container-aware subtitle handling
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
                    # Capture more stderr so the real error is visible in logs
                    error_msg = stderr.decode("utf-8", errors="ignore")
                    # Print full error to console for debugging
                    print(f"[FFmpeg] Exit code {process.returncode}\n{error_msg}")
                    # Return a trimmed version to the caller
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