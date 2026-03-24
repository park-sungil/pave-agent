# pave-agent v8 — 구현 가이드

> Claude Code에서 새 디렉토리로 시작하는 구현 순서와 지침.
> 이 문서와 함께 SPEC_v8.md, CLAUDE_v8.md, schema_catalog.md, sql_patterns_v8.md, pave_domain_v8.md를 참조한다.

---

## 0. 프로젝트 초기화

```bash
mkdir pave-agent && cd pave-agent
python -m venv .venv && source .venv/bin/activate
```

### 디렉토리 구조 생성
```
pave-agent/
├── SPEC.md                          # SPEC_v8.md 복사
├── CLAUDE.md                        # CLAUDE_v8.md 복사
├── graph.py
├── state.py
├── config.py
├── nodes/
│   ├── __init__.py
│   ├── intent_parser.py
│   ├── pdk_resolver.py
│   ├── query_builder.py
│   ├── data_executor.py
│   ├── analyzer.py
│   ├── interpreter.py
│   ├── visualizer.py
│   ├── response_formatter.py
│   └── fallback_agent.py
├── nodes/tools/
│   ├── __init__.py
│   ├── execute_sql.py
│   ├── stats_tool.py
│   ├── correlation_tool.py
│   ├── interpolation_tool.py
│   └── ask_user.py
├── nodes/resources/
│   ├── schema_catalog.md
│   ├── pave_domain.md
│   ├── sql_patterns.md
│   └── domain_loader.py
├── shared/
│   ├── __init__.py
│   ├── db.py
│   └── llm.py
├── api/
│   ├── __init__.py
│   └── routes.py
├── chat.py
├── test_connections.py
├── requirements.txt
└── .env.example
```

### requirements.txt
```
langgraph>=0.2.0
langchain>=0.3.0
langchain-openai>=0.2.0
langchain-anthropic>=0.2.0
fastapi>=0.115.0
uvicorn>=0.32.0
python-dotenv>=1.0.0
pydantic-settings>=2.0.0
python-oracledb>=2.0.0
pandas>=2.0.0
numpy>=1.26.0
scipy>=1.12.0
sse-starlette>=2.0.0
```

### .env.example
```
# LLM (prod: 사내 모델)
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://your-internal-api.com/v1
LLM_API_KEY=your-key
LLM_MODEL_HEAVY=GLM4.7
LLM_MODEL_LIGHT=MiniMax-M2.1

# LLM (dev: Anthropic Claude)
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-...
# ANTHROPIC_MODEL_HEAVY=claude-sonnet-4-20250514
# ANTHROPIC_MODEL_LIGHT=claude-haiku-4-5-20251001

# Oracle DB
ORACLE_DSN=your-tns-dsn
ORACLE_USER=antsdb
ORACLE_PASSWORD=your-password
```

---

## 1단계: state.py + config.py

### config.py
- pydantic-settings 기반
- .env에서 LLM/DB 설정 로딩
- LLM_PROVIDER: "openai_compat" (prod) / "anthropic" (dev)

### state.py
- SPEC_v8.md 섹션 5의 타입 정의를 그대로 구현
- IntentType = Literal["analyze", "trend", "anomaly", "unknown"]
- AnalysisHint = Literal["profile", "sensitivity", "worst_case", "tradeoff", "correlation", "interpolation", None]
- ParsedIntent, ResolvedPDK, PDKResolution, QueryPlan, QueryResult, AnalysisResult, Interpretation, ChartSpec, FinalResponse
- PaveAgentState (LangGraph TypedDict)

**검증**: 타입 힌트가 정확한지 mypy 또는 수동 확인.

---

## 2단계: shared/ (DB + LLM 인프라)

### shared/db.py
- Oracle Thick 모드 연결 (oracledb)
- execute_query(sql: str, timeout: int = 30) → list[dict]
- SELECT only 검증 (안전장치)

### shared/llm.py
- heavy/light 2-tier LLM 클라이언트
- get_llm(tier: Literal["heavy", "light"]) → ChatOpenAI 또는 ChatAnthropic
- LLM_PROVIDER=openai_compat: LLM_BASE_URL + LLM_MODEL_HEAVY/LIGHT 사용
- LLM_PROVIDER=anthropic: ANTHROPIC_API_KEY + ANTHROPIC_MODEL_HEAVY/LIGHT 사용

**검증**: `PYTHONPATH=. python test_connections.py db` 성공.

---

## 3단계: graph.py (LangGraph 그래프 정의)

- 분산 파이프라인: intent_parser → pdk_resolver → query_builder → data_executor → analyzer → interpreter → visualizer → response_formatter
- Fallback 경로: intent_parser → fallback_agent → visualizer → response_formatter
- route 분기: intent_parser가 state["route"]를 "distributed" 또는 "fallback"로 설정
- pdk_resolver에서 interrupt() 지원 (ask_user)

