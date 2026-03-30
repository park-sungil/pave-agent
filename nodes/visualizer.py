from __future__ import annotations

import logging
from typing import Any

from state import PaveAgentState, ChartSpec

logger = logging.getLogger(__name__)

# 분석 모드 → 기본 차트 타입 매핑
DEFAULT_CHART_MAP = {
    "compare": "grouped_bar",
    "summarize": "grouped_bar",
    "sensitivity": "line",
    "worst_case": "grouped_bar",
    "tradeoff": "grouped_bar",
    "correlation": "heatmap",
    "interpolation": "scatter",
    "trend": "line",
    "anomaly": "scatter",
    "optimization": "efficiency_line",
}


def _build_grouped_bar(analysis: dict, title: str) -> dict:
    """Grouped bar chart Plotly spec"""
    summary = analysis.get("summary_table", [])
    chart_data = analysis.get("chart_data", {})
    groups = chart_data.get("groups", [])
    metrics = chart_data.get("metrics", [])

    data = []
    if groups:
        for group in groups:
            y_vals = []
            x_labels = []
            for row in summary:
                metric = row.get("metric", "")
                x_labels.append(metric)
                val = None
                for k, v in row.items():
                    if group in str(k) and k != "metric":
                        val = v
                        break
                y_vals.append(val or 0)

            data.append({
                "type": "bar",
                "name": str(group),
                "x": x_labels,
                "y": y_vals,
            })
    else:
        # summarize 모드: metric별 mean 값으로 단일 bar
        x_labels = [row.get("metric", "") for row in summary]
        y_vals = [row.get("mean", 0) for row in summary]
        data.append({
            "type": "bar",
            "name": "값",
            "x": x_labels,
            "y": y_vals,
        })

    return {
        "data": data,
        "layout": {
            "title": {"text": title},
            "barmode": "group",
            "xaxis": {"title": "Metric"},
            "yaxis": {"title": "Value"},
        },
    }


def _build_line(analysis: dict, title: str) -> dict:
    """Line chart Plotly spec"""
    summary = analysis.get("summary_table", [])
    chart_data = analysis.get("chart_data", {})
    x_axis = chart_data.get("x_axis", "")

    data = []
    if analysis.get("mode") == "sensitivity":
        for row in summary:
            metric = row.get("metric", "")
            points = row.get("points", [])
            data.append({
                "type": "scatter",
                "mode": "lines+markers",
                "name": metric,
                "x": [p["axis_value"] for p in points],
                "y": [p["mean"] for p in points],
            })
    elif analysis.get("mode") == "trend":
        metrics = chart_data.get("metrics", [])
        for m in metrics:
            data.append({
                "type": "scatter",
                "mode": "lines+markers",
                "name": m,
                "x": [str(row.get("PDK_ID", "")) for row in summary],
                "y": [row.get(m, 0) for row in summary],
            })

    return {
        "data": data,
        "layout": {
            "title": {"text": title},
            "xaxis": {"title": x_axis or "X"},
            "yaxis": {"title": "Value"},
        },
    }


def _build_scatter(analysis: dict, title: str) -> dict:
    """Scatter chart Plotly spec"""
    summary = analysis.get("summary_table", [])

    data = []
    if analysis.get("mode") == "anomaly":
        # 클러스터별 이상치 scatter
        for cluster in summary:
            samples = cluster.get("samples", [])
            data.append({
                "type": "scatter",
                "mode": "markers",
                "name": cluster.get("cluster", ""),
                "x": [s.get("metric", "") for s in samples],
                "y": [s.get("z_score", 0) for s in samples],
                "text": [f"delta={s.get('delta_pct', 0)}%" for s in samples],
            })
    elif analysis.get("mode") == "interpolation":
        for row in summary:
            metric = row.get("metric", "")
            measured = row.get("measured", [])
            interpolated = row.get("interpolated", [])
            data.append({
                "type": "scatter",
                "mode": "markers",
                "name": f"{metric} (실측)",
                "x": [p[0] for p in measured],
                "y": [p[1] for p in measured],
            })
            data.append({
                "type": "scatter",
                "mode": "lines",
                "name": f"{metric} (보간)",
                "x": [p["x"] for p in interpolated],
                "y": [p["y"] for p in interpolated],
                "line": {"dash": "dash"},
            })

    return {
        "data": data,
        "layout": {
            "title": {"text": title},
            "xaxis": {"title": "X"},
            "yaxis": {"title": "Value"},
        },
    }


def _build_heatmap(analysis: dict, title: str) -> dict:
    """Heatmap Plotly spec (correlation)"""
    summary = analysis.get("summary_table", [])
    chart_data = analysis.get("chart_data", {})
    metrics = chart_data.get("metrics", [])

    # correlation matrix 재구성
    n = len(metrics)
    z = [[1.0] * n for _ in range(n)]
    for row in summary:
        x_idx = metrics.index(row["x"]) if row["x"] in metrics else -1
        y_idx = metrics.index(row["y"]) if row["y"] in metrics else -1
        if x_idx >= 0 and y_idx >= 0:
            z[x_idx][y_idx] = row["correlation"]
            z[y_idx][x_idx] = row["correlation"]

    return {
        "data": [{
            "type": "heatmap",
            "z": z,
            "x": metrics,
            "y": metrics,
            "colorscale": "RdBu",
            "zmid": 0,
        }],
        "layout": {
            "title": {"text": title},
        },
    }


