import uvicorn
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from .config import settings
from .models import Base, Product, Order
from .schemas import CreateOrderIn, CreateOrderOut, SalesReportIn, SalesReportItem, SalesReportOut
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from datetime import datetime, timezone, timedelta, date
from .tinkoff_client import create_tinkoff_payment, check_order, generate_token, build_paid_message, send_admin_notification
from pathlib import Path

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
# @app.post("/api/tinkoff/webhook")
# async def tinkoff_webhook(request: Request):
#     payload = await request.json()

#     received_token = payload.get("Token")
#     if not received_token:
#         return JSONResponse({"ok": False, "detail": "Token missing"}, status_code=400)

#     calc_token = generate_token(payload, settings.TINKOFF_PASSWORD)

#     if calc_token != received_token:
#         return JSONResponse(
#             {"ok": False, "detail": "Invalid token"},
#             status_code=400
#         )

@app.post("/api/tinkoff/webhook")
async def tinkoff_webhook(request: Request):
    payload = await request.json()

    print("=== TINKOFF WEBHOOK HIT ===")
    print(payload)

    # 1. Проверка токена
    received_token = payload.get("Token")
    if not received_token:
        return JSONResponse({"ok": False, "detail": "Token missing"}, status_code=400)

    calc_token = generate_token(payload, settings.TINKOFF_PASSWORD)
    if calc_token != received_token:
        return JSONResponse({"ok": False, "detail": "Invalid token"}, status_code=400)

    # 2. Получаем данные из webhook
    payment_id = payload.get("PaymentId")
    order_id = payload.get("OrderId")
    status = (payload.get("Status") or "").lower()
    
    session = SessionLocal()
    try:
        # 3. Ищем заказ
        order = None

        if payment_id:
            order = session.query(Order).filter(
                Order.yookassa_payment_id == str(payment_id)
            ).first()

        if not order and order_id:
            order = session.query(Order).filter(
                Order.order_id_str == str(order_id)
            ).first()

        if not order:
            return JSONResponse({"ok": False, "detail": "Order not found"}, status_code=404)

        # 4. Защита от повторных webhook
        if order.status == "paid":
            return {"ok": True}
        
        # 5. Успешная оплата
        if status in ("confirmed", "completed", "authorized", "success", "pending"):
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            session.commit()
        
            product = session.query(Product).filter(
                Product.id == order.product_id
            ).first()
        
            message = build_paid_message(order, product)
            send_admin_notification(message)


        # 6. Неуспешные статусы
        elif status in (
            "reversed", "refunded", "failed",
            "declined", "rejected", "canceled", "cancelled"
        ):
            order.status = "cancelled"
            session.commit()

        return {"ok": True}

    finally:
        session.close()



#генерация pdf
BASE_DIR = Path(__file__).resolve().parent
FONT_PATH = BASE_DIR / "static" / "fonts" / "Inter-Medium.ttf"

pdfmetrics.registerFont(
    TTFont("Inter-Medium", str(FONT_PATH))
)

def generate_sales_report_pdf(
    title: str,
    items: list[dict],
    total_sum: int,
    total_agent: int
) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50

    c.setFont("Inter-Medium", 14)
    c.drawString(40, y, title)
    y -= 40

    c.setFont("Inter-Medium", 10)
    c.drawString(40, y, "Товар")
    c.drawString(240, y, "Кол-во")
    c.drawString(310, y, "Сумма ₽")
    c.drawString(400, y, "Агент ₽")
    y -= 15

    c.setFont("Inter-Medium", 10)

    for item in items:
        if y < 80:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)

        c.drawString(40, y, item["product_title"])
        c.drawRightString(280, y, str(item["quantity"]))
        c.drawRightString(360, y, f"{item['total_amount']:,}".replace(",", " "))
        c.drawRightString(460, y, f"{item['agent_fee']:,}".replace(",", " "))
        y -= 15

    y -= 20
    c.setFont("Inter-Medium", 11)
    c.drawString(40, y, f"Итого сумма: {total_sum:,} ₽".replace(",", " "))
    y -= 15
    c.drawString(40, y, f"Итого агентская сумма: {total_agent:,} ₽".replace(",", " "))

    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer.read()

@app.post("/api/reports/sales")
def sales_report(payload: SalesReportIn):
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Определяем период
        if payload.period:
            if payload.period == "all":
                date_from = None
            else:
                date_from = now - timedelta(days=int(payload.period))
            date_to = now
        else:
            date_from = datetime.combine(payload.start_date, datetime.min.time(), tzinfo=timezone.utc)
            date_to = datetime.combine(payload.end_date, datetime.max.time(), tzinfo=timezone.utc)

        # Базовый запрос — ТОЛЬКО оплаченные
        query = (
            session.query(
                Product.title.label("product_title"),
                func.sum(Order.quantity).label("quantity"),
                func.sum(Order.total_amount_cents).label("total_amount"),
                func.sum(Order.agent_fee_cents).label("agent_fee"),
            )
            .join(Product, Product.id == Order.product_id)
            .filter(Order.status.in_(["paid", "pending"]))
        )

        if date_from:
            query = query.filter(Order.paid_at >= date_from)
        if date_to:
            query = query.filter(Order.paid_at <= date_to)

        query = query.group_by(Product.title)

        rows = query.all()

        items = []
        total_sum = 0
        total_agent = 0

        for r in rows:
            items.append({
                "product_title": r.product_title,
                "quantity": int(r.quantity),
                "total_amount": int(r.total_amount / 100),
                "agent_fee": int(r.agent_fee / 100),
            })
            total_sum += int(r.total_amount / 100)
            total_agent += int(r.agent_fee / 100)

        # Заголовок отчёта
        if payload.period == "all":
            title = "Отчёт за всё время"
        elif payload.period:
            title = f"Отчёт за последние {payload.period} дней"
        else:
            title = f"Отчёт за период: {payload.start_date} - {payload.end_date}"

        pdf_bytes = generate_sales_report_pdf(
            title=title,
            items=items,
            total_sum=total_sum,
            total_agent=total_agent
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=sales_report.pdf"
            }
        )

    finally:
        session.close()

# ==========================
# RUN
# ==========================
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
