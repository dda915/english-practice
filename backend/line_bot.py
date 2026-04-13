"""LINE Messaging API (PaePae公式アカウント) でのメッセージ送信"""

import json
import os
import urllib.request
from .database import SessionLocal
from .models import LineFriend


def _get_token() -> str | None:
    return os.environ.get("LINE_CHANNEL_TOKEN_PAEPAE")


def send_line_message(user_id: str, message: str) -> bool:
    """特定ユーザーにテキストメッセージを送信"""
    token = _get_token()
    if not token:
        print("[LINE] LINE_CHANNEL_TOKEN_PAEPAE が未設定")
        return False

    payload = json.dumps({
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"[LINE] 送信失敗 (user={user_id[:10]}...): {e}")
        return False


def broadcast_line_message(message: str) -> int:
    """line_friends テーブルの全ユーザーにメッセージ送信。送信成功数を返す。"""
    token = _get_token()
    if not token:
        print("[LINE] LINE_CHANNEL_TOKEN_PAEPAE が未設定")
        return 0

    db = SessionLocal()
    try:
        friends = db.query(LineFriend).all()
        if not friends:
            print("[LINE] line_friends が空です")
            return 0

        sent = 0
        for f in friends:
            if send_line_message(f.line_user_id, message):
                sent += 1
        return sent
    except Exception as e:
        print(f"[LINE] broadcast エラー: {e}")
        return 0
    finally:
        db.close()
