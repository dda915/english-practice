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
from .routers import questions, children, answers, points, settings, photos, grading, messages, push, parent_devices, line_webhook, bonus

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


def _migrate_bonus_defaults():
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        # points_per_clear を 1 → 2 に更新（初回のみ）
        ppc = conn.execute("SELECT value FROM settings WHERE key = 'points_per_clear'").fetchone()
        if ppc and ppc[0] == "1":
            conn.execute("UPDATE settings SET value = '2' WHERE key = 'points_per_clear'")
        # ボーナス関連デフォルト設定
        for key, val in [("bonus_points", "8"), ("bonus_child_ids", "[3]")]:
            existing = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if not existing:
                conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (bonus defaults): {e}")


# unit_number=999 をギャグ問題（日本語回答）専用枠として使う。
# get_batch は通常10問の末尾にこの枠の未クリア問題を1問混入する。
GAG_UNIT_NUMBER = 999.0
GAG_QUESTIONS = [
    (
        1402,
        "Aさんを殺そうとしたら誤ってBさんを殺してしまいました。何罪が成立しますか？",
        "Bさんに対する殺人罪と、Aさんに対する殺人未遂罪が成立し、両者は観念的競合となる(法定的符合説・数故意犯説)",
    ),
]


def _seed_gag_questions():
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        for num, jp, en in GAG_QUESTIONS:
            row = conn.execute("SELECT id FROM questions WHERE number = ?", (num,)).fetchone()
            if row:
                continue
            conn.execute(
                "INSERT INTO questions (number, unit_number, japanese, english) VALUES (?, ?, ?, ?)",
                (num, GAG_UNIT_NUMBER, jp, en),
            )
            print(f"[seed gag] 問{num} を追加しました")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Seed warning (gag questions): {e}")


