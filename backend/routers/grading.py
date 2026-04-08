import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ActiveSession,
    Child,
    Question,
    SessionPhoto,
    GradingBatch,
    Grading,
    Answer,
    PointLog,
    Setting,
)
from ..backup import backup_to_dropbox
from .photos import PHOTO_DIR

router = APIRouter(tags=["grading"])

CLAUDE_MODEL = "claude-sonnet-4-5"


def _guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(ext, "image/jpeg")


def _build_prompt(questions: list[Question]) -> str:
    lines = [
        "あなたは小学生の英語学習を支援する優しい先生です。",
        "添付された画像は、和文英訳の答案をノートに手書きしたものです。",
        "以下の10問程度の問題について、画像から手書きの英文を読み取り、模範解答と比較して採点してください。",
        "",
        "【問題一覧】",
    ]
    for q in questions:
        lines.append(f"- 問{q.number}: 和文「{q.japanese}」 / 模範解答「{q.english}」")
    lines += [
        "",
        "【採点基準】",
        "- 意味が合っていて文法的に許容できれば○。模範解答と語順・単語が多少違っても可。",
        "- スペルミス・冠詞/前置詞抜け・時制違いなど意味に関わる間違いは×。",
        "- 明らかに空欄・未記入の場合は ai_reading を空文字にして×。",
        "",
        "【出力形式】",
        "必ず以下のJSON形式のみで回答してください。前後に説明文を付けないこと。",
        '{"results": [{"number": <問題番号>, "ai_reading": "<読み取った英文>", "correct": <true|false>, "comment": "<小学生向けの短いコメント（日本語、30〜80文字）。○なら褒める、×なら間違いの要点を優しく説明>"}]}',
        "問題一覧の全問について必ず1件ずつ結果を返してください。",
    ]
    return "\n".join(lines)


def _call_claude(questions: list[Question], photo_paths: list[Path]):
    try:
        from anthropic import Anthropic
    except ImportError:
        raise HTTPException(500, "anthropic パッケージがインストールされていません")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY が設定されていません")

    client = Anthropic(api_key=api_key)

    content = []
    for p in photo_paths:
        data = p.read_bytes()
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _guess_media_type(p),
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        })
    content.append({"type": "text", "text": _build_prompt(questions)})

    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    # JSON抽出（余計な文字が混じった場合の保険）
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise HTTPException(500, f"AI応答のパースに失敗しました: {text[:200]}")
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"AI応答のJSON解析失敗: {e}")

    return parsed, msg.usage.input_tokens, msg.usage.output_tokens


@router.post("/api/sessions/{session_id}/grade")
def grade_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ActiveSession).get(session_id)
    if not session:
        raise HTTPException(404, "セッションが見つかりません")

    qids = json.loads(session.question_ids)
    questions = [db.query(Question).get(qid) for qid in qids]
    questions = [q for q in questions if q]
    if not questions:
        raise HTTPException(400, "問題がありません")

    photos = (
        db.query(SessionPhoto)
        .filter(SessionPhoto.session_id == session_id)
        .order_by(SessionPhoto.id)
        .all()
    )
    if not photos:
        raise HTTPException(400, "写真がアップロードされていません")

    photo_paths = [PHOTO_DIR / p.filename for p in photos]
    photo_paths = [p for p in photo_paths if p.exists()]
    if not photo_paths:
        raise HTTPException(400, "写真ファイルが見つかりません")

    parsed, in_tok, out_tok = _call_claude(questions, photo_paths)

    now = datetime.now()
    batch = GradingBatch(
        session_id=session_id,
        child_id=session.child_id,
        created_at=now,
        model=CLAUDE_MODEL,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )
    db.add(batch)
    db.flush()

    results_by_number = {}
    for r in parsed.get("results", []):
        try:
            results_by_number[int(r.get("number"))] = r
        except (TypeError, ValueError):
            continue

    gradings = []
    for q in questions:
        r = results_by_number.get(q.number, {})
        g = Grading(
            batch_id=batch.id,
            question_id=q.id,
            ai_reading=str(r.get("ai_reading", "") or ""),
            ai_correct=bool(r.get("correct", False)),
            ai_comment=str(r.get("comment", "") or ""),
            created_at=now,
        )
        db.add(g)
        gradings.append(g)

    db.commit()
    for g in gradings:
        db.refresh(g)

    return {
        "batch_id": batch.id,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "gradings": [
            {
                "id": g.id,
                "question_id": g.question_id,
                "number": next((q.number for q in questions if q.id == g.question_id), None),
                "unit_number": next((q.unit_number for q in questions if q.id == g.question_id), None),
                "japanese": next((q.japanese for q in questions if q.id == g.question_id), ""),
                "english": next((q.english for q in questions if q.id == g.question_id), ""),
                "ai_reading": g.ai_reading,
                "ai_correct": g.ai_correct,
                "ai_comment": g.ai_comment,
                "status": g.status,
                "feedback": g.feedback,
            }
            for g in gradings
        ],
    }


