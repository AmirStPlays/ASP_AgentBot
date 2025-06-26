import io
import time
import traceback
import random
from PIL import Image
from telebot.types import Message
from md2tgmd import escape
from telebot import TeleBot
from config import conf, safety_settings, generation_config
from datetime import datetime, timezone, timedelta, time as dt_time
import google.generativeai as genai
from google import genai as genai1
import os
from dotenv import load_dotenv
import json
import aiofiles
import asyncio


model_1 = conf["model_1"]
model_2 = conf["model_2"]
model_3 = conf["model_3"]
error_info = conf["error_info"]
before_generate_info = conf["before_generate_info"]
download_pic_notify = conf["download_pic_notify"]
default_system_prompt = conf.get("default_system_prompt", "").strip()
default_image_processing_prompt = conf.get("default_image_processing_prompt", "")



search_tool = {"google_search": {}}


MODELS_WITH_SEARCH = {conf["model_1"]}


load_dotenv()
GEMINI_API_KEYS = os.getenv("gemini_api_keys", "").split(",")


user_chats = {}
USER_CHATS_FILE = "user_chats_data.json"
_save_lock = asyncio.Lock()


def get_random_client():
    api_key = random.choice(GEMINI_API_KEYS)
    return genai1.Client(api_key=api_key)

def random_configure():
    api_key = random.choice(GEMINI_API_KEYS)
    return genai.configure(api_key=api_key)

def _initialize_user(user_id_str):
    if user_id_str not in user_chats:
        user_chats[user_id_str] = {
            "history": [],
            "stats": {
                "messages": 0,
                "generated_images": 0,
                "edited_images": 0,
            }
        }
    elif "stats" not in user_chats[user_id_str]:
        user_chats[user_id_str]["stats"] = {
            "messages": 0,
            "generated_images": 0,
            "edited_images": 0,
        }
    if "history" not in user_chats[user_id_str]:
        user_chats[user_id_str]["history"] = []


async def save_user_chats():
    async with _save_lock:
        try:
            async with aiofiles.open(USER_CHATS_FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(user_chats, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"Error saving user chats to file: {e}")

async def load_user_chats_async():
    global user_chats
    user_chats = {}
    print("Initialized in-memory user_chats dictionary.")
    if os.path.exists(USER_CHATS_FILE):
        try:
            async with aiofiles.open(USER_CHATS_FILE, "r", encoding="utf-8") as f:
                content = await f.read()
                user_chats = json.loads(content)
            print(f"Successfully loaded chat data for {len(user_chats)} users.")
        except Exception as e:
            print(f"Error loading user chats from file: {e}")
            user_chats = {}

def _convert_chat_history_to_dicts(chat_session):
    history_list = []
    for content in chat_session.history:
        if content.parts and all(hasattr(p, 'text') for p in content.parts):
             role = content.role if content.role else "model"
             parts = [{"text": part.text} for part in content.parts if hasattr(part, 'text')]
             if parts:
                 history_list.append({"role": role, "parts": parts})
    return history_list


async def daily_reset_stats():
    """آمار روزانه ساخت و ویرایش تصویر را برای همه کاربران در نیمه‌شب ریست می‌کند."""
    while True:
        # Timezone for Iran
        tz = timezone(timedelta(hours=3, minutes=30))
        now = datetime.now(tz)
        # Calculate midnight of the next day
        tomorrow = now.date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, dt_time(0, 0), tzinfo=tz)
        
        seconds_until_midnight = (midnight - now).total_seconds()
        print(f"Daily stat reset scheduled in {seconds_until_midnight / 3600:.2f} hours.")
        await asyncio.sleep(seconds_until_midnight)

        print("Performing daily stat reset...")
        async with _save_lock:
            users_to_reset = list(user_chats.keys())
            for user_id in users_to_reset:
                if "stats" in user_chats.get(user_id, {}):
                    user_chats[user_id]["stats"]["generated_images"] = 0
                    user_chats[user_id]["stats"]["edited_images"] = 0
            
            await save_user_chats() 
        print("Daily stat reset complete.")
        await asyncio.sleep(1)