def _migrate_child_settings_cols():
    """子供ごとの設定カラム追加 + 既存子供にグローバル値をバックフィル"""
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(children)")]
        added = []
        if "points_per_clear" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN points_per_clear REAL")
            added.append("points_per_clear")
        if "exchange_rate_money" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN exchange_rate_money REAL")
            added.append("exchange_rate_money")
        if "exchange_rate_phone" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN exchange_rate_phone REAL")
            added.append("exchange_rate_phone")
        if "batch_size" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN batch_size INTEGER")
            added.append("batch_size")
        conn.commit()

        # バックフィル: NULLの行に現在のグローバル設定値を入れる
        defaults = {
            "points_per_clear": ("REAL", 2.0),
            "exchange_rate_money": ("REAL", 10.0),
            "exchange_rate_phone": ("REAL", 10.0),
            "batch_size": ("INTEGER", 10),
        }
        for key, (sql_type, fallback) in defaults.items():
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row:
                try:
                    val = float(row[0]) if sql_type == "REAL" else int(float(row[0]))
                except (ValueError, TypeError):
                    val = fallback
            else:
                val = fallback
            conn.execute(f"UPDATE children SET {key} = ? WHERE {key} IS NULL", (val,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (child settings cols): {e}")


def _migrate_round_system():
    """ラウンド制: children.round カラムと answers.round カラムを追加"""
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        # children.round
        cols = [row[1] for row in conn.execute("PRAGMA table_info(children)")]
        if "round" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN round INTEGER NOT NULL DEFAULT 1")
        # answers.round
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "answers" in tables:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(answers)")]
            if "round" not in cols:
                conn.execute("ALTER TABLE answers ADD COLUMN round INTEGER NOT NULL DEFAULT 1")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (round system): {e}")


def _migrate_question_language():
    """韓国語編対応: questions に language カラムを追加し、番号のユニーク制約を
    (language, number) の複合に変更する。既存問題は language='en'。
    SQLite の列レベル UNIQUE は索引削除できないためテーブルを再構築する
    （id を保持するので answers / gradings の参照は維持される）。"""
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "questions" not in tables:
            conn.close()
            return  # 新規DB: create_all がモデル通りに作る
        cols = [row[1] for row in conn.execute("PRAGMA table_info(questions)")]
        if "language" in cols:
            conn.close()
            return  # 移行済み
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            CREATE TABLE questions_new (
                id INTEGER PRIMARY KEY,
                unit_number REAL NOT NULL DEFAULT 0,
                number INTEGER NOT NULL,
                japanese TEXT NOT NULL,
                english TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT 'en',
                CONSTRAINT uq_question_language_number UNIQUE (language, number)
            );
            INSERT INTO questions_new (id, unit_number, number, japanese, english, language)
                SELECT id, unit_number, number, japanese, english, 'en' FROM questions;
            DROP TABLE questions;
            ALTER TABLE questions_new RENAME TO questions;
            CREATE INDEX ix_questions_unit_number ON questions (unit_number);
            CREATE INDEX ix_questions_number ON questions (number);
            CREATE INDEX ix_questions_language ON questions (language);
            """
        )
        conn.commit()
        conn.close()
        print("[migrate] questions テーブルを language 対応に再構築しました")
    except Exception as e:
        print(f"Migration warning (question language): {e}")


def _migrate_child_round_ko():
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(children)")]
        if "round_ko" not in cols:
            conn.execute("ALTER TABLE children ADD COLUMN round_ko INTEGER NOT NULL DEFAULT 1")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning (child round_ko): {e}")


def _migrate_session_language():
    """active_sessions に language を追加し、ユニーク制約を (child_id, language) に変更。
    セッションは一時データなので再構築しても影響は小さい。"""
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "active_sessions" not in tables:
            conn.close()
            return
        cols = [row[1] for row in conn.execute("PRAGMA table_info(active_sessions)")]
        if "language" in cols:
            conn.close()
            return
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            CREATE TABLE active_sessions_new (
                id INTEGER PRIMARY KEY,
                child_id INTEGER NOT NULL,
                question_ids TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT 'en',
                CONSTRAINT uq_session_child_language UNIQUE (child_id, language)
            );
            INSERT INTO active_sessions_new (id, child_id, question_ids, language)
                SELECT id, child_id, question_ids, 'en' FROM active_sessions;
            DROP TABLE active_sessions;
            ALTER TABLE active_sessions_new RENAME TO active_sessions;
            CREATE INDEX ix_active_sessions_child_id ON active_sessions (child_id);
            """
        )
        conn.commit()
        conn.close()
        print("[migrate] active_sessions テーブルを language 対応に再構築しました")
    except Exception as e:
        print(f"Migration warning (session language): {e}")


_migrate_unit_number()
_migrate_grading_cols()
_migrate_child_stage()
_migrate_child_access_code()
_migrate_photo_batch_id()
_migrate_bonus_defaults()
_migrate_round_system()
_migrate_child_settings_cols()
_migrate_question_language()
_migrate_child_round_ko()
_migrate_session_language()
Base.metadata.create_all(bind=engine)
_seed_gag_questions()

app = FastAPI(title="和文英訳トレーニング")

app.include_router(questions.router)
app.include_router(children.router)
app.include_router(answers.router)
app.include_router(points.router)
app.include_router(settings.router)
app.include_router(settings.child_router)
app.include_router(photos.router)
app.include_router(grading.router)
app.include_router(messages.router)
app.include_router(push.router)
app.include_router(parent_devices.router)
app.include_router(line_webhook.router)
app.include_router(bonus.router)

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


def _is_bonus_disabled() -> bool:
    from .database import SessionLocal
    db = SessionLocal()
    try:
        s = db.query(Setting).get("bonus_disabled")
        return bool(s and s.value == "1")
    finally:
        db.close()


async def _bonus_scheduler_loop():
    """毎日6:30/18:00にLINEボーナス通知、21:50に振り返りを送信"""
    from .line_bot import broadcast_line_message
    from .daily_review import send_daily_review
    sent_today = set()
    while True:
        try:
            now = now_jst()
            key_prefix = str(now.date())

            if _is_bonus_disabled():
                sent_today = {k for k in sent_today if k.startswith(key_prefix)}
                await asyncio.sleep(30)
                continue

            if now.hour == 6 and now.minute == 30 and f"{key_prefix}-6:30" not in sent_today:
                sent_today.add(f"{key_prefix}-6:30")
                broadcast_line_message(
                    "🌅 おはよう！朝のボーナスタイム開始！\n"
                    "今から15分間、1問クリアで8ポイントだよ！\n"
                    "急いでPaePaeを開こう！💪"
                )
            elif now.hour == 18 and now.minute == 0 and f"{key_prefix}-18:0" not in sent_today:
                sent_today.add(f"{key_prefix}-18:0")
                broadcast_line_message(
                    "🌆 夕方のボーナスタイム開始！\n"
                    "今から15分間、1問クリアで8ポイントだよ！\n"
                    "PaePaeを開こう！💪"
                )
            elif now.hour == 21 and now.minute == 50 and f"{key_prefix}-21:50" not in sent_today:
                sent_today.add(f"{key_prefix}-21:50")
                send_daily_review()

            # Clean old entries daily
            sent_today = {k for k in sent_today if k.startswith(key_prefix)}
        except Exception as e:
            print(f"[bonus scheduler] {e}")
        await asyncio.sleep(30)


@app.on_event("startup")
async def _start_cleanup():
    asyncio.create_task(_cleanup_loop())
    asyncio.create_task(_bonus_scheduler_loop())






