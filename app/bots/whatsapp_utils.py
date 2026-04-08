import os
import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")


def send_whatsapp_text(to_number: str, text: str) -> None:
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text},
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print("SEND STATUS:", response.status_code)
    print("SEND RESPONSE:", response.text)