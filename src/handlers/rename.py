import copy
import os
import re
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

_SUPPORTED_PLACEHOLDERS = {"season", "episode"}
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ── Guard helpers ─────────────────────────────────────────────────────────────

async def fetch_media_group(client: Client, chat_id: int, replied: Message) -> list:
    media_group_id = replied.media_group_id
    start_id = max(1, replied.id - 3)
    end_id   = replied.id + 20
    ids      = list(range(start_id, end_id + 1))
    try:
        messages = await client.get_messages(chat_id, ids)
    except Exception as exc:
        logger.error(f"[encode] fetch_media_group error: {exc}")
        return []
    group = [
        m for m in messages
        if m
        and not getattr(m, "empty", True)
        and m.media_group_id == media_group_id
        and (m.video or m.document)
    ]
    group.sort(key=lambda m: m.id)
    return group


async def _check_access(client, message: Message, config) -> bool:
    user_id = message.from_user.id
    if user_id not in config.admin_ids:
        await message.reply_text("Dukhi Atma!😔")
        return False
    try:
        await client.get_chat(user_id)
    except Exception:
        await message.reply_text(
            "⚠️ Please start the bot in DM before giving tasks here."
        )
        return False
    return True


# ── File helpers ──────────────────────────────────────────────────────────────

def _valid_extension(filename: str) -> bool:
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return bool(ext) and ext in ALLOWED_VIDEO_EXTENSIONS


def _file_info(media_msg: Message):
    """Return (file_id, original_file_name, file_size) from a media message."""
    if media_msg.video:
        v = media_msg.video
        return (
            v.file_id,
            v.file_name or f"video_{v.file_id[:8]}.mp4",
            v.file_size,
        )
    d = media_msg.document
    ext = os.path.splitext(d.file_name or "")[1].lower() or ".mkv"
    return (
        d.file_id,
        d.file_name or f"video_{d.file_id[:8]}{ext}",
        d.file_size,
    )


def _is_video_message(msg: Message) -> bool:
    if msg.video:
        return True
    if msg.document:
        ext = os.path.splitext(msg.document.file_name or "")[1].lower()
        return ext in ALLOWED_VIDEO_EXTENSIONS
    return False


# ── Command parsing ───────────────────────────────────────────────────────────

def _parse_rename_command(message_text: str):
    text = re.sub(r"^/\S+\s*", "", message_text).strip()

    is_batch = False
    if text.startswith("-b"):
        rest = text[2:].lstrip()
        if not rest:
            return True, None, "Please provide a filename template after `-b`."
        is_batch = True
        text = rest

    if not text:
        return is_batch, None, "Please provide a filename."
    if (text.startswith('"') and text.endswith('"')) or \
       (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]

    if not text:
        return is_batch, None, "Filename cannot be empty."

    return is_batch, text, None


def _validate_batch_template(template: str):
    found = {m.group(1) for m in _PLACEHOLDER_RE.finditer(template)}
    unsupported = found - _SUPPORTED_PLACEHOLDERS
    if unsupported:
        bad = ", ".join(f"`{{{p}}}`" for p in sorted(unsupported))
        return False, (
            f"Unsupported placeholder(s): {bad}\n"
            "Only `{season}` and `{episode}` are allowed in batch rename filenames."
        )
    return True, None


def _resolve_template(template: str, season: int, episode: int) -> str:
    filename = template
    filename = filename.replace("{season}",  f"{season:02d}")
    filename = filename.replace("{episode}", f"{episode:02d}")
    return filename


# ── Task builder ──────────────────────────────────────────────────────────────

def _build_task(
    *,
    message: Message,
    file_id: str,
    original_file_name: str,
    file_size: int,
    output_filename: str,
    settings: dict,
    watermark: dict,
    created_at: str,
    batch: bool = False,
) -> dict:
    job = {
        "resolution":      "rename",
        "output_filename": output_filename,
        "processing_mode": "rename",
        "audio_bitrate":   None,
        "metadata":        settings.get("metadata", {}),
        "thumbnail_path":  settings.get("thumbnail_path", ""),
        "send_type":       settings.get("send_type", "media"),
    }
    return {
        "user_id":                   message.from_user.id,
        "first_name":                message.from_user.first_name,
        "username":                  message.from_user.username,
        "chat_id":                   message.chat.id,
        "message_id":                message.id,
        "file_id":                   file_id,
        "original_file_name":        original_file_name,
        "requested_output_filename": output_filename,
        "output_filename":           output_filename,
        "resolution":                "rename",
        "created_at":                created_at,
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
        "batch_rename":              batch,
    }


# ── Single rename ─────────────────────────────────────────────────────────────

