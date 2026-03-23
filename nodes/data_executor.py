from __future__ import annotations

import logging

from shared.db import execute_query
from state import PaveAgentState, QueryResult

logger = logging.getLogger(__name__)


def data_executor(state: PaveAgentState) -> dict:
    """SQL 실행 + 결과 수집 (코드 기반)"""
    query_plan = state["query_plan"]
    is_bulk = query_plan["is_bulk"]
    timeout = 60 if is_bulk else 30

    datasets = []
    warnings = []
    total_rows = 0

    for q in query_plan["queries"]:
        sql = q["sql"]
        pdk_id = q["pdk_id"]
        purpose = q["purpose"]

        try:
            rows = execute_query(sql, timeout=timeout)
            row_count = len(rows)
            total_rows += row_count

            if row_count == 0:
                warnings.append(f"{purpose}: 결과 없음")

            datasets.append({
                "pdk_id": pdk_id,
                "purpose": purpose,
                "rows": rows,
                "row_count": row_count,
            })

        except Exception as e:
            logger.error("SQL 실행 실패 (%s): %s", purpose, e)
            return {"error": f"데이터 조회 실패 ({purpose}): {e}"}

    if total_rows == 0:
        return {"error": "조회 결과가 없습니다. 조건을 확인해주세요."}

    return {
        "query_result": QueryResult(
            datasets=datasets,
            total_rows=total_rows,
            warnings=warnings,
        ),
    }
