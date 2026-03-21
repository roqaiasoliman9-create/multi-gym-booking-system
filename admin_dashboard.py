import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

DB_PATH = "gym.sqlite3"
TZ = "Africa/Cairo"



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
                COALESCE(m.full_name, 'بدون اسم') AS full_name
            FROM bookings b
            JOIN members m ON m.id = b.member_id
            WHERE b.gym_id=? AND b.session_id=? AND b.status='booked'
            ORDER BY m.full_name, m.member_code
        """, (gym_id, session["id"])).fetchall()

        member_names = [
            m["full_name"] if m["full_name"] != "بدون اسم" else m["member_code"]
            for m in members
        ]

        booked_count = len(member_names)
        remaining = int(session["capacity"]) - booked_count

        result.append({
            "session_id": session["id"],
            "class_name": session["class_name"],
            "time": session["time"],
            "coach": session["coach"],
            "capacity": int(session["capacity"]),
            "booked_count": booked_count,
            "remaining": remaining,
            "members": member_names,
        })

    return result


def now_cairo() -> str:
    return datetime.now(ZoneInfo(TZ)).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def today_english_day() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%A")


def get_gym_id(conn):
    row = conn.execute("SELECT id FROM gyms ORDER BY id LIMIT 1").fetchone()
    return int(row["id"]) if row else None


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

    return int(sessions_count), int(bookings_count), int(waitlist_count)


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
            "Session ID": r["id"],
            "Time": r["time"],
            "Class": r["class_name"],
            "Coach": r["coach"],
            "Booked": int(booked),
            "Capacity": int(r["capacity"]),
            "Remaining": int(r["capacity"]) - int(booked),
        })

    return pd.DataFrame(data)


def get_active_bookings(conn, gym_id: int):
    rows = conn.execute("""
        SELECT
            b.id AS booking_id,
            b.session_id,
            m.id AS member_id,
            m.member_code,
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
        ORDER BY s.day, s.time, b.created_at DESC
    """, (gym_id,)).fetchall()

    return pd.DataFrame([dict(r) for r in rows])


def get_waitlist(conn, gym_id: int):
    rows = conn.execute("""
        SELECT
            w.id AS waitlist_id,
            m.member_code,
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


st.set_page_config(page_title="Gym Admin Dashboard", layout="wide")
st.title("Gym Admin Dashboard")

conn = connect()
gym_id = get_gym_id(conn)

if not gym_id:
    st.error("No gym found in database.")
    st.stop()

days = ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
selected_day = st.selectbox(
    "Select day",
    days,
    index=days.index(today_english_day()) if today_english_day() in days else 0
)

sessions_count, bookings_count, waitlist_count = get_summary(conn, gym_id, selected_day)

col1, col2, col3 = st.columns(3)
col1.metric("Classes Today", sessions_count)
col2.metric("Active Bookings", bookings_count)
col3.metric("Waitlist", waitlist_count)

st.subheader(f"Schedule - {selected_day}")
schedule_df = get_day_schedule(conn, gym_id, selected_day)
if schedule_df.empty:
    st.info("No classes for this day.")
else:
    st.dataframe(schedule_df, use_container_width=True)

st.subheader(f"Today Bookings by Class - {selected_day}")

classes_data = get_today_classes_with_members(conn, gym_id, selected_day)

if not classes_data:
    st.info("No classes for this day.")
else:
    for item in classes_data:
        with st.container(border=True):
            st.markdown(
                f"""
                **Class:** {item['class_name']}  
                **Time:** {item['time']}  
                **Coach:** {item['coach']}  
                **Booked:** {item['booked_count']} / {item['capacity']}  
                **Remaining:** {item['remaining']}
                """
            )

            if item["members"]:
                st.markdown("**Booked Members:**")
                for member in item["members"]:
                    st.write(f"- {member}")
            else:
                st.write("No bookings yet.")


st.subheader("Active Bookings")
bookings_df = get_active_bookings(conn, gym_id)

if bookings_df.empty:
    st.info("No active bookings.")
else:
    for _, row in bookings_df.iterrows():
        with st.container(border=True):
            st.markdown(
                f"""
                **Booking #{row['booking_id']}**  
                **Member Code:** {row['member_code']}  
                **Class:** {row['class_name']}  
                **Day:** {row['day']}  
                **Time:** {row['time']}  
                **Coach:** {row['coach']}  
                **Source:** {row['source']}  
                """,
            )

            c1, c2, c3 = st.columns(3)

            with c1:
                if st.button("Check-in", key=f"checkin_{row['booking_id']}"):
                    ok = checkin_booking_by_id(conn, gym_id, int(row["booking_id"]))
                    if ok:
                        st.success(f"Booking {row['booking_id']} marked as attended.")
                    else:
                        st.error("Booking not found or already processed.")
                    st.rerun()

            with c2:
                if st.button("No-show", key=f"noshow_{row['booking_id']}"):
                    ok = no_show_booking_by_id(conn, gym_id, int(row["booking_id"]))
                    if ok:
                        st.success(f"Booking {row['booking_id']} marked as no_show.")
                    else:
                        st.error("Booking not found or already processed.")
                    st.rerun()

            with c3:
                if st.button("Cancel Booking", key=f"cancel_{row['booking_id']}"):
                    cancel_booking_by_id(conn, int(row["booking_id"]))
                    st.success(f"Booking {row['booking_id']} cancelled.")
                    st.rerun()

st.subheader("Attendance")
attendance_df = get_attendance(conn, gym_id, selected_day)
if attendance_df.empty:
    st.info("No attendance records for this day.")
else:
    st.dataframe(attendance_df, use_container_width=True)

st.subheader("Waitlist")
waitlist_df = get_waitlist(conn, gym_id)
if waitlist_df.empty:
    st.info("Waitlist is empty.")
else:
    st.dataframe(waitlist_df, use_container_width=True)

conn.close()