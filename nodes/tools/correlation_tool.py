from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def correlation_tool(data_json: str, x_column: str, y_column: str) -> str:
    """두 숫자 컬럼 간의 피어슨 상관계수를 계산한다.

    Args:
        data_json: execute_sql이 반환한 JSON 문자열 (columns + data 포함)
        x_column: X축 컬럼명. 예: "VDD"
        y_column: Y축 컬럼명. 예: "FREQ_GHZ"

    Returns:
        상관분석 결과 JSON. correlation, count, interpretation 포함.
    """
    try:
        data = json.loads(data_json)
        col_names = data.get("columns", [])
        rows = data.get("data", [])
        col_idx = {name: i for i, name in enumerate(col_names)}

        if x_column not in col_idx or y_column not in col_idx:
            return json.dumps({
                "error": f"컬럼을 찾을 수 없음: {x_column}, {y_column}. 사용 가능: {col_names}"
            })

        xi, yi = col_idx[x_column], col_idx[y_column]
        pairs = []
        for row in rows:
            try:
                pairs.append((float(row[xi]), float(row[yi])))
            except (ValueError, TypeError):
                continue

        n = len(pairs)
        if n < 3:
            return json.dumps({"error": f"유효한 데이터 쌍이 부족합니다 ({n}개)."})

        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / n
        std_x = (sum((x - mean_x) ** 2 for x in xs) / n) ** 0.5
        std_y = (sum((y - mean_y) ** 2 for y in ys) / n) ** 0.5
        corr = cov / (std_x * std_y) if std_x and std_y else 0.0

        return json.dumps({
            "x_column": x_column,
            "y_column": y_column,
            "correlation": round(corr, 6),
            "count": n,
            "x_stats": {"mean": round(mean_x, 6), "std": round(std_x, 6)},
            "y_stats": {"mean": round(mean_y, 6), "std": round(std_y, 6)},
            "interpretation": (
                "강한 양의 상관" if corr > 0.7 else
                "보통 양의 상관" if corr > 0.3 else
                "약한/무상관" if corr > -0.3 else
                "보통 음의 상관" if corr > -0.7 else
                "강한 음의 상관"
            ),
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("correlation_tool 에러: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
