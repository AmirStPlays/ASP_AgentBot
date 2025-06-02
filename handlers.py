import json
import os
from functools import wraps
from telebot import TeleBot, types as telebot_types
from telebot.types import Message
from md2tgmd import escape
import traceback
from config import conf, USER_AUTH_FILE, CHANNEL_USERNAME
import gemini

# بارگذاری پیام‌های فارسی
pm = conf["persian_messages"]
error_info              =       conf["error_info"]
before_generate_info    =       conf["before_generate_info"]
download_pic_notify     =       conf["download_pic_notify"]
model_1                 =       conf["model_1"]
model_2                 =       conf["model_2"]
model_3                 =       conf["model_3"]
default_image_prompt    =       conf.get("default_image_processing_prompt", "این تصویر را توصیف کن.")


gemini_chat_dict        = gemini.gemini_chat_dict
gemini_pro_chat_dict    = gemini.gemini_pro_chat_dict
default_model_dict      = gemini.default_model_dict


# --- مدیریت فایل کاربران ---
def load_authorized_users():
    if not os.path.exists(USER_AUTH_FILE):
        return set()
    try:
        with open(USER_AUTH_FILE, "r") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError):
        return set()

def save_authorized_user(user_id):
    authorized_users = load_authorized_users()
    authorized_users.add(user_id)
    with open(USER_AUTH_FILE, "w") as f:
        json.dump(list(authorized_users), f)

authorized_user_ids = load_authorized_users()

# --- دکوریتور برای بررسی‌ها ---
def pre_command_checks(func):
    @wraps(func)
    async def wrapper(message: Message, bot: TeleBot, *args, **kwargs):
        user_id = message.from_user.id
        
        try:
            member_status = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
            if member_status.status not in ['member', 'administrator', 'creator']:
                keyboard = telebot_types.InlineKeyboardMarkup()
                join_button = telebot_types.InlineKeyboardButton(
                    text=pm["channel_button_join"],
                    url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
                )
                confirm_button = telebot_types.InlineKeyboardButton(
                    text=pm["channel_button_confirm"],
                    callback_data="confirm_join"
                )
                keyboard.add(join_button)
                keyboard.add(confirm_button)
                await bot.reply_to(message, pm["join_channel_prompt"], reply_markup=keyboard)
                return
        except Exception as e:
            print(f"Error checking channel membership for user {user_id} in {CHANNEL_USERNAME}: {e}")
            if "user not found" in str(e).lower():
                 await bot.reply_to(message, pm["join_channel_prompt"]) 
                 return
            elif "chat not found" in str(e).lower() or "bot is not a member" in str(e).lower() or "peer_id_invalid" in str(e).lower():
                 await bot.reply_to(message, "امکان بررسی عضویت در کانال فراهم نیست (خطای ادمین ربات). لطفاً با ادمین تماس بگیرید.")
            else:
                await bot.reply_to(message, error_info)
            return

        if user_id not in authorized_user_ids:
            keyboard = telebot_types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True, one_time_keyboard=True)
            phone_button = telebot_types.KeyboardButton(
                text=pm["phone_button_share"],
                request_contact=True
            )
            keyboard.add(phone_button)
            await bot.reply_to(message, pm["share_phone_prompt"], reply_markup=keyboard)
            return

        return await func(message, bot, *args, **kwargs)
    return wrapper

