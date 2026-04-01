import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from datetime import datetime
from math import ceil
import humanize
import psutil
import time

BOT_START_TIME = time.time()

# chat_id → message_id of the currently open status message in that chat
_active_status: dict[int, int] = {}

# chat_id → asyncio.Task running the auto-refresh loop for that chat
_refresh_tasks: dict[int, asyncio.Task] = {}

AUTO_REFRESH_INTERVAL = 15   # seconds

# Statuses that count as "active" (mirrors task_queue.py)
_ACTIVE_STATUSES = frozenset({
    "starting", "queued", "downloading", "encoding", "uploading"
})


async def _check_access(client, message: Message, admin_ids: list) -> bool:
    user_id = message.from_user.id

    if user_id not in admin_ids:
        await message.reply_text("Dukhi Atma!😔", parse_mode=enums.ParseMode.HTML)
        return False

    try:
        await client.get_chat(user_id)
    except Exception:
        bot_username = (await client.get_me()).username
        await message.reply_text(
            f"⚠️ Please start the bot in DM first.\n"
            f"👉 @{bot_username} — press <b>Start</b>, then try again.",
            parse_mode=enums.ParseMode.HTML,
        )
        return False

    return True


def setup_status_handlers(app: Client, task_queue, admin_ids, config):

    allowed_group_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["s", "status"]) & allowed_group_filter)
    async def status_command(client: Client, message: Message):
        if not await _check_access(client, message, admin_ids):
            return

        chat_id = message.chat.id

        _cancel_refresh(chat_id)

        old_msg_id = _active_status.get(chat_id)
        if old_msg_id:
            try:
                await client.delete_messages(chat_id, old_msg_id)
            except Exception:
                pass
            _active_status.pop(chat_id, None)

        sent = await _send_status(client, message, task_queue, page=0)
        if sent:
            _active_status[chat_id] = sent.id
            task = asyncio.create_task(
                _auto_refresh_loop(client, chat_id, sent, task_queue, admin_ids)
            )
            _refresh_tasks[chat_id] = task

    @app.on_callback_query(filters.regex(r"^status_page:(.+):(.+)$"))
    async def status_callback(client: Client, callback_query: CallbackQuery):
        if callback_query.from_user.id not in admin_ids:
            await callback_query.answer("Invalid!", show_alert=True)
            return

        _, action, page_str = callback_query.data.split(":")
        page = int(page_str)

        if action == "prev":
            page = max(0, page - 1)
        elif action == "next":
            page = page + 1

        await show_status(client, callback_query.message, task_queue, page, is_callback=True)
        await callback_query.answer()

    @app.on_callback_query(filters.regex(r"^status_close$"))
    async def status_close_callback(client: Client, callback_query: CallbackQuery):
        if callback_query.from_user.id not in admin_ids:
            await callback_query.answer("Invalid!", show_alert=True)
            return
        chat_id = callback_query.message.chat.id
        _cancel_refresh(chat_id)
        _active_status.pop(chat_id, None)
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.answer("Status closed.")


# ── Auto-refresh loop ─────────────────────────────────────────────────────────

def _cancel_refresh(chat_id: int):
    task = _refresh_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


async def _auto_refresh_loop(
    client: Client,
    chat_id: int,
    status_msg: Message,
    task_queue,
    admin_ids: list,
):
    try:
        while True:
            await asyncio.sleep(AUTO_REFRESH_INTERVAL)
            if _active_status.get(chat_id) != status_msg.id:
                break
            try:
                await show_status(client, status_msg, task_queue, page=0, is_callback=True)
            except Exception:
                break
    except asyncio.CancelledError:
        pass


# ── Status sender ─────────────────────────────────────────────────────────────

