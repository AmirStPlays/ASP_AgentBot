from functools import wraps
from telebot import TeleBot, types as telebot_types
import requests
from telebot.types import Message
from md2tgmd import escape
import traceback
import asyncio
from config import conf, CHANNEL_USERNAME
import gemini

pm = conf["persian_messages"]
error_info              =       conf["error_info"]
before_generate_info    =       conf["before_generate_info"]
download_pic_notify     =       conf["download_pic_notify"]
model_1                 =       conf["model_1"]
model_2                 =       conf["model_2"]
model_3                 =       conf["model_3"]
default_image_prompt    =       conf.get("default_image_processing_prompt", "این تصویر را توصیف کن.")

user_model_preference = {}

async def _build_prompt_with_reply_context(message: Message, bot: TeleBot):
    new_prompt = message.text or message.caption or ""
    photo_file = None
    status_message = None

    if not message.reply_to_message:
        return new_prompt, None, None

    replied_msg = message.reply_to_message
    context_prefix = ""

    if replied_msg.photo:
        try:
            status_message = await bot.reply_to(message, pm["photo_proccessing_prompt"])
            file_path = await bot.get_file(replied_msg.photo[-1].file_id)
            photo_file = await bot.download_file(file_path.file_path)
            final_prompt = new_prompt if new_prompt else default_image_prompt
            return final_prompt, photo_file, status_message
        except Exception as e:
            traceback.print_exc()
            await bot.reply_to(message, f"{error_info}\nخطا در دانلود عکس کانتکست: {e}")
            return None, None, status_message

    elif replied_msg.text:
        sender = "کاربر"
        if replied_msg.from_user.is_bot:
            sender = "دستیار AI"
        
        context_prefix = (
            f"از این پیام به عنوان کانتکست برای پاسخ به درخواست جدید استفاده کن:\n"
            f"--- شروع کانتکست ---\n"
            f"({sender}): '{replied_msg.text}'\n"
            f"--- پایان کانتکست ---\n\n"
            f"درخواست جدید کاربر: "
        )
    
    final_prompt = context_prefix + new_prompt
    return final_prompt, None, None

