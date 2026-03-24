# pave-agent 프로젝트 명세서

> **pave-agent** — Process Assessment & Verification for Evaluation
>
> Oracle 운영 DB에 저장된 PDK의 셀 레벨 PPA 성능 데이터를 자연어로 분석하고,
> 인터랙티브 시각화와 함께 인사이트를 제공하는 사내 AI 에이전트.
> pave 웹 서비스의 백엔드 분석 엔진으로 동작하며, API를 통해 호출된다.
>
> v8 — 2026-03-16

---

## 1. 프로젝트 개요

### 1.1 배경 및 목적

PAVE는 PDK의 셀 레벨 PPA(Power, Performance, Area) 성능 측정 결과를 표준화하여 관리하는 시스템이다. 성능 데이터가 Oracle DB에 저장되어 있지만, 이를 분석하려면 SQL 작성 능력과 PPA 도메인 지식이 모두 필요하다.

pave-agent는 자연어 질문만으로 PPA 데이터를 조회·비교·시각화할 수 있게 하여, 설계/검증 엔지니어의 데이터 접근성을 높이고 분석 효율을 개선하는 것을 목표로 한다.

**v8 핵심 목표: 업무 경험이 많고 적음에 관계없이, 일정 수준 이상의 분석 insight를 얻어갈 수 있도록 한다.**

### 1.2 서비스 정의

| 항목 | 내용 |
|------|------|
| 서비스명 | pave-agent |
| 정식 명칭 | Process Assessment & Verification for Evaluation |
| 역할 | pave 웹 서비스의 백엔드 분석 에이전트 (API 서버) |
| 사용자 | 설계/검증 엔지니어 (pave 웹을 통해 간접 사용) |
| 분석 대상 | Oracle 운영 DB — PDK 버전 정보 + 셀 레벨 PPA 성능 데이터 |
| 핵심 기능 | 자연어 질의, 특성 변화 해석, 이상치 감지, 판단 보조, 시각화 |
| 시각화 전달 | JSON 차트 스펙 → pave 웹에서 Plotly.js 렌더링 |
| DB 접근 권한 | READ-ONLY |
| DB 사용자 | antsdb |
| 응답 언어 | 한국어 (존댓말) |
| LLM | 사내 모델 (OpenAI 호환 API) — heavy/light 2-tier |
| 프레임워크 | LangGraph |
| DB 드라이버 | python-oracledb (Thick 모드) |

### 1.3 기능 요구사항

| # | 기능 | 설명 | 응답 모드 |
|---|------|------|-----------|
| F1 | 자연어 질의 | PDK 데이터 조회, 비교, 필터링 | 동기 (채팅, 10~30초) |
| F2 | 특성 변화 해석 | 3~5개 PDK 버전 간 추이 분석. LLM을 활용한 다수 PDK 추이 분석 | 동기 (채팅, 20~60초) |
| F3 | 이상치 감지 | 두 PDK 간 전체 데이터 sweep → 설계 주의 수치 식별 + 추정 원인 | 동기 (채팅, SSE 진행표시, 2~5분) |
| F4 | 판단 보조 | VTH 선택 등 trade-off 분석. 실측 데이터 우선 + 도메인 지식 보조의 소극적 권장 | 동기 (채팅, 10~30초) |
| F5 | 시각화 | 분석 결과의 시각적 근거로 차트 제시. 모든 분석 응답에 포함 | 동기 (분석 응답에 포함) |

### 1.4 이상치 감지 정의 (v8 신규)

**목적**: 모델링이 정상이라는 전제 하에, 설계자가 주의해야 할 수치를 선제적으로 알려준다.

**탐지 대상**:
- 파라미터 공간 내 비선형적 급변 구간
- 예상 추세에서 벗어나는 데이터 포인트
- 설계 시 마진 확보가 필요한 영역

**결과 구성**: 이상치 목록 + 파라미터 간 상관관계 기반 추정 원인

**주의**: 이것은 제조 결함/모델링 오류 탐지가 아니다. 정상 데이터 내에서 설계자의 의사결정에 영향을 줄 수 있는 수치를 식별하는 것이다.

### 1.5 아키텍처 설계 철학

v7은 "결정론적 워크플로우 + 내부 ReAct 에이전트" 하이브리드였다. v8은 이를 **"분산 노드 파이프라인 + Fallback ReAct"**로 전환한다.

**전환 이유**:

1. **토큰 효율**: ReAct는 매 iteration마다 누적 컨텍스트를 LLM에 전송. 5회 tool call 시 총 ~94K 토큰 소비, 실제 필요량 ~17K. 토큰 효율 18%.
2. **사내 모델 적합성**: prod에서 사내 모델만 사용. tool calling 안정성 리스크가 있으며, ReAct의 자율적 도구 선택에 의존하면 품질 저하 가능성.
3. **응답 시간**: 사내 모델의 TTFT가 컨텍스트 길이에 비례. 누적 컨텍스트 → 응답 시간 급증.
4. **예측 가능성**: 분산 노드는 각 단계의 입출력이 명확하여 디버깅과 성능 최적화 용이.

**v8 원칙**:
1. 각 노드는 자기 역할에 필요한 최소 컨텍스트만 받는다
2. LLM이 필요 없는 단계는 코드로 처리한다 (결정론적)
3. 무거운 모델은 "해석"이 필요한 곳에만 쓴다
4. 비정형 질문은 Fallback ReAct로 안전하게 처리한다

### 1.6 데이터 규모

| 항목 | 수치 |
|------|------|
| 1 PDK당 PPA 행 수 | ~13,000행 |
| 추이 분석 대상 PDK 수 | ~10개 (최대 130K행) |
| 이상치 sweep 대상 | 2 PDK × 13K행 = ~26K행 |

### 1.7 시스템 구성도

