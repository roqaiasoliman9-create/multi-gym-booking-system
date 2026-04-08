from db import connect, init_db, now_cairo

DB_PATH = "gym.sqlite3"

def run_reminders(send_func):
    """
    send_func(member_id, text) -> sends message via Telegram/WhatsApp
    """
    with connect(DB_PATH) as conn:
        init_db(conn)
        safe_migrate(conn)
        rows = conn.execute("""
            SELECT r.id, r.booking_id, b.member_id, s.class_name, s.day, s.time
            FROM reminders r
            JOIN bookings b ON b.id = r.booking_id
            JOIN sessions s ON s.id = b.session_id
            WHERE r.status='pending' AND r.send_at <= ?
              AND b.status='booked'
            ORDER BY r.send_at ASC
            LIMIT 50
        """, (now_cairo(),)).fetchall()

        for r in rows:
            text = f"⏰ تذكير: {r['class_name']} - {r['day']} {r['time']}"
            try:
                send_func(int(r["member_id"]), text)
                conn.execute("UPDATE reminders SET status='sent' WHERE id=?", (r["id"],))
            except Exception:
                conn.execute("UPDATE reminders SET status='failed' WHERE id=?", (r["id"],))
        conn.commit()