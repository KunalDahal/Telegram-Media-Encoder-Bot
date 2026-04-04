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
RESOLUTION_ALIASES = {
    "hdrip": "HDRip",
    "1080p": "1080p",
    "720p":  "720p",
    "480p":  "480p",
    "480":   "480p",
}


# ── Guard helper ──────────────────────────────────────────────────────────────

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
            f"⚠️ Please start the bot in DM before giving tasks here.\n"
            f"👉 @{bot_username} — press **Start**, then try again."
        )
        return False

    return True


# ── Argument parser ───────────────────────────────────────────────────────────

def parse_encode_args(command_text: str):
    text = re.sub(r"^/\S+\s*", "", command_text).strip()
    t_match = re.search(r"(?:^|\s)-t\s+(.*)", text, re.DOTALL)
    if not t_match:
        return None, (
            "`-t <title>` is required and must be the last flag.\n\n"
            "Usage: `/encode [-b] [-s S] [-e E] [-a AUDIO] [-q QUALITY] -t Title`"
        )

    title = t_match.group(1).strip()
    if not title:
        return None, "Title cannot be empty after `-t`."
    pre_t = text[: t_match.start()]
    batch = bool(re.search(r"(?:^|\s)-b(?:\s|$)", pre_t))
    season = None
    m = re.search(r"(?:^|\s)-s\s+(\d+)", pre_t)
    if m:
        season = int(m.group(1))
    episode = None
    m = re.search(r"(?:^|\s)-e\s+(\d+)", pre_t)
    if m:
        episode = int(m.group(1))
        if episode < 1:
            return None, "Episode number must be ≥ 1."
    audio = None
    m = re.search(r"(?:^|\s)-a\s+(\S+)", pre_t)
    if m:
        audio = m.group(1)
    quality = None
    m = re.search(r"(?:^|\s)-q\s+(\S+)", pre_t)
    if m:
        raw_q = m.group(1).strip().lower()
        quality = RESOLUTION_ALIASES.get(raw_q)
        if quality is None:
            return None, (
                f"Unknown quality `{m.group(1)}`.\n"
                f"Valid values: {', '.join(SUPPORTED_RESOLUTIONS)}"
            )

    return {
        "batch":   batch,
        "season":  season,
        "episode": episode,
        "audio":   audio,  
        "quality": quality, 
        "title":   title,
    }, None


# ── Format/filename helpers ───────────────────────────────────────────────────

def validate_user_format(format_string: str):
    if not format_string or not format_string.strip():
        return False, (
            "No filename format is set.\n"
            "Configure one via /es → Filename Format."
        )
    required = ["{quality}", "{title}", "{episode}"]
    missing  = [ph for ph in required if ph not in format_string]
    if missing:
        return False, (
            f"Your filename format is missing: {', '.join(missing)}\n"
            f"Current format: `{format_string}`\n\n"
            "All three of `{{quality}}`, `{{title}}`, and `{{episode}}` are required."
        )
    dummy = re.sub(r"\{[^}]+\}", "X", format_string)
    ext   = os.path.splitext(dummy)[1].lower()
    if not ext or ext not in ALLOWED_VIDEO_EXTENSIONS:
        return False, (
            "Your filename format must end with a valid video extension "
            "(.mp4, .mkv, etc.).\n"
            f"Current format: `{format_string}`"
        )
    return True, None


def build_encode_filename(format_string: str, title: str, season: int,
                          episode: int, audio: str) -> str:
    filename = format_string
    filename = filename.replace("{title}",   title or "")
    filename = filename.replace("{season}",  f"{season:02d}")
    filename = filename.replace("{episode}", f"{episode:02d}")
    audio = audio or ""
    if audio:
        filename = filename.replace("{audio}", audio)
    else:
        filename = re.sub(r"\s*[\[(]\s*\{audio\}\s*[\])]", "", filename)
        filename = filename.replace("{audio}", "")
    return filename


def build_output_filename(filename: str, resolution: str, total_jobs: int = 1) -> str:
    return re.sub(r"\{quality\}", resolution, filename, flags=re.IGNORECASE)


def get_selected_resolutions(settings: dict) -> list:
    resolutions = settings.get("resolutions") or [settings.get("resolution", "1080p")]
    normalized  = []
    for r in resolutions:
        if r in SUPPORTED_RESOLUTIONS and r not in normalized:
            normalized.append(r)
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


# ── Media-group fetcher ───────────────────────────────────────────────────────

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


# ── Value resolver ────────────────────────────────────────────────────────────

