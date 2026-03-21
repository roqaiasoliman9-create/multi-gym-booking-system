# Multi Gym Booking System

A scalable multi-tenant gym booking system built in Python with Telegram and WhatsApp integration, automated scheduling, reminders, and attendance tracking.

---

## Overview

This system is designed to manage gym operations across multiple branches or tenants.
Users can book sessions through messaging platforms while the system handles reminders, attendance, and scheduling automatically.

---

## Features

* Multi-gym (multi-tenant) architecture
* Booking and scheduling system
* Telegram bot integration
* WhatsApp webhook integration
* Automated reminder workers
* Attendance tracking system
* Admin dashboard

---

## Tech Stack

* Python
* SQLite (for local development)
* Telegram Bot API
* WhatsApp Cloud API (Webhook)
* Background workers (custom loops)

---

## Project Structure

```
.
├── app.py
├── telegram_bot.py
├── whatsapp_webhook.py
├── booking_logic.py
├── database.py
├── reminder_worker.py
├── worker_attendance.py
├── admin_dashboard.py
├── requirements.txt
├── .env.example
```

---

## Setup

1. Create virtual environment:

```
python -m venv .venv
```

2. Activate environment:

```
source .venv/bin/activate
```

3. Install dependencies:

```
pip install -r requirements.txt
```

4. Create `.env` file based on `.env.example`

5. Run the project:

```
python app.py
```

---

## Environment Variables

```
TELEGRAM_BOT_TOKEN=
WHATSAPP_VERIFY_TOKEN=
OPENAI_API_KEY=
DATABASE_URL=
```

---

## Notes

* `.env` file is not included for security reasons
* Database files are ignored
* The system is designed to be scalable and extendable

---

## Future Improvements

* Switch to PostgreSQL
* Add REST API (FastAPI)
* Add authentication system
* Deploy to cloud (AWS / Render / Railway)

---

## Author

Ruqaya Suleyman
