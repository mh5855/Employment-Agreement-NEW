"""직원용 전자서명 페이지 (포트 8502).

실행: python -m streamlit run sign_app.py --server.port 8502
직원은 이메일 링크 클릭 → 이 페이지에서 서명 → 자동 저장
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from config import config

st.set_page_config(
    page_title="근로계약서 전자서명",
    page_icon="✍️",
    layout="centered",
)

st.markdown("""
<style>
  .sign-header {
    background:linear-gradient(90deg,#1B3A6B,#2C5F8A);
    color:white;padding:20px 28px;border-radius:10px;margin-bottom:20px;
  }
  .info-box {
    background:#F5F8FC;border:1px solid #C5D8EC;
    padding:14px 18px;border-radius:8px;margin-bottom:16px;
  }
  .success-box {
    background:#E6F4EA;border:1px solid #34A853;
    padding:16px 20px;border-radius:8px;
  }
  .warn-box {
    background:#FEF7E0;border:1px solid #FBBC04;
    padding:14px 18px;border-radius:8px;
  }
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="sign-header">
  <h2 style="margin:0;">✍️ 근로계약서 전자서명</h2>
  <p style="margin:4px 0 0;opacity:.85;">{config.HOSPITAL_NAME} 인사총무팀</p>
</div>
""", unsafe_allow_html=True)


# ── URL 파라미터에서 토큰 추출 ─────────────────────────────────────────────────
params = st.query_params
token = params.get("token", "")

if not token:
    st.error("서명 링크가 올바르지 않습니다. 이메일의 링크를 다시 확인해 주세요.")
    st.stop()

# ── 토큰 유효성 확인 ───────────────────────────────────────────────────────────
from modules.db_logger import get_sign_token, mark_token_signed

token_info = get_sign_token(token)

if not token_info:
    st.error("유효하지 않은 서명 링크입니다.")
    st.stop()

if token_info.get("signed_at"):
    st.markdown(f"""
    <div class="success-box">
      <b>✅ 이미 서명이 완료되었습니다.</b><br>
      서명 일시: {token_info['signed_at']}<br>
      서명자: {token_info['employee_name']} 님
    </div>
    """, unsafe_allow_html=True)
    st.stop()

from datetime import datetime
if datetime.now().strftime("%Y-%m-%d %H:%M:%S") > token_info["expires_at"]:
    st.error(f"서명 링크가 만료되었습니다 (만료: {token_info['expires_at']}). 인사총무팀에 재발급을 요청해 주세요.")
    st.stop()

# ── 직원 정보 표시 ─────────────────────────────────────────────────────────────
emp_name = token_info["employee_name"]
emp_id   = token_info["employee_id"]
pdf_path = token_info["pdf_path"]

st.markdown(f"""
<div class="info-box">
  <b>서명 대상자</b><br>
  이름: <b>{emp_name}</b> 님 &nbsp;|&nbsp; 사번: {emp_id}
</div>
""", unsafe_allow_html=True)

st.info("아래 순서대로 진행해 주세요: ① 비밀번호 입력 → ② 서명 → ③ 서명 완료 버튼")

# ── STEP 1: 비밀번호 확인 (주민번호 뒷 7자리) ─────────────────────────────────
st.subheader("① PDF 비밀번호 확인")
st.caption("이메일에 안내된 비밀번호 (주민등록번호 뒷 7자리)를 입력하세요.")
password_input = st.text_input(
    "비밀번호 (주민번호 뒷 7자리)",
    type="password",
    max_chars=7,
    placeholder="예: 1234567",
)

# ── STEP 2: 서명 캔버스 ────────────────────────────────────────────────────────
st.subheader("② 아래 칸에 서명하세요")
st.caption("마우스 또는 터치로 서명을 입력해 주세요. 서명 후 완료 버튼을 누르세요.")

try:
    from streamlit_drawable_canvas import st_canvas
    canvas_result = st_canvas(
        fill_color="rgba(0,0,0,0)",
        stroke_width=3,
        stroke_color="#000000",       # 검정으로 명확하게
        background_color="#FAFAFA",   # 거의 흰색 (투명 처리 임계값 230 이상)
        height=160,
        width=680,
        drawing_mode="freedraw",
        display_toolbar=True,
        key="signature_canvas",
    )
except ImportError:
    st.error("streamlit-drawable-canvas 패키지가 설치되어 있지 않습니다.\npip install streamlit-drawable-canvas")
    st.stop()

# ── STEP 3: 서명 완료 처리 ────────────────────────────────────────────────────
st.subheader("③ 서명 완료")
submit = st.button("✅ 서명 완료 및 제출", use_container_width=True, type="primary")

if submit:
    # 입력값 검증
    if not password_input or len(password_input) != 7:
        st.warning("비밀번호를 7자리로 입력해 주세요.")
        st.stop()

    if canvas_result.image_data is None:
        st.warning("서명을 먼저 입력해 주세요.")
        st.stop()

    # 서명 캔버스 → PNG 바이트
    import numpy as np
    from PIL import Image as PILImage

    sig_arr = canvas_result.image_data.astype("uint8")
    if sig_arr.max() == 0:
        st.warning("서명이 비어 있습니다. 서명란에 서명을 입력해 주세요.")
        st.stop()

    sig_img = PILImage.fromarray(sig_arr, "RGBA")
    sig_buf = io.BytesIO()
    sig_img.save(sig_buf, format="PNG")
    sig_png_bytes = sig_buf.getvalue()

    # 서명 삽입 + 저장
    with st.spinner("서명을 처리하는 중입니다..."):
        try:
            from modules.web_signer import embed_signature_and_finalize
            from modules.email_sender import send_final_contract

            signed_path = pdf_path.replace(".pdf", f"_서명완료_{emp_id}.pdf")
            embed_signature_and_finalize(
                encrypted_pdf_path=pdf_path,
                pdf_password=password_input,
                signature_png_bytes=sig_png_bytes,
                output_path=signed_path,
            )

            # 토큰 완료 처리
            mark_token_signed(token, signed_path)

            # 구글 드라이브 업로드 (설정된 경우)
            drive_id = ""
            if config.GDRIVE_ROOT_FOLDER_ID:
                try:
                    from modules.drive_uploader import upload_signed_contract
                    pseudo_emp = {"사번": emp_id, "성명": emp_name, "이메일": token_info["email"]}
                    drive_id = upload_signed_contract(pseudo_emp, signed_path)
                except Exception as e:
                    st.warning(f"구글 드라이브 업로드 실패 (서명은 저장됨): {e}")

            # 최종 계약서 이메일 발송
            try:
                pseudo_emp = {"성명": emp_name, "이메일": token_info["email"]}
                send_final_contract(pseudo_emp, signed_path)
            except Exception as e:
                st.warning(f"최종 계약서 이메일 발송 실패: {e}")

            st.balloons()
            st.markdown(f"""
            <div class="success-box">
              <h3 style="margin:0 0 8px;">✅ 서명이 완료되었습니다!</h3>
              <p style="margin:0;">
                <b>{emp_name}</b> 님의 근로계약서 서명이 정상적으로 처리되었습니다.<br>
                서명 완료본이 이메일({token_info['email']})로 발송되었습니다.
              </p>
            </div>
            """, unsafe_allow_html=True)

            # 서명 완료 PDF 직접 다운로드 버튼
            if os.path.exists(signed_path):
                with open(signed_path, "rb") as f:
                    st.download_button(
                        label="📄 서명 완료 계약서 다운로드",
                        data=f.read(),
                        file_name=os.path.basename(signed_path),
                        mime="application/pdf",
                    )

        except ValueError as e:
            st.error(f"❌ {e}")
        except Exception as e:
            st.error(f"처리 중 오류가 발생했습니다: {e}")
        finally:
            # 비밀번호 메모리 제거
            del password_input
