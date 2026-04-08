import sqlite3

DB_NAME = "gym.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_code TEXT UNIQUE,
        phone TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT,
        name TEXT,
        time TEXT,
        max_capacity INTEGER DEFAULT 25
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_code TEXT,
        class_id INTEGER,
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )
    """)

    conn.commit()
    conn.close()


def book_spot(member_code, class_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # عدد الحجوزات الحالية
    cursor.execute("SELECT COUNT(*) FROM bookings WHERE class_id=?", (class_id,))
    count = cursor.fetchone()[0]

    cursor.execute("SELECT max_capacity FROM classes WHERE id=?", (class_id,))
    max_capacity = cursor.fetchone()[0]

    if count >= max_capacity:
        conn.close()
        return False

    cursor.execute(
        "INSERT INTO bookings (member_code, class_id) VALUES (?, ?)",
        (member_code, class_id)
    )
    conn.commit()
    conn.close()
    return True