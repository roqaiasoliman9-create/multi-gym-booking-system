import json
import os
import re
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, Optional, TypedDict
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from groq import Groq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from db import (
    cancel_latest_booking,
    connect,
    create_booking,
    ensure_member,
    get_or_create_gym,
    get_waitlist_position,
    init_db,
    list_day_sessions,
    now_cairo,
    session_current_count,
    validate_membership,
    waitlist_accept,
    waitlist_add,
    waitlist_offer_next,
)

# =========================================
# Config
# =========================================

DB_PATH = "gym.sqlite3"
DEFAULT_GYM_NAME = "Default Gym"
DEFAULT_TZ = "Africa/Cairo"

EN_DAYS = {
    "Saturday", "Sunday", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday"
}



def today_english_day(tz: str = DEFAULT_TZ) -> str:
    return datetime.now(ZoneInfo(tz)).strftime("%A")


# =========================================
# Arabic normalization
# =========================================

_AR_DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670]")
_AR_TOKEN_SPLIT = re.compile(r"[^\u0600-\u06FFA-Za-z0-9]+")


def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    s = text.strip().replace("ـ", "")
    s = _AR_DIACRITICS.sub("", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ة", "ه")
    s = re.sub(r"\s+", "", s)
    return s.lower()


def fuzzy_match_arabic_term(user_text: str, choices: list[str], cutoff: float = 0.6) -> Optional[str]:
    norm_text = normalize_arabic(user_text)
    norm_choices = {normalize_arabic(choice): choice for choice in choices}

    words = norm_text.split()
    if not words:
        return None

    for word in words:
        match = get_close_matches(word, list(norm_choices.keys()), n=1, cutoff=cutoff)
        if match:
            return norm_choices[match[0]]

    return None


CLASS_ALIASES = {
    "بيلاتس": "Pilates",
    "بيلاتيس": "Pilates",
    "pilates": "Pilates",
    "زومبا": "Zumba",
    "zumba": "Zumba",
    "كروس فيت": "Cross Fit",
    "cross fit": "Cross Fit",
}

def detect_class_from_text(message: str) -> Optional[str]:
    norm_text = normalize_arabic(message)
    lower_text = message.lower()

    # exact match
    for alias, class_name in CLASS_ALIASES.items():
        if normalize_arabic(alias) in norm_text or alias.lower() in lower_text:
            return class_name

    # fuzzy fallback
    alias_keys = list(CLASS_ALIASES.keys())
    fuzzy = fuzzy_match_arabic_term(message, alias_keys, cutoff=0.65)
    if fuzzy:
        return CLASS_ALIASES[fuzzy]

    return None

# =========================================
# Day detection
# =========================================

ARABIC_DAY_SYNONYMS = {
    "السبت": "Saturday",
    "سبت": "Saturday",

    "الاحد": "Sunday",
    "الأحد": "Sunday",
    "احد": "Sunday",
    "أحد": "Sunday",
    "الحد": "Sunday",
    "حد": "Sunday",

    "الاثنين": "Monday",
    "الإثنين": "Monday",
    "اثنين": "Monday",
    "إثنين": "Monday",
    "الاتنين": "Monday",
    "اتنين": "Monday",

    "الثلاثاء": "Tuesday",
    "ثلاثاء": "Tuesday",
    "التلات": "Tuesday",
    "تلات": "Tuesday",

    "الاربعاء": "Wednesday",
    "الأربعاء": "Wednesday",
    "اربعاء": "Wednesday",
    "أربعاء": "Wednesday",
    "الاربع": "Wednesday",
    "الأربع": "Wednesday",
    "اربع": "Wednesday",

    "الخميس": "Thursday",
    "خميس": "Thursday",

    "الجمعة": "Friday",
    "جمعه": "Friday",
    "جمعة": "Friday",
}

ARABIC_DAY_SYNONYMS_NORM = {
    normalize_arabic(k): v for k, v in ARABIC_DAY_SYNONYMS.items()
}


def checkin_member_by_choice_sqlite(gym_id: int, member_code: str, choice: int) -> str:
    member_code = str(member_code).strip()
    if not member_code:
        return "من فضلك ابعتي كود العضوية."

    with connect(DB_PATH) as conn:
        init_db(conn)

        member = conn.execute("""
            SELECT id
            FROM members
            WHERE gym_id=? AND member_code=?
        """, (gym_id, member_code)).fetchone()

        if not member:
            return "❌ مش لاقية كود العضوية ده عندنا."

        member_id = int(member["id"])

        bookings = conn.execute("""
            SELECT b.id AS booking_id, b.session_id, s.class_name, s.day, s.time
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            WHERE b.gym_id=? AND b.member_id=? AND b.status='booked'
            ORDER BY s.day, s.time
        """, (gym_id, member_id)).fetchall()

        if not bookings:
            return "❌ مفيش حجز نشط لتسجيل الحضور."

        if choice < 1 or choice > len(bookings):
            return "❌ رقم الاختيار غير صحيح."

        booking = bookings[choice - 1]

        conn.execute("""
            INSERT OR REPLACE INTO attendance(gym_id, session_id, member_id, status, checkin_at, created_at)
            VALUES(?,?,?,?,?,?)
        """, (
            gym_id,
            booking["session_id"],
            member_id,
            "attended",
            now_cairo(),
            now_cairo()
        ))

        conn.execute("""
            UPDATE bookings
            SET status='attended'
            WHERE id=?
        """, (booking["booking_id"],))

        conn.commit()

        return (
            f"✅ تم تسجيل الحضور.\n"
            f"الكلاس: {booking['class_name']}\n"
            f"اليوم: {booking['day']}\n"
            f"الوقت: {booking['time']}"
        )


def is_checkin_choice_request(text: str) -> bool:
    return re.fullmatch(r"\s*\d+\s+\d{3,10}\s*", text.strip()) is not None

def process_checkin_choice_request(message: str) -> str:
    m = re.fullmatch(r"\s*(\d+)\s+(\d{3,10})\s*", message.strip())
    if not m:
        return "❌ الصيغة غير صحيحة"

    choice = int(m.group(1))
    member_code = m.group(2)

    return checkin_member_by_choice_sqlite(GYM_ID, member_code, choice)

def detect_day_from_text_ar(message: str) -> Optional[str]:
    tokens = [normalize_arabic(t) for t in _AR_TOKEN_SPLIT.split(message) if t.strip()]
    for t in tokens:
        if t in ARABIC_DAY_SYNONYMS_NORM:
            return ARABIC_DAY_SYNONYMS_NORM[t]
        if t.startswith("ال") and t[2:] in ARABIC_DAY_SYNONYMS_NORM:
            return ARABIC_DAY_SYNONYMS_NORM[t[2:]]
        if ("ال" + t) in ARABIC_DAY_SYNONYMS_NORM:
            return ARABIC_DAY_SYNONYMS_NORM["ال" + t]
    return None


def detect_day_from_text_en(message: str) -> Optional[str]:
    m = re.search(
        r"\b(Saturday|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday)\b",
        message,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    day = m.group(1).capitalize()
    return day if day in EN_DAYS else None


def detect_any_day_from_text(message: str) -> Optional[str]:
    return detect_day_from_text_ar(message) or detect_day_from_text_en(message)


# =========================================
# Class detection
# =========================================

CLASS_ALIASES = {
    "بيلاتس": "Pilates",
    "بيلاتيس": "Pilates",
    "بيلايتس": "Pilates",
    "pilates": "Pilates",

    "زومبا": "Zumba",
    "zumba": "Zumba",

    "كروس فيت": "Cross Fit",
    "كروسفيت": "Cross Fit",
    "cross fit": "Cross Fit",

    "يوجا": "Vinyasa Yoga",
    "yoga": "Vinyasa Yoga",

    "ايريل يوجا": "Aerial Yoga",
    "ايريل": "Aerial Yoga",
    "aerial yoga": "Aerial Yoga",

    "باليه دانس": "Belly Dance",
    "بيلي دانس": "Belly Dance",
    "رقص شرقي": "Belly Dance",
    "belly dance": "Belly Dance",

    "هيت": "HIIT",
    "hiit": "HIIT",

    "اكوا": "Aqua Aerobics",
    "aqua": "Aqua Aerobics",
    "aqua aerobics": "Aqua Aerobics",

    "بودي بامب": "Body Pump",
    "body pump": "Body Pump",

    "باور بول": "Power Ball",
    "power ball": "Power Ball",

    "تركس": "TRX",
    "trx": "TRX",

    "كيك بوكسينج": "Kick Boxing Beginner",
    "kick boxing": "Kick Boxing Beginner",
}


CHECKIN_WORDS = {
    "تسجيل حضور", "سجل حضور", "حضور", "checkin", "check in"
}

NO_SHOW_WORDS = {
    "عدم حضور", "لم تحضر", "نو شو", "no show"
}

ATTENDANCE_WORDS = {
    "الحضور اليوم", "اعرض الحضور", "attendance today", "attendance"
}


def is_checkin_request(text: str) -> bool:
    t = text.strip().lower()
    norm_t = normalize_arabic(text)
    return any(w.lower() in t or normalize_arabic(w) in norm_t for w in CHECKIN_WORDS)


def is_no_show_request(text: str) -> bool:
    t = text.strip().lower()
    norm_t = normalize_arabic(text)
    return any(w.lower() in t or normalize_arabic(w) in norm_t for w in NO_SHOW_WORDS)


def is_attendance_request(text: str) -> bool:
    t = text.strip().lower()
    norm_t = normalize_arabic(text)
    return any(w.lower() in t or normalize_arabic(w) in norm_t for w in ATTENDANCE_WORDS)

def process_checkin_request(message: str) -> str:
    member_code = find_member_code_in_text(message)
    if not member_code:
        return "من فضلك ابعتي كود العضوية مع طلب تسجيل الحضور. مثال: تسجيل حضور 2415"
    return checkin_member_sqlite(GYM_ID, member_code)


def process_no_show_request(message: str) -> str:
    member_code = find_member_code_in_text(message)
    if not member_code:
        return "من فضلك ابعتي كود العضوية مع الطلب. مثال: عدم حضور 2415"
    return mark_no_show_sqlite(GYM_ID, member_code)


def process_attendance_request(message: str) -> str:
    day = detect_any_day_from_text(message) or today_english_day(DEFAULT_TZ)
    return get_attendance_for_day_sqlite(GYM_ID, day)



def detect_class_from_text(message: str) -> Optional[str]:
    norm_text = normalize_arabic(message)
    lower_text = message.lower()

    for alias, class_name in CLASS_ALIASES.items():
        if normalize_arabic(alias) in norm_text:
            return class_name

    for alias, class_name in CLASS_ALIASES.items():
        if alias.lower() in lower_text:
            return class_name

    return None


# =========================================
# Utility detection
# =========================================

def find_member_code_in_text(text: str) -> Optional[str]:
    m = re.search(r"\b\d{3,10}\b", text)
    return m.group(0) if m else None


SCHEDULE_WORDS = {
    "الكلاسات اليوم", "جدول اليوم", "كلاسات اليوم", "مواعيد اليوم",
    "جدول", "الكلاسات", "المواعيد", "المتاح اليوم",
    "what's available today", "available today", "today schedule",
    "schedule", "classes today", "today classes"
}

CANCEL_WORDS = {
    "الغاء الحجز", "إلغاء الحجز", "الغي الحجز", "ألغي الحجز",
    "الغي حجزي", "ألغي حجزي", "cancel booking", "cancel", "الغاء"
}

BOOKING_STATUS_WORDS = {
    "ما هو حجزي", "ما هو الحجز", "ما حجزي", "حجزي",
    "هل عندي حجز", "هل لدي حجز", "اعرض حجوزاتي", "حجوزاتي",
    "my booking", "my bookings", "do i have a booking", "show my bookings"
}

WAITLIST_CONFIRM_WORDS = {
    "تأكيد", "اكد", "أكد", "confirm", "yes", "ok", "تمام"
}


def is_schedule_request(text: str) -> bool:
    t = text.strip().lower()
    norm_t = normalize_arabic(text)

    for word in SCHEDULE_WORDS:
        if word.lower() in t or normalize_arabic(word) in norm_t:
            return True

    if ("جدول" in text or "كلاسات" in text or "الكلاسات" in text or "schedule" in t) and detect_any_day_from_text(text):
        return True

    if ("اليوم" in text or "today" in t) and ("كلاس" in text or "كلاسات" in text or "جدول" in text or "schedule" in t):
        return True

    return False


def is_cancel_request(text: str) -> bool:
    t = text.strip().lower()
    norm_t = normalize_arabic(text)
    return any(w.lower() in t or normalize_arabic(w) in norm_t for w in CANCEL_WORDS)


def is_booking_status_request(text: str) -> bool:
    t = text.strip().lower()
    norm_t = normalize_arabic(text)
    return any(w.lower() in t or normalize_arabic(w) in norm_t for w in BOOKING_STATUS_WORDS)


def is_waitlist_confirm_request(text: str) -> bool:
    t = text.strip().lower()
    norm_t = normalize_arabic(text)
    return any(w.lower() in t or normalize_arabic(w) in norm_t for w in WAITLIST_CONFIRM_WORDS)


# =========================================
# Groq
# =========================================

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("Missing GROQ_API_KEY in .env")

client = Groq(api_key=api_key)


def extract_data_with_groq(user_message: str) -> Dict[str, Any]:
    prompt = f"""
Extract the following from the message:
1) day (must be in English: Saturday, Sunday, Monday, Tuesday, Wednesday, Thursday, Friday) OR "Not Found"
2) gym_class (the class name) OR "Not Found"
3) member_code (ID number as string or number) OR "Not Found"

Message: "{user_message}"

Return ONLY a JSON object with keys: day, gym_class, member_code.
"""
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.1-8b-instant",
        response_format={"type": "json_object"},
    )
    return json.loads(chat_completion.choices[0].message.content)


# =========================================
# Seed schedule
# =========================================

gym_db = {
    "Saturday": [
        {"time": "10:00 am", "class": "Cardio Hiit", "coach": "Linda", "current": 0, "max": 25},
        {"time": "10:30 am", "class": "Cross Fit", "coach": "Toka", "current": 20, "max": 25},
        {"time": "11:00 am", "class": "Aqua Aerobics", "coach": "Linda", "current": 25, "max": 25},
        {"time": "12:00 pm", "class": "Bungee fitness", "coach": "Toka", "current": 0, "max": 25},
        {"time": "1:00 pm", "class": "Mind & Body Yoga", "coach": "Enji", "current": 0, "max": 25},
        {"time": "7:00 pm", "class": "Power Ball", "coach": "Walaa A. Fattah", "current": 0, "max": 25},
        {"time": "8:00 pm", "class": "Cross Fit", "coach": "Walaa A. Fattah", "current": 0, "max": 25},
        {"time": "8:30 pm", "class": "Pilates", "coach": "Nada Khayal", "current": 0, "max": 25},
        {"time": "9:30 pm", "class": "Gentle Yoga Flow", "coach": "Wela", "current": 0, "max": 25},
    ],
    "Sunday": [
        {"time": "10:00 am", "class": "Shape up", "coach": "Walaa A. Elfattah", "current": 5, "max": 25},
        {"time": "10:30 am", "class": "Aqua Aerobics", "coach": "Touki", "current": 0, "max": 25},
        {"time": "11:00 am", "class": "Shape up", "coach": "Walaa A. Fattah", "current": 0, "max": 25},
        {"time": "1:30 pm", "class": "Pilates", "coach": "Walaa Fekry", "current": 0, "max": 25},
        {"time": "5:00 pm", "class": "Cross Fit", "coach": "Yasmin", "current": 0, "max": 25},
        {"time": "6:00 pm", "class": "TRX", "coach": "Yasmin", "current": 0, "max": 25},
        {"time": "7:00 pm", "class": "Pilates", "coach": "Nadya", "current": 0, "max": 25},
        {"time": "8:00 pm", "class": "Strength & Conditioning", "coach": "Nancy", "current": 0, "max": 25},
        {"time": "9:00 pm", "class": "Belly Dance", "coach": "Touki", "current": 0, "max": 25},
    ],
    "Monday": [
        {"time": "10:00 am", "class": "Pilates", "coach": "Dina Yehia", "current": 0, "max": 25},
        {"time": "10:30 am", "class": "Aqua Aerobics", "coach": "Touki", "current": 0, "max": 25},
        {"time": "11:00 am", "class": "Pilates", "coach": "Dina Yehia", "current": 0, "max": 25},
        {"time": "12:00 pm", "class": "Belly Dance", "coach": "Alaa", "current": 0, "max": 25},
        {"time": "6:00 pm", "class": "Strength & Conditioning", "coach": "Nancy", "current": 0, "max": 25},
        {"time": "7:00 pm", "class": "Zumba", "coach": "Nour", "current": 0, "max": 25},
        {"time": "7:45 pm", "class": "Belly Dance", "coach": "Nada", "current": 0, "max": 25},
        {"time": "8:00 pm", "class": "Cross Fit", "coach": "Yasmin", "current": 0, "max": 25},
        {"time": "8:30 pm", "class": "Aqua Aerobics", "coach": "Linda", "current": 0, "max": 25},
        {"time": "8:45 pm", "class": "Pilates", "coach": "Walaa Fekry", "current": 0, "max": 25},
        {"time": "9:00 pm", "class": "Kick Boxing Beginner", "coach": "Lujain", "current": 0, "max": 25},
    ],
    "Tuesday": [
        {"time": "8:00 am", "class": "Vinyasa Yoga", "coach": "Hager", "current": 0, "max": 25},
        {"time": "9:00 am", "class": "Cross Fit", "coach": "Yasmin", "current": 0, "max": 25},
        {"time": "9:30 am", "class": "Abs & Core", "coach": "Linda", "current": 0, "max": 25},
        {"time": "10:00 am", "class": "Cross Fit", "coach": "Yasmin", "current": 0, "max": 25},
        {"time": "1:00 pm", "class": "Cardio Hiit", "coach": "Dalia Hamdy", "current": 0, "max": 25},
        {"time": "6:00 pm", "class": "Aerial Yoga", "coach": "Amna", "current": 0, "max": 25},
        {"time": "7:00 pm", "class": "Belly Dance", "coach": "Mariam", "current": 0, "max": 25},
        {"time": "8:00 pm", "class": "Senior Workout", "coach": "Walaa A. Fattah", "current": 0, "max": 25},
        {"time": "9:00 pm", "class": "HIIT", "coach": "Walaa", "current": 0, "max": 25},
    ],
    "Wednesday": [
        {"time": "8:00 am", "class": "Pilates", "coach": "Yasmin", "current": 0, "max": 25},
        {"time": "10:00 am", "class": "Zumba", "coach": "Alaa", "current": 0, "max": 25},
        {"time": "10:30 am", "class": "Body Pump", "coach": "Touki", "current": 0, "max": 25},
        {"time": "11:00 am", "class": "Zumba", "coach": "Alaa", "current": 0, "max": 25},
        {"time": "6:00 pm", "class": "Vinyasa Yoga", "coach": "Hager", "current": 0, "max": 25},
        {"time": "7:00 pm", "class": "Cardio Hiit", "coach": "Dalia Hamdy", "current": 0, "max": 25},
        {"time": "8:00 pm", "class": "Strength & Conditioning", "coach": "Nancy", "current": 0, "max": 25},
        {"time": "9:00 pm", "class": "Aerial Hammock", "coach": "Sarah", "current": 0, "max": 25},
        {"time": "10:00 pm", "class": "Aerial Hammock", "coach": "Sarah", "current": 0, "max": 25},
    ],
    "Thursday": [
        {"time": "9:00 am", "class": "Power Ball", "coach": "Linda", "current": 0, "max": 25},
        {"time": "10:30 am", "class": "Belly Dance", "coach": "Yara", "current": 0, "max": 25},
        {"time": "10:30 am", "class": "Body Pump", "coach": "Touki", "current": 0, "max": 25},
        {"time": "6:00 pm", "class": "Aqua Aerobics", "coach": "Touki", "current": 0, "max": 25},
        {"time": "7:00 pm", "class": "Pilates", "coach": "Nadya", "current": 0, "max": 25},
        {"time": "8:00 pm", "class": "Zumba", "coach": "Dalia Osama", "current": 0, "max": 25},
    ],
    "Friday": [
        {"time": "5:00 pm", "class": "Body Pump", "coach": "Touki", "current": 0, "max": 25},
        {"time": "6:00 pm", "class": "Belly Dance", "coach": "Touki", "current": 0, "max": 25},
        {"time": "8:00 pm", "class": "Aerial Yoga", "coach": "Amna", "current": 0, "max": 25},
    ],
}


def seed_sessions_from_gym_db(conn, gym_id: int, schedule: dict) -> None:
    for day, items in schedule.items():
        for it in items:
            conn.execute("""
                INSERT OR IGNORE INTO sessions(gym_id, day, time, class_name, coach, capacity)
                VALUES(?,?,?,?,?,?)
            """, (gym_id, day, it["time"], it["class"], it.get("coach"), it["max"]))
    conn.commit()


# =========================================
# Core booking
# =========================================

def book_class_sqlite(gym_id: int, info: dict, source: str = "telegram") -> str:
    day = info.get("day")
    if not day or day == "Not Found" or day not in EN_DAYS:
        day = today_english_day(DEFAULT_TZ)

    requested_class = info.get("gym_class")
    member_code = str(info.get("member_code") or "").strip()

    if not requested_class or requested_class == "Not Found" or not member_code or member_code == "Not Found":
        return "❌ اكتب اسم الكلاس + كود العضوية. (اليوم اختياري)"

    with connect(DB_PATH) as conn:
        init_db(conn)

        ok, reason = validate_membership(conn, gym_id, member_code)
        if not ok:
            return f"❌ {reason}"

        member_id = ensure_member(conn, gym_id, member_code)

        rows = conn.execute("""
            SELECT id, class_name, coach, time, capacity
            FROM sessions
            WHERE gym_id=? AND day=? AND is_active=1
        """, (gym_id, day)).fetchall()

        if not rows:
            return f"مفيش جدول متاح يوم {day}."

        classes = [r["class_name"] for r in rows]
        requested = str(requested_class).strip()

        match = get_close_matches(requested.lower(), [c.lower() for c in classes], n=1, cutoff=0.6)
        if not match:
            return f"للأسف مش لاقية كلاس {requested_class} في جدول يوم {day}."

        matched_name_lower = match[0]
        session = next(r for r in rows if r["class_name"].lower() == matched_name_lower)
        session_id = int(session["id"])

        current = session_current_count(conn, gym_id, session_id)
        capacity = int(session["capacity"])

        if current < capacity:
            booking_id = create_booking(conn, gym_id, session_id, member_id, source=source)
            return (
                f"✅ تم الحجز بنجاح!\n"
                f"الكود: {member_code}\n"
                f"اليوم: {day}\n"
                f"الكلاس: {session['class_name']}\n"
                f"الوقت: {session['time']}\n"
                f"الحجز رقم: {booking_id}\n"
                f"مستنيينك يا بطلة!"
            )

        waitlist_add(conn, gym_id, session_id, member_id)
        position = get_waitlist_position(conn, gym_id, session_id, member_id)

        return (
            f"⏳ الكلاس ده ممتلئ ({capacity}/{capacity}).\n"
            f"✅ ضفتك لقائمة الانتظار.\n"
            f"🔢 ترتيبك في الانتظار: {position}\n"
            f"لو مكان اتاح هبعتلك رسالة للتأكيد."
        )


def cancel_booking_sqlite(gym_id: int, member_code: str) -> str:
    member_code = str(member_code).strip()
    if not member_code:
        return "❌ ابعتي كود العضوية."

    with connect(DB_PATH) as conn:
        init_db(conn)

        row = conn.execute("""
            SELECT id
            FROM members
            WHERE gym_id=? AND member_code=?
        """, (gym_id, member_code)).fetchone()

        if not row:
            return "❌ مش لاقية الكود ده عندنا."

        member_id = int(row["id"])
        cancelled = cancel_latest_booking(conn, gym_id, member_id)

        if not cancelled:
            return "❌ مفيش حجز نشط علشان ألغيه."

        session_id_row = conn.execute("""
            SELECT session_id
            FROM bookings
            WHERE id=?
        """, (cancelled["booking_id"],)).fetchone()

        session_id = int(session_id_row["session_id"])
        offered = waitlist_offer_next(conn, gym_id, session_id, minutes=10)

        msg = (
            f"✅ تم إلغاء الحجز.\n"
            f"{cancelled['class_name']} - {cancelled['day']} {cancelled['time']}"
        )
        if offered:
            msg += "\n📩 تم إرسال الدور لأول واحدة في الانتظار."
        return msg


# =========================================
# Schedule
# =========================================

def get_day_schedule_sqlite(gym_id: int, day: str) -> str:
    with connect(DB_PATH) as conn:
        init_db(conn)

        rows = list_day_sessions(conn, gym_id, day)

        if not rows:
            return f"مفيش كلاسات متاحة يوم {day}."

        lines = [f"📅 جدول {day}:"]
        for r in rows:
            current = session_current_count(conn, gym_id, int(r["id"]))
            capacity = int(r["capacity"])
            remaining = capacity - current
            lines.append(
                f"• {r['time']} - {r['class_name']} | المدرب: {r['coach']} | المتبقي: {remaining}/{capacity}"
            )

        lines.append("\nللحجز ابعتي: اسم الكلاس + كود العضوية + اليوم")
        return "\n".join(lines)


def process_schedule_request(message: str) -> str:
    day = detect_any_day_from_text(message)

    if not day:
        if "اليوم" in message or "today" in message.lower():
            day = today_english_day(DEFAULT_TZ)

    if not day:
        day = today_english_day(DEFAULT_TZ)

    return get_day_schedule_sqlite(GYM_ID, day)


# =========================================
# Booking status
# =========================================

def get_latest_active_booking_sqlite(gym_id: int, member_code: str) -> str:
    member_code = str(member_code).strip()
    if not member_code:
        return "من فضلك ابعتي كود العضوية للاستعلام عن الحجز."

    with connect(DB_PATH) as conn:
        init_db(conn)

        member = conn.execute("""
            SELECT id
            FROM members
            WHERE gym_id=? AND member_code=?
        """, (gym_id, member_code)).fetchone()

        if not member:
            return "❌ مش لاقية كود العضوية ده عندنا."

        member_id = int(member["id"])

        row = conn.execute("""
            SELECT b.id AS booking_id, s.class_name, s.day, s.time, s.coach
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            WHERE b.gym_id=? AND b.member_id=? AND b.status='booked'
            ORDER BY b.created_at DESC, b.id DESC
            LIMIT 1
        """, (gym_id, member_id)).fetchone()

        if not row:
            return "مفيش حجز نشط على الكود ده حاليًا."

        return (
            f"📌 حجزك الحالي:\n"
            f"الكود: {member_code}\n"
            f"اليوم: {row['day']}\n"
            f"الكلاس: {row['class_name']}\n"
            f"الوقت: {row['time']}\n"
            f"المدرب: {row['coach']}"
        )


def get_all_active_bookings_sqlite(gym_id: int, member_code: str) -> str:
    member_code = str(member_code).strip()
    if not member_code:
        return "من فضلك ابعتي كود العضوية لعرض الحجوزات."

    with connect(DB_PATH) as conn:
        init_db(conn)

        member = conn.execute("""
            SELECT id
            FROM members
            WHERE gym_id=? AND member_code=?
        """, (gym_id, member_code)).fetchone()

        if not member:
            return "❌ مش لاقية كود العضوية ده عندنا."

        member_id = int(member["id"])

        rows = conn.execute("""
            SELECT s.class_name, s.day, s.time, s.coach
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            WHERE b.gym_id=? AND b.member_id=? AND b.status='booked'
            ORDER BY s.day, s.time
        """, (gym_id, member_id)).fetchall()

        if not rows:
            return "مفيش حجوزات نشطة على الكود ده حاليًا."

        lines = [f"📋 حجوزات الكود {member_code}:"]
        for r in rows:
            lines.append(f"• {r['day']} - {r['time']} - {r['class_name']} | {r['coach']}")
        return "\n".join(lines)


def process_booking_status_request(message: str) -> str:
    member_code = find_member_code_in_text(message)
    if not member_code:
        return "من فضلك ابعتي كود العضوية للاستعلام"

    if "حجوزاتي" in message or "اعرض" in message or "my bookings" in message.lower():
        return get_all_active_bookings_sqlite(GYM_ID, member_code)

    return get_latest_active_booking_sqlite(GYM_ID, member_code)


# =========================================
# Waitlist
# =========================================

def process_waitlist_confirm_request(message: str) -> str:
    member_code = find_member_code_in_text(message)
    if not member_code:
        return "من فضلك ابعتي كود العضوية مع التأكيد. مثال: تأكيد 2415"

    with connect(DB_PATH) as conn:
        init_db(conn)

        row = conn.execute("""
            SELECT id
            FROM members
            WHERE gym_id=? AND member_code=?
        """, (GYM_ID, member_code)).fetchone()

        if not row:
            return "❌ مش لاقية كود العضوية ده عندنا."

        member_id = int(row["id"])
        accepted = waitlist_accept(conn, GYM_ID, member_id)

        if not accepted:
            return "مفيش عرض انتظار نشط على الكود ده حاليًا."

        return (
            f"✅ تم تأكيد الحجز من قائمة الانتظار.\n"
            f"الكود: {member_code}\n"
            f"اليوم: {accepted['day']}\n"
            f"الكلاس: {accepted['class_name']}\n"
            f"الوقت: {accepted['time']}\n"
            f"مستنيينك يا بطلة!"
        )


# =========================================
# Extraction
# =========================================

class AgentState(TypedDict):
    user_message: str
    extracted_info: Optional[dict]
    registration_result: str


def extraction_node(state: AgentState) -> Dict[str, Any]:
    user_msg = state["user_message"]
    info = extract_data_with_groq(user_msg) or {}

    explicit_day = detect_any_day_from_text(user_msg)
    explicit_class = detect_class_from_text(user_msg)
    explicit_code = find_member_code_in_text(user_msg)

    if explicit_day:
        info["day"] = explicit_day

    if explicit_class:
        info["gym_class"] = explicit_class

    if explicit_code:
        info["member_code"] = explicit_code

    if (not info.get("day")) or (info.get("day") == "Not Found") or (info["day"] not in EN_DAYS):
        info["day"] = today_english_day(DEFAULT_TZ)

    return {"extracted_info": info}


def booking_node(state: AgentState) -> Dict[str, Any]:
    info = state.get("extracted_info") or {}
    result = book_class_sqlite(gym_id=GYM_ID, info=info, source="whatsapp")
    return {"registration_result": result}


def build_app():
    workflow = StateGraph(AgentState)
    workflow.add_node("understand", extraction_node)
    workflow.add_node("book", booking_node)

    workflow.set_entry_point("understand")
    workflow.add_edge("understand", "book")
    workflow.add_edge("book", END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# =========================================
# Public handlers
# =========================================

def process_gym_registration(message: str, user_id: str = "user_990") -> str:
    config = {"configurable": {"thread_id": user_id}}
    initial_state: AgentState = {
        "user_message": message,
        "extracted_info": None,
        "registration_result": "",
    }
    final_state = app.invoke(initial_state, config=config)
    return final_state.get("registration_result", "")


def process_cancel_request(message: str) -> str:
    member_code = find_member_code_in_text(message)
    if not member_code:
        return "من فضلك ابعتي كود العضوية مع طلب الإلغاء"

    return cancel_booking_sqlite(GYM_ID, member_code)


def checkin_member_sqlite(gym_id: int, member_code: str) -> str:
    member_code = str(member_code).strip()
    if not member_code:
        return "من فضلك ابعتي كود العضوية."

    with connect(DB_PATH) as conn:
        init_db(conn)

        member = conn.execute("""
            SELECT id
            FROM members
            WHERE gym_id=? AND member_code=?
        """, (gym_id, member_code)).fetchone()

        if not member:
            return "❌ مش لاقية كود العضوية ده عندنا."

        member_id = int(member["id"])

        booking = conn.execute("""
            SELECT b.id AS booking_id, b.session_id, s.class_name, s.day, s.time
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            WHERE b.gym_id=? AND b.member_id=? AND b.status='booked'
            ORDER BY b.created_at DESC, b.id DESC
            LIMIT 1
        """, (gym_id, member_id)).fetchone()

        if not booking:
            return "❌ مفيش حجز نشط لتسجيل الحضور."

        conn.execute("""
            INSERT OR REPLACE INTO attendance(gym_id, session_id, member_id, status, checkin_at, created_at)
            VALUES(?,?,?,?,?,?)
        """, (
            gym_id,
            booking["session_id"],
            member_id,
            "attended",
            now_cairo(),
            now_cairo()
        ))

        conn.execute("""
            UPDATE bookings
            SET status='attended'
            WHERE id=?
        """, (booking["booking_id"],))

        conn.commit()

        return (
            f"✅ تم تسجيل الحضور.\n"
            f"الكود: {member_code}\n"
            f"الكلاس: {booking['class_name']}\n"
            f"اليوم: {booking['day']}\n"
            f"الوقت: {booking['time']}"
        )

def mark_no_show_sqlite(gym_id: int, member_code: str) -> str:
        member_code = str(member_code).strip()
        if not member_code:
            return "من فضلك ابعتي كود العضوية."

        with connect(DB_PATH) as conn:
            init_db(conn)

            member = conn.execute("""
                                  SELECT id
                                  FROM members
                                  WHERE gym_id = ?
                                    AND member_code = ?
                                  """, (gym_id, member_code)).fetchone()

            if not member:
                return "❌ مش لاقية كود العضوية ده عندنا."

            member_id = int(member["id"])

            booking = conn.execute("""
                                   SELECT b.id AS booking_id, b.session_id, s.class_name, s.day, s.time
                                   FROM bookings b
                                            JOIN sessions s ON s.id = b.session_id
                                   WHERE b.gym_id = ?
                                     AND b.member_id = ?
                                     AND b.status = 'booked'
                                   ORDER BY b.created_at DESC, b.id DESC LIMIT 1
                                   """, (gym_id, member_id)).fetchone()

            if not booking:
                return "❌ مفيش حجز نشط لتسجيل عدم الحضور."

            conn.execute("""
                INSERT OR REPLACE INTO attendance(gym_id, session_id, member_id, status, created_at)
                VALUES(?,?,?,?,?)
            """, (
                gym_id,
                booking["session_id"],
                member_id,
                "no_show",
                now_cairo()
            ))

            conn.execute("""
                         UPDATE bookings
                         SET status='no_show'
                         WHERE id = ?
                         """, (booking["booking_id"],))

            conn.commit()

            return (
                f"✅ تم تسجيل عدم الحضور.\n"
                f"الكود: {member_code}\n"
                f"الكلاس: {booking['class_name']}\n"
                f"اليوم: {booking['day']}\n"
                f"الوقت: {booking['time']}"
            )


def get_attendance_for_day_sqlite(gym_id: int, day: str) -> str:
    with connect(DB_PATH) as conn:
        init_db(conn)

        rows = conn.execute("""
            SELECT
                s.class_name,
                s.time,
                m.member_code,
                a.status,
                a.checkin_at
            FROM attendance a
            JOIN sessions s ON s.id = a.session_id
            JOIN members m ON m.id = a.member_id
            WHERE a.gym_id=? AND s.day=?
            ORDER BY s.time, s.class_name
        """, (gym_id, day)).fetchall()

        if not rows:
            return f"مفيش بيانات حضور ليوم {day}."

        lines = [f"📋 الحضور - {day}:"]
        for r in rows:
            lines.append(
                f"• {r['time']} - {r['class_name']} - الكود {r['member_code']} - {r['status']}"
            )

        return "\n".join(lines)

# =========================================
# Bootstrap
# =========================================

with connect(DB_PATH) as _conn:
    init_db(_conn)
    GYM_ID = get_or_create_gym(_conn, DEFAULT_GYM_NAME)
    seed_sessions_from_gym_db(_conn, GYM_ID, gym_db)

app = build_app()