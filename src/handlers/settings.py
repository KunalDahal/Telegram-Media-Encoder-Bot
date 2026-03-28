from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
import os
from src import Config
from pyrogram.enums import ParseMode

config = Config()
RESOLUTION_OPTIONS = ["HDRip", "1080p", "720p", "480p"]

PRESET_OPTIONS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
CODEC_OPTIONS = ["libx264", "libx265"]
AUDIO_OPTIONS = ["96k", "128k", "192k", "256k", "320k"]

DEFAULT_PROFILES = {
    "1080p": {"crf": 22, "preset": "medium", "codec": "libx264", "audio_bitrate": "192k"},
    "720p": {"crf": 26, "preset": "medium", "codec": "libx264", "audio_bitrate": "128k"},
    "480p": {"crf": 28, "preset": "fast", "codec": "libx264", "audio_bitrate": "96k"}
}


def format_resolutions(settings):
    resolutions = settings.get("resolutions") or [settings.get("resolution", "1080p")]
    return ", ".join(resolutions)


def format_profile_summary(profile, resolution):
    if resolution == "HDRip":
        return "  <i>HDRip</i> — metadata only <i>(no re-encode)</i>"
    crf    = profile.get('crf', 23)
    preset = profile.get('preset', 'medium')
    codec  = profile.get('codec', 'libx264')
    audio  = profile.get('audio_bitrate', '128k')
    return (
        f"  <b>{resolution}</b>  "
        f"CRF <code>{crf}</code> · "
        f"<code>{preset}</code> · "
        f"<code>{codec}</code> · "
        f"<code>{audio}</code>"
    )

def build_settings_text(name, username, user_id, settings):
    profiles     = settings.get("profiles", {})
    has_thumb    = settings['thumbnail_path'] and os.path.exists(settings['thumbnail_path'])
    thumb_status = "<u>Set ✓</u>" if has_thumb else "<i>Not set</i>"
    send_type    = "Media" if settings['send_type'] == 'media' else "Document"
    meta         = settings['metadata']

    profile_lines = "\n".join([
        format_profile_summary(profiles.get(res, {}), res)
        for res in ["HDRip", "1080p", "720p", "480p"]
    ])

    return (
        "<blockquote><b>Encoding Settings</b></blockquote>\n\n"
        f"<b>User:</b> {name} (@{username if username else 'N/A'})\n"
        f"<b>ID:</b> <code>{user_id}</code>\n\n"
        f"<b>Selected Resolutions:</b> <code>{format_resolutions(settings)}</code>\n\n"
        "<blockquote><b>Quality Profiles:</b></blockquote>\n"
        f"<blockquote>{profile_lines}</blockquote>\n"
        f"<b>Send Type:</b> <code>{send_type}</code>\n\n"
        "<blockquote><b>Metadata:</b></blockquote>\n"
        f"Title   : <code>{meta['title'] or '—'}</code>\n"
        f"Author  : <code>{meta['author'] or '—'}</code>\n"
        f"Encoder : <code>{meta['encoder'] or '—'}</code>\n\n"
        f"<blockquote><b>Thumbnail:</b> {thumb_status}</blockquote>"
    )


def build_profile_text(resolution, profile, subtitle=""):
    crf    = profile.get('crf', 23)
    preset = profile.get('preset', 'medium')
    codec  = profile.get('codec', 'libx264')
    audio  = profile.get('audio_bitrate', '128k')
    extra  = f"\n<i>{subtitle}</i>" if subtitle else ""
    return (
        f"<b>{resolution} Profile</b>{extra}\n\n"
        "<blockquote>"
        f"CRF    : <code>{crf}</code>  <i>(lower = better quality)</i>\n"
        f"Preset : <code>{preset}</code>\n"
        f"Codec  : <code>{codec}</code>\n"
        f"Audio  : <code>{audio}</code>"
        "</blockquote>\n"
        "<i>Tap any button below to change a setting.</i>"
    )


def build_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Resolutions",      callback_data="set_resolution")],
        [InlineKeyboardButton("Quality Profiles", callback_data="set_profiles")],
        [InlineKeyboardButton("Send Type",        callback_data="set_send_type")],
        [InlineKeyboardButton("Metadata",         callback_data="set_metadata")],
        [InlineKeyboardButton("Thumbnail",        callback_data="set_thumbnail")],
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
        [InlineKeyboardButton("Reset", callback_data="profile_reset_all")],
        [InlineKeyboardButton("Back", callback_data="back_to_menu")],
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
        [InlineKeyboardButton(f"CRF: {profile.get('crf', 23)}",              callback_data=f"profile_edit_{resolution}_crf")],
        [InlineKeyboardButton(f"Preset: {profile.get('preset', 'medium')}",  callback_data=f"profile_edit_{resolution}_preset")],
        [InlineKeyboardButton(f"Codec: {profile.get('codec', 'libx264')}",   callback_data=f"profile_edit_{resolution}_codec")],
        [InlineKeyboardButton(f"Audio: {profile.get('audio_bitrate','128k')}",callback_data=f"profile_edit_{resolution}_audio")],
        [InlineKeyboardButton(f"Reset {resolution} to Default",           callback_data=f"profile_reset_{resolution}")],
        [InlineKeyboardButton("Back to Profiles",                          callback_data="set_profiles")],
    ])


