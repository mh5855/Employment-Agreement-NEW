"""직원명단 및 급여테이블 로드 및 매핑 모듈."""
from __future__ import annotations

import io
from typing import Optional

import pandas as pd


EMPLOYEE_COLUMNS = [
    "사번", "성명", "주민등록번호", "소속부서", "직급", "연차", "입사일",
    "이메일", "주소", "근로계약기간",
]

SALARY_COLUMNS = [
    "소속", "직급", "연차", "기본급",
    "간호간병평가인센티브", "간호간병특별수당", "처우개선비",
    "특별간호수당", "간호근속수당", "연장수당2",
    "근로시간", "휴게시간",
]

SALARY_ITEMS = [
    "기본급", "간호간병평가인센티브", "간호간병특별수당",
    "처우개선비", "특별간호수당", "간호근속수당", "연장수당2",
]


def _read_file(source) -> pd.DataFrame:
    """파일 경로 또는 업로드 바이트 스트림을 DataFrame으로 읽기."""
    if isinstance(source, (str,)):
        if source.endswith(".csv"):
            return pd.read_csv(source, dtype=str)
        return pd.read_excel(source, dtype=str)
    # Streamlit UploadedFile 또는 bytes
    raw = source.read() if hasattr(source, "read") else source
    buf = io.BytesIO(raw)
    try:
        return pd.read_excel(buf, dtype=str)
    except Exception:
        buf.seek(0)
        return pd.read_csv(buf, dtype=str)


def load_employees(source) -> pd.DataFrame:
    """직원명단 로드 후 컬럼 검증."""
    df = _read_file(source)
    df.columns = df.columns.str.strip()
    missing = [c for c in EMPLOYEE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"직원명단에 필수 컬럼이 없습니다: {missing}")
    df["사번"] = df["사번"].str.strip()
    return df


def load_salary_table(source) -> pd.DataFrame:
    """급여테이블 로드 후 컬럼 검증."""
    df = _read_file(source)
    df.columns = df.columns.str.strip()
    missing = [c for c in SALARY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"급여테이블에 필수 컬럼이 없습니다: {missing}")
    return df


def find_employee(employees: pd.DataFrame, emp_id: str) -> Optional[dict]:
    """사번으로 직원 정보 조회. 없으면 None 반환."""
    row = employees[employees["사번"] == emp_id.strip()]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def find_salary(salary_table: pd.DataFrame, dept: str, position: str, years: str) -> Optional[dict]:
    """소속+직급+연차로 급여 정보 조회. 없으면 None 반환."""
    mask = (
        (salary_table["소속"].str.strip() == dept.strip()) &
        (salary_table["직급"].str.strip() == position.strip()) &
        (salary_table["연차"].str.strip() == years.strip())
    )
    row = salary_table[mask]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def compute_salary_summary(salary: dict) -> dict:
    """월 합계 및 연봉 합계 계산."""
    monthly_total = 0
    for item in SALARY_ITEMS:
        try:
            val = salary.get(item, "0") or "0"
            monthly_total += int(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            pass
    annual_total = monthly_total * 12
    return {
        "salary_items": {k: salary.get(k, "0") for k in SALARY_ITEMS},
        "monthly_total": monthly_total,
        "annual_total": annual_total,
        "working_hours": salary.get("근로시간", ""),
        "break_time": salary.get("휴게시간", ""),
    }
