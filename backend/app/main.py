import uvicorn
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from .config import settings
from .models import Base, Product, Order, Admin, OrdersArchive, SalesReportArchive
from .schemas import CreateOrderIn, CreateOrderOut, SalesReportIn, SalesReportItem, SalesReportOut, CancelOrderIn, DeleteSalesReportIn
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from datetime import datetime, timezone, timedelta, date
from .tinkoff_client import create_tinkoff_payment, check_order, generate_token, build_paid_message, send_admin_notification
from pathlib import Path
from sqlalchemy import or_, and_

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



#генерация pdf продаж
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

    c.setFont("Inter-Medium", 9)

    for item in items:
        if y < 80:
            c.showPage()
            y = height - 50
            c.setFont("Inter-Medium", 9)

        product_title = item.get("product_title", "")
        quantity = item.get("quantity", 0)
        total_amount = item.get("total_amount", 0)
        agent_fee = item.get("agent_fee", 0)

        c.drawString(40, y, str(product_title))
        c.drawRightString(280, y, str(quantity))
        c.drawRightString(360, y, f"{total_amount:,}".replace(",", " "))
        c.drawRightString(460, y, f"{agent_fee:,}".replace(",", " "))
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
                date_to = None
            else:
                date_from = now - timedelta(days=int(payload.period))
                date_to = now
        else:
            # payload.start_date и payload.end_date предполагаются объектами date (pydantic)
            # приводим их к datetime с timezone UTC
            date_from = datetime.combine(payload.start_date, datetime.min.time(), tzinfo=timezone.utc)
            date_to = datetime.combine(payload.end_date, datetime.max.time(), tzinfo=timezone.utc)


        query = (
            session.query(
                Product.title.label("product_title"),
                func.coalesce(func.sum(Order.quantity), 0).label("quantity"),
                func.coalesce(func.sum(Order.total_amount_cents), 0).label("total_amount"),
                func.coalesce(func.sum(Order.agent_fee_cents), 0).label("agent_fee"),
            )
            .join(Product, Product.id == Order.product_id)
            .filter(Order.status.in_(["pending", "paid"]))
        )

        # Если период задан — фильтруем так, чтобы учитывались:
        #  - paid  — по полю paid_at
        #  - created — по полю created_at
        if date_from or date_to:
            # составим условия по lower/upper границам
            conds = []
            if date_from and date_to:
                conds.append(
                    or_(
                        and_(Order.status == "paid", Order.paid_at >= date_from, Order.paid_at <= date_to),
                        and_(Order.status == "pending", Order.created_at >= date_from, Order.created_at <= date_to),
                    )
                )
            elif date_from:
                conds.append(
                    or_(
                        and_(Order.status == "paid", Order.paid_at >= date_from),
                        and_(Order.status == "pending", Order.created_at >= date_from),
                    )
                )
            elif date_to:
                conds.append(
                    or_(
                        and_(Order.status == "paid", Order.paid_at <= date_to),
                        and_(Order.status == "pending", Order.created_at <= date_to),
                    )
                )

            if conds:
                query = query.filter(*conds)

        query = query.group_by(Product.title)

        rows = query.all()

        items = []
        total_sum = 0
        total_agent = 0

        for r in rows:
            qty = int(r.quantity or 0)
            total_amount_rub = int((r.total_amount or 0) // 100)
            agent_fee_rub = int((r.agent_fee or 0) // 100)

            items.append({
                "product_title": r.product_title,
                "quantity": qty,
                "total_amount": total_amount_rub,
                "agent_fee": agent_fee_rub,
            })
            total_sum += total_amount_rub
            total_agent += agent_fee_rub

        # Заголовок отчёта
        if payload.period == "all":
            title = "Отчёт за всё время"
        elif payload.period:
            title = f"Отчёт за последние {payload.period} дней"
        else:
            title = f"Отчёт за период: {payload.start_date} - {payload.end_date}"

        # Если нет данных — сгенерируем PDF с пометкой "Нет данных"
        if not items:
            pdf_bytes = generate_sales_report_pdf(
                title=title,
                items=[{"product_title": "Нет данных за период", "quantity": 0, "total_amount": 0, "agent_fee": 0}],
                total_sum=0,
                total_agent=0
            )
        else:
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

# генерация pdf клиентов
def wrap_text(text: str, max_width: int, font: str, font_size: int) -> list[str]:
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = f"{current} {word}".strip()
        if stringWidth(test, font, font_size) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines or [""]


def generate_clients_report_pdf(title: str, items: list[dict]) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50

    LINE_HEIGHT = 12
    ROW_PADDING = 10
    PRODUCT_COL_WIDTH = 55
    CLIENT_COL_WIDTH = 160
    CLIENT_X = 410
       

    # Заголовок
    c.setFont("Inter-Medium", 14)
    c.drawString(40, y, title)
    y -= 40

    # Шапка таблицы
    c.setFont("Inter-Medium", 10)
    c.drawString(60, y, "ID заказа")
    c.drawString(140, y, "Товар")
    c.drawString(200, y, "Кол-во")
    c.drawString(260, y, "Сумма ₽")
    c.drawString(330, y, "Дата")
    c.drawString(CLIENT_X, y, "Клиент")
    y -= 20

    c.setFont("Inter-Medium", 9)

    for item in items:
        if y < 140:
            c.showPage()
            y = height - 50
            c.setFont("Inter-Medium", 9)

        # ---------- ТОВАР (перенос строк) ----------
        product_lines = wrap_text(
            item["product_title"],
            PRODUCT_COL_WIDTH,
            "Inter-Medium",
            9
        )

        # ---------- КЛИЕНТ ----------
        client_lines = []
        client = item["client"]
        
        for value in (
            client.get("fullname"),
            client.get("phone"),
            client.get("city"),
            client.get("address"),
        ):
            if value:
                wrapped = wrap_text(
                    value,
                    CLIENT_COL_WIDTH,
                    "Inter-Medium",
                    9
                )
                client_lines.extend(wrapped)


        # ---------- ВЫСОТА СТРОКИ ----------
        row_height = max(
            len(product_lines),
            len(client_lines),
            1
        ) * LINE_HEIGHT + ROW_PADDING

        # ---------- ОТРИСОВКА ----------
        c.drawString(60, y, item["order_id"])

        py = y
        for line in product_lines:
            c.drawString(140, py, line)
            py -= LINE_HEIGHT

        c.drawRightString(220, y, str(item["quantity"]))
        c.drawRightString(290, y, f"{item['total_amount']:,}".replace(",", " "))
        c.drawString(330, y, item["date"])

        cy = y
        for line in client_lines:
            c.drawString(CLIENT_X, cy, line)
            cy -= LINE_HEIGHT

        y -= row_height

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

@app.post("/api/reports/clients")
def clients_report(payload: SalesReportIn):
    session = SessionLocal()

    try:
        now = datetime.now(timezone.utc)

        # -------- Период --------
        if payload.period:
            if payload.period == "all":
                date_from = None
                date_to = None
            else:
                date_from = now - timedelta(days=int(payload.period))
                date_to = now
        else:
            date_from = datetime.combine(
                payload.start_date,
                datetime.min.time(),
                tzinfo=timezone.utc
            )
            date_to = datetime.combine(
                payload.end_date,
                datetime.max.time(),
                tzinfo=timezone.utc
            )

        # -------- Запрос --------
        query = (
            session.query(
                Order,
                Product.title.label("product_title")
            )
            .join(Product, Product.id == Order.product_id)
            .filter(Order.status.in_(["pending", "paid"]))
        )

        if date_from:
            query = query.filter(Order.created_at >= date_from)
        if date_to:
            query = query.filter(Order.created_at <= date_to)

        rows = query.order_by(Order.created_at).all()

        # -------- Формирование данных --------
        items = []

        for order, product_title in rows:
            items.append({
                "order_id": order.order_id_str,
                "product_title": product_title,
                "quantity": order.quantity,
                "total_amount": int(order.total_amount_cents // 100),
                "date": order.created_at.strftime("%d.%m.%y") if order.created_at else "",
                "client": {
                    "fullname": order.customer_fullname,
                    "phone": order.customer_phone,
                    "city": order.customer_city,
                    "address": order.customer_address,
                }
            })

        # -------- Заголовок --------
        if payload.period == "all":
            title = "Отчёт по клиентам за всё время"
        elif payload.period:
            title = f"Отчёт по клиентам за последние {payload.period} дней"
        else:
            title = f"Отчёт по клиентам: {payload.start_date} - {payload.end_date}"

        # -------- Если данных нет --------
        if not items:
            items = [{
                "order_id": "Нет данных",
                "product_title": "",
                "quantity": 0,
                "total_amount": 0,
                "date": "",
                "client": {}
            }]

        # -------- Генерация PDF --------
        pdf_bytes = generate_clients_report_pdf(title, items)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=clients_report.pdf"
            }
        )

    finally:
        session.close()

        
# отмена заказа
@app.post("/api/orders/cancel")
def cancel_order(payload: CancelOrderIn):
    session: Session = SessionLocal()

    try:
        # 1) Найти заказ по правильному полю
        order = (
            session.query(Order)
            .filter(Order.order_id_str == payload.order_id)
            .first()
        )

        if not order:
            raise HTTPException(status_code=404, detail="Заказ не найден")

        # 2) Проверка статуса — разрешаем отменять только pending или paid
        if order.status not in ("pending", "paid"):
            raise HTTPException(
                status_code=400,
                detail="Отменить можно только заказ со статусом pending или paid"
            )

        # 3) Собираем данные клиента (используем реальные имена колонок)
        client = {
            "fullname": order.customer_fullname,
            "phone": order.customer_phone,
            "city": order.customer_city,
            "address": order.customer_address
        }

        # 4) Сохраняем в архив (используем корректный класс OrderArchive и оригинальное поле)
        archive = OrdersArchive(
            original_order_id=order.order_id_str,
            data={
                "order": {
                    "order_id_str": order.order_id_str,
                    "product_id": order.product_id,
                    "quantity": order.quantity,
                    "total_amount_cents": order.total_amount_cents,
                    "agent_fee_cents": order.agent_fee_cents,
                    "status": order.status,
                    "created_at": order.created_at.isoformat() if order.created_at else None
                },
                "client": client
            },
            restore_until=datetime.now(timezone.utc) + timedelta(days=30)
        )

        session.add(archive)

        # 5) Удаляем заказ из основной таблицы
        session.delete(order)
        session.commit()

        # 6) Возвращаем ответ, который ожидает бот
        return JSONResponse(
            {
                "message": f"Заказ с ID {payload.order_id} удален из системы",
                "refund": {
                    "amount": f"{order.total_amount_cents // 100:,}".replace(",", " "),
                    "client": client["fullname"],
                    "phone": client["phone"]
                }
            }
        )

    except HTTPException:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        # Логирование ошибки полезно для диагностики (вставь свой logger)
        # logger.exception("Error cancelling order")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

# удаление отчета по продажам
@app.post("/api/reports/sales/delete")
def delete_sales_report(payload: DeleteSalesReportIn):
    session: Session = SessionLocal()

    try:
        now = datetime.now(timezone.utc)

        # -------- Период --------
        if payload.period:
            if payload.period == "all":
                date_from = None
                date_to = None
            else:
                date_from = now - timedelta(days=int(payload.period))
                date_to = now
        else:
            date_from = datetime.combine(payload.start_date, datetime.min.time(), tzinfo=timezone.utc)
            date_to = datetime.combine(payload.end_date, datetime.max.time(), tzinfo=timezone.utc)

        # -------- Агрегация --------
        report_rows = (
            session.query(
                Product.id.label("product_id"),
                Product.title.label("product_title"),
                func.sum(Order.quantity).label("quantity"),
                func.sum(Order.total_amount_cents).label("total_amount"),
                func.sum(Order.agent_fee_cents).label("agent_fee"),
            )
            .join(Product, Product.id == Order.product_id)
            .filter(Order.status.in_(["pending", "paid"]))
        )

        if date_from:
            report_rows = report_rows.filter(Order.created_at >= date_from)
        if date_to:
            report_rows = report_rows.filter(Order.created_at <= date_to)

        report_rows = report_rows.group_by(Product.id, Product.title).all()

        if not report_rows:
            raise HTTPException(status_code=404, detail="Нет данных за выбранный период")

        data = {
            "items": [
                {
                    "product_id": r.product_id,
                    "product_title": r.product_title,
                    "quantity": int(r.quantity or 0),
                    "total_amount_cents": int(r.total_amount or 0),
                    "agent_fee_cents": int(r.agent_fee or 0),
                }
                for r in report_rows
            ],
            "total_sum_cents": sum(int(r.total_amount or 0) for r in report_rows),
            "total_agent_cents": sum(int(r.agent_fee or 0) for r in report_rows),
        }

        # -------- Архив --------
        archive = SalesReportArchive(
            period_from=date_from,
            period_to=date_to,
            data=data,
            restore_until=now + timedelta(days=30)
        )
        session.add(archive)

        # -------- Удаление заказов --------
        delete_q = session.query(Order).filter(Order.status.in_(["pending", "paid"]))

        if date_from:
            delete_q = delete_q.filter(Order.created_at >= date_from)
        if date_to:
            delete_q = delete_q.filter(Order.created_at <= date_to)

        deleted_count = delete_q.delete(synchronize_session=False)

        session.commit()

        return {
            "message": "Отчёт по продажам удалён",
            "deleted_orders": deleted_count
        }

    finally:
        session.close()

# удаление отчета по клиентам
# @app.post("/api/reports/clients/delete")
# def delete_clients_report(payload: DeleteClientsReportIn):
#     session: Session = SessionLocal()

#     try:
#         now = datetime.now(timezone.utc)

#         # -------- Период --------
#         if payload.period:
#             if payload.period == "all":
#                 date_from = None
#                 date_to = None
#             else:
#                 date_from = now - timedelta(days=int(payload.period))
#                 date_to = now
#         else:
#             date_from = datetime.combine(payload.start_date, datetime.min.time(), tzinfo=timezone.utc)
#             date_to = datetime.combine(payload.end_date, datetime.max.time(), tzinfo=timezone.utc)

#         # -------- Получаем данные клиентов --------
#         query = session.query(Order).filter(Order.status.in_(["pending", "paid"]))

#         if date_from:
#             query = query.filter(Order.created_at >= date_from)
#         if date_to:
#             query = query.filter(Order.created_at <= date_to)

#         orders = query.all()

#         if not orders:
#             raise HTTPException(status_code=404, detail="Нет данных за выбранный период")

#         # -------- Формируем архивные данные --------
#         data = [
#             {
#                 "order_id": o.order_id_str,
#                 "customer_fullname": o.customer_fullname,
#                 "customer_phone": o.customer_phone,
#                 "customer_email": o.customer_email,
#                 "customer_city": o.customer_city,
#                 "customer_address": o.customer_address,
#                 "comment": o.comment,
#                 "product_id": o.product_id,
#                 "quantity": o.quantity,
#                 "total_amount_cents": o.total_amount_cents,
#                 "agent_fee_cents": o.agent_fee_cents,
#                 "status": o.status,
#                 "created_at": o.created_at.isoformat(),
#                 "paid_at": o.paid_at.isoformat() if o.paid_at else None
#             }
#             for o in orders
#         ]

#         archive = ClientsReportArchive(
#             period_from=date_from,
#             period_to=date_to,
#             data=data,
#             restore_until=now + timedelta(days=30)
#         )
#         session.add(archive)

#         # -------- Удаляем данные клиентов --------
#         delete_q = session.query(Order).filter(Order.status.in_(["pending", "paid"]))

#         if date_from:
#             delete_q = delete_q.filter(Order.created_at >= date_from)
#         if date_to:
#             delete_q = delete_q.filter(Order.created_at <= date_to)

#         deleted_count = delete_q.delete(synchronize_session=False)

#         session.commit()

#         return {
#             "message": "Отчёт по клиентам удалён",
#             "deleted_orders": deleted_count
#         }

#     finally:
#         session.close()



# ==========================
# RUN
# ==========================
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
