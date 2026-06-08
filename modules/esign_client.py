"""전자서명 클라이언트 모듈 (모두싸인 API v2).

모두싸인 API 문서: https://developer.modusign.co.kr
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Optional

import requests

from config import config

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _auth_headers() -> dict:
    return {**_HEADERS, "Authorization": f"Bearer {config.MODUSIGN_API_KEY}"}


# ── 서명 요청 생성 ─────────────────────────────────────────────────────────────
def create_sign_request(
    employee: dict,
    pdf_path: str,
    title: Optional[str] = None,
) -> dict:
    """
    모두싸인에 전자서명 요청을 생성하고 서명 URL을 반환.

    Returns:
        {
          "request_id": "...",
          "sign_url": "https://...",
          "status": "pending"
        }
    """
    if not config.MODUSIGN_API_KEY:
        raise RuntimeError("MODUSIGN_API_KEY 환경변수가 설정되지 않았습니다.")

    name = employee["성명"]
    email = employee["이메일"]
    doc_title = title or f"{name} 님 근로계약서"

    # Step 1: 문서 업로드
    doc_id = _upload_document(pdf_path, doc_title)

    # Step 2: 서명 요청 생성
    payload = {
        "title": doc_title,
        "documents": [{"id": doc_id}],
        "participants": [
            {
                "name": name,
                "email": email,
                "role": "signer",
                "signingMethod": {"type": "email"},
            }
        ],
        "expirationDate": _expiry_date(),
    }

    resp = requests.post(
        f"{config.MODUSIGN_API_URL}/document-requests",
        headers=_auth_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    request_id = data.get("id") or data.get("requestId", "")
    sign_url = (
        data.get("participants", [{}])[0]
        .get("signingUrl", "")
    )

    return {"request_id": request_id, "sign_url": sign_url, "status": "pending"}


def _upload_document(pdf_path: str, title: str) -> str:
    """모두싸인에 PDF 업로드 후 document ID 반환."""
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{config.MODUSIGN_API_URL}/documents",
            headers={"Authorization": f"Bearer {config.MODUSIGN_API_KEY}"},
            files={"file": (Path(pdf_path).name, f, "application/pdf")},
            data={"title": title},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["id"]


def _expiry_date() -> str:
    from datetime import datetime, timedelta
    return (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── 상태 조회 ──────────────────────────────────────────────────────────────────
def get_sign_status(request_id: str) -> str:
    """서명 요청 상태 조회. 반환값: 'pending' | 'completed' | 'cancelled'"""
    resp = requests.get(
        f"{config.MODUSIGN_API_URL}/document-requests/{request_id}",
        headers=_auth_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("status", "unknown")


# ── 서명 완료 PDF 다운로드 ─────────────────────────────────────────────────────
def download_signed_pdf(request_id: str, save_path: str) -> str:
    """서명 완료된 PDF를 다운로드하여 save_path에 저장."""
    resp = requests.get(
        f"{config.MODUSIGN_API_URL}/document-requests/{request_id}/download",
        headers=_auth_headers(),
        timeout=60,
    )
    resp.raise_for_status()
    Path(save_path).write_bytes(resp.content)
    return save_path


# ── Webhook 서명 검증 ──────────────────────────────────────────────────────────
def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    """모두싸인 webhook 요청의 HMAC-SHA256 서명 검증."""
    if not config.MODUSIGN_WEBHOOK_SECRET:
        return True  # 시크릿 미설정 시 검증 스킵
    expected = hmac.new(
        config.MODUSIGN_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def parse_webhook_event(body: bytes) -> dict:
    """Webhook 이벤트 파싱. 서명 완료 이벤트인지 확인."""
    data = json.loads(body)
    return {
        "request_id": data.get("documentRequestId", ""),
        "status": data.get("status", ""),
        "is_completed": data.get("status") == "completed",
    }
