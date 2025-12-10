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
            result.extend(_flatten_for_signature(item))
        return result

    return [str(obj)]


# ---------------------------
# Token generation
# ---------------------------
def generate_init_token(payload: Dict[str, Any]) -> str:
    """Токен для Init карт: SHA256(sorted(values) + Password)"""
    items = sorted((k, v) for k, v in payload.items() if k != "Token")
    pieces: List[str] = []

    for _, v in items:
        pieces.extend(_flatten_for_signature(v))

    concat = "".join("" if p is None else p for p in pieces) + settings.TINKOFF_PASSWORD
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_check_order_token(order_id: str) -> str:
    """Токен для CheckOrder: SHA256(OrderId + Password + TerminalKey)"""
    concat = f"{order_id}{settings.TINKOFF_PASSWORD}{settings.TINKOFF_TERMINAL_KEY}"
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_webhook_token(payload: Dict[str, Any]) -> str:
    flat = {k: v for k, v in payload.items() if k != "Token"}

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
TINKOFF_CHECK_URL = f"{settings.TINKOFF_API_URL.rstrip('/')}/CheckOrder"


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
# Check order
# ---------------------------
def check_order(order_id: str) -> Dict[str, Any]:
    """Проверка платежа через CheckOrder"""
    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "OrderId": order_id,
        "Token": generate_check_order_token(order_id),
    }
    r = requests.post(TINKOFF_CHECK_URL, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()
