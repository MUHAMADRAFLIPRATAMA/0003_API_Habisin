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
    request = urllib.request.Request(
        N8N_RAG_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=N8N_RAG_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read())
    answer = str(data.get("jawaban", "")).strip()
    if not answer:
        raise RuntimeError("n8n mengembalikan jawaban kosong")
    return answer


@router.post("/chat", response_model=ChatResponse)
async def chat(data: ChatRequest, db: Session = Depends(get_db)):
    question = safe_question(data.pesan)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    active = or_(Product.batas_konsumsi.is_(None), Product.batas_konsumsi >= now)
    products = list(db.scalars(select(Product).where(Product.stok > 0, active).order_by(Product.id.desc()).limit(30)).all())
    catalog = "\\n".join(f"- {p.nama}: {p.deskripsi} (jenis: {p.jenis_makanan}, stok: {p.stok})" for p in products)
    context_match = re.match(r"Tentang produk\\s+(.+?):\\s*(.*)", question, re.IGNORECASE | re.DOTALL)
    selected_name = context_match.group(1).strip() if context_match else ""
    actual_question = context_match.group(2).strip() if context_match else question
    search_terms = {word.lower() for word in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", actual_question) if len(word) > 2}
    matched_products = [p for p in products if selected_name.lower() == p.nama.lower()] if selected_name else [p for p in products if search_terms.intersection({word.lower() for word in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", f"{p.nama} {p.deskripsi or ''} {p.jenis_makanan or ''}")})]
    product_data = [{"id": p.id, "nama": p.nama, "deskripsi": p.deskripsi, "harga_diskon": p.harga_diskon, "stok": p.stok, "jenis_makanan": p.jenis_makanan} for p in matched_products]
    matched_catalog = "\\n".join(f"- {p.nama}: {p.deskripsi} (jenis: {p.jenis_makanan}, stok: {p.stok})" for p in matched_products)
    prompt = f"Kamu adalah Habisin AI. Jawab pertanyaan pengguna secara langsung, natural, dan spesifik—bukan dengan template. Produk aktif yang sedang dibahas: {selected_name or '(tidak ada produk aktif)'}. Pertanyaan pengguna: {actual_question}. Gunakan data produk aktif di bawah sebagai konteks utama. Kamu boleh memakai pengetahuan umum yang relevan untuk menjawab pertanyaan, tetapi jangan menampilkan atau membahas produk katalog lain yang tidak ditanyakan. Jangan mengulang deskripsi produk jika tidak diminta. Hanya katakan informasi belum tersedia jika pengguna meminta fakta khusus produk yang memang tidak ada pada data. Jangan mengarang bahan, kandungan, tanggal, harga, stok, atau kondisi produk. Untuk keamanan makanan, jangan menjamin aman/basi dan jangan mendiagnosis. Jawab bahasa Indonesia. Data produk aktif:\\n{matched_catalog or '(data produk aktif tidak tersedia)'}"
    fallback = "Habisin AI belum tersambung. Coba lagi nanti."
    started = asyncio.get_running_loop().time()
    try:
        answer = await asyncio.wait_for(asyncio.to_thread(gemini_prompt, prompt), timeout=15)
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0.0, 3.0 - elapsed))
        return {"jawaban": answer, "dari_gemini": True, "produk": product_data}
    except Exception:
        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(n8n_prompt, actual_question, product_data),
                timeout=N8N_RAG_TIMEOUT_SECONDS,
            )
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, 3.0 - elapsed))
            return {"jawaban": answer, "dari_gemini": False, "dari_n8n": True, "produk": product_data}
        except Exception:
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, 3.0 - elapsed))
            return {"jawaban": fallback, "dari_gemini": False, "dari_n8n": False, "produk": product_data}


@router.post("/saran-harga")
async def suggest_price(data: PriceRequest, user: User = Depends(current_user)):
    seller_only(user)
    # Harga deterministik dari batas konsumsi; AI hanya menjelaskan alasan.
    discount_rate = 0.25
    if data.batas_konsumsi:
        try:
            expiry = datetime.strptime(data.batas_konsumsi[:16], "%Y-%m-%d %H:%M")
            days_left = (expiry - datetime.now()).total_seconds() / 86400
            discount_rate = 0.45 if days_left <= 1 else 0.35 if days_left <= 3 else 0.25
        except ValueError:
            pass
    discount = max(1, min(data.harga_normal - 1, round(data.harga_normal * (1 - discount_rate))))
    fallback = f"Usulan harga Rp{discount}. Pertimbangkan batas konsumsi dan kondisi produk sebelum mengubah harga."
    answer = await ask_ai(f"Jelaskan dalam satu kalimat alasan saran harga Rp{discount} untuk produk {data.nama} dengan harga normal Rp{data.harga_normal} dan batas konsumsi {data.batas_konsumsi or 'belum diisi'}. Jangan menjamin keamanan makanan.", fallback)
    return {"harga_saran": discount, "alasan": answer}


@router.post("/deskripsi-produk")
async def product_description(data: DescriptionRequest, user: User = Depends(current_user)):
    seller_only(user)
    fallback = f"{data.nama} merupakan {data.jenis_makanan} pilihan dengan harga diskon untuk membantu mengurangi makanan terbuang."
    answer = await ask_ai(f"Tulis tepat satu kalimat deskripsi bahasa Indonesia untuk produk {data.nama}, jenis {data.jenis_makanan}; maksimal 20 kata, tanpa daftar, baris baru, klaim kesehatan, atau jaminan keamanan.", fallback)
    return {"deskripsi": one_sentence(answer, fallback)}


@router.get("/ringkasan-penjualan")
async def sales_summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    seller_only(user)
    rows = list(db.scalars(select(Order).join(Product).where(Product.penjual_id == user.id, Order.status == "selesai")).all())
    total_orders = len(rows)
    revenue = sum(x.total_harga for x in rows)
    units = sum(x.jumlah for x in rows)
    fallback = f"Dalam data yang tersedia, terdapat {total_orders} pesanan selesai, {units} porsi tersalamatkan, dan pendapatan Rp{revenue}."
    answer = await ask_ai(f"Ringkas data penjualan berikut tanpa mengubah angka: pesanan={total_orders}, porsi={units}, pendapatan={revenue} rupiah.", fallback)
    return {"jumlah_pesanan": total_orders, "jumlah_porsi": units, "pendapatan": revenue, "ringkasan": answer}


@router.post("/cari")
async def smart_search(data: SmartSearchRequest, db: Session = Depends(get_db)):
    # Pencarian katalog publik; endpoint tidak membutuhkan token.
    text = safe_question(data.pertanyaan)
    answer = await ask_ai(f"Ubah kalimat pencarian makanan ini menjadi kata kunci singkat saja: {text}", text)
    terms = {word.strip().lower() for word in (text + " " + answer).split() if len(word.strip()) >= 3}
    aliases = {
        "segar": {"minuman", "dingin", "teh", "jus", "es"},
        "dingin": {"minuman", "teh", "jus", "es"},
        "manis": {"minuman", "teh", "jus"},
        "minuman": {"teh", "jus", "es"},
    }
    expanded_terms = terms | {alias for term in terms for alias in aliases.get(term, set())}
    conditions = [
        Product.nama.ilike(f"%{term}%")
        for term in expanded_terms
    ] + [
        Product.deskripsi.ilike(f"%{term}%")
        for term in expanded_terms
    ] + [
        Product.jenis_makanan.ilike(f"%{term}%")
        for term in expanded_terms
    ]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    active = or_(Product.batas_konsumsi.is_(None), Product.batas_konsumsi >= now)
    products = list(db.scalars(select(Product).where(or_(*conditions), Product.stok > 0, active).order_by(Product.id.desc())).unique().all()) if conditions else []
    return {"kata_kunci": answer, "produk": products}


@router.get("/dampakku")
async def impact(user: User = Depends(current_user), db: Session = Depends(get_db)):
    buyer_only(user)
    rows = list(db.scalars(select(Order).where(Order.user_id == user.id, Order.status == "selesai")).all())
    portions = sum(x.jumlah for x in rows)
    saved = sum(max(0, x.total_harga) for x in rows)
    fallback = f"Kamu sudah menyelesaikan {len(rows)} pesanan dan membantu menyelamatkan {portions} porsi makanan."
    answer = await ask_ai(f"Buat ringkasan ramah dari angka ini tanpa mengubahnya: pesanan selesai={len(rows)}, porsi terselamatkan={portions}, total belanja={saved} rupiah.", fallback)
    return {"pesanan_selesai": len(rows), "porsi_terselamatkan": portions, "total_belanja": saved, "ringkasan": answer}


