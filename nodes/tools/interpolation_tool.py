from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def interpolation_tool(
    data_json: str,
    x_column: str,
    y_column: str,
    target_x: float,
    method: str = "linear",
) -> str:
    """x_column 기준으로 y_column 값을 보간한다.

    Args:
        data_json: execute_sql이 반환한 JSON 문자열
        x_column: 독립변수 컬럼명. 예: "VDD"
        y_column: 종속변수 컬럼명. 예: "FREQ_GHZ"
        target_x: 보간할 x 값. 예: 0.81
        method: 보간 방법 — "linear" 또는 "spline"

    Returns:
        보간 결과 JSON. target_x, estimated_y 포함.
    """
    try:
        data = json.loads(data_json)
        col_names = data.get("columns", [])
        rows = data.get("data", [])
        col_idx = {name: i for i, name in enumerate(col_names)}

        if x_column not in col_idx or y_column not in col_idx:
            return json.dumps({"error": f"컬럼을 찾을 수 없음: {x_column}, {y_column}"})

        xi, yi = col_idx[x_column], col_idx[y_column]
        points = []
        for row in rows:
            try:
                points.append((float(row[xi]), float(row[yi])))
            except (ValueError, TypeError):
                continue

        if len(points) < 2:
            return json.dumps({"error": "보간에 필요한 데이터 포인트가 부족합니다 (최소 2개)."})

        points.sort(key=lambda p: p[0])
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        extrapolation = target_x < xs[0] or target_x > xs[-1]

        if method == "linear" or len(points) < 4:
            estimated_y = _linear_interp(xs, ys, target_x)
            used_method = "linear"
        else:
            estimated_y = _polynomial_interp(xs, ys, target_x, degree=min(3, len(points) - 1))
            used_method = "polynomial"

        return json.dumps({
            "target_x": target_x,
            "x_column": x_column,
            "y_column": y_column,
            "estimated_y": round(estimated_y, 6),
            "method": used_method,
            "extrapolation": extrapolation,
            "data_points_used": len(points),
            "x_range": [round(xs[0], 6), round(xs[-1], 6)],
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("interpolation_tool 에러: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _linear_interp(xs: list[float], ys: list[float], target: float) -> float:
    for i in range(len(xs) - 1):
        if xs[i] <= target <= xs[i + 1]:
            t = (target - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0
            return ys[i] + t * (ys[i + 1] - ys[i])
    if target <= xs[0]:
        t = (target - xs[0]) / (xs[1] - xs[0]) if xs[1] != xs[0] else 0
        return ys[0] + t * (ys[1] - ys[0])
    else:
        t = (target - xs[-2]) / (xs[-1] - xs[-2]) if xs[-1] != xs[-2] else 0
        return ys[-2] + t * (ys[-1] - ys[-2])


def _polynomial_interp(xs: list[float], ys: list[float], target: float, degree: int = 3) -> float:
    indexed = sorted(range(len(xs)), key=lambda i: abs(xs[i] - target))
    selected = sorted(indexed[: degree + 1])
    sel_x = [xs[i] for i in selected]
    sel_y = [ys[i] for i in selected]
    result = 0.0
    for i in range(len(sel_x)):
        basis = 1.0
        for j in range(len(sel_x)):
            if i != j:
                basis *= (target - sel_x[j]) / (sel_x[i] - sel_x[j])
        result += sel_y[i] * basis
    return result
