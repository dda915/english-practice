"""毎晩の振り返りLINEメッセージ生成・送信"""

import os
from datetime import datetime, timedelta
from .database import SessionLocal, now_jst, JST
from .models import Answer, Question, Child, PointLog, Setting
from .line_bot import broadcast_line_message


def _get_daily_stats(db, child_id: int, today: datetime):
    """今日の実績を集計"""
    start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    # 今日の解答
    answers = (
        db.query(Answer)
        .filter(
            Answer.child_id == child_id,
            Answer.answered_date >= start,
            Answer.answered_date < end,
        )
        .all()
    )

    total = len(answers)
    correct = sum(1 for a in answers if a.correct)
    wrong = total - correct

    # 今日クリアした問題を特定（今日の解答でクリア条件を満たしたもの）
    child = db.query(Child).get(child_id)
    stage = child.stage if child and child.stage else 1

    cleared_questions = []
    question_ids_today = set(a.question_id for a in answers)
    for qid in question_ids_today:
        all_answers = (
            db.query(Answer)
            .filter(Answer.child_id == child_id, Answer.question_id == qid)
            .order_by(Answer.answered_date)
            .all()
        )
        c = w = 0
        was_cleared = False
        cleared_by_today = False
        for a in all_answers:
            if a.correct:
                c += 1
            else:
                w += 1
            is_cleared = c > w + (stage - 1)
            if is_cleared and not was_cleared:
                # このクリアが今日の解答によるものか
                if a.answered_date >= start:
                    cleared_by_today = True
                was_cleared = True

        if cleared_by_today:
            q = db.query(Question).get(qid)
            if q:
                cleared_questions.append(q)

    # 今日のポイント獲得
    point_logs = (
        db.query(PointLog)
        .filter(
            PointLog.child_id == child_id,
            PointLog.logged_date == today.date(),
            PointLog.amount > 0,
        )
        .all()
    )
    earned_points = sum(p.amount for p in point_logs)

    # 累計ポイント
    all_points = db.query(PointLog).filter(PointLog.child_id == child_id).all()
    total_points = sum(p.amount for p in all_points)

    # 連続学習日数
    streak = 0
    check_date = today.date()
    while True:
        day_start = datetime(check_date.year, check_date.month, check_date.day, tzinfo=JST)
        day_end = day_start + timedelta(days=1)
        has_activity = (
            db.query(Answer)
            .filter(
                Answer.child_id == child_id,
                Answer.answered_date >= day_start,
                Answer.answered_date < day_end,
            )
            .first()
        )
        if has_activity:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    return {
        "total_answers": total,
        "correct": correct,
        "wrong": wrong,
        "cleared_questions": cleared_questions,
        "earned_points": earned_points,
        "total_points": total_points,
        "streak": streak,
        "child_name": child.name if child else "子供",
    }


def _generate_review_message(stats: dict) -> str:
    """ClaudeでパーソナライズされたLINE振り返りメッセージを生成"""
    if stats["total_answers"] == 0:
        # 今日何もしなかった場合もAIに任せる
        prompt = f"""あなたは小学生の英語学習アプリ「PaePae」のキャラクターです。
{stats['child_name']}ちゃん（小学生の女の子）に、今日は練習しなかったことについて
優しく声をかけるLINEメッセージを作ってください。

情報:
- 累計ポイント: {stats['total_points']}pt
- 明日の朝6:30からボーナスタイム（8ポイント）がある

ルール:
- 責めない、プレッシャーをかけすぎない
- 明日のボーナスタイムに軽く誘う
- 絵文字を適度に使う
- 3行以内でLINEメッセージとして自然な長さ
- 挨拶不要、本題だけ"""
    else:
        cleared_list = ""
        if stats["cleared_questions"]:
            cleared_list = "\n".join(
                f"  - 問{q.number}「{q.japanese}」" for q in stats["cleared_questions"]
            )

        prompt = f"""あなたは小学生の英語学習アプリ「PaePae」のキャラクターです。
{stats['child_name']}ちゃん（小学生の女の子）に、今日の学習を振り返るLINEメッセージを作ってください。

今日の実績:
- 解答数: {stats['total_answers']}問（正解{stats['correct']}、不正解{stats['wrong']}）
- 新しくクリアした問題: {len(stats['cleared_questions'])}問
{cleared_list if cleared_list else '  （なし）'}
- 今日の獲得ポイント: {stats['earned_points']}pt
- 累計ポイント: {stats['total_points']}pt
- 連続学習日数: {stats['streak']}日

ルール:
- 具体的な数字や問題に触れて褒める
- 連続学習日数が長ければ特に褒める
- 不正解が多くても前向きに
- 明日のボーナスタイム（朝6:30）に軽く触れる
- 絵文字を適度に使う
- 4行以内でLINEメッセージとして自然な長さ
- 挨拶不要、本題だけ"""

    try:
        from anthropic import Anthropic
        client = Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"[daily review] Claude API エラー: {e}")
        # フォールバック
        if stats["total_answers"] == 0:
            return f"今日はお休みだったね。明日の朝6:30からボーナスタイムだよ！💪"
        return (
            f"今日は{stats['total_answers']}問チャレンジして"
            f"{stats['earned_points']}ptゲットしたね！"
            f"明日もボーナスタイム狙おう！🌟"
        )


def send_daily_review() -> dict:
    """全ボーナス対象の子供に振り返りLINEを送信。結果を返す。"""
    import json
    result = {"children": [], "error": None}
    db = SessionLocal()
    try:
        now = now_jst()
        # ボーナス対象の子供IDを取得
        s = db.query(Setting).get("bonus_child_ids")
        try:
            child_ids = json.loads(s.value) if s else []
        except (json.JSONDecodeError, TypeError):
            child_ids = []

        result["child_ids"] = child_ids

        for child_id in child_ids:
            stats = _get_daily_stats(db, child_id, now)
            message = _generate_review_message(stats)
            print(f"[daily review] {stats['child_name']}: {message}")
            sent = broadcast_line_message(message)
            result["children"].append({
                "child_id": child_id,
                "name": stats["child_name"],
                "message": message,
                "sent": sent,
                "total_answers": stats["total_answers"],
            })
    except Exception as e:
        print(f"[daily review] エラー: {e}")
        result["error"] = str(e)
    finally:
        db.close()
    return result
