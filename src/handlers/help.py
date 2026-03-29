from pyrogram import enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


HELP_TEXT = """
<b>EncodeBot Help</b>

<i>Command Reference and Usage Guide</i>

════════════════════════════
<b>◆ /es</b>
Configure all encoding settings before using /encode.
The settings menu includes the following options:

◇ Resolution Selection  
Select one or more output resolutions. When you run /encode, the file will be encoded into all selected resolutions.

Example:
<code>1080p, 720p, 480p</code>

◇ Quality Profile  
For every selected resolution, you can set a separate:

• CRF  
• Preset  
• Video Codec  
• Audio Codec  

This allows different quality profiles for different resolutions.

Example:

<code>1080p → CRF 18 | preset slow | h264 | aac</code>
<code>720p  → CRF 20 | preset medium | h264 | aac</code>
<code>480p  → CRF 24 | preset fast | h265 | aac</code>

◇ Send Type  
Choose how encoded files are sent:

• Media  
• Document

◇ Metadata  
Set custom metadata for the output file.

Examples:
<code>Title</code>
<code>Author</code>
<code>Source</code>

◇ Thumbnail  
Set a custom thumbnail that will be used for encoded or renamed files.

◇ Watermark  
Customize watermark settings completely.

Available options include:

• Text  
• Font  
• Font Size  
• Text Color  
• Padding  
• Position  
• Start Time  
• End Time

You may adjust the watermark design according to your own preference.

════════════════════════════

<b>◆ /encode &lt;filename&gt;</b>

Reply to a video file with /encode.

The filename must include:

◇ A valid file extension
◇ A quality placeholder

The quality placeholder will automatically be replaced with each selected resolution.

Example:

<code>/encode Movie [quality].mkv</code>

If your selected resolutions are:

<code>1080p, 720p, 480p</code>

The generated files will be:

<code>Movie 1080p.mkv</code>
<code>Movie 720p.mkv</code>
<code>Movie 480p.mkv</code>

════════════════════════════

<b>◆ /rename &lt;filename&gt;</b>

Reply to a file with /rename followed by the new filename.

Example:

<code>/rename New Movie.mkv</code>

While renaming, the following settings may also be applied:

◇ Thumbnail  
◇ Metadata  
◇ Watermark

════════════════════════════

<b>◆ /status</b>

Shows all currently running tasks.

The status page includes:

• Current task state  
• Active resolution  
• Progress  
• Speed  
• ETA  
• Queue position

════════════════════════════

<b>◆ /start</b>

Displays the introduction and basic information about EncodeBot.

════════════════════════════

<b>◆ /help</b>

Displays this help message.

════════════════════════════

<b>◇ Notes</b>

• Configure your settings first using /es  
• The quality placeholder is required when using /encode  
• A valid file extension must always be included  
• Multiple resolutions can be generated from a single command  
• Thumbnail, metadata and watermark settings apply to both encoding and renaming
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