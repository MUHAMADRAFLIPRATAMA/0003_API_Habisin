# Habisin API — REST API Marketplace Makanan Surplus

Backend REST API untuk aplikasi Habisin: FastAPI + SQLAlchemy + MySQL 8.0, dijalankan dengan Docker Compose, dan dipakai oleh klien Android (`0003-Habisin`) serta antarmuka web yang disajikan Nginx.

| Item | Keterangan |
|---|---|
| Nama repositori | `0003_API_Habisin` (format `4NIMBelakang_API_NamaProject`) |
| Repositori pasangan | `MUHAMADRAFLIPRATAMA/0003-Habisin` (aplikasi Android) |
| Penyusun | Muhamad Rafli Pratama — NIM 20240140003 — Kelas A |
| Program studi | Teknologi Informasi, Universitas Muhammadiyah Yogyakarta |
| Mata kuliah | Pengembangan Aplikasi Mobile 2026 |
| Dokumen acuan | `SRS_HABISIN_20240140003-v1.0` (SRS proyek Habisin) |
| URL publik | `https://habisin.raflipratama.my.id` |
| Dokumentasi interaktif | `https://habisin.raflipratama.my.id/docs` |

---

## 1. Ringkasan Layanan

API ini menjadi pusat logika bisnis Habisin: autentikasi, otorisasi berbasis peran, katalog produk surplus, keranjang, checkout atomik, pembayaran QR simulasi, riwayat pesanan, ulasan, favorit, struk, laporan penjualan, dan asisten Habisin AI. Aplikasi Android dan antarmuka web memakai API yang sama sehingga data tetap tunggal.

Prinsip yang dipegang:

- **Kredensial hanya di environment** — tidak ada kunci API, kata sandi DB, atau secret JWT di kode maupun repositori.
- **Perhitungan harga di server** — total belanja dihitung dari `harga_diskon` di basis data, bukan dari klien.
- **Stok atomik** — checkout mengunci baris produk dan mengurangi stok dalam satu transaksi.
- **Riwayat tidak dihapus** — pembatalan pesanan mengubah status, bukan menghapus baris.

## 2. Arsitektur

```
Klien Android / Web
        │  HTTPS + JSON + Authorization: Bearer <access_token>
        ▼
   Nginx (container web, port 80/8081)
        │  proxy /auth /produk /keranjang /pesanan /ulasan /favorit /struk /ai /toko /health
        ▼
   FastAPI (container api, port 8000)
        │  SQLAlchemy 2.x
        ▼
   MySQL 8.0 (container db, port 3306 → host 3307)
        ▲
        │
Cloudflare Tunnel (habisin.raflipratama.my.id) → web:80
```

| Komponen | Teknologi |
|---|---|
| Framework | FastAPI 0.x, Uvicorn |
| ORM | SQLAlchemy 2.x + PyMySQL |
| Validasi | Pydantic v2 |
| Autentikasi | python-jose (JWT HS256), passlib + bcrypt |
| Basis data | MySQL 8.0 (utf8mb4, zona waktu Asia/Jakarta) |
| QR | pustaka `qrcode` (PNG → Base64) |
| AI | Gemini / endpoint RAG kompatibel, kunci hanya di `.env` |
| Orkestrasi | Docker Compose (db, api, web, tunnel, tunnel-named) |

## 3. Struktur Repositori

```
0003_API_Habisin/
├── app/
│   ├── main.py            # bootstrap FastAPI, registrasi router, /health
│   ├── config.py          # environment, TTL QR, resolusi base URL pembayaran
│   ├── database.py        # engine + session SQLAlchemy
│   ├── models.py          # 9 entitas (users, products, cart_items, orders, ...)
│   ├── schemas.py         # skema Pydantic
│   ├── security.py        # hash bcrypt, pembuatan & verifikasi JWT
│   ├── seed_demo.py       # akun & produk demo
│   └── routers/
│       ├── auth.py        # register, login, refresh, profil
│       ├── products.py    # katalog, CRUDS produk, unggah gambar
│       ├── cart.py        # keranjang, checkout, QR sesi
│       ├── orders.py      # pesanan, pembayaran, pembatalan, QR pesanan
│       ├── social.py      # ulasan & favorit
│       ├── struk.py       # struk pembayaran
│       ├── reports.py     # ekspor CSV, toko
│       └── ai.py          # chat, saran harga, deskripsi, ringkasan
├── sql/create_database.sql
├── web/                   # antarmuka web pembeli/penjual (dilayani Nginx)
├── docker-compose.yml
├── Dockerfile
├── nginx-web.conf
├── requirements.txt
├── .env.example
├── update_host_ip.py      # menulis IP LAN / URL tunnel untuk isi QR
├── tunnel_watch.py        # memantau URL quick tunnel, memperbarui base URL
├── cek_token_tunnel.py    # memeriksa bentuk token tunnel tanpa menampilkan isi
└── start_demo.bat         # jalankan stack + seed untuk demo
```

## 4. Menjalankan

### 4.1 Docker (cara utama)

```bash
cp .env.example .env      # isi minimal JWT_SECRET dan DATABASE_URL
docker compose up -d db api web
docker compose exec api python -m app.seed_demo
curl -s http://127.0.0.1:8000/health
```

Hasil yang diharapkan:

```json
{"status":"ok","service":"habisin-api","qr_base":"https://habisin.raflipratama.my.id"}
```

Alamat layanan: API `http://127.0.0.1:8000`, Swagger `http://127.0.0.1:8000/docs`, web `http://127.0.0.1:8081`.

### 4.2 Tanpa Docker (venv)

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL="mysql+pymysql://root:<sandi>@127.0.0.1:3306/habisin"
export JWT_SECRET="<secret-panjang>"
uvicorn app.main:app --reload --port 8000
```

Tabel dibuat otomatis oleh SQLAlchemy saat aplikasi pertama kali berjalan (`Base.metadata.create_all`), atau lewat `sql/create_database.sql` untuk pembuatan basis data.

## 5. Variabel Environment

| Variabel | Wajib | Default | Keterangan |
|---|---|---|---|
| `DATABASE_URL` | ya | — | DSN MySQL, mis. `mysql+pymysql://root:sandi@db:3306/habisin` |
| `JWT_SECRET` | ya | — | kunci penandatanganan JWT; aplikasi gagal start bila kosong |
| `ACCESS_TOKEN_MINUTES` | tidak | 15 | masa berlaku access token |
| `REFRESH_TOKEN_DAYS` | tidak | 7 | masa berlaku refresh token |
| `PAYMENT_QR_TTL_SECONDS` | tidak | 60 | masa berlaku kode QR pembayaran |
| `MYSQL_ROOT_PASSWORD` | tidak | `habisin_local` | kata sandi MySQL untuk container `db` |
| `HOST_LAN_IP` | tidak | — | paksa base URL QR memakai IP tertentu |
| `LOCAL_PAYMENT_BASE_URL` | tidak | — | paksa base URL QR (mis. domain tunnel) |
| `GEMINI_API_KEY` | tidak | — | kunci layanan AI; tanpa ini endpoint AI membalas 503 |
| `N8N_RAG_URL` | tidak | — | endpoint RAG alternatif untuk Habisin AI |

Berkas `.env` **tidak** di-commit (lihat `.gitignore`). Gunakan `.env.example` sebagai kerangka.

## 6. Kontrak API

Semua endpoint terproteksi memakai header `Authorization: Bearer <access_token>` dan memeriksa kepemilikan data.

### 6.1 Autentikasi (`/auth`)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| POST | `/auth/register` | — | daftar akun (nama, email, sandi ≥ 8, peran) |
| POST | `/auth/login` | — | mengembalikan `access_token`, `refresh_token`, `peran` |
| POST | `/auth/refresh` | — | menerbitkan access token baru dari refresh token |
| GET | `/auth/me` | ✔ | profil pengguna aktif |

### 6.2 Produk (`/produk`)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| GET | `/produk` | — | katalog; parameter `q`, `jenis_makanan`, `sort` |
| GET | `/produk/{product_id}` | — | detail produk + data penjual |
| GET | `/produk/penjual` | ✔ penjual | daftar produk milik penjual |
| POST | `/produk` | ✔ penjual | tambah produk |
| PUT | `/produk/{product_id}` | ✔ pemilik | ubah produk |
| DELETE | `/produk/{product_id}` | ✔ pemilik | hapus produk |
| POST | `/produk/{product_id}/gambar` | ✔ pemilik | unggah gambar produk |

### 6.3 Keranjang dan Checkout (`/keranjang`)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| GET | `/keranjang` | ✔ | isi keranjang (parameter `q`) |
| POST | `/keranjang` | ✔ | tambah produk (validasi stok) |
| PUT | `/keranjang/{item_id}` | ✔ pemilik | ubah jumlah |
| DELETE | `/keranjang/{item_id}` | ✔ pemilik | hapus item |
| POST | `/keranjang/checkout` | ✔ | membuat sesi, mengunci stok, membuat pesanan |
| GET | `/keranjang/checkout/{session_id}/qr` | ✔ | PNG QR Base64 + `payment_code` + sisa waktu |
| POST | `/keranjang/checkout/{session_id}/refresh` | ✔ | kode baru, kode lama dibatalkan |
| GET | `/keranjang/checkout/{session_id}/status` | ✔ | status sesi untuk pemantauan aplikasi |

### 6.4 Pesanan dan Pembayaran (`/pesanan`)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| POST | `/pesanan` | ✔ | membuat pesanan tunggal |
| GET | `/pesanan/saya` | ✔ | daftar pesanan pembeli |
| GET | `/pesanan/semua` | ✔ penjual | pesanan yang masuk ke penjual |
| PUT | `/pesanan/{order_id}` | ✔ pemilik | ubah data pesanan |
| PATCH | `/pesanan/{order_id}/status` | ✔ penjual | ubah status pesanan |
| POST | `/pesanan/{order_id}/batal` | ✔ | batal (status, bukan hapus) |
| GET | `/pesanan/{order_id}/qr` | ✔ | QR untuk satu pesanan |
| POST | `/pesanan/{order_id}/bayar` | ✔ | tandai pesanan dibayar |
| GET | `/pesanan/bayar/{payment_code}` | — | halaman bayar HTML (dibuka dari QR) |
| GET | `/pesanan/bayar-data/{payment_code}` | — | data sesi dalam JSON |
| POST | `/pesanan/bayar/{payment_code}` | — | konfirmasi pembayaran dari halaman bayar |

### 6.5 Ulasan dan Favorit (`/ulasan`, `/favorit`)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| GET | `/ulasan` | — | daftar ulasan; `q`, `rating`, `product_id` |
| GET | `/ulasan/saya` | ✔ | ulasan milik pengguna |
| POST | `/ulasan/{order_id}` | ✔ | buat ulasan (rating 1–5) |
| PUT | `/ulasan/{review_id}` | ✔ penulis | ubah ulasan |
| DELETE | `/ulasan/{review_id}` | ✔ penulis | hapus ulasan |
| GET | `/favorit` | ✔ | daftar favorit; parameter `q` |
| POST | `/favorit/{product_id}` | ✔ | tambah favorit |
| PUT | `/favorit/{favorite_id}` | ✔ pemilik | ubah catatan |
| DELETE | `/favorit/{favorite_id}` | ✔ pemilik | hapus favorit |

### 6.6 Struk (`/struk`)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| POST | `/struk` | ✔ | simpan struk pembayaran (upsert per pesanan) |
| GET | `/struk` | ✔ | daftar struk; parameter `q` |
| GET | `/struk/{struk_id}` | ✔ pemilik | detail struk |
| DELETE | `/struk/{struk_id}` | ✔ pemilik | hapus struk |

### 6.7 Laporan dan Toko

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| GET | `/pesanan/export.csv` | ✔ penjual | ekspor pesanan penjual sebagai CSV |
| GET | `/toko` | — | daftar toko/penjual |
| GET | `/toko/{seller_id}` | — | detail toko + produk tersedia |

### 6.8 Habisin AI (`/ai`)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| POST | `/ai/chat` | ✔ | percakapan asisten belanja |
| POST | `/ai/cari` | ✔ | pencarian produk dengan bahasa alami |
| POST | `/ai/tanya-produk` | ✔ | tanya detail satu produk |
| POST | `/ai/saran-harga` | ✔ penjual | saran harga diskon |
| POST | `/ai/deskripsi-produk` | ✔ penjual | penyusun deskripsi produk |
| GET | `/ai/ringkasan-penjualan` | ✔ penjual | ringkasan penjualan untuk dashboard |
| GET | `/ai/dampakku` | ✔ | dampak penjualan surplus pembeli |

Total **53 endpoint** pada 8 router. Kode status galat mengikuti SRS 4.4: `400` validasi, `401` autentikasi, `403` akses terlarang, `404` tidak ditemukan, `503` layanan belum dikonfigurasi (mis. kunci AI kosong).

## 7. Contoh Alur (curl)

```bash
# 1. login
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"pembeli@habisin.id","password":"habisin123"}' | jq -r .access_token)

# 2. tambah produk ke keranjang
curl -s -X POST http://127.0.0.1:8000/keranjang \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"product_id":1,"jumlah":1}'

# 3. checkout -> sesi + kode pembayaran
SESSION=$(curl -s -X POST http://127.0.0.1:8000/keranjang/checkout \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' | jq -r .session_id)

# 4. ambil QR (Base64) dan URL pembayaran
curl -s "http://127.0.0.1:8000/keranjang/checkout/$SESSION/qr" -H "Authorization: Bearer $TOKEN" | jq '{payment_code, url, detik_berlaku}'

# 5. bayar (dipanggil halaman bayar setelah pembeli menekan tombol)
curl -s -X POST "http://127.0.0.1:8000/pesanan/bayar/<payment_code>"
```

## 8. Model Data

| Tabel | Kolom kunci | Relasi |
|---|---|---|
| `users` | id, nama, email, kata_sandi (bcrypt), peran, dibuat_pada | induk seluruh data pengguna |
| `products` | id, penjual_id, nama, deskripsi, harga_normal, harga_diskon, stok, jenis_makanan, penyimpanan, batas_konsumsi, gambar | → `users` |
| `cart_items` | id, user_id, product_id, jumlah | → `users`, `products` |
| `orders` | id, user_id, product_id, jumlah, total_harga, status, status_bayar, checkout_session_id | → `users`, `products`, `checkout_sessions` |
| `checkout_sessions` | id, user_id, payment_code, payment_expires_at, status | → `users`; induk banyak `orders` |
| `ulasan` | id, user_id, product_id, order_id, rating, komentar | → `users`, `products`, `orders` |
| `favorit` | id, user_id, product_id, catatan | unik pada (`user_id`, `product_id`) |
| `struk` | id, user_id, order_id, nama_berkas, total_harga, dibuat_pada | → `users`, `orders` |
| `refresh_tokens` | id, user_id, token, kedaluwarsa_pada | → `users` |

## 9. Pembayaran QR Simulasi

1. `POST /keranjang/checkout` mengunci baris produk (`SELECT ... FOR UPDATE`), memvalidasi stok, membuat satu `checkout_sessions`, dan menerbitkan `payment_code = secrets.token_urlsafe(24)` berlaku `PAYMENT_QR_TTL_SECONDS` (60 detik).
2. `GET /keranjang/checkout/{id}/qr` mengembalikan PNG Base64; isi QR adalah `<base>/pesanan/bayar/<payment_code>`.
3. `<base>` ditentukan berurutan: `HOST_LAN_IP` → `hostnet/base.txt` → `hostnet/ip.txt` → `LOCAL_PAYMENT_BASE_URL`. Nilai loopback dan IP internal Docker (`172.16.0.0/12`) ditolak agar QR tidak menunjuk alamat yang tidak bisa dibuka HP.
4. Bila kode kedaluwarsa, endpoint QR dan endpoint refresh menerbitkan kode baru; kode lama tidak dapat dipakai lagi sehingga tidak ada pembayaran ganda.
5. `POST /pesanan/bayar/{payment_code}` menandai seluruh pesanan sesi `sudah_dibayar`, mengosongkan keranjang, dan menutup sesi.

## 10. Keamanan

| Aspek | Implementasi |
|---|---|
| Kata sandi | hash bcrypt (`passlib`), tidak pernah dikembalikan API |
| Token | JWT HS256 berisi `sub`, `type`, `iat`, `exp`; access 15 menit, refresh 7 hari |
| Pembedaan token | klaim `type` (`access` / `refresh`) diperiksa saat refresh |
| Otorisasi | dekorator dependency memeriksa peran (403) dan kepemilikan data |
| Refresh token | disimpan di tabel `refresh_tokens` sehingga dapat dicabut |
| Rahasia | hanya pada `.env`; `.env.example` tanpa nilai nyata |
| Kode QR | token acak 24 byte, sekali pakai, 60 detik |

## 11. Skrip Operasional

| Berkas | Fungsi |
|---|---|
| `app/seed_demo.py` | membuat akun demo dan produk surplus dengan batas konsumsi segar |
| `update_host_ip.py` | menulis IP LAN host ke `hostnet/ip.txt`, atau URL quick tunnel ke `hostnet/base.txt` (`--tunnel`) |
| `tunnel_watch.py` | memantau log container tunnel tiap 10 detik dan memperbarui `hostnet/base.txt` |
| `cek_token_tunnel.py` | memeriksa bentuk `CLOUDFLARE_TUNNEL_TOKEN` tanpa menampilkan isinya |
| `start_demo.bat` | menjalankan stack Docker, seed, dan menampilkan URL untuk demo |

## 12. Tunnel Permanen

```bash
docker compose stop tunnel
docker compose --profile named up -d tunnel-named
curl -s https://habisin.raflipratama.my.id/health
```

Membutuhkan `cloudflared/config.yml` (salin dari `cloudflared/config.example.yml`) dan berkas kredensial tunnel. Keduanya **tidak** di-commit.

