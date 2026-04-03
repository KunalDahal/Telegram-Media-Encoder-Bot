import os
from pyrogram import filters, enums
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from src import Config


# ── Style constants ────────────────────────────────────────────────────────────

_D  = "━━━━━━━━━━━━━━━━━━"
_Ds = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
_B  = "◆"
_S  = "◈"
_A  = "↳"
_H  = "■"


# ── Start screen ───────────────────────────────────────────────────────────────

START_TEXT = (
    "<b>TOJI-Encode</b>  <i>— Video Encoding &amp; Renaming Bot</i>\n"
    "\n"
    "<i>Drop a video, configure settings, get perfectly\n"
    "processed files — without leaving Telegram.</i>\n"
    "\n"
    f"{_D}\n"
    "\n"
    f"{_B}  Multi-resolution encoding  <i>(up to 4 at once)</i>\n"
    f"{_B}  Batch rename entire albums in one command\n"
    f"{_B}  Per-resolution quality profiles\n"
    f"{_B}  Custom watermark with timing control\n"
    f"{_B}  Metadata embedding on every output\n"
    f"{_B}  Live queue and real-time progress\n"
    "\n"
    f"{_D}\n"
    "\n"
    f"<code>/es</code>  to configure  ·  tap <b>Guide ⮞</b> for full reference"
)


# ── Help pages  (each MUST stay ≤ 1024 chars) ─────────────────────────────────