def pre_command_checks(func):
    @wraps(func)
    async def wrapper(message: Message, bot: TeleBot, *args, **kwargs):
        user_id = message.from_user.id
        try:
            member_status = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
            if member_status.status not in ['member', 'administrator', 'creator']:
                keyboard = telebot_types.InlineKeyboardMarkup()
                join_button = telebot_types.InlineKeyboardButton(text=pm["channel_button_join"], url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")
                confirm_button = telebot_types.InlineKeyboardButton(text=pm["channel_button_confirm"], callback_data="confirm_join")
                keyboard.add(join_button, confirm_button)
                await bot.reply_to(message, pm["join_channel_prompt"], reply_markup=keyboard)
                return
        except Exception as e:
            print(f"Error checking channel membership for user {user_id} in {CHANNEL_USERNAME}: {e}")
            if "user not found" in str(e).lower():
                 keyboard = telebot_types.InlineKeyboardMarkup()
                 join_button = telebot_types.InlineKeyboardButton(text=pm["channel_button_join"], url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")
                 confirm_button = telebot_types.InlineKeyboardButton(text=pm["channel_button_confirm"], callback_data="confirm_join")
                 keyboard.add(join_button, confirm_button)
                 await bot.reply_to(message, pm["join_channel_prompt"], reply_markup=keyboard)
                 return
            elif "chat not found" in str(e).lower() or "bot is not a member" in str(e).lower() or "peer_id_invalid" in str(e).lower():
                 await bot.reply_to(message, "امکان بررسی عضویت در کانال فراهم نیست (خطای ادمین ربات).")
            else:
                await bot.reply_to(message, error_info)
            return
        return await func(message, bot, *args, **kwargs)
    return wrapper

@pre_command_checks
async def show_help(message: Message, bot: TeleBot):
    help_text = "راهنمای جامع..."
    await bot.reply_to(message, help_text, parse_mode="MarkdownV2")

@pre_command_checks
async def show_info(message: Message, bot: TeleBot):
    user_id_str = str(message.from_user.id)
    user_data = gemini.user_chats.get(user_id_str)
    
    if user_data and "stats" in user_data:
        stats = user_data["stats"]
        messages = stats.get("messages", 0)
        generated_images = stats.get("generated_images", 0)
        edited_images = stats.get("edited_images", 0)
    else:
        messages, generated_images, edited_images = 0, 0, 0

    info_text_raw = (f"📊 *آمار استفاده شما* 📊\n\n💬 *کل پیام‌ها:* {messages}\n🎨 *تصاویر ساخته شده امروز:* {generated_images}\n🖼️ *تصاویر ویرایش شده امروز:* {edited_images}\n\n__آمار تصویر روزانه ریست می‌شود.__")
    await bot.reply_to(message, escape(info_text_raw), parse_mode="MarkdownV2")

@pre_command_checks
async def start(message: Message, bot: TeleBot) -> None:
    try:
        await bot.reply_to(message , escape(pm["welcome"]), parse_mode="MarkdownV2", reply_markup=telebot_types.ReplyKeyboardRemove())
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, error_info)

@pre_command_checks
async def clear(message: Message, bot: TeleBot) -> None:
    user_id_str = str(message.from_user.id)
    history_cleared_flag = False
    if user_id_str in gemini.user_chats:
        gemini.user_chats[user_id_str]["history"] = []
        if "stats" in gemini.user_chats[user_id_str]:
            gemini.user_chats[user_id_str]["stats"]["messages"] = 0
        history_cleared_flag = True

    if user_id_str in user_model_preference:
        del user_model_preference[user_id_str]
    
    if history_cleared_flag:
        asyncio.create_task(gemini.save_user_chats())
        await bot.reply_to(message, pm["history_cleared"])
    else:
        await bot.reply_to(message, "تاریخچه‌ای برای پاک کردن وجود نداشت.")

@pre_command_checks
async def switch(message: Message, bot: TeleBot) -> None:
    if message.chat.type != "private":
        await bot.reply_to(message, pm["switch_only_private"])
        return
    user_id_str = str(message.from_user.id)
    current_prefers_model_1 = user_model_preference.get(user_id_str, True)
    if current_prefers_model_1:
        user_model_preference[user_id_str] = False
        await bot.reply_to(message, pm["switched_to_model_2"].format(model_2))
    else:
        user_model_preference[user_id_str] = True
        await bot.reply_to(message, pm["switched_to_model_1"].format(model_1))

@pre_command_checks
async def gemini_private_handler(message: Message, bot: TeleBot) -> None:
    final_prompt, photo_file, status_message = await _build_prompt_with_reply_context(message, bot)
    if final_prompt is None:
        if status_message: await bot.delete_message(status_message.chat.id, status_message.message_id)
        return
    if not final_prompt.strip(): return

    user_id_str = str(message.from_user.id)
    prefers_model_1 = user_model_preference.get(user_id_str, True)
    model_to_use = model_1 if prefers_model_1 else model_2
    
    if photo_file:
        await gemini.gemini_process_image_stream(bot, message, final_prompt, photo_file, model_to_use, status_message)
    else:
        await gemini.gemini_stream(bot, message, final_prompt, model_to_use)

@pre_command_checks
async def gemini_group_text_handler(message: Message, bot: TeleBot) -> None:
    text = message.text.strip()
    if not text.startswith('.'): return
    message.text = text[1:].strip()
    if not message.text:
        await bot.reply_to(message, pm["group_prompt_needed"])
        return
        
    final_prompt, photo_file, status_message = await _build_prompt_with_reply_context(message, bot)
    if final_prompt is None:
        if status_message: await bot.delete_message(status_message.chat.id, status_message.message_id)
        return

    user_id_str = str(message.from_user.id)
    prefers_model_1 = user_model_preference.get(user_id_str, True)
    model_to_use = model_1 if prefers_model_1 else model_2
    
    if photo_file:
        await gemini.gemini_process_image_stream(bot, message, final_prompt, photo_file, model_to_use, status_message)
    else:
        await gemini.gemini_stream(bot, message, final_prompt, model_to_use)

@pre_command_checks
async def gemini_photo_handler(message: Message, bot: TeleBot) -> None:
    caption = (message.caption or "").strip()
    is_group = message.chat.type != "private"
    if is_group:
        if not caption.startswith("."): return
        prompt_to_use = caption[1:].strip() or default_image_prompt
    else:
        if caption.lower().startswith(("/edit ", "/img ")):
            await bot.reply_to(message, escape(pm["photo_command_caption_info"]), parse_mode="MarkdownV2")
            return
        prompt_to_use = caption or default_image_prompt
    if not prompt_to_use: return

    try:
        status_message = await bot.reply_to(message, pm["photo_proccessing_prompt"])
        file_path = await bot.get_file(message.photo[-1].file_id)
        photo_file = await bot.download_file(file_path.file_path)
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, f"{error_info}\nDetails: {str(e)}")
        return

    user_id_str = str(message.from_user.id)
    model_to_use = model_1 if user_model_preference.get(user_id_str, True) else model_2
    await gemini.gemini_process_image_stream(bot, message, prompt_to_use, photo_file, model_to_use, status_message)