## 13. Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| `/health` gagal | container `api` belum sehat | `docker compose logs api`, tunggu healthcheck `db` |
| `401 Invalid token` | access token kedaluwarsa | panggil `/auth/refresh` |
| `403` saat tambah produk | peran bukan penjual | gunakan akun penjual |
| `503` pada endpoint AI | `GEMINI_API_KEY` kosong | isi kunci di `.env`, restart `api` |
| QR tidak bisa dibuka HP | `qr_base` menunjuk `127.0.0.1`/IP Docker | cek `/health`, jalankan `update_host_ip.py` |
| Halaman bayar kedaluwarsa | kode lewat 60 detik | minta QR baru dari aplikasi |
| Port 3307/8000/8081 dipakai | container lain | ubah port di `docker-compose.yml` |

## 14. Progress Pertemuan 9–16

| Pertemuan | Fokus | Hasil |
|---|---|---|
| 9 | Fondasi backend | Docker Compose (db, api, web), skema 9 tabel, konfigurasi environment, endpoint `/health` |
| 10 | Autentikasi & otorisasi | registrasi, login, JWT HS256 + refresh token, bcrypt, pemeriksaan peran dan kepemilikan |
| 11 | Produk & katalog | CRUDS produk, unggah gambar, pencarian `q`, filter jenis, penyembunyian produk kedaluwarsa/stok nol |
| 12 | Keranjang | CRUDS keranjang, validasi stok, total dihitung server dari harga diskon |
| 13 | Checkout & QR | sesi checkout atomik, `SELECT ... FOR UPDATE`, kode QR acak 60 detik, refresh kode, status sesi |
| 14 | Pesanan & struk | riwayat pesanan, sinkronisasi status bayar, pembatalan berbasis status, QR per pesanan, endpoint struk |
| 15 | Ulasan, favorit, laporan | CRUDS ulasan & favorit dengan kepemilikan, ekspor CSV, daftar/detail toko |
| 16 | AI, publikasi, dokumentasi | Habisin AI (chat, saran harga, deskripsi, ringkasan), tunnel permanen Cloudflare, pemisahan repo API, README |

## 15. Progress Mingguan (Weekly Progress)

Progress didokumentasikan dari riwayat commit git pada repositori ini.

### Minggu 1 (24 November 2026)

- [x] `.gitignore`, `.dockerignore`, dan contoh environment (`421c1d5`)
- [x] Docker Compose, Dockerfile, dan konfigurasi Nginx (`a55db86`)
- [x] README arsitektur layanan, kontrak endpoint, dan cara menjalankan (`60a51d3`)

### Minggu 2 (25 - 28 November 2026)

- [x] Bootstrap FastAPI: impor, CORS, folder media, dan registrasi router (`1784f4f`, `ec58e4e`, `803c5b2`)
- [x] Registrasi router auth, produk, pesanan, sosial, laporan, struk, dan AI (`63745f4`, `1d32009`, `9135312`)
- [x] Endpoint health, status layanan, dan inisialisasi basis data (`4931273`, `5418e4c`)
- [x] Router keranjang: struktur, daftar, tambah, ubah, dan hapus (`8657c1d`, `788ba9c`, `fb759b3`, `b82bba2`, `9e83b0e`)
- [x] Checkout atomik, gambar QR, penyegaran kode, dan status sesi (`bb6b3f9`, `28ff0cd`, `66d2e00`)
- [x] Asisten AI: skema permintaan, pembatas peran, dan klien Gemini (`e91f4e6`, `919a17d`, `f3a9b29`)
- [x] Pemanggilan model, prompt RAG n8n, dan endpoint chat (`8bda7a5`, `0781c31`)
- [x] Saran harga, deskripsi produk, ringkasan penjualan, dan pencarian cerdas (`f3a2875`, `1df954f`)
- [x] Tanya produk dan AI isi keranjang (`80ff8be`, `1d80f4b`)
- [x] Dokumentasi kode router AI (`fca97dc`, `14d03c9`, `8bb7128`, `b1105e6`, `f9f3ad7`, `2aa1418`, `9a23a56`, `a76969b`, `2a7a802`, `3e47ab8`)
- [x] Dokumentasi kode router keranjang (`890c485`, `f44ee6b`, `e9babd9`, `ce4686d`, `b622a32`, `cd10bff`, `983043f`, `577f320`)
- [x] Dokumentasi kode bootstrap API (`a8ea3bc`, `de5bad2`, `998723c`, `24bc146`, `834cde9`, `a145622`, `deae9da`)

## 16. Lisensi dan Atribusi

Proyek akademik Mata Kuliah Pengembangan Aplikasi Mobile 2026, Program Studi Teknologi Informasi, Universitas Muhammadiyah Yogyakarta. Hak atas kode sumber berada pada Muhamad Rafli Pratama (20240140003).
