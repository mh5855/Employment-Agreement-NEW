"""표준근로계약서 PDF 생성 모듈 (ReportLab 기반, 한글 지원)."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from config import config


# ── 한글 폰트 등록 ─────────────────────────────────────────────────────────────
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",          # Windows 맑은 고딕
    "C:/Windows/Fonts/malgunbd.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
    os.path.join(os.path.dirname(__file__), "../fonts/NanumGothic.ttf"),
]

_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/malgunbd.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    os.path.join(os.path.dirname(__file__), "../fonts/NanumGothicBold.ttf"),
]

FONT_NAME = "KoreanFont"
FONT_BOLD = "KoreanFontBold"


def _register_fonts():
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont(FONT_NAME, path))
            break
    else:
        raise FileNotFoundError(
            "한글 폰트를 찾을 수 없습니다.\n"
            "fonts/ 폴더에 NanumGothic.ttf 를 복사하거나 Windows 환경에서 실행하세요."
        )

    for path in _BOLD_CANDIDATES:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont(FONT_BOLD, path))
            return
    # 굵은 폰트 없으면 일반 폰트로 대체
    pdfmetrics.registerFont(TTFont(FONT_BOLD, _FONT_CANDIDATES[0]))


_register_fonts()

# ── 스타일 정의 ────────────────────────────────────────────────────────────────
_base = ParagraphStyle(
    "base", fontName=FONT_NAME, fontSize=9, leading=14, spaceAfter=2
)
_title = ParagraphStyle(
    "title", fontName=FONT_BOLD, fontSize=14, leading=20,
    alignment=TA_CENTER, spaceAfter=6
)
_subtitle = ParagraphStyle(
    "subtitle", fontName=FONT_BOLD, fontSize=10, leading=14, spaceAfter=4
)
_bold = ParagraphStyle(
    "bold", fontName=FONT_BOLD, fontSize=9, leading=14
)
_center = ParagraphStyle(
    "center", fontName=FONT_NAME, fontSize=9, leading=14, alignment=TA_CENTER
)
_center_bold = ParagraphStyle(
    "center_bold", fontName=FONT_BOLD, fontSize=9, leading=14, alignment=TA_CENTER
)


def _p(text: str, style=None) -> Paragraph:
    return Paragraph(text, style or _base)


def _fmt_num(val) -> str:
    try:
        n = int(str(val).replace(",", "").strip())
        return f"{n:,}"
    except (ValueError, TypeError):
        return str(val)


def _mask_ssn(ssn: str) -> str:
    """주민등록번호 뒷 6자리 마스킹 (표시용)."""
    ssn = str(ssn).replace("-", "")
    if len(ssn) >= 13:
        return ssn[:7] + "******"
    return ssn


# ── 페이지 하단 고정 서명 바 (푸터) ───────────────────────────────────────────
_FOOTER_BAR_H  = 22 * mm   # 수령 확인 + 서 명 : 바 높이
_FOOTER_SIG_ROW_H = 14 * mm   # 서 명 : 행 높이


def _draw_sign_footer(canvas, emp_name: str) -> None:
    """모든 페이지 최하단에 '수령하였음 + 서  명 :' 바를 고정 위치로 그린다."""
    from reportlab.lib.pagesizes import A4 as _A4
    PAGE_W = _A4[0]

    X       = 20 * mm                    # 좌측 여백
    Y       = 20 * mm                    # 바 하단 y (하단 여백 위)
    W       = PAGE_W - 2 * 20 * mm       # 바 너비 = 컨텐츠 너비
    BAR_H   = _FOOTER_BAR_H
    SIG_H   = _FOOTER_SIG_ROW_H
    TOP_H   = BAR_H - SIG_H

    canvas.setStrokeColor(colors.HexColor("#2C5F8A"))
    canvas.setLineWidth(0.7)
    canvas.rect(X, Y, W, BAR_H)

    canvas.setLineWidth(0.5)
    canvas.line(X, Y + SIG_H, X + W, Y + SIG_H)

    # 상단 행: 체크박스 + 확인 텍스트 + 성명
    BS  = 9
    TY  = Y + SIG_H + (TOP_H - BS) / 2
    canvas.setLineWidth(0.9)
    canvas.rect(X + 8, TY, BS, BS, fill=0)
    canvas.setFillColor(colors.black)
    canvas.setFont(FONT_NAME, 8.5)
    canvas.drawString(X + 21, TY + 1, "※ 근로계약서를 수령하였음을 확인합니다.")
    canvas.drawString(X + W - 100, TY + 1, f"성 명: {emp_name}")

    # 하단 행: 서  명 : + 서명 영역 시각적 박스
    LABEL_W = 20 * mm
    FIELD_H = SIG_H - 4
    canvas.setFont(FONT_BOLD, 9)
    canvas.setFillColor(colors.HexColor("#1B3A6B"))
    canvas.drawString(X + 5, Y + (SIG_H - 9) / 2, "서  명 :")

    canvas.setFillColor(colors.HexColor("#EBF5FF"))
    canvas.setStrokeColor(colors.HexColor("#2C5F8A"))
    canvas.setLineWidth(0.5)
    canvas.rect(X + LABEL_W + 3, Y + 2, W - LABEL_W - 8, FIELD_H, fill=1, stroke=1)


# ── 메인 생성 함수 ─────────────────────────────────────────────────────────────
def generate_contract_pdf(
    employee: dict,
    salary_summary: dict,
    output_path: str,
    sign_date: Optional[str] = None,
) -> str:
    if sign_date is None:
        sign_date = datetime.now().strftime("%Y년 %m월 %d일")

    emp_name = employee.get("성명", "")

    def _footer(canvas, doc):
        canvas.saveState()
        _draw_sign_footer(canvas, emp_name)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm + _FOOTER_BAR_H + 3 * mm,  # 하단 여백 + 바 + 간격
    )

    story = []
    story += _build_header()
    story += _build_parties(employee, sign_date)
    story += _build_contract_terms(employee, salary_summary)
    story += _build_salary_table(salary_summary)
    story += _build_clauses()
    story += _build_signature_section(employee, sign_date)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output_path


# ── 섹션 빌더 ──────────────────────────────────────────────────────────────────
def _build_header() -> list:
    return [
        _p("표  준  근  로  계  약  서", _title),
        Spacer(1, 4 * mm),
        _p(
            f"<b>{config.HOSPITAL_NAME}</b>(이하 \"갑\"이라 한다)과(와) 아래 을은 다음과 같이 근로계약을 체결한다.",
            _base,
        ),
        Spacer(1, 3 * mm),
    ]


def _build_parties(emp: dict, sign_date: str) -> list:
    name = emp.get("성명", "")
    emp_id = emp.get("사번", "")
    dept = emp.get("소속부서", "")
    position = emp.get("직급", "")

    data = [
        ["구  분", "갑 (사업주)", "을 (근로자)"],
        ["성    명", config.HOSPITAL_NAME, name],
        ["사업자등록번호 / 사번", config.HOSPITAL_BIZ_REG, emp_id],
        ["소속 / 직급", "", f"{dept} / {position}"],
        ["주    소", config.HOSPITAL_ADDRESS, ""],
    ]

    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5F8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])

    col_widths = [45 * mm, 70 * mm, 55 * mm]
    table = Table(
        [[_p(str(c), _center_bold if r == 0 else _center) for c in row] for r, row in enumerate(data)],
        colWidths=col_widths,
        style=style,
    )
    return [table, Spacer(1, 5 * mm)]


def _build_contract_terms(emp: dict, sal: dict) -> list:
    start_date = emp.get("입사일", "")
    period = emp.get("근로계약기간", "")
    dept = emp.get("소속부서", "")
    working_hours = sal.get("working_hours", "")
    break_time = sal.get("break_time", "")

    if period and "~" in str(period):
        contract_period = str(period)
    elif period:
        contract_period = f"{start_date} ~ {period}"
    else:
        contract_period = f"{start_date} ~ (정함 없음)"

    items = [
        ("1. 근로계약기간", contract_period),
        ("2. 근 무 장 소", f"{config.HOSPITAL_NAME} 사업장"),
        ("3. 업 무 내 용", f"{dept} 관련 업무"),
        ("4. 소정근로시간",
         f"{working_hours}  (휴게시간: {break_time})"),
        ("5. 근무일 / 휴일",
         "주 5일 근무, 주휴일 매주 일요일 (단체협약 및 취업규칙에 따름)"),
    ]

    story = []
    for label, value in items:
        row_data = [[_p(label, _bold), _p(value, _base)]]
        t = Table(row_data, colWidths=[55 * mm, 115 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ]))
        story.append(t)

    story.append(Spacer(1, 3 * mm))
    return story


def _build_salary_table(sal: dict) -> list:
    story = [_p("6.  임  금", _subtitle)]

    monthly = sal["monthly_total"]
    annual = sal["annual_total"]

    header = [
        _p("구  분", _center_bold),
        _p("산출방식", _center_bold),
        _p("월  금  액 (원)", _center_bold),
    ]

    rows = [header]
    for item_name, item_val in sal["salary_items"].items():
        rows.append([
            _p(item_name, _center),
            _p("해당 직급 기준", _center),
            _p(_fmt_num(item_val), _center),
        ])

    rows.append([
        _p("월 지급 합계", _center_bold),
        _p("", _center),
        _p(_fmt_num(monthly), _center_bold),
    ])
    rows.append([
        _p("연봉 합계", _center_bold),
        _p("(월 합계 × 12개월)", _center),
        _p(_fmt_num(annual), _center_bold),
    ])

    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5F8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#EBF2FA")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -3), [colors.white, colors.HexColor("#F5F8FC")]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])

    col_widths = [55 * mm, 60 * mm, 55 * mm]
    table = Table(rows, colWidths=col_widths, style=style)

    story.append(table)
    story.append(
        _p("  ※ 임금지급일: 매월 25일 (공휴일인 경우 전일 지급)", _base)
    )
    story.append(
        _p("  ※ 지급방법: 근로자 명의 예금통장에 입금", _base)
    )
    story.append(Spacer(1, 3 * mm))
    return story


def _build_clauses() -> list:
    clauses = [
        ("7. 연차유급휴가", "근로기준법에서 정하는 바에 따름"),
        ("8. 사회보험 적용", "□ 고용보험  □ 산재보험  □ 국민연금  □ 건강보험"),
        ("9. 근로계약서 교부",
         "사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자에게 교부함"),
        ("10. 기    타",
         "이 계약에 정함이 없는 사항은 근로기준법령에 따름"),
    ]
    story = []
    for label, value in clauses:
        row_data = [[_p(label, _bold), _p(value, _base)]]
        t = Table(row_data, colWidths=[55 * mm, 115 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ]))
        story.append(t)
    story.append(Spacer(1, 5 * mm))
    return story


def _build_signature_section(emp: dict, sign_date: str) -> list:
    name    = emp.get("성명", "")
    ssn     = emp.get("주민등록번호", "")
    address = emp.get("주소", "")
    today_ascii = datetime.now().strftime("%Y-%m-%d")

    story = [
        _p(sign_date, _center),
        Spacer(1, 4 * mm),
    ]

    _row_style = TableStyle([
        ("FONTNAME",     (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LINEBELOW",    (0, 0), (-1, -1), 0.3, colors.lightgrey),
    ])

    # ── 갑 (사업주) ────────────────────────────────────────────────────────────
    ga_data = [
        [_p("(갑) 사업체명", _bold), _p(config.HOSPITAL_NAME,       _base)],
        [_p("      대 표 자", _bold), _p(config.HOSPITAL_REPRESENTATIVE, _base)],
        [_p("      주    소", _bold), _p(config.HOSPITAL_ADDRESS,    _base)],
    ]
    ga_table = Table(ga_data, colWidths=[45 * mm, 125 * mm])
    ga_table.setStyle(_row_style)
    story.append(ga_table)
    story.append(Spacer(1, 1 * mm))
    story.append(_p("      대표자 서명", _bold))
    story.append(Spacer(1, 1 * mm))
    story.append(_AcroSignField("ga_signature", 170 * mm, 14 * mm, bg="#F5F8FC"))
    story.append(Spacer(1, 5 * mm))

    # ── 을 (근로자) ────────────────────────────────────────────────────────────
    eul_data = [
        [_p("(을) 성    명", _bold), _p(name,              _base)],
        [_p("  주민등록번호", _bold), _p(_mask_ssn(ssn),   _base)],
        [_p("  주    소",   _bold), _p(address,            _base)],
    ]
    eul_table = Table(eul_data, colWidths=[45 * mm, 125 * mm])
    eul_table.setStyle(_row_style)
    story.append(eul_table)

    story.append(Spacer(1, 2 * mm))

    # ── 서명란 + 회신란 + 수령 체크박스 (통합 블록) ───────────────────────────
    story.append(_SignatureSectionBlock(name, today_ascii, width=170 * mm))

    return story


# ── 서명란 + 회신란 + 수령 체크박스 통합 Flowable ─────────────────────────────
class _SignatureSectionBlock(Flowable):
    """
    [근로자 서명란] | [수령 확인 회신란 ✂]
    [        수령하였음 □ 체크박스 바        ]
    """

    # 치수 상수 (pt)
    HEADER_H  = 7  * mm   # 박스 헤더 높이
    SIG_H     = 32 * mm   # 전자서명 입력 영역 높이
    DATE_H    = 9  * mm   # 날짜 필드 높이
    IPAD      = 2  * mm   # 내부 패딩
    BOX_H     = HEADER_H + SIG_H + IPAD + DATE_H + IPAD   # 서명 박스 전체 높이
    def __init__(self, emp_name: str, today_ascii: str, width: float = 170 * mm):
        Flowable.__init__(self)
        self.emp_name    = emp_name
        self.today_ascii = today_ascii
        self.width       = width
        self.height      = self.BOX_H  # CB_H 바는 페이지 푸터로 이동

    def wrap(self, avW, avH):
        return self.width, self.height

    def draw(self):                             # noqa: C901
        c  = self.canv
        W  = self.width

        # ── 치수 ──────────────────────────────────────────────────────────────
        LEFT_W  = W * 0.585
        COL_GAP = 4
        RIGHT_W = W - LEFT_W - COL_GAP
        RX      = LEFT_W + COL_GAP

        BOX_H  = self.BOX_H
        BASE_Y = 0   # CB_H 바는 페이지 푸터로 이동 → 박스가 y=0에서 시작

        H_H    = self.HEADER_H
        SIG_H  = self.SIG_H
        DATE_H = self.DATE_H
        IPAD   = self.IPAD

        # ══════════════════════════════════════════════════════════════════════
        # 1. 근로자 서명란 (좌측 박스)
        # ══════════════════════════════════════════════════════════════════════
        c.setStrokeColor(colors.HexColor("#2C5F8A"))
        c.setLineWidth(0.8)
        c.rect(0, BASE_Y, LEFT_W, BOX_H)

        # 헤더 배경
        c.setFillColor(colors.HexColor("#EBF2FA"))
        c.rect(0, BASE_Y + BOX_H - H_H, LEFT_W, H_H, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#1B3A6B"))
        c.setFont(FONT_BOLD, 9)
        c.drawCentredString(LEFT_W / 2, BASE_Y + BOX_H - H_H + 2.5,
                            "근로자 서명  (전자서명)")

        # ── 서명 영역 안내 텍스트 (필드는 을 테이블 서명 행에 배치됨) ─────────
        sig_y = BASE_Y + IPAD + DATE_H + IPAD
        c.setFillColor(colors.HexColor("#7B9EC5"))
        c.setFont(FONT_NAME, 8)
        c.drawCentredString(LEFT_W / 2, sig_y + SIG_H / 2 - 4, "하단 서명란에 서명해 주세요")

        # ── AcroForm: 서명 날짜 ────────────────────────────────────────────────
        c.setFont(FONT_NAME, 8)
        c.setFillColor(colors.black)
        c.drawString(3, BASE_Y + 2, "서명 날짜:")
        c.acroForm.textfield(
            name="sign_date_field",
            tooltip="서명 날짜",
            value=self.today_ascii,
            x=28, y=BASE_Y + 1,
            width=LEFT_W - 32, height=DATE_H - 2,
            relative=True,
            borderStyle="solid",
            borderColor=colors.HexColor("#CCCCCC"),
            fillColor=colors.HexColor("#FAFAFA"),
            textColor=colors.black,
            forceBorder=True,
            fontName="Helvetica", fontSize=9,
        )

        # ══════════════════════════════════════════════════════════════════════
        # 3. 수령 확인 회신란 (우측 박스 — 점선 테두리)
        # ══════════════════════════════════════════════════════════════════════
        c.setStrokeColor(colors.HexColor("#B22222"))
        c.setLineWidth(1.0)
        c.setDash(5, 3)
        c.rect(RX, BASE_Y, RIGHT_W, BOX_H)
        c.setDash()

        # 헤더 배경
        c.setFillColor(colors.HexColor("#FFF0F0"))
        c.rect(RX, BASE_Y + BOX_H - H_H, RIGHT_W, H_H, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#B22222"))
        c.setFont(FONT_BOLD, 7.5)
        c.drawCentredString(RX + RIGHT_W / 2, BASE_Y + BOX_H - H_H + 2.5,
                            "✂  서명 후 인사팀 제출  (회신용)")

        # 수령확인 체크박스
        c.setStrokeColor(colors.HexColor("#B22222"))
        c.setLineWidth(0.8)
        CB2_Y = BASE_Y + BOX_H - H_H - 14
        c.rect(RX + 4, CB2_Y, 9, 9, fill=0)    # □
        c.setFillColor(colors.black)
        c.setFont(FONT_NAME, 8)
        c.drawString(RX + 16, CB2_Y + 1, "수령하였음")

        # 성명 / 서명 / 날짜 기재란
        c.setStrokeColor(colors.HexColor("#AAAAAA"))
        c.setLineWidth(0.4)
        LINE_X1 = RX + 26
        LINE_X2 = RX + RIGHT_W - 4
        rows = [("성  명", CB2_Y - 16), ("서  명", CB2_Y - 34), ("날  짜", CB2_Y - 52)]
        for label, ly in rows:
            c.setFillColor(colors.black)
            c.setFont(FONT_NAME, 8)
            c.drawString(RX + 4, ly + 2, f"{label}:")
            c.setStrokeColor(colors.HexColor("#AAAAAA"))
            c.line(LINE_X1, ly, LINE_X2, ly)

        # 서명 박스 (서명란 강조)
        sig_box_y = CB2_Y - 56
        c.setStrokeColor(colors.HexColor("#CCCCCC"))
        c.setLineWidth(0.5)
        c.rect(RX + 4, sig_box_y, RIGHT_W - 8, 14, fill=0)
        c.setFillColor(colors.HexColor("#DDDDDD"))
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(RX + RIGHT_W / 2, sig_box_y + 4, "sign here")


# ── AcroForm 서명 입력 필드 (Flowable 래퍼) ───────────────────────────────────
class _AcroSignField(Flowable):
    """단독 배치용 AcroForm 텍스트 서명 필드."""

    def __init__(self, field_name, width, height, default="", bg="#EBF5FF"):
        Flowable.__init__(self)
        self.field_name = field_name
        self.width      = width
        self.height     = height
        self.default    = default
        self.bg         = bg

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def draw(self):
        self.canv.acroForm.textfield(
            name=self.field_name,
            tooltip="클릭하여 서명(성함)을 입력하세요",
            value=self.default,
            x=0, y=0,
            width=self.width, height=self.height,
            relative=True,
            borderStyle="solid",
            borderColor=colors.HexColor("#2C5F8A"),
            fillColor=colors.HexColor(self.bg),
            textColor=colors.black,
            forceBorder=True,
            fontName="Helvetica", fontSize=12,
        )
        self.canv.saveState()
        self.canv.setFont("Helvetica", 8)
        self.canv.setFillColor(colors.HexColor("#7B9EC5"))
        self.canv.drawString(4, self.height / 2 - 4, "Click here to sign")
        self.canv.restoreState()


# ── 파일명 생성 헬퍼 ───────────────────────────────────────────────────────────
def build_output_path(emp_id: str, name: str, output_dir: str) -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{emp_id}_{name}_근로계약서_{date_str}.pdf"
    return os.path.join(output_dir, filename)
