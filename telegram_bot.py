
import re
from telegram import Update
from telegram.ext import ContextTypes

from gym_system import (
    detect_any_day_from_text,
    today_english_day,
    book_class_sqlite,   # موجود عندك
    GYM_ID,              # لو عندك global gym id بعد bootstrap
)

DEFAULT_TZ = "Africa/Cairo"

# ====== 1) Greeting detection ======
GREETINGS = {
    "صباح الخير", "صباح النور", "مساء الخير", "مساء النور",
    "اهلا", "أهلا", "هاي", "هلا", "السلام عليكم", "سلام عليكم",
    "hello", "hi", "hey"
}

def is_greeting(text: str) -> bool:
    t = text.strip().lower()
    # تطبيع بسيط عربي/انجليزي
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    t = t.replace("ً", "").replace("ٌ", "").replace("ٍ", "").replace("َ", "").replace("ُ", "").replace("ِ", "").replace("ْ", "")
    for g in GREETINGS:
        gg = g.lower().replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        if gg in t:
            return True
    return False

# ====== 2) Member code extraction ======
CODE_RE = re.compile(r"\b(\d{3,})\b")  # 3+ digits

def extract_code(text: str) -> str | None:
    m = CODE_RE.search(text)
    return m.group(1) if m else None

# ====== 3) Reset words ======
RESET_RE = re.compile(r"(ابدأ من جديد|نبدأ من جديد|ريست|reset|start over|ابدأ)", re.IGNORECASE)

def reset_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("step", None)
    context.user_data.pop("member_code", None)
    context.user_data.pop("gym_class", None)
    context.user_data.pop("day", None)

# ====== 4) Main handler ======

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    # Reset
    if RESET_RE.search(text):
        reset_flow(context)
        await update.message.reply_text("تمام. اكتب/ي كود العضوية علشان نبدأ الحجز.")
        context.user_data["step"] = "await_code"
        return

    step = context.user_data.get("step")

    # (A) Greeting → reply + ask for code
    if is_greeting(text) and step is None:
        await update.message.reply_text("أهلًا! 👋")
        await update.message.reply_text("اكتب/ي كود العضوية علشان أبدأ الحجز.")
        context.user_data["step"] = "await_code"
        return

    # لو أول رسالة مش تحية (مثلاً كود مباشر) نبدأ flow بدون تحية
    if step is None:
        context.user_data["step"] = "await_code"
        step = "await_code"

    # (B) Await member code
    if step == "await_code":
        code = extract_code(text)
        if not code:
            await update.message.reply_text("محتاج/ة كود العضوية (أرقام فقط).")
            return
        context.user_data["member_code"] = code
        context.user_data["step"] = "await_class"
        await update.message.reply_text("تمام ✅ دلوقتي اسم الكلاس إيه؟ (مثال: Pilates)")
        return

    # (C) Await class name
    if step == "await_class":

        code = context.user_data.get("member_code")
        gym_class = text
        if code:
            gym_class = gym_class.replace(code, "").strip()
        if len(gym_class) < 2:
            await update.message.reply_text("اكتب/ي اسم الكلاس بشكل واضح.")
            return
        context.user_data["gym_class"] = gym_class
        context.user_data["step"] = "await_day"
        await update.message.reply_text("اليوم إيه؟ (اختياري) ممكن تكتب/ي: السبت / الاحد / الاربع ... أو اكتب/ي (اليوم) لو عايز/ة النهارده.")
        return

    # (D) Await day (optional)
    if step == "await_day":
        # لو كتب “اليوم/النهارده/Today” نعتبره اليوم الحالي
        t = text.strip().lower()
        if t in {"اليوم", "النهارده", "نهارده", "today", "now"}:
            day = today_english_day(DEFAULT_TZ)
        else:
            day = detect_any_day_from_text(text) or today_english_day(DEFAULT_TZ)

        context.user_data["day"] = day

        # Execute booking
        member_code = context.user_data["member_code"]
        gym_class = context.user_data["gym_class"]

        info = {"day": day, "gym_class": gym_class, "member_code": member_code}
        reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="telegram")

        await update.message.reply_text(reply)

        reset_flow(context)
        await update.message.reply_text("تحب/ي تحجزي كلاس تاني؟ لو آه، اكتب/ي كود العضوية.")
        context.user_data["step"] = "await_code"
        return

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))