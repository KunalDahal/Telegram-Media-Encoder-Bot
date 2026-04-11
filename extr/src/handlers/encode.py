import copy
import os
import re
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message
import logging

logger = logging.getLogger(__name__)

ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
    ".mpeg", ".mpg", ".wmv", ".flv", ".3gp",
}
SUPPORTED_RESOLUTIONS = ["1080p", "720p", "480p"]

# ── Access guard ──────────────────────────────────────────────────────────────

async def _check_access(client, message: Message, config) -> bool:
    user_id = message.from_user.id
    if user_id not in config.admin_ids:
        await message.reply_text("Dukhi Atma!😔")
        return False
    try:
        await client.get_chat(user_id)
    except Exception:
        bot = await client.get_me()
        await message.reply_text(
            f"⚠️ Please start the bot in DM first.\n"
            f"👉 @{bot.username} — press **Start**, then try again."
        )
        return False
    return True


# ── Command parser ────────────────────────────────────────────────────────────

def _parse_encode_command(text: str):
    text = re.sub(r"^/\S+\s*", "", text).strip()

    batch       = False
    batch_count = None

    if text.startswith("-b"):
        batch = True
        rest  = text[2:].lstrip()
        m     = re.match(r'^(\d+)\s+(.*)', rest, re.DOTALL)
        if m:
            n = int(m.group(1))
            if n < 2:
                return False, None, None, "`-b N` requires N ≥ 2."
            batch_count = n
            template    = m.group(2).strip()
        else:
            template = rest.strip()
    else:
        template = text.strip()

    if not template:
        return False, None, None, "Please provide a filename template."

    dummy = re.sub(r"\{[^}]+\}", "X", template)
    ext   = os.path.splitext(dummy)[1].lower()
    if not ext or ext not in ALLOWED_VIDEO_EXTENSIONS:
        return False, None, None, (
            f"Template must end with a valid video extension (.mkv, .mp4, etc.).\n"
            f"Got: `{template}`"
        )

    if "{quality}" not in template:
        return False, None, None, (
            "Template must contain `{quality}` so the resolution is filled in automatically.\n"
            "Example: `[S1-03] My Show [{quality}] [SUB] @Source.mkv`"
        )

    return batch, batch_count, template, None


# ── Filename / job helpers ────────────────────────────────────────────────────

def get_selected_resolutions(settings: dict) -> list:
    resolutions = settings.get("resolutions") or [settings.get("resolution", "1080p")]
    normalized  = [r for r in resolutions if r in SUPPORTED_RESOLUTIONS]
    if not normalized:
        normalized = ["1080p"]
    return [r for r in SUPPORTED_RESOLUTIONS if r in normalized][:4]


def build_output_filename(template: str, episode: str | None, resolution: str) -> str:
    name = template
    if episode is not None:
        name = name.replace("{episode}", episode)
    name = re.sub(r"\{quality\}", resolution, name, flags=re.IGNORECASE)
    return name


