"""좋은문화병원 근로계약서 자동화 시스템."""
from __future__ import annotations

import io
import os
import time
import tempfile
from pathlib import Path
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

# Streamlit Cloud 시크릿 → os.environ 주입 (로컬은 .env 파일 사용)
try:
    for _k, _v in st.secrets.items():
        if _k not in os.environ:
            os.environ[_k] = str(_v)
except Exception:
    pass

load_dotenv(override=True)
from config import config

# ── 서명 모드 라우팅 ──────────────────────────────────────────────────────────
_sign_token = st.query_params.get("token", "")

if _sign_token:
    st.set_page_config(
        page_title="근로계약서 전자서명",
        page_icon="✍️",
        layout="centered",
    )
    st.markdown("""
    <style>
      .sign-header{background:linear-gradient(90deg,#1B3A6B,#2C5F8A);color:white;
        padding:20px 28px;border-radius:10px;margin-bottom:20px;}
      .info-box{background:#F5F8FC;border:1px solid #C5D8EC;
        padding:14px 18px;border-radius:8px;margin-bottom:16px;}
      .success-box{background:#E6F4EA;border:1px solid #34A853;
        padding:16px 20px;border-radius:8px;}
    </style>""", unsafe_allow_html=True)
    st.markdown(f"""<div class="sign-header">
      <h2 style="margin:0;">✍️ 근로계약서 전자서명</h2>
      <p style="margin:4px 0 0;opacity:.85;">{config.HOSPITAL_NAME} 인사총무팀</p>
    </div>""", unsafe_allow_html=True)

    from modules.db_logger import get_sign_token, mark_token_signed
    _ti = get_sign_token(_sign_token)

    if not _ti:
        st.error("유효하지 않은 서명 링크입니다.")
        st.stop()
    if _ti.get("signed_at"):
        st.markdown(f"""<div class="success-box"><b>✅ 이미 서명이 완료되었습니다.</b><br>
          서명 일시: {_ti['signed_at']}<br>서명자: {_ti['employee_name']} 님</div>""",
          unsafe_allow_html=True)
        st.stop()
    if datetime.now().strftime("%Y-%m-%d %H:%M:%S") > _ti["expires_at"]:
        st.error(f"서명 링크가 만료되었습니다 (만료: {_ti['expires_at']}). 인사총무팀에 재발급을 요청해 주세요.")
        st.stop()

    _emp_name = _ti["employee_name"]
    _emp_id   = _ti["employee_id"]
    _pdf_path = _ti["pdf_path"]

    st.markdown(f"""<div class="info-box"><b>서명 대상자</b><br>
      이름: <b>{_emp_name}</b> 님 &nbsp;|&nbsp; 사번: {_emp_id}</div>""",
      unsafe_allow_html=True)
    st.info("아래 순서대로 진행해 주세요: ① 비밀번호 입력 → ② 서명 → ③ 서명 완료 버튼")

    st.subheader("① PDF 비밀번호 확인")
    st.caption("이메일에 안내된 비밀번호 (주민등록번호 뒷 7자리)를 입력하세요.")
    _pw_input = st.text_input("비밀번호 (주민번호 뒷 7자리)", type="password", max_chars=7, placeholder="예: 1234567")

    st.subheader("② 아래 칸에 서명하세요")
    st.caption("마우스 또는 터치로 서명을 입력해 주세요.")
    try:
        from streamlit_drawable_canvas import st_canvas
        _canvas = st_canvas(
            fill_color="rgba(0,0,0,0)", stroke_width=3, stroke_color="#000000",
            background_color="#FAFAFA", height=160, width=680,
            drawing_mode="freedraw", display_toolbar=True, key="sign_canvas",
        )
    except ImportError:
        st.error("streamlit-drawable-canvas 패키지가 필요합니다.")
        st.stop()

    st.subheader("③ 서명 완료")
    _submit = st.button("✅ 서명 완료 및 제출", use_container_width=True, type="primary")

    if _submit:
        if not _pw_input or len(_pw_input) != 7:
            st.warning("비밀번호를 7자리로 입력해 주세요.")
            st.stop()
        if _canvas.image_data is None:
            st.warning("서명을 먼저 입력해 주세요.")
            st.stop()
        import numpy as np
        from PIL import Image as _PILImage
        _sig_arr = _canvas.image_data.astype("uint8")
        if _sig_arr.max() == 0:
            st.warning("서명이 비어 있습니다.")
            st.stop()
        _sig_img = _PILImage.fromarray(_sig_arr, "RGBA")
        _sig_buf = io.BytesIO()
        _sig_img.save(_sig_buf, format="PNG")
        _sig_bytes = _sig_buf.getvalue()

        with st.spinner("서명을 처리하는 중입니다..."):
            try:
                from modules.web_signer import embed_signature_and_finalize
                from modules.email_sender import send_final_contract
                _signed_path = _pdf_path.replace(".pdf", f"_서명완료_{_emp_id}.pdf")
                embed_signature_and_finalize(
                    encrypted_pdf_path=_pdf_path,
                    pdf_password=_pw_input,
                    signature_png_bytes=_sig_bytes,
                    output_path=_signed_path,
                    draw_x=float(_ti.get("sig_x", 680.0)),
                    draw_y=float(_ti.get("sig_y", 18.0)),
                    draw_w=float(_ti.get("sig_w", 80.0)),
                    draw_h=float(_ti.get("sig_h", 50.0)),
                    sig_page=int(_ti.get("sig_page", -1)),
                )
                mark_token_signed(_sign_token, _signed_path)
                if config.GDRIVE_ROOT_FOLDER_ID:
                    try:
                        from modules.drive_uploader import upload_signed_contract
                        upload_signed_contract({"사번": _emp_id, "성명": _emp_name, "이메일": _ti["email"]}, _signed_path)
                    except Exception as _e:
                        st.warning(f"구글 드라이브 업로드 실패 (서명은 저장됨): {_e}")
                try:
                    send_final_contract({"성명": _emp_name, "이메일": _ti["email"]}, _signed_path)
                except Exception as _e:
                    st.warning(f"최종 계약서 이메일 발송 실패: {_e}")
                st.balloons()
                st.markdown(f"""<div class="success-box">
                  <h3 style="margin:0 0 8px;">✅ 서명이 완료되었습니다!</h3>
                  <p style="margin:0;"><b>{_emp_name}</b> 님의 근로계약서 서명이 완료되었습니다.<br>
                  서명 완료본이 이메일({_ti['email']})로 발송되었습니다.</p>
                </div>""", unsafe_allow_html=True)
                if os.path.exists(_signed_path):
                    with open(_signed_path, "rb") as _f:
                        st.download_button("📄 서명 완료 계약서 다운로드", _f.read(),
                            file_name=os.path.basename(_signed_path), mime="application/pdf")
            except ValueError as _e:
                st.error(f"❌ {_e}")
            except Exception as _e:
                st.error(f"처리 중 오류가 발생했습니다: {_e}")
            finally:
                del _pw_input
    st.stop()

