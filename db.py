import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional


# =========================================
# Time helpers
# =========================================

TZ = "Africa/Cairo"


def get_upcoming_bookings(conn, gym_id: int, minutes_before: int = 60):
    now = now_cairo_dt()
    target = now + timedelta(minutes=minutes_before)

    rows = conn.execute("""
        SELECT
            b.id AS booking_id,
            m.member_code,
            m.phone,
            s.class_name,
            s.day,
            s.time,
            s.id AS session_id
        FROM bookings b
        JOIN members m ON m.id = b.member_id
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=? AND b.status='booked'
    """, (gym_id,)).fetchall()

    result = []

    for r in rows:

        try:
            session_dt = datetime.strptime(f"{r['day']} {r['time']}", "%A %I:%M %p")
            session_dt = session_dt.replace(
                year=now.year,
                month=now.month,
                day=now.day,
                tzinfo=ZoneInfo(TZ)
            )
        except:
            continue

        diff = (session_dt - now).total_seconds() / 60

        if 0 <= diff <= minutes_before:
            result.append(dict(r))

    return result


def now_cairo_dt() -> datetime:
    return datetime.now(ZoneInfo(TZ))


def now_cairo() -> str:
    return now_cairo_dt().isoformat(timespec="seconds")


# =========================================
# Connection
# =========================================