def build_jobs(template: str, episode: str | None, resolutions: list, settings_obj) -> list:
    jobs = []
    for resolution in resolutions:
        effective = settings_obj.get_effective_settings(
            resolution,
            {
                "metadata":       settings_obj.data.get("metadata", {}),
                "thumbnail_path": settings_obj.data.get("thumbnail_path", ""),
                "send_type":      settings_obj.data.get("send_type", "media"),
            },
        )
        jobs.append({
            "resolution":      resolution,
            "output_filename": build_output_filename(template, episode, resolution),
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


# ── Media fetchers ────────────────────────────────────────────────────────────

async def fetch_media_group(client: Client, chat_id: int, replied: Message) -> list:
    media_group_id = replied.media_group_id
    ids = list(range(max(1, replied.id - 3), replied.id + 20))
    try:
        messages = await client.get_messages(chat_id, ids)
    except Exception as e:
        logger.error(f"[encode] fetch_media_group: {e}")
        return []
    group = [
        m for m in messages
        if m and not getattr(m, "empty", True)
        and m.media_group_id == media_group_id
        and (m.video or m.document)
    ]
    group.sort(key=lambda m: m.id)
    return group


async def fetch_sequential_messages(client: Client, chat_id: int, start_id: int, count: int) -> list:
    ids = list(range(start_id, start_id + count))
    try:
        messages = await client.get_messages(chat_id, ids)
    except Exception as e:
        logger.error(f"[encode] fetch_sequential_messages: {e}")
        return []
    result = [m for m in messages if m and not getattr(m, "empty", True) and (m.video or m.document)]
    result.sort(key=lambda m: m.id)
    return result


def _is_video(msg: Message) -> bool:
    if msg.video:
        return True
    if msg.document:
        return os.path.splitext(msg.document.file_name or "")[1].lower() in ALLOWED_VIDEO_EXTENSIONS
    return False


def _file_info(msg: Message):
    if msg.video:
        v = msg.video
        return v.file_id, (v.file_name or f"video_{v.file_id[:8]}.mp4"), v.file_size
    d   = msg.document
    ext = os.path.splitext(d.file_name or "")[1].lower() or ".mkv"
    return d.file_id, (d.file_name or f"video_{d.file_id[:8]}{ext}"), d.file_size


def _source_thumbnail_file_id(msg: Message) -> str:
    media = msg.video or msg.document
    thumbs = getattr(media, "thumbs", None) or []
    if not thumbs:
        return ""
    return getattr(thumbs[-1], "file_id", "") or ""


# ── Single encode ─────────────────────────────────────────────────────────────

async def _process_single_encode(client, message, task_queue, settings_obj, settings, template):
    replied = message.reply_to_message
    if not _is_video(replied):
        await message.reply_text(
            f"Only video files are supported.\n"
            f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    file_id, original_file_name, file_size = _file_info(replied)
    resolutions = get_selected_resolutions(settings)
    ep_str = None
    if "{episode}" in template:
        raw_ep = str(settings.get("default_start_episode", 1))
        ep_str = str(int(raw_ep)).zfill(max(len(raw_ep), 2))

    jobs      = build_jobs(template, ep_str, resolutions, settings_obj)
    first_job = jobs[0]

    task_data = {
        "user_id":            message.from_user.id,
        "first_name":         message.from_user.first_name,
        "username":           message.from_user.username,
        "chat_id":            message.chat.id,
        "message_id":         message.id,
        "file_id":            file_id,
        "original_file_name": original_file_name,
        "output_filename":    first_job["output_filename"],
        "resolution":         first_job["resolution"],
        "created_at":         datetime.utcnow().isoformat(),
        "file_size":          file_size,
        "send_type":          settings.get("send_type", "media"),
        "auto_detect_thumb":  bool(settings.get("auto_detect_thumb", False)),
        "source_thumbnail_file_id": _source_thumbnail_file_id(replied),
        "resolutions":        resolutions,
        "jobs":               jobs,
        "total_jobs":         len(jobs),
        "current_job":        0,
        "current_stage":      "queued",
        "thumbnail_path":     settings.get("thumbnail_path", ""),
        "watermark":          settings_obj.get_watermark(),
    }

    task_id  = task_queue.create_task(task_data)
    position = task_queue.get_queue_position(task_id)

    await message.reply_text(
        f"✅ Queued at position **[{position}]**\n"
        f"Task ID: `{task_id}`\n"
        f"File: `{first_job['output_filename']}`\n"
        f"Quality: `{' → '.join(resolutions)}`\n\n"
        "Output will be delivered to your DM."
    )


# ── Batch encode ──────────────────────────────────────────────────────────────

async def _process_batch_encode(client, message, task_queue, settings_obj, settings, template, batch_count):
    replied     = message.reply_to_message
    has_ep_token = "{episode}" in template

    if batch_count is not None:
        status_msg = await message.reply_text(f"⏳ Fetching {batch_count} messages…")
        raw_msgs   = await fetch_sequential_messages(client, message.chat.id, replied.id, batch_count)
    else:
        if not replied.media_group_id:
            await message.reply_text(
                "The replied message is not part of a media group.\n"
                "Send files as an album, or use `-b N` for sequential messages."
            )
            return
        status_msg = await message.reply_text("⏳ Fetching media group…")
        raw_msgs   = await fetch_media_group(client, message.chat.id, replied)

    valid_files = [m for m in raw_msgs if _is_video(m)]
    skipped     = len(raw_msgs) - len(valid_files)

    if not valid_files:
        await status_msg.edit_text("No supported video files found.")
        return

    resolutions = get_selected_resolutions(settings)
    raw_ep      = str(settings.get("default_start_episode", 1))
    ep_width    = max(len(raw_ep), 2)
    ep_int      = int(raw_ep)
    created_at  = datetime.utcnow().isoformat()

    task_ids, positions, episodes = [], [], []

    for index, media_msg in enumerate(valid_files):
        ep_num = ep_int + index
        ep_str = str(ep_num).zfill(ep_width) if has_ep_token else None
        episodes.append(ep_num)

        file_id, original_file_name, file_size = _file_info(media_msg)
        jobs      = build_jobs(template, ep_str, resolutions, settings_obj)
        first_job = jobs[0]

        task_data = {
            "user_id":            message.from_user.id,
            "first_name":         message.from_user.first_name,
            "username":           message.from_user.username,
            "chat_id":            message.chat.id,
            "message_id":         message.id,
            "file_id":            file_id,
            "original_file_name": original_file_name,
            "output_filename":    first_job["output_filename"],
            "resolution":         first_job["resolution"],
            "created_at":         created_at,
            "file_size":          file_size,
            "send_type":          settings.get("send_type", "media"),
            "auto_detect_thumb":  bool(settings.get("auto_detect_thumb", False)),
            "source_thumbnail_file_id": _source_thumbnail_file_id(media_msg),
            "resolutions":        resolutions,
            "jobs":               jobs,
            "total_jobs":         len(jobs),
            "current_job":        0,
            "current_stage":      "queued",
            "thumbnail_path":     settings.get("thumbnail_path", ""),
            "watermark":          settings_obj.get_watermark(),
        }

        task_id  = task_queue.create_task(task_data)
        position = task_queue.get_queue_position(task_id)
        task_ids.append(task_id)
        positions.append(position)

    ep_start   = str(episodes[0]).zfill(ep_width)
    ep_end     = str(episodes[-1]).zfill(ep_width)
    pos_min, pos_max = min(positions), max(positions)
    pos_text   = f"[{pos_min}]" if pos_min == pos_max else f"[{pos_min} – {pos_max}]"
    mode_label = f"sequential ({batch_count} msgs)" if batch_count else "media group"

    lines = [
    f"Added {len(valid_files)} file(s) to the queue {pos_text}. ({mode_label})\n",
    f"Naming format: `{template}`",
    (f"Episodes: {ep_start} to {ep_end}" if has_ep_token else f"Episode: {ep_start}"),
    f"Video quality: {' → '.join(resolutions)}"
]
    if skipped:
        lines.append(f"**Skipped:** {skipped} non-video file(s)")
    lines.append("\nOutput will be delivered to your DM.")

    await status_msg.edit_text("\n".join(lines))


# ── Entry point ───────────────────────────────────────────────────────────────

async def process_encode_command(client: Client, message: Message, task_queue, user_settings):
    if not message.reply_to_message:
        await message.reply_text(
            "Reply to a video file and use:\n\n"
            "**Single encode:**\n"
            "`/e [S1-03] Show Name [{quality}] [SUB] @Source.mkv`\n\n"
            "**Batch encode (media group):**\n"
            "`/e -b [S1-{episode}] Show Name [{quality}] [SUB] @Source.mkv`\n\n"
            "**Batch encode (N sequential messages):**\n"
            "`/e -b 12 [S1-{episode}] Show Name [{quality}] [SUB] @Source.mkv`\n\n"
            "`{quality}` → filled from your resolution settings\n"
            "`{episode}` → auto-fills/increments from your default episode setting"
        )
        return

    if len(message.command) < 2:
        await message.reply_text("Missing filename template. Reply to a video and try again.")
        return

    batch, batch_count, template, error = _parse_encode_command(message.text)
    if error:
        await message.reply_text(f"❌ {error}")
        return

    user_id      = message.from_user.id
    settings_obj = user_settings(user_id)
    settings     = copy.deepcopy(settings_obj.get())

    if batch:
        await _process_batch_encode(
            client, message, task_queue, settings_obj, settings, template, batch_count
        )
    else:
        await _process_single_encode(
            client, message, task_queue, settings_obj, settings, template
        )


# ── Handler registration ──────────────────────────────────────────────────────

def setup_encode_handlers(app: Client, task_queue, user_settings, config):
    allowed_group_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["e", "encode"]) & allowed_group_filter)
    async def encode_command(client: Client, message: Message):
        if not await _check_access(client, message, config):
            return
        await process_encode_command(client, message, task_queue, user_settings)