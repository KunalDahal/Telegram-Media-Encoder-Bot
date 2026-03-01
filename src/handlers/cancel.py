from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram import enums
from src.utils.config import Config

config=Config()

worker_instance = None
admin_ids = []

def set_worker_instance(worker):
    global worker_instance
    worker_instance = worker

def set_admin_ids(ids):
    global admin_ids
    admin_ids = ids

def get_worker_instance():
    return worker_instance

def get_admin_ids():
    return admin_ids

def setup_cancel_handlers(app: Client, task_queue):
    
    @app.on_message(filters.command("cancel") & filters.private)
    async def cancel_command(client: Client, message: Message):
        if message.from_user.id not in config.admin_ids:
            await message.reply_text("Invalid!")
            return
            
        if not message.reply_to_message:
            await message.reply_text("Please reply to a video file.")
            return
        try:
            task_id_part = None
            
            if len(message.command) >= 2:
                task_id_part = message.command[1]
            elif message.text and "_" in message.text:
                parts = message.text.split("_")
                if len(parts) >= 2:
                    task_id_part = parts[1]
            else:
                await message.reply_text(
                    "Usage: `/cancel task_id` or `/cancel_taskid`\n"
                    "You can get task ID from /status command",
                    parse_mode=enums.ParseMode.HTML
                )
                return
            
            task_id_part = task_id_part.strip()
            
            matching_task = None
            for tid in list(task_queue.tasks.keys()):
                if tid.startswith(task_id_part):
                    matching_task = tid
                    break
            
            if not matching_task:
                await message.reply_text(f"❌ Task with ID <code>{task_id_part}</code> not found.", parse_mode=enums.ParseMode.HTML)
                return
            
            task = task_queue.get_task(matching_task)
            
            if message.from_user.id not in admin_ids and task.get("user_id") != message.from_user.id:
                await message.reply_text("❌ You can only cancel your own tasks.", parse_mode=enums.ParseMode.HTML)
                return
            
            worker_instance = get_worker_instance()
            
            if worker_instance:
                await worker_instance.cancel_task(matching_task)
                await message.reply_text(f"✅ Task <code>{matching_task[:8]}</code> has been cancelled.", parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text("❌ Worker not available.", parse_mode=enums.ParseMode.HTML)
                
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}", parse_mode=enums.ParseMode.HTML)