def connect(db_path: str = "gym.sqlite3") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# =========================================
# Schema
# =========================================

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS gyms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        timezone TEXT NOT NULL DEFAULT 'Africa/Cairo',
        is_active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gym_id INTEGER NOT NULL,
        channel_type TEXT NOT NULL,
        channel_key TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        UNIQUE(channel_type, channel_key),
        FOREIGN KEY (gym_id) REFERENCES gyms(id)
    );

    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gym_id INTEGER NOT NULL,
        member_code TEXT NOT NULL,
        external_member_id TEXT,
        full_name TEXT,
        phone TEXT,
        telegram_chat_id TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        UNIQUE(gym_id, member_code),
        FOREIGN KEY (gym_id) REFERENCES gyms(id)
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gym_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        time TEXT NOT NULL,
        start_at TEXT,
        class_name TEXT NOT NULL,
        coach TEXT,
        capacity INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        UNIQUE(gym_id, day, time, class_name),
        FOREIGN KEY (gym_id) REFERENCES gyms(id)
    );

    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gym_id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        cancelled_at TEXT,
        source TEXT NOT NULL DEFAULT 'telegram',
        FOREIGN KEY (gym_id) REFERENCES gyms(id),
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (member_id) REFERENCES members(id)
    );

    CREATE INDEX IF NOT EXISTS idx_bookings_lookup
    ON bookings(gym_id, session_id, member_id, status);

    CREATE TABLE IF NOT EXISTS waitlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gym_id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        offered_until TEXT,
        UNIQUE(gym_id, session_id, member_id),
        FOREIGN KEY (gym_id) REFERENCES gyms(id),
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (member_id) REFERENCES members(id)
    );

    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gym_id INTEGER NOT NULL,
        booking_id INTEGER NOT NULL,
        send_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY (gym_id) REFERENCES gyms(id),
        FOREIGN KEY (booking_id) REFERENCES bookings(id)
    );

    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gym_id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        checkin_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(gym_id, session_id, member_id),
        FOREIGN KEY (gym_id) REFERENCES gyms(id),
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (member_id) REFERENCES members(id)
    );

    CREATE TABLE IF NOT EXISTS gym_settings (
        gym_id INTEGER PRIMARY KEY,
        cancel_cutoff_minutes INTEGER NOT NULL DEFAULT 60,
        max_bookings_per_day INTEGER NOT NULL DEFAULT 2,
        no_show_limit INTEGER NOT NULL DEFAULT 5,
        reminder_hours_1 INTEGER NOT NULL DEFAULT 6,
        reminder_hours_2 INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (gym_id) REFERENCES gyms(id)
    );
    """)
    conn.commit()


# =========================================
# Migrations
# =========================================

def migrate_v1(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE members ADD COLUMN telegram_chat_id TEXT;")
    conn.commit()


def migrate_v2(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE sessions ADD COLUMN start_at TEXT;")
    conn.commit()


def safe_migrate(conn: sqlite3.Connection) -> None:
    for fn in (migrate_v1, migrate_v2):
        try:
            fn(conn)
        except sqlite3.OperationalError:
            pass


# =========================================
# Gym helpers
# =========================================

def get_or_create_gym(conn: sqlite3.Connection, name: str = "Default Gym") -> int:
    row = conn.execute(
        "SELECT id FROM gyms WHERE name=?",
        (name,)
    ).fetchone()

    if row:
        return int(row["id"])

    conn.execute(
        "INSERT INTO gyms(name, timezone) VALUES(?, ?)",
        (name, TZ)
    )
    gym_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    conn.execute(
        "INSERT OR IGNORE INTO gym_settings(gym_id) VALUES(?)",
        (gym_id,)
    )
    conn.commit()
    return gym_id


# =========================================
# Member helpers
# =========================================

def ensure_member(conn: sqlite3.Connection, gym_id: int, member_code: str) -> int:
    row = conn.execute("""
        SELECT id, status
        FROM members
        WHERE gym_id=? AND member_code=?
    """, (gym_id, member_code)).fetchone()

    if row:
        return int(row["id"])

    conn.execute("""
        INSERT INTO members(gym_id, member_code, created_at)
        VALUES(?,?,?)
    """, (gym_id, member_code, now_cairo()))
    conn.commit()

    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def get_member_by_code(conn: sqlite3.Connection, gym_id: int, member_code: str) -> Optional[sqlite3.Row]:
    return conn.execute("""
        SELECT id, member_code, status, telegram_chat_id
        FROM members
        WHERE gym_id=? AND member_code=?
    """, (gym_id, member_code)).fetchone()


def upsert_member_chat_id(conn: sqlite3.Connection, gym_id: int, member_code: str, chat_id: str) -> None:
    conn.execute("""
        UPDATE members
        SET telegram_chat_id=?
        WHERE gym_id=? AND member_code=?
    """, (chat_id, gym_id, member_code))
    conn.commit()


def validate_membership(conn: sqlite3.Connection, gym_id: int, member_code: str) -> tuple[bool, str]:
    row = conn.execute("""
        SELECT status
        FROM members
        WHERE gym_id=? AND member_code=?
    """, (gym_id, member_code)).fetchone()

    if not row:
        return True, "ok"

    status = row["status"]

    if status == "active":
        return True, "ok"
    if status == "expired":
        return False, "عضويتك منتهية. من فضلك جددي الاشتراك."
    if status == "inactive":
        return False, "عضويتك غير مفعلة حاليًا. تواصلي مع الاستقبال."

    return False, "حالة العضوية غير معروفة."


# =========================================
# Session helpers
# =========================================

def find_session(conn: sqlite3.Connection, gym_id: int, day: str, class_name: str):
    return conn.execute("""
        SELECT *
        FROM sessions
        WHERE gym_id=? AND day=? AND is_active=1
    """, (gym_id, day)).fetchall()


def list_day_sessions(conn: sqlite3.Connection, gym_id: int, day: str) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT id, class_name, coach, time, capacity
        FROM sessions
        WHERE gym_id=? AND day=? AND is_active=1
        ORDER BY id ASC
    """, (gym_id, day)).fetchall()


def session_current_count(conn: sqlite3.Connection, gym_id: int, session_id: int) -> int:
    row = conn.execute("""
        SELECT COUNT(*) AS c
        FROM bookings
        WHERE gym_id=? AND session_id=? AND status='booked'
    """, (gym_id, session_id)).fetchone()
    return int(row["c"])


# =========================================
# Booking helpers
# =========================================

def create_booking(
    conn: sqlite3.Connection,
    gym_id: int,
    session_id: int,
    member_id: int,
    source: str = "telegram"
) -> int:
    conn.execute("""
        INSERT INTO bookings(gym_id, session_id, member_id, status, created_at, source)
        VALUES(?,?,?,?,?,?)
    """, (gym_id, session_id, member_id, "booked", now_cairo(), source))

    booking_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    return booking_id


