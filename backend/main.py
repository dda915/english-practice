from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .database import engine, Base
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






