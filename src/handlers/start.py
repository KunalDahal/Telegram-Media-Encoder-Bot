import os
from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from src import Config

config = Config()

START_TEXT = """
<b>Welcome to the Encoding Bot!</b>

Queue video files for encoding with full per-resolution quality control.

<blockquote><b>Quick start:</b>
1. Use /es to configure your resolutions and quality profiles
2. Reply to any video file and type /encode
3. Use /status to track progress
4. Use /cancel &lt;task_id&gt; to cancel a task</blockquote>

Type /help for the full command reference.
"""

START_IMAGE = "./src/bin/start.jpg"


def setup_start_handler(app):
    @app.on_message(filters.command("start") & filters.private)
    async def start_handler(client, message: Message):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Developer", url="https://t.me/Renzo")]
        ])

        try:
            if os.path.exists(START_IMAGE):
                await message.reply_photo(
                    photo=START_IMAGE,
                    caption=START_TEXT,
                    reply_markup=keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await message.reply_text(
                    text=START_TEXT,
                    reply_markup=keyboard,
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        except Exception as e:
            print(f"Error sending start: {e}")
            await message.reply_text(
                f"Welcome {message.from_user.first_name}! Use /help to see all commands.",
                reply_markup=keyboard,
            )