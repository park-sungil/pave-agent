from __future__ import annotations

import json
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from nodes.resources.domain_loader import load_domain_sections
from shared.llm import get_llm
from state import PaveAgentState, Interpretation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 반도체 PDK PPA 분석 결과를 해석하는 전문가입니다.
아래 분석 결과와 도메인 지식을 바탕으로, 설계/검증 엔지니어에게 유용한 해석을 제공합니다.

## 응답 규칙
- 존댓말(합쇼체)을 사용합니다.
- DB 컬럼명(FREQ_GHZ, S_POWER 등)을 그대로 사용합니다. 한국어 번역이나 괄호 부연설명을 붙이지 않습니다.
- "golden PDK", "대표 버전", "프로젝트/마스크" 표현을 사용하지 않습니다. "버전"이라고 합니다.
- 평균 표기: "DS AVG(D1/D4)", "CELL AVG(INV/ND2/NR2)"
- 이모지를 사용하지 않습니다.
- 소극적 권장: "추천합니다" (X) → "검토해볼 만합니다" (O)
- 근거는 반드시 실측 데이터(분석 결과)에서 가져옵니다. 도메인 지식은 보조 설명으로만 활용합니다.

## 출력 형식

반드시 아래 JSON만 출력하세요. 설명이나 마크다운 없이 순수 JSON만.

```json
{
  "narrative": "한국어 해석 텍스트 (2~5문장)",
  "key_insights": ["핵심 인사이트 1", "핵심 인사이트 2"],
  "recommendations": ["소극적 권장 1"],
  "suggested_charts": [{"type": "grouped_bar", "title": "차트 제목"}],
  "additional_analysis": ["추가 분석 제안"]
}
```
"""


def _build_user_message(state: PaveAgentState, domain_knowledge: str) -> str:
    """interpreter에 전달할 사용자 메시지 구성"""
    parsed = state["parsed_intent"]
    resolution = state["pdk_resolution"]
    analysis = state["analysis_result"]
    entities = parsed["entities"]

    parts = []

    # 원래 질문
    parts.append(f"## 사용자 질문\n{parsed['raw_question']}")

    # PDK 정보
    pdk_info = []
    for pdk in resolution["target_pdks"]:
        pdk_info.append(
            f"- {pdk['project_name']} {pdk['mask']} "
            f"(PDK_ID={pdk['pdk_id']}, {pdk['process']}, VDD_NOM={pdk['vdd_nominal']}V)"
        )
    parts.append(f"## PDK 버전\n" + "\n".join(pdk_info))

    # 적용 기본값
    defaults = resolution.get("applied_defaults", {})
    if defaults:
        defaults_str = ", ".join(f"{k}={v}" for k, v in defaults.items())
        parts.append(f"## 적용 기본값\n{defaults_str}")

    # 분석 결과
    parts.append(f"## 분석 모드\n{analysis['mode']}")
    parts.append(f"## 분석 결과 (summary_table)\n{json.dumps(analysis['summary_table'], ensure_ascii=False, indent=2)}")

    # VTH tradeoff ratio 테이블이 있으면 포함
    ratio_table = analysis.get("chart_data", {}).get("ratio_table")
    ratio_ref = analysis.get("chart_data", {}).get("ratio_reference")
    if ratio_table:
        parts.append(
            f"## VTH ratio 테이블 (기준: {ratio_ref})\n"
            + json.dumps(ratio_table, ensure_ascii=False, indent=2)
        )

    if analysis["findings"]:
        parts.append(f"## 주요 발견\n{json.dumps(analysis['findings'], ensure_ascii=False, indent=2)}")

    # 도메인 지식
    if domain_knowledge:
        parts.append(f"## 참고 도메인 지식\n{domain_knowledge}")

    return "\n\n".join(parts)


def _parse_interpretation(text: str) -> dict | None:
    """LLM 응답에서 JSON 추출"""
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                cleaned = part
                break

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _fallback_interpretation(state: PaveAgentState) -> Interpretation:
    """LLM 실패 시 분석 결과만으로 기본 해석 생성 (graceful degradation)"""
    analysis = state["analysis_result"]
    findings = analysis.get("findings", [])

    narrative_parts = [f"분석 모드: {analysis['mode']}"]
    for f in findings[:5]:
        if f.get("type") == "change":
            narrative_parts.append(
                f"{f['metric']}: {f['delta_pct']}% {f.get('direction', '')}"
            )
        elif f.get("type") == "worst_case":
            narrative_parts.append(
                f"{f['metric']} worst: {f['value']}"
            )
        elif f.get("type") == "anomaly_cluster":
            narrative_parts.append(
                f"이상치 클러스터 [{f['cluster']}]: {f['count']}건"
            )

    return Interpretation(
        narrative=". ".join(narrative_parts) + ".",
        key_insights=[],
        recommendations=[],
        suggested_charts=[],
        additional_analysis=[],
    )


def interpreter(state: PaveAgentState) -> dict:
    """분석 결과 해석 (LLM-heavy)"""
    parsed = state["parsed_intent"]
    resolution = state["pdk_resolution"]
    entities = parsed["entities"]
    intent = parsed["intent"]
    pdk_count = len(resolution["target_pdks"])

    # 도메인 지식 선택적 로딩
    domain_knowledge = load_domain_sections(entities, intent, pdk_count)

    # 사용자 메시지 구성
    user_message = _build_user_message(state, domain_knowledge)

    # LLM 호출
    llm = get_llm("heavy")
    try:
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
        parsed_resp = _parse_interpretation(response.content)
    except Exception as e:
        logger.warning("interpreter LLM 호출 실패: %s", e)
        parsed_resp = None

    if not parsed_resp or "narrative" not in parsed_resp:
        logger.warning("interpreter JSON 파싱 실패 → fallback 해석")
        return {"interpretation": _fallback_interpretation(state)}

    return {
        "interpretation": Interpretation(
            narrative=parsed_resp.get("narrative", ""),
            key_insights=parsed_resp.get("key_insights", []),
            recommendations=parsed_resp.get("recommendations", []),
            suggested_charts=parsed_resp.get("suggested_charts", []),
            additional_analysis=parsed_resp.get("additional_analysis", []),
        ),
    }
