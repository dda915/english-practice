"""ボーナスタイム管理 API"""

import json
from datetime import timedelta
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db, now_jst, JST
from ..models import Setting
from ..bonus import is_bonus_time
from ..line_bot import broadcast_line_message

router = APIRouter(tags=["bonus"])


class GuerrillaRequest(BaseModel):
    minutes: int = Field(default=15, ge=1, le=120)
    points: int = Field(default=8, ge=1, le=100)


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
    try:
        bonus_child_ids = json.loads(_get_setting(db, "bonus_child_ids", "[]"))
    except (json.JSONDecodeError, TypeError):
        bonus_child_ids = []

    check_id = bonus_child_ids[0] if bonus_child_ids else 0
    _is_bonus, points, reason = is_bonus_time(db, check_id)

    guerrilla_until = _get_setting(db, "guerrilla_bonus_until", "")
    guerrilla_points = _get_setting(db, "guerrilla_bonus_points", "")
    normal_points = int(_get_setting(db, "points_per_clear", "2"))
    bonus_points = int(_get_setting(db, "bonus_points", "8"))

    return {
        "is_bonus": _is_bonus,
        "points": points,
        "reason": reason,
        "guerrilla_until": guerrilla_until or None,
        "guerrilla_points": int(guerrilla_points) if guerrilla_points else None,
        "normal_points": normal_points,
        "bonus_points": bonus_points,
        "bonus_child_ids": bonus_child_ids,
    }


@router.post("/api/bonus/guerrilla")
def start_guerrilla(req: GuerrillaRequest = GuerrillaRequest(), db: Session = Depends(get_db)):
    """ゲリラボーナスを開始（分数・ポイント指定可）"""
    now = now_jst()
    until = now + timedelta(minutes=req.minutes)
    until_str = until.isoformat()
    _set_setting(db, "guerrilla_bonus_until", until_str)
    _set_setting(db, "guerrilla_bonus_points", str(req.points))
    db.commit()

    # LINE通知
    sent = 0
    try:
        sent = broadcast_line_message(
            f"🎉 ゲリラボーナスタイム発動！\n"
            f"今から{req.minutes}分間、1問クリアで{req.points}ポイント！\n"
            f"今すぐPaePaeを開こう！🔥"
        )
        print(f"[guerrilla] LINE通知送信: {sent}人")
    except Exception as e:
        print(f"[guerrilla] LINE通知失敗: {e}")

    return {
        "ok": True,
        "guerrilla_until": until_str,
        "bonus_points": req.points,
        "minutes": req.minutes,
        "line_sent": sent,
    }
