import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Child, Answer, Question, PointLog, ActiveSession, SessionPhoto, Grading, GradingBatch, ChatMessage, Message, Setting
from ..mail import send_activity
from .photos import PHOTO_DIR

router = APIRouter(prefix="/api/children", tags=["children"])


class ChildUpdate(BaseModel):
    name: str


@router.get("")
def list_children(db: Session = Depends(get_db)):
    children = db.query(Child).order_by(Child.id).all()
    return [{"id": c.id, "name": c.name, "stage": c.stage or 1} for c in children]


@router.put("/{child_id}")
def update_child(child_id: int, body: ChildUpdate, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    child.name = body.name
    db.commit()
    return {"id": child.id, "name": child.name}


def _get_stage(db: Session, child_id: int) -> int:
    child = db.query(Child).get(child_id)
    return child.stage if child and child.stage else 1


def _is_cleared(db: Session, child_id: int, question_id: int, stage: int | None = None) -> bool:
    if stage is None:
        stage = _get_stage(db, child_id)
    answers = (
        db.query(Answer)
        .filter(Answer.child_id == child_id, Answer.question_id == question_id)
        .all()
    )
    if not answers:
        return False
    correct = sum(1 for a in answers if a.correct)
    wrong = sum(1 for a in answers if not a.correct)
    return correct > wrong + (stage - 1)


def _get_cleared_set(db: Session, child_id: int, stage: int | None = None) -> set[int]:
    """クリア済み問題IDのセットを一括取得"""
    if stage is None:
        stage = _get_stage(db, child_id)
    answers = db.query(Answer).filter(Answer.child_id == child_id).all()
    stats: dict[int, list[int]] = {}  # question_id -> [correct, wrong]
    for a in answers:
        if a.question_id not in stats:
            stats[a.question_id] = [0, 0]
        if a.correct:
            stats[a.question_id][0] += 1
        else:
            stats[a.question_id][1] += 1
    return {qid for qid, (c, w) in stats.items() if c > w + (stage - 1)}


def _annotate_history(q_answers, points_per_clear, stage: int = 1):
    """各解答に cleared_by_this / points_earned を付与"""
    history = []
    c = 0
    w = 0
    clear_count = 0  # 何回クリアしたか
    was_cleared_at_stage = {s: False for s in range(1, stage + 1)}
    for a in q_answers:
        if a.correct:
            c += 1
        else:
            w += 1
        # 現在のステージでクリアしているか
        is_cleared = c > w + (stage - 1)
        newly = is_cleared and not was_cleared_at_stage.get(stage, False)
        history.append({
            "date": a.answered_date.isoformat(),
            "correct": a.correct,
            "cleared_after": is_cleared,
            "cleared_by_this": newly,
            "points_earned": points_per_clear if newly else 0,
            "correct_so_far": c,
            "wrong_so_far": w,
        })
        if newly:
            was_cleared_at_stage[stage] = True
    return history


def _get_points_per_clear(db: Session) -> int:
    s = db.query(Setting).get("points_per_clear")
    try:
        return int(s.value) if s else 1
    except Exception:
        return 1


@router.get("/{child_id}/progress")
def get_progress(child_id: int, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")

    stage = _get_stage(db, child_id)
    questions = db.query(Question).order_by(Question.unit_number, Question.number).all()
    answers = db.query(Answer).filter(Answer.child_id == child_id).order_by(Answer.id).all()
    ppc = _get_points_per_clear(db)

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
        cleared = correct_count > wrong_count + (stage - 1) if total > 0 else False
        accuracy = round(correct_count / total * 100) if total > 0 else None

        history = _annotate_history(q_answers, ppc, stage)

        result.append({
            "question_id": q.id,
            "unit_number": q.unit_number,
            "number": q.number,
            "japanese": q.japanese,
            "english": q.english,
            "cleared": cleared,
            "accuracy": accuracy,
            "history": history,
        })

    return result


def _session_response(session: ActiveSession, questions: list[Question]):
    return {
        "session_id": session.id,
        "questions": [
            {"id": q.id, "unit_number": q.unit_number, "number": q.number, "japanese": q.japanese, "english": q.english}
            for q in questions
        ],
    }


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
            return _session_response(session, remaining)
        # 全部クリア済みならセッション削除して新規作成へ
        db.delete(session)
        db.flush()

    # 新規セッション作成
    questions = db.query(Question).order_by(Question.unit_number, Question.number).all()
    uncleared = [q for q in questions if q.id not in cleared]
    batch = uncleared[:size]

    if batch:
        qids = [q.id for q in batch]
        new_session = ActiveSession(child_id=child_id, question_ids=json.dumps(qids))
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        try:
            nums = ", ".join(f"問{q.number}" for q in batch)
            send_activity(child.name, "出題を開始", f"{len(batch)}問: {nums}")
        except Exception:
            pass
        return _session_response(new_session, batch)

    return {"session_id": None, "questions": []}


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
                "id": q.id, "unit_number": q.unit_number, "number": q.number,
                "japanese": q.japanese, "english": q.english,
                "cleared": is_cleared,
            })
            if not is_cleared:
                remaining += 1

    return {"active": True, "session_id": session.id, "total": len(qids), "remaining": remaining, "questions": questions}


