# app/tinkoff_client.py
import requests
import hashlib
from .config import settings

TINKOFF_INIT_URL = "https://securepay.tinkoff.ru/v2/Init"
TINKOFF_STATE_URL = "https://securepay.tinkoff.ru/v2/GetState"


# ============================================
# TOKEN — строго по правилам Тинькофф эквайринга
# ============================================
def generate_token(params: dict) -> str:
    """
    Token = SHA256(sorted_values + Password)
    НЕЛЬЗЯ включать:
    - Token
    - Receipt
    - вложенные объекты
    """
    password = settings.TINKOFF_PASSWORD

    flat_params = {}

    # ТОЛЬКО плоские поля → вложенные игнорируем
    for k, v in params.items():
        if k in ("Token", "Receipt"):
            continue
        if isinstance(v, dict):
            continue
        flat_params[k] = v

    # сортируем
    #sorted_items = sorted(flat_params.items(), key=lambda x: x[0].lower())
    sorted_items = sorted(flat_params.items(), key=lambda x: x[0])

    concat = "".join(str(v) for _, v in sorted_items) + password

    return hashlib.sha256(concat.encode()).hexdigest()


# ============================================
# Создание платежа Init
# ============================================
def create_tinkoff_payment(amount_cents: int, order_id: str, email: str = "", phone: str = "") -> dict:

    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "OrderId": order_id,
        "Amount": amount_cents,
        "Description": f"Оплата заказа №{order_id}",

        "SuccessURL": settings.FRONTEND_RETURN_URL,
        "FailURL": settings.FRONTEND_RETURN_URL,

        # Только плоские поля!!!
        "CustomerEmail": email,
        "CustomerPhone": phone
    }

    # Token генерируется строго по плоскому объекту
    payload["Token"] = generate_token(payload)

    r = requests.post(TINKOFF_INIT_URL, json=payload, timeout=10)
    r.raise_for_status()

    data = r.json()

    if not data.get("Success"):
        raise Exception(data.get("Message") or data)

    return {
        "payment_url": data["PaymentURL"],
        "payment_id": data["PaymentId"]
    }


def get_tinkoff_payment_state(payment_id: str):
    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "PaymentId": payment_id
    }
    payload["Token"] = generate_token(payload)

    r = requests.post(TINKOFF_STATE_URL, json=payload, timeout=10)
    r.raise_for_status()

    return r.json()
