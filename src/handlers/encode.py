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


# ── Guard helpers ─────────────────────────────────────────────────────────────

async def _check_access(client, message: Message, config) -> bool:
    user_id = message.from_user.id

    if user_id not in config.admin_ids:
        await message.reply_text("Dukhi Atma!😔")
        return False

    try:
        await client.get_chat(user_id)
    except Exception:
        bot_username = (await client.get_me()).username
        await message.reply_text(
            f"⚠️ Please start the bot in DM before giving tasks here.\n",
        )
        return False

    return True


def setup_encode_handlers(app: Client, task_queue, user_settings, config):

    allowed_group_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["e", "encode"]) & allowed_group_filter)
    async def encode_command(client: Client, message: Message):
        if not await _check_access(client, message, config):
            return
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


def has_quality_placeholder(filename: str) -> bool:
    return bool(re.search(r"\{quality\}", filename, re.IGNORECASE))


def build_output_filename(filename: str, resolution: str, total_jobs: int) -> str:
    return re.sub(r"\{quality\}", resolution, filename, flags=re.IGNORECASE)


def get_selected_resolutions(settings: dict) -> list:
    resolutions = settings.get("resolutions") or [settings.get("resolution", "1080p")]
    normalized = []
    for resolution in resolutions:
        if resolution in SUPPORTED_RESOLUTIONS and resolution not in normalized:
            normalized.append(resolution)
    if not normalized:
        normalized = ["1080p"]
    return [r for r in SUPPORTED_RESOLUTIONS if r in normalized][:4]


def build_jobs(base_filename, resolutions, user_settings_obj, base_metadata):
    total_jobs = len(resolutions)
    jobs = []
    for resolution in resolutions:
        effective = user_settings_obj.get_effective_settings(
            resolution,
            {
                "metadata":       base_metadata,
                "thumbnail_path": user_settings_obj.data.get("thumbnail_path", ""),
                "send_type":      user_settings_obj.data.get("send_type", "media"),
            },
        )
        jobs.append({
            "resolution":      resolution,
            "output_filename": build_output_filename(base_filename, resolution, total_jobs),
            "processing_mode": effective.get("processing_mode", "encode"),
            "crf":             effective.get("crf"),
            "preset":          effective.get("preset"),
            "codec":           effective.get("codec"),
            "audio_bitrate":   effective.get("audio_bitrate"),
            "metadata":        effective.get("metadata", {}),
            "thumbnail_path":  effective.get("thumbnail_path", ""),
            "send_type":       effective.get("send_type", "media"),
        })
    return jobs


# ── /encode ───────────────────────────────────────────────────────────────────

async def process_encode_command(client: Client, message: Message, task_queue, user_settings):
    command_name = "encode"
    user_id = message.from_user.id

    if not message.reply_to_message:
        await message.reply_text(
            f'Reply to a video.\nUse: /{command_name} "movie {{quality}}.mp4"'
        )
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
        file_ext  = os.path.splitext(file_name)[1].lower()
        if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
            await message.reply_text(
                f"Only video files allowed.\n"
                f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
            )
            return
        file_id = replied.document.file_id
        original_file_name = replied.document.file_name or f"video_{replied.document.file_id[:8]}{file_ext}"
        file_size = replied.document.file_size

    else:
        await message.reply_text(
            f'Reply to a video.\nUse: /{command_name} "movie.mp4"'
        )
        return

    if len(message.command) < 2:
        await message.reply_text(
            f'Filename required.\nUse: /{command_name} "movie {{quality}}.mp4"'
        )
        return

    requested_filename = parse_filename_from_command(message.text)
    if not requested_filename:
        await message.reply_text("Invalid filename format.")
        return

    if not validate_filename_extension(requested_filename):
        await message.reply_text(
            f'Invalid filename.\nUse: /{command_name} "movie.mp4"\n'
            f'Allowed: {", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))}'
        )
        return

    if not has_quality_placeholder(requested_filename):
        await message.reply_text(
            f'Missing {{quality}}.\nUse: /{command_name} "Show - S01E01 {{quality}}.mkv"'
        )
        return

    settings_obj = user_settings(user_id)
    settings     = copy.deepcopy(settings_obj.get())

    selected_resolutions = get_selected_resolutions(settings)
    base_metadata        = settings.get("metadata", {})
    jobs                 = build_jobs(requested_filename, selected_resolutions, settings_obj, base_metadata)

    first_job  = jobs[0]
    created_at = datetime.utcnow().isoformat()

    task_data = {
        "user_id":                   user_id,
        "first_name":                message.from_user.first_name,
        "username":                  message.from_user.username,
        "chat_id":                   message.chat.id,
        "message_id":                message.id,
        "file_id":                   file_id,
        "original_file_name":        original_file_name,
        "requested_output_filename": requested_filename,
        "output_filename":           first_job["output_filename"],
        "resolution":                first_job["resolution"],
        "created_at":                created_at,
        "file_size":                 file_size,
        "send_type":                 settings["send_type"],
        "resolutions":               selected_resolutions,
        "jobs":                      jobs,
        "total_jobs":                len(jobs),
        "current_job":               0,
        "current_stage":             "queued",
        "thumbnail_path":            settings.get("thumbnail_path", ""),
        "watermark":                 settings_obj.get_watermark(),
        "settings_snapshot":         settings,
    }

    task_id  = task_queue.create_task(task_data)
    position = task_queue.get_queue_position(task_id)
    resolution_text = " -> ".join(selected_resolutions)

    await message.reply_text(
        f"Task `{requested_filename}` queued at position **[{position}]**\n"
        f"Task ID : `{task_id}`\n"
        f"**Output file will be delivered to your DM.** Please wait patiently.\n"
    )