def _build_efficiency_line(analysis: dict, title: str) -> dict:
    """Efficiency line chart: X=sweep축, Y=효율비 (delta_perf/delta_leakage)"""
    chart_data = analysis.get("chart_data", {})
    axis = chart_data.get("axis", "VDD")
    efficiency_rows = chart_data.get("efficiency_rows", [])
    perf_metric = chart_data.get("perf_metric", "FREQ_GHZ")
    leak_metric = chart_data.get("leak_metric", "IDDQ_NA")
    summary = analysis.get("summary_table", [])

    x_eff = [str(r[axis]) for r in efficiency_rows]
    y_eff = [r.get("efficiency_ratio") or 0 for r in efficiency_rows]

    # 원본 perf / leak 값도 보조 trace로 표시
    x_raw = [str(r[axis]) for r in summary]
    y_perf = [r.get(perf_metric, 0) for r in summary]
    y_leak = [r.get(leak_metric, 0) for r in summary]

    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": f"효율비 ({perf_metric}/{leak_metric})",
                "x": x_eff,
                "y": y_eff,
            },
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": perf_metric,
                "x": x_raw,
                "y": y_perf,
                "yaxis": "y2",
            },
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": leak_metric,
                "x": x_raw,
                "y": y_leak,
                "yaxis": "y2",
            },
        ],
        "layout": {
            "title": {"text": title},
            "xaxis": {"title": axis},
            "yaxis": {"title": "효율비"},
            "yaxis2": {"title": "절대값", "overlaying": "y", "side": "right"},
        },
    }


def _build_pareto_scatter(analysis: dict, title: str) -> dict:
    """Pareto scatter: X=leakage, Y=performance, Pareto frontier 오버레이"""
    chart_data = analysis.get("chart_data", {})
    x_metric = chart_data.get("x_metric", "IDDQ_NA")
    y_metric = chart_data.get("y_metric", "FREQ_GHZ")
    group_cols = chart_data.get("group_cols", [])
    pareto_pts = chart_data.get("pareto_points", [])
    summary = analysis.get("summary_table", [])

    # 전체 점
    x_all = [r.get(x_metric, 0) for r in summary]
    y_all = [r.get(y_metric, 0) for r in summary]
    labels = [", ".join(f"{c}={r.get(c,'')}" for c in group_cols) for r in summary]

    # Pareto 점 강조
    x_par = [r.get(x_metric, 0) for r in pareto_pts]
    y_par = [r.get(y_metric, 0) for r in pareto_pts]

    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "전체 조합",
                "x": x_all,
                "y": y_all,
                "text": labels,
                "marker": {"size": 8, "color": "lightblue"},
            },
            {
                "type": "scatter",
                "mode": "markers+lines",
                "name": "Pareto Frontier",
                "x": x_par,
                "y": y_par,
                "marker": {"size": 12, "color": "red"},
            },
        ],
        "layout": {
            "title": {"text": title},
            "xaxis": {"title": x_metric},
            "yaxis": {"title": y_metric},
        },
    }


# chart type → builder 매핑
CHART_BUILDERS = {
    "grouped_bar": _build_grouped_bar,
    "line": _build_line,
    "scatter": _build_scatter,
    "heatmap": _build_heatmap,
    "efficiency_line": _build_efficiency_line,
    "pareto_scatter": _build_pareto_scatter,
}


def visualizer(state: PaveAgentState) -> dict:
    """Plotly JSON 차트 스펙 생성 (코드 기반)"""
    analysis = state.get("analysis_result")
    interpretation = state.get("interpretation")

    if not analysis:
        return {"chart_specs": []}

    mode = analysis.get("mode", "")
    charts: list[ChartSpec] = []

    # interpreter의 suggested_charts 우선 사용
    suggested = []
    if interpretation:
        suggested = interpretation.get("suggested_charts") or []

    if suggested:
        for s in suggested:
            chart_type = s.get("type", DEFAULT_CHART_MAP.get(mode, "grouped_bar"))
            title = s.get("title", f"{mode} 분석 결과")
            builder = CHART_BUILDERS.get(chart_type)
            if not builder:
                # 미지원 타입은 mode 기반 기본 차트로 fallback
                chart_type = DEFAULT_CHART_MAP.get(mode, "grouped_bar")
                builder = CHART_BUILDERS.get(chart_type)
            if builder:
                plotly_spec = builder(analysis, title)
                charts.append(ChartSpec(
                    chart_type=chart_type,
                    title=title,
                    plotly_spec=plotly_spec,
                ))
    else:
        # 기본 차트
        chart_type = DEFAULT_CHART_MAP.get(mode, "grouped_bar")
        title = f"{mode} 분석 결과"
        builder = CHART_BUILDERS.get(chart_type)
        if builder:
            plotly_spec = builder(analysis, title)
            charts.append(ChartSpec(
                chart_type=chart_type,
                title=title,
                plotly_spec=plotly_spec,
            ))

    return {"chart_specs": charts}
