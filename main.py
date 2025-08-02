import os
import tempfile
import subprocess
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
from PIL import Image

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

user_sessions = {}

# Available FFmpeg filters
FILTERS = {
    "brightness_up": "eq=brightness=0.2",
    "brightness_down": "eq=brightness=-0.2",
    "colorful": "hue=s=2",
    "black_white": "hue=s=0",
    "high_contrast": "eq=contrast=1.5",
    "blur": "boxblur=10:1",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "vignette": "vignette",
    "sharpness": "unsharp=5:5:1.0:5:5:0.0"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হ্যালো! আমাকে ভিডিও লিঙ্ক পাঠাও।")

# Step 1: Handle link and show filter options
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.message.from_user.id

    user_sessions[user_id] = {"video_url": url}

    keyboard = [
        [
            InlineKeyboardButton("Brightness ↑", callback_data="filter_brightness_up"),
            InlineKeyboardButton("Brightness ↓", callback_data="filter_brightness_down"),
        ],
        [
            InlineKeyboardButton("Colorful", callback_data="filter_colorful"),
            InlineKeyboardButton("Black & White", callback_data="filter_black_white"),
        ],
        [
            InlineKeyboardButton("High Contrast", callback_data="filter_high_contrast"),
            InlineKeyboardButton("Blur", callback_data="filter_blur"),
        ],
        [
            InlineKeyboardButton("Sepia", callback_data="filter_sepia"),
            InlineKeyboardButton("Vignette", callback_data="filter_vignette"),
        ],
        [
            InlineKeyboardButton("Sharpness", callback_data="filter_sharpness"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("কোন ফিল্টার লাগাতে চাও?", reply_markup=reply_markup)

# Step 2: Handle filter selection
async def handle_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    filter_key = query.data.replace("filter_", "")
    if filter_key not in FILTERS:
        await query.edit_message_text("⚠️ ফিল্টার ভুল। আবার চেষ্টা করো।")
        return

    user_sessions[user_id]["filter"] = FILTERS[filter_key]
    await query.edit_message_text("ফিল্টার সেট হয়েছে ✅\nএখন লোগো পাঠাও (ইমেজ পাঠাও)।")

# Step 3: Handle logo
async def handle_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_sessions or "filter" not in user_sessions[user_id]:
        await update.message.reply_text("⚠️ আগে ভিডিও লিঙ্ক পাঠাও ও ফিল্টার সিলেক্ট করো।")
        return

    logo_file = await update.message.photo[-1].get_file()
    logo_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.png")
    await logo_file.download_to_drive(logo_path)

    # Convert to PNG and keep transparency
    img = Image.open(logo_path).convert("RGBA")
    img.save(logo_path, "PNG")

    user_sessions[user_id]["logo_path"] = logo_path

    # Position buttons
    keyboard = [
        [
            InlineKeyboardButton("উপর বাঁ", callback_data="pos_top_left"),
            InlineKeyboardButton("উপর ডান", callback_data="pos_top_right"),
        ],
        [
            InlineKeyboardButton("নিচে বাঁ", callback_data="pos_bottom_left"),
            InlineKeyboardButton("নিচে ডান", callback_data="pos_bottom_right"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("লোগো কোথায় বসাতে চাও?", reply_markup=reply_markup)

# Step 4: Handle position selection and process video
async def handle_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in user_sessions or "logo_path" not in user_sessions[user_id]:
        await query.edit_message_text("⚠️ আগে ভিডিও লিঙ্ক, ফিল্টার আর লোগো পাঠাও।")
        return

    user_sessions[user_id]["position"] = query.data.replace("pos_", "")
    await query.edit_message_text("⏳ ভিডিও প্রসেস হচ্ছে...")

    await process_video(user_id, query)

# Step 5: Process video
async def process_video(user_id, query):
    data = user_sessions[user_id]
    video_url = data["video_url"]
    logo_path = data["logo_path"]
    position = data["position"]
    selected_filter = data["filter"]

    video_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")
    output_path = os.path.join(tempfile.gettempdir(), f"{uuid4()}.mp4")

    # Download video
    ydl_opts = {"outtmpl": video_path, "format": "mp4/best"}
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    # Get video resolution
    probe_cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", video_path
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    width, height = map(int, probe_result.stdout.strip().split('x'))

    # Resize logo (10% width or min 50px)
    max_logo_width = max(50, int(width * 0.1))
    img = Image.open(logo_path).convert("RGBA")
    aspect_ratio = img.height / img.width
    new_height = int(max_logo_width * aspect_ratio)
    img = img.resize((max_logo_width, new_height))
    img.save(logo_path, "PNG")

    # Position map with 20px margin
    positions = {
        "top_left": "20:20",
        "top_right": "main_w-overlay_w-20:20",
        "bottom_left": "20:main_h-overlay_h-20",
        "bottom_right": "main_w-overlay_w-20:main_h-overlay_h-20"
    }
    pos = positions[position]

    # FFmpeg command with filter, logo overlay and text watermark
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
        "-y", output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        await query.message.reply_text(f"FFmpeg Error:\n{result.stderr}")
        # Cleanup
        for path in [video_path, output_path, logo_path]:
            if os.path.exists(path):
                os.remove(path)
        del user_sessions[user_id]
        return

    await query.message.reply_video(video=open(output_path, "rb"))

    # Cleanup
    for path in [video_path, output_path, logo_path]:
        if os.path.exists(path):
            os.remove(path)
    del user_sessions[user_id]

if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(handle_filter, pattern="^filter_"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_logo))
    app.add_handler(CallbackQueryHandler(handle_position, pattern="^pos_"))

    port = int(os.environ.get("PORT", 8080))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )
