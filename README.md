![EncodeBot Banner](https://i.ibb.co/Lz3H4kZ6/start.png)

# EncodeBot

> A powerful Telegram video encoding assistant built with Pyrogram.

EncodeBot lets users encode, rename, watermark, and organize video files directly from Telegram. It supports single-file operations, full album batch processing, multiple resolutions, metadata injection, queue tracking, and interactive help pages.

---

## Features

* Multi-resolution encoding (up to 4 outputs at once)
* HDRip passthrough mode with no re-encoding
* Batch encode Telegram albums
* Batch rename Telegram albums
* Per-resolution quality profiles
* Custom watermark support with timing control
* Metadata injection (title, author, encoder)
* Upload as media or document
* Queue system with live progress tracking
* Task cancellation support
* Interactive `/start` and paginated `/help` interface

---

## Supported Commands

| Command   | Description                       |
| --------- | --------------------------------- |
| `/start`  | Show the welcome screen           |
| `/help`   | Open the interactive help guide   |
| `/es`     | Open encoding settings            |
| `/encode` | Encode a single video             |
| `/be`     | Batch encode an album             |
| `/rename` | Rename a single file              |
| `/br`     | Batch rename an album             |
| `/mi`     | Generate a MediaInfo report       |
| `/status` | View current queue and task stats |
| `/cancel` | Cancel an active or queued task   |

---

# Encoding Modes

## Single File Encoding

Reply to a video and run:

```bash
/encode "Movie Name {{quality}}.mkv"
```

Example:

```bash
/encode "The Dark Knight {{quality}}.mkv"
```

If 1080p and 720p are selected, the bot generates:

```text
The Dark Knight 1080p.mkv
The Dark Knight 720p.mkv
```

### Rules

* Must be used as a reply to a video or video document
* `{{quality}}` is required in the output filename
* Output filename must end with a valid video extension
* Use quotes if the filename contains spaces

Supported extensions:

```text
.mp4 .mkv .webm .mov .avi .mpeg .flv .3gp
```

---

## Batch Encoding

Reply to the first item in a Telegram album:

```bash
/be -e 1 -s 1 -t Attack on Titan
```

Example output:

```text
Attack on Titan S01E01 [1080p].mkv
Attack on Titan S01E02 [1080p].mkv
Attack on Titan S01E03 [1080p].mkv
```

### Available Arguments

| Argument | Description                    |
| -------- | ------------------------------ |
| `-e`     | Starting episode number        |
| `-t`     | Title of the series or movie   |
| `-s`     | Season number                  |
| `-a`     | Audio label such as SUB or DUB |

---

# Filename Template System

The batch commands rely on a saved filename template.

Example template:

```text
{{title}} S{{season}}E{{episode}} [{{quality}}].mkv
```

Available placeholders:

```text
{{title}}
{{season}}
{{episode}}
{{quality}}
{{audio}}
```

### Notes

* `{{title}}`, `{{episode}}`, and `{{quality}}` are always required
* `{{audio}}` can be made optional using brackets:

```text
[{{audio}}]
```

If no audio label is provided, the entire bracketed section is removed automatically.

---

# Resolution Profiles

Each resolution has independent settings.

| Resolution | Default Configuration               |
| ---------- | ----------------------------------- |
| HDRip      | Copy only (no encoding)             |
| 1080p      | CRF 23, medium, libx264, 192k audio |
| 720p       | CRF 26, medium, libx264, 128k audio |
| 480p       | CRF 28, fast, libx264, 96k audio    |

### Adjustable Options

* CRF
* Preset
* Codec (`libx264` or `libx265`)
* Audio bitrate

---

# Watermark System

EncodeBot can burn text directly into the video.

Configurable options:

* Text
* Font (TTF / OTF)
* Font size
* Color
* Position
* Padding

### Supported Timing Modes

| Mode     | Description                            |
| -------- | -------------------------------------- |
| `full`   | Entire video duration                  |
| `range`  | Between start and end seconds          |
| `random` | Random start time for a fixed duration |

### Supported Positions

```text
top-left     top-center     top-right
mid-left     mid-center     mid-right
bottom-left  bottom-center  bottom-right
```

---

# Metadata Injection

Each encoded or renamed file can include:

* Title
* Author
* Encoder tag

Metadata is automatically embedded into every output file.

---

# Queue System

EncodeBot processes one task at a time.

The `/status` command shows:

* Current active task
* Queue position
* Download / Encode / Upload stage
* CPU usage
* RAM usage
* Free disk space
* Bot uptime

Queued tasks also include a ready-to-use cancellation command.

Example:

```bash
/cancel a3f9c1b2
```

---

# MediaInfo Support

Generate technical reports using:

```bash
/mi
```

Supported input methods:

1. Reply to a media file
2. Provide a direct media URL
3. Reply to a message containing a URL

The report includes:

* General container information
* Video details
* Audio track details
* Subtitle information
* Chapters / menu data

---

# Installation

```bash
git clone https://github.com/KunalDahal/Toji-Encode.git
cd encodebot
pip install -r requirements.txt
```

Create a configuration file and provide:

```env
API_ID=
API_HASH=
BOT_TOKEN=
OWNER_ID=
```

Then run:

```bash
python main.py
```

---

# Project Structure

```text
src/
├── handlers/
│   ├── start.py
│   ├── encode.py
│   ├── batch_encode.py
│   ├── rename.py
│   ├── batch_rename.py
│   ├── status.py
│   └── mediainfo.py
├── utils/
├── config/
└── main.py
```

---

# Screenshots / Preview

You may want to include:

* `/start` welcome screen
* Help page navigation
* Encoding progress view
* Queue status page
* Settings menu

---

# Requirements

* Python 3.10+
* Pyrogram
* FFmpeg
* TgCrypto

Install FFmpeg before running the bot.

Ubuntu:

```bash
sudo apt update
sudo apt install ffmpeg
```

---

# License

This project is licensed under the MIT License.

```text
MIT License
```

---

# Credits

* Built with Pyrogram
* Powered by FFmpeg
* Designed for Telegram media workflows
* By KunalDahal
