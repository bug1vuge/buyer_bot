from pydantic import BaseModel, EmailStr
from typing import Optional, Union, List
from datetime import date

class CreateOrderIn(BaseModel):
    product_id: int
    quantity: int = 1
    fullname: str
    phone: str
    email: EmailStr
    city: str
    address: str
    comment: Optional[str] = None

class CreateOrderOut(BaseModel):
    order_id: str
    confirmation_url: str

class SalesReportIn(BaseModel):
    period: Optional[Union[int, str]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class SalesReportItem(BaseModel):
    product_title: str
    quantity: int
    total_amount: int
    agent_fee: int

class SalesReportOut(BaseModel):
    period_from: date
    period_to: date
    items: List[SalesReportItem]
    total_sum: int
    total_agent_fee: int

class CancelOrderIn(BaseModel):
    order_id: str

class DeleteSalesReportIn(BaseModel):
    period: int | str | None = None
    start_date: date | None = None
    end_date: date | None = None
