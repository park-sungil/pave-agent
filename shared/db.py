from __future__ import annotations

from typing import Any

from config import settings


def _get_oracle_connection() -> Any:
    """Oracle 연결 반환"""
    import oracledb

    oracledb.init_oracle_client()
    return oracledb.connect(
        user=settings.oracle_user,
        password=settings.oracle_password,
        dsn=settings.oracle_dsn,
    )


def _validate_select_only(sql: str) -> None:
    """SELECT 문만 허용"""
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT"):
        raise ValueError(f"SELECT 문만 실행 가능합니다: {sql[:50]}...")


def execute_query(sql: str, timeout: int = 30) -> list[dict]:
    """SQL 실행 후 결과를 dict 리스트로 반환

    Args:
        sql: SELECT 문
        timeout: 타임아웃(초)

    Returns:
        결과 행의 dict 리스트
    """
    _validate_select_only(sql)

    conn = _get_oracle_connection()
    try:
        cursor = conn.cursor()
        cursor.callTimeout = timeout * 1000
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()
