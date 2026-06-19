from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db, now_jst
from ..models import Answer, Question, PointLog, Child, Setting
from ..bonus import get_points_per_clear as get_bonus_points
from ..backup import backup_to_dropbox

router = APIRouter(prefix="/api/children", tags=["answers"])


class AnswerItem(BaseModel):
    question_id: int
    correct: bool


class AnswersSubmit(BaseModel):
    answers: list[AnswerItem]


def _is_cleared(db: Session, child_id: int, question_id: int, current_round: int = 1) -> bool:
    answers = (
        db.query(Answer)
        .filter(Answer.child_id == child_id, Answer.question_id == question_id, Answer.round == current_round)
        .all()
    )
    if not answers:
        return False
    correct = sum(1 for a in answers if a.correct)
    wrong = sum(1 for a in answers if not a.correct)
    return correct > wrong


def _round_for_question(child: Child, q: Question) -> int:
    """問題の言語に応じたラウンド番号を返す"""
    if getattr(q, "language", "en") == "ko":
        return child.round_ko or 1
    return child.round or 1


@router.post("/{child_id}/answers")
def submit_answers(child_id: int, body: AnswersSubmit, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")

    now = now_jst()
    today = now.date()

    # 問題を事前取得し、言語ごとのラウンドを決定
    q_map: dict[int, Question] = {}
    round_map: dict[int, int] = {}
    for item in body.answers:
        q = db.query(Question).get(item.question_id)
        if not q:
            raise HTTPException(400, f"問題ID {item.question_id} が見つかりません")
        q_map[item.question_id] = q
        round_map[item.question_id] = _round_for_question(child, q)

    # Check which questions were cleared BEFORE recording
    was_cleared = {}
    for item in body.answers:
        was_cleared[item.question_id] = _is_cleared(db, child_id, item.question_id, round_map[item.question_id])

    # Record answers
    for item in body.answers:
        db.add(Answer(
            child_id=child_id,
            question_id=item.question_id,
            answered_date=now,
            correct=item.correct,
            round=round_map[item.question_id],
        ))

    db.flush()

    # Check newly cleared
    newly_cleared = []
    for item in body.answers:
        if not was_cleared[item.question_id] and _is_cleared(db, child_id, item.question_id, round_map[item.question_id]):
            newly_cleared.append(q_map[item.question_id])

    # Award points for newly cleared
    if newly_cleared:
        points_per_clear = get_bonus_points(db, child_id)
        total_points = len(newly_cleared) * points_per_clear
        nums = ", ".join(f"問{q.number}" for q in newly_cleared)
        db.add(PointLog(
            child_id=child_id,
            logged_date=today,
            amount=total_points,
            description=f"{nums} クリア",
        ))

    db.commit()
    backup_to_dropbox()

    correct_count = sum(1 for item in body.answers if item.correct)
    earned = total_points if newly_cleared else 0
    return {
        "total": len(body.answers),
        "correct": correct_count,
        "newly_cleared": [{"id": q.id, "unit_number": q.unit_number, "number": q.number} for q in newly_cleared],
        "points_earned": earned,
    }
