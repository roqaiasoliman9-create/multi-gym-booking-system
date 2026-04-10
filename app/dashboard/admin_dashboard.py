import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from app.database.db import init_db
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt


DB_PATH = "gym.sqlite3"
TZ = "Africa/Cairo"

ASSETS = Path("assets")
LOGO = ASSETS / "logo_white.png"
if not LOGO.exists():
    LOGO = ASSETS / "logo.png"

BLUE_IMG = ASSETS / "blue_fitness.jpg"
PINK_IMG = ASSETS / "pink_fitness.png"
PURPLE_IMG = ASSETS / "purble_fitness.jpg"

BG = "#050B16"
SURFACE = "#0F1830"
SURFACE_2 = "#111D37"
TEXT = "#F8FAFC"
MUTED = "#A7B7D0"

BLUE = "#00A6FF"
CYAN = "#31E1FF"
PINK = "#FF43B5"
MAGENTA = "#FF6ED8"
PURPLE = "#8B5CFF"
LAVENDER = "#B794FF"
GREEN = "#27E38B"
ORANGE = "#FFB020"
RED = "#FF5C7A"

BORDER = "rgba(255,255,255,0.08)"


# =========================
# Core helpers
# =========================
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_cairo() -> str:
    return datetime.now(ZoneInfo(TZ)).isoformat(timespec="seconds")


def today_english_day() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%A")


def get_gym_id(conn):
    row = conn.execute("SELECT id FROM gyms ORDER BY id LIMIT 1").fetchone()
    return int(row["id"]) if row else None


# =========================
# Queries
# =========================
def get_summary(conn, gym_id: int, day: str):
    sessions_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM sessions
        WHERE gym_id=? AND day=? AND is_active=1
    """, (gym_id, day)).fetchone()["c"]

    bookings_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM bookings
        WHERE gym_id=? AND status='booked'
    """, (gym_id,)).fetchone()["c"]

    waitlist_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM waitlist
        WHERE gym_id=? AND status IN ('waiting', 'offered')
    """, (gym_id,)).fetchone()["c"]

    admin_requests_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM admin_contact_requests
        WHERE gym_id=? AND status='new'
    """, (gym_id,)).fetchone()["c"]

    return int(sessions_count), int(bookings_count), int(waitlist_count), int(admin_requests_count)


def get_day_schedule(conn, gym_id: int, day: str):
    rows = conn.execute("""
        SELECT s.id, s.time, s.class_name, s.coach, s.capacity
        FROM sessions s
        WHERE s.gym_id=? AND s.day=? AND s.is_active=1
        ORDER BY s.time
    """, (gym_id, day)).fetchall()

    data = []
    for r in rows:
        booked = conn.execute("""
            SELECT COUNT(*) AS c
            FROM bookings
            WHERE gym_id=? AND session_id=? AND status='booked'
        """, (gym_id, r["id"])).fetchone()["c"]

        data.append({
            "session_id": r["id"],
            "time": r["time"],
            "class_name": r["class_name"],
            "coach": r["coach"],
            "booked": int(booked),
            "capacity": int(r["capacity"]),
            "remaining": int(r["capacity"]) - int(booked),
            "occupancy_ratio": (int(booked) / int(r["capacity"])) if int(r["capacity"]) else 0,
        })

    return data


def get_today_classes_with_members(conn, gym_id: int, day: str):
    sessions = conn.execute("""
        SELECT
            s.id,
            s.class_name,
            s.time,
            s.coach,
            s.capacity
        FROM sessions s
        WHERE s.gym_id=? AND s.day=? AND s.is_active=1
        ORDER BY s.time
    """, (gym_id, day)).fetchall()

    result = []
    for session in sessions:
        members = conn.execute("""
            SELECT
                m.member_code,
                COALESCE(m.full_name, 'No Name') AS full_name
            FROM bookings b
            JOIN members m ON m.id = b.member_id
            WHERE b.gym_id=? AND b.session_id=? AND b.status='booked'
            ORDER BY m.full_name, m.member_code
        """, (gym_id, session["id"])).fetchall()

        member_names = [
            m["full_name"] if m["full_name"] != "No Name" else m["member_code"]
            for m in members
        ]

        booked_count = len(member_names)
        remaining = int(session["capacity"]) - booked_count
        ratio = (booked_count / int(session["capacity"])) if int(session["capacity"]) else 0

        result.append({
            "session_id": session["id"],
            "class_name": session["class_name"],
            "time": session["time"],
            "coach": session["coach"],
            "capacity": int(session["capacity"]),
            "booked_count": booked_count,
            "remaining": remaining,
            "members": member_names,
            "occupancy_ratio": ratio,
        })

    return result


