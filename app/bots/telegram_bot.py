import os
import re
import logging
from difflib import SequenceMatcher, get_close_matches

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ContextTypes, ApplicationBuilder, MessageHandler, filters

from gym_system import (
    detect_any_day_from_text,
    today_english_day,
    book_class_sqlite,
    GYM_ID,
)

from db import connect, init_db, safe_migrate, create_admin_contact_request, list_day_sessions

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEFAULT_TZ = "Africa/Cairo"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AR_GREETINGS = {
    "اهلا", "أهلا", "هاي", "هلا", "سلام", "السلام عليكم", "سلام عليكم",
    "ازيك", "ازيك", "ازيكي", "اخبارك", "أخبارك", "ايه الاخبار", "إيه الأخبار",
    "عامل ايه", "عاملة ايه", "عامله ايه", "صباح الخير", "مساء الخير"
}

EN_GREETINGS = {
    "hello", "hi", "hey", "good morning", "good evening", "how are you"
}

EN_SMALL_TALK_GOOD = {
    "i'm good", "im good", "i am good", "good", "fine", "i'm fine", "im fine",
    "i am fine", "great", "not bad", "doing well", "well"
}

AR_SMALL_TALK_GOOD = {
    "كويس", "الحمدلله", "الحمد لله", "بخير", "تمام", "جيد",
    "انا كويس", "أنا كويس", "انا بخير", "أنا بخير", "تمام الحمدلله"
}

EN_NO_WORDS = {
    "no", "no thanks", "no thank you", "thank you", "thanks",
    "not now", "maybe later", "no thank u", "no thanks!"
}

AR_NO_WORDS = {
    "لا", "لا شكرا", "لا شكرًا", "شكرا", "شكراً", "مشكور",
    "لا حاليا", "لا حالياً", "بعدين", "لا شكرا لك"
}

EN_YES_WORDS = {
    "yes", "yeah", "yes please", "sure", "okay", "ok", "yep", "of course"
}

AR_YES_WORDS = {
    "نعم", "ايوه", "أيوه", "ايوا", "أيوة", "اكيد", "أكيد", "تمام", "ماشي"
}

RESET_RE = re.compile(r"(ابدأ من جديد|نبدأ من جديد|ريست|reset|start over|ابدأ)", re.IGNORECASE)

EN_DAYS_CANONICAL = {
    "saturday": ["saturday", "satarday", "saterday", "sat"],
    "sunday": ["sunday", "sanday", "sun"],
    "monday": ["monday", "mondey", "mondy", "mon"],
    "tuesday": ["tuesday", "tuesdy", "tuseday", "tue", "tues"],
    "wednesday": ["wednesday", "wednsday", "wensday", "wed"],
    "thursday": ["thursday", "thrusday", "thurday", "thu", "thur"],
    "friday": ["friday", "fridy", "fri"],
    "today": ["today", "now"],
}

AR_DAYS_CANONICAL = {
    "Monday": ["الاثنين", "الاتنين", "الأتنين", "اثنين", "اتنين", "الاثنين"],
    "Tuesday": ["الثلاثاء", "التلات", "التلاته", "الثلاثا", "ثلاثاء", "تلات"],
    "Wednesday": ["الاربعاء", "الأربعاء", "الاربعا", "اربعاء"],
    "Thursday": ["الخميس", "خميس"],
    "Friday": ["الجمعة", "جمعه", "جمعة"],
    "Saturday": ["السبت", "سبت"],
    "Sunday": ["الاحد", "الأحد", "احد", "أحد"],
    "today": ["اليوم", "النهارده", "نهارده", "دلوقتي"],
}

EN_CONTACT_PATTERNS = [
    "contact management",
    "contact admin",
    "contact administration",
    "contact support",
    "contact the manager",
    "contact manager",
    "i want to contact management",
    "i want to contact admin",
    "i want to contact the manager",
    "i want to speak to the manager",
    "talk to management",
    "talk to the manager",
    "speak to the manager",
]

