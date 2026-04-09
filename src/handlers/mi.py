from __future__ import annotations

import os
import uuid

from pyrogram import filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message

from src.utils.telegraphpage import MediaInfoHelper

# ─── Singleton ────────────────────────────────────────────────────────────────
_telegraph = MediaInfoHelper()

PARTIAL_BYTES = 3 * 1024 * 1024   # 3 MB head — enough for mediainfo


# ─── Handler ──────────────────────────────────────────────────────────────────

async def _handle_media(client, message: Message):
    media = (
        message.document
        or message.video
        or message.audio
        or message.voice
        or message.video_note
    )
    if not media:
        return

    filename  = getattr(media, "file_name", None) or f"file_{media.file_id[:8]}"
    tmp_dir   = f"/tmp/mi_{uuid.uuid4().hex}"
    save_path = os.path.join(tmp_dir, filename)

    os.makedirs(tmp_dir, exist_ok=True)
    status_msg = await message.reply_text("⏳ Downloading partial file…")

    try:
        # ── 1. Partial download (head only) ───────────────────────────────────
        await _telegraph.download_partial(
            client=client,
            media=media,
            save_path=save_path,
            max_bytes=PARTIAL_BYTES,
        )

        # ── 2. Generate Telegraph page ────────────────────────────────────────
        await status_msg.edit_text("🔍 Generating MediaInfo page…")
        url, err = await _telegraph.generate_mediainfo(save_path, filename)

        if err:
            await status_msg.edit_text(f"❌ Error: {err}")
            return

        # ── 3. Reply with link ────────────────────────────────────────────────
        await status_msg.edit_text(
            f"📄 <b>MediaInfo</b>\n"
            f"<b>File:</b> <code>{filename}</code>\n"
            f"<b>Link:</b> {url}",
            parse_mode="html",
            disable_web_page_preview=True,
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Failed: {e}")

    finally:
        # Clean up temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── Register ─────────────────────────────────────────────────────────────────

def setup_mediainfo_handlers(app, config=None):
    app.add_handler(
        MessageHandler(
            _handle_media,
            filters.private & (
                filters.document
                | filters.video
                | filters.audio
                | filters.voice
                | filters.video_note
            ),
        )
    )