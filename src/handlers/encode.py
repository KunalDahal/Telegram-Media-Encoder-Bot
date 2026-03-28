import copy
import os
import re
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
    ".mpeg", ".mpg", ".wmv", ".flv", ".3gp",
}
SUPPORTED_RESOLUTIONS = ["HDRip", "1080p", "720p", "480p"]


# ── Handler setup ─────────────────────────────────────────────────────────────

def setup_encode_handlers(app: Client, task_queue, user_settings):
    @app.on_message(filters.command("encode") & filters.private)
    async def encode_command(client: Client, message: Message):
        await process_encode_command(client, message, task_queue, user_settings)


# ── Filename helpers ──────────────────────────────────────────────────────────

def parse_filename_from_command(command_text: str):
    parts = command_text.split(maxsplit=1)
    if len(parts) < 2:
        return None

    filename_part = parts[1].strip()

    if filename_part.startswith('"') and filename_part.endswith('"'):
        return filename_part[1:-1]
    if filename_part.startswith("'") and filename_part.endswith("'"):
        return filename_part[1:-1]

    return filename_part


def validate_filename_extension(filename: str) -> bool:
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return bool(ext) and ext in ALLOWED_VIDEO_EXTENSIONS


def build_output_filename(filename: str, resolution: str, total_jobs: int) -> str:
    updated = re.sub(r"\{quality\}", resolution, filename, flags=re.IGNORECASE)
    if updated != filename:
        return updated

    updated = re.sub(r"\{audio\}-", f"{resolution}-", filename, flags=re.IGNORECASE)
    if updated != filename:
        return updated

    updated = re.sub(r"\{audio\}", resolution, filename, flags=re.IGNORECASE)
    if updated != filename:
        return updated

    if total_jobs > 1:
        base_name, ext = os.path.splitext(filename)
        return f"{base_name}_{resolution}{ext}"

    return filename


# ── Resolution helpers ────────────────────────────────────────────────────────

def get_selected_resolutions(settings: dict) -> list:
    resolutions = settings.get("resolutions") or [settings.get("resolution", "1080p")]
    normalized = []
    for resolution in resolutions:
        if resolution in SUPPORTED_RESOLUTIONS and resolution not in normalized:
            normalized.append(resolution)

    if not normalized:
        normalized = ["1080p"]

    ordered = [r for r in SUPPORTED_RESOLUTIONS if r in normalized]
    return ordered[:4]


# ── Job builder ───────────────────────────────────────────────────────────────

def build_jobs(
    base_filename: str,
    resolutions: list,
    user_settings_obj,
    base_metadata: dict,
) -> list:
    total_jobs = len(resolutions)
    jobs = []

    for resolution in resolutions:
        effective = user_settings_obj.get_effective_settings(
            resolution,
            {
                "metadata": base_metadata,
                "thumbnail_path": user_settings_obj.data.get("thumbnail_path", ""),
                "send_type": user_settings_obj.data.get("send_type", "media"),
            },
        )

        jobs.append(
            {
                "resolution": resolution,
                "output_filename": build_output_filename(base_filename, resolution, total_jobs),
                "processing_mode": effective.get("processing_mode", "encode"),
                "crf": effective.get("crf"),
                "preset": effective.get("preset"),
                "codec": effective.get("codec"),
                "audio_bitrate": effective.get("audio_bitrate"),
                "metadata": effective.get("metadata", {}),
                "thumbnail_path": effective.get("thumbnail_path", ""),
                "send_type": effective.get("send_type", "media"),
            }
        )

    return jobs


# ── Command handler ───────────────────────────────────────────────────────────

async def process_encode_command(
    client: Client, message: Message, task_queue, user_settings
):
    if not message.reply_to_message:
        await message.reply_text("Reply to a video file.")
        return

    replied = message.reply_to_message
    file_id = None
    original_file_name = None
    file_size = None

    if replied.video:
        file_id = replied.video.file_id
        original_file_name = replied.video.file_name or f"video_{replied.video.file_id[:8]}.mp4"
        file_size = replied.video.file_size

    elif replied.document:
        file_name = replied.document.file_name or ""
        file_ext = os.path.splitext(file_name)[1].lower()

        if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
            await message.reply_text("Invalid file type. Only video files are allowed.")
            return

        file_id = replied.document.file_id
        original_file_name = replied.document.file_name or f"video_{replied.document.file_id[:8]}{file_ext}"
        file_size = replied.document.file_size

    else:
        await message.reply_text("Only video files are allowed.")
        return

    # ── Determine requested output filename ───────────────────────────────────
    if len(message.command) < 2:
        requested_filename = original_file_name
    else:
        requested_filename = parse_filename_from_command(message.text)
        if not requested_filename:
            await message.reply_text("Invalid filename format.")
            return

        if not validate_filename_extension(requested_filename):
            await message.reply_text(
                "Provide a valid video filename.\n"
                "Example: `/encode my_video.mp4` or `/encode \"My Show [{quality}] Sub.mkv\"`"
            )
            return

    # ── Build jobs ────────────────────────────────────────────────────────────
    settings_obj = user_settings(message.from_user.id)
    settings = copy.deepcopy(settings_obj.get())

    selected_resolutions = get_selected_resolutions(settings)
    base_metadata = settings.get("metadata", {})

    jobs = build_jobs(requested_filename, selected_resolutions, settings_obj, base_metadata)

    first_job = jobs[0]
    created_at = datetime.utcnow().isoformat()

    task_data = {
        "user_id": message.from_user.id,
        "first_name": message.from_user.first_name,
        "username": message.from_user.username,
        "chat_id": message.chat.id,
        "message_id": message.id,
        "file_id": file_id,
        "original_file_name": original_file_name,
        "requested_output_filename": requested_filename,
        "output_filename": first_job["output_filename"],
        "resolution": first_job["resolution"],
        "created_at": created_at,
        "file_size": file_size,
        "send_type": settings["send_type"],
        "resolutions": selected_resolutions,
        "jobs": jobs,
        "total_jobs": len(jobs),
        "current_job": 0,
        "current_stage": "queued",
        "thumbnail_path": settings.get("thumbnail_path", ""),
        "watermark": settings_obj.get_watermark(),
        "settings_snapshot": settings,
    }

    task_id = task_queue.create_task(task_data)

    position = task_queue.get_queue_position(task_id)
    total_in_queue = len(task_queue.queue)
    resolution_text = " → ".join(selected_resolutions)

    job_lines = []
    for job in jobs:
        job_lines.append(f"  `{job['output_filename']}`")

    jobs_text = "\n".join(job_lines)

    await message.reply_text(
        f"**Task queued** `{task_id}` · [{position}/{total_in_queue}]\n\n"
        f"**Pipeline:** `{resolution_text}`\n"
        f"**Jobs ({len(jobs)}):**\n{jobs_text}\n\n"
        f"**Please Wait Patiently, The files will be delivered soon...**"
    )