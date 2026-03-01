from pyrogram import filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

async def help_command(client, message: Message):
    
    help_text = """
<blockquote><b>Bot Commands Guide</b></blockquote>
Here’s a complete overview of the bot and its features.

<blockquote><b>Basic Commands:</b></blockquote>
• <b>/start – Start the bot.</b>
• <b>/help – Show the help message.</b>

<blockquote><b>Other Commands:</b></blockquote>

• <b>/us – Configure your custom encoding settings</b>
- Set video resolution, CRF, preset, codec
- Set audio bitrate
- Set metadata such as title, author, encoder
- Choose file type to send: Telegram media, Telegram video, or Telegram document
- Set a custom thumbnail
<i>With /us, you can fully customize how your files are encoded and sent.</i>

• <b>/encode filename.ext – Encode a replied video</b>
Reply to a video and type <b>/encode</b> to use the original filename.
Or specify a filename with extension like <b>/encode myvideo.mp4</b>.
<i>The bot will encode your file according to your /us settings and send it back.</i>

• <b>/status – Check the progress of encoding tasks</b>
Shows download, encoding, and upload progress for your files.

<blockquote><b>Upcoming Features:</b></blockquote>
• Parallel encoding – handle multiple files at once
• Batch Rename – rename files in batch
• Watermark – add watermark to full video or for a short duration

<blockquote><b>Notes:</b></blockquote>
• All commands work in private chat only
• Only authorized admins can use this bot
• Large files may take time to process

<blockquote><b>Need help?</b></blockquote>
Contact the developer if you face any issues.
"""
    
    keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Developer", url="https://t.me/aniindexadminbot")]
])
    
    try:
        await message.reply_text(
                text=help_text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML
            )
    except Exception as e:
        print(f"Error sending help: {e}")
        await message.reply_text(
            text="/start to begin\nUse /encode to encode videos\nUse /status to check queue",
            reply_markup=keyboard
        )


def setup_help_handlers(app):
    @app.on_message(filters.command("help") & filters.private)
    async def help_handler(client, message: Message):
        await help_command(client, message)
    