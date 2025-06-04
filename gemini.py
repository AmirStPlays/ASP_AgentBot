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

gemini_draw_dict = {}
gemini_chat_dict = {}
gemini_pro_chat_dict = {}
default_model_dict = {}

model_1                 =       conf["model_1"]
model_2                 =       conf["model_2"]
model_3                 =       conf["model_3"]
error_info              =       conf["error_info"]
before_generate_info    =       conf["before_generate_info"]
download_pic_notify     =       conf["download_pic_notify"]
default_system_prompt   =       conf.get("default_system_prompt", "").strip()


search_tool = {'google_search': {}}

# Ensure API key is handled securely, e.g., via environment variables or a secure config management system
# For demonstration, using the placeholder directly from the prompt.
# It's highly recommended to move this to a more secure location.
GEMINI_API_KEYS = [
    "AIzaSyAc2PYevmpUo_3PW5PMJpu491eg9EaqWqY",
    "AIzaSyCrSk31t3oLsK4uiDcZwo20cDGkxa8IuVg",
    "AIzaSyAE6JIR_tjXSWbXRTWvd1POKIOMkTzf5O8",
    "AIzaSyCf5kmryeqRICx0zZLhU6o40O9cbQCCjfQ"
]

def get_random_client():
    api_key = random.choice(GEMINI_API_KEYS)
    return genai.Client(api_key=api_key)
    