def resolve_encode_values(args: dict, settings: dict) -> dict:
    return {
        "season":  args["season"]  if args["season"]  is not None else settings.get("default_season", 1),
        "episode": args["episode"] if args["episode"] is not None else settings.get("default_start_episode", 1),
        "audio":   args["audio"]   if args["audio"]   is not None else settings.get("default_audio", ""),
        "title":   args["title"],
    }


# ── Single encode ─────────────────────────────────────────────────────────────

async def process_single_encode(
    client: Client,
    message: Message,
    task_queue,
    user_settings,
    args: dict,
):
    user_id = message.from_user.id

    replied = message.reply_to_message
    file_id = original_file_name = file_size = None

    if replied.video:
        file_id            = replied.video.file_id
        original_file_name = replied.video.file_name or f"video_{replied.video.file_id[:8]}.mp4"
        file_size          = replied.video.file_size

    elif replied.document:
        fname    = replied.document.file_name or ""
        file_ext = os.path.splitext(fname)[1].lower()
        if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
            await message.reply_text(
                f"Only video files are allowed.\n"
                f"Supported: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
            )
            return
        file_id            = replied.document.file_id
        original_file_name = fname or f"video_{replied.document.file_id[:8]}{file_ext}"
        file_size          = replied.document.file_size

    else:
        await message.reply_text("Reply to a video file.")
        return

    settings_obj = user_settings(user_id)
    settings     = copy.deepcopy(settings_obj.get())

    format_string = settings_obj.get_format()
    ok, fmt_error = validate_user_format(format_string)
    if not ok:
        await message.reply_text(f"❌ **Format error:**\n{fmt_error}")
        return

    resolved = resolve_encode_values(args, settings)
    season   = resolved["season"]
    episode  = resolved["episode"]
    audio    = resolved["audio"]
    title    = resolved["title"]

    # Quality: -q override or all saved resolutions
    if args["quality"]:
        selected_resolutions = [args["quality"]]
    else:
        selected_resolutions = get_selected_resolutions(settings)

    filename_template = build_encode_filename(
        format_string, title, season, episode, audio
    )

    base_metadata = settings.get("metadata", {})
    jobs          = build_jobs(filename_template, selected_resolutions, settings_obj, base_metadata)
    first_job     = jobs[0]
    created_at    = datetime.utcnow().isoformat()

    task_data = {
        "user_id":                   user_id,
        "first_name":                message.from_user.first_name,
        "username":                  message.from_user.username,
        "chat_id":                   message.chat.id,
        "message_id":                message.id,
        "file_id":                   file_id,
        "original_file_name":        original_file_name,
        "requested_output_filename": filename_template,
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
    res_text = " → ".join(selected_resolutions)

    await message.reply_text(
        f"✅ Task queued at position **[{position}]**\n"
        f"Task ID : `{task_id}`\n"
        f"File    : `{first_job['output_filename']}`\n"
        f"Quality : `{res_text}`\n\n"
        "**Output will be delivered to your DM.** Please wait patiently."
    )


# ── Batch encode ──────────────────────────────────────────────────────────────

async def process_batch_encode(
    client: Client,
    message: Message,
    task_queue,
    user_settings,
    args: dict,
):
    user_id = message.from_user.id
    replied = message.reply_to_message

    if not replied.media_group_id:
        await message.reply_text(
            "The replied message is not part of a media group (album).\n"
            "Send your files together as an album, then reply to the first one."
        )
        return

    settings_obj  = user_settings(user_id)
    settings      = copy.deepcopy(settings_obj.get())
    format_string = settings_obj.get_format()

    ok, fmt_error = validate_user_format(format_string)
    if not ok:
        await message.reply_text(f"❌ **Format error:**\n{fmt_error}")
        return

    resolved = resolve_encode_values(args, settings)
    season   = resolved["season"]
    episode  = resolved["episode"]
    audio    = resolved["audio"]
    title    = resolved["title"]
    if args["quality"]:
        selected_resolutions = [args["quality"]]
    else:
        selected_resolutions = get_selected_resolutions(settings)
    status_msg  = await message.reply_text("⏳ Fetching media group…")
    media_group = await fetch_media_group(client, message.chat.id, replied)

    if not media_group:
        await status_msg.edit_text(
            "Could not find any media in the album.\n"
            "Make sure you replied to the first file of the group."
        )
        return
    valid_files = []
    skipped     = 0
    for m in media_group:
        if m.video:
            valid_files.append(m)
        elif m.document:
            ext = os.path.splitext(m.document.file_name or "")[1].lower()
            if ext in ALLOWED_VIDEO_EXTENSIONS:
                valid_files.append(m)
            else:
                skipped += 1
        else:
            skipped += 1

    if not valid_files:
        await status_msg.edit_text(
            f"No supported video files found in the album.\n"
            f"Supported: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    base_metadata = settings.get("metadata", {})
    created_at    = datetime.utcnow().isoformat()
    season_str    = f"{season:02d}"

    task_ids  = []
    positions = []
    episodes  = []

    for index, media_msg in enumerate(valid_files):
        ep      = episode + index
        episodes.append(ep)

        filename_template = build_encode_filename(
            format_string, title, season, ep, audio
        )

        if media_msg.video:
            file_id            = media_msg.video.file_id
            original_file_name = (
                media_msg.video.file_name
                or f"video_{media_msg.video.file_id[:8]}.mp4"
            )
            file_size = media_msg.video.file_size
        else:
            file_id            = media_msg.document.file_id
            original_file_name = (
                media_msg.document.file_name
                or f"video_{media_msg.document.file_id[:8]}.mkv"
            )
            file_size = media_msg.document.file_size

        jobs      = build_jobs(filename_template, selected_resolutions, settings_obj, base_metadata)
        first_job = jobs[0]

        task_data = {
            "user_id":                   user_id,
            "first_name":                message.from_user.first_name,
            "username":                  message.from_user.username,
            "chat_id":                   message.chat.id,
            "message_id":                message.id,
            "file_id":                   file_id,
            "original_file_name":        original_file_name,
            "requested_output_filename": filename_template,
            "output_filename":           first_job["output_filename"],
            "resolution":                first_job["resolution"],
            "created_at":                created_at,
            "file_size":                 file_size,
            "send_type":                 settings.get("send_type", "media"),
            "resolutions":               selected_resolutions,
            "jobs":                      jobs,
            "total_jobs":                len(jobs),
            "current_job":               0,
            "current_stage":             "queued",
            "thumbnail_path":            settings.get("thumbnail_path", ""),
            "watermark":                 settings_obj.get_watermark(),
            "settings_snapshot":         settings,
            "batch_encode":              True,
        }

        task_id  = task_queue.create_task(task_data)
        position = task_queue.get_queue_position(task_id)
        task_ids.append(task_id)
        positions.append(position)

    ep_start = f"{episodes[0]:02d}"
    ep_end   = f"{episodes[-1]:02d}"
    pos_min  = min(positions)
    pos_max  = max(positions)
    pos_text = f"[{pos_min}]" if pos_min == pos_max else f"[{pos_min} – {pos_max}]"
    res_text = " → ".join(selected_resolutions)

    lines = [
        f"✅ Queued **{len(valid_files)}** file(s) successfully.\n",
        f"**Title:**    {title}",
        f"**Season:**   {season_str}",
        f"**Episodes:** {ep_start} → {ep_end}",
        f"**Quality:**  {res_text}",
    ]
    if audio:
        lines.append(f"**Audio:** {audio}")
    if skipped:
        lines.append(f"**Skipped:** {skipped} non-video file(s)")
    lines.append(f"**Queue position(s):** {pos_text}")
    lines.append("\n**Output will be delivered to your DM.** Please wait patiently.")

    await status_msg.edit_text("\n".join(lines))


# ── /encode handler ───────────────────────────────────────────────────────────

async def process_encode_command(
    client: Client,
    message: Message,
    task_queue,
    user_settings,
):
    if not message.reply_to_message:
        await message.reply_text(
            "Reply to a video file and use:\n\n"
            "`/encode [-b] [-s SEASON] [-e EPISODE] [-a AUDIO] [-q QUALITY] -t Title`\n\n"
            "Examples:\n"
            "`/encode -t Pokemon`\n"
            "`/encode -e 12 -t Pokemon`\n"
            "`/encode -s 2 -e 5 -a DUAL -t Pokemon Season 2`\n"
            "`/encode -b -s 1 -e 1 -t Pokemon`  ← batch mode"
        )
        return

    if len(message.command) < 2:
        await message.reply_text(
            "Missing arguments. `-t <title>` is required.\n\n"
            "Usage: `/encode [-b] [-s S] [-e E] [-a AUDIO] [-q QUALITY] -t Title`"
        )
        return

    args, parse_error = parse_encode_args(message.text)
    if parse_error:
        await message.reply_text(f"❌ **Argument error:**\n{parse_error}")
        return

    if args["batch"]:
        await process_batch_encode(client, message, task_queue, user_settings, args)
    else:
        await process_single_encode(client, message, task_queue, user_settings, args)


# ── Handler registration ──────────────────────────────────────────────────────

def setup_encode_handlers(app: Client, task_queue, user_settings, config):

    allowed_group_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["e", "encode"]) & allowed_group_filter)
    async def encode_command(client: Client, message: Message):
        if not await _check_access(client, message, config):
            return
        await process_encode_command(client, message, task_queue, user_settings)