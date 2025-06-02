import argparse
import traceback
import asyncio
import re
import telebot
from telebot.async_telebot import AsyncTeleBot
import handlers
from config import conf
from keep_alive import keep_alive
keep_alive()

# Init args
parser = argparse.ArgumentParser()
# توکن تلگرام شما
TG_TOKEN_PROVIDED = "8048656293:AAHlZUYeR0Iv4rtZ0cAPvWq6vwBgZmq8XUE" # Placeholder, use environment variables or secure config


class Options:
    def __init__(self, tg_token): # google_gemini_key removed
        self.tg_token = tg_token
        # self.GOOGLE_GEMINI_KEY = google_gemini_key # Removed

# options = Options(TG_TOKEN_PROVIDED, GEMINI_API_KEY_PROVIDED) # GEMINI_API_KEY_PROVIDED removed
options = Options(TG_TOKEN_PROVIDED)


async def main():
    # Init bot
    bot = AsyncTeleBot(options.tg_token)
    await bot.delete_my_commands(scope=None, language_code=None)
    await bot.set_my_commands(
    commands=[
        telebot.types.BotCommand("start", "شروع و خوش آمدگویی"),
        telebot.types.BotCommand("clear", "پاک کردن تاریخچه گفتگو"),
        telebot.types.BotCommand("img", "ترسیم تصویر (مثال: /img یک گربه)"),
        telebot.types.BotCommand("edit", "ویرایش عکس با توضیح (ریپلای روی عکس)"),
        telebot.types.BotCommand("switch","تغییر مدل پیش‌فرض چت (خصوصی)"), # Description slightly updated for clarity
        telebot.types.BotCommand("help", "راهنمای استفاده از ربات"),
        # telebot.types.BotCommand("gemini", f"پرسش با مدل {conf['model_1']}"), # Removed
        # telebot.types.BotCommand("gemini_pro", f"پرسش با مدل {conf['model_2']}"), # Removed
    ],
)
    print("Bot init done (Persian).")

    # Init commands from handlers module
    bot.register_message_handler(handlers.start,                         commands=['start'],         pass_bot=True)
    bot.register_message_handler(handlers.draw_handler,                  commands=['img'],           pass_bot=True)
    bot.register_message_handler(handlers.gemini_edit_handler,           commands=['edit'],          pass_bot=True)
    bot.register_message_handler(handlers.clear,                         commands=['clear'],         pass_bot=True)
    bot.register_message_handler(handlers.switch,                        commands=['switch'],        pass_bot=True)
    bot.register_message_handler(handlers.show_help,                     commands=['help'],          pass_bot=True)

    # bot.register_message_handler(handlers.gemini_stream_handler,         commands=['gemini'],        pass_bot=True) # Removed
    # bot.register_message_handler(handlers.gemini_pro_stream_handler,     commands=['gemini_pro'],    pass_bot=True) # Removed

    bot.register_message_handler(handlers.gemini_photo_handler,          content_types=["photo"],    pass_bot=True)

    # کنترلگر برای پیام‌های متنی در چت خصوصی (باید بعد از دستورات باشد)
    # این هندلر اکنون تمام پیام‌های متنی بدون دستور در چت خصوصی را مدیریت می‌کند
    bot.register_message_handler(
        handlers.gemini_private_handler,
        func=lambda message: message.chat.type == "private" and message.text and not message.text.startswith('/'),
        content_types=['text'],
        pass_bot=True)

    # کنترلگر برای دریافت contact (اشتراک‌گذاری شماره تلفن)
    bot.register_message_handler(handlers.handle_contact, content_types=['contact'], pass_bot=True)

    # کنترلگر برای callback query (دکمه‌های اینلاین)
    bot.register_callback_query_handler(handlers.handle_callback_query, func=lambda call: True, pass_bot=True)


    # Start bot
    # print(f"Starting Gemini_Telegram_Bot (Persian) with API Key: ...{options.GOOGLE_GEMINI_KEY[-4:]}") # Removed API key logging
    print("Starting Gemini_Telegram_Bot (Persian)...")
    await bot.polling(none_stop=True, skip_pending=True)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        traceback.print_exc()
        print(f"Error running bot: {e}")
