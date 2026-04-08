from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import sqlite3

from .database import engine, Base, DATABASE_URL
from .models import Question, Child, Answer, PointLog, Setting
from .routers import questions, children, answers, points, settings, photos, grading

# マイグレーション: unit_numberカラム追加（create_allより前に実行）
def _migrate_unit_number():
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(questions)")]
        if "unit_number" not in cols:
            conn.execute("ALTER TABLE questions ADD COLUMN unit_number REAL NOT NULL DEFAULT 0")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning: {e}")

_migrate_unit_number()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="和文英訳トレーニング")

app.include_router(questions.router)
app.include_router(children.router)
app.include_router(answers.router)
app.include_router(points.router)
app.include_router(settings.router)
app.include_router(photos.router)
app.include_router(grading.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(FRONTEND_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
def serve_sw():
    return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript")


@app.get("/icon-192.png")
def serve_icon_192():
    return FileResponse(FRONTEND_DIR / "icon-192.png", media_type="image/png")


@app.get("/icon-512.png")
def serve_icon_512():
    return FileResponse(FRONTEND_DIR / "icon-512.png", media_type="image/png")


@app.get("/.well-known/assetlinks.json")
def serve_assetlinks():
    return FileResponse(FRONTEND_DIR / "assetlinks.json", media_type="application/json")






