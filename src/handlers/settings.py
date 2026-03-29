from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
import os
from src import Config
from pyrogram.enums import ParseMode

config = Config()
RESOLUTION_OPTIONS = ["HDRip", "1080p", "720p", "480p"]

PRESET_OPTIONS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
CODEC_OPTIONS  = ["libx264", "libx265"]
AUDIO_OPTIONS  = ["96k", "128k", "192k", "256k", "320k"]

DEFAULT_PROFILES = {
    "1080p": {"crf": 23, "preset": "medium", "codec": "libx264", "audio_bitrate": "192k"},
    "720p":  {"crf": 26, "preset": "medium", "codec": "libx264", "audio_bitrate": "128k"},
    "480p":  {"crf": 28, "preset": "fast",   "codec": "libx264", "audio_bitrate": "96k"},
}

WM_POSITION_LABELS = {
    "top_left":  "↖ Top Left",
    "top_mid":   "⬆ Top Mid",
    "top_right": "↗ Top Right",
    "mid_left":  "◀ Mid Left",
    "mid_right": "▶ Mid Right",
    "bot_left":  "↙ Bot Left",
    "bot_right": "↘ Bot Right",
}


# ── Text builders ─────────────────────────────────────────────────────────────

def format_resolutions(settings):
    resolutions = settings.get("resolutions") or [settings.get("resolution", "1080p")]
    return ", ".join(resolutions)


def format_profile_summary(profile, resolution):
    if resolution == "HDRip":
        return "  <i>HDRip</i> — metadata only <i>(no re-encode)</i>"
    crf    = profile.get("crf", 23)
    preset = profile.get("preset", "medium")
    codec  = profile.get("codec", "libx264")
    audio  = profile.get("audio_bitrate", "128k")
    return (
        f"  <b>{resolution}</b>  "
        f"CRF <code>{crf}</code> · "
        f"<code>{preset}</code> · "
        f"<code>{codec}</code> · "
        f"<code>{audio}</code>"
    )


def build_settings_text(name, username, user_id, settings):
    profiles     = settings.get("profiles", {})
    has_thumb    = settings["thumbnail_path"] and os.path.exists(settings["thumbnail_path"])
    thumb_status = "<u>Set ✓</u>" if has_thumb else "<i>Not set</i>"
    send_type    = "Media" if settings["send_type"] == "media" else "Document"
    meta         = settings["metadata"]

    profile_lines = "\n".join([
        format_profile_summary(profiles.get(res, {}), res)
        for res in ["HDRip", "1080p", "720p", "480p"]
    ])

    wm = settings.get("watermark", {})
    wm_on   = wm.get("enabled", False)
    wm_text = wm.get("text", "") or "—"
    wm_pos  = WM_POSITION_LABELS.get(wm.get("position", "bot_right"), "Bot Right")
    wm_color = wm.get("color", "white").capitalize()
    if wm_on:
        wm_summary = f"<u>On ✓</u>  <code>{wm_text}</code>  {wm_pos}  {wm_color}"
    else:
        wm_summary = "<i>Off</i>"

    return (
        "<b>Encoding Settings</b>\n\n"
        f"<b>User:</b> {name} (@{username if username else 'N/A'})\n"
        f"<b>ID:</b> <code>{user_id}</code>\n\n"
        f"<b>Selected Resolutions:</b> <code>{format_resolutions(settings)}</code>\n\n"
        "<b>Quality Profiles:</b>\n"
        f"<blockquote>{profile_lines}</blockquote>\n"
        f"<b>Send Type:</b> <code>{send_type}</code>\n\n"
        "<b>Metadata:</b>\n"
        "<blockquote>"
        f"Title   : <code>{meta['title'] or '—'}</code>\n"
        f"Author  : <code>{meta['author'] or '—'}</code>\n"
        f"Encoder : <code>{meta['encoder'] or '—'}</code>"
        "</blockquote>\n"
        f"<b>Thumbnail:</b> {thumb_status}\n\n"
        f"<b>Watermark:</b> {wm_summary}"
    )


def build_profile_text(resolution, profile, subtitle=""):
    crf    = profile.get("crf", 23)
    preset = profile.get("preset", "medium")
    codec  = profile.get("codec", "libx264")
    audio  = profile.get("audio_bitrate", "128k")
    extra  = f"\n<i>{subtitle}</i>" if subtitle else ""
    return (
        f"<b>{resolution} Profile</b>{extra}\n\n"
        f"CRF    : <code>{crf}</code>  <i>(lower = better quality)</i>\n"
        f"Preset : <code>{preset}</code>\n"
        f"Codec  : <code>{codec}</code>\n"
        f"Audio  : <code>{audio}</code>\n\n"
        "<i>Tap any button below to change a setting.</i>"
    )


