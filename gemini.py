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
import json
import os
from dotenv import load_dotenv

user_chats = {}  # user_id -> chat
USER_CHATS_FILE = "user_chats_data.json" 
load_dotenv()

async def load_user_chats_async():
    global user_chats
    user_chats = {}
    print("Initialized in-memory user_chats dictionary.")

    if os.path.exists(USER_CHATS_FILE):
        try:
            with open(USER_CHATS_FILE, "r") as f:
                pass
        except Exception as e:
            print(f"Error loading user chats from file (not implemented for Chat objects): {e}")
            user_chats = {}
async def save_user_chats():

    print("save_user_chats called. (Note: True persistence of genai.Chat objects is not implemented here).")

    try:
        with open(USER_CHATS_FILE, "w") as f:
            pass
    except Exception as e:
        print(f"Error saving user chats to file (not implemented for Chat objects): {e}")



model_1 = conf["model_1"]
model_2 = conf["model_2"]
model_3 = conf["model_3"]
error_info = conf["error_info"]
before_generate_info = conf["before_generate_info"]
download_pic_notify = conf["download_pic_notify"]
default_system_prompt = conf.get("default_system_prompt", "").strip()

search_tool = {'google_search': {}}

GEMINI_API_KEYS = os.getenv("gemini_api_keys", "").split(",") # ---> type(GEMINI_API_KEYS) = list

def get_random_client():
    api_key = random.choice(GEMINI_API_KEYS)
    return genai.Client(api_key=api_key)


async def gemini_stream(bot: TeleBot, message: Message, m: str, model_type: str):
    client = get_random_client()
    sent_message = None
    user_id_str = str(message.from_user.id)

    try:
        sent_message = await bot.reply_to(message, before_generate_info)

        chat = user_chats.get(user_id_str)

        if not chat:
            chat = client.aio.chats.create(model=model_type, config={'tools': [search_tool]})

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
                            escape(full_response + "✍️"),
                            chat_id=sent_message.chat.id,
                            message_id=sent_message.message_id,
                            parse_mode="MarkdownV2"
                        )
                    except Exception as e:
                        if "parse markdown" in str(e).lower():
                            try:
                                await bot.edit_message_text(
                                    full_response + "✍️",
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
                if "parse markdown" in str(e).lower() or "message is not modified" in str(e).lower():
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


async def gemini_draw(bot: TeleBot, message: Message, m: str):
    client = get_random_client()
    image_generation_chat = client.aio.chats.create(model=model_3, config=generation_config)

    try:
        # Send the image prompt 'm' using the dedicated image generation chat session
        response = await image_generation_chat.send_message(m)
    except Exception as e:
        traceback.print_exc()
        await bot.send_message(message.chat.id, f"{error_info}\nخطا در هنگام تولید تصویر: {str(e)}")
        return

    if not (response and hasattr(response, 'candidates') and response.candidates and \
       hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts')):
        await bot.send_message(message.chat.id, f"{error_info}\nپاسخ معتبری هنگام ترسیم تصویر دریافت نشد.")
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


async def gemini_edit(bot: TeleBot, message: Message, m: str, photo_file: bytes):
    image = Image.open(io.BytesIO(photo_file))
    client = get_random_client()
    user_id_str = str(message.from_user.id)
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