```
┌────────────────────────────────────────────────────┐
│                   pave 웹 서비스                      │
│  ┌──────────┐     ┌────────────────────────────┐   │
│  │ 프론트엔드 │     │ Plotly.js 렌더링             │   │
│  │ (챗봇 UI) │     │ (JSON 차트 스펙으로 생성)     │   │
│  └─────┬────┘     └────────────────────────────┘   │
└────────┼───────────────────────────────────────────┘
         │ REST (요청) + SSE (응답 스트리밍)
┌────────▼───────────────────────────────────────────┐
│                  pave-agent (API 서버)                │
│  ┌───────────────────────────────────────────────┐ │
│  │          LangGraph — 분산 노드 파이프라인        │ │
│  │                                               │ │
│  │  intent_parser (LLM-light)                    │ │
│  │       │                                       │ │
│  │       ├─→ [분산] pdk_resolver → query_builder  │ │
│  │       │         → data_executor → analyzer     │ │
│  │       │         → interpreter (LLM-heavy)      │ │
│  │       │         → visualizer                   │ │
│  │       │         → response_formatter (LLM-light)│ │
│  │       │                                       │ │
│  │       └─→ [fallback] fallback_agent (ReAct)    │ │
│  │                   → visualizer                 │ │
│  │                   → response_formatter          │ │
│  └──────────────────────┬────────────────────────┘ │
│  ┌──────────┐  ┌────────┴─────────┐  ┌──────────┐ │
│  │ nodes/   │  │    shared/       │  │  api/    │ │
│  │resources/│  │ (DB, LLM)       │  │(REST+SSE)│ │
│  └──────────┘  └──────────────────┘  └──────────┘ │
└─────────────────────────┬──────────────────────────┘
                          │ python-oracledb (READ-ONLY)
              ┌───────────▼───────────┐
              │    Oracle 운영 DB      │
              └───────────────────────┘
```

---

## 2. 설계 결정 로그 (Design Decision Log)

### DDL-01~07: v7에서 유지
- DDL-01: 프레임워크 — LangGraph
- DDL-02: LLM — 사내 모델 (OpenAI 호환 API), heavy/light 2-tier
- DDL-03: 스트리밍 — REST + SSE 하이브리드
- DDL-04: 되묻기 — pdk_resolver의 ask_user에서 interrupt() (v7: main_agent → v8: pdk_resolver로 이동)
- DDL-05: 데이터 소스 — View 2개만 노출
- DDL-06: 시각화 — 선택적 실행 (v8: 모든 분석 응답에 포함 권장)
- DDL-07: DB 접속 — Oracle Thick 모드 + TNS DSN

### DDL-08: v7 3-node → v8 분산 노드 전환
- **변경 전 (v7)**: router → main_agent(ReAct) → format_response. LLM 2~3호출, 11~80초.
- **변경 후 (v8)**: intent_parser → pdk_resolver → query_builder → data_executor → analyzer → interpreter → visualizer → response_formatter. LLM 3회 (light 2 + heavy 1), 15~25초 (일반 질의).
- **이유**: 토큰 효율 18% → 90%+, 사내 모델 tool calling 리스크 제거, 응답 시간 단축, 노드별 디버깅 가능.
- **안전장치**: Fallback ReAct를 유지하여 비정형 질문 대응.

### DDL-09: LLM 3-point 호출 구조
| 호출 지점 | 티어 | 역할 | 컨텍스트 |
|-----------|------|------|----------|
| intent_parser | light | intent 분류 (5종) + entity 추출 + analysis_hint 판단 | ~1.5K |
| interpreter | heavy | 분석 결과 해석 + 도메인 지식 적용 + 소극적 권장 | ~8K |
| response_formatter | light | 한국어 정제 (중국어 혼입 방지) + 응답 포맷팅 | ~4K |

### DDL-10: 도메인 지식 선택적 로딩 (v7 유지, 방식 개선)
- pave_domain.md (23K+)를 매번 전부 로딩하면 토큰 낭비
- v8: intent별로 관련 섹션만 선택하는 매핑 테이블 사용
- 향후 문서 확장 시 임베딩 RAG 도입 검토 (임베딩/리랭커 모델 이미 확보)

### DDL-11: 이상치 감지를 분산 파이프라인에 통합
- 별도 파이프라인이 아닌, 같은 노드 구조에서 intent="anomaly"로 모드 전환
- analyzer가 anomaly 모드로 동작, interpreter가 클러스터별 원인 추정
- SSE로 단계별 진행상황 스트리밍

### DDL-13: Intent 간소화 — 3+1 체제
- **변경 전**: 14개 intent (ppa_lookup, pdk_compare, cross_process_compare, vth_compare, ...)
- **변경 후**: 4개 intent (analyze, trend, anomaly, unknown) + entity + analysis_hint
- **이유**: intent 간 포함관계 문제 해소 (lookup과 compare의 경계 모호), LLM 분류 정확도 향상 (4지선다), 노드 코드 중복 제거
- `analyze`가 1~2 PDK의 모든 일반 분석을 커버. PDK 수는 entity에서 pdk_resolver가 자동 판단
- `trend`(3+ PDK)와 `anomaly`(bulk sweep)만 데이터 흐름이 근본적으로 달라서 분리

### DDL-12: 판단 보조 수준 — 소극적 권장
- "RVT를 추천합니다" (X)
- "RVT 선택 시 leakage가 X% 감소하지만 freq가 Y% 하락합니다. 실측 기준으로 leakage 절감 효과가 크므로 검토해볼 만합니다" (O)
- 실측 데이터를 근거로, 도메인 지식은 보조 설명으로 활용

---

## 3. LLM 모델 구성

### 3.1 prod 환경 (사내 모델만)

| 티어 | 용도 | 후보 모델 | 선정 기준 |
|------|------|-----------|-----------|
| **heavy** | interpreter | GLM-5-FP8 (예정), Kimi-K2.5, GLM4.7 | 긴 컨텍스트, 강한 reasoning, 한국어 품질 |
| **light** | intent_parser, response_formatter | MiniMax-M2.1, GLM4.7 | 빠른 응답, 구조화 JSON 출력, 한국어 정제 |

