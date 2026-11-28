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
    query = select(CartItem).join(Product).where(CartItem.user_id == user.id)
    if q.strip(): query = query.where(Product.nama.ilike(f"%{q.strip()}%"))
    return [out(x) for x in db.scalars(query.order_by(CartItem.id.desc())).all()]

@router.post("")
def add_cart(data: CartIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    product = db.get(Product, data.product_id)
    if not product or product.stok < data.jumlah: raise HTTPException(400, "Produk tidak tersedia atau stok kurang")
    item = db.scalar(select(CartItem).where(CartItem.user_id == user.id, CartItem.product_id == data.product_id))
    if item: item.jumlah += data.jumlah
    else: item = CartItem(user_id=user.id, product_id=data.product_id, jumlah=data.jumlah); db.add(item)
    if item.jumlah > product.stok: raise HTTPException(400, "Jumlah melebihi stok")
    db.commit(); db.refresh(item); return out(item)

