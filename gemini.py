import random
import io
import traceback
import asyncio
from datetime import datetime, timezone, timedelta, time as dt_time
from PIL import Image
from telebot import TeleBot
from dotenv import load_dotenv
import os
from telebot.types import Message
import aiofiles
import json
import time
from google import genai as genai1
from md2tgmd import escape
from config import conf, safety_settings, generation_config


PRO_MODELS = {
    conf["model_1"],
    conf["model_2"]}


model_1 = conf["model_1"]
model_2 = conf["model_2"]
model_3 = conf["model_3"]
error_info = conf["error_info"]
before_generate_info = conf["before_generate_info"]
download_pic_notify = conf["download_pic_notify"]
default_system_prompt = conf.get("default_system_prompt", "").strip()
default_image_processing_prompt = conf.get("default_image_processing_prompt", "")


load_dotenv()
GEMINI_API_KEYS = os.getenv("gemini_api_keys", "").split(",")

user_chats = {}
USER_CHATS_FILE = "user_chats_data.json"
_save_lock = asyncio.Lock()




def split_long_message(text, max_length=4000):
    """تقسیم متن به بخش‌هایی با حداکثر max_length کاراکتر"""
    if len(text) <= max_length:
        return [text]
    parts = []
    while len(text) > max_length:
        split_index = text.rfind('\n', 0, max_length)
        if split_index == -1 or split_index < max_length // 2:
            split_index = max_length
        parts.append(text[:split_index])
        text = text[split_index:].lstrip()
    if text:
        parts.append(text)
    return parts

def _initialize_user(user_id_str):
    if user_id_str not in user_chats:
        user_chats[user_id_str] = {"history": [], "stats": {"messages": 0, "generated_images": 0, "edited_images": 0}}
    elif "stats" not in user_chats[user_id_str]:
        user_chats[user_id_str]["stats"] = {"messages": 0, "generated_images": 0, "edited_images": 0}
    if "history" not in user_chats[user_id_str]:
        user_chats[user_id_str]["history"] = []

async def save_user_chats():
    async with _save_lock:
        try:
            save_data = {}
            for uid, data in user_chats.items():
                # Do not save the chat session object, only serializable data
                history_to_save = data.get("history", [])
                stats_to_save = data.get("stats", {"messages": 0, "generated_images": 0, "edited_images": 0})
                save_data[uid] = {
                    "history": history_to_save,
                    "stats": stats_to_save
                }
            async with aiofiles.open(USER_CHATS_FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(save_data, ensure_ascii=False, indent=2))
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
                loaded_data = json.loads(content)
                for uid, data in loaded_data.items():
                     _initialize_user(uid)
                     user_chats[uid]["history"] = data.get("history", [])
                     user_chats[uid]["stats"] = data.get("stats", {"messages": 0, "generated_images": 0, "edited_images": 0})
            print(f"Successfully loaded chat data for {len(user_chats)} users.")
        except Exception as e:
            print(f"Error loading user chats from file: {e}")
            user_chats = {}


async def daily_reset_stats():
    while True:
        tz = timezone(timedelta(hours=3, minutes=30))
        now = datetime.now(tz)
        tomorrow = now.date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, dt_time(0, 0), tzinfo=tz)
        seconds_until_midnight = (midnight - now).total_seconds()
        print(f"Daily stat reset scheduled in {seconds_until_midnight / 3600:.2f} hours.")
        await asyncio.sleep(seconds_until_midnight)
        print("Performing daily stat reset...")
        async with _save_lock:
            for user_id in user_chats:
                if "stats" in user_chats.get(user_id, {}):
                    user_chats[user_id]["stats"]["generated_images"] = 0
                    user_chats[user_id]["stats"]["edited_images"] = 0
            await save_user_chats()
        print("Daily stat reset complete.")
        await asyncio.sleep(1)

def _get_tools_for_model(model_type: str):
    if model_type in PRO_MODELS:
        return [search_tool]
    return None



search_tool = {'google_search': {}}

def get_random_client():
    api_key = random.choice(os.getenv("gemini_api_keys", "").split(","))
    return genai1.Client(api_key=api_key)