AR_CONTACT_PATTERNS = [
    "اريد التواصل مع الادارة",
    "أريد التواصل مع الإدارة",
    "عايز اتواصل مع الادارة",
    "عاوزه اتواصل مع الادارة",
    "التواصل مع الادارة",
    "التواصل مع الإدارة",
    "اريد التواصل مع المدير",
    "أريد التواصل مع المدير",
    "عايز اكلم الادارة",
    "عاوزه اكلم الادارة",
    "اكلم الادارة",
    "أكلم الإدارة",
    "اتواصل مع الادارة",
    "أتواصل مع الإدارة",
    "اتواصل مع المدير",
    "أتواصل مع المدير",
    "اكلم الدعم",
    "التواصل مع الدعم",
    "اتواصل مع الادار",
    "التواصل مع الادار",
]

AR_CLASS_ALIASES = {
    "yoga": [
        "يوجا", "يوغا", "يوجه", "يوغاا", "yoga", "ygaa", "yooga", "yogaa",
        "yoga class", "yoga session", "يوجا كلاس", "كلاس يوجا", "يوغا كلاس"
    ],

    "zumba": [
        "زومبا", "زومبه", "زمبا", "زومباا", "zumba", "zubma", "zamba", "zomba",
        "zumba class", "كلاس زومبا", "زومبا كلاس"
    ],

    "crossfit": [
        "كروس فيت", "كروس فت", "كروسفت", "كروس فيتت", "كروس فيت ",
        "crossfit", "cross fit", "crossfitt", "crossfut", "crosfit", "crssfit",
        "كلاس كروس فيت", "crossfit class"
    ],

    "boxing": [
        "بوكس", "بوكسنج", "بوكسينج", "بوكسينغ", "boxing", "box", "boxingg",
        "boxing class", "كلاس بوكس", "كلاس بوكسنج"
    ],

    "pilates": [
        "بيلاتس", "بلاتس", "بلاتيس", "بيليتس", "pilates", "pilats", "plates",
        "pilates class", "كلاس بيلاتس"
    ],

    "spinning": [
        "سبين", "سبيننج", "سبننغ", "سبينينج", "spinning", "spin", "spining", "spinnng",
        "spinning class", "كلاس سبين", "كلاس سبيننج"
    ],

    "hiit": [
        "هيت", "هت", "هييت", "hiit", "hit", "hiiit", "hitt",
        "hiit class", "كلاس هيت"
    ],

    "strength": [
        "سترينث", "سترينجث", "سترنجث", "strength", "strenght", "strenth",
        "strength training", "كلاس سترينث"
    ],

    "conditioning": [
        "كونديشننج", "كونديشن", "كونديشيننج", "conditioning", "conditoning", "conditionng",
        "conditioning class", "كلاس كونديشننج"
    ],

    "cardio": [
        "كارديو", "كارديوو", "cardio", "cardeo", "kardio",
        "cardio class", "كلاس كارديو"
    ],

    "abs": [
        "بطن", "تمارين بطن", "abs", "abbs", "ab workout",
        "abs class", "كلاس بطن"
    ],

    "legs": [
        "ارجل", "رجل", "تمارين رجل", "legs", "leg day",
        "legs class", "كلاس رجل"
    ],

    "upper body": [
        "جزء علوي", "اعلى الجسم", "upper body", "upperbody",
        "upper body class"
    ],

    "lower body": [
        "جزء سفلي", "اسفل الجسم", "lower body", "lowerbody",
        "lower body class"
    ],

    "full body": [
        "فل بودي", "full body", "fullbody", "فول بودي",
        "full body class", "كلاس فل بودي"
    ],

    "trx": [
        "تي ار اكس", "trx", "t r x", "trx class", "كلاس trx"
    ],

    "kickboxing": [
        "كيك بوكس", "كيك بوكسينج", "kickboxing", "kick boxing", "kikboxing",
        "kickboxing class", "كلاس كيك بوكس"
    ],

    "stretching": [
        "استرتش", "استرتشينج", "stretch", "stretching", "streching",
        "stretching class", "كلاس استرتش"
    ],
}