### 3.2 dev 환경

| 티어 | 모델 |
|------|------|
| heavy | Claude Sonnet |
| light | Claude Haiku |

### 3.3 임베딩 / 리랭커 (향후 RAG용)

| 용도 | 후보 모델 |
|------|-----------|
| 임베딩 | BAAI-bge-m3, Qwen3-Embedding-8B |
| 리랭커 | Qwen3-Reranker-8B, BAAI-bge-reranker-v2-m3 |

### 3.4 모델 선정 시 검증 필요 사항
1. 구조화 JSON 출력 안정성 (intent_parser)
2. 한국어 reasoning 품질 (interpreter)
3. 중국어 혼입 없는 한국어 생성 (response_formatter)
4. 컨텍스트 윈도우 크기 (interpreter: ~8K 필요)

---

## 4. 그래프 설계

### 4.1 노드 목록 (8+1개)

| 노드 | LLM | 티어 | 역할 |
|------|-----|------|------|
| intent_parser | O | light | intent 분류 + entity 추출 + 누락 판단 |
| pdk_resolver | X | - | PDK 버전 특정 (코드, ask_user interrupt) |
| query_builder | X | - | SQL 템플릿 선택 + 파라미터 바인딩 |
| data_executor | X | - | SQL 실행 + 결과 수집 |
| analyzer | X | - | 통계 분석 (compare, trend, anomaly, ...) |
| interpreter | O | heavy | 분석 결과 해석 + 도메인 지식 적용 |
| visualizer | X | - | Plotly JSON 차트 스펙 생성 |
| response_formatter | O | light | 한국어 정제 + 응답 포맷팅 |
| fallback_agent | O | heavy (ReAct) | 비정형 질문 대응 (v7 main_agent 계승) |

### 4.2 그래프 플로우

```
START → intent_parser ─┬─ route: distributed ─→ pdk_resolver → query_builder → data_executor → analyzer → interpreter → visualizer → response_formatter → END
                       │
                       └─ route: fallback ────→ fallback_agent → visualizer → response_formatter → END
```

- `pdk_resolver`에서 ask_user interrupt 발생 가능
- `visualizer`, `response_formatter`는 양쪽 경로에서 공유
- `intent_parser`가 `unknown` 반환 시 fallback 경로

### 4.3 Intent 정의 (3 + 1)

Intent는 **"데이터 흐름의 규모와 형태"만 결정**한다. "무엇을/어떤 관점으로 분석할지"는 entity가 결정한다. PDK를 몇 개 다루느냐는 intent가 아니라 entity의 내용에서 pdk_resolver가 자동 판단한다.

| Intent | 설명 | PDK 수 | 예시 질문 |
|--------|------|--------|-----------|
| `analyze` | 일반 분석. 조회, 비교, 민감도, trade-off, worst-case, 상관분석, 보간 모두 포함 | entity에 따라 1~2개 (pdk_resolver가 자동 판단) | "INV D1 LVT 데이터 보여줘", "SF3 대비 SF2 성능 비교", "LVT랑 RVT 차이?", "온도 올리면 leakage?", "low power에 어떤 Vth?" |
| `trend` | 3개 이상 PDK/버전의 추이 분석 | 3~5개 | "최근 3개 버전 성능 추이", "SF2→SF2P→SF3 변화 추이" |
| `anomaly` | 두 PDK 간 전체 데이터 sweep 이상치 탐지 | 2개 (bulk) | "이상치 찾아줘", "주의할 수치 있어?" |
| `unknown` | 분류 불가 → fallback ReAct | - | (비정형 복합 질문) |

**설계 원칙**:
- `analyze`가 가장 넓은 범위를 커버한다. 단일 PDK 조회도, 2 PDK 비교도, Vth/DS/CH/NS 비교도, 민감도도, worst-case도, trade-off도 전부 `analyze`다.
- `analyze` 안에서 PDK 1개 vs 2개의 차이는 **entity에 process/project가 몇 개 있느냐**로 pdk_resolver가 자동 결정한다. intent 단계에서 구분하지 않는다.
- `trend`를 분리하는 이유: 3~5개 PDK(최대 65K행)는 데이터 규모와 요약 전략이 근본적으로 다르다.
- `anomaly`를 분리하는 이유: 전체 sweep(26K행)은 bulk SQL + SSE 진행표시가 필요하여 데이터 흐름이 다르다.

**intent 분류 기준** (intent_parser LLM에게 주는 규칙):
1. "추이", "히스토리", 또는 **3개 이상의 PDK/공정/버전** 언급 → `trend`
2. "이상치", "주의할 수치", "튀는 거" → `anomaly`
3. 위에 해당하지 않는 모든 분석 → `analyze`
4. 분류 불가 → `unknown`

### 4.4 Entity 구조

intent_parser가 질문에서 추출하는 entity. 이후 모든 노드가 이 entity를 참조하여 동작을 결정한다.

```json
{
  "processes": ["SF3", "SF2"],
  "projects": [],
  "project_names": ["Thetis"],
  "masks": [],
  "cells": ["INV"],
  "drive_strengths": ["D1", "D4"],
  "vths": ["LVT", "RVT"],
  "corners": ["TT"],
  "temps": [25, 125],
  "vdds": [0.72],
  "metrics": ["freq_ghz", "s_power"],
  "cell_heights": ["CH138", "CH168"],
  "nanosheet_widths": [],
  "analysis_hint": "sensitivity"
}
```

**analysis_hint**: analyzer가 데이터를 어떻게 분석할지의 힌트. intent_parser가 질문의 의도를 해석하여 설정한다. analyzer는 이 힌트를 참고하되, entity의 실제 내용에 따라 최종 분석 방식을 결정한다.

