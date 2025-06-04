import io
import time
import traceback
import random
from PIL import Image
from telebot.types import Message
from md2tgmd import escape
from telebot import TeleBot
# Import safety_settings directly from config to be used in start_chat
from config import conf, generation_config, safety_settings as global_safety_settings_list
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from google import genai as gen # Ensure genai is imported
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
    # Assuming genai.configure() is not needed here if Client takes api_key directly
    # or that it's configured globally elsewhere.
    # If not, you might need genai.configure(api_key=api_key) before returning client
    return gen.Client(api_key=api_key)

# Helper to ensure model name has 'models/' prefix
def ensure_model_prefix(model_name):
    if model_name and not model_name.startswith('models/'):
        return f'models/{model_name}'
    return model_name


async def save_user_chats():
    async with _save_lock:
        data_to_save = {}
        for user_id, chat_obj in user_chats.items():
            # Ensure chat_obj and its model attribute are valid
            if not hasattr(chat_obj, 'model') or not hasattr(chat_obj.model, 'model_name') or not hasattr(chat_obj, 'history'):
                print(f"Skipping user {user_id} in save_user_chats: chat object incomplete (missing model.model_name or history).")
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
                    
                    if part_dict:
                        serializable_parts.append(part_dict)
                
                if hasattr(content_item, 'role'):
                    serializable_history.append({'role': content_item.role, 'parts': serializable_parts})

            data_to_save[user_id] = {
                'model_name': chat_obj.model.model_name, # Use model_name
                'history': serializable_history
            }
        try:
            async with aiofiles.open(USER_CHATS_FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data_to_save, indent=2, ensure_ascii=False))
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
                
                if 'role' in content_data:
                    rehydrated_history.append(genai_types.Content(parts=rehydrated_parts, role=content_data['role']))
            
            model_name_to_load = chat_data.get('model_name')
            if model_name_to_load: 
                try:
                    full_model_name = ensure_model_prefix(model_name_to_load)
                    # Create GenerativeModel instance instead of client.aio.models.get()
                    model_instance = genai.GenerativeModel(
                        model_name=full_model_name,
                        safety_settings=global_safety_settings_list, # Pass safety settings here
                        tools=[search_tool],                         # Pass tools here
                        client=client                                # Pass the client instance
                    )
                    
                    chat_session = model_instance.start_chat(
                        history=rehydrated_history if rehydrated_history else None
                        # safety_settings and tools are now part of model_instance
                    )
                    _loaded_chats[user_id] = chat_session
                except Exception as e_create_chat:
                    print(f"Error re-creating chat for user {user_id} with model {model_name_to_load}: {e_create_chat}")
                    traceback.print_exc()
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
        new_chat_created_or_model_switched = False

        full_model_type = ensure_model_prefix(model_type)
        # Check against model.model_name
        if not chat or not hasattr(chat, 'model') or chat.model.model_name != full_model_type:
            if chat and hasattr(chat, 'model') and chat.model.model_name != full_model_type:
                print(f"Model type changed for user {user_id_str} from {chat.model.model_name} to {full_model_type}. Creating new chat session.")
            elif not chat:
                print(f"No existing chat session for user {user_id_str}. Creating new one for model {full_model_type}.")
            else: 
                print(f"Existing chat for user {user_id_str} is malformed. Recreating for model {full_model_type}.")

            # Create GenerativeModel instance
            model_instance = genai.GenerativeModel(
                model_name=full_model_type,
                safety_settings=global_safety_settings_list,
                tools=[search_tool],
                client=client # Pass the client instance
            )
            # Start chat
            chat = model_instance.start_chat(
                history=[], # For a new chat
            )
            new_chat_created_or_model_switched = True
            
            if default_system_prompt:
                try:
                    # System prompt (instruction) should ideally be part of GenerativeModel
                    # or sent as the first message. Sending as a message here is fine.
                    time_zone = timezone(timedelta(hours=3, minutes=30))
                    date = datetime.now(time_zone).strftime("%d/%m/%Y")
                    timenow = datetime.now(time_zone).strftime("%H:%M:%S")
                    time_prompt = f"""
                    **اطلاعات مربوط به تاریخ و زمان:**
                    تاریخ به میلادی: {date}  /// زمان: {timenow}
                    این اطلاعات رو داشته باش تا درصورتی که کاربر ازت پرسیدشون جواب بدی."""
                    full_prompt_with_time = default_system_prompt + "\n\n" + time_prompt
                    # Sending system prompt. Note: this will be part of chat history.
                    # For true system instructions, use system_instruction in GenerativeModel
                    await chat.send_message_async(full_prompt_with_time) # Use send_message_async
                except Exception as e_default_prompt:
                    print(f"Warning: Could not send default system prompt for user {user_id_str}: {e_default_prompt}")
                    traceback.print_exc()
            
            user_chats[user_id_str] = chat
            if new_chat_created_or_model_switched: 
                await save_user_chats()

        # Assuming chat.send_message_stream is a custom or older method.
        # Standard way is chat.send_message_async(m, stream=True)
        # For this fix, we'll keep it if it works for user, but it's non-standard.
        response_stream = await chat.send_message_async(m, stream=True) # Corrected to standard API

        full_response = ""
        last_update = time.time()
        update_interval = conf["streaming_update_interval"]

        async for chunk in response_stream: # Iterate over the standard stream
            if hasattr(chunk, 'text') and chunk.text:
                full_response += chunk.text
                current_time = time.time()
                if current_time - last_update >= update_interval and full_response.strip(): 
                    try:
                        await bot.edit_message_text(
                            escape(full_response + "...") if len(full_response) < 4000 else escape(full_response[:4000] + "..."), 
                            chat_id=sent_message.chat.id,
                            message_id=sent_message.message_id,
                            parse_mode="MarkdownV2"
                            )
                    except Exception as e:
                        if "parse markdown" in str(e).lower():
                            try:
                                await bot.edit_message_text(
                                    (full_response + "...") if len(full_response) < 4090 else (full_response[:4090] + "..."),
                                    chat_id=sent_message.chat.id,
                                    message_id=sent_message.message_id
                                    )
                            except Exception as e2:
                                if "message is not modified" not in str(e2).lower():
                                     print(f"Error updating message (non-Markdown fallback): {e2}")
                        elif "message is not modified" not in str(e).lower():
                            print(f"Error updating message: {e}")
                    last_update = current_time
        
        if not full_response.strip() and sent_message: 
             print(f"Empty response from model for user {user_id_str}, prompt: {m[:50]}")
             try:
                await bot.edit_message_text(
                    "متاسفانه پاسخی از مدل دریافت نشد. لطفا دوباره تلاش کنید.",
                    chat_id=sent_message.chat.id,
                    message_id=sent_message.message_id
                )
             except Exception as e_empty_edit:
                print(f"Error editing message for empty model response: {e_empty_edit}")
             return 

        try:
            if sent_message and full_response.strip():
                await bot.edit_message_text(
                    escape(full_response),
                    chat_id=sent_message.chat.id,
                    message_id=sent_message.message_id,
                    parse_mode="MarkdownV2"
                )
        except Exception as e:
            try:
                if sent_message and full_response.strip() and ("parse markdown" in str(e).lower() or "message is not modified" in str(e).lower()) : 
                    await bot.edit_message_text(
                        full_response,
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id
                    )
                elif sent_message and full_response.strip(): 
                    print(f"Error in final message edit (Markdown): {e}, falling back to plain text for non-empty response.")
                    await bot.edit_message_text(
                        full_response, 
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id
                    )
                else: 
                    if full_response.strip(): 
                         raise
            except Exception as final_e: 
                print(f"Error in final message edit (non-Markdown fallback): {final_e}")
                if sent_message and not full_response.strip(): 
                     await bot.edit_message_text(
                        "پاسخ خالی دریافت شد.", 
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id
                    )
        
        await save_user_chats()

    except Exception as e:
        traceback.print_exc()
        error_message_detail = f"{error_info}\nجزئیات خطا: ```\n{str(e)}\n```"
        if sent_message:
            try:
                await bot.edit_message_text(
                    escape(error_message_detail), 
                    chat_id=sent_message.chat.id,
                    message_id=sent_message.message_id,
                    parse_mode="MarkdownV2"
                )
            except Exception as edit_err_md:
                print(f"Could not edit message to show Markdown error: {edit_err_md}")
                try: 
                    await bot.edit_message_text(
                        f"{error_info}\nجزئیات خطا: {str(e)}",
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id
                    )
                except Exception as edit_err_plain:
                     print(f"Could not edit message to show plain text error: {edit_err_plain}")
                     await bot.reply_to(message, f"{error_info}\nجزئیات خطا: {str(e)}")
        else:
            await bot.reply_to(message, f"{error_info}\nجزئیات خطا: {str(e)}") 

