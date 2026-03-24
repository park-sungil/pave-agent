from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from shared.db import execute_query
from state import PaveAgentState, PDKResolution, ResolvedPDK

logger = logging.getLogger(__name__)

# --- SQL 템플릿 ---

SQL_GOLDEN_OPTIONS_BY_PROCESS = """
    SELECT PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS, HSPICE, LVS, PEX
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE IS_GOLDEN = 1 AND PROCESS = '{process}'{mask_filter}
    ORDER BY PROJECT, MASK, DK_GDS
    FETCH FIRST 20 ROWS ONLY
"""

SQL_GOLDEN_OPTIONS_BY_PROJECT = """
    SELECT PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS, HSPICE, LVS, PEX
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE IS_GOLDEN = 1 AND PROJECT = '{project}'{mask_filter}
    ORDER BY MASK, DK_GDS
    FETCH FIRST 20 ROWS ONLY
"""

SQL_GOLDEN_OPTIONS_BY_PROJECT_NAME = """
    SELECT PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS, HSPICE, LVS, PEX
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE IS_GOLDEN = 1 AND PROJECT_NAME = '{name}'{mask_filter}
    ORDER BY MASK, DK_GDS
    FETCH FIRST 20 ROWS ONLY
"""

SQL_LATEST_PDK = """
    SELECT PDK_ID, PROJECT, PROJECT_NAME, PROCESS, MASK, DK_GDS,
           HSPICE, LVS, PEX, IS_GOLDEN, VDD_NOMINAL
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}' AND MASK = '{mask}' AND DK_GDS = '{dk_gds}'
      AND HSPICE = '{hspice}' AND LVS = '{lvs}' AND PEX = '{pex}'
    ORDER BY CREATED_AT DESC
    FETCH FIRST 1 ROW ONLY
"""

SQL_AVAILABLE_VALUES = """
    SELECT DISTINCT d.{col}
    FROM antsdb.PAVE_PPA_DATA_VIEW d
    WHERE d.PDK_ID = {pdk_id}
    FETCH FIRST 50 ROWS ONLY
"""

# 버전 선택 테이블 컬럼 순서
_VERSION_TABLE_HEADERS = ["PROCESS", "PROJECT", "PROJECT_NAME", "MASK", "DK_GDS", "HSPICE", "LVS", "PEX"]

# sensitivity 변동축 매핑: entity 키워드 → (DB 컬럼, entity 키)
SENSITIVITY_AXIS_MAP = {
    "temp": ("TEMP", "temps"),
    "vdd": ("VDD", "vdds"),
    "corner": ("CORNER", "corners"),
    "vth": ("VTH", "vths"),
    "ds": ("DS", "drive_strengths"),
    "ch": ("CH", "cell_heights"),
    "wns": ("WNS", "nanosheet_widths"),
}


# ──────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────

def _ask_user(question: str, options: list[str],
              table_headers: list[str] | None = None,
              table_rows: list[list[str]] | None = None) -> str:
    """사용자에게 선택을 요청 (interrupt).

    table_headers + table_rows가 있으면 구조화 테이블로 표시.
    options는 유효 번호 범위 전달용 (["1","2",...]).
    """
    payload: dict[str, Any] = {"question": question, "options": options}
    if table_headers is not None:
        payload["table_headers"] = table_headers
        payload["table_rows"] = table_rows or []
    result = interrupt(payload)
    return str(result)


def _parse_choice(choice: str, max_idx: int) -> int:
    """사용자 응답을 인덱스로 변환"""
    choice = choice.strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < max_idx:
            return idx
    except ValueError:
        pass
    return 0


def _query_golden_options(process: str | None, project: str | None,
                           project_name: str | None,
                           mask_hint: str | None = None) -> list[dict]:
    """IS_GOLDEN=1 레코드를 조회하여 선택 가능한 버전 목록 반환.

    process 입력 시 결과가 없으면 project_name으로 재시도
    (사용자가 "Vanguard"처럼 project_name을 입력하는 경우 대비).
    """
    mask_filter = f" AND MASK = '{mask_hint}'" if mask_hint else ""

    if project:
        return execute_query(SQL_GOLDEN_OPTIONS_BY_PROJECT.format(
            project=project, mask_filter=mask_filter))
    if project_name:
        return execute_query(SQL_GOLDEN_OPTIONS_BY_PROJECT_NAME.format(
            name=project_name, mask_filter=mask_filter))
    if process:
        rows = execute_query(SQL_GOLDEN_OPTIONS_BY_PROCESS.format(
            process=process, mask_filter=mask_filter))
        if not rows:
            # process 문자열이 사실 project_name일 수 있음
            rows = execute_query(SQL_GOLDEN_OPTIONS_BY_PROJECT_NAME.format(
                name=process, mask_filter=mask_filter))
        return rows
    return []


