from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path
import shutil

from .database import engine, Base, DB_DIR
from .models import Question, Child, Answer, PointLog, Setting
from .routers import questions, children, answers, points, settings

Base.metadata.create_all(bind=engine)

app = FastAPI(title="和文英訳トレーニング")

app.include_router(questions.router)
app.include_router(children.router)
app.include_router(answers.router)
app.include_router(points.router)
app.include_router(settings.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/upload-db", response_class=HTMLResponse)
def upload_db_page():
    return """
    <html><body style="font-family:sans-serif;max-width:500px;margin:50px auto">
    <h2>DBアップロード</h2>
    <form action="/upload-db" method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".db"><br><br>
        <button type="submit" style="padding:10px 20px;font-size:16px">アップロード</button>
    </form>
    </body></html>
    """


@app.post("/upload-db")
async def upload_db(file: UploadFile = File(...)):
    db_path = DB_DIR / "english.db"
    with open(db_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return HTMLResponse("""
    <html><body style="font-family:sans-serif;max-width:500px;margin:50px auto">
    <h2>アップロード完了！</h2>
    <a href="/">トップに戻る</a>
    </body></html>
    """)