PAGES = [

# ══════════════════════════════════════════════════════════════════════════════
# Page 1 — Table of Contents
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>EncodeBot  —  Complete Guide</b>

Navigate page by page using the arrows below.

{_D}
<b>{_H} Command Index</b>

<b>Settings</b>
  <code>/es</code>        — Configure all bot settings

<b>Encoding</b>
  <code>/encode</code>   — Encode a video  <i>(single or batch with -b)</i>

<b>Renaming</b>
  <code>/rename</code>   — Rename a file   <i>(single or batch with -b)</i>

<b>Utility</b>
  <code>/mi</code>       — MediaInfo report
  <code>/status</code>   — Live queue &amp; bot stats
  <code>/cancel</code>   — Stop a running task

<b>Reference</b>
  Tips &amp; Best Practices
  Do's and Don'ts
{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 2 — /es Settings (1/2)
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /es  —  Settings  (1/2)</b>

<i>Opens the settings panel. Changes are saved to your account.</i>

{_D}

<b>{_S} Resolution</b>
Select one or more output resolutions (up to 4).

  <code>HDRip  ·  1080p  ·  720p  ·  480p</code>

<b>HDRip</b> = stream-copy + metadata only.
No re-encode, source quality preserved exactly.

{_Ds}

<b>{_S} Quality Profile  <i>(per resolution)</i></b>
Each resolution has its own encoding profile.

  <b>CRF</b>     — 0–51  (lower = better, larger file)
  <b>Preset</b>  — ultrafast → veryslow
  <b>Codec</b>   — <code>libx264</code>  or  <code>libx265</code>
  <b>Audio</b>   — <code>96k  128k  192k  320k</code>

<b>Defaults:</b>
  <code>1080p</code>  CRF 23 · medium · libx264 · 192k
  <code>720p</code>   CRF 26 · medium · libx264 · 128k
  <code>480p</code>   CRF 28 · fast   · libx264 · 96k

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 3 — /es Settings (2/2)
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /es  —  Settings  (2/2)</b>

{_D}

<b>{_S} Send Type</b>
<code>Media</code> — streamable  ·  <code>Document</code> — raw file

{_Ds}

<b>{_S} Metadata</b>
  <b>Title</b> · <b>Author</b> · <b>Encoder</b>
  Embedded in every output automatically.

{_Ds}

<b>{_S} Thumbnail</b>
  Upload <code>JPG/PNG</code> via <code>/es</code>.
  Reused for all encoded and renamed files.

{_Ds}

<b>{_S} Watermark</b>
  Text burned onto the video.
  Fields: Text · Font · Size · Color · Padding · Position
  Modes: <code>full</code> · <code>range</code> · <code>random</code>

{_Ds}

<b>{_S} Placeholders</b>
  <code>-e</code> Episode · <code>-s</code> Season · <code>-a</code> Audio
  Used by <code>/encode</code> when flags are omitted.

{_Ds}

<b>{_S} Filename Format</b>
<code>[S{{season}}-{{episode}}] {{title}} [{{quality}}].mkv</code>
→ <code>[S01-01] Title [1080p].mkv</code>

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 4 — /encode (single)
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /encode  —  Encode a Video</b>

<i>Reply to a video, then send /encode with flags. Filename is built from your format template in /es.</i>

{_D}

<b>{_S} Usage</b>
<code>/encode [-s S] [-e E] [-a AUDIO] [-q RES] -t Title</code>

<b>Flags</b>
  <code>-t</code>  Title  <b>(required, must be last)</b>
  <code>-e</code>  Episode  <i>(falls back to saved default)</i>
  <code>-s</code>  Season   <i>(falls back to saved default)</i>
  <code>-a</code>  Audio tag  e.g. <code>SUB</code> · <code>DUAL</code>
  <code>-q</code>  Force one resolution  e.g. <code>720p</code>

{_Ds}

<b>{_S} Examples</b>
<code>/encode -t Pokemon</code>
<code>/encode -e 12 -t Dragon Ball</code>
<code>/encode -s 2 -e 5 -a DUAL -t Naruto</code>
<code>/encode -q 720p -e 3 -t One Piece</code>

{_Ds}

<b>{_S} Notes</b>
{_B}  Reply to a video or video document
{_B}  Without <code>-q</code>, all selected resolutions are used
{_B}  Omitted flags use saved defaults from <code>/es</code>

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 5 — /encode -b (batch encode)
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /encode -b  —  Batch Encode an Album</b>

<i>Reply to the first file of an album and add -b. Each file is queued with an auto-incremented episode.</i>

{_D}

<b>{_S} Usage</b>
<code>/encode -b [-s S] [-e E] [-a AUDIO] [-q RES] -t Title</code>

<b>Flags</b>
  <code>-b</code>  Batch mode  <b>(required)</b>
  <code>-t</code>  Title       <b>(required, must be last)</b>
  <code>-e</code>  Start episode 
  <code>-s</code>  Season  <i>(use saved defaults if omitted)</i>
  <code>-a</code>  Audio tag e.g. <code>SUB</code>
  <code>-q</code>  Force resolution e.g. <code>720p</code>

{_Ds}

<b>{_S} Example</b>
{_A} Album: 3 files · resolutions: <code>1080p, 720p</code>
<code>/encode -b -s 1 -e 4 -a SUB -t Pokemon</code>
{_A} Queues Ep 04, 05, 06 at both 1080p and 720p

{_Ds}

<b>{_S} Notes</b>
{_B}  Reply to the <u>first</u> file of the album
{_B}  Episode auto-increments by 1 per file
{_B}  Filename built from format template in <code>/es</code>

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 6 — /rename (single)
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /rename  —  Rename a Single File</b>

<i>Reply to any video file with /rename followed by the new filename. No re-encoding. Thumbnail, metadata, and watermark are applied.</i>

{_D}

<b>{_S} Usage</b>
<code>/rename &lt;new filename.ext&gt;</code>

{_Ds}

<b>{_S} Example</b>
{_A} Command:
<code>/rename [S01-E05] Pokemon [1080p].mkv</code>
{_A} Output sent to your DM:
<code>[S01-E05] Pokemon [1080p].mkv</code>
with thumbnail, metadata, watermark applied.

{_Ds}

<b>{_S} What Gets Applied</b>
{_B}  Thumbnail from your settings
{_B}  Metadata  <i>(title, author, encoder)</i>
{_B}  Watermark  <i>(if enabled in /es)</i>

{_Ds}

<b>{_S} Notes</b>
{_B}  Must reply to a video or video document
{_B}  New filename must include a valid video extension
{_B}  You write the full filename — no placeholders needed
{_B}  No re-encoding — stream-copied as-is

<code>.mp4  .mkv  .webm  .mov  .avi  .flv  .3gp</code>

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 7 — /rename -b (batch rename)
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /rename -b  —  Batch Rename an Album</b>

<i>Reply to the first file of a Telegram album with /rename -b and a filename template. Files are renamed with auto-incremented episode numbers.</i>

{_D}

<b>{_S} Usage</b>
<code>/rename -b &lt;filename template.ext&gt;</code>

{_Ds}

<b>{_S} Placeholders</b>
<code>{{season}}</code>  — season  <i>(zero-padded, from /es)</i>
<code>{{episode}}</code> — episode  <i>(auto-incremented)</i>

Only these two are valid.

{_Ds}

<b>{_S} Example</b>
{_A} Album: 3 files · Season <code>01</code> · Start ep <code>01</code>
<code>/rename -b [S{{season}}-E{{episode}}] Show.mkv</code>
{_A} Output:
  <code>[S01-E01] Show.mkv</code>
  <code>[S01-E02] Show.mkv</code>
  <code>[S01-E03] Show.mkv</code>

{_Ds}

<b>{_S} Notes</b>
{_B}  Reply to the <u>first</u> file of the album
{_B}  All files must be sent as one Telegram album
{_B}  Season &amp; start episode set in <code>/es → Placeholders</code>
{_B}  Non-video files are skipped automatically

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 8 — /mi
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /mi  —  MediaInfo Report</b>

<i>Generates a detailed MediaInfo report and publishes it to a permanent Telegraph page.</i>

{_D}

<b>{_S} Usage</b>
{_A}  Reply to a media file:  <code>/mi</code>
{_A}  With a download link:   <code>/mi &lt;url&gt;</code>
{_A}  Reply to a URL message: <code>/mi</code>

{_Ds}

<b>{_S} Example Output</b>
✅ MediaInfo ready!
📄 File: <code>Movie.mkv</code>
🔗 View: Telegraph page

{_Ds}

<b>{_S} Report Includes</b>
{_B}  General  <i>(format, size, duration, bitrate)</i>
{_B}  Video    <i>(codec, resolution, fps, colour)</i>
{_B}  Audio    <i>(codec, channels, bitrate, language)</i>
{_B}  Subtitles &amp; chapters if present

{_Ds}

<b>{_S} Notes</b>
{_B}  Only first ~3 MB downloaded for analysis
{_B}  Works on remote URLs — no upload needed
{_B}  Telegraph link is permanent and shareable

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 9 — /status
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /status  —  Live Queue &amp; Stats</b>

<i>Shows all active tasks with real-time progress. Auto-refreshes every 15 seconds.</i>

{_D}

<b>{_S} Usage</b>
<code>/status</code>  or  <code>/s</code>

{_Ds}

<b>{_S} Example</b>
<b>Task 1</b>
┃ File: <code>Movie [1080p].mkv</code>
┃ Size: 2.4 GB
┠ Resolution : <u>1080p</u>  ||  720p
┠ Status : Encoding  <i>(Job 1/2)</i>
┠ [████████░░░░░░░░░] 48.3%
┠ Elapsed: 4m 12s
┖ /cancel <code>a1b2c3d4</code>

{_Ds}

<b>{_S} Fields</b>
<b>Resolution</b> — underlined = currently active
<b>Progress</b>   — bar + percentage
<b>Speed/ETA</b>  — shown during download &amp; upload
<b>Bot Stats</b>  — CPU · RAM · Disk · Uptime

{_Ds}

<b>{_S} Notes</b>
{_B}  Auto-refreshes every 15 s
{_B}  One status message per group at a time
{_B}  Use <code>/cancel &lt;id&gt;</code> from task block to cancel

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 10 — /cancel
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} /cancel  —  Cancel a Task</b>

<i>Stops a running or queued task. Temporary files are cleaned up automatically.</i>

{_D}

<b>{_S} Usage</b>
<code>/cancel &lt;task_id&gt;</code>  or  <code>/c &lt;task_id&gt;</code>

{_Ds}

<b>{_S} Finding the Task ID</b>
Run <code>/status</code> — task ID shown at bottom of each block.

{_A} Example:  <code>┖ /cancel a1b2c3d4</code>

Only the first few characters are needed.

{_Ds}

<b>{_S} Example</b>
{_A} Input:  <code>/cancel a1b2</code>
{_A} Output: ✅ Task <code>a1b2</code> cancelled.

{_Ds}

<b>{_S} Notes</b>
{_B}  You can only cancel your own tasks
{_B}  Admins can cancel any task
{_B}  Works at any stage: queued → uploading
{_B}  Temp files deleted on cancellation
{_B}  Check <code>/status</code> if task ID not found

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 11 — Tips & Best Practices
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} Tips &amp; Best Practices</b>

