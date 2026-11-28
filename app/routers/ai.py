import asyncio
import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from ..config import GEMINI_API_KEY, N8N_RAG_TIMEOUT_SECONDS, N8N_RAG_URL
from ..database import get_db
from ..models import CartItem, Order, Product, User
from .orders import current_user

router = APIRouter(prefix="/ai", tags=["ai"])
WARNING = "Ini perkiraan umum. Periksa kondisi makanan sebelum dimakan. Jika bau, rasa, atau tampilan berubah, jangan dikonsumsi."

class PriceRequest(BaseModel):
    nama: str = Field(min_length=1, max_length=150)
    harga_normal: int = Field(gt=0)
    batas_konsumsi: str | None = Field(default=None, max_length=80)

class DescriptionRequest(BaseModel):
    nama: str = Field(min_length=1, max_length=150)
    jenis_makanan: str = Field(min_length=1, max_length=40)

class SmartSearchRequest(BaseModel):
    pertanyaan: str = Field(min_length=1, max_length=300)

class AskProductRequest(BaseModel):
    produk_id: int
    pertanyaan: str = Field(min_length=1, max_length=300)

class ChatRequest(BaseModel):
    pesan: str = Field(min_length=1, max_length=500)

class ChatResponse(BaseModel):
    jawaban: str
    dari_gemini: bool
    dari_n8n: bool = False
    produk: list[dict] = []


def seller_only(user: User):
    if user.peran != "penjual":
