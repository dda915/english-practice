from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db, now_jst
from ..models import ParentDevice
from ..auth import require_parent, is_parent, password_ok

router = APIRouter(prefix="/api/parent-devices", tags=["parent-devices"])


class RegisterBody(BaseModel):
    device_id: str
    name: str


class CheckBody(BaseModel):
    device_id: str


@router.post("/check")
def check_device(body: CheckBody, db: Session = Depends(get_db)):
    d = db.query(ParentDevice).filter(ParentDevice.device_id == body.device_id).first()
    if d:
        d.last_seen_at = now_jst()
        db.commit()
        return {"registered": True, "id": d.id, "name": d.name}
    return {"registered": False}


class LoginBody(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginBody, request: Request):
    # 合言葉は画面ではなく ここで比べる (画面に合言葉を書いておかないため)
    if not password_ok(body.password, request):
        raise HTTPException(401, "パスワードが違います")
    return {"ok": True}


@router.post("/register")
def register_device(body: RegisterBody, request: Request, db: Session = Depends(get_db)):
    # 登録した端末は 以後 合言葉なしで保護者になれるので 登録そのものに保護者の確かめが要る
    if not is_parent(request, db):
        raise HTTPException(401, "保護者の操作です。保護者モードに切り替えてください")
    name = (body.name or "").strip() or "無名の端末"
    d = db.query(ParentDevice).filter(ParentDevice.device_id == body.device_id).first()
    now = now_jst()
    if d:
        d.name = name
        d.last_seen_at = now
    else:
        d = ParentDevice(
            device_id=body.device_id,
            name=name,
            registered_at=now,
            last_seen_at=now,
        )
        db.add(d)
    db.commit()
    db.refresh(d)
    return {"id": d.id, "name": d.name}


@router.get("", dependencies=[Depends(require_parent)])
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(ParentDevice).order_by(ParentDevice.registered_at.desc()).all()
    return [
        {
            "id": d.id,
            "device_id": d.device_id,
            "name": d.name,
            "registered_at": d.registered_at.isoformat(),
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        }
        for d in devices
    ]


@router.delete("/{device_pk}", dependencies=[Depends(require_parent)])
def delete_device(device_pk: int, db: Session = Depends(get_db)):
    d = db.query(ParentDevice).get(device_pk)
    if not d:
        raise HTTPException(404, "端末が見つかりません")
    db.delete(d)
    db.commit()
    return {"ok": True}
