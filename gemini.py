import io
import time
import traceback
import random
from PIL import Image
from telebot.types import Message
from md2tgmd import escape
from telebot import TeleBot
from config import conf, generation_config
from datetime import datetime, timezone, timedelta
from google import genai
from google.generativeai import types as genai_types # For Content, Part, Blob

import json
import os
import base64
import aiofiles # For async file operations
import asyncio # For Lock

user_chats = {}
USER_CHATS_FILE = "user_chats_history.json"
_save_lock = asyncio.Lock()


model_1                 =       conf["model_1"]
model_2                 =       conf["model_2"]
model_3                 =       conf["model_3"]
error_info              =       conf["error_info"]
before_generate_info    =       conf["before_generate_info"]
download_pic_notify     =       conf["download_pic_notify"]
default_system_prompt   =       conf.get("default_system_prompt", "").strip()


search_tool = {'google_search': {}}

GEMINI_API_KEYS = [
    "AIzaSyAc2PYevmpUo_3PW5PMJpu491eg9EaqWqY",
    "AIzaSyCrSk31t3oLsK4uiDcZwo20cDGkxa8IuVg",
    "AIzaSyAE6JIR_tjXSWbXRTWvd1POKIOMkTzf5O8",
    "AIzaSyCf5kmryeqRICx0zZLhU6o40O9cbQCCjfQ",
    "AIzaSyBOIXuEQl9WgW5apBINjoCtXvLm8WZ_xnA",
    "AIzaSyA6p0iVHt4M9THM08kaOfLdglV-aCMq4s4",
    "AIzaSyB9FY6yLciPeX_0YT2nnGDiofYGgogWnoU"
]

def get_random_client():
    api_key = random.choice(GEMINI_API_KEYS)
    return genai.Client(api_key=api_key)

async def save_user_chats():
    async with _save_lock:
        data_to_save = {}
        for user_id, chat_obj in user_chats.items():
            if not hasattr(chat_obj, 'history') or not hasattr(chat_obj, 'model_name'):
                print(f"Skipping user {user_id} in save_user_chats: chat object incomplete.")
                continue

            serializable_history = []
            for content_item in chat_obj.history:
                serializable_parts = []
                for part_item in content_item.parts:
                    part_dict = {}
                    if hasattr(part_item, 'text') and part_item.text is not None:
                        part_dict['text'] = part_item.text
                    elif hasattr(part_item, 'inline_data') and part_item.inline_data is not None:
                        try:
                            b64_data = base64.b64encode(part_item.inline_data.data).decode('utf-8')
                            part_dict['inline_data'] = {'mime_type': part_item.inline_data.mime_type, 'data': b64_data}
                        except Exception as e_b64:
                            print(f"Error encoding inline_data for user {user_id}: {e_b64}")
                            # Potentially skip this part or handle error appropriately
                    
                    if part_dict:
                        serializable_parts.append(part_dict)
                
                if hasattr(content_item, 'role'): # and serializable_parts: # Allow empty parts for model responses
                    serializable_history.append({'role': content_item.role, 'parts': serializable_parts})

            data_to_save[user_id] = {
                'model_name': chat_obj.model_name,
                'history': serializable_history
            }
        try:
            async with aiofiles.open(USER_CHATS_FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data_to_save, indent=2, ensure_ascii=False))
            # print(f"User chats saved to {USER_CHATS_FILE}") # For debugging
        except Exception as e:
            print(f"Error saving user chats to {USER_CHATS_FILE}: {e}")
            traceback.print_exc()

async def load_user_chats_async():
    global user_chats
    if not os.path.exists(USER_CHATS_FILE):
        print(f"{USER_CHATS_FILE} not found. Starting with empty chats.")
        user_chats = {}
        return

    try:
        async with aiofiles.open(USER_CHATS_FILE, "r", encoding="utf-8") as f:
            content = await f.read()
            loaded_data = json.loads(content)
        
        client = get_random_client()
        _loaded_chats = {} 

        for user_id, chat_data in loaded_data.items():
            rehydrated_history = []
            for content_data in chat_data.get('history', []):
                rehydrated_parts = []
                for part_data in content_data.get('parts', []):
                    if 'text' in part_data:
                        rehydrated_parts.append(genai_types.Part(text=part_data['text']))
                    elif 'inline_data' in part_data:
                        id_info = part_data['inline_data']
                        try:
                            img_data = base64.b64decode(id_info['data'])
                            blob = genai_types.Blob(mime_type=id_info['mime_type'], data=img_data)
                            rehydrated_parts.append(genai_types.Part(inline_data=blob))
                        except Exception as e_b64_dec:
                            print(f"Error decoding inline_data for user {user_id}: {e_b64_dec}")
                
                if 'role' in content_data: # Parts can be empty for some model responses
                    rehydrated_history.append(genai_types.Content(parts=rehydrated_parts, role=content_data['role']))
            
            model_name_to_load = chat_data.get('model_name')
            if model_name_to_load: 
                try:
                    chat_session = client.aio.chats.create(
                        model=model_name_to_load,
                        history=rehydrated_history if rehydrated_history else None, # Pass None if history is empty
                        config={'tools': [search_tool]} 
                    )
                    _loaded_chats[user_id] = chat_session
                except Exception as e_create_chat:
                    print(f"Error re-creating chat for user {user_id} with model {model_name_to_load}: {e_create_chat}")
            else:
                 print(f"Skipping chat for user {user_id} due to missing model_name.")

        user_chats = _loaded_chats
        print(f"Successfully loaded {len(user_chats)} user chats from {USER_CHATS_FILE}.")

    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Could not load user chats from {USER_CHATS_FILE}: {e}. Starting with empty chats.")
        user_chats = {}
    except Exception as e_outer:
        print(f"An unexpected error occurred during loading user chats: {e_outer}. Starting with empty chats.")
        traceback.print_exc()
        user_chats = {}


