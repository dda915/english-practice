from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Setting, Child

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    exchange_rate_money: float | None = None
    exchange_rate_phone: float | None = None
    points_per_clear: float | None = None
    batch_size: int | None = None


class ChildSettingsUpdate(BaseModel):
    exchange_rate_money: float | None = None
    exchange_rate_phone: float | None = None
    points_per_clear: float | None = None
    batch_size: int | None = None


_DEFAULTS = {
    "exchange_rate_money": ("float", 10.0),
    "exchange_rate_phone": ("float", 10.0),
    "points_per_clear": ("float", 2.0),
    "batch_size": ("int", 10),
}


def _get_setting(db: Session, key: str, default: str) -> str:
    s = db.query(Setting).get(key)
    return s.value if s else default


def _set_setting(db: Session, key: str, value: str):
    s = db.query(Setting).get(key)
    if s:
        s.value = value
    else:
        db.add(Setting(key=key, value=value))


def _global(db: Session, key: str):
    kind, default = _DEFAULTS[key]
    raw = _get_setting(db, key, str(default))
    try:
        return float(raw) if kind == "float" else int(float(raw))
    except (ValueError, TypeError):
        return default


def get_child_setting(db: Session, child: Child | None, key: str):
    """child の値を返す。NULL ならグローバル値、それも無ければ既定値。"""
    if child is not None:
        v = getattr(child, key, None)
        if v is not None:
            kind, _ = _DEFAULTS[key]
            return float(v) if kind == "float" else int(v)
    return _global(db, key)


def get_child_setting_by_id(db: Session, child_id: int, key: str):
    child = db.query(Child).get(child_id)
    return get_child_setting(db, child, key)


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return {
        "exchange_rate_money": _global(db, "exchange_rate_money"),
        "exchange_rate_phone": _global(db, "exchange_rate_phone"),
        "points_per_clear": _global(db, "points_per_clear"),
        "batch_size": _global(db, "batch_size"),
    }


@router.put("")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    if body.exchange_rate_money is not None:
        _set_setting(db, "exchange_rate_money", str(body.exchange_rate_money))
    if body.exchange_rate_phone is not None:
        _set_setting(db, "exchange_rate_phone", str(body.exchange_rate_phone))
    if body.points_per_clear is not None:
        _set_setting(db, "points_per_clear", str(body.points_per_clear))
    if body.batch_size is not None:
        _set_setting(db, "batch_size", str(body.batch_size))

    db.commit()
    return get_settings(db)


# ─── 子供ごと設定 ───

child_router = APIRouter(prefix="/api/children", tags=["child-settings"])


def _serialize_child_settings(db: Session, child: Child) -> dict:
    return {
        "child_id": child.id,
        "exchange_rate_money": get_child_setting(db, child, "exchange_rate_money"),
        "exchange_rate_phone": get_child_setting(db, child, "exchange_rate_phone"),
        "points_per_clear": get_child_setting(db, child, "points_per_clear"),
        "batch_size": get_child_setting(db, child, "batch_size"),
    }


@child_router.get("/{child_id}/settings")
def get_child_settings(child_id: int, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    return _serialize_child_settings(db, child)


@child_router.put("/{child_id}/settings")
def update_child_settings(child_id: int, body: ChildSettingsUpdate, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    if body.exchange_rate_money is not None:
        child.exchange_rate_money = body.exchange_rate_money
    if body.exchange_rate_phone is not None:
        child.exchange_rate_phone = body.exchange_rate_phone
    if body.points_per_clear is not None:
        child.points_per_clear = body.points_per_clear
    if body.batch_size is not None:
        child.batch_size = body.batch_size
    db.commit()
    return _serialize_child_settings(db, child)
