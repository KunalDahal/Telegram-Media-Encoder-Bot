import os
import re
from pyrogram import filters
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler
from src import Config
from src.core.media_helper import MediaInfoHelper
import enum

TEMP_DIR = "./src/bin/temp_mediainfo"
os.makedirs(TEMP_DIR, exist_ok=True)

mediainfo_helper = MediaInfoHelper()


async def mediainfo_command(client, message: Message):
    config = Config()

    if message.from_user.id not in config.admin_ids:
        await message.reply_text(
            "❌ <b>You are not authorized to use this command.</b>",
            parse_mode=enum.parse_mode.HTML
        )
        return

    help_text = (
        "🎬 <b>MediaInfo Generator</b>\n\n"
        "<b>Usage:</b>\n"
        "• Reply to a media file with <code>/mediainfo</code>\n"
        "• Send <code>/mediainfo &lt;download_link&gt;</code>\n"
        "• Reply to a message containing a link with <code>/mediainfo</code>"
    )

    reply = message.reply_to_message
    file_path = None
    filename = None

    status_msg = await message.reply_text(
        "⏳ <b>Processing...</b>",
        parse_mode=enum.parse_mode.HTML
    )

    try:

        if len(message.command) > 1:
            link = message.command[1]

            filename = os.path.basename(link.split("?")[0])
            if not filename:
                await status_msg.edit_text("❌ Invalid download link.")
                return

            file_path = os.path.join(TEMP_DIR, filename)

            await status_msg.edit_text(
                "📥 <b>Downloading from link...</b>",
                parse_mode=enum.parse_mode.HTML
            )

            await mediainfo_helper.download_file(link, file_path)

        elif reply and (
            reply.document or reply.video or reply.audio or
            reply.voice or reply.animation or reply.video_note
        ):
            media = (
                reply.document or reply.video or reply.audio or
                reply.voice or reply.animation or reply.video_note
            )

            filename = media.file_name or f"{media.file_unique_id}.bin"
            file_path = os.path.join(TEMP_DIR, filename)

            await status_msg.edit_text(
                f"📥 <b>Downloading {filename[:30]}...</b>",
                parse_mode=enum.parse_mode.HTML
            )

            await mediainfo_helper.download_media(client, media, file_path)

        elif reply and reply.text:
            link_match = re.search(r'https?://\S+', reply.text)
            if not link_match:
                await status_msg.edit_text(help_text, parse_mode=enum.parse_mode.HTML)
                return

            link = link_match.group(0)
            filename = os.path.basename(link.split("?")[0])
            file_path = os.path.join(TEMP_DIR, filename)

            await status_msg.edit_text(
                "📥 <b>Downloading from link...</b>",
                parse_mode=enum.parse_mode.HTML
            )

            await mediainfo_helper.download_file(link, file_path)

        else:
            await status_msg.edit_text(help_text, parse_mode=enum.parse_mode.HTML)
            return

        await status_msg.edit_text(
            "🔍 <b>Analyzing media...</b>",
            parse_mode=enum.parse_mode.HTML
        )

        telegraph_url, error = await mediainfo_helper.generate_mediainfo(
            file_path, filename
        )

        if error:
            await status_msg.edit_text(
                f"<b>Error:</b> {error}",
                parse_mode=enum.parse_mode.HTML
            )
        else:
            await status_msg.edit_text(
                f"<b>MediaInfo Generated!</b>\n\n"
                f"<b>File:</b> <code>{filename}</code>\n"
                f"<b>View:</b> <a href='{telegraph_url}'>Click here</a>",
                parse_mode=enum.parse_mode.HTML,
                disable_web_page_preview=True
            )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Error:</b> {str(e)}",
            parse_mode=enum.parse_mode.HTML
        )


def setup_mediainfo_handlers(app):
    app.add_handler(
        MessageHandler(
            mediainfo_command,
            filters.command("mediainfo") & filters.private
        )
    )