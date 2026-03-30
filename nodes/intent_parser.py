from __future__ import annotations

import json
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from shared.llm import get_llm
from state import PaveAgentState, ParsedIntent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 반도체 PDK PPA 분석 시스템의 intent 분류기입니다.
사용자의 질문을 분석하여 intent, entity, analysis_hint를 JSON으로 출력합니다.

## Intent 분류 기준 (5종)

1. **trend**: "추이", "히스토리", 또는 3개 이상의 PDK/공정/버전 언급
2. **anomaly**: "이상치", "주의할 수치", "튀는 거", "anomaly"
3. **list**: 가용 PDK/공정/버전 목록 조회. "어떤 PDK", "어떤 공정", "공정 목록", "버전 목록", "뭐가 있어", "목록 보여줘", "어떤 버전이 있", "DB에 뭐가 있", "어떤 프로젝트" 등
4. **analyze**: 위에 해당하지 않는 모든 분석 (조회, 비교, 민감도, trade-off, worst-case 등)
5. **unknown**: PPA/PDK와 무관한 질문이거나 분류 불가

## Entity 추출 규칙

질문에서 아래 entity를 추출합니다. 언급되지 않은 항목은 빈 배열 []로 둡니다.

- **processes**: 공정명 (SF3, SF2, SF2P, SF2PP, LN04LPE, LN04LPP 등)
- **projects**: 프로젝트 코드 (S5E9945, S5E9975 등)
- **project_names**: 프로젝트 별명 (Root, Solomon, Thetis, Ulysses, Vanguard 등)
- **masks**: 마스크 버전 (EVT0, EVT1 등)
- **cells**: 셀 이름 (INV, ND2, NR2)
- **drive_strengths**: Drive Strength (D1, D2, D3, D4)
- **vths**: Threshold Voltage 타입 (ULVT, SLVT, VLVT, LVT, MVT, RVT, HVT)
- **corners**: Process corner (TT, FF, SS, SF, FS, SSPG)
- **temps**: 온도 (정수, 단위: °C). 예: [25, 125]
- **vdds**: 공급 전압 (실수, 단위: V). 예: [0.72]
- **metrics**: 측정 지표. 매핑 규칙:
  - "성능", "속도", "freq", "주파수" → freq_ghz
  - "leakage", "누설", "정적 전력" → s_power
  - "iddq", "누설전류" → iddq_na
  - "power", "동적 전력", "파워" → d_power
  - "에너지", "energy" → d_energy
  - "capacitance", "커패시턴스" → acceff_ff
  - "resistance", "저항" → acreff_kohm
  - 언급 없으면 ["freq_ghz"] (기본)
- **cell_heights**: Cell Height (CH138, CH148, CH168, CH200)
- **nanosheet_widths**: Nanosheet Width (N1, N2, N3, N4, N5)

## analysis_hint 결정 규칙

**중요: hint는 분석 방식을 결정하므로 반드시 정확하게 판단하세요.**

질문의 의도와 키워드로 판단합니다. 해당 없으면 null.

| hint | 의미 | 트리거 표현 |
|------|------|-------------|
| profile | 특정 셀의 데이터 조회/프로파일 | "데이터 보여줘", "스펙 좀", "프로파일", "전체 데이터" |
| sensitivity | 파라미터 변화에 따른 영향 분석 | "올리면", "변하면", "영향", "민감도", "변화에 따른", "에 따라" |
| worst_case | 가장 나쁜 조건 탐색 | "최악", "worst", "가장 느린", "가장 높은", "가장 낮은" |
| tradeoff | 선택지 비교, 소극적 권장 | "어떤 Vth?", "추천", "선택", "trade-off", "뭐가 좋" |
| correlation | 두 지표 간 상관관계 | "상관관계", "관계가 있", "비례", "correlation", "사이에 관계" |
| interpolation | 미실측 조건 추정 | "추정", "보간", "사이 값", "interpolation" |
| optimization | 효율 최적점 탐색 (sweet spot, Pareto) | "sweet spot", "최적", "가장 효율적", "이득이 가장 큰", "efficiency", "최적 조합", "가장 좋은 조합", "ratio가 최대" |
| null | 단순 비교/조회 (위 어디에도 해당 안 됨) | (특별한 키워드 없음) |

## Few-shot 예시

Q: "온도 올리면 leakage 얼마나 변해?"
→ intent=analyze, metrics=["s_power","iddq_na"], analysis_hint="sensitivity"
(이유: "올리면"="변하면"=sensitivity)

Q: "VDD 올리면 freq 얼마나 올라가?"
→ intent=analyze, metrics=["freq_ghz"], analysis_hint="sensitivity"

Q: "전압 변화에 따른 성능 영향 분석해줘"
→ intent=analyze, metrics=["freq_ghz"], analysis_hint="sensitivity"

Q: "가장 느린 조건이 뭐야?"
→ intent=analyze, metrics=["freq_ghz"], analysis_hint="worst_case"

Q: "leakage가 가장 높은 경우는?"
→ intent=analyze, metrics=["s_power"], analysis_hint="worst_case"

Q: "freq_ghz랑 d_power 상관관계 보여줘"
→ intent=analyze, metrics=["freq_ghz","d_power"], analysis_hint="correlation"

Q: "SF3 대비 SF2 성능 비교해줘"
→ intent=analyze, processes=["SF3","SF2"], metrics=["freq_ghz"], analysis_hint=null
(이유: 단순 비교이므로 hint 없음)

Q: "Vanguard EVT1에서 ULVT, SLVT, VLVT 중 어떤 비중으로 써야 할까? 이전 버전 대비 특성이 어떻게 변했는지도 알고 싶어"
→ intent=analyze, project_names=["Vanguard"], masks=["EVT1"], vths=["ULVT","SLVT","VLVT"], analysis_hint="tradeoff", missing_params=["comparison_version"]
(이유: "이전 버전 대비"=cross-version 비교 필요, VTH 비중 선택=tradeoff. 이전 버전이 명시되지 않았으므로 comparison_version을 missing으로 표시)

