from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from state import PaveAgentState, AnalysisResult

logger = logging.getLogger(__name__)

# 주요 PPA metric 컬럼
METRIC_COLS = ["FREQ_GHZ", "D_POWER", "D_ENERGY", "ACCEFF_FF", "ACREFF_KOHM", "S_POWER", "IDDQ_NA"]
# 조건 컬럼 (매칭/그룹핑 키)
CONDITION_COLS = ["CELL", "DS", "VTH", "CORNER", "TEMP", "VDD", "CH", "WNS"]
# log 변환 대상 (exponential 분포)
LOG_METRICS = {"S_POWER", "IDDQ_NA"}


# ──────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────

def _datasets_to_df(datasets: list[dict]) -> pd.DataFrame:
    """datasets → 단일 DataFrame (PDK_ID 포함)"""
    frames = []
    for ds in datasets:
        if ds["rows"]:
            df = pd.DataFrame(ds["rows"])
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _available_metrics(df: pd.DataFrame) -> list[str]:
    """DataFrame에 존재하는 metric 컬럼 목록"""
    return [m for m in METRIC_COLS if m in df.columns]


def _pct_change(old: float, new: float) -> float:
    """변화율(%) 계산"""
    if old == 0:
        return 0.0
    return round((new - old) / abs(old) * 100, 2)