async def gemini_stream(bot: TeleBot, message: Message, m: str, model_type: str):
    random_configure()
    sent_message = None
    user_id_str = str(message.from_user.id)
    _initialize_user(user_id_str)

    try:
        history_dicts = user_chats[user_id_str]["history"]

        if not history_dicts and default_system_prompt:
            try:
                time_zone = timezone(timedelta(hours=3, minutes=30))
                date = datetime.now(time_zone).strftime("%d/%m/%Y")
                timenow = datetime.now(time_zone).strftime("%H:%M:%S")
                time_prompt = f"**اطلاعات تاریخ و زمان:**\nتاریخ: {date}\nزمان: {timenow}"
                full_prompt = default_system_prompt + "\n\n" + time_prompt
                
                history_dicts.append({"role": "user", "parts": [{"text": full_prompt}]})
                history_dicts.append({"role": "model", "parts": [{"text": "باشه، متوجه شدم."}]})
                print(f"Default prompt added for user {user_id_str}")
            except Exception as e:
                print(f"Warning failed to add default prompt: {e}")

        model = genai.GenerativeModel(model_type, tools=[search_tool] if model_type in MODELS_WITH_SEARCH else None)
        chat = model.start_chat(history=history_dicts)
        
        sent_message = await bot.reply_to(message, before_generate_info)
        response = await chat.send_message_async(m, stream=True, safety_settings=safety_settings)

        full_response = ""
        last_update = time.time()
        update_interval = conf["streaming_update_interval"]
        
        async for chunk in response:
            if hasattr(chunk, 'text') and chunk.text:
                full_response += chunk.text
                current_time = time.time()
                if current_time - last_update >= update_interval:
                    try:
                        await bot.edit_message_text(escape(full_response + "✍️"), chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
                    except Exception as e:
                        if "message is not modified" not in str(e).lower():
                             await bot.edit_message_text(full_response + "✍️", chat_id=sent_message.chat.id, message_id=sent_message.message_id)
                    last_update = current_time

        final_text = escape(full_response) if full_response else "پاسخی دریافت نشد."
        await bot.edit_message_text(final_text, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
        
        user_chats[user_id_str]["stats"]["messages"] += 1
        user_chats[user_id_str]["history"] = _convert_chat_history_to_dicts(chat)
        asyncio.create_task(save_user_chats())

    except Exception as e:
        traceback.print_exc()
        error_message_detail = f"{error_info}\nجزئیات خطا: {str(e)}"
        if sent_message:
            await bot.edit_message_text(error_message_detail, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
        else:
            await bot.reply_to(message, error_message_detail)


async def gemini_process_image_stream(bot: TeleBot, message: Message, m: str, photo_file: bytes, model_type: str, status_message: Message = None):
    random_configure()
    user_id_str = str(message.from_user.id)
    _initialize_user(user_id_str)
    sent_message = status_message
    
    try:
        image = Image.open(io.BytesIO(photo_file))
    
        model = genai.GenerativeModel(model_type) 
        

        chat_contents = []
        if default_image_processing_prompt:
            chat_contents.append({"role": "user", "parts": [{"text": default_image_processing_prompt}]})
            chat_contents.append({"role": "model", "parts": [{"text": "باشه، متوجه شدم. از این به بعد تصاویر را با توجه به این دستورالعمل پردازش می‌کنم."}]})


        chat_contents.append({"role": "user", "parts": [m, image]})

        if not sent_message:
            sent_message = await bot.reply_to(message, before_generate_info)
        
        response = await model.generate_content_async(chat_contents, stream=True, safety_settings=safety_settings)

        full_response = ""
        last_update = time.time()
        update_interval = conf["streaming_update_interval"]
        
        async for chunk in response:
            if hasattr(chunk, 'text') and chunk.text:
                full_response += chunk.text
                current_time = time.time()
                if current_time - last_update >= update_interval:
                    try:
                        await bot.edit_message_text(escape(full_response + "✍️"), chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
                    except Exception as e:
                        if "message is not modified" not in str(e).lower():
                            await bot.edit_message_text(full_response + "✍️", chat_id=sent_message.chat.id, message_id=sent_message.message_id)
                    last_update = current_time

        final_text = escape(full_response) if full_response else "پاسخی دریافت نشد."
        await bot.edit_message_text(final_text, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
        

        user_chats[user_id_str]["stats"]["messages"] += 1
        asyncio.create_task(save_user_chats())

    except Exception as e:
        traceback.print_exc()
        error_message_detail = f"{error_info}\nجزئیات خطا: {str(e)}"
        if sent_message:
            await bot.edit_message_text(error_message_detail, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
        else:
            await bot.reply_to(message, error_message_detail)


async def gemini_draw(bot: TeleBot, message: Message, m: str):
    client = get_random_client()
    user_id_str = str(message.from_user.id)
    _initialize_user(user_id_str)
    

    try:
        response = await client.aio.models.generate_content(
            model=model_3,
            contents=m,
            generation_config=generation_config
        )
    except Exception as e:
        traceback.print_exc()
        await bot.send_message(message.chat.id, f"{error_info}\nخطا در هنگام تولید تصویر: {str(e)}")
        return

    if not (response and hasattr(response, 'candidates') and response.candidates and \
       hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts')):
        await bot.send_message(message.chat.id, f"{error_info}\nپاسخ معتبری هنگام ترسیم تصویر دریافت نشد.")
        await bot.send_message(message.chat.id, f"احتمال زیاد مشکل از متنته.\nاحتمالا یکم sus بوده.🤭")
        return

    image_sent = False
    for part in response.candidates[0].content.parts:
        if hasattr(part, 'text') and part.text is not None:
            text = part.text
            while len(text) > 4000:
                await bot.send_message(message.chat.id, escape(text[:4000]), parse_mode="MarkdownV2")
                text = text[4000:]
            if text:
                await bot.send_message(message.chat.id, escape(text), parse_mode="MarkdownV2")
        elif hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
            photo_data = part.inline_data.data
            await bot.send_photo(message.chat.id, photo_data, caption=escape(f"تصویر تولید شده برای: {m[:100]}"))
            image_sent = True

    if image_sent:
        user_chats[user_id_str]["stats"]["generated_images"] += 1
        asyncio.create_task(save_user_chats())
    elif not any(hasattr(p, 'text') and p.text for p in response.candidates[0].content.parts):
        await bot.send_message(message.chat.id, "تصویری تولید نشد یا محتوای قابل نمایشی وجود نداشت.")


async def gemini_edit(bot: TeleBot, message: Message, m: str, photo_file: bytes):
    image = Image.open(io.BytesIO(photo_file))
    client = get_random_client()
    user_id_str = str(message.from_user.id)
    _initialize_user(user_id_str)
    
    sent_progress_message = None
    try:
        sent_progress_message = await bot.reply_to(message, "در حال پردازش تصویر با دستور شما... 🖼️")
        

        response = await client.aio.models.generate_content(
            model=model_3,
            contents=[m, image],
            generation_config=generation_config
        )

        if sent_progress_message:
            await bot.delete_message(sent_progress_message.chat.id, sent_progress_message.message_id)

        if not (response and hasattr(response, 'candidates') and response.candidates and \
           hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts')):
            await bot.send_message(message.chat.id, f"{error_info}\nپاسخ معتبری از سرویس دریافت نشد.")
            return

        image_sent = False
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text is not None:
                text_response = part.text
                while len(text_response) > 4000:
                    await bot.send_message(message.chat.id, escape(text_response[:4000]), parse_mode="MarkdownV2")
                    text_response = text_response[4000:]
                if text_response:
                    await bot.send_message(message.chat.id, escape(text_response), parse_mode="MarkdownV2")
            elif hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
                photo = part.inline_data.data
                await bot.send_photo(message.chat.id, photo, caption=escape("نتیجه ویرایش تصویر:") if not m.startswith("تصویر را توصیف کن") else escape(m))
                image_sent = True

        if image_sent:
            user_chats[user_id_str]["stats"]["edited_images"] += 1
            asyncio.create_task(save_user_chats())
        elif not any(hasattr(p, 'text') and p.text for p in response.candidates[0].content.parts):
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
