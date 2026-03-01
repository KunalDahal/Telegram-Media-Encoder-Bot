from pyrogram import filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from src import Config
import os

config = Config()

async def start_command(client, message: Message):
    user = message.from_user
    start_image = "./src/bin/start.jpg"
    
    start_text = """
<b>Welcome to the Encoding Bot!</b>

Encode videos with full customization: set all encoding options and rename files easily.

Use <b>/help</b> to see all commands and settings.

Join the main channel for updates and tips!
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Developer", url="https://t.me/aniindexadminbot"),
        InlineKeyboardButton(" Channel", url="https://t.me/AniIndex")]
    ])
    
    try:
        # Check if image exists
        if os.path.exists(start_image):
            await message.reply_photo(
                photo=start_image,
                caption=start_text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                text=start_text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True
            )
    except Exception as e:
        print(f"Error sending start message: {e}")
        await message.reply_text(
            text=f"Welcome {user.first_name}! Use /help to see commands.",
            reply_markup=keyboard
        )

def setup_start_handler(app):
    """Setup start command handler"""
    @app.on_message(filters.command("start") & filters.private)
    async def start_handler(client, message: Message):
        await start_command(client, message)