@router.post("/tanya-produk")
async def ask_product(data: AskProductRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    authenticated_only(user)
    question = safe_question(data.pertanyaan)
    product = db.get(Product, data.produk_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not product or product.stok <= 0 or (product.batas_konsumsi and product.batas_konsumsi < now):
        raise HTTPException(404, "Produk tidak tersedia atau sudah melewati batas konsumsi")
    answer = await ask_ai(f"Jawab pertanyaan umum tentang waktu konsumsi produk {product.nama}: {question}. Jangan menyatakan pasti aman atau basi. Jangan memberi diagnosis.", f"Produk {product.nama} memiliki informasi batas konsumsi dari penjual. Periksa label dan kondisi produk secara langsung.")
    return {"produk_id": product.id, "sisa_waktu": "Tidak tersedia", "jawaban": answer, "catatan": WARNING}

class CartQuestionRequest(BaseModel):
    pertanyaan: str = Field(default="", max_length=300)


def _parse_batas(value: str | None) -> datetime | None:
    """`batas_konsumsi` disimpan sebagai teks, jadi diurai ke datetime sebelum dihitung."""
    if not value:
        return None
    teks = str(value).strip()[:19]
    for pola in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(teks, pola)
        except ValueError:
            continue
    return None


def _cart_snapshot(db: Session, user: User) -> tuple[list[dict], dict]:
    """Membaca isi keranjang pengguna beserta ringkasan yang dipakai fitur AI."""
    rows = (
        db.query(CartItem, Product)
        .join(Product, CartItem.product_id == Product.id)
        .filter(CartItem.user_id == user.id)
        .all()
    )
    sekarang = datetime.now()
    item: list[dict] = []
    total = hemat = 0
    segera: list[str] = []
    for cart, produk in rows:
        harga = produk.harga_diskon or 0
        subtotal = harga * cart.jumlah
        total += subtotal
        hemat += max(0, (produk.harga_normal or 0) - harga) * cart.jumlah
        batas = _parse_batas(produk.batas_konsumsi)
        sisa_jam = None
        if batas:
            sisa_jam = int((batas - sekarang).total_seconds() // 3600)
            if sisa_jam <= 6:
                segera.append(produk.nama)
        item.append(
            {
                "cart_id": cart.id,
                "produk_id": produk.id,
                "nama": produk.nama,
                "jumlah": cart.jumlah,
                "harga": harga,
                "harga_normal": produk.harga_normal,
                "subtotal": subtotal,
                "stok": produk.stok,
                "jenis_makanan": produk.jenis_makanan,
                "batas_konsumsi": produk.batas_konsumsi,
                "sisa_jam": sisa_jam,
            }
        )
    ringkasan = {
        "jumlah_item": sum(i["jumlah"] for i in item),
        "jenis_produk": len(item),
        "total": total,
        "hemat": hemat,
        "segera_kedaluwarsa": segera,
    }
    return item, ringkasan


def _cart_fallback(item: list[dict], ringkasan: dict, pertanyaan: str) -> str:
    """Jawaban tanpa model bahasa: disusun dari data keranjang agar fitur tetap berguna."""
    if not item:
        return "Keranjang masih kosong. Tambahkan produk surplus dulu, lalu tanyakan lagi."
    nama = ", ".join(f"{i['nama']} x{i['jumlah']}" for i in item[:3])
    kalimat = [
        f"Keranjang berisi {ringkasan['jumlah_item']} item dari {ringkasan['jenis_produk']} produk: {nama}.",
        f"Total {ringkasan['total']:,} rupiah dengan penghematan {ringkasan['hemat']:,} rupiah dibanding harga normal.".replace(",", "."),
    ]
    if ringkasan["segera_kedaluwarsa"]:
        kalimat.append(
            "Segera dihabiskan atau diambil hari ini: " + ", ".join(ringkasan["segera_kedaluwarsa"]) + "."
        )
    if "murah" in pertanyaan.lower() or "hemat" in pertanyaan.lower():
        termurah = min(item, key=lambda i: i["harga"])
        kalimat.append(f"Item termurah adalah {termurah['nama']} ({termurah['harga']:,} rupiah).".replace(",", "."))
    return " ".join(kalimat)


@router.get("/keranjang")
def cart_insight(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Deteksi isi keranjang pengguna beserta ringkasan hemat dan produk yang mendesak."""
    buyer_only(user)
    item, ringkasan = _cart_snapshot(db, user)
    return {
        "item": item,
        "ringkasan": ringkasan,
        "dari_gemini": False,
        "model_tersedia": bool(GEMINI_API_KEY),
    }