| analysis_hint | 의미 | 트리거 표현 |
|---------------|------|-------------|
| `profile` | 특정 셀의 전체 PPA 프로파일 | "데이터 보여줘", "수치" |
| `sensitivity` | 특정 파라미터의 민감도 분석 | "올리면", "변하면", "영향" |
| `worst_case` | worst-case 조건 탐색 | "최악", "worst", "가장 느린" |
| `tradeoff` | trade-off 분석 + 소극적 권장 | "어떤 Vth?", "추천", "선택" |
| `correlation` | 파라미터 간 상관분석 | "상관관계", "비례", "관계" |
| `interpolation` | 미실측 조건 보간 | "추정", "보간", "사이 값" |
| `null` | 일반 비교/조회 (기본) | (특별한 키워드 없음) |

### 4.5 Entity가 노드 동작을 결정하는 방식

**query_builder — entity로 WHERE 절 동적 조립**:

| entity 조건 | SQL WHERE 절 효과 |
|-------------|-------------------|
| `vths: ["LVT", "RVT"]` | `AND d.VTH IN ('LVT', 'RVT')` |
| `drive_strengths: ["D1", "D4"]` | `AND d.DS IN ('D1', 'D4')` |
| `temps: [25, 125]` | `AND d.TEMP IN (25, 125)` |
| `cell_heights: ["CH138", "CH168"]` | `AND d.CH IN ('CH138', 'CH168')` |
| `cells` 비어있음 (AVG) | `AND d.CELL IN ('INV', 'ND2', 'NR2')` |
| `drive_strengths` 비어있음 (AVG) | `AND d.DS IN ('D1', 'D4')` |

**analyzer — entity + analysis_hint로 분석 방식 결정**:

```python
def analyze(intent, entity, resolution, datasets):
    if intent == "analyze":
        hint = entity.get("analysis_hint")
        pdk_count = len(resolution["target_pdks"])

        if hint == "sensitivity":
            return calc_sensitivity(datasets, vary_axis=infer_axis(entity))
        elif hint == "worst_case":
            return find_worst_case(datasets, metric=entity["metrics"])
        elif hint == "tradeoff":
            return calc_tradeoff(datasets, axis=infer_compare_axis(entity))
        elif hint == "correlation":
            return calc_correlation(datasets, x=..., y=...)
        elif hint == "interpolation":
            return interpolate(datasets, target=...)
        elif pdk_count == 2:
            return calc_delta(datasets, axis="pdk")
        else:
            compare_axis = infer_compare_axis(entity)
            if compare_axis:
                return calc_delta(datasets, axis=compare_axis)
            else:
                return summarize(datasets)
    elif intent == "trend":
        return calc_trend(datasets, metric=entity["metrics"])
    elif intent == "anomaly":
        return detect_anomalies(datasets)
```

**interpreter — entity로 도메인 지식 선택**:

| entity 내용 | 로딩 섹션 |
|-------------|-----------|
| `vths`에 2종 이상 | 5.4 Vth |
| `drive_strengths`에 2종 이상 | 5.1 Drive Strength |
| `temps`에 2종 이상 또는 hint=sensitivity | 6.1 Temperature × PPA |
| `vdds`에 2종 이상 또는 hint=sensitivity | 6.2 VDD × PPA |
| `cell_heights`에 2종 이상 | 5.3 Cell Height |
| `nanosheet_widths`에 2종 이상 | 5.2 Nanosheet Width |
| pdk_count == 2 또는 intent=trend | 3. PPA 기본 Trade-off |
| intent=anomaly | 6.1 + 6.2 + 5.4 |
| hint=worst_case | 규칙 2: Worst-case 매핑 |
| hint=tradeoff | 3. PPA 기본 Trade-off |

---

## 5. 상태 스키마

```python
from __future__ import annotations
from typing import TypedDict, Optional, Any, Literal

IntentType = Literal["analyze", "trend", "anomaly", "unknown"]

AnalysisHint = Literal[
    "profile", "sensitivity", "worst_case", "tradeoff",
    "correlation", "interpolation", None
]


class ParsedIntent(TypedDict):
    """intent_parser 출력"""
    intent: IntentType
    entities: dict[str, Any]
    # {
    #   "processes": ["SF3", "SF2"],
    #   "projects": [], "project_names": ["Thetis"],
    #   "masks": [], "cells": ["INV"],
    #   "drive_strengths": ["D1", "D4"],
    #   "vths": ["LVT", "RVT"],
    #   "corners": ["TT"], "temps": [25], "vdds": [],
    #   "metrics": ["freq_ghz", "s_power"],
    #   "cell_heights": [], "nanosheet_widths": [],
    #   "analysis_hint": "sensitivity" | "worst_case" | ... | null,
    # }
    missing_params: list[str]
    raw_question: str


class ResolvedPDK(TypedDict):
    """단일 PDK 해석 결과"""
    pdk_id: int
    process: str
    project: str
    project_name: str
    mask: str
    dk_gds: str
    is_golden: int
    hspice: str
    lvs: str
    pex: str
    vdd_nominal: float


class PDKResolution(TypedDict):
    """pdk_resolver 출력"""
    target_pdks: list[ResolvedPDK]
    comparison_mode: Literal["single", "pair", "multi"]
    resolved_params: dict[str, Any]
    applied_defaults: dict[str, str]


class QueryPlan(TypedDict):
    """query_builder 출력"""
    queries: list[dict[str, Any]]
    # [{"sql": "SELECT ...", "purpose": "SF3 PPA", "pdk_id": 900}]
    is_bulk: bool


class QueryResult(TypedDict):
    """data_executor 출력"""
    datasets: list[dict[str, Any]]
    # [{"pdk_id": 900, "purpose": "...", "rows": [...], "row_count": 250}]
    total_rows: int
    warnings: list[str]


class AnalysisResult(TypedDict):
    """analyzer 출력"""
    mode: str
    summary_table: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    chart_data: dict[str, Any]
    raw_for_avg: Optional[dict[str, Any]]


class Interpretation(TypedDict):
    """interpreter 출력"""
    narrative: str
    key_insights: list[str]
    recommendations: list[str]
    suggested_charts: list[dict[str, Any]]
    additional_analysis: list[str]


class ChartSpec(TypedDict):
    """visualizer 출력"""
    chart_type: str
    title: str
    plotly_spec: dict


class FinalResponse(TypedDict):
    """response_formatter 출력 (API 응답)"""
    text: str
    data_tables: list[dict[str, Any]]
    charts: list[ChartSpec]
    applied_defaults: dict[str, str]
    metadata: dict[str, Any]


class PaveAgentState(TypedDict):
    """LangGraph 전체 상태"""

    # 입력
    user_question: str
    conversation_id: str
    conversation_history: list[dict[str, Any]]
    screen_context: Optional[dict[str, Any]]

    # 노드 출력
    parsed_intent: Optional[ParsedIntent]
    pdk_resolution: Optional[PDKResolution]
    query_plan: Optional[QueryPlan]
    query_result: Optional[QueryResult]
    analysis_result: Optional[AnalysisResult]
    interpretation: Optional[Interpretation]
    chart_specs: Optional[list[ChartSpec]]
    final_response: Optional[FinalResponse]

    # fallback
    fallback_result: Optional[dict[str, Any]]

    # 공통
    route: Literal["distributed", "fallback"]
    error: Optional[str]

    # anomaly SSE 진행상황
    anomaly_progress: Optional[dict[str, Any]]
```

