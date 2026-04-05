from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    exchange_rate_money: int | None = None
    exchange_rate_phone: int | None = None
    points_per_clear: int | None = None
    batch_size: int | None = None


def _get_setting(db: Session, key: str, default: str) -> str:
    s = db.query(Setting).get(key)
    return s.value if s else default


def _set_setting(db: Session, key: str, value: str):
    s = db.query(Setting).get(key)
    if s:
        s.value = value
    else:
        db.add(Setting(key=key, value=value))


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return {
        "exchange_rate_money": int(_get_setting(db, "exchange_rate_money", "10")),
        "exchange_rate_phone": int(_get_setting(db, "exchange_rate_phone", "10")),
        "points_per_clear": int(_get_setting(db, "points_per_clear", "1")),
        "batch_size": int(_get_setting(db, "batch_size", "10")),
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
