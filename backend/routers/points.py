from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import PointLog, Child, Setting, ExchangeRequest
from ..mail import send_notification

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
        type_label = "お金"
        unit = "円"
    elif body.type == "phone":
        converted = body.amount * phone_val
        desc = f"スマホ時間に交換（{converted}分）"
        type_label = "スマホ時間"
        unit = "分"
    else:
        raise HTTPException(400, "typeは 'money' または 'phone' にしてください")

    # ポイント減算
    db.add(PointLog(
        child_id=child_id,
        logged_date=date.today(),
        amount=-body.amount,
        description=desc,
    ))

    # 交換リクエスト作成
    req = ExchangeRequest(
        child_id=child_id,
        requested_date=date.today(),
        exchange_type=body.type,
        points=body.amount,
        converted_value=converted,
        fulfilled=False,
    )
    db.add(req)
    db.commit()

    # メール通知
    send_notification(
        subject=f"【英語学習】{child.name}がポイント交換を申請しました",
        body=(
            f"{child.name}がポイント交換を申請しました。\n\n"
            f"交換内容: {type_label} {converted}{unit}\n"
            f"使用ポイント: {body.amount}pt\n"
            f"残高: {balance - body.amount}pt\n\n"
            f"対応したら管理画面で「対応済み」にしてください。"
        ),
    )

    new_balance = balance - body.amount
    return {"balance": new_balance, "spent": body.amount, "description": desc}


@router.get("/exchange-requests")
def list_exchange_requests(db: Session = Depends(get_db)):
    """全交換リクエスト一覧"""
    reqs = (
        db.query(ExchangeRequest)
        .order_by(ExchangeRequest.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "child_name": r.child.name,
            "date": r.requested_date.isoformat(),
            "type": r.exchange_type,
            "points": r.points,
            "converted_value": r.converted_value,
            "fulfilled": r.fulfilled,
        }
        for r in reqs
    ]


@router.put("/exchange-requests/{req_id}/fulfill")
def fulfill_request(req_id: int, db: Session = Depends(get_db)):
    """リクエストを対応済みにする"""
    req = db.query(ExchangeRequest).get(req_id)
    if not req:
        raise HTTPException(404, "リクエストが見つかりません")
    req.fulfilled = True
    db.commit()
    return {"ok": True}
