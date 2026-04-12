import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from database.db import init_db, get_or_create_gym
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

DB_PATH = "database/gym.sqlite3"
TZ = "Africa/Cairo"

ASSETS = Path("assets")
LOGO = ASSETS / "logo_white.png"
if not LOGO.exists():
    LOGO = ASSETS / "logo.png"

BLUE_IMG   = ASSETS / "blue_fitness.jpg"
PINK_IMG   = ASSETS / "pink_fitness.png"
PURPLE_IMG = ASSETS / "purble_fitness.jpg"

# ── Palette ────────────────────────────────────────────────────────────────
BG        = "#050B16"
SURFACE   = "#0D1A30"
SURFACE2  = "#111D37"
TEXT      = "#F0F6FF"
MUTED     = "#8A9DC0"
BORDER    = "rgba(255,255,255,0.07)"

BLUE    = "#1A8FFF"
CYAN    = "#22DEFF"
PINK    = "#FF3DA8"
MAGENTA = "#FF7DE0"
PURPLE  = "#7C4DFF"
LAVENDER= "#B18AFF"
GREEN   = "#1AD98A"
ORANGE  = "#FFAA00"
RED     = "#FF4F6D"

PLOTLY_TEMPLATE = dict(
    layout=dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,26,48,0.7)",
        font=dict(color=TEXT, family="'DM Sans', sans-serif", size=12),
        colorway=[BLUE, PINK, PURPLE, GREEN, ORANGE, CYAN, RED, LAVENDER],
        margin=dict(l=16, r=16, t=36, b=36),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.08)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.08)"),
    )
)


# =============================================================================
# Core helpers
# =============================================================================
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_cairo() -> str:
    return datetime.now(ZoneInfo(TZ)).isoformat(timespec="seconds")

def today_english_day() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%A")

def get_gym_id(conn):
    row = conn.execute("SELECT id FROM gyms ORDER BY id DESC LIMIT 1").fetchone()
    return int(row["id"]) if row else None


# =============================================================================
# Queries  (unchanged logic, kept intact)
# =============================================================================
def get_summary(conn, gym_id, day):
    sessions_count = conn.execute(
        "SELECT COUNT(*) AS c FROM sessions WHERE gym_id=? AND day=? AND is_active=1",
        (gym_id, day)).fetchone()["c"]
    bookings_count = conn.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE gym_id=? AND status='booked'",
        (gym_id,)).fetchone()["c"]
    waitlist_count = conn.execute(
        "SELECT COUNT(*) AS c FROM waitlist WHERE gym_id=? AND status IN ('waiting','offered')",
        (gym_id,)).fetchone()["c"]
    admin_count = conn.execute(
        "SELECT COUNT(*) AS c FROM admin_contact_requests WHERE gym_id=? AND status='new'",
        (gym_id,)).fetchone()["c"]
    return int(sessions_count), int(bookings_count), int(waitlist_count), int(admin_count)


def get_today_classes_with_members(conn, gym_id, day):
    sessions = conn.execute("""
        SELECT id, class_name, COALESCE(start_at, time) AS time, coach, capacity
        FROM sessions WHERE gym_id=? AND day=? AND is_active=1 ORDER BY COALESCE(start_at, time)
    """, (gym_id, day)).fetchall()

    result = []
    for s in sessions:
        members = conn.execute("""
            SELECT m.member_code, COALESCE(m.full_name,'No Name') AS full_name
            FROM bookings b JOIN members m ON m.id=b.member_id
            WHERE b.gym_id=? AND b.session_id=? AND b.status='booked'
            ORDER BY m.full_name
        """, (gym_id, s["id"])).fetchall()
        member_names = [m["full_name"] if m["full_name"] != "No Name" else m["member_code"] for m in members]
        booked = len(member_names)
        cap    = int(s["capacity"])
        result.append({
            "session_id": s["id"], "class_name": s["class_name"],
            "time": s["time"], "coach": s["coach"], "capacity": cap,
            "booked_count": booked, "remaining": cap - booked,
            "members": member_names,
            "occupancy_ratio": (booked / cap) if cap else 0,
        })
    return result


def get_active_bookings(conn, gym_id, source_filter="all", class_filter="all", coach_filter="all"):
    q = """
        SELECT b.id AS booking_id, b.session_id, m.id AS member_id,
               m.member_code, COALESCE(m.full_name,'') AS full_name, m.phone,
               s.day, COALESCE(s.start_at, s.time) AS time, s.class_name, s.coach, b.created_at, b.source
        FROM bookings b JOIN members m ON m.id=b.member_id JOIN sessions s ON s.id=b.session_id
        WHERE b.gym_id=? AND b.status='booked'
    """
    params = [gym_id]
    if source_filter != "all":
        q += " AND b.source=?"; params.append(source_filter)
    if class_filter != "all":
        q += " AND s.class_name=?"; params.append(class_filter)
    if coach_filter != "all":
        q += " AND s.coach=?"; params.append(coach_filter)
    q += " ORDER BY s.day, s.time, b.created_at DESC"
    return pd.DataFrame([dict(r) for r in conn.execute(q, tuple(params)).fetchall()])