# تابع کمکی برای مدیریت استریم پاسخ از کتابخانه google-genai
async def _handle_response_streaming_genai1(response_stream, sent_message, bot):
    """Handles streaming responses from the google-genai library."""
    full_response = ""
    last_update = time.time()
    update_interval = conf["streaming_update_interval"]
    try:
        async for chunk in response_stream:
            if hasattr(chunk, 'text') and chunk.text:
                full_response += chunk.text
                current_time = time.time()
                if current_time - last_update >= update_interval and full_response.strip():
                    text_to_send = escape(full_response + "✍️")
                    try:
                        await bot.edit_message_text(text_to_send, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
                    except Exception as e:
                        if "message is not modified" not in str(e).lower():
                            # Fallback to sending without MarkdownV2 if escaping fails
                            await bot.edit_message_text(full_response + "✍️", chat_id=sent_message.chat.id, message_id=sent_message.message_id)
                    last_update = current_time
    except Exception as e:
        print(f"Error during streaming with genai1: {e}")
    return full_response

async def gemini_stream(bot: TeleBot, message: Message, m: str, model_type: str):
    user_id = str(message.from_user.id)
    _initialize_user(user_id)
    sent_message = None
    try:
        client = get_random_client()
        chat_session_key = 'chat_session'
        chat_model_key = 'chat_model'
        chat_session = user_chats[user_id].get(chat_session_key)
        current_model = user_chats[user_id].get(chat_model_key)
        if not chat_session or current_model != model_type:
            user = message.from_user
            first_name = user.first_name or "کاربر"
            tz = timezone(timedelta(hours=3, minutes=30))
            date = datetime.now(tz).strftime("%d/%m/%Y")
            timenow = datetime.now(tz).strftime("%H:%M:%S")
            system_prompt_text = (
                f"نام کاربر: {first_name}\n"
                f"تاریخ: {date}\nزمان: {timenow}\n\n"
                f"{default_system_prompt}"
            )
            initial_history = [
                {'role': 'user', 'parts': [{'text': system_prompt_text}]},
                {'role': 'model', 'parts': [{'text': "باشه، متوجه شدم. آماده‌ام."}]}
            ]
            tools_config = [search_tool] if model_type in PRO_MODELS else None
            chat_config = {}
            if tools_config:
                chat_config['tools'] = tools_config

            chat_session = client.aio.chats.create(
                model=model_type,
                history=initial_history,
                config=chat_config
            )
            user_chats[user_id][chat_session_key] = chat_session
            user_chats[user_id][chat_model_key] = model_type

        sent_message = await bot.reply_to(message, before_generate_info)
        response_stream = await chat_session.send_message_stream(m)
        full_response = ""
        last_update = time.time()
        update_interval = conf["streaming_update_interval"]
        async for chunk in response_stream:
            if hasattr(chunk, 'text') and chunk.text:
                full_response += chunk.text
                current_time = time.time()
                if current_time - last_update >= update_interval and full_response.strip():
                    try:
                        await bot.edit_message_text(
                            escape(full_response + "✍️"),
                            chat_id=sent_message.chat.id,
                            message_id=sent_message.message_id,
                            parse_mode="MarkdownV2"
                        )
                    except Exception as e:
                        if "message is not modified" not in str(e).lower():
                            await bot.edit_message_text(
                                full_response + "✍️",
                                chat_id=sent_message.chat.id,
                                message_id=sent_message.message_id
                            )
                    last_update = current_time

        final_text = escape(full_response or "پاسخی دریافت نشد.")
        text_parts = split_long_message(final_text, 4000)

        for i, part in enumerate(text_parts):
            try:
                if i == 0:
                    await bot.edit_message_text(part, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
                else:
                    await bot.send_message(message.chat.id, part, parse_mode="MarkdownV2")
            except Exception:
                if i == 0:
                    await bot.edit_message_text(part, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
                else:
                    await bot.send_message(message.chat.id, part)

        user_chats[user_id]["stats"]["messages"] += 1
    except Exception as e:
        traceback.print_exc()
        err = f"{error_info}\nجزئیات خطا: {str(e)}"
        if sent_message:
            try:
                await bot.edit_message_text(err, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
            except Exception:
                await bot.reply_to(message, err)
        else:
            await bot.reply_to(message, err)


async def gemini_process_image_stream(bot: TeleBot, message: Message, m: str, photo_file: bytes, model_type: str, status_message: Message = None):
    user_id = str(message.from_user.id)
    _initialize_user(user_id)
    sent_message = status_message
    try:
        client = get_random_client()
        chat_session_key = 'chat_session'
        chat_model_key = 'chat_model'
        chat_session = user_chats[user_id].get(chat_session_key)
        current_model = user_chats[user_id].get(chat_model_key)
        if not chat_session or current_model != model_type:
            user = message.from_user
            first_name = user.first_name or "کاربر"
            tz = timezone(timedelta(hours=3, minutes=30))
            date = datetime.now(tz).strftime("%d/%m/%Y")
            timenow = datetime.now(tz).strftime("%H:%M:%S")
            system_prompt_text = (
                f"نام کاربر: {first_name}\n"
                f"تاریخ: {date}\nزمان: {timenow}\n\n"
                f"{default_system_prompt}"
            )
            initial_history = [
                {'role': 'user', 'parts': [{'text': system_prompt_text}]},
                {'role': 'model', 'parts': [{'text': "باشه، متوجه شدم. آماده‌ام."}]}
            ]
            chat_session = client.aio.chats.create(
                model=model_type,
                history=initial_history
            )
            user_chats[user_id][chat_session_key] = chat_session
            user_chats[user_id][chat_model_key] = model_type

        image = Image.open(io.BytesIO(photo_file))
        contents = [m, image]

        if not sent_message:
            sent_message = await bot.reply_to(message, before_generate_info)

        response_stream = await chat_session.send_message_stream(contents)
        full_response = ""
        last_update = time.time()
        update_interval = conf["streaming_update_interval"]
        async for chunk in response_stream:
            if hasattr(chunk, 'text') and chunk.text:
                full_response += chunk.text
                current_time = time.time()
                if current_time - last_update >= update_interval and full_response.strip():
                    try:
                        await bot.edit_message_text(
                            escape(full_response + "✍️"),
                            chat_id=sent_message.chat.id,
                            message_id=sent_message.message_id,
                            parse_mode="MarkdownV2"
                        )
                    except Exception as e:
                        if "message is not modified" not in str(e).lower():
                            await bot.edit_message_text(
                                full_response + "✍️",
                                chat_id=sent_message.chat.id,
                                message_id=sent_message.message_id
                            )
                    last_update = current_time

        final_text = escape(full_response or "پاسخی دریافت نشد.")
        text_parts = split_long_message(final_text, 4000)

        for i, part in enumerate(text_parts):
            try:
                if i == 0:
                    await bot.edit_message_text(part, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
                else:
                    await bot.send_message(message.chat.id, part, parse_mode="MarkdownV2")
            except Exception:
                if i == 0:
                    await bot.edit_message_text(part, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
                else:
                    await bot.send_message(message.chat.id, part)

        user_chats[user_id]["stats"]["messages"] += 1
        asyncio.create_task(save_user_chats())

    except Exception as e:
        traceback.print_exc()
        err = escape(f"{error_info}\nجزئیات خطا: {str(e)}")
        if sent_message:
            await bot.edit_message_text(err, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
        else:
            await bot.reply_to(message, err, parse_mode="MarkdownV2")



async def gemini_process_voice(bot: TeleBot, message: Message, voice_file: bytes, model_type: str, status_message: Message = None):
    user_id = str(message.from_user.id)
    _initialize_user(user_id)
    sent_message = status_message

    try:
        client = get_random_client()

        chat_session_key = 'chat_session'
        chat_model_key = 'chat_model'
        chat_session = user_chats[user_id].get(chat_session_key)
        current_model = user_chats[user_id].get(chat_model_key)

        if not chat_session or current_model != model_type:
            user = message.from_user
            first_name = user.first_name or "کاربر"
            tz = timezone(timedelta(hours=3, minutes=30))
            date = datetime.now(tz).strftime("%d/%m/%Y")
            timenow = datetime.now(tz).strftime("%H:%M:%S")
            system_prompt_text = (
                f"نام کاربر: {first_name}\n"
                f"تاریخ: {date}\nزمان: {timenow}\n\n"
                f"{default_system_prompt}"
            )
            initial_history = [
                {'role': 'user', 'parts': [{'text': system_prompt_text}]},
                {'role': 'model', 'parts': [{'text': "باشه، متوجه شدم. آماده‌ام."}]}
            ]
            chat_session = client.aio.chats.create(
                model=model_type,
                history=initial_history
            )
            user_chats[user_id][chat_session_key] = chat_session
            user_chats[user_id][chat_model_key] = model_type

        prompt = (
            "لطفاً فقط متن دقیق گفته‌شده در فایل صوتی زیر را بدون هیچ توضیح یا اصلاحی بنویس.\n"
            "ممکن است زبان گفتار فارسی، انگلیسی یا ترکیبی باشد، بنابراین با دقت همان را بازنویسی کن.\n"
        )

        if not sent_message:
            sent_message = await bot.reply_to(message, "در حال تبدیل ویس به متن... 🎤")

        contents = [{"text": prompt}, {"mime_type": "audio/ogg", "data": voice_file}]
        response = await chat_session.send_message(contents)

        transcribed_text = response.text.strip() if hasattr(response, "text") and response.text else "متنی از این پیام صوتی تشخیص داده نشد."
        final_text = f"```\n{escape(transcribed_text)}\n```"

        await bot.edit_message_text(final_text, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")

        user_chats[user_id]["stats"]["messages"] += 1
        asyncio.create_task(save_user_chats())

    except Exception as e:
        traceback.print_exc()
        err = escape(f"{error_info}\nجزئیات خطا: {str(e)}")
        if sent_message:
            await bot.edit_message_text(err, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
        else:
            await bot.reply_to(message, err, parse_mode="MarkdownV2")




async def gemini_draw(bot: TeleBot, message: Message, m: str):
    client = get_random_client()
    image_generation_chat = client.aio.chats.create(model=model_3, config=generation_config)
    user_id_str = str(message.from_user.id)
    _initialize_user(user_id_str)

    try:
        response = await image_generation_chat.send_message(m)
    except Exception as e:
        traceback.print_exc()
        await bot.send_message(message.chat.id, f"{error_info}\nخطا در هنگام تولید تصویر: {str(e)}")
        return

    if not (response and hasattr(response, 'candidates') and response.candidates and \
       hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts')):
        await bot.send_message(message.chat.id, f"{error_info}\nپاسخ معتبری هنگام ترسیم تصویر دریافت نشد.")
        await bot.send_message(message.chat.id, f"احتمال زیاد مشکل از متنته.\nاحتمالا یکم sus بوده.🤭")
        return

    processed_parts = False
    for part in response.candidates[0].content.parts:
        if hasattr(part, 'text') and part.text is not None:
            text = part.text
            while len(text) > 4000:
                await bot.send_message(message.chat.id, escape(text[:4000]), parse_mode="MarkdownV2")
                text = text[4000:]
            if text:
                await bot.send_message(message.chat.id, escape(text), parse_mode="MarkdownV2")
            processed_parts = True
        elif hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
            photo_data = part.inline_data.data
            await bot.send_photo(message.chat.id, photo_data, caption=escape(f"تصویر تولید شده برای: {m[:100]}"))
            processed_parts = True

    if not processed_parts:
        await bot.send_message(message.chat.id, "تصویری تولید نشد یا محتوای قابل نمایشی وجود نداشت.")

    user_chats[user_id_str]["stats"]["generated_images"] = user_chats[user_id_str]["stats"].get("generated_images", 0) + 1
    asyncio.create_task(save_user_chats())



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

        user_chats[user_id_str]["stats"]["edited_images"] = user_chats[user_id_str]["stats"].get("edited_images", 0) + 1
        asyncio.create_task(save_user_chats())

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
