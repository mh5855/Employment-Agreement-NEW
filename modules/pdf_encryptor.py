"""PDF AES-256 암호화 모듈 (pikepdf).
주민등록번호는 메모리에서만 처리하고 절대 로그/파일에 기록하지 않는다.
"""
from __future__ import annotations

import os
import tempfile


def encrypt_pdf(input_path: str, output_path: str, ssn: str) -> str:
    """
    PDF를 AES-256으로 암호화.

    Args:
        input_path: 원본 PDF 경로
        output_path: 암호화된 PDF 저장 경로
        ssn: 주민등록번호 (뒷 7자리를 비밀번호로 사용)

    Returns:
        output_path
    """
    try:
        import pikepdf
    except ImportError:
        raise ImportError("pikepdf 패키지가 필요합니다: pip install pikepdf")

    password = _extract_password(ssn)
    try:
        with pikepdf.open(input_path) as pdf:
            permissions = pikepdf.Permissions(
                print_highres=True,
                print_lowres=True,
                extract=False,
                modify_annotation=False,
                modify_assembly=False,
                modify_form=False,
                modify_other=False,
            )
            pdf.save(
                output_path,
                encryption=pikepdf.Encryption(
                    owner=password,
                    user=password,
                    aes=True,
                    R=5,          # PDF 1.7 AES-256 — Chrome/Edge/모바일 호환
                    allow=permissions,
                ),
            )
    finally:
        # 비밀번호를 메모리에서 명시적으로 제거
        del password

    return output_path


def _extract_password(ssn: str) -> str:
    """주민등록번호 뒷 7자리 추출 (비밀번호 용도)."""
    clean = str(ssn).replace("-", "").strip()
    if len(clean) >= 13:
        return clean[6:13]
    if len(clean) >= 7:
        return clean[-7:]
    raise ValueError("주민등록번호 형식이 올바르지 않습니다.")