async def gemini_stream(bot:TeleBot, message:Message, m:str, model_type:str):
    client = get_random_client()
    sent_message = None
    try:
        sent_message = await bot.reply_to(message, before_generate_info) # Using consistent message

        chat = None
        user_id_str = str(message.from_user.id)

        if model_type == model_1:
            chat_dict = gemini_chat_dict
        else:
            chat_dict = gemini_pro_chat_dict

        if user_id_str not in chat_dict:
            chat = client.aio.chats.create(model=model_type, config={'tools': [search_tool]})
            
            # Send the default system prompt if it exists for new chats
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
                    # This message sets the context; its response is not streamed to the user.
                    await chat.send_message(full_prompt)
                    # The chat history will now contain the system prompt and the model's (hidden) ack/response.
                except Exception as e_default_prompt:
                    print(f"Warning: Could not send default system prompt for user {user_id_str}: {e_default_prompt}")
            
            chat_dict[user_id_str] = chat
        else:
            chat = chat_dict[user_id_str]

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
                            escape(full_response + "✍️"), # Add typing indicator during stream
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

        # Final update without the typing indicator
        try:
            await bot.edit_message_text(
                escape(full_response),
                chat_id=sent_message.chat.id,
                message_id=sent_message.message_id,
                parse_mode="MarkdownV2"
            )
        except Exception as e:
            try:
                if "parse markdown" in str(e).lower() or "message is not modified" in str(e).lower() : # also handle not modified if it was the final state
                    await bot.edit_message_text(
                        full_response,
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id
                    )
                else:
                    raise # Re-raise other errors for the main handler
            except Exception as final_e: # Catch error during non-markdown final edit
                print(f"Error in final message edit (non-Markdown): {final_e}")
                # If even plain text edit fails, it might be due to message content.
                # As a last resort, if full_response is empty or problematic, send a generic message or log.
                if not full_response.strip():
                     await bot.edit_message_text(
                        "پاسخ خالی دریافت شد.", # Or some other indicator
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
                await bot.reply_to(message, error_message_detail) # Fallback to reply
        else:
            await bot.reply_to(message, error_message_detail)

async def gemini_edit(bot: TeleBot, message: Message, m: str, photo_file: bytes):
    image = Image.open(io.BytesIO(photo_file))
    client = get_random_client()
    sent_progress_message = None
    try:
        # It's good practice to notify the user that processing has started,
        # especially for potentially long operations like image processing.
        sent_progress_message = await bot.reply_to(message, "در حال پردازش تصویر با دستور شما... 🖼️")

        response = await client.aio.models.generate_content(
            model=model_3, # Ensure model_3 is appropriate for text + image input and text/image output
            contents=[m, image], # Prompt 'm' comes first, then the image
            config=generation_config
        )

        # Delete the progress message once we have a response
        if sent_progress_message:
            await bot.delete_message(sent_progress_message.chat.id, sent_progress_message.message_id)

        if not (response and hasattr(response, 'candidates') and response.candidates and \
           hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts')):
            await bot.send_message(message.chat.id, f"{error_info}\nپاسخ معتبری از سرویس دریافت نشد.")
            return

        # Process parts
        processed_parts = False
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text is not None:
                text_response = part.text
                # Send text in chunks if too long
                while len(text_response) > 4000:
                    await bot.send_message(message.chat.id, escape(text_response[:4000]), parse_mode="MarkdownV2")
                    text_response = text_response[4000:]
                if text_response:
                    await bot.send_message(message.chat.id, escape(text_response), parse_mode="MarkdownV2")
                processed_parts = True
            elif hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
                photo = part.inline_data.data
                await bot.send_photo(message.chat.id, photo, caption=escape("نتیجه ویرایش تصویر:") if not m.startswith("تصویر را توصیف کن") else escape(m)) # Add caption to output image
                processed_parts = True
        
        if not processed_parts:
            await bot.send_message(message.chat.id, "پاسخی از مدل دریافت نشد یا محتوای قابل نمایشی وجود نداشت.")


    except Exception as e:
        traceback.print_exc()
        error_message_detail = f"{error_info}\nجزئیات خطا: {str(e)}"
        if sent_progress_message: # If progress message was sent, try to edit it to show error
            try:
                await bot.edit_message_text(error_message_detail, chat_id=sent_progress_message.chat.id, message_id=sent_progress_message.message_id)
            except: # If editing fails, send a new message
                await bot.send_message(message.chat.id, error_message_detail)
        else: # If no progress message, send error as a new message
            await bot.send_message(message.chat.id, error_message_detail)


async def gemini_draw(bot:TeleBot, message:Message, m:str):
    # gemini_draw_dict is used to maintain chat history for image generation model if it supports multi-turn.
    # If model_3 for image generation is stateless per call for drawing, this dict might not be strictly necessary for history,
    # but can be kept for consistency or future models that might benefit from it.
    chat_dict = gemini_draw_dict 
    client = get_random_client()
    user_id_str = str(message.from_user.id)

    if user_id_str not in chat_dict:
        # For image generation, a chat session might not be needed if each call is independent.
        # However, if the API benefits from context or if we want to use specific chat features:
        chat = client.aio.chats.create(
            model=model_3, # Uses model_3 for image generation
            config=generation_config, # Contains safety settings
        )
        chat_dict[user_id_str] = chat
    else:
        chat = chat_dict[user_id_str]

    try:
        # The prompt 'm' is sent to the model.
        # For some image generation models, the response might directly be image data or include it.
        response = await chat.send_message(m) 
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
            # Sometimes image models return text, e.g., acknowledgments or errors.
            text = part.text
            while len(text) > 4000: # Split long messages
                await bot.send_message(message.chat.id, escape(text[:4000]), parse_mode="MarkdownV2")
                text = text[4000:]
            if text:
                await bot.send_message(message.chat.id, escape(text), parse_mode="MarkdownV2")
            processed_parts = True # Consider text part as processed
        elif hasattr(part, 'inline_data') and part.inline_data is not None and hasattr(part.inline_data, 'data'):
            photo_data = part.inline_data.data
            await bot.send_photo(message.chat.id, photo_data, caption=escape(f"تصویر تولید شده برای: {m[:100]}"))
            processed_parts = True
            
    if not processed_parts:
        await bot.send_message(message.chat.id, "تصویری تولید نشد یا محتوای قابل نمایشی وجود نداشت.")
