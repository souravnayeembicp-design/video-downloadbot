import os
import tempfile
import random
import subprocess
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
from PIL import Image

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# সেশন ডেটা
user_sessions = {}

# Random ffmpeg filters
FILTERS = [
    "hue=s=0",  # black & white
    "eq=contrast=1.5:brightness=0.05",  # contrast & brightness
    "negate",  # invert colors
    "hue=h=90",  # color shift
]

def apply_ffmpeg_filter(input_path, output_path, logo_path, position):
    # Random filter select
    filter_choice = random.choice(FILTERS)

    # Logo position mapping
    positions = {
        "top_left": "(10,10)",
        "top_right": "(main_w-overlay_w-10,10)",
        "bottom_left": "(10,main_h-overlay_h-10)",
        "bottom_right": "(main_w-overlay_w-10,main_h-overlay_h-10)",
    }
    pos = positions[position]

    # Prepare ffmpeg command
    command = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-i", logo_path,
        "-filter_complex", f"[0:v] {filter_choice} [v]; [v][1:v] overlay={pos}",
        "-c:a", "copy",
        output_path
    ]
    subprocess.run(command, check=True)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হ্যালো! আমাকে ভিডিও লিঙ্ক পাঠাও।")

# লিঙ্ক হ্যান্ডলার
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.message.from_user.id
    user_sessions[user_id] = {"video_url": url}

    await update.message.reply_text("🔗 লিঙ্ক পেয়েছি। এবার লোগো পাঠাও (ইমেজ পাঠাও)।")

# লোগো হ্যান্ডলার
async def handle_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_sessions or "video_url" not in user_sessions[user_id]:
        await update.message.reply_text("⚠️ আগে ভিডিও লিঙ্ক পাঠাও।")
        return

    logo_file = await update.message.photo[-1].get_file()
    logo_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.png")
    await logo_file.download_to_drive(logo_path)
    user_sessions[user_id]["logo_path"] = logo_path

    keyboard = [
        [InlineKeyboardButton("উপর বাঁ", callback_data="top_left"),
         InlineKeyboardButton("উপর ডান", callback_data="top_right")],
        [InlineKeyboardButton("নিচে বাঁ", callback_data="bottom_left"),
         InlineKeyboardButton("নিচে ডান", callback_data="bottom_right")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("লোগো কোথায় বসাতে চাও?", reply_markup=reply_markup)

# পজিশন হ্যান্ডলার
async def handle_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in user_sessions or "logo_path" not in user_sessions[user_id]:
        await query.edit_message_text("⚠️ আগে ভিডিও লিঙ্ক আর লোগো পাঠাও।")
        return

    user_sessions[user_id]["position"] = query.data
    await query.edit_message_text("⏳ ভিডিও প্রসেস হচ্ছে...")

    await process_video(user_id, query)

# প্রসেস ভিডিও
async def process_video(user_id, query):
    data = user_sessions[user_id]
    video_url = data["video_url"]
    logo_path = data["logo_path"]
    position = data["position"]

    video_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")
    output_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")

    # Download video
    ydl_opts = {"outtmpl": video_path, "format": "mp4"}
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    # Apply filter + overlay using ffmpeg
    apply_ffmpeg_filter(video_path, output_path, logo_path, position)

    # Send video
    await query.message.reply_video(video=open(output_path, "rb"))

    # Cleanup
    for path in [video_path, output_path, logo_path]:
        if os.path.exists(path):
            os.remove(path)

    del user_sessions[user_id]

# Main app
if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(MessageHandler(filters.PHOTO, handle_logo))
    app.add_handler(CallbackQueryHandler(handle_position))

    # Webhook setup
    port = int(os.environ.get("PORT", 8080))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )
