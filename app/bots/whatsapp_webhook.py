import os
import re
import requests
from flask import Flask, request
from dotenv import load_dotenv

from db import connect, init_db, create_admin_contact_request
from gym_system import (
    GYM_ID,
    detect_any_day_from_text,
    detect_class_from_text,
    find_member_code_in_text,
    today_english_day,
    book_class_sqlite,
)

load_dotenv()

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_verify_token")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
DEFAULT_TZ = "Africa/Cairo"

# جلسات المستخدمين داخل الذاكرة
user_sessions = {}

GREETINGS = {
    "hi", "hello", "hey", "good morning", "good evening",
    "اهلا", "أهلا", "هاي", "هلا", "السلام عليكم", "سلام عليكم",
    "صباح الخير", "مساء الخير"
}

EN_FEELING_GOOD = {
    "good", "fine", "great", "i am good", "i'm good", "im good",
    "i am fine", "i'm fine", "im fine", "not bad", "doing well"
}

AR_FEELING_GOOD = {
    "كويس", "الحمدلله", "الحمد لله", "بخير", "تمام", "جيد",
    "انا كويس", "أنا كويس", "انا بخير", "أنا بخير"
}

EN_YES = {"yes", "yeah", "ok", "okay", "sure", "yes please", "yep"}
AR_YES = {"نعم", "ايوه", "أيوه", "ايوا", "أيوة", "تمام", "اكيد", "أكيد"}

EN_NO = {"no", "no thanks", "no thank you", "not now", "maybe later"}
AR_NO = {"لا", "لا شكرا", "لا شكرًا", "لا حاليا", "لا حالياً", "بعدين"}

EN_CONTACT_WORDS = {
    "contact management", "contact admin", "contact administration",
    "i want to contact management", "i want to contact admin",
    "speak to management", "talk to management", "contact support"
}

AR_CONTACT_WORDS = {
    "اريد التواصل مع الادارة", "أريد التواصل مع الإدارة",
    "التواصل مع الادارة", "التواصل مع الإدارة",
    "اكلم الادارة", "أكلم الإدارة",
    "اتواصل مع الادارة", "أتواصل مع الإدارة",
    "اكلم الدعم", "أتواصل مع الدعم", "التواصل مع الدعم"
}

PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{7,}\d)")
RESET_RE = re.compile(r"(ابدأ من جديد|نبدأ من جديد|ريست|reset|start over|ابدأ)", re.IGNORECASE)


def detect_lang(text: str) -> str:
    return "en" if re.search(r"[a-zA-Z]", text or "") else "ar"


def tr(lang: str, ar: str, en: str) -> str:
    return en if lang == "en" else ar


def normalize_ar(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)
    return text


def is_greeting(text: str) -> bool:
    t = normalize_ar(text)
    return any(normalize_ar(g) == t for g in GREETINGS)


def is_feeling_good(text: str, lang: str) -> bool:
    t = normalize_ar(text)
    if lang == "en":
        return t in {normalize_ar(x) for x in EN_FEELING_GOOD}
    return t in {normalize_ar(x) for x in AR_FEELING_GOOD}


def is_yes(text: str, lang: str) -> bool:
    t = normalize_ar(text)
    if lang == "en":
        return t in {normalize_ar(x) for x in EN_YES}
    return t in {normalize_ar(x) for x in AR_YES}


def is_no(text: str, lang: str) -> bool:
    t = normalize_ar(text)
    if lang == "en":
        return t in {normalize_ar(x) for x in EN_NO}
    return t in {normalize_ar(x) for x in AR_NO}


def wants_contact_management(text: str, lang: str) -> bool:
    t = normalize_ar(text)
    if lang == "en":
        return t in {normalize_ar(x) for x in EN_CONTACT_WORDS}
    return t in {normalize_ar(x) for x in AR_CONTACT_WORDS}


def extract_code(text: str) -> str | None:
    m = re.search(r"\b(\d{3,})\b", text or "")
    return m.group(1) if m else None


def extract_phone(text: str) -> str | None:
    m = PHONE_RE.search(text or "")
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1))