class FeedbackBody(BaseModel):
    feedback: str  # 'accept' | 'question'


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


@router.post("/api/gradings/{grading_id}/feedback")
def submit_feedback(grading_id: int, body: FeedbackBody, db: Session = Depends(get_db)):
    g = db.query(Grading).get(grading_id)
    if not g:
        raise HTTPException(404, "採点結果が見つかりません")

    if body.feedback not in ("accept", "question"):
        raise HTTPException(400, "feedback は accept か question")

    batch = db.query(GradingBatch).get(g.batch_id)
    if not batch:
        raise HTTPException(500, "バッチが見つかりません")

    g.feedback = body.feedback

    result = {"id": g.id, "status": None, "points_earned": 0, "newly_cleared": False}

    if body.feedback == "accept":
        # 納得 → 現在のAI判定で確定、Answer記録、ポイント付与
        if g.status == "confirmed":
            result["status"] = g.status
            return result

        was_cleared = _is_cleared(db, batch.child_id, g.question_id)
        db.add(Answer(
            child_id=batch.child_id,
            question_id=g.question_id,
            answered_date=datetime.now(),
            correct=g.ai_correct,
        ))
        db.flush()
        now_cleared = _is_cleared(db, batch.child_id, g.question_id)

        g.status = "confirmed"
        g.final_correct = g.ai_correct

        if not was_cleared and now_cleared:
            q = db.query(Question).get(g.question_id)
            ppc_setting = db.query(Setting).get("points_per_clear")
            points_per_clear = int(ppc_setting.value) if ppc_setting else 1
            db.add(PointLog(
                child_id=batch.child_id,
                logged_date=datetime.now().date(),
                amount=points_per_clear,
                description=f"問{q.number} クリア",
            ))
            result["points_earned"] = points_per_clear
            result["newly_cleared"] = True

        db.commit()
        backup_to_dropbox()
    else:
        # 質問がある → Phase 3でチャット実装予定。暫定で保留状態にする
        g.status = "awaiting_parent"
        db.commit()

    result["status"] = g.status
    return result


@router.get("/api/gradings/batch/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(GradingBatch).get(batch_id)
    if not batch:
        raise HTTPException(404, "バッチが見つかりません")
    gradings = db.query(Grading).filter(Grading.batch_id == batch_id).order_by(Grading.id).all()
    return {
        "batch_id": batch.id,
        "created_at": batch.created_at.isoformat(),
        "model": batch.model,
        "input_tokens": batch.input_tokens,
        "output_tokens": batch.output_tokens,
        "gradings": [
            {
                "id": g.id,
                "question_id": g.question_id,
                "ai_reading": g.ai_reading,
                "ai_correct": g.ai_correct,
                "ai_comment": g.ai_comment,
                "status": g.status,
                "feedback": g.feedback,
                "final_correct": g.final_correct,
            }
            for g in gradings
        ],
    }
