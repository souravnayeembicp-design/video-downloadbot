import os
import tempfile
import random
import subprocess
from uuid import uuid4
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
from PIL import Image

TOKEN = os.getenv("BOT_TOKEN")  # আপনার বট টোকেন
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # ওয়েবহুক URL
REMOVE_BG_API_KEY = os.getenv("REMOVE_BG_API_KEY")  # remove.bg API কী

user_sessions = {}

FFMPEG_FILTERS = [
    "hue=s=0",          # কালো-সাদা
    "eq=contrast=1.5",  # কনট্রাস্ট বাড়ানো
    "hue=h=90",         # কালার শিফট
    "negate",           # কালার ইনভার্ট
    "boxblur=10:1",     # ব্লার (box blur)
    "gblur=sigma=5"     # ব্লার (Gaussian blur)
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হ্যালো! আমাকে ভিডিও লিঙ্ক পাঠাও।")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.message.from_user.id

    user_sessions[user_id] = {"video_url": url}
    await update.message.reply_text("🔗 লিঙ্ক পেয়েছি। এবার লোগো পাঠাও (ইমেজ পাঠাও)।")

def remove_bg_api(input_path, output_path):
    with open(input_path, 'rb') as image_file:
        response = requests.post(
            'https://api.remove.bg/v1.0/removebg',
            files={'image_file': image_file},
            data={'size': 'auto'},
            headers={'X-Api-Key': REMOVE_BG_API_KEY},
        )
        if response.status_code == requests.codes.ok:
            with open(output_path, 'wb') as out:
                out.write(response.content)
            return True
        else:
            print("Remove.bg API Error:", response.text)
            return False

async def handle_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_sessions or "video_url" not in user_sessions[user_id]:
        await update.message.reply_text("⚠️ আগে ভিডিও লিঙ্ক পাঠান।")
        return

    logo_file = await update.message.photo[-1].get_file()
    logo_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.png")
    await logo_file.download_to_drive(logo_path)

    # ব্যাকগ্রাউন্ড রিমুভ
    logo_no_bg_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}_no_bg.png")
    success = remove_bg_api(logo_path, logo_no_bg_path)
    if not success:
        await update.message.reply_text("⚠️ ব্যাকগ্রাউন্ড রিমুভ করা সম্ভব হয়নি। অন্য লোগো পাঠান।")
        return

    user_sessions[user_id]["logo_path"] = logo_no_bg_path

    keyboard = [
        [
            InlineKeyboardButton("উপর বাঁ", callback_data="top_left"),
            InlineKeyboardButton("উপর ডান", callback_data="top_right"),
        ],
        [
            InlineKeyboardButton("নিচে বাঁ", callback_data="bottom_left"),
            InlineKeyboardButton("নিচে ডান", callback_data="bottom_right"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("লোগো কোথায় বসাতে চাও?", reply_markup=reply_markup)

async def handle_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in user_sessions or "logo_path" not in user_sessions[user_id]:
        await query.edit_message_text("⚠️ আগে ভিডিও লিঙ্ক আর লোগো পাঠান।")
        return

    user_sessions[user_id]["position"] = query.data
    user_sessions[user_id]["filter"] = random.choice(FFMPEG_FILTERS)

    await query.edit_message_text("⏳ ভিডিও প্রসেস হচ্ছে...")

    await process_video(user_id, query)

async def process_video(user_id, query):
    data = user_sessions.get(user_id)
    if not data:
        await query.message.reply_text("সেশন টাইমআউট হয়েছে, আবার চেষ্টা করুন।")
        return

    video_url = data.get("video_url")
    logo_path = data.get("logo_path")
    position = data.get("position")
    selected_filter = data.get("filter")

    video_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")
    output_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")

    try:
        ydl_opts = {"outtmpl": video_path, "format": "mp4/best"}
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        # ভিডিওর রেজুলেশন বের করা
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0", video_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        width, height = map(int, probe_result.stdout.strip().split('x'))

        # লোগো রিসাইজ (ভিডিওর ১০% চওড়া)
        max_logo_width = max(50, int(width * 0.1))
        img = Image.open(logo_path).convert("RGBA")
        aspect_ratio = img.height / img.width
        new_height = int(max_logo_width * aspect_ratio)
        img = img.resize((max_logo_width, new_height))
        img.save(logo_path, "PNG")

        positions = {
            "top_left": "20:20",
            "top_right": "main_w-overlay_w-20:20",
            "bottom_left": "20:main_h-overlay_h-20",
            "bottom_right": "main_w-overlay_w-20:main_h-overlay_h-20"
        }
        pos = positions.get(position, "main_w-overlay_w-20:main_h-overlay_h-20")

        filter_complex = (
            f"[0:v]{selected_filter}[v];"
            f"[v][1:v]overlay={pos},"
            "drawtext=text='Power by BICP Team':"
            "fontcolor=white:fontsize=24:borderw=2:bordercolor=black:"
            "x=w-tw-20:y=h-th-20"
        )

        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-i", logo_path,
            "-filter_complex", filter_complex,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "veryfast",
            "-crf", "28",
            "-y", output_path
        ]

        subprocess.run(cmd, check=True, timeout=600)

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        if size_mb > 50:
            await query.message.reply_text("ভিডিওর সাইজ ৫০ MB এর বেশি, তাই পাঠানো সম্ভব হচ্ছে না।")
            return

        with open(output_path, "rb") as video_file:
            await query.message.reply_video(video=video_file)

    except subprocess.TimeoutExpired:
        await query.message.reply_text("ভিডিও প্রসেসিং টাইমআউট হয়েছে, অনুগ্রহ করে ছোট ভিডিও পাঠান।")
    except Exception as e:
        await query.message.reply_text(f"ভিডিও প্রসেসিংয়ে সমস্যা হয়েছে: {e}")
    finally:
        for path in [video_path, output_path, logo_path]:
            if os.path.exists(path):
                os.remove(path)
        if user_id in user_sessions:
            del user_sessions[user_id]

if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(MessageHandler(filters.PHOTO, handle_logo))
    app.add_handler(CallbackQueryHandler(handle_position))

    port = int(os.environ.get("PORT", 8080))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )
