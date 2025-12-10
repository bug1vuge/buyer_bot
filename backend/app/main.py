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
from .tinkoff_client import create_tinkoff_payment, check_order, generate_webhook_token

# DATABASE
DATABASE_URL = settings.DATABASE_URL
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

# FASTAPI
app = FastAPI(title="Payment backend")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# ==========================
# PRODUCT API
# ==========================
class CreateProductIn(BaseModel):
    title: str
    base_price: int
    percent: int

class CreateProductOut(BaseModel):
    product_id: int

@app.post("/api/products/create", response_model=CreateProductOut)
def create_product(payload: CreateProductIn):
    session = SessionLocal()
    try:
        product = Product(
            title=payload.title,
            base_price_cents=payload.base_price*100,
            agent_percent=payload.percent
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        return CreateProductOut(product_id=product.id)
    finally:
        session.close()

# ==========================
# CREATE ORDER + INIT PAYMENT
# ==========================
@app.post("/api/orders/create", response_model=CreateOrderOut)
def api_create_order(payload: CreateOrderIn):
    session = SessionLocal()
    try:
        product = session.query(Product).filter(Product.id == payload.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        seq = session.query(Order).filter(
            Order.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        ).count() + 1
        order_id_str = f"{today_str}_{seq:03d}"

        quantity = getattr(payload, "quantity", 1)
        base_amount = product.base_price_cents * quantity
        agent_fee = int(base_amount * product.agent_percent / 100)
        total_cents = base_amount + agent_fee

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

        # Tinkoff Init
        tinkoff_resp = create_tinkoff_payment(
            amount_cents=order.total_amount_cents,
            order_id=order.order_id_str,
            email=order.customer_email,
            phone=order.customer_phone
        )

        order.yookassa_payment_id = str(tinkoff_resp['payment_id'])
        order.status = "pending"
        session.commit()

        return CreateOrderOut(order_id=order.order_id_str, confirmation_url=tinkoff_resp['payment_url'])
    finally:
        session.close()

# ==========================
# PAYMENT PAGE
# ==========================
@app.get("/pay/{product_id}", response_class=HTMLResponse)
def pay_page(request: Request, product_id: int):
    session = SessionLocal()
    product = session.query(Product).filter(Product.id == product_id).first()
    session.close()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return templates.TemplateResponse(
        "payment.html",
        {"request": request, "product": product, "BASE_URL": settings.BASE_URL, "DADATA_API_KEY": settings.DADATA_API_KEY},
    )

# ==========================
# TINKOFF WEBHOOK
# ==========================
@app.post("/api/tinkoff/webhook")
async def tinkoff_webhook(request: Request):
    payload = await request.json()
    received_token = payload.get("Token")
    calc_token = generate_webhook_token(payload)
    if calc_token != received_token:
        return JSONResponse({"ok": False, "detail": "Invalid token"}, status_code=400)

    session = SessionLocal()
    try:
        payment_id = payload.get("PaymentId")
        order_id = payload.get("OrderId")
        status = payload.get("Status")
        order = None

        if payment_id:
            order = session.query(Order).filter(Order.yookassa_payment_id == str(payment_id)).first()
        if not order and order_id:
            order = session.query(Order).filter(Order.order_id_str == str(order_id)).first()
        if not order:
            return JSONResponse({"ok": False, "detail": "Order not found"}, status_code=404)

        s = (status or "").lower()
        if s in ("confirmed", "completed", "authorized", "success"):
            order.status = "paid"
            order.paid_at = datetime.utcnow()
        elif s in ("reversed", "refunded", "failed", "declined", "rejected", "canceled", "cancelled"):
            order.status = "cancelled"

        session.commit()
        return {"ok": True}
    finally:
        session.close()

# ==========================
# RUN
# ==========================
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