{_D}

<b>{_S} Before Encoding</b>
{_B}  Configure <code>/es</code> first
{_B}  Select only the resolutions you need
{_B}  Set metadata once — applies to all tasks
{_B}  Upload thumbnail once — reused every time

{_Ds}

<b>{_S} Choosing Settings</b>
<b>Archival:</b>  CRF 18–20 · slow · libx265
<b>Streaming:</b> CRF 23–26 · medium · libx264
<b>Fast:</b>      CRF 26–28 · fast · libx264
<b>Lossless:</b>  Use <code>HDRip</code>

{_Ds}

<b>{_S} Watermark Tips</b>
{_B}  <code>range</code> mode — watermark the intro only
{_B}  <code>random</code> mode — anti-piracy overlays
{_B}  Use TTF/OTF fonts from Google Fonts

{_Ds}

<b>{_S} Queue &amp; Batch Tips</b>
{_B}  Tasks run one at a time in order
{_B}  Use <code>/status</code> to monitor position and ETA
{_B}  For batch, reply to the <u>first</u> file of the album
{_B}  Test template with a single rename first

{_D}""",


# ══════════════════════════════════════════════════════════════════════════════
# Page 12 — Do's and Don'ts
# ══════════════════════════════════════════════════════════════════════════════
f"""<b>{_H} Do's and Don'ts</b>

