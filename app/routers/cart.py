from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import CartItem, CheckoutSession, Order, Product, User
from datetime import datetime, timedelta
import secrets
import base64
import io
import qrcode
from .orders import current_user
from ..config import PAYMENT_QR_TTL_SECONDS, payment_base_url

router = APIRouter(prefix="/keranjang", tags=["keranjang"])
class CartIn(BaseModel):
    product_id: int
    jumlah: int = Field(gt=0)
class CartUpdate(BaseModel):
    jumlah: int = Field(gt=0)

def out(item):
    return {"id": item.id, "product_id": item.product_id, "jumlah": item.jumlah, "product": item.product}

@router.get("")
def list_cart(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
