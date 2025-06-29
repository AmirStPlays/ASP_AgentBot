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
import google.generativeai as genai
from google.generativeai.types import generation_types
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

def get_random_client():
    api_key = random.choice(GEMINI_API_KEYS)
    return genai1.Client(api_key=api_key)

def random_configure():
    api_key = random.choice(GEMINI_API_KEYS)
    return genai.configure(api_key=api_key)

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
                save_data[uid] = {
                    "history": [],
                    "stats": data.get("stats", {"messages": 0, "generated_images": 0, "edited_images": 0})
                }
                if "history_for_saving" in data:
                     save_data[uid]["history"] = data["history_for_saving"]
                elif "history" in data:
                    clean_history = []
                    for item in data["history"]:
                        if isinstance(item, dict) and 'parts' in item and isinstance(item['parts'], list):
                            text_parts = [p['text'] for p in item['parts'] if isinstance(p, dict) and 'text' in p]
                            if text_parts:
                                clean_history.append({
                                    "role": item.get("role"),
                                    "parts": [{"text": " ".join(text_parts)}]
                                })
                    save_data[uid]["history"] = clean_history

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
                user_chats = json.loads(content)
            print(f"Successfully loaded chat data for {len(user_chats)} users.")
        except Exception as e:
            print(f"Error loading user chats from file: {e}")
            user_chats = {}

def _convert_chat_history_to_dicts(chat_session):
    persistent_history = []
    for content in chat_session.history:
        is_tool_related = any(hasattr(p, 'function_call') or hasattr(p, 'function_response') for p in content.parts)
        if is_tool_related:
            continue
        
        text_parts = [p.text for p in content.parts if hasattr(p, 'text') and p.text]
        if text_parts:
            persistent_history.append({
                "role": content.role,
                "parts": [{"text": " ".join(text_parts)}]
            })
    return persistent_history

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
        return ['code_execution']
    return None



