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
import google.generativeai as genai
from google import genai as genai1
from google.generativeai.types import generation_types
from google.generativeai import types
from md2tgmd import escape
from config import conf, safety_settings, generation_config
from duckduckgo_search import duckduckgo_search

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
search_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search",
            description="Search the web for information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        )
    ]
)



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

async def execute_search(query: str):
    """Performs a web search using DuckDuckGo and returns formatted results."""
    try:
        async with duckduckgo_search() as ddgs:
            results = [r async for r in ddgs.text(query, max_results=5)]
        if not results:
            return "No search results found."
        
        formatted_results = []
        for i, result in enumerate(results, 1):
            formatted_results.append(
                f"Result {i}:\nTitle: {result.get('title')}\n"
                f"Snippet: {result.get('body')}\nURL: {result.get('href')}\n"
            )
        return "\n".join(formatted_results)
    except Exception as e:
        print(f"Error during web search: {e}")
        return "An error occurred while searching the web."


search_tool_genai1 = {
    "function_declarations": [
        {
            "name": "search",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"],
            },
        }
    ]
}

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
        chat_session_lib_key = 'chat_session_library'

        chat_session = user_chats[user_id].get(chat_session_key)
        current_model = user_chats[user_id].get(chat_model_key)
        session_lib = user_chats[user_id].get(chat_session_lib_key)

        if not chat_session or current_model != model_type or session_lib != 'genai1':
            user = message.from_user
            first_name = user.first_name or "کاربر"
            tz = timezone(timedelta(hours=3, minutes=30))
            date = datetime.now(tz).strftime("%d/%m/%Y")
            timenow = datetime.now(tz).strftime("%H:%M:%S")
            system_prompt_text = (f"نام کاربر: {first_name}\nتاریخ: {date}\nزمان: {timenow}\n{default_system_prompt or ''}")

            stored_history = user_chats[user_id].get("history", [])
            
            # *** اصلاحیه اول: تبدیل تاریخچه ذخیره‌شده به فرمت صحیح ***
            history_for_genai1 = [
                {'role': msg['role'], 'parts': [{'text': p['text']} for p in msg['parts']]}
                for msg in stored_history
            ]

            # *** اصلاحیه دوم: افزودن پرامپت سیستمی با فرمت صحیح ***
            if not stored_history and default_system_prompt:
                history_for_genai1.extend([
                    {"role": "user", "parts": [{"text": system_prompt_text}]},
                    {"role": "model", "parts": [{"text": "باشه، متوجه شدم."}]}
                ])

            tools_config = [search_tool_genai1] if model_type in PRO_MODELS else None
            chat_config = {}
            if tools_config:
                chat_config['tools'] = tools_config
            
            chat_session = client.aio.chats.create(model=model_type, history=history_for_genai1, config=chat_config)
            user_chats[user_id][chat_session_key] = chat_session
            user_chats[user_id][chat_model_key] = model_type
            user_chats[user_id][chat_session_lib_key] = 'genai1'

        sent_message = await bot.reply_to(message, before_generate_info)
        
        async def combine_stream(first, rest_iterator):
            yield first
            async for item in rest_iterator:
                yield item

        response_stream = await chat_session.send_message_stream(m)
        stream_iterator = response_stream.__aiter__()
        full_response = ""

        try:
            first_chunk = await stream_iterator.__anext__()
        except StopAsyncIteration:
            full_response = "پاسخ خالی دریافت شد."
        else:
            if first_chunk.function_calls:
                fc = first_chunk.function_calls[0]
                if fc.name == "search":
                    await bot.edit_message_text("... در حال جستجو در وب 🔍", chat_id=sent_message.chat.id, message_id=sent_message.message_id)
                    query = fc.args["query"]
                    search_result_text = await execute_search(query)
                    
                    response_stream_2 = await chat_session.send_message_stream(
                        content={'parts': [{'function_response': {'name': 'search', 'response': {'result': search_result_text}}}]}
                    )
                    full_response = await _handle_response_streaming_genai1(response_stream_2, sent_message, bot)
                else:
                    full_response = f"Unsupported function call: {fc.name}"
            else:
                combined_stream_gen = combine_stream(first_chunk, stream_iterator)
                full_response = await _handle_response_streaming_genai1(combined_stream_gen, sent_message, bot)

        final_text = escape(full_response or "پاسخی دریافت نشد.")
        text_parts = split_long_message(final_text, 4000)
        
        for i, part in enumerate(text_parts):
            try:
                if i == 0:
                    await bot.edit_message_text(part, chat_id=sent_message.chat.id, message_id=sent_message.message_id, parse_mode="MarkdownV2")
                else:
                    await bot.send_message(message.chat.id, part, parse_mode="MarkdownV2")
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    if i == 0:
                        await bot.edit_message_text(part, chat_id=sent_message.chat.id, message_id=sent_message.message_id)
                    else:
                        await bot.send_message(message.chat.id, part)
        
        user_chats[user_id]["stats"]["messages"] += 1
        serializable_history = []
        if chat_session and chat_session.history:
            for content in chat_session.history:
                is_tool_message = any(hasattr(p, 'function_call') or hasattr(p, 'function_response') for p in content.parts)
                if is_tool_message:
                    continue
                parts_to_save = [{'text': p.text} for p in content.parts if hasattr(p, 'text')]
                if parts_to_save:
                    serializable_history.append({'role': content.role, 'parts': parts_to_save})
        user_chats[user_id]["history"] = serializable_history
        asyncio.create_task(save_user_chats())

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



async def gemini_process_image_stream(bot: TeleBot,message: Message,m: str,photo_file: bytes,model_type: str,status_message: Message = None):
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
        model = genai.GenerativeModel(
            model_name=model_type,
            safety_settings=safety_settings
        )

        if not sent_message:
            sent_message = await bot.reply_to(message, before_generate_info)

        contents = [full_prompt, image]
        response = await model.generate_content_async(contents, stream=True)
        full_response = await _handle_response_streaming(response, sent_message, bot)

        final_text = escape(full_response or "پاسخی دریافت نشد.")
        text_parts = split_long_message(final_text, 4000)
        for i, part in enumerate(text_parts):
            if i == 0:
                await bot.edit_message_text(
                    part,
                    chat_id=sent_message.chat.id,
                    message_id=sent_message.message_id,
                    parse_mode="MarkdownV2"
                )
            else:
                await bot.send_message(
                    message.chat.id,
                    part,
                    parse_mode="MarkdownV2"
                )

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
    api_key = random.choice(GEMINI_API_KEYS)
    genai.configure(api_key=api_key)
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