async def show_help(message: Message, bot: TeleBot):
    # بخش‌های متنی که نیاز به escape دارند
    title = "راهنمای جامع استفاده از بات"
    img_description_raw = """برای تولید عکس توسط ربات ابتدا این دستور را از طریق منوی پایین چپ نگه داشته تا عبارت آن بر روی کیبورد نمایان بشه.
پس از این متن خودتون رو جلوی دستور برای ساخت عکس بنویسید.
این رو هم بدونید که ممکنه این عملیات زمانبر باشه """
    edit_description_raw = """برای اینکار یا یک عکس از گالری خود و یا یک عکس از تاریخچه چتتون انتخاب کنید(روی پیامش ریپلای بزنید)
بعد از اینکار مثل دستور قبل عبارت /edit را پشت کپشن یا پیام ریپلای زده شده خودتون بنویسین و ادیتی که میخواین روی عکس اعمال بشه رو تایپ کنید.
این عملیات هم میتونه کمی زمانبر باشه."""
    switch_description_raw = "با استفاده از این دستور میتونین مدل پردازش متن رو عوض کنید "
    help_description_raw = "برای دیدن راهنمای استفاده از بات از این دستور استفاده کنید "
    footer_raw = "در صورت داشتن هرگونه ابهام یا مشکل در ربات حتما به من بگید تا درستش کنم"
    admin_id_raw = "اینم آیدیم: @AmirStPlays"

    # Escape کردن بخش‌های متنی
    help_text = f"**{escape(title)}**\n\n"

    help_text += escape("1. دستور /img") + "\n"
    help_text += "```\n" + escape(img_description_raw) + "\n```\n\n" # متن داخل بلاک کد هم escape شود برای اطمینان

    help_text += escape("2. دستور /edit") + "\n"
    help_text += "```\n" + escape(edit_description_raw) + "\n```\n\n"

    help_text += escape("3. دستور /switch") + "\n"
    help_text += "```\n" + escape(switch_description_raw) + "\n```\n\n"

    help_text += escape("دستور /help") + "\n" # یا "4. دستور /help"
    help_text += "```\n" + escape(help_description_raw) + "\n```\n\n"

    help_text += escape(footer_raw) + "\n"
    help_text += escape(admin_id_raw)
        
    await bot.reply_to(message, help_text, parse_mode="MarkdownV2")

# --- کنترلگرهای اصلی ---
@pre_command_checks
async def start(message: Message, bot: TeleBot) -> None:
    try:
        await bot.reply_to(message , escape(pm["welcome"]), parse_mode="MarkdownV2")
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, error_info)

@pre_command_checks
async def gemini_stream_handler(message: Message, bot: TeleBot) -> None:
    try:
        m = message.text.strip().split(maxsplit=1)[1].strip()
        if not m:
            await bot.reply_to(message, escape(pm["add_prompt_gemini"]), parse_mode="MarkdownV2")
            return
    except IndexError:
        await bot.reply_to(message, escape(pm["add_prompt_gemini"]), parse_mode="MarkdownV2")
        return
    await gemini.gemini_stream(bot, message, m, model_1)

@pre_command_checks
async def gemini_pro_stream_handler(message: Message, bot: TeleBot) -> None:
    try:
        m = message.text.strip().split(maxsplit=1)[1].strip()
        if not m:
            await bot.reply_to(message, escape(pm["add_prompt_gemini_pro"]), parse_mode="MarkdownV2")
            return
    except IndexError:
        await bot.reply_to(message, escape(pm["add_prompt_gemini_pro"]), parse_mode="MarkdownV2")
        return
    await gemini.gemini_stream(bot, message, m, model_2)

@pre_command_checks
async def clear(message: Message, bot: TeleBot) -> None:
    user_id_str = str(message.from_user.id)
    if user_id_str in gemini.gemini_chat_dict:
        del gemini.gemini_chat_dict[user_id_str]
    if user_id_str in gemini.gemini_pro_chat_dict:
        del gemini.gemini_pro_chat_dict[user_id_str]
    if user_id_str in gemini.gemini_draw_dict: # Also clear draw history if any
        del gemini.gemini_draw_dict[user_id_str]
    await bot.reply_to(message, pm["history_cleared"])

@pre_command_checks
async def switch(message: Message, bot: TeleBot) -> None:
    if message.chat.type != "private":
        await bot.reply_to( message , pm["switch_only_private"])
        return

    user_id_str = str(message.from_user.id)
    if user_id_str not in gemini.default_model_dict or gemini.default_model_dict[user_id_str] is False:
        gemini.default_model_dict[user_id_str] = True
        await bot.reply_to( message , pm["switched_to_model_1"].format(model_1))
    else:
        gemini.default_model_dict[user_id_str] = False
        await bot.reply_to( message , pm["switched_to_model_2"].format(model_2))


