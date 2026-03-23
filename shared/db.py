from __future__ import annotations

import re
import sqlite3
from typing import Any

from config import settings


def _get_sqlite_connection() -> sqlite3.Connection:
    """SQLite 연결 반환"""
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


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


def _adapt_sql_for_sqlite(sql: str) -> str:
    """Oracle SQL을 SQLite 호환으로 변환"""
    # antsdb. 스키마 접두사 제거
    adapted = re.sub(r"antsdb\.", "", sql, flags=re.IGNORECASE)
    # FETCH FIRST N ROWS ONLY → LIMIT N
    match = re.search(r"FETCH\s+FIRST\s+(\d+)\s+ROWS\s+ONLY", adapted, re.IGNORECASE)
    if match:
        limit = match.group(1)
        adapted = re.sub(
            r"FETCH\s+FIRST\s+\d+\s+ROWS\s+ONLY",
            f"LIMIT {limit}",
            adapted,
            flags=re.IGNORECASE,
        )
    return adapted


def execute_query(sql: str, timeout: int = 30) -> list[dict]:
    """SQL 실행 후 결과를 dict 리스트로 반환

    Args:
        sql: SELECT 문
        timeout: 타임아웃(초). Oracle에서만 적용.

    Returns:
        결과 행의 dict 리스트
    """
    _validate_select_only(sql)

    if settings.db_type == "sqlite":
        adapted = _adapt_sql_for_sqlite(sql)
        conn = _get_sqlite_connection()
        try:
            cursor = conn.execute(adapted)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()
    else:
        conn = _get_oracle_connection()
        try:
            cursor = conn.cursor()
            cursor.callTimeout = timeout * 1000
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()
