from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Child, Question, Message

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
        created_at=datetime.now(),
        read_by_parent=(body.sender == "parent"),
        read_by_child=(body.sender == "child"),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
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