{_D}

<b>◆ Do</b>
✦  Run <code>/es</code> before queuing any task
✦  Always include <code>-t Title</code> in <code>/encode</code>
✦  Use <code>-b</code> flag for batch encode/rename on albums
✦  Reply to the <u>first</u> file of the album for batch
✦  Set season, episode &amp; audio in <code>/es → Placeholders</code>
✦  Start the bot in DM before using in a group

{_D}

<b>◇ Don't</b>
✦  Don't forget <code>-t</code> — it's required for <code>/encode</code>
✦  Don't use unsupported placeholders in <code>/rename -b</code>
✦  Don't send batch files as separate messages
✦  Don't queue without configuring settings first
✦  Don't select HDRip if you need a re-encode

{_D}

<b>{_S} Quick Reminders</b>
{_B}  Lower CRF = better quality, larger file
{_B}  <code>libx265</code> compresses better than <code>libx264</code>
{_B}  Use <code>/mi</code> to inspect files before encoding
{_B}  Premium accounts support uploads up to ~4 GB

{_D}""",

]

TOTAL_PAGES = len(PAGES)


# ── Sanity-check all pages at import time ──────────────────────────────────────

for _i, _p in enumerate(PAGES):
    _l = len(_p)
    if _l > 1024:
        import warnings
        warnings.warn(f"[start.py] Page {_i + 1} exceeds 1024 chars ({_l})", stacklevel=2)


# ── Keyboard builders ──────────────────────────────────────────────────────────

def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Developer", url="https://t.me/renzobot"),
            InlineKeyboardButton("Guide ⮞",  callback_data="help_open:0"),
        ],
        [
            InlineKeyboardButton("Close",  callback_data="start_close"),
        ],
    ])


def _help_keyboard(page: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⮜", callback_data=f"help_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1} / {TOTAL_PAGES}", callback_data="help_noop"))
    if page < TOTAL_PAGES - 1:
        nav.append(InlineKeyboardButton("⮞", callback_data=f"help_page:{page + 1}"))

    return InlineKeyboardMarkup([
        nav,
        [
            InlineKeyboardButton("Back",  callback_data="help_back"),
            InlineKeyboardButton("Close", callback_data="start_close"),
        ],
    ])


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _edit_message(msg, text: str, kb: InlineKeyboardMarkup):
    try:
        if msg.photo:
            await msg.edit_caption(
                caption=text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await msg.edit_text(
                text=text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
    except Exception as e:
        print(f"[EncodeBot] edit failed: {e}")


async def _show_start(message: Message, config: Config, edit: bool = False):
    kb   = _start_keyboard()
    text = START_TEXT

    if edit:
        await _edit_message(message, text, kb)
        return

    try:
        if os.path.exists(config.paths.start_image):
            await message.reply_photo(
                photo=config.paths.start_image,
                caption=text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await message.reply_text(
                text=text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        print(f"[Start] send failed: {e}")
        await message.reply_text(
            f"Welcome {message.from_user.first_name}!  Tap <b>Guide ⮞</b> for all commands.",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
        )


async def _show_help(message: Message, page: int, config: Config, edit: bool = False):
    kb   = _help_keyboard(page)
    text = PAGES[page]

    if edit:
        await _edit_message(message, text, kb)
        return

    if config.paths.help_banner and os.path.exists(config.paths.help_banner):
        try:
            await message.reply_photo(
                photo=config.paths.help_banner,
                caption=text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML,
            )
            return
        except Exception as e:
            print(f"[Help] photo send failed, falling back to text: {e}")

    await message.reply_text(
        text=text,
        reply_markup=kb,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ── Handler registration ───────────────────────────────────────────────────────

def setup_start_handler(app, config: Config):

    @app.on_message(
        filters.command(["start", "help"])
        & (filters.private | filters.chat(config.allowed_group_ids))
    )
    async def start_handler(client, message: Message):
        await _show_start(message, config)

    # Guide button on /start screen ────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_open:(\d+)$"))
    async def help_open_callback(client, callback_query: CallbackQuery):
        page = int(callback_query.data.split(":")[1])
        page = max(0, min(page, TOTAL_PAGES - 1))
        await _show_help(callback_query.message, page=page, config=config, edit=True)
        await callback_query.answer()

    # Pagination inside guide ──────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_page:(\d+)$"))
    async def help_page_callback(client, callback_query: CallbackQuery):
        page = int(callback_query.data.split(":")[1])
        page = max(0, min(page, TOTAL_PAGES - 1))
        await _show_help(callback_query.message, page=page, config=config, edit=True)
        await callback_query.answer()

    # Back → /start screen ─────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_back$"))
    async def help_back_callback(client, callback_query: CallbackQuery):
        await _show_start(callback_query.message, config=config, edit=True)
        await callback_query.answer()

    # Close → delete the message ───────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^start_close$"))
    async def start_close_callback(client, callback_query: CallbackQuery):
        try:
            await callback_query.message.delete()
        except Exception:
            await callback_query.answer("Couldn't close.", show_alert=False)
            return
        await callback_query.answer()

    # Page counter button (no-op) ──────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_noop$"))
    async def help_noop(client, callback_query: CallbackQuery):
        await callback_query.answer()