def _pick_from_options(rows: list[dict], question: str) -> dict:
    """여러 golden 옵션 중 사용자 선택. 전체 컬럼 테이블로 표시."""
    table_rows = [[str(r.get(h, "")) for h in _VERSION_TABLE_HEADERS] for r in rows]
    options = [str(i) for i in range(1, len(rows) + 1)]
    choice = _ask_user(question, options,
                       table_headers=_VERSION_TABLE_HEADERS,
                       table_rows=table_rows)
    return rows[_parse_choice(choice, len(rows))]


def _row_to_resolved_pdk(row: dict) -> ResolvedPDK:
    """DB 행 → ResolvedPDK 변환"""
    return ResolvedPDK(
        pdk_id=row["PDK_ID"],
        process=row.get("PROCESS", ""),
        project=row["PROJECT"],
        project_name=row["PROJECT_NAME"],
        mask=row["MASK"],
        dk_gds=row["DK_GDS"],
        is_golden=row.get("IS_GOLDEN", 0),
        hspice=row.get("HSPICE", ""),
        lvs=row.get("LVS", ""),
        pex=row.get("PEX", ""),
        vdd_nominal=row.get("VDD_NOMINAL", 0.0),
    )


def _get_latest_pdk(project: str, mask: str, dk_gds: str,
                    hspice: str, lvs: str, pex: str) -> dict | None:
    """project+mask+dk_gds+hspice+lvs+pex 조합에서 최신 pdk_id 조회"""
    rows = execute_query(SQL_LATEST_PDK.format(
        project=project, mask=mask, dk_gds=dk_gds,
        hspice=hspice, lvs=lvs, pex=pex,
    ))
    return rows[0] if rows else None


def _resolve_single_pdk(process: str | None, project: str | None,
                         project_name: str | None,
                         mask_hint: str | None = None) -> ResolvedPDK | None:
    """하나의 소스에서 PDK 1개 특정.

    IS_GOLDEN=1 레코드를 전체 조회 후:
    - 1개 → 자동 선택
    - 여러 개 → 전체 컬럼 테이블로 사용자 선택
    """
    rows = _query_golden_options(process, project, project_name, mask_hint)
    if not rows:
        return None

    if len(rows) == 1:
        r = rows[0]
    else:
        label = project_name or project or process or "?"
        r = _pick_from_options(rows, f"분석할 버전을 선택해주세요. ({label})")

    pdk_row = _get_latest_pdk(r["PROJECT"], r["MASK"], r["DK_GDS"],
                               r["HSPICE"], r["LVS"], r["PEX"])
    return _row_to_resolved_pdk(pdk_row) if pdk_row else None


# ──────────────────────────────────────────────
# sensitivity 축 추론
# ──────────────────────────────────────────────

def _infer_sensitivity_axis(entities: dict) -> str | None:
    """sensitivity 분석의 변동축 추론"""
    raw_q = entities.get("_raw_question", "").lower()
    if any(w in raw_q for w in ["온도", "temp", "temperature"]):
        return "temp"
    if any(w in raw_q for w in ["전압", "vdd", "voltage"]):
        return "vdd"
    if any(w in raw_q for w in ["corner", "공정 편차"]):
        return "corner"
    if any(w in raw_q for w in ["vth", "threshold"]):
        return "vth"
    for ent_key, (_, entity_key) in SENSITIVITY_AXIS_MAP.items():
        if len(entities.get(entity_key, [])) >= 2:
            return ent_key
    return "temp"


def _query_available_values(pdk_id: int, col: str) -> list:
    """특정 PDK에서 가용한 파라미터 값 조회"""
    rows = execute_query(SQL_AVAILABLE_VALUES.format(col=col, pdk_id=pdk_id))
    return sorted([r[col] for r in rows])


def _build_applied_defaults(entities: dict, sensitivity_axis: str | None = None) -> dict[str, str]:
    """적용된 기본값 목록 생성"""
    defaults = {}
    if not entities.get("corners"):
        defaults["corner"] = "전체" if sensitivity_axis == "corner" else "TT"
    if not entities.get("temps"):
        defaults["temp"] = "전체" if sensitivity_axis == "temp" else "25"
    if not entities.get("vdds"):
        defaults["vdd"] = "전체" if sensitivity_axis == "vdd" else "nominal"
    if not entities.get("cells"):
        defaults["cell"] = "AVG(INV/ND2/NR2)"
    if not entities.get("drive_strengths"):
        defaults["ds"] = "AVG(D1/D4)"
    return defaults


# ──────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────