**이 단계에서는 각 노드를 stub으로 구현** (pass-through). 그래프 연결과 라우팅만 검증.

```python
# stub 예시
def intent_parser(state: PaveAgentState) -> dict:
    return {
        "parsed_intent": ParsedIntent(
            intent="analyze",
            entities={},
            missing_params=[],
            raw_question=state["user_question"],
        ),
        "route": "distributed",
    }
```

**검증**: stub 그래프가 START → ... → END까지 흐르는지 확인. chat.py로 간단한 질문 테스트.

---

## 4단계: intent_parser.py (LLM-light)

### 구현
- 시스템 프롬프트: SPEC_v8.md 섹션 6.1 참조
- LLM 호출: shared/llm.py의 light-tier
- JSON 파싱: 실패 시 route="fallback"
- conversation_history에서 최근 2턴만 요약하여 포함

### 시스템 프롬프트 핵심
- Intent 4종 정의 + 분류 기준 (SPEC 4.3)
- Entity 추출 규칙 (SPEC 4.4)
- analysis_hint 규칙 (SPEC 4.4)
- 출력: 구조화 JSON

**검증**: benchmark_llm.py의 intent_parser 케이스 15건으로 테스트.

---

## 5단계: pdk_resolver.py (코드, ask_user)

### 구현
- 입력: parsed_intent.entities
- SQL로 PDK 버전 조회 (shared/db.py 사용)
- 단계적 축소: process → project → mask → dk_gds → golden (pave_domain.md 규칙 8)
- 선택지 1개 → 자동 확정, N개 → interrupt() + ask_user
- 기본값 적용: TT, 25°C, nominal VDD, CELL AVG, DS AVG
- intent에 따라 PDK 수 결정:
  - analyze: entity에 process/project 2개면 pair, 1개면 single
  - trend: 3~5개
  - anomaly: 2개

### PDK 조회 SQL (코드 내 상수)
```sql
-- process로 project 찾기
SELECT DISTINCT PROJECT, PROJECT_NAME, PROCESS
FROM antsdb.PAVE_PDK_VERSION_VIEW
WHERE PROCESS = '{process}'
FETCH FIRST 20 ROWS ONLY

-- project의 mask 찾기
SELECT DISTINCT MASK
FROM antsdb.PAVE_PDK_VERSION_VIEW
WHERE PROJECT = '{project}'
FETCH FIRST 10 ROWS ONLY

-- golden PDK 찾기
SELECT PAVE_PDK_ID, PROJECT, PROJECT_NAME, MASK, DK_GDS,
       HSPICE, LVS, PEX, IS_GOLDEN, VDD_NOMINAL
FROM antsdb.PAVE_PDK_VERSION_VIEW
WHERE PROJECT = '{project}' AND MASK = '{mask}' AND IS_GOLDEN = 1
FETCH FIRST 5 ROWS ONLY
```

**검증**: Oracle DB에서 "SF3" 입력 → project 목록 반환, project_name 입력 → PDK 특정 확인.

---

## 6단계: query_builder.py (코드)

### 구현
- 입력: parsed_intent + pdk_resolution
- SQL 동적 조립 (SPEC 6.3의 build_query 로직)
- entity 기반 WHERE 절 조립
- AVG 처리: cells 비어있으면 INV/ND2/NR2, ds 비어있으면 D1/D4
- anomaly: is_bulk=True, WHERE 최소화, FETCH FIRST 15000
- 안전 규칙 코드 레벨 강제

**검증**: 다양한 entity 조합으로 SQL 생성 → 문법 오류 없는지 확인.

---

## 7단계: data_executor.py (코드)

### 구현
- 입력: query_plan
- SQL 실행 (shared/db.py)
- SELECT only 재검증
- 타임아웃: 30s (일반), 60s (bulk)
- 결과: datasets[] + warnings[]

**검증**: Oracle DB에서 실제 SQL 실행 → 결과 행 반환 확인.

---

## 8단계: analyzer.py (코드, 핵심)

### 구현
- 3개 모드: analyze, trend, anomaly
- analyze 모드 내부: analysis_hint + pdk_count 기반 분기 (SPEC 6.5)
  - pdk_count==2: calc_delta (변화율)
  - hint=sensitivity: calc_sensitivity
  - hint=worst_case: find_worst_case
  - hint=tradeoff: calc_tradeoff
  - hint=correlation: calc_correlation
  - hint=interpolation: interpolate
  - 기본: entity에 비교축 있으면 calc_delta, 없으면 summarize
