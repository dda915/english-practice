from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import sqlite3

from .database import engine, Base, DATABASE_URL
from .models import Question, Child, Answer, PointLog, Setting
from .routers import questions, children, answers, points, settings

Base.metadata.create_all(bind=engine)

# マイグレーション: unit_numberカラム追加
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

app = FastAPI(title="和文英訳トレーニング")

app.include_router(questions.router)
app.include_router(children.router)
app.include_router(answers.router)
app.include_router(points.router)
app.include_router(settings.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


# 一時的: ローカルDBをRenderにアップロード用（使用後削除すること）
from fastapi import UploadFile, File

@app.post("/upload-db")
async def upload_db(file: UploadFile = File(...)):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    content = await file.read()
    with open(db_path, "wb") as f:
        f.write(content)
    return {"ok": True, "size": len(content)}






