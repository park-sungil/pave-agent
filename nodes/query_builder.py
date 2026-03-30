from __future__ import annotations

import logging
from typing import Any

from state import PaveAgentState, QueryPlan

logger = logging.getLogger(__name__)

# --- 기본 SELECT 컬럼 ---
BASE_COLS = [
    "d.PDK_ID", "d.CELL", "d.DS", "d.CORNER", "d.TEMP", "d.VDD",
    "d.VTH", "d.WNS", "d.WNS_VAL", "d.CH", "d.CH_TYPE",
]

# 전체 metric 컬럼
ALL_METRIC_COLS = [
    "d.FREQ_GHZ", "d.D_POWER", "d.D_ENERGY",
    "d.ACCEFF_FF", "d.ACREFF_KOHM", "d.S_POWER", "d.IDDQ_NA",
]

# metric 이름 → 컬럼 매핑
METRIC_COL_MAP = {
    "freq_ghz": "d.FREQ_GHZ",
    "d_power": "d.D_POWER",
    "d_energy": "d.D_ENERGY",
    "acceff_ff": "d.ACCEFF_FF",
    "acreff_kohm": "d.ACREFF_KOHM",
    "s_power": "d.S_POWER",
    "iddq_na": "d.IDDQ_NA",
}


def _resolve_metric_cols(metrics: list[str] | None) -> list[str]:
    """요청된 metric → SELECT 컬럼 목록. 비어있으면 전체 metric 반환."""
    if not metrics:
        return ALL_METRIC_COLS
    cols = []
    for m in metrics:
        col = METRIC_COL_MAP.get(m.lower())
        if col and col not in cols:
            cols.append(col)
    # 비교 분석 시 관련 metric도 함께 조회
    return cols if cols else ALL_METRIC_COLS


def _quote_list(values: list[str]) -> str:
    """문자열 리스트 → SQL IN 절용 ('A', 'B')"""
    return ", ".join(f"'{v}'" for v in values)


def _num_list(values: list[int | float]) -> str:
    """숫자 리스트 → SQL IN 절용 (1, 2, 3)"""
    return ", ".join(str(v) for v in values)


def build_query(pdk_id: int, entities: dict, is_bulk: bool,
                applied_defaults: dict | None = None,
                sensitivity_col: str | None = None,
                optimization_axes: list[str] | None = None,
                vdd_nominal: float | None = None) -> str:
    """entity 기반 SQL 동적 조립

    기본값 적용 규칙:
    - entity에 값이 있으면 → 그 값으로 WHERE
    - entity에 값이 없으면 → applied_defaults 기본값 적용
    - sensitivity_col이 지정되면 → 해당 축은 기본값 적용 안 함 (전체 조회)
    - optimization_axes에 포함된 컬럼도 기본값 적용 안 함 (전체 sweep)
    - is_bulk=True면 → 기본값 적용 안 함 (전체 sweep)
    """
    applied_defaults = applied_defaults or {}
    opt_axes = set(optimization_axes or [])
    select_cols = BASE_COLS + _resolve_metric_cols(entities.get("metrics"))
    where_clauses = [f"d.PDK_ID = {pdk_id}"]

    def _should_apply_default(col: str) -> bool:
        """해당 컬럼에 기본값을 적용할지 판단"""
        if is_bulk:
            return False
        if sensitivity_col and col == sensitivity_col:
            return False
        if col in opt_axes:
            return False
        return True

    # CORNER
    if entities.get("corners"):
        where_clauses.append(f"d.CORNER IN ({_quote_list(entities['corners'])})")
    elif _should_apply_default("CORNER"):
        where_clauses.append("d.CORNER = 'TT'")

    # TEMP
    if entities.get("temps"):
        where_clauses.append(f"d.TEMP IN ({_num_list(entities['temps'])})")
    elif _should_apply_default("TEMP"):
        where_clauses.append("d.TEMP = 25")

    # VDD
    if entities.get("vdds"):
        where_clauses.append(f"d.VDD IN ({_num_list(entities['vdds'])})")
    elif _should_apply_default("VDD") and vdd_nominal is not None:
        where_clauses.append(f"d.VDD = {vdd_nominal}")

    # VTH
    if entities.get("vths"):
        where_clauses.append(f"d.VTH IN ({_quote_list(entities['vths'])})")
    elif _should_apply_default("VTH"):
        pass  # VTH는 기본값 없음 — 전체 조회

    # CELL
    if entities.get("cells"):
        where_clauses.append(f"d.CELL IN ({_quote_list(entities['cells'])})")
    elif not is_bulk and _should_apply_default("CELL"):
        where_clauses.append(
            "(d.CELL LIKE 'INV%' OR d.CELL LIKE 'ND2%' OR d.CELL LIKE 'NR2%')"
        )

    # DS
    if entities.get("drive_strengths"):
        where_clauses.append(f"d.DS IN ({_quote_list(entities['drive_strengths'])})")
    elif not is_bulk and _should_apply_default("DS"):
        where_clauses.append("d.DS IN ('D1', 'D4')")

    # CH
    if entities.get("cell_heights"):
        where_clauses.append(f"d.CH IN ({_quote_list(entities['cell_heights'])})")
    elif _should_apply_default("CH"):
        pass  # CH는 기본값 없음

    # WNS
    if entities.get("nanosheet_widths"):
        where_clauses.append(f"d.WNS IN ({_quote_list(entities['nanosheet_widths'])})")

    limit = 15000 if is_bulk else 1000

    sql = (
        f"SELECT {', '.join(select_cols)}\n"
        f"FROM antsdb.PAVE_PPA_DATA_VIEW d\n"
        f"WHERE {' AND '.join(where_clauses)}\n"
        f"FETCH FIRST {limit} ROWS ONLY"
    )
    return sql


def query_builder(state: PaveAgentState) -> dict:
    """SQL 동적 조립 (코드 기반)"""
    parsed = state["parsed_intent"]
    resolution = state["pdk_resolution"]
    entities = parsed["entities"]
    intent = parsed["intent"]
    is_bulk = intent == "anomaly"

    resolved_params = resolution.get("resolved_params") or {}
    sensitivity_col = resolved_params.get("sensitivity_col")
    optimization_axes = resolved_params.get("optimization_axes")
    applied_defaults = resolution.get("applied_defaults") or {}

    queries = []
    for pdk in resolution["target_pdks"]:
        sql = build_query(
            pdk["pdk_id"], entities, is_bulk,
            applied_defaults=applied_defaults,
            sensitivity_col=sensitivity_col,
            optimization_axes=optimization_axes,
            vdd_nominal=pdk.get("vdd_nominal"),
        )
        queries.append({
            "sql": sql,
            "purpose": f"{pdk['project_name']} {pdk['mask']} PPA",
            "pdk_id": pdk["pdk_id"],
        })

    return {
        "query_plan": QueryPlan(
            queries=queries,
            is_bulk=is_bulk,
        ),
    }
