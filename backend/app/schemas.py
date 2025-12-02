from pydantic import BaseModel, EmailStr
from typing import Optional

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
