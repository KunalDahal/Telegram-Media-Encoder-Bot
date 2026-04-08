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
from src.handlers.cancel import setup_cancel_handlers, set_worker_instance, set_admin_ids
from src.handlers.mi import setup_mediainfo_handlers
from src.handlers.rename import setup_rename_handler

logging.basicConfig(level=logging.INFO)


async def main():
    config = Config()

    config.paths.makedirs()

    app = Client(
        "encode_bot_session",
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=config.bot_token,
        workdir=config.paths.logs,
        workers=16,
    )

    task_queue = TaskQueue()
    ffmpeg = FFmpeg(
        ffmpeg_path=config.paths.ffmpeg,
        ffprobe_path=config.paths.ffprobe,
    )

    _user_settings_cache: dict[int, UserSettings] = {}

    def get_user_settings(user_id: int) -> UserSettings:
        if user_id not in _user_settings_cache:
            _user_settings_cache[user_id] = UserSettings(user_id, config.paths)
        return _user_settings_cache[user_id]

    await app.start()

    # ── Register handlers ─────────────────────────────────────────────────────
    setup_encode_handlers(app=app, task_queue=task_queue, user_settings=get_user_settings, config=config)
    setup_rename_handler(app, task_queue, get_user_settings, config)
    setup_mediainfo_handlers(app=app, config=config)
    setup_cancel_handlers(app, task_queue, config)
    setup_status_handlers(app=app, task_queue=task_queue, admin_ids=config.admin_ids, config=config)
    setup_start_handler(app, config)  
    setup_settings_handlers(app=app, user_settings=get_user_settings, config=config)

    # ── Worker ────────────────────────────────────────────────────────────────
    worker = Worker(task_queue, get_user_settings, ffmpeg, app, config)
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
    ║  /es      – Encoding settings    ║
    ║  /encode  – Single Encode        ║
    ║  /be      – Batch Encode         ║
    ║  /rename  – Rename a file        ║
    ║  /br      – Batch Rename         ║
    ║  /status  – Queue status         ║
    ║  /mi      – Media Info           ║
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