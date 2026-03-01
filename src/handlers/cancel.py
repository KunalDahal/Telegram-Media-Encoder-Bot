# handlers/cancel.py
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram import enums
import re
import os
import shutil

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
        if len(message.command) < 2:
            await message.reply_text(
                "Usage: `/cancel task_id` or reply to a task message with `/cancel`\n"
                "You can get task ID from /status command",
                parse_mode=enums.ParseMode.HTML
            )
            return
        
        task_id_part = message.command[1]
        
        matching_task = None
        for tid in task_queue.tasks.keys():
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
    
    @app.on_message(filters.regex(r"^/cancel_([a-f0-9]{8})$") & filters.private)
    async def cancel_with_underscore(client: Client, message: Message):
        match = re.match(r"^/cancel_([a-f0-9]{8})$", message.text)
        if match:
            task_id_part = match.group(1)
            
            matching_task = None
            for tid in task_queue.tasks.keys():
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