import json
import os
from functools import wraps
from telebot import TeleBot, types as telebot_types
from telebot.types import Message
from md2tgmd import escape
import traceback
from config import conf, CHANNEL_USERNAME # Removed USER_AUTH_FILE
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


# دیکشنری برای نگهداری ترجیح مدل پیش‌فرض کاربر
user_model_preference = {}


# --- دکوریتور برای بررسی‌ها ---
def pre_command_checks(func):
    @wraps(func)
    async def wrapper(message: Message, bot: TeleBot, *args, **kwargs):
        user_id = message.from_user.id
        # chat_id = message.chat.id # Not used here currently
        # chat_type = message.chat.type # Not used here currently

        # 1. Channel Membership Check
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

        return await func(message, bot, *args, **kwargs)
    return wrapper

@pre_command_checks
async def show_help(message: Message, bot: TeleBot):
    title = "راهنمای جامع استفاده از بات"
    img_description_raw = """برای تولید عکس توسط ربات ابتدا این دستور را از طریق منوی پایین چپ نگه داشته تا عبارت آن بر روی کیبورد نمایان بشه.
پس از این متن خودتون رو جلوی دستور برای ساخت عکس بنویسید.
این رو هم بدونید که ممکنه این عملیات زمانبر باشه """
    edit_description_raw = """برای اینکار یا یک عکس از گالری خود و یا یک عکس از تاریخچه چتتون انتخاب کنید(روی پیامش ریپلای بزنید)
بعد از اینکار مثل دستور قبل عبارت /edit را پشت کپشن یا پیام ریپلای زده شده خودتون بنویسین و ادیتی که میخواین روی عکس اعمال بشه رو تایپ کنید.
این عملیات هم میتونه کمی زمانبر باشه."""
    switch_description_raw = "با استفاده از این دستور میتونین مدل پردازش متن رو عوض کنید "
    help_description_raw = "برای دیدن راهنمای استفاده از بات از این دستور استفاده کنید "
    group_text_raw = "در گروه ها، برای اینکه ربات به پیام متنی شما پاسخ دهد، پیام خود را با `.` شروع کنید. مثال: `.سلام خوبی؟`"
    group_image_raw = "در گروه ها، برای پردازش یک عکس (مثلاً توصیف آن)، کپشن عکس را با `.` شروع کنید. مثال: `.این عکس چیست؟`"
    footer_raw = "در صورت داشتن هرگونه ابهام یا مشکل در ربات حتما به من بگید تا درستش کنم"
    admin_id_raw = "اینم آیدیم: @AmirStPlays"

    help_text = f"**{escape(title)}**\n\n"
    help_text += escape("1. دستور /img (تولید تصویر)") + "\n"
    help_text += "```\n" + escape(img_description_raw) + "\n```\n\n"
    help_text += escape("2. دستور /edit (ویرایش تصویر با ریپلای)") + "\n"
    help_text += "```\n" + escape(edit_description_raw) + "\n```\n\n"
    help_text += escape("3. دستور /switch (تغییر مدل متن در چت خصوصی)") + "\n"
    help_text += "```\n" + escape(switch_description_raw) + "\n```\n\n"
    help_text += escape("4. دستور /help (همین راهنما)") + "\n"
    help_text += "```\n" + escape(help_description_raw) + "\n```\n\n"
    help_text += escape("5. استفاده در گروه (متن)") + "\n"
    help_text += "```\n" + escape(group_text_raw) + "\n```\n\n"
    help_text += escape("6. استفاده در گروه (عکس)") + "\n"
    help_text += "```\n" + escape(group_image_raw) + "\n```\n\n"
    help_text += escape(footer_raw) + "\n"
    help_text += escape(admin_id_raw)

    await bot.reply_to(message, help_text, parse_mode="MarkdownV2")

# --- کنترلگرهای اصلی ---
@pre_command_checks
async def start(message: Message, bot: TeleBot) -> None:
    try:
        await bot.reply_to(message , escape(pm["welcome"]), parse_mode="MarkdownV2", reply_markup=telebot_types.ReplyKeyboardRemove())
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, error_info)


@pre_command_checks
async def clear(message: Message, bot: TeleBot) -> None:
    user_id_str = str(message.from_user.id) # History is per user
    history_cleared_flag = False
    if user_id_str in gemini.user_chats:
        del gemini.user_chats[user_id_str]
        history_cleared_flag = True

    if user_id_str in user_model_preference: # This is also per user
        del user_model_preference[user_id_str]
        history_cleared_flag = True # Though it might have been set above already

    if history_cleared_flag:
        await gemini.save_user_chats()

    await bot.reply_to(message, pm["history_cleared"])

