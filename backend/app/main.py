# ---------------------------
# app/main.py
# ---------------------------
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from .config import settings
from .models import Base, Product, Order
from .schemas import CreateOrderIn, CreateOrderOut
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
from datetime import datetime, timezone

from .tinkoff_client import (
    create_tinkoff_payment,
    get_tinkoff_payment_state,
    generate_webhook_token,
)

# ==================================
# DATABASE
# ==================================
DATABASE_URL = settings.DATABASE_URL
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine)

Base.metadata.create_all(bind=engine)


# ==================================
# FASTAPI
# ==================================
app = FastAPI(title="Payment backend")

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)


# ==================================
# PRODUCT API
# ==================================
class CreateProductIn(BaseModel):
    title: str
    base_price: int         # рубли
    percent: int            # агентский %


class CreateProductOut(BaseModel):
    product_id: int


@app.post("/api/products/create", response_model=CreateProductOut)
def create_product(payload: CreateProductIn):
    session = SessionLocal()
    try:
        product = Product(
            title=payload.title,
            base_price_cents=payload.base_price * 100,
            agent_percent=payload.percent
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        return CreateProductOut(product_id=product.id)
    finally:
        session.close()


# ==================================
# ORDER + TINKOFF Init (Test SBP)
# ==================================
@app.post("/api/orders/create", response_model=CreateOrderOut)
def api_create_order(payload: CreateOrderIn):
    session = SessionLocal()
    try:
        # 1. Найти продукт
        product = session.query(Product).filter(Product.id == payload.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # 2. Сформировать уникальный order_id (UTC)
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        seq = session.query(Order).filter(
            Order.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        ).count() + 1
        order_id_str = f"{today_str}_{seq:03d}"

        # 3. Рассчитать сумму
        quantity = getattr(payload, "quantity", 1)
        base_amount = product.base_price_cents * quantity
        agent_fee = int(base_amount * product.agent_percent / 100)
        total_cents = base_amount + agent_fee

        # 4. Создать заказ локально
        order = Order(
            order_id_str=order_id_str,
            product_id=product.id,
            quantity=quantity,
            total_amount_cents=total_cents,
            agent_fee_cents=agent_fee,

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

        # 5. Создать тестовую SBP-сессию Тинькофф
        try:
            from .tinkoff_client import create_tinkoff_sbp_test_payment
            tinkoff_resp = create_tinkoff_sbp_test_payment(order_id=order.order_id_str)
        except Exception as e:
            order.status = "error"
            session.commit()
            raise HTTPException(status_code=502, detail=f"Tinkoff payment error: {e}")
        
        payment_url = tinkoff_resp.get("payment_url")
        payment_id = tinkoff_resp.get("payment_id")
        
        if not payment_url:
            order.status = "error"
            session.commit()
            raise HTTPException(status_code=502, detail="Tinkoff did not return payment_url")
        
        # 6. Сохраняем PaymentId и помечаем заказ как pending
        order.yookassa_payment_id = str(payment_id)
        order.status = "pending"
        session.commit()


        # 7. Вернуть клиенту ссылку для оплаты
        return CreateOrderOut(order_id=order.order_id_str, confirmation_url=payment_url)

    finally:
        session.close()



# ==================================
# PAYMENT HTML PAGE
# ==================================
@app.get("/pay/{product_id}", response_class=HTMLResponse)
def pay_page(request: Request, product_id: int):
    session = SessionLocal()
    product = session.query(Product).filter(Product.id == product_id).first()
    session.close()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return templates.TemplateResponse(
        "payment.html",
        {
            "request": request,
            "product": product,
            "BASE_URL": settings.BASE_URL,
            "DADATA_API_KEY": settings.DADATA_API_KEY,
        },
    )


# ==================================
# TINKOFF WEBHOOK (Notify)
# ==================================
@app.post("/api/tinkoff/webhook")
async def tinkoff_webhook(request: Request):
    payload = await request.json()

    # Логируем полностью для дебага — в продакшене лучше логировать в файл и без секретов
    print("\n🔥 Incoming Tinkoff Webhook:")
    print(payload)
    print("🔥 END\n")

    received_token = payload.get("Token")

    # Проверка подписи с помощью генератора, учитывающего вложенные структуры
    calc_token = generate_webhook_token(payload)
    if calc_token != received_token:
        # Логируем для отладки (не включай реальные секреты в лог)
        print("Invalid webhook token. calc:", calc_token, "recv:", received_token)
        return JSONResponse({"ok": False, "detail": "Invalid token"}, status_code=400)

    session = SessionLocal()
    try:
        payment_id = payload.get("PaymentId")
        order_id = payload.get("OrderId")
        status = payload.get("Status")

        order = None

        # Найти по payment_id (сохраняем в yookassa_payment_id)
        if payment_id:
            order = session.query(Order).filter(Order.yookassa_payment_id == str(payment_id)).first()

        # fallback: поиск по order_id
        if not order and order_id:
            order = session.query(Order).filter(Order.order_id_str == str(order_id)).first()

        if not order:
            print("Webhook: order not found for payment_id/order_id:", payment_id, order_id)
            return JSONResponse({"ok": False, "detail": "Order not found"}, status_code=404)

        # Normalize status
        s = (status or "").lower()

        if s in ("confirmed", "completed", "authorized", "success"):
            order.status = "paid"
        elif s in ("reversed", "refunded", "failed", "declined", "rejected", "canceled", "cancelled"):
            order.status = "cancelled"
        else:
            # Можно расширить маппинг статусов при необходимости
            order.status = order.status  # без изменений

        session.commit()

        return {"ok": True}

    finally:
        session.close()


# ==================================
# RUN
# ==================================
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