CODE_RE = re.compile(r"\b\d{3,6}\b")
PHONE_RE = re.compile(r"\+?\d[\d\s\-]{7,}\d")


def detect_lang(text: str) -> str | None:
    text = text.strip()
    if re.search(r"[a-zA-Z]", text):
        return "en"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    return None


def resolve_lang(text: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    detected = detect_lang(text)
    if detected:
        context.user_data["lang"] = detected
        return detected
    return context.user_data.get("lang", "ar")


def tr(lang: str, ar: str, en: str) -> str:
    return en if lang == "en" else ar


def normalize_ar(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_en(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_text(text: str, lang: str | None = None) -> str:
    if lang == "en":
        return normalize_en(text)
    if lang == "ar":
        return normalize_ar(text)

    detected = detect_lang(text)
    if detected == "en":
        return normalize_en(text)
    return normalize_ar(text)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_in(text: str, patterns: list[str] | set[str], lang: str, threshold: float = 0.82) -> bool:
    t = normalize_text(text, lang)

    for p in patterns:
        np = normalize_text(p, lang)
        if np in t or t in np:
            return True
        if similarity(t, np) >= threshold:
            return True

    words = t.split()
    for p in patterns:
        np = normalize_text(p, lang)
        p_words = np.split()
        if not p_words:
            continue
        size = len(p_words)
        if len(words) >= size:
            for i in range(len(words) - size + 1):
                chunk = " ".join(words[i:i + size])
                if similarity(chunk, np) >= threshold:
                    return True
    return False


def is_greeting(text: str, lang: str) -> bool:
    patterns = EN_GREETINGS if lang == "en" else AR_GREETINGS
    return fuzzy_in(text, patterns, lang, threshold=0.78)


def is_small_talk_good(text: str, lang: str) -> bool:
    patterns = EN_SMALL_TALK_GOOD if lang == "en" else AR_SMALL_TALK_GOOD
    return fuzzy_in(text, patterns, lang, threshold=0.80)


def is_yes(text: str, lang: str) -> bool:
    patterns = EN_YES_WORDS if lang == "en" else AR_YES_WORDS
    return fuzzy_in(text, patterns, lang, threshold=0.86)


def is_no(text: str, lang: str) -> bool:
    patterns = EN_NO_WORDS if lang == "en" else AR_NO_WORDS
    return fuzzy_in(text, patterns, lang, threshold=0.82)


def wants_contact_management(text: str, lang: str) -> bool:
    patterns = EN_CONTACT_PATTERNS if lang == "en" else AR_CONTACT_PATTERNS
    return fuzzy_in(text, patterns, lang, threshold=0.74)


def extract_membership_code(text: str) -> str | None:
    matches = CODE_RE.findall(text)
    return matches[-1] if matches else None


def extract_phone(text: str) -> str | None:
    matches = PHONE_RE.findall(text)
    if not matches:
        return None
    cleaned = [re.sub(r"[^\d+]", "", m) for m in matches]
    cleaned.sort(key=len, reverse=True)
    return cleaned[0]


def extract_name_phone_membership(text: str) -> tuple[str | None, str | None, str | None]:
    phone = extract_phone(text)
    membership_code = extract_membership_code(text)

    cleaned = text
    if phone:
        cleaned = cleaned.replace(phone, " ")

    if membership_code:
        cleaned = re.sub(rf"\b{re.escape(membership_code)}\b", " ", cleaned)

    cleaned = re.sub(
        r"(اسمي|my name is|name is|name|رقمي|phone|number|رقم تلفوني|رقمي هو|membership|membership code|member code|code|كود العضوية|رقم العضوية)",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r"[:,-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned or None, phone, membership_code


def detect_day_fuzzy(text: str, lang: str) -> str | None:
    raw = normalize_text(text, lang)

    if lang == "en":
        for canonical, variants in EN_DAYS_CANONICAL.items():
            for v in variants:
                nv = normalize_en(v)
                if nv in raw or similarity(raw, nv) >= 0.84:
                    if canonical == "today":
                        return today_english_day(DEFAULT_TZ)
                    return canonical.capitalize()
    else:
        for canonical, variants in AR_DAYS_CANONICAL.items():
            for v in variants:
                nv = normalize_ar(v)
                if nv in raw or similarity(raw, nv) >= 0.80:
                    if canonical == "today":
                        return today_english_day(DEFAULT_TZ)
                    return canonical

    builtin = detect_any_day_from_text(text)
    if builtin:
        return builtin
    return None


def remove_day_words(text: str, lang: str) -> str:
    cleaned = text
    maps = EN_DAYS_CANONICAL if lang == "en" else AR_DAYS_CANONICAL
    for variants in maps.values():
        for v in variants:
            cleaned = re.sub(re.escape(v), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def canonical_hint_from_alias(raw_text: str) -> str | None:
    t = normalize_ar(raw_text)
    for canonical, aliases in AR_CLASS_ALIASES.items():
        for alias in aliases:
            na = normalize_ar(alias)
            if na in t or similarity(t, na) >= 0.72:
                return canonical
    return None


def best_class_match(raw_class: str, available_classes: list[str], lang: str) -> str | None:
    if not available_classes:
        return None

    raw_norm = normalize_text(raw_class, lang)

    exact_map = {}
    for cls in available_classes:
        exact_map[normalize_en(cls)] = cls

    if lang == "en":
        close = get_close_matches(raw_norm, list(exact_map.keys()), n=1, cutoff=0.72)
        if close:
            return exact_map[close[0]]

    alias_hint = canonical_hint_from_alias(raw_class)
    if alias_hint:
        best = None
        best_score = 0.0
        for cls in available_classes:
            score = similarity(alias_hint, normalize_en(cls))
            if score > best_score:
                best_score = score
                best = cls
        if best and best_score >= 0.45:
            return best

    best = None
    best_score = 0.0
    for cls in available_classes:
        score = similarity(raw_norm, normalize_en(cls))
        if lang == "ar":
            score = max(
                score,
                similarity(normalize_ar(raw_class), normalize_ar(cls)),
                similarity(normalize_ar(raw_class).replace(" ", ""), normalize_ar(cls).replace(" ", "")),
            )
        if score > best_score:
            best_score = score
            best = cls

    if best and best_score >= (0.58 if lang == "ar" else 0.72):
        return best

    return None


def looks_like_class_request(text: str, lang: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if extract_phone(t):
        return False
    cleaned = remove_day_words(t, lang)
    return len(cleaned) >= 2


def format_booking_reply(reply: str, lang: str, gym_class: str | None = None, day: str | None = None) -> str:
    if not reply:
        return tr(
            lang,
            "حدث خطأ غير متوقع أثناء تنفيذ الطلب.",
            "An unexpected error occurred while processing your request."
        )

    nr = normalize_ar(reply)

    if "للاسف" in nr and ("مش لاقيه" in nr or "غير متاح" in nr):
        if lang == "en":
            return f"Sorry, {gym_class or 'this class'} is not available on {day or 'the selected day'}."
        return reply

    if lang == "ar":
        return reply

    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    mapped = []

    for line in lines:
        n = normalize_ar(line)
        if "تم الحجز بنجاح" in n:
            mapped.append("✅ Booking confirmed successfully!")
        elif n.startswith("الكود"):
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            mapped.append(f"Code: {value}")
        elif n.startswith("اليوم"):
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            mapped.append(f"Day: {value}")
        elif n.startswith("الكلاس"):
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            mapped.append(f"Class: {value}")
        elif n.startswith("الوقت"):
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            mapped.append(f"Time: {value}")
        elif n.startswith("الحجز رقم"):
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            mapped.append(f"Booking No.: {value}")
        elif "مستنيينك" in n:
            mapped.append("See you there! 💪")
        else:
            mapped.append(line)

    return "\n".join(mapped)


def save_admin_request(
    name: str,
    phone: str,
    membership_code: str | None,
    language: str,
    telegram_user: str
) -> None:
    with connect("gym.sqlite3") as conn:
        init_db(conn)
        safe_migrate(conn)
        create_admin_contact_request(
            conn=conn,
            gym_id=GYM_ID,
            source="telegram",
            full_name=name,
            phone=phone,
            membership_code=membership_code,
            language=language,
            platform_user=telegram_user,
        )


def reset_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in [
        "step", "member_code", "last_member_code", "gym_class", "day",
        "lang", "post_booking", "admin_contact_mode",
        "admin_name", "admin_phone", "admin_member_code"
    ]:
        context.user_data.pop(key, None)


def clear_admin_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ["admin_contact_mode", "admin_name", "admin_phone", "admin_member_code", "step"]:
        context.user_data.pop(key, None)


def get_missing_admin_fields(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    missing = []
    if not context.user_data.get("admin_name"):
        missing.append("name")
    if not context.user_data.get("admin_phone"):
        missing.append("phone")
    if not context.user_data.get("admin_member_code"):
        missing.append("membership")
    return missing


def admin_missing_message(lang: str, missing: list[str]) -> str:
    if lang == "en":
        labels = {"name": "your name", "phone": "your phone number", "membership": "your membership code"}
        return f"Please send {', '.join(labels[m] for m in missing)}."
    labels = {"name": "اسمك", "phone": "رقم هاتفك", "membership": "رقم العضوية"}
    return f"من فضلك أرسل {'، '.join(labels[m] for m in missing)}."


async def process_booking(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, incoming_text: str):
    raw_text = incoming_text.strip()
    detected_day = detect_day_fuzzy(raw_text, lang)
    gym_class_raw = remove_day_words(raw_text, lang)

    if len(gym_class_raw) < 2:
        await update.message.reply_text(
            tr(lang, "اكتب/ي اسم الكلاس بشكل أوضح لو سمحتي.", "Please enter the class name more clearly.")
        )
        return

    if detected_day:
        with connect("gym.sqlite3") as conn:
            init_db(conn)
            safe_migrate(conn)
            sessions = list_day_sessions(conn, GYM_ID, detected_day)
            available_classes = [row["class_name"] for row in sessions]

        resolved_class = best_class_match(gym_class_raw, available_classes, lang) or gym_class_raw
        context.user_data["gym_class"] = resolved_class
        context.user_data["day"] = detected_day

        member_code = context.user_data.get("member_code")
        if not member_code:
            context.user_data["step"] = "await_code"
            await update.message.reply_text(
                tr(lang, "من فضلك أرسل رقم العضوية أولًا.", "Please send your membership code first.")
            )
            return

        info = {
            "day": detected_day,
            "gym_class": resolved_class,
            "member_code": member_code
        }

        reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="telegram")
        reply = format_booking_reply(reply, lang, gym_class=resolved_class, day=detected_day)
        await update.message.reply_text(reply)

        context.user_data["last_member_code"] = member_code
        context.user_data["post_booking"] = True
        context.user_data["step"] = None
        context.user_data.pop("gym_class", None)
        context.user_data.pop("day", None)

        await update.message.reply_text(
            tr(lang, "عاوزة تحجزي كلاس تاني؟", "Would you like to book another class?")
        )
        return

    context.user_data["gym_class"] = gym_class_raw
    context.user_data["step"] = "await_day"
    await update.message.reply_text(
        tr(lang, "محتاجة تحجزي أي يوم؟", "Which day would you like?")
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    telegram_user = update.effective_user.username or str(update.effective_user.id)
    lang = resolve_lang(text, context)

    if RESET_RE.search(text):
        reset_flow(context)
        context.user_data["lang"] = lang
        context.user_data["step"] = "await_code"
        await update.message.reply_text(
            tr(lang, "تمام. اكتب/ي كود العضوية عشان نبدأ الحجز.", "Done. Please enter your membership code to start booking.")
        )
        return

    if wants_contact_management(text, lang):
        context.user_data["admin_contact_mode"] = True
        context.user_data["step"] = "await_admin_contact"
        context.user_data["post_booking"] = False
        await update.message.reply_text(
            tr(
                lang,
                "أكيد. أرسل/ي الاسم ورقم الهاتف ورقم العضوية في رسالة واحدة، أو على عدة رسائل.",
                "Sure. Please send your name, phone number, and membership code in one message, or across multiple messages."
            )
        )
        return

    step = context.user_data.get("step")

    if is_greeting(text, lang) and step is None and not context.user_data.get("admin_contact_mode"):
        context.user_data["step"] = "await_small_talk"
        await update.message.reply_text(
            tr(
                lang,
                "أهلًا 🌷 نورت/ي الجيم. ازيك؟",
                "Hello 🌷 Glad to see you here. How are you?"
            )
        )
        return

    if step == "await_small_talk":
        await update.message.reply_text(
            tr(
                lang,
                "ده حقيقي يسعدني ✨ اكتب/ي كود العضوية عشان نبدأ الحجز.",
                "Glad to hear that ✨ Please enter your membership code to start booking."
            ) if is_small_talk_good(text, lang) else
            tr(
                lang,
                "أتمنى ليكي يوم جميل ✨ اكتب/ي كود العضوية عشان نبدأ الحجز.",
                "Hope you have a lovely day ✨ Please enter your membership code to start booking."
            )
        )
        context.user_data["step"] = "await_code"
        return

    if step == "await_admin_contact":
        name, phone, membership_code = extract_name_phone_membership(text)

        if name and not context.user_data.get("admin_name"):
            context.user_data["admin_name"] = name
        if phone and not context.user_data.get("admin_phone"):
            context.user_data["admin_phone"] = phone
        if membership_code and not context.user_data.get("admin_member_code"):
            context.user_data["admin_member_code"] = membership_code

        missing = get_missing_admin_fields(context)
        if missing:
            await update.message.reply_text(admin_missing_message(lang, missing))
            return

        try:
            save_admin_request(
                name=context.user_data.get("admin_name"),
                phone=context.user_data.get("admin_phone"),
                membership_code=context.user_data.get("admin_member_code"),
                language=lang,
                telegram_user=telegram_user
            )
            clear_admin_flow(context)

            await update.message.reply_text(
                tr(
                    lang,
                    "تم رفع طلبك إلى الإدارة بنجاح ✅\nهيتم التواصل معك قريبًا.",
                    "Your request has been forwarded to management successfully ✅\nThey will contact you soon."
                )
            )
            await update.message.reply_text(
                tr(
                    lang,
                    "شكرًا لك 🌷 احنا هنا دايمًا لخدمتك، ونتمنى ليكي يوم جميل وتمرينة بيرفيكت 💪",
                    "Thank you 🌷 We’re always here for you. Wishing you a great day and a strong workout 💪"
                )
            )
            return
        except Exception as e:
            logger.exception("Error while saving admin request: %s", e)
            await update.message.reply_text(
                tr(
                    lang,
                    "حدث خطأ أثناء تسجيل طلبك. حاول/ي مرة أخرى.",
                    "An error occurred while registering your request. Please try again."
                )
            )
            return

    if context.user_data.get("post_booking") is True:
        if is_yes(text, lang):
            context.user_data["post_booking"] = False
            if context.user_data.get("last_member_code"):
                context.user_data["member_code"] = context.user_data["last_member_code"]
            context.user_data["step"] = "await_class"
            await update.message.reply_text(
                tr(lang, "ممتاز ✅  محتاجة تحجزي كلاس ايه؟", "Great ✅ What class would you like to book?")
            )
            return

        if is_no(text, lang):
            context.user_data["post_booking"] = False
            context.user_data["step"] = None
            await update.message.reply_text(
                tr(
                    lang,
                    "العفو 🌷 لو احتاجتي أي حاجة بعدين، أنا هنا دايمًا.",
                    "You’re very welcome 🌷 If you need anything later, I’m always here."
                )
            )
            await update.message.reply_text(
                tr(lang, "نتمنى لك يومًا رائعًا وتمرينًا موفقًا 💪", "Wishing you a great day and an excellent workout 💪")
            )
            return

        if wants_contact_management(text, lang):
            context.user_data["admin_contact_mode"] = True
            context.user_data["post_booking"] = False
            context.user_data["step"] = "await_admin_contact"
            await update.message.reply_text(
                tr(
                    lang,
                    "أكيد. أرسل/ي الاسم ورقم الهاتف ورقم العضوية في رسالة واحدة، أو على عدة رسائل.",
                    "Sure. Please send your name, phone number, and membership code in one message, or across multiple messages."
                )
            )
            return

        if looks_like_class_request(text, lang):
            context.user_data["post_booking"] = False
            if context.user_data.get("last_member_code"):
                context.user_data["member_code"] = context.user_data["last_member_code"]
            context.user_data["step"] = "await_class"
            await process_booking(update, context, lang, text)
            return

    if step is None:
        context.user_data["step"] = "await_code"
        step = "await_code"

    if step == "await_code":
        code = extract_membership_code(text)
        if not code:
            await update.message.reply_text(
                tr(lang, "محتاج/ة كود العضوية بالأرقام فقط.", "I need your membership code in numbers only.")
            )
            return

        context.user_data["member_code"] = code
        context.user_data["last_member_code"] = code
        context.user_data["step"] = "await_class"

        await update.message.reply_text(
            tr(lang, "تمام ✅ محتاجة تحجزي كلاس ايه؟", "Great ✅ What class would you like to book?")
        )
        return

    if step == "await_class":
        await process_booking(update, context, lang, text)
        return

    if step == "await_day":
        day = detect_day_fuzzy(text, lang)
        if not day:
            await update.message.reply_text(
                tr(lang, "من فضلك اكتب/ي اليوم بشكل أوضح.", "Please write the day more clearly.")
            )
            return

        member_code = context.user_data.get("member_code")
        gym_class_raw = context.user_data.get("gym_class")

        if not member_code:
            context.user_data["step"] = "await_code"
            await update.message.reply_text(
                tr(lang, "من فضلك أرسل رقم العضوية أولًا.", "Please send your membership code first.")
            )
            return

        with connect("gym.sqlite3") as conn:
            init_db(conn)
            safe_migrate(conn)
            sessions = list_day_sessions(conn, GYM_ID, day)
            available_classes = [row["class_name"] for row in sessions]

        resolved_class = best_class_match(gym_class_raw, available_classes, lang) or gym_class_raw

        info = {
            "day": day,
            "gym_class": resolved_class,
            "member_code": member_code
        }

        reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="telegram")
        reply = format_booking_reply(reply, lang, gym_class=resolved_class, day=day)
        await update.message.reply_text(reply)

        context.user_data["last_member_code"] = member_code
        context.user_data["post_booking"] = True
        context.user_data["step"] = None
        context.user_data.pop("gym_class", None)
        context.user_data.pop("day", None)

        await update.message.reply_text(
            tr(lang, "هل تريد/ين حجز كلاس آخر؟", "Would you like to book another class?")
        )
        return


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing in .env file")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Telegram bot is running...")
    application.run_polling()