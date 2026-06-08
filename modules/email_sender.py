"""이메일 발송 모듈 (Gmail SMTP / SendGrid 지원)."""
from __future__ import annotations

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

from config import config


def _build_request_body(name: str, esign_url: str = "") -> str:
    sign_section = ""
    if esign_url:
        sign_section = f"""
<div style="background:#EBF5FF;border:1px solid #2C5F8A;border-radius:8px;
            padding:18px;margin:16px 0;">
  <p style="margin:0 0 10px;font-weight:bold;color:#1B3A6B;">📝 전자서명 안내</p>
  <p style="margin:0 0 14px;">아래 버튼을 클릭하시면 브라우저에서 바로 서명하실 수 있습니다.<br>
     서명 후 자동으로 저장되며 별도 회신이 필요하지 않습니다.</p>
  <a href="{esign_url}"
     style="background:#2C5F8A;color:white;padding:12px 28px;
            border-radius:6px;text-decoration:none;font-weight:bold;
            font-size:15px;display:inline-block;">
     ✍️ 전자서명 하기
  </a>
  <p style="margin:12px 0 0;font-size:12px;color:#666;">
     링크는 14일간 유효합니다. 문제가 있으면 인사총무팀으로 연락해주세요.
  </p>
</div>
"""
    return f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;">
<div style="background:#1B3A6B;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
  <h2 style="margin:0;font-size:18px;">{config.HOSPITAL_NAME}</h2>
  <p style="margin:4px 0 0;font-size:13px;opacity:0.85;">인사총무팀</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
  <p>안녕하세요, <b>{name}</b> 님.</p>
  <p>근로계약서를 첨부드립니다.</p>
  <ul>
    <li>PDF 비밀번호는 <b>주민등록번호 뒷 7자리</b>입니다.</li>
    <li>첨부 파일을 먼저 저장하신 후 서명 버튼을 눌러주세요.</li>
  </ul>
  {sign_section}
  <p style="color:#666;font-size:12px;margin-top:20px;border-top:1px solid #eee;padding-top:12px;">
    {config.HOSPITAL_NAME} 인사총무팀 | 이 이메일은 자동발송입니다.
  </p>
</div>
</body></html>
"""


def _build_final_body(name: str) -> str:
    return f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;">
<div style="background:#1B3A6B;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
  <h2 style="margin:0;font-size:18px;">{config.HOSPITAL_NAME}</h2>
  <p style="margin:4px 0 0;font-size:13px;opacity:0.85;">인사총무팀</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
  <p>안녕하세요, <b>{name}</b> 님.</p>
  <p>서명이 완료된 근로계약서 최종본을 첨부드립니다.</p>
  <p>소중한 자료이므로 안전한 곳에 보관해 주시기 바랍니다.</p>
  <p style="color:#666;font-size:12px;margin-top:20px;border-top:1px solid #eee;padding-top:12px;">
    {config.HOSPITAL_NAME} 인사총무팀 | 이 이메일은 자동발송입니다.
  </p>
</div>
</body></html>
"""


def _build_admin_final_body(name: str) -> str:
    return f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;">
<div style="background:#1B3A6B;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
  <h2 style="margin:0;font-size:18px;">{config.HOSPITAL_NAME}</h2>
  <p style="margin:4px 0 0;font-size:13px;opacity:0.85;">인사총무팀 — 서명완료 알림</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
  <div style="background:#E6F4EA;border:1px solid #34A853;border-radius:8px;padding:14px 18px;margin-bottom:16px;">
    <b>✅ 전자서명 완료</b><br>
    <b>{name}</b> 님이 근로계약서 서명을 완료했습니다.
  </div>
  <p>서명 완료된 근로계약서 원본을 첨부드립니다. 보관 처리해 주세요.</p>
  <p style="color:#666;font-size:12px;margin-top:20px;border-top:1px solid #eee;padding-top:12px;">
    {config.HOSPITAL_NAME} 인사총무팀 자동알림 시스템
  </p>
