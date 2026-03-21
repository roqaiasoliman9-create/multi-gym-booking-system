import os
import requests
from flask import Flask, request
from dotenv import load_dotenv

from gym_system import (
    process_gym_registration,
    is_schedule_request,
    process_schedule_request,
    is_cancel_request,
    process_cancel_request,
    is_booking_status_request,
    process_booking_status_request,
    is_waitlist_confirm_request,
    process_waitlist_confirm_request,
    is_checkin_choice_request,
    process_checkin_choice_request,
    is_checkin_request,
    process_checkin_request,
    is_no_show_request,
    process_no_show_request,
    is_attendance_request,
    process_attendance_request,
)

load_dotenv()

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_verify_token")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

GREETING_WORDS = {
    # عربي
    "هاي", "هاي هاي", "هالو", "هلا", "هلا والله", "هلا بيك", "هلا بيكم",
    "اهلا", "أهلا", "اهلا بيك", "أهلا بيك", "اهلا وسهلا", "أهلا وسهلا",
    "مرحبا", "مرحبا بيك", "مرحبا بيكم",
    "السلام", "السلام عليكم", "السلام عليكم ورحمة الله",
    "صباح الخير", "صباح النور",
    "مساء الخير", "مساء النور",
    "ازيك", "إزيك", "عامل ايه", "عاملة ايه",
    "اخبارك", "أخبارك ايه",

    # English
    "hello", "hi", "hey", "hey there",
    "good morning", "good evening", "good afternoon",
    "yo", "sup", "what's up"
}

HELP_WORDS = {
    # عربي
    "مساعدة", "ساعدني", "ممكن مساعدة", "عايز مساعدة", "محتاج مساعدة",
    "ازاي", "إزاي", "كيف", "كيفية", "شرح",
    "مش فاهم", "مش فاهمة", "مش عارف", "مش عارفة",
    "اعمل ايه", "اعمل اي", "ابدأ ازاي",
    "عايز احجز", "محتاج احجز", "محتاجة احجز",
    "ازاي احجز", "طريقة الحجز",
    "ايه النظام", "النظام ايه", "ايه المطلوب",
    "ايه الكلاسات", "الكلاسات ايه",
    "عندكم ايه", "متاح ايه",
    "جدول الكلاسات", "الجدول",
    "مواعيد الكلاسات", "المواعيد",
    "تفاصيل", "معلومات", "info",

    # English
    "help", "support", "assist",
    "how", "how to", "how does it work",
    "what can i do", "what should i do",
    "booking", "how to book",
    "info", "information", "details",
    "schedule", "classes", "class schedule"
}




def is_greeting(text: str) -> bool:
    t = text.strip().lower()
    return t in {w.lower() for w in GREETING_WORDS}


def is_help_request(text: str) -> bool:
    t = text.strip().lower()
    return t in {w.lower() for w in HELP_WORDS}


def get_welcome_message() -> str:
    return (
        "أهلاً بيكِ في نظام حجز الكلاسات 💚\n"
        "للحجز ابعتي الرسالة بهذا الشكل:\n"
        "اسم الكلاس + كود العضوية + اليوم \n\n"

    )


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


@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    print("VERIFY REQUEST:", mode, token, challenge)

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
                            "من فضلك ابعتي رسالة نصية تحتوي على كود العضوية واسم الكلاس واليوم."
                        )
                        continue

                    text_body = message.get("text", {}).get("body", "").strip()
                    if not text_body:
                        continue

                    print("USER MESSAGE:", text_body)

                    if is_greeting(text_body):
                        send_whatsapp_text(from_number, get_welcome_message())
                        continue

                    if is_help_request(text_body):
                        send_whatsapp_text(from_number, get_welcome_message())
                        continue

                    if is_schedule_request(text_body):
                        reply = process_schedule_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    if is_cancel_request(text_body):
                        reply = process_cancel_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    if is_booking_status_request(text_body):
                        reply = process_booking_status_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    if is_waitlist_confirm_request(text_body):
                        reply = process_waitlist_confirm_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    if is_checkin_choice_request(text_body):
                        reply = process_checkin_choice_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    if is_checkin_request(text_body):
                        reply = process_checkin_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    if is_no_show_request(text_body):
                        reply = process_no_show_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    if is_attendance_request(text_body):
                        reply = process_attendance_request(text_body)
                        send_whatsapp_text(from_number, reply)
                        continue

                    reply = process_gym_registration(text_body, user_id=from_number)
                    send_whatsapp_text(from_number, reply)

    except Exception as e:
        print("WEBHOOK ERROR:", str(e))

    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)