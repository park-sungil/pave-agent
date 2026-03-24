# CLAUDE.md

## Project Overview

PDK cell-level PPA 분석 에이전트. 사용자의 자연어 질문을 받아 Oracle DB에서 데이터를 조회하고 분석 결과를 반환.

- **Stack**: Python 3.12, LangGraph, LangChain, FastAPI
- **DB**: Oracle
- **LLM (prod)**: 사내 모델 (OpenAI 호환 API) — heavy/light 2-tier
- **LLM (dev)**: Anthropic Claude (Sonnet=heavy, Haiku=light)

## Architecture — 분산 노드 + Fallback ReAct

```
intent_parser (LLM-light)
    ├── distributed → pdk_resolver → query_builder → data_executor
    │                → analyzer → interpreter (LLM-heavy)
    │                → visualizer → response_formatter (LLM-light)
    │
    └── fallback → fallback_agent (ReAct, LLM-heavy)
                 → visualizer → response_formatter (LLM-light)
```

### LLM 호출 지점 (3곳만)

| 노드 | 티어 | 역할 | 호출 수 |
|------|------|------|---------|
| intent_parser | light | intent 분류 + entity 추출 | 1회 |
| interpreter | heavy | 분석 결과 해석 + 도메인 지식 적용 | 1~5회 |
| response_formatter | light | 한국어 정제 + 포맷팅 | 1회 |

나머지 노드는 전부 코드 기반 (LLM 없음).

## Key Files

| 파일 | 역할 |
|------|------|
| `graph.py` | LangGraph 그래프 정의 (분산 + fallback) |
| `state.py` | PaveAgentState + 구조체 (ParsedIntent, PDKResolution, ...) |
| `nodes/intent_parser.py` | intent 분류 + entity 추출 (LLM-light) |
| `nodes/pdk_resolver.py` | PDK 버전 특정 (코드, ask_user interrupt) |
| `nodes/query_builder.py` | SQL 동적 조립 — entity 기반 WHERE 절 (코드) |
| `nodes/data_executor.py` | SQL 실행 (코드) |
| `nodes/analyzer.py` | 통계 분석 — 모드별 분기 (코드) |
| `nodes/interpreter.py` | 분석 결과 해석 (LLM-heavy) |
| `nodes/visualizer.py` | Plotly JSON 차트 스펙 (코드) |
| `nodes/response_formatter.py` | 한국어 정제 + 포맷팅 (LLM-light) |
| `nodes/fallback_agent.py` | ReAct 에이전트 (LLM-heavy, v7 계승) |
| `nodes/resources/domain_loader.py` | entity 기반 도메인 섹션 선택적 로딩 |
| `nodes/resources/schema_catalog.md` | DB 스키마 정의 |
| `nodes/resources/sql_patterns.md` | SQL 패턴 예시 |
| `nodes/resources/pave_domain.md` | PPA 도메인 지식 |
| `config.py` + `.env` | 설정 (API 키, DB 접속, 모델명) |
| `shared/llm.py` | LLM 인스턴스 관리 (heavy/light 2-tier) |
| `shared/db.py` | DB 연결 (Oracle) |
| `api/routes.py` | FastAPI 엔드포인트 (/analyze, /clarify) |
| `chat.py` | 디버깅용 CLI |

## Commands

```bash
source .venv/bin/activate
PYTHONPATH=. python test_connections.py        # 연결 테스트
PYTHONPATH=. python test_connections.py db     # DB만
PYTHONPATH=. python test_connections.py llm    # LLM만
PYTHONPATH=. python test_connections.py graph  # E2E
PYTHONPATH=. python chat.py                    # 대화형 테스트
PYTHONPATH=. uvicorn api:app --reload          # API 서버
```

## Coding Conventions

- Python 3.12, type hints 사용
- 한국어 docstring/주석
- `from __future__ import annotations` 모든 파일 상단에
- DB 쿼리: Oracle SQL 문법
- SQL에 `AVG()` 집계 함수 사용 금지 — 개별 행 조회 후 analyzer에서 계산
- 모든 SQL에 `antsdb.` 스키마 접두사, WHERE 필수, FETCH FIRST N ROWS ONLY 필수
- SQL은 LLM이 생성하지 않음 (fallback 제외) — query_builder의 entity 기반 동적 조립

## 노드 개발 규칙

### 코드 노드 (pdk_resolver, query_builder, data_executor, analyzer, visualizer)
- LLM 호출 금지
- 입출력은 state.py의 TypedDict로 타입 지정
- 단위 테스트 필수 (입력 → 기대 출력)
- 에러 시 state["error"]에 메시지 기록

### LLM 노드 (intent_parser, interpreter, response_formatter)
- 시스템 프롬프트는 각 노드 파일 내 상수로 관리
- 구조화 JSON 출력 시 파싱 실패 처리 필수
- interpreter: 도메인 지식은 domain_loader.py로 필요 섹션만 로딩
- response_formatter: 중국어 혼입 제거 확인

### fallback_agent
- v7 main_agent.py를 계승
- 시스템 프롬프트 + ReAct 도구 세트 유지
- 분산 파이프라인의 intent 커버리지가 넓어지면 fallback 비율 감소 목표

## 응답 규칙 (interpreter + response_formatter 공통)

- 존댓말(합쇼체)
- DB 컬럼명을 그대로 사용, 한국어 번역/부연설명 괄호 금지
- "golden PDK", "대표 버전", "프로젝트/마스크" 표현 금지 → "버전"
- 평균 표기: "DS AVG(D1/D4)", "CELL AVG(INV/ND2/NR2)"
- 숫자 비교는 테이블 우선, raw data + 변화율 함께 표시
- 근거 데이터 테이블 항상 포함
- CELL/DS 미지정 시 AVG, 성능 지표 미지정 시 FREQ_GHZ
- 버전 1개면 자동 선택, 2개 이상이면 ask_user
- 이모지 금지
- 소극적 권장: "추천합니다" (X) → "검토해볼 만합니다" (O)
