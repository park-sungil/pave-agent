from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from shared.db import execute_query

logger = logging.getLogger(__name__)


@tool
def execute_sql(sql: str) -> str:
    """Oracle SQL을 실행하고 결과를 반환한다.

    Args:
        sql: 실행할 SELECT SQL문. antsdb. 스키마 접두사 포함, FETCH FIRST N ROWS ONLY 필수.

    Returns:
        조회 결과 JSON 문자열. 에러 시 error 필드 포함.
    """
    sql = sql.strip()
    if not sql.upper().startswith("SELECT"):
        return json.dumps({"error": "SELECT 문만 허용됩니다."}, ensure_ascii=False)

    try:
        rows = execute_query(sql)
        columns = list(rows[0].keys()) if rows else []
        data = [list(r.values()) for r in rows]
        return json.dumps({
            "columns": columns,
            "data": data,
            "row_count": len(rows),
            "sql": sql,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("SQL 실행 에러: %s", e)
        return json.dumps({"error": str(e), "sql": sql}, ensure_ascii=False)
