from celery import Celery
import os
from .config import settings

cel = Celery("tasks", broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))

@cel.task
def send_admin_notification(chat_id, text, pdf_path=None):
    # простая задача: отправка через Telegram Bot API (можно использовать requests)
    import requests, os
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})
    if pdf_path:
        # отправляем документ
        url_send = f"https://api.telegram.org/bot{token}/sendDocument"
        with open(pdf_path, "rb") as f:
            requests.post(url_send, files={"document": f}, data={"chat_id": chat_id})
