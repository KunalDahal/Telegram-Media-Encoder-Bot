import asyncio
import sys
import os
import logging

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

_original_get_event_loop = asyncio.get_event_loop

def _patched_get_event_loop():
    try:
        return _original_get_event_loop()
    except RuntimeError:
        return _loop

asyncio.get_event_loop = _patched_get_event_loop

from pyrogram import Client, idle, filters
from pyrogram.types import Message

from src import Config, TaskQueue, UserSettings, FFmpeg
from src.services import Worker
from src.handlers.encode import setup_encode_handlers
from src.handlers.settings import setup_settings_handlers
from src.handlers.status import setup_status_handlers
from src.handlers.start import setup_start_handler
from src.handlers.help import setup_help_handlers
from src.handlers.cancel import setup_cancel_handlers, set_worker_instance, set_admin_ids

logging.basicConfig(level=logging.INFO)

os.makedirs("./src/bin/logs", exist_ok=True)
os.makedirs("./src/bin/tmp", exist_ok=True)
os.makedirs("./src/bin/thumbnails", exist_ok=True)
os.makedirs("./src/bin/users", exist_ok=True)


async def main():
    config = Config()

    app = Client(
        "encode_bot_session",
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=config.bot_token,
        workdir="./src/bin/logs/",
        workers=16,
    )

    task_queue = TaskQueue()
    ffmpeg = FFmpeg()

    _user_settings_cache: dict[int, UserSettings] = {}

    def get_user_settings(user_id: int) -> UserSettings:
        if user_id not in _user_settings_cache:
            _user_settings_cache[user_id] = UserSettings(user_id)
        return _user_settings_cache[user_id]

    await app.start()

    # ── Register handlers (order matters for Pyrogram) ────────────────────────

    setup_start_handler(app)
    setup_help_handlers(app)
    setup_cancel_handlers(app, task_queue)
    setup_status_handlers(app=app, task_queue=task_queue, admin_ids=config.admin_ids)
    setup_encode_handlers(app=app, task_queue=task_queue, user_settings=get_user_settings)
    setup_settings_handlers(app=app, user_settings=get_user_settings)

    # ── Worker ────────────────────────────────────────────────────────────────
    worker = Worker(task_queue, get_user_settings, ffmpeg, app)
    set_worker_instance(worker)
    set_admin_ids(config.admin_ids)

    asyncio.create_task(worker.start())

    # ── Ready ─────────────────────────────────────────────────────────────────
    me = await app.get_me()
    print(f"""
    ╔══════════════════════════════════╗
    ║  @{me.username:<31}║
    ╠══════════════════════════════════╣
    ║  /start   – Welcome              ║
    ║  /help    – Help menu            ║
    ║  /es      – Encoding settings    ║
    ║  /encode  – Queue a file         ║
    ║  /status  – Queue status         ║
    ║  /cancel  – Cancel a task        ║
    ╚══════════════════════════════════╝
    """)

    await idle()
    await app.stop()


if __name__ == "__main__":
    try:
        _loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        _loop.close()