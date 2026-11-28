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

@router.put("/{item_id}")
def update_cart(item_id: int, data: CartUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(CartItem, item_id)
    if not item or item.user_id != user.id: raise HTTPException(404, "Item keranjang tidak ditemukan")
    product = db.get(Product, item.product_id)
    if not product or data.jumlah > product.stok: raise HTTPException(400, "Stok tidak mencukupi")
    item.jumlah = data.jumlah; db.commit(); db.refresh(item); return out(item)

@router.delete("/{item_id}")
def delete_cart(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(CartItem, item_id)
    if not item or item.user_id != user.id: raise HTTPException(404, "Item keranjang tidak ditemukan")
    db.delete(item); db.commit(); return {"ok": True}

@router.post("/checkout")
def checkout(user: User = Depends(current_user), db: Session = Depends(get_db)):
    active = db.scalar(select(CheckoutSession).where(CheckoutSession.user_id == user.id, CheckoutSession.status == "aktif"))
    if active:
        total = sum(x.total_harga for x in db.scalars(select(Order).where(Order.checkout_session_id == active.id)).all())
        return {"session_id": active.id, "payment_code": active.payment_code, "total_harga": total, "berlaku_sampai": active.payment_expires_at}
    items = list(db.scalars(select(CartItem).where(CartItem.user_id == user.id)).all())
    if not items: raise HTTPException(400, "Keranjang kosong")
    locked = []
    for item in items:
        product = db.scalar(select(Product).where(Product.id == item.product_id).with_for_update())
        if not product or product.stok < item.jumlah: raise HTTPException(400, "Stok produk berubah atau tidak mencukupi")
        product.stok -= item.jumlah; locked.append((item, product))
    session = CheckoutSession(user_id=user.id, payment_code=secrets.token_urlsafe(24), payment_expires_at=datetime.now() + timedelta(seconds=PAYMENT_QR_TTL_SECONDS))
    db.add(session); db.flush()
    for item, product in locked:
        db.add(Order(user_id=user.id, product_id=product.id, jumlah=item.jumlah, total_harga=product.harga_diskon * item.jumlah, status="menunggu", payment_code=None, payment_expires_at=session.payment_expires_at, checkout_session_id=session.id))
    db.commit(); db.refresh(session)
    return {"session_id": session.id, "payment_code": session.payment_code, "total_harga": sum(product.harga_diskon * item.jumlah for item, product in locked), "berlaku_sampai": session.payment_expires_at}

@router.get("/checkout/{session_id}/qr")
def checkout_qr(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = db.get(CheckoutSession, session_id)
    if not session or session.user_id != user.id or session.status != "aktif": raise HTTPException(404, "Checkout tidak ditemukan")
    if datetime.now() > session.payment_expires_at:
        session.payment_code = secrets.token_urlsafe(24); session.payment_expires_at = datetime.now() + timedelta(seconds=PAYMENT_QR_TTL_SECONDS); db.commit(); db.refresh(session)
