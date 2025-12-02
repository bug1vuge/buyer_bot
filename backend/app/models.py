from sqlalchemy import (
    Column, Integer, String, DateTime, Text, ForeignKey,
    BigInteger
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(64), unique=True, nullable=True)
    title = Column(String(256), nullable=False)
    base_price_cents = Column(Integer, nullable=False, default=0)  # цена в копейках
    agent_percent = Column(Integer, nullable=False, default=0)     # % агентского вознаграждения
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<Product id={self.id} title={self.title!r} price={self.base_price_cents}>"

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_id_str = Column(String(32), unique=True, nullable=False, index=True)  # формата YYYYMMDD_### 
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1)
    total_amount_cents = Column(Integer, nullable=False, default=0)  # сумма в копейках
    agent_fee_cents = Column(Integer, nullable=False, default=0)     # агентское вознаграждение в копейках

    customer_fullname = Column(String(256))
    customer_phone = Column(String(64))
    customer_email = Column(String(256))
    customer_city = Column(String(128))
    customer_address = Column(Text)
    comment = Column(Text, nullable=True)

    status = Column(String(32), default="created")  # created, pending, paid, cancelled, archived
    yookassa_payment_id = Column(String(128), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    paid_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    # relationship to product
    product = relationship("Product", lazy="joined")

    def __repr__(self):
        return f"<Order id={self.id} order_id={self.order_id_str!r} status={self.status}>"

class Admin(Base):
    __tablename__ = "admins"

    telegram_id = Column(BigInteger, primary_key=True)
    name = Column(String(256))
    permissions = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Admin telegram_id={self.telegram_id}>"
