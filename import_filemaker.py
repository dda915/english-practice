"""
FileMaker CSVからのデータインポートスクリプト

CSVファイル構造:
  mondai.csv: [0]単元番号, [1]和文, [2]英訳, [3]UUID, ..., [12]問題番号
  log.csv:    [0]UUID, ..., [5]問題UUID, [6]OK/NG, ..., [9]回答日
  point.csv:  [0]ID, [1]日付, [2]無視, [3]空, [4]amount, [5]get/spend

使い方:
  python import_filemaker.py --child 1 \\
      --mondai ../2026-04-05-180706-mondai.csv \\
      --log ../2026-04-05-180640-log.csv \\
      --point ../2026-04-05-180909-point.csv
"""
import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.database import engine, SessionLocal, Base
from backend.models import Question, Child, Answer, PointLog, Setting


def parse_date(s: str) -> date:
    """YYYY/MM/DD or YYYY-MM-DD を date に変換"""
    s = s.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日付を解析できません: {s}")


def read_csv(path: str) -> list[list[str]]:
    """CSVを読み込む（複数エンコーディング対応）"""
    for enc in ["utf-8-sig", "utf-8", "shift_jis", "cp932"]:
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"エンコーディング判別不能: {path}")


def import_mondai(db, path: str) -> dict[str, int]:
    """問題をインポート。UUID→question.id のマッピングを返す"""
    rows = read_csv(path)
    uuid_to_id: dict[str, int] = {}
    imported = 0
    updated = 0

    for row in rows:
        if len(row) < 13:
            continue

        try:
            number = int(row[12].strip())
        except ValueError:
            continue

        japanese = row[1].strip()
        english = row[2].strip()
        uuid = row[3].strip()

        if not japanese:
            continue

        existing = db.query(Question).filter(Question.number == number).first()
        if existing:
            existing.japanese = japanese
            existing.english = english
            uuid_to_id[uuid] = existing.id
            updated += 1
        else:
            q = Question(number=number, japanese=japanese, english=english)
            db.add(q)
            db.flush()
            uuid_to_id[uuid] = q.id
            imported += 1

    db.commit()
    print(f"[mondai] {imported}問追加, {updated}問更新 (合計{imported + updated}問)")
    return uuid_to_id


def import_log(db, path: str, child_id: int, uuid_map: dict[str, int]):
    """回答履歴をインポート"""
    rows = read_csv(path)
    imported = 0
    skipped = 0

    for row in rows:
        if len(row) < 10:
            continue

        question_uuid = row[5].strip()
        result = row[6].strip()
        date_str = row[9].strip()

        if question_uuid not in uuid_map:
            skipped += 1
            continue

        if result not in ("OK", "NG"):
            skipped += 1
            continue

        try:
            answered_date = parse_date(date_str)
        except ValueError:
            skipped += 1
            continue

        db.add(Answer(
            child_id=child_id,
            question_id=uuid_map[question_uuid],
            answered_date=answered_date,
            correct=(result == "OK"),
        ))
        imported += 1

    db.commit()
    print(f"[log] {imported}件インポート, {skipped}件スキップ")


def import_point(db, path: str, child_id: int):
    """ポイント履歴をインポート"""
    rows = read_csv(path)
    imported = 0

    for row in rows:
        if len(row) < 6:
            continue

        date_str = row[1].strip()
        try:
            amount = int(row[4].strip())
        except ValueError:
            continue

        point_type = row[5].strip()

        try:
            logged_date = parse_date(date_str)
        except ValueError:
            continue

        if point_type == "get":
            seq = row[0].strip()
            desc = f"問題クリア (#{seq})" if seq else "問題クリア"
        elif point_type == "spend":
            desc = f"ポイント使用 ({abs(amount)}pt)"
        else:
            continue

        db.add(PointLog(
            child_id=child_id,
            logged_date=logged_date,
            amount=amount,
            description=desc,
        ))
        imported += 1

    db.commit()
    print(f"[point] {imported}件インポート")


def main():
    parser = argparse.ArgumentParser(description="FileMaker CSVインポート")
    parser.add_argument("--child", type=int, required=True,
                        help="インポート先の子供ID (1, 2, 3)")
    parser.add_argument("--mondai", required=True, help="問題CSV")
    parser.add_argument("--log", help="回答履歴CSV")
    parser.add_argument("--point", help="ポイント履歴CSV")
    parser.add_argument("--reset", action="store_true",
                        help="既存データを削除してからインポート")
    args = parser.parse_args()

    # DB初期化
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 子供の存在確認（なければseedから作成）
        child = db.query(Child).get(args.child)
        if not child:
            # seed相当の初期化
            if db.query(Child).count() == 0:
                for name in ["子供A", "子供B", "子供C"]:
                    db.add(Child(name=name))
                db.commit()
                print("子供3人を作成しました")
            child = db.query(Child).get(args.child)
            if not child:
                print(f"エラー: 子供ID {args.child} が見つかりません")
                return

        # デフォルト設定
        if not db.query(Setting).get("exchange_rate_money"):
            db.add(Setting(key="exchange_rate_money", value="10"))
        if not db.query(Setting).get("exchange_rate_phone"):
            db.add(Setting(key="exchange_rate_phone", value="10"))
        db.commit()

        print(f"=== {child.name} (ID:{child.id}) にインポート ===\n")

        if args.reset:
            # 既存データ削除
            deleted_a = db.query(Answer).filter(Answer.child_id == args.child).delete()
            deleted_p = db.query(PointLog).filter(PointLog.child_id == args.child).delete()
            deleted_q = db.query(Question).delete()
            db.commit()
            print(f"[reset] 問題{deleted_q}件, 回答{deleted_a}件, ポイント{deleted_p}件 削除\n")

        # 問題インポート
        uuid_map = import_mondai(db, args.mondai)

        # 回答履歴インポート
        if args.log:
            import_log(db, args.log, args.child, uuid_map)

        # ポイント履歴インポート
        if args.point:
            import_point(db, args.point, args.child)

        # サマリー
        total_q = db.query(Question).count()
        total_a = db.query(Answer).filter(Answer.child_id == args.child).count()
        total_p = db.query(PointLog).filter(PointLog.child_id == args.child).count()
        balance = sum(
            l.amount for l in
            db.query(PointLog).filter(PointLog.child_id == args.child).all()
        )
        print(f"\n=== 完了 ===")
        print(f"問題数: {total_q}")
        print(f"回答履歴: {total_a}件")
        print(f"ポイント履歴: {total_p}件 (残高: {balance}pt)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
