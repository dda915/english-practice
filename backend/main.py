import asyncio
import os
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import sqlite3

from .database import engine, Base, DATABASE_URL, now_jst
from .models import Question, Child, Answer, PointLog, Setting
from .routers import questions, children, answers, points, settings, photos, grading, messages, push, parent_devices

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

def _migrate_grading_cols():
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "gradings" in tables:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(gradings)")]
            if "parent_comment" not in cols:
                conn.execute("ALTER TABLE gradings ADD COLUMN parent_comment TEXT")
            if "seen_by_child" not in cols:
                conn.execute("ALTER TABLE gradings ADD COLUMN seen_by_child INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (gradings): {e}")


def _migrate_child_stage():
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(children)")]
        if "stage" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN stage INTEGER NOT NULL DEFAULT 1")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (child stage): {e}")

def _migrate_child_access_code():
    import secrets
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(children)")]
        if "access_code" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN access_code TEXT")
            conn.commit()
        # 未設定の子供にコードを発行
        rows = conn.execute("SELECT id FROM children WHERE access_code IS NULL").fetchall()
        for (cid,) in rows:
            code = secrets.token_urlsafe(8)
            conn.execute("UPDATE children SET access_code = ? WHERE id = ?", (code, cid))
        if rows:
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (access_code): {e}")

def _migrate_photo_batch_id():
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "session_photos" in tables:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(session_photos)")]
            if "batch_id" not in cols:
                conn.execute("ALTER TABLE session_photos ADD COLUMN batch_id INTEGER")
                conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (photo batch_id): {e}")

_migrate_unit_number()
_migrate_grading_cols()
_migrate_child_stage()
_migrate_child_access_code()
_migrate_photo_batch_id()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="和文英訳トレーニング")

app.include_router(questions.router)
app.include_router(children.router)
app.include_router(answers.router)
app.include_router(points.router)
app.include_router(settings.router)
app.include_router(photos.router)
app.include_router(grading.router)
app.include_router(messages.router)
app.include_router(push.router)
app.include_router(parent_devices.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


APP_VERSION = os.environ.get("RENDER_GIT_COMMIT") or now_jst().strftime("%Y%m%d%H%M%S")


@app.get("/api/version")
def get_version():
    return {"version": APP_VERSION}


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


# ─── 古い答案写真の自動削除 (7日以上前) ───
PHOTO_RETENTION_DAYS = 7


def _cleanup_old_photos():
    from .database import SessionLocal, DB_DIR
    from .models import SessionPhoto

    photo_dir = DB_DIR / "photos"
    cutoff = now_jst() - timedelta(days=PHOTO_RETENTION_DAYS)
    db = SessionLocal()
    try:
        old = db.query(SessionPhoto).filter(SessionPhoto.created_at < cutoff).all()
        n = 0
        for p in old:
            try:
                fp = photo_dir / p.filename
                if fp.exists():
                    fp.unlink()
            except Exception as e:
                print(f"[cleanup] ファイル削除失敗 {p.filename}: {e}")
            db.delete(p)
            n += 1
        db.commit()
        if n:
            print(f"[cleanup] {n}枚の古い写真を削除しました (>{PHOTO_RETENTION_DAYS}日)")
    except Exception as e:
        print(f"[cleanup] エラー: {e}")
    finally:
        db.close()


async def _cleanup_loop():
    while True:
        try:
            _cleanup_old_photos()
        except Exception as e:
            print(f"[cleanup loop] {e}")
        await asyncio.sleep(24 * 60 * 60)  # 24時間


@app.on_event("startup")
async def _start_cleanup():
    asyncio.create_task(_cleanup_loop())