---

## 6. 노드 상세 설계

### 6.1 intent_parser

| 항목 | 내용 |
|------|------|
| 읽기 | user_question, conversation_history, screen_context |
| 쓰기 | parsed_intent, route |
| LLM | light-tier, 1회 |
| 컨텍스트 | ~1.5K: 시스템프롬프트(intent 4종 + entity 추출 규칙 + analysis_hint 규칙) + 질문 + 대화 요약 |
| 실패 처리 | JSON 파싱 실패 또는 intent=unknown → route="fallback" |

**시스템 프롬프트 핵심 요소**:
- Intent 4종 정의: analyze(1~2 PDK 일반 분석), trend(3+ PDK 추이), anomaly(이상치 sweep), unknown(fallback)
- Entity 추출 규칙: process, project, project_name, cell, ds, vth, corner, temp, vdd, metric, cell_height, nanosheet_width
- analysis_hint 결정 규칙: 질문의 키워드로 판단 (sensitivity, worst_case, tradeoff, correlation, interpolation, profile, null)
- 기본 매핑: "성능"→freq_ghz, "leakage"→s_power/iddq_na, "power"→d_power
- 출력 형식: 구조화 JSON

**intent 분류 기준** (LLM에게 주는 규칙):
1. "추이/히스토리" 또는 **3개 이상의 PDK/공정/버전** 언급 → `trend`
2. "이상치", "주의할 수치", "튀는 거" → `anomaly`
3. 위에 해당하지 않는 모든 분석 → `analyze`
4. 분류 불가 → `unknown`

### 6.2 pdk_resolver

| 항목 | 내용 |
|------|------|
| 읽기 | parsed_intent |
| 쓰기 | pdk_resolution |
| LLM | 없음 (코드 기반) |
| SQL 호출 | 1~3회 (버전 조회용, 템플릿 기반) |
| 부작용 | ask_user interrupt (선택지 N개일 때) |

**핵심 로직** (pave_domain.md 규칙 8의 단계적 축소를 코드로 구현):

```
Step 1: process/project 특정
  - entities에서 process 또는 project/project_name 추출
  - DB 조회로 매칭 → 1개면 자동, N개면 ask_user

Step 2: mask 확인
  - project의 mask 조회 → 1개면 자동, N개면 ask_user

Step 3: dk_gds 확인
  - (project, mask)의 dk_gds 조회 → 1개면 자동, N개면 ask_user

Step 4: golden 자동 선택
  - HSPICE/LVS/PEX 미명시 → IS_GOLDEN=1 자동

기본값 적용:
  - corner 미지정 → TT
  - temp 미지정 → 25°C
  - vdd 미지정 → nominal VDD
  - cell 미지정 → AVG (INV, ND2, NR2)
  - ds 미지정 → AVG (D1, D4)
```

### 6.3 query_builder

| 항목 | 내용 |
|------|------|
| 읽기 | parsed_intent, pdk_resolution |
| 쓰기 | query_plan |
| LLM | 없음 (코드 기반) |

**핵심 로직 — SQL 동적 조립**:

intent별 SQL 템플릿이 아니라, **하나의 SQL builder가 entity를 보고 WHERE 절을 조립**한다.

```python
def build_query(pdk_id: int, entity: dict, is_bulk: bool) -> str:
    select_cols = BASE_COLS + resolve_metric_cols(entity.get("metrics"))
    where_clauses = [f"d.PDK_ID = {pdk_id}"]

    # entity 기반 WHERE 조건 추가
    if entity.get("corners"):
        where_clauses.append(f"d.CORNER IN ({quote_list(entity['corners'])})")
    if entity.get("temps"):
        where_clauses.append(f"d.TEMP IN ({num_list(entity['temps'])})")
    if entity.get("vdds"):
        where_clauses.append(f"d.VDD IN ({num_list(entity['vdds'])})")
    if entity.get("vths"):
        where_clauses.append(f"d.VTH IN ({quote_list(entity['vths'])})")
    if entity.get("cells"):
        where_clauses.append(f"d.CELL IN ({quote_list(entity['cells'])})")
    elif not is_bulk:  # cells 비어있음 = AVG
        where_clauses.append("(d.CELL LIKE 'INV%' OR d.CELL LIKE 'ND2%' OR d.CELL LIKE 'NR2%')")
    if entity.get("drive_strengths"):
        where_clauses.append(f"d.DS IN ({quote_list(entity['drive_strengths'])})")
    elif not is_bulk:  # ds 비어있음 = AVG
        where_clauses.append("d.DS IN ('D1', 'D4')")
    if entity.get("cell_heights"):
        where_clauses.append(f"d.CH IN ({quote_list(entity['cell_heights'])})")
    if entity.get("nanosheet_widths"):
        where_clauses.append(f"d.WNS IN ({quote_list(entity['nanosheet_widths'])})")

    limit = 15000 if is_bulk else 1000
    return f"""
        SELECT {', '.join(select_cols)}
        FROM antsdb.PAVE_PPA_DATA_VIEW d
        WHERE {' AND '.join(where_clauses)}
        FETCH FIRST {limit} ROWS ONLY
    """
```

