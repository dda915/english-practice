from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, now_jst
from ..models import Child, Question, Message
from ..push import notify_parents, notify_child
from ..mail import send_notification, send_activity, SITE_URL

router = APIRouter(tags=["messages"])


class MessageCreate(BaseModel):
    body: str
    sender: str  # 'parent' | 'child'
    question_id: int | None = None


def _serialize(m: Message, q: Question | None) -> dict:
    return {
        "id": m.id,
        "child_id": m.child_id,
        "question_id": m.question_id,
        "question_number": q.number if q else None,
        "sender": m.sender,
        "body": m.body,
        "created_at": m.created_at.isoformat(),
        "read_by_parent": m.read_by_parent,
        "read_by_child": m.read_by_child,
    }


@router.get("/api/children/{child_id}/messages")
def list_messages(child_id: int, question_id: int | None = None, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    q = db.query(Message).filter(Message.child_id == child_id)
    if question_id is not None:
        q = q.filter(Message.question_id == question_id)
    msgs = q.order_by(Message.id).all()
    out = []
    for m in msgs:
        qobj = db.query(Question).get(m.question_id) if m.question_id else None
        out.append(_serialize(m, qobj))
    return out


@router.post("/api/children/{child_id}/messages")
def create_message(child_id: int, body: MessageCreate, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    if body.sender not in ("parent", "child"):
        raise HTTPException(400, "sender は parent か child")
    text = (body.body or "").strip()
    if not text:
        raise HTTPException(400, "本文が空です")

    qobj = None
    if body.question_id is not None:
        qobj = db.query(Question).get(body.question_id)
        if not qobj:
            raise HTTPException(404, "問題が見つかりません")

    m = Message(
        child_id=child_id,
        question_id=body.question_id,
        sender=body.sender,
        body=text,
        created_at=now_jst(),
        read_by_parent=(body.sender == "parent"),
        read_by_child=(body.sender == "child"),
    )
    db.add(m)
    db.commit()
    db.refresh(m)

    # 通知: 反対側に送る
    try:
        preview = text[:60] + ("…" if len(text) > 60 else "")
        if body.sender == "child":
            notify_parents({
                "title": f"{child.name}からメッセージ",
                "body": preview,
                "url": "/",
            })
            # メール通知（目立つ件名）
            try:
                q_label = f"（問{qobj.number}について）" if qobj else ""
                html = f"""\
<div style="font-family:sans-serif; max-width:500px; margin:0 auto;">
  <h2 style="color:#c9932b;">💬 {child.name}からメッセージが届きました{q_label}</h2>
  <div style="margin:16px 0; padding:16px; background:#fff7d6; border-radius:8px; border-left:4px solid #c9932b; font-size:15px;">
    {text}
  </div>
  <div style="margin:24px 0; text-align:center;">
    <a href="{SITE_URL}" style="display:inline-block; background:#c9932b; color:#fff; padding:14px 28px; border-radius:8px; text-decoration:none; font-weight:bold;">アプリを開いて返信する</a>
  </div>
</div>"""
                send_notification(
                    subject=f"🚨🚨【返信してください】{child.name}からメッセージ{q_label} 🚨🚨",
                    body=html,
                    html=True,
                )
            except Exception as e:
                print(f"[mail message] 失敗: {e}")
        else:
            notify_child(child_id, {
                "title": "お父さんからメッセージ",
                "body": preview,
                "url": "/",
            })
    except Exception as e:
        print(f"[push message] 失敗: {e}")

    return _serialize(m, qobj)


class MarkReadBody(BaseModel):
    by: str  # 'parent' | 'child'


@router.post("/api/messages/{message_id}/read")
def mark_read(message_id: int, body: MarkReadBody, db: Session = Depends(get_db)):
    m = db.query(Message).get(message_id)
    if not m:
        raise HTTPException(404, "メッセージが見つかりません")
    if body.by == "parent":
        m.read_by_parent = True
    elif body.by == "child":
        m.read_by_child = True
    else:
        raise HTTPException(400, "by は parent か child")
    db.commit()
    return {"ok": True}


@router.post("/api/messages/{message_id}/seen")
def mark_seen(message_id: int, db: Session = Depends(get_db)):
    """子供がメッセージカードを見た時の通知"""
    m = db.query(Message).get(message_id)
    if not m:
        raise HTTPException(404, "メッセージが見つかりません")
    child = db.query(Child).get(m.child_id)
    child_name = child.name if child else "子供"
    preview = m.body[:40] + ("…" if len(m.body) > 40 else "")
    try:
        send_activity(child_name, f"👀 メッセージを確認中", f"元のメッセージ: {m.body}\n\n返信を待っています…")
    except Exception as e:
        print(f"[mail seen] 失敗: {e}")
    return {"ok": True}


@router.post("/api/messages/{message_id}/skipped")
def mark_skipped(message_id: int, db: Session = Depends(get_db)):
    """子供がメッセージをスルーした時の通知"""
    m = db.query(Message).get(message_id)
    if not m:
        raise HTTPException(404, "メッセージが見つかりません")
    child = db.query(Child).get(m.child_id)
    child_name = child.name if child else "子供"
    preview = m.body[:40] + ("…" if len(m.body) > 40 else "")
    try:
        send_activity(child_name, f"😅 メッセージをスルーしました", f"元のメッセージ: {m.body}\n\nあとで返信が来るかもしれません。")
    except Exception as e:
        print(f"[mail skipped] 失敗: {e}")
    return {"ok": True}


@router.post("/api/children/{child_id}/messages/read-all")
def mark_all_read(child_id: int, body: MarkReadBody, db: Session = Depends(get_db)):
    msgs = db.query(Message).filter(Message.child_id == child_id).all()
    for m in msgs:
        if body.by == "parent":
            m.read_by_parent = True
        elif body.by == "child":
            m.read_by_child = True
    db.commit()
    return {"ok": True, "count": len(msgs)}
