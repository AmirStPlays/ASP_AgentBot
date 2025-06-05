import argparse
import traceback
import asyncio
import re
import telebot
from telebot.async_telebot import AsyncTeleBot
import handlers
import gemini
from config import conf
from keep_alive import keep_alive
keep_alive()

# Init args
parser = argparse.ArgumentParser()
TG_TOKEN_PROVIDED = "8048656293:AAHlZUYeR0Iv4rtZ0cAPvWq6vwBgZmq8XUE"

class Options:
    def __init__(self, tg_token):
        self.tg_token = tg_token

options = Options(TG_TOKEN_PROVIDED)

async def main():
    await gemini.load_user_chats_async()

    bot = AsyncTeleBot(options.tg_token)
    await bot.delete_my_commands(scope=None, language_code=None)
    await bot.set_my_commands(
    commands=[
        telebot.types.BotCommand("start", "شروع و خوش آمدگویی"),
        telebot.types.BotCommand("clear", "پاک کردن تاریخچه گفتگو (برای کاربر)"),
        telebot.types.BotCommand("img", "ترسیم تصویر (مثال: /img یک گربه)"),
        telebot.types.BotCommand("edit", "ویرایش عکس با توضیح (ریپلای روی عکس)"),
        telebot.types.BotCommand("switch","تغییر مدل پیش‌فرض (فقط در pv)"),
        telebot.types.BotCommand("help", "راهنمای استفاده از ربات"),
    ],
)
    print("Bot init done (Persian).")

    # Command handlers (should have pre_command_checks if they interact with Gemini or need auth)
    bot.register_message_handler(handlers.start,                         commands=['start'],         pass_bot=True)
    bot.register_message_handler(handlers.draw_handler,                  commands=['img'],           pass_bot=True)
    bot.register_message_handler(handlers.gemini_edit_handler,           commands=['edit'],          pass_bot=True)
    bot.register_message_handler(handlers.clear,                         commands=['clear'],         pass_bot=True)
    bot.register_message_handler(handlers.switch,                        commands=['switch'],        pass_bot=True)
    bot.register_message_handler(handlers.show_help,                     commands=['help'],          pass_bot=True) # pre_command_checks applied

    # Content type handlers (photo handler now has pre_command_checks)
    bot.register_message_handler(handlers.gemini_photo_handler,          content_types=["photo"],    pass_bot=True)

    # Text Handlers - Order matters: more specific (group with prefix) before general (private)
    # Group text handler (for messages starting with '.')
    bot.register_message_handler(
        handlers.gemini_group_text_handler,
        func=lambda message: message.chat.type != "private" and message.text and message.text.startswith('.'),
        content_types=['text'],
        pass_bot=True)

    # Private text handler (for non-command messages in private chat)
    bot.register_message_handler(
        handlers.gemini_private_handler,
        func=lambda message: message.chat.type == "private" and message.text and not message.text.startswith('/'),
        content_types=['text'],
        pass_bot=True)

    # Callback query handler (for inline buttons)
    bot.register_callback_query_handler(handlers.handle_callback_query, func=lambda call: True, pass_bot=True)

    print(f"Starting Gemini_Telegram_Bot (Persian)...")
    await bot.polling(none_stop=True, skip_pending=True)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        traceback.print_exc()
        print(f"Error running bot: {e}")
