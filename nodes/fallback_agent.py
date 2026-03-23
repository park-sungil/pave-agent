"""fallback_agent — 비정형 질문 대응 ReAct 에이전트 (v7 main_agent 계승)."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, AIMessage

from nodes.resources import load_resource, load_domain_sections
from shared.llm import get_llm
from state import PaveAgentState

logger = logging.getLogger(__name__)

MAX_SQL_QUERIES = 5
MAX_RESULT_ROWS = 10000


def _select_domain_keywords(question: str) -> list[str]:
    """질문 키워드로 필요한 도메인 섹션 선택"""
    q = question.lower()
    keywords = ["파라미터 정의", "Trade-off"]

    if any(w in q for w in ["vth", "threshold", "ulvt", "slvt", "vlvt", "lvt", "mvt", "rvt", "hvt"]):
        keywords.append("Vth")
    if any(w in q for w in ["drive", "ds", "d1", "d2", "d3", "d4"]):
        keywords.append("Drive Strength")
    if any(w in q for w in ["온도", "temp", "temperature", "vdd", "전압", "민감도"]):
        keywords.append("조건별 상관관계")
    if any(w in q for w in ["worst", "최악"]):
        keywords.append("조건별 상관관계")
    if any(w in q for w in ["iddq", "불량", "결함", "이상"]):
        keywords.append("IDDQ")
    if any(w in q for w in ["nanosheet", "wns", "cell height", "ch138", "ch168"]):
        keywords.extend(["Nanosheet", "Cell Height"])
    if any(w in q for w in ["pdk", "버전", "golden", "비교"]):
        keywords.append("PDK")
    if any(w in q for w in ["avg", "평균"]):
        keywords.append("AVG")

    return keywords


def _build_system_prompt(question: str) -> str:
    """fallback_agent 시스템 프롬프트"""
    schema = load_resource("schema_catalog.md")
    sql_patterns = load_resource("sql_patterns.md")
    domain_keywords = _select_domain_keywords(question)
    domain = load_domain_sections(*domain_keywords)

    return f"""당신은 PDK의 cell-level PPA 측정 데이터를 조회·분석하는 에이전트입니다.

## 역할
- 사용자의 자연어 질문을 이해하고, DB에서 데이터를 조회하여 분석 결과를 제공합니다.
- 도메인 지식에 없는 내용을 추측하지 마세요.

## DB 스키마
{schema}

## SQL 패턴 참고
{sql_patterns}

## PPA 도메인 지식
{domain}

## 작업 방식
1. 질문 분석: 필요한 조건 파악
2. 조건이 모호하면: ask_user 도구로 되묻기
3. SQL 작성: Oracle SQL을 직접 작성하여 execute_sql로 실행
4. 데이터가 부족하면 추가 SQL 실행 (최대 {MAX_SQL_QUERIES}회)
5. 분석 완료 후 최종 결과를 아래 JSON 형식으로 출력

## SQL 작성 규칙
- SELECT 문만 (DML/DDL 금지)
- WHERE 조건절 필수
- FETCH FIRST N ROWS ONLY 필수 (최대 {MAX_RESULT_ROWS}행)
- antsdb. 스키마 접두사 사용
- AVG() 집계 함수 사용 금지. 개별 행 조회 후 stats_tool로 평균 계산

## 기본값 (미지정 시)
- PVT corner: TT, 25°C, nominal VDD
- PDK 버전: IS_GOLDEN=1
- CELL: AVG (INV, ND2, NR2)
- DS: AVG (D1, D4)
- 성능 지표: FREQ_GHZ

## 응답 규칙
- 존댓말(합쇼체)
- DB 컬럼명 그대로 사용 (한국어 번역/괄호 부연 금지)
- 이모지 금지
- 소극적 권장: "추천합니다" (X) → "검토해볼 만합니다" (O)
- 숫자 비교는 테이블 우선, raw data + 변화율 함께 표시

## 최종 출력 형식 (반드시 이 JSON으로 마무리)
ANALYSIS_COMPLETE:
{{
    "summary": "1~2문장 핵심 요약 (한국어)",
    "key_findings": ["핵심 발견 1", "핵심 발견 2"],
    "data_tables": [{{
        "title": "테이블 제목",
        "columns": ["컬럼1"],
        "data": [[값1]]
    }}],
    "suggested_chart": "bar|line|scatter|heatmap|null",
    "suggestions": ["추가 분석 제안"]
}}
"""


def _parse_analysis_result(text: str) -> dict:
    """에이전트 최종 메시지에서 구조화된 분석 결과 추출"""
    marker = "ANALYSIS_COMPLETE:"
    if marker in text:
        json_part = text.split(marker, 1)[1].strip()
    else:
        json_part = text.strip()

    if "```" in json_part:
        parts = json_part.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                json_part = part
                break

    try:
        return json.loads(json_part)
    except json.JSONDecodeError:
        return {
            "summary": text[:500],
            "key_findings": [],
            "raw_text": text,
        }


def fallback_agent(state: PaveAgentState) -> dict:
    """비정형 질문 대응 ReAct 에이전트 (v7 main_agent 계승)"""
    from langgraph.prebuilt import create_react_agent

    from nodes.tools import AGENT_TOOLS

    question = state["user_question"]
    system_prompt = _build_system_prompt(question)

    llm = get_llm("heavy")
    agent = create_react_agent(llm, tools=AGENT_TOOLS, prompt=system_prompt)

    # 이전 대화 컨텍스트 구성
    conversation_history = state.get("conversation_history") or []
    messages = []
    for turn in conversation_history:
        messages.append(HumanMessage(content=f"질문: {turn['question']}"))
        messages.append(AIMessage(content=turn.get("summary", "")))

    user_msg = f"질문: {question}"
    screen_ctx = state.get("screen_context")
    if screen_ctx:
        user_msg += f"\n\n화면 컨텍스트: {json.dumps(screen_ctx, ensure_ascii=False)}"
    messages.append(HumanMessage(content=user_msg))

    try:
        result = agent.invoke({"messages": messages})
        final_msg = result["messages"][-1].content
        analysis_result = _parse_analysis_result(final_msg)

        return {
            "fallback_result": {
                "text": analysis_result.get("summary", final_msg[:500]),
                "tables": analysis_result.get("data_tables", []),
                "key_findings": analysis_result.get("key_findings", []),
                "suggested_chart": analysis_result.get("suggested_chart"),
                "suggestions": analysis_result.get("suggestions", []),
            },
        }

    except BaseException as e:
        if "Interrupt" in type(e).__name__ or "interrupt" in type(e).__name__.lower():
            raise
        if "429" in str(e) or "rate_limit" in str(e).lower():
            raise
        logger.error("fallback_agent 에러: %s", e)
        return {
            "fallback_result": {
                "text": f"분석 중 오류가 발생했습니다: {e}",
                "tables": [],
            },
        }
