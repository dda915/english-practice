"""保護者だけの操作を 本体の側で確かめる (2026-10-26)

それまでは 保護者モードの合言葉を 画面 (index.html) の中で比べているだけだった。
合言葉はページの中身にそのまま書いてあり、画面を通さずに直接頼めば 誰でも保護者の操作ができた。

保護者と認めるのは 次のどちらかを要求の見出しに付けてきたとき
    X-Parent-Device    登録済みの保護者の端末の device_id (端末ごとに作る推測できない並び)
    X-Parent-Password  保護者の合言葉 (環境変数 PARENT_PASSWORD)
"""
import hmac
import os
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import ParentDevice

# 合言葉は .env の PARENT_PASSWORD にだけ置く (この倉庫は公開なので ここに書かない)
#   入っていなければ 合言葉では誰も保護者になれない (登録済みの端末だけが通る)
PARENT_PASSWORD = os.environ.get("PARENT_PASSWORD", "")


# 合言葉は 4 桁なので 総当たりなら 1 万回で当たる。間違いが続いた相手は しばらく受け付けない
#   10 分に 10 回間違えたら その相手からの合言葉は 10 分間 正しくても通さない
FAIL_WINDOW_SEC = 600
FAIL_LIMIT = 10
_fails: dict[str, deque] = defaultdict(deque)


def _client(request: Request | None) -> str:
    if request is None:
        return "-"
    # nginx (資料シェアの入口) が付ける本当の相手の住所。Funnel 経由のときは無いので 接続元で数える
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "-")


def password_ok(pw: str | None, request: Request | None = None) -> bool:
    if not pw or not PARENT_PASSWORD:
        return False
    who = _client(request)
    q = _fails[who]
    now = time.time()
    while q and now - q[0] > FAIL_WINDOW_SEC:
        q.popleft()
    if len(q) >= FAIL_LIMIT:
        return False
    # 1 文字ずつ比べて途中で抜けると 時間の差から合言葉を当てられるので 一定時間で比べる
    if hmac.compare_digest(pw.encode("utf-8"), PARENT_PASSWORD.encode("utf-8")):
        return True
    q.append(now)
    return False


def is_parent(request: Request, db: Session) -> bool:
    if password_ok(request.headers.get("x-parent-password"), request):
        return True
    did = request.headers.get("x-parent-device")
    if did:
        return db.query(ParentDevice).filter(ParentDevice.device_id == did).first() is not None
    return False


def require_parent(request: Request, db: Session = Depends(get_db)) -> None:
    if not is_parent(request, db):
        raise HTTPException(401, "保護者の操作です。保護者モードに切り替えてください")
