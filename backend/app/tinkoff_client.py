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

def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()
# ==============================
# Инициализация платежа Init
# ==============================
def create_tinkoff_payment(amount_cents: int, order_id: str, email: str, phone: str):
    """
    amount_cents: сумма в копейках (int, например 1000 => 10.00 руб)
    order_id: ваш OrderId (строка)
    email, phone: данные покупателя
    """
    terminal_key = settings.TINKOFF_TERMINAL_KEY
    secret_key = settings.TINKOFF_PASSWORD  # SecretKey / Password в терминах Tinkoff

    # ВАЖНО: строковый вид полей должен соответствовать документации (Amount — число в копейках без .00)
    # Точный порядок для Init (по документации/практике): Amount + Description + OrderId + Password + TerminalKey
    description = f"Оплата заказа {order_id}"
    amount_str = str(int(amount_cents))  # убедиться, что целое число

    concat = amount_str + description + str(order_id) + secret_key + terminal_key
    token = _sha256_hex(concat)

    payload = {
        "TerminalKey": terminal_key,
        "Amount": int(amount_cents),
        "OrderId": str(order_id),
        "Description": description,
        "Token": token,
        "DATA": {"Email": email, "Phone": phone},
        "PayType": "O",
        "Recurrent": "N",
    }

    logger.error(payload)

    logger.error("TK=%s SK=%s", terminal_key, secret_key)

    logger.error("Concat for token: %s", concat)
    logger.error("Token: %s", token)
    logger.error("Payload: %s", payload)


    url = "https://securepay.tinkoff.ru/v2/Init"
    resp = requests.post(url, json=payload, timeout=15)
    logger.debug("Tinkoff Init request payload (no secret): %s", {k: v for k,v in payload.items() if k != 'Token'})
    logger.debug("Tinkoff Init response: %s", resp.text)

    data = resp.json()
    if not data.get("Success"):
        raise Exception(f"Tinkoff Init error: {data.get('Message')} {data.get('Details')}")
    return {"payment_url": data.get("PaymentURL"), "payment_id": data.get("PaymentId")}

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