@pre_command_checks
async def gemini_private_handler(message: Message, bot: TeleBot) -> None:
    m = message.text.strip()
    if not m:
        return
        
    user_id_str = str(message.from_user.id)
    if user_id_str not in gemini.default_model_dict:
        gemini.default_model_dict[user_id_str] = True 

    if gemini.default_model_dict[user_id_str]:
        await gemini.gemini_stream(bot,message,m,model_1)
    else:
        await gemini.gemini_stream(bot,message,m,model_2)

@pre_command_checks
async def gemini_photo_handler(message: Message, bot: TeleBot) -> None:
    caption = (message.caption or "").strip()
    prompt_to_use = ""

    if caption.lower().startswith("/edit ") or caption.lower().startswith("/img "):
        # If caption starts with /edit or /img, inform user about correct usage and do not process.
        # This handler is for general image understanding, not for commands in captions.
        await bot.reply_to(message, escape(pm["photo_command_caption_info"]), parse_mode="MarkdownV2")
        return
    elif caption: # If there's a caption (and it's not /edit or /img)
        prompt_to_use = caption
    else: # No caption, or caption was a command (already handled)
        prompt_to_use = default_image_prompt # Use the default image processing prompt

    if not prompt_to_use: # Should not happen if logic is correct, but as a safeguard
        await bot.reply_to(message, escape(pm["photo_caption_prompt"]), parse_mode="MarkdownV2")
        return

    try:
        await bot.send_chat_action(message.chat.id, 'typing')
        # await bot.send_message(message.chat.id, download_pic_notify) # Notify about download
        
        file_path = await bot.get_file(message.photo[-1].file_id)
        photo_file = await bot.download_file(file_path.file_path)

    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, f"{error_info}\nDetails: {str(e)}")
        return
    
    # Call gemini_edit (which uses model_3) for general photo processing
    await gemini.gemini_edit(bot, message, prompt_to_use, photo_file)


@pre_command_checks
async def gemini_edit_handler(message: Message, bot: TeleBot) -> None:
    original_message = message
    photo_message = None
    text_prompt_from_command = ""

    if original_message.reply_to_message and original_message.reply_to_message.photo:
        photo_message = original_message.reply_to_message
        command_text = original_message.text or ""
        try:
            # Ensure it's the /edit command and not something else being replied to
            if not command_text.lower().startswith("/edit "):
                 await bot.reply_to(original_message, escape("برای ویرایش عکس، لطفاً با دستور /edit و توضیح ویرایش روی عکس ریپلای کنید."), parse_mode="MarkdownV2")
                 return
            text_prompt_from_command = command_text.strip().split(maxsplit=1)[1].strip()
        except IndexError:
            await bot.reply_to(original_message, escape("لطفا توضیح ویرایش را بعد از دستور /edit بنویسید."), parse_mode="MarkdownV2")
            return
    else:
        await bot.reply_to(original_message, pm["photo_edit_prompt"])
        return

    if not text_prompt_from_command: # Should be caught by IndexError, but good to double check
        await bot.reply_to(original_message, escape("لطفا توضیح ویرایش را بعد از دستور /edit بنویسید."), parse_mode="MarkdownV2")
        return
        
    if not photo_message or not photo_message.photo: # Should not happen if logic above is correct
        await bot.reply_to(original_message, pm["photo_edit_prompt"])
        return

    try:
        await bot.send_chat_action(original_message.chat.id, 'typing')
        # await bot.send_message(original_message.chat.id, download_pic_notify) # Notify about download
        file_path = await bot.get_file(photo_message.photo[-1].file_id)
        photo_file = await bot.download_file(file_path.file_path)
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(original_message, f"{error_info}\nDetails: {str(e)}")
        return
    
    # Call gemini_edit, which uses model_3, with the specific edit prompt
    await gemini.gemini_edit(bot, original_message, text_prompt_from_command, photo_file)