def build_watermark_text(wm: dict, subtitle: str = "") -> str:
    enabled     = wm.get("enabled", False)
    text        = wm.get("text", "") or "—"
    color       = wm.get("color", "white").capitalize()
    font_name   = wm.get("font_name", "default")
    font_size   = wm.get("font_size", 24)
    padding     = wm.get("padding", 7)
    timing_mode = wm.get("timing_mode", "range")
    position    = WM_POSITION_LABELS.get(wm.get("position", "bot_right"), "Bot Right")
    extra       = f"\n<i>{subtitle}</i>" if subtitle else ""

    if timing_mode == "full":
        timing_str = "Full Duration"
    elif timing_mode == "range":
        timing_str = f"Range  <code>{wm.get('start', 0)}s → {wm.get('end', 0)}s</code>"
    else:
        timing_str = f"Random  <code>{wm.get('duration', 30)}s</code> duration"

    status = "Enabled" if enabled else "Disabled"

    return (
        f"<b>Watermark</b>{extra}\n\n"
        f"Status    : {status}\n"
        f"Text      : <code>{text}</code>\n"
        f"Color     : <code>{color}</code>\n"
        f"Font      : <code>{font_name}</code>\n"
        f"Font Size : <code>{font_size}px</code>\n"
        f"Padding   : <code>{padding}%</code>\n"
        f"Timing    : {timing_str}\n"
        f"Position  : {position}\n\n"
        "<i>HDRip jobs skip the watermark (stream-copy, no re-encode).</i>"
    )


# ── Keyboard builders ─────────────────────────────────────────────────────────

def build_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Resolutions",      callback_data="set_resolution")],
        [InlineKeyboardButton("Quality Profiles", callback_data="set_profiles")],
        [InlineKeyboardButton("Send Type",        callback_data="set_send_type")],
        [InlineKeyboardButton("Metadata",         callback_data="set_metadata")],
        [InlineKeyboardButton("Thumbnail",        callback_data="set_thumbnail")],
        [InlineKeyboardButton("Watermark",        callback_data="set_watermark")],
        [InlineKeyboardButton("Reset All",        callback_data="reset_settings"),
         InlineKeyboardButton("Close",            callback_data="close_menu")],
    ])


def build_resolution_keyboard(settings):
    selected = set(settings.get("resolutions") or [settings.get("resolution", "1080p")])

    def btn(res):
        return f"☑ {res}" if res in selected else f"☐ {res}"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn("HDRip"), callback_data="res_toggle_HDRip"),
         InlineKeyboardButton(btn("1080p"), callback_data="res_toggle_1080p")],
        [InlineKeyboardButton(btn("720p"),  callback_data="res_toggle_720p"),
         InlineKeyboardButton(btn("480p"),  callback_data="res_toggle_480p")],
        [InlineKeyboardButton("Back", callback_data="back_to_menu")],
    ])


def build_profiles_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1080p", callback_data="profile_res_1080p")],
        [InlineKeyboardButton("720p",  callback_data="profile_res_720p")],
        [InlineKeyboardButton("480p",  callback_data="profile_res_480p")],
        [InlineKeyboardButton("Back", callback_data="back_to_menu"),
         InlineKeyboardButton("Reset", callback_data="profile_reset_all")],
    ])


def build_preset_keyboard(resolution, current_preset):
    buttons = []
    row = []
    for preset in PRESET_OPTIONS:
        label = f"☑ {preset}" if preset == current_preset else preset
        row.append(InlineKeyboardButton(label, callback_data=f"profile_set_{resolution}_preset_{preset}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("Back", callback_data=f"profile_res_{resolution}")])
    return InlineKeyboardMarkup(buttons)


def build_codec_keyboard(resolution, current_codec):
    def lbl(codec, display):
        return f"☑ {display}" if codec == current_codec else display

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl("libx264", "H.264 (libx264)"), callback_data=f"profile_set_{resolution}_codec_libx264"),
         InlineKeyboardButton(lbl("libx265", "H.265 (libx265)"), callback_data=f"profile_set_{resolution}_codec_libx265")],
        [InlineKeyboardButton("Back", callback_data=f"profile_res_{resolution}")]
    ])


def build_audio_keyboard(resolution, current_audio):
    buttons = []
    row = []
    for bitrate in AUDIO_OPTIONS:
        label = f"☑ {bitrate}" if bitrate == current_audio else bitrate
        row.append(InlineKeyboardButton(label, callback_data=f"profile_set_{resolution}_audio_{bitrate}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("Back", callback_data=f"profile_res_{resolution}")])
    return InlineKeyboardMarkup(buttons)


def build_profile_edit_keyboard(resolution, profile):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"CRF: {profile.get('crf', 23)}",               callback_data=f"profile_edit_{resolution}_crf")],
        [InlineKeyboardButton(f"Preset: {profile.get('preset', 'medium')}",   callback_data=f"profile_edit_{resolution}_preset")],
        [InlineKeyboardButton(f"Codec: {profile.get('codec', 'libx264')}",    callback_data=f"profile_edit_{resolution}_codec")],
        [InlineKeyboardButton(f"Audio: {profile.get('audio_bitrate','128k')}", callback_data=f"profile_edit_{resolution}_audio")],
        [InlineKeyboardButton("Back",                           callback_data="set_profiles"),
         InlineKeyboardButton(f"Reset",            callback_data=f"profile_reset_{resolution}")],
    ])


def build_watermark_keyboard(wm: dict) -> InlineKeyboardMarkup:
    enabled   = wm.get("enabled", False)
    toggle_lbl = "Enabled — tap to disable" if enabled else "Disabled — tap to enable"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_lbl,          callback_data="wm_toggle")],
        [InlineKeyboardButton("Text",           callback_data="wm_set_text"),
         InlineKeyboardButton("Color",          callback_data="wm_set_color")],
        [InlineKeyboardButton("Font",           callback_data="wm_set_font"),
         InlineKeyboardButton("Timing",         callback_data="wm_set_timing")],
        [InlineKeyboardButton("Font Size",      callback_data="wm_set_font_size"),
         InlineKeyboardButton("Padding",        callback_data="wm_set_padding")],
        [InlineKeyboardButton("Position",       callback_data="wm_set_position")],
        [InlineKeyboardButton("Back",            callback_data="back_to_menu"),
         InlineKeyboardButton("Reset", callback_data="wm_reset")],
    ])


