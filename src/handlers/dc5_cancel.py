"""
dc5_cancel.py
─────────────
Cancel handler registered on the DC5 (secondary) bot.

Rules:
  • Any user can cancel THEIR OWN task.
  • Admins can cancel anyone's task.
  • The worker instance is shared from the main bot — tasks are in the
    shared task_queue, and the shared worker executes them.
"""

from pyrogram import Client, filters, enums
from pyrogram.types import Message

# These are set once from __main__.py after the worker is created
_worker_instance = None
_admin_ids: list[int] = []


def set_dc5_worker_instance(worker):
    global _worker_instance
    _worker_instance = worker


def set_dc5_admin_ids(ids):
    global _admin_ids
    _admin_ids = list(ids)


async def _check_access(client: Client, message: Message) -> bool:
    """Make sure the user has started the bot in DM (basic reachability check)."""
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


def setup_dc5_cancel_handlers(app: Client, task_queue, config):
    """Register /cancel and /c on the DC5 bot."""

    allowed_filter = filters.chat(config.allowed_group_ids)

    @app.on_message(filters.command(["cancel", "c"]) & allowed_filter)
    async def cancel_command(client: Client, message: Message):
        if not await _check_access(client, message):
            return

        if len(message.command) < 2:
            await message.reply_text(
                "Usage: <code>/cancel &lt;task_id&gt;</code>\n"
                "Get the task ID from /status on the main bot.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        task_id_part = message.command[1].strip()
        user_id      = message.from_user.id
        is_admin     = user_id in _admin_ids

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

        # ── Bot ownership: DC5 bot only handles tasks it queued ───────────────
        if task.get("queued_by_bot_dc") != 5:
            # This task belongs to the main bot — let main bot handle the cancel
            return

        # ── Ownership check ───────────────────────────────────────────────────
        if not is_admin and task.get("user_id") != user_id:
            await message.reply_text(
                "❌ You can only cancel your own tasks.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        worker = _worker_instance
        if not worker:
            await message.reply_text(
                "Worker is not available.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # ── If still queued, remove directly ─────────────────────────────────
        if task.get("status") == "queued":
            task_queue.remove_task(matching_task_id)
            await message.reply_text(
                f"✅ Task <code>{task_id_part}</code> cancelled (was queued, not yet started).",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # ── Active task — delegate to shared worker ───────────────────────────
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