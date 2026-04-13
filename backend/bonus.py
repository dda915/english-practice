"""ボーナスタイム判定ロジック"""

import json
from datetime import datetime
from sqlalchemy.orm import Session
from .database import now_jst, JST
from .models import Setting


def _get_setting(db: Session, key: str, default: str) -> str:
    s = db.query(Setting).get(key)
    return s.value if s else default


def is_bonus_time(db: Session, child_id: int) -> tuple[bool, int, str]:
    """
    ボーナスタイム判定。
    Returns: (is_bonus, points, reason)
    """
    normal_points = int(_get_setting(db, "points_per_clear", "2"))
    bonus_points = int(_get_setting(db, "bonus_points", "8"))

    # ボーナス対象の子供IDリスト
    try:
        bonus_child_ids = json.loads(_get_setting(db, "bonus_child_ids", "[]"))
    except (json.JSONDecodeError, TypeError):
        bonus_child_ids = []

    if child_id not in bonus_child_ids:
        return False, normal_points, ""

    now = now_jst()

    # ゲリラボーナスチェック
    guerrilla_until_str = _get_setting(db, "guerrilla_bonus_until", "")
    if guerrilla_until_str:
        try:
            guerrilla_until = datetime.fromisoformat(guerrilla_until_str)
            if guerrilla_until.tzinfo is None:
                guerrilla_until = guerrilla_until.replace(tzinfo=JST)
            if now < guerrilla_until:
                return True, bonus_points, "guerrilla"
        except (ValueError, TypeError):
            pass

    # 定期ボーナスウィンドウ: 6:30-6:45, 18:00-18:15
    h, m = now.hour, now.minute
    time_minutes = h * 60 + m
    if (6 * 60 + 30 <= time_minutes < 6 * 60 + 45) or \
       (18 * 60 <= time_minutes < 18 * 60 + 15):
        return True, bonus_points, "scheduled"

    return False, normal_points, ""


def get_points_per_clear(db: Session, child_id: int) -> int:
    """
    child_id に応じたクリアポイントを返す。
    ボーナスタイム中かつ対象の子供なら bonus_points、それ以外は通常 points_per_clear。
    """
    _is_bonus, points, _reason = is_bonus_time(db, child_id)
    return points
