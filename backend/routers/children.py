import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Child, Answer, Question, PointLog, ActiveSession, SessionPhoto, Grading, GradingBatch, ChatMessage, Message, Setting
from ..mail import send_activity
from .photos import PHOTO_DIR
from .settings import get_child_setting, get_child_setting_by_id

router = APIRouter(prefix="/api/children", tags=["children"])

# ギャグ問題（日本語回答）専用の unit_number。get_batch は通常バッチの末尾に1問混入する。
GAG_UNIT_NUMBER = 999.0


class ChildUpdate(BaseModel):
    name: str


@router.get("")
def list_children(db: Session = Depends(get_db)):
    children = db.query(Child).order_by(Child.id).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "round": c.round or 1,
            "round_ko": c.round_ko or 1,
            "access_code": c.access_code,
            "points_per_clear": get_child_setting(db, c, "points_per_clear"),
            "exchange_rate_money": get_child_setting(db, c, "exchange_rate_money"),
            "exchange_rate_phone": get_child_setting(db, c, "exchange_rate_phone"),
            "batch_size": get_child_setting(db, c, "batch_size"),
        }
        for c in children
    ]


@router.get("/by-code/{code}")
def get_child_by_code(code: str, db: Session = Depends(get_db)):
    child = db.query(Child).filter(Child.access_code == code).first()
    if not child:
        raise HTTPException(404, "無効なコードです")
    return {"id": child.id, "name": child.name, "round": child.round or 1, "round_ko": child.round_ko or 1}


@router.post("")
def add_child(body: ChildUpdate, db: Session = Depends(get_db)):
    import secrets
    from .settings import _global
    child = Child(
        name=body.name,
        round=1,
        access_code=secrets.token_urlsafe(8),
        points_per_clear=_global(db, "points_per_clear"),
        exchange_rate_money=_global(db, "exchange_rate_money"),
        exchange_rate_phone=_global(db, "exchange_rate_phone"),
        batch_size=_global(db, "batch_size"),
    )
    db.add(child)
    db.commit()
    return {"id": child.id, "name": child.name, "round": child.round or 1, "access_code": child.access_code}


