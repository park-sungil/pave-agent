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

# VTH 정렬 순서 (낮은 threshold → 높은 threshold, 즉 빠름 → 느림)
# 새 VTH 타입 추가 시 여기에만 삽입
VTH_ORDER = ["ULVT", "SLVT", "VLVT", "LVT", "MVT", "RVT", "HVT"]


def _vth_sort_key(v: str) -> int:
    """VTH 정렬 키: VTH_ORDER 인덱스, 미등록이면 뒤로"""
    return VTH_ORDER.index(v.upper()) if v.upper() in VTH_ORDER else len(VTH_ORDER)


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


def _calc_delta(df: pd.DataFrame, axis: str, metrics: list[str],
                pdk_labels: dict | None = None) -> AnalysisResult:
    """축별 변화율 계산 (PDK 비교 또는 VTH/DS/TEMP 등 비교).

    pdk_labels: {pdk_id: "SF3(900)"} 형태로 전달하면 PDK_ID 대신 공정명 표시.
    axis==PDK_ID일 때 VTH별 breakdown 테이블도 생성.
    """
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

    # 라벨: PDK_ID일 때 pdk_labels 사용 (예: "SF3(900)"), 없으면 기본
    def _label(val) -> str:
        if pdk_labels and _to_python(val) in pdk_labels:
            return pdk_labels[_to_python(val)]
        return f"{axis}={_to_python(val)}"

    base_label = _label(base_val)
    comp_label = _label(comp_val)

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
            base_label: round(b_mean, 6),
            comp_label: round(c_mean, 6),
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

    # cross-process PDK 비교일 때 VTH별 breakdown 추가
    breakdown: list[dict[str, Any]] = []
    if axis == "PDK_ID" and "VTH" in df.columns:
        vth_vals = sorted(df["VTH"].unique(), key=_vth_sort_key)
        for vth in vth_vals:
            for m in metrics:
                b_sub = base_df[base_df["VTH"] == vth][m]
                c_sub = comp_df[comp_df["VTH"] == vth][m]
                if b_sub.empty or c_sub.empty:
                    continue
                b_v = float(b_sub.mean())
                c_v = float(c_sub.mean())
                breakdown.append({
                    "VTH": vth,
                    "metric": m,
                    base_label: round(b_v, 6),
                    comp_label: round(c_v, 6),
                    "delta_pct": _pct_change(b_v, c_v),
                })

    return AnalysisResult(
        mode="compare",
        summary_table=summary,
        findings=findings,
        chart_data={
            "type": "grouped_bar",
            "axis": axis,
            "groups": [base_label, comp_label],
            "metrics": metrics,
            "breakdown": breakdown,
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
    """trade-off 분석 (소극적 권장용 데이터).

    VTH 축일 때:
    - 요청 metrics 무시, 가용 전체 metric 표시 (추가 질문 방지)
    - VTH_ORDER 순서로 정렬
    - 최고 VTH(가장 느린 쪽)를 기준으로 ratio 테이블 추가
    """
    # VTH 비교는 항상 전체 metric (요청 metric만 보면 정보 부족)
    if axis == "VTH":
        metrics = _available_metrics(df)
        axis_vals = sorted(df[axis].unique(), key=_vth_sort_key)
    else:
        metrics = [m for m in metrics if m in df.columns] or _available_metrics(df)
        axis_vals = sorted(df[axis].unique(), key=str)

    summary = []
    for v in axis_vals:
        subset = df[df[axis] == v]
        row: dict[str, Any] = {axis: _to_python(v)}
        for m in metrics:
            row[m] = round(float(subset[m].mean()), 6)
        summary.append(row)

    # ratio 테이블: 최고 VTH(마지막)를 기준으로 각 VTH의 상대값
    ratio_table: list[dict[str, Any]] = []
    if axis == "VTH" and len(summary) >= 2:
        ref = summary[-1]  # 가장 높은 VTH = 기준
        ref_label = str(ref[axis])
        for row in summary:
            ratio_row: dict[str, Any] = {axis: row[axis]}
            for m in metrics:
                ref_val = ref.get(m, 0)
                ratio_row[m] = round(row[m] / ref_val, 4) if ref_val else None
            ratio_table.append(ratio_row)

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

    chart_data: dict[str, Any] = {
        "type": "grouped_bar",
        "axis": axis,
        "groups": [str(v) for v in axis_vals],
        "metrics": metrics,
    }
    if ratio_table:
        chart_data["ratio_table"] = ratio_table
        chart_data["ratio_reference"] = str(summary[-1][axis])

    return AnalysisResult(
        mode="tradeoff",
        summary_table=summary,
        findings=findings,
        chart_data=chart_data,
        raw_for_avg=None,
    )


def _calc_correlation(df: pd.DataFrame, metrics: list[str]) -> AnalysisResult:
    """파라미터 간 상관분석.

    FREQ_GHZ가 포함되고 ACCEFF_FF/ACREFF_KOHM이 함께 있으면
    각 parasitic 파라미터의 R² 기여도도 계산 (attribution 분석).
    """
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

    # Reff/Ceff attribution: FREQ_GHZ를 target으로 각 parasitic R² 계산
    attribution: list[dict[str, Any]] = []
    target = "FREQ_GHZ"
    parasitic_candidates = [m for m in metrics if m in ("ACCEFF_FF", "ACREFF_KOHM") and m != target]
    if target in df.columns and len(parasitic_candidates) >= 1:
        y = df[target].dropna()
        for p in parasitic_candidates:
            if p not in df.columns:
                continue
            xy = df[[target, p]].dropna()
            if len(xy) < 3:
                continue
            r2 = float(xy[target].corr(xy[p]) ** 2)
            attribution.append({
                "type": "attribution",
                "target": target,
                "predictor": p,
                "r_squared": round(r2, 4),
                "description": (
                    f"{p}이(가) {target} 변동의 {round(r2*100,1)}%를 설명합니다."
                ),
            })
        # R² 높은 순으로 정렬
        attribution.sort(key=lambda x: -x["r_squared"])
        findings.extend(attribution)

    return AnalysisResult(
        mode="correlation",
        summary_table=summary,
        findings=findings,
        chart_data={"type": "heatmap", "metrics": metrics, "attribution": attribution},
        raw_for_avg=None,
    )


def _find_sweet_spot(df: pd.DataFrame, entities: dict,
                     metrics: list[str],
                     optimization_axes: list[str] | None = None) -> AnalysisResult:
    """효율 최적점(sweet spot) 탐색.

    단일 축(VDD sweep): 인접 구간별 delta_perf / delta_leakage 효율비를 계산하여
    효율비가 가장 높은 전압 구간(= 누설 대비 성능 이득이 최대인 지점)을 식별.

    다중 축(VTH × VDD): 모든 조합별 perf/leakage 복합 점수를 계산하여 상위 조합 제시.
    또한 Pareto frontier(어떤 점보다도 모든 metric에서 나쁘지 않은 점)를 식별.
    """
    axes = optimization_axes or ["VDD"]
    perf_metric = next((m for m in metrics if m in df.columns and m == "FREQ_GHZ"), None)
    if perf_metric is None:
        perf_metric = next((m for m in _available_metrics(df)
                            if m not in ("S_POWER", "IDDQ_NA")), "FREQ_GHZ")
    leak_metric = next(
        (m for m in metrics if m in df.columns and m in ("IDDQ_NA", "S_POWER")),
        "IDDQ_NA" if "IDDQ_NA" in df.columns else "S_POWER"
    )

    # ── 단일 축 (VDD 또는 VTH) ─────────────────────────
    if len(axes) == 1:
        axis = axes[0]
        if axis not in df.columns:
            axis = "VDD"
        axis_vals = sorted(df[axis].unique(), key=(_vth_sort_key if axis == "VTH" else float))
        summary = []
        for v in axis_vals:
            sub = df[df[axis] == v]
            row: dict[str, Any] = {axis: _to_python(v)}
            for m in _available_metrics(df):
                row[m] = round(float(sub[m].mean()), 6)
            summary.append(row)

        # 인접 구간 효율비: delta_perf / delta_leakage
        efficiency_rows = []
        for i in range(1, len(summary)):
            prev, cur = summary[i - 1], summary[i]
            d_perf = cur.get(perf_metric, 0) - prev.get(perf_metric, 0)
            d_leak = cur.get(leak_metric, 0) - prev.get(leak_metric, 0)
            ratio = round(d_perf / d_leak, 6) if d_leak and d_leak != 0 else None
            efficiency_rows.append({
                axis: cur[axis],
                "delta_perf": round(d_perf, 6),
                "delta_leakage": round(d_leak, 6),
                "efficiency_ratio": ratio,
            })

        # sweet spot = 효율비 최대 구간
        valid = [r for r in efficiency_rows if r["efficiency_ratio"] is not None]
        best = max(valid, key=lambda r: r["efficiency_ratio"]) if valid else None
        findings: list[dict[str, Any]] = []
        if best:
            findings.append({
                "type": "sweet_spot",
                "axis": axis,
                "point": best[axis],
                "efficiency_ratio": best["efficiency_ratio"],
                "description": (
                    f"{axis}={best[axis]} 구간에서 {leak_metric} 증가 대비 "
                    f"{perf_metric} 이득이 가장 큽니다."
                ),
            })

        chart_data: dict[str, Any] = {
            "type": "efficiency_line",
            "axis": axis,
            "perf_metric": perf_metric,
            "leak_metric": leak_metric,
            "efficiency_rows": efficiency_rows,
            "metrics": _available_metrics(df),
        }
        return AnalysisResult(
            mode="optimization",
            summary_table=summary,
            findings=findings,
            chart_data=chart_data,
            raw_for_avg=None,
        )

    # ── 다중 축 (VTH × VDD) ───────────────────────────
    group_cols = [ax for ax in axes if ax in df.columns]
    if not group_cols:
        group_cols = ["VDD"]

    grp = df.groupby(group_cols)
    rows_2d: list[dict[str, Any]] = []
    for key, sub in grp:
        if not isinstance(key, tuple):
            key = (key,)
        row = dict(zip(group_cols, [_to_python(k) for k in key]))
        p_val = float(sub[perf_metric].mean()) if perf_metric in sub.columns else 0.0
        l_val = float(sub[leak_metric].mean()) if leak_metric in sub.columns else 1.0
        row[perf_metric] = round(p_val, 6)
        row[leak_metric] = round(l_val, 6)
        row["score"] = round(p_val / l_val, 6) if l_val > 0 else 0.0
        rows_2d.append(row)

    rows_2d.sort(key=lambda r: -r["score"])

    # Pareto frontier: 어떤 다른 점보다 perf >= and leakage <= 인 점
    pareto = []
    for i, r in enumerate(rows_2d):
        dominated = False
        for j, other in enumerate(rows_2d):
            if i == j:
                continue
            if (other[perf_metric] >= r[perf_metric]
                    and other[leak_metric] <= r[leak_metric]
                    and (other[perf_metric] > r[perf_metric]
                         or other[leak_metric] < r[leak_metric])):
                dominated = True
                break
        if not dominated:
            pareto.append(row)

    findings = []
    for rank, r in enumerate(rows_2d[:3], 1):
        label = ", ".join(f"{k}={r[k]}" for k in group_cols)
        findings.append({
            "type": "sweet_spot",
            "rank": rank,
            "conditions": {k: r[k] for k in group_cols},
            "score": r["score"],
            "description": (
                f"[{rank}위] {label}: {perf_metric}={r[perf_metric]}, "
                f"{leak_metric}={r[leak_metric]}"
            ),
        })

    chart_data = {
        "type": "pareto_scatter",
        "x_metric": leak_metric,
        "y_metric": perf_metric,
        "group_cols": group_cols,
        "pareto_points": pareto,
        "metrics": _available_metrics(df),
    }
    return AnalysisResult(
        mode="optimization",
        summary_table=rows_2d,
        findings=findings,
        chart_data=chart_data,
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

            # cross-process 비교 시 PDK_ID → "공정명(ID)" 라벨 매핑
            pdk_labels: dict[int, str] = {
                pdk["pdk_id"]: f"{pdk.get('process', pdk['project_name'])}({pdk['pdk_id']})"
                for pdk in resolution["target_pdks"]
            }

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
            elif hint == "optimization":
                opt_axes = (resolution.get("resolved_params") or {}).get("optimization_axes")
                result = _find_sweet_spot(df, entities, metrics_hint, opt_axes)
            elif pdk_count == 2:
                result = _calc_delta(df, "PDK_ID", metrics_hint, pdk_labels=pdk_labels)
            else:
                compare_axis = _infer_compare_axis(entities)
                if compare_axis:
                    result = _calc_delta(df, compare_axis, metrics_hint)
                else:
                    result = _summarize(df, metrics_hint)
            # Phase 2 확장 지점:
            # 새 hint 추가 시 위 elif 체인에 새 elif만 추가 (기존 분기 수정 없음)
            # 예: elif hint == "root_cause": result = _find_root_cause(df, ...)
            # 예: elif hint == "prediction": result = _predict(df, ...)

    except Exception as e:
        logger.error("분석 중 오류: %s", e)
        return {"error": f"분석 중 오류가 발생했습니다: {e}"}

    return {"analysis_result": result}