def pdk_resolver(state: PaveAgentState) -> dict:
    """PDK 버전 특정 (코드 기반, ask_user interrupt)"""
    parsed = state["parsed_intent"]
    intent = parsed["intent"]
    entities = parsed["entities"]

    processes = entities.get("processes") or []
    projects = entities.get("projects") or []
    project_names = entities.get("project_names") or []
    masks = entities.get("masks") or []
    missing_params = parsed.get("missing_params") or []

    # 사용자가 명시한 mask가 하나면 hint로 사용
    mask_hint: str | None = masks[0] if len(masks) == 1 else None

    target_pdks: list[ResolvedPDK] = []

    if intent == "trend":
        sources = processes or project_names or projects
        if not sources:
            choice = _ask_user("추이 분석할 공정을 3개 이상 입력해주세요. (예: SF2, SF2P, SF3)", [])
            sources = [s.strip() for s in choice.split(",")]
        for src in sources[:5]:
            pdk = _resolve_single_pdk(src, None, None)
            if pdk:
                target_pdks.append(pdk)

    elif intent == "anomaly":
        if len(processes) >= 2:
            for p in processes[:2]:
                pdk = _resolve_single_pdk(p, None, None)
                if pdk:
                    target_pdks.append(pdk)
        elif len(processes) == 1:
            pdk1 = _resolve_single_pdk(processes[0], None, None)
            if pdk1:
                target_pdks.append(pdk1)
            choice = _ask_user("비교할 다른 공정을 입력해주세요.", [])
            pdk2 = _resolve_single_pdk(choice.strip(), None, None)
            if pdk2:
                target_pdks.append(pdk2)
        else:
            choice = _ask_user("이상치 분석할 두 공정을 입력해주세요. (예: SF3, SF2)", [])
            parts = [s.strip() for s in choice.split(",")]
            for p in parts[:2]:
                pdk = _resolve_single_pdk(p, None, None)
                if pdk:
                    target_pdks.append(pdk)

    else:  # analyze
        sources: list[tuple[str | None, str | None, str | None]] = []

        if len(processes) >= 2:
            for p in processes[:2]:
                sources.append((p, None, None))
        elif len(processes) == 1:
            sources.append((processes[0], None, None))
        elif len(projects) >= 1:
            for p in projects[:2]:
                sources.append((None, p, None))
        elif len(project_names) >= 1:
            for pn in project_names[:2]:
                sources.append((None, None, pn))

        if not sources:
            choice = _ask_user("어떤 공정에서 확인할까요?", [])
            sources.append((choice.strip(), None, None))

        for proc, proj, pname in sources:
            pdk = _resolve_single_pdk(proc, proj, pname, mask_hint=mask_hint)
            if pdk:
                target_pdks.append(pdk)

        # comparison_version: 같은 project의 다른 버전 목록을 테이블로 제시
        if "comparison_version" in missing_params and len(target_pdks) == 1:
            primary = target_pdks[0]
            all_options = _query_golden_options(None, primary["project"], None)
            other_options = [
                r for r in all_options
                if not (r["MASK"] == primary["mask"] and r["DK_GDS"] == primary["dk_gds"])
            ]
            if other_options:
                r = _pick_from_options(other_options, "비교할 이전 버전을 선택해주세요.")
                pdk_row = _get_latest_pdk(r["PROJECT"], r["MASK"], r["DK_GDS"],
                                          r["HSPICE"], r["LVS"], r["PEX"])
                if pdk_row:
                    target_pdks.append(_row_to_resolved_pdk(pdk_row))
            else:
                # 동일 project에 다른 버전이 없으면 자유 입력
                choice = _ask_user("비교할 이전 버전을 입력해주세요. (예: EVT0)", [])
                rows = _query_golden_options(None, primary["project"], None,
                                             mask_hint=choice.strip())
                if rows:
                    r = rows[0] if len(rows) == 1 else _pick_from_options(
                        rows, "비교할 버전을 선택해주세요.")
                    pdk_row = _get_latest_pdk(r["PROJECT"], r["MASK"], r["DK_GDS"],
                                              r["HSPICE"], r["LVS"], r["PEX"])
                    if pdk_row:
                        target_pdks.append(_row_to_resolved_pdk(pdk_row))

    if not target_pdks:
        return {"error": "PDK를 특정할 수 없습니다."}

    mode = "single" if len(target_pdks) == 1 else "pair" if len(target_pdks) == 2 else "multi"

    hint = entities.get("analysis_hint")
    resolved_params: dict[str, Any] = {}
    sensitivity_axis = None

    if hint == "sensitivity":
        entities_with_q = dict(entities)
        entities_with_q["_raw_question"] = parsed.get("raw_question", "")
        sensitivity_axis = _infer_sensitivity_axis(entities_with_q)

        if sensitivity_axis and sensitivity_axis in SENSITIVITY_AXIS_MAP:
            db_col, entity_key = SENSITIVITY_AXIS_MAP[sensitivity_axis]
            available_per_pdk = {}
            for pdk in target_pdks:
                vals = _query_available_values(pdk["pdk_id"], db_col)
                available_per_pdk[pdk["pdk_id"]] = vals
            resolved_params["sensitivity_axis"] = sensitivity_axis
            resolved_params["sensitivity_col"] = db_col
            resolved_params["sensitivity_entity_key"] = entity_key
            resolved_params["available_values"] = available_per_pdk

    return {
        "pdk_resolution": PDKResolution(
            target_pdks=target_pdks,
            comparison_mode=mode,
            resolved_params=resolved_params,
            applied_defaults=_build_applied_defaults(entities, sensitivity_axis),
        ),
    }
