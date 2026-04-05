"""メール送信ユーティリティ"""
import os
import smtplib
from email.mime.text import MIMEText


def send_notification(subject: str, body: str):
    """管理者にメール通知を送信"""
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    notify_email = os.environ.get("NOTIFY_EMAIL")

    if not all([smtp_user, smtp_pass, notify_email]):
        print(f"[mail] 環境変数未設定のためスキップ: {subject}")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = notify_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"[mail] 送信完了: {subject}")
    except Exception as e:
        print(f"[mail] 送信失敗: {e}")
