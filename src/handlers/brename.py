import copy
import os
import re
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from src.handlers.encode import (
    _check_access,
    ALLOWED_VIDEO_EXTENSIONS,
)
from src.handlers.bencode import (
    fetch_media_group,
    validate_user_format,
    _get_format_placeholders,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1.  Argument parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_batch_rename_args(command_text: str):
    text = re.sub(r"^/\S+\s*", "", command_text).strip()

    errors = []
    result = {
        "start_episode": None,
        "season":        1,
        "audio":         "",
        "quality":       None,
        "title":         None,
    }

    m = re.search(r"-e\s+(\d+)", text)
    if m:
        result["start_episode"] = int(m.group(1))
    else:
        errors.append("• `-e <number>` — starting episode is required.")

    m = re.search(r"-s\s+(\d+)", text)
    if m:
        result["season"] = int(m.group(1))

    m = re.search(r"-a\s+(\S+)", text)
    if m:
        result["audio"] = m.group(1)

    m = re.search(r"-q\s+(\S+)", text)
    if m:
        result["quality"] = m.group(1)
    else:
        errors.append("• `-q <quality>` — quality label is required (e.g. HDRip, 1080p, BluRay).")

    m = re.search(
        r"-t\s+(.*?)(?=\s+-[a-zA-Z](?:\s|$)|$)",
        text,
        re.DOTALL,
    )
    if m:
        result["title"] = m.group(1).strip()
    else:
        errors.append("• `-t <title>` — show/movie title is required.")

    if result["start_episode"] is not None and result["start_episode"] < 1:
        errors.append("• Episode number must be ≥ 1.")

    if errors:
        return None, "\n".join(errors)
    return result, None


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Format-string helpers
# ─────────────────────────────────────────────────────────────────────────────

def validate_brename_args_against_format(format_string: str, args: dict) -> tuple[bool, str | None]:
    """
    Check that every placeholder in the format that requires a user argument
    has actually been supplied for /br.

    Mapping:
        {title}   → -t   (always required by parser, double-checked here)
        {episode} → -e   (always required by parser, double-checked here)
        {quality} → -q   (required if in format — unlike /be where it's auto-filled)
        {season}  → -s   (has default 1, so never truly missing)
        {audio}   → -a   (optional — only required if in format AND not in optional bracket)
    """
    placeholders = _get_format_placeholders(format_string)
    missing = []

    # {title}
    if "{title}" in placeholders and not (args.get("title") or "").strip():
        missing.append("`-t <title>` is required because your format contains `{title}`.")

    # {episode}
    if "{episode}" in placeholders and args.get("start_episode") is None:
        missing.append("`-e <episode>` is required because your format contains `{episode}`.")

    # {quality} — for /br this is a manual CLI arg, always required when in format
    if "{quality}" in placeholders and not (args.get("quality") or "").strip():
        missing.append("`-q <quality>` is required because your format contains `{quality}`.")

    # {audio} — only required if NOT wrapped in an optional bracket
    if "{audio}" in placeholders and not (args.get("audio") or "").strip():
        optional_pattern = r"[\[(]\s*\{audio\}\s*[\])]"
        if not re.search(optional_pattern, format_string):
            missing.append(
                "`-a <audio>` is required because your format contains `{audio}` "
                "without an optional bracket.\n"
                "  Either pass `-a SUB` (or any label), or update your format to use "
                "`[{audio}]` so it is auto-dropped when omitted."
            )

    # {season} always has a default (1) so we never block on it.

    if missing:
        return False, "\n".join(f"• {m}" for m in missing)
    return True, None


def build_batch_rename_filename(format_string: str, data: dict) -> str:
    filename = format_string
    filename = filename.replace("{title}",   data.get("title",       ""))
    filename = filename.replace("{season}",  data.get("season_str",  "01"))
    filename = filename.replace("{episode}", data.get("episode_str", "01"))
    filename = filename.replace("{quality}", data.get("quality",     ""))

    audio = data.get("audio", "")
    if audio:
        filename = filename.replace("{audio}", audio)
    else:
        # Drop optional audio bracket entirely: [SUB] or (SUB) → gone
        filename = re.sub(r"\s*[\[(]\s*\{audio\}\s*[\])]", "", filename)
        filename = filename.replace("{audio}", "")

    return filename


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Core command handler
# ─────────────────────────────────────────────────────────────────────────────

async def process_batch_rename_command(
    client: Client,
    message: Message,
    task_queue,
    user_settings,
):
    user_id = message.from_user.id

    # ── 3.1  Must be a reply ──────────────────────────────────────────────────
    if not message.reply_to_message:
        await message.reply_text(
            "Reply to the **first** file of a media group (album).\n\n"
            "Usage:\n`/br -e 1 -s 1 -a SUB -q HDRip -t My Show Title`"
        )
        return

    replied = message.reply_to_message

    # ── 3.2  Replied message must belong to a media group ─────────────────────
    if not replied.media_group_id:
        await message.reply_text(
            "The replied message is not part of a media group (album).\n"
            "Send your files together as an album, then reply to the first one."
        )
        return

    # ── 3.3  Parse command arguments ──────────────────────────────────────────
    args, parse_error = parse_batch_rename_args(message.text)
    if parse_error:
        await message.reply_text(
            f"**Argument error:**\n{parse_error}\n\n"
            "Usage: `/br -e 1 -s 1 -a SUB -q HDRip -t My Show Title`"
        )
        return

    start_episode = args["start_episode"]
    season        = args["season"]
    audio         = args["audio"]
    quality       = args["quality"]
    title         = args["title"]

    # ── 3.4  Load user settings & validate the saved format ───────────────────
    settings_obj  = user_settings(user_id)
    settings      = copy.deepcopy(settings_obj.get())
    format_string = settings_obj.get_format()
    watermark     = settings_obj.get_watermark()

    ok, fmt_error = validate_user_format(format_string)
    if not ok:
        await message.reply_text(f"❌ **Format error:**\n{fmt_error}")
        return

    # ── 3.4b  Validate that supplied args satisfy every format placeholder ─────
    ok, arg_error = validate_brename_args_against_format(format_string, args)
    if not ok:
        placeholders = _get_format_placeholders(format_string)
        ph_list      = "  " + "  ".join(f"`{{{p}}}`" for p in sorted(placeholders))
        await message.reply_text(
            f"❌ **Missing argument(s) for your filename template:**\n{arg_error}\n\n"
            f"Your current format: `{format_string}`\n"
            f"Placeholders found:{ph_list}\n\n"
            "Please supply all required arguments and try again.\n"
            "To change your template, go to /es → Filename Format."
        )
        return

    # ── 3.5  Fetch the full media group ───────────────────────────────────────
    status_msg  = await message.reply_text("⏳ Fetching media group…")
    media_group = await fetch_media_group(client, message.chat.id, replied)

    if not media_group:
        await status_msg.edit_text(
            "Could not find any media in the album.\n"
            "Make sure you replied to the first file of the group."
        )
        return

    # ── 3.6  Filter to supported video files only ─────────────────────────────
    valid_files: list[Message] = []
    skipped = 0
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
            f"Allowed extensions: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )
        return

    # ── 3.7  Build and queue one rename task per file ─────────────────────────
    base_metadata = settings.get("metadata", {})
    created_at    = datetime.utcnow().isoformat()
    season_str    = f"{season:02d}"

    task_ids:  list[str] = []
    positions: list[int] = []
    episodes:  list[int] = []

    for index, media_msg in enumerate(valid_files):
        episode     = start_episode + index
        episode_str = f"{episode:02d}"
        episodes.append(episode)

        output_filename = build_batch_rename_filename(
            format_string,
            {
                "title":       title,
                "season_str":  season_str,
                "episode_str": episode_str,
                "quality":     quality,
                "audio":       audio,
            },
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

        job = {
            "resolution":      "rename",
            "output_filename": output_filename,
            "processing_mode": "rename",
            "audio_bitrate":   None,
            "metadata":        base_metadata,
            "thumbnail_path":  settings.get("thumbnail_path", ""),
            "send_type":       settings.get("send_type", "media"),
        }

        task_data = {
            # ── Standard fields ───────────────────────────────────────────────
            "user_id":                   user_id,
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
            "batch_rename":              True,
        }

        task_id  = task_queue.create_task(task_data)
        position = task_queue.get_queue_position(task_id)
        task_ids.append(task_id)
        positions.append(position)

    # ── 3.8  Summary reply ────────────────────────────────────────────────────
    ep_start = f"{episodes[0]:02d}"
    ep_end   = f"{episodes[-1]:02d}"
    pos_min  = min(positions)
    pos_max  = max(positions)

    wm = watermark or {}
    wm_note = (
        "rename + watermark + metadata"
        if wm.get("enabled") and wm.get("text")
        else "rename + metadata"
    )

    lines = [
        f"Queued **{len(valid_files)}** rename task(s) successfully.\n",
        f"**Title:** {title}",
        f"**Season:** {season_str}",
        f"**Episodes:** {ep_start} → {ep_end}",
        f"**Quality:** {quality}",
    ]
    if audio:
        lines.append(f"**Audio:** {audio}")
    if skipped:
        lines.append(f"**Skipped:** {skipped} non-video file(s)")

    lines.append(f"**Mode:** {wm_note}")

    pos_text = f"[{pos_min}]" if pos_min == pos_max else f"[{pos_min} – {pos_max}]"
    lines.append(f"**Queue position(s):** {pos_text}")
    lines.append("\n**Output will be delivered to your DM.** Please wait patiently.")

    await status_msg.edit_text("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Handler registration
# ─────────────────────────────────────────────────────────────────────────────

def setup_batch_rename_handlers(app: Client, task_queue, user_settings, config):
    allowed_group_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["br", "batchrename"]) & allowed_group_filter)
    async def batch_rename_command(client: Client, message: Message):
        if not await _check_access(client, message, config):
            return
        await process_batch_rename_command(client, message, task_queue, user_settings)