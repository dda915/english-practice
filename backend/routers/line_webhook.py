"""LINE Webhook エンドポイント（友だち追加/ブロック検知）"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from ..database import get_db, now_jst
from ..models import LineFriend

router = APIRouter(tags=["line"])


@router.post("/api/line/webhook")
async def line_webhook(request: Request, db: Session = Depends(get_db)):
    """LINE Webhook を受信。follow/unfollow イベントを処理する。"""
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}

    events = body.get("events", [])
    for event in events:
        event_type = event.get("type")
        source = event.get("source", {})
        user_id = source.get("userId")

        if not user_id:
            continue

        if event_type == "follow":
            # 友だち追加
            existing = db.query(LineFriend).filter(LineFriend.line_user_id == user_id).first()
            if existing:
                # 再追加（ブロック解除）の場合は更新
                existing.created_at = now_jst()
            else:
                display_name = None
                # profile 取得は省略（webhook内では取れないことが多いため）
                db.add(LineFriend(
                    line_user_id=user_id,
                    display_name=display_name,
                    created_at=now_jst(),
                ))
            db.commit()

        elif event_type == "unfollow":
            # ブロック/友だち解除
            friend = db.query(LineFriend).filter(LineFriend.line_user_id == user_id).first()
            if friend:
                db.delete(friend)
                db.commit()

    return {"ok": True}
