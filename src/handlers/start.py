import os
from pyrogram import filters, enums
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from src import Config


# ── Start text ────────────────────────────────────────────────────────────────

START_TEXT = """<b>TojiEncodeBot</b>  <i>— Video Encoding & Renaming Assistant</i>

<blockquote>Drop a video or an album, configure your settings, and receive
perfectly processed files — all without leaving Telegram.</blockquote>

&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;

&#9670;  Multi-resolution encoding  <i>(up to 4 at once)</i>
&#9670;  Batch encode or rename entire albums in one command
&#9670;  Per-resolution quality profiles  <i>(CRF, preset, codec)</i>
&#9670;  Custom watermark with timing control
&#9670;  Metadata embedding on every output
&#9670;  Live queue and progress tracking

&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;&#9135;

<code>/es</code>  to configure  &#183;  tap <b>Guide</b> for the full reference"""

# ── Help pages (all ≤ 1024 rendered chars for photo caption compatibility) ────

_D = "&#9135;" * 18   # divider
_B = "&#9675;"         # bullet  ○
_A = "&#8594;"         # arrow   →
_V = "&#8627;"         # down    ↳

PAGES = [

# ── Page 1 — Index ────────────────────────────────────────────────────────────
f"""<b>EncodeBot</b>  <i>— Complete Guide</i>

<blockquote>Every command explained in full detail.
Navigate page by page using the arrows below.</blockquote>

{_D}

<b>Command Index</b>

  <code>/es</code>      &#8212;  Settings panel            pg 2&#8211;3
  <code>/encode</code>  &#8212;  Encode a single file      pg 4
  <code>/be</code>      &#8212;  Batch encode an album     pg 5
  <code>/rename</code>  &#8212;  Rename a single file      pg 6
  <code>/br</code>      &#8212;  Batch rename an album     pg 7
  <code>/mi</code>      &#8212;  MediaInfo report          pg 8
  <code>/status</code>  &#8212;  Live queue &amp; stats        pg 9
  <code>/cancel</code>  &#8212;  Stop a running task       pg 10
  <code>/start</code>   &#8212;  Introduction screen

{_D}
<i>Page 1 / 12  &#8212;  tap &#11158; to begin</i>""",


# ── Page 2 — /es (1/2) ───────────────────────────────────────────────────────
f"""<b>&#9632; /es  &#8212;  Settings  (1/2)</b>

<blockquote>Opens an interactive panel.  All settings are saved
per user and persist across every session.</blockquote>

{_D}

<b>&#9112; Resolution</b>
<blockquote>Select one or more output resolutions  (max 4 per task).
  <code>HDRip  &#183;  1080p  &#183;  720p  &#183;  480p</code>

<code>HDRip</code> = stream-copy + metadata only.  No re-encode ever.
Use it to preserve the original quality untouched.</blockquote>

<b>&#9112; Quality Profile  <i>(per resolution)</i></b>
<blockquote>Each resolution has its own independent profile.

  <b>CRF</b>     &#8212;  0&#8211;51  (lower = better quality, bigger file)
  <b>Preset</b>  &#8212;  ultrafast / fast / medium / slow / veryslow
  <b>Codec</b>   &#8212;  <code>libx264</code>  or  <code>libx265</code>
  <b>Audio</b>   &#8212;  bitrate e.g. <code>96k  128k  192k  320k</code>

Defaults:
  HDRip  &#8212;  copy only
  1080p  &#8212;  CRF 23, medium, libx264, 192k
  720p   &#8212;  CRF 26, medium, libx264, 128k
  480p   &#8212;  CRF 28, fast,   libx264,  96k</blockquote>

{_D}
<i>Page 2 / 12  &#8212;  continued &#11158;</i>""",


# ── Page 3 — /es (2/2) ───────────────────────────────────────────────────────
f"""<b>&#9632; /es  &#8212;  Settings  (2/2)</b>

{_D}

<b>&#9112; Send Type</b>
<blockquote><code>Media</code>     &#8212;  sent as a streamable video
<code>Document</code>  &#8212;  sent as a raw file (no compression)</blockquote>

<b>&#9112; Metadata</b>
<blockquote>Embedded into every output file automatically.
  <b>Title</b>    &#8212;  film or episode name
  <b>Author</b>   &#8212;  your name or channel
  <b>Encoder</b>  &#8212;  encoder tag string</blockquote>

<b>&#9112; Thumbnail</b>
<blockquote>Cover image attached on every upload.
Send a JPEG or PNG via /es to set it.</blockquote>

<b>&#9112; Watermark</b>
<blockquote>Text burned onto the video track.
  Fields: text, font (TTF/OTF), size, colour, position, padding

  Timing: <code>full</code> (all) &#183; <code>range</code> (start&#8211;end sec) &#183; <code>random</code> (duration, random start)
  Positions: top/mid/bot &#215; left/mid/right  (9 total)</blockquote>

<b>&#9112; Filename Format</b>
<blockquote>Template used by <code>/be</code> and <code>/br</code> to name output files.
Set it here via /es &#8594; Filename Format.
Placeholders: <code>{{title}} {{season}} {{episode}} {{quality}} {{audio}}</code>
<code>{{title}}</code>, <code>{{episode}}</code>, <code>{{quality}}</code> are always required.
<code>[{{audio}}]</code> in brackets is auto-dropped when -a is not passed.
The bot validates your command against the template and will
tell you exactly which argument is missing if anything is wrong.</blockquote>

{_D}
<i>Page 3 / 12</i>""",


# ── Page 4 — /encode ──────────────────────────────────────────────────────────
f"""<b>&#9632; /encode  &#8212;  Encode a Single File</b>

<blockquote>Reply to a video, then run this command with an output filename.
The bot downloads, encodes at each resolution, and uploads
each output to your DM automatically.</blockquote>

{_D}

<b>Syntax</b>
<blockquote><code>/encode "Filename {{quality}}.ext"</code></blockquote>

<b>Rules</b>
<blockquote>{_B}  Must be a reply to a video or video document
{_B}  <code>{{quality}}</code> placeholder is required in the filename
{_B}  Must end with a valid video extension
{_B}  Wrap filenames in quotes if they contain spaces</blockquote>

<b>Extensions</b>
<blockquote><code>.mp4  .mkv  .webm  .mov  .avi  .mpeg  .flv  .3gp</code></blockquote>

<b>Example</b>
<blockquote>Settings: 1080p + 720p selected
<code>/encode "Dark Knight {{quality}}.mkv"</code>

Output to your DM:
  {_V}  Dark Knight 1080p.mkv
  {_V}  Dark Knight 720p.mkv</blockquote>

<b>What gets applied</b>
<blockquote>Resolution scaling with aspect-ratio padding
CRF / preset / codec from the per-resolution profile
Watermark burn-in <i>(if enabled)</i>  &#183;  Metadata  &#183;  Thumbnail
<code>HDRip</code> skips all encoding — stream-copy + metadata only</blockquote>

<b>Flow per resolution</b>
<blockquote>Download  {_A}  Encode  {_A}  Upload to DM  {_A}  next resolution</blockquote>

{_D}
<i>Page 4 / 12</i>""",


# ── Page 5 — /be ──────────────────────────────────────────────────────────────
f"""<b>&#9632; /be  &#8212;  Batch Encode an Album</b>

<blockquote>Queues an entire Telegram album for encoding in one command.
Episode numbers are assigned automatically from -e onward.
Uses your saved filename template and encoding settings.</blockquote>

{_D}

<b>Syntax</b>  <i>(reply to first file in the album)</i>
<blockquote><code>/be -e &lt;ep&gt; -t &lt;title&gt; [-s &lt;season&gt;] [-a &lt;audio&gt;]</code></blockquote>

<b>Arguments</b>
<blockquote><code>-e</code>  Starting episode number   <i>required</i>
<code>-t</code>  Show or movie title        <i>required — always last</i>
<code>-s</code>  Season number              <i>optional, default: 1</i>
<code>-a</code>  Audio label (SUB/DUB/etc)  <i>optional</i></blockquote>

<b>Which arguments are required?</b>
<blockquote>The bot checks your saved template and only requires the
arguments that match the placeholders present in it.

Template: <code>{{title}} S{{season}}E{{episode}} [{{quality}}].mkv</code>
{_A}  <code>-e</code> and <code>-t</code> required  &#183;  <code>-s</code> defaults to 1  &#183;  <code>-a</code> not needed

Template: <code>{{title}} S{{season}}E{{episode}} [{{quality}}] [{{audio}}].mkv</code>
{_A}  All four required  <i>({{audio}} without brackets forces -a)</i>

Template: <code>{{title}} S{{season}}E{{episode}} [{{quality}}] [{{audio}}].mkv</code>
wrapped as <code>[{{audio}}]</code> &#8594; <code>-a</code> is optional; bracket auto-drops if omitted.</blockquote>

<b>Example</b>
<blockquote>Album: 3 files  &#183;  Template: <code>{{title}} S{{season}}E{{episode}} [{{quality}}].mkv</code>
<code>/be -e 5 -s 2 -t Attack on Titan</code>

Output to DM:
  {_V}  Attack on Titan S02E05 [1080p].mkv
  {_V}  Attack on Titan S02E06 [1080p].mkv
  {_V}  Attack on Titan S02E07 [1080p].mkv</blockquote>

<b>Notes</b>
<blockquote>{_B}  Template must be set first via /es {_A} Filename Format
{_B}  Template must include <code>{{title}}</code>, <code>{{episode}}</code>, <code>{{quality}}</code>
{_B}  Each file gets its own task ID — cancel individually if needed
{_B}  Non-video files in the album are skipped automatically</blockquote>

{_D}
<i>Page 5 / 12</i>""",


# ── Page 6 — /rename ──────────────────────────────────────────────────────────
f"""<b>&#9632; /rename  &#8212;  Rename a Single File</b>

<blockquote>Renames any video with a new filename.
Injects your saved metadata and optionally burns a watermark.
No encoding configuration or {{quality}} placeholder needed.</blockquote>

{_D}

<b>Syntax</b>
<blockquote><code>/rename "New Filename.ext"</code>
Reply to the target video first.</blockquote>

<b>Example</b>
<blockquote><code>/rename "Inception.2010.BluRay.mkv"</code>

Output to your DM:
  {_V}  Inception.2010.BluRay.mkv</blockquote>

<b>What gets applied</b>
<blockquote>{_B}  New filename
{_B}  Metadata  <i>(Title, Author, Encoder from /es)</i>
{_B}  Thumbnail on upload
{_B}  Watermark  <i>(only if enabled in /es)</i></blockquote>

<b>Encoding behaviour</b>
<blockquote><u>Watermark disabled</u>
Pure stream-copy.  Video, audio, subtitles, fonts and all
metadata preserved with zero quality loss.  Fastest operation.

<u>Watermark enabled</u>
Video re-encoded at CRF 18 using the source codec
<i>(H.264 or H.265 auto-detected)</i>.  Audio, subtitles, and
fonts are still stream-copied.  Only video track is touched.</blockquote>

{_D}
<i>Page 6 / 12</i>""",


# ── Page 7 — /br ──────────────────────────────────────────────────────────────
f"""<b>&#9632; /br  &#8212;  Batch Rename an Album</b>

<blockquote>Renames an entire Telegram album in one command.
Quality label is supplied manually via -q (not auto-detected).
Applies metadata and watermark the same way as /rename.</blockquote>

{_D}

<b>Syntax</b>  <i>(reply to first file in the album)</i>
<blockquote><code>/br -e &lt;ep&gt; -q &lt;quality&gt; -t &lt;title&gt; [-s &lt;season&gt;] [-a &lt;audio&gt;]</code></blockquote>

<b>Arguments</b>
<blockquote><code>-e</code>  Starting episode number   <i>required</i>
<code>-q</code>  Quality label              <i>required  e.g. HDRip BluRay WEBRip</i>
<code>-t</code>  Show or movie title        <i>required — always last</i>
<code>-s</code>  Season number              <i>optional, default: 1</i>
<code>-a</code>  Audio label                <i>optional</i></blockquote>

<b>Which arguments are required?</b>
<blockquote>The bot checks your saved template and only requires the
arguments that match the placeholders present in it.

If your template has <code>{{quality}}</code> {_A} <code>-q</code> is required.
If your template has <code>{{audio}}</code> without brackets {_A} <code>-a</code> is required.
If your template has <code>[{{audio}}]</code> {_A} <code>-a</code> is optional; bracket auto-drops.</blockquote>

<b>Example</b>
<blockquote>Template: <code>{{title}} S{{season}}E{{episode}} [{{quality}}].mkv</code>
<code>/br -e 1 -s 1 -q HDRip -t Demon Slayer</code>

Output to DM:
  {_V}  Demon Slayer S01E01 [HDRip].mkv
  {_V}  Demon Slayer S01E02 [HDRip].mkv  … etc.</blockquote>

<b>Notes</b>
<blockquote>{_B}  -q fills {{quality}} literally — any label works (BluRay, WEBRip…)
{_B}  Template must be set via /es {_A} Filename Format
{_B}  Each file gets its own task ID
{_B}  Non-video files in the album are skipped</blockquote>

{_D}
<i>Page 7 / 12</i>""",


# ── Page 8 — /mi ──────────────────────────────────────────────────────────────
f"""<b>&#9632; /mi  &#8212;  MediaInfo Report</b>

<blockquote>Generates a full technical report and publishes it to Telegraph.
Only the first 3 MB (container header) is downloaded —
fast even on multi-gigabyte files.</blockquote>

{_D}

<b>Three ways to use it</b>

<b>1.  Reply to a media file</b>
<blockquote>Reply to any video, audio, or document with <code>/mi</code>.</blockquote>

<b>2.  Pass a direct link</b>
<blockquote><code>/mi https://example.com/video.mkv</code>
URL is passed directly to MediaInfo — no server download.</blockquote>

<b>3.  Reply to a message containing a link</b>
<blockquote>Reply to any message that has a URL.
Bot extracts the first URL found and analyses it.</blockquote>

<b>Report includes</b>
<blockquote>{_B}  General  &#8212;  container, duration, bitrate, file size
{_B}  Video    &#8212;  codec, resolution, FPS, bit depth, HDR
{_B}  Audio    &#8212;  codec, channels, sample rate, language
{_B}  Subtitle &#8212;  format and language (per track)
{_B}  Menu     &#8212;  chapter markers (if present)</blockquote>

<b>Output</b>
<blockquote>A Telegraph link is sent in the chat.
Publicly accessible and shareable.</blockquote>

{_D}
<i>Page 8 / 12</i>""",


# ── Page 9 — /status ──────────────────────────────────────────────────────────
f"""<b>&#9632; /status  &#8212;  Live Queue &amp; Stats</b>

<blockquote>Shows all active and queued tasks in real time.
Five tasks per page, with refresh and pagination controls.</blockquote>

{_D}

<b>Active task</b>
<blockquote>The currently running task shows its live stage:
  <code>Downloading</code>  &#8212;  fetching file from Telegram
  <code>Encoding</code>     &#8212;  FFmpeg is processing  <i>(CPU-bound)</i>
  <code>Uploading</code>    &#8212;  sending output to user&#39;s DM

For multi-resolution tasks, the current job index
and resolution are shown alongside the stage.</blockquote>

<b>Queued tasks</b>
<blockquote>Each waiting task shows:
  {_B}  Output filename  &#183;  File size
  {_B}  Resolution pipeline  e.g.  1080p {_A} 720p {_A} 480p
  {_B}  Number of jobs  &#183;  User handle and Telegram ID
  {_B}  Ready-to-use cancel shortcut:  <code>/cancel xxxxxxxx</code></blockquote>

<b>Footer stats</b>
<blockquote>CPU %  &#183;  RAM %  &#183;  Free disk  &#183;  Bot uptime</blockquote>

<b>Buttons</b>
<blockquote>&#11157;  Previous page    &#8635;  Refresh    &#11158;  Next page</blockquote>

{_D}
<i>Page 9 / 12</i>""",


# ── Page 10 — /cancel ─────────────────────────────────────────────────────────
f"""<b>&#9632; /cancel  &#8212;  Stop a Running Task</b>

<blockquote>Cancels a queued or actively processing task immediately.
All temporary files for that task are cleaned up automatically.</blockquote>

{_D}

<b>Syntax</b>
<blockquote><code>/cancel &lt;task_id&gt;</code>
A partial ID (first 8 chars) is accepted.</blockquote>

<b>How to find the Task ID</b>
<blockquote>1.  The bot replies with the Task ID when you queue any task.
2.  Run <code>/status</code> — each task block shows a ready-to-use
    cancel command at the bottom: <code>/cancel xxxxxxxx</code></blockquote>

<b>Example</b>
<blockquote><code>/cancel a3f9c1b2</code>
Bot replies: <i>Task a3f9c1b2 cancelled.</i></blockquote>

<b>What happens on cancel</b>
<blockquote>{_B}  Running FFmpeg process is terminated immediately
{_B}  In-progress download or upload is stopped
{_B}  All temp files for that task are deleted from disk
{_B}  User receives a cancellation message in their DM
{_B}  The next queued task starts automatically</blockquote>

<b>Permissions</b>
<blockquote>Admins can cancel any task.
Regular users can only cancel their own tasks.</blockquote>

{_D}
<i>Page 10 / 12</i>""",


# ── Page 11 — General notes ───────────────────────────────────────────────────
f"""<b>&#9633; Things to Keep in Mind</b>

{_D}

<b>&#9112; Setup first</b>
<blockquote>Configure /es before your first task.  Settings persist between
sessions — do it once, update only when you want to change something.
For /be and /br, set a filename template via /es &#8594; Filename Format.</blockquote>

<b>&#9112; Start the bot in DM</b>
<blockquote>All files are delivered to your <b>private DM</b>, not the group.
Open a private chat with the bot and press Start before queuing —
otherwise uploads will fail.</blockquote>

<b>&#9112; Filename rules</b>
<blockquote>{_B}  <code>{{quality}}</code> is required in /encode filenames
{_B}  <code>{{quality}}</code> is NOT used in /rename (no placeholder needed)
{_B}  /be and /br use the template set via /es &#8594; Filename Format
{_B}  Always use a valid video extension (.mp4, .mkv, etc.)</blockquote>

<b>&#9112; HDRip is a passthrough</b>
<blockquote>HDRip = stream-copy + metadata only.  No re-encode, no resize.
Use it to preserve the source quality exactly as-is.</blockquote>

<b>&#9112; Queue</b>
<blockquote>One task at a time.  Multiple users can queue tasks — they run
in order of submission.  Use /status to check your position.</blockquote>

{_D}
<i>Page 11 / 12</i>""",


# ── Page 12 — Troubleshooting ─────────────────────────────────────────────────
f"""<b>&#9633; Troubleshooting</b>

{_D}

<b>&#9632; Upload fails: "start the bot in DM first"</b>
<blockquote>Open a private chat with the bot and press Start,
then re-queue your task.</blockquote>

<b>&#9632; Encoding fails with an FFmpeg error</b>
<blockquote>{_B}  Source file is corrupted or truncated
{_B}  Unsupported container (check extension list)
{_B}  Server disk full — check the disk line in /status</blockquote>

<b>&#9632; Watermark font not applying</b>
<blockquote>Some TTF files are rejected by FFmpeg's drawtext filter.
Fix: use a plain static-weight TTF from Google Fonts.
Upload via /es {_A} Watermark {_A} Font.</blockquote>

<b>&#9632; HDRip still shows original resolution</b>
<blockquote>Expected — HDRip is stream-copy, resolution never changes.
Pick 1080p / 720p / 480p if you need a resize.</blockquote>

<b>&#9632; Watermark timing is wrong</b>
<blockquote><code>full</code> &#8212; entire video  &#183;  <code>range</code> &#8212; fixed start + end seconds
<code>random</code> &#8212; set duration, start is chosen randomly
End &#8804; start in range mode defaults to full duration.</blockquote>

<b>&#9632; Task frozen on Downloading</b>
<blockquote>Large files take time.  If no progress for 30+ min,
cancel and re-queue.</blockquote>

{_D}
<i>Page 12 / 12  &#8212;  end of guide</i>""",

]