async def _handle_response_streaming(response, sent_message, bot):
    full_response = ""
    last_update = time.time()
    update_interval = conf["streaming_update_interval"]
    try:
        async for chunk in response:
            try:
                if chunk.text:
                    full_response += chunk.text
                    current_time = time.time()
                    if current_time - last_update >= update_interval:
                        await bot.edit_message_text(escape(full_response + "✍️"), chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
                        last_update = current_time
            except (ValueError, generation_types.StopCandidateException) as e:
                print(f"Streaming stopped for a valid reason: {e}")
                break
    except Exception as e:
        print(f"Error during streaming: {e}")
    return full_response

async def gemini_stream(bot: TeleBot, message: Message, m: str, model_type: str):
    # انتخاب و کانفیگ کلید API
    api_key = random.choice(GEMINI_API_KEYS)
    genai.configure(api_key=api_key)

    sent_message = None
    user_id = str(message.from_user.id)
    _initialize_user(user_id)
    user = message.from_user
    first_name = user.first_name or "کاربر"

    # ساخت system prompt با تاریخ و زمان
    tz = timezone(timedelta(hours=3, minutes=30))
    date = datetime.now(tz).strftime("%d/%m/%Y")
    timenow = datetime.now(tz).strftime("%H:%M:%S")
    system_prompt = (
        f"نام کاربر: {first_name}\n"
        f"تاریخ: {date}\nزمان: {timenow}\n"
        + (default_system_prompt or "")
    )

    try:
        history = user_chats[user_id].setdefault("history", [])
        if not history and default_system_prompt:
            history.extend([
                {"role": "user",  "parts":[{"text": system_prompt}]},
                {"role": "model", "parts":[{"text": "باشه، متوجه شدم."}]}
            ])

        # انتخاب ابزار بر اساس مدل
        tools = _get_tools_for_model(model_type)

        # ایجاد یا بازیابی چت
        model = genai.GenerativeModel(
            model_name=model_type,
            tools=tools,
            safety_settings=safety_settings
        )
        chat = model.start_chat(history=history)

        sent_message = await bot.reply_to(message, before_generate_info)

        # اگر ابزار داریم، استریم خاموش؛ وگرنه استریم روشن
        stream_enabled = not bool(tools)
        response = await chat.send_message_async(m, stream=stream_enabled)

        # جمع‌آوری پاسخ
        if stream_enabled:
            full_response = await _handle_response_streaming(response, sent_message, bot)
        else:
            try:
                full_response = response.text
            except (ValueError, generation_types.StopCandidateException):
                full_response = ""

        final_text = escape(full_response or "پاسخی دریافت نشد. (احتمالاً فیلتر ایمنی)")
        await bot.edit_message_text(
            final_text,
            chat_id=sent_message.chat.id,
            message_id=sent_message.message_id,
            parse_mode="MarkdownV2"
        )

        # ذخیره‌ی تاریخچه
        user_chats[user_id]["stats"]["messages"] += 1
        user_chats[user_id]["history_for_saving"] = _convert_chat_history_to_dicts(chat)
        user_chats[user_id]["history"] = chat.history
        asyncio.create_task(save_user_chats())

    except Exception as e:
        traceback.print_exc()
        err = f"{error_info}\nجزئیات خطا: {e}"
        if sent_message:
            await bot.edit_message_text(err, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
        else:
            await bot.reply_to(message, err)

# ———— تابع gemini_process_image_stream ————
async def gemini_process_image_stream(
    bot: TeleBot,
    message: Message,
    m: str,
    photo_file: bytes,
    model_type: str,
    status_message: Message = None
):
    # انتخاب و کانفیگ کلید API
    api_key = random.choice(GEMINI_API_KEYS)
    genai.configure(api_key=api_key)

    user_id = str(message.from_user.id)
    _initialize_user(user_id)
    sent_message = status_message
    user = message.from_user
    first_name = user.first_name or "کاربر"

    tz = timezone(timedelta(hours=3, minutes=30))
    date = datetime.now(tz).strftime("%d/%m/%Y")
    timenow = datetime.now(tz).strftime("%H:%M:%S")
    full_prompt = (
        f"نام کاربر: {first_name}\n"
        f"تاریخ: {date}\nزمان: {timenow}\n\n"
        f"{default_image_processing_prompt}\n\n{m}"
    )

    try:
        image = Image.open(io.BytesIO(photo_file))

        # انتخاب ابزار برای تصویر
        tools = _get_tools_for_model(model_type)
        model = genai.GenerativeModel(
            model_name=model_type,
            tools=tools,
            safety_settings=safety_settings
        )

        history = user_chats[user_id].setdefault("history", [])
        user_part = {"role": "user", "parts": [full_prompt, image]}
        chat_contents = history + [user_part]

        if not sent_message:
            sent_message = await bot.reply_to(message, before_generate_info)

        stream_enabled = not bool(tools)
        response = await model.generate_content_async(chat_contents, stream=stream_enabled)

        if stream_enabled:
            full_response = await _handle_response_streaming(response, sent_message, bot)
        else:
            try:
                full_response = response.text
            except Exception:
                full_response = ""

        final_text = escape(full_response or "پاسخی دریافت نشد. (احتمالاً فیلتر ایمنی)")
        await bot.edit_message_text(
            final_text,
            chat_id=sent_message.chat.id,
            message_id=sent_message.message_id,
            parse_mode="MarkdownV2"
        )

        # به‌روزرسانی تاریخچه
        model_part = {"role": "model", "parts": [{"text": full_response}]}
        history.extend([user_part, model_part])
        user_chats[user_id]["stats"]["messages"] += 1
        asyncio.create_task(save_user_chats())

    except Exception as e:
        traceback.print_exc()
        err = escape(f"{error_info}\nجزئیات خطا: {e}")
        if sent_message:
            await bot.edit_message_text(err, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
        else:
            await bot.reply_to(message, err, parse_mode="MarkdownV2")


async def gemini_process_voice(bot: TeleBot, message: Message, voice_file: bytes, model_type: str):
    random_configure()
    user_id_str = str(message.from_user.id)
    _initialize_user(user_id_str)
    sent_message = None
    user = message.from_user
    first_name = user.first_name or "کاربر"

    time_zone = timezone(timedelta(hours=3, minutes=30))
    date = datetime.now(time_zone).strftime("%d/%m/%Y")
    timenow = datetime.now(time_zone).strftime("%H:%M:%S")
    time_prompt = f"اطلاعات تاریخ و زمان:\nتاریخ: {date}\nزمان: {timenow}"
    user_prompt = f"نام کاربر: {first_name}"
    system_prompt = f"{user_prompt}\n{time_prompt}"

    try:
        sent_message = await bot.reply_to(message, "در حال تبدیل ویس به متن... 🎤")

        prompt = (
            f"{system_prompt}\n"
            "لطفاً فقط متن دقیق گفته‌شده در فایل صوتی زیر را بدون هیچ توضیح یا اصلاحی بنویس.\n"
            "ممکن است زبان گفتار فارسی، انگلیسی یا ترکیبی باشد، بنابراین با دقت همان را بازنویسی کن.\n"
        )

        model = genai.GenerativeModel(model_name=model_type, safety_settings=safety_settings)
        response = await model.generate_content_async([
            {"text": prompt},
            {"mime_type": "audio/ogg", "data": voice_file}
        ])

        transcribed_text = response.text.strip() if response.text else "متنی از این پیام صوتی تشخیص داده نشد."
        transcribed_text = escape(transcribed_text)

        final_text = f"```\n{transcribed_text}\n```"
        await bot.edit_message_text(final_text, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")

    except Exception as e:
        traceback.print_exc()
        error_message_detail = f"{error_info}\nجزئیات خطا: {str(e)}"
        if sent_message:
            await bot.edit_message_text(error_message_detail, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
        else:
            await bot.reply_to(message, error_message_detail)



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
    chat = user_chats.get(user_id_str)

    if not chat:
        chat = client.aio.chats.create(model=model_3, config=generation_config)
        user_chats[user_id_str] = chat

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
