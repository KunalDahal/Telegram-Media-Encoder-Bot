from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
import os
from src import Config

config=Config()

def setup_settings_handlers(app: Client, user_settings):
    
    @app.on_message(filters.command("us") & filters.private)
    async def us_command(client: Client, message: Message):
        if message.from_user.id not in config.admin_ids:
            await message.reply_text("Invalid!")
            return
        user = message.from_user
        user_id = user.id
        name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = user.username or ""
        
        settings = user_settings(user_id).get()
        
        text = (
            f"**Your Encoding Settings**\n\n"
            f"**User:** {name} (@{username if username else 'N/A'})\n"
            f"**ID:** `{user_id}`\n\n"
            f"**Video:**\n"
            f"• Resolution: `{settings['resolution']}`\n"
            f"• CRF: `{settings['crf']}`\n"
            f"• Preset: `{settings['preset']}`\n"
            f"• Codec: `{settings['codec']}`\n\n"
            f"**Audio:**\n"
            f"• Bitrate: `{settings['audio_bitrate']}`\n\n"
            f"**Send Type:** `{'Media' if settings['send_type'] == 'media' else 'Document'}`\n"
            f"**Metadata:**\n"
            f"• Title: `{settings['metadata']['title'] or 'None'}`\n"
            f"• Author: `{settings['metadata']['author'] or 'None'}`\n"
            f"• Encoder: `{settings['metadata']['encoder'] or 'None'}`\n\n"
            f"**Thumbnail:** {'✅ Set' if settings['thumbnail_path'] and os.path.exists(settings['thumbnail_path']) else '❌ Not set'}"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Resolution", callback_data="set_resolution"),
             InlineKeyboardButton("CRF", callback_data="set_crf")],
            [InlineKeyboardButton("Preset", callback_data="set_preset"),
             InlineKeyboardButton("Codec", callback_data="set_codec")],
            [InlineKeyboardButton("Audio Bit Rate", callback_data="set_audio_bitrate"),
             InlineKeyboardButton("Send Type", callback_data="set_send_type")],
            [InlineKeyboardButton("Metadata", callback_data="set_metadata"),
             InlineKeyboardButton("Thumbnail", callback_data="set_thumbnail")],
            [InlineKeyboardButton("Reset All", callback_data="reset_settings"),
             InlineKeyboardButton("Close", callback_data="close_menu")]
        ])
        
        thumbnail_path = settings['thumbnail_path'] if settings['thumbnail_path'] and os.path.exists(settings['thumbnail_path']) else "./src/bin/default.jpg"
        
        if os.path.exists(thumbnail_path):
            try:
                await message.reply_photo(
                    photo=thumbnail_path,
                    caption=text,
                    reply_markup=keyboard
                )
            except Exception:
                await message.reply_text(text, reply_markup=keyboard)
        else:
            await message.reply_text(text, reply_markup=keyboard)

    @app.on_callback_query(filters.regex(r'^(set_|res_|preset_|codec_|abit_|sendtype_|meta_|reset_|back_to|close_)'))
    async def handle_settings_callbacks(client: Client, callback_query: CallbackQuery):
        user = callback_query.from_user
        user_id = user.id
        data = callback_query.data
        message = callback_query.message

        if data == "set_resolution":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("1080p", callback_data="res_1080p"),
                 InlineKeyboardButton("720p", callback_data="res_720p")],
                [InlineKeyboardButton("480p", callback_data="res_480p"),
                 InlineKeyboardButton("360p", callback_data="res_360p")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "Select resolution:",
                reply_markup=keyboard
            )

        elif data.startswith("res_"):
            resolution = data.replace("res_", "")
            user_settings(user_id).update("resolution", resolution)
            await callback_query.answer(f"Resolution set to {resolution}")
            await update_main_menu(client, message, user_id)

        elif data == "set_crf":
            sent_message = await message.edit_text(
                "Send CRF value (0-58):\nLower = better quality, higher = smaller file\n\nUse /cancel to go back."
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_crf",
                "prompt_message_id": sent_message.id
            }

        elif data == "set_preset":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("ultrafast", callback_data="preset_ultrafast"),
                 InlineKeyboardButton("superfast", callback_data="preset_superfast")],
                [InlineKeyboardButton("veryfast", callback_data="preset_veryfast"),
                 InlineKeyboardButton("faster", callback_data="preset_faster")],
                [InlineKeyboardButton("fast", callback_data="preset_fast"),
                 InlineKeyboardButton("medium", callback_data="preset_medium")],
                [InlineKeyboardButton("slow", callback_data="preset_slow"),
                 InlineKeyboardButton("slower", callback_data="preset_slower")],
                [InlineKeyboardButton("veryslow", callback_data="preset_veryslow")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "Select preset:",
                reply_markup=keyboard
            )

        elif data.startswith("preset_"):
            preset = data.replace("preset_", "")
            user_settings(user_id).update("preset", preset)
            await callback_query.answer(f"Preset set to {preset}")
            await update_main_menu(client, message, user_id)

        elif data == "set_codec":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("H.264 (libx264)", callback_data="codec_libx264"),
                 InlineKeyboardButton("H.265 (libx265)", callback_data="codec_libx265")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "Select codec:",
                reply_markup=keyboard
            )

        elif data.startswith("codec_"):
            codec = data.replace("codec_", "")
            user_settings(user_id).update("codec", codec)
            await callback_query.answer(f"Codec set to {codec}")
            await update_main_menu(client, message, user_id)

        elif data == "set_audio_bitrate":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("128k", callback_data="abit_128k"),
                 InlineKeyboardButton("192k", callback_data="abit_192k")],
                [InlineKeyboardButton("256k", callback_data="abit_256k"),
                 InlineKeyboardButton("320k", callback_data="abit_320k")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "Select audio bitrate:",
                reply_markup=keyboard
            )

        elif data.startswith("abit_"):
            bitrate = data.replace("abit_", "")
            user_settings(user_id).update("audio_bitrate", bitrate)
            await callback_query.answer(f"Audio bitrate set to {bitrate}")
            await update_main_menu(client, message, user_id)

        elif data == "set_send_type":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Media", callback_data="sendtype_media"),
                 InlineKeyboardButton("Document", callback_data="sendtype_document")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "Select how to send files:",
                reply_markup=keyboard
            )

        elif data.startswith("sendtype_"):
            send_type = data.replace("sendtype_", "")
            user_settings(user_id).update("send_type", send_type)
            await callback_query.answer(f"Send type set to {send_type.capitalize()}")
            await update_main_menu(client, message, user_id)

        elif data == "set_metadata":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Set Title", callback_data="meta_title"),
                 InlineKeyboardButton("Set Author", callback_data="meta_author")],
                [InlineKeyboardButton("Set Encoder", callback_data="meta_encoder"),
                 InlineKeyboardButton("Clear All", callback_data="meta_clear")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_to_menu")]
            ])
            await message.edit_text(
                "Metadata options:",
                reply_markup=keyboard
            )

        elif data == "meta_title":
            sent_message = await message.edit_text(
                "Send the title for your videos:\n\nUse /cancel to go back."
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_title",
                "prompt_message_id": sent_message.id
            }

        elif data == "meta_author":
            sent_message = await message.edit_text(
                "Send the author name:\n\nUse /cancel to go back."
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_author",
                "prompt_message_id": sent_message.id
            }

        elif data == "meta_encoder":
            sent_message = await message.edit_text(
                "Send the encoder name:\n\nUse /cancel to go back."
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_meta_encoder",
                "prompt_message_id": sent_message.id
            }

        elif data == "meta_clear":
            user_settings(user_id).update_metadata(title="", author="", encoder="")
            await callback_query.answer("Metadata cleared")
            await update_main_menu(client, message, user_id)

        elif data == "set_thumbnail":
            sent_message = await message.edit_text(
                "Send me an image to use as thumbnail.\nUse /cancel to go back."
            )
            user_settings(user_id).temp_state[user_id] = {
                "state": "waiting_thumbnail",
                "prompt_message_id": sent_message.id
            }

        elif data == "reset_settings":
            user_settings(user_id).reset()
            await callback_query.answer("Settings reset to defaults!")
            await update_main_menu(client, message, user_id)

        elif data == "back_to_menu":
            await update_main_menu(client, message, user_id)
            
        elif data == "close_menu":
            await message.delete()
            await callback_query.answer("Menu closed")

        await callback_query.answer()

    async def update_main_menu(client, message, user_id):
        user = await client.get_users(user_id)
        name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = user.username or ""
        
        settings = user_settings(user_id).get()
        
        text = (
            f"**Your Encoding Settings**\n\n"
            f"**User:** {name} (@{username if username else 'N/A'})\n"
            f"**ID:** `{user_id}`\n\n"
            f"**Video:**\n"
            f"• Resolution: `{settings['resolution']}`\n"
            f"• CRF: `{settings['crf']}`\n"
            f"• Preset: `{settings['preset']}`\n"
            f"• Codec: `{settings['codec']}`\n\n"
            f"**Audio:**\n"
            f"• Bitrate: `{settings['audio_bitrate']}`\n\n"
            f"**Send Type:** `{'Media' if settings['send_type'] == 'media' else 'Document'}`\n"
            f"**Metadata:**\n"
            f"• Title: `{settings['metadata']['title'] or 'None'}`\n"
            f"• Author: `{settings['metadata']['author'] or 'None'}`\n"
            f"• Encoder: `{settings['metadata']['encoder'] or 'None'}`\n\n"
            f"**Thumbnail:** {'✅ Set' if settings['thumbnail_path'] and os.path.exists(settings['thumbnail_path']) else '❌ Not set'}"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Resolution", callback_data="set_resolution"),
             InlineKeyboardButton("CRF", callback_data="set_crf")],
            [InlineKeyboardButton("Preset", callback_data="set_preset"),
             InlineKeyboardButton("Codec", callback_data="set_codec")],
            [InlineKeyboardButton("Audio Bit Rate", callback_data="set_audio_bitrate"),
             InlineKeyboardButton("Send Type", callback_data="set_send_type")],
            [InlineKeyboardButton("Metadata", callback_data="set_metadata"),
             InlineKeyboardButton("Thumbnail", callback_data="set_thumbnail")],
            [InlineKeyboardButton("Reset All", callback_data="reset_settings"),
             InlineKeyboardButton("Close", callback_data="close_menu")]
        ])
        
        thumbnail_path = settings['thumbnail_path'] if settings['thumbnail_path'] and os.path.exists(settings['thumbnail_path']) else "./src/bin/default.jpg"
        
        try:
            if message.photo:
                await message.edit_media(
                    media=InputMediaPhoto(
                        media=thumbnail_path,
                        caption=text
                    ),
                    reply_markup=keyboard
                )
            elif message.text:
                await message.delete()
                await client.send_photo(
                    chat_id=user_id,
                    photo=thumbnail_path,
                    caption=text,
                    reply_markup=keyboard
                )
            else:
                await message.edit_text(text, reply_markup=keyboard)
        except Exception:
            try:
                await message.edit_text(text, reply_markup=keyboard)
            except Exception:
                await client.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=keyboard
                )

    @app.on_message(filters.text & filters.private)
    async def handle_text_input(client: Client, message: Message):
        user_id = message.from_user.id
        
        if message.text.startswith('/'):
            return
            
        if user_id in user_settings(user_id).temp_state:
            state_data = user_settings(user_id).temp_state[user_id]
            state = state_data["state"] if isinstance(state_data, dict) else state_data
            prompt_message_id = state_data.get("prompt_message_id") if isinstance(state_data, dict) else None
            
            if state == "waiting_crf":
                try:
                    crf = int(message.text)
                    if 0 <= crf <= 58:
                        user_settings(user_id).update("crf", crf)
                        del user_settings(user_id).temp_state[user_id]
                        
                        try:
                            await client.delete_messages(
                                chat_id=user_id,
                                message_ids=[prompt_message_id, message.id]
                            )
                        except Exception:
                            pass
                            
                        await us_command(client, message)
                    else:
                        await message.reply_text("❌ CRF must be between 0 and 58")
                except ValueError:
                    await message.reply_text("❌ Please send a valid number")
                    
            elif state == "waiting_meta_title":
                user_settings(user_id).update_metadata(title=message.text)
                del user_settings(user_id).temp_state[user_id]
                
                try:
                    await client.delete_messages(
                        chat_id=user_id,
                        message_ids=[prompt_message_id, message.id]
                    )
                except Exception:
                    pass
                    
                await us_command(client, message)
                
            elif state == "waiting_meta_author":
                user_settings(user_id).update_metadata(author=message.text)
                del user_settings(user_id).temp_state[user_id]
                
                try:
                    await client.delete_messages(
                        chat_id=user_id,
                        message_ids=[prompt_message_id, message.id]
                    )
                except Exception:
                    pass
                    
                await us_command(client, message)
                
            elif state == "waiting_meta_encoder":
                user_settings(user_id).update_metadata(encoder=message.text)
                del user_settings(user_id).temp_state[user_id]
                
                try:
                    await client.delete_messages(
                        chat_id=user_id,
                        message_ids=[prompt_message_id, message.id]
                    )
                except Exception:
                    pass
                    
                await us_command(client, message)

    @app.on_message(filters.command("cancel") & filters.private)
    async def cancel_command(client: Client, message: Message):
        user_id = message.from_user.id
        
        if user_id in user_settings(user_id).temp_state:
            state_data = user_settings(user_id).temp_state[user_id]
            prompt_message_id = state_data.get("prompt_message_id") if isinstance(state_data, dict) else None
            
            del user_settings(user_id).temp_state[user_id]
            
            try:
                if prompt_message_id:
                    await client.delete_messages(
                        chat_id=user_id,
                        message_ids=[prompt_message_id, message.id]
                    )
                else:
                    await message.delete()
            except Exception:
                pass
                
            await us_command(client, message)
        else:
            await message.reply_text("Nothing to cancel.")

    @app.on_message(filters.photo & filters.private)
    async def handle_thumbnail(client: Client, message: Message):
        user_id = message.from_user.id
        
        if user_id in user_settings(user_id).temp_state:
            state_data = user_settings(user_id).temp_state[user_id]
            if isinstance(state_data, dict) and state_data.get("state") == "waiting_thumbnail":
                prompt_message_id = state_data.get("prompt_message_id")
                
                temp_thumb_dir = "./src/bin/temp_thumbs"
                os.makedirs(temp_thumb_dir, exist_ok=True)
                temp_file_path = os.path.join(temp_thumb_dir, f"{user_id}_{message.id}.jpg")
                
                await message.download(file_name=temp_file_path)
                user_settings(user_id).set_thumbnail(temp_file_path)
                
                try:
                    os.remove(temp_file_path)
                except:
                    pass
                    
                del user_settings(user_id).temp_state[user_id]
                
                try:
                    await client.delete_messages(
                        chat_id=user_id,
                        message_ids=[prompt_message_id, message.id]
                    )
                except Exception:
                    pass
                    
                await us_command(client, message)