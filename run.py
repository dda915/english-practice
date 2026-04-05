"""起動スクリプト: 初期データ投入 → サーバー起動"""
import os
import uvicorn
from backend.seed import seed

if __name__ == "__main__":
    seed()
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
