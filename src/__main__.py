import asyncio
import os
import logging
from pyrogram import Client, idle, filters
from pyrogram.types import Message

from src import Config, TaskQueue, UserSettings, FFmpeg
from src.services import Worker
from src.handlers.encode import setup_encode_handlers, process_encode_command
from src.handlers.settings import setup_settings_handlers
from src.handlers.status import setup_status_handlers
from src.handlers.start import setup_start_handler
from src.handlers.help import setup_help_handlers
from src.handlers.cancel import setup_cancel_handlers, set_worker_instance, set_admin_ids

logging.basicConfig(level=logging.INFO)

sessions_dir = "./src/bin/logs/"
os.makedirs(sessions_dir, exist_ok=True)
os.makedirs("./src/bin/", exist_ok=True)
os.makedirs("./src/bin/tmp", exist_ok=True)
os.makedirs("./src/bin/thumbnails", exist_ok=True)

async def main():
    config = Config()
    
    app = Client(
        "encode_bot_session",
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=config.bot_token,
        workdir=sessions_dir,
        workers=16
    )
    
    task_queue = TaskQueue()
    ffmpeg = FFmpeg()
    user_settings_cache = {}
    
    def get_user_settings(user_id):
        if user_id not in user_settings_cache:
            user_settings_cache[user_id] = UserSettings(user_id)
        return user_settings_cache[user_id]
    
    await app.start()
    
    @app.on_message(filters.command("encode") & filters.private)
    async def encode_private(client: Client, message: Message):
        if message.from_user.id not in config.admin_ids:
            await message.reply_text("Invalid!")
            return
            
        if not message.reply_to_message:
            await message.reply_text("Please reply to a video file.")
            return
        
        await handle_encode_in_dm(client, message, task_queue, get_user_settings)
    
    setup_start_handler(app)
    setup_help_handlers(app)
    setup_cancel_handlers(app, task_queue)
    setup_status_handlers(
        app=app,
        task_queue=task_queue,
        admin_ids=config.admin_ids
    )
    setup_encode_handlers(
        app=app,
        task_queue=task_queue,
        user_settings=get_user_settings
    )
    setup_settings_handlers(
        app=app,
        user_settings=get_user_settings
    )
    
    worker = Worker(task_queue, get_user_settings, ffmpeg, app)
    set_worker_instance(worker)
    set_admin_ids(config.admin_ids)
    

    
    asyncio.create_task(worker.start())
    
    user = await app.get_me()
    name = user.username
    print(f"""
    ╔══════════════════════════════════╗
    ║   @{name} Started!               ║
    ╠══════════════════════════════════╣
    ║ Commands:                        ║
    ║ • /start - Welcome               ║
    ║ • /help - Help menu              ║
    ║ • /us - Your settings            ║
    ║ • /encode - Encode video         ║
    ║ • /status - Check queue          ║
    ║ • /cancel - Cancel task          ║
    ╚══════════════════════════════════╝
    """)
    
    await idle()
    await app.stop()

async def handle_encode_in_dm(client: Client, message: Message, task_queue, user_settings):
    await process_encode_command(client, message, task_queue, user_settings)

if __name__ == "__main__":
    asyncio.run(main())