def build_wm_color_keyboard(current: str) -> InlineKeyboardMarkup:
    def lbl(c):
        return f"☑ {c.capitalize()}" if c == current else c.capitalize()

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl("white"), callback_data="wm_color_white"),
         InlineKeyboardButton(lbl("black"), callback_data="wm_color_black")],
        [InlineKeyboardButton("Back", callback_data="set_watermark")],
    ])


def build_wm_timing_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    def lbl(mode, label):
        return f"[x] {label}" if mode == current_mode else label

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl("full",            "Full Duration"),     callback_data="wm_timing_full")],
        [InlineKeyboardButton(lbl("range",           "Start → End"),      callback_data="wm_timing_range")],
        [InlineKeyboardButton(lbl("random_duration", "Random Duration"),  callback_data="wm_timing_random")],
        [InlineKeyboardButton("Back", callback_data="set_watermark")],
    ])


def build_wm_position_keyboard(current: str) -> InlineKeyboardMarkup:
    def btn(key):
        label = WM_POSITION_LABELS[key]
        return InlineKeyboardButton(
            f"☑ {label}" if key == current else label,
            callback_data=f"wm_pos_{key}"
        )

    return InlineKeyboardMarkup([
        [btn("top_left"),  btn("top_mid"),   btn("top_right")],
        [btn("mid_left"),                    btn("mid_right")],
        [btn("bot_left"),                    btn("bot_right")],
        [InlineKeyboardButton("Back", callback_data="set_watermark")],
    ])


def build_cancel_keyboard(label: str = "Cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data="cancel_input")]
    ])


def get_thumbnail_path(settings):
    thumbnail_path = (
        settings["thumbnail_path"]
        if settings["thumbnail_path"] and os.path.exists(settings["thumbnail_path"])
        else "./src/bin/default.jpg"
    )
    return thumbnail_path if os.path.exists(thumbnail_path) else None


# ── Handler setup ─────────────────────────────────────────────────────────────

