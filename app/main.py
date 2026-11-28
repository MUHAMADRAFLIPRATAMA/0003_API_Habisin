from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import inspect, text
from .config import payment_base_url
from .database import Base, engine
from .routers import auth, products, orders, ai, social, reports, cart, struk

Base.metadata.create_all(bind=engine)
with engine.begin() as connection:
    columns = {column["name"] for column in inspect(engine).get_columns("products")}
    if "penjual_id" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN penjual_id INTEGER NULL"))
        connection.execute(text("CREATE INDEX ix_products_penjual_id ON products (penjual_id)"))
    if "gambar_url" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN gambar_url VARCHAR(500) NULL"))
    if "batas_konsumsi" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN batas_konsumsi VARCHAR(16) NULL"))
    else:
        connection.execute(text("ALTER TABLE products MODIFY COLUMN batas_konsumsi VARCHAR(16) NULL"))
    if "cara_penyimpanan" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN cara_penyimpanan VARCHAR(20) NOT NULL DEFAULT 'suhu_ruang'"))
    order_columns = {column["name"] for column in inspect(engine).get_columns("orders")}
    if "status_bayar" not in order_columns:
        connection.execute(text("ALTER TABLE orders ADD COLUMN status_bayar VARCHAR(20) NOT NULL DEFAULT 'belum_dibayar'"))
    if "payment_code" not in order_columns:
        connection.execute(text("ALTER TABLE orders ADD COLUMN payment_code VARCHAR(64) NULL UNIQUE"))
