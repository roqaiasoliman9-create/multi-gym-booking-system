import time
from db import connect, init_db, get_upcoming_bookings, now_cairo_dt
from whatsapp_utils import send_whatsapp_text

GYM_ID = 1


def format_reminder(r):
    return (
        f"⏰ تذكير بالكلاس\n"
        f"الكلاس: {r['class_name']}\n"
        f"اليوم: {r['day']}\n"
        f"الوقت: {r['time']}\n"
        f"نتمنى نشوفك 💙"
    )


def run():
    print("Reminder worker started...")

    while True:
        with connect() as conn:
            init_db(conn)

            bookings = get_upcoming_bookings(conn, GYM_ID, minutes_before=60)

            for b in bookings:
                if not b["phone"]:
                    continue

                message = format_reminder(b)

                try:
                    send_whatsapp_text(b["phone"], message)
                    print(f"Sent reminder to {b['phone']}")
                except Exception as e:
                    print("Error:", e)

        time.sleep(60)


if __name__ == "__main__":
    run()