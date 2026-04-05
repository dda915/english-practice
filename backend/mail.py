"""メール送信ユーティリティ"""
import os
import smtplib
from email.mime.text import MIMEText

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
        subject=f"【英語学習】{child_name}がポイント交換を申請（{type_label} {converted}{unit}）",
        body=html,
        html=True,
    )


def send_notification(subject: str, body: str, html: bool = False):
    """管理者にメール通知を送信"""
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    notify_email = os.environ.get("NOTIFY_EMAIL")

    if not all([smtp_user, smtp_pass, notify_email]):
        print(f"[mail] 環境変数未設定のためスキップ: {subject}")
        return

    subtype = "html" if html else "plain"
    msg = MIMEText(body, subtype, "utf-8")
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