- 안전 규칙 코드 레벨 강제: SELECT만, WHERE 필수, FETCH FIRST N ROWS ONLY
- 모든 SQL에 `antsdb.` 스키마 접두사 자동 포함
- anomaly intent: `is_bulk=True`, WHERE 조건 최소화 (전체 sweep)

### 6.4 data_executor

| 항목 | 내용 |
|------|------|
| 읽기 | query_plan |
| 쓰기 | query_result |
| LLM | 없음 |
| 안전장치 | SELECT only 검증, 타임아웃 30s (일반) / 60s (bulk) |

### 6.5 analyzer

| 항목 | 내용 |
|------|------|
| 읽기 | parsed_intent, pdk_resolution, query_result |
| 쓰기 | analysis_result |
| LLM | 없음 (Python: pandas, numpy, scipy) |

**3개 모드 + analysis_hint 기반 분기**:

| intent | 모드 | 핵심 연산 |
|--------|------|-----------|
| `analyze` | analyze | entity + analysis_hint에 따라 아래 분기. PDK 1개면 요약/프로파일, 2개면 변화율 비교. entity에 비교축(vths 2종 등)이 있으면 자동으로 축별 비교 |
| `trend` | trend | N개 PDK 요약 → 버전별 추이 |
| `anomaly` | anomaly | z-score/IQR → 클러스터링 |

**analyze 모드 내부 분기**:

```python
def analyze_mode(entity, resolution, datasets):
    hint = entity.get("analysis_hint")
    pdk_count = len(resolution["target_pdks"])

    if hint == "sensitivity":
        return calc_sensitivity(datasets, vary_axis=infer_axis(entity))
    elif hint == "worst_case":
        return find_worst_case(datasets, metric=entity["metrics"])
    elif hint == "tradeoff":
        return calc_tradeoff(datasets, axis=infer_compare_axis(entity))
    elif hint == "correlation":
        return calc_correlation(datasets, x=..., y=...)
    elif hint == "interpolation":
        return interpolate(datasets, target=...)
    elif pdk_count == 2:
        # 2 PDK 비교: 변화율(Δ%) 계산
        return calc_delta(datasets, axis="pdk")
    else:
        # 1 PDK: entity에 비교축이 있으면 비교, 없으면 요약
        compare_axis = infer_compare_axis(entity)
        if compare_axis:
            return calc_delta(datasets, axis=compare_axis)
        else:
            return summarize(datasets)
```

**핵심**: PDK 1개 vs 2개의 분기가 intent가 아니라 `pdk_count`로 자동 결정된다.

**anomaly 모드 상세**:
- 두 PDK의 동일 조건(CELL/DS/VTH/CORNER/TEMP/VDD) 쌍 매칭
- 지표별 변화율 계산 (FREQ_GHZ, D_POWER, S_POWER, IDDQ_NA, ACCEFF_FF, ACREFF_KOHM)
- s_power/iddq_na는 log 변환 후 z-score (exponential 분포 고려)
- |z| > 2인 데이터 포인트를 이상치로 식별
- 이상치를 조건 영역별로 클러스터링 (예: "VTH=HVT, TEMP=125" 영역에 집중)
- SSE: 단계별 진행상황 발행

### 6.6 interpreter

| 항목 | 내용 |
|------|------|
| 읽기 | parsed_intent, pdk_resolution, analysis_result |
| 쓰기 | interpretation |
| LLM | heavy-tier |
| 호출 횟수 | 일반: 1회. anomaly: 클러스터당 1회 (최대 5회) |
| 컨텍스트 | ~8K: 시스템프롬프트(~2K) + 도메인지식 관련 섹션(~3K) + 분석 결과 요약(~2K) + 기본값(~0.5K) |

**시스템 프롬프트 핵심 요소**:
- 응답 규칙 (존댓말, DB 컬럼명 그대로, 이모지 금지)
- 소극적 권장 가이드라인
- 도메인 지식 (선택적 로딩, intent별 매핑)

**도메인 지식 선택적 로딩 — entity 기반 매핑**:

도메인 지식은 intent가 아니라 **entity의 내용**으로 결정한다.

| entity 조건 | 로딩 섹션 |
|-------------|-----------|
| `vths`에 2종 이상 또는 hint=tradeoff | 5.4 Vth |
| `drive_strengths`에 2종 이상 | 5.1 Drive Strength |
| `temps`에 2종 이상 또는 hint=sensitivity | 6.1 Temperature × PPA |
| `vdds`에 2종 이상 또는 hint=sensitivity | 6.2 VDD × PPA |
| `cell_heights`에 2종 이상 | 5.3 Cell Height |
| `nanosheet_widths`에 2종 이상 | 5.2 Nanosheet Width |
| pdk_count == 2 또는 intent=trend | 3. PPA 기본 Trade-off |
| intent=anomaly | 6.1 + 6.2 + 5.4 |
| hint=worst_case | 규칙 2: Worst-case 매핑 |
| hint=tradeoff | 3. PPA 기본 Trade-off |

### 6.7 visualizer

| 항목 | 내용 |
|------|------|
| 읽기 | analysis_result, interpretation |
| 쓰기 | chart_specs |
| LLM | 없음 (코드 기반) |

