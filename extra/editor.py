from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
from pyrogram import enums, filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.user_setting import UserSettings
from src.utils.telegraphpage import MediaInfoHelper

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

PREVIEW_DURATION      = 30              
PARTIAL_STREAM_BYTES  = 50 * 1024 * 1024
_CB                   = "edit"            


# ═══════════════════════════════════════════════════════════════════════════════
# Parameter metadata  (drives the entire Parameters UI)
# ═══════════════════════════════════════════════════════════════════════════════
_PARAM_META: Dict[str, Tuple[str, str, str]] = {
    "audio_offset":    ("Audio Offset",      "float", "seconds (+late / -early)"),
    "subtitle_offset": ("Subtitle Offset",   "float", "seconds (+late / -early)"),
    "audio_async":     ("Audio Async",       "int",   "aresample async value (0 = off)"),
    "audio_tempo":     ("Audio Tempo",       "float", "atempo multiplier  e.g. 1.001"),
    "video_fps":       ("Video FPS",         "str",   "source | 24 | 25 | 30 | 24000/1001"),
    "video_vsync":     ("Video VSYNC",       "str",   "cfr | vfr | passthrough | drop"),
    "video_pts":       ("Video PTS",         "str",   "setpts expression e.g. PTS-STARTPTS"),
    "audio_pts":       ("Audio PTS",         "str",   "asetpts expression e.g. PTS-STARTPTS"),
    "audio_pad":       ("Audio Pad",         "toggle","extend audio to match video"),
    "video_pad":       ("Video Pad",         "toggle","extend video to match audio"),
    "shortest":        ("Shortest",          "toggle","end at shortest stream (-shortest)"),
    "fix_sub_duration":("Fix Sub Duration",  "toggle","-fix_sub_duration"),
    "generate_pts":    ("Generate PTS",      "toggle","-fflags +genpts"),
    "ignore_dts":      ("Ignore DTS",        "toggle","-fflags +igndts"),
    "copy_timestamps": ("Copy Timestamps",   "toggle","-copyts"),
    "start_at_zero":   ("Start At Zero",     "toggle","-start_at_zero"),
}

_TOGGLE_PARAMS = {k for k, (_, t, _h) in _PARAM_META.items() if t == "toggle"}
_VALUE_PARAMS  = {k for k, (_, t, _h) in _PARAM_META.items() if t != "toggle"}


# ═══════════════════════════════════════════════════════════════════════════════
# Session dataclass
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MiSession:
    user_id:          int
    file_id:          str
    filename:         str
    file_size:        int
    temp_dir:         str
    preview_path:     Optional[str]  = None
    preview_msg_id:   Optional[int]  = None
    telegraph_url:    Optional[str]  = None
    remove_audio:     List[int]      = field(default_factory=list)
    remove_subtitle:  List[int]      = field(default_factory=list)
    extract_audio:    List[int]      = field(default_factory=list)
    extract_subtitle: List[int]      = field(default_factory=list)
    added_audio_path: Optional[str]  = None
    added_sub_path:   Optional[str]  = None
    audio_tracks:     List[Dict]     = field(default_factory=list)
    subtitle_tracks:  List[Dict]     = field(default_factory=list)
    nav_state:        str            = "main"
    confirm_data:     Optional[Any]  = None
    waiting_for:      Optional[str]  = None
    waiting_param:    Optional[str]  = None
    param_prompt_id:  Optional[int]  = None
    mi_task_id:       Optional[str]  = None

    # Concurrency guard
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Global registry
_sessions: Dict[int, MiSession] = {}
_telegraph = MediaInfoHelper()


# ═══════════════════════════════════════════════════════════════════════════════
# Callback-data helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _cb(*parts) -> str:
    return f"{_CB}:" + ":".join(str(p) for p in parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Keyboard builders
# ═══════════════════════════════════════════════════════════════════════════════

def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Add Audio",        callback_data=_cb("add_audio")),
            InlineKeyboardButton("Add Subtitle",      callback_data=_cb("add_sub")),
        ],
        [
            InlineKeyboardButton("Remove Audio",     callback_data=_cb("rm_audio")),
            InlineKeyboardButton("Remove Subtitle",  callback_data=_cb("rm_sub")),
        ],
        [
            InlineKeyboardButton("Extract Audio",    callback_data=_cb("ex_audio")),
            InlineKeyboardButton("Extract Subtitle", callback_data=_cb("ex_sub")),
        ],
        [InlineKeyboardButton("Parameters",          callback_data=_cb("params"))],
        [InlineKeyboardButton("Generate Info Page",  callback_data=_cb("info_page"))],
        [InlineKeyboardButton("Apply All",            callback_data=_cb("apply_all"))],
        [InlineKeyboardButton("Close",                callback_data=_cb("close"))],
    ])


def _params_keyboard(params: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    for key, (label, ptype, _hint) in _PARAM_META.items():
        val = params.get(key)
        if ptype == "toggle":
            state = "ON" if val else "☐ OFF"
            text  = f"{label}  [{state}]"
        else:
            text = f"{label}  [{val}]"
        rows.append([InlineKeyboardButton(text, callback_data=_cb("param_tap", key))])

    rows.append([
        InlineKeyboardButton("Reset All",  callback_data=_cb("param_reset")),
        InlineKeyboardButton("Back",        callback_data=_cb("back")),
    ])
    return InlineKeyboardMarkup(rows)


def _track_keyboard(tracks: List[Dict], action: str, marked: List[int]) -> InlineKeyboardMarkup:
    rows = []
    for idx, t in enumerate(tracks):
        label = t.get("language") or t.get("title") or f"Track {idx + 1}"
        codec = t.get("codec", "")
        extra = f" ({codec})" if codec else ""
        tick  = " ✓" if idx in marked else ""
        rows.append([InlineKeyboardButton(
            f"{label}{extra}{tick}",
            callback_data=_cb(action, idx),
        )])
    rows.append([InlineKeyboardButton("Back", callback_data=_cb("back"))])
    return InlineKeyboardMarkup(rows)


def _confirm_keyboard(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes", callback_data=yes_cb),
        InlineKeyboardButton("No",  callback_data=no_cb),
    ]])


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Cancel", callback_data=_cb("cancel_wait")),
    ]])


