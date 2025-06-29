from google.genai import types

with open("default_prompt.txt", "r", encoding="utf-8") as f:
    full_prompt = f.read()

with open("default_image_processing_prompt.txt", "r", encoding="utf-8") as f:
    default_image_processing_prompt = f.read()



default_image_processing_prompt = full_prompt + "\n\n" + default_image_processing_prompt

conf = {
    "error_info":           "⚠️⚠️⚠️\nمشکلی پیش آمد!\nلطفاً درخواست خود را دوباره امتحان کنید و یا با ادمین ارتباط بگیرید!\n@AmirStPlays",
    "before_generate_info": "در حال نوشتن پاسخ ...✍️",
    "download_pic_notify":  "🤖 در حال بارگذاری تصویر 🤖",
    "model_1":              "gemini-2.5-flash",
    "model_2":              "gemini-2.0-flash-thinking-exp",
    "model_3":              "gemini-2.0-flash-preview-image-generation",
    "streaming_update_interval": 0.8,
    "default_system_prompt": full_prompt,
    "default_image_processing_prompt": default_image_processing_prompt,
    "persian_messages": {
        "welcome": "\nمیتونی از دستور های ربات استفاده کنی و یا پیام خودت رو بفرستی.\nدر صورت نیاز /help را بزن.",
        "add_prompt_gemini": "لطفاً متن سوال خود را بعد از دستور /gemini بنویسید.\nبرای مثال: `/gemini جان لنون کیست؟`",
        "add_prompt_gemini_pro": "لطفاً متن سوال خود را بعد از دستور /gemini_pro بنویسید.\nبرای مثال: `/gemini_pro جان لنون کیست؟`",
        "history_cleared": "تاریخچه شما پاک شد.",
        "switch_only_private": "این دستور فقط در چت خصوصی قابل استفاده است!",
        "switched_to_model_2": "اکنون از مدل {} استفاده می‌کنید.",
        "switched_to_model_1": "اکنون از مدل {} استفاده می‌کنید.",
        "photo_edit_prompt": "لطفا یک عکس همراه با دستور ارسال کنید یا روی یک عکس ریپلای کنید و دستور /edit را بنویسید.",
        "add_prompt_img": "لطفاً چیزی که می‌خواهید ترسیم شود را بعد از دستور /img بنویسید.\nبرای مثال: `/img یک گربه پشمالو برای من بکش.`",
        "drawing_in_progress": "در حال ساخت تصویر شما ...",
        "join_channel_prompt": "برای ادامه و استفاده از امکانات ربات، لطفاً ابتدا در کانال زیر عضو شوید و سپس روی دکمه 'تایید عضویت' کلیک کنید:",
        "membership_confirmed": "عضویت شما تایید شد. حالا می‌تونید از ربات استفاده کنید😉.",
        "membership_not_confirmed": "عضویت شما در کانال تایید نشد. لطفاً ابتدا در کانال عضو شوید و سپس مجدداً تلاش کنید.",
        "channel_button_join": "عضویت در کانال",
        "channel_button_confirm": "✅ تایید عضویت",
        "photo_caption_prompt": "لطفاً یک توضیح یا دستور برای عکس ارائه دهید. برای مثال: `این تصویر چیست؟` یا `مسئله ریاضی داخل عکس را حل کن`",
        "photo_command_caption_info": "برای ویرایش عکس، روی آن ریپلای کرده و از دستور `/edit <توضیح ویرایش>` استفاده کنید.\nبرای تولید تصویر جدید از متن، از دستور `/img <توضیح تصویر>` استفاده کنید.",
        "group_prompt_needed": "لطفاً پس از نقطه `.`، دستور یا سوال خود را بنویسید. مثال: `.سلام، خوبی؟`",
        "image_prompt_needed_group": "لطفاً پس از نقطه `.` در کپشن عکس، توضیح یا دستور خود را بنویسید. مثال: `.این عکس را توصیف کن`",
        "photo_proccessing_prompt": "درحال پردازش عکس شما ... 🧐",
    }
}


CHANNEL_USERNAME = "@ASP_bot_collection"


safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

generation_config = types.GenerateContentConfig(
    response_modalities=['Text', 'Image'],
)