async def _send_status(
    client: Client,
    message: Message,
    task_queue,
    page: int = 0,
) -> Message | None:
    text, reply_markup = _build_status_content(task_queue, page)
    try:
        return await message.reply_text(
            text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except Exception as e:
        print(f"[status] send failed: {e}")
        return None


# ── Main status renderer ──────────────────────────────────────────────────────

async def show_status(
    client: Client,
    message: Message,
    task_queue,
    page: int = 0,
    is_callback: bool = False,
):
    text, reply_markup = _build_status_content(task_queue, page)
    parse_mode = enums.ParseMode.HTML

    if is_callback:
        try:
            await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            pass
    else:
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


def _build_status_content(task_queue, page: int) -> tuple[str, InlineKeyboardMarkup | None]:
    # ── Collect ALL active tasks in queue order ───────────────────────────────
    # Pipeline mode can have multiple tasks simultaneously active
    # (one downloading, one encoding, one uploading). We must not rely on
    # get_current_task() which only tracks the most-recently-started task.
    all_active = []
    for task_id in task_queue.queue:
        task = task_queue.get_task(task_id)
        if task and task.get("status") in _ACTIVE_STATUSES:
            all_active.append(task)

    items_per_page = 5
    total_pages    = ceil(len(all_active) / items_per_page) if all_active else 1
    page           = min(page, total_pages - 1)
    start_idx      = page * items_per_page
    page_tasks     = all_active[start_idx: start_idx + items_per_page]

    status_text = ""

    for i, task in enumerate(page_tasks, start=start_idx + 1):
        user_info   = f"@{task['username']}" if task.get("username") else task.get("first_name", "Unknown")
        user_id     = task["user_id"]
        filename    = (
            task.get("output_filename")
            or task.get("file_name")
            or task.get("original_file_name")
            or "Unknown"
        )
        elapsed     = _format_elapsed(task.get("started_at"))
        task_status = task["status"]
        job_label   = _build_job_label(task)

        status_text += f"<b>Task {i}</b>\n"

        if task_status == "downloading":
            prog           = _get_download_progress(task)
            total_size_str = (
                humanize.naturalsize(prog["total_size"], binary=True)
                if prog["total_size"] else "unknown size"
            )
            pct       = prog.get("percentage", 0)
            speed_str = _fmt_speed(prog.get("speed", 0))
            eta_str   = _fmt_eta(prog.get("eta", 0))

            status_text += f"┃ File: <code>{filename}</code>\n"
            status_text += f"┃ Size: {total_size_str}\n"
            status_text += f"┠ ⬇ Downloading: <b>{pct:.1f}%</b>"
            if speed_str:
                status_text += f" | {speed_str}"
            if eta_str and pct < 99:
                status_text += f" | ETA {eta_str}"
            status_text += "\n"
            status_text += f"┠ Elapsed: {elapsed}\n"

        elif task_status == "encoding":
            mode       = task.get("current_job_mode", "encode")
            mode_label = "copy+meta" if mode == "metadata_only" else (
                "rename" if mode == "rename" else "encoding"
            )
            status_text += f"┃ File: <code>{filename}</code>\n"
            if job_label:
                status_text += f"┃ {job_label}  <i>({mode_label})</i>\n"
            else:
                status_text += f"┃ Mode: <i>{mode_label}</i>\n"
            status_text += f"┠ ⚙ Encoding…  <i>(CPU)</i>\n"
            status_text += f"┠ Elapsed: {elapsed}\n"

        elif task_status == "uploading":
            prog           = _get_upload_progress(task)
            total_size_str = (
                humanize.naturalsize(prog["total_size"], binary=True)
                if prog["total_size"] else "unknown size"
            )
            pct       = prog.get("percentage", 0)
            speed_str = _fmt_speed(prog.get("speed", 0))
            eta_str   = _fmt_eta(prog.get("eta", 0))

            status_text += f"┃ File: <code>{filename}</code>\n"
            if job_label:
                status_text += f"┃ {job_label}\n"
            status_text += f"┃ Size: {total_size_str}\n"
            status_text += f"┠ ⬆ Uploading: <b>{pct:.1f}%</b>"
            if speed_str:
                status_text += f" | {speed_str}"
            if eta_str and pct < 99:
                status_text += f" | ETA {eta_str}"
            status_text += "\n"
            status_text += f"┠ Elapsed: {elapsed}\n"

        else:
            # queued / starting
            file_size   = task.get("file_size", 0)
            size_str    = humanize.naturalsize(file_size, binary=True) if file_size else "unknown size"
            total_jobs  = task.get("total_jobs") or len(task.get("jobs", []))
            resolutions = " → ".join(task.get("resolutions", [task.get("resolution", "?")]))
            status_text += f"┃ File: <code>{filename}</code>\n"
            status_text += f"┃ Size: {size_str}\n"
            status_text += f"┃ Pipeline: <code>{resolutions}</code>  ({total_jobs} job{'s' if total_jobs != 1 else ''})\n"
            status_text += f"┠ ⏳ Queued\n"

        status_text += f"┠ User: {user_info}  ID: <code>{user_id}</code>\n"
        status_text += f"┖ <code>/cancel {task['task_id'][:8]}</code>\n"

        if i < start_idx + len(page_tasks):
            status_text += "▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁\n"

    if not all_active:
        status_text = "✅ No tasks in queue.\n\n"

    cpu_pct    = psutil.cpu_percent(interval=0.1)
    mem        = psutil.virtual_memory()
    disk       = psutil.disk_usage("/")
    uptime_str = _format_uptime(int(time.time() - BOT_START_TIME))
    free_disk  = humanize.naturalsize(disk.free, binary=True)
    disk_pct   = disk.used / disk.total * 100

    status_text += (
        f"\n<b>⌬ Bot Stats</b>\n"
        f"┠ Tasks: {len(all_active)}\n"
        f"┠ CPU: {cpu_pct}%  Disk: {free_disk} free [{disk_pct:.1f}%]\n"
        f"┖ RAM: {mem.percent}%  Uptime: {uptime_str}"
    )

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⮜", callback_data=f"status_page:prev:{page}"))
    nav_buttons.append(InlineKeyboardButton("🔄", callback_data=f"status_page:refresh:{page}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("⮞", callback_data=f"status_page:next:{page}"))

    bottom_row = [InlineKeyboardButton("✕ Close", callback_data="status_close")]

    rows = []
    if nav_buttons:
        rows.append(nav_buttons)
    rows.append(bottom_row)

    reply_markup = InlineKeyboardMarkup(rows)
    return status_text, reply_markup


# ── Progress helpers ──────────────────────────────────────────────────────────

def _get_download_progress(task: dict) -> dict:
    base = {
        "total_size": task.get("file_size", 0),
        "downloaded": 0,
        "percentage": float(task.get("progress", 0)),
        "speed":      0,
        "eta":        0,
    }
    details = task.get("progress_details", {})
    if details and task.get("status") == "downloading":
        base.update({
            "percentage": details.get("percentage", base["percentage"]),
            "downloaded": details.get("downloaded", base["downloaded"]),
            "total_size": details.get("total_size") or base["total_size"],
            "speed":      details.get("speed", 0),
            "eta":        details.get("eta", 0),
        })
    return base


def _get_upload_progress(task: dict) -> dict:
    base = {
        "total_size": task.get("file_size", 0),
        "uploaded":   0,
        "percentage": float(task.get("progress", 0)),
        "speed":      0,
        "eta":        0,
    }
    up = task.get("upload_progress", {})
    if up and up.get("total_size"):
        base.update({
            "total_size": up["total_size"],
            "uploaded":   up.get("uploaded", base["uploaded"]),
            "percentage": up.get("percentage", base["percentage"]),
            "speed":      up.get("speed", 0),
            "eta":        up.get("eta", 0),
        })
    return base


# ── Format helpers ────────────────────────────────────────────────────────────

def _fmt_speed(bytes_per_sec: float) -> str:
    if not bytes_per_sec or bytes_per_sec < 100:
        return ""
    return f"{humanize.naturalsize(bytes_per_sec, binary=True)}/s"


def _fmt_eta(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return ""
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m"
    if seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s}s"
    return f"{seconds}s"


def _build_job_label(task: dict) -> str:
    resolution  = task.get("resolution", "")
    current_job = task.get("current_job", 0)
    total_jobs  = task.get("total_jobs") or len(task.get("jobs", []))
    if not resolution or resolution == "rename":
        return ""
    if total_jobs and total_jobs > 1:
        return f"⚙ <b>{resolution}</b>  <i>(Job {current_job}/{total_jobs})</i>"
    return f"⚙ <b>{resolution}</b>"


def _format_elapsed(started_at: str) -> str:
    if not started_at:
        return "—"
    try:
        started = datetime.fromisoformat(started_at)
        secs    = int((datetime.utcnow() - started).total_seconds())
        if secs < 0:
            secs = 0
        hours   = secs // 3600
        minutes = (secs % 3600) // 60
        secs_r  = secs % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        if minutes > 0:
            return f"{minutes}m {secs_r}s"
        return f"{secs}s"
    except Exception:
        return "—"


def _format_uptime(secs: int) -> str:
    parts = []
    if secs >= 86400:
        parts.append(f"{secs // 86400}d")
        secs %= 86400
    if secs >= 3600:
        parts.append(f"{secs // 3600}h")
        secs %= 3600
    if secs >= 60:
        parts.append(f"{secs // 60}m")
        secs %= 60
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)