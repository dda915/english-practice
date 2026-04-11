from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, now_jst
from ..models import PushSubscription
from ..push import get_public_key, notify_parents, notify_child

router = APIRouter(prefix="/api/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeBody(BaseModel):
    endpoint: str
    keys: SubscriptionKeys
    user_type: str  # 'parent' | 'child'
    child_id: int | None = None


@router.get("/public-key")
def public_key():
    return {"public_key": get_public_key()}


@router.post("/subscribe")
def subscribe(body: SubscribeBody, db: Session = Depends(get_db)):
    if body.user_type not in ("parent", "child"):
        raise HTTPException(400, "user_type は parent か child")
    existing = db.query(PushSubscription).filter(PushSubscription.endpoint == body.endpoint).first()
    if existing:
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.user_type = body.user_type
        existing.child_id = body.child_id
    else:
        db.add(PushSubscription(
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_type=body.user_type,
            child_id=body.child_id,
            created_at=now_jst(),
        ))
    db.commit()
    return {"ok": True}


class UnsubscribeBody(BaseModel):
    endpoint: str


@router.post("/unsubscribe")
def unsubscribe(body: UnsubscribeBody, db: Session = Depends(get_db)):
    obj = db.query(PushSubscription).filter(PushSubscription.endpoint == body.endpoint).first()
    if obj:
        db.delete(obj)
        db.commit()
    return {"ok": True}


class TestBody(BaseModel):
    user_type: str
    child_id: int | None = None


@router.get("/subscriptions")
def list_subscriptions(db: Session = Depends(get_db)):
    subs = db.query(PushSubscription).all()
    return [{"id": s.id, "user_type": s.user_type, "child_id": s.child_id, "endpoint": s.endpoint[:80] + "..."} for s in subs]


@router.get("/debug")
def debug_push():
    """VAPID設定の診断"""
    import os
    from ..push import _get_private_key
    pk = _get_private_key()
    raw = os.environ.get("VAPID_PRIVATE_KEY", "")
    return {
        "public_key_set": bool(os.environ.get("VAPID_PUBLIC_KEY")),
        "private_key_set": bool(raw),
        "private_key_length": len(raw),
        "private_key_has_begin": "BEGIN" in raw,
        "private_key_has_newlines": "\n" in raw,
        "private_key_preview": raw[:30] + "..." if raw else "(empty)",
        "processed_key_preview": (pk[:30] + "...") if pk else "(None)",
        "subject": os.environ.get("VAPID_SUBJECT", "(not set)"),
    }


@router.post("/test")
def test_push(body: TestBody, db: Session = Depends(get_db)):
    payload = {
        "title": "テスト通知",
        "body": "Web Push が正常に動いています 🎉",
        "url": "/",
    }
    from ..push import send_to_subscription
    if body.user_type == "parent":
        subs = db.query(PushSubscription).filter(PushSubscription.user_type == "parent").all()
    elif body.user_type == "child" and body.child_id:
        subs = db.query(PushSubscription).filter(PushSubscription.user_type == "child", PushSubscription.child_id == body.child_id).all()
    else:
        subs = []
    results = []
    for s in subs:
        ok = send_to_subscription(s, payload)
        results.append({"endpoint": s.endpoint[:60], "success": ok})
    return {"ok": True, "subscriptions_count": len(subs), "results": results}
