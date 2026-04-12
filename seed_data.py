"""
seed_data.py
============
Run once to populate the gym database with realistic demo data.
Automatically detects which columns exist — safe to run on any schema version.

Usage:
    python seed_data.py
"""

import sqlite3
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = "database/gym.sqlite3"
TZ = "Africa/Cairo"

def now():
    return datetime.now(ZoneInfo(TZ)).isoformat(timespec="seconds")

def past(days=0, hours=0, minutes=0):
    dt = datetime.now(ZoneInfo(TZ)) - timedelta(days=days, hours=hours, minutes=minutes)
    return dt.isoformat(timespec="seconds")

def table_columns(conn, table):
    """Return set of column names for a table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}

def safe_insert(conn, table, data: dict):
    """Insert only columns that exist in the table."""
    cols = table_columns(conn, table)
    filtered = {k: v for k, v in data.items() if k in cols}
    keys = ", ".join(filtered.keys())
    placeholders = ", ".join(["?"] * len(filtered))
    conn.execute(f"INSERT INTO {table}({keys}) VALUES({placeholders})", list(filtered.values()))

def safe_insert_or_ignore(conn, table, data: dict):
    cols = table_columns(conn, table)
    filtered = {k: v for k, v in data.items() if k in cols}
    keys = ", ".join(filtered.keys())
    placeholders = ", ".join(["?"] * len(filtered))
    conn.execute(f"INSERT OR IGNORE INTO {table}({keys}) VALUES({placeholders})", list(filtered.values()))

def safe_insert_or_replace(conn, table, data: dict):
    cols = table_columns(conn, table)
    filtered = {k: v for k, v in data.items() if k in cols}
    keys = ", ".join(filtered.keys())
    placeholders = ", ".join(["?"] * len(filtered))
    conn.execute(f"INSERT OR REPLACE INTO {table}({keys}) VALUES({placeholders})", list(filtered.values()))

# ── Demo Data ─────────────────────────────────────────────────────────────────
DAYS = ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

CLASSES = [
    {"name": "CrossFit",       "capacity": 15},
    {"name": "Yoga",           "capacity": 20},
    {"name": "Zumba",          "capacity": 25},
    {"name": "Boxing",         "capacity": 12},
    {"name": "Pilates",        "capacity": 18},
    {"name": "Spinning",       "capacity": 20},
    {"name": "HIIT",           "capacity": 16},
    {"name": "Strength",       "capacity": 14},
]

COACHES = ["Ahmed Hassan", "Sara Mohamed", "Omar Khalil", "Nada Ibrahim", "Youssef Ali"]

TIMES = ["07:00", "08:30", "10:00", "11:30", "13:00", "17:00", "18:30", "20:00"]

MEMBER_NAMES = [
    "Layla Ahmed", "Mohamed Karim", "Nour Hassan", "Yasmin Omar",
    "Khaled Ibrahim", "Dina Youssef", "Amr Samir", "Rania Tarek",
    "Hany Mostafa", "Salma Adel", "Tamer Fawzy", "Aya Mahmoud",
    "Sherif Nasser", "Mona Elgamal", "Bassem Wahba", "Heba Soliman",
    "Amir Refaat", "Doaa Essam", "Wael Gamal", "Nadia Farouk",
    "Karim Abdelaziz", "Reem Hamdy", "Tarek Mourad", "Mariam Fouad",
    "Sameh Lotfy", "Ghada Samy", "Hazem Nour", "Inas Helmy",
    "Mazen Farid", "Passant Saad",
]

SOURCES = ["telegram", "whatsapp"]

CONTACT_NAMES = [
    ("Ali Mostafa",  "+201001234567"),
    ("Fatma Saeed",  "+201112345678"),
    ("Hassan Omar",  "+201223456789"),
    ("Menna Tarek",  "+201334567890"),
    ("Samir Adel",   "+201445678901"),
]


def seed(conn):
    print("🌱 Seeding demo data...")
    print(f"   Database: {DB_PATH}\n")

    # ── Show existing columns ────────────────────────────────────────────────
    for tbl in ["gyms", "members", "sessions", "bookings", "waitlist", "attendance", "admin_contact_requests"]:
        try:
            cols = table_columns(conn, tbl)
            print(f"   {tbl}: {sorted(cols)}")
        except:
            print(f"   {tbl}: ❌ not found")
    print()

    # ── Gym ──────────────────────────────────────────────────────────────────
    conn.execute("DELETE FROM gyms")
    safe_insert(conn, "gyms", {"name": "PowerZone Gym", "created_at": past(30)})
    gym_id = conn.execute("SELECT id FROM gyms LIMIT 1").fetchone()[0]
    print(f"  ✅ Gym created — id={gym_id}")

    # ── Members ───────────────────────────────────────────────────────────────
    conn.execute("DELETE FROM members WHERE gym_id=?", (gym_id,))
    member_ids = []
    for i, name in enumerate(MEMBER_NAMES):
        code  = f"M{str(i+1).zfill(3)}"
        phone = f"+2010{random.randint(10000000, 99999999)}"
        safe_insert_or_ignore(conn, "members", {
            "gym_id": gym_id, "member_code": code, "full_name": name,
            "phone": phone, "status": "active", "created_at": past(random.randint(1, 60))
        })
        row = conn.execute(
            "SELECT id FROM members WHERE gym_id=? AND member_code=?", (gym_id, code)
        ).fetchone()
        if row:
            member_ids.append(row[0])
    print(f"  ✅ {len(member_ids)} members created")

    # ── Sessions ──────────────────────────────────────────────────────────────
    conn.execute("DELETE FROM sessions WHERE gym_id=?", (gym_id,))
    for day in DAYS:
        day_classes = random.sample(CLASSES, k=random.randint(3, 5))
        day_times   = random.sample(TIMES, k=len(day_classes))
        for cls, t in zip(day_classes, day_times):
            safe_insert(conn, "sessions", {
                "gym_id": gym_id, "day": day, "time": t, "start_at": t,
                "class_name": cls["name"], "coach": random.choice(COACHES),
                "capacity": cls["capacity"], "is_active": 1,
                "created_at": past(30)
            })

    all_sessions = conn.execute(
        "SELECT id, day, class_name, capacity FROM sessions WHERE gym_id=?", (gym_id,)
    ).fetchall()
    print(f"  ✅ {len(all_sessions)} sessions created")

    # ── Bookings ──────────────────────────────────────────────────────────────
    conn.execute("DELETE FROM bookings WHERE gym_id=?", (gym_id,))
    booking_ids = []
    booked_pairs = set()

    for session in all_sessions:
        sid, day, cls_name, capacity = session
        fill   = random.randint(int(capacity * 0.5), capacity)
        chosen = random.sample(member_ids, min(fill, len(member_ids)))
        for mid in chosen:
            if (sid, mid) in booked_pairs:
                continue
            booked_pairs.add((sid, mid))
            safe_insert_or_ignore(conn, "bookings", {
                "gym_id": gym_id, "session_id": sid, "member_id": mid,
                "status": "booked", "source": random.choice(SOURCES),
                "created_at": past(days=random.randint(0, 14), hours=random.randint(0, 12))
            })
            bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            booking_ids.append((bid, sid, mid))

    print(f"  ✅ {len(booking_ids)} bookings created")

    # ── Waitlist ──────────────────────────────────────────────────────────────
    conn.execute("DELETE FROM waitlist WHERE gym_id=?", (gym_id,))
    full_sessions = [
        s for s in all_sessions
        if conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE gym_id=? AND session_id=? AND status='booked'",
            (gym_id, s[0])
        ).fetchone()[0] >= s[3]
    ]
    wl_count = 0
    for session in random.sample(full_sessions, min(4, len(full_sessions))):
        sid = session[0]
        for mid in random.sample(member_ids, k=random.randint(2, 4)):
            if (sid, mid) in booked_pairs:
                continue
            status = random.choice(["waiting", "waiting", "offered"])
            try:
                safe_insert_or_ignore(conn, "waitlist", {
                    "gym_id": gym_id, "session_id": sid, "member_id": mid,
                    "status": status,
                    "created_at": past(days=random.randint(0, 3)),
                    "offered_until": past(hours=2) if status == "offered" else None
                })
                wl_count += 1
            except:
                pass
    print(f"  ✅ {wl_count} waitlist entries created")

    # ── Attendance ────────────────────────────────────────────────────────────
    conn.execute("DELETE FROM attendance WHERE gym_id=?", (gym_id,))
    att_count = 0
    past_sessions = random.sample(all_sessions, min(15, len(all_sessions)))
    for session in past_sessions:
        sid = session[0]
        session_bookings = conn.execute(
            "SELECT id, member_id FROM bookings WHERE gym_id=? AND session_id=? AND status='booked'",
            (gym_id, sid)
        ).fetchall()
        for bid, mid in session_bookings:
            outcome = random.choices(["attended", "no_show"], weights=[80, 20])[0]
            try:
                safe_insert_or_replace(conn, "attendance", {
                    "gym_id": gym_id, "session_id": sid, "member_id": mid,
                    "status": outcome,
                    "checkin_at": past(days=random.randint(1, 7)) if outcome == "attended" else None,
                    "created_at": past(days=random.randint(1, 7))
                })
                conn.execute("UPDATE bookings SET status=? WHERE id=?", (outcome, bid))
                att_count += 1
            except:
                pass
    print(f"  ✅ {att_count} attendance records created")

    # ── Admin Contact Requests ────────────────────────────────────────────────
    conn.execute("DELETE FROM admin_contact_requests WHERE gym_id=?", (gym_id,))
    statuses  = ["new", "new", "new", "in_progress", "contacted", "resolved"]
    languages = ["ar", "ar", "en"]
    for name, phone in CONTACT_NAMES:
        source = random.choice(SOURCES)
        safe_insert(conn, "admin_contact_requests", {
            "gym_id": gym_id, "source": source,
            "platform_user": f"user_{name.split()[0].lower()}_{random.randint(100,999)}",
            "full_name": name, "phone": phone,
            "language": random.choice(languages),
            "status": random.choice(statuses),
            "created_at": past(days=random.randint(0, 5), hours=random.randint(0, 12))
        })
    print(f"  ✅ {len(CONTACT_NAMES)} admin requests created")

    conn.commit()
    print(f"""
🎉 Demo data seeded successfully!
   Gym        : PowerZone Gym (id={gym_id})
   Members    : {len(member_ids)}
   Sessions   : {len(all_sessions)} across all days
   Bookings   : {len(booking_ids)}
   Waitlist   : {wl_count}
   Attendance : {att_count}
   Requests   : {len(CONTACT_NAMES)}

▶  Now run:
   streamlit run app/dashboard/admin_dashboard.py
""")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    seed(conn)
    conn.close()
