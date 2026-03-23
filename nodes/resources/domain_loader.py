from __future__ import annotations

import os
import re
from typing import Any

_DOMAIN_PATH = os.path.join(os.path.dirname(__file__), "pave_domain.md")

# 섹션 캐시
_sections: dict[str, str] = {}


def _load_sections() -> dict[str, str]:
    """pave_domain.md를 ## 섹션별로 분할하여 캐싱"""
    global _sections
    if _sections:
        return _sections

    with open(_DOMAIN_PATH, encoding="utf-8") as f:
        content = f.read()

    # ## 헤더 기준으로 분할
    parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 섹션 키 추출: "## 3. PPA 기본 Trade-off" → "3"
        match = re.match(r"^## (\d+)\.", part)
        if match:
            _sections[match.group(1)] = part

    return _sections


def load_domain_sections(entities: dict, intent: str,
                         pdk_count: int) -> str:
    """entity 기반으로 관련 도메인 지식 섹션 선택적 로딩

    SPEC 6.6의 매핑 테이블 구현:
    - vths 2종+ 또는 hint=tradeoff → 5.4 Vth
    - drive_strengths 2종+ → 5.1 Drive Strength
    - temps 2종+ 또는 hint=sensitivity → 6.1 Temperature
    - vdds 2종+ 또는 hint=sensitivity → 6.2 VDD
    - cell_heights 2종+ → 5.3 Cell Height
    - nanosheet_widths 2종+ → 5.2 Nanosheet Width
    - pdk_count==2 또는 intent=trend → 3. PPA Trade-off
    - intent=anomaly → 6.1 + 6.2 + 5.4
    - hint=worst_case → 규칙 8 (Worst-case 매핑)
    - hint=tradeoff → 3. PPA Trade-off
    """
    sections = _load_sections()
    needed: set[str] = set()
    hint = entities.get("analysis_hint")

    # entity 기반 매핑
    if len(entities.get("vths", [])) >= 2 or hint == "tradeoff":
        needed.add("5")  # 5.4 Vth 포함
    if len(entities.get("drive_strengths", [])) >= 2:
        needed.add("5")  # 5.1 Drive Strength 포함
    if len(entities.get("temps", [])) >= 2 or hint == "sensitivity":
        needed.add("6")  # 6.1 Temperature
    if len(entities.get("vdds", [])) >= 2 or hint == "sensitivity":
        needed.add("6")  # 6.2 VDD
    if len(entities.get("cell_heights", [])) >= 2:
        needed.add("5")  # 5.3 Cell Height
    if len(entities.get("nanosheet_widths", [])) >= 2:
        needed.add("5")  # 5.2 Nanosheet Width

    # intent/pdk_count 기반
    if pdk_count >= 2 or intent == "trend":
        needed.add("3")  # PPA Trade-off
    if intent == "anomaly":
        needed.add("5")
        needed.add("6")
    if hint == "worst_case":
        needed.add("8")  # 쿼리 처리 규칙 (worst-case 매핑)
    if hint == "tradeoff":
        needed.add("3")

    # 아무것도 해당 없으면 기본: 섹션 3
    if not needed:
        needed.add("3")

    # 선택된 섹션 결합
    result_parts = []
    for key in sorted(needed):
        if key in sections:
            result_parts.append(sections[key])

    return "\n\n---\n\n".join(result_parts)
