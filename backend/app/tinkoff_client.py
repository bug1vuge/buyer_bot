import requests
import hashlib
from .config import settings
import logging
import json

logger = logging.getLogger(__name__)

def generate_token(payload: dict, secret_key: str) -> str:
    """
    Генерация токена строго по документации Tinkoff MAPI
    """

    token_data = {}

    for k, v in payload.items():
        # Исключаем Token и вложенные объекты
        if k == "Token":
            continue
        if isinstance(v, (dict, list)):
            continue
        token_data[k] = str(v)

    # Добавляем Password как ОБЫЧНОЕ поле
    token_data["Password"] = secret_key

    # Сортировка по ключу
    sorted_items = sorted(token_data.items(), key=lambda x: x[0])

    # Конкатенация значений
    concat = "".join(value for _, value in sorted_items)

    return hashlib.sha256(concat.encode("utf-8")).hexdigest()




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



# ==============================
# Проверка статуса платежа CheckOrder
# ==============================
def check_order(order_id: str):
    """
    Проверка статуса платежа (CheckOrder/GetState).
    Подпись: OrderId + Password + TerminalKey (в этом порядке).
    """
    terminal_key = settings.TINKOFF_TERMINAL_KEY
    secret_key = settings.TINKOFF_PASSWORD

    concat = str(order_id) + secret_key + terminal_key
    token = _sha256_hex(concat)

    payload = {"TerminalKey": terminal_key, "OrderId": str(order_id), "Token": token}
    url = "https://securepay.tinkoff.ru/v2/CheckOrder"
    resp = requests.post(url, json=payload, timeout=10)
    logger.debug("Tinkoff CheckOrder response: %s", resp.text)

    data = resp.json()
    if not data.get("Success"):
        return {"status": False, "message": f"{data.get('Message')} {data.get('Details')}"}
    payments = data.get("Payments", [])
    if not payments:
        return {"status": False, "message": "Нет платежей в заказе"}
    payment = payments[0]
    return {"status": payment.get("Success"), "message": payment.get("Message"), "status_payment": payment.get("Status")}


def build_paid_message(order, product) -> str:
    return (
        "✅ Заказ оплачен!\n\n"
        f"ID: {order.order_id_str}\n"
        f"Товар: {product.title}\n"
        f"Количество: {order.quantity} шт\n"
        f"Сумма: {order.total_amount_cents // 100} ₽\n"
        f"Дата: {order.paid_at.strftime('%d.%m.%Y')}\n\n"
        "👤 Клиент:\n"
        f"ФИО: {order.customer_fullname}\n"
        f"Телефон: {order.customer_phone}\n"
        f"Город: {order.customer_city}\n"
        f"Адрес: {order.customer_address}"
    )

def send_admin_notification(text: str):
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.ADMIN_CHAT_ID,
        "text": text
    }

    resp = requests.post(url, json=payload, timeout=10)
    if not resp.ok:
        logger.error("Telegram send error: %s", resp.text)