def setup_settings_handlers(app: Client, user_settings):

    @app.on_message(filters.command("es") & filters.private)
    async def us_command(client: Client, message: Message):
        if message.from_user.id not in config.admin_ids:
            await message.reply_text("Invalid!", parse_mode=ParseMode.HTML)
            return

        user     = message.from_user
        user_id  = user.id
        name     = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = user.username or ""
        settings = user_settings(user_id).get()

        text           = build_settings_text(name, username, user_id, settings)
        keyboard       = build_main_keyboard()
        thumbnail_path = get_thumbnail_path(settings)

        if thumbnail_path:
            try:
                await message.reply_photo(
                    photo=thumbnail_path, caption=text,
                    reply_markup=keyboard, parse_mode=ParseMode.HTML
                )
                return
            except Exception:
                pass

        await message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    # ── Main callback dispatcher ──────────────────────────────────────────────

    @app.on_callback_query(filters.regex(
        r"^(set_|res_|profile_|sendtype_|meta_|reset_|back_to|close_|wm_|cancel_input)"
    ))
    async def handle_settings_callbacks(client: Client, callback_query: CallbackQuery):
        user    = callback_query.from_user
        user_id = user.id
        data    = callback_query.data
        message = callback_query.message

        # ── Quality Profiles list ─────────────────────────────────────────────
        if data == "set_profiles":
            await message.edit_text(
                "<b>Quality Profiles</b>\n\n"
                "<blockquote>Select a resolution to customise its encoding settings.\n"
                "<i>HDRip is metadata-only and cannot be configured.</i></blockquote>",
                reply_markup=build_profiles_keyboard(),
                parse_mode=ParseMode.HTML
            )
            await callback_query.answer()
            return

        elif data.startswith("profile_edit_"):
            parts = data.split("_")
            if len(parts) >= 4:
                resolution = parts[2]
                setting    = parts[3]

                if setting == "crf":
                    sent_message = await message.edit_text(
                        f"<b>Set CRF — {resolution}</b>\n\n"
                        "<blockquote>Range: <code>0 – 58</code></blockquote>\n"
                        "Lower value → better quality, larger file\n"
                        "Higher value → smaller file, lower quality\n"
                        "<i>Please send a number...</i>",
                        reply_markup=build_cancel_keyboard(),
                        parse_mode=ParseMode.HTML
                    )
                    user_settings(user_id).temp_state[user_id] = {
                        "state": f"waiting_profile_{resolution}_crf",
                        "prompt_message_id": sent_message.id,
                        "back_to": f"profile_{resolution}",
                    }

                elif setting == "preset":
                    profile = user_settings(user_id).get_profile(resolution)
                    current = profile.get("preset", "medium")
                    await message.edit_text(
                        f"<b>Select Preset — {resolution}</b>\n\n"
                        f"Current: <code>{current}</code>\n"
                        "<blockquote><i>Faster presets encode quicker but reduce quality.\n"
                        "Slower presets give better compression.</i></blockquote>",
                        reply_markup=build_preset_keyboard(resolution, current),
                        parse_mode=ParseMode.HTML
                    )

                elif setting == "codec":
                    profile = user_settings(user_id).get_profile(resolution)
                    current = profile.get("codec", "libx264")
                    await message.edit_text(
                        f"<b>Select Codec — {resolution}</b>\n\n"
                        f"Current: <code>{current}</code>\n"
                        "<blockquote><b>H.264</b> — wider device compatibility\n"
                        "<b>H.265</b> — better compression, slower encode</blockquote>",
                        reply_markup=build_codec_keyboard(resolution, current),
                        parse_mode=ParseMode.HTML
                    )

                elif setting == "audio":
                    profile = user_settings(user_id).get_profile(resolution)
                    current = profile.get("audio_bitrate", "128k")
                    await message.edit_text(
                        f"<b>Select Audio Bitrate — {resolution}</b>\n\n"
                        f"Current: <code>{current}</code>\n"
                        "<blockquote><i>Higher bitrate = better audio quality, larger file.</i></blockquote>",
                        reply_markup=build_audio_keyboard(resolution, current),
                        parse_mode=ParseMode.HTML
                    )

                await callback_query.answer()
                return

        elif data.startswith("profile_set_"):
            parts = data.split("_")
            if len(parts) >= 5:
                resolution   = parts[2]
                setting_type = parts[3]
                value        = parts[4]

                if setting_type == "preset":
                    user_settings(user_id).update_profile(resolution, "preset", value)
                    await callback_query.answer(f"Preset → {value}")
                elif setting_type == "codec":
                    user_settings(user_id).update_profile(resolution, "codec", value)
                    await callback_query.answer(f"Codec → {value}")
                elif setting_type == "audio":
                    user_settings(user_id).update_profile(resolution, "audio_bitrate", value)
                    await callback_query.answer(f"Audio → {value}")

                profile = user_settings(user_id).get_profile(resolution)
                await message.edit_text(
                    build_profile_text(resolution, profile),
                    reply_markup=build_profile_edit_keyboard(resolution, profile),
                    parse_mode=ParseMode.HTML
                )
                return

        elif data.startswith("profile_reset_"):
            resolution = data.replace("profile_reset_", "")
            if resolution == "all":
                settings_obj = user_settings(user_id)
                for res, prof in DEFAULT_PROFILES.items():
                    settings_obj.update_profile(res, "crf",           prof["crf"])
                    settings_obj.update_profile(res, "preset",        prof["preset"])
                    settings_obj.update_profile(res, "codec",         prof["codec"])
                    settings_obj.update_profile(res, "audio_bitrate", prof["audio_bitrate"])
                await callback_query.answer("All profiles reset to defaults")
                await update_main_menu(client, message, user_id)
                return
            elif resolution in ["1080p", "720p", "480p"]:
                default = DEFAULT_PROFILES[resolution]
                us      = user_settings(user_id)
                us.update_profile(resolution, "crf",           default["crf"])
                us.update_profile(resolution, "preset",        default["preset"])
                us.update_profile(resolution, "codec",         default["codec"])
                us.update_profile(resolution, "audio_bitrate", default["audio_bitrate"])
                await callback_query.answer(f"{resolution} reset to defaults")
                profile = us.get_profile(resolution)
                await message.edit_text(
                    build_profile_text(resolution, profile, "Reset to default ✓"),
                    reply_markup=build_profile_edit_keyboard(resolution, profile),
                    parse_mode=ParseMode.HTML
                )
                return

        elif data.startswith("profile_res_"):
            resolution = data.replace("profile_res_", "")
            if resolution in ["1080p", "720p", "480p"]:
                profile = user_settings(user_id).get_profile(resolution)
                await message.edit_text(
                    build_profile_text(resolution, profile),
                    reply_markup=build_profile_edit_keyboard(resolution, profile),
                    parse_mode=ParseMode.HTML
                )
                await callback_query.answer()
                return

        # ── Resolution toggle ─────────────────────────────────────────────────

        elif data == "set_resolution":
            await update_resolution_menu(message, user_id)

        elif data.startswith("res_toggle_"):
            resolution = data.replace("res_toggle_", "", 1)
            changed, status_text = user_settings(user_id).toggle_resolution(resolution)
            await callback_query.answer(status_text, show_alert=not changed)
            await update_resolution_menu(message, user_id)
            return

        # ── Send type ─────────────────────────────────────────────────────────

        elif data == "set_send_type":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Media",    callback_data="sendtype_media"),
                 InlineKeyboardButton("Document", callback_data="sendtype_document")],
                [InlineKeyboardButton("Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "<b>Send Type</b>\n\n"
                "<blockquote><b>Media</b> — sent as streamable video\n"
                "<b>Document</b> — sent as a raw file</blockquote>",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

        elif data.startswith("sendtype_"):
            send_type = data.replace("sendtype_", "")
            user_settings(user_id).update("send_type", send_type)
            await callback_query.answer(f"Send type → {send_type.capitalize()}")
            await update_main_menu(client, message, user_id)
            return

        # ── Metadata ──────────────────────────────────────────────────────────

        elif data == "set_metadata":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Set Title",   callback_data="meta_title"),
                 InlineKeyboardButton("Set Author",  callback_data="meta_author")],
                [InlineKeyboardButton("Set Encoder", callback_data="meta_encoder"),
                 InlineKeyboardButton("Clear All",   callback_data="meta_clear")],
                [InlineKeyboardButton("Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "<b>Metadata</b>\n\n"
                "<blockquote>Title, author, and encoder tags are embedded\n"
                "directly into the output file.</blockquote>",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

        elif data == "meta_title":
            sent_message = await message.edit_text(
                "<b>Set Title</b>\n\nSend the title to embed in your videos.",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_title",
                "prompt_message_id": sent_message.id,
                "back_to": "metadata",
            }

        elif data == "meta_author":
            sent_message = await message.edit_text(
                "<b>Set Author</b>\n\nSend the author name to embed.",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_author",
                "prompt_message_id": sent_message.id,
                "back_to": "metadata",
            }

        elif data == "meta_encoder":
            sent_message = await message.edit_text(
                "<b>Set Encoder</b>\n\nSend the encoder name to embed.",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_encoder",
                "prompt_message_id": sent_message.id,
                "back_to": "metadata",
            }

        elif data == "meta_clear":
            user_settings(user_id).update_metadata(title="", author="", encoder="")
            await callback_query.answer("Metadata cleared")
            await update_main_menu(client, message, user_id)
            return

        # ── Thumbnail ─────────────────────────────────────────────────────────

        elif data == "set_thumbnail":
            sent_message = await message.edit_text(
                "<b>Set Thumbnail</b>\n\nSend an image to use as the video thumbnail.",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_thumbnail",
                "prompt_message_id": sent_message.id,
                "back_to": "main",
            }

        # ── Watermark ─────────────────────────────────────────────────────────

        elif data == "set_watermark":
            wm = user_settings(user_id).get_watermark()
            await message.edit_text(
                build_watermark_text(wm),
                reply_markup=build_watermark_keyboard(wm),
                parse_mode=ParseMode.HTML
            )
            await callback_query.answer()
            return

        elif data == "wm_toggle":
            us = user_settings(user_id)
            wm = us.get_watermark()
            new_state = not wm.get("enabled", False)
            us.update_watermark(enabled=new_state)
            wm = us.get_watermark()
            await callback_query.answer("Watermark enabled ✓" if new_state else "Watermark disabled")
            await message.edit_text(
                build_watermark_text(wm),
                reply_markup=build_watermark_keyboard(wm),
                parse_mode=ParseMode.HTML
            )
            return

        elif data == "wm_set_text":
            sent_message = await message.edit_text(
                "<b>Watermark Text</b>\n\n"
                "Send the text to display on the video.\n"
                "<i>Example: <code>My Channel</code></i>\n\n",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_wm_text",
                "prompt_message_id": sent_message.id,
                "back_to": "watermark",
            }
            await callback_query.answer()
            return

        elif data == "wm_set_color":
            wm = user_settings(user_id).get_watermark()
            await message.edit_text(
                "<b>Watermark Color</b>\n\nChoose the text color.",
                reply_markup=build_wm_color_keyboard(wm.get("color", "white")),
                parse_mode=ParseMode.HTML
            )
            await callback_query.answer()
            return

        elif data.startswith("wm_color_"):
            color = data.replace("wm_color_", "")
            if color in ("white", "black"):
                user_settings(user_id).update_watermark(color=color)
                await callback_query.answer(f"Color → {color.capitalize()}")
            wm = user_settings(user_id).get_watermark()
            await message.edit_text(
                build_watermark_text(wm, f"Color set to {color} ✓"),
                reply_markup=build_watermark_keyboard(wm),
                parse_mode=ParseMode.HTML
            )
            return

        elif data == "wm_set_font":
            sent_message = await message.edit_text(
                "<b>Watermark Font</b>\n\n"
                "Send a <code>.ttf</code> or <code>.otf</code> font file to use a custom font.\n\n"
                "The font family name will be extracted and stored automatically.\n\n",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_wm_font",
                "prompt_message_id": sent_message.id,
                "back_to": "watermark",
            }
            await callback_query.answer()
            return

        elif data == "wm_set_timing":
            wm = user_settings(user_id).get_watermark()
            await message.edit_text(
                "<b>Watermark Timing</b>\n\n"
                "<blockquote>"
                "<b>Full Duration</b>  Visible for the entire video.\n\n"
                "<b>Start → End</b>  Visible between two exact timestamps.\n\n"
                "<b>Random Duration</b>  Appears for N seconds at a random point in the video.</blockquote>",
                reply_markup=build_wm_timing_keyboard(wm.get("timing_mode", "range")),
                parse_mode=ParseMode.HTML
            )
            await callback_query.answer()
            return

        elif data == "wm_timing_full":
            user_settings(user_id).update_watermark(timing_mode="full")
            await callback_query.answer("Timing set to Full Duration")
            wm = user_settings(user_id).get_watermark()
            await message.edit_text(
                build_watermark_text(wm, "Timing set to Full Duration"),
                reply_markup=build_watermark_keyboard(wm),
                parse_mode=ParseMode.HTML
            )
            return

        elif data == "wm_timing_range":
            user_settings(user_id).update_watermark(timing_mode="range")
            sent_message = await message.edit_text(
                "<b>Set Start Time</b>\n\n"
                "Send the <b>start time in seconds</b> (e.g. <code>22</code>).\n\n",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_wm_range_start",
                "prompt_message_id": sent_message.id,
                "back_to": "watermark",
            }
            await callback_query.answer()
            return

        elif data == "wm_timing_random":
            user_settings(user_id).update_watermark(timing_mode="random_duration")
            sent_message = await message.edit_text(
                "<b>Random Duration</b>\n\n"
                "Send the <b>duration in seconds</b> the watermark should be visible.\n"
                "<i>Example: <code>30</code></i>\n\n"
                "A random start time will be chosen automatically.\n\n",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_wm_duration",
                "prompt_message_id": sent_message.id,
                "back_to": "watermark",
            }
            await callback_query.answer()
            return

        elif data == "wm_set_position":
            wm = user_settings(user_id).get_watermark()
            await message.edit_text(
                "<b>Watermark Position</b>\n\n"
                "Choose where the watermark appears on the frame.\n"
                "<i>All positions use your configured padding % from the edge.</i>",
                reply_markup=build_wm_position_keyboard(wm.get("position", "bot_right")),
                parse_mode=ParseMode.HTML
            )
            await callback_query.answer()
            return

        elif data == "wm_set_font_size":
            wm = user_settings(user_id).get_watermark()
            sent_message = await message.edit_text(
                "<b>Watermark Font Size</b>\n\n"
                f"Current: <code>{wm.get('font_size', 24)}px</code>\n\n"
                "Send a font size between <code>8</code> and <code>200</code>.\n\n",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_wm_font_size",
                "prompt_message_id": sent_message.id,
                "back_to": "watermark",
            }
            await callback_query.answer()
            return

        elif data == "wm_set_padding":
            wm = user_settings(user_id).get_watermark()
            sent_message = await message.edit_text(
                "<b>Watermark Padding</b>\n\n"
                f"Current: <code>{wm.get('padding', 7)}%</code>\n\n"
                "Padding controls how far the watermark sits from the frame edge.\n"
                "Send a whole number between <code>1</code> and <code>25</code>.\n\n"
                "<i>Example: <code>7</code> = 7% of frame width/height</i>\n\n",
                reply_markup=build_cancel_keyboard(),
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_wm_padding",
                "prompt_message_id": sent_message.id,
                "back_to": "watermark",
            }
            await callback_query.answer()
            return

        elif data.startswith("wm_pos_"):
            pos = data.replace("wm_pos_", "")
            if pos in WM_POSITION_LABELS:
                user_settings(user_id).update_watermark(position=pos)
                label = WM_POSITION_LABELS[pos]
                await callback_query.answer(f"Position → {label}")
                wm = user_settings(user_id).get_watermark()
                await message.edit_text(
                    build_watermark_text(wm, f"Position set to {label} ✓"),
                    reply_markup=build_watermark_keyboard(wm),
                    parse_mode=ParseMode.HTML
                )
            return

        elif data == "wm_reset":
            user_settings(user_id).reset_watermark()
            await callback_query.answer("Watermark reset to defaults")
            wm = user_settings(user_id).get_watermark()
            await message.edit_text(
                build_watermark_text(wm, "Reset to defaults ✓"),
                reply_markup=build_watermark_keyboard(wm),
                parse_mode=ParseMode.HTML
            )
            return

        # ── Cancel pending input ──────────────────────────────────────────────

        elif data == "cancel_input":
            us = user_settings(user_id)
            state_data = us.temp_state.get(user_id, {})
            back_to = state_data.get("back_to", "main") if isinstance(state_data, dict) else "main"
            us.temp_state.pop(user_id, None)
            await callback_query.answer("Cancelled")

            if back_to == "watermark":
                wm = us.get_watermark()
                await message.edit_text(
                    build_watermark_text(wm),
                    reply_markup=build_watermark_keyboard(wm),
                    parse_mode=ParseMode.HTML
                )
            elif back_to == "metadata":
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Set Title",   callback_data="meta_title"),
                     InlineKeyboardButton("Set Author",  callback_data="meta_author")],
                    [InlineKeyboardButton("Set Encoder", callback_data="meta_encoder"),
                     InlineKeyboardButton("Clear All",   callback_data="meta_clear")],
                    [InlineKeyboardButton("Back", callback_data="back_to_menu")]
                ])
                await message.edit_text(
                    "<b>Metadata</b>\n\n"
                    "<blockquote>Title, author, and encoder tags are embedded\n"
                    "directly into the output file.</blockquote>",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            elif back_to.startswith("profile_"):
                resolution = back_to.replace("profile_", "")
                profile = us.get_profile(resolution)
                await message.edit_text(
                    build_profile_text(resolution, profile),
                    reply_markup=build_profile_edit_keyboard(resolution, profile),
                    parse_mode=ParseMode.HTML
                )
            else:
                await update_main_menu(client, message, user_id)
            return

        # ── Reset / back / close ──────────────────────────────────────────────

        elif data == "reset_settings":
            user_settings(user_id).reset()
            await callback_query.answer("Settings reset to defaults")
            await update_main_menu(client, message, user_id)
            return

        elif data == "back_to_menu":
            await update_main_menu(client, message, user_id)
            return

        elif data == "close_menu":
            await message.delete()
            await callback_query.answer("Menu closed")
            return

        await callback_query.answer()

    # ── Helper: resolution menu ───────────────────────────────────────────────

    async def update_resolution_menu(message, user_id):
        settings = user_settings(user_id).get()
        await message.edit_text(
            "<b>Select Resolutions</b>\n\n"
            "<blockquote>Choose 1–4 resolutions to encode per file.\n"
            "Each resolution uses its own quality profile.</blockquote>",
            reply_markup=build_resolution_keyboard(settings),
            parse_mode=ParseMode.HTML
        )

    # ── Helper: rebuild main menu ─────────────────────────────────────────────

    async def update_main_menu(client, message, user_id):
        user     = await client.get_users(user_id)
        name     = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = user.username or ""
        settings = user_settings(user_id).get()

        text           = build_settings_text(name, username, user_id, settings)
        keyboard       = build_main_keyboard()
        thumbnail_path = get_thumbnail_path(settings)

        try:
            if message.photo and thumbnail_path:
                await message.edit_media(
                    media=InputMediaPhoto(media=thumbnail_path, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=keyboard
                )
            elif message.text and thumbnail_path:
                await message.delete()
                await client.send_photo(
                    chat_id=user_id,
                    photo=thumbnail_path,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            except Exception:
                await client.send_message(
                    chat_id=user_id, text=text,
                    reply_markup=keyboard, parse_mode=ParseMode.HTML
                )

    # ── Text input handler ────────────────────────────────────────────────────

    @app.on_message(filters.text & filters.private)
    async def handle_text_input(client: Client, message: Message):
        user_id = message.from_user.id
        if message.text.startswith("/"):
            return

        us = user_settings(user_id)
        if user_id not in us.temp_state:
            return

        state_data        = us.temp_state[user_id]
        state             = state_data["state"] if isinstance(state_data, dict) else state_data
        prompt_message_id = state_data.get("prompt_message_id") if isinstance(state_data, dict) else None

        # ── Profile CRF ──────────────────────────────────────────────────────
        if state.startswith("waiting_profile_"):
            parts = state.split("_")
            if len(parts) >= 4 and parts[3] == "crf":
                resolution = parts[2]
                try:
                    crf = int(message.text)
                    if 0 <= crf <= 58:
                        us.update_profile(resolution, "crf", crf)
                        del us.temp_state[user_id]
                        try:
                            await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
                        except Exception:
                            pass
                        profile = us.get_profile(resolution)
                        await client.send_message(
                            user_id,
                            build_profile_text(resolution, profile, f"CRF updated to {crf} ✓"),
                            reply_markup=build_profile_edit_keyboard(resolution, profile),
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await message.reply_text(
                            "<b>Invalid value.</b> CRF must be between <code>0</code> and <code>58</code>.",
                            parse_mode=ParseMode.HTML
                        )
                except ValueError:
                    await message.reply_text("<b>Invalid input.</b> Please send a whole number.", parse_mode=ParseMode.HTML)
            return

        # ── Metadata ──────────────────────────────────────────────────────────
        elif state == "waiting_meta_title":
            us.update_metadata(title=message.text)
            del us.temp_state[user_id]
            try:
                await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
            except Exception:
                pass
            await us_command(client, message)

        elif state == "waiting_meta_author":
            us.update_metadata(author=message.text)
            del us.temp_state[user_id]
            try:
                await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
            except Exception:
                pass
            await us_command(client, message)

        elif state == "waiting_meta_encoder":
            us.update_metadata(encoder=message.text)
            del us.temp_state[user_id]
            try:
                await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
            except Exception:
                pass
            await us_command(client, message)

        # ── Watermark text ────────────────────────────────────────────────────
        elif state == "waiting_wm_text":
            text_val = message.text.strip()
            if text_val:
                us.update_watermark(text=text_val)
                del us.temp_state[user_id]
                try:
                    await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
                except Exception:
                    pass
                wm = us.get_watermark()
                await client.send_message(
                    user_id,
                    build_watermark_text(wm, "Text updated ✓"),
                    reply_markup=build_watermark_keyboard(wm),
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.reply_text("Text cannot be empty.", parse_mode=ParseMode.HTML)

        # ── Watermark timing: range start ─────────────────────────────────────
        elif state == "waiting_wm_range_start":
            try:
                start = int(message.text)
                if start < 0:
                    raise ValueError
                us.update_watermark(start=start)
                del us.temp_state[user_id]
                try:
                    await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
                except Exception:
                    pass
                sent = await client.send_message(
                    user_id,
                    f"<b>Set End Time</b>\n\n"
                    f"Start is set to <code>{start}s</code>.\n"
                    "Now send the <b>end time in seconds</b>.\n\n",
                    reply_markup=build_cancel_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                us.temp_state[user_id] = {
                    "state": "waiting_wm_range_end",
                    "prompt_message_id": sent.id,
                    "back_to": "watermark",
                }
            except ValueError:
                await message.reply_text("Please send a valid non-negative number.", parse_mode=ParseMode.HTML)

        # ── Watermark timing: range end ───────────────────────────────────────
        elif state == "waiting_wm_range_end":
            try:
                end = int(message.text)
                wm  = us.get_watermark()
                if end <= wm.get("start", 0):
                    await message.reply_text(
                        f"End time must be greater than start time (<code>{wm.get('start', 0)}s</code>).",
                        parse_mode=ParseMode.HTML
                    )
                    return
                us.update_watermark(end=end)
                del us.temp_state[user_id]
                try:
                    await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
                except Exception:
                    pass
                wm = us.get_watermark()
                await client.send_message(
                    user_id,
                    build_watermark_text(wm, f"Timing set: {wm['start']}s → {end}s ✓"),
                    reply_markup=build_watermark_keyboard(wm),
                    parse_mode=ParseMode.HTML
                )
            except ValueError:
                await message.reply_text("Please send a valid number.", parse_mode=ParseMode.HTML)

        # ── Watermark timing: random duration ─────────────────────────────────
        elif state == "waiting_wm_duration":
            try:
                duration = int(message.text)
                if duration <= 0:
                    raise ValueError
                us.update_watermark(duration=duration)
                del us.temp_state[user_id]
                try:
                    await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
                except Exception:
                    pass
                wm = us.get_watermark()
                await client.send_message(
                    user_id,
                    build_watermark_text(wm, f"Random duration set to {duration}s ✓"),
                    reply_markup=build_watermark_keyboard(wm),
                    parse_mode=ParseMode.HTML
                )
            except ValueError:
                await message.reply_text("Please send a positive number of seconds.", parse_mode=ParseMode.HTML)

        # ── Watermark font size ───────────────────────────────────────────────
        elif state == "waiting_wm_font_size":
            try:
                size = int(message.text)
                if not (8 <= size <= 200):
                    raise ValueError
                us.update_watermark(font_size=size)
                del us.temp_state[user_id]
                try:
                    await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
                except Exception:
                    pass
                wm = us.get_watermark()
                await client.send_message(
                    user_id,
                    build_watermark_text(wm, f"Font size set to {size}px ✓"),
                    reply_markup=build_watermark_keyboard(wm),
                    parse_mode=ParseMode.HTML
                )
            except ValueError:
                await message.reply_text(
                    "Please send a valid integer between <code>8</code> and <code>200</code>.",
                    parse_mode=ParseMode.HTML
                )

        # ── Watermark padding ─────────────────────────────────────────────────
        elif state == "waiting_wm_padding":
            try:
                padding = int(message.text)
                if not (1 <= padding <= 25):
                    raise ValueError
                us.update_watermark(padding=padding)
                del us.temp_state[user_id]
                try:
                    await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
                except Exception:
                    pass
                wm = us.get_watermark()
                await client.send_message(
                    user_id,
                    build_watermark_text(wm, f"Padding set to {padding}% ✓"),
                    reply_markup=build_watermark_keyboard(wm),
                    parse_mode=ParseMode.HTML
                )
            except ValueError:
                await message.reply_text(
                    "Please send a whole number between <code>1</code> and <code>25</code>.",
                    parse_mode=ParseMode.HTML
                )

    # ── Thumbnail photo handler ───────────────────────────────────────────────

    @app.on_message(filters.photo & filters.private)
    async def handle_thumbnail(client: Client, message: Message):
        user_id = message.from_user.id
        us = user_settings(user_id)
        if user_id not in us.temp_state:
            return

        state_data = us.temp_state[user_id]
        if not (isinstance(state_data, dict) and state_data.get("state") == "waiting_thumbnail"):
            return

        prompt_message_id = state_data.get("prompt_message_id")

        try:
            thumb_dir  = "./src/bin/thumbnails"
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_path = os.path.join(thumb_dir, f"{user_id}.jpg")

            downloaded_path = await client.download_media(message, file_name=thumb_path)

            if not downloaded_path or not os.path.exists(downloaded_path):
                await message.reply_text("<b>Failed to save thumbnail.</b> Please try again.", parse_mode=ParseMode.HTML)
                return

            us.set_thumbnail(os.path.abspath(downloaded_path))
            del us.temp_state[user_id]

            try:
                await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
            except Exception:
                pass

            await us_command(client, message)

        except Exception as e:
            await message.reply_text(f"<b>Error saving thumbnail:</b> <code>{e}</code>", parse_mode=ParseMode.HTML)

    # ── Font file document handler ────────────────────────────────────────────

    @app.on_message(filters.document & filters.private)
    async def handle_font_upload(client: Client, message: Message):
        user_id = message.from_user.id
        us = user_settings(user_id)
        if user_id not in us.temp_state:
            return

        state_data = us.temp_state[user_id]
        if not (isinstance(state_data, dict) and state_data.get("state") == "waiting_wm_font"):
            return

        prompt_message_id = state_data.get("prompt_message_id")
        doc = message.document

        if not doc:
            return

        file_name = doc.file_name or ""
        ext = os.path.splitext(file_name)[1].lower()

        if ext not in (".ttf", ".otf"):
            await message.reply_text(
                "Only <code>.ttf</code> and <code>.otf</code> font files are accepted.",
                parse_mode=ParseMode.HTML
            )
            return

        try:
            fonts_dir = "./src/bin/fonts"
            os.makedirs(fonts_dir, exist_ok=True)
            tmp_path = os.path.join(fonts_dir, f"tmp_{user_id}{ext}")

            downloaded = await client.download_media(message, file_name=tmp_path)
            if not downloaded or not os.path.exists(downloaded):
                await message.reply_text("Failed to download font file. Please try again.", parse_mode=ParseMode.HTML)
                return

            font_name = us.set_watermark_font(os.path.abspath(downloaded))

            if os.path.exists(downloaded) and downloaded == tmp_path:
                try:
                    os.remove(downloaded)
                except Exception:
                    pass

            del us.temp_state[user_id]

            try:
                await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
            except Exception:
                pass

            wm = us.get_watermark()
            await client.send_message(
                user_id,
                build_watermark_text(wm, f"Font set to <b>{font_name}</b> ✓"),
                reply_markup=build_watermark_keyboard(wm),
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            await message.reply_text(f"<b>Error saving font:</b> <code>{e}</code>", parse_mode=ParseMode.HTML)