@pre_command_checks
async def switch(message: Message, bot: TeleBot) -> None:
    if message.chat.type != "private":
        await bot.reply_to( message , pm["switch_only_private"])
        return

    user_id_str = str(message.from_user.id)
    current_prefers_model_1 = user_model_preference.get(user_id_str, True)

    if current_prefers_model_1:
        user_model_preference[user_id_str] = False
        await bot.reply_to( message , pm["switched_to_model_2"].format(model_2))
    else:
        user_model_preference[user_id_str] = True
        await bot.reply_to( message , pm["switched_to_model_1"].format(model_1))


@pre_command_checks
async def gemini_private_handler(message: Message, bot: TeleBot) -> None:
    # This handler is already configured for private chats only via main.py registration
    m = message.text.strip()
    if not m: # Should not happen due to message.text check in registration
        return

    user_id_str = str(message.from_user.id)
    prefers_model_1 = user_model_preference.get(user_id_str, True)

    model_to_use = model_1 if prefers_model_1 else model_2
    await gemini.gemini_stream(bot, message, m, model_to_use)

@pre_command_checks
async def gemini_group_text_handler(message: Message, bot: TeleBot) -> None:
    # This handler is for group messages starting with '.'
    text = message.text.strip()
    if not text.startswith('.'): # Should be caught by registration func, but double check
        return

    m = text[1:].strip() # Remove the dot and strip
    if not m:
        await bot.reply_to(message, pm["group_prompt_needed"])
        return

    user_id_str = str(message.from_user.id) # Per-user history in group
    prefers_model_1 = user_model_preference.get(user_id_str, True) # Users can't use /switch in group, so this uses their PV preference or default

    model_to_use = model_1 if prefers_model_1 else model_2
    await gemini.gemini_stream(bot, message, m, model_to_use)


@pre_command_checks # Apply decorator
async def gemini_photo_handler(message: Message, bot: TeleBot) -> None:
    caption = (message.caption or "").strip()
    prompt_to_use = ""
    is_group = message.chat.type != "private"

    if is_group:
        if not caption.startswith("."):
            return # Ignore in group if caption doesn't start with .
        prompt_to_use = caption[1:].strip()
        if not prompt_to_use:
            # await bot.reply_to(message, escape(pm["image_prompt_needed_group"]), parse_mode="MarkdownV2")
            # return
            # Or use default if dot is present but no text after it. Let's use default.
            prompt_to_use = default_image_prompt
    else: # Private chat
        if caption.lower().startswith("/edit ") or caption.lower().startswith("/img "):
            await bot.reply_to(message, escape(pm["photo_command_caption_info"]), parse_mode="MarkdownV2")
            return
        elif caption:
            prompt_to_use = caption
        else:
            prompt_to_use = default_image_prompt

    if not prompt_to_use: # Should only happen if logic changes above
        await bot.reply_to(message, escape(pm["photo_caption_prompt"]), parse_mode="MarkdownV2")
        return

    try:
        await bot.send_chat_action(message.chat.id, 'typing')
        file_path = await bot.get_file(message.photo[-1].file_id)
        photo_file = await bot.download_file(file_path.file_path)
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(message, f"{error_info}\nDetails: {str(e)}")
        return

    # For gemini_edit (which uses model_3), history isn't typically maintained in the same way as text chats.
    # The call to gemini.gemini_edit doesn't rely on user_chats state from gemini_stream.
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
            # Command /edit should work in groups and PV if called correctly
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

    if not text_prompt_from_command:
        await bot.reply_to(original_message, escape("لطفا توضیح ویرایش را بعد از دستور /edit بنویسید."), parse_mode="MarkdownV2")
        return

    if not photo_message or not photo_message.photo:
        await bot.reply_to(original_message, pm["photo_edit_prompt"]) # Should be caught above
        return

    try:
        await bot.send_chat_action(original_message.chat.id, 'typing')
        file_path = await bot.get_file(photo_message.photo[-1].file_id)
        photo_file = await bot.download_file(file_path.file_path)
    except Exception as e:
        traceback.print_exc()
        await bot.reply_to(original_message, f"{error_info}\nDetails: {str(e)}")
        return

    await gemini.gemini_edit(bot, original_message, text_prompt_from_command, photo_file)


@pre_command_checks
async def draw_handler(message: Message, bot: TeleBot) -> None: # Handles /img
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
                # Inform user they can now use the bot or retry previous command
                await bot.send_message(chat_to_edit_id, "اکنون می‌توانید از امکانات ربات استفاده کنید یا دستور قبلی خود را مجدداً ارسال نمایید.")

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