# ═══════════════════════════════════════════════════════════════════════════════
# Parameter text display
# ═══════════════════════════════════════════════════════════════════════════════

def _params_text(params: Dict[str, Any]) -> str:
    lines = ["<b>Parameters</b>\n"]
    for key, (label, ptype, hint) in _PARAM_META.items():
        val = params.get(key)
        if ptype == "toggle":
            display = "ON" if val else "☐ OFF"
        else:
            display = f"<code>{val}</code>"
        lines.append(f"<b>{label}</b>  →  {display}\n  <i>{hint}</i>")
    lines.append("\nTap any row to change. Changes are saved and preview rebuilds.")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Track parsing
# ═══════════════════════════════════════════════════════════════════════════════

def _lang_label(lang: str, title: str, idx: int) -> str:
    if lang:
        return lang.capitalize()
    if title:
        return title
    return f"Track {idx + 1}"


def _parse_tracks(media_info) -> Tuple[List[Dict], List[Dict]]:
    audio_tracks: List[Dict]    = []
    subtitle_tracks: List[Dict] = []
    if media_info is None:
        return audio_tracks, subtitle_tracks
    for track in media_info.tracks:
        tt    = track.track_type
        lang  = getattr(track, "language", None) or ""
        title = getattr(track, "title",    None) or ""
        codec = getattr(track, "format",   None) or ""
        if tt == "Audio":
            audio_tracks.append({
                "language": _lang_label(lang, title, len(audio_tracks)),
                "codec": codec, "title": title,
            })
        elif tt == "Text":
            subtitle_tracks.append({
                "language": _lang_label(lang, title, len(subtitle_tracks)),
                "codec": codec, "title": title,
            })
    return audio_tracks, subtitle_tracks


# ═══════════════════════════════════════════════════════════════════════════════
# Partial download
# ═══════════════════════════════════════════════════════════════════════════════

async def _download_partial(client, media, save_path: str,
                             max_bytes: int = PARTIAL_STREAM_BYTES):
    file_size = getattr(media, "file_size", None) or 0
    if file_size and file_size <= max_bytes:
        await client.download_media(media, file_name=save_path)
        return
    received = 0
    async with aiofiles.open(save_path, "wb") as f:
        async for chunk in client.stream_media(media):
            await f.write(chunk)
            received += len(chunk)
            if received >= max_bytes:
                break


# ═══════════════════════════════════════════════════════════════════════════════
# FFmpeg helpers
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_ffmpeg(*args: str) -> Tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_b = await proc.communicate()
    stderr = stderr_b.decode("utf-8", errors="ignore")
    return proc.returncode == 0, stderr[-500:] if proc.returncode != 0 else ""