# ── 관리자 페이지 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="근로계약서 발송 | 좋은문화병원",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
:root { --blue:#1B3A6B; --blue2:#2C5F8A; }
.header {
    background:linear-gradient(90deg,var(--blue),var(--blue2));
    color:white; padding:22px 32px; border-radius:12px; margin-bottom:24px;
}
.card {
    background:#F5F8FC; border:1px solid #D0DFF0;
    border-radius:10px; padding:20px 24px; margin-bottom:12px;
}
.ok-box  { background:#E6F4EA; border:1px solid #34A853; border-radius:8px; padding:16px 20px; }
.err-box { background:#FCE8E6; border:1px solid #EA4335; border-radius:8px; padding:16px 20px; }
.label   { font-size:13px; color:#555; margin-bottom:2px; }
.badge-sent   { background:#E8F0FE; color:#1A73E8; padding:2px 10px; border-radius:12px; font-size:12px; }
.badge-signed { background:#E6F4EA; color:#1E8E3E; padding:2px 10px; border-radius:12px; font-size:12px; }
</style>
""", unsafe_allow_html=True)

# ── 관리자 로그인 (앱 전체 보호) ──────────────────────────────────────────────
_MAX_ATTEMPTS = 5      # 최대 시도 횟수
_LOCK_SECONDS = 300    # 잠금 시간 (5분)

if "login_attempts" not in st.session_state:
    st.session_state["login_attempts"] = 0
if "login_locked_until" not in st.session_state:
    st.session_state["login_locked_until"] = 0.0

if not st.session_state.get("admin_logged_in"):
    st.markdown(f"""
    <div style="max-width:420px;margin:80px auto 0;">
      <div style="background:linear-gradient(90deg,#1B3A6B,#2C5F8A);color:white;
                  padding:20px 28px;border-radius:10px 10px 0 0;text-align:center;">
        <h2 style="margin:0;">📋 근로계약서 발송 시스템</h2>
        <p style="margin:4px 0 0;opacity:.85;">{config.HOSPITAL_NAME} 인사총무팀</p>
      </div>
      <div style="border:1px solid #D0DFF0;border-top:none;padding:28px;border-radius:0 0 10px 10px;background:#fff;">
    """, unsafe_allow_html=True)

    now = time.time()
    locked_until = st.session_state["login_locked_until"]
    if now < locked_until:
        remaining = int(locked_until - now)
        st.error(f"🔒 로그인 시도가 너무 많습니다. {remaining}초 후 다시 시도해 주세요.")
        st.stop()

    pw = st.text_input("관리자 비밀번호", type="password", key="login_pw")
    if st.button("로그인", use_container_width=True, type="primary"):
        if pw == config.ADMIN_PASSWORD:
            st.session_state["admin_logged_in"] = True
            st.session_state["login_attempts"] = 0
            st.rerun()
        else:
            st.session_state["login_attempts"] += 1
            remaining_attempts = _MAX_ATTEMPTS - st.session_state["login_attempts"]
            if st.session_state["login_attempts"] >= _MAX_ATTEMPTS:
                st.session_state["login_locked_until"] = time.time() + _LOCK_SECONDS
                st.session_state["login_attempts"] = 0
                st.error("🔒 5회 실패로 5분간 잠금되었습니다.")
            else:
                st.error(f"비밀번호가 올바르지 않습니다. (남은 시도: {remaining_attempts}회)")

    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

# ── 헤더 (로그인 후) ──────────────────────────────────────────────────────────
st.markdown(f"""
<div class="header">
  <h2 style="margin:0;font-size:1.6rem;">📋 근로계약서 발송 시스템</h2>
  <p style="margin:5px 0 0;opacity:.85;font-size:.92rem;">{config.HOSPITAL_NAME} 인사총무팀</p>
</div>
""", unsafe_allow_html=True)

# ── 데이터 파일 경로 ───────────────────────────────────────────────────────────
DEFAULT_EMP = os.path.join(config.DATA_DIR, "employees.xlsx")
DEFAULT_SAL = os.path.join(config.DATA_DIR, "salary_table.xlsx")

# ── 사이드바 ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 최근 발송 현황")
    try:
        from modules.db_logger import get_recent_logs
        logs = get_recent_logs(6)
        if logs:
            for lg in logs:
                badge = "badge-signed" if lg["status"] == "signed" else "badge-sent"
                label = "서명완료" if lg["status"] == "signed" else "발송"
                name  = lg["employee_name"] or ""
                masked = name[:1] + "*" * max(len(name) - 1, 1) if name else "-"
                st.markdown(
                    f"<span class='{badge}'>{label}</span> "
                    f"**{masked}** {lg['sent_at'][:10]}",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("발송 이력 없음")
    except Exception:
        st.caption("이력 로드 실패")

    st.divider()
    st.markdown("### 서명 앱 상태")
    try:
        import urllib.request
        urllib.request.urlopen(config.SIGN_APP_URL, timeout=2)
        st.success("서명 앱 정상 동작 중")
    except Exception:
        st.error("서명 앱 응답 없음")
        st.caption(f"{config.SIGN_APP_URL}")


# ── 탭 ────────────────────────────────────────────────────────────────────────
tab_upload, tab_bulk, tab_logs = st.tabs([
    "📎  전자서명 요청 계약서 발송",
    "📦  다건 발송",
    "📋  발송 이력",
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1: 완성본 업로드 → 이메일 직접 발송
# ════════════════════════════════════════════════════════════════════════════════
with tab_upload:

    st.markdown("근로계약서 PDF를 업로드하고 서명 요청을 발송합니다.")
    st.markdown("---")

    left, right = st.columns([1, 1], gap="large")

    # ── 좌측: 파일 + 수신자 ───────────────────────────────────────────────────
    with left:
        st.markdown("#### 1. 파일 선택")
        uploaded_pdf = st.file_uploader(
            "근로계약서 PDF",
            type=["pdf"],
            label_visibility="collapsed",
            key="upload_pdf",
        )
        if uploaded_pdf:
            st.success(f"✅ {uploaded_pdf.name}  ({uploaded_pdf.size:,} bytes)")

        # ── 서명 위치 미리보기 ─────────────────────────────────────────────
        if uploaded_pdf:
            with st.expander("⚙️ 서명 위치 미리보기 / 조정", expanded=False):
                try:
                    from modules.web_signer import render_page_with_sig_preview
                    import fitz as _fitz

                    pdf_preview_bytes = uploaded_pdf.getvalue()

                    # 전체 페이지 수 파악
                    _doc = _fitz.open(stream=pdf_preview_bytes, filetype="pdf")
                    _total_pages = len(_doc)
                    _doc.close()

                    # 페이지 선택
                    _page_options = [f"{i+1}페이지" for i in range(_total_pages)]
                    _page_options[-1] += " (마지막)"
                    _sel_page_label = st.selectbox(
                        "미리볼 페이지 (서명이 찍힐 페이지)",
                        options=_page_options,
                        index=_total_pages - 1,
                        key="u_sig_page_sel",
                    )
                    _sel_page_idx = _page_options.index(_sel_page_label)  # 0-indexed

                    # 해당 페이지 크기
                    _, _pw, _ph = render_page_with_sig_preview(
                        pdf_preview_bytes, _sel_page_idx, 0, 0, 1, 1
                    )

                    # 슬라이더 기본값 (세션 없으면 페이지 우하단)
                    _def_x = float(st.session_state.get("u_sig_x", max(0.0, _pw - 120.0)))
                    _def_x = max(0.0, min(_def_x, _pw - 10.0))
                    _def_y = float(st.session_state.get("u_sig_y", 18.0))
                    _def_y = max(0.0, min(_def_y, _ph - 10.0))
                    _def_w = float(st.session_state.get("u_sig_w", 100.0))
                    _def_w = max(10.0, min(_def_w, 300.0))
                    _def_h = float(st.session_state.get("u_sig_h", 40.0))
                    _def_h = max(10.0, min(_def_h, 150.0))

                    sl_col, pv_col = st.columns([1, 2])
                    with sl_col:
                        st.caption(f"페이지 크기: {_pw:.0f} × {_ph:.0f} pt")
                        u_sig_x = st.slider("X 위치 (←→)", 0.0, max(1.0, _pw - 10.0), _def_x, step=1.0, key="u_sig_x")
                        u_sig_y = st.slider("Y 위치 (↑↓, 하단 기준)", 0.0, max(1.0, _ph - 10.0), _def_y, step=1.0, key="u_sig_y")
                        u_sig_w = st.slider("서명 너비", 10.0, min(300.0, _pw - u_sig_x), _def_w, step=1.0, key="u_sig_w")
                        u_sig_h = st.slider("서명 높이", 10.0, min(150.0, _ph - u_sig_y), _def_h, step=1.0, key="u_sig_h")
                        if st.button("기본값 초기화", key="u_sig_reset"):
                            for k in ("u_sig_x", "u_sig_y", "u_sig_w", "u_sig_h", "u_sig_page_sel"):
                                st.session_state.pop(k, None)
                            st.rerun()
                    with pv_col:
                        preview_img, _, _ = render_page_with_sig_preview(
                            pdf_preview_bytes, _sel_page_idx,
                            u_sig_x, u_sig_y, u_sig_w, u_sig_h
                        )
                        if preview_img:
                            st.image(preview_img, caption=f"서명 위치 미리보기 — {_sel_page_label}", use_container_width=True)
                except Exception as _e:
                    st.caption(f"미리보기 불가: {_e}")

        st.markdown("#### 2. 수신자 정보")

        recipient_name = st.text_input(
            "이름 *",
            value=st.session_state.get("pre_name", ""),
            placeholder="예: 홍길동",
            key="rec_name",
        )
        recipient_email = st.text_input(
            "이메일 *",
            value=st.session_state.get("pre_email", ""),
            placeholder="예: hong@goodhospital.or.kr",
            key="rec_email",
        )

        upload_emp_id = ""  # 사번 불필요
        memo = ""

        st.markdown("#### 3. 주민번호 뒷 7자리")
        st.caption("PDF 암호화에 사용됩니다. 직원은 이 번호로만 파일을 열 수 있습니다.")
        ssn_input = st.text_input(
            "주민번호 뒷 7자리 *",
            placeholder="예: 1234567",
            max_chars=7,
            type="password",
            key="upload_ssn",
        )

    # ── 우측: 미리보기 + 발송 ─────────────────────────────────────────────────
    with right:
        st.markdown("#### 발송 요약")

        name_ok  = bool(recipient_name.strip())
        email_ok = "@" in recipient_email and "." in recipient_email
        file_ok  = uploaded_pdf is not None
        ssn_ok   = len(ssn_input.strip()) == 7 and ssn_input.strip().isdigit()

        def check(ok, label):
            icon = "✅" if ok else "⬜"
            st.markdown(f"{icon} {label}")

        check(file_ok,  f"파일: **{uploaded_pdf.name}**" if file_ok else "파일 선택 필요")
        check(name_ok,  f"수신자: **{recipient_name}**" if name_ok else "수신자 성명 필요")
        check(email_ok, f"이메일: **{recipient_email}**" if email_ok else "수신자 이메일 필요")
        check(ssn_ok,   "주민번호 7자리 입력됨" if ssn_ok else "주민번호 뒷 7자리 필요 (숫자 7자리)")

        st.markdown("---")

        ready = file_ok and name_ok and email_ok and ssn_ok
        send_btn = st.button(
            "✍️ 서명 요청 발송",
            disabled=not ready,
            use_container_width=True,
            type="primary",
            key="direct_send_btn",
        )

        if not ready:
            st.caption("필수 항목을 모두 입력하면 발송 버튼이 활성화됩니다.")

        if send_btn and ready:
            st.session_state["single_confirm"] = True

        if st.session_state.get("single_confirm") and not st.session_state.get("send_done"):
            st.warning(f"**최종 전송하시겠습니까?**\n\n수신자: **{recipient_name}** ({recipient_email})")
            ok_col, cancel_col = st.columns(2)
            confirmed = ok_col.button("✅ 확인", use_container_width=True, key="single_confirm_ok", type="primary")
            cancelled = cancel_col.button("❌ 취소", use_container_width=True, key="single_confirm_cancel")
            if cancelled:
                st.session_state.pop("single_confirm", None)
                st.rerun()
            if not confirmed:
                st.stop()

        if st.session_state.get("single_confirm") and not st.session_state.get("send_done"):
            st.session_state.pop("single_confirm", None)
            with st.spinner("발송 중..."):
                try:
                    from modules.db_logger import log_email_sent
                    from modules.email_sender import send_sign_request
                    from modules.web_signer import create_signing_token, build_sign_url
                    from datetime import datetime as _dt

                    from modules.pdf_encryptor import encrypt_pdf

                    date_str  = _dt.now().strftime("%Y%m%d")
                    raw_name  = f"{recipient_name.strip()}_근로계약서_{date_str}_원본.pdf"
                    save_name = f"{recipient_name.strip()}_근로계약서_{date_str}.pdf"
                    raw_path  = os.path.join(os.path.abspath(config.OUTPUT_DIR), raw_name)
                    save_path = os.path.join(os.path.abspath(config.OUTPUT_DIR), save_name)

                    # 원본 저장 후 AES-256 암호화 (주민번호 뒷 7자리)
                    with open(raw_path, "wb") as f:
                        f.write(uploaded_pdf.getbuffer())
                    encrypt_pdf(raw_path, save_path, ssn_input.strip())
                    os.remove(raw_path)

                    emp_info = {
                        "사번":   "",
                        "성명":   recipient_name.strip(),
                        "이메일": recipient_email.strip(),
                    }
                    token    = create_signing_token(
                        emp_info, save_path,
                        sig_x=st.session_state.get("u_sig_x", 680.0),
                        sig_y=st.session_state.get("u_sig_y", 18.0),
                        sig_w=st.session_state.get("u_sig_w", 80.0),
                        sig_h=st.session_state.get("u_sig_h", 50.0),
                        sig_page=_page_options.index(st.session_state.get("u_sig_page_sel", _page_options[-1])) if uploaded_pdf else -1,
                    )
                    sign_url = build_sign_url(token)
                    send_sign_request(emp_info, save_path, sign_url)
                    log_email_sent(emp_info, save_name, token)

                    st.markdown(f"""
                    <div class="ok-box">
                      <b>✅ 서명 요청 발송 완료!</b><br>
                      수신자: <b>{recipient_name}</b> ({recipient_email})<br>
                      서명 링크가 이메일에 포함되었습니다.
                    </div>
                    """, unsafe_allow_html=True)

                    st.session_state["send_done"] = True
                    for k in ("pre_name", "pre_email"):
                        st.session_state.pop(k, None)

                except Exception as e:
                    st.markdown(f'<div class="err-box">❌ 발송 실패: {e}</div>',
                                unsafe_allow_html=True)

        if st.session_state.get("send_done"):
            if st.button("🆕 신규 문서 작성", use_container_width=True, key="reset_btn"):
                for k in ("send_done", "pre_name", "pre_email",
                          "upload_pdf", "rec_name", "rec_email", "upload_ssn"):
                    st.session_state.pop(k, None)
                st.rerun()




# ════════════════════════════════════════════════════════════════════════════════
# TAB 2: 다건 발송
# ════════════════════════════════════════════════════════════════════════════════
with tab_bulk:
    st.markdown("여러 PDF를 한 번에 업로드하고 수신자 정보를 입력하여 일괄 발송합니다.")
    st.markdown("---")

    bulk_files = st.file_uploader(
        "근로계약서 PDF (여러 개 선택 가능)",
        type=["pdf"],
        accept_multiple_files=True,
        key="bulk_pdfs",
    )

    if bulk_files:
        # ── 서명 위치 공통 설정 ────────────────────────────────────────────
        with st.expander("⚙️ 서명 위치 설정 (전체 파일 공통 적용)"):
            b_sl, b_pv = st.columns([1, 2])
            with b_sl:
                b_sig_x = st.slider("X 위치", 0.0, 900.0, st.session_state.get("b_sig_x", 680.0), step=1.0, key="b_sig_x")
                b_sig_y = st.slider("Y 위치 (하단 기준)", 0.0, 400.0, st.session_state.get("b_sig_y", 18.0), step=1.0, key="b_sig_y")
                b_sig_w = st.slider("서명 너비", 10.0, 300.0, st.session_state.get("b_sig_w", 80.0), step=1.0, key="b_sig_w")
                b_sig_h = st.slider("서명 높이", 10.0, 150.0, st.session_state.get("b_sig_h", 50.0), step=1.0, key="b_sig_h")
                st.caption("첫 번째 파일을 업로드하면 미리보기가 활성화됩니다.")
                if bulk_files:
                    try:
                        from modules.web_signer import render_page_with_sig_preview
                        bpv_bytes, bpw, bph = render_page_with_sig_preview(
                            bulk_files[0].getvalue(), -1,
                            b_sig_x, b_sig_y, b_sig_w, b_sig_h
                        )
                        if bpv_bytes:
                            with b_pv:
                                st.image(bpv_bytes, caption=f"첫 번째 파일 미리보기 (페이지: {bpw:.0f}×{bph:.0f}pt)", use_container_width=True)
                    except Exception:
                        pass

        st.markdown(f"**총 {len(bulk_files)}건** — 각 파일의 수신자 정보를 입력해 주세요.")

        bulk_rows = []
        for idx, f in enumerate(bulk_files):
            name_val  = st.session_state.get(f"b_name_{idx}", "")
            email_val = st.session_state.get(f"b_email_{idx}", "")
            ssn_val   = st.session_state.get(f"b_ssn_{idx}", "")

            # 유효성 아이콘
            ok_name  = bool(name_val.strip())
            ok_email = "@" in email_val and "." in email_val
            ok_ssn   = len(ssn_val.strip()) == 7 and ssn_val.strip().isdigit()
            status_icon = "✅" if (ok_name and ok_email and ok_ssn) else "⬜"

            st.markdown(f"""
            <div style="border:1px solid #D0D8E4;border-radius:10px;
                        padding:14px 18px 6px 18px;margin:10px 0;
                        background:#FAFCFF;">
              <span style="font-size:13px;color:#555;font-weight:600;">
                {status_icon} &nbsp;#{idx+1} &nbsp;
                <span style="color:#1B3A6B;">📄 {f.name[:40]}{'…' if len(f.name)>40 else ''}</span>
              </span>
            </div>
            """, unsafe_allow_html=True)

            col1, col2, col3 = st.columns([2, 3, 2])
            with col1:
                name = st.text_input("수신자 성명 *", key=f"b_name_{idx}",
                                     placeholder="예: 홍길동")
            with col2:
                email = st.text_input("이메일 *", key=f"b_email_{idx}",
                                      placeholder="예: hong@goodhospital.or.kr")
            with col3:
                ssn = st.text_input("주민번호 뒷 7자리 *", key=f"b_ssn_{idx}",
                                    placeholder="예: 1234567", max_chars=7, type="password")

            bulk_rows.append({"file": f, "name": name, "email": email, "ssn": ssn})

        st.markdown("---")

        # 유효성 검사
        errors = []
        for i, row in enumerate(bulk_rows):
            if not row["name"].strip():
                errors.append(f"{i+1}번: 성명 필요")
            if "@" not in row["email"]:
                errors.append(f"{i+1}번: 이메일 오류")
            if len(row["ssn"].strip()) != 7 or not row["ssn"].strip().isdigit():
                errors.append(f"{i+1}번: 주민번호 7자리 필요")

        bulk_ready = len(errors) == 0

        if errors:
            for e in errors[:3]:
                st.caption(f"⬜ {e}")
            if len(errors) > 3:
                st.caption(f"… 외 {len(errors)-3}건")

        bulk_send_btn = st.button(
            f"✍️ 전체 {len(bulk_files)}건 서명 요청 발송",
            disabled=not bulk_ready,
            use_container_width=True,
            type="primary",
            key="bulk_send_btn",
        )

        if not bulk_ready:
            st.caption("모든 항목을 입력하면 발송 버튼이 활성화됩니다.")

        if bulk_send_btn and bulk_ready:
            st.session_state["bulk_confirm"] = True

        if st.session_state.get("bulk_confirm") and not st.session_state.get("bulk_done"):
            names_preview = ", ".join(r["name"] for r in bulk_rows if r["name"].strip())
            st.warning(f"**최종 전송하시겠습니까?**\n\n총 **{len(bulk_rows)}건** 발송 대상: {names_preview}")
            bok_col, bcancel_col = st.columns(2)
            bconfirmed = bok_col.button("✅ 확인", use_container_width=True, key="bulk_confirm_ok", type="primary")
            bcancelled = bcancel_col.button("❌ 취소", use_container_width=True, key="bulk_confirm_cancel")
            if bcancelled:
                st.session_state.pop("bulk_confirm", None)
                st.rerun()
            if not bconfirmed:
                st.stop()

        if st.session_state.get("bulk_confirm") and not st.session_state.get("bulk_done"):
            st.session_state.pop("bulk_confirm", None)
            from modules.pdf_encryptor import encrypt_pdf
            from modules.email_sender import send_sign_request
            from modules.web_signer import create_signing_token, build_sign_url
            from modules.db_logger import log_email_sent
            from datetime import datetime as _dt

            progress = st.progress(0)
            status   = st.empty()
            success_count = 0
            fail_msgs = []

            for idx, row in enumerate(bulk_rows):
                status.caption(f"발송 중… {idx+1}/{len(bulk_rows)}  {row['name']}")
                try:
                    date_str  = _dt.now().strftime("%Y%m%d")
                    raw_name  = f"{row['name'].strip()}_근로계약서_{date_str}_원본.pdf"
                    save_name = f"{row['name'].strip()}_근로계약서_{date_str}.pdf"
                    raw_path  = os.path.join(os.path.abspath(config.OUTPUT_DIR), raw_name)
                    save_path = os.path.join(os.path.abspath(config.OUTPUT_DIR), save_name)

                    with open(raw_path, "wb") as fp:
                        fp.write(row["file"].getbuffer())
                    encrypt_pdf(raw_path, save_path, row["ssn"].strip())
                    os.remove(raw_path)

                    emp_info = {
                        "사번":   "",
                        "성명":   row["name"].strip(),
                        "이메일": row["email"].strip(),
                    }
                    token    = create_signing_token(
                        emp_info, save_path,
                        sig_x=st.session_state.get("b_sig_x", 680.0),
                        sig_y=st.session_state.get("b_sig_y", 18.0),
                        sig_w=st.session_state.get("b_sig_w", 80.0),
                        sig_h=st.session_state.get("b_sig_h", 50.0),
                        sig_page=int(st.session_state.get("b_sig_page", -1)),
                    )
                    sign_url = build_sign_url(token)
                    send_sign_request(emp_info, save_path, sign_url)
                    log_email_sent(emp_info, save_name, token)
                    success_count += 1
                except Exception as e:
                    fail_msgs.append(f"{row['name']}: {e}")

                progress.progress((idx + 1) / len(bulk_rows))

            progress.empty()
            status.empty()

            if success_count:
                st.markdown(f"""
                <div class="ok-box">
                  <b>✅ {success_count}건 발송 완료!</b><br>
                  수신자들에게 서명 요청 이메일이 발송되었습니다.
                </div>
                """, unsafe_allow_html=True)
            for fm in fail_msgs:
                st.markdown(f'<div class="err-box">❌ 발송 실패: {fm}</div>', unsafe_allow_html=True)

            if not fail_msgs:
                st.session_state["bulk_done"] = True

        if st.session_state.get("bulk_done"):
            if st.button("🆕 새 다건 발송", use_container_width=True, key="bulk_reset_btn"):
                for k in list(st.session_state.keys()):
                    if k.startswith("b_name_") or k.startswith("b_email_") or k.startswith("b_ssn_"):
                        st.session_state.pop(k, None)
                st.session_state.pop("bulk_done", None)
                st.session_state.pop("bulk_pdfs", None)
                st.rerun()
    else:
        st.info("PDF 파일을 위에서 선택하면 수신자 입력 폼이 나타납니다.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3: 발송 이력 (관리자 전용)
# ════════════════════════════════════════════════════════════════════════════════
with tab_logs:
    logout_col, _, ref_col = st.columns([1, 4, 1])
    with logout_col:
        if st.button("🔓 로그아웃", key="admin_logout"):
            st.session_state.pop("admin_logged_in", None)
            st.rerun()
    with ref_col:
        st.button("🔄 새로고침", key="refresh_logs")

    try:
        from modules.db_logger import get_recent_logs
        import pandas as pd

        logs = get_recent_logs(100)
        if not logs:
            st.info("발송 이력이 없습니다.")
        else:
            df = pd.DataFrame(logs)
            df["상태"] = df["status"].map({"sent": "📤 발송", "signed": "✅ 서명완료"}).fillna(df["status"])
            df = df.rename(columns={
                "employee_id":   "사번",
                "employee_name": "성명",
                "email":         "이메일",
                "filename":      "파일명",
                "sent_at":       "발송일시",
                "signed_at":     "서명완료일",
            })
            st.dataframe(
                df[["사번", "성명", "이메일", "파일명", "발송일시", "상태", "서명완료일"]],
                use_container_width=True,
                hide_index=True,
            )

            m1, m2, m3 = st.columns(3)
            m1.metric("전체 발송",  len(df))
            m2.metric("서명 완료",  (df["상태"] == "✅ 서명완료").sum())
            m3.metric("서명 대기",  (df["상태"] == "📤 발송").sum())

    except Exception as e:
        st.error(f"이력 조회 오류: {e}")

    st.markdown("---")
    st.markdown("#### 서명 토큰 현황")
    if st.button("토큰 현황 조회", key="token_status"):
        try:
            import sqlite3, pandas as pd
            con  = sqlite3.connect(config.DB_PATH)
            rows = con.execute("""
                SELECT employee_id, employee_name, email,
                       created_at, expires_at, signed_at
                FROM sign_tokens ORDER BY created_at DESC LIMIT 30
            """).fetchall()
            con.close()
            if rows:
                df2 = pd.DataFrame(rows, columns=["사번","성명","이메일","발급일","만료일","서명일"])
                df2["상태"] = df2["서명일"].apply(lambda x: "✅ 완료" if x else "⏳ 대기")
                st.dataframe(df2, use_container_width=True, hide_index=True)
            else:
                st.info("서명 토큰이 없습니다.")
        except Exception as e:
            st.error(f"조회 오류: {e}")
