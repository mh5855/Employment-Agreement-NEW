"""자체 웹 서명 모듈.

pikepdf 단독으로 서명 이미지를 PDF 콘텐츠 스트림에 직접 삽입.
AcroForm 위젯을 완전히 제거하여 서명이 가려지는 문제를 원천 차단.
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime


# ── 토큰 생성 ──────────────────────────────────────────────────────────────────
def create_signing_token(employee: dict, pdf_path: str) -> str:
    from modules.db_logger import create_sign_token
    token = str(uuid.uuid4())
    create_sign_token(
        token=token,
        employee_id=employee["사번"],
        employee_name=employee["성명"],
        email=employee["이메일"],
        pdf_path=os.path.abspath(pdf_path),   # 절대경로로 저장
    )
    return token


def build_sign_url(token: str) -> str:
    from config import config
    return f"{config.SIGN_APP_URL}/?token={token}"


# ── 텍스트 앵커로 서명 삽입 좌표 탐색 ────────────────────────────────────────
def _find_sign_anchor(enc_path: str, password: str) -> tuple[int, tuple]:
    """
    '서  명 :' 텍스트를 PDF에서 찾아 서명 삽입 좌표 반환.
    Returns (page_idx, (x, y, w, h)) | (-1, ())
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return -1, ()

    try:
        doc = fitz.open(enc_path)
        if doc.needs_pass:
            if not doc.authenticate(password):
                return -1, ()
    except Exception:
        return -1, ()

    for pidx in range(len(doc) - 1, -1, -1):
        page = doc[pidx]
        page_h = page.rect.height
        page_w = page.rect.width

        _SIG_H = 30.0  # 서명 이미지 높이 (pt) — 수령확인 행 높이에 맞춤

        def _make_sig_rect(text_x1, pdf_y_bot, pdf_y_top):
            """텍스트 오른쪽에 서명 삽입 좌표 계산."""
            center_y = (pdf_y_bot + pdf_y_top) / 2
            sx = text_x1 + 2
            sy = center_y - _SIG_H / 2
            sw = page_w - text_x1 - 57 - 5
            sh = _SIG_H
            return (sx, sy, sw, sh) if sw > 20 else None

        # 방법 1: search_for 빠른 검색
        for variant in ["서  명 :", "서 명 :", "서명 :"]:
            hits = page.search_for(variant)
            if hits:
                r = hits[-1]
                pdf_y_bot = page_h - r.y1
                pdf_y_top = page_h - r.y0
                result = _make_sig_rect(r.x1, pdf_y_bot, pdf_y_top)
                if result:
                    doc.close()
                    return pidx, result

        # 방법 2: get_text dict 정밀 파싱
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    raw = span.get("text", "")
                    normalized = " ".join(raw.split())
                    if "서 명 :" in normalized or "서명:" in normalized.replace(" ", ""):
                        bbox = span["bbox"]
                        pdf_y_bot = page_h - bbox[3]
                        pdf_y_top = page_h - bbox[1]
                        result = _make_sig_rect(bbox[2], pdf_y_bot, pdf_y_top)
                        if result:
                            doc.close()
                            return pidx, result

    doc.close()
    return -1, ()


# ── AcroForm 필드 위치 탐색 (fallback) ────────────────────────────────────────
def _find_field_rect(pdf_path: str, password: str, field_name: str) -> tuple[int, list]:
    import pikepdf
    with pikepdf.open(pdf_path, password=password) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            if "/Annots" not in page:
                continue
            for annot in page.Annots:
                t_raw = annot.get("/T", None)
                if t_raw is None:
                    continue
                if field_name not in str(t_raw):
                    continue
                rect_raw = annot.get("/Rect", None)
                if rect_raw is None:
                    continue
                return page_idx, [float(v) for v in rect_raw]
    return -1, []


# ── 서명 이미지 준비 (흰 배경 합성 → JPEG) ────────────────────────────────────
def _prepare_signature_jpeg(sig_png_bytes: bytes) -> tuple[bytes, int, int]:
    """
    PNG 서명 이미지를 흰 배경 JPEG로 변환.
    Returns: (jpeg_bytes, width, height)
    """
    from PIL import Image

    sig = Image.open(io.BytesIO(sig_png_bytes)).convert("RGBA")

    # 흰 배경에 합성 (투명 → 흰색)
    bg = Image.new("RGB", sig.size, (255, 255, 255))
    bg.paste(sig, mask=sig.split()[3])

    # 서명 영역만 crop (공백 제거)
    import numpy as np
    arr = np.array(sig)
    alpha = arr[:, :, 3]
    rows = np.any(alpha > 30, axis=1)
    cols = np.any(alpha > 30, axis=0)
    if rows.any() and cols.any():
        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]
        pad = 10
        rmin = max(0, rmin - pad)
        rmax = min(sig.height - 1, rmax + pad)
        cmin = max(0, cmin - pad)
        cmax = min(sig.width - 1, cmax + pad)
        bg = bg.crop((cmin, rmin, cmax + 1, rmax + 1))

    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=95)
    return buf.getvalue(), bg.width, bg.height


