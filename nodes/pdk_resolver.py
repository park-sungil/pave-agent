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

# sensitivity 분석 시 PDK별 가용 파라미터 값 조회 (유일한 SQL)
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
                validated.append(c)

        return {"candidates": validated, "message": result.get("message", "")}

    except Exception as e:
        logger.warning("_llm_select_from_catalog 실패: %s", e)
        return {"candidates": [], "message": ""}


def _filter_pdks(available_pdks: list[dict], cand: dict,
                 mask_hint: str | None = None) -> list[dict]:
    """candidate 조건으로 available_pdks 인메모리 필터링.

    IS_GOLDEN=1 항목이 있으면 우선 반환.
    """
    result = available_pdks
    if cand.get("process"):
        result = [p for p in result if p.get("PROCESS") == cand["process"]]
    if cand.get("project"):
        result = [p for p in result if p.get("PROJECT") == cand["project"]]
    if cand.get("project_name"):
        result = [p for p in result if p.get("PROJECT_NAME") == cand["project_name"]]
    if mask_hint:
        result = [p for p in result if p.get("MASK") == mask_hint]
    golden = [p for p in result if p.get("IS_GOLDEN") == 1]
    return golden if golden else result


def _resolve_candidates(candidates: list[dict], available_pdks: list[dict],
                         mask_hint: str | None) -> list[dict]:
    """LLM candidates → available_pdks 필터링 → 버전 선택 → 확정 엔트리 목록"""
    resolved = []
    for cand in candidates[:5]:
        matches = _filter_pdks(available_pdks, cand, mask_hint)
        if not matches:
            continue
        if len(matches) == 1:
            resolved.append(matches[0])
        else:
            label = cand.get("process") or cand.get("project_name") or "?"
            chosen = _pick_from_options(matches, f"분석할 버전을 선택해주세요. ({label})")
            resolved.append(chosen)
    return resolved


def _pick_from_options(entries: list[dict], question: str) -> dict:
    """여러 옵션 중 사용자 선택. 전체 컬럼 테이블로 표시."""
    table_rows = [[str(e.get(h, "")) for h in _VERSION_TABLE_HEADERS] for e in entries]
    options = [str(i) for i in range(1, len(entries) + 1)]
    choice = _ask_user(question, options,
                       table_headers=_VERSION_TABLE_HEADERS,
                       table_rows=table_rows)
    return entries[_parse_choice(choice, len(entries))]


def _entry_to_resolved_pdk(entry: dict) -> ResolvedPDK:
    """pdk_cache 항목 → ResolvedPDK 변환 (DB 쿼리 없음)"""
    return ResolvedPDK(
        pdk_id=entry["PDK_ID"],
        process=entry.get("PROCESS", ""),
        project=entry["PROJECT"],
        project_name=entry["PROJECT_NAME"],
        mask=entry["MASK"],
        dk_gds=entry["DK_GDS"],
        is_golden=entry.get("IS_GOLDEN", 0),
        hspice=entry.get("HSPICE", ""),
        lvs=entry.get("LVS", ""),
        pex=entry.get("PEX", ""),
        vdd_nominal=entry.get("VDD_NOMINAL", 0.0),
    )


def _ask_user_catalog(msg: str, available_pdks: list[dict]) -> str:
    """PROCESS/PROJECT_NAME 예시를 인라인으로 보여주며 사용자에게 질문."""
    examples: list[str] = []
    seen: set[str] = set()
    for p in available_pdks:
        val = p.get("PROCESS") or p.get("PROJECT_NAME") or ""
        if val and val not in seen:
            examples.append(val)
            seen.add(val)
        if len(examples) >= 5:
            break
    hint = f"(예: {', '.join(examples)}, ...)" if examples else ""
    question = f"{msg} {hint}".strip()
    return _ask_user(question, [])


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
    """PDK 버전 특정 (LLM-light 루프 + interrupt, SQL 없음)"""
    parsed = state["parsed_intent"]
    entities = parsed["entities"]
    available_pdks = state.get("available_pdks") or []
    masks = entities.get("masks") or []
    mask_hint: str | None = masks[0] if len(masks) == 1 else None

    question = parsed["raw_question"]

    _CANCEL_KEYWORDS = {"취소", "그만", "cancel", "quit", "종료", "stop", "넘어가"}
    _MAX_RETRIES = 3

    # PDK 확정될 때까지 루프 (최대 3회 사용자 질문)
    for _attempt in range(_MAX_RETRIES + 1):
        result = _llm_select_from_catalog(question, parsed["intent"], available_pdks)
        candidates = result.get("candidates") or []
        target_entries = _resolve_candidates(candidates, available_pdks, mask_hint)
        if target_entries:
            break

        if _attempt >= _MAX_RETRIES:
            return {"error": "공정을 특정할 수 없습니다. 질문에 공정명(예: SF3, SF2P)을 포함해 다시 시도해주세요."}

        msg = result.get("message") or "분석할 공정을 선택해주세요."
        question = _ask_user_catalog(msg, available_pdks)

        # 취소 키워드 → 즉시 종료
        if any(kw in question.lower() for kw in _CANCEL_KEYWORDS):
            return {"error": "PDK 선택이 취소되었습니다. 다른 질문을 입력해주세요."}

    target_pdks = [_entry_to_resolved_pdk(e) for e in target_entries]

    # comparison_version: 같은 project의 다른 버전 목록 제시
    missing_params = parsed.get("missing_params") or []
    if "comparison_version" in missing_params and len(target_pdks) == 1:
        primary = target_pdks[0]
        others = [
            p for p in available_pdks
            if p.get("PROJECT") == primary["project"]
            and not (p.get("MASK") == primary["mask"] and p.get("DK_GDS") == primary["dk_gds"])
            and p.get("IS_GOLDEN") == 1
        ]
        if others:
            chosen = others[0] if len(others) == 1 else _pick_from_options(
                others, "비교할 이전 버전을 선택해주세요.")
            target_pdks.append(_entry_to_resolved_pdk(chosen))
        else:
            question = _ask_user("비교할 이전 버전을 입력해주세요. (예: EVT0)", [])
            cand = {"process": primary["process"]}
            matches = _filter_pdks(available_pdks, cand, mask_hint=question.strip())
            if matches:
                target_pdks.append(_entry_to_resolved_pdk(matches[0]))

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