- trend 모드: 버전별 요약 → 추이 계산
- anomaly 모드: 조건 매칭 → 변화율 → z-score/IQR → 클러스터링

### 의존
- pandas, numpy, scipy.stats

**검증**: Oracle DB 실 데이터로 각 모드 단위 테스트. anomaly 모드는 z-score 임계값 조정이 필요할 수 있음.

---

## 9단계: interpreter.py (LLM-heavy)

### 구현
- 입력: parsed_intent + pdk_resolution + analysis_result
- 도메인 지식 선택적 로딩: domain_loader.py (entity 기반 매핑, SPEC 6.6)
- 시스템 프롬프트: 응답 규칙 + 도메인 지식 관련 섹션 + 분석 결과
- LLM 호출: heavy-tier, 1회 (anomaly: 클러스터당 1회, 최대 5회)
- JSON 출력 파싱
- 실패 시: 분석 결과만으로 응답 (graceful degradation)

### domain_loader.py
- pave_domain.md를 섹션별로 분할하여 딕셔너리에 저장
- entity 내용에 따라 관련 섹션 선택 (SPEC 6.6의 매핑 테이블)

**검증**: analyzer 출력을 입력으로 넣고, 한국어 해석이 나오는지 확인. 중국어 혼입 여부 확인.

---

## 10단계: visualizer.py (코드)

### 구현
- 입력: analysis_result + interpretation.suggested_charts
- Plotly JSON 차트 스펙 생성
- 차트 유형: grouped_bar, line, scatter, heatmap, histogram, box_plot

**검증**: 생성된 JSON을 Plotly.js에서 렌더링 가능한지 확인 (또는 plotly.py로 검증).

---

## 11단계: response_formatter.py (LLM-light)

### 구현
- 입력: interpretation + analysis_result + chart_specs + pdk_resolution (또는 fallback_result)
- LLM 호출: light-tier, 1회
- 역할: 한국어 정제 (중국어 혼입 제거) + 응답 포맷팅 (테이블 배치, 핵심 수치 강조)
- 실패 시: interpreter 출력을 그대로 반환

**검증**: 중국어가 섞인 interpreter 출력을 넣고 정제 결과 확인.

---

## 12단계: fallback_agent.py (LLM-heavy, ReAct)

### 구현
- v7 main_agent.py를 복사하여 리네이밍
- 도구: execute_sql, stats_tool, correlation_tool, interpolation_tool, ask_user
- 시스템 프롬프트: 기존 v7 프롬프트 + schema_catalog.md + sql_patterns.md + pave_domain.md

**검증**: intent_parser에서 unknown으로 빠진 질문이 fallback에서 처리되는지 확인.

---

## 13단계: api/routes.py + chat.py

### api/routes.py
- POST /api/v1/analyze → 그래프 실행 + SSE 스트리밍
- POST /api/v1/clarify → interrupt resume
- GET /api/v1/health
- SSE 이벤트: progress, clarification, result, done, error

### chat.py
- 디버깅용 대화형 CLI
- 그래프 실행 + 결과 출력 + interrupt 처리

**검증**: E2E 테스트 — chat.py로 다양한 질문 유형 테스트.

---

## 구현 원칙 (CLAUDE.md 참조)

- Python 3.12, type hints
- `from __future__ import annotations` 모든 파일 상단
- 한국어 docstring/주석
- 각 노드 구현 후 반드시 단위 테스트
- SQL에 AVG() 집계 함수 사용 금지
- 모든 SQL에 antsdb. 접두사, WHERE 필수, FETCH FIRST N ROWS ONLY
- LLM 노드의 JSON 출력은 파싱 실패 처리 필수

---

## 검증 체크리스트

| 단계 | 검증 항목 | 통과 기준 |
|------|-----------|-----------|
| 1 | state.py 타입 정의 | mypy 에러 없음 |
| 2 | DB 연결 | Oracle DB SELECT 성공 |
| 3 | 그래프 stub 흐름 | START → END 도달 |
| 4 | intent_parser | 15건 중 12건 이상 정확 |
| 5 | pdk_resolver | "SF3" → project 목록, "Thetis" → PDK 특정 |
| 6 | query_builder | 생성된 SQL 문법 오류 없음 |
| 7 | data_executor | Oracle DB에서 결과 반환 |
| 8 | analyzer | 각 모드 단위 테스트 통과 |
| 9 | interpreter | 한국어 해석 생성, JSON 파싱 성공 |
| 10 | visualizer | Plotly JSON 스펙 유효 |
| 11 | response_formatter | 중국어 정제 성공 |
| 12 | fallback_agent | unknown 질문 처리 |
| 13 | E2E | "SF3 대비 SF2 비교" 전체 흐름 성공 |
