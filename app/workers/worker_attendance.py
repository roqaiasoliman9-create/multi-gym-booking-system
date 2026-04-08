from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from db import connect, init_db, safe_migrate

TZ = "Africa/Cairo"
DB_PATH = "gym.sqlite3"
GRACE_MINUTES = 15

def now_cairo() -> datetime:
    return datetime.now(ZoneInfo(TZ))

def mark_no_show():
    with connect(DB_PATH) as conn:
        init_db(conn); safe_migrate(conn)

        cutoff = (now_cairo() - timedelta(minutes=GRACE_MINUTES)).isoformat(timespec="seconds")

        rows = conn.execute("""
            SELECT b.id AS booking_id, b.gym_id, b.member_id, b.session_id, s.start_at
            FROM bookings b
            JOIN sessions s ON s.id=b.session_id
            LEFT JOIN attendance a
              ON a.gym_id=b.gym_id AND a.session_id=b.session_id AND a.member_id=b.member_id
            WHERE b.status='booked'
              AND s.start_at IS NOT NULL
              AND s.start_at <= ?
              AND a.id IS NULL
        """, (cutoff,)).fetchall()

        for r in rows:
            conn.execute("""
                INSERT OR IGNORE INTO attendance(gym_id, session_id, member_id, status, created_at)
                VALUES(?,?,?,?,?)
            """, (r["gym_id"], r["session_id"], r["member_id"], "no_show", now_cairo().isoformat(timespec="seconds")))
            conn.execute("""
                UPDATE bookings
                SET status='no_show'
                WHERE id=? AND status='booked'
            """, (r["booking_id"],))

        conn.commit()
        return len(rows)

if __name__ == "__main__":
    n = mark_no_show()
    print("no_show marked:", n)

