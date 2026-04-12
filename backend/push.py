"""Web Push 通知ユーティリティ (VAPID)"""
import json
import os
from datetime import datetime
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import PushSubscription


def _vapid_claims():
    return {"sub": os.environ.get("VAPID_SUBJECT", "mailto:dda915@gmail.com")}


def _get_private_key() -> str | None:
    key = os.environ.get("VAPID_PRIVATE_KEY")
    if not key:
        return None
    # Render環境変数で改行が消える場合の対応
    key = key.replace("\\n", "\n")
    # PEM形式でない場合（Base64生キー）はそのまま返す
    if "BEGIN" not in key:
        return key
    # PEM形式の場合、改行が正しいか確認
    if "\n" not in key.strip():
        # 改行なしの1行PEM → 復元
        key = key.replace("-----BEGIN PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\n")
        key = key.replace("-----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----\n")
    return key


def get_public_key() -> str:
    return os.environ.get("VAPID_PUBLIC_KEY", "")


_last_push_error = None


def get_last_push_error():
    return _last_push_error


def send_to_subscription(sub: PushSubscription, payload: dict) -> bool:
    """1件の subscription に通知を送る。endpointが死んでいたら True を返さない"""
    global _last_push_error
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        _last_push_error = "pywebpush 未インストール"
        print(f"[push] {_last_push_error}")
        return False

    private_key = _get_private_key()
    if not private_key:
        _last_push_error = "VAPID_PRIVATE_KEY 未設定"
        print(f"[push] {_last_push_error}")
        return False

    subscription_info = {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=private_key,
            vapid_claims=_vapid_claims(),
            ttl=86400,
        )
        _last_push_error = None
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        _last_push_error = f"WebPushException ({status}): {e}"
        print(f"[push] 送信失敗 ({status}): {e}")
        if status in (404, 410):
            try:
                db = SessionLocal()
                obj = db.query(PushSubscription).filter(PushSubscription.endpoint == sub.endpoint).first()
                if obj:
                    db.delete(obj)
                    db.commit()
                db.close()
            except Exception:
                pass
        return False
    except Exception as e:
        import traceback
        _last_push_error = f"Exception: {e}"
        print(f"[push] 例外: {e}")
        traceback.print_exc()
        return False


def notify_parents(payload: dict):
    """親(秋元さん)の全購読に送信"""
    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).filter(PushSubscription.user_type == "parent").all()
        for s in subs:
            send_to_subscription(s, payload)
    finally:
        db.close()


def notify_child(child_id: int, payload: dict):
    """指定子供の全購読に送信"""
    db = SessionLocal()
    try:
        subs = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_type == "child", PushSubscription.child_id == child_id)
            .all()
        )
        for s in subs:
            send_to_subscription(s, payload)
    finally:
        db.close()
