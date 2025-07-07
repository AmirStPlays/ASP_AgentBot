from functools import wraps
from telebot import TeleBot, types as telebot_types
from telebot.types import ReplyKeyboardRemove
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
default_image_prompt    =       conf.get("default_image_prompt", "این تصویر را توصیف کن.")

user_model_preference = {}

async def _build_prompt_with_reply_context(message: Message, bot: TeleBot):
    """
    Builds a prompt considering the replied message context.
    Handles replies to text, photos, and documents.
    Returns: (final_prompt, file_info, status_message)
    - file_info is a dict {'data': bytes, 'mime_type': str} or None.
    """
    new_prompt = message.text or message.caption or ""
    file_info = None
    status_message = None

    if not message.reply_to_message:
        return new_prompt, None, None

    replied_msg = message.reply_to_message
    context_prefix = ""

    # Check for reply to a photo
    if replied_msg.photo:
        try:
            status_message = await bot.reply_to(message, pm["photo_proccessing_prompt"])
            file_path = await bot.get_file(replied_msg.photo[-1].file_id)
            photo_bytes = await bot.download_file(file_path.file_path)
            # Use default prompt if the reply text is empty
            final_prompt = new_prompt if new_prompt.strip() else default_image_prompt
            file_info = {'data': photo_bytes, 'mime_type': 'image/jpeg'}
            return final_prompt, file_info, status_message
        except Exception as e:
            traceback.print_exc()
            err_msg = f"{error_info}\nخطا در دانلود عکس کانتکست: {e}"
            if status_message:
                await bot.edit_message_text(err_msg, chat_id=status_message.chat.id, message_id=status_message.message_id)
            else:
                await bot.reply_to(message, err_msg)
            return None, None, status_message

    # Check for reply to a document
    elif replied_msg.document:
        try:
            status_message = await bot.reply_to(message, "در حال دانلود فایل الصاق شده... 📥")
            file_path = await bot.get_file(replied_msg.document.file_id)
            if file_path.file_size > 20 * 1024 * 1024:
                await bot.edit_message_text("فایل الصاق شده بزرگتر از 20MB است و قابل پردازش نیست.", chat_id=status_message.chat.id, message_id=status_message.message_id)
                return None, None, status_message
            
            doc_bytes = await bot.download_file(file_path.file_path)
            mime_type = replied_msg.document.mime_type or 'application/octet-stream'
            # Use a default prompt if the reply text is empty
            final_prompt = new_prompt if new_prompt.strip() else pm["default_file_prompt"]
            file_info = {'data': doc_bytes, 'mime_type': mime_type}
            return final_prompt, file_info, status_message
        except Exception as e:
            traceback.print_exc()
            err_msg = f"{error_info}\nخطا در دانلود فایل کانتکست: {e}"
            if status_message:
                await bot.edit_message_text(err_msg, chat_id=status_message.chat.id, message_id=status_message.message_id)
            else:
                await bot.reply_to(message, err_msg)
            return None, None, status_message

    # Handle reply to a text message
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


def mono(text: str) -> str:
    return f"`{escape(text)}`"

