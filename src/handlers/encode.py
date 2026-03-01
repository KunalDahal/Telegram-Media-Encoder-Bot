import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.mpeg', '.mpg', '.wmv', '.flv', '.3gp'}

def setup_encode_handlers(app: Client, task_queue, user_settings):
    
    @app.on_message(filters.command("encode") & filters.private)
    async def encode_command(client: Client, message: Message):
        await process_encode_command(client, message, task_queue, user_settings)

def parse_filename_from_command(command_text):
    parts = command_text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    
    filename_part = parts[1].strip()
    
    if filename_part.startswith('"') and filename_part.endswith('"'):
        return filename_part[1:-1]
    elif filename_part.startswith("'") and filename_part.endswith("'"):
        return filename_part[1:-1]
    
    return filename_part

def validate_filename_extension(filename):
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        return False
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        return False
    return True

async def process_encode_command(client: Client, message: Message, task_queue, user_settings):
    if not message.reply_to_message:
        await message.reply_text("Reply to a video file.")
        return

    replied = message.reply_to_message
    file_id = None
    original_file_name = None
    file_size = None

    if replied.video:
        file_id = replied.video.file_id
        original_file_name = replied.video.file_name or f"video_{file_id[:8]}.mp4"
        file_size = replied.video.file_size
        
    elif replied.document:
        file_name = replied.document.file_name or ""
        file_ext = os.path.splitext(file_name)[1].lower()
        
        if file_ext in ALLOWED_VIDEO_EXTENSIONS:
            file_id = replied.document.file_id
            original_file_name = replied.document.file_name or f"video_{file_id[:8]}{file_ext}"
            file_size = replied.document.file_size
        else:
            await message.reply_text("Invalid file type. Only video files are allowed...")
            return
    else:
        await message.reply_text("Only video files are allowed...")
        return

    if len(message.command) < 2:
        output_filename = original_file_name
    else:
        output_filename = parse_filename_from_command(message.text)
        if not output_filename:
            await message.reply_text("Invalid filename format...")
            return
        
        is_valid = validate_filename_extension(output_filename)
        if not is_valid:
            await message.reply_text(
                f"Example: `/encode my_video.mp4` or `/encode \"my video with spaces.mkv\"`"
            )
            return

    settings_obj = user_settings(message.from_user.id)
    settings = settings_obj.get()
    
    created_at = datetime.utcnow().isoformat()
    
    task_data = {
        "user_id": message.from_user.id,
        "first_name":message.from_user.first_name,
        "username":message.from_user.username,
        "chat_id": message.chat.id,
        "message_id": message.id,
        "file_id": file_id,
        "original_file_name": original_file_name,
        "output_filename": output_filename,
        "created_at": created_at,
        "file_size": file_size,
        "send_type": settings["send_type"],
        "resolution": settings["resolution"],
        "crf": settings["crf"],
        "preset": settings["preset"],
        "codec": settings["codec"],
        "audio_bitrate": settings["audio_bitrate"],
        "metadata": settings["metadata"],
        "thumbnail_path": settings["thumbnail_path"]
    }
    
    task_id = task_queue.create_task(task_data)
    
    position = task_queue.get_queue_position(task_id)
    total_in_queue = len(task_queue.queue)
    is_processing = task_queue.is_processing()
    if position == 1 and not is_processing:
        status = "Processing"
    else:
        status = f"Queued"
    
    await message.reply_text(
        f"**Task Added:** `{task_id}` [`{position}/{total_in_queue}`] || `{output_filename}`\n"
    )