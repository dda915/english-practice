"""ボーナスタイム管理 API"""

from datetime import timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db, now_jst, JST
from ..models import Setting
from ..bonus import is_bonus_time
from ..line_bot import broadcast_line_message

router = APIRouter(tags=["bonus"])


def _get_setting(db: Session, key: str, default: str) -> str:
    s = db.query(Setting).get(key)
    return s.value if s else default


def _set_setting(db: Session, key: str, value: str):
    s = db.query(Setting).get(key)
    if s:
        s.value = value
    else:
        db.add(Setting(key=key, value=value))


@router.get("/api/bonus/status")
def bonus_status(db: Session = Depends(get_db)):
    """現在のボーナスステータスを返す"""
    # child_id=3 (ゆめ) をデフォルトでチェック
    import json
    try:
        bonus_child_ids = json.loads(_get_setting(db, "bonus_child_ids", "[]"))
    except (json.JSONDecodeError, TypeError):
        bonus_child_ids = []

    check_id = bonus_child_ids[0] if bonus_child_ids else 0
    _is_bonus, points, reason = is_bonus_time(db, check_id)

    guerrilla_until = _get_setting(db, "guerrilla_bonus_until", "")
    normal_points = int(_get_setting(db, "points_per_clear", "2"))
    bonus_points = int(_get_setting(db, "bonus_points", "8"))

    return {
        "is_bonus": _is_bonus,
        "points": points,
        "reason": reason,
        "guerrilla_until": guerrilla_until or None,
        "normal_points": normal_points,
        "bonus_points": bonus_points,
        "bonus_child_ids": bonus_child_ids,
    }


@router.post("/api/bonus/guerrilla")
def start_guerrilla(db: Session = Depends(get_db)):
    """ゲリラボーナスを開始（15分間）"""
    now = now_jst()
    until = now + timedelta(minutes=15)
    until_str = until.isoformat()
    _set_setting(db, "guerrilla_bonus_until", until_str)
    db.commit()

    # LINE通知
    sent = 0
    try:
        sent = broadcast_line_message(
            "🎉 ゲリラボーナスタイム発動！\n"
            "今から15分間、1問クリアで8ポイント！\n"
            "今すぐPaePaeを開こう！🔥"
        )
        print(f"[guerrilla] LINE通知送信: {sent}人")
    except Exception as e:
        print(f"[guerrilla] LINE通知失敗: {e}")

    bonus_points = int(_get_setting(db, "bonus_points", "8"))
    return {
        "ok": True,
        "guerrilla_until": until_str,
        "bonus_points": bonus_points,
        "line_sent": sent,
    }