async def show_help(message: Message, bot: TeleBot):
    title = "راهنمای جامع استفاده از بات"
    
    img_description_raw = """برای تولید عکس، از دستور /img استفاده کرده و در ادامه، توضیح تصویر مورد نظر خود را بنویسید.
مثال: `/img یک گربه سفید در فضا`
این عملیات ممکن است کمی زمان‌بر باشد."""

    edit_description_raw = """برای ویرایش یک عکس، ابتدا روی پیام حاوی عکس ریپلای کنید. سپس دستور /edit را نوشته و در ادامه، توضیح تغییری که می‌خواهید اعمال شود را بنویسید.
مثال: `/edit رنگ ماشین را قرمز کن`"""

    file_description_raw = """برای پردازش فایل (مانند خلاصه‌سازی PDF، توضیح کد، یا پرسش از محتوای فایل متنی) می‌توانید به دو روش عمل کنید:
۱. ارسال مستقیم فایل: فایل خود را (با حجم کمتر از ۲۰ مگابایت) ارسال کرده و در قسمت کپشن (توضیحات) فایل، سوال یا دستور خود را بنویسید.
۲. ریپلای روی فایل: روی فایلی که قبلاً در چت ارسال شده، ریپلای کرده و سوال خود را به عنوان متن ریپلای بنویسید.
اگر کپشن یا متن ریپلای خالی باشد، ربات یک تحلیل کلی از فایل ارائه می‌دهد."""
    
    supported_formats_raw = """- *کدنویسی:* `PY`, `ipynb`, `java`, `c`, `cpp`, `cs`, `h`, `hpp`, `swift`, `js`, `ts`, `html`, `css`, `php`, `rb`, `go`, `rs`, `kt`, `kts`
- *تصویر:* `PNG`, `JPEG`, `WEBP`, `HEIC`, `HEIF`
- *صدا:* `MP3`, `WAV`, `MIDI`, `OGG`, `AAC`, `FLAC`
- *ویدیو:* `MP4`, `MPEG`, `MOV`, `AVI`, `FLV`, `WMV`, `WEBM`, `3GP` (ربات فریم‌های کلیدی را تحلیل می‌کند)
- *متن ساده:* `TXT`, `RTF`, `CSV`, `TSV`, `PDF`, `DOCX`, `PPTX`, `EPUB`"""

    switch_description_raw = "با استفاده از این دستور، می‌توانید بین مدل‌های مختلف پردازش متن جابجا شوید. این دستور فقط در چت خصوصی کار می‌کند."
    
    group_text_raw = "در گروه‌ها، برای اینکه ربات به پیام متنی شما پاسخ دهد، پیام خود را با `.` شروع کنید. مثال: `.سلام خوبی؟`"
    
    group_media_raw = """در گروه‌ها، برای پردازش عکس یا فایل، حتماً باید کپشن یا متن ریپلای خود را با `.` شروع کنید.
مثال برای عکس: `.این عکس را توصیف کن`
مثال برای فایل: `.این کد پایتون چه کاری انجام می‌دهد؟`"""

    footer_raw = "در صورت داشتن هرگونه ابهام یا مشکل، حتماً به ادمین اطلاع دهید."
    admin_id_raw = "آیدی ادمین: @AmirStPlays"

    help_text = f"*{escape(title)}*\n\n"

    help_text += f"{mono('/img')} {escape('(تولید تصویر)')}\n"
    help_text += f"```\n{escape(img_description_raw)}\n```\n\n"

    help_text += f"{mono('/edit')} {escape('(ویرایش تصویر با ریپلای)')}\n"
    help_text += f"```\n{escape(edit_description_raw)}\n```\n\n"
    
    help_text += f"{mono('فایل')} {escape('(پردازش PDF، کد و غیره)')}\n"
    help_text += f"```\n{escape(file_description_raw)}\n```\n"
    help_text += f"*{escape('فرمت‌های فایل پشتیبانی شده:')}*\n"
    help_text += f"```\n{escape(supported_formats_raw)}\n```\n\n"

    help_text += f"{mono('/switch')} {escape('(تغییر مدل متن در PV)')}\n"
    help_text += f"```\n{escape(switch_description_raw)}\n```\n\n"

    help_text += f"*{escape('نکات استفاده در گروه')}*\n"
    help_text += f"{mono('.')} {escape('(فراخوانی ربات برای متن)')}\n"
    help_text += f"```\n{escape(group_text_raw)}\n```\n"
    help_text += f"{mono('.')} {escape('(فراخوانی ربات برای عکس و فایل)')}\n"
    help_text += f"```\n{escape(group_media_raw)}\n```\n\n"

    help_text += f"*{escape('پشتیبانی')}*\n"
    help_text += f"{escape(footer_raw)}\n"
    help_text += f"{escape(admin_id_raw)}"

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


