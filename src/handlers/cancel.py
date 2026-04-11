"""
cancel.py
─────────
Unified /cancel handler for both the main bot (DC4) and the DC5 bot.

Each bot is registered with its own `bot_dc` value so it only acts on
tasks it owns — but every bot replies with its own message, preventing
double-replies.

Usage in __main__.py
────────────────────
    from src.handlers.cancel import setup_cancel_handlers, set_worker_instance, set_admin_ids

    # Main bot (DC4)
    setup_cancel_handlers(main_app, task_queue, config, bot_dc=4)

    # DC5 bot
    setup_cancel_handlers(dc5_app, task_queue, config, bot_dc=5)

    set_worker_instance(worker)
    set_admin_ids(config.admin_ids)
"""

from pyrogram import Client, filters, enums
from pyrogram.types import Message

_worker_instance = None
_admin_ids: list[int] = []


# ── Shared state setters (called once from __main__.py) ───────────────────────

def set_worker_instance(worker):
    global _worker_instance
    _worker_instance = worker


def set_admin_ids(ids):
    global _admin_ids
    _admin_ids = list(ids)


def get_worker_instance():
    return _worker_instance


def get_admin_ids():
    return _admin_ids


# ── DM reachability check ─────────────────────────────────────────────────────

async def _check_access(client: Client, message: Message) -> bool:
    """Ensure the user has started this bot in DM so we can reply there."""
    try:
        await client.get_chat(message.from_user.id)
    except Exception:
        bot_username = (await client.get_me()).username
        await message.reply_text(
            f"⚠️ Please start the bot in DM first.\n"
            f"👉 @{bot_username} — press <b>Start</b>, then try again.",
            parse_mode=enums.ParseMode.HTML,
        )
        return False
    return True


# ── Handler registration ──────────────────────────────────────────────────────

def setup_cancel_handlers(app: Client, task_queue, config, bot_dc: int = 4):
    """
    Register /cancel and /c on `app`.

    `bot_dc` — the DC this bot instance owns (4 = main, 5 = secondary).
    Each bot silently ignores tasks that belong to the other bot.
    """

    allowed_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["cancel", "c"]) & allowed_filter)
    async def cancel_command(client: Client, message: Message):
        if not await _check_access(client, message):
            return

        # ── Argument check ────────────────────────────────────────────────────
        if len(message.command) < 2:
            await message.reply_text(
                "Usage: <code>/cancel &lt;task_id&gt;</code>\n"
                "Get the task ID from /status.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        task_id_part = message.command[1].strip()

        # ── Find task by prefix ───────────────────────────────────────────────
        matching_task_id = None
        for tid in list(task_queue.tasks.keys()):
            if tid.startswith(task_id_part):
                matching_task_id = tid
                break

        if not matching_task_id:
            await message.reply_text(
                f"No task found matching <code>{task_id_part}</code>.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        task = task_queue.get_task(matching_task_id)
        if not task:
            await message.reply_text(
                f"Task <code>{task_id_part}</code> no longer exists.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # ── DC ownership: each bot only handles its own tasks ─────────────────
        task_dc = task.get("queued_by_bot_dc", 4)   # default 4 for legacy tasks
        if task_dc != bot_dc:
            # Silently ignore — the correct bot will handle it
            return

        # ── Permission check ──────────────────────────────────────────────────
        user_id  = message.from_user.id
        is_admin = user_id in _admin_ids
        if not is_admin and task.get("user_id") != user_id:
            await message.reply_text(
                "❌ You can only cancel your own tasks.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # ── Queued (not yet running) — remove directly ────────────────────────
        if task.get("status") == "queued":
            task_queue.remove_task(matching_task_id)
            await message.reply_text(
                f"✅ Task <code>{task_id_part}</code> cancelled (was queued, not yet started).",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # ── Active task — delegate to shared worker ───────────────────────────
        worker = _worker_instance
        if not worker:
            await message.reply_text(
                "Worker is not available.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        try:
            await worker.cancel_task(matching_task_id)
            await message.reply_text(
                f"✅ Task <code>{task_id_part}</code> cancelled.",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            await message.reply_text(
                f"Failed to cancel task: <code>{e}</code>",
                parse_mode=enums.ParseMode.HTML,
            )