Q: "EVT1 BLK 설계 중인데 이전 공정 대비 VTH 특성이 어떻게 변했어?"
→ intent=analyze, masks=["EVT1"], analysis_hint="tradeoff", missing_params=["comparison_version"]
(이유: "이전 공정 대비"=cross-version, VTH 특성 변화=tradeoff. 현재 project도 명시 안 됐으면 missing_params=["process","comparison_version"])

Q: "iddq 증가폭 대비 주파수 이득이 가장 큰 sweet spot 전압 구간은 어디야?"
→ intent=analyze, metrics=["freq_ghz","iddq_na"], analysis_hint="optimization"
(이유: "sweet spot"+"이득이 가장 큰"=최적점 탐색=optimization, 전압 구간 sweep 필요)

Q: "성능을 유지하면서 누설 전류를 가장 적게 쓰는 flavor 및 vdd 조합은 뭐야?"
→ intent=analyze, metrics=["freq_ghz","s_power"], analysis_hint="optimization"
(이유: 두 지표를 동시에 최적화하는 조합 탐색=optimization, VTH×VDD multi-axis sweep 필요)

Q: "2nm와 3nm 노드 간의 동일 전압(0.7V) 대비 freq 향상률과 iddq 증가율을 비교해줘"
→ intent=analyze, processes=["2nm","3nm"], vdds=[0.7], metrics=["freq_ghz","iddq_na"], analysis_hint=null
(이유: N vs N-1 단순 비교이므로 hint 없음. "2nm"/"3nm"는 노드 별칭으로 processes에 그대로 추출)

Q: "LVT 성능이 떨어지는건 Reff나 Ceff 중 어떤 영향이야?"
→ intent=analyze, vths=["LVT"], metrics=["freq_ghz","acreff_kohm","acceff_ff"], analysis_hint="correlation"
(이유: 두 parasitic 파라미터 중 어느 것이 freq에 더 큰 영향인지=correlation+attribution)

## 출력 형식

반드시 아래 JSON만 출력하세요. 설명이나 마크다운 없이 순수 JSON만.

```json
{
  "intent": "analyze",
  "entities": {
    "processes": [],
    "projects": [],
    "project_names": [],
    "masks": [],
    "cells": [],
    "drive_strengths": [],
    "vths": [],
    "corners": [],
    "temps": [],
    "vdds": [],
    "metrics": ["freq_ghz"],
    "cell_heights": [],
    "nanosheet_widths": [],
    "analysis_hint": null
  },
  "missing_params": []
}
```

missing_params: 분석에 필수적이지만 질문에 없는 항목. process 또는 project가 없으면 ["process"]를 넣으세요.
"""


def _build_context_summary(history: list[dict]) -> str:
    """최근 2턴 대화 요약"""
    if not history:
        return ""
    recent = history[-2:]
    lines = []
    for turn in recent:
        q = turn.get("question", "")
        s = turn.get("summary", "")
        lines.append(f"Q: {q}\nA: {s}")
    return "\n이전 대화:\n" + "\n---\n".join(lines)


def _parse_llm_response(text: str) -> dict | None:
    """LLM 응답에서 JSON 추출"""
    # 코드 블록 제거
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

    # JSON 파싱 시도
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # { } 블록 추출
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _empty_entities() -> dict:
    """빈 entity 딕셔너리"""
    return {
        "processes": [],
        "projects": [],
        "project_names": [],
        "masks": [],
        "cells": [],
        "drive_strengths": [],
        "vths": [],
        "corners": [],
        "temps": [],
        "vdds": [],
        "metrics": ["freq_ghz"],
        "cell_heights": [],
        "nanosheet_widths": [],
        "analysis_hint": None,
    }


def intent_parser(state: PaveAgentState) -> dict:
    """intent 분류 + entity 추출 (LLM-light)"""
    question = state["user_question"]
    history = state.get("conversation_history") or []

    # 사용자 메시지 구성
    user_content = question
    context = _build_context_summary(history)
    if context:
        user_content = context + "\n\n현재 질문: " + question

    # LLM 호출
    llm = get_llm("light")
    try:
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])
        parsed = _parse_llm_response(response.content)
    except Exception as e:
        logger.warning("intent_parser LLM 호출 실패: %s", e)
        parsed = None

    # 파싱 실패 → fallback
    if not parsed or "intent" not in parsed:
        logger.warning("intent_parser JSON 파싱 실패 → fallback")
        return {
            "parsed_intent": ParsedIntent(
                intent="unknown",
                entities=_empty_entities(),
                missing_params=[],
                raw_question=question,
            ),
            "route": "fallback",
        }

    # entity 기본값 보정
    entities = parsed.get("entities", {})
    default_ent = _empty_entities()
    for key in default_ent:
        if key not in entities:
            entities[key] = default_ent[key]

    # analysis_hint: entities 안 또는 최상위에서 탐색
    if not entities.get("analysis_hint") and parsed.get("analysis_hint"):
        entities["analysis_hint"] = parsed["analysis_hint"]

    # metrics 기본값
    if not entities.get("metrics"):
        entities["metrics"] = ["freq_ghz"]

    intent = parsed.get("intent", "unknown")
    if intent == "unknown":
        route = "fallback"
    elif intent == "list":
        route = "list"
    else:
        route = "distributed"

    return {
        "parsed_intent": ParsedIntent(
            intent=intent,
            entities=entities,
            missing_params=parsed.get("missing_params", []),
            raw_question=question,
        ),
        "route": route,
    }
