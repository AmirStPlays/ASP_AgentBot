import argparse
import traceback
import asyncio
import re
import telebot # types از اینجا حذف شد چون در handlers استفاده شده
from telebot.async_telebot import AsyncTeleBot
import handlers
from config import conf # generation_config, safety_settings اگر در اینجا لازم نیستند، حذف شوند
                        # اما conf برای تنظیمات دستورات لازم است

# Init args
parser = argparse.ArgumentParser()
# مقادیر توکن و کلید API شما که ارائه دادید
TG_TOKEN_PROVIDED = "8048656293:AAHlZUYeR0Iv4rtZ0cAPvWq6vwBgZmq8XUE" # Placeholder, use environment variables or secure config




class Options:
    def __init__(self, tg_token, google_gemini_key):
        self.tg_token = tg_token

options = Options(TG_TOKEN_PROVIDED)



async def main():
    # Init bot
    bot = AsyncTeleBot(options.tg_token)
    await bot.delete_my_commands(scope=None, language_code=None)
    await bot.set_my_commands(
    commands=[
        telebot.types.BotCommand("start", "شروع و خوش آمدگویی"),
        telebot.types.BotCommand("clear", "پاک کردن تاریخچه گفتگو"),
        telebot.types.BotCommand("img", "ترسیم تصویر (مثال: /img یک گربه)"), # Changed from draw to img
        telebot.types.BotCommand("edit", "ویرایش عکس با توضیح (ریپلای روی عکس)"),
        telebot.types.BotCommand("switch","تغییر مدل پیش‌فرض (خصوصی)"),
        telebot.types.BotCommand("help", "راهنمای استفاده از ربات"),
    ],
)
    print("Bot init done (Persian).")

    # Init commands from handlers module
    bot.register_message_handler(handlers.start,                         commands=['start'],         pass_bot=True)
    bot.register_message_handler(handlers.draw_handler,                  commands=['img'],           pass_bot=True) # Changed from draw to img
    bot.register_message_handler(handlers.gemini_edit_handler,           commands=['edit'],          pass_bot=True)
    bot.register_message_handler(handlers.clear,                         commands=['clear'],         pass_bot=True)
    bot.register_message_handler(handlers.switch,                        commands=['switch'],        pass_bot=True)
    bot.register_message_handler(handlers.show_help,                     commands=['help'],          pass_bot=True)
    bot.register_message_handler(handlers.gemini_photo_handler,          content_types=["photo"],    pass_bot=True)

    # کنترلگر برای پیام‌های متنی در چت خصوصی (باید بعد از دستورات باشد)
    bot.register_message_handler(
        handlers.gemini_private_handler,
        func=lambda message: message.chat.type == "private" and message.text and not message.text.startswith('/'), # Added message.text check
        content_types=['text'],
        pass_bot=True)

    # کنترلگر برای دریافت contact (اشتراک‌گذاری شماره تلفن)
    bot.register_message_handler(handlers.handle_contact, content_types=['contact'], pass_bot=True)

    # کنترلگر برای callback query (دکمه‌های اینلاین)
    bot.register_callback_query_handler(handlers.handle_callback_query, func=lambda call: True, pass_bot=True)


    # Start bot
    print(f"Starting Gemini_Telegram_Bot (Persian) with API Key: ...{options.GOOGLE_GEMINI_KEY[-4:]}")
    await bot.polling(none_stop=True, skip_pending=True)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        traceback.print_exc()
        print(f"Error running bot: {e}")