@router.put("/{child_id}")
def update_child(child_id: int, body: ChildUpdate, db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    child.name = body.name
    db.commit()
    return {"id": child.id, "name": child.name}


def _norm_lang(language: str | None) -> str:
    return "ko" if language == "ko" else "en"


def _get_round(db: Session, child_id: int, language: str = "en") -> int:
    child = db.query(Child).get(child_id)
    if not child:
        return 1
    if _norm_lang(language) == "ko":
        return child.round_ko if child.round_ko else 1
    return child.round if child.round else 1


def _is_cleared(db: Session, child_id: int, question_id: int, current_round: int | None = None) -> bool:
    if current_round is None:
        current_round = _get_round(db, child_id)
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


def _get_cleared_set(db: Session, child_id: int, language: str = "en", current_round: int | None = None) -> set[int]:
    """クリア済み問題IDのセットを一括取得（指定言語・現在のラウンドの解答のみ）"""
    lang = _norm_lang(language)
    if current_round is None:
        current_round = _get_round(db, child_id, lang)
    answers = (
        db.query(Answer)
        .join(Question, Answer.question_id == Question.id)
        .filter(Answer.child_id == child_id, Answer.round == current_round, Question.language == lang)
        .all()
    )
    stats: dict[int, list[int]] = {}  # question_id -> [correct, wrong]
    for a in answers:
        if a.question_id not in stats:
            stats[a.question_id] = [0, 0]
        if a.correct:
            stats[a.question_id][0] += 1
        else:
            stats[a.question_id][1] += 1
    return {qid for qid, (c, w) in stats.items() if c > w}


def _get_awaiting_parent_set(db: Session, child_id: int, language: str = "en") -> set[int]:
    """不服申立中（awaiting_parent）の問題IDセットを取得（指定言語のみ）"""
    from ..models import Grading, GradingBatch
    lang = _norm_lang(language)
    rows = (
        db.query(Grading.question_id)
        .join(GradingBatch, Grading.batch_id == GradingBatch.id)
        .join(Question, Grading.question_id == Question.id)
        .filter(GradingBatch.child_id == child_id, Grading.status == "awaiting_parent", Question.language == lang)
        .all()
    )
    return {r[0] for r in rows}


def _annotate_history(q_answers, points_per_clear, current_round: int = 1):
    """各解答に cleared_by_this / points_earned を付与（ラウンドごとに集計）"""
    history = []
    # ラウンドごとの正解/不正解を追跡
    round_stats: dict[int, list[int]] = {}  # round -> [correct, wrong]
    round_cleared: dict[int, bool] = {}  # round -> already_cleared
    for a in q_answers:
        r = a.round if hasattr(a, 'round') and a.round else 1
        if r not in round_stats:
            round_stats[r] = [0, 0]
            round_cleared[r] = False
        if a.correct:
            round_stats[r][0] += 1
        else:
            round_stats[r][1] += 1
        c, w = round_stats[r]
        is_cleared = c > w
        newly = is_cleared and not round_cleared[r]
        history.append({
            "date": a.answered_date.isoformat(),
            "correct": a.correct,
            "round": r,
            "cleared_after": is_cleared,
            "cleared_by_this": newly,
            "points_earned": points_per_clear if newly else 0,
            "correct_so_far": c,
            "wrong_so_far": w,
        })
        if newly:
            round_cleared[r] = True
    return history


def _get_points_per_clear(db: Session, child_id: int | None = None) -> float:
    if child_id is not None:
        return float(get_child_setting_by_id(db, child_id, "points_per_clear"))
    s = db.query(Setting).get("points_per_clear")
    try:
        return float(s.value) if s else 2
    except Exception:
        return 2


def _count_clears(q_answers) -> int:
    """この問題が全ラウンド通じて何回クリアされたかを数える"""
    round_stats: dict[int, list[int]] = {}
    round_cleared: dict[int, bool] = {}
    for a in q_answers:
        r = a.round if hasattr(a, 'round') and a.round else 1
        if r not in round_stats:
            round_stats[r] = [0, 0]
            round_cleared[r] = False
        if a.correct:
            round_stats[r][0] += 1
        else:
            round_stats[r][1] += 1
        c, w = round_stats[r]
        if c > w and not round_cleared[r]:
            round_cleared[r] = True
    return sum(1 for v in round_cleared.values() if v)


@router.get("/{child_id}/progress")
def get_progress(child_id: int, language: str = "en", db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")

    lang = _norm_lang(language)
    current_round = _get_round(db, child_id, lang)
    questions = db.query(Question).filter(Question.language == lang).order_by(Question.unit_number, Question.number).all()
    answers = db.query(Answer).filter(Answer.child_id == child_id).order_by(Answer.id).all()
    ppc = _get_points_per_clear(db, child_id)

    # Group answers by question
    answer_map: dict[int, list] = {}
    for a in answers:
        answer_map.setdefault(a.question_id, []).append(a)

    result = []
    for q in questions:
        q_answers = answer_map.get(q.id, [])
        # クリア判定は現在のラウンドの解答のみ
        current_round_answers = [a for a in q_answers if (a.round or 1) == current_round]
        correct_count = sum(1 for a in current_round_answers if a.correct)
        wrong_count = sum(1 for a in current_round_answers if not a.correct)
        total_current = len(current_round_answers)
        cleared = correct_count > wrong_count if total_current > 0 else False
        # 正答率は全ラウンドの合計
        total_all = len(q_answers)
        accuracy = round(sum(1 for a in q_answers if a.correct) / total_all * 100) if total_all > 0 else None
        # クリア回数（過去の全ラウンドで何回クリアしたか）
        clear_count = _count_clears(q_answers)

        history = _annotate_history(q_answers, ppc, current_round)

        result.append({
            "question_id": q.id,
            "unit_number": q.unit_number,
            "number": q.number,
            "japanese": q.japanese,
            "english": q.english,
            "cleared": cleared,
            "clear_count": clear_count,
            "accuracy": accuracy,
            "history": history,
        })

    return result


def _session_response(session: ActiveSession, questions: list[Question], resumed: bool = False):
    return {
        "session_id": session.id,
        "resumed": resumed,
        "questions": [
            {"id": q.id, "unit_number": q.unit_number, "number": q.number, "japanese": q.japanese, "english": q.english}
            for q in questions
        ],
    }


@router.get("/{child_id}/batch")
def get_batch(child_id: int, size: int | None = None, language: str = "en", db: Session = Depends(get_db)):
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    if size is None:
        size = int(get_child_setting(db, child, "batch_size"))

    lang = _norm_lang(language)
    cleared = _get_cleared_set(db, child_id, lang)
    awaiting = _get_awaiting_parent_set(db, child_id, lang)
    exclude = cleared | awaiting

    # 既存セッションがあればそれを返す
    session = (
        db.query(ActiveSession)
        .filter(ActiveSession.child_id == child_id, ActiveSession.language == lang)
        .first()
    )
    if session:
        qids = json.loads(session.question_ids)
        remaining = []
        for qid in qids:
            if qid not in exclude:
                q = db.query(Question).get(qid)
                if q:
                    remaining.append(q)
        if remaining:
            return _session_response(session, remaining, resumed=True)
        # 全部クリア済みならセッション削除して新規作成へ
        old_photos = db.query(SessionPhoto).filter(SessionPhoto.session_id == session.id).all()
        for p in old_photos:
            if p.batch_id:
                p.session_id = -1
            else:
                try:
                    fp = PHOTO_DIR / p.filename
                    if fp.exists():
                        fp.unlink()
                except Exception:
                    pass
                db.delete(p)
        db.delete(session)
        db.flush()

    # 新規セッション作成
    questions = db.query(Question).filter(Question.language == lang).order_by(Question.unit_number, Question.number).all()
    uncleared_normal = [q for q in questions if q.id not in exclude and q.unit_number != GAG_UNIT_NUMBER]
    batch = uncleared_normal[:size]

    if batch:
        qids = [q.id for q in batch]
        new_session = ActiveSession(child_id=child_id, question_ids=json.dumps(qids), language=lang)
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
def get_session(child_id: int, language: str = "en", db: Session = Depends(get_db)):
    """現在のセッション情報を返す"""
    lang = _norm_lang(language)
    session = (
        db.query(ActiveSession)
        .filter(ActiveSession.child_id == child_id, ActiveSession.language == lang)
        .first()
    )
    if not session:
        return {"active": False, "questions": []}

    cleared = _get_cleared_set(db, child_id, lang)
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
    current_round = _get_round(db, child_id, q.language)
    history = _annotate_history(answers, _get_points_per_clear(db, child_id), current_round)

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
            "language": q.language,
        },
        "history": history,
        "gradings": grading_list,
        "messages": message_list,
    }