def get_active_bookings(conn, gym_id: int, source_filter: str = "all", class_filter: str = "all", coach_filter: str = "all"):
    query = """
        SELECT
            b.id AS booking_id,
            b.session_id,
            m.id AS member_id,
            m.member_code,
            COALESCE(m.full_name, '') AS full_name,
            m.phone,
            s.day,
            s.time,
            s.class_name,
            s.coach,
            b.created_at,
            b.source
        FROM bookings b
        JOIN members m ON m.id = b.member_id
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=? AND b.status='booked'
    """
    params = [gym_id]

    if source_filter != "all":
        query += " AND b.source=?"
        params.append(source_filter)

    if class_filter != "all":
        query += " AND s.class_name=?"
        params.append(class_filter)

    if coach_filter != "all":
        query += " AND s.coach=?"
        params.append(coach_filter)

    query += " ORDER BY s.day, s.time, b.created_at DESC"

    rows = conn.execute(query, tuple(params)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_waitlist(conn, gym_id: int):
    rows = conn.execute("""
        SELECT
            w.id AS waitlist_id,
            m.member_code,
            COALESCE(m.full_name, '') AS full_name,
            s.day,
            s.time,
            s.class_name,
            w.status,
            w.created_at,
            w.offered_until
        FROM waitlist w
        JOIN members m ON m.id = w.member_id
        JOIN sessions s ON s.id = w.session_id
        WHERE w.gym_id=?
        ORDER BY w.created_at ASC
    """, (gym_id,)).fetchall()

    return pd.DataFrame([dict(r) for r in rows])


def get_admin_contact_requests(conn, gym_id: int, status_filter: str = "all"):
    query = """
        SELECT
            id,
            source,
            platform_user,
            full_name,
            phone,
            language,
            status,
            created_at
        FROM admin_contact_requests
        WHERE gym_id=?
    """
    params = [gym_id]

    if status_filter != "all":
        query += " AND status=?"
        params.append(status_filter)

    query += " ORDER BY created_at DESC, id DESC"

    rows = conn.execute(query, tuple(params)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_attendance(conn, gym_id: int, day: str):
    rows = conn.execute("""
        SELECT
            s.day,
            s.time,
            s.class_name,
            m.member_code,
            a.status,
            a.checkin_at
        FROM attendance a
        JOIN sessions s ON s.id = a.session_id
        JOIN members m ON m.id = a.member_id
        WHERE a.gym_id=? AND s.day=?
        ORDER BY s.time, s.class_name, m.member_code
    """, (gym_id, day)).fetchall()

    return pd.DataFrame([dict(r) for r in rows])


def get_all_classes(conn, gym_id: int):
    rows = conn.execute("""
        SELECT DISTINCT class_name
        FROM sessions
        WHERE gym_id=? AND is_active=1
        ORDER BY class_name
    """, (gym_id,)).fetchall()
    return [r["class_name"] for r in rows]


def get_all_coaches(conn, gym_id: int):
    rows = conn.execute("""
        SELECT DISTINCT coach
        FROM sessions
        WHERE gym_id=? AND is_active=1 AND coach IS NOT NULL AND coach != ''
        ORDER BY coach
    """, (gym_id,)).fetchall()
    return [r["coach"] for r in rows]


def get_recent_activity(conn, gym_id: int, limit: int = 12):
    rows = conn.execute("""
        SELECT b.created_at AS event_time, 'booking_created' AS event_type,
               'Booking created' AS event_label,
               b.source AS source,
               m.member_code AS member_code,
               s.class_name AS class_name,
               s.day AS day,
               s.time AS time
        FROM bookings b
        JOIN members m ON m.id = b.member_id
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=?

        UNION ALL

        SELECT w.created_at AS event_time, 'waitlist_joined' AS event_type,
               'Joined waitlist' AS event_label,
               'waitlist' AS source,
               m.member_code AS member_code,
               s.class_name AS class_name,
               s.day AS day,
               s.time AS time
        FROM waitlist w
        JOIN members m ON m.id = w.member_id
        JOIN sessions s ON s.id = w.session_id
        WHERE w.gym_id=?

        UNION ALL

        SELECT acr.created_at AS event_time, 'admin_request' AS event_type,
               'Admin request created' AS event_label,
               acr.source AS source,
               acr.platform_user AS member_code,
               acr.full_name AS class_name,
               '' AS day,
               '' AS time
        FROM admin_contact_requests acr
        WHERE acr.gym_id=?

        UNION ALL

        SELECT a.created_at AS event_time, 'attendance' AS event_type,
               'Attendance marked' AS event_label,
               'attendance' AS source,
               m.member_code AS member_code,
               s.class_name AS class_name,
               s.day AS day,
               s.time AS time
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        JOIN sessions s ON s.id = a.session_id
        WHERE a.gym_id=?

        ORDER BY event_time DESC
        LIMIT ?
    """, (gym_id, gym_id, gym_id, gym_id, limit)).fetchall()

    return [dict(r) for r in rows]


def get_member_profile(conn, gym_id: int, member_code: str):
    member = conn.execute("""
        SELECT id, member_code, COALESCE(full_name, '') AS full_name, COALESCE(phone, '') AS phone,
               COALESCE(status, '') AS status
        FROM members
        WHERE gym_id=? AND member_code=?
    """, (gym_id, member_code)).fetchone()

    if not member:
        return None

    bookings = conn.execute("""
        SELECT b.id AS booking_id, b.status, b.source, b.created_at,
               s.class_name, s.day, s.time, s.coach
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=? AND b.member_id=?
        ORDER BY b.created_at DESC
    """, (gym_id, member["id"])).fetchall()

    attendance = conn.execute("""
        SELECT a.status, a.checkin_at, a.created_at,
               s.class_name, s.day, s.time
        FROM attendance a
        JOIN sessions s ON s.id = a.session_id
        WHERE a.gym_id=? AND a.member_id=?
        ORDER BY a.created_at DESC
    """, (gym_id, member["id"])).fetchall()

    no_show_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM attendance
        WHERE gym_id=? AND member_id=? AND status='no_show'
    """, (gym_id, member["id"])).fetchone()["c"]

    return {
        "member": dict(member),
        "bookings": [dict(r) for r in bookings],
        "attendance": [dict(r) for r in attendance],
        "no_show_count": int(no_show_count),
    }


def get_source_split(conn, gym_id: int):
    rows = conn.execute("""
        SELECT source, COUNT(*) AS c
        FROM bookings
        WHERE gym_id=? AND status='booked'
        GROUP BY source
        ORDER BY c DESC
    """, (gym_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_bookings_by_day(conn, gym_id: int):
    rows = conn.execute("""
        SELECT s.day, COUNT(*) AS c
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=? AND b.status='booked'
        GROUP BY s.day
    """, (gym_id,)).fetchall()

    order = ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    mapping = {r["day"]: int(r["c"]) for r in rows}
    return pd.DataFrame({"day": order, "bookings": [mapping.get(d, 0) for d in order]})


def get_top_classes(conn, gym_id: int):
    rows = conn.execute("""
        SELECT s.class_name, COUNT(*) AS c
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=? AND b.status='booked'
        GROUP BY s.class_name
        ORDER BY c DESC, s.class_name ASC
        LIMIT 8
    """, (gym_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_peak_times(conn, gym_id: int):
    rows = conn.execute("""
        SELECT s.time, COUNT(*) AS c
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        WHERE b.gym_id=? AND b.status='booked'
        GROUP BY s.time
        ORDER BY c DESC, s.time ASC
        LIMIT 8
    """, (gym_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_rates(conn, gym_id: int):
    total_booked = conn.execute("""
        SELECT COUNT(*) AS c FROM bookings WHERE gym_id=?
    """, (gym_id,)).fetchone()["c"]

    total_attended = conn.execute("""
        SELECT COUNT(*) AS c FROM attendance WHERE gym_id=? AND status='attended'
    """, (gym_id,)).fetchone()["c"]

    total_no_show = conn.execute("""
        SELECT COUNT(*) AS c FROM attendance WHERE gym_id=? AND status='no_show'
    """, (gym_id,)).fetchone()["c"]

    attendance_rate = (int(total_attended) / int(total_booked) * 100) if total_booked else 0
    no_show_rate = (int(total_no_show) / int(total_booked) * 100) if total_booked else 0

    return round(attendance_rate, 1), round(no_show_rate, 1)


def get_alerts(conn, gym_id: int, selected_day: str):
    alerts = []

    full_classes = conn.execute("""
        SELECT s.class_name, s.time, s.capacity,
               (SELECT COUNT(*) FROM bookings b WHERE b.session_id=s.id AND b.gym_id=s.gym_id AND b.status='booked') AS booked
        FROM sessions s
        WHERE s.gym_id=? AND s.day=? AND s.is_active=1
    """, (gym_id, selected_day)).fetchall()

    for r in full_classes:
        if int(r["booked"]) >= int(r["capacity"]):
            alerts.append({
                "level": "danger",
                "title": f"{r['class_name']} is full",
                "desc": f"{r['time']} reached full capacity."
            })
        elif int(r["capacity"]) > 0 and int(r["booked"]) / int(r["capacity"]) >= 0.8:
            alerts.append({
                "level": "warning",
                "title": f"{r['class_name']} almost full",
                "desc": f"{r['time']} is above 80% occupancy."
            })

    new_requests = conn.execute("""
        SELECT COUNT(*) AS c
        FROM admin_contact_requests
        WHERE gym_id=? AND status='new'
    """, (gym_id,)).fetchone()["c"]

    if int(new_requests) > 0:
        alerts.append({
            "level": "info",
            "title": "New admin requests",
            "desc": f"There are {new_requests} new admin request(s)."
        })

    offered_waitlist = conn.execute("""
        SELECT COUNT(*) AS c
        FROM waitlist
        WHERE gym_id=? AND status='offered'
    """, (gym_id,)).fetchone()["c"]

    if int(offered_waitlist) > 0:
        alerts.append({
            "level": "warning",
            "title": "Pending waitlist offers",
            "desc": f"{offered_waitlist} member(s) have offered spots waiting for confirmation."
        })

    repeat_no_show = conn.execute("""
        SELECT m.member_code, COUNT(*) AS c
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        WHERE a.gym_id=? AND a.status='no_show'
        GROUP BY m.member_code
        HAVING COUNT(*) >= 2
        ORDER BY c DESC
        LIMIT 3
    """, (gym_id,)).fetchall()

    for r in repeat_no_show:
        alerts.append({
            "level": "danger",
            "title": f"Repeat no-show: {r['member_code']}",
            "desc": f"{r['c']} no-show record(s)."
        })

    return alerts[:8]


# =========================
# Actions
# =========================
def update_admin_request_status(conn, request_id: int, status: str):
    conn.execute("""
        UPDATE admin_contact_requests
        SET status=?
        WHERE id=?
    """, (status, request_id))
    conn.commit()


def cancel_booking_by_id(conn, booking_id: int):
    conn.execute("""
        UPDATE bookings
        SET status='cancelled', cancelled_at=?
        WHERE id=? AND status='booked'
    """, (now_cairo(), booking_id))
    conn.commit()


def checkin_booking_by_id(conn, gym_id: int, booking_id: int):
    booking = conn.execute("""
        SELECT id, session_id, member_id
        FROM bookings
        WHERE id=? AND gym_id=? AND status='booked'
    """, (booking_id, gym_id)).fetchone()

    if not booking:
        return False

    conn.execute("""
        INSERT OR REPLACE INTO attendance(
            gym_id, session_id, member_id, status, checkin_at, created_at
        )
        VALUES(?,?,?,?,?,?)
    """, (
        gym_id,
        booking["session_id"],
        booking["member_id"],
        "attended",
        now_cairo(),
        now_cairo()
    ))

    conn.execute("""
        UPDATE bookings
        SET status='attended'
        WHERE id=?
    """, (booking_id,))

    conn.commit()
    return True


def no_show_booking_by_id(conn, gym_id: int, booking_id: int):
    booking = conn.execute("""
        SELECT id, session_id, member_id
        FROM bookings
        WHERE id=? AND gym_id=? AND status='booked'
    """, (booking_id, gym_id)).fetchone()

    if not booking:
        return False

    conn.execute("""
        INSERT OR REPLACE INTO attendance(
            gym_id, session_id, member_id, status, created_at
        )
        VALUES(?,?,?,?,?)
    """, (
        gym_id,
        booking["session_id"],
        booking["member_id"],
        "no_show",
        now_cairo()
    ))

    conn.execute("""
        UPDATE bookings
        SET status='no_show'
        WHERE id=?
    """, (booking_id,))

    conn.commit()
    return True


# =========================
# Exports
# =========================
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def pdf_like_text_report(selected_day: str, summary_vals: tuple[int, int, int, int], activities: list[dict]) -> bytes:
    sessions_count, bookings_count, waitlist_count, admin_requests_count = summary_vals
    lines = [
        "GYM DAILY REPORT",
        "",
        f"Day: {selected_day}",
        f"Classes Today: {sessions_count}",
        f"Active Bookings: {bookings_count}",
        f"Waitlist: {waitlist_count}",
        f"Admin Requests: {admin_requests_count}",
        "",
        "RECENT ACTIVITY",
        "---------------------------",
    ]
    for item in activities:
        lines.append(
            f"{item.get('event_time', '')} | {item.get('event_label', '')} | "
            f"{item.get('member_code', '')} | {item.get('class_name', '')} | {item.get('day', '')} {item.get('time', '')}"
        )
    return "\n".join(lines).encode("utf-8")


# =========================
# UI helpers
# =========================
def inject_css():

    st.markdown(f"""
    <style>
        .stApp {{
            background:
                radial-gradient(circle at top left, rgba(0,166,255,0.18), transparent 22%),
                radial-gradient(circle at top right, rgba(255,67,181,0.18), transparent 22%),
                radial-gradient(circle at bottom right, rgba(139,92,255,0.14), transparent 24%),
                linear-gradient(180deg, {BG}, #040914 100%);
            color: {TEXT};
        }}

        .block-container {{
            max-width: 100% !important;
            width: 100% !important;
            padding-top: 0.35rem;
            padding-bottom: 1rem;
            padding-left: 0.8rem;
            padding-right: 0.8rem;
        }}

        section.main > div {{
            padding-top: 0rem !important;
        }}

        header[data-testid="stHeader"] {{
            display: none;
        }}

        div[data-testid="stToolbar"] {{
            display: none;
        }}

        #MainMenu {{
            visibility: hidden;
        }}

        footer {{
            visibility: hidden;
        }}

        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #0A1327, #08101F);
            border-right: 1px solid {BORDER};
        }}

        h1, h2, h3, h4, h5, h6, p, span, div, label {{
            color: {TEXT};
        }}

        .top-logo-wrap {{
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 12px;
            margin-top: 4px;
        }}

        .top-logo-wrap img {{
            filter: brightness(0) invert(1);
            opacity: 1;
            animation: floatGlow 4s ease-in-out infinite;
        }}

        .hero-title {{
            font-size: 42px;
            font-weight: 900;
            line-height: 1.02;
            text-align: center;
            margin-bottom: 6px;
            color: white;
            letter-spacing: -0.03em;
            animation: fadeUp 0.8s ease both;
        }}

        .hero-sub {{
            color: #D6E2F2;
            font-size: 14px;
            line-height: 1.6;
            text-align: center;
            max-width: 760px;
            margin: 0 auto 14px auto;
            animation: fadeUp 1s ease both;
        }}

        .kpi-card {{
            border-radius: 26px;
            padding: 14px 18px !important;
            min-height: 110px !important;
            color: white;
            box-shadow: 0 18px 42px rgba(0,0,0,0.24);
            animation: fadeUp 0.7s ease both;
            transition: transform 0.25s ease, box-shadow 0.25s ease;
        }}

        .kpi-card:hover {{
            transform: translateY(-6px) scale(1.02);
            box-shadow: 0 22px 50px rgba(0,0,0,0.30);
        }}

        .kpi-blue {{ background: linear-gradient(135deg, {BLUE}, {CYAN}); }}
        .kpi-pink {{ background: linear-gradient(135deg, {PINK}, {MAGENTA}); }}
        .kpi-purple {{ background: linear-gradient(135deg, {PURPLE}, {LAVENDER}); }}
        .kpi-mix {{ background: linear-gradient(135deg, {BLUE}, {PURPLE}, {PINK}); }}

        .kpi-label {{
            font-size: 13px !important;
            font-weight: 700;
            opacity: 0.96;
        }}

        .kpi-value {{
            font-size: 30px !important;
            font-weight: 900;
            margin-top: 14px !important;
            line-height: 1;
        }}

        .section-title {{
            font-size: 26px !important;
            font-weight: 900;
            margin: 6px 0 4px 0 !important;
            color: white;
            letter-spacing: -0.02em;
            animation: fadeUp 0.65s ease both;
        }}

        .section-sub {{
            color: {MUTED};
            font-size: 14px !important;
            margin-bottom: 10px !important;
            animation: fadeUp 0.8s ease both;
        }}

        .image-card {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 26px;
            overflow: hidden;
            box-shadow: 0 16px 36px rgba(0,0,0,0.18);
            animation: fadeUp 0.85s ease both;
            transition: transform 0.25s ease, box-shadow 0.25s ease;
        }}

        .image-card:hover {{
            transform: translateY(-6px) scale(1.015);
            box-shadow: 0 22px 44px rgba(0,0,0,0.26);
        }}

        .image-body {{
            padding: 16px 18px 18px 18px;
        }}

        .image-title {{
            font-size: 26px;
            font-weight: 900;
            margin-bottom: 8px;
            color: white;
        }}

        .image-sub {{
            font-size: 14px;
            color: {MUTED};
        }}

        .chip {{
            display: inline-block;
            padding: 8px 14px;
            border-radius: 999px;
            font-size: 14px;
            font-weight: 800;
            margin-right: 8px;
            margin-bottom: 10px;
            animation: fadeUp 0.9s ease both;
        }}

        .chip-blue {{ background: rgba(0,166,255,0.18); color: #C9ECFF; }}
        .chip-pink {{ background: rgba(255,67,181,0.18); color: #FFD1EE; }}
        .chip-purple {{ background: rgba(139,92,255,0.18); color: #E0D3FF; }}
        .chip-green {{ background: rgba(39,227,139,0.18); color: #CDFBE3; }}
        .chip-orange {{ background: rgba(255,176,32,0.18); color: #FFE4B0; }}
        .chip-red {{ background: rgba(255,92,122,0.18); color: #FFD0DA; }}

        .class-card {{
            background: linear-gradient(180deg, rgba(15,24,48,0.98), rgba(11,18,37,0.98));
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 30px;
            padding: 24px;
            box-shadow: 0 18px 38px rgba(0,0,0,0.18);
            margin-bottom: 20px;
            animation: fadeUp 0.75s ease both;
            transition: transform 0.25s ease, box-shadow 0.25s ease;
        }}

        .class-card:hover {{
            transform: translateY(-6px);
            box-shadow: 0 24px 46px rgba(0,0,0,0.26);
        }}

        .class-name {{
            font-size: 34px;
            font-weight: 900;
            margin-bottom: 10px;
            color: white;
            letter-spacing: -0.02em;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            margin-top: 14px;
            margin-bottom: 16px;
        }}

        .stat-box {{
            background: linear-gradient(135deg, rgba(21,34,63,0.96), rgba(18,31,56,0.96));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 14px 16px;
            animation: fadeUp 0.85s ease both;
            transition: transform 0.2s ease;
        }}

        .stat-box:hover {{
            transform: scale(1.02);
        }}

        .stat-label {{
            font-size: 15px;
            color: {MUTED};
            margin-bottom: 4px;
            font-weight: 600;
        }}

        .stat-value {{
            font-size: 22px;
            font-weight: 900;
            color: {TEXT};
        }}

        .member-wrap {{
            border-top: 1px dashed rgba(255,255,255,0.08);
            padding-top: 14px;
            margin-top: 8px;
            animation: fadeUp 0.95s ease both;
        }}

        .member-title {{
            font-size: 16px;
            color: {MUTED};
            margin-bottom: 10px;
            font-weight: 700;
        }}

        .member-row {{
            font-size: 17px;
            color: #F2F7FF;
            margin-bottom: 8px;
            font-weight: 600;
        }}

        .clean-card {{
            background: linear-gradient(180deg, rgba(15,24,48,0.98), rgba(11,18,37,0.98));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 24px;
            padding: 18px;
            box-shadow: 0 16px 34px rgba(0,0,0,0.14);
            margin-bottom: 12px;
            animation: fadeUp 0.75s ease both;
            transition: transform 0.25s ease, box-shadow 0.25s ease;
        }}

        .clean-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 22px 40px rgba(0,0,0,0.22);
        }}

        .clean-title {{
            font-size: 22px;
            font-weight: 900;
            margin-bottom: 8px;
            color: white;
        }}

        .alert-card {{
            border-radius: 20px;
            padding: 14px 16px;
            margin-bottom: 10px;
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 12px 28px rgba(0,0,0,0.14);
            animation: fadeUp 0.6s ease both, softPulse 3.2s infinite ease-in-out;
        }}

        .alert-info {{ background: linear-gradient(135deg, rgba(0,166,255,0.16), rgba(49,225,255,0.08)); }}
        .alert-warning {{ background: linear-gradient(135deg, rgba(255,176,32,0.16), rgba(255,176,32,0.08)); }}
        .alert-danger {{ background: linear-gradient(135deg, rgba(255,92,122,0.18), rgba(255,92,122,0.08)); }}

        .alert-title {{
            font-size: 16px;
            font-weight: 900;
            color: white;
            margin-bottom: 4px;
        }}

        .alert-desc {{
            font-size: 14px;
            color: #D8E2F0;
        }}

        .activity-card {{
            background: linear-gradient(180deg, rgba(14,22,40,0.98), rgba(10,16,31,0.98));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 14px;
            margin-bottom: 10px;
            animation: fadeUp 0.7s ease both;
        }}

        .activity-title {{
            font-size: 15px;
            font-weight: 800;
            color: white;
            margin-bottom: 3px;
        }}

        .activity-sub {{
            font-size: 13px;
            color: {MUTED};
        }}

        .quick-wrap {{
            background: linear-gradient(135deg, rgba(0,166,255,0.12), rgba(255,67,181,0.10), rgba(139,92,255,0.10));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 24px;
            padding: 12px !important;
            margin-bottom: 10px !important;
            animation: fadeUp 0.65s ease both;
        }}

        .occ-track {{
            width: 100%;
            height: 16px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 999px;
            overflow: hidden;
            position: relative;
            box-shadow: inset 0 2px 8px rgba(0,0,0,0.25);
        }}

        .occ-fill {{
            height: 100%;
            border-radius: 999px;
            position: relative;
            animation: fillGrow 1.2s ease-out both;
            box-shadow: 0 0 18px rgba(255,255,255,0.18);
        }}

        .occ-fill::after {{
            content: "";
            position: absolute;
            top: 0;
            left: -35%;
            width: 35%;
            height: 100%;
            background: linear-gradient(
                90deg,
                rgba(255,255,255,0) 0%,
                rgba(255,255,255,0.28) 50%,
                rgba(255,255,255,0) 100%
            );
            animation: shimmerSweep 2s linear infinite;
        }}

        div[data-testid="stTabs"] {{
            margin-top: 4px !important;
            animation: fadeUp 0.6s ease both;
        }}

        div[data-testid="stTabs"] button {{
            color: {TEXT} !important;
            font-weight: 800;
            font-size: 14px !important;
            padding-top: 6px !important;
            padding-bottom: 6px !important;
            transition: transform 0.2s ease;
        }}

        div[data-testid="stTabs"] button:hover {{
            transform: translateY(-2px);
        }}

        div[data-testid="stDataFrame"] {{
            border: 1px solid {BORDER};
            border-radius: 18px;
            overflow: hidden;
            animation: fadeUp 0.75s ease both;
        }}

        [data-testid="stMetric"] {{
            background: linear-gradient(135deg, rgba(21,34,63,0.96), rgba(18,31,56,0.96));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 8px 14px;
            animation: fadeUp 0.7s ease both;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}

        [data-testid="stMetric"]:hover {{
            transform: translateY(-3px);
            box-shadow: 0 16px 28px rgba(0,0,0,0.18);
        }}

        [data-testid="stMetricLabel"] {{
            color: {MUTED};
            font-size: 14px;
            font-weight: 700;
        }}

        [data-testid="stMetricValue"] {{
            color: {TEXT};
            font-size: 24px;
            font-weight: 900;
        }}

        @keyframes fadeUp {{
            from {{
                opacity: 0;
                transform: translateY(18px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}

        @keyframes softPulse {{
            0% {{ box-shadow: 0 0 0 rgba(255,255,255,0); }}
            50% {{ box-shadow: 0 0 28px rgba(255,255,255,0.08); }}
            100% {{ box-shadow: 0 0 0 rgba(255,255,255,0); }}
        }}

        @keyframes floatGlow {{
            0% {{ transform: translateY(0px); }}
            50% {{ transform: translateY(-6px); }}
            100% {{ transform: translateY(0px); }}
        }}

        @keyframes fillGrow {{
            from {{
                width: 0%;
            }}
        }}

        @keyframes shimmerSweep {{
            from {{
                left: -35%;
            }}
            to {{
                left: 110%;
            }}
        }}
    </style>
    """, unsafe_allow_html=True)


def kpi_card(title: str, value: int, variant: str):
    st.markdown(
        f"""
        <div class="kpi-card {variant}">
            <div class="kpi-label">{title}</div>
            <div class="kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-sub">{subtitle}</div>', unsafe_allow_html=True)


def image_info_card(title: str, subtitle: str, image_path: Path, chips: list[tuple[str, str]]):
    with st.container():
        st.markdown('<div class="image-card">', unsafe_allow_html=True)
        if image_path.exists():
            st.image(str(image_path), use_container_width=True)
        chips_html = "".join([f'<span class="chip {cls}">{txt}</span>' for txt, cls in chips])
        st.markdown(
            f"""
            <div class="image-body">
                <div>{chips_html}</div>
                <div class="image-title">{title}</div>
                <div class="image-sub">{subtitle}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)


def occupancy_color(ratio: float):
    if ratio >= 1:
        return "red"
    if ratio >= 0.8:
        return "orange"
    return "green"


def occupancy_label(ratio: float):
    if ratio >= 1:
        return "Full"
    if ratio >= 0.8:
        return "Almost Full"
    return "Available"


def class_card(item: dict):
    status = occupancy_label(item["occupancy_ratio"])
    color_cls = occupancy_color(item["occupancy_ratio"])
    percent = int(item["occupancy_ratio"] * 100)

    bar_color = {
        "green": "linear-gradient(90deg, #27E38B, #7CFFB2)",
        "orange": "linear-gradient(90deg, #FFB020, #FFD36B)",
        "red": "linear-gradient(90deg, #FF5C7A, #FF8FA3)",
    }.get(color_cls, "linear-gradient(90deg, #27E38B, #7CFFB2)")

    st.markdown(
        f"""
        <div class="class-card">
            <div class="class-name">{item['class_name']}</div>
            <div>
                <span class="chip chip-blue">{item['time']}</span>
                <span class="chip chip-pink">{item['coach']}</span>
                <span class="chip chip-{color_cls}">{status}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("##### Occupancy")
    st.markdown(
        f"""
        <div class="occ-track">
            <div class="occ-fill" style="width:{percent}%; background:{bar_color};"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(f"{percent}% occupied — {item['booked_count']} / {item['capacity']}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Capacity", item["capacity"])
    with c2:
        st.metric("Booked", item["booked_count"])
    with c3:
        st.metric("Remaining", item["remaining"])
    with c4:
        st.metric("Session ID", item["session_id"])

    st.markdown("##### Booked Members")
    if item["members"]:
        for m in item["members"]:
            st.markdown(f"- **{m}**")
    else:
        st.caption("No bookings yet.")

    st.progress(item["occupancy_ratio"], text=f"Occupancy: {item['booked_count']} / {item['capacity']}")

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Capacity", item["capacity"])
    with c2:
        st.metric("Booked", item["booked_count"])

    c3, c4 = st.columns(2)
    with c3:
        st.metric("Remaining", item["remaining"])
    with c4:
        st.metric("Session ID", item["session_id"])

    st.markdown("#### Booked Members")
    if item["members"]:
        for m in item["members"]:
            st.markdown(f"- **{m}**")
    else:
        st.caption("No bookings yet.")


def booking_card(conn, gym_id: int, row):
    source_class = {
        "telegram": "chip-blue",
        "whatsapp": "chip-pink",
        "waitlist": "chip-purple",
    }.get(row["source"], "chip-blue")

    st.markdown(
        f"""
        <div class="clean-card">
            <div>
                <span class="chip {source_class}">{row['source']}</span>
                <span class="chip chip-purple">{row['day']}</span>
                <span class="chip chip-blue">{row['time']}</span>
            </div>
            <div class="clean-title">{row['class_name']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Booking ID", row["booking_id"])
    with c2:
        st.metric("Member Code", row["member_code"])
    with c3:
        st.metric("Coach", row["coach"])
    with c4:
        st.metric("Created", row["created_at"])

    a1, a2, a3 = st.columns(3)
    with a1:
        if st.button("Check-in", key=f"checkin_{row['booking_id']}", use_container_width=True):
            ok = checkin_booking_by_id(conn, gym_id, int(row["booking_id"]))
            if ok:
                st.success(f"Booking {row['booking_id']} marked as attended.")
            else:
                st.error("Booking not found or already processed.")
            st.rerun()

    with a2:
        if st.button("No-show", key=f"noshow_{row['booking_id']}", use_container_width=True):
            ok = no_show_booking_by_id(conn, gym_id, int(row["booking_id"]))
            if ok:
                st.success(f"Booking {row['booking_id']} marked as no_show.")
            else:
                st.error("Booking not found or already processed.")
            st.rerun()

    with a3:
        if st.button("Cancel", key=f"cancel_{row['booking_id']}", use_container_width=True):
            cancel_booking_by_id(conn, int(row["booking_id"]))
            st.success(f"Booking {row['booking_id']} cancelled.")
            st.rerun()


def admin_request_card(conn, row):
    status_class = {
        "new": "chip-blue",
        "in_progress": "chip-orange",
        "done": "chip-green",
        "contacted": "chip-purple",
        "resolved": "chip-green",
        "archived": "chip-orange",
    }.get(row["status"], "chip-blue")

    st.markdown(
        f"""
        <div class="clean-card">
            <div>
                <span class="chip {status_class}">{row['status']}</span>
                <span class="chip chip-pink">{row['source']}</span>
                <span class="chip chip-purple">{row['language']}</span>
            </div>
            <div class="clean-title">{row['full_name']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Request ID", row["id"])
    with c2:
        st.metric("Phone", row["phone"])
    with c3:
        st.metric("User", row["platform_user"])
    with c4:
        st.metric("Created", row["created_at"])

    statuses = ["new", "in_progress", "contacted", "resolved", "archived"]
    selected = st.selectbox(
        "Update status",
        statuses,
        index=statuses.index(row["status"]) if row["status"] in statuses else 0,
        key=f"status_select_{row['id']}"
    )

    if st.button("Save Status", key=f"save_status_{row['id']}", use_container_width=True):
        update_admin_request_status(conn, int(row["id"]), selected)
        st.success(f"Request {row['id']} updated to {selected}.")
        st.rerun()


def render_alerts(alerts):
    if not alerts:
        st.info("No alerts right now.")
        return

    for alert in alerts:
        level_class = {
            "info": "alert-info",
            "warning": "alert-warning",
            "danger": "alert-danger",
        }.get(alert["level"], "alert-info")

        st.markdown(
            f"""
            <div class="alert-card {level_class}">
                <div class="alert-title">{alert['title']}</div>
                <div class="alert-desc">{alert['desc']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_activity_feed(items):
    if not items:
        st.info("No recent activity.")
        return

    for item in items:
        subtitle = f"{item.get('event_time', '')} • {item.get('member_code', '')} • {item.get('class_name', '')} • {item.get('day', '')} {item.get('time', '')}"
        st.markdown(
            f"""
            <div class="activity-card">
                <div class="activity-title">{item.get('event_label', '')}</div>
                <div class="activity-sub">{subtitle}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def plot_bar(df: pd.DataFrame, x_col: str, y_col: str, title: str):
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.bar(df[x_col], df[y_col])
    ax.set_title(title)
    ax.tick_params(axis='x', rotation=30)
    fig.patch.set_alpha(0)
    ax.set_facecolor("white")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def plot_donut(df: pd.DataFrame, label_col: str, value_col: str, title: str):
    fig, ax = plt.subplots(figsize=(5.4, 5.4))
    wedges, texts = ax.pie(df[value_col], labels=df[label_col], startangle=90, wedgeprops=dict(width=0.42))
    ax.set_title(title)
    fig.patch.set_alpha(0)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def quick_actions_panel(conn, gym_id):
    st.markdown('<div class="quick-wrap">', unsafe_allow_html=True)
    st.markdown("### Quick Actions")

    qa1, qa2, qa3 = st.columns(3)
    with qa1:
        with st.popover("Add Admin Request", use_container_width=True):
            with st.form("quick_admin_request_form"):
                full_name = st.text_input("Name")
                phone = st.text_input("Phone")
                language = st.selectbox("Language", ["ar", "en"])
                source = st.selectbox("Source", ["telegram", "whatsapp"])
                platform_user = st.text_input("Platform User")
                submitted = st.form_submit_button("Save")
                if submitted and full_name and phone:
                    conn.execute("""
                        INSERT INTO admin_contact_requests(gym_id, source, platform_user, full_name, phone, language, status, created_at)
                        VALUES(?,?,?,?,?,?,?,?)
                    """, (gym_id, source, platform_user, full_name, phone, language, "new", now_cairo()))
                    conn.commit()
                    st.success("Admin request added.")
                    st.rerun()

    with qa2:
        with st.popover("Search Member", use_container_width=True):
            search_code = st.text_input("Member Code", key="search_member_code")
            if search_code:
                profile = get_member_profile(conn, gym_id, search_code.strip())
                if profile:
                    st.success(f"Found member {profile['member']['member_code']}")
                    st.write(profile["member"])
                else:
                    st.error("Member not found.")

    with qa3:
        with st.popover("Export Daily Report", use_container_width=True):
            st.write("Download a lightweight report snapshot.")
            # handled outside with download button area

    st.markdown('</div>', unsafe_allow_html=True)


# =========================
# App
# =========================
st.set_page_config(page_title="Gym Admin Dashboard", layout="wide")
inject_css()

conn = connect()
init_db(conn)
gym_id = get_gym_id(conn)

if not gym_id:
    st.error("No gym found in database.")
    st.stop()

with st.sidebar:
    st.markdown("## Gym Dashboard")
    days = ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    selected_day = st.selectbox(
        "Select day",
        days,
        index=days.index(today_english_day()) if today_english_day() in days else 0
    )

    source_filter = st.selectbox(
        "Filter bookings by source",
        ["all", "telegram", "whatsapp", "waitlist"],
        index=0
    )

    all_classes = ["all"] + get_all_classes(conn, gym_id)
    all_coaches = ["all"] + get_all_coaches(conn, gym_id)

    class_filter = st.selectbox("Filter by class", all_classes, index=0)
    coach_filter = st.selectbox("Filter by coach", all_coaches, index=0)

    status_filter = st.selectbox(
        "Admin request status",
        ["all", "new", "in_progress", "contacted", "resolved", "archived"],
        index=0
    )

def top_branding():
    c1, c2, c3 = st.columns([1, 1.4, 1])
    with c2:
        if LOGO.exists():
            st.markdown('<div class="top-logo-wrap">', unsafe_allow_html=True)
            st.image(str(LOGO), width=220)
            st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="hero-title">Vibrant Fitness Dashboard</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="hero-sub">A cleaner, brighter control panel for classes, bookings, waitlist, attendance, and management requests.</div>',
        unsafe_allow_html=True,
    )

sessions_count, bookings_count, waitlist_count, admin_requests_count = get_summary(conn, gym_id, selected_day)
summary_vals = (sessions_count, bookings_count, waitlist_count, admin_requests_count)

k1, k2, k3, k4 = st.columns(4)
with k1:
    kpi_card("Classes Today", sessions_count, "kpi-blue")
with k2:
    kpi_card("Active Bookings", bookings_count, "kpi-pink")
with k3:
    kpi_card("Waitlist", waitlist_count, "kpi-purple")
with k4:
    kpi_card("Admin Requests", admin_requests_count, "kpi-mix")

quick_actions_panel(conn, gym_id)

alerts = get_alerts(conn, gym_id, selected_day)
activities = get_recent_activity(conn, gym_id)

t1, t2, t3, t4, t5, t6 = st.tabs([
    "Overview",
    "Analytics",
    "Bookings",
    "Attendance",
    "Waitlist",
    "Admin Requests",
])

with t1:
    section_header("Alerts & Overview", "Operational alerts, quick visuals, and class occupancy.")

    a1, a2 = st.columns([1.05, 1.25], vertical_alignment="top")
    with a1:
        st.markdown("### Alert Center")
        render_alerts(alerts)

        st.markdown("### Recent Activity")
        render_activity_feed(activities)

    with a2:
        c1, c2, c3 = st.columns(3)
        with c1:
            image_info_card(
                "Training Programs",
                "Showcase your main classes and class activity with a polished visual block.",
                BLUE_IMG,
                [("Blue Section", "chip-blue"), ("Performance", "chip-purple")]
            )
        with c2:
            image_info_card(
                "Cardio & Zumba",
                "Perfect for vibrant social content and energetic brand presentation.",
                PINK_IMG,
                [("Cardio", "chip-pink"), ("Popular", "chip-orange")]
            )
        with c3:
            image_info_card(
                "Strength & Premium",
                "Present premium classes, strength sessions, and coaching highlights.",
                PURPLE_IMG,
                [("Strength", "chip-purple"), ("Premium", "chip-green")]
            )

    section_header(
        f"Classes & Members — {selected_day}",
        "Every class is displayed as a separate clean card with occupancy status."
    )

    classes_data = get_today_classes_with_members(conn, gym_id, selected_day)
    if not classes_data:
        st.info("No classes for this day.")
    else:
        cols = st.columns(2)
        for i, item in enumerate(classes_data):
            with cols[i % 2]:
                class_card(item)

with t2:
    section_header("Analytics", "Booking trends, source mix, top classes, peak times, and rates.")

    source_df = get_source_split(conn, gym_id)
    by_day_df = get_bookings_by_day(conn, gym_id)
    top_classes_df = get_top_classes(conn, gym_id)
    peak_times_df = get_peak_times(conn, gym_id)
    attendance_rate, no_show_rate = get_rates(conn, gym_id)

    r1, r2 = st.columns([1, 1], vertical_alignment="top")
    with r1:
        if not source_df.empty:
            plot_donut(source_df, "source", "c", "Bookings by Source")
        else:
            st.info("No source data available.")

    with r2:
        plot_bar(by_day_df, "day", "bookings", "Bookings by Day")

    r3, r4 = st.columns([1, 1], vertical_alignment="top")
    with r3:
        if not top_classes_df.empty:
            plot_bar(top_classes_df, "class_name", "c", "Top Classes")
        else:
            st.info("No class analytics available.")

    with r4:
        if not peak_times_df.empty:
            plot_bar(peak_times_df, "time", "c", "Peak Times")
        else:
            st.info("No peak-time analytics available.")

    rr1, rr2 = st.columns(2)
    with rr1:
        st.metric("Attendance Rate", f"{attendance_rate}%")
    with rr2:
        st.metric("No-show Rate", f"{no_show_rate}%")

with t3:
    section_header("Active Bookings", "Manage check-in, no-show, cancellation, and member search.")

    bookings_df = get_active_bookings(
        conn,
        gym_id,
        source_filter=source_filter,
        class_filter=class_filter,
        coach_filter=coach_filter
    )

    search_code = st.text_input("Search by member code", "")
    if search_code.strip() and not bookings_df.empty:
        bookings_df = bookings_df[bookings_df["member_code"].astype(str).str.contains(search_code.strip(), case=False, na=False)]

    cexp1, cexp2 = st.columns(2)
    with cexp1:
        st.download_button(
            "Export bookings CSV",
            data=to_csv_bytes(bookings_df if not bookings_df.empty else pd.DataFrame()),
            file_name=f"bookings_{selected_day}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with cexp2:
        st.download_button(
            "Download daily report",
            data=pdf_like_text_report(selected_day, summary_vals, activities),
            file_name=f"daily_report_{selected_day}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    if bookings_df.empty:
        st.info("No active bookings.")
    else:
        for _, row in bookings_df.iterrows():
            booking_card(conn, gym_id, row)

    st.markdown("---")
    section_header("Member Profile", "Search a member to view booking and attendance history.")
    member_lookup = st.text_input("Member code for profile", key="member_profile_lookup")

    if member_lookup.strip():
        profile = get_member_profile(conn, gym_id, member_lookup.strip())
        if not profile:
            st.warning("Member not found.")
        else:
            st.subheader(f"Member {profile['member']['member_code']}")
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Full Name", profile["member"]["full_name"] or "-")
            with m2:
                st.metric("Phone", profile["member"]["phone"] or "-")
            with m3:
                st.metric("Status", profile["member"]["status"] or "-")
            with m4:
                st.metric("No-show Count", profile["no_show_count"])

            st.markdown("#### Booking History")
            if profile["bookings"]:
                st.dataframe(pd.DataFrame(profile["bookings"]), use_container_width=True, hide_index=True)
            else:
                st.caption("No bookings found.")

            st.markdown("#### Attendance History")
            if profile["attendance"]:
                st.dataframe(pd.DataFrame(profile["attendance"]), use_container_width=True, hide_index=True)
            else:
                st.caption("No attendance found.")

with t4:
    section_header("Attendance", "Attendance records for the selected day.")
    attendance_df = get_attendance(conn, gym_id, selected_day)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Export attendance CSV",
            data=to_csv_bytes(attendance_df if not attendance_df.empty else pd.DataFrame()),
            file_name=f"attendance_{selected_day}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    if attendance_df.empty:
        st.info("No attendance records for this day.")
    else:
        st.dataframe(attendance_df, use_container_width=True, hide_index=True)

with t5:
    section_header("Waitlist", "Members waiting for fully booked sessions.")
    waitlist_df = get_waitlist(conn, gym_id)

    st.download_button(
        "Export waitlist CSV",
        data=to_csv_bytes(waitlist_df if not waitlist_df.empty else pd.DataFrame()),
        file_name="waitlist.csv",
        mime="text/csv",
        use_container_width=True,
    )

    if waitlist_df.empty:
        st.info("Waitlist is empty.")
    else:
        st.dataframe(waitlist_df, use_container_width=True, hide_index=True)

with t6:
    section_header("Admin Contact Requests", "Requests received from Telegram and WhatsApp with workflow states.")
    admin_requests_df = get_admin_contact_requests(conn, gym_id, status_filter=status_filter)

    st.download_button(
        "Export admin requests CSV",
        data=to_csv_bytes(admin_requests_df if not admin_requests_df.empty else pd.DataFrame()),
        file_name="admin_requests.csv",
        mime="text/csv",
        use_container_width=True,
    )

    if admin_requests_df.empty:
        st.info("No admin contact requests.")
    else:
        for _, row in admin_requests_df.iterrows():
            admin_request_card(conn, row)

conn.close()