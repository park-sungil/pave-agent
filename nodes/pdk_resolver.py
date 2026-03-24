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

SQL_GOLDEN_BY_PROJECT_MASK_DK_GDS = """
    SELECT PDK_ID, PROJECT, PROJECT_NAME, PROCESS, MASK, DK_GDS,
           HSPICE, LVS, PEX, IS_GOLDEN, VDD_NOMINAL
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}' AND MASK = '{mask}' AND DK_GDS = '{dk_gds}'
      AND IS_GOLDEN = 1
    FETCH FIRST 1 ROW ONLY
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


def _resolve_mask(project: str, mask_hint: str | None = None) -> str:
    """project의 mask 특정.

    mask_hint가 주어지고 DB에 존재하면 바로 사용 (재질문 없음).
    """
    rows = execute_query(SQL_MASKS_BY_PROJECT.format(project=project))
    if not rows:
        return ""
    options = [r["MASK"] for r in rows]
    # 사용자가 명시한 mask가 DB에 있으면 바로 반환
    if mask_hint:
        matched = next((o for o in options if o.upper() == mask_hint.upper()), None)
        if matched:
            return matched
    if len(options) == 1:
        return options[0]
    choice = _ask_user("마스크 버전을 선택해주세요.", options)
    idx = _parse_choice(choice, len(options))
    return options[idx]


def _resolve_dk_gds(project: str, mask: str) -> str | None:
    """project+mask에서 DK_GDS 특정.

    1개이면 자동 선택. 여러 개이면 사용자 선택.
    IS_GOLDEN은 project+mask+dk_gds 단위이므로 이 단계에서 golden으로
    좁히는 것은 의미 없음 (dk_gds마다 golden이 각각 존재).
    """
    rows = execute_query(SQL_DK_GDS_BY_PROJECT_MASK.format(project=project, mask=mask))
    if not rows:
        return None
    options = [r["DK_GDS"] for r in rows]
    if len(options) == 1:
        return options[0]
    choice = _ask_user(f"DK_GDS 버전을 선택해주세요. ({project} {mask})", options)
    idx = _parse_choice(choice, len(options))
    return options[idx]


def _get_golden_record(project: str, mask: str,
                       dk_gds: str) -> tuple[str, str, str] | None:
    """project+mask+dk_gds의 IS_GOLDEN=1 레코드에서 HSPICE+LVS+PEX 확정.

    이 조합에 IS_GOLDEN은 반드시 1개 존재하므로 사용자 선택 불필요.
    """
    rows = execute_query(SQL_GOLDEN_BY_PROJECT_MASK_DK_GDS.format(
        project=project, mask=mask, dk_gds=dk_gds))
    if not rows:
        return None
    r = rows[0]
    return r["HSPICE"], r["LVS"], r["PEX"]


def _get_latest_pdk(project: str, mask: str, dk_gds: str,
                    hspice: str, lvs: str, pex: str) -> dict | None:
    """project+mask+dk_gds+hspice+lvs+pex 조합에서 최신 pdk_id 조회"""
    rows = execute_query(SQL_LATEST_PDK.format(
        project=project, mask=mask, dk_gds=dk_gds,
        hspice=hspice, lvs=lvs, pex=pex,
    ))
    return rows[0] if rows else None


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
                         project_name: str | None,
                         mask_hint: str | None = None) -> ResolvedPDK | None:
    """하나의 process/project 소스로부터 PDK 1개 특정.

    계층 순서: project → mask → dk_gds → hspice+lvs+pex → 최신 pdk_id
    """
    proj_row = _resolve_project(process, project, project_name)
    if not proj_row:
        return None
    proj_code = proj_row["PROJECT"]

    mask = _resolve_mask(proj_code, mask_hint=mask_hint)
    if not mask:
        return None

    dk_gds = _resolve_dk_gds(proj_code, mask)
    if not dk_gds:
        return None

    combo = _get_golden_record(proj_code, mask, dk_gds)
    if not combo:
        return None
    hspice, lvs, pex = combo

    pdk_row = _get_latest_pdk(proj_code, mask, dk_gds, hspice, lvs, pex)
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
    masks = entities.get("masks") or []
    missing_params = parsed.get("missing_params") or []

    # 사용자가 명시한 mask가 하나면 hint로 사용 (여러 개면 모호하므로 무시)
    mask_hint: str | None = masks[0] if len(masks) == 1 else None

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
            pdk = _resolve_single_pdk(proc, proj, pname, mask_hint=mask_hint)
            if pdk:
                target_pdks.append(pdk)

        # comparison_version 요청: "이전 버전 대비" 비교가 필요하지만 1개 PDK만 resolve된 경우
        if "comparison_version" in missing_params and len(target_pdks) == 1:
            primary = target_pdks[0]
            choice = _ask_user(
                f"비교할 이전 버전을 알려주세요. (예: EVT0)",
                [],
            )
            comp_mask = choice.strip()
            pdk2 = _resolve_single_pdk(None, primary["project"], None, mask_hint=comp_mask)
            if pdk2:
                target_pdks.append(pdk2)

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