async def gemini_stream(bot:TeleBot, message:Message, m:str, model_type:str):
    client = get_random_client()
    sent_message = None
    user_id_str = str(message.from_user.id)
    try:
        sent_message = await bot.reply_to(message, before_generate_info) 

        chat = user_chats.get(user_id_str)
        new_chat_created = False

        if not chat or chat.model_name != model_type: # Also re-create if model type preference changed
            if chat and chat.model_name != model_type:
                print(f"Model type changed for user {user_id_str}. Creating new chat session.")
            
            chat = client.aio.chats.create(model=model_type, config={'tools': [search_tool]})
            new_chat_created = True
            
            if default_system_prompt:
                try:
                    time_zone = timezone(timedelta(hours=3, minutes=30))
                    date = datetime.now(time_zone).strftime("%d/%m/%Y")
                    timenow = datetime.now(time_zone).strftime("%H:%M:%S")
                    time_prompt = f"""
                    **اطلاعات مربوط به تاریخ و زمان:**
                    تاریخ به میلادی: {date}  /// زمان: {timenow}
                    این اطلاعات رو داشته باش تا درصورتی که کاربر ازت پرسیدشون جواب بدی."""
                    full_prompt = default_system_prompt + "\n\n" + time_prompt
                    await chat.send_message(full_prompt)
                except Exception as e_default_prompt:
                    print(f"Warning: Could not send default system prompt for user {user_id_str}: {e_default_prompt}")
            
            user_chats[user_id_str] = chat
            if new_chat_created: # Save immediately after new chat creation with system prompt
                await save_user_chats()


        response = await chat.send_message_stream(m)

        full_response = ""
        last_update = time.time()
        update_interval = conf["streaming_update_interval"]

        async for chunk in response:
            if hasattr(chunk, 'text') and chunk.text:
                full_response += chunk.text
                current_time = time.time()
                if current_time - last_update >= update_interval:
                    try:
                        await bot.edit_message_text(
                            escape(full_response + "|"),
                            chat_id=sent_message.chat.id,
                            message_id=sent_message.message_id,
                            parse_mode="MarkdownV2"
                            )
                    except Exception as e:
                        if "parse markdown" in str(e).lower():
                            try:
                                await bot.edit_message_text(
                                    full_response + "|",
                                    chat_id=sent_message.chat.id,
                                    message_id=sent_message.message_id
                                    )
                            except Exception as e2:
                                if "message is not modified" not in str(e2).lower():
                                     print(f"Error updating message (non-Markdown fallback): {e2}")
                        elif "message is not modified" not in str(e).lower():
                            print(f"Error updating message: {e}")
                    last_update = current_time
        try:
            await bot.edit_message_text(
                escape(full_response),
                chat_id=sent_message.chat.id,
                message_id=sent_message.message_id,
                parse_mode="MarkdownV2"
            )
        except Exception as e:
            try:
                if "parse markdown" in str(e).lower() or "message is not modified" in str(e).lower() : 
                    await bot.edit_message_text(
                        full_response,
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id
                    )
                else:
                    raise 
            except Exception as final_e: 
                print(f"Error in final message edit (non-Markdown): {final_e}")
                if not full_response.strip():
                     await bot.edit_message_text(
                        "پاسخ خالی دریافت شد.", 
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id
                    )
        
        # Save history after successful interaction
        await save_user_chats()

    except Exception as e:
        traceback.print_exc()
        error_message_detail = f"{error_info}\nجزئیات خطا: {str(e)}"
        if sent_message:
            try:
                await bot.edit_message_text(
                    error_message_detail,
                    chat_id=sent_message.chat.id,
                    message_id=sent_message.message_id
                )
            except Exception as edit_err:
                print(f"Could not edit message to show error: {edit_err}")
                await bot.reply_to(message, error_message_detail) 
        else:
            await bot.reply_to(message, error_message_detail)

