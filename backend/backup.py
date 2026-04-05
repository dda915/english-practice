"""Dropboxへの自動バックアップ"""
import os
import threading
import requests
from pathlib import Path
from .database import DB_DIR

DROPBOX_PATH = "/Inbox/temp/2026-04-05-英語学習システム/backups/english.db"


def backup_to_dropbox():
    """バックグラウンドでDBをDropboxにアップロード"""
    token = os.environ.get("DROPBOX_TOKEN")
    if not token:
        print("[backup] DROPBOX_TOKEN未設定、スキップ")
        return

    def _upload():
        db_path = DB_DIR / "english.db"
        if not db_path.exists():
            print("[backup] DBファイルが見つかりません")
            return

        try:
            with open(db_path, "rb") as f:
                data = f.read()

            import json
            resp = requests.post(
                "https://content.dropboxapi.com/2/files/upload",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Dropbox-API-Arg": json.dumps({
                        "path": DROPBOX_PATH,
                        "mode": "overwrite",
                        "mute": True,
                    }),
                    "Content-Type": "application/octet-stream",
                },
                data=data,
                timeout=30,
            )

            if resp.status_code == 200:
                print(f"[backup] Dropboxアップロード完了 ({len(data)} bytes)")
            else:
                print(f"[backup] Dropboxエラー: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[backup] 失敗: {e}")

    threading.Thread(target=_upload, daemon=True).start()
