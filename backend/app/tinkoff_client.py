# app/tinkoff_client.py
import requests
import hashlib
from .config import settings

TINKOFF_INIT_URL = f"{settings.TINKOFF_API_URL}/Init"
TINKOFF_STATE_URL = f"{settings.TINKOFF_API_URL}/GetState"


def generate_token(params: dict) -> str:
    password = settings.TINKOFF_PASSWORD

    flat = {}
    for k, v in params.items():
        if k in ("Token", "Receipt"):
            continue
        if isinstance(v, dict):
            continue
        flat[k] = v

    sorted_items = sorted(flat.items(), key=lambda x: x[0])

    concat = "".join(str(v) for _, v in sorted_items) + password

    return hashlib.sha256(concat.encode()).hexdigest()


def create_tinkoff_payment(amount_cents: int, order_id: str, email: str = "", phone: str = "") -> dict:

    # Создаем payload (полный)
    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "OrderId": order_id,
        "Amount": amount_cents,
        "Description": f"Оплата заказа №{order_id}",
        "SuccessURL": settings.FRONTEND_RETURN_URL,
        "FailURL": settings.FRONTEND_RETURN_URL,
        "CustomerEmail": email,
        "CustomerPhone": phone,
        "Receipt": {
            "Email": email,
            "Phone": phone,
            "Taxation": "usn_income",
            "Items": [{
                "Name": f"Товар {order_id}",
                "Price": amount_cents,
                "Quantity": 1,
                "Amount": amount_cents,
                "PaymentMethod": "full_payment",
                "PaymentObject": "service",
                "Tax": "none"
            }]
        }
    }
    
    # --- Token НЕ должен учитывать Receipt ---
    token_payload = {k: v for k, v in payload.items() if k != "Receipt"}
    payload["Token"] = generate_token(token_payload)


    r = requests.post(TINKOFF_INIT_URL, json=payload, timeout=10)
    r.raise_for_status()

    data = r.json()

    # if not data.get("Success"):
    #     raise Exception(data.get("Message") or data)
    if not data.get("Success"):
        print("\n🔥 RAW TINKOFF ERROR:")
        print(data)
        print("🔥 END RAW TINKOFF ERROR\n")
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