@pre_command_checks
async def draw_handler(message: Message, bot: TeleBot) -> None: # Handles /img now
    try:
        m = message.text.strip().split(maxsplit=1)[1].strip()
        if not m:
            await bot.reply_to(message, escape(pm["add_prompt_img"]), parse_mode="MarkdownV2")
            return
    except IndexError:
        await bot.reply_to(message, escape(pm["add_prompt_img"]), parse_mode="MarkdownV2")
        return
    
    drawing_msg = await bot.reply_to(message, pm["drawing_in_progress"])
    try:
        await gemini.gemini_draw(bot, message, m) 
    except Exception as e:
        traceback.print_exc()
        if drawing_msg: 
             await bot.edit_message_text(f"{error_info}\n<code>{str(e)}</code>", chat_id=drawing_msg.chat.id, message_id=drawing_msg.message_id, parse_mode="HTML")
        else: 
            await bot.reply_to(message, f"{error_info}\n<code>{str(e)}</code>" , parse_mode="HTML")
        return 

    try:
        if drawing_msg: 
            await bot.delete_message(chat_id=drawing_msg.chat.id, message_id=drawing_msg.message_id)
    except Exception:
        pass

# --- کنترلگرهای callback و contact ---
async def handle_contact(message: Message, bot: TeleBot):
    user_id = message.from_user.id
    save_authorized_user(user_id) 
    authorized_user_ids.add(user_id) 
    await bot.send_message(message.chat.id, pm["phone_shared_thanks"], reply_markup=telebot_types.ReplyKeyboardRemove())


async def handle_callback_query(call: telebot_types.CallbackQuery, bot: TeleBot):
    user_id = call.from_user.id
    message_with_button = call.message 
    
    if call.data == "confirm_join":
        message_to_edit_id = message_with_button.message_id 
        chat_to_edit_id = message_with_button.chat.id

        try:
            await bot.answer_callback_query(call.id, "در حال بررسی عضویت...")
            member_status = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
            
            keyboard_for_not_confirmed = telebot_types.InlineKeyboardMarkup()
            join_b = telebot_types.InlineKeyboardButton(text=pm["channel_button_join"], url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")
            confirm_b = telebot_types.InlineKeyboardButton(text=pm["channel_button_confirm"], callback_data="confirm_join")
            keyboard_for_not_confirmed.add(join_b)
            keyboard_for_not_confirmed.add(confirm_b)

            if member_status.status in ['member', 'administrator', 'creator']:
                await bot.edit_message_text(
                    pm["membership_confirmed"],
                    chat_id=chat_to_edit_id,
                    message_id=message_to_edit_id,
                    reply_markup=None
                )
                if user_id not in authorized_user_ids:
                    phone_keyboard = telebot_types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True, one_time_keyboard=True)
                    phone_button = telebot_types.KeyboardButton(text=pm["phone_button_share"], request_contact=True)
                    phone_keyboard.add(phone_button)
                    await bot.send_message(chat_to_edit_id, pm["share_phone_prompt"], reply_markup=phone_keyboard)
                else:
                    await bot.send_message(chat_to_edit_id, "عضویت شما تایید شد. لطفاً دستور قبلی خود را مجدداً ارسال کنید یا دستور جدیدی بدهید.")
            else:
                await bot.edit_message_text(
                    pm["membership_not_confirmed"],
                    chat_id=chat_to_edit_id,
                    message_id=message_to_edit_id,
                    reply_markup=keyboard_for_not_confirmed
                )
        except Exception as e:
            print(f"TRACEBACK for Error in callback query for join confirmation (user: {user_id}):")
            traceback.print_exc()
            
            await bot.answer_callback_query(call.id, "خطا در پردازش درخواست.")
            try:
                await bot.edit_message_text(
                    error_info, 
                    chat_id=chat_to_edit_id,
                    message_id=message_to_edit_id,
                    reply_markup=None 
                )
            except Exception as final_edit_error:
                print(f"Further error trying to edit message to error_info: {final_edit_error}")
                await bot.send_message(chat_to_edit_id, error_info)