def _to_python(val):
    """numpy/pandas 타입 → 순수 Python 타입 변환 (JSON 직렬화 안전)"""
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return round(float(val), 6)
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, dict):
        return {k: _to_python(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_python(v) for v in val]
    return val


def _infer_compare_axis(entities: dict) -> str | None:
    """entity에서 비교축 추론 (값이 2종 이상인 파라미터)"""
    axis_map = {
        "vths": "VTH",
        "drive_strengths": "DS",
        "temps": "TEMP",
        "vdds": "VDD",
        "cell_heights": "CH",
        "nanosheet_widths": "WNS",
        "corners": "CORNER",
        "cells": "CELL",
    }
    for ent_key, col in axis_map.items():
        vals = entities.get(ent_key, [])
        if len(vals) >= 2:
            return col
    return None


def _infer_vary_axis(entities: dict) -> str | None:
    """sensitivity 분석의 변동축 추론"""
    # hint=sensitivity이면 temp/vdd 중 언급된 것, 없으면 temp 기본
    if entities.get("temps") and len(entities["temps"]) >= 2:
        return "TEMP"
    if entities.get("vdds") and len(entities["vdds"]) >= 2:
        return "VDD"
    # 키워드 기반: 온도 관련이면 TEMP
    return "TEMP"


# ──────────────────────────────────────────────
# analyze 모드 분석 함수들
# ──────────────────────────────────────────────

def _summarize(df: pd.DataFrame, metrics: list[str]) -> AnalysisResult:
    """단일 PDK 요약 통계"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    summary = []
    for m in metrics:
        vals = df[m].dropna()
        if vals.empty:
            continue
        summary.append({
            "metric": m,
            "mean": round(float(vals.mean()), 6),
            "std": round(float(vals.std()), 6),
            "min": round(float(vals.min()), 6),
            "max": round(float(vals.max()), 6),
            "count": int(len(vals)),
        })

    return AnalysisResult(
        mode="summarize",
        summary_table=summary,
        findings=[],
        chart_data={"type": "summary", "metrics": metrics},
        raw_for_avg=None,
    )


def _calc_delta(df: pd.DataFrame, axis: str, metrics: list[str]) -> AnalysisResult:
    """축별 변화율 계산 (PDK 비교 또는 VTH/DS/TEMP 등 비교)"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    groups = df[axis].unique()
    if len(groups) < 2:
        return _summarize(df, metrics)

    # 그룹핑 키: axis 제외한 조건 컬럼
    group_keys = [c for c in CONDITION_COLS if c in df.columns and c != axis]
    if axis == "PDK_ID":
        group_keys = [c for c in CONDITION_COLS if c in df.columns]

    base_val, comp_val = groups[0], groups[1]
    base_df = df[df[axis] == base_val]
    comp_df = df[df[axis] == comp_val]

    # 그룹별 평균으로 비교
    if group_keys:
        base_agg = base_df.groupby(group_keys)[metrics].mean().reset_index()
        comp_agg = comp_df.groupby(group_keys)[metrics].mean().reset_index()
    else:
        base_agg = base_df[metrics].mean().to_frame().T
        comp_agg = comp_df[metrics].mean().to_frame().T

    summary = []
    findings = []
    for m in metrics:
        b_mean = float(base_agg[m].mean()) if m in base_agg.columns else 0
        c_mean = float(comp_agg[m].mean()) if m in comp_agg.columns else 0
        delta = _pct_change(b_mean, c_mean)
        row = {
            "metric": m,
            f"{axis}={_to_python(base_val)}": round(b_mean, 6),
            f"{axis}={_to_python(comp_val)}": round(c_mean, 6),
            "delta_pct": delta,
        }
        summary.append(row)

        severity = "high" if abs(delta) > 10 else "medium" if abs(delta) > 5 else "low"
        if abs(delta) > 3:
            direction = "증가" if delta > 0 else "감소"
            findings.append({
                "type": "change",
                "metric": m,
                "delta_pct": delta,
                "direction": direction,
                "severity": severity,
            })

    return AnalysisResult(
        mode="compare",
        summary_table=summary,
        findings=findings,
        chart_data={
            "type": "grouped_bar",
            "axis": axis,
            "groups": [str(base_val), str(comp_val)],
            "metrics": metrics,
        },
        raw_for_avg=None,
    )


def _calc_sensitivity(df: pd.DataFrame, vary_axis: str,
                      metrics: list[str]) -> AnalysisResult:
    """파라미터 민감도 분석"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    axis_vals = sorted(df[vary_axis].unique())

    summary = []
    for m in metrics:
        points = []
        for v in axis_vals:
            subset = df[df[vary_axis] == v]
            mean_val = float(subset[m].mean())
            points.append({"axis_value": _to_python(v), "mean": round(mean_val, 6)})
        # 전체 범위 변화율
        if len(points) >= 2 and points[0]["mean"] != 0:
            total_delta = _pct_change(points[0]["mean"], points[-1]["mean"])
        else:
            total_delta = 0.0
        summary.append({
            "metric": m,
            "vary_axis": vary_axis,
            "points": points,
            "total_delta_pct": total_delta,
        })

    findings = [
        {"type": "sensitivity", "metric": s["metric"],
         "axis": vary_axis, "total_delta_pct": s["total_delta_pct"]}
        for s in summary if abs(s["total_delta_pct"]) > 5
    ]

    return AnalysisResult(
        mode="sensitivity",
        summary_table=summary,
        findings=findings,
        chart_data={
            "type": "line",
            "x_axis": vary_axis,
            "metrics": metrics,
        },
        raw_for_avg=None,
    )


def _find_worst_case(df: pd.DataFrame, metrics: list[str]) -> AnalysisResult:
    """worst-case 조건 탐색"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    summary = []
    findings = []

    for m in metrics:
        # freq는 min이 worst, power/leakage는 max가 worst
        is_lower_worse = m in ("FREQ_GHZ",)
        if is_lower_worse:
            idx = df[m].idxmin()
            worst_label = "최저"
        else:
            idx = df[m].idxmax()
            worst_label = "최고"

        worst_row = df.loc[idx]
        conditions = {c: _to_python(worst_row[c]) for c in CONDITION_COLS if c in df.columns}
        summary.append({
            "metric": m,
            "worst_value": round(float(worst_row[m]), 6),
            "worst_type": worst_label,
            "conditions": conditions,
        })
        findings.append({
            "type": "worst_case",
            "metric": m,
            "value": round(float(worst_row[m]), 6),
            "conditions": conditions,
        })

    return AnalysisResult(
        mode="worst_case",
        summary_table=summary,
        findings=findings,
        chart_data={"type": "highlight_table", "metrics": metrics},
        raw_for_avg=None,
    )


def _calc_tradeoff(df: pd.DataFrame, axis: str,
                   metrics: list[str]) -> AnalysisResult:
    """trade-off 분석 (소극적 권장용 데이터)"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    axis_vals = sorted(df[axis].unique(), key=str)

    summary = []
    for v in axis_vals:
        subset = df[df[axis] == v]
        row: dict[str, Any] = {axis: _to_python(v)}
        for m in metrics:
            row[m] = round(float(subset[m].mean()), 6)
        summary.append(row)

    # 비교 findings
    findings = []
    if len(summary) >= 2:
        for m in metrics:
            vals = [s[m] for s in summary]
            delta = _pct_change(vals[0], vals[-1])
            if abs(delta) > 1:
                findings.append({
                    "type": "tradeoff",
                    "metric": m,
                    "axis": axis,
                    "values": {str(summary[i][axis]): vals[i] for i in range(len(vals))},
                    "delta_pct": delta,
                })

    return AnalysisResult(
        mode="tradeoff",
        summary_table=summary,
        findings=findings,
        chart_data={
            "type": "grouped_bar",
            "axis": axis,
            "groups": [str(v) for v in axis_vals],
            "metrics": metrics,
        },
        raw_for_avg=None,
    )


def _calc_correlation(df: pd.DataFrame, metrics: list[str]) -> AnalysisResult:
    """파라미터 간 상관분석"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    if len(metrics) < 2:
        metrics = _available_metrics(df)[:4]

    corr_matrix = df[metrics].corr().round(4)
    summary = []
    findings = []

    for i, m1 in enumerate(metrics):
        for m2 in metrics[i + 1:]:
            r = float(corr_matrix.loc[m1, m2])
            summary.append({"x": m1, "y": m2, "correlation": r})
            if abs(r) > 0.7:
                findings.append({
                    "type": "correlation",
                    "x": m1,
                    "y": m2,
                    "r": r,
                    "strength": "강한 양의 상관" if r > 0 else "강한 음의 상관",
                })

    return AnalysisResult(
        mode="correlation",
        summary_table=summary,
        findings=findings,
        chart_data={"type": "heatmap", "metrics": metrics},
        raw_for_avg=None,
    )


def _interpolate(df: pd.DataFrame, entities: dict,
                 metrics: list[str]) -> AnalysisResult:
    """미실측 조건 보간"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    # 보간축 결정
    axis = _infer_vary_axis(entities)
    axis_vals = sorted(df[axis].unique())

    summary = []
    for m in metrics:
        points = []
        for v in axis_vals:
            subset = df[df[axis] == v]
            points.append((float(v), float(subset[m].mean())))

        if len(points) >= 2:
            x_arr = np.array([p[0] for p in points])
            y_arr = np.array([p[1] for p in points])
            # 선형 보간 결과
            x_new = np.linspace(x_arr.min(), x_arr.max(), 20)
            y_new = np.interp(x_new, x_arr, y_arr)
            summary.append({
                "metric": m,
                "axis": axis,
                "measured": points,
                "interpolated": [
                    {"x": round(float(x), 2), "y": round(float(y), 6)}
                    for x, y in zip(x_new, y_new)
                ],
            })

    return AnalysisResult(
        mode="interpolation",
        summary_table=summary,
        findings=[],
        chart_data={"type": "scatter", "axis": axis, "metrics": metrics},
        raw_for_avg=None,
    )


def _profile(df: pd.DataFrame, metrics: list[str]) -> AnalysisResult:
    """특정 셀의 전체 PPA 프로파일"""
    metrics = _available_metrics(df)  # 프로파일은 전체 metric
    return _summarize(df, metrics)


# ──────────────────────────────────────────────
# trend 모드
# ──────────────────────────────────────────────

def _calc_trend(df: pd.DataFrame, metrics: list[str]) -> AnalysisResult:
    """N개 PDK 버전별 추이"""
    metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
    pdk_ids = df["PDK_ID"].unique()

    summary = []
    for pdk_id in pdk_ids:
        subset = df[df["PDK_ID"] == pdk_id]
        row: dict[str, Any] = {"PDK_ID": _to_python(pdk_id)}
        for m in metrics:
            row[m] = round(float(subset[m].mean()), 6)
        summary.append(row)

    # 전체 추이 findings
    findings = []
    if len(summary) >= 2:
        for m in metrics:
            first = summary[0][m]
            last = summary[-1][m]
            delta = _pct_change(first, last)
            if abs(delta) > 1:
                findings.append({
                    "type": "trend",
                    "metric": m,
                    "start": first,
                    "end": last,
                    "total_delta_pct": delta,
                    "direction": "상승" if delta > 0 else "하락",
                })

    return AnalysisResult(
        mode="trend",
        summary_table=summary,
        findings=findings,
        chart_data={
            "type": "line",
            "x_axis": "PDK_ID",
            "metrics": metrics,
        },
        raw_for_avg=None,
    )


# ──────────────────────────────────────────────
# anomaly 모드
# ──────────────────────────────────────────────

def _detect_anomalies(df: pd.DataFrame, datasets: list[dict]) -> AnalysisResult:
    """두 PDK 간 이상치 탐지 (z-score 기반)"""
    if len(datasets) < 2:
        return AnalysisResult(
            mode="anomaly", summary_table=[], findings=[],
            chart_data={}, raw_for_avg=None,
        )

    pdk_ids = df["PDK_ID"].unique()
    base_id, comp_id = pdk_ids[0], pdk_ids[1]
    base_df = df[df["PDK_ID"] == base_id].copy()
    comp_df = df[df["PDK_ID"] == comp_id].copy()

    # 조건별 매칭 키
    match_cols = [c for c in CONDITION_COLS if c in df.columns]
    metrics = _available_metrics(df)

    # 매칭 조인
    merged = pd.merge(
        base_df, comp_df,
        on=match_cols, suffixes=("_base", "_comp"),
        how="inner",
    )

    if merged.empty:
        return AnalysisResult(
            mode="anomaly", summary_table=[],
            findings=[{"type": "warning", "message": "매칭되는 조건 쌍이 없습니다."}],
            chart_data={}, raw_for_avg=None,
        )

    # 지표별 변화율 계산
    anomalies = []
    for m in metrics:
        base_col = f"{m}_base"
        comp_col = f"{m}_comp"
        if base_col not in merged.columns:
            continue

        base_vals = merged[base_col].values.astype(float)
        comp_vals = merged[comp_col].values.astype(float)

        # log 변환 (exponential 분포 metric)
        if m in LOG_METRICS:
            base_vals = np.log1p(np.abs(base_vals))
            comp_vals = np.log1p(np.abs(comp_vals))

        # 변화율
        with np.errstate(divide="ignore", invalid="ignore"):
            delta = np.where(base_vals != 0, (comp_vals - base_vals) / np.abs(base_vals), 0)

        # z-score
        if np.std(delta) > 0:
            z = (delta - np.mean(delta)) / np.std(delta)
        else:
            z = np.zeros_like(delta)

        # |z| > 2인 이상치
        outlier_mask = np.abs(z) > 2
        for idx in np.where(outlier_mask)[0]:
            row = merged.iloc[idx]
            conditions = {c: _to_python(row[c]) for c in match_cols}
            anomalies.append({
                "metric": m,
                "z_score": round(float(z[idx]), 2),
                "delta_pct": round(float(delta[idx] * 100), 2),
                "base_value": round(float(merged.iloc[idx][f"{m}_base"]), 6),
                "comp_value": round(float(merged.iloc[idx][f"{m}_comp"]), 6),
                "conditions": conditions,
            })

    # 클러스터링 (조건 영역별 그룹핑)
    clusters: dict[str, list[dict]] = {}
    for a in anomalies:
        conds = a["conditions"]
        # VTH + TEMP 기반 클러스터 키
        key_parts = []
        if "VTH" in conds:
            key_parts.append(f"VTH={conds['VTH']}")
        if "TEMP" in conds:
            key_parts.append(f"TEMP={conds['TEMP']}")
        cluster_key = ", ".join(key_parts) if key_parts else "기타"
        clusters.setdefault(cluster_key, []).append(a)

    # 클러스터 요약
    summary = []
    for key, items in sorted(clusters.items(), key=lambda x: -len(x[1])):
        metric_counts: dict[str, int] = {}
        for item in items:
            metric_counts[item["metric"]] = metric_counts.get(item["metric"], 0) + 1
        summary.append({
            "cluster": key,
            "count": len(items),
            "metrics": metric_counts,
            "samples": items[:3],
        })

    findings = [
        {
            "type": "anomaly_cluster",
            "cluster": s["cluster"],
            "count": s["count"],
            "dominant_metrics": sorted(s["metrics"].items(), key=lambda x: -x[1]),
        }
        for s in summary
    ]

    return AnalysisResult(
        mode="anomaly",
        summary_table=summary,
        findings=findings,
        chart_data={
            "type": "scatter",
            "total_anomalies": len(anomalies),
            "clusters": len(clusters),
        },
        raw_for_avg=None,
    )


# ──────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────

def analyzer(state: PaveAgentState) -> dict:
    """통계 분석 (코드 기반, 모드별 분기)"""
    parsed = state["parsed_intent"]
    resolution = state["pdk_resolution"]
    query_result = state["query_result"]

    intent = parsed["intent"]
    entities = parsed["entities"]
    datasets = query_result["datasets"]
    metrics_hint = [m.upper() for m in (entities.get("metrics") or ["freq_ghz"])]

    df = _datasets_to_df(datasets)
    if df.empty:
        return {"error": "분석할 데이터가 없습니다."}

    try:
        if intent == "trend":
            result = _calc_trend(df, metrics_hint)

        elif intent == "anomaly":
            result = _detect_anomalies(df, datasets)

        else:  # analyze
            hint = entities.get("analysis_hint")
            pdk_count = len(resolution["target_pdks"])

            if hint == "profile":
                result = _profile(df, metrics_hint)
            elif hint == "sensitivity":
                vary_axis = _infer_vary_axis(entities)
                result = _calc_sensitivity(df, vary_axis, metrics_hint)
            elif hint == "worst_case":
                result = _find_worst_case(df, metrics_hint)
            elif hint == "tradeoff":
                axis = _infer_compare_axis(entities) or "VTH"
                result = _calc_tradeoff(df, axis, metrics_hint)
            elif hint == "correlation":
                result = _calc_correlation(df, metrics_hint)
            elif hint == "interpolation":
                result = _interpolate(df, entities, metrics_hint)
            elif pdk_count == 2:
                result = _calc_delta(df, "PDK_ID", metrics_hint)
            else:
                compare_axis = _infer_compare_axis(entities)
                if compare_axis:
                    result = _calc_delta(df, compare_axis, metrics_hint)
                else:
                    result = _summarize(df, metrics_hint)

    except Exception as e:
        logger.error("분석 중 오류: %s", e)
        return {"error": f"분석 중 오류가 발생했습니다: {e}"}

    return {"analysis_result": result}
