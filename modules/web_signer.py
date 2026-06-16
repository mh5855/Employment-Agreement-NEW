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
    우선순위: 텍스트 검색 → OCR (이미지 기반 PDF)
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

        _SIG_H = 22.0

        def _make_sig_rect(text_x1, pdf_y_bot, pdf_y_top, right_margin=40.0):
            """텍스트 오른쪽에 서명 삽입 좌표 계산."""
            center_y = (pdf_y_bot + pdf_y_top) / 2
            row_h = abs(pdf_y_top - pdf_y_bot)
            sx = text_x1 + 5
            sy = center_y - max(row_h, _SIG_H) / 2
            sw = page_w - text_x1 - right_margin - 5
            sh = max(row_h, _SIG_H)
            return (sx, sy, sw, sh) if sw > 20 else None

        def _make_sig_rect_over_cell(bbox, pad_x=8.0, pad_y=6.0):
            """(인) 셀 위에 서명을 덮어씌우는 좌표 계산 (셀 중앙 기준)."""
            # bbox: (x0, y0, x1, y1) in fitz coords (top-left origin)
            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2
            cell_w = max(bbox[2] - bbox[0], 40.0)
            cell_h = max(bbox[3] - bbox[1], 20.0)
            sw = cell_w + pad_x * 2
            sh = cell_h + pad_y * 2
            sx = cx - sw / 2
            # PDF 좌표는 하단 기준
            sy_pdf = page_h - cy - sh / 2
            return (sx, sy_pdf, sw, sh)

        # ── 우선순위 0: '(인)' 셀 탐색 → 셀 위에 서명 배치 ─────────────────
        for variant in ["(인)", "（인）", "(印)"]:
            hits = page.search_for(variant)
            if hits:
                # 페이지 하단 50% 이내 항목만 사용 (상단 인감 제외, 없으면 skip)
                lower_hits = [r for r in hits if r.y0 > page_h * 0.5]
                if not lower_hits:
                    continue
                r = max(lower_hits, key=lambda rect: rect.y1)
                result = _make_sig_rect_over_cell((r.x0, r.y0, r.x1, r.y1))
                # 페이지 하단 70% 이내 위치만 유효
                if result and result[2] > 10 and result[1] < page_h * 0.7:
                    doc.close()
                    return pidx, result

        # ── 우선순위 1: '확인 서명 :' 또는 '수령하였음' 라인 텍스트 검색 ──────
        for variant in ["확인 서명 :", "확인서명:", "확인 서명:", "수령하였음을 확인", "수령하였음", "근로계약서를 수령"]:
            hits = page.search_for(variant)
            if hits:
                r = hits[-1]
                pdf_y_bot = page_h - r.y1
                pdf_y_top = page_h - r.y0
                result = _make_sig_rect(r.x1, pdf_y_bot, pdf_y_top, right_margin=40.0)
                # 페이지 하단 70% 이내 위치만 유효
                if result and result[1] < page_h * 0.7:
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
                if result and result[1] < page_h * 0.7:
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
                        result = _make_sig_rect(bbox[2], pdf_y_bot, pdf_y_top, right_margin=40.0)
                        if result and result[1] < page_h * 0.7:
                            doc.close()
                            return pidx, result
                    if "서 명 :" in normalized or "서명:" in normalized.replace(" ", ""):
                        bbox = span["bbox"]
                        pdf_y_bot = page_h - bbox[3]
                        pdf_y_top = page_h - bbox[1]
                        result = _make_sig_rect(bbox[2], pdf_y_bot, pdf_y_top, right_margin=57.0)
                        if result and result[1] < page_h * 0.7:
                            doc.close()
                            return pidx, result

        # ── 우선순위 4: OCR (이미지 기반 PDF 대응) ───────────────────────────
        try:
            import pytesseract
            from PIL import Image as _PILImage

            DPI = 200
            scale = DPI / 72.0
            pix = page.get_pixmap(dpi=DPI)
            ocr_img = _PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
            data = pytesseract.image_to_data(
                ocr_img, lang='kor+eng',
                output_type=pytesseract.Output.DICT
            )

            # OCR 우선순위 A: (인) 셀 탐색
            in_items = []
            for i, txt in enumerate(data['text']):
                if not txt.strip():
                    continue
                if "(인)" in txt or "（인）" in txt or "(印)" in txt:
                    in_items.append((data['left'][i], data['top'][i],
                                     data['width'][i], data['height'][i], txt))
            if in_items:
                # 가장 하단의 (인) 항목 선택
                it = max(in_items, key=lambda t: t[1] + t[3])
                cx = (it[0] + it[0] + it[2]) / 2
                cy = (it[1] + it[1] + it[3]) / 2
                sw = max(it[2], 40.0) + 16.0
                sh = max(it[3], 20.0) + 12.0
                sx = (cx - sw / 2) / scale
                sy_pdf = page_h - (cy + sh / 2) / scale
                result = (sx, sy_pdf, sw / scale, sh / scale)
                if result[2] > 10:
                    doc.close()
                    return pidx, result

            # OCR 우선순위 B: "확인 서명 :" 콜론 위치 탐색
            keywords = ["확인", "서명", "수령하였음", "수령"]
            found_items = []
            for i, txt in enumerate(data['text']):
                if not txt.strip():
                    continue
                if any(k in txt for k in keywords):
                    found_items.append((data['left'][i], data['top'][i],
                                        data['width'][i], data['height'][i], txt))

            if found_items:
                # y좌표 기준 클러스터링 → 가장 하단 줄 선택
                found_items.sort(key=lambda t: t[1], reverse=True)
                ref_y = found_items[0][1]
                same_line = [it for it in found_items if abs(it[1] - ref_y) < 25]
                same_line.sort(key=lambda t: t[0])

                # 줄에서 가장 오른쪽 텍스트 끝 좌표
                rightmost = max(same_line, key=lambda t: t[0] + t[2])
                img_x1 = rightmost[0] + rightmost[2]
                img_y0 = min(it[1] for it in same_line)
                img_y1 = max(it[1] + it[3] for it in same_line)

                # 이미지 좌표 → PDF pt (하단 기준)
                pdf_x1   = img_x1 / scale
                pdf_y_bot = page_h - img_y1 / scale
                pdf_y_top = page_h - img_y0 / scale

                result = _make_sig_rect(pdf_x1, pdf_y_bot, pdf_y_top, right_margin=40.0)
                if result:
                    doc.close()
                    return pidx, result
        except Exception:
            pass

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
    bg = bg.transpose(Image.FLIP_TOP_BOTTOM)  # PDF 이미지 좌표계 보정 (Y축 반전)
    bg.save(buf, format="JPEG", quality=95)
    return buf.getvalue(), bg.width, bg.height


