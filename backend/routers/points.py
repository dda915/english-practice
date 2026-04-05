from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import PointLog, Child, Setting, ExchangeRequest
from ..mail import send_exchange_notification
from ..backup import backup_to_dropbox

router = APIRouter(prefix="/api/children", tags=["points"])

JST = timezone(timedelta(hours=9))


class SpendRequest(BaseModel):
    amount: int
    type: str  # "money" or "phone"


def _get_balance(db: Session, child_id: int) -> int:
    logs = db.query(PointLog).filter(PointLog.child_id == child_id).all()
    return sum(l.amount for l in logs)


def _get_pending_points(db: Session, child_id: int) -> int:
    """未処理の申請で予約されているポイント合計"""
    reqs = db.query(ExchangeRequest).filter(
        ExchangeRequest.child_id == child_id,
        ExchangeRequest.fulfilled == False,
    ).all()
    return sum(r.points for r in reqs)


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
    pending = _get_pending_points(db, child_id)

    return {
        "balance": balance,
        "available": balance - pending,
        "pending": pending,
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

    # 残高 - 申請中ポイント = 使用可能ポイント
    balance = _get_balance(db, child_id)
    pending = _get_pending_points(db, child_id)
    available = balance - pending
    if body.amount > available:
        raise HTTPException(400, "ポイントが足りません")

    # Get exchange rates
    money_rate = db.query(Setting).get("exchange_rate_money")
    phone_rate = db.query(Setting).get("exchange_rate_phone")
    money_val = int(money_rate.value) if money_rate else 10
    phone_val = int(phone_rate.value) if phone_rate else 10

    if body.type == "money":
        converted = body.amount * money_val
        type_label = "お金"
        unit = "円"
    elif body.type == "phone":
        converted = body.amount * phone_val
        type_label = "スマホ時間"
        unit = "分"
    else:
        raise HTTPException(400, "typeは 'money' または 'phone' にしてください")

    # 申請だけ作成（ポイントはまだ減らさない）
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
    send_exchange_notification(
        child_name=child.name,
        type_label=type_label,
        converted=converted,
        unit=unit,
        points=body.amount,
        balance=available - body.amount,
        request_id=req.id,
    )

    return {"ok": True, "description": f"{type_label}に交換申請（{converted}{unit}）"}


@router.get("/exchange-requests")
def list_exchange_requests(db: Session = Depends(get_db)):
    """交換リクエスト一覧（処理済みは1時間後に非表示）"""
    now = datetime.now(JST)
    cutoff = now - timedelta(hours=1)

    reqs = (
        db.query(ExchangeRequest)
        .order_by(ExchangeRequest.id.desc())
        .all()
    )

    result = []
    for r in reqs:
        # 処理済みかつ1時間経過 → 表示しない
        if r.fulfilled and r.fulfilled_at:
            fulfilled_time = r.fulfilled_at.replace(tzinfo=JST) if r.fulfilled_at.tzinfo is None else r.fulfilled_at
            if fulfilled_time < cutoff:
                continue

        result.append({
            "id": r.id,
            "child_name": r.child.name,
            "date": r.requested_date.isoformat(),
            "type": r.exchange_type,
            "points": r.points,
            "converted_value": r.converted_value,
            "fulfilled": r.fulfilled,
        })

    return result


@router.put("/exchange-requests/{req_id}/fulfill")
def fulfill_request(req_id: int, db: Session = Depends(get_db)):
    """リクエストを対応済みにする（ポイント減算もここで実行）"""
    req = db.query(ExchangeRequest).get(req_id)
    if not req:
        raise HTTPException(404, "リクエストが見つかりません")
    if req.fulfilled:
        return {"ok": True, "already": True}

    # ポイント減算
    if req.exchange_type == "money":
        desc = f"お金に交換（{req.converted_value}円）"
    else:
        desc = f"スマホ時間に交換（{req.converted_value}分）"

    db.add(PointLog(
        child_id=req.child_id,
        logged_date=date.today(),
        amount=-req.points,
        description=desc,
    ))

    req.fulfilled = True
    req.fulfilled_at = datetime.now(JST)
    db.commit()
    backup_to_dropbox()
    return {"ok": True}


@router.get("/exchange-requests/{req_id}/fulfill")
def fulfill_request_from_email(req_id: int, db: Session = Depends(get_db)):
    """メールのリンクから対応済みにする"""
    from fastapi.responses import HTMLResponse
    req = db.query(ExchangeRequest).get(req_id)
    if not req:
        return HTMLResponse("<h2>リクエストが見つかりません</h2>")

    if req.fulfilled:
        return HTMLResponse(f"""\
<html><body style="font-family:sans-serif; max-width:500px; margin:50px auto; text-align:center;">
<h2 style="color:#666;">処理済みです</h2>
<p>このリクエストは既に対応済みです。</p>
<a href="https://english-practice-5285.onrender.com" style="color:#2d5a27;">サイトに戻る</a>
</body></html>""")

    # ポイント減算
    if req.exchange_type == "money":
        desc = f"お金に交換（{req.converted_value}円）"
    else:
        desc = f"スマホ時間に交換（{req.converted_value}分）"

    db.add(PointLog(
        child_id=req.child_id,
        logged_date=date.today(),
        amount=-req.points,
        description=desc,
    ))

    req.fulfilled = True
    req.fulfilled_at = datetime.now(JST)
    db.commit()
    backup_to_dropbox()

    return HTMLResponse(f"""\
<html><body style="font-family:sans-serif; max-width:500px; margin:50px auto; text-align:center;">
<h2 style="color:#2d5a27;">対応済みにしました</h2>
<p>{req.child.name}: {desc}</p>
<p>{req.points}pt を減算しました。</p>
<a href="https://english-practice-5285.onrender.com" style="color:#2d5a27;">サイトに戻る</a>
</body></html>""")