@pre_command_checks
async def gemini_voice_handler(message: Message, bot: TeleBot) -> None:
    user_id_str = str(message.from_user.id)
    prefers_model_1 = user_model_preference.get(user_id_str, True)

    if not prefers_model_1:
        await bot.reply_to(message, f"پردازش صدا فقط با مدل {model_1} امکان‌پذیر است. لطفا با دستور /switch مدل خود را تغییر دهید.")
        return

    try:
        file_path = await bot.get_file(message.voice.file_id)
        voice_file = await bot.download_file(file_path.file_path)
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, f"{error_info}\nخطا در دانلود فایل صوتی: {str(e)}")
        return
        
    await gemini.gemini_process_voice(bot, message, voice_file, model_1)

@pre_command_checks
async def gemini_edit_handler(message: Message, bot: TeleBot) -> None:
    if not (message.reply_to_message and message.reply_to_message.photo):
        await bot.reply_to(message, pm["photo_edit_prompt"])
        return
    
    photo_message = message.reply_to_message
    command_text = message.text or ""
    try:
        if not command_text.lower().startswith("/edit "):
             await bot.reply_to(message, escape("..."), parse_mode="MarkdownV2")
             return
        text_prompt = command_text.strip().split(maxsplit=1)[1].strip()
    except IndexError:
        await bot.reply_to(message, escape("..."), parse_mode="MarkdownV2")
        return
    if not text_prompt:
        await bot.reply_to(message, escape("..."), parse_mode="MarkdownV2")
        return

    try:
        file_path = await bot.get_file(photo_message.photo[-1].file_id)
        photo_file = await bot.download_file(file_path.file_path)
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, f"{error_info}\nDetails: {str(e)}")
        return
    await gemini.gemini_edit(bot, message, text_prompt, photo_file)

@pre_command_checks
async def draw_handler(message: Message, bot: TeleBot) -> None:
    try:
        m = message.text.strip().split(maxsplit=1)[1].strip()
    except IndexError:
        await bot.reply_to(message, escape(pm["add_prompt_img"]), parse_mode="MarkdownV2")
        return
    if not m:
        await bot.reply_to(message, escape(pm["add_prompt_img"]), parse_mode="MarkdownV2")
        return

    drawing_msg = await bot.reply_to(message, pm["drawing_in_progress"])
    try:
        await gemini.gemini_draw(bot, message, m)
    except Exception as e:
        traceback.print_exc()
        await bot.edit_message_text(f"{error_info}\n<code>{str(e)}</code>", chat_id=drawing_msg.chat.id, message_id=drawing_msg.message_id, parse_mode="HTML")
        return
    try:
        await bot.delete_message(chat_id=drawing_msg.chat.id, message_id=drawing_msg.message_id)
    except Exception: pass

async def handle_callback_query(call: telebot_types.CallbackQuery, bot: TeleBot):
    user_id = call.from_user.id
    if call.data == "confirm_join":
        try:
            await bot.answer_callback_query(call.id, "در حال بررسی عضویت...")
            member_status = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
            if member_status.status in ['member', 'administrator', 'creator']:
                await bot.edit_message_text(pm["membership_confirmed"], call.message.chat.id, call.message.message_id, reply_markup=None)
                await bot.send_message(call.message.chat.id, "اکنون می‌توانید از ربات استفاده کنید.")
            else:
                await bot.edit_message_text(pm["membership_not_confirmed"], call.message.chat.id, call.message.message_id, reply_markup=call.message.reply_markup)
        except Exception as e:
            traceback.print_exc()
            await bot.answer_callback_query(call.id, "خطا در پردازش.")
            if "user not found" in str(e).lower():
                await bot.edit_message_text(pm["membership_not_confirmed"], call.message.chat.id, call.message.message_id, reply_markup=call.message.reply_markup)
            else:
                await bot.edit_message_text(error_info, call.message.chat.id, call.message.message_id, reply_markup=None)

def clear_updates(tg_token):
    url = f"https://api.telegram.org/bot{tg_token}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("ok") and (updates := data.get("result")):
            last_update_id = updates[-1]["update_id"]
            requests.get(f"{url}?offset={last_update_id + 1}", timeout=10)
            print(f"✅ {len(updates)} pending updates cleared.")
        else:
            print("📭 No pending updates to clear.")
    except requests.RequestException as e:
        print(f"❌ Network error while clearing updates: {e}")