# ── pikepdf로 이미지를 PDF 콘텐츠 스트림에 직접 삽입 ──────────────────────────
def _embed_image_to_page(
    pdf,           # pikepdf.Pdf (open 상태)
    page_idx: int,
    jpeg_bytes: bytes,
    img_w: int,
    img_h: int,
    x: float,
    y: float,
    draw_w: float,
    draw_h: float,
):
    import pikepdf

    page = pdf.pages[page_idx]

    # 1. 이미지 XObject 생성
    img_xobj = pikepdf.Stream(pdf, jpeg_bytes)
    img_xobj["/Type"]             = pikepdf.Name("/XObject")
    img_xobj["/Subtype"]          = pikepdf.Name("/Image")
    img_xobj["/Width"]            = img_w
    img_xobj["/Height"]           = img_h
    img_xobj["/ColorSpace"]       = pikepdf.Name("/DeviceRGB")
    img_xobj["/BitsPerComponent"] = 8
    img_xobj["/Filter"]           = pikepdf.Name("/DCTDecode")

    # 2. 페이지 Resources에 XObject 등록
    if "/Resources" not in page:
        page["/Resources"] = pikepdf.Dictionary()
    if "/XObject" not in page.Resources:
        page.Resources["/XObject"] = pikepdf.Dictionary()

    xobj_ref = pdf.make_indirect(img_xobj)
    page.Resources["/XObject"]["/SigImg"] = xobj_ref

    # 3. 그리기 명령 (콘텐츠 스트림 추가)
    draw_cmd = (
        f"q {draw_w:.4f} 0 0 {draw_h:.4f} {x:.4f} {y:.4f} cm "
        f"/SigImg Do Q\n"
    ).encode()
    draw_stream = pdf.make_indirect(pikepdf.Stream(pdf, draw_cmd))

    # 4. 기존 Contents에 append
    contents = page.get("/Contents")
    if contents is None:
        page["/Contents"] = draw_stream
    elif isinstance(contents, pikepdf.Array):
        new_arr = pikepdf.Array(list(contents) + [draw_stream])
        page["/Contents"] = new_arr
    else:
        page["/Contents"] = pikepdf.Array([contents, draw_stream])


# ── AcroForm 및 Widget 어노테이션 완전 제거 ────────────────────────────────────
def _strip_acroform(pdf) -> None:
    import pikepdf

    if "/AcroForm" in pdf.Root:
        del pdf.Root["/AcroForm"]

    for page in pdf.pages:
        if "/Annots" not in page:
            continue
        keep = []
        for annot in page.Annots:
            try:
                if "/Widget" not in str(annot.get("/Subtype", "")):
                    keep.append(annot)
            except Exception:
                keep.append(annot)
        page["/Annots"] = pikepdf.Array(keep)


# ── 메인: 서명 삽입 + 저장 ────────────────────────────────────────────────────
def embed_signature_and_finalize(
    encrypted_pdf_path: str,
    pdf_password: str,
    signature_png_bytes: bytes,
    output_path: str,
) -> str:
    """
    1) AcroForm 필드 위치 탐색
    2) 서명 PNG → 흰 배경 JPEG 변환 + 공백 crop
    3) pikepdf로 복호화 + 이미지 콘텐츠 스트림 직접 삽입
    4) AcroForm / Widget 어노테이션 완전 제거
    5) 서명된 PDF 저장 (암호화 없음)
    """
    import pikepdf

    # 절대경로 확인
    enc_path = os.path.abspath(encrypted_pdf_path)
    if not os.path.exists(enc_path):
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {enc_path}")

    # ── 1. 서명 이미지 준비 ───────────────────────────────────────────────────
    jpeg_bytes, img_w, img_h = _prepare_signature_jpeg(signature_png_bytes)

    # ── 2. pikepdf로 직접 처리 ────────────────────────────────────────────────
    try:
        with pikepdf.open(enc_path, password=pdf_password) as pdf:
            total_pages = len(pdf.pages)
            target = total_pages - 1  # 마지막 페이지

            # 서명 삽입 좌표 (PDF pt, 좌하단 기준)
            draw_x = 680.0
            draw_y = 18.0
            draw_w = 80.0
            draw_h = 50.0

            # 이미지 삽입
            _embed_image_to_page(
                pdf, target,
                jpeg_bytes, img_w, img_h,
                draw_x, draw_y, draw_w, draw_h,
            )

            # AcroForm 완전 제거
            _strip_acroform(pdf)

            pdf.save(output_path)

    except pikepdf.PasswordError:
        raise ValueError("비밀번호가 올바르지 않습니다. 주민등록번호 뒷 7자리를 확인해주세요.")

    return output_path
