from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def stats_tool(data_json: str, columns: str, group_by: str = "") -> str:
    """쿼리 결과 데이터에 대한 기술 통계를 계산한다.

    Args:
        data_json: execute_sql이 반환한 JSON 문자열 (columns + data 포함)
        columns: 통계를 계산할 컬럼명 (쉼표 구분). 예: "FREQ_GHZ,D_POWER"
        group_by: 그룹별 통계를 원할 경우 그룹 컬럼명. 예: "CORNER"

    Returns:
        통계 결과 JSON 문자열.
    """
    try:
        data = json.loads(data_json)
        col_names = data.get("columns", [])
        rows = data.get("data", [])

        if not rows:
            return json.dumps({"error": "데이터가 비어있습니다."})

        target_cols = [c.strip() for c in columns.split(",")]
        group_col = group_by.strip() if group_by else None
        col_idx = {name: i for i, name in enumerate(col_names)}

        groups: dict[str, list] = {}
        for row in rows:
            key = str(row[col_idx[group_col]]) if group_col and group_col in col_idx else "_all"
            groups.setdefault(key, []).append(row)

        result = {}
        for group_key, group_rows in groups.items():
            group_stats = {}
            for tc in target_cols:
                if tc not in col_idx:
                    group_stats[tc] = {"error": f"컬럼 '{tc}' 없음"}
                    continue
                idx = col_idx[tc]
                values = []
                for r in group_rows:
                    v = r[idx]
                    if v is not None:
                        try:
                            values.append(float(v))
                        except (ValueError, TypeError):
                            pass
                if not values:
                    group_stats[tc] = {"error": "숫자 데이터 없음"}
                    continue

                values.sort()
                n = len(values)
                mean = sum(values) / n
                variance = sum((x - mean) ** 2 for x in values) / n
                std = variance ** 0.5

                group_stats[tc] = {
                    "count": n,
                    "mean": round(mean, 6),
                    "std": round(std, 6),
                    "min": round(values[0], 6),
                    "max": round(values[-1], 6),
                    "median": round(values[n // 2], 6),
                    "p25": round(values[n // 4], 6) if n >= 4 else None,
                    "p75": round(values[3 * n // 4], 6) if n >= 4 else None,
                }
            result[group_key] = group_stats

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error("stats_tool 에러: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
