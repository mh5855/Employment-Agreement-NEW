"""이메일 발송 이력 DB 로깅 (SQLite).
주민등록번호는 절대 저장하지 않는다.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import config

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS email_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id      TEXT    NOT NULL,
    employee_name    TEXT    NOT NULL,
    email            TEXT    NOT NULL,
    filename         TEXT    NOT NULL,
    sent_at          TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'sent',
    esign_request_id TEXT,
    signed_at        TEXT,
    drive_file_id    TEXT
);
CREATE TABLE IF NOT EXISTS sign_tokens (
    token          TEXT PRIMARY KEY,
    employee_id    TEXT NOT NULL,
    employee_name  TEXT NOT NULL,
    email          TEXT NOT NULL,
    pdf_path       TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    sig_x           REAL    NOT NULL DEFAULT 680.0,
    sig_y           REAL    NOT NULL DEFAULT 18.0,
    sig_w           REAL    NOT NULL DEFAULT 80.0,
    sig_h           REAL    NOT NULL DEFAULT 50.0,
    sig_page        INTEGER NOT NULL DEFAULT -1,
    signed_at      TEXT,
    signed_pdf_path TEXT
);
"""


@contextmanager
def _conn():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_CREATE_SQL)   # 다중 구문 허용
        con.commit()
        # 기존 sign_tokens 테이블 마이그레이션 (컬럼 없으면 추가)
        for col, typ, default in [
            ("sig_x","REAL","680.0"), ("sig_y","REAL","18.0"),
            ("sig_w","REAL","80.0"), ("sig_h","REAL","50.0"),
            ("sig_page","INTEGER","-1"),
        ]:
            try:
                con.execute(f"ALTER TABLE sign_tokens ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}")
                con.commit()
            except Exception:
                pass
        yield con
    finally:
        con.close()


def log_email_sent(
    employee: dict,
    filename: str,
    esign_request_id: str = "",
) -> int:
    """발송 이력 기록. 반환값: 레코드 ID."""
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO email_log
               (employee_id, employee_name, email, filename, sent_at, status, esign_request_id)
               VALUES (?, ?, ?, ?, ?, 'sent', ?)""",
            (
                employee["사번"],
                employee["성명"],
                employee["이메일"],
                filename,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                esign_request_id,
            ),
        )
        con.commit()
        return cur.lastrowid


def log_signed(log_id: int, drive_file_id: str = "") -> None:
    """서명 완료 및 드라이브 업로드 이력 갱신."""
    with _conn() as con:
        con.execute(
            """UPDATE email_log
               SET status='signed', signed_at=?, drive_file_id=?
               WHERE id=?""",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                drive_file_id,
                log_id,
            ),
        )
        con.commit()


def get_recent_logs(limit: int = 50) -> list[dict]:
    """최근 발송 이력 조회 (주민등록번호 미포함)."""
    with _conn() as con:
        rows = con.execute(
            """SELECT id, employee_id, employee_name, email, filename,
                      sent_at, status, esign_request_id, signed_at, drive_file_id
               FROM email_log
               ORDER BY id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── 서명 토큰 관리 ─────────────────────────────────────────────────────────────
def create_sign_token(
    token: str,
    employee_id: str,
    employee_name: str,
    email: str,
    pdf_path: str,
    expires_days: int = 14,
    sig_x: float = 680.0,
    sig_y: float = 18.0,
    sig_w: float = 80.0,
    sig_h: float = 50.0,
    sig_page: int = -1,
) -> None:
    now = datetime.now()
    expires = (now + __import__("datetime").timedelta(days=expires_days)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as con:
        con.execute(
            """INSERT OR REPLACE INTO sign_tokens
               (token, employee_id, employee_name, email, pdf_path, created_at, expires_at,
                sig_x, sig_y, sig_w, sig_h, sig_page)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (token, employee_id, employee_name, email, pdf_path,
             now.strftime("%Y-%m-%d %H:%M:%S"), expires,
             sig_x, sig_y, sig_w, sig_h, sig_page),
        )
        con.commit()


def get_sign_token(token: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM sign_tokens WHERE token=?", (token,)
        ).fetchone()
        return dict(row) if row else None


def mark_token_signed(token: str, signed_pdf_path: str) -> None:
    with _conn() as con:
        con.execute(
            """UPDATE sign_tokens SET signed_at=?, signed_pdf_path=? WHERE token=?""",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), signed_pdf_path, token),
        )
        con.commit()


def get_log_by_esign_id(request_id: str) -> dict | None:
    """모두싸인 request_id로 이력 조회."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM email_log WHERE esign_request_id=?",
            (request_id,),
        ).fetchone()
        return dict(row) if row else None
