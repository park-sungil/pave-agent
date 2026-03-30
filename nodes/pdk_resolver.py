from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.types import interrupt

from shared.db import execute_query
from shared.llm import get_llm
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

# LLM 프롬프트: 카탈로그에서 공정 선택
CATALOG_SYSTEM_PROMPT = """\
사용자의 반도체 PPA 분석 질문에서 분석 대상 공정을 아래 등록된 목록에서 찾아 JSON으로 반환하세요.
목록에 없는 이름을 만들지 마세요.

# 등록 공정 (PROCESS | PROJECT_NAME 예시)
{catalog}

# 출력 (JSON만, 설명 없이)
특정 가능:   {{"candidates": [{{"process": "SF3"}}]}}
비교/트렌드: {{"candidates": [{{"process": "SF3"}}, {{"process": "SF2P"}}]}}
project_name 기준: {{"candidates": [{{"project_name": "Thetis"}}]}}
정보 부족:   {{"candidates": [], "message": "어떤 공정에서 분석할까요?"}}
목록에 없음: {{"candidates": [], "message": "'XXX'는 등록된 공정이 아닙니다. 아래 목록에서 선택해주세요."}}
"""


# ──────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────

def _ask_user(question: str, options: list[str],
              table_headers: list[str] | None = None,
              table_rows: list[list[str]] | None = None) -> str:
    """사용자에게 선택을 요청 (interrupt)."""
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


def _build_catalog(available_pdks: list[dict]) -> str:
    """PROCESS별 PROJECT_NAME 예시 최대 3개를 텍스트로 구성 (LLM 프롬프트용)"""
    grouped: dict[str, list[str]] = defaultdict(list)
    for pdk in available_pdks:
        process = pdk.get("PROCESS") or ""
        pname = pdk.get("PROJECT_NAME") or ""
        if process and pname and pname not in grouped[process]:
            grouped[process].append(pname)

    lines = []
    for process in sorted(grouped.keys()):
        examples = grouped[process][:3]
        lines.append(f"{process} | {', '.join(examples)}")
    return "\n".join(lines)


def _llm_select_from_catalog(question: str, intent: str,
                              available_pdks: list[dict]) -> dict:
    """LLM이 카탈로그에서 분석 대상 공정을 선택.

    반환: {"candidates": [...], "message": "..."}
    candidates가 비어있으면 사용자 interrupt로 넘긴다.
    """
    if not available_pdks:
        return {"candidates": [], "message": "등록된 공정 목록이 없습니다."}

    catalog = _build_catalog(available_pdks)
    system_prompt = CATALOG_SYSTEM_PROMPT.format(catalog=catalog)

    # 검증용 집합
    valid_processes = {p.get("PROCESS") for p in available_pdks if p.get("PROCESS")}
    valid_project_names = {p.get("PROJECT_NAME") for p in available_pdks if p.get("PROJECT_NAME")}

    try:
        llm = get_llm("light")
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=question),
        ])
        text = response.content.strip()

        # JSON 추출
        if "```" in text:
            for part in text.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    text = part
                    break
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]

        result = json.loads(text)
        candidates = result.get("candidates") or []

        # 검증: 목록에 실제 존재하는 값만 허용
        validated = []
        for c in candidates:
            if c.get("process") and c["process"] in valid_processes:
                validated.append(c)
            elif c.get("project_name") and c["project_name"] in valid_project_names:
                validated.append(c)
            elif c.get("project"):
                # project 코드는 available_pdks에 없으므로 그대로 허용 (DB 조회에서 확인)
                validated.append(c)

        return {"candidates": validated, "message": result.get("message", "")}

    except Exception as e:
        logger.warning("_llm_select_from_catalog 실패: %s", e)
        return {"candidates": [], "message": ""}


