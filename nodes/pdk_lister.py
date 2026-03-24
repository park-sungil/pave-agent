from __future__ import annotations

import logging
from collections import defaultdict

from shared.db import execute_query
from state import PaveAgentState

logger = logging.getLogger(__name__)

SQL_LIST_ALL = """
    SELECT DISTINCT PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS, HSPICE, LVS, PEX, IS_GOLDEN
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROCESS IS NOT NULL
    ORDER BY PROCESS, PROJECT, MASK
    FETCH FIRST 200 ROWS ONLY
"""

SQL_LIST_BY_PROCESS = """
    SELECT DISTINCT PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS, HSPICE, LVS, PEX, IS_GOLDEN
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROCESS = '{process}'
    ORDER BY PROJECT, MASK
    FETCH FIRST 50 ROWS ONLY
"""

SQL_LIST_BY_PROJECT = """
    SELECT DISTINCT PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS, HSPICE, LVS, PEX, IS_GOLDEN
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT = '{project}'
    ORDER BY MASK
    FETCH FIRST 50 ROWS ONLY
"""

SQL_LIST_BY_PROJECT_NAME = """
    SELECT DISTINCT PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS, HSPICE, LVS, PEX, IS_GOLDEN
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROJECT_NAME = '{project_name}'
    ORDER BY MASK
    FETCH FIRST 50 ROWS ONLY
"""


def _build_text(rows: list[dict]) -> tuple[str, list[dict]]:
    """DB 행 목록 → 사람이 읽기 좋은 텍스트 + data_tables 형식으로 변환"""
    if not rows:
        return "조회된 PDK가 없습니다.", []

    # process별 그룹핑
    by_process: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_process[r["PROCESS"]].append(r)

    lines = [f"총 {len(rows)}개 버전 조회됨.\n"]
    table_rows = []

    for process in sorted(by_process.keys()):
        entries = by_process[process]
        lines.append(f"### {process}")
        for e in entries:
            golden_mark = " [Golden]" if e.get("IS_GOLDEN") else ""
            lines.append(
                f"  - {e['PROJECT_NAME']} ({e['PROJECT']}) / MASK={e['MASK']}"
                f" / DK_GDS={e.get('DK_GDS', '')} / HSPICE={e.get('HSPICE', '')}"
                f" / LVS={e.get('LVS', '')} / PEX={e.get('PEX', '')}{golden_mark}"
            )
            table_rows.append([
                process,
                e["PROJECT"],
                e["PROJECT_NAME"],
                e["MASK"],
                e.get("DK_GDS", ""),
                e.get("HSPICE", ""),
                e.get("LVS", ""),
                e.get("PEX", ""),
                "Y" if e.get("IS_GOLDEN") else "N",
            ])
        lines.append("")

    text = "\n".join(lines).strip()
    data_table = {
        "title": "가용 PDK 목록",
        "headers": ["PROCESS", "PROJECT", "PROJECT_NAME", "MASK", "DK_GDS", "HSPICE", "LVS", "PEX", "IS_GOLDEN"],
        "rows": table_rows,
    }
    return text, [data_table]


def pdk_lister(state: PaveAgentState) -> dict:
    """가용 PDK 목록 조회 (코드 기반, LLM 없음)

    entities에 process/project가 지정된 경우 해당 범위만 조회,
    없으면 전체 목록 반환.
    """
    entities = state["parsed_intent"]["entities"]
    processes = entities.get("processes") or []
    projects = entities.get("projects") or []
    project_names = entities.get("project_names") or []

    rows: list[dict] = []

    if processes:
        for proc in processes:
            rows.extend(execute_query(SQL_LIST_BY_PROCESS.format(process=proc)))
    elif projects:
        for proj in projects:
            rows.extend(execute_query(SQL_LIST_BY_PROJECT.format(project=proj)))
    elif project_names:
        for pname in project_names:
            rows.extend(execute_query(SQL_LIST_BY_PROJECT_NAME.format(project_name=pname)))
    else:
        rows = execute_query(SQL_LIST_ALL)

    if not rows:
        return {"fallback_result": {"text": "조회된 PDK가 없습니다."}}

    text, data_tables = _build_text(rows)
    return {"fallback_result": {"text": text, "data_tables": data_tables}}
