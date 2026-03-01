from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from datetime import datetime
import psutil
import time
import humanize
from pyrogram import enums
from math import ceil

BOT_START_TIME = time.time()

def setup_status_handlers(app: Client, task_queue, admin_ids):
    
    @app.on_message(filters.command("status") & filters.private)
    async def status_command(client: Client, message: Message):
        if message.from_user.id not in admin_ids:
            await message.reply_text("❌ You are not authorized to use this command.", parse_mode=enums.ParseMode.HTML)
            return
        await show_status(client, message, task_queue, page=0)
    
    @app.on_callback_query(filters.regex(r"^status_page:(.+):(.+)$"))
    async def status_callback(client: Client, callback_query: CallbackQuery):
        if callback_query.from_user.id not in admin_ids:
            await callback_query.answer("❌ Unauthorized", show_alert=True)
            return
        
        action, page_str = callback_query.data.split(":")[1:]
        page = int(page_str)
        
        if action == "prev":
            page = max(0, page - 1)
        elif action == "next":
            page = page + 1
        elif action == "refresh":
            pass
        
        await show_status(client, callback_query.message, task_queue, page, is_callback=True)
        await callback_query.answer()

async def show_status(client: Client, message: Message, task_queue, page=0, is_callback=False):
    queued_tasks = []
    processing_task = None
    
    current_task = task_queue.get_current_task()
    if current_task and current_task["status"] in ["downloading", "encoding", "uploading"]:
        processing_task = current_task
    
    task_ids = task_queue.queue
    
    for task_id in task_ids:
        task = task_queue.get_task(task_id)
        if task:
            if processing_task and task["task_id"] == processing_task["task_id"]:
                continue
            if task["status"] in ["queued", "downloading", "encoding", "uploading"]:
                queued_tasks.append(task)
    
    all_active_tasks = []
    if processing_task:
        all_active_tasks.append(processing_task)
    all_active_tasks.extend(queued_tasks)
    
    items_per_page = 5
    total_pages = ceil(len(all_active_tasks) / items_per_page) if all_active_tasks else 1
    page = min(page, total_pages - 1)
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_page_tasks = all_active_tasks[start_idx:end_idx]
    
    status_text = ""
    
    for i, task in enumerate(current_page_tasks, start=start_idx + 1):
        user_info = f"@{task['username']}" if task.get('username') else task.get('first_name', 'Unknown')
        user_id = task['user_id']
        
        filename = task.get('output_filename') or task.get('file_name') or task.get('original_filename') or "Unknown"
        
        elapsed = ""
        if task.get('started_at'):
            started = datetime.fromisoformat(task['started_at'])
            elapsed_seconds = (datetime.utcnow() - started).seconds
            hours = elapsed_seconds // 3600
            minutes = (elapsed_seconds % 3600) // 60
            if hours > 0:
                elapsed = f"{hours}h {minutes}m"
            else:
                elapsed = f"{minutes}m"
        
        status_text += f"<b>Task {i}</b>\n"
        status_text += f"┃ File: <code>{filename}</code>\n"
        
        if task['status'] == 'encoding':
            status_text += f"┃ Encoding in progress, Using CPU for encoding.\n"
            status_text += f"┠ Status: <code>{task['status'].title()}</code>\n"
            status_text += f"┠ Elapsed: {elapsed}\n"
        else:
            progress_data = get_task_progress(task)
            
            if task['status'] == 'uploading':
                if 'encoded_file_size' in task and task['encoded_file_size']:
                    total_size = task['encoded_file_size']
                elif 'upload_progress' in task and task['upload_progress'].get('total_size'):
                    total_size = task['upload_progress']['total_size']
                else:
                    total_size = progress_data['total_size']
            else:
                total_size = progress_data['total_size']
            
            total_str = humanize.naturalsize(total_size, binary=True) if total_size else "Unknown"
            
            status_text += f"┠ Size: {total_str}\n"
            status_text += f"┠ Status: <code>{task['status'].title()}</code>\n"
            status_text += f"┠ Elapsed: {elapsed}\n"
        
        status_text += f"┠ User: {user_info} | ID: <code>{user_id}</code>\n"
        status_text += f"┖ <code>/cancel {task['task_id'][:8]}</code>\n"
        
        if i < end_idx:
            status_text += "▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁\n"
    
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    uptime_seconds = int(time.time() - BOT_START_TIME)
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    
    uptime_parts = []
    if days > 0:
        uptime_parts.append(f"{days}d")
    if hours > 0:
        uptime_parts.append(f"{hours}h")
    if minutes > 0:
        uptime_parts.append(f"{minutes}m")
    if seconds > 0 and not uptime_parts:
        uptime_parts.append(f"{seconds}s")
    uptime_str = "".join(uptime_parts) if uptime_parts else "0s"
    
    free_disk = humanize.naturalsize(disk.free, binary=True)
    disk_percent = disk.used/disk.total*100
    
    status_text += f"\n<b>⌬ Bot Stats</b>\n"
    status_text += f"┠ Tasks: {len(all_active_tasks)}\n"
    status_text += f"┠ CPU: {cpu_percent}% | F: {free_disk} [{disk_percent:.1f}%]\n"
    status_text += f"┖ RAM: {memory.percent}% | UPTIME: {uptime_str}"
    
    keyboard = []
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀", callback_data=f"status_page:prev:{page}"))
    
    nav_buttons.append(InlineKeyboardButton("🔄", callback_data=f"status_page:refresh:{page}"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("▶", callback_data=f"status_page:next:{page}"))
    
    keyboard.append(nav_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    if is_callback:
        await message.edit_text(status_text, parse_mode=enums.ParseMode.HTML, reply_markup=reply_markup)
    else:
        await message.reply_text(status_text, parse_mode=enums.ParseMode.HTML, reply_markup=reply_markup)

def get_task_progress(task):
    progress = {
        'percentage': task.get('progress', 0),
        'downloaded': task.get('downloaded_bytes', 0),
        'total_size': task.get('file_size', 0),
        'speed': task.get('speed', 0)
    }
    
    if 'progress_details' in task:
        details = task['progress_details']
        if task['status'] == 'downloading':
            progress.update({
                'percentage': details.get('percentage', progress['percentage']),
                'downloaded': details.get('downloaded', progress['downloaded']),
                'total_size': details.get('total_size', progress['total_size']),
                'speed': details.get('speed', progress['speed'])
            })
        elif task['status'] == 'uploading':
            progress.update({
                'percentage': details.get('percentage', progress['percentage']),
                'downloaded': details.get('uploaded', progress['downloaded']),
                'total_size': details.get('total_size', progress['total_size']),
                'speed': details.get('speed', progress['speed'])
            })
    if task['status'] == 'uploading' and 'upload_progress' in task:
        upload_progress = task['upload_progress']
        if upload_progress.get('total_size') and upload_progress['total_size'] > 0:
            progress['total_size'] = upload_progress['total_size']
            progress['downloaded'] = upload_progress.get('uploaded', progress['downloaded'])
            progress['percentage'] = upload_progress.get('percentage', progress['percentage'])
            progress['speed'] = upload_progress.get('speed', progress['speed'])
    
    return progress