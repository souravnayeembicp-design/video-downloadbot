import os
import tempfile
import random
import subprocess
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
from PIL import Image
from rembg import remove

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

user_sessions = {}

# FFmpeg filters
FFMPEG_FILTERS = [
    "hue=s=0",             # Black & White
    "eq=contrast=1.5",     # High Contrast
    "hue=h=90",            # Color shift
    "negate"               # Invert colors
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হ্যালো! আমাকে ভিডিও লিঙ্ক পাঠাও।")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.message.from_user.id

    user_sessions[user_id] = {"video_url": url}
    await update.message.reply_text("🔗 লিঙ্ক পেয়েছি। এবার লোগো পাঠাও (ইমেজ পাঠাও)।")

async def handle_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_sessions or "video_url" not in user_sessions[user_id]:
        await update.message.reply_text("⚠️ আগে ভিডিও লিঙ্ক পাঠাও।")
        return

    logo_file = await update.message.photo[-1].get_file()
    logo_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.png")
    await logo_file.download_to_drive(logo_path)

    # Background remove using rembg
    input_image = Image.open(logo_path)
    output_image = remove(input_image)
    output_image.save(logo_path)

    user_sessions[user_id]["logo_path"] = logo_path

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
        await query.edit_message_text("⚠️ আগে ভিডিও লিঙ্ক আর লোগো পাঠাও।")
        return

    user_sessions[user_id]["position"] = query.data
    # Randomly select a filter
    user_sessions[user_id]["filter"] = random.choice(FFMPEG_FILTERS)

    await query.edit_message_text("⏳ ভিডিও প্রসেস হচ্ছে...")

    await process_video(user_id, query)

async def process_video(user_id, query):
    data = user_sessions.get(user_id)
    if not data:
        await query.message.reply_text("সেশন টাইম আউট হয়েছে, আবার চেষ্টা করুন।")
        return

    video_url = data.get("video_url")
    logo_path = data.get("logo_path")
    position = data.get("position")
    selected_filter = data.get("filter")

    video_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")
    output_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")

    try:
        print(f"[{user_id}] ভিডিও ডাউনলোড শুরু হচ্ছে...")
        ydl_opts = {"outtmpl": video_path, "format": "mp4/best"}
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print(f"[{user_id}] ভিডিও ডাউনলোড শেষ হয়েছে: {video_path}")

        # ভিডিও resolution বের করা
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0", video_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        width, height = map(int, probe_result.stdout.strip().split('x'))
        print(f"[{user_id}] ভিডিও রেজুলেশন: {width}x{height}")

        # লোগো রিসাইজ করা (ভিডিওর ১০% চওড়া)
        max_logo_width = max(50, int(width * 0.1))
        img = Image.open(logo_path).convert("RGBA")
        aspect_ratio = img.height / img.width
        new_height = int(max_logo_width * aspect_ratio)
        img = img.resize((max_logo_width, new_height))
        img.save(logo_path, "PNG")
        print(f"[{user_id}] লোগো রিসাইজ শেষ")

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

        print(f"[{user_id}] FFmpeg প্রোসেস শুরু হচ্ছে...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # ১০ মিনিট timeout
        print(f"[{user_id}] FFmpeg প্রোসেস শেষ হয়েছে, রিটার্ন কোড: {result.returncode}")

        if result.returncode != 0:
            print(f"[{user_id}] FFmpeg error: {result.stderr}")
            await query.message.reply_text(f"ভিডিও প্রোসেসিংয়ে সমস্যা হয়েছে:\n{result.stderr}")
            return

        size_mb = os.path.getsize(output_path) / (1024*1024)
        print(f"[{user_id}] আউটপুট ভিডিও সাইজ: {size_mb:.2f} MB")

        if size_mb > 50:
            await query.message.reply_text("ভিডিওর সাইজ ৫০ MB এর বেশি, তাই পাঠানো সম্ভব হচ্ছেনা।")
            return

        with open(output_path, "rb") as video_file:
            await query.message.reply_video(video=video_file)

        print(f"[{user_id}] ভিডিও সফলভাবে পাঠানো হয়েছে।")

    except subprocess.TimeoutExpired:
        await query.message.reply_text("ভিডিও প্রোসেসিং টাইমআউট হয়েছে, অনুগ্রহ করে ছোট ভিডিও পাঠান।")
    except Exception as e:
        print(f"[{user_id}] Exception: {e}")
        await query.message.reply_text(f"ভিডিও প্রোসেসিংয়ে সমস্যা হয়েছে: {e}")
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
