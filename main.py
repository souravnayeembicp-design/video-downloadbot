import os
import tempfile
import random
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip, vfx
from PIL import Image
import imageio_ffmpeg

# ffmpeg path fix for Render
os.environ["IMAGEIO_FFMPEG_EXE"] = imageio_ffmpeg.get_ffmpeg_exe()

TOKEN = os.getenv("BOT_TOKEN")  # Render Config vars এ সেট করো
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Render URL

# সেশন ডেটা রাখার জন্য
user_sessions = {}

# Random filters
def apply_random_filter(clip):
    filters = [
        lambda c: c.fx(vfx.blackwhite),
        lambda c: c.fx(vfx.colorx, 1.5),
        lambda c: c.fx(vfx.lum_contrast, lum=10, contrast=50),
        lambda c: c.fx(vfx.mirror_x),
    ]
    return random.choice(filters)(clip)

# /start কমান্ড
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হ্যালো! আমাকে ভিডিও লিঙ্ক পাঠাও।")

# লিঙ্ক হ্যান্ডলার
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.message.from_user.id

    # সেশন সেটআপ
    user_sessions[user_id] = {"video_url": url}

    await update.message.reply_text("🔗 লিঙ্ক পেয়েছি। এবার লোগো পাঠাও (ইমেজ পাঠাও)।")

# লোগো হ্যান্ডলার
async def handle_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_sessions or "video_url" not in user_sessions[user_id]:
        await update.message.reply_text("⚠️ আগে ভিডিও লিঙ্ক পাঠাও।")
        return

    # লোগো টেম্প ফাইল সেভ
    logo_file = await update.message.photo[-1].get_file()
    logo_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.png")
    await logo_file.download_to_drive(logo_path)

    user_sessions[user_id]["logo_path"] = logo_path

    # পজিশন সিলেকশন
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

    # প্রসেস শুরু
    await process_video(user_id, query)

# ভিডিও প্রসেস ফাংশন
async def process_video(user_id, query):
    data = user_sessions[user_id]
    video_url = data["video_url"]
    logo_path = data["logo_path"]
    position = data["position"]

    # Temp paths
    video_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")
    output_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")

    # Download video
    ydl_opts = {"outtmpl": video_path, "format": "mp4"}
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    # Process with moviepy
    clip = VideoFileClip(video_path)
    clip = apply_random_filter(clip)

    # Resize logo
    logo = Image.open(logo_path).convert("RGBA")
    logo_clip = ImageClip(logo_path).set_duration(clip.duration).resize(height=80)

    # Positioning
    margin = 10
    if position == "top_left":
        logo_clip = logo_clip.set_pos((margin, margin))
    elif position == "top_right":
        logo_clip = logo_clip.set_pos((clip.w - logo_clip.w - margin, margin))
    elif position == "bottom_left":
        logo_clip = logo_clip.set_pos((margin, clip.h - logo_clip.h - margin))
    elif position == "bottom_right":
        logo_clip = logo_clip.set_pos((clip.w - logo_clip.w - margin, clip.h - logo_clip.h - margin))

    final = CompositeVideoClip([clip, logo_clip])
    final.write_videofile(output_path, codec="libx264", audio_codec="aac", threads=4, preset="ultrafast")

    # Send video
    await query.message.reply_video(video=open(output_path, "rb"))

    # Cleanup
    for path in [video_path, output_path, logo_path]:
        if os.path.exists(path):
            os.remove(path)

    del user_sessions[user_id]

# Main
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

