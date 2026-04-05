from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import PointLog, Child, Setting

router = APIRouter(prefix="/api/children", tags=["points"])


class SpendRequest(BaseModel):
    amount: int
    type: str  # "money" or "phone"


@router.get("/{child_id}/points")
def get_points(child_id: int, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")

    logs = (
        db.query(PointLog)
        .filter(PointLog.child_id == child_id)
        .order_by(PointLog.id)
        .all()
    )
    balance = sum(l.amount for l in logs)

    return {
        "balance": balance,
        "logs": [
            {
                "id": l.id,
                "date": l.logged_date.isoformat(),
                "amount": l.amount,
                "description": l.description,
            }
            for l in logs
        ],
    }


@router.post("/{child_id}/points/spend")
def spend_points(child_id: int, body: SpendRequest, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")

    if body.amount <= 0:
        raise HTTPException(400, "ポイント数は1以上にしてください")

    # Check balance
    logs = db.query(PointLog).filter(PointLog.child_id == child_id).all()
    balance = sum(l.amount for l in logs)
    if body.amount > balance:
        raise HTTPException(400, "ポイントが足りません")

    # Get exchange rates
    money_rate = db.query(Setting).get("exchange_rate_money")
    phone_rate = db.query(Setting).get("exchange_rate_phone")
    money_val = int(money_rate.value) if money_rate else 10
    phone_val = int(phone_rate.value) if phone_rate else 10

    if body.type == "money":
        converted = body.amount * money_val
        desc = f"お金に交換（{converted}円）"
    elif body.type == "phone":
        converted = body.amount * phone_val
        desc = f"スマホ時間に交換（{converted}分）"
    else:
        raise HTTPException(400, "typeは 'money' または 'phone' にしてください")

    db.add(PointLog(
        child_id=child_id,
        logged_date=date.today(),
        amount=-body.amount,
        description=desc,
    ))
    db.commit()

    new_balance = balance - body.amount
    return {"balance": new_balance, "spent": body.amount, "description": desc}
