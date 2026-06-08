"""Google Drive 자동 업로드 모듈 (서비스 계정 인증).

서비스 계정 설정 방법:
1. Google Cloud Console → IAM 및 관리자 → 서비스 계정 생성
2. Drive API 활성화
3. 서비스 계정 JSON 키 다운로드 → credentials.json 으로 저장
4. 공유 드라이브 또는 루트 폴더에 서비스 계정 이메일 공유 권한 부여
"""
from __future__ import annotations

import os
from pathlib import Path

from config import config


def _get_service():
    """Google Drive API 서비스 객체 반환."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "google-api-python-client 패키지가 필요합니다:\n"
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )

    creds_file = config.GDRIVE_CREDENTIALS_FILE
    if not os.path.exists(creds_file):
        raise FileNotFoundError(
            f"Google 서비스 계정 키 파일을 찾을 수 없습니다: {creds_file}\n"
            "credentials.json 파일을 프로젝트 루트에 위치시켜 주세요."
        )

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(
        creds_file, scopes=scopes
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """폴더가 없으면 생성, 있으면 기존 ID 반환."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def upload_signed_contract(employee: dict, signed_pdf_path: str) -> str:
    """
    서명 완료 PDF를 구글 드라이브에 업로드.

    폴더 구조: 근로계약서 > [사번_성명] > 파일

    Returns:
        Google Drive 파일 ID
    """
    from googleapiclient.http import MediaFileUpload

    emp_id = employee["사번"]
    name = employee["성명"]

    service = _get_service()
    root_id = config.GDRIVE_ROOT_FOLDER_ID

    if not root_id:
        raise ValueError("GDRIVE_ROOT_FOLDER_ID 환경변수가 설정되지 않았습니다.")

    # 근로계약서 폴더
    contract_folder_id = _get_or_create_folder(service, "근로계약서", root_id)
    # 직원별 폴더
    employee_folder_id = _get_or_create_folder(
        service, f"{emp_id}_{name}", contract_folder_id
    )

    file_name = Path(signed_pdf_path).name
    media = MediaFileUpload(signed_pdf_path, mimetype="application/pdf", resumable=True)
    file_meta = {"name": file_name, "parents": [employee_folder_id]}

    uploaded = (
        service.files()
        .create(body=file_meta, media_body=media, fields="id, webViewLink")
        .execute()
    )
    return uploaded.get("id", "")