def _build_fflags(params: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    if params.get("generate_pts"):
        flags.append("+genpts")
    if params.get("ignore_dts"):
        flags.append("+igndts")
    if not flags:
        return []
    return ["-fflags", "".join(flags)]


async def _build_preview_command(
    ffmpeg_path: str,
    source_path: str,
    output_path: str,
    session:     MiSession,
    params:      Dict[str, Any],
    duration:    int = PREVIEW_DURATION,
) -> List[str]:
    n_audio = len(session.audio_tracks)
    n_sub   = len(session.subtitle_tracks)

    keep_audio = [i for i in range(n_audio) if i not in session.remove_audio]
    keep_sub   = [i for i in range(n_sub)   if i not in session.remove_subtitle]

    cmd: List[str] = [ffmpeg_path, "-y"]

    # ── Global flags ──────────────────────────────────────────────────────────
    cmd += _build_fflags(params)
    if params.get("copy_timestamps"):
        cmd += ["-copyts"]

    # ── Source input (fix_sub_duration is an input-side option) ──────────────
    if params.get("fix_sub_duration"):
        cmd += ["-fix_sub_duration"]
    cmd += ["-ss", "0", "-t", str(duration), "-i", source_path]

    # ── Extra audio input ─────────────────────────────────────────────────────
    extra_audio_idx = None
    if session.added_audio_path and os.path.exists(session.added_audio_path):
        ao = params.get("audio_offset", 0.0)
        if ao:
            cmd += ["-itsoffset", str(ao)]
        cmd += ["-ss", "0", "-t", str(duration), "-i", session.added_audio_path]
        extra_audio_idx = 1   # second input

    # ── Stream maps ───────────────────────────────────────────────────────────
    maps: List[str] = ["-map", "0:v:0"]
    for ai in keep_audio:
        maps += ["-map", f"0:a:{ai}"]
    if extra_audio_idx is not None:
        maps += ["-map", f"{extra_audio_idx}:a:0"]
    for si in keep_sub:
        maps += ["-map", f"0:s:{si}"]

    cmd += maps

    # ── Video filter chain ────────────────────────────────────────────────────
    vf_parts: List[str] = []

    fps = params.get("video_fps", "source")
    if fps and fps != "source":
        vf_parts.append(f"fps={fps}")

    vpts = params.get("video_pts", "")
    if vpts:
        vf_parts.append(f"setpts={vpts}")

    # Subtitle burn-in
    if session.added_sub_path and os.path.exists(session.added_sub_path):
        so = params.get("subtitle_offset", 0.0)
        sub_esc = session.added_sub_path.replace("\\", "/").replace(":", "\\:")
        if so:
            vf_parts.append(f"subtitles='{sub_esc}':si=0,setpts=PTS+{so}/TB")
        else:
            vf_parts.append(f"subtitles='{sub_esc}'")

    needs_reencode = bool(vf_parts or session.added_sub_path)

    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    # ── Audio filter chain ────────────────────────────────────────────────────
    af_parts: List[str] = []

    async_val = params.get("audio_async", 0)
    if async_val and int(async_val) > 0:
        af_parts.append(f"aresample=async={int(async_val)}")

    tempo = params.get("audio_tempo", 1.0)
    if tempo and float(tempo) != 1.0:
        af_parts.append(f"atempo={float(tempo)}")

    apts = params.get("audio_pts", "")
    if apts:
        af_parts.append(f"asetpts={apts}")

    if params.get("audio_pad"):
        af_parts.append("apad")

    if af_parts:
        cmd += ["-af", ",".join(af_parts)]
        needs_reencode = True

    # ── Codec selection ───────────────────────────────────────────────────────
    if needs_reencode:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c:v", "copy", "-c:a", "copy"]

    cmd += ["-c:s", "copy"]

    # ── Misc flags ────────────────────────────────────────────────────────────
    vsync = params.get("video_vsync", "cfr")
    if vsync:
        cmd += ["-vsync", str(vsync)]

    if params.get("shortest"):
        cmd.append("-shortest")

    if params.get("video_pad"):
        cmd += ["-vf", f"tpad=stop_mode=clone:stop_duration={duration}"]

    if params.get("start_at_zero"):
        cmd.append("-start_at_zero")

    cmd.append(output_path)
    return cmd


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction helpers
# ═══════════════════════════════════════════════════════════════════════════════

async def _extract_audio_track(ffmpeg_path: str, source: str,
                                idx: int, out_dir: str, codec: str = "") -> Optional[str]:
    ext = ".m4a" if codec.lower() in ("aac", "alac") else ".mka"
    out = os.path.join(out_dir, f"audio_track_{idx}{ext}")
    ok, _ = await _run_ffmpeg(
        ffmpeg_path, "-y", "-i", source,
        "-map", f"0:a:{idx}", "-c:a", "copy", out,
    )
    return out if ok and os.path.exists(out) else None


async def _extract_subtitle_track(ffmpeg_path: str, source: str,
                                   idx: int, out_dir: str, codec: str = "") -> Optional[str]:
    lc  = codec.lower()
    ext = ".ass" if lc in ("ass", "ssa") else ".sup" if lc in ("hdmv_pgs_subtitle", "dvd_subtitle", "dvdsub") else ".srt"
    out = os.path.join(out_dir, f"subtitle_track_{idx}{ext}")
    ok, _ = await _run_ffmpeg(
        ffmpeg_path, "-y", "-i", source,
        "-map", f"0:s:{idx}", "-c:s", "copy", out,
    )
    return out if ok and os.path.exists(out) else None


# ═══════════════════════════════════════════════════════════════════════════════
# Preview send / refresh
# ═══════════════════════════════════════════════════════════════════════════════

def _preview_caption(session: MiSession, params: Dict[str, Any]) -> str:
    lines = [f"<b>{session.filename}</b>", "<i>30-second preview</i>"]
    edits = []
    if session.remove_audio:
        edits.append(f"Audio tracks removed: {session.remove_audio}")
    if session.remove_subtitle:
        edits.append(f"Subtitle tracks removed: {session.remove_subtitle}")
    if session.added_audio_path:
        edits.append("Audio added")
    if session.added_sub_path:
        edits.append("Subtitle added")
    from src.core.user_setting import DEFAULT_MI_PARAMS
    param_edits = []
    for k, v in params.items():
        default = DEFAULT_MI_PARAMS.get(k)
        if v != default:
            label = _PARAM_META.get(k, (k, "", ""))[0]
            param_edits.append(f"⚙ {label}: {v}")
    if param_edits:
        edits += param_edits
    if edits:
        lines.append("\n<b>Active edits:</b>")
        lines += [f"  • {e}" for e in edits]
    return "\n".join(lines)


async def _send_or_refresh_preview(
    client,
    session:     MiSession,
    ffmpeg_path: str,
    chat_id:     int,
    config,
    status_msg:  Optional[Message] = None,
) -> bool:
    async with session._lock:
        try:
            # ── Load current params from disk ─────────────────────────────────
            us     = UserSettings(session.user_id, config.paths)
            params = us.get_params()

            raw_path    = os.path.join(session.temp_dir, "raw_partial")
            new_preview = os.path.join(
                session.temp_dir, f"preview_{uuid.uuid4().hex[:8]}.mkv"
            )

            if not os.path.exists(raw_path):
                return False

            cmd = await _build_preview_command(
                ffmpeg_path, raw_path, new_preview, session, params
            )
            ok, err = await _run_ffmpeg(*cmd)

            if not ok or not os.path.exists(new_preview):
                if status_msg:
                    await status_msg.edit_text(
                        f"Preview failed.\n<code>{err[:300]}</code>",
                        parse_mode=enums.ParseMode.HTML,
                    )
                return False

            # ── Replace old preview message ───────────────────────────────────
            if session.preview_msg_id:
                try:
                    await client.delete_messages(chat_id, session.preview_msg_id)
                except Exception:
                    pass
                session.preview_msg_id = None

            if session.preview_path and os.path.exists(session.preview_path):
                try:
                    os.remove(session.preview_path)
                except Exception:
                    pass
            session.preview_path = new_preview

            caption = _preview_caption(session, params)
            msg = await client.send_video(
                chat_id=chat_id,
                video=new_preview,
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_main_keyboard(),
                supports_streaming=True,
            )
            session.preview_msg_id = msg.id
            session.nav_state      = "main"
            return True

        except Exception as e:
            if status_msg:
                try:
                    await status_msg.edit_text(
                        f"Error: <code>{str(e)[:300]}</code>",
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass
            return False


async def _rebuild_preview(client, cq: CallbackQuery, session: MiSession, config):
    chat_id = cq.message.chat.id
    try:
        await cq.message.edit_reply_markup(InlineKeyboardMarkup([]))
    except Exception:
        pass
    status = await cq.message.reply_text(
        "<b>Rebuilding preview…</b>", parse_mode=enums.ParseMode.HTML
    )
    ok = await _send_or_refresh_preview(
        client, session, config.paths.ffmpeg, chat_id, config, status
    )
    if ok:
        try:
            await status.delete()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Session lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

async def _close_session(client, user_id: int, chat_id: int):
    session = _sessions.pop(user_id, None)
    if session is None:
        return
    if session.preview_msg_id:
        try:
            await client.delete_messages(chat_id, session.preview_msg_id)
        except Exception:
            pass
    if os.path.exists(session.temp_dir):
        shutil.rmtree(session.temp_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# /mi command
# ═══════════════════════════════════════════════════════════════════════════════

async def mediainfo_command(client, message: Message, config):
    user_id = message.from_user.id
    if user_id not in config.admin_ids:
        await message.reply_text("Dukhi Atma! 😔")
        return

    chat_id = message.chat.id
    await _close_session(client, user_id, chat_id)

    reply = message.reply_to_message
    if not reply or not (
        reply.document or reply.video or reply.audio
        or reply.voice  or reply.animation or reply.video_note
    ):
        await message.reply_text(
            "<b>Usage:</b> Reply to a media file with <code>/mi</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    media    = (reply.document or reply.video or reply.audio
                or reply.voice or reply.animation or reply.video_note)
    filename = getattr(media, "file_name", None) or f"{getattr(media, 'file_unique_id', 'media')}.mkv"
    file_size = getattr(media, "file_size", 0) or 0

    temp_dir = os.path.join(config.paths.tmp, f"mi_{user_id}_{uuid.uuid4().hex[:8]}")
    os.makedirs(temp_dir, exist_ok=True)

    session = MiSession(
        user_id=user_id, file_id=media.file_id,
        filename=filename, file_size=file_size, temp_dir=temp_dir,
    )
    _sessions[user_id] = session

    status_msg = await message.reply_text(
        "<b>Downloading partial file for preview…</b>",
        parse_mode=enums.ParseMode.HTML,
    )

    try:
        raw_path = os.path.join(temp_dir, "raw_partial")
        await _download_partial(client, media, raw_path)

        if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
            raise Exception("Partial download produced an empty file")

        await status_msg.edit_text("<b>Analysing media…</b>", parse_mode=enums.ParseMode.HTML)
        mi_helper  = MediaInfoHelper()
        media_info = await mi_helper.run_mediainfo(raw_path)
        session.audio_tracks, session.subtitle_tracks = _parse_tracks(media_info)

        await status_msg.edit_text(
            "<b>Generating 30-second preview…</b>", parse_mode=enums.ParseMode.HTML
        )
        ok = await _send_or_refresh_preview(
            client, session, config.paths.ffmpeg, chat_id, config, status_msg
        )
        if ok:
            await status_msg.delete()

    except asyncio.CancelledError:
        await _close_session(client, user_id, chat_id)
        raise
    except Exception as e:
        await status_msg.edit_text(
            f"<b>Error:</b> <code>{str(e)[:300]}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        await _close_session(client, user_id, chat_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Callback query handler
# ═══════════════════════════════════════════════════════════════════════════════

async def mi_callback(client, cq: CallbackQuery, config):
    data    = cq.data or ""
    user_id = cq.from_user.id
    chat_id = cq.message.chat.id

    if not data.startswith(f"{_CB}:"):
        return
    parts  = data.split(":")[1:]
    action = parts[0] if parts else ""

    # ── Close (no session needed) ─────────────────────────────────────────────
    if action == "close":
        await cq.answer("Session closed.")
        await _close_session(client, user_id, chat_id)
        return

    session = _sessions.get(user_id)
    if session is None:
        await cq.answer("No active session. Run /mi again.", show_alert=True)
        return

    # ── Cancel upload wait ────────────────────────────────────────────────────
    if action == "cancel_wait":
        session.waiting_for   = None
        session.waiting_param = None
        session.nav_state     = "main"
        await cq.answer("Cancelled.")
        await cq.message.edit_reply_markup(_main_keyboard())
        return

    # ── Back ──────────────────────────────────────────────────────────────────
    if action == "back":
        session.nav_state    = "main"
        session.confirm_data = None
        await cq.answer()
        await cq.message.edit_reply_markup(_main_keyboard())
        return

    # ── Generate Info Page ────────────────────────────────────────────────────
    if action == "info_page":
        await cq.answer("Generating…")
        if session.telegraph_url:
            await cq.message.reply_text(
                f"<b>MediaInfo:</b> <a href='{session.telegraph_url}'>Telegraph page</a>",
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return
        raw_path = os.path.join(session.temp_dir, "raw_partial")
        url, err = await _telegraph.generate_mediainfo(raw_path, session.filename)
        if err:
            await cq.message.reply_text(
                f"<b>Error:</b> <code>{err[:200]}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            session.telegraph_url = url
            await cq.message.reply_text(
                f"<b>MediaInfo:</b> <a href='{url}'>Telegraph page</a>",
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
        return

    # ──────────────────────────────────────────────────────────────────────────
    # PARAMETERS
    # ──────────────────────────────────────────────────────────────────────────

    if action == "params":
        us     = UserSettings(user_id, config.paths)
        params = us.get_params()
        session.nav_state = "params"
        await cq.answer()
        try:
            await cq.message.edit_text(
                _params_text(params),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_params_keyboard(params),
            )
        except Exception:
            await cq.message.reply_text(
                _params_text(params),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_params_keyboard(params),
            )
        return

    if action == "param_tap":
        key = parts[1] if len(parts) > 1 else ""
        if key not in _PARAM_META:
            await cq.answer("Unknown parameter.", show_alert=True)
            return

        ptype = _PARAM_META[key][1]

        if ptype == "toggle":
            us     = UserSettings(user_id, config.paths)
            params = us.get_params()
            new_val = not bool(params.get(key))
            us.update_param(key, new_val)
            params = us.get_params()
            label  = _PARAM_META[key][0]
            await cq.answer(f"{label} → {'ON' if new_val else 'OFF'}")
            try:
                await cq.message.edit_text(
                    _params_text(params),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=_params_keyboard(params),
                )
            except Exception:
                pass
            await _rebuild_preview(client, cq, session, config)

        else:
            us     = UserSettings(user_id, config.paths)
            params = us.get_params()
            label, _, hint = _PARAM_META[key]
            session.waiting_param = key
            session.nav_state     = "param_input"
            await cq.answer()
            prompt = await cq.message.reply_text(
                f"<b>{label}</b>\n"
                f"<i>{hint}</i>\n\n"
                f"Current: <code>{params.get(key)}</code>\n\n"
                "Send the new value, or press Cancel.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_cancel_keyboard(),
            )
            session.param_prompt_id = prompt.id
        return

    if action == "param_reset":
        us = UserSettings(user_id, config.paths)
        us.reset_params()
        params = us.get_params()
        await cq.answer("All parameters reset to defaults.")
        try:
            await cq.message.edit_text(
                _params_text(params),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_params_keyboard(params),
            )
        except Exception:
            pass
        await _rebuild_preview(client, cq, session, config)
        return

    # ──────────────────────────────────────────────────────────────────────────
    # ADD AUDIO / ADD SUBTITLE
    # ──────────────────────────────────────────────────────────────────────────

    if action == "add_audio":
        session.waiting_for = "audio"
        session.nav_state   = "waiting_audio"
        await cq.answer()
        await cq.message.edit_reply_markup(_cancel_keyboard())
        await cq.message.reply_text(
            "<b>Send a WAV / MP3 / AAC / M4A / FLAC audio file to mix into the preview.</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_cancel_keyboard(),
        )
        return

    if action == "add_sub":
        session.waiting_for = "subtitle"
        session.nav_state   = "waiting_sub"
        await cq.answer()
        await cq.message.edit_reply_markup(_cancel_keyboard())
        await cq.message.reply_text(
            "<b>Send a subtitle file (.srt / .ass / .vtt / .sup) to burn into the preview.</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_cancel_keyboard(),
        )
        return

    # ──────────────────────────────────────────────────────────────────────────
    # REMOVE AUDIO
    # ──────────────────────────────────────────────────────────────────────────

    if action == "rm_audio":
        if not session.audio_tracks:
            await cq.answer("No audio tracks found.", show_alert=True)
            return
        session.nav_state = "rm_audio"
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.audio_tracks, "rm_audio_pick", session.remove_audio)
        )
        return

    if action == "rm_audio_pick":
        idx  = int(parts[1])
        lang = session.audio_tracks[idx].get("language", f"Track {idx + 1}")
        session.nav_state    = "rm_audio_confirm"
        session.confirm_data = idx
        await cq.answer()
        await cq.message.edit_reply_markup(
            _confirm_keyboard(_cb("rm_audio_yes", idx), _cb("rm_audio_no", idx))
        )
        await cq.message.reply_text(
            f"Remove audio track <b>{lang}</b>?",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if action == "rm_audio_yes":
        idx = int(parts[1])
        if idx not in session.remove_audio:
            session.remove_audio.append(idx)
        await cq.answer("Marked for removal. Rebuilding…")
        await _rebuild_preview(client, cq, session, config)
        return

    if action == "rm_audio_no":
        session.nav_state    = "rm_audio"
        session.confirm_data = None
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.audio_tracks, "rm_audio_pick", session.remove_audio)
        )
        return

    # ──────────────────────────────────────────────────────────────────────────
    # REMOVE SUBTITLE
    # ──────────────────────────────────────────────────────────────────────────

    if action == "rm_sub":
        if not session.subtitle_tracks:
            await cq.answer("No subtitle tracks found.", show_alert=True)
            return
        session.nav_state = "rm_sub"
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.subtitle_tracks, "rm_sub_pick", session.remove_subtitle)
        )
        return

    if action == "rm_sub_pick":
        idx  = int(parts[1])
        lang = session.subtitle_tracks[idx].get("language", f"Track {idx + 1}")
        session.nav_state    = "rm_sub_confirm"
        session.confirm_data = idx
        await cq.answer()
        await cq.message.edit_reply_markup(
            _confirm_keyboard(_cb("rm_sub_yes", idx), _cb("rm_sub_no", idx))
        )
        await cq.message.reply_text(
            f"Remove subtitle track <b>{lang}</b>?",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if action == "rm_sub_yes":
        idx = int(parts[1])
        if idx not in session.remove_subtitle:
            session.remove_subtitle.append(idx)
        await cq.answer("Marked for removal. Rebuilding…")
        await _rebuild_preview(client, cq, session, config)
        return

    if action == "rm_sub_no":
        session.nav_state    = "rm_sub"
        session.confirm_data = None
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.subtitle_tracks, "rm_sub_pick", session.remove_subtitle)
        )
        return

    # ──────────────────────────────────────────────────────────────────────────
    # EXTRACT AUDIO
    # ──────────────────────────────────────────────────────────────────────────

    if action == "ex_audio":
        if not session.audio_tracks:
            await cq.answer("No audio tracks found.", show_alert=True)
            return
        session.nav_state = "ex_audio"
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.audio_tracks, "ex_audio_pick", session.extract_audio)
        )
        return

    if action == "ex_audio_pick":
        idx  = int(parts[1])
        lang = session.audio_tracks[idx].get("language", f"Track {idx + 1}")
        session.nav_state    = "ex_audio_confirm"
        session.confirm_data = idx
        await cq.answer()
        await cq.message.edit_reply_markup(
            _confirm_keyboard(_cb("ex_audio_yes", idx), _cb("ex_audio_no", idx))
        )
        await cq.message.reply_text(
            f"Extract audio track <b>{lang}</b>?",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if action == "ex_audio_yes":
        idx   = int(parts[1])
        codec = session.audio_tracks[idx].get("codec", "")
        await cq.answer("Extracting…")
        status = await cq.message.reply_text(
            "Extracting audio…", parse_mode=enums.ParseMode.HTML
        )
        raw_path = os.path.join(session.temp_dir, "raw_partial")
        out = await _extract_audio_track(config.paths.ffmpeg, raw_path, idx, session.temp_dir, codec)
        if out and os.path.exists(out):
            if idx not in session.extract_audio:
                session.extract_audio.append(idx)
            lang = session.audio_tracks[idx].get("language", f"Track {idx + 1}")
            await status.delete()
            await client.send_document(
                chat_id=chat_id, document=out,
                caption=f"Extracted audio: <b>{lang}</b> (30-s preview)",
                parse_mode=enums.ParseMode.HTML,
            )
            try:
                os.remove(out)
            except Exception:
                pass
        else:
            await status.edit_text("Extraction failed.", parse_mode=enums.ParseMode.HTML)
        session.nav_state    = "ex_audio"
        session.confirm_data = None
        try:
            await cq.message.edit_reply_markup(
                _track_keyboard(session.audio_tracks, "ex_audio_pick", session.extract_audio)
            )
        except Exception:
            pass
        return

    if action == "ex_audio_no":
        session.nav_state    = "ex_audio"
        session.confirm_data = None
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.audio_tracks, "ex_audio_pick", session.extract_audio)
        )
        return

    # ──────────────────────────────────────────────────────────────────────────
    # EXTRACT SUBTITLE
    # ──────────────────────────────────────────────────────────────────────────

    if action == "ex_sub":
        if not session.subtitle_tracks:
            await cq.answer("No subtitle tracks found.", show_alert=True)
            return
        session.nav_state = "ex_sub"
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.subtitle_tracks, "ex_sub_pick", session.extract_subtitle)
        )
        return

    if action == "ex_sub_pick":
        idx  = int(parts[1])
        lang = session.subtitle_tracks[idx].get("language", f"Track {idx + 1}")
        session.nav_state    = "ex_sub_confirm"
        session.confirm_data = idx
        await cq.answer()
        await cq.message.edit_reply_markup(
            _confirm_keyboard(_cb("ex_sub_yes", idx), _cb("ex_sub_no", idx))
        )
        await cq.message.reply_text(
            f"Extract subtitle track <b>{lang}</b>?",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if action == "ex_sub_yes":
        idx   = int(parts[1])
        codec = session.subtitle_tracks[idx].get("codec", "")
        await cq.answer("Extracting…")
        status = await cq.message.reply_text(
            "Extracting subtitle…", parse_mode=enums.ParseMode.HTML
        )
        raw_path = os.path.join(session.temp_dir, "raw_partial")
        out = await _extract_subtitle_track(config.paths.ffmpeg, raw_path, idx, session.temp_dir, codec)
        if out and os.path.exists(out):
            if idx not in session.extract_subtitle:
                session.extract_subtitle.append(idx)
            lang = session.subtitle_tracks[idx].get("language", f"Track {idx + 1}")
            await status.delete()
            await client.send_document(
                chat_id=chat_id, document=out,
                caption=f"Extracted subtitle: <b>{lang}</b> (30-s preview)",
                parse_mode=enums.ParseMode.HTML,
            )
            try:
                os.remove(out)
            except Exception:
                pass
        else:
            await status.edit_text("Extraction failed.", parse_mode=enums.ParseMode.HTML)
        session.nav_state    = "ex_sub"
        session.confirm_data = None
        try:
            await cq.message.edit_reply_markup(
                _track_keyboard(session.subtitle_tracks, "ex_sub_pick", session.extract_subtitle)
            )
        except Exception:
            pass
        return

    if action == "ex_sub_no":
        session.nav_state    = "ex_sub"
        session.confirm_data = None
        await cq.answer()
        await cq.message.edit_reply_markup(
            _track_keyboard(session.subtitle_tracks, "ex_sub_pick", session.extract_subtitle)
        )
        return
    if action == "apply_all":
        await _handle_apply_all(client, cq, session, config)
        return

    await cq.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# Incoming message handler  (uploads + param text input)
# ═══════════════════════════════════════════════════════════════════════════════

async def mi_message_handler(client, message: Message, config):
    user_id = message.from_user.id
    session = _sessions.get(user_id)
    if session is None:
        return

    chat_id = message.chat.id
    if session.waiting_param and message.text:
        key   = session.waiting_param
        label, ptype, hint = _PARAM_META.get(key, (key, "str", ""))
        raw   = message.text.strip()

        parsed_val = None
        error_msg  = None

        try:
            if ptype == "float":
                parsed_val = float(raw)
            elif ptype == "int":
                parsed_val = int(raw)
            else:
                parsed_val = raw
        except ValueError:
            error_msg = f"Invalid value for <b>{label}</b>. Expected a {ptype}."

        if error_msg:
            await message.reply_text(error_msg, parse_mode=enums.ParseMode.HTML)
            return
        us = UserSettings(user_id, config.paths)
        us.update_param(key, parsed_val)
        params = us.get_params()
        if session.param_prompt_id:
            try:
                await client.delete_messages(chat_id, session.param_prompt_id)
            except Exception:
                pass
            session.param_prompt_id = None
        try:
            await message.delete()
        except Exception:
            pass

        session.waiting_param = None
        session.nav_state     = "params"
        pm = await message.reply_text(
            _params_text(params),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_params_keyboard(params),
        )
        status = await message.reply_text(
            "<b>Rebuilding preview…</b>", parse_mode=enums.ParseMode.HTML
        )
        ok = await _send_or_refresh_preview(
            client, session, config.paths.ffmpeg, chat_id, config, status
        )
        if ok:
            try:
                await status.delete()
            except Exception:
                pass
        return
    if session.waiting_for is None:
        return

    waiting = session.waiting_for
    doc     = message.document or message.audio or message.voice
    if doc is None:
        return

    file_name = getattr(doc, "file_name", None) or "upload"
    ext       = os.path.splitext(file_name)[1].lower()

    # ── Add Audio ─────────────────────────────────────────────────────────────
    if waiting == "audio":
        if ext not in (".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus"):
            await message.reply_text(
                "Send a valid audio file (WAV, MP3, AAC, M4A, FLAC, OGG, OPUS).",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        status = await message.reply_text(
            "<b>Downloading audio…</b>", parse_mode=enums.ParseMode.HTML
        )
        tmp_audio = os.path.join(session.temp_dir, f"uploaded_audio{ext}")
        await client.download_media(doc, file_name=tmp_audio)

        trimmed = os.path.join(session.temp_dir, "added_audio_30s.wav")
        ok, err = await _run_ffmpeg(
            config.paths.ffmpeg, "-y",
            "-ss", "0", "-t", str(PREVIEW_DURATION),
            "-i", tmp_audio,
            "-acodec", "pcm_s16le", trimmed,
        )
        try:
            os.remove(tmp_audio)
        except Exception:
            pass

        if not ok or not os.path.exists(trimmed):
            await status.edit_text(
                f"Could not process audio.\n<code>{err[:200]}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        session.added_audio_path = trimmed
        session.waiting_for      = None
        await status.edit_text("<b>Rebuilding preview…</b>", parse_mode=enums.ParseMode.HTML)
        ok2 = await _send_or_refresh_preview(
            client, session, config.paths.ffmpeg, chat_id, config, status
        )
        if ok2:
            try:
                await status.delete()
            except Exception:
                pass

    # ── Add Subtitle ──────────────────────────────────────────────────────────
    elif waiting == "subtitle":
        if ext not in (".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"):
            await message.reply_text(
                "Send a subtitle file (.srt, .ass, .vtt, .sup, etc.).",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        status = await message.reply_text(
            "<b>Downloading subtitle…</b>", parse_mode=enums.ParseMode.HTML
        )
        sub_path = os.path.join(session.temp_dir, f"added_subtitle{ext}")
        await client.download_media(doc, file_name=sub_path)

        if not os.path.exists(sub_path) or os.path.getsize(sub_path) == 0:
            await status.edit_text(
                "Failed to download subtitle.", parse_mode=enums.ParseMode.HTML
            )
            return

        session.added_sub_path = sub_path
        session.waiting_for    = None
        await status.edit_text("<b>Rebuilding preview…</b>", parse_mode=enums.ParseMode.HTML)
        ok2 = await _send_or_refresh_preview(
            client, session, config.paths.ffmpeg, chat_id, config, status
        )
        if ok2:
            try:
                await status.delete()
            except Exception:
                pass

# ══════════════════════════════Handler registration═════════════════════════════════════════════════

def setup_mediainfo_handlers(app, config):
    allowed = filters.chat(config.allowed_group_ids) | filters.private
    async def _cmd(client, message: Message):
        await mediainfo_command(client, message, config)

    app.add_handler(
        MessageHandler(
            _cmd,
            filters.command(["mi", "mediainfo"]) & allowed,
        )
    )
    async def _cb_handler(client, cq: CallbackQuery):
        await mi_callback(client, cq, config)

    app.add_handler(
        CallbackQueryHandler(
            _cb_handler,
            filters.regex(rf"^{_CB}:"),
        )
    )
    async def _msg_handler(client, message: Message):
        await mi_message_handler(client, message, config)

    app.add_handler(
        MessageHandler(
            _msg_handler,
            (filters.text | filters.document | filters.audio | filters.voice) & allowed,
        )
    )

def _has_any_mi_edit(session: MiSession) -> bool:
    return bool(
        session.remove_audio
        or session.remove_subtitle
        or session.added_audio_path
        or session.added_sub_path
    )


def _mi_has_active_job(task_queue, user_id: int) -> bool:
    for task in task_queue.tasks.values():
        if task.get("user_id") == user_id and task.get("mi_apply") and \
                task.get("status") not in ("done", "failed", "cancelled"):
            return True
    return False


def _build_apply_all_ffmpeg_cmd(
    ffmpeg_path:   str,
    input_path:    str,
    output_path:   str,
    session:       MiSession,
    params:        dict,
    added_audio:   Optional[str],
    added_sub:     Optional[str],
) -> List[str]:
    n_audio = len(session.audio_tracks)
    n_sub   = len(session.subtitle_tracks)

    keep_audio = [i for i in range(n_audio) if i not in session.remove_audio]
    keep_sub   = [i for i in range(n_sub)   if i not in session.remove_subtitle]

    cmd: List[str] = [ffmpeg_path, "-y"]

    # Global fflags
    cmd += _build_fflags(params)
    if params.get("copy_timestamps"):
        cmd += ["-copyts"]
    if params.get("fix_sub_duration"):
        cmd += ["-fix_sub_duration"]
    cmd += ["-i", input_path]
    extra_audio_input_idx = None
    if added_audio and os.path.exists(added_audio):
        ao = params.get("audio_offset", 0.0)
        if ao:
            cmd += ["-itsoffset", str(ao)]
        cmd += ["-i", added_audio]
        extra_audio_input_idx = 1
    maps: List[str] = ["-map", "0:v:0"]
    for ai in keep_audio:
        maps += ["-map", f"0:a:{ai}"]
    if extra_audio_input_idx is not None:
        maps += ["-map", f"{extra_audio_input_idx}:a:0"]
    for si in keep_sub:
        maps += ["-map", f"0:s:{si}"]
    cmd += maps
    vf_parts: List[str] = []
    fps = params.get("video_fps", "source")
    if fps and fps != "source":
        vf_parts.append(f"fps={fps}")
    vpts = params.get("video_pts", "")
    if vpts:
        vf_parts.append(f"setpts={vpts}")
    if added_sub and os.path.exists(added_sub):
        so      = params.get("subtitle_offset", 0.0)
        sub_esc = added_sub.replace("\\", "/").replace(":", "\\:")
        if so:
            vf_parts.append(f"subtitles='{sub_esc}':si=0,setpts=PTS+{so}/TB")
        else:
            vf_parts.append(f"subtitles='{sub_esc}'")

    needs_reencode = bool(vf_parts or added_sub)
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]
    af_parts: List[str] = []
    async_val = params.get("audio_async", 0)
    if async_val and int(async_val) > 0:
        af_parts.append(f"aresample=async={int(async_val)}")
    tempo = params.get("audio_tempo", 1.0)
    if tempo and float(tempo) != 1.0:
        af_parts.append(f"atempo={float(tempo)}")
    apts = params.get("audio_pts", "")
    if apts:
        af_parts.append(f"asetpts={apts}")
    if params.get("audio_pad"):
        af_parts.append("apad")
    if af_parts:
        cmd += ["-af", ",".join(af_parts)]
        needs_reencode = True
    if needs_reencode:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "23"]
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c:v", "copy", "-c:a", "copy"]
    cmd += ["-c:s", "copy"]
    vsync = params.get("video_vsync", "cfr")
    if vsync:
        cmd += ["-vsync", str(vsync)]
    if params.get("shortest"):
        cmd.append("-shortest")
    if params.get("start_at_zero"):
        cmd.append("-start_at_zero")

    cmd.append(output_path)
    return cmd


async def _mi_apply_worker(
    client,
    task_queue,
    task:        dict,
    session:     MiSession,
    config,
):
    task_id  = task["task_id"]
    user_id  = task["user_id"]
    chat_id  = task["chat_id"]
    filename = task["original_filename"]

    mi_tmp = os.path.join(config.paths.tmp, f"mi_apply_{task_id}")
    os.makedirs(mi_tmp, exist_ok=True)

    async def _notify(text: str):
        try:
            await client.send_message(user_id, text, parse_mode="html")
        except Exception:
            pass

    try:
        # ── 1. Download full file ─────────────────────────────────────────────
        task_queue.update_status(task_id, "downloading", 0)
        await _notify(f"<b>Downloading full file for Apply All…</b>\n<code>{task_id[:8]}</code>")

        full_path = os.path.join(mi_tmp, filename)
        from src.services.downloader import Downloader
        dl = Downloader(mi_tmp, task_queue, task_id)
        download_task_data = {
            "task_id":            task_id,
            "file_id":            task["file_id"],
            "original_file_name": filename,
            "file_size":          task.get("file_size", 0),
        }
        downloaded_path = await dl.download(client=client, task_data=download_task_data)

        if not downloaded_path or not os.path.exists(downloaded_path):
            raise Exception("Full download failed — file missing after download")

        # ── 2. FFmpeg apply ───────────────────────────────────────────────────
        task_queue.update_status(task_id, "encoding", 0)
        await _notify("<b>Applying edits to full file…</b>")

        params      = task["mi_params"]
        added_audio = task.get("added_audio_path")
        added_sub   = task.get("added_sub_path")
        base, ext    = os.path.splitext(filename)
        output_name  = f"{base} [Edited]{ext}" if ext else f"{base}_edited"
        output_path  = os.path.join(mi_tmp, output_name)
        if added_audio and os.path.exists(added_audio):
            tmp_audio = os.path.join(mi_tmp, "added_audio" + os.path.splitext(added_audio)[1])
            import shutil as _shutil
            _shutil.copy2(added_audio, tmp_audio)
            added_audio = tmp_audio

        if added_sub and os.path.exists(added_sub):
            tmp_sub = os.path.join(mi_tmp, "added_sub" + os.path.splitext(added_sub)[1])
            import shutil as _shutil
            _shutil.copy2(added_sub, tmp_sub)
            added_sub = tmp_sub

        cmd = _build_apply_all_ffmpeg_cmd(
            config.paths.ffmpeg,
            downloaded_path,
            output_path,
            session,
            params,
            added_audio,
            added_sub,
        )

        ok, err = await _run_ffmpeg(*cmd)

        if not ok or not os.path.exists(output_path):
            raise Exception(f"FFmpeg apply failed: {err[:300]}")

        task_queue.update_status(task_id, "encoding", 100)

        # ── 3. Upload result ──────────────────────────────────────────────────
        task_queue.update_status(task_id, "uploading", 0)
        await _notify("<b>Uploading edited file…</b>")

        from src.services.uploader import Uploader

        upload_task_data = {
            "task_id":         task_id,
            "user_id":         user_id,
            "output_filename": output_name,
            "send_type":       "doc",   
            "thumbnail_path":  "",
            "upload_file_path": output_path,
        }
        user_is_premium = False
        try:
            tg_user         = await client.get_users(user_id)
            user_is_premium = bool(getattr(tg_user, "is_premium", False))
        except Exception:
            pass

        uploader = Uploader(
            client,
            upload_task_data,
            task_queue,
            tmp_dir=mi_tmp,
            ffmpeg=None,
            user_is_premium=user_is_premium,
        )
        await uploader.upload()

        task_queue.update_status(task_id, "uploading", 100)
        await _notify(f"<b>Done!</b> Applied all edits to <code>{filename}</code>.")

    except asyncio.CancelledError:
        await _notify(f"Apply All for <code>{task_id[:8]}</code> was cancelled.")
        raise

    except Exception as e:
        print(f"[MI Apply] Task {task_id} failed: {e}")
        await _notify(f"<b>Apply All failed.</b>\n<code>{str(e)[:300]}</code>")

    finally:
        task_queue.remove_task(task_id)
        import shutil as _shutil
        _shutil.rmtree(mi_tmp, ignore_errors=True)


async def _handle_apply_all(client, cq: CallbackQuery, session: MiSession, config):
    user_id = session.user_id
    task_queue = getattr(config, "task_queue", None)
    if task_queue is None:
        await cq.answer("Task queue not available.", show_alert=True)
        return
    if session.mi_task_id:
        existing = task_queue.get_task(session.mi_task_id)
        if existing and existing.get("status") not in ("done", "failed", "cancelled"):
            pos = task_queue.get_queue_position(session.mi_task_id)
            await cq.answer(
                f"You already have an active Apply All job.\n"
                f"Status: {existing['status']}  Position: {pos}",
                show_alert=True,
            )
            return
    if _mi_has_active_job(task_queue, user_id):
        await cq.answer(
            "You already have an active media processing job.\n"
            "Please wait until it finishes.",
            show_alert=True,
        )
        return
    if not _has_any_mi_edit(session):
        await cq.answer(
            "No edits to apply.\n"
            "Add/remove audio or subtitle tracks first.",
            show_alert=True,
        )
        return

    await cq.answer("Adding to queue…")
    us     = UserSettings(user_id, config.paths)
    params = us.get_params()
    task_data = {
        "user_id":           user_id,
        "chat_id":           cq.message.chat.id,
        "file_id":           session.file_id,
        "file_size":         session.file_size,
        "original_filename": session.filename,
        "mi_apply":          True,
        "mi_params":         params,
        "remove_audio":      list(session.remove_audio),
        "remove_subtitle":   list(session.remove_subtitle),
        "added_audio_path":  session.added_audio_path,
        "added_sub_path":    session.added_sub_path,
    }
    task_id = task_queue.create_task(task_data)
    task    = task_queue.get_task(task_id)
    session.mi_task_id = task_id
    asyncio.create_task(
        _mi_apply_worker(client, task_queue, task, session, config),
        name=f"mi_apply_{task_id}",
    )
    pos = task_queue.get_queue_position(task_id) or 1
    try:
        await cq.message.reply_text(
            f"<b>Apply All queued.</b>\n"
            f"Task: <code>{task_id[:8]}</code>\n"
            f"Position: <b>{pos}</b>\n\n"
            f"You'll be notified when it's done.",
            parse_mode="html",
        )
    except Exception:
        pass