def remove_day_words(text: str) -> str:
    text = re.sub(
        r"\b(saturday|sunday|monday|tuesday|wednesday|thursday|friday|today|now)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(السبت|الاحد|الأحد|الاثنين|الثلاثاء|الاربعاء|الأربعاء|الخميس|الجمعة|اليوم|النهارده|نهارده)",
        "",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def reset_session(user_id: str):
    user_sessions.pop(user_id, None)


def save_admin_request(name: str, phone: str, language: str, whatsapp_user: str, member_code: str):
    with connect("gym.sqlite3") as conn:
        init_db(conn)
        create_admin_contact_request(
            conn=conn,
            gym_id=GYM_ID,
            source="whatsapp",
            full_name=name,
            phone=phone,
            language=language,
            platform_user=f"{whatsapp_user} | member_code={member_code}",
        )


def format_booking_reply(reply: str, lang: str) -> str:
    if lang == "ar":
        return reply

    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    mapped = []

    for line in lines:
        n = normalize_ar(line)

        if "تم الحجز بنجاح" in n:
            mapped.append("✅ Booking confirmed successfully!")
        elif n.startswith("الكود:"):
            mapped.append(f"Code: {line.split(':', 1)[1].strip()}")
        elif n.startswith("اليوم:"):
            mapped.append(f"Day: {line.split(':', 1)[1].strip()}")
        elif n.startswith("الكلاس:"):
            mapped.append(f"Class: {line.split(':', 1)[1].strip()}")
        elif n.startswith("الوقت:"):
            mapped.append(f"Time: {line.split(':', 1)[1].strip()}")
        elif n.startswith("الحجز رقم:"):
            mapped.append(f"Booking No.: {line.split(':', 1)[1].strip()}")
        elif "مستنيينك يا بطله" in n or "مستنيينك يا بطل" in n:
            mapped.append("See you there! 💪")
        elif "الكلاس ده ممتلئ" in n:
            mapped.append("⏳ This class is full.")
        elif "ضفتك لقائمه الانتظار" in n:
            mapped.append("✅ You were added to the waitlist.")
        elif "ترتيبك في الانتظار" in n:
            mapped.append(f"Waitlist position: {line.split(':', 1)[1].strip()}")
        else:
            mapped.append(line)

    return "\n".join(mapped)


def send_whatsapp_text(to_number: str, text: str):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text},
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("SEND STATUS:", r.status_code)
    print("SEND RESPONSE:", r.text)