def get_waitlist(conn, gym_id):
    rows = conn.execute("""
        SELECT w.id AS waitlist_id, m.member_code, COALESCE(m.full_name,'') AS full_name,
               s.day, COALESCE(s.start_at, s.time) AS time, s.class_name, w.status, w.created_at, w.offered_until
        FROM waitlist w JOIN members m ON m.id=w.member_id JOIN sessions s ON s.id=w.session_id
        WHERE w.gym_id=? ORDER BY w.created_at ASC
    """, (gym_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_admin_contact_requests(conn, gym_id, status_filter="all"):
    q = """
        SELECT id, source, platform_user, full_name, phone, language, status, created_at
        FROM admin_contact_requests WHERE gym_id=?
    """
    params = [gym_id]
    if status_filter != "all":
        q += " AND status=?"; params.append(status_filter)
    q += " ORDER BY created_at DESC, id DESC"
    return pd.DataFrame([dict(r) for r in conn.execute(q, tuple(params)).fetchall()])


def get_attendance(conn, gym_id, day):
    rows = conn.execute("""
        SELECT s.day, COALESCE(s.start_at, s.time) AS time, s.class_name, m.member_code, a.status, a.checkin_at
        FROM attendance a JOIN sessions s ON s.id=a.session_id JOIN members m ON m.id=a.member_id
        WHERE a.gym_id=? AND s.day=? ORDER BY COALESCE(s.start_at, s.time), s.class_name, m.member_code
    """, (gym_id, day)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_all_classes(conn, gym_id):
    return [r["class_name"] for r in conn.execute(
        "SELECT DISTINCT class_name FROM sessions WHERE gym_id=? AND is_active=1 ORDER BY class_name",
        (gym_id,)).fetchall()]


def get_all_coaches(conn, gym_id):
    return [r["coach"] for r in conn.execute(
        "SELECT DISTINCT coach FROM sessions WHERE gym_id=? AND is_active=1 AND coach IS NOT NULL AND coach!='' ORDER BY coach",
        (gym_id,)).fetchall()]


def get_recent_activity(conn, gym_id, limit=12):
    rows = conn.execute("""
        SELECT b.created_at AS event_time,'booking_created' AS event_type,'Booking Created' AS event_label,
               b.source,m.member_code,s.class_name,s.day,COALESCE(s.start_at,s.time) AS time
        FROM bookings b JOIN members m ON m.id=b.member_id JOIN sessions s ON s.id=b.session_id WHERE b.gym_id=?
        UNION ALL
        SELECT w.created_at,'waitlist_joined','Joined Waitlist','waitlist',m.member_code,s.class_name,s.day,COALESCE(s.start_at,s.time) AS time
        FROM waitlist w JOIN members m ON m.id=w.member_id JOIN sessions s ON s.id=w.session_id WHERE w.gym_id=?
        UNION ALL
        SELECT acr.created_at,'admin_request','Admin Request',acr.source,acr.platform_user,acr.full_name,'',''
        FROM admin_contact_requests acr WHERE acr.gym_id=?
        UNION ALL
        SELECT a.created_at,'attendance','Attendance Marked','attendance',m.member_code,s.class_name,s.day,COALESCE(s.start_at,s.time) AS time
        FROM attendance a JOIN members m ON m.id=a.member_id JOIN sessions s ON s.id=a.session_id WHERE a.gym_id=?
        ORDER BY event_time DESC LIMIT ?
    """, (gym_id, gym_id, gym_id, gym_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_member_profile(conn, gym_id, member_code):
    member = conn.execute("""
        SELECT id, member_code, COALESCE(full_name,'') AS full_name,
               COALESCE(phone,'') AS phone, COALESCE(status,'') AS status
        FROM members WHERE gym_id=? AND member_code=?
    """, (gym_id, member_code)).fetchone()
    if not member:
        return None
    bookings = conn.execute("""
        SELECT b.id AS booking_id, b.status, b.source, b.created_at,
               s.class_name, s.day, COALESCE(s.start_at, s.time) AS time, s.coach
        FROM bookings b JOIN sessions s ON s.id=b.session_id
        WHERE b.gym_id=? AND b.member_id=? ORDER BY b.created_at DESC
    """, (gym_id, member["id"])).fetchall()
    attendance = conn.execute("""
        SELECT a.status, a.checkin_at, a.created_at, s.class_name, s.day, COALESCE(s.start_at, s.time) AS time
        FROM attendance a JOIN sessions s ON s.id=a.session_id
        WHERE a.gym_id=? AND a.member_id=? ORDER BY a.created_at DESC
    """, (gym_id, member["id"])).fetchall()
    no_show = conn.execute(
        "SELECT COUNT(*) AS c FROM attendance WHERE gym_id=? AND member_id=? AND status='no_show'",
        (gym_id, member["id"])).fetchone()["c"]
    return {"member": dict(member), "bookings": [dict(r) for r in bookings],
            "attendance": [dict(r) for r in attendance], "no_show_count": int(no_show)}


def get_source_split(conn, gym_id):
    rows = conn.execute("""
        SELECT source, COUNT(*) AS c FROM bookings WHERE gym_id=? AND status='booked'
        GROUP BY source ORDER BY c DESC
    """, (gym_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_bookings_by_day(conn, gym_id):
    rows = conn.execute("""
        SELECT s.day, COUNT(*) AS c FROM bookings b JOIN sessions s ON s.id=b.session_id
        WHERE b.gym_id=? AND b.status='booked' GROUP BY s.day
    """, (gym_id,)).fetchall()
    order   = ["Saturday","Sunday","Monday","Tuesday","Wednesday","Thursday","Friday"]
    mapping = {r["day"]: int(r["c"]) for r in rows}
    return pd.DataFrame({"day": order, "bookings": [mapping.get(d, 0) for d in order]})


def get_top_classes(conn, gym_id):
    rows = conn.execute("""
        SELECT s.class_name, COUNT(*) AS c FROM bookings b JOIN sessions s ON s.id=b.session_id
        WHERE b.gym_id=? AND b.status='booked' GROUP BY s.class_name ORDER BY c DESC, s.class_name ASC LIMIT 8
    """, (gym_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_peak_times(conn, gym_id):
    rows = conn.execute("""
        SELECT COALESCE(s.start_at, s.time) AS time, COUNT(*) AS c FROM bookings b JOIN sessions s ON s.id=b.session_id
        WHERE b.gym_id=? AND b.status='booked' GROUP BY COALESCE(s.start_at, s.time) ORDER BY c DESC, COALESCE(s.start_at, s.time) ASC LIMIT 8
    """, (gym_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_rates(conn, gym_id):
    total    = conn.execute("SELECT COUNT(*) AS c FROM bookings WHERE gym_id=?", (gym_id,)).fetchone()["c"]
    attended = conn.execute("SELECT COUNT(*) AS c FROM attendance WHERE gym_id=? AND status='attended'", (gym_id,)).fetchone()["c"]
    no_show  = conn.execute("SELECT COUNT(*) AS c FROM attendance WHERE gym_id=? AND status='no_show'", (gym_id,)).fetchone()["c"]
    att_rate = (int(attended)/int(total)*100) if total else 0
    ns_rate  = (int(no_show)/int(total)*100) if total else 0
    return round(att_rate, 1), round(ns_rate, 1)


def get_alerts(conn, gym_id, selected_day):
    alerts = []
    full_classes = conn.execute("""
        SELECT s.class_name, COALESCE(s.start_at, s.time) AS time, s.capacity,
               (SELECT COUNT(*) FROM bookings b WHERE b.session_id=s.id AND b.gym_id=s.gym_id AND b.status='booked') AS booked
        FROM sessions s WHERE s.gym_id=? AND s.day=? AND s.is_active=1
    """, (gym_id, selected_day)).fetchall()
    for r in full_classes:
        booked, cap = int(r["booked"]), int(r["capacity"])
        if booked >= cap:
            alerts.append({"level":"danger","title":f"🔴 {r['class_name']} is Full","desc":f"{r['time']} has reached maximum capacity."})
        elif cap > 0 and booked/cap >= 0.8:
            alerts.append({"level":"warning","title":f"🟡 {r['class_name']} Almost Full","desc":f"{r['time']} is above 80% occupancy."})
    new_req = conn.execute("SELECT COUNT(*) AS c FROM admin_contact_requests WHERE gym_id=? AND status='new'",(gym_id,)).fetchone()["c"]
    if int(new_req) > 0:
        alerts.append({"level":"info","title":f"🔵 {new_req} New Admin Request(s)","desc":"Pending requests need your attention."})
    offered = conn.execute("SELECT COUNT(*) AS c FROM waitlist WHERE gym_id=? AND status='offered'",(gym_id,)).fetchone()["c"]
    if int(offered) > 0:
        alerts.append({"level":"warning","title":f"🟡 {offered} Waitlist Offer(s) Pending","desc":"Members haven't confirmed their offered spots."})
    repeat_ns = conn.execute("""
        SELECT m.member_code, COUNT(*) AS c FROM attendance a JOIN members m ON m.id=a.member_id
        WHERE a.gym_id=? AND a.status='no_show' GROUP BY m.member_code HAVING COUNT(*)>=2 ORDER BY c DESC LIMIT 3
    """, (gym_id,)).fetchall()
    for r in repeat_ns:
        alerts.append({"level":"danger","title":f"🔴 Repeat No-show: {r['member_code']}","desc":f"{r['c']} no-show records found."})
    return alerts[:8]


# =============================================================================
# Actions
# =============================================================================
def update_admin_request_status(conn, request_id, status):
    conn.execute("UPDATE admin_contact_requests SET status=? WHERE id=?", (status, request_id))
    conn.commit()

def cancel_booking_by_id(conn, booking_id):
    conn.execute("UPDATE bookings SET status='cancelled', cancelled_at=? WHERE id=? AND status='booked'",
                 (now_cairo(), booking_id))
    conn.commit()

def checkin_booking_by_id(conn, gym_id, booking_id):
    booking = conn.execute(
        "SELECT id, session_id, member_id FROM bookings WHERE id=? AND gym_id=? AND status='booked'",
        (booking_id, gym_id)).fetchone()
    if not booking:
        return False
    conn.execute("""
        INSERT OR REPLACE INTO attendance(gym_id,session_id,member_id,status,checkin_at,created_at)
        VALUES(?,?,?,?,?,?)
    """, (gym_id, booking["session_id"], booking["member_id"], "attended", now_cairo(), now_cairo()))
    conn.execute("UPDATE bookings SET status='attended' WHERE id=?", (booking_id,))
    conn.commit()
    return True

def no_show_booking_by_id(conn, gym_id, booking_id):
    booking = conn.execute(
        "SELECT id, session_id, member_id FROM bookings WHERE id=? AND gym_id=? AND status='booked'",
        (booking_id, gym_id)).fetchone()
    if not booking:
        return False
    conn.execute("""
        INSERT OR REPLACE INTO attendance(gym_id,session_id,member_id,status,created_at)
        VALUES(?,?,?,?,?)
    """, (gym_id, booking["session_id"], booking["member_id"], "no_show", now_cairo()))
    conn.execute("UPDATE bookings SET status='no_show' WHERE id=?", (booking_id,))
    conn.commit()
    return True


# =============================================================================
# Export helpers
# =============================================================================
def to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8-sig")

def pdf_like_text_report(selected_day, summary_vals, activities):
    sessions_count, bookings_count, waitlist_count, admin_requests_count = summary_vals
    lines = [
        "GYM DAILY REPORT", "",
        f"Day: {selected_day}",
        f"Classes Today: {sessions_count}",
        f"Active Bookings: {bookings_count}",
        f"Waitlist: {waitlist_count}",
        f"Admin Requests: {admin_requests_count}", "",
        "RECENT ACTIVITY", "---",
    ]
    for item in activities:
        lines.append(f"{item.get('event_time','')} | {item.get('event_label','')} | "
                     f"{item.get('member_code','')} | {item.get('class_name','')} | "
                     f"{item.get('day','')} {item.get('time','')}")
    return "\n".join(lines).encode("utf-8")


# =============================================================================
# CSS injection
# =============================================================================
def inject_css():
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700;800;900&family=Space+Mono:wght@400;700&display=swap');

    *, *::before, *::after {{ box-sizing: border-box; }}

        /* ── Hide sidebar entirely ── */
        section[data-testid="stSidebar"] {{
            display: none !important;
        }}
        .stMainBlockContainer {{
            padding-left: 1.2rem !important;
        }}


    html, body, .stApp {{
        font-family: 'DM Sans', sans-serif !important;
        background: {BG};
        color: {TEXT};
    }}

    .stApp {{
        background:
            radial-gradient(ellipse 60% 45% at 0% 0%, rgba(26,143,255,0.13) 0%, transparent 60%),
            radial-gradient(ellipse 50% 40% at 100% 0%, rgba(255,61,168,0.11) 0%, transparent 60%),
            radial-gradient(ellipse 40% 35% at 100% 100%, rgba(124,77,255,0.09) 0%, transparent 55%),
            linear-gradient(175deg, #060D1C 0%, #030810 100%);
    }}

    /* ── Layout ── */
    .block-container {{
        max-width: 100% !important;
        padding: 0.5rem 1.2rem 2rem !important;
    }}
    section.main > div {{ padding-top: 0 !important; }}
    header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer {{ display: none !important; visibility: hidden !important; }}

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #080F1F 0%, #060C1A 100%) !important;
        border-right: 1px solid {BORDER} !important;
        padding-top: 0 !important;
    }}
    section[data-testid="stSidebar"] .block-container {{
        padding: 1.2rem 1rem 2rem !important;
    }}
    .sidebar-logo {{
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 14px 4px 18px;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 20px;
    }}
    .sidebar-logo-text {{
        font-size: 16px;
        font-weight: 800;
        color: {TEXT};
        letter-spacing: -0.02em;
        line-height: 1.2;
    }}
    .sidebar-logo-sub {{
        font-size: 11px;
        color: {MUTED};
        font-weight: 500;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }}
    .sidebar-section-label {{
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: {MUTED};
        margin: 20px 0 8px;
        padding-left: 2px;
    }}

    /* Sidebar selectbox labels */
    section[data-testid="stSidebar"] label {{
        font-size: 12px !important;
        font-weight: 600 !important;
        color: {MUTED} !important;
        letter-spacing: 0.04em !important;
        text-transform: uppercase !important;
    }}

    /* ── Hero / Branding ── */
    .dash-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 18px 0 14px;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 22px;
    }}
    .dash-title {{
        font-size: 28px;
        font-weight: 900;
        letter-spacing: -0.035em;
        color: {TEXT};
        line-height: 1;
    }}
    .dash-subtitle {{
        font-size: 13px;
        color: {MUTED};
        margin-top: 4px;
        font-weight: 400;
    }}
    .dash-badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: rgba(26,143,255,0.12);
        border: 1px solid rgba(26,143,255,0.25);
        border-radius: 999px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 700;
        color: #7BC8FF;
        letter-spacing: 0.03em;
    }}
    .live-dot {{
        width: 7px; height: 7px;
        border-radius: 50%;
        background: {GREEN};
        box-shadow: 0 0 8px {GREEN};
        animation: pulseDot 1.8s ease-in-out infinite;
    }}

    /* ── KPI Cards ── */
    .kpi-row {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 14px;
        margin-bottom: 20px;
    }}
    .kpi-card {{
        border-radius: 20px;
        padding: 20px 22px;
        position: relative;
        overflow: hidden;
        cursor: default;
        transition: transform 0.22s ease, box-shadow 0.22s ease;
        animation: fadeUp 0.6s ease both;
    }}
    .kpi-card::before {{
        content: "";
        position: absolute;
        inset: 0;
        background: rgba(255,255,255,0.04);
        border-radius: inherit;
        opacity: 0;
        transition: opacity 0.2s;
    }}
    .kpi-card:hover {{ transform: translateY(-5px) scale(1.015); box-shadow: 0 24px 48px rgba(0,0,0,0.30); }}
    .kpi-card:hover::before {{ opacity: 1; }}
    .kpi-blue   {{ background: linear-gradient(135deg, #0E6FCC, {BLUE}); box-shadow: 0 12px 32px rgba(26,143,255,0.22); }}
    .kpi-pink   {{ background: linear-gradient(135deg, #CC1A7A, {PINK}); box-shadow: 0 12px 32px rgba(255,61,168,0.22); }}
    .kpi-purple {{ background: linear-gradient(135deg, #5A28CC, {PURPLE}); box-shadow: 0 12px 32px rgba(124,77,255,0.22); }}
    .kpi-green  {{ background: linear-gradient(135deg, #0FA865, {GREEN}); box-shadow: 0 12px 32px rgba(26,217,138,0.22); }}
    .kpi-icon {{
        font-size: 22px;
        margin-bottom: 14px;
        display: block;
        opacity: 0.92;
    }}
    .kpi-value {{
        font-size: 38px;
        font-weight: 900;
        letter-spacing: -0.04em;
        color: white;
        line-height: 1;
        margin-bottom: 6px;
    }}
    .kpi-label {{
        font-size: 13px;
        font-weight: 600;
        color: rgba(255,255,255,0.82);
        letter-spacing: 0.01em;
    }}
    .kpi-glow {{
        position: absolute;
        bottom: -20px; right: -20px;
        width: 80px; height: 80px;
        border-radius: 50%;
        background: rgba(255,255,255,0.08);
        pointer-events: none;
    }}

    /* ── Section headers ── */
    .sec-header {{
        display: flex;
        align-items: baseline;
        gap: 12px;
        margin: 24px 0 14px;
    }}
    .sec-title {{
        font-size: 20px;
        font-weight: 800;
        letter-spacing: -0.025em;
        color: {TEXT};
    }}
    .sec-dot {{
        width: 6px; height: 6px;
        border-radius: 50%;
        background: {BLUE};
        flex-shrink: 0;
        margin-bottom: 2px;
        box-shadow: 0 0 10px {BLUE};
    }}
    .sec-sub {{
        font-size: 13px;
        color: {MUTED};
        margin-bottom: 16px;
        font-weight: 400;
    }}

    /* ── Tabs ── */
    div[data-testid="stTabs"] {{
        margin-top: 2px !important;
    }}
    div[data-testid="stTabs"] > div:first-child {{
        border-bottom: 1px solid {BORDER} !important;
        gap: 4px;
    }}
    div[data-testid="stTabs"] button {{
        font-family: 'DM Sans', sans-serif !important;
        font-size: 13px !important;
        font-weight: 700 !important;
        color: {MUTED} !important;
        padding: 8px 16px !important;
        border-radius: 10px 10px 0 0 !important;
        border: none !important;
        background: transparent !important;
        transition: color 0.18s, background 0.18s !important;
        letter-spacing: 0.01em !important;
    }}
    div[data-testid="stTabs"] button:hover {{
        color: {TEXT} !important;
        background: rgba(255,255,255,0.04) !important;
    }}
    div[data-testid="stTabs"] button[aria-selected="true"] {{
        color: {TEXT} !important;
        background: rgba(26,143,255,0.10) !important;
        border-bottom: 2px solid {BLUE} !important;
    }}

    /* ── Cards ── */
    .card {{
        background: linear-gradient(180deg, rgba(13,26,48,0.95), rgba(9,17,33,0.95));
        border: 1px solid {BORDER};
        border-radius: 18px;
        padding: 18px 20px;
        margin-bottom: 12px;
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
        animation: fadeUp 0.5s ease both;
    }}
    .card:hover {{
        transform: translateY(-4px);
        box-shadow: 0 20px 42px rgba(0,0,0,0.25);
        border-color: rgba(26,143,255,0.18);
    }}
    .card-title {{
        font-size: 18px;
        font-weight: 800;
        color: {TEXT};
        letter-spacing: -0.02em;
        margin-bottom: 10px;
    }}

    /* ── Class card ── */
    .class-card {{
        background: linear-gradient(160deg, rgba(13,26,48,0.98), rgba(8,15,28,0.98));
        border: 1px solid {BORDER};
        border-radius: 22px;
        padding: 22px 24px;
        margin-bottom: 16px;
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
        animation: fadeUp 0.55s ease both;
        position: relative;
        overflow: hidden;
    }}
    .class-card::after {{
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
        background: linear-gradient(90deg, {BLUE}, {PURPLE}, {PINK});
        opacity: 0;
        transition: opacity 0.2s;
    }}
    .class-card:hover {{
        transform: translateY(-5px);
        box-shadow: 0 22px 46px rgba(0,0,0,0.28);
        border-color: rgba(26,143,255,0.20);
    }}
    .class-card:hover::after {{ opacity: 1; }}
    .class-name {{
        font-size: 24px;
        font-weight: 900;
        color: {TEXT};
        letter-spacing: -0.03em;
        margin-bottom: 12px;
    }}

    /* ── Occupancy bar ── */
    .occ-wrap {{ margin: 14px 0 6px; }}
    .occ-track {{
        width: 100%;
        height: 8px;
        background: rgba(255,255,255,0.07);
        border-radius: 999px;
        overflow: hidden;
    }}
    .occ-fill {{
        height: 100%;
        border-radius: 999px;
        animation: fillGrow 1s ease-out both;
        position: relative;
    }}
    .occ-fill::after {{
        content: "";
        position: absolute; inset: 0;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.22), transparent);
        animation: shimmer 2s linear infinite;
    }}
    .occ-caption {{
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        color: {MUTED};
        margin-top: 6px;
        font-weight: 500;
    }}

    /* ── Chips ── */
    .chip {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.02em;
        margin: 0 4px 6px 0;
    }}
    .chip-blue   {{ background: rgba(26,143,255,0.14);  color: #90CEFF; border: 1px solid rgba(26,143,255,0.2); }}
    .chip-pink   {{ background: rgba(255,61,168,0.14);  color: #FFB0DF; border: 1px solid rgba(255,61,168,0.2); }}
    .chip-purple {{ background: rgba(124,77,255,0.14);  color: #C4AAFF; border: 1px solid rgba(124,77,255,0.2); }}
    .chip-green  {{ background: rgba(26,217,138,0.14);  color: #A0F5D0; border: 1px solid rgba(26,217,138,0.2); }}
    .chip-orange {{ background: rgba(255,170,0,0.14);   color: #FFDEA0; border: 1px solid rgba(255,170,0,0.2); }}
    .chip-red    {{ background: rgba(255,79,109,0.14);  color: #FFB0BE; border: 1px solid rgba(255,79,109,0.2); }}

    /* ── Stat boxes ── */
    .stat-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin: 14px 0;
    }}
    .stat-box {{
        background: rgba(255,255,255,0.04);
        border: 1px solid {BORDER};
        border-radius: 14px;
        padding: 12px 14px;
        transition: background 0.18s;
    }}
    .stat-box:hover {{ background: rgba(255,255,255,0.07); }}
    .stat-label {{ font-size: 11px; font-weight: 600; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }}
    .stat-value {{ font-size: 20px; font-weight: 800; color: {TEXT}; letter-spacing: -0.02em; }}

    /* ── Member list ── */
    .member-section {{ margin-top: 14px; padding-top: 14px; border-top: 1px solid {BORDER}; }}
    .member-section-title {{ font-size: 12px; font-weight: 700; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }}
    .member-pill {{
        display: inline-flex;
        align-items: center;
        background: rgba(255,255,255,0.05);
        border: 1px solid {BORDER};
        border-radius: 999px;
        padding: 5px 13px;
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
        margin: 3px;
    }}

    /* ── Alert cards ── */
    .alert-card {{
        border-radius: 14px;
        padding: 13px 16px;
        margin-bottom: 8px;
        border: 1px solid transparent;
        animation: fadeUp 0.5s ease both;
    }}
    .alert-info    {{ background: rgba(26,143,255,0.09);  border-color: rgba(26,143,255,0.18); }}
    .alert-warning {{ background: rgba(255,170,0,0.09);   border-color: rgba(255,170,0,0.18); }}
    .alert-danger  {{ background: rgba(255,79,109,0.09);  border-color: rgba(255,79,109,0.18); }}
    .alert-title {{ font-size: 14px; font-weight: 800; color: {TEXT}; margin-bottom: 3px; }}
    .alert-desc  {{ font-size: 13px; color: {MUTED}; line-height: 1.45; }}

    /* ── Activity feed ── */
    .activity-item {{
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 12px 0;
        border-bottom: 1px solid {BORDER};
        animation: fadeUp 0.5s ease both;
    }}
    .activity-item:last-child {{ border-bottom: none; }}
    .activity-dot {{
        width: 8px; height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
        margin-top: 5px;
    }}
    .activity-label {{ font-size: 14px; font-weight: 700; color: {TEXT}; margin-bottom: 2px; }}
    .activity-meta  {{ font-size: 12px; color: {MUTED}; font-weight: 400; font-family: 'Space Mono', monospace; }}

    /* ── Booking / request cards ── */
    .action-card {{
        background: linear-gradient(160deg, rgba(13,26,48,0.95), rgba(8,15,28,0.98));
        border: 1px solid {BORDER};
        border-radius: 18px;
        padding: 18px 20px;
        margin-bottom: 14px;
        animation: fadeUp 0.5s ease both;
        transition: border-color 0.2s;
    }}
    .action-card:hover {{ border-color: rgba(26,143,255,0.20); }}
    .action-title {{ font-size: 19px; font-weight: 800; color: {TEXT}; letter-spacing: -0.025em; margin: 10px 0 14px; }}

    /* ── Metrics override ── */
    [data-testid="stMetric"] {{
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid {BORDER} !important;
        border-radius: 14px !important;
        padding: 12px 16px !important;
    }}
    [data-testid="stMetricLabel"] {{ color: {MUTED} !important; font-size: 12px !important; font-weight: 600 !important; text-transform: uppercase !important; letter-spacing: 0.05em !important; }}
    [data-testid="stMetricValue"] {{ color: {TEXT} !important; font-size: 22px !important; font-weight: 800 !important; letter-spacing: -0.02em !important; }}

    /* ── DataFrames ── */
    [data-testid="stDataFrame"] {{
        border: 1px solid {BORDER} !important;
        border-radius: 16px !important;
        overflow: hidden !important;
    }}

    /* ── Buttons ── */
    .stButton > button {{
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid {BORDER} !important;
        color: {TEXT} !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 13px !important;
        font-family: 'DM Sans', sans-serif !important;
        padding: 8px 18px !important;
        transition: background 0.18s, border-color 0.18s, transform 0.15s !important;
    }}
    .stButton > button:hover {{
        background: rgba(26,143,255,0.14) !important;
        border-color: rgba(26,143,255,0.35) !important;
        transform: translateY(-2px) !important;
    }}

    /* ── Quick actions panel ── */
    .quick-panel {{
        background: rgba(255,255,255,0.03);
        border: 1px solid {BORDER};
        border-radius: 18px;
        padding: 16px 20px;
        margin-bottom: 22px;
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .quick-label {{
        font-size: 12px;
        font-weight: 700;
        color: {MUTED};
        text-transform: uppercase;
        letter-spacing: 0.08em;
        white-space: nowrap;
        margin-right: 8px;
    }}

    /* ── Keyframes ── */
    @keyframes fadeUp {{
        from {{ opacity: 0; transform: translateY(14px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes pulseDot {{
        0%, 100% {{ opacity: 1; box-shadow: 0 0 6px {GREEN}; }}
        50%       {{ opacity: 0.6; box-shadow: 0 0 14px {GREEN}; }}
    }}
    @keyframes fillGrow {{
        from {{ width: 0%; }}
    }}
    @keyframes shimmer {{
        from {{ transform: translateX(-100%); }}
        to   {{ transform: translateX(300%); }}
    }}
    </style>
    """, unsafe_allow_html=True)


# =============================================================================
# UI components
# =============================================================================
def render_kpi_row(sessions_count, bookings_count, waitlist_count, admin_requests_count):
    kpis = [
        ("📅", sessions_count, "Classes Today",    "kpi-blue"),
        ("🎟", bookings_count, "Active Bookings",  "kpi-pink"),
        ("⏳", waitlist_count, "On Waitlist",      "kpi-purple"),
        ("📬", admin_requests_count, "New Requests", "kpi-green"),
    ]
    cols = st.columns(4)
    for col, (icon, val, label, cls) in zip(cols, kpis):
        with col:
            st.markdown(f"""
            <div class="kpi-card {cls}">
                <span class="kpi-icon">{icon}</span>
                <div class="kpi-value">{val}</div>
                <div class="kpi-label">{label}</div>
                <div class="kpi-glow"></div>
            </div>
            """, unsafe_allow_html=True)


def section_header(title: str, subtitle: str = ""):
    st.markdown(f"""
    <div class="sec-header">
        <div class="sec-dot"></div>
        <div class="sec-title">{title}</div>
    </div>
    {"" if not subtitle else f'<div class="sec-sub">{subtitle}</div>'}
    """, unsafe_allow_html=True)


def render_chip(text, variant="blue"):
    return f'<span class="chip chip-{variant}">{text}</span>'


def occupancy_color(ratio):
    if ratio >= 1:   return "red",    "#FF4F6D"
    if ratio >= 0.8: return "orange", "#FFAA00"
    return "green", "#1AD98A"


def class_card(item):
    status_lbl, bar_hex = occupancy_color(item["occupancy_ratio"])
    status_text = {"red": "🔴 Full", "orange": "🟡 Almost Full", "green": "🟢 Available"}.get(status_lbl, "Available")
    percent = int(item["occupancy_ratio"] * 100)

    # Card header
    st.markdown(f"""
    <div class="class-card">
        <div class="class-name">{item["class_name"]}</div>
        <div style="margin-bottom:10px;">
            <span class="chip chip-blue">🕐 {item["time"]}</span>
            <span class="chip chip-pink">🏋 {item["coach"]}</span>
            <span class="chip chip-{status_lbl}">{status_text}</span>
        </div>
        <div class="occ-wrap">
            <div class="occ-track">
                <div class="occ-fill" style="width:{percent}%; background:{bar_hex};"></div>
            </div>
            <div class="occ-caption">
                <span>{item["booked_count"]} booked</span>
                <span>{item["remaining"]} remaining · {percent}%</span>
            </div>
        </div>
        <div class="stat-grid">
            <div class="stat-box"><div class="stat-label">Capacity</div><div class="stat-value">{item["capacity"]}</div></div>
            <div class="stat-box"><div class="stat-label">Booked</div><div class="stat-value">{item["booked_count"]}</div></div>
            <div class="stat-box"><div class="stat-label">Remaining</div><div class="stat-value">{item["remaining"]}</div></div>
            <div class="stat-box"><div class="stat-label">Session ID</div><div class="stat-value">#{item["session_id"]}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Members — rendered with native Streamlit inside the card area
    if item["members"]:
        st.markdown(f"""<div style="padding:10px 4px 4px; border-top:1px solid rgba(255,255,255,0.07); margin-top:2px;">
            <div style="font-size:11px;font-weight:700;color:{MUTED};text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;">
                👥 Booked Members ({item["booked_count"]})
            </div></div>""", unsafe_allow_html=True)
        # show members as pills using columns
        member_chunks = [item["members"][i:i+3] for i in range(0, len(item["members"]), 3)]
        for chunk in member_chunks:
            row_cols = st.columns(len(chunk))
            for col, name in zip(row_cols, chunk):
                col.markdown(f"""<div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.09);
                    border-radius:999px;padding:6px 12px;font-size:13px;font-weight:600;
                    color:{TEXT};text-align:center;margin-bottom:6px;">👤 {name}</div>""",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"""<div style="color:{MUTED};font-size:13px;padding:8px 4px;">No bookings yet.</div>""",
            unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


def render_alerts(alerts):
    if not alerts:
        st.markdown('<div class="alert-card alert-info"><div class="alert-title">✅ All Clear</div><div class="alert-desc">No active alerts at this time.</div></div>', unsafe_allow_html=True)
        return
    for a in alerts:
        lvl = a["level"]
        st.markdown(f'<div class="alert-card alert-{lvl}"><div class="alert-title">{a["title"]}</div><div class="alert-desc">{a["desc"]}</div></div>', unsafe_allow_html=True)


def render_activity_feed(items):
    if not items:
        st.info("No recent activity.")
        return
    dot_colors = {
        "booking_created": BLUE,
        "waitlist_joined": PURPLE,
        "admin_request":   ORANGE,
        "attendance":      GREEN,
    }
    feed_html = ""
    for item in items:
        color = dot_colors.get(item.get("event_type", ""), MUTED)
        raw_time = item.get('event_time', '')
        try:
            short_time = raw_time[11:16] if len(raw_time) >= 16 else raw_time
        except:
            short_time = raw_time
        meta  = f"{short_time} · {item.get('member_code','')} · {item.get('class_name','')} {item.get('day','')} {item.get('time','')}".strip(' ·')
        feed_html += f"""
        <div class="activity-item">
            <div class="activity-dot" style="background:{color}; box-shadow: 0 0 8px {color};"></div>
            <div>
                <div class="activity-label">{item.get('event_label','')}</div>
                <div class="activity-meta">{meta}</div>
            </div>
        </div>"""
    st.markdown(feed_html, unsafe_allow_html=True)


def booking_card(conn, gym_id, row):
    source_variant = {"telegram": "blue", "whatsapp": "green", "waitlist": "purple"}.get(row["source"], "blue")
    st.markdown(f"""
    <div class="action-card">
        <div>
            {render_chip(row['source'], source_variant)}
            {render_chip(row['day'], "purple")}
            {render_chip(row['time'], "blue")}
        </div>
        <div class="action-title">{row['class_name']}</div>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Booking ID", row["booking_id"])
    with c2: st.metric("Member", row["member_code"])
    with c3: st.metric("Coach", row["coach"])
    with c4: st.metric("Created", str(row["created_at"])[:16])
    a1, a2, a3 = st.columns(3)
    with a1:
        if st.button("✅ Check-in", key=f"ci_{row['booking_id']}", use_container_width=True):
            checkin_booking_by_id(conn, gym_id, int(row["booking_id"])) and st.success(f"Booking {row['booking_id']} attended.") or st.error("Already processed.")
            st.rerun()
    with a2:
        if st.button("❌ No-show", key=f"ns_{row['booking_id']}", use_container_width=True):
            no_show_booking_by_id(conn, gym_id, int(row["booking_id"])) and st.success(f"Booking {row['booking_id']} no-show.") or st.error("Already processed.")
            st.rerun()
    with a3:
        if st.button("🚫 Cancel", key=f"ca_{row['booking_id']}", use_container_width=True):
            cancel_booking_by_id(conn, int(row["booking_id"]))
            st.success(f"Booking {row['booking_id']} cancelled.")
            st.rerun()
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)


def admin_request_card(conn, row):
    status_variant = {"new":"blue","in_progress":"orange","done":"green","contacted":"purple","resolved":"green","archived":"orange"}.get(row["status"],"blue")
    st.markdown(f"""
    <div class="action-card">
        <div>
            {render_chip(row['status'], status_variant)}
            {render_chip(row['source'], "pink")}
            {render_chip(row['language'], "purple")}
        </div>
        <div class="action-title">{row['full_name'] or '—'}</div>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Request ID", row["id"])
    with c2: st.metric("Phone", row["phone"] or "—")
    with c3: st.metric("User", row["platform_user"] or "—")
    with c4: st.metric("Created", str(row["created_at"])[:16])
    statuses = ["new","in_progress","contacted","resolved","archived"]
    sc1, sc2 = st.columns([3, 1])
    with sc1:
        selected = st.selectbox("Update status", statuses,
            index=statuses.index(row["status"]) if row["status"] in statuses else 0,
            key=f"sel_{row['id']}")
    with sc2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("Save", key=f"save_{row['id']}", use_container_width=True):
            update_admin_request_status(conn, int(row["id"]), selected)
            st.success(f"Updated to {selected}.")
            st.rerun()
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)


def quick_actions_panel(conn, gym_id):
    qa1, qa2, qa3 = st.columns(3)
    with qa1:
        with st.popover("➕ Add Admin Request", use_container_width=True):
            with st.form("quick_admin_form"):
                full_name     = st.text_input("Name")
                phone         = st.text_input("Phone")
                language      = st.selectbox("Language", ["ar","en"])
                source        = st.selectbox("Source", ["telegram","whatsapp"])
                platform_user = st.text_input("Platform User")
                if st.form_submit_button("Save") and full_name and phone:
                    conn.execute("""
                        INSERT INTO admin_contact_requests
                        (gym_id,source,platform_user,full_name,phone,language,status,created_at)
                        VALUES(?,?,?,?,?,?,?,?)
                    """, (gym_id, source, platform_user, full_name, phone, language, "new", now_cairo()))
                    conn.commit()
                    st.success("Request added.")
                    st.rerun()
    with qa2:
        with st.popover("🔍 Search Member", use_container_width=True):
            code = st.text_input("Member Code")
            if code:
                p = get_member_profile(conn, gym_id, code.strip())
                if p:
                    st.success(f"Found: {p['member']['member_code']}")
                    st.write(p["member"])
                else:
                    st.error("Member not found.")
    with qa3:
        with st.popover("📋 About Exports", use_container_width=True):
            st.write("Use the **Bookings** and **Attendance** tabs to download CSV files for any day.")


def make_plotly_bar(df, x_col, y_col, title, color=BLUE):
    fig = go.Figure(go.Bar(
        x=df[x_col], y=df[y_col],
        marker=dict(
            color=color,
            opacity=0.85,
            line=dict(width=0),
        ),
        hovertemplate=f"<b>%{{x}}</b><br>{y_col.title()}: %{{y}}<extra></extra>",
    ))
    fig.update_layout(**PLOTLY_TEMPLATE["layout"], title=dict(text=title, font=dict(size=14, weight=700)))
    fig.update_xaxes(tickangle=-30)
    return fig


def make_plotly_donut(df, label_col, value_col, title):
    colors = [BLUE, PINK, PURPLE, GREEN, ORANGE, CYAN]
    fig = go.Figure(go.Pie(
        labels=df[label_col], values=df[value_col],
        hole=0.55,
        marker=dict(colors=colors[:len(df)], line=dict(color=BG, width=3)),
        hovertemplate="<b>%{label}</b><br>%{value} bookings (%{percent})<extra></extra>",
    ))
    fig.update_layout(**PLOTLY_TEMPLATE["layout"], title=dict(text=title, font=dict(size=14, weight=700)),
                      legend=dict(orientation="h", y=-0.12))
    return fig


# =============================================================================
# App entry point
# =============================================================================
st.set_page_config(page_title="Gym Admin Dashboard", layout="wide", page_icon="🏋️")
inject_css()

conn   = connect()
init_db(conn)
gym_id = get_gym_id(conn)

# ── Filters bar ──────────────────────────────────────────────────────────────
days = ["Saturday","Sunday","Monday","Tuesday","Wednesday","Thursday","Friday"]
now_str = datetime.now(ZoneInfo(TZ)).strftime("%d %b %Y · %H:%M")

st.markdown(f"""
<div style="
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 16px;
    padding: 12px 20px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 8px;
">
    <span style="font-size:12px; font-weight:700; color:{MUTED}; text-transform:uppercase; letter-spacing:0.08em; white-space:nowrap; margin-right:4px;">⚙ Filters</span>
</div>
""", unsafe_allow_html=True)

f1, f2, f3, f4, f5, f6 = st.columns([1.2, 1, 1, 1, 1, 1])
with f1:
    selected_day = st.selectbox("📅 Day", days,
        index=days.index(today_english_day()) if today_english_day() in days else 0)
with f2:
    source_filter = st.selectbox("📡 Source", ["all","telegram","whatsapp","waitlist"])
with f3:
    all_classes = ["all"] + get_all_classes(conn, gym_id)
    class_filter = st.selectbox("🏃 Class", all_classes)
with f4:
    all_coaches = ["all"] + get_all_coaches(conn, gym_id)
    coach_filter = st.selectbox("👤 Coach", all_coaches)
with f5:
    status_filter = st.selectbox("📬 Request Status", ["all","new","in_progress","contacted","resolved","archived"])
with f6:
    st.markdown(f"""
    <div style="padding:8px 12px; background:rgba(26,143,255,0.08); border:1px solid rgba(26,143,255,0.18);
    border-radius:12px; margin-top:28px; text-align:center;">
        <div style="font-size:10px; color:{MUTED}; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;">🕐 Cairo</div>
        <div style="font-size:15px; font-weight:800; color:{TEXT}; font-family:'Space Mono',monospace; margin-top:2px;">{now_str}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

# ── Dashboard header ──────────────────────────────────────────────────────────
st.markdown(f"""
<div class="dash-header" style="margin-top:0; padding-top:8px;">
    <div>
        <div class="dash-title">🏋️ Gym Admin Dashboard</div>
        <div class="dash-subtitle">Multi-gym booking management · {selected_day}</div>
    </div>
    <div class="dash-badge">
        <div class="live-dot"></div>
        Live
    </div>
</div>
""", unsafe_allow_html=True)

# ── KPIs ─────────────────────────────────────────────────────────────────────
sessions_count, bookings_count, waitlist_count, admin_requests_count = get_summary(conn, gym_id, selected_day)
summary_vals = (sessions_count, bookings_count, waitlist_count, admin_requests_count)
render_kpi_row(sessions_count, bookings_count, waitlist_count, admin_requests_count)

# ── Quick Actions ─────────────────────────────────────────────────────────────
section_header("Quick Actions")
quick_actions_panel(conn, gym_id)

# ── Data load ─────────────────────────────────────────────────────────────────
alerts     = get_alerts(conn, gym_id, selected_day)
activities = get_recent_activity(conn, gym_id)

# ── Tabs ──────────────────────────────────────────────────────────────────────
t1, t2, t3, t4, t5, t6 = st.tabs([
    "📊 Overview", "📈 Analytics", "🎟 Bookings",
    "✅ Attendance", "⏳ Waitlist", "📬 Admin Requests",
])

# ─────────────────── TAB 1 — OVERVIEW ────────────────────────────────────────
with t1:
    # Alerts + Activity
    left, right = st.columns([1, 1], gap="large")
    with left:
        section_header("🚨 Alerts", "Operational flags for today.")
        render_alerts(alerts)
    with right:
        section_header("⚡ Recent Activity", "Latest events across all sessions.")
        render_activity_feed(activities)

    st.markdown("<hr style='border-color:rgba(255,255,255,0.06); margin:24px 0;'>", unsafe_allow_html=True)

    # Classes full width
    section_header(f"🏋️ Classes & Members — {selected_day}", "Occupancy and member breakdown per session.")
    classes_data = get_today_classes_with_members(conn, gym_id, selected_day)
    if not classes_data:
        st.info(f"No classes scheduled for {selected_day}.")
    else:
        cols = st.columns(2)
        for i, item in enumerate(classes_data):
            with cols[i % 2]:
                class_card(item)

# ─────────────────── TAB 2 — ANALYTICS ───────────────────────────────────────
with t2:
    section_header("Analytics", "Booking trends, source distribution, class popularity, and performance rates.")

    source_df    = get_source_split(conn, gym_id)
    by_day_df    = get_bookings_by_day(conn, gym_id)
    top_cls_df   = get_top_classes(conn, gym_id)
    peak_time_df = get_peak_times(conn, gym_id)
    att_rate, ns_rate = get_rates(conn, gym_id)

    # Row 1: metrics
    m1, m2, m3 = st.columns(3)
    with m1: st.metric("Attendance Rate", f"{att_rate}%")
    with m2: st.metric("No-show Rate", f"{ns_rate}%")
    with m3: st.metric("Total Bookings", bookings_count)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # Row 2: donut + by-day bar
    c1, c2 = st.columns(2)
    with c1:
        if not source_df.empty:
            st.plotly_chart(make_plotly_donut(source_df, "source", "c", "Bookings by Source"),
                            use_container_width=True)
        else:
            st.info("No source data.")
    with c2:
        st.plotly_chart(make_plotly_bar(by_day_df, "day", "bookings", "Bookings by Day", BLUE),
                        use_container_width=True)

    # Row 3: top classes + peak times
    c3, c4 = st.columns(2)
    with c3:
        if not top_cls_df.empty:
            st.plotly_chart(make_plotly_bar(top_cls_df, "class_name", "c", "Top Classes", PINK),
                            use_container_width=True)
        else:
            st.info("No class data.")
    with c4:
        if not peak_time_df.empty:
            st.plotly_chart(make_plotly_bar(peak_time_df, "time", "c", "Peak Times", PURPLE),
                            use_container_width=True)
        else:
            st.info("No peak-time data.")

# ─────────────────── TAB 3 — BOOKINGS ────────────────────────────────────────
with t3:
    section_header("Active Bookings", "Manage check-in, no-show, and cancellations.")

    bookings_df = get_active_bookings(conn, gym_id, source_filter, class_filter, coach_filter)

    sc1, sc2, sc3 = st.columns([2, 1, 1])
    with sc1:
        search_code = st.text_input("🔍 Search by member code", "")
    with sc2:
        st.download_button("⬇️ Export CSV", data=to_csv_bytes(bookings_df if not bookings_df.empty else pd.DataFrame()),
                           file_name=f"bookings_{selected_day}.csv", mime="text/csv", use_container_width=True)
    with sc3:
        st.download_button("📄 Daily Report", data=pdf_like_text_report(selected_day, summary_vals, activities),
                           file_name=f"report_{selected_day}.txt", mime="text/plain", use_container_width=True)

    if search_code.strip() and not bookings_df.empty:
        bookings_df = bookings_df[bookings_df["member_code"].astype(str).str.contains(search_code.strip(), case=False, na=False)]

    if bookings_df.empty:
        st.info("No active bookings match the current filters.")
    else:
        for _, row in bookings_df.iterrows():
            booking_card(conn, gym_id, row)

    st.markdown("---")
    section_header("Member Profile Lookup")
    member_lookup = st.text_input("Enter member code", key="profile_lookup")
    if member_lookup.strip():
        p = get_member_profile(conn, gym_id, member_lookup.strip())
        if not p:
            st.warning("Member not found.")
        else:
            pm1, pm2, pm3, pm4 = st.columns(4)
            with pm1: st.metric("Name",     p["member"]["full_name"] or "—")
            with pm2: st.metric("Phone",    p["member"]["phone"] or "—")
            with pm3: st.metric("Status",   p["member"]["status"] or "—")
            with pm4: st.metric("No-shows", p["no_show_count"])
            if p["bookings"]:
                st.markdown("#### Booking History")
                st.dataframe(pd.DataFrame(p["bookings"]), use_container_width=True, hide_index=True)
            if p["attendance"]:
                st.markdown("#### Attendance History")
                st.dataframe(pd.DataFrame(p["attendance"]), use_container_width=True, hide_index=True)

# ─────────────────── TAB 4 — ATTENDANCE ──────────────────────────────────────
with t4:
    section_header("Attendance", f"Attendance records for {selected_day}.")
    att_df = get_attendance(conn, gym_id, selected_day)
    st.download_button("⬇️ Export CSV", data=to_csv_bytes(att_df if not att_df.empty else pd.DataFrame()),
                       file_name=f"attendance_{selected_day}.csv", mime="text/csv")
    if att_df.empty:
        st.info("No attendance records for this day.")
    else:
        st.dataframe(att_df, use_container_width=True, hide_index=True)

# ─────────────────── TAB 5 — WAITLIST ────────────────────────────────────────
with t5:
    section_header("Waitlist", "Members awaiting available spots.")
    wl_df = get_waitlist(conn, gym_id)
    st.download_button("⬇️ Export CSV", data=to_csv_bytes(wl_df if not wl_df.empty else pd.DataFrame()),
                       file_name="waitlist.csv", mime="text/csv")
    if wl_df.empty:
        st.info("Waitlist is empty.")
    else:
        st.dataframe(wl_df, use_container_width=True, hide_index=True)

# ─────────────────── TAB 6 — ADMIN REQUESTS ──────────────────────────────────
with t6:
    section_header("Admin Requests", "Requests from Telegram and WhatsApp with workflow management.")
    req_df = get_admin_contact_requests(conn, gym_id, status_filter)
    st.download_button("⬇️ Export CSV", data=to_csv_bytes(req_df if not req_df.empty else pd.DataFrame()),
                       file_name="admin_requests.csv", mime="text/csv")
    if req_df.empty:
        st.info("No admin requests match the current filter.")
    else:
        for _, row in req_df.iterrows():
            admin_request_card(conn, row)

conn.close()
