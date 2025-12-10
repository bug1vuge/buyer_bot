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
        secret_key = settings.TERMINALPASSWORD

    # Ключи в payload сортируются по алфавиту
    keys = sorted([k for k in payload.keys() if k.lower() != 'token'])
    concat_values = ''.join([str(payload[k]) for k in keys])
    concat_values += secret_key
    token = hashlib.sha256(concat_values.encode('utf-8')).hexdigest()
    return token

# ==============================
# Инициализация платежа Init
# ==============================
def create_tinkoff_payment(amount_cents: int, order_id: str, email: str, phone: str):
    terminal_key = settings.TERMINALKEY
    secret_key = settings.TERMINALPASSWORD

    values = {
        'Amount': str(amount_cents),
        'OrderId': order_id,
        'TerminalKey': terminal_key,
        'Password': secret_key
    }

    concatenated_values = ''.join([values[key] for key in values.keys()])
    token = hashlib.sha256(concatenated_values.encode('utf-8')).hexdigest()

    payload = {
        'TerminalKey': terminal_key,
        'OrderId': order_id,
        'Amount': amount_cents,
        'Token': token,
        'Description': f"Оплата заказа {order_id}",
        'DATA': {
            'Email': email,
            'Phone': phone
        },
        'PayType': "O",      # одноразовый платеж
        'Recurrent': "N",    # не рекуррент
        # Можно добавить SuccessURL и FailURL если нужно
    }

    url = "https://securepay.tinkoff.ru/v2/Init"
    response = requests.post(url, json=payload)
    logger.debug("Tinkoff Init response: %s", response.text)

    data = response.json()
    if not data.get('Success'):
        raise Exception(f"Tinkoff Init error: {data.get('Message')} {data.get('Details')}")

    return {
        "payment_url": data['PaymentURL'],
        "payment_id": data['PaymentId']
    }

# ==============================
# Проверка статуса платежа CheckOrder
# ==============================
def check_order(order_id: str):
    terminal_key = settings.TERMINALKEY
    secret_key = settings.TERMINALPASSWORD

    values = {
        'OrderId': order_id,
        'TerminalKey': terminal_key,
        'Password': secret_key
    }

    concatenated_values = ''.join([values[key] for key in values.keys()])
    token = hashlib.sha256(concatenated_values.encode('utf-8')).hexdigest()

    payload = {
        'TerminalKey': terminal_key,
        'OrderId': order_id,
        'Token': token
    }

    url = "https://securepay.tinkoff.ru/v2/CheckOrder"
    response = requests.post(url, json=payload)
    logger.debug("Tinkoff CheckOrder response: %s", response.text)

    data = response.json()
    if not data.get('Success'):
        return {"status": False, "message": f"{data.get('Message')} {data.get('Details')}"}

    payments = data.get('Payments', [])
    if not payments:
        return {"status": False, "message": "Нет платежей в заказе"}

    payment = payments[0]
    return {"status": payment.get('Success'), "message": payment.get('Message'), "status_payment": payment.get('Status')}
