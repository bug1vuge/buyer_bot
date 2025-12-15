import requests
import hashlib
from .config import settings
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==============================
# TOKEN
# ==============================
def generate_token(payload: dict, secret_key: str) -> str:
    """
    Генерация токена строго по документации Tinkoff MAPI
    """
    token_data = {}

    for k, v in payload.items():
        if k == "Token":
            continue
        if isinstance(v, (dict, list)):
            continue
        token_data[k] = str(v)

    token_data["Password"] = secret_key

    concat = "".join(
        value for _, value in sorted(token_data.items(), key=lambda x: x[0])
    )

    return hashlib.sha256(concat.encode("utf-8")).hexdigest()


# ==============================
# TELEGRAM
# ==============================
def send_admin_notification(text: str):
    """
    Отправка уведомления администратору в Telegram
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.ADMIN_CHAT_ID:
        logger.warning("Telegram settings not configured")
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error("Telegram send error: %s", e)


def build_paid_message(order, product) -> str:
    """
    Формирование текста уведомления об успешной оплате
    """
    return (
        "✅ <b>Заказ оплачен!</b>\n\n"
        f"<b>ID:</b> {order.order_id_str}\n"
        f"<b>Товар:</b> {product.title}\n"
        f"<b>Количество:</b> {order.quantity} шт\n"
        f"<b>Сумма:</b> {order.total_amount_cents // 100} ₽\n"
        f"<b>Дата:</b> {datetime.now().strftime('%d.%m.%y')}\n\n"
        "<b>Клиент:</b>\n"
        f"ФИО: {order.customer_fullname}\n"
        f"Телефон: {order.customer_phone}\n"
        f"Город: {order.customer_city}\n"
        f"Адрес: {order.customer_address}"
    )


# ==============================
# INIT PAYMENT
# ==============================
def create_tinkoff_payment(amount_cents: int, order_id: str, email: str, phone: str):
    terminal_key = settings.TINKOFF_TERMINAL_KEY
    secret_key = settings.TINKOFF_PASSWORD

    payload = {
        "TerminalKey": terminal_key,
        "Amount": amount_cents,
        "OrderId": str(order_id),
        "Description": f"Оплата заказа {order_id}",
        "PayType": "O",
        "Recurrent": "N",
        "DATA": {
            "Email": email,
            "Phone": phone
        }
    }

    payload["Token"] = generate_token(payload, secret_key)

    url = "https://securepay.tinkoff.ru/v2/Init"
    resp = requests.post(url, json=payload, timeout=15)

    data = resp.json()
    if not data.get("Success"):
        raise Exception(
            f"Tinkoff Init error: {data.get('Message')} {data.get('Details')}"
        )

    return {
        "payment_url": data.get("PaymentURL"),
        "payment_id": data.get("PaymentId"),
    }
