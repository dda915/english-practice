from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
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
            created_at=datetime.now(),
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


@router.post("/test")
def test_push(body: TestBody):
    payload = {
        "title": "テスト通知",
        "body": "Web Push が正常に動いています 🎉",
        "url": "/",
    }
    if body.user_type == "parent":
        notify_parents(payload)
    elif body.user_type == "child" and body.child_id:
        notify_child(body.child_id, payload)
    return {"ok": True}
