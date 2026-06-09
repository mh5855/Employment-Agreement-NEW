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
def create_signing_token(employee: dict, pdf_path: str,
                         sig_x: float = 680.0, sig_y: float = 18.0,
                         sig_w: float = 80.0, sig_h: float = 50.0,
                         sig_page: int = -1) -> str:
    from modules.db_logger import create_sign_token
    token = str(uuid.uuid4())
    create_sign_token(
        token=token,
        employee_id=employee["사번"],
        employee_name=employee["성명"],
        email=employee["이메일"],
        pdf_path=os.path.abspath(pdf_path),
        sig_x=sig_x, sig_y=sig_y, sig_w=sig_w, sig_h=sig_h, sig_page=sig_page,
    )
    return token


def build_sign_url(token: str) -> str:
    from config import config
    return f"{config.SIGN_APP_URL}/?token={token}"


# ── 텍스트 앵커로 서명 삽입 좌표 탐색 ────────────────────────────────────────
def _find_sign_anchor(enc_path: str, password: str) -> tuple[int, tuple]:
    """
    PDF에서 서명 삽입 좌표 자동 탐색.
    우선순위: '수령하였음' 라인 → '서  명 :' 라벨
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

        _SIG_H = 22.0  # 수령확인 행 높이에 맞춘 서명 이미지 높이 (pt)

        def _make_sig_rect(text_x1, pdf_y_bot, pdf_y_top, right_margin=110.0):
            """텍스트 오른쪽에 서명 삽입 좌표 계산."""
            center_y = (pdf_y_bot + pdf_y_top) / 2
            row_h = abs(pdf_y_top - pdf_y_bot)
            sx = text_x1 + 5
            sy = center_y - max(row_h, _SIG_H) / 2
            sw = page_w - text_x1 - right_margin - 5
            sh = max(row_h, _SIG_H)
            return (sx, sy, sw, sh) if sw > 20 else None

        # ── 우선순위 1: '확인 서명 :' 또는 '수령하였음' 라인 ────────────────
        for variant in ["확인 서명 :", "확인서명:", "확인 서명:", "수령하였음을 확인", "수령하였음", "근로계약서를 수령"]:
            hits = page.search_for(variant)
            if hits:
                r = hits[-1]
                pdf_y_bot = page_h - r.y1
                pdf_y_top = page_h - r.y0
                # '성 명:' 텍스트가 오른쪽에 있으므로 ~100pt 여백 확보
                result = _make_sig_rect(r.x1, pdf_y_bot, pdf_y_top, right_margin=105.0)
                if result:
                    doc.close()
                    return pidx, result

        # ── 우선순위 2: '서  명 :' 라벨 (fallback) ───────────────────────────
        for variant in ["서  명 :", "서 명 :", "서명 :"]:
            hits = page.search_for(variant)
            if hits:
                r = hits[-1]
                pdf_y_bot = page_h - r.y1
                pdf_y_top = page_h - r.y0
                result = _make_sig_rect(r.x1, pdf_y_bot, pdf_y_top, right_margin=57.0)
                if result:
                    doc.close()
                    return pidx, result

        # ── 우선순위 3: get_text dict 정밀 파싱 ──────────────────────────────
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    raw = span.get("text", "")
                    normalized = " ".join(raw.split())
                    if "수령하였음" in normalized:
                        bbox = span["bbox"]
                        pdf_y_bot = page_h - bbox[3]
                        pdf_y_top = page_h - bbox[1]
                        result = _make_sig_rect(bbox[2], pdf_y_bot, pdf_y_top, right_margin=105.0)
                        if result:
                            doc.close()
                            return pidx, result
                    if "서 명 :" in normalized or "서명:" in normalized.replace(" ", ""):
                        bbox = span["bbox"]
                        pdf_y_bot = page_h - bbox[3]
                        pdf_y_top = page_h - bbox[1]
                        result = _make_sig_rect(bbox[2], pdf_y_bot, pdf_y_top, right_margin=57.0)
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
_AUTO_DETECT_SENTINEL = (680.0, 18.0)  # 기본값 = 자동탐색 필요 신호


def embed_signature_and_finalize(
    encrypted_pdf_path: str,
    pdf_password: str,
    signature_png_bytes: bytes,
    output_path: str,
    draw_x: float = 680.0,
    draw_y: float = 18.0,
    draw_w: float = 80.0,
    draw_h: float = 50.0,
    sig_page: int = -1,
) -> str:
    """
    1) 좌표가 기본값(680, 18)이면 '수령하였음' 텍스트 앵커로 자동 탐색
    2) 서명 PNG → 흰 배경 JPEG 변환 + 공백 crop
    3) pikepdf로 복호화 + 이미지 콘텐츠 스트림 직접 삽입
    4) AcroForm / Widget 어노테이션 완전 제거
    5) 서명된 PDF 저장 (암호화 없음)
    """
    import pikepdf

    enc_path = os.path.abspath(encrypted_pdf_path)
    if not os.path.exists(enc_path):
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {enc_path}")

    # ── 1. 좌표 자동 탐색 (기본값이면 PDF 텍스트에서 '수령하였음' 위치 검출) ──
    _dx, _dy = _AUTO_DETECT_SENTINEL
    if abs(draw_x - _dx) < 0.5 and abs(draw_y - _dy) < 0.5:
        auto_page, auto_rect = _find_sign_anchor(enc_path, pdf_password)
        if auto_page >= 0 and auto_rect:
            draw_x, draw_y, draw_w, draw_h = auto_rect
            if sig_page < 0:
                sig_page = auto_page

    # ── 2. 서명 이미지 준비 ───────────────────────────────────────────────────
    jpeg_bytes, img_w, img_h = _prepare_signature_jpeg(signature_png_bytes)

    # ── 3. pikepdf로 직접 처리 ────────────────────────────────────────────────
    try:
        with pikepdf.open(enc_path, password=pdf_password) as pdf:
            total_pages = len(pdf.pages)
            if sig_page < 0:
                target = total_pages + sig_page
            else:
                target = sig_page
            target = max(0, min(target, total_pages - 1))

            _embed_image_to_page(
                pdf, target,
                jpeg_bytes, img_w, img_h,
                draw_x, draw_y, draw_w, draw_h,
            )

            _strip_acroform(pdf)
            pdf.save(output_path)

    except pikepdf.PasswordError:
        raise ValueError("비밀번호가 올바르지 않습니다. 주민등록번호 뒷 7자리를 확인해주세요.")

    return output_path


def render_page_with_sig_preview(
    pdf_bytes: bytes,
    page_idx: int = -1,
    sig_x: float = 680.0,
    sig_y: float = 18.0,
    sig_w: float = 80.0,
    sig_h: float = 50.0,
    dpi: int = 100,
) -> tuple:
    """PDF 페이지를 이미지로 렌더링하고 서명 위치를 빨간 박스로 표시.
    Returns: (img_bytes: bytes, page_w: float, page_h: float)
    """
    import io as _io
    try:
        import fitz
    except ImportError:
        return None, 595.0, 842.0

    from PIL import Image, ImageDraw, ImageFont

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if page_idx < 0:
        page_idx = len(doc) + page_idx
    page_idx = max(0, min(page_idx, len(doc) - 1))
    page = doc[page_idx]
    page_w = page.rect.width
    page_h = page.rect.height

    scale = dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()

    # sig_x/y가 페이지 범위를 벗어나면 페이지 안쪽으로 조정
    sig_x = min(sig_x, page_w - 1)
    sig_y = min(sig_y, page_h - 1)
    sig_w = min(sig_w, page_w - sig_x)
    sig_h = min(sig_h, page_h - sig_y)

    # PDF 좌표(좌하단 기준) → 이미지 좌표(좌상단 기준) 변환
    img_x1 = max(0.0, sig_x * scale)
    img_y1 = max(0.0, (page_h - sig_y - sig_h) * scale)
    img_x2 = min(float(pix.width),  (sig_x + sig_w) * scale)
    img_y2 = min(float(pix.height), (page_h - sig_y) * scale)

    # 박스가 1px 미만이면 최소 크기 보장
    if img_x2 <= img_x1:
        img_x2 = img_x1 + 1
    if img_y2 <= img_y1:
        img_y2 = img_y1 + 1

    draw = ImageDraw.Draw(img)
    draw.rectangle([img_x1, img_y1, img_x2, img_y2], outline=(220, 50, 50), width=3)
    # 서명 영역 반투명 오버레이 (빨간색 10% 불투명)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rectangle([img_x1, img_y1, img_x2, img_y2], fill=(220, 50, 50, 30))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")

    # 라벨 텍스트
    draw2 = ImageDraw.Draw(img)
    label_x = max(0, img_x1 + 3)
    label_y = max(0, img_y1 + 3)
    draw2.text((label_x, label_y), "✍ 서명", fill=(180, 30, 30))

    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), page_w, page_h
