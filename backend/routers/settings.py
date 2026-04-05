from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    exchange_rate_money: int | None = None
    exchange_rate_phone: int | None = None


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    money = db.query(Setting).get("exchange_rate_money")
    phone = db.query(Setting).get("exchange_rate_phone")
    return {
        "exchange_rate_money": int(money.value) if money else 10,
        "exchange_rate_phone": int(phone.value) if phone else 10,
    }


@router.put("")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    if body.exchange_rate_money is not None:
        s = db.query(Setting).get("exchange_rate_money")
        if s:
            s.value = str(body.exchange_rate_money)
        else:
            db.add(Setting(key="exchange_rate_money", value=str(body.exchange_rate_money)))

    if body.exchange_rate_phone is not None:
        s = db.query(Setting).get("exchange_rate_phone")
        if s:
            s.value = str(body.exchange_rate_phone)
        else:
            db.add(Setting(key="exchange_rate_phone", value=str(body.exchange_rate_phone)))

    db.commit()

    return get_settings(db)
