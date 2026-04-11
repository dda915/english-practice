"""メール送信ユーティリティ"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import make_msgid

SITE_URL = "https://english-practice-5285.onrender.com"


def send_exchange_notification(child_name: str, type_label: str, converted: int, unit: str, points: int, balance: int, request_id: int):
    """交換リクエストのメール通知（HTML）"""
    fulfill_url = f"{SITE_URL}/api/children/exchange-requests/{request_id}/fulfill?from=email"

    html = f"""\
<div style="font-family:sans-serif; max-width:500px; margin:0 auto;">
  <h2 style="color:#2d5a27;">{child_name} がポイント交換を申請しました</h2>
  <table style="border-collapse:collapse; width:100%; margin:16px 0;">
    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#666;">交換内容</td>
        <td style="padding:8px; border-bottom:1px solid #eee; font-weight:bold;">{type_label} {converted}{unit}</td></tr>
    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#666;">使用ポイント</td>
        <td style="padding:8px; border-bottom:1px solid #eee;">{points}pt</td></tr>
    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#666;">残高</td>
        <td style="padding:8px; border-bottom:1px solid #eee;">{balance}pt</td></tr>
  </table>
  <div style="margin:24px 0;">
    <a href="{fulfill_url}" style="display:inline-block; background:#2d5a27; color:#fff; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:bold;">対応済みにする</a>
  </div>
  <div style="margin-top:16px;">
    <a href="{SITE_URL}" style="color:#2d5a27;">サイトを開く</a>
  </div>
</div>"""

    send_notification(
        subject=f"🚨🚨【承認してください】{child_name} → {type_label} {converted}{unit} 🚨🚨",
        body=html,
        html=True,
    )


def send_escalation_notification(
    child_name: str,
    grading_id: int,
    japanese: str,
    english: str,
    ai_reading: str,
    ai_correct: bool,
    ai_comment: str,
    chat_history: list[dict],
    photo_urls: list[str],
):
    """「お父さんに確認してほしい」発生時のメール通知"""
    review_url = f"{SITE_URL}/review/{grading_id}"
    mark = "○ 正解" if ai_correct else "× 不正解"
    mark_color = "#2d5a27" if ai_correct else "#c62828"

    chat_html = ""
    if chat_history:
        chat_html = '<div style="margin:12px 0; padding:12px; background:#fafafa; border-radius:8px; border:1px solid #eee;"><div style="font-size:12px; color:#666; margin-bottom:8px;">AIとのやり取り:</div>'
        for m in chat_history:
            who = "娘" if m["role"] == "user" else "AI"
            bg = "#fff7d6" if m["role"] == "user" else "#ffffff"
            chat_html += f'<div style="margin:6px 0; padding:8px; background:{bg}; border-radius:6px; font-size:13px;"><strong>{who}:</strong> {m["content"]}</div>'
        chat_html += "</div>"

    photos_html = ""
    if photo_urls:
        photos_html = '<div style="margin:12px 0;"><div style="font-size:12px; color:#666; margin-bottom:6px;">答案写真:</div>'
        for url in photo_urls:
            photos_html += f'<a href="{url}" style="display:inline-block; margin:4px;">{url}</a><br>'
        photos_html += "</div>"

    html = f"""\
<div style="font-family:sans-serif; max-width:560px; margin:0 auto;">
  <h2 style="color:#c9932b;">{child_name} の採点を確認してください</h2>
  <div style="margin:16px 0; padding:16px; background:#fff; border:1px solid #ddd; border-radius:8px;">
    <div style="font-size:12px; color:#666; margin-bottom:4px;">問題</div>
    <div style="font-size:15px; font-weight:bold; margin-bottom:12px;">{japanese}</div>
    <div style="font-size:12px; color:#666; margin-bottom:4px;">模範解答</div>
    <div style="font-size:14px; font-style:italic; margin-bottom:12px;">{english}</div>
    <div style="font-size:12px; color:#666; margin-bottom:4px;">娘の回答 (AI読取)</div>
    <div style="font-size:14px; font-style:italic; margin-bottom:12px; padding:8px; background:#fffbea; border-left:3px solid #c9932b;">{ai_reading or '(読み取れませんでした)'}</div>
    <div style="font-size:12px; color:#666; margin-bottom:4px;">AI判定</div>
    <div style="font-size:16px; font-weight:bold; color:{mark_color}; margin-bottom:8px;">{mark}</div>
    <div style="font-size:12px; color:#666; margin-bottom:4px;">AIコメント</div>
    <div style="font-size:13px; margin-bottom:8px;">{ai_comment}</div>
  </div>
  {chat_html}
  {photos_html}
  <div style="margin:24px 0; text-align:center;">
    <a href="{review_url}" style="display:inline-block; background:#c9932b; color:#fff; padding:14px 28px; border-radius:8px; text-decoration:none; font-weight:bold;">確認画面を開く</a>
  </div>
</div>"""

    send_notification(
        subject=f"⚠️⚠️【要確認】{child_name}の採点 ⚠️⚠️",
        body=html,
        html=True,
    )


def send_activity(child_name: str, event: str, detail: str = "", attachments: list | None = None):
    """子供のアクティビティ通知（平文）。Gmailで娘ごとに同一スレッドにまとまる。"""
    body = f"{child_name} が {event}"
    if detail:
        body += f"\n\n{detail}"
    body += f"\n\n{SITE_URL}"

    send_notification(
        subject=f"【PaePae】{child_name}の学習ログ",
        body=body,
        html=False,
        attachments=attachments,
        thread_key=f"activity-{child_name}",
    )


def send_notification(subject: str, body: str, html: bool = False, attachments: list | None = None, thread_key: str | None = None):
    """管理者にメール通知を送信。thread_key を指定するとGmailで同一スレッドにまとまる。"""
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    notify_email = os.environ.get("NOTIFY_EMAIL")

    if not all([smtp_user, smtp_pass, notify_email]):
        print(f"[mail] 環境変数未設定のためスキップ: {subject}")
        return

    subtype = "html" if html else "plain"
    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, subtype, "utf-8"))
        for att in attachments:
            try:
                filename, data, mime_subtype = att
                img = MIMEImage(data, _subtype=mime_subtype)
                img.add_header("Content-Disposition", "attachment", filename=filename)
                msg.attach(img)
            except Exception as e:
                print(f"[mail] 添付失敗: {e}")
    else:
        msg = MIMEText(body, subtype, "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = notify_email

    # スレッドをまとめる: 同じ thread_key のメールは In-Reply-To/References で連結
    if thread_key:
        try:
            from .database import SessionLocal
            from .models import EmailThread
            db = SessionLocal()
            try:
                et = db.query(EmailThread).filter(EmailThread.thread_key == thread_key).first()
                if et:
                    # 既存スレッド → このメールを返信にする
                    msg["In-Reply-To"] = et.message_id
                    msg["References"] = et.message_id
                else:
                    # 新規スレッド → Message-ID を記録
                    new_id = make_msgid(domain="english-practice-5285.onrender.com")
                    msg["Message-ID"] = new_id
                    db.add(EmailThread(thread_key=thread_key, message_id=new_id))
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[mail] スレッド処理エラー（送信は続行）: {e}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"[mail] 送信完了: {subject}")
    except Exception as e:
        print(f"[mail] 送信失敗: {e}")
