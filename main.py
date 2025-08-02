import os
import cv2
import mediapipe as mp
import numpy as np
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

user_sessions = {}

# Color filters (no blur here, blur handled separately)
FFMPEG_FILTERS = [
    "hue=s=0",          # Black & White
    "eq=contrast=1.5",  # High Contrast
    "hue=h=90",         # Color shift
    "negate"            # Invert colors
]

mp_selfie_segmentation = mp.solutions.selfie_segmentation

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
        await update.message.reply_text("⚠️ আগে ভিডিও লিঙ্ক পাঠান।")
        return

    logo_file = await update.message.photo[-1].get_file()
    logo_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.png")
    await logo_file.download_to_drive(logo_path)

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
        await query.edit_message_text("⚠️ আগে ভিডিও লিঙ্ক আর লোগো পাঠান।")
        return

    user_sessions[user_id]["position"] = query.data
    user_sessions[user_id]["filter"] = random.choice(FFMPEG_FILTERS)

    await query.edit_message_text("⏳ ভিডিও প্রসেস হচ্ছে...")

    await process_video(user_id, query)

def apply_background_blur(input_video, output_video):
    cap = cv2.VideoCapture(input_video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_video, fourcc, fps, (width, height))

    with mp_selfie_segmentation.SelfieSegmentation(model_selection=1) as selfie_seg:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = selfie_seg.process(rgb_frame)
            mask = result.segmentation_mask > 0.5

            blurred = cv2.GaussianBlur(frame, (55, 55), 0)
            combined = np.where(mask[..., None], frame, blurred)

            out.write(combined)

    cap.release()
    out.release()

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
    blurred_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")
    output_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")

    try:
        # ভিডিও ডাউনলোড
        ydl_opts = {"outtmpl": video_path, "format": "mp4/best"}
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        # Step 1: Apply background blur
        apply_background_blur(video_path, blurred_path)

        # ভিডিও রেজুলেশন বের করা
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0", blurred_path
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

        # ফিল্টার + লোগো + ওয়াটারমার্ক
        filter_complex = (
            f"[0:v]{selected_filter}[v];"
            f"[v][1:v]overlay={pos},"
            "drawtext=text='Power by BICP Team':"
            "fontcolor=white:fontsize=24:borderw=2:bordercolor=black:"
            "x=w-tw-20:y=h-th-20"
        )

        cmd = [
            "ffmpeg",
            "-i", blurred_path,
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
        for path in [video_path, blurred_path, output_path, logo_path]:
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