def _build_catalog_interrupt(available_pdks: list[dict]) -> tuple[list[list[str]], list[str]]:
    """distinct PROCESS 순서로 번호 선택 테이블 생성.

    반환: (table_rows, options)
    table_rows: [[번호, PROCESS, PROJECT_NAME 예시], ...]
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for pdk in available_pdks:
        process = pdk.get("PROCESS") or ""
        pname = pdk.get("PROJECT_NAME") or ""
        if process and pname and pname not in grouped[process]:
            grouped[process].append(pname)

    table_rows = []
    for i, process in enumerate(sorted(grouped.keys()), start=1):
        examples = ", ".join(grouped[process][:3])
        table_rows.append([str(i), process, examples])

    options = [str(i) for i in range(1, len(table_rows) + 1)]
    return table_rows, options


def _query_golden_options(process: str | None, project: str | None,
                           project_name: str | None,
                           mask_hint: str | None = None) -> list[dict]:
    """IS_GOLDEN=1 레코드를 조회하여 선택 가능한 버전 목록 반환."""
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
        if rows:
            return rows
        # project_name으로 재시도 (사용자가 "Thetis" 등을 process 필드에 넣은 경우)
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


def _build_applied_defaults(
    entities: dict,
    sensitivity_axis: str | None = None,
    optimization_axes: list[str] | None = None,
) -> dict[str, str]:
    """적용된 기본값 목록 생성"""
    opt_axes = set(optimization_axes or [])
    defaults = {}
    if not entities.get("corners"):
        defaults["corner"] = "전체" if sensitivity_axis == "corner" else "TT"
    if not entities.get("temps"):
        defaults["temp"] = "전체" if sensitivity_axis == "temp" else "25"
    if not entities.get("vdds"):
        defaults["vdd"] = "전체" if (sensitivity_axis == "vdd" or "VDD" in opt_axes) else "nominal"
    if not entities.get("vths") and "VTH" in opt_axes:
        defaults["vth"] = "전체"
    if not entities.get("cells"):
        defaults["cell"] = "AVG(INV/ND2/NR2)"
    if not entities.get("drive_strengths"):
        defaults["ds"] = "AVG(D1/D4)"
    return defaults


# ──────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────

def pdk_resolver(state: PaveAgentState) -> dict:
    """PDK 버전 특정 (LLM-light 카탈로그 선택 + ask_user interrupt)"""
    parsed = state["parsed_intent"]
    entities = parsed["entities"]
    available_pdks = state.get("available_pdks") or []
    masks = entities.get("masks") or []
    mask_hint: str | None = masks[0] if len(masks) == 1 else None

    # Step 1: LLM이 카탈로그에서 공정 선택
    result = _llm_select_from_catalog(parsed["raw_question"], parsed["intent"], available_pdks)
    candidates = result.get("candidates") or []

    # Step 2: LLM 판단 불가 → 사용자에게 카탈로그 표시
    if not candidates:
        msg = result.get("message") or "분석할 공정을 선택해주세요."
        table_rows, options = _build_catalog_interrupt(available_pdks)
        answer = _ask_user(
            msg, options,
            table_headers=["번호", "PROCESS", "PROJECT_NAME 예시"],
            table_rows=table_rows,
        )
        idx = _parse_choice(answer, len(table_rows))
        candidates = [{"process": table_rows[idx][1]}]

    # Step 3: DB 조회 + 버전 선택
    target_pdks: list[ResolvedPDK] = []
    for cand in candidates[:5]:
        rows = _query_golden_options(
            process=cand.get("process"),
            project=cand.get("project"),
            project_name=cand.get("project_name"),
            mask_hint=mask_hint,
        )
        if not rows:
            continue
        label = cand.get("process") or cand.get("project_name") or "?"
        r = rows[0] if len(rows) == 1 else _pick_from_options(
            rows, f"분석할 버전을 선택해주세요. ({label})"
        )
        pdk_row = _get_latest_pdk(
            r["PROJECT"], r["MASK"], r["DK_GDS"], r["HSPICE"], r["LVS"], r["PEX"]
        )
        if pdk_row:
            target_pdks.append(_row_to_resolved_pdk(pdk_row))

    # comparison_version: 같은 project의 다른 버전 목록을 테이블로 제시
    missing_params = parsed.get("missing_params") or []
    if "comparison_version" in missing_params and len(target_pdks) == 1:
        primary = target_pdks[0]
        all_options = _query_golden_options(None, primary["project"], None)
        other_options = [
            r for r in all_options
            if not (r["MASK"] == primary["mask"] and r["DK_GDS"] == primary["dk_gds"])
        ]
        if other_options:
            r = _pick_from_options(other_options, "비교할 이전 버전을 선택해주세요.")
            pdk_row = _get_latest_pdk(
                r["PROJECT"], r["MASK"], r["DK_GDS"], r["HSPICE"], r["LVS"], r["PEX"]
            )
            if pdk_row:
                target_pdks.append(_row_to_resolved_pdk(pdk_row))
        else:
            choice = _ask_user("비교할 이전 버전을 입력해주세요. (예: EVT0)", [])
            rows = _query_golden_options(None, primary["project"], None,
                                         mask_hint=choice.strip())
            if rows:
                r = rows[0] if len(rows) == 1 else _pick_from_options(
                    rows, "비교할 버전을 선택해주세요.")
                pdk_row = _get_latest_pdk(
                    r["PROJECT"], r["MASK"], r["DK_GDS"], r["HSPICE"], r["LVS"], r["PEX"]
                )
                if pdk_row:
                    target_pdks.append(_row_to_resolved_pdk(pdk_row))

    # Step 4: 진짜 시스템 오류 (DB에 데이터 없음)
    if not target_pdks:
        return {"error": "선택한 공정의 PDK 데이터가 DB에 없습니다."}

    mode = "single" if len(target_pdks) == 1 else "pair" if len(target_pdks) == 2 else "multi"

    hint = entities.get("analysis_hint")
    resolved_params: dict[str, Any] = {}
    sensitivity_axis = None
    optimization_axes: list[str] = []

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

    elif hint == "optimization":
        raw_q = parsed.get("raw_question", "").lower()
        if any(w in raw_q for w in ["전압", "vdd", "voltage", "volt"]):
            optimization_axes.append("VDD")
        if any(w in raw_q for w in ["flavor", "vth", "threshold", "조합"]):
            optimization_axes.append("VTH")
        if not optimization_axes:
            optimization_axes.append("VDD")
        resolved_params["optimization_axes"] = optimization_axes

    return {
        "pdk_resolution": PDKResolution(
            target_pdks=target_pdks,
            comparison_mode=mode,
            resolved_params=resolved_params,
            applied_defaults=_build_applied_defaults(
                entities, sensitivity_axis, optimization_axes
            ),
        ),
    }