def process_whatsapp_flow(user_id: str, text: str) -> str:
    session = user_sessions.get(user_id, {})
    msg_lang = detect_lang(text)

    if session.get("lang") is None:
        session["lang"] = msg_lang

    lang = session.get("lang", msg_lang)
    step = session.get("step")

    # reset
    if RESET_RE.search(text):
        reset_session(user_id)
        user_sessions[user_id] = {"lang": msg_lang, "step": "await_code"}
        return tr(
            msg_lang,
            "تمام. اكتب/ي كود العضوية علشان نبدأ الحجز.",
            "Done. Please enter your membership code to start booking."
        )

    # direct admin trigger
    if wants_contact_management(text, msg_lang):
        session = {"lang": msg_lang, "step": "admin_name"}
        user_sessions[user_id] = session
        return tr(
            msg_lang,
            "أكيد. اكتب/ي اسمك أولًا.",
            "Sure. Please enter your name first."
        )

    # greeting
    if is_greeting(text) and step is None:
        session["lang"] = msg_lang
        session["step"] = "await_small_talk"
        user_sessions[user_id] = session
        return tr(
            msg_lang,
            "أهلًا! كيف حالك؟ 👋",
            "Hello! How are you? 👋"
        )

    # small talk
    if step == "await_small_talk":
        session["step"] = "await_code"
        user_sessions[user_id] = session
        if is_feeling_good(text, lang):
            return tr(
                lang,
                "يسعدني هذا 🌷 اكتب/ي كود العضوية لبدء الحجز.",
                "Glad to hear that 😊 Please enter your membership code to start booking."
            )
        return tr(
            lang,
            "أتمنى لك يومًا جميلًا ✨ اكتب/ي كود العضوية لبدء الحجز.",
            "Hope you have a lovely day ✨ Please enter your membership code to start booking."
        )

    # admin flow
    if step == "admin_name":
        session["admin_name"] = text.strip()
        session["step"] = "admin_member_code"
        user_sessions[user_id] = session
        return tr(
            lang,
            "اكتب/ي رقم العضوية.",
            "Please enter your membership code."
        )

    if step == "admin_member_code":
        code = extract_code(text)
        if not code:
            return tr(
                lang,
                "من فضلك اكتب/ي رقم العضوية بالأرقام فقط.",
                "Please enter your membership code in numbers only."
            )
        session["admin_member_code"] = code
        session["step"] = "admin_phone"
        user_sessions[user_id] = session
        return tr(
            lang,
            "اكتب/ي رقم هاتفك.",
            "Please enter your phone number."
        )

    if step == "admin_phone":
        phone = extract_phone(text)
        if not phone:
            return tr(
                lang,
                "من فضلك اكتب/ي رقم الهاتف بشكل صحيح.",
                "Please enter a valid phone number."
            )

        save_admin_request(
            name=session.get("admin_name", ""),
            phone=phone,
            language=lang,
            whatsapp_user=user_id,
            member_code=session.get("admin_member_code", ""),
        )
        reset_session(user_id)
        return tr(
            lang,
            "تم تسجيل طلبك بنجاح، وسيتم إرساله إلى الإدارة، وسوف تتواصل معك قريبًا.",
            "Your request has been recorded successfully and sent to management. They will contact you soon."
        )

    # after booking flow
    if session.get("post_booking") is True:
        if is_yes(text, msg_lang):
            session["lang"] = msg_lang
            session["post_booking"] = False
            session["step"] = "await_class"
            user_sessions[user_id] = session
            return tr(
                msg_lang,
                "ممتاز ✅ ما اسم الكلاس الذي تريد/ين حجزه؟",
                "Great ✅ What class would you like to book?"
            )

        if is_no(text, msg_lang):
            reset_session(user_id)
            return tr(
                msg_lang,
                "على الرحب والسعة 🌷 إذا احتجت/ي أي شيء لاحقًا أنا هنا.",
                "You’re very welcome 🌷 If you need anything later, I’m here."
            )

    # if no step, allow direct smart extraction
    # if no step, smart extraction for one-message or partial-message booking
    if step is None:
        direct_code = extract_code(text)
        direct_class = detect_class_from_text(text)
        direct_day = detect_any_day_from_text(text)

        if normalize_ar(text) in {"اليوم", "النهارده", "نهارده"} or text.strip().lower() in {"today", "now"}:
            direct_day = today_english_day(DEFAULT_TZ)

        # 1) all data موجودة -> احجز مباشرة
        if direct_code and direct_class and direct_day:
            info = {
                "day": direct_day,
                "gym_class": direct_class,
                "member_code": direct_code,
            }
            reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="whatsapp")
            reply = format_booking_reply(reply, msg_lang)

            user_sessions[user_id] = {
                "lang": msg_lang,
                "post_booking": True,
                "step": None,
            }

            return reply + "\n\n" + tr(
                msg_lang,
                "هل تريد/ين حجز كلاس آخر؟",
                "Would you like to book another class?"
            )

        # 2) كلاس + يوم بدون كود -> اسأل عن الكود فقط
        if direct_class and direct_day and not direct_code:
            session["lang"] = msg_lang
            session["gym_class"] = direct_class
            session["day"] = direct_day
            session["step"] = "await_code_after_day_and_class"
            user_sessions[user_id] = session
            return tr(
                msg_lang,
                "تمام ✅ اكتب/ي كود العضوية.",
                "Great ✅ Please enter your membership code."
            )

        # 3) كود + كلاس بدون يوم -> اسأل عن اليوم فقط
        if direct_code and direct_class and not direct_day:
            session["lang"] = msg_lang
            session["member_code"] = direct_code
            session["gym_class"] = direct_class
            session["step"] = "await_day"
            user_sessions[user_id] = session
            return tr(
                msg_lang,
                "ما اليوم المطلوب؟",
                "Which day would you like?"
            )

        # 4) كود + يوم بدون كلاس -> اسأل عن الكلاس فقط
        if direct_code and direct_day and not direct_class:
            session["lang"] = msg_lang
            session["member_code"] = direct_code
            session["day"] = direct_day
            session["step"] = "await_class_after_code_and_day"
            user_sessions[user_id] = session
            return tr(
                msg_lang,
                "ما اسم الكلاس الذي تريد/ين حجزه؟",
                "What class would you like to book?"
            )

        # 5) كلاس فقط -> اسأل عن اليوم
        if direct_class and not direct_day and not direct_code:
            session["lang"] = msg_lang
            session["gym_class"] = direct_class
            session["step"] = "await_day_only"
            user_sessions[user_id] = session
            return tr(
                msg_lang,
                "ما اليوم المطلوب لهذا الكلاس؟",
                "Which day would you like for this class?"
            )

        # 6) كود فقط -> اسأل عن الكلاس
        if direct_code and not direct_class and not direct_day:
            session["lang"] = msg_lang
            session["member_code"] = direct_code
            session["step"] = "await_class"
            user_sessions[user_id] = session
            return tr(
                msg_lang,
                "تمام ✅ ما اسم الكلاس الذي تريد/ين حجزه؟",
                "Great ✅ What class would you like to book?"
            )

        # 7) يوم فقط -> اسأل عن الكلاس أولًا
        if direct_day and not direct_class and not direct_code:
            session["lang"] = msg_lang
            session["day"] = direct_day
            session["step"] = "await_class_after_day_only"
            user_sessions[user_id] = session
            return tr(
                msg_lang,
                "ما اسم الكلاس الذي تريد/ين حجزه؟",
                "What class would you like to book?"
            )

        # 8) لا شيء واضح -> ابدأ بالكود
        session["lang"] = msg_lang
        session["step"] = "await_code"
        user_sessions[user_id] = session


    # booking flow
    step = user_sessions[user_id].get("step")
    lang = user_sessions[user_id].get("lang", msg_lang)

    if step == "await_code":
        code = extract_code(text)
        if not code:
            return tr(
                lang,
                "محتاج/ة كود العضوية بالأرقام فقط.",
                "I need your membership code in numbers only."
            )

        session["member_code"] = code
        session["step"] = "await_class"
        user_sessions[user_id] = session
        return tr(
            lang,
            "تمام ✅ ما اسم الكلاس الذي تريد/ين حجزه؟",
            "Great ✅ What class would you like to book?"
        )

    if step == "await_class":
        raw_text = text.strip()
        code = session.get("member_code")

        if code:
            raw_text = raw_text.replace(code, "").strip()

        detected_day = detect_any_day_from_text(raw_text)
        if raw_text.lower() in {"today", "now"} or raw_text in {"اليوم", "النهارده", "نهارده"}:
            detected_day = today_english_day(DEFAULT_TZ)

        gym_class = remove_day_words(raw_text)
        gym_class = detect_class_from_text(gym_class) or gym_class

        if len(str(gym_class).strip()) < 2:
            return tr(
                lang,
                "اكتب/ي اسم الكلاس بشكل واضح.",
                "Please enter the class name clearly."
            )

        session["gym_class"] = gym_class

        if detected_day:
            info = {
                "day": detected_day,
                "gym_class": gym_class,
                "member_code": session["member_code"],
            }
            reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="whatsapp")
            reply = format_booking_reply(reply, lang)

            user_sessions[user_id] = {
                "lang": lang,
                "post_booking": True,
                "step": None,
            }
            return reply + "\n\n" + tr(
                lang,
                "هل تريد/ين حجز كلاس آخر؟",
                "Would you like to book another class?"
            )

        session["step"] = "await_day"
        user_sessions[user_id] = session
        return tr(
            lang,
            "ما اليوم المطلوب؟",
            "Which day would you like?"
        )

    if step == "await_day_only":
        day = detect_any_day_from_text(text)
        if not day:
            return tr(
                lang,
                "من فضلك اكتب/ي اليوم بشكل واضح.",
                "Please enter the day clearly."
            )

        if not session.get("gym_class"):
            session["step"] = "await_class"
            user_sessions[user_id] = session
            return tr(
                lang,
                "ما اسم الكلاس الذي تريد/ين حجزه؟",
                "What class would you like to book?"
            )

        if not session.get("member_code"):
            session["day"] = day
            session["step"] = "await_code_after_day"
            user_sessions[user_id] = session
            return tr(
                lang,
                "تمام ✅ اكتب/ي كود العضوية.",
                "Great ✅ Please enter your membership code."
            )

    if step == "await_code_after_day":
        code = extract_code(text)
        if not code:
            return tr(
                lang,
                "محتاج/ة كود العضوية بالأرقام فقط.",
                "I need your membership code in numbers only."
            )

        info = {
            "day": session.get("day") or today_english_day(DEFAULT_TZ),
            "gym_class": session.get("gym_class"),
            "member_code": code,
        }
        reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="whatsapp")
        reply = format_booking_reply(reply, lang)

        user_sessions[user_id] = {
            "lang": lang,
            "post_booking": True,
            "step": None,
        }
        return reply + "\n\n" + tr(
            lang,
            "هل تريد/ين حجز كلاس آخر؟",
            "Would you like to book another class?"
        )

    if step == "await_day":
        t = text.strip().lower()
        if t in {"today", "now", "اليوم", "النهارده", "نهارده"}:
            day = today_english_day(DEFAULT_TZ)
        else:
            day = detect_any_day_from_text(text)

        if not day:
            return tr(
                lang,
                "من فضلك اكتب/ي اليوم بشكل واضح.",
                "Please enter the day clearly."
            )

        info = {
            "day": day,
            "gym_class": session.get("gym_class"),
            "member_code": session.get("member_code"),
        }
        reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="whatsapp")
        reply = format_booking_reply(reply, lang)

        user_sessions[user_id] = {
            "lang": lang,
            "post_booking": True,
            "step": None,
        }
        return reply + "\n\n" + tr(
            lang,
            "هل تريد/ين حجز كلاس آخر؟",
            "Would you like to book another class?"
        )

    if step == "await_code_after_day_and_class":
        code = extract_code(text)
        if not code:
            return tr(
                lang,
                "محتاج/ة كود العضوية بالأرقام فقط.",
                "I need your membership code in numbers only."
            )

        info = {
            "day": session.get("day") or today_english_day(DEFAULT_TZ),
            "gym_class": session.get("gym_class"),
            "member_code": code,
        }
        reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="whatsapp")
        reply = format_booking_reply(reply, lang)

        user_sessions[user_id] = {
            "lang": lang,
            "post_booking": True,
            "step": None,
        }
        return reply + "\n\n" + tr(
            lang,
            "هل تريد/ين حجز كلاس آخر؟",
            "Would you like to book another class?"
        )

    if step == "await_class_after_code_and_day":
        gym_class = detect_class_from_text(text) or remove_day_words(text)
        if len(str(gym_class).strip()) < 2:
            return tr(
                lang,
                "اكتب/ي اسم الكلاس بشكل واضح.",
                "Please enter the class name clearly."
            )

        info = {
            "day": session.get("day") or today_english_day(DEFAULT_TZ),
            "gym_class": gym_class,
            "member_code": session.get("member_code"),
        }
        reply = book_class_sqlite(gym_id=GYM_ID, info=info, source="whatsapp")
        reply = format_booking_reply(reply, lang)

        user_sessions[user_id] = {
            "lang": lang,
            "post_booking": True,
            "step": None,
        }
        return reply + "\n\n" + tr(
            lang,
            "هل تريد/ين حجز كلاس آخر؟",
            "Would you like to book another class?"
        )

    if step == "await_class_after_day_only":
        gym_class = detect_class_from_text(text) or remove_day_words(text)
        if len(str(gym_class).strip()) < 2:
            return tr(
                lang,
                "اكتب/ي اسم الكلاس بشكل واضح.",
                "Please enter the class name clearly."
            )

        session["gym_class"] = gym_class
        session["step"] = "await_code_after_day_and_class"
        user_sessions[user_id] = session
        return tr(
            lang,
            "تمام ✅ اكتب/ي كود العضوية.",
            "Great ✅ Please enter your membership code."
        )


    return tr(
        lang,
        "لم أفهم طلبك، اكتب/ي: ابدأ من جديد",
        "I couldn't understand your request. Type: reset"
    )


@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return str(challenge), 200

    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    print("INCOMING WEBHOOK:", data)

    try:
        if not data:
            return "no data", 200

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for message in messages:
                    from_number = message.get("from")
                    msg_type = message.get("type")

                    if msg_type != "text":
                        send_whatsapp_text(
                            from_number,
                            "Please send a text message only."
                        )
                        continue

                    text_body = message.get("text", {}).get("body", "").strip()
                    if not text_body:
                        continue

                    print("USER MESSAGE:", text_body)

                    reply = process_whatsapp_flow(from_number, text_body)
                    print("BOT REPLY:", reply)
                    send_whatsapp_text(from_number, reply)

    except Exception as e:
        import traceback
        print("WEBHOOK ERROR:", str(e))
        traceback.print_exc()

    return "ok", 200


if __name__ == "__main__":
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise ValueError("WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID is missing in .env")

    app.run(host="0.0.0.0", port=5001, debug=False)