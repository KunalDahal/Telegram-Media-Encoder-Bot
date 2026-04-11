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

from pyrogram import Client, idle

from src import Config, TaskQueue, UserSettings, FFmpeg
from src.services import Worker
from src.handlers.encode  import setup_encode_handlers
from src.handlers.settings import setup_settings_handlers
from src.handlers.status  import setup_status_handlers
from src.handlers.start   import setup_start_handler
from src.handlers.cancel  import setup_cancel_handlers, set_worker_instance, set_admin_ids
from src.handlers.mi      import setup_mediainfo_handlers
from src.handlers.set     import setup_set_handlers
from src.handlers.rename  import setup_rename_handler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_client(name: str, token: str, config: Config) -> Client:
    """Create a Pyrogram bot client with shared API credentials."""
    return Client(
        name,
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=token,
        workdir=config.paths.logs,
        workers=32,
        max_concurrent_transmissions=10,
        sleep_threshold=60,        # wait up to 60 s on flood instead of raising
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    config = Config()
    config.paths.makedirs()

    # ── Shared infrastructure ─────────────────────────────────────────────────
    task_queue = TaskQueue()
    ffmpeg     = FFmpeg(
        ffmpeg_path=config.paths.ffmpeg,
        ffprobe_path=config.paths.ffprobe,
    )

    # ── Shared user-settings cache (both bots use the same files on disk) ─────
    _user_settings_cache: dict[int, UserSettings] = {}

    def get_user_settings(user_id: int) -> UserSettings:
        if user_id not in _user_settings_cache:
            _user_settings_cache[user_id] = UserSettings(user_id, config.paths)
        return _user_settings_cache[user_id]

    # ── Main bot (DC4) ────────────────────────────────────────────────────────
    main_app = _make_client("encode_bot_session", config.bot_token, config)
    await main_app.start()

    # ── Secondary bot (DC5) — optional ───────────────────────────────────────
    dc5_app: Client | None = None
    if config.has_dc5_bot:
        dc5_app = _make_client("dc5_bot_session", config.dc5_bot_token, config)
        await dc5_app.start()
        logger.info("[Main] DC5 secondary bot started.")
    else:
        logger.info("[Main] DC5_BOT_TOKEN not set — secondary bot disabled.")

    # ── Worker (shared, encode+upload always via main_app) ────────────────────
    worker = Worker(
        task_queue,
        get_user_settings,
        ffmpeg,
        main_app,          # encode + upload client
        config,
        dc5_client=dc5_app,   # download-only client for DC5 files (may be None)
    )

    # ── Main bot: register ALL handlers ──────────────────────────────────────
    setup_set_handlers(app=main_app, user_settings=get_user_settings, config=config)
    setup_encode_handlers(app=main_app, task_queue=task_queue, user_settings=get_user_settings, config=config, bot_dc=4)
    setup_rename_handler(main_app, task_queue, get_user_settings, config, bot_dc=4)
    setup_cancel_handlers(main_app, task_queue, config)
    setup_status_handlers(app=main_app, task_queue=task_queue, admin_ids=config.admin_ids, config=config)
    setup_start_handler(main_app, config)
    setup_mediainfo_handlers(app=main_app, config=config)
    setup_settings_handlers(app=main_app, user_settings=get_user_settings, config=config)

    set_worker_instance(worker)
    set_admin_ids(config.admin_ids)

    # ── DC5 bot: register ONLY encode + rename + cancel handlers ─────────────
    if dc5_app is not None:
        setup_encode_handlers(app=dc5_app, task_queue=task_queue, user_settings=get_user_settings, config=config, bot_dc=5)
        setup_rename_handler(dc5_app, task_queue, get_user_settings, config, bot_dc=5)
        setup_cancel_handlers(dc5_app, task_queue, config, bot_dc=5)   # unified handler, DC5 instance

    # ── Start the worker loop ─────────────────────────────────────────────────
    asyncio.create_task(worker.start())

    # ── Print status banners ──────────────────────────────────────────────────
    me_main = await main_app.get_me()
    print(f"""
    ╔══════════════════════════════════╗
    ║  MAIN BOT  @{me_main.username:<21}║
    ╠══════════════════════════════════╣
    ║  /start   – Welcome              ║
    ║  /es      – Encoding settings    ║
    ║  /encode  – Single Encode        ║
    ║  /rename  – Rename a file        ║
    ║  /status  – Queue status         ║
    ║  /mi      – Media Info           ║
    ║  /cancel  – Cancel a task        ║
    ╚══════════════════════════════════╝
    """)

    if dc5_app is not None:
        me_dc5 = await dc5_app.get_me()
        print(f"""
    ╔══════════════════════════════════╗
    ║  DC5 BOT   @{me_dc5.username:<21}║
    ╠══════════════════════════════════╣
    ║  /encode  – Queue encode task    ║
    ║  /rename  – Queue rename task    ║
    ║  /cancel  – Cancel own task      ║
    ║  (DC5 files downloaded here)     ║
    ╚══════════════════════════════════╝
        """)

    await idle()

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    await main_app.stop()
    if dc5_app is not None:
        await dc5_app.stop()


if __name__ == "__main__":
    try:
        _loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        _loop.close()