</div>
</body></html>
"""


def _build_message(to: str, subject: str, html_body: str, attachment_path: str) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = f"{config.EMAIL_FROM_NAME} <{config.EMAIL_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    attachment = Path(attachment_path)
    with attachment.open("rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)

    # RFC 5987 인코딩 — 한글 파일명을 모든 이메일 클라이언트에서 .pdf 로 정상 표시
    encoded_name = quote(attachment.name)
    part["Content-Type"] = f'application/pdf; name="{attachment.name}"'
    part["Content-Disposition"] = (
        f"attachment; "
        f"filename*=UTF-8''{encoded_name}; "
        f"filename=\"{attachment.name}\""
    )

    msg.attach(part)
    return msg


def _send_smtp(to: str, subject: str, html_body: str, attachment_path: str):
    msg = _build_message(to, subject, html_body, attachment_path)

    # 포트 465: SSL 직접 연결 / 포트 587: STARTTLS 업그레이드
    if config.EMAIL_PORT == 465:
        import ssl
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(config.EMAIL_HOST, config.EMAIL_PORT, context=context) as server:
            server.login(config.EMAIL_USER, config.EMAIL_PASSWORD)
            server.sendmail(config.EMAIL_USER, to, msg.as_string())
    else:
        with smtplib.SMTP(config.EMAIL_HOST, config.EMAIL_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.EMAIL_USER, config.EMAIL_PASSWORD)
            server.sendmail(config.EMAIL_USER, to, msg.as_string())


def _send_sendgrid(to: str, subject: str, html_body: str, attachment_path: str):
    try:
        import base64
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Attachment, ContentId, Disposition, FileContent,
            FileName, FileType, Mail,
        )
    except ImportError:
        raise ImportError("sendgrid 패키지가 필요합니다: pip install sendgrid")

    mail = Mail(
        from_email=(config.EMAIL_USER, config.EMAIL_FROM_NAME),
        to_emails=to,
        subject=subject,
        html_content=html_body,
    )

    attachment_data = Path(attachment_path).read_bytes()
    encoded = base64.b64encode(attachment_data).decode()
    attachment = Attachment(
        FileContent(encoded),
        FileName(Path(attachment_path).name),
        FileType("application/pdf"),
        Disposition("attachment"),
    )
    mail.attachment = attachment

    sg = SendGridAPIClient(config.SENDGRID_API_KEY)
    response = sg.send(mail)
    if response.status_code >= 400:
        raise RuntimeError(f"SendGrid 발송 실패: {response.status_code} {response.body}")


def _dispatch(to: str, subject: str, html_body: str, attachment_path: str):
    if config.SENDGRID_API_KEY:
        _send_sendgrid(to, subject, html_body, attachment_path)
    else:
        _send_smtp(to, subject, html_body, attachment_path)


def send_sign_request(
    employee: dict,
    encrypted_pdf_path: str,
    esign_url: str = "",
) -> None:
    """전자서명 요청 이메일 발송."""
    name = employee["성명"]
    to = employee["이메일"]
    subject = f"[{config.HOSPITAL_NAME}] 근로계약서 서명 요청 - {name} 님"
    body = _build_request_body(name, esign_url)
    _dispatch(to, subject, body, encrypted_pdf_path)


def send_final_contract(employee: dict, signed_pdf_path: str) -> None:
    """서명 완료된 최종 계약서를 근로자·관리자 모두에게 발송."""
    name = employee["성명"]
    emp_email = employee["이메일"]

    # 근로자 발송
    _dispatch(
        emp_email,
        f"[{config.HOSPITAL_NAME}] 근로계약서 최종본 - {name} 님",
        _build_final_body(name),
        signed_pdf_path,
    )

    # 관리자 발송 (ADMIN_EMAIL 미설정 시 EMAIL_USER로 대체)
    admin_email = config.ADMIN_EMAIL or config.EMAIL_USER
    if admin_email and admin_email != emp_email:
        _dispatch(
            admin_email,
            f"[{config.HOSPITAL_NAME}] 서명완료 알림 - {name} 님",
            _build_admin_final_body(name),
            signed_pdf_path,
        )


def send_document(
    to: str,
    name: str,
    pdf_path: str,
    subject: str = "",
    memo: str = "",
) -> None:
    """완성된 계약서 PDF를 지정 이메일로 직접 발송."""
    if not subject:
        subject = f"[{config.HOSPITAL_NAME}] 근로계약서 - {name} 님"

    memo_section = ""
    if memo.strip():
        memo_section = f"""
<div style="background:#F5F8FC;border-left:4px solid #2C5F8A;
            padding:12px 16px;margin:16px 0;border-radius:0 6px 6px 0;">
  <p style="margin:0;color:#333;">{memo.replace(chr(10), '<br>')}</p>
</div>"""

    body = f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;">
<div style="background:#1B3A6B;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
  <h2 style="margin:0;font-size:18px;">{config.HOSPITAL_NAME}</h2>
  <p style="margin:4px 0 0;font-size:13px;opacity:0.85;">인사총무팀</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
  <p>안녕하세요, <b>{name}</b> 님.</p>
  <p>근로계약서를 첨부드립니다. 내용을 확인하시고 보관해 주시기 바랍니다.</p>
  {memo_section}
  <p style="color:#666;font-size:12px;margin-top:20px;border-top:1px solid #eee;padding-top:12px;">
    {config.HOSPITAL_NAME} 인사총무팀 | 이 이메일은 자동발송입니다.
  </p>
</div>
</body></html>
"""
    _dispatch(to, subject, body, pdf_path)
