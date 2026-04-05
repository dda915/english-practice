from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Child, Answer, Question, PointLog

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

    questions = db.query(Question).order_by(Question.number).all()
    uncleared = [q for q in questions if not _is_cleared(db, child_id, q.id)]
    batch = uncleared[:size]

    return [
        {"id": q.id, "number": q.number, "japanese": q.japanese, "english": q.english}
        for q in batch
    ]