def cancel_latest_booking(conn: sqlite3.Connection, gym_id: int, member_id: int) -> Optional[sqlite3.Row]:
    row = conn.execute("""
        SELECT b.id AS booking_id, s.class_name, s.day, s.time
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=? AND b.member_id=? AND b.status='booked'
        ORDER BY b.created_at DESC, b.id DESC
        LIMIT 1
    """, (gym_id, member_id)).fetchone()

    if not row:
        return None

    conn.execute("""
        UPDATE bookings
        SET status='cancelled', cancelled_at=?
        WHERE id=? AND gym_id=? AND member_id=? AND status='booked'
    """, (now_cairo(), row["booking_id"], gym_id, member_id))
    conn.commit()

    return row


# =========================================
# Waitlist helpers
# =========================================

def waitlist_add(conn: sqlite3.Connection, gym_id: int, session_id: int, member_id: int) -> int:
    existing = conn.execute("""
        SELECT id
        FROM waitlist
        WHERE gym_id=? AND session_id=? AND member_id=?
    """, (gym_id, session_id, member_id)).fetchone()

    if existing:
        return int(existing["id"])

    conn.execute("""
        INSERT INTO waitlist(gym_id, session_id, member_id, status, created_at)
        VALUES(?,?,?,?,?)
    """, (gym_id, session_id, member_id, "waiting", now_cairo()))
    conn.commit()

    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def get_waitlist_position(conn: sqlite3.Connection, gym_id: int, session_id: int, member_id: int) -> Optional[int]:
    rows = conn.execute("""
        SELECT member_id
        FROM waitlist
        WHERE gym_id=? AND session_id=? AND status='waiting'
        ORDER BY created_at ASC, id ASC
    """, (gym_id, session_id)).fetchall()

    for idx, row in enumerate(rows, start=1):
        if int(row["member_id"]) == member_id:
            return idx

    return None


def waitlist_offer_next(
    conn: sqlite3.Connection,
    gym_id: int,
    session_id: int,
    minutes: int = 10
) -> Optional[sqlite3.Row]:
    row = conn.execute("""
        SELECT id, member_id
        FROM waitlist
        WHERE gym_id=? AND session_id=? AND status='waiting'
        ORDER BY created_at ASC, id ASC
        LIMIT 1
    """, (gym_id, session_id)).fetchone()

    if not row:
        return None

    offered_until = (now_cairo_dt() + timedelta(minutes=minutes)).isoformat(timespec="seconds")

    conn.execute("""
        UPDATE waitlist
        SET status='offered', offered_until=?
        WHERE id=? AND gym_id=? AND session_id=?
    """, (offered_until, row["id"], gym_id, session_id))
    conn.commit()

    return row


def get_offered_waitlist(conn: sqlite3.Connection, gym_id: int, member_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("""
        SELECT
            w.id AS waitlist_id,
            w.session_id,
            w.offered_until,
            s.class_name,
            s.day,
            s.time,
            s.capacity
        FROM waitlist w
        JOIN sessions s ON s.id = w.session_id
        WHERE w.gym_id=? AND w.member_id=? AND w.status='offered'
        ORDER BY w.created_at DESC, w.id DESC
        LIMIT 1
    """, (gym_id, member_id)).fetchone()


def waitlist_accept(conn: sqlite3.Connection, gym_id: int, member_id: int) -> Optional[sqlite3.Row]:
    row = get_offered_waitlist(conn, gym_id, member_id)

    if not row or not row["offered_until"]:
        return None

    if datetime.fromisoformat(row["offered_until"]) < now_cairo_dt():
        conn.execute(
            "UPDATE waitlist SET status='expired' WHERE id=?",
            (row["waitlist_id"],)
        )
        conn.commit()
        return None

    current = session_current_count(conn, gym_id, row["session_id"])
    if int(current) >= int(row["capacity"]):
        return None

    booking_id = create_booking(
        conn,
        gym_id,
        row["session_id"],
        member_id,
        source="waitlist"
    )

    conn.execute("""
        UPDATE waitlist
        SET status='accepted'
        WHERE id=?
    """, (row["waitlist_id"],))
    conn.commit()

    return conn.execute("""
        SELECT ? AS booking_id, class_name, day, time
        FROM sessions
        WHERE id=?
    """, (booking_id, row["session_id"])).fetchone()