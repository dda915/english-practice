import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Child, Answer, Question, PointLog, ActiveSession

router = APIRouter(prefix="/api/children", tags=["children"])


class ChildUpdate(BaseModel):
    name: str


@router.get("")
def list_children(db: Session = Depends(get_db)):
    children = db.query(Child).order_by(Child.id).all()
    return [{"id": c.id, "name": c.name} for c in children]


@router.put("/{child_id}")
def update_child(child_id: int, body: ChildUpdate, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    child.name = body.name
    db.commit()
    return {"id": child.id, "name": child.name}


def _is_cleared(db: Session, child_id: int, question_id: int) -> bool:
    answers = (
        db.query(Answer)
        .filter(Answer.child_id == child_id, Answer.question_id == question_id)
        .all()
    )
    if not answers:
        return False
    correct = sum(1 for a in answers if a.correct)
    wrong = sum(1 for a in answers if not a.correct)
    return correct > wrong


def _get_cleared_set(db: Session, child_id: int) -> set[int]:
    """クリア済み問題IDのセットを一括取得"""
    answers = db.query(Answer).filter(Answer.child_id == child_id).all()
    stats: dict[int, list[int]] = {}  # question_id -> [correct, wrong]
    for a in answers:
        if a.question_id not in stats:
            stats[a.question_id] = [0, 0]
        if a.correct:
            stats[a.question_id][0] += 1
        else:
            stats[a.question_id][1] += 1
    return {qid for qid, (c, w) in stats.items() if c > w}


@router.get("/{child_id}/progress")
def get_progress(child_id: int, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")

    questions = db.query(Question).order_by(Question.number).all()
    answers = db.query(Answer).filter(Answer.child_id == child_id).order_by(Answer.id).all()

    # Group answers by question
    answer_map: dict[int, list] = {}
    for a in answers:
        answer_map.setdefault(a.question_id, []).append(a)

    result = []
    for q in questions:
        q_answers = answer_map.get(q.id, [])
        correct_count = sum(1 for a in q_answers if a.correct)
        wrong_count = sum(1 for a in q_answers if not a.correct)
        total = len(q_answers)
        cleared = correct_count > wrong_count if total > 0 else False
        accuracy = round(correct_count / total * 100) if total > 0 else None

        history = [
            {"date": a.answered_date.isoformat(), "correct": a.correct}
            for a in q_answers
        ]

        result.append({
            "question_id": q.id,
            "number": q.number,
            "japanese": q.japanese,
            "english": q.english,
            "cleared": cleared,
            "accuracy": accuracy,
            "history": history,
        })

    return result


@router.get("/{child_id}/batch")
def get_batch(child_id: int, size: int = 10, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")

    cleared = _get_cleared_set(db, child_id)

    # 既存セッションがあればそれを返す
    session = db.query(ActiveSession).filter(ActiveSession.child_id == child_id).first()
    if session:
        qids = json.loads(session.question_ids)
        remaining = []
        for qid in qids:
            if qid not in cleared:
                q = db.query(Question).get(qid)
                if q:
                    remaining.append(q)
        if remaining:
            return [
                {"id": q.id, "number": q.number, "japanese": q.japanese, "english": q.english}
                for q in remaining
            ]
        # 全部クリア済みならセッション削除して新規作成へ
        db.delete(session)
        db.flush()

    # 新規セッション作成
    questions = db.query(Question).order_by(Question.number).all()
    uncleared = [q for q in questions if q.id not in cleared]
    batch = uncleared[:size]

    if batch:
        qids = [q.id for q in batch]
        db.add(ActiveSession(child_id=child_id, question_ids=json.dumps(qids)))
        db.commit()

    return [
        {"id": q.id, "number": q.number, "japanese": q.japanese, "english": q.english}
        for q in batch
    ]


@router.get("/{child_id}/session")
def get_session(child_id: int, db: Session = Depends(get_db)):
    """現在のセッション情報を返す"""
    session = db.query(ActiveSession).filter(ActiveSession.child_id == child_id).first()
    if not session:
        return {"active": False, "questions": []}

    cleared = _get_cleared_set(db, child_id)
    qids = json.loads(session.question_ids)
    questions = []
    remaining = 0
    for qid in qids:
        q = db.query(Question).get(qid)
        if q:
            is_cleared = qid in cleared
            questions.append({
                "id": q.id, "number": q.number,
                "japanese": q.japanese, "english": q.english,
                "cleared": is_cleared,
            })
            if not is_cleared:
                remaining += 1

    return {"active": True, "total": len(qids), "remaining": remaining, "questions": questions}


@router.delete("/{child_id}/session")
def clear_session(child_id: int, db: Session = Depends(get_db)):
    """セッションを手動でリセット"""
    session = db.query(ActiveSession).filter(ActiveSession.child_id == child_id).first()
    if session:
        db.delete(session)
        db.commit()
    return {"ok": True}
