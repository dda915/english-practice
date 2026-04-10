"""起動スクリプト: 初期データ投入 → サーバー起動"""
import os
import sys
import traceback

try:
    import uvicorn
    from backend.seed import seed
except Exception as e:
    traceback.print_exc()
    sys.exit(1)

if __name__ == "__main__":
    try:
        seed()
    except Exception as e:
        print(f"[SEED ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
    try:
        from backend.main import app  # noqa: test import
        print("[OK] backend.main imported successfully")
    except Exception as e:
        print(f"[IMPORT ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port)
