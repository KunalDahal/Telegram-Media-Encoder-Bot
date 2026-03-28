from pyrogram import Client, filters, enums
from pyrogram.types import Message
from src.utils.config import Config

config = Config()

_worker_instance = None
_admin_ids = []


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


def setup_cancel_handlers(app: Client, task_queue):

    @app.on_message(filters.command("cancel") & filters.private)
    async def cancel_command(client: Client, message: Message):
        user_id = message.from_user.id

        if user_id not in _admin_ids:
            await message.reply_text("Invalid!")
            return

        # ── Parse task ID from command argument ───────────────────────────────
        # Usage: /cancel <task_id>   (first 8 chars of the UUID are enough)
        if len(message.command) < 2:
            await message.reply_text(
                "Usage: <code>/cancel &lt;task_id&gt;</code>\n"
                "Get the task ID from /status.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        task_id_part = message.command[1].strip()

        # ── Find matching task ────────────────────────────────────────────────
        matching_task_id = None
        for tid in list(task_queue.tasks.keys()):
            if tid.startswith(task_id_part):
                matching_task_id = tid
                break

        if not matching_task_id:
            await message.reply_text(
                f"❌ No task found matching <code>{task_id_part}</code>.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        task = task_queue.get_task(matching_task_id)
        if not task:
            await message.reply_text(
                f"❌ Task <code>{task_id_part}</code> no longer exists.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # Non-admins can only cancel their own tasks
        if user_id not in _admin_ids and task.get("user_id") != user_id:
            await message.reply_text(
                "❌ You can only cancel your own tasks.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # ── Delegate to worker ────────────────────────────────────────────────
        worker = get_worker_instance()
        if not worker:
            await message.reply_text(
                "❌ Worker is not available.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        try:
            await worker.cancel_task(matching_task_id)
        except Exception as e:
            await message.reply_text(
                f"❌ Failed to cancel task: <code>{e}</code>",
                parse_mode=enums.ParseMode.HTML,
            )