@router.get("/{child_id}/questions/{question_id}/detail")
def get_question_detail(child_id: int, question_id: int, db: Session = Depends(get_db)):
    """問題詳細画面：解答履歴・採点AIコメント・AIチャット・メッセージを集約"""
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    q = db.query(Question).get(question_id)
    if not q:
        raise HTTPException(404, "問題が見つかりません")

    answers = (
        db.query(Answer)
        .filter(Answer.child_id == child_id, Answer.question_id == question_id)
        .order_by(Answer.id)
        .all()
    )
    history = _annotate_history(answers, _get_points_per_clear(db))

    # この子供のこの問題に対する全 grading（AIコメント＋チャット履歴）
    gradings = (
        db.query(Grading)
        .join(GradingBatch, Grading.batch_id == GradingBatch.id)
        .filter(GradingBatch.child_id == child_id, Grading.question_id == question_id)
        .order_by(Grading.id)
        .all()
    )
    grading_list = []
    for g in gradings:
        chat_msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.grading_id == g.id)
            .order_by(ChatMessage.id)
            .all()
        )
        grading_list.append({
            "id": g.id,
            "created_at": g.created_at.isoformat(),
            "ai_reading": g.ai_reading,
            "ai_correct": g.ai_correct,
            "ai_comment": g.ai_comment,
            "status": g.status,
            "final_correct": g.final_correct,
            "parent_comment": g.parent_comment or "",
            "chat": [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in chat_msgs],
        })

    msgs = (
        db.query(Message)
        .filter(Message.child_id == child_id, Message.question_id == question_id)
        .order_by(Message.id)
        .all()
    )
    message_list = [
        {
            "id": m.id,
            "sender": m.sender,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
            "read_by_parent": m.read_by_parent,
            "read_by_child": m.read_by_child,
        }
        for m in msgs
    ]

    return {
        "question": {
            "id": q.id,
            "number": q.number,
            "unit_number": q.unit_number,
            "japanese": q.japanese,
            "english": q.english,
        },
        "history": history,
        "gradings": grading_list,
        "messages": message_list,
    }


@router.delete("/{child_id}/session")
def clear_session(child_id: int, db: Session = Depends(get_db)):
    """セッションを手動でリセット"""
    session = db.query(ActiveSession).filter(ActiveSession.child_id == child_id).first()
    if session:
        # GradingBatch が紐づいていれば写真は保持（レビューページで必要）
        has_batch = db.query(GradingBatch).filter(GradingBatch.session_id == session.id).first()
        if not has_batch:
            photos = db.query(SessionPhoto).filter(SessionPhoto.session_id == session.id).all()
            for p in photos:
                try:
                    fp = PHOTO_DIR / p.filename
                    if fp.exists():
                        fp.unlink()
                except Exception:
                    pass
                db.delete(p)
        db.delete(session)
        db.commit()
    return {"ok": True}


# ─── ステージ変更 ───


class StageBody(BaseModel):
    stage: int


@router.put("/{child_id}/stage")
def update_stage(child_id: int, body: StageBody, db: Session = Depends(get_db)):
    """子供のステージを変更"""
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    if body.stage < 1:
        raise HTTPException(400, "ステージは1以上")
    child.stage = body.stage
    db.commit()
    return {"id": child.id, "name": child.name, "stage": child.stage}
