# app/tinkoff_client.py
import hashlib
import requests
from .config import settings

TINKOFF_INIT_URL = f"{settings.TINKOFF_API_URL}/Init"
TINKOFF_STATE_URL = f"{settings.TINKOFF_API_URL}/GetState"


# ==========================
#   TOKEN GENERATION
# ==========================
def generate_init_token(amount: int, order_id: str) -> str:
    """
    Token = SHA256(Amount + OrderId + TerminalKey + Password)
    """
    concat = f"{amount}{order_id}{settings.TINKOFF_TERMINAL_KEY}{settings.TINKOFF_PASSWORD}"
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_state_token(payment_id: str) -> str:
    """
    Token = SHA256(PaymentId + TerminalKey + Password)
    """
    concat = f"{payment_id}{settings.TINKOFF_TERMINAL_KEY}{settings.TINKOFF_PASSWORD}"
    return hashlib.sha256(concat.encode()).hexdigest()


# ==========================
#   CREATE PAYMENT (SBP)
# ==========================
def create_tinkoff_payment(amount_cents: int, order_id: str) -> dict:
    """
    Создание платежа по API Tinkoff для СБП.
    Работает в DEMO и PROD.
    """

    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "OrderId": order_id,
        "Amount": amount_cents,
        "PayType": "SBP",   # обязательно для СБП
    }

    # Корректный токен
    payload["Token"] = generate_init_token(amount_cents, order_id)

    r = requests.post(TINKOFF_INIT_URL, json=payload, timeout=10)
    r.raise_for_status()

    data = r.json()

    if not data.get("Success"):
        print("\n🔥 RAW TINKOFF ERROR:")
        print(data)
        print("🔥 END RAW TINKOFF ERROR\n")
        raise Exception(data.get("Message") or "Ошибка Tinkoff Init")

    # В некоторых режимах возвращается PaymentURL, в SBP — ConfirmationURL
    payment_url = data.get("PaymentURL") or data.get("ConfirmationURL")

    return {
        "payment_url": payment_url,
        "payment_id": data["PaymentId"]
    }


# ==========================
#   CHECK PAYMENT STATE
# ==========================
def get_tinkoff_payment_state(payment_id: str) -> dict:

    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "PaymentId": payment_id,
        "Token": generate_state_token(payment_id)
    }

    r = requests.post(TINKOFF_STATE_URL, json=payload, timeout=10)
    r.raise_for_status()

    return r.json()
