"""좋은문화병원 근로계약서 자동화 시스템 — 관리자 앱 (포트 8501)."""
from __future__ import annotations

import os
import time
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)
from config import config

# ── 페이지 설정 ────────────────────────────────────────────────────────────────
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
                    token    = create_signing_token(emp_info, save_path)
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
                    token    = create_signing_token(emp_info, save_path)
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
