from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from shared.db import execute_query
from state import PaveAgentState, PDKResolution, ResolvedPDK

logger = logging.getLogger(__name__)

# --- PDK 조회 SQL 템플릿 ---

SQL_PROJECTS_BY_PROCESS = """
    SELECT DISTINCT PROJECT, PROJECT_NAME, PROCESS
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROCESS = '{process}'
    FETCH FIRST 20 ROWS ONLY
"""

SQL_PROJECTS_BY_NAME = """
    SELECT DISTINCT PROJECT, PROJECT_NAME, PROCESS
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT_NAME = '{name}'
    FETCH FIRST 20 ROWS ONLY
"""

SQL_PROJECTS_BY_CODE = """
    SELECT DISTINCT PROJECT, PROJECT_NAME, PROCESS
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}'
    FETCH FIRST 20 ROWS ONLY
"""

SQL_MASKS_BY_PROJECT = """
    SELECT DISTINCT MASK
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}'
    FETCH FIRST 10 ROWS ONLY
"""

SQL_DK_GDS_BY_PROJECT_MASK = """
    SELECT DISTINCT DK_GDS
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}' AND MASK = '{mask}'
    FETCH FIRST 10 ROWS ONLY
"""

SQL_GOLDEN_PDK = """
    SELECT PDK_ID, PROJECT, PROJECT_NAME, PROCESS, MASK, DK_GDS,
           HSPICE, LVS, PEX, IS_GOLDEN, VDD_NOMINAL
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}' AND MASK = '{mask}' AND IS_GOLDEN = 1
    FETCH FIRST 5 ROWS ONLY
"""

SQL_ALL_PDKS_BY_PROJECT_MASK = """
    SELECT PDK_ID, PROJECT, PROJECT_NAME, PROCESS, MASK, DK_GDS,
           HSPICE, LVS, PEX, IS_GOLDEN, VDD_NOMINAL
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}' AND MASK = '{mask}'
    FETCH FIRST 10 ROWS ONLY
"""


def _ask_user(question: str, options: list[str]) -> str:
    """사용자에게 선택을 요청 (interrupt)"""
    result = interrupt({
        "question": question,
        "options": options,
    })
    return str(result)


def _resolve_project(process: str | None, project: str | None,
                     project_name: str | None) -> dict:
    """process/project/project_name으로 project 특정"""
    if project:
        rows = execute_query(SQL_PROJECTS_BY_CODE.format(project=project))
        if rows:
            return rows[0]

    if project_name:
        rows = execute_query(SQL_PROJECTS_BY_NAME.format(name=project_name))
        if rows:
            if len(rows) == 1:
                return rows[0]
            options = [f"{r['PROJECT_NAME']} ({r['PROJECT']}, {r['PROCESS']})" for r in rows]
            choice = _ask_user(
                f"'{project_name}'에 해당하는 프로젝트가 여러 개 있습니다. 선택해주세요.",
                options,
            )
            idx = _parse_choice(choice, len(rows))
            return rows[idx]

    if process:
        rows = execute_query(SQL_PROJECTS_BY_PROCESS.format(process=process))
        if not rows:
            return {}
        if len(rows) == 1:
            return rows[0]
        options = [f"{r['PROJECT_NAME']} ({r['PROJECT']})" for r in rows]
        choice = _ask_user(
            f"{process}에 {', '.join(options)}이(가) 있습니다. 선택해주세요.",
            options,
        )
        idx = _parse_choice(choice, len(rows))
        return rows[idx]

    return {}


def _resolve_mask(project: str) -> str:
    """project의 mask 특정"""
    rows = execute_query(SQL_MASKS_BY_PROJECT.format(project=project))
    if not rows:
        return ""
    if len(rows) == 1:
        return rows[0]["MASK"]
    options = [r["MASK"] for r in rows]
    choice = _ask_user(
        f"마스크 버전을 선택해주세요.",
        options,
    )
    idx = _parse_choice(choice, len(rows))
    return rows[idx]["MASK"]


def _resolve_golden(project: str, mask: str) -> dict | None:
    """golden PDK 조회. 없으면 전체 조회 후 선택"""
    rows = execute_query(SQL_GOLDEN_PDK.format(project=project, mask=mask))
    if rows:
        if len(rows) == 1:
            return rows[0]
        # golden이 여러 개인 경우
        options = [f"{r['DK_GDS']} (HSPICE={r['HSPICE']})" for r in rows]
        choice = _ask_user("Golden 버전이 여러 개 있습니다. 선택해주세요.", options)
        idx = _parse_choice(choice, len(rows))
        return rows[idx]

    # golden 없음 → 전체에서 선택
    rows = execute_query(SQL_ALL_PDKS_BY_PROJECT_MASK.format(project=project, mask=mask))
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    options = [f"{r['DK_GDS']} (Golden={'Y' if r['IS_GOLDEN'] else 'N'})" for r in rows]
    choice = _ask_user("Golden PDK가 없습니다. 버전을 선택해주세요.", options)
    idx = _parse_choice(choice, len(rows))
    return rows[idx]


