import hashlib
import requests
from typing import Any, Dict, List
from .config import settings


# ---------------------------
# Helpers
# ---------------------------
def _flatten_for_signature(obj: Any) -> List[str]:
    """Рекурсивно сплющивает объект в список строк для токена."""
    result: List[str] = []

    if obj is None:
        return [""]

    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            val = obj[key]
            result.extend(_flatten_for_signature(val))
        return result

    if isinstance(obj, (list, tuple)):
        for item in obj:
            result.extend(_flatten_for_signature[item])
        return result

    return [str(obj)]


# ---------------------------
# Token generation
# ---------------------------
def generate_init_token(payload: Dict[str, Any]) -> str:
    """Правильный токен для Init карт: SHA256(sorted(values) + Password)."""
    items = sorted((k, v) for k, v in payload.items() if k != "Token")
    pieces: List[str] = []

    for _, v in items:
        pieces.extend(_flatten_for_signature(v))

    concat = "".join("" if p is None else p for p in pieces) + settings.TINKOFF_PASSWORD
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_state_token(payment_id: str) -> str:
    concat = f"{payment_id}{settings.TINKOFF_TERMINAL_KEY}{settings.TINKOFF_PASSWORD}"
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_webhook_token(payload: Dict[str, Any]) -> str:
    flat = {}
    for k, v in payload.items():
        if k == "Token":
            continue
        flat[k] = v

    items = sorted(flat.items(), key=lambda x: x[0])
    pieces = []
    for _, v in items:
        pieces.extend(_flatten_for_signature(v))

    concat = "".join("" if p is None else p for p in pieces) + settings.TINKOFF_PASSWORD
    return hashlib.sha256(concat.encode()).hexdigest()


# ---------------------------
# URLs
# ---------------------------
TINKOFF_INIT_URL = f"{settings.TINKOFF_API_URL.rstrip('/')}/Init"
TINKOFF_STATE_URL = f"{settings.TINKOFF_API_URL.rstrip('/')}/GetState"


# ---------------------------
# Create card payment
# ---------------------------
def create_tinkoff_payment(
    amount_cents: int,
    order_id: str,
    email: str = "",
    phone: str = "",
) -> Dict[str, Any]:
    """Создаёт платеж картой через Init + PaymentURL."""

    payload: Dict[str, Any] = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "OrderId": order_id,
        "Amount": amount_cents,
        "Description": f"Оплата заказа {order_id}",
        "SuccessURL": f"{settings.BASE_URL}/pay/success",
        "FailURL": f"{settings.BASE_URL}/pay/failed",
    }

    if email:
        payload["CustomerEmail"] = email
    if phone:
        payload["CustomerPhone"] = phone

    # Генерация токена
    payload["Token"] = generate_init_token(payload)

    r = requests.post(TINKOFF_INIT_URL, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data.get("Success"):
        raise Exception(f"Tinkoff Init returned error: {data}")

    return {
        "payment_url": data.get("PaymentURL") or data.get("ConfirmationURL"),
        "payment_id": data.get("PaymentId"),
    }


# ---------------------------
# Get state
# ---------------------------
def get_tinkoff_payment_state(payment_id: str) -> Dict[str, Any]:
    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "PaymentId": payment_id,
        "Token": generate_state_token(payment_id),
    }

    r = requests.post(TINKOFF_STATE_URL, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()
