from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pathlib import Path

import os

JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    """現在時刻をJSTで返す"""
    return datetime.now(JST)

# Render Persistent Disk: /data があればそこに保存、なければローカル
if os.path.isdir("/data"):
    DB_DIR = Path("/data")
else:
    DB_DIR = Path(__file__).resolve().parent.parent / "database"
    DB_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_DIR / 'english.db'}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