def _parse_choice(choice: str, max_idx: int) -> int:
    """사용자 응답을 인덱스로 변환"""
    choice = choice.strip()
    # 숫자 응답
    try:
        idx = int(choice) - 1
        if 0 <= idx < max_idx:
            return idx
    except ValueError:
        pass
    # 텍스트 매칭은 0번째로 fallback
    return 0


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


def _resolve_single_pdk(process: str | None, project: str | None,
                         project_name: str | None) -> ResolvedPDK | None:
    """하나의 process/project 소스로부터 PDK 1개 특정"""
    proj_row = _resolve_project(process, project, project_name)
    if not proj_row:
        return None
    proj_code = proj_row["PROJECT"]

    mask = _resolve_mask(proj_code)
    if not mask:
        return None

    pdk_row = _resolve_golden(proj_code, mask)
    if not pdk_row:
        return None

    return _row_to_resolved_pdk(pdk_row)


SQL_AVAILABLE_VALUES = """
    SELECT DISTINCT d.{col}
    FROM antsdb.PAVE_PPA_DATA_VIEW d
    WHERE d.PDK_ID = {pdk_id}
    FETCH FIRST 50 ROWS ONLY
"""

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


def _infer_sensitivity_axis(entities: dict) -> str | None:
    """sensitivity 분석의 변동축 추론

    질문에서 언급된 파라미터 또는 키워드로 판단.
    """
    raw_q = entities.get("_raw_question", "").lower()

    # 명시적 키워드
    if any(w in raw_q for w in ["온도", "temp", "temperature"]):
        return "temp"
    if any(w in raw_q for w in ["전압", "vdd", "voltage"]):
        return "vdd"
    if any(w in raw_q for w in ["corner", "공정 편차"]):
        return "corner"
    if any(w in raw_q for w in ["vth", "threshold"]):
        return "vth"

    # entity에 값이 2개 이상이면 그것이 변동축
    for ent_key, (_, _) in SENSITIVITY_AXIS_MAP.items():
        _, entity_key = SENSITIVITY_AXIS_MAP[ent_key]
        if len(entities.get(entity_key, [])) >= 2:
            return ent_key

    # 기본: temp
    return "temp"


def _query_available_values(pdk_id: int, col: str) -> list:
    """특정 PDK에서 가용한 파라미터 값 조회"""
    rows = execute_query(
        SQL_AVAILABLE_VALUES.format(col=col, pdk_id=pdk_id)
    )
    values = sorted([r[col] for r in rows])
    return values


def _build_applied_defaults(entities: dict, sensitivity_axis: str | None = None) -> dict[str, str]:
    """적용된 기본값 목록 생성

    sensitivity_axis가 지정되면 해당 축은 기본값 대신 '전체'로 표시.
    """
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


def pdk_resolver(state: PaveAgentState) -> dict:
    """PDK 버전 특정 (코드 기반, ask_user interrupt)"""
    parsed = state["parsed_intent"]
    intent = parsed["intent"]
    entities = parsed["entities"]

    processes = entities.get("processes") or []
    projects = entities.get("projects") or []
    project_names = entities.get("project_names") or []

    target_pdks: list[ResolvedPDK] = []

    if intent == "trend":
        # trend: 3~5개 PDK — process 목록으로 각각 resolve
        sources = processes or project_names or projects
        if not sources:
            # process 미지정 → 사용자에게 요청
            choice = _ask_user(
                "추이 분석할 공정을 3개 이상 입력해주세요. (예: SF2, SF2P, SF3)",
                [],
            )
            sources = [s.strip() for s in choice.split(",")]
        for src in sources[:5]:
            pdk = _resolve_single_pdk(src, None, None)
            if pdk:
                target_pdks.append(pdk)

    elif intent == "anomaly":
        # anomaly: 정확히 2개 PDK
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

    else:
        # analyze: entity에 process/project가 몇 개 있느냐로 1~2 PDK
        # 소스 목록 구성
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
            # process/project 미지정 → 사용자에게 요청
            choice = _ask_user("어떤 공정에서 확인할까요?", [])
            sources.append((choice.strip(), None, None))

        for proc, proj, pname in sources:
            pdk = _resolve_single_pdk(proc, proj, pname)
            if pdk:
                target_pdks.append(pdk)

    if not target_pdks:
        return {"error": "PDK를 특정할 수 없습니다."}

    # comparison_mode 결정
    if len(target_pdks) == 1:
        mode = "single"
    elif len(target_pdks) == 2:
        mode = "pair"
    else:
        mode = "multi"

    # sensitivity 축 처리
    hint = entities.get("analysis_hint")
    resolved_params: dict[str, Any] = {}
    sensitivity_axis = None

    if hint == "sensitivity":
        # raw_question을 entities에 임시 전달하여 축 추론
        entities_with_q = dict(entities)
        entities_with_q["_raw_question"] = parsed.get("raw_question", "")
        sensitivity_axis = _infer_sensitivity_axis(entities_with_q)

        if sensitivity_axis and sensitivity_axis in SENSITIVITY_AXIS_MAP:
            db_col, entity_key = SENSITIVITY_AXIS_MAP[sensitivity_axis]
            # 각 PDK에서 가용 값 조회
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
