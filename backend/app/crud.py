# app/crud.py

from datetime import datetime, date
from sqlalchemy.exc import IntegrityError
from .models import Order, Product
from .tinkoff_client import create_tinkoff_payment
from .config import settings


def _generate_order_id(session):
    today = date.today().strftime("%Y%m%d")
    count = session.query(Order).filter(
        Order.created_at >= datetime.combine(date.today(), datetime.min.time())
    ).count()
    seq = count + 1
    return f"{today}_{seq:03d}"


def create_order_and_payment(session, payload):
    """
    Создаёт заказ в БД + инициализирует оплату в Tinkoff Acquiring.
    Возвращает: (order_id_str, payment_url)
    """

    # -- 1. Ищем продукт --
    product = session.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise ValueError("Product not found")

    # -- 2. Генерируем order_id --
    order_id_str = _generate_order_id(session)

    # -- 3. Рассчитываем стоимость --
    quantity = payload.quantity
    base_amount_cents = product.base_price_cents * quantity
    agent_fee_cents = int(base_amount_cents * product.agent_percent / 100)
    total_amount_cents = base_amount_cents + agent_fee_cents

    # -- 4. Создаём заказ локально --
    order = Order(
        order_id_str=order_id_str,
        product_id=product.id,
        quantity=quantity,
        total_amount_cents=total_amount_cents,
        agent_fee_cents=agent_fee_cents,
        customer_fullname=payload.fullname,
        customer_phone=payload.phone,
        customer_email=payload.email,
        customer_city=payload.city,
        customer_address=payload.address,
        comment=payload.comment,
        status="created",
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    # -- 5. Запрос в Tinkoff Init --
    try:
        payment = create_tinkoff_payment(
            amount_cents=total_amount_cents,
            order_id=order.order_id_str,
            email=order.customer_email or "",
            phone=order.customer_phone or "",
        )
    except Exception as e:
        order.status = "error"
        session.commit()
        raise

    payment_url = payment["payment_url"]
    payment_id = payment["payment_id"]

    # сохраняем Tinkoff PaymentId в колонку yookassa_payment_id (переиспользуем)
    order.yookassa_payment_id = str(payment_id)
    order.status = "pending"
    session.commit()

    return order.order_id_str, payment_url


def get_order_by_payment_id(session, payment_id):
    """Ищет заказ по Tinkoff PaymentId."""
    return (
        session.query(Order)
        .filter(Order.yookassa_payment_id == str(payment_id))
        .first()
    )
