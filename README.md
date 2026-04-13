![EncodeBot Banner](https://i.ibb.co/Lz3H4kZ6/start.png)

# EncodeBot

> A Telegram-based video encoding assistant built with Pyrogram and FFmpeg.

---

## Overview

EncodeBot is a Pyrogram bot that accepts video files in a Telegram group, processes them through FFmpeg, and delivers the output to the user's DM. The entire pipeline — download, encode, upload — runs inside a single async Python process with a serialised task queue and a prefetch system to keep the pipeline busy.

---

## Architecture

### Entry Point — `__main__.py`

The bot starts by creating a new `asyncio` event loop and patching `asyncio.get_event_loop` to return it when called from threads that don't own a loop. This avoids `RuntimeError: no current event loop` on some platforms (notably Windows with `WindowsProactorEventLoopPolicy`).

A single `pyrogram.Client` is initialised with `workers=32` and `max_concurrent_transmissions=10`. All handler modules are registered against this client before it starts idle.

A `Worker` coroutine is launched as an `asyncio.Task` and runs concurrently with Pyrogram's own dispatcher via `asyncio.create_task`.

---

### Task Queue — `task_queue.py`

`TaskQueue` is an in-memory store with two data structures: a `list[str]` queue that preserves insertion order, and a `dict[str, dict]` task map keyed by a random 8-character UUID. Tasks have a lifecycle of statuses:

```
queued → starting → downloading → ready → encoding → uploading
```

`update_status` advances a task and timestamps the first transition into an active state. `_refresh_processing_flag` scans all tasks to keep a `processing` boolean accurate. `purge_stale_tasks` removes any task whose status is not in the active set, used at startup to clear leftovers from a previous crash.

Queue positions are computed by counting tasks with active statuses ahead of the target task.

---

### Worker — `worker.py`

`Worker` owns the main processing loop. It picks the next task with `status == "queued"` or `"ready"`, creates an `asyncio.Task` to run it, and awaits that task. If the task raises `CancelledError` or any other exception, the worker notifies the user via DM, removes the task, and cleans up the temporary folder.

Between finishing one task and starting the next, the worker sleeps for `TASK_COOLDOWN` (30 s) to give Telegram's rate limits time to recover. Between encode jobs within the same task (e.g. 1080p → 720p → 480p) it waits `JOB_COOLDOWN` (10 s).

**Prefetch.** After a file finishes downloading, the worker fires `_maybe_prefetch_next` as a background task. This starts a `Downloader` for the next queued task immediately, so the file arrives locally before the worker is done with the current one. If the prefetch is already complete when the worker picks up the next task, it skips the download entirely.

**Job loop.** Each task carries a `jobs` list, one entry per resolution. The worker iterates through jobs in order, calling `_encode` and `_upload` for each one. The encoded file is deleted after the upload finishes so disk space doesn't accumulate.

**Thumbnail snapshot.** Before starting a task the worker copies the user's thumbnail into the task's temporary folder. This prevents a race where the user updates their thumbnail while a task is in progress.

---

### Downloader — `downloader.py`

Calls `pyrogram.Client.download_media` with a progress callback. The callback fires on every chunk delivered by Pyrogram and maintains a `download_progress` dict with `total_size`, `downloaded`, `percentage`, `speed`, and `eta`. Speed is computed over intervals of at least 0.5 s to avoid noise from very small chunks. Progress is written both into the local dict and into `task_queue.tasks[task_id]` so the status handler can read it without any shared state.

If the file lands at a different path from the desired one (Pyrogram sometimes adjusts filenames), it is moved with `os.replace`.

---

### Encoder — `encoder.py`

Wraps `FFmpeg.build_command` and `FFmpeg.execute`. Before encoding it probes the input for duration using a four-step fallback chain:

1. `ffprobe -show_format` (container duration)
2. `ffprobe -show_entries stream=duration` on stream 0
3. `ffprobe -select_streams v:0 -show_entries stream=duration`
4. Packet count divided by frame rate for streams that don't carry a duration tag

The duration is passed to `execute` so the progress callback can compute a percentage from `out_time_us`.

A progress callback is injected into the task dict under `encode_progress.percentage` on every update. This is read directly by `status.py`'s per-task block renderer.

After FFmpeg finishes, the encoder writes to a `_tmp_{task_id}_{resolution}{ext}` path and only renames to the final filename on success, so a failed encode never leaves a partial file at the destination.

---

### FFmpeg — `ffmpeg.py`

`FFmpeg.build_command` assembles the argument list based on the `processing_mode`:

- `rename` — maps all streams with `-c copy`, injects metadata, no video filter.
- `encode` — builds a `scale` + optional `drawtext` video filter, sets codec/CRF/preset/audio, maps all stream types including subtitles, data, and attachments.

The scale filter uses `force_original_aspect_ratio=decrease` followed by a `trunc(iw/2)*2` pass to ensure both dimensions are even, which is required by most H.264 profiles.

For libx264 and libx265, per-encoder thread parameters are set explicitly (`x264-params threads=3`, `x265-params pools=3`) to control CPU usage on shared hosts.

**Watermark.** The `drawtext` filter is assembled from user settings. Position expressions map symbolic names like `bot_right` to FFmpeg geometry expressions using percentage-based padding. The timing `enable=` expression is built from three modes:

- `full` — no `enable=`, filter runs for the entire video.
- `range` — `between(t,start,end)`.
- `random_duration` — the video duration is divided into N equal sections; a random window is chosen inside each section and the clauses are joined with `+` (FFmpeg `enable` evaluates as nonzero = on).

Fonts are resolved by looking for the configured path first, falling back to a bundled `default.ttf`. The font path is escaped for FFmpeg's filter string syntax (colons, backslashes, Windows drive letters).

**Progress parsing.** When a progress callback is provided, `execute` appends `-progress pipe:1 -nostats` to the command and reads `stdout` line by line. Lines are parsed as `key=value`. `out_time_us` is used for elapsed microseconds; `out_time_ms` is deliberately skipped because FFmpeg emits the same microsecond integer for both keys and dividing by 1000 would read it as milliseconds. `out_time` (HH:MM:SS) is kept as a fallback for older FFmpeg builds.

---

### Uploader — `uploader.py`

Sends the encoded file to the user's DM using either `send_video` (streamable) or `send_document` (raw), depending on `send_type`. A `_TokenBucket` rate limiter caps upload throughput at roughly 200 MB/s to avoid saturating the MTProto connection.

If the file exceeds the Telegram size limit (1.95 GB for regular accounts, 3.95 GB for Premium), it is split. The split first attempts an FFmpeg segment split using `-f segment` and stream copy, which preserves container integrity. If that fails, it falls back to a raw byte split with an 8 MB read buffer.

Multi-part uploads track a global `_grand_total_bytes` so the progress percentage reflects the overall upload across all parts, not just the current part.

---

### Handlers

**`encode.py`** — Parses the `/e` or `/encode` command. The template must contain `{quality}` and end with a valid video extension. The `-b` flag triggers batch mode. Batch mode either collects a Telegram media group (album) or fetches N sequential message IDs starting from the replied message. A `jobs` list is built — one job per selected resolution — and passed into the task dict. `{episode}` is filled from the user's `default_start_episode` setting and zero-padded.

**`rename.py`** — Same structure as encode but `processing_mode` is always `"rename"`. Batch rename supports `{season}` and `{episode}` placeholders only; any other placeholder causes an early rejection. Single rename accepts the filename literally with no placeholder substitution.

**`settings.py`** — An inline keyboard menu with two pages. All interactive states (waiting for CRF input, waiting for font upload, etc.) are stored in a class-level `_temp_state` dict on `UserSettings`, keyed by `user_id`. When text is sent in the group, the text input handler checks this dict and routes the input to the appropriate update function before deleting both the prompt message and the user's reply to keep the group clean.

**`status.py`** — Renders a paginated status message that auto-refreshes every 3 seconds via an `asyncio` loop task. Each task gets a block with a Unicode progress bar, speed, ETA, DC number, and a cancel command. Rendering is skipped if the new content equals the last rendered content to avoid `MessageNotModified` errors. A "Cancel All" button goes through a confirm step before iterating the queue and delegating to `Worker.cancel_task`.

**`cancel.py`** — Matches a task by ID prefix. Queued tasks are removed directly. Running tasks are delegated to `Worker.cancel_task`, which cancels the asyncio task and lets `_worker_loop` handle cleanup.

**`mi.py`** — Downloads only the first 3 MB of the replied file using a partial download helper, runs `mediainfo` on it, and posts the result to a Telegraph page via `MediaInfoHelper`.

**`set.py`** — Saves a thumbnail by downloading the replied photo and delegating to `UserSettings.set_thumbnail`.

---

### User Settings — `user_setting.py`

Settings are persisted as a JSON file per user in `src/bin/users/{user_id}.json`. On load, missing keys are back-filled from defaults so old settings files remain compatible with new fields.

Each resolution has its own quality profile (CRF, preset, codec, audio bitrate) stored under `profiles`. The watermark config lives under `watermark`. Fonts and thumbnails are stored as absolute paths to files in `src/bin/fonts/` and `src/bin/thumbnails/`. When a new font is uploaded, the old one is deleted if it is in the managed fonts folder.

`_temp_state` is a class-level dict so it is shared across all `UserSettings` instances for the same user, which matters when the settings handler and the text input handler are invoked on different instances.

---

## Data Flow

```
User sends /encode template
        │
        ▼
encode.py parses command, builds jobs list
        │
        ▼
TaskQueue.create_task → task_id returned to user
        │
        ▼
Worker._worker_loop picks task
        │
        ├─► Downloader downloads file (Pyrogram MTProto)
        │          │
        │          ▼
        │   (prefetch next task in background)
        │
        ├─► for each job (resolution):
        │       Encoder runs FFmpeg → temp output file
        │       Uploader sends file to user DM
        │       temp file deleted
        │
        └─► task removed, temp folder deleted
```

---

## Installation

```bash
git clone https://github.com/KunalDahal/Toji-Encode.git
cd Toji-Encode
pip install -r requirements.txt
```

Create a `.env` file:

```env
API_ID=
API_HASH=
BOT_TOKEN=
ALLOWED_GROUP_IDS=
ADMIN_IDS=
```

Run the bot:

```bash
python main.py
```

---

## Requirements

- Python 3.10+
- FFmpeg + FFprobe
- Pyrogram + TgCrypto
- mediainfo (CLI)
- psutil, humanize, fontTools

---

## License

MIT License

## Credits

Built with Pyrogram and FFmpeg by **KunalDahal**