TOTAL_PAGES = len(PAGES)


# ── Keyboard builders ─────────────────────────────────────────────────────────

def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Developer", url="https://t.me/Renzo"),
            InlineKeyboardButton("Guide",     callback_data="help_open:0"),
        ],
        [
            InlineKeyboardButton("Close",     callback_data="start_close"),
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


# ── Internal helpers ──────────────────────────────────────────────────────────

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
            f"Welcome {message.from_user.first_name}!  Tap Guide for all commands.",
            reply_markup=kb,
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
            print(f"[Help] photo send failed, falling back: {e}")

    await message.reply_text(
        text=text,
        reply_markup=kb,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ── Handler registration ──────────────────────────────────────────────────────

def setup_start_handler(app, config: Config):

    @app.on_message(filters.command(["start", "help"]) & (filters.private | filters.chat(config.allowed_group_ids)))
    async def start_handler(client, message: Message):
        await _show_start(message, config)

    # Guide button on /start screen ───────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_open:(\d+)$"))
    async def help_open_callback(client, callback_query: CallbackQuery):
        page = int(callback_query.data.split(":")[1])
        page = max(0, min(page, TOTAL_PAGES - 1))
        await _show_help(callback_query.message, page=page, config=config, edit=True)
        await callback_query.answer()

    # Pagination inside guide ─────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_page:(\d+)$"))
    async def help_page_callback(client, callback_query: CallbackQuery):
        page = int(callback_query.data.split(":")[1])
        page = max(0, min(page, TOTAL_PAGES - 1))
        await _show_help(callback_query.message, page=page, config=config, edit=True)
        await callback_query.answer()

    # Back → /start screen ────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_back$"))
    async def help_back_callback(client, callback_query: CallbackQuery):
        await _show_start(callback_query.message, config=config, edit=True)
        await callback_query.answer()

    # Close → delete the message ──────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^start_close$"))
    async def start_close_callback(client, callback_query: CallbackQuery):
        try:
            await callback_query.message.delete()
        except Exception:
            await callback_query.answer("Couldn't close.", show_alert=False)
            return
        await callback_query.answer()

    # Page counter button (no-op) ─────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^help_noop$"))
    async def help_noop(client, callback_query: CallbackQuery):
        await callback_query.answer()