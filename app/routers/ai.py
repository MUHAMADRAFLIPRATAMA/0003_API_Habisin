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
        raise HTTPException(403, "Akses khusus penjual")


def buyer_only(user: User):
    if user.peran != "pembeli":
        raise HTTPException(403, "Akses khusus pembeli")


def authenticated_only(user: User):
    if user.peran not in {"pembeli", "penjual"}:
        raise HTTPException(403, "Role akun tidak valid")


def safe_question(text: str) -> str:
    lowered = text.lower()
    blocked = ("pasti aman", "sudah basi", "gejala sakit", "keracunan", "diagnosis")
    if any(word in lowered for word in blocked):
        raise HTTPException(400, "Pertanyaan di luar cakupan. Hubungi penjual atau tenaga kesehatan.")
    return text.strip()


def _gemini_models() -> list[str]:
    configured = os.getenv("GEMINI_MODEL", "").strip()
    models = [configured] if configured else []
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100",
            headers={"x-goog-api-key": GEMINI_API_KEY},
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read())
        available = [str(item.get("name", "")).removeprefix("models/") for item in data.get("models", [])]
        available = [name for name in available if "flash" in name and "generateContent" in str(next((item.get("supportedGenerationMethods", []) for item in data.get("models", []) if str(item.get("name", "")).endswith(name)), []))]
        models.extend(available)
    except Exception:
        pass
    models.extend(["gemini-flash-lite-latest", "gemini-flash-latest"])
    return list(dict.fromkeys(model for model in models if model))[:5]


def gemini_prompt(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("AI key belum dikonfigurasi")
    variants = [
        {"maxOutputTokens": 600, "thinkingConfig": {"thinkingBudget": 0}},
        {"maxOutputTokens": 600},
    ]