def get_thumbnail_path(settings):
    thumbnail_path = (
        settings["thumbnail_path"]
        if settings["thumbnail_path"] and os.path.exists(settings["thumbnail_path"])
        else "./src/bin/default.jpg"
    )
    return thumbnail_path if os.path.exists(thumbnail_path) else None


def setup_settings_handlers(app: Client, user_settings):
    @app.on_message(filters.command("es") & filters.private)
    async def us_command(client: Client, message: Message):
        if message.from_user.id not in config.admin_ids:
            await message.reply_text("Invalid!")
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

    @app.on_callback_query(filters.regex(r'^(set_|res_|profile_|sendtype_|meta_|reset_|back_to|close_)'))
    async def handle_settings_callbacks(client: Client, callback_query: CallbackQuery):
        user    = callback_query.from_user
        user_id = user.id
        data    = callback_query.data
        message = callback_query.message

        # ── Quality Profiles list ──────────────────────────────────────────
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

        # ── Must be checked BEFORE the generic profile_ block ──────────────

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
                        parse_mode=ParseMode.HTML
                    )
                    user_settings(user_id).temp_state[user_id] = {
                        "state": f"waiting_profile_{resolution}_crf",
                        "prompt_message_id": sent_message.id
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

        # ── Resolution profile edit screen ─────────────────────────────────

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

        # ── Resolution toggle ───────────────────────────────────────────────

        elif data == "set_resolution":
            await update_resolution_menu(message, user_id)

        elif data.startswith("res_toggle_"):
            resolution = data.replace("res_toggle_", "", 1)
            changed, status_text = user_settings(user_id).toggle_resolution(resolution)
            await callback_query.answer(status_text, show_alert=not changed)
            await update_resolution_menu(message, user_id)
            return

        # ── Send type ───────────────────────────────────────────────────────

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

        # ── Metadata ────────────────────────────────────────────────────────

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
                "<b>Set Title</b>\n\n"
                "Send the title to embed in your videos.",
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_title",
                "prompt_message_id": sent_message.id
            }

        elif data == "meta_author":
            sent_message = await message.edit_text(
                "<b>Set Author</b>\n\n"
                "Send the author name to embed.",
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_author",
                "prompt_message_id": sent_message.id
            }

        elif data == "meta_encoder":
            sent_message = await message.edit_text(
                "<b>Set Encoder</b>\n\n"
                "Send the encoder name to embed.",
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_encoder",
                "prompt_message_id": sent_message.id
            }

        elif data == "meta_clear":
            user_settings(user_id).update_metadata(title="", author="", encoder="")
            await callback_query.answer("Metadata cleared")
            await update_main_menu(client, message, user_id)
            return

        # ── Thumbnail ───────────────────────────────────────────────────────

        elif data == "set_thumbnail":
            sent_message = await message.edit_text(
                "<b>🖼 Set Thumbnail</b>\n\n"
                "Send an image to use as the video thumbnail.",
                parse_mode=ParseMode.HTML
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_thumbnail",
                "prompt_message_id": sent_message.id
            }

        # ── Reset / back / close ────────────────────────────────────────────

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

    # ── Helper: resolution menu ─────────────────────────────────────────────

    async def update_resolution_menu(message, user_id):
        settings = user_settings(user_id).get()
        await message.edit_text(
            "<b>Select Resolutions</b>\n\n"
            "<blockquote>Choose 1–4 resolutions to encode per file.\n"
            "Each resolution uses its own quality profile.</blockquote>",
            reply_markup=build_resolution_keyboard(settings),
            parse_mode=ParseMode.HTML
        )

    # ── Helper: rebuild main menu ───────────────────────────────────────────

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

    # ── Text input handler ──────────────────────────────────────────────────

    @app.on_message(filters.text & filters.private)
    async def handle_text_input(client: Client, message: Message):
        user_id = message.from_user.id

        if message.text.startswith('/'):
            return

        us = user_settings(user_id)
        if user_id not in us.temp_state:
            return

        state_data        = us.temp_state[user_id]
        state             = state_data["state"] if isinstance(state_data, dict) else state_data
        prompt_message_id = state_data.get("prompt_message_id") if isinstance(state_data, dict) else None

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
                            await client.delete_messages(
                                chat_id=user_id,
                                message_ids=[prompt_message_id, message.id]
                            )
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
                    await message.reply_text(
                        "<b>Invalid input.</b> Please send a whole number.",
                        parse_mode=ParseMode.HTML
                    )
                return

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

    # ── Thumbnail upload handler ────────────────────────────────────────────

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
            thumb_dir  = "./bin/thumbnails"
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_path = os.path.join(thumb_dir, f"{user_id}.jpg")

            downloaded_path = await client.download_media(message, file_name=thumb_path)

            if not downloaded_path or not os.path.exists(downloaded_path):
                await message.reply_text(
                    "<b>Failed to save thumbnail.</b> Please try again.",
                    parse_mode=ParseMode.HTML
                )
                return

            final_path = os.path.abspath(downloaded_path)
            us.set_thumbnail(final_path)
            del us.temp_state[user_id]

            try:
                await client.delete_messages(chat_id=user_id, message_ids=[prompt_message_id, message.id])
            except Exception:
                pass

            await us_command(client, message)

        except Exception as e:
            await message.reply_text(
                f"<b>Error saving thumbnail:</b> <code>{e}</code>\nPlease try again.",
                parse_mode=ParseMode.HTML
            )