async def _process_single_rename(
    client: Client,
    message: Message,
    filename: str,
    task_queue,
    user_settings,
):
    if not message.reply_to_message:
        await message.reply_text(
            'Reply to a video file.\nUsage: `/rename "movie.mkv"`'
        )
        return

    replied = message.reply_to_message

    if not _is_video_message(replied):
        await message.reply_text(
            f"Only video files are supported.\n"
            f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    if not _valid_extension(filename):
        await message.reply_text(
            f"Invalid file extension.\n"
            f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    user_id      = message.from_user.id
    settings_obj = user_settings(user_id)
    settings     = copy.deepcopy(settings_obj.get())
    watermark    = settings_obj.get_watermark()

    file_id, original_file_name, file_size = _file_info(replied)
    created_at = datetime.utcnow().isoformat()

    task_data = _build_task(
        message=message,
        file_id=file_id,
        original_file_name=original_file_name,
        file_size=file_size,
        output_filename=filename,
        settings=settings,
        watermark=watermark,
        created_at=created_at,
        batch=False,
    )

    task_id  = task_queue.create_task(task_data)
    position = task_queue.get_queue_position(task_id)

    wm     = watermark or {}
    mode   = (
        "rename + watermark + metadata"
        if wm.get("enabled") and wm.get("text")
        else "rename + metadata"
    )

    await message.reply_text(
        f"Task `{filename}` queued at position **[{position}]**\n"
        f"Task ID : `{task_id}`\n"
        f"**Mode:** {mode}\n"
        f"**Output will be delivered to your DM.** Please wait patiently."
    )


# ── Batch rename ──────────────────────────────────────────────────────────────

async def _process_batch_rename(
    client: Client,
    message: Message,
    template: str,
    task_queue,
    user_settings,
):
    if not message.reply_to_message:
        await message.reply_text(
            "Reply to the **first** file of a media group (album).\n\n"
            "Usage: `/rename -b [S{season}-E{episode}] Show Name.mkv`"
        )
        return

    replied = message.reply_to_message

    if not replied.media_group_id:
        await message.reply_text(
            "The replied message is not part of a media group (album).\n"
            "Send your files together as an album, then reply to the first one."
        )
        return
    ok, err = _validate_batch_template(template)
    if not ok:
        await message.reply_text(f"❌ {err}")
        return

    if not _valid_extension(template):
        await message.reply_text(
            f"Invalid file extension in template.\n"
            f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    user_id      = message.from_user.id
    settings_obj = user_settings(user_id)
    settings     = copy.deepcopy(settings_obj.get())
    watermark    = settings_obj.get_watermark()

    season        = int(settings.get("default_season",        1))
    start_episode = int(settings.get("default_start_episode", 1))

    status_msg  = await message.reply_text("⏳ Fetching media group…")
    media_group = await fetch_media_group(client, message.chat.id, replied)

    if not media_group:
        await status_msg.edit_text(
            "Could not find any media in the album.\n"
            "Make sure you replied to the first file of the group."
        )
        return
    valid_files: list[Message] = []
    skipped = 0
    for mg_msg in media_group:
        if _is_video_message(mg_msg):
            valid_files.append(mg_msg)
        else:
            skipped += 1

    if not valid_files:
        await status_msg.edit_text(
            f"No supported video files found in the album.\n"
            f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    created_at = datetime.utcnow().isoformat()
    task_ids:  list[str] = []
    positions: list[int] = []
    episodes:  list[int] = []

    for index, mg_msg in enumerate(valid_files):
        episode = start_episode + index
        episodes.append(episode)

        output_filename = _resolve_template(template, season, episode)
        file_id, original_file_name, file_size = _file_info(mg_msg)

        task_data = _build_task(
            message=message,
            file_id=file_id,
            original_file_name=original_file_name,
            file_size=file_size,
            output_filename=output_filename,
            settings=settings,
            watermark=watermark,
            created_at=created_at,
            batch=True,
        )

        task_id  = task_queue.create_task(task_data)
        position = task_queue.get_queue_position(task_id)
        task_ids.append(task_id)
        positions.append(position)

    # Summary
    ep_start = f"{episodes[0]:02d}"
    ep_end   = f"{episodes[-1]:02d}"
    pos_min  = min(positions)
    pos_max  = max(positions)
    pos_text = f"[{pos_min}]" if pos_min == pos_max else f"[{pos_min} – {pos_max}]"

    wm     = watermark or {}
    mode   = (
        "rename + watermark + metadata"
        if wm.get("enabled") and wm.get("text")
        else "rename + metadata"
    )

    lines = [
        f"Queued **{len(valid_files)}** rename task(s) successfully.\n",
        f"**Season:** {season:02d}",
        f"**Episodes:** {ep_start} → {ep_end}",
        f"**Mode:** {mode}",
        f"**Queue position(s):** {pos_text}",
    ]
    if skipped:
        lines.append(f"**Skipped:** {skipped} non-video file(s)")
    lines.append("\n**Output will be delivered to your DM.** Please wait patiently.")

    await status_msg.edit_text("\n".join(lines))


# ── Entry point ───────────────────────────────────────────────────────────────

async def process_rename_command(
    client: Client,
    message: Message,
    task_queue,
    user_settings,
):
    is_batch, filename, parse_error = _parse_rename_command(message.text)

    if parse_error:
        await message.reply_text(
            f"❌ {parse_error}\n\n"
            "Usage:\n"
            "  Single: `/rename movie.mkv`\n"
            "  Batch:  `/rename -b [S{season}-E{episode}] Show.mkv`"
        )
        return

    if is_batch:
        await _process_batch_rename(client, message, filename, task_queue, user_settings)
    else:
        await _process_single_rename(client, message, filename, task_queue, user_settings)


# ── Handler registration ──────────────────────────────────────────────────────

def setup_rename_handler(app: Client, task_queue, user_settings, config):
    allowed_group_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["r", "rename"]) & allowed_group_filter)
    async def rename_command(client: Client, message: Message):
        if not await _check_access(client, message, config):
            return
        await process_rename_command(client, message, task_queue, user_settings)