async def start(message: Message, bot: TeleBot) -> None:
    try:
        user = message.from_user
        first_name = user.first_name or "کاربر"

        text = f"سلام {first_name}\nبه ایجنت ASP خوش اومدی.\n{pm['welcome']}"
        escaped_text = escape(text)

        await bot.reply_to(
            message,
            escaped_text,
            parse_mode="MarkdownV2",
            reply_markup=ReplyKeyboardRemove()
        )
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
    final_prompt, file_info, status_message = await _build_prompt_with_reply_context(message, bot)
    if final_prompt is None and file_info is None:
        if status_message: await bot.delete_message(status_message.chat.id, status_message.message_id)
        return
    
    # اگر فایلی ضمیمه باشد، یک پرامپت پیش‌فرض به آن اختصاص داده می‌شود،
    # بنابراین این شرط فقط پیام‌های متنی خالی را متوقف می‌کند.
    if not final_prompt.strip(): return

    user_id_str = str(message.from_user.id)
    model_to_use = model_1 if user_model_preference.get(user_id_str, True) else model_2
    
    if file_info:
        # اصلاح: بر اساس نوع فایل (mime_type) بین پردازش عکس و فایل تمایز قائل شو
        if 'image' in file_info['mime_type']:
            await gemini.gemini_process_image_stream(bot, message, final_prompt, file_info['data'], model_to_use, status_message)
        else:
            await gemini.gemini_process_file_stream(bot, message, final_prompt, file_info, model_to_use, status_message)
    else:
        await gemini.gemini_stream(bot, message, final_prompt, model_to_use)

@pre_command_checks
async def gemini_group_text_handler(message: Message, bot: TeleBot) -> None:
    text = message.text.strip()
    if not text.startswith('.'): return
    message.text = text[1:].strip()
    if not message.text and not message.reply_to_message:
        await bot.reply_to(message, pm["group_prompt_needed"])
        return
        
    final_prompt, file_info, status_message = await _build_prompt_with_reply_context(message, bot)
    
    if final_prompt is None and file_info is None:
        if status_message: await bot.delete_message(status_message.chat.id, status_message.message_id)
        return

    user_id_str = str(message.from_user.id)
    model_to_use = model_1 if user_model_preference.get(user_id_str, True) else model_2
    
    if file_info:
        # اصلاح: بر اساس نوع فایل (mime_type) بین پردازش عکس و فایل تمایز قائل شو
        if 'image' in file_info['mime_type']:
            await gemini.gemini_process_image_stream(bot, message, final_prompt, file_info['data'], model_to_use, status_message)
        else:
            await gemini.gemini_process_file_stream(bot, message, final_prompt, file_info, model_to_use, status_message)
    else:
        if not final_prompt: # در صورتی که ریپلای با متن خالی باشد دوباره چک کن
             await bot.reply_to(message, pm["group_prompt_needed"])
             return
        await gemini.gemini_stream(bot, message, final_prompt, model_to_use)

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
async def gemini_document_handler(message: Message, bot: TeleBot) -> None:
 
    caption = (message.caption or "").strip()
    is_group = message.chat.type != "private"
    
    if is_group and not caption.startswith("."): return

    prompt_to_use = (caption[1:].strip() if is_group else caption) or pm["default_file_prompt"]

    try:
        status_message = await bot.reply_to(message, "در حال دانلود و آماده‌سازی فایل... 📥")
        file_info_tg = await bot.get_file(message.document.file_id)
        
        if file_info_tg.file_size > 20 * 1024 * 1024:
            await bot.edit_message_text("حجم فایل بیشتر از 20 مگابایت است.", chat_id=status_message.chat.id, message_id=status_message.message_id)
            return

        file_bytes = await bot.download_file(file_info_tg.file_path)
        mime_type = message.document.mime_type or 'application/octet-stream'
        file_info = {'data': file_bytes, 'mime_type': mime_type}

    except Exception as e:
        traceback.print_exc()
        await bot.edit_message_text(f"{error_info}\nخطا در دانلود فایل: {str(e)}", chat_id=status_message.chat.id, message_id=status_message.message_id)
        return

    user_id_str = str(message.from_user.id)
    model_to_use = model_1 if user_model_preference.get(user_id_str, True) else model_2
    await gemini.gemini_process_file_stream(bot, message, prompt_to_use, file_info, model_to_use, status_message)

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
