from flask import Flask
from threading import Thread
import asyncio
import telebot
from telebot.async_telebot import AsyncTeleBot
import argparse
import traceback
import handlers
import gemini
import os
from dotenv import load_dotenv 
from config import conf

app = Flask(__name__)
load_dotenv()
@app.route('/')
def home():
    return "bot is alive ✅"

# Flask server runner
def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Init args
parser = argparse.ArgumentParser()
TG_TOKEN_PROVIDED = os.environ.get("tg_token")

class Options:
    def __init__(self, tg_token):
        self.tg_token = tg_token

options = Options(TG_TOKEN_PROVIDED)

async def run_bot():
    handlers.clear_updates(TG_TOKEN_PROVIDED)
    await gemini.load_user_chats_async()
    asyncio.create_task(gemini.daily_reset_stats())
    bot = AsyncTeleBot(options.tg_token)

    await bot.delete_my_commands(scope=None, language_code=None)
    await bot.set_my_commands(commands=[
        telebot.types.BotCommand("start", "شروع و خوش آمدگویی"),
        telebot.types.BotCommand("clear", "پاک کردن تاریخچه گفتگو (برای کاربر)"),
        telebot.types.BotCommand("img", "ترسیم تصویر (مثال: /img یک گربه)"),
        telebot.types.BotCommand("edit", "ویرایش عکس با توضیح (ریپلای روی عکس)"),
        telebot.types.BotCommand("switch", "تغییر مدل پیش‌فرض (فقط در pv)"),
        telebot.types.BotCommand("help", "راهنمای استفاده از ربات"),
        telebot.types.BotCommand("info", "نمایش آمار استفاده کاربر"),
    ])

    # Register handlers
    bot.register_message_handler(handlers.start, commands=['start'], pass_bot=True)
    bot.register_message_handler(handlers.show_info, commands=['info'], pass_bot=True)
    bot.register_message_handler(handlers.draw_handler, commands=['img'], pass_bot=True)
    bot.register_message_handler(handlers.gemini_edit_handler, commands=['edit'], pass_bot=True)
    bot.register_message_handler(handlers.clear, commands=['clear'], pass_bot=True)
    bot.register_message_handler(handlers.switch, commands=['switch'], pass_bot=True)
    bot.register_message_handler(handlers.show_help, commands=['help'], pass_bot=True)
    bot.register_message_handler(handlers.gemini_photo_handler, content_types=["photo"], pass_bot=True)
    bot.register_message_handler(
        handlers.gemini_group_text_handler,
        func=lambda m: m.chat.type != "private" and m.text and m.text.startswith('.'),
        content_types=["text"],
        pass_bot=True)
    bot.register_message_handler(
        handlers.gemini_private_handler,
        func=lambda m: m.chat.type == "private" and m.text and not m.text.startswith('/'),
        content_types=["text"],
        pass_bot=True)
    bot.register_callback_query_handler(handlers.handle_callback_query, func=lambda call: True, pass_bot=True)

    print("Starting Gemini_Telegram_Bot (Persian)...")
    await bot.polling(none_stop=True, skip_pending=True)

if __name__ == '__main__':
    try:
        Thread(target=run_flask).start()
        asyncio.run(run_bot())
    except Exception as e:
        traceback.print_exc()
        print(f"Error running bot: {e}")