# ── 페이지 최상위 CTM 파싱 & 역행렬 ────────────────────────────────────────────
def _get_page_ctm(pdf, page_idx: int) -> list:
    """현재 페이지 Contents 스트림들에서 q-depth=0 의 누적 CTM을 반환."""
    import re
    import pikepdf as _pikepdf
    page = pdf.pages[page_idx]
    contents = page.get("/Contents")
    if contents is None:
        return [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

    streams = list(contents) if isinstance(contents, _pikepdf.Array) else [contents]

    all_data = ""
    for s in streams:
        try:
            all_data += bytes(s.read_bytes()).decode("latin-1", errors="ignore")
        except Exception:
            pass

    # q/Q 깊이 0 수준에서만 cm 적용
    ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    depth = 0
    nums: list = []
    for tok in re.split(r"\s+", all_data.strip()):
        if tok == "q":
            depth += 1
            nums = []
        elif tok == "Q":
            depth = max(0, depth - 1)
            nums = []
        elif tok == "cm" and depth == 0 and len(nums) >= 6:
            try:
                m = [float(v) for v in nums[-6:]]
                # 행렬 곱 ctm = ctm × m
                a1, b1, c1, d1, e1, f1 = ctm
                a2, b2, c2, d2, e2, f2 = m
                ctm = [
                    a1*a2 + b1*c2,      a1*b2 + b1*d2,
                    c1*a2 + d1*c2,      c1*b2 + d1*d2,
                    e1*a2 + f1*c2 + e2, e1*b2 + f1*d2 + f2,
                ]
            except ValueError:
                pass
            nums = []
        else:
            nums.append(tok)

    return ctm


def _invert_ctm(m: list) -> list:
    """2D 아핀 CTM [a b c d e f] 역행렬."""
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-10:
        return [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    ai = d / det;  bi = -b / det
    ci = -c / det; di = a / det
    return [ai, bi, ci, di, -(ai*e + ci*f), -(bi*e + di*f)]


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
    signed_at: str = "",   # "YYYY-MM-DD HH:MM:SS" 형식 (ASCII만 사용)
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

    # 2. 페이지 Resources에 XObject + Font 등록
    if "/Resources" not in page:
        page["/Resources"] = pikepdf.Dictionary()
    if "/XObject" not in page.Resources:
        page.Resources["/XObject"] = pikepdf.Dictionary()
    if "/Font" not in page.Resources:
        page.Resources["/Font"] = pikepdf.Dictionary()

    page.Resources["/XObject"]["/SigImg"] = pdf.make_indirect(img_xobj)

    # Helvetica (내장 폰트) — ASCII 날짜 텍스트용
    page.Resources["/Font"]["/SigFont"] = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Font"),
            Subtype=pikepdf.Name("/Type1"),
            BaseFont=pikepdf.Name("/Helvetica"),
            Encoding=pikepdf.Name("/WinAnsiEncoding"),
        )
    )

    # 3. 페이지 기존 CTM 역행렬 적용 → 표준 PDF 디바이스 좌표계(y-up)에서 작업
    page_ctm = _get_page_ctm(pdf, page_idx)
    inv = _invert_ctm(page_ctm)
    inv_cm = (f"{inv[0]:.6f} {inv[1]:.6f} {inv[2]:.6f} "
              f"{inv[3]:.6f} {inv[4]:.6f} {inv[5]:.6f} cm\n")

    font_sz = 8.0
    # 표준 y-up 좌표계에서 서명 박스 아래에 텍스트 배치
    text_y = y - font_sz - 2.0
    if text_y < 2.0:
        text_y = y + 2.0

    safe_text = ""
    if signed_at:
        safe_text = signed_at.encode("ascii", errors="ignore").decode("ascii")

    # q/Q 로 CTM 역행렬 범위 한정 → 이 블록 안은 표준 디바이스 좌표계
    parts = [
        f"q\n{inv_cm}",
        # 박스 테두리 (남색 0.8pt)
        f"0.8 w\n0.18 0.27 0.47 RG\n"
        f"{x:.4f} {y:.4f} {draw_w:.4f} {draw_h:.4f} re\nS\n",
        # 서명 이미지 (PIL FLIP_TOP_BOTTOM + 표준 cm 행렬)
        f"q\n{draw_w:.4f} 0 0 {draw_h:.4f} {x:.4f} {y:.4f} cm\n/SigImg Do\nQ\n",
    ]
    if safe_text:
        parts.append(
            f"BT\n/SigFont {font_sz:.1f} Tf\n0.25 0.25 0.45 rg\n"
            f"1 0 0 1 {x:.4f} {text_y:.4f} Tm\n({safe_text}) Tj\nET\n"
        )
    parts.append("Q\n")

    draw_stream = pdf.make_indirect(
        pikepdf.Stream(pdf, "".join(parts).encode())
    )

    # 6. 기존 Contents에 append
    contents = page.get("/Contents")
    if contents is None:
        page["/Contents"] = draw_stream
    elif isinstance(contents, pikepdf.Array):
        page["/Contents"] = pikepdf.Array(list(contents) + [draw_stream])
    else:
        page["/Contents"] = pikepdf.Array([contents, draw_stream])