async def gemini_edit(bot: TeleBot, message: Message, m: str, photo_file: bytes):
    image = Image.open(io.BytesIO(photo_file))
    client = get_random_client()
    sent_progress_message = None
    try:
        sent_progress_message = await bot.reply_to(message, "در حال پردازش تصویر با دستور شما... 🖼️")
        response = await client.aio.models.generate_content(
            model=model_3, 
            contents=[m, image],
            config=generation_config
        )
        if sent_progress_message:
            await bot.delete_message(sent_progress_message.chat.id, sent_progress_message.message_id)

        if not (response and hasattr(response, 'candidates') and response.candidates and \
           hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts')):
            await bot.send_message(message.chat.id, f"{error_info}\nپاسخ معتبری از سرویس دریافت نشد.")
            return

        processed_parts = False
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text is not None:
                text_response = part.text
                while len(text_response) > 4000:
                    await bot.send_message(message.chat.id, escape(text_response[:4000]), parse_mode="MarkdownV2")
                    text_response = text_response[4000:]
                if text_response:
                    await bot.send_message(message.chat.id, escape(text_response), parse_mode="MarkdownV2")
                processed_parts = True
            elif hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
                photo = part.inline_data.data
                await bot.send_photo(message.chat.id, photo, caption=escape("نتیجه ویرایش تصویر:") if not m.startswith("تصویر را توصیف کن") else escape(m))
                processed_parts = True
        if not processed_parts:
            await bot.send_message(message.chat.id, "پاسخی از مدل دریافت نشد یا محتوای قابل نمایشی وجود نداشت.")
    except Exception as e:
        traceback.print_exc()
        error_message_detail = f"{error_info}\nجزئیات خطا: {str(e)}"
        if sent_progress_message:
            try:
                await bot.edit_message_text(error_message_detail, chat_id=sent_progress_message.chat.id, message_id=sent_progress_message.message_id)
            except: 
                await bot.send_message(message.chat.id, error_message_detail)
        else:
            await bot.send_message(message.chat.id, error_message_detail)


async def gemini_draw(bot:TeleBot, message:Message, m:str):
    client = get_random_client()
    try:
        response = await client.aio.models.generate_content(
            model=model_3, 
            contents=[m],  
            config=generation_config 
        )
    except Exception as e:
        traceback.print_exc()
        await bot.send_message(message.chat.id, f"{error_info}\nخطا در هنگام فراخوانی سرویس تولید تصویر: {str(e)}")
        return

    if not (response and hasattr(response, 'candidates') and response.candidates and \
       hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts')):
        await bot.send_message(message.chat.id, f"{error_info}\nپاسخ معتبری هنگام ترسیم تصویر دریافت نشد.")
        return

    image_generated = False
    for part in response.candidates[0].content.parts:
        if hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
            photo_data = part.inline_data.data
            try:
                await bot.send_photo(message.chat.id, photo_data, caption=escape(f"تصویر تولید شده برای: {m[:100]}"))
                image_generated = True
                break 
            except Exception as send_photo_e:
                traceback.print_exc()
                await bot.send_message(message.chat.id, f"{error_info}\nخطا در هنگام ارسال تصویر: {str(send_photo_e)}")
                image_generated = False 
                break 
    if not image_generated:
        text_response_parts = []
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text is not None:
                text_response_parts.append(part.text)
        if text_response_parts:
            full_text_response = "\n".join(text_response_parts).strip()
            if full_text_response: 
                response_message = f"مدل تصویری تولید نکرد، اما این پیام را ارسال کرد:\n{escape(full_text_response)}"
                max_len = 4096 
                if len(response_message) > max_len:
                    response_message = response_message[:max_len - 100] + "...\n(پیام کوتاه شد)"
                try:
                    await bot.send_message(message.chat.id, response_message, parse_mode="MarkdownV2")
                except Exception as send_text_e:
                    print(f"Error sending MarkdownV2 text in gemini_draw, falling back: {send_text_e}")
                    await bot.send_message(message.chat.id, f"مدل تصویری تولید نکرد، اما این پیام را ارسال کرد:\n{full_text_response}")
            else: 
                 await bot.send_message(message.chat.id, "تصویری تولید نشد و پاسخی از مدل دریافت نگردید.")
        else: 
            await bot.send_message(message.chat.id, "تصویری تولید نشد و پاسخی از مدل دریافت نگردید.")
