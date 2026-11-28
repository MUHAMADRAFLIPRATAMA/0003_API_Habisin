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
