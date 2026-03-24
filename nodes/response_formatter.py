from __future__ import annotations

import json
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from shared.llm import get_llm
from state import PaveAgentState, FinalResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 반도체 PPA 분석 결과를 한국어로 정제하여 최종 응답을 만드는 포맷터입니다.

## 역할
1. 한국어 정제: 중국어 혼입 제거, 자연스러운 한국어로 변환
2. 응답 포맷팅: 핵심 수치를 강조하고 데이터 테이블을 적절히 배치

## 규칙
- 존댓말(합쇼체)
- DB 컬럼명(FREQ_GHZ, S_POWER 등) 그대로 사용. 한국어 번역/괄호 부연 금지
- "golden PDK", "대표 버전", "프로젝트/마스크" 표현 금지 → "버전"
- 평균 표기: "DS AVG(D1/D4)", "CELL AVG(INV/ND2/NR2)"
- 이모지 금지
- 소극적 권장: "추천합니다" (X) → "검토해볼 만합니다" (O)
- 중국어 문자가 있으면 반드시 한국어로 대체
- 숫자 비교는 테이블 형태로 정리, raw data + 변화율 함께 표시
- PDK/버전 목록 조회 결과는 반드시 마크다운 테이블로 출력

## 출력 형식

반드시 아래 JSON만 출력하세요.

```json
{
  "text": "정제된 한국어 응답 텍스트 (마크다운 테이블 포함 가능)",
  "data_tables": [{"title": "테이블 제목", "headers": ["col1", "col2"], "rows": [["v1", "v2"]]}]
}
```
"""


def _build_user_message(state: PaveAgentState) -> str:
    """포맷터에 전달할 사용자 메시지 구성"""
    parts = []

    # interpretation 또는 fallback_result
    interpretation = state.get("interpretation")
    fallback_result = state.get("fallback_result")

    if interpretation:
        parts.append(f"## 해석 결과\n{interpretation['narrative']}")
        if interpretation.get("key_insights"):
            parts.append("## 핵심 인사이트\n" + "\n".join(
                f"- {i}" for i in interpretation["key_insights"]
            ))
        if interpretation.get("recommendations"):
            parts.append("## 권장사항\n" + "\n".join(
                f"- {r}" for r in interpretation["recommendations"]
            ))
    elif fallback_result:
        parts.append(f"## Fallback 결과\n{fallback_result.get('text', '')}")

    # 분석 summary_table
    analysis = state.get("analysis_result")
    if analysis and analysis.get("summary_table"):
        parts.append(
            f"## 분석 데이터\n{json.dumps(analysis['summary_table'], ensure_ascii=False, indent=2)}"
        )

    # 적용 기본값
    resolution = state.get("pdk_resolution")
    if resolution and resolution.get("applied_defaults"):
        defaults = ", ".join(
            f"{k}={v}" for k, v in resolution["applied_defaults"].items()
        )
        parts.append(f"## 적용 기본값\n{defaults}")

    return "\n\n".join(parts)


def _parse_response(text: str) -> dict | None:
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


def _fallback_format(state: PaveAgentState) -> FinalResponse:
    """LLM 실패 시 interpreter 출력을 그대로 반환"""
    interpretation = state.get("interpretation")
    fallback_result = state.get("fallback_result")

    if interpretation:
        text = interpretation["narrative"]
    elif fallback_result:
        text = fallback_result.get("text", "응답을 생성할 수 없습니다.")
    else:
        text = "응답을 생성할 수 없습니다."

    resolution = state.get("pdk_resolution") or {}
    return FinalResponse(
        text=text,
        data_tables=[],
        charts=state.get("chart_specs") or [],
        applied_defaults=resolution.get("applied_defaults", {}),
        metadata={},
    )


def response_formatter(state: PaveAgentState) -> dict:
    """한국어 정제 + 응답 포맷팅 (LLM-light)"""
    user_message = _build_user_message(state)

    llm = get_llm("light")
    try:
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
        parsed = _parse_response(response.content)
    except Exception as e:
        logger.warning("response_formatter LLM 호출 실패: %s", e)
        parsed = None

    if not parsed or "text" not in parsed:
        logger.warning("response_formatter JSON 파싱 실패 → fallback")
        return {"final_response": _fallback_format(state)}

    resolution = state.get("pdk_resolution") or {}
    return {
        "final_response": FinalResponse(
            text=parsed["text"],
            data_tables=parsed.get("data_tables", []),
            charts=state.get("chart_specs") or [],
            applied_defaults=resolution.get("applied_defaults", {}),
            metadata={},
        ),
    }
