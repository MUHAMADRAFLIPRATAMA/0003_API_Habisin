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
