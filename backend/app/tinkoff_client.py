# ---------------------------
# app/tinkoff_client.py
# ---------------------------
import hashlib
import requests
from typing import Any, Dict, List, Tuple
from .config import settings

TINKOFF_INIT_URL = f"{settings.TINKOFF_API_URL.rstrip('/')}/Init"
TINKOFF_STATE_URL = f"{settings.TINKOFF_API_URL.rstrip('/')}/GetState"

# ---------------------------
# Helpers for flattening payloads deterministically
# ---------------------------
def _flatten_for_signature(obj: Any) -> List[str]:
    """
    Рекурсивно "сплющивает" объект в список строк-значений в детерминированном порядке.
    Правила:
    - Для dict: сортируем ключи по алфавиту, обходим в этом порядке; для каждого ключа
      рекурсивно сплющиваем значение и добавляем в результирующий список.
    - Для list/tuple: обходим элементы в порядке и рекурсивно сплющиваем.
    - Для None -> пустая строка.
    - Для примитивов -> str(value).
    Этот порядок гарантированно детерминирован и стабильный.
    """
    result: List[str] = []

    if obj is None:
        return [""]

    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            val = obj[key]
            # Если значение - dict/iterable — рекурсивно, иначе строчка
            result.extend(_flatten_for_signature(val))
        return result

    if isinstance(obj, (list, tuple)):
        for item in obj:
            result.extend(_flatten_for_signature(item))
        return result

    # Примитивный тип
    return [str(obj)]


# ---------------------------
# Token generation
# ---------------------------
def generate_init_token(amount: int, order_id: str) -> str:
    """
    Token для Init в режиме SBP (и обычно для простого SBP Init согласно документации demo/prod):
    SHA256(Amount + OrderId + TerminalKey + Password)
    """
    concat = f"{amount}{order_id}{settings.TINKOFF_TERMINAL_KEY}{settings.TINKOFF_PASSWORD}"
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_state_token(payment_id: str) -> str:
    """
    Token для GetState:
    SHA256(PaymentId + TerminalKey + Password)
    """
    concat = f"{payment_id}{settings.TINKOFF_TERMINAL_KEY}{settings.TINKOFF_PASSWORD}"
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_init_token_from_payload(payload: Dict[str, Any]) -> str:
    """
    Более общий вариант генерации Token для Init (если вы используете не-SBP Init
    и документация/банк ожидает токен, основанный на сортировке полей).
    Формула: concat(sorted_values) + Password -> SHA256
    Исключаем ключи Token и Receipt; вложенные структуры учитываются рекурсивно.
    """
    flat = {}
    for k, v in payload.items():
        if k in ("Token", "Receipt"):
            continue
        flat[k] = v

    # Сортировка по ключу
    items = sorted(flat.items(), key=lambda x: x[0])

    # Конкатенируем значения (рекурсивно обрабатываем вложенные структуры)
    pieces: List[str] = []
    for _, v in items:
        pieces.extend(_flatten_for_signature(v))

    concat = "".join("" if p is None else p for p in pieces) + settings.TINKOFF_PASSWORD
    return hashlib.sha256(concat.encode()).hexdigest()


def generate_webhook_token(payload: Dict[str, Any]) -> str:
    """
    Токен для валидации вебхука (Notify).
    - Удаляем Token и Receipt
    - Рекурсивно сплющиваем оставшиеся значения в детерминированном порядке
    - Конкатенируем и добавляем пароль в конец
    - SHA256
    Это покрывает случаи, когда Tinkoff может присылать Data: { ... } — оно будет включено в подпись.
    NOTE: если у тебя есть конкретный пример webhook, и подпись всё равно не совпадает —
    пришли пример (без секретов) и я подгоню функцию под формат банка.
    """
    flat = {}
    for k, v in payload.items():
        if k in ("Token", "Receipt"):
            continue
        flat[k] = v

    # Сортировка по ключу
    items = sorted(flat.items(), key=lambda x: x[0])

    pieces: List[str] = []
    for _, v in items:
        pieces.extend(_flatten_for_signature(v))

    concat = "".join("" if p is None else p for p in pieces) + settings.TINKOFF_PASSWORD
    return hashlib.sha256(concat.encode()).hexdigest()


# ---------------------------
# Create payment
# ---------------------------
def create_tinkoff_payment(
    amount_cents: int,
    order_id: str,
    email: str = "",
    phone: str = "",
    pay_type: str = "SBP",
    extra: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Создает платёж в Tinkoff.
    - Для SBP используем короткую формулу токена (amount+orderId+TerminalKey+Password)
    - Для других типов Init (если понадобится) можно использовать generate_init_token_from_payload
    Параметры:
      - amount_cents: сумма в копейках (int)
      - order_id: строковый идентификатор заказа (строго)
      - email, phone: опционально (будут отправлены в payload, но для demo-режима
        они могут вызывать ошибки — если используешь demo и видишь Wrong params, попробуй без них)
      - pay_type: "SBP" по умолчанию; можно передать "" / None для обычного Init
      - extra: словарь с доп. полями, которые нужно передать (не рекоммендовано в demo)
    Возвращает: {"payment_url": ..., "payment_id": ...}
    """
    # Собираем payload
    payload: Dict[str, Any] = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "OrderId": order_id,
        "Amount": amount_cents,
    }

    if pay_type:
        payload["PayType"] = pay_type

    # Добавляем опциональные поля, но будьте осторожны в demo-режиме (demo часто требует минимальный набор)
    if email:
        payload["CustomerEmail"] = email
    if phone:
        payload["CustomerPhone"] = phone

    if extra:
        payload.update(extra)

    # Генерация токена — для SBP используем строгое правило, кроме этого используем общий метод
    if str(payload.get("PayType", "")).upper() == "SBP":
        token = generate_init_token(amount_cents, order_id)
    else:
        token = generate_init_token_from_payload(payload)

    payload["Token"] = token

    try:
        r = requests.post(TINKOFF_INIT_URL, json=payload, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        # Более подробный контекст ошибки
        raise Exception(f"Tinkoff Init request failed: {e}") from e

    data = r.json()

    if not data.get("Success"):
        # логируем данные для дебага (в проде — не печатать секреты)
        raise Exception(f"Tinkoff Init returned error: {data}")

    # SBP может вернуть ConfirmationURL, обычный Init — PaymentURL
    payment_url = data.get("PaymentURL") or data.get("ConfirmationURL")
    return {"payment_url": payment_url, "payment_id": data.get("PaymentId")}


# ---------------------------
# Get state
# ---------------------------
def get_tinkoff_payment_state(payment_id: str) -> Dict[str, Any]:
    payload = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "PaymentId": payment_id,
        "Token": generate_state_token(payment_id),
    }

    try:
        r = requests.post(TINKOFF_STATE_URL, json=payload, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        raise Exception(f"Tinkoff GetState request failed: {e}") from e

    return r.json()