@router.delete("/{child_id}/session")
def clear_session(child_id: int, language: str = "en", db: Session = Depends(get_db)):
    """セッションを手動でリセット"""
    lang = _norm_lang(language)
    session = (
        db.query(ActiveSession)
        .filter(ActiveSession.child_id == child_id, ActiveSession.language == lang)
        .first()
    )
    if session:
        photos = db.query(SessionPhoto).filter(SessionPhoto.session_id == session.id).all()
        for p in photos:
            if p.batch_id:
                # バッチ紐づき済み → session_idだけクリア（レビューページで参照可能）
                p.session_id = -1
            else:
                # 未採点の写真 → ファイルごと削除
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


# ─── ラウンド管理 ───


class SetRoundBody(BaseModel):
    round: int


@router.post("/{child_id}/new-round")
def start_new_round(child_id: int, language: str = "en", db: Session = Depends(get_db)):
    """復習開始: ラウンドを1つ進める（全問が未クリア状態に戻る）"""
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    lang = _norm_lang(language)
    if lang == "ko":
        child.round_ko = (child.round_ko or 1) + 1
        new_round = child.round_ko
    else:
        child.round = (child.round or 1) + 1
        new_round = child.round
    # 進行中のセッションがあれば削除（該当言語のみ）
    session = (
        db.query(ActiveSession)
        .filter(ActiveSession.child_id == child_id, ActiveSession.language == lang)
        .first()
    )
    if session:
        db.delete(session)
    db.commit()
    return {"id": child.id, "name": child.name, "round": new_round, "language": lang}


@router.put("/{child_id}/round")
def set_round(child_id: int, body: SetRoundBody, language: str = "en", db: Session = Depends(get_db)):
    """ラウンドを直接指定（管理用）"""
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(404, "子供が見つかりません")
    if body.round < 1:
        raise HTTPException(400, "ラウンドは1以上")
    lang = _norm_lang(language)
    if lang == "ko":
        child.round_ko = body.round
        new_round = child.round_ko
    else:
        child.round = body.round
        new_round = child.round
    session = (
        db.query(ActiveSession)
        .filter(ActiveSession.child_id == child_id, ActiveSession.language == lang)
        .first()
    )
    if session:
        db.delete(session)
    db.commit()
    return {"id": child.id, "name": child.name, "round": new_round, "language": lang}


@router.get("/timeline")
def get_timeline(limit: int = 100, db: Session = Depends(get_db)):
    """全子供の最近の解答を時系列で返す（ポイント獲得情報付き）"""
    # 最近の解答を取得
    recent = (
        db.query(Answer, Question, Child)
        .join(Question, Answer.question_id == Question.id)
        .join(Child, Answer.child_id == Child.id)
        .order_by(Answer.answered_date.desc())
        .limit(limit)
        .all()
    )

    # クリア判定のため、子供ごとのラウンドと全解答を取得
    children = {c.id: c for c in db.query(Child).all()}
    ppc_by_child = {cid: float(get_child_setting(db, c, "points_per_clear")) for cid, c in children.items()}

    # 子供×問題×ラウンドご��の累計を事前計算（クリア判定用）
    all_answers = (
        db.query(Answer)
        .order_by(Answer.answered_date)
        .all()
    )
    # {(child_id, question_id, round): [(correct, answer_id), ...]}
    answer_seq: dict[tuple[int, int, int], list] = {}
    for a in all_answers:
        key = (a.child_id, a.question_id, a.round or 1)
        if key not in answer_seq:
            answer_seq[key] = []
        answer_seq[key].append((a.correct, a.id))

    # 各解答がクリアを引き��こしたか判定
    clear_answers: set[int] = set()  # answer.id のセット
    for (cid, qid, rnd), seq in answer_seq.items():
        c = w = 0
        was_cleared = False
        for correct, aid in seq:
            if correct:
                c += 1
            else:
                w += 1
            is_cleared = c > w
            if is_cleared and not was_cleared:
                clear_answers.add(aid)
                was_cleared = True

    result = []
    for answer, question, child in recent:
        cleared = answer.id in clear_answers
        result.append({
            "time": answer.answered_date.isoformat(),
            "child_name": child.name,
            "question_number": question.number,
            "japanese": question.japanese,
            "correct": answer.correct,
            "cleared": cleared,
            "points_earned": ppc_by_child.get(child.id, 0) if cleared else 0,
        })

    return result