interpreter의 suggested_charts를 우선 사용, 없으면 intent 기반 기본 매핑으로 차트 유형 결정.

### 6.8 response_formatter

| 항목 | 내용 |
|------|------|
| 읽기 | interpretation (또는 fallback_result), analysis_result, chart_specs, pdk_resolution |
| 쓰기 | final_response |
| LLM | light-tier, 1회 |
| 컨텍스트 | ~4K: 포맷팅 규칙 + interpretation + 데이터 테이블 요약 |
| 역할 | 한국어 정제 (중국어 혼입 제거), 응답 포맷팅 (테이블 배치, 핵심 수치 강조) |

### 6.9 fallback_agent

| 항목 | 내용 |
|------|------|
| 읽기 | user_question, conversation_history, screen_context |
| 쓰기 | fallback_result, analysis_result (선택적) |
| LLM | heavy-tier (ReAct) |
| 도구 | execute_sql, stats_tool, correlation_tool, interpolation_tool, ask_user |
| 구조 | v7 main_agent 계승 |

---

## 7. 안전 정책

| 정책 | 분산 파이프라인 | fallback ReAct |
|------|----------------|----------------|
| SELECT only 강제 | query_builder + data_executor | execute_sql 도구 |
| SQL 호출 횟수 | 최대 6회 (resolver 3 + executor 3) | 최대 5회 |
| 결과 행 제한 | 일반: 1,000행. bulk: 15,000행 | 최대 10,000행 |
| 쿼리 타임아웃 | 일반: 30초. bulk: 60초 | 30초 |
| WHERE 필수 | query_builder에서 강제 | 시스템 프롬프트 + sql_patterns.md |
| AVG() 집계 금지 | query_builder에서 강제 | 시스템 프롬프트 + sql_patterns.md |
| 연결 풀 제한 | 최대 10개 동시 연결 | 동일 |

---

## 8. API 엔드포인트

### POST /api/v1/analyze (v7 동일, SSE 이벤트 확장)

```json
{
    "question": "SF3 대비 SF2 성능 비교해줘",
    "conversation_id": "conv-001",
    "conversation_history": [{"question": "...", "summary": "..."}],
    "screen_context": null
}
```

SSE 이벤트:

| event | 발생 노드 | data 예시 |
|-------|-----------|-----------|
| `progress` | intent_parser | `{"stage": "parsing", "message": "질문 분석 중..."}` |
| `progress` | pdk_resolver | `{"stage": "resolving", "message": "PDK 버전 확정: Root EVT1 (Golden)"}` |
| `clarification` | pdk_resolver | `{"question": "SF3에 Root EVT0, Root EVT1, Solomon EVT1이 있습니다.", "options": [...]}` |
| `progress` | data_executor | `{"stage": "querying", "message": "데이터 조회 중..."}` |
| `progress` | analyzer | `{"stage": "analyzing", "message": "비교 분석 중..."}` |
| `progress` | analyzer (anomaly) | `{"stage": "detecting", "message": "이상치 17건 탐지"}` |
| `progress` | interpreter | `{"stage": "interpreting", "message": "결과 해석 중..."}` |
| `result` | response_formatter | `{final_response}` |
| `done` | | `{}` |
| `error` | any | `{"message": "...", "stage": "..."}` |

### POST /api/v1/clarify (v7 동일)

```json
{
    "conversation_id": "conv-001",
    "response": "2"
}
```

### GET /api/v1/health (v7 동일)

```json
{"status": "healthy", "version": "0.8.0"}
```

---

## 9. 프로젝트 구조

```
pave-agent/
├── SPEC.md                          # 이 문서
├── CLAUDE.md                        # Claude Code 작업 지침
├── graph.py                         # LangGraph 그래프 정의 (분산 노드 + fallback)
├── state.py                         # PaveAgentState + 구조체 정의
├── config.py                        # pydantic-settings 환경설정
├── nodes/                           # 그래프 노드
│   ├── intent_parser.py             # ★ intent 분류 + entity 추출 (LLM-light)
│   ├── pdk_resolver.py              # PDK 버전 특정 (코드, ask_user)
│   ├── query_builder.py             # SQL 동적 조립 — entity 기반 WHERE 절 (코드)
│   ├── data_executor.py             # SQL 실행 (코드)
│   ├── analyzer.py                  # 통계 분석 (코드, 모드별 분기)
│   ├── interpreter.py               # ★ 분석 결과 해석 (LLM-heavy)
│   ├── visualizer.py                # Plotly JSON 차트 스펙 (코드)
│   ├── response_formatter.py        # ★ 한국어 정제 + 포맷팅 (LLM-light)
│   └── fallback_agent.py            # ReAct 에이전트 (LLM-heavy, v7 계승)
├── nodes/tools/                     # fallback_agent 도구
│   ├── execute_sql.py
│   ├── stats_tool.py
│   ├── correlation_tool.py
│   ├── interpolation_tool.py
│   └── ask_user.py
├── nodes/resources/                 # 도메인 지식
│   ├── schema_catalog.md
│   ├── pave_domain.md
│   ├── sql_patterns.md
│   └── domain_loader.py             # ★ entity 기반 도메인 섹션 선택적 로딩
├── shared/
│   ├── db.py                        # DB 연결 (Oracle)
│   └── llm.py                       # LLM 클라이언트 (heavy/light 2-tier)
├── api/
│   └── routes.py                    # /analyze, /clarify, /health
├── chat.py                          # 디버깅용 대화형 CLI
├── test_connections.py
├── requirements.txt
└── .env.example
```

---

## 10. 예상 질문 처리 흐름 예시

### 예시 1: "SF3 대비 SF2 성능 비교해줘"

