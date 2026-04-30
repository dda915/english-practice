import csv
import io
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Question

router = APIRouter(prefix="/api/questions", tags=["questions"])


class QuestionBody(BaseModel):
    number: int
    japanese: str
    english: str
    unit_number: float = 0


@router.post("")
def add_question(body: QuestionBody, db: Session = Depends(get_db)):
    existing = db.query(Question).filter(Question.number == body.number).first()
    if existing:
        raise HTTPException(400, f"問題番号 {body.number} は既に存在します")
    q = Question(number=body.number, unit_number=body.unit_number, japanese=body.japanese, english=body.english)
    db.add(q)
    db.commit()
    db.refresh(q)
    return {"id": q.id, "number": q.number, "unit_number": q.unit_number, "japanese": q.japanese, "english": q.english}


@router.get("")
def list_questions(db: Session = Depends(get_db)):
    qs = db.query(Question).order_by(Question.unit_number, Question.number).all()
    return [
        {"id": q.id, "unit_number": q.unit_number, "number": q.number, "japanese": q.japanese, "english": q.english}
        for q in qs
    ]


@router.post("/import")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "CSVファイルをアップロードしてください")

    content = await file.read()
    # Try utf-8 first, then shift_jis (common for Japanese CSV)
    for encoding in ["utf-8-sig", "utf-8", "shift_jis", "cp932"]:
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(400, "ファイルのエンコーディングを認識できません")

    reader = csv.reader(io.StringIO(text))
    imported = 0
    skipped = 0

    for row in reader:
        if len(row) < 3:
            continue
        # Skip header row
        try:
            number = int(row[0].strip())
        except ValueError:
            continue

        japanese = row[1].strip()
        english = row[2].strip()

        if not japanese or not english:
            continue

        existing = db.query(Question).filter(Question.number == number).first()
        if existing:
            existing.japanese = japanese
            existing.english = english
            skipped += 1
        else:
            db.add(Question(number=number, japanese=japanese, english=english))
            imported += 1

    db.commit()
    return {"imported": imported, "updated": skipped}
