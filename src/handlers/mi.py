import os
import re
from pyrogram import filters, enums
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler
from src.core.media_helper import MediaInfoHelper


mediainfo_helper = MediaInfoHelper()

HELP_TEXT = (
    "<b>MediaInfo Generator</b>\n\n"
    "<b>Usage:</b>\n"
    "• Reply to a media file with <code>/mi</code>\n"
    "• <code>/mi &lt;download_link&gt;</code>\n"
    "• Reply to a message containing a link with <code>/mi</code>"
)


async def _check_access(client, message: Message, config) -> bool:
    user_id = message.from_user.id

    if user_id not in config.admin_ids:
        await message.reply_text("Dukhi Atma!😔")
        return False

    return True


async def mediainfo_command(client, message: Message, config):
    if not await _check_access(client, message, config):
        return

    temp_dir = config.paths.tmp
    os.makedirs(temp_dir, exist_ok=True)

    reply     = message.reply_to_message
    file_path = None
    filename  = None
    use_url   = False
    media_url = None

    status_msg = await message.reply_text(
        "⏳ <b>Processing...</b>",
        parse_mode=enums.ParseMode.HTML,
    )

    try:
        if len(message.command) > 1:
            media_url = message.command[1]
            filename  = os.path.basename(media_url.split("?")[0]) or "file.mkv"
            use_url   = True

        elif reply and (
            reply.document or reply.video or reply.audio
            or reply.voice or reply.animation or reply.video_note
        ):
            media    = (
                reply.document or reply.video or reply.audio
                or reply.voice or reply.animation or reply.video_note
            )
            filename  = getattr(media, "file_name", None) or f"{media.file_unique_id}.bin"
            file_path = os.path.join(temp_dir, filename)

            await status_msg.edit_text(
                f"📥 <b>Downloading header of</b> <code>{filename[:40]}</code><b>...</b>",
                parse_mode=enums.ParseMode.HTML,
            )
            await mediainfo_helper.download_partial(client, media, file_path)

        elif reply and reply.text:
            match = re.search(r"https?://\S+", reply.text)
            if not match:
                await status_msg.edit_text(HELP_TEXT, parse_mode=enums.ParseMode.HTML)
                return
            media_url = match.group(0)
            filename  = os.path.basename(media_url.split("?")[0]) or "file.mkv"
            use_url   = True

        else:
            await status_msg.edit_text(HELP_TEXT, parse_mode=enums.ParseMode.HTML)
            return

        await status_msg.edit_text(
            "🔍 <b>Analyzing media...</b>",
            parse_mode=enums.ParseMode.HTML,
        )

        target = media_url if use_url else file_path
        telegraph_url, error = await mediainfo_helper.generate_mediainfo(target, filename)

        if error:
            await status_msg.edit_text(
                f"❌ <b>Error:</b> {error}",
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await status_msg.edit_text(
                f"✅ <b>MediaInfo ready!</b>\n\n"
                f"📄 <b>File:</b> <code>{filename}</code>\n"
                f"🔗 <b>View:</b> <a href='{telegraph_url}'>Telegraph page</a>",
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Error:</b> <code>{str(e)[:300]}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


def setup_mediainfo_handlers(app, config):
    allowed_chat_filter = filters.chat(config.allowed_group_ids) | filters.private

    async def _handler(client, message: Message):
        await mediainfo_command(client, message, config)

    app.add_handler(
        MessageHandler(
            _handler,
            filters.command(["mi", "mediainfo"]) & allowed_chat_filter,
        )
    )