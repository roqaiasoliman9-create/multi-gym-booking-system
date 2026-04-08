# الحجز
import sqlite3
from database import book_spot, DB_NAME
from difflib import get_close_matches


def find_class(day, requested_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM classes WHERE day=?", (day,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        return None

    class_map = {name.lower(): cid for cid, name in results}
    match = get_close_matches(requested_name.lower(), class_map.keys(), n=1, cutoff=0.6)

    if not match:
        return None

    return class_map[match[0]]


def process_booking(day, class_name, member_code):
    class_id = find_class(day, class_name)
    if not class_id:
        return "❌ لم يتم العثور على الكلاس."

    success = book_spot(member_code, class_id)
    if success:
        return "✅ تم الحجز بنجاح!"
    else:
        return "❌ الكلاس ممتلئ."