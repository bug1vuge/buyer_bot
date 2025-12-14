import requests
import hashlib
from .config import settings
import logging
import json

logger = logging.getLogger(__name__)

def generate_webhook_token(payload: dict, secret_key: str = None) -> str:
    """
    Генерация токена для проверки webhook от Tinkoff.
    payload: dict - пришедший JSON от Tinkoff
    secret_key: str - ваш секретный ключ терминала (если не передан, берется из settings)
    """
    from .config import settings
    if not secret_key:
        secret_key = settings.TINKOFF_PASSWORD

    # Ключи в payload сортируются по алфавиту
    keys = sorted([k for k in payload.keys() if k.lower() != 'token'])
    concat_values = ''.join([str(payload[k]) for k in keys])
    concat_values += secret_key
    token = hashlib.sha256(concat_values.encode('utf-8')).hexdigest()
    return token

def create_tinkoff_payment(amount_cents: int, order_id: str, email: str, phone: str):
    terminal_key = settings.TINKOFF_TERMINAL_KEY
    secret_key = settings.TINKOFF_PASSWORD

    payload = {
        "TerminalKey": terminal_key,
        "Amount": int(amount_cents),
        "OrderId": str(order_id),
        "Description": f"Оплата заказа {order_id}",
        "PayType": "O",
        "Recurrent": "N",
        "DATA": {
            "Email": email,
            "Phone": phone
        }
    }

    # ГЕНЕРАЦИЯ ТОКЕНА СТРОГО ПО ДОКУМЕНТАЦИИ
    token = generate_webhook_token(payload, secret_key)
    payload["Token"] = token

    url = "https://securepay.tinkoff.ru/v2/Init"
    resp = requests.post(url, json=payload, timeout=15)

    data = resp.json()
    if not data.get("Success"):
        raise Exception(f"Tinkoff Init error: {data.get('Message')} {data.get('Details')}")

    return {
        "payment_url": data.get("PaymentURL"),
        "payment_id": data.get("PaymentId")
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