```
[intent_parser] LLM-light
  입력: "SF3 대비 SF2 성능 비교해줘"
  출력: {intent: "analyze",
         entities: {processes: ["SF3","SF2"], metrics: ["freq_ghz"], analysis_hint: null},
         missing: ["mask"]}
  route: "distributed"

[pdk_resolver] 코드
  SF3 → 3개 project → ask_user("SF3에 Root EVT0, Root EVT1, Solomon EVT1이 있습니다.")
  사용자: "Root EVT1"
  SF2 → 1개 → 자동 선택 (Thetis EVT0)
  기본값: TT, 25°C, nominal VDD, CELL AVG, DS AVG

[query_builder] 코드
  SQL builder가 entity 기반으로 WHERE 조립 × 2 PDK
  cells 비어있음 → AVG 조건, ds 비어있음 → AVG 조건

[data_executor] 코드
  SQL 실행 → 각 ~250행

[analyzer] 코드 (compare 모드)
  변화율 계산: FREQ_GHZ +5.8%, D_POWER +3.2%, S_POWER +12.1%
  findings: [{type: "regression", metric: "S_POWER", severity: "high", detail: "+12.1%"}]

[interpreter] LLM-heavy
  entity에 processes 2종 → 섹션 3 (PPA Trade-off) 로딩
  "SF3(Root EVT1)은 SF2(Thetis EVT0) 대비 FREQ_GHZ가 5.8% 향상되었으나..."

[visualizer] 코드 → Grouped Bar
[response_formatter] LLM-light → 한국어 정제
```

### 예시 2: "LVT랑 RVT 차이 얼마나 돼?"

```
[intent_parser] LLM-light
  출력: {intent: "analyze",
         entities: {vths: ["LVT","RVT"], metrics: ["freq_ghz","s_power"], analysis_hint: null},
         missing: ["process"]}

[pdk_resolver] 코드
  ask_user("어떤 공정에서 확인할까요?") → 사용자 응답 → 1 PDK 특정
  기본값: TT, 25°C, nominal VDD, CELL AVG, DS AVG

[query_builder] 코드
  SQL 1개: WHERE PDK_ID=... AND VTH IN ('LVT','RVT') AND DS IN ('D1','D4') AND ...

[analyzer] 코드 (analyze → entity에 vths 2종 → 자동 변화율 계산)

[interpreter] LLM-heavy
  entity에 vths 2종 → 섹션 5.4 (Vth) 로딩
  "LVT는 RVT 대비 FREQ_GHZ가 X% 높지만, S_POWER가 Y배 높습니다..."
```

### 예시 3: "이상치 찾아줘"

```
[intent_parser] → {intent: "anomaly", missing: ["process"]}
[pdk_resolver] → ask_user → 2 PDK 특정
[query_builder] → bulk SQL ×2 (WHERE 최소, FETCH FIRST 15000)
[data_executor] → ~13K행 ×2. SSE: "데이터 수집 완료"
[analyzer] → anomaly 모드. SSE: "이상치 17건 탐지"
[interpreter] → 클러스터별 원인 추정 (최대 5회). SSE: "원인 분석 중 (3/5)"
[visualizer] → scatter + heatmap
[response_formatter] → 한국어 정제 + 이상치 리포트
```

### 예시 4: "온도 올리면 leakage 얼마나 변해?"

```
[intent_parser] → {intent: "analyze",
                    entities: {metrics: ["s_power","iddq_na"], analysis_hint: "sensitivity"},
                    missing: ["process"]}
[pdk_resolver] → ask_user → 1 PDK 특정. 기본값에서 temps를 전 온도 포인트로 확장
[query_builder] → SQL 1개: temps 조건 없이 전 온도 데이터 조회
[analyzer] → analyze + hint=sensitivity: 온도 축 기준 변화율 계산
[interpreter] → entity에 hint=sensitivity → 섹션 6.1 로딩
               "s_power는 온도에 exponential하게 증가합니다..."
```

---

## 11. 에러 처리

| 노드 | 에러 유형 | 처리 |
|------|-----------|------|
| intent_parser | LLM 응답 파싱 실패 / 타임아웃 | route → fallback |
| pdk_resolver | 프로젝트 미존재 / Golden 미존재 | error 메시지 → response_formatter → END |
| query_builder | 템플릿 매칭 실패 | route → fallback |
| data_executor | SQL 에러 / 타임아웃 / 결과 0행 | error 또는 warning → END |
| analyzer | 연산 에러 | error → END |
| interpreter | LLM 타임아웃 / 품질 저하 | 분석 결과만으로 응답 (해석 없이 테이블+차트) |
| response_formatter | LLM 타임아웃 | interpreter 출력을 그대로 반환 (정제 없이) |

---

## 변경 이력

| 버전 | 날짜 | 주요 변경 |
|------|------|----------|
| v1~v2 | 2026-02-26 | 초기 설계, skill 시스템 |
| v3 | 2026-02-26 | PAVE 도메인 반영, View 2개 전략 |
| v4 | 2026-03-05 | skills/ 제거 → resources 통합, clarifier 통합, 노드 10→8개 |
| v5 | 2026-03-05 | analysis-agent ReAct 도입, 노드 8→6개, 분석 도구 4종 추가 |
| v6 | 2026-03-06 | stub 모드 제거, dev/live 2모드 체제 |
| v7 | 2026-03-08 | 6-node→3-node 통합. sql_tool→execute_sql, clarifier→ask_user, report_composer→format_response |
| **v8** | **2026-03-16** | **ReAct 단일 에이전트 → 분산 노드 + Fallback ReAct 전환. Intent 간소화 (14종 → 3+1종: analyze/trend/anomaly/unknown, entity + analysis_hint 기반 세부 분기). LLM 3-point 호출 (intent_parser light + interpreter heavy + response_formatter light). SQL 동적 조립 (entity 기반 WHERE 절). 이상치 감지 재정의 (결함 탐지 → 설계 주의 수치 식별). 판단 보조 소극적 권장. 사내 모델 전용 prod 아키텍처.** |