# ── 기존 서명(/SigImg) 제거 ───────────────────────────────────────────────────
def _strip_existing_signature(pdf, page_idx: int) -> None:
    """이미 삽입된 /SigImg 서명을 콘텐츠 스트림과 Resources에서 제거."""
    import pikepdf
    import re

    page = pdf.pages[page_idx]

    # 1. Resources에서 /SigImg XObject 제거
    try:
        if "/Resources" in page and "/XObject" in page.Resources:
            xobjs = page.Resources["/XObject"]
            if "/SigImg" in xobjs:
                del xobjs["/SigImg"]
    except Exception:
        pass

    # 2. 콘텐츠 스트림 배열에서 /SigImg Do 포함 스트림 제거
    contents = page.get("/Contents")
    if contents is None:
        return

    if isinstance(contents, pikepdf.Array):
        kept = []
        for s in list(contents):
            try:
                data = bytes(s.read_bytes())
                if b'/SigImg' in data:
                    continue  # 서명 스트림 제거
            except Exception:
                pass
            kept.append(s)
        if len(kept) == 1:
            page["/Contents"] = kept[0]
        else:
            page["/Contents"] = pikepdf.Array(kept)
    else:
        # 단일 스트림 내부에서 /SigImg Do 패턴 제거
        try:
            data = bytes(contents.read_bytes())
            if b'/SigImg' in data:
                cleaned = re.sub(
                    rb'q\s+[\d\.\s]+cm\s+/SigImg\s+Do\s+Q[\r\n]*', b'', data
                )
                if b'/SigImg' in cleaned:
                    cleaned = re.sub(rb'/SigImg\s+Do', b'', cleaned)
                page["/Contents"] = pdf.make_indirect(pikepdf.Stream(pdf, cleaned))
        except Exception:
            pass


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
_AUTO_DETECT_SENTINEL = (680.0, 80.0)  # 기본값 = 자동탐색 필요 신호


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
    signed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 3. pikepdf로 직접 처리 ────────────────────────────────────────────────
    try:
        with pikepdf.open(enc_path, password=pdf_password) as pdf:
            total_pages = len(pdf.pages)
            if sig_page < 0:
                target = total_pages + sig_page
            else:
                target = sig_page
            target = max(0, min(target, total_pages - 1))

            # 페이지 크기 파악 후 좌표 보정
            try:
                _mb = pdf.pages[target].get("/MediaBox")
                pg_w = float(_mb[2]) if _mb else 595.0
                pg_h_pt = float(_mb[3]) if _mb else 842.0
            except Exception:
                pg_w, pg_h_pt = 595.0, 842.0

            # y가 페이지 상단 30% 이상이면 자동탐색 결과가 잘못된 것 → 기본값 사용
            if draw_y > pg_h_pt * 0.7:
                draw_y = 80.0
            # 페이지 경계 초과 시에만 보정 (자동탐색 위치 최대한 유지)
            if draw_x + draw_w > pg_w or draw_x < 0:
                draw_w = min(draw_w, 120.0)
                draw_x = pg_w - draw_w - 10.0

            _strip_existing_signature(pdf, target)
            _embed_image_to_page(
                pdf, target,
                jpeg_bytes, img_w, img_h,
                draw_x, draw_y, draw_w, draw_h,
                signed_at=signed_at,
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
