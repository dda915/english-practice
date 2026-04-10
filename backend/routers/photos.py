import os
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db, DB_DIR, now_jst
from ..models import ActiveSession, SessionPhoto, Child
from ..mail import send_activity

router = APIRouter(prefix="/api/sessions", tags=["photos"])

PHOTO_DIR = DB_DIR / "photos"
PHOTO_DIR.mkdir(exist_ok=True)

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MAX_BYTES = 15 * 1024 * 1024  # 15MB


def _get_session(db: Session, session_id: int) -> ActiveSession:
    session = db.query(ActiveSession).get(session_id)
    if not session:
        raise HTTPException(404, "セッションが見つかりません")
    return session


@router.post("/{session_id}/photos")
async def upload_photo(session_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _get_session(db, session_id)

    original = file.filename or "photo"
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXT:
        ext = ".jpg"

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "空のファイルです")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "ファイルが大きすぎます（15MB以下）")

    stored = f"{session_id}_{uuid.uuid4().hex}{ext}"
    (PHOTO_DIR / stored).write_bytes(data)

    photo = SessionPhoto(session_id=session_id, filename=stored, created_at=now_jst())
    db.add(photo)
    db.commit()
    db.refresh(photo)

    try:
        session = db.query(ActiveSession).get(session_id)
        child = db.query(Child).get(session.child_id) if session else None
        if child:
            mime_sub = ext.lstrip(".").replace("jpg", "jpeg")
            send_activity(
                child.name,
                "答案写真をアップロード",
                f"{len(data)//1024}KB",
                attachments=[(stored, data, mime_sub)],
            )
    except Exception:
        pass

    return {
        "id": photo.id,
        "session_id": session_id,
        "url": f"/api/sessions/{session_id}/photos/{photo.id}/file",
        "created_at": photo.created_at.isoformat(),
    }


@router.get("/{session_id}/photos")
def list_photos(session_id: int, db: Session = Depends(get_db)):
    _get_session(db, session_id)
    photos = (
        db.query(SessionPhoto)
        .filter(SessionPhoto.session_id == session_id)
        .order_by(SessionPhoto.id)
        .all()
    )
    return [
        {
            "id": p.id,
            "session_id": session_id,
            "url": f"/api/sessions/{session_id}/photos/{p.id}/file",
            "created_at": p.created_at.isoformat(),
        }
        for p in photos
    ]


@router.get("/{session_id}/photos/{photo_id}/file")
def get_photo_file(session_id: int, photo_id: int, db: Session = Depends(get_db)):
    photo = db.query(SessionPhoto).get(photo_id)
    if not photo or photo.session_id != session_id:
        raise HTTPException(404, "写真が見つかりません")
    path = PHOTO_DIR / photo.filename
    if not path.exists():
        raise HTTPException(404, "ファイルが見つかりません")
    return FileResponse(path)


@router.delete("/{session_id}/photos/{photo_id}")
def delete_photo(session_id: int, photo_id: int, db: Session = Depends(get_db)):
    photo = db.query(SessionPhoto).get(photo_id)
    if not photo or photo.session_id != session_id:
        raise HTTPException(404, "写真が見つかりません")
    path = PHOTO_DIR / photo.filename
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
    db.delete(photo)
    db.commit()
    return {"ok": True}