async def gemini_edit(bot: TeleBot, message: Message, m: str, photo_file: bytes):
    image = Image.open(io.BytesIO(photo_file))
    client = get_random_client()
    sent_progress_message = None
    try:
        sent_progress_message = await bot.reply_to(message, "در حال پردازش تصویر با دستور شما... 🖼️")
        
        full_model_3_name = ensure_model_prefix(model_3)
        # Create GenerativeModel instance
        model_instance = genai.GenerativeModel(
            model_name=full_model_3_name,
            client=client
            # generation_config contains safety_settings, so not explicitly set here
        )
        
        response = await model_instance.generate_content_async( # Use generate_content_async
            contents=[m, image],
            generation_config=generation_config 
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
                current_pos = 0
                while current_pos < len(text_response):
                    end_pos = current_pos + 4000 
                    chunk_text = text_response[current_pos:end_pos]
                    try:
                        await bot.send_message(message.chat.id, escape(chunk_text), parse_mode="MarkdownV2")
                    except Exception as e_md:
                        print(f"Error sending MD chunk in gemini_edit: {e_md}, falling back to plain.")
                        await bot.send_message(message.chat.id, chunk_text)
                    current_pos = end_pos
                processed_parts = True
            elif hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
                photo = part.inline_data.data
                caption_text = escape("نتیجه ویرایش تصویر:") if not m.lower().startswith("تصویر را توصیف کن") else escape(m)
                await bot.send_photo(message.chat.id, photo, caption=caption_text[:1024]) 
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
        full_model_3_name = ensure_model_prefix(model_3)
        # Create GenerativeModel instance
        model_instance = genai.GenerativeModel(
            model_name=full_model_3_name,
            client=client
            # generation_config contains safety_settings
        )

        response = await model_instance.generate_content_async( # Use generate_content_async
            contents=[m],  
            generation_config=generation_config 
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
                caption_text = escape(f"تصویر تولید شده برای: {m[:100]}")
                await bot.send_photo(message.chat.id, photo_data, caption=caption_text[:1024]) 
                image_generated = True
                break 
            except Exception as send_photo_e:
                traceback.print_exc()
                await bot.send_message(message.chat.id, f"{error_info}\nخطا در هنگام ارسال تصویر: {str(send_photo_e)}")
                image_generated = False 
                break 
    if not image_generated:
        text_response_parts = []
        for part_item in response.candidates[0].content.parts: 
            if hasattr(part_item, 'text') and part_item.text is not None:
                text_response_parts.append(part_item.text)
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
                 await bot.send_message(message.chat.id, "تصویری تولید نشد و پاسخی متنی نیز از مدل دریافت نگردید.")
        else: 
            await bot.send_message(message.chat.id, "تصویری تولید نشد و پاسخی از مدل دریافت نگردید.")
