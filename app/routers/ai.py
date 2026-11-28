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
    last_error = "Gemini tidak merespons"
    for model in _gemini_models():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for generation_config in variants:
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": generation_config}).encode()
            request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    data = json.loads(response.read())
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(str(part.get("text", "")) for part in parts).strip()
                if text:
                    return text
                last_error = "Gemini mengembalikan jawaban kosong"
            except urllib.error.HTTPError as exc:
                last_error = f"Gemini HTTP {exc.code}"
                if exc.code in (401, 403):
                    raise RuntimeError(last_error)
            except Exception as exc:
                last_error = type(exc).__name__
    raise RuntimeError(last_error)


def one_sentence(text: str, fallback: str) -> str:
    value = " ".join(str(text).replace("\n", " ").split()).strip()
    value = re.split(r"(?<=[.!?])\s+", value, maxsplit=1)[0].strip()
    if not value:
        value = fallback
    if value[-1] not in ".!?":
        value += "."
    return value


async def ask_ai(prompt: str, fallback: str) -> str:
    try:
        return await asyncio.wait_for(asyncio.to_thread(gemini_prompt, prompt), timeout=15)
    except Exception:
        try:
            return await asyncio.wait_for(asyncio.to_thread(n8n_prompt, prompt, []), timeout=N8N_RAG_TIMEOUT_SECONDS)
        except Exception:
            return fallback


def n8n_prompt(question: str, products: list[dict]) -> str:
    if not N8N_RAG_URL:
        raise RuntimeError("n8n belum dikonfigurasi")
    body = json.dumps({"pesan": question, "produk": products}).encode()
