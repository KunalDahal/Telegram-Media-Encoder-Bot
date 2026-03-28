from pyrogram import enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


HELP_TEXT = """
<b>📦 Encoding Bot — Commands</b>

<blockquote><b>🎬 Encoding</b>
<b>/encode</b> <code>[filename.ext]</code>
Reply to a video file to queue it for encoding.

• Without a filename → uses the original file name
• With a filename → renames the output
• Supports <code>{quality}</code> placeholder in filenames:
  <code>/encode [S01E01] Show [{quality}] Sub.mkv</code>
  → produces <code>[S01E01] Show [1080p] Sub.mkv</code>, <code>[720p]</code>, etc.

Each file is processed <b>sequentially</b>:
<code>Download → Encode → Upload</code> per resolution, one at a time.
HDRip skips re-encoding — only metadata, rename and thumbnail are applied.</blockquote>

<blockquote><b>⚙️ Settings  /es</b>
Opens the full settings panel.

<b>📐 Resolutions</b> — select 1 to 4 per file
<code>HDRip · 1080p · 720p · 480p</code>

<b>🎛 Quality Profiles</b> — per-resolution settings
Each resolution has its own independent profile:
  • CRF (0–58, lower = better quality)
  • Preset (ultrafast → veryslow)
  • Codec (H.264 / H.265)
  • Audio bitrate (96k – 320k)

<b>📤 Send Type</b> — <code>Media</code> or <code>Document</code>

<b>🏷 Metadata</b> — embed Title, Author, Encoder tags

<b>🖼 Thumbnail</b> — send a photo to set a custom thumbnail</blockquote>

<blockquote><b>📊 Queue  /status</b>
Shows all active and queued tasks with:
• Current stage (Downloading / Encoding / Uploading)
• Active resolution and job index (e.g. Job 2/3)
• Speed, ETA, elapsed time
• Bot CPU / RAM / Disk stats</blockquote>

<blockquote><b>🚫 Cancel  /cancel</b> <code>&lt;task_id&gt;</code>
Cancel a queued or active task by its ID.
Task IDs are shown in /status and in the queue confirmation message.</blockquote>

<blockquote><b>📝 Notes</b>
• Private chat only
• Admin access required
• Files processed one at a time — no parallel jobs
• HDRip = copy-only (no re-encode), just metadata + thumbnail</blockquote>
"""


def setup_help_handlers(app):
    @app.on_message(filters.command("help") & filters.private)
    async def help_handler(client, message: Message):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Developer", url="https://t.me/renzobot")]
        ])
        try:
            await message.reply_text(
                text=HELP_TEXT,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            print(f"Error sending help: {e}")
            await message.reply_text(
                "Use /encode to queue a video, /es for settings, /status for queue."
            )