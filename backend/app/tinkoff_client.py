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
def generate_init_token(amount: int, order_id: str) -> str:
    """Токен для SBP / Init: SHA256(Amount + OrderId + TerminalKey + Password)"""
    concat = f"{amount}{order_id}{settings.TINKOFF_TERMINAL_KEY}{settings.TINKOFF_PASSWORD}"
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_state_token(payment_id: str) -> str:
    """Токен для GetState: SHA256(PaymentId + TerminalKey + Password)"""
    concat = f"{payment_id}{settings.TINKOFF_TERMINAL_KEY}{settings.TINKOFF_PASSWORD}"
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_webhook_token(payload: Dict[str, Any]) -> str:
    """Токен для проверки webhook"""
    flat = {}
    for k, v in payload.items():
        if k in ("Token", "Receipt"):
            continue
        flat[k] = v

    items = sorted(flat.items(), key=lambda x: x[0])
    pieces: List[str] = []
    for _, v in items:
        pieces.extend(_flatten_for_signature(v))

    concat = "".join("" if p is None else p for p in pieces) + settings.TINKOFF_PASSWORD
    return hashlib.sha256(concat.encode()).hexdigest()


# ---------------------------
# Create Tinkoff payment (prod / demo)
# ---------------------------
TINKOFF_INIT_URL = f"{settings.TINKOFF_API_URL.rstrip('/')}/Init"
TINKOFF_STATE_URL = f"{settings.TINKOFF_API_URL.rstrip('/')}/GetState"


def create_tinkoff_payment(
    amount_cents: int,
    order_id: str,
    email: str = "",
    phone: str = "",
    pay_type: str = "SBP",
    extra: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Создает обычный Init платеж"""
    payload: Dict[str, Any] = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "OrderId": order_id,
        "Amount": amount_cents,
    }

    if pay_type:
        payload["PayType"] = pay_type

    if email:
        payload["CustomerEmail"] = email
    if phone:
        payload["CustomerPhone"] = phone
    if extra:
        payload.update(extra)

    token = generate_init_token(amount_cents, order_id) if pay_type.upper() == "SBP" else generate_webhook_token(payload)
    payload["Token"] = token

    r = requests.post(TINKOFF_INIT_URL, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data.get("Success"):
        raise Exception(f"Tinkoff Init returned error: {data}")

    payment_url = data.get("PaymentURL") or data.get("ConfirmationURL")
    return {"payment_url": payment_url, "payment_id": data.get("PaymentId")}


# ---------------------------
# Create test SBP payment
# ---------------------------
def create_tinkoff_sbp_test_payment(order_id: str) -> Dict[str, str]:
    """
    Создает тестовую SBP-платежную сессию через SbpPayTest
    order_id <= 20 символов
    """
    payment_id = order_id[:20]
    token_str = f"{settings.TINKOFF_TERMINAL_KEY}{payment_id}{settings.TINKOFF_PASSWORD}"
    token = hashlib.sha256(token_str.encode()).hexdigest()

    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "PaymentId": payment_id,
        "Token": token,
        "IsDeadlineExpired": False,
        "IsRejected": False,
    }

    r = requests.post(settings.TINKOFF_API_URL, json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()

    if not data.get("Success"):
        raise Exception(f"Tinkoff SBP test Init error: {data}")

    payment_url = data.get("PaymentURL") or data.get("ConfirmationURL")
    return {"payment_url": payment_url, "payment_id": payment_id}


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
