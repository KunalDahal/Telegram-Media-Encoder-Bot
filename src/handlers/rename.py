# src/handlers/rename.py

import copy
import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
    ".mpeg", ".mpg", ".wmv", ".flv", ".3gp",
}


# ── Filename helpers ──────────────────────────────────────────────────────────

def _parse_filename(command_text: str):
    parts = command_text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    filename_part = parts[1].strip()
    if filename_part.startswith('"') and filename_part.endswith('"'):
        return filename_part[1:-1]
    if filename_part.startswith("'") and filename_part.endswith("'"):
        return filename_part[1:-1]
    return filename_part


def _valid_extension(filename: str) -> bool:
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return bool(ext) and ext in ALLOWED_VIDEO_EXTENSIONS


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


# ── /rename command processing ────────────────────────────────────────────────

async def process_rename_command(client: Client, message: Message, task_queue, user_settings):
    user_id = message.from_user.id

    if not message.reply_to_message:
        await message.reply_text(
            'Reply to a video.\nUse: /rename "movie.mp4"'
        )
        return

    replied = message.reply_to_message
    file_id = None
    original_file_name = None
    file_size = None

    if replied.video:
        file_id            = replied.video.file_id
        original_file_name = replied.video.file_name or f"video_{replied.video.file_id[:8]}.mp4"
        file_size          = replied.video.file_size

    elif replied.document:
        file_name = replied.document.file_name or ""
        file_ext  = os.path.splitext(file_name)[1].lower()
        if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
            await message.reply_text(
                f"Only video files are allowed.\n"
                f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
            )
            return
        file_id            = replied.document.file_id
        original_file_name = replied.document.file_name or f"video_{replied.document.file_id[:8]}{file_ext}"
        file_size          = replied.document.file_size

    else:
        await message.reply_text(
            'Reply to a video.\nUse: /rename "movie.mp4"'
        )
        return

    if len(message.command) < 2:
        await message.reply_text(
            'Filename required.\nUse: /rename "movie.mp4"'
        )
        return

    requested_filename = _parse_filename(message.text)
    if not requested_filename:
        await message.reply_text("Invalid filename format.")
        return

    if not _valid_extension(requested_filename):
        await message.reply_text(
            f"Invalid filename. Use: /rename \"movie.mp4\"\n"
            f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    settings_obj = user_settings(user_id)
    settings     = copy.deepcopy(settings_obj.get())
    watermark    = settings_obj.get_watermark()

    job = {
        "resolution":      "rename",
        "output_filename": requested_filename,
        "processing_mode": "rename",
        "audio_bitrate":   None,
        "metadata":        settings.get("metadata", {}),
        "thumbnail_path":  settings.get("thumbnail_path", ""),
        "send_type":       settings.get("send_type", "media"),
    }

    task_data = {
        "user_id":                   user_id,
        "first_name":                message.from_user.first_name,
        "username":                  message.from_user.username,
        "chat_id":                   message.chat.id,
        "message_id":                message.id,
        "file_id":                   file_id,
        "original_file_name":        original_file_name,
        "requested_output_filename": requested_filename,
        "output_filename":           requested_filename,
        "resolution":                "rename",
        "created_at":                datetime.utcnow().isoformat(),
        "file_size":                 file_size,
        "send_type":                 settings.get("send_type", "media"),
        "resolutions":               ["rename"],
        "jobs":                      [job],
        "total_jobs":                1,
        "current_job":               0,
        "current_stage":             "queued",
        "thumbnail_path":            settings.get("thumbnail_path", ""),
        "watermark":                 watermark,
        "settings_snapshot":         settings,
    }

    task_id  = task_queue.create_task(task_data)
    position = task_queue.get_queue_position(task_id)

    await message.reply_text(
        f"Task `{requested_filename}` queued at position **[{position}]**\n"
        f"Task ID : `{task_id}`\n"
        f"**Output file will be delivered to your DM.** Please wait patiently.\n"
    )


def setup_rename_handler(app: Client, task_queue, user_settings, config):
    allowed_group_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["r", "rename"]) & allowed_group_filter)
    async def rename_command(client: Client, message: Message):
        if not await _check_access(client, message, config):
            return
        await process_rename_command(client, message, task_queue, user_settings)