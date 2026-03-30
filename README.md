# pave-agent

PDK 셀 수준 PPA 분석 에이전트. 자연어 질문 → Oracle DB 조회 → 분석 결과 반환.

---

## 시작하기

### 1. 가상환경 생성 및 의존성 설치

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
# .env 열어서 LLM_BASE_URL, LLM_API_KEY, ORACLE_* 값 채우기
```

### 3. 연결 테스트

```bash
PYTHONPATH=. python test_connections.py       # 전체 (DB + LLM + 그래프)
PYTHONPATH=. python test_connections.py db    # DB만
PYTHONPATH=. python test_connections.py llm   # LLM만
```

### 4. 대화형 테스트

```bash
PYTHONPATH=. python chat.py
```

---

## 파일 구조

```
pave-agent/
├── graph.py                  # 에이전트 흐름 정의
├── state.py                  # 노드 간 공유 데이터 구조
├── nodes/
│   ├── intent_parser.py      # 질문 의도 분류 (LLM)
│   ├── pdk_resolver.py       # PDK 버전 특정
│   ├── query_builder.py      # SQL 동적 조립
│   ├── data_executor.py      # SQL 실행
│   ├── analyzer.py           # 통계 분석
│   ├── interpreter.py        # 결과 해석 (LLM)
│   ├── visualizer.py         # 차트 스펙 생성
│   ├── response_formatter.py # 한국어 응답 정제 (LLM)
│   ├── fallback_agent.py     # ReAct 에이전트 (예외 처리)
│   └── resources/            # 도메인 지식, DB 스키마, SQL 패턴
├── shared/
│   ├── llm.py                # LLM 인스턴스 (heavy / light)
│   └── db.py                 # Oracle DB 연결
├── api/                      # FastAPI 엔드포인트
├── requirements.txt
└── .env.example
```

---

## 에이전트 구조

```
사용자 질문
    │
intent_parser          ← 질문을 분류하고 entity 추출 (LLM)
    │
    ├─ 일반 분석 ──────── pdk_resolver → query_builder → data_executor
    │                         → analyzer → interpreter (LLM) → visualizer
    │
    ├─ 목록 조회 ──────── (바로 응답)
    │
    └─ 판단 불가 ──────── fallback_agent (LLM, ReAct)
                               │
                          response_formatter ← 한국어 정제 (LLM)
                               │
                          최종 응답 반환
```

LLM은 3곳에서만 호출됩니다: `intent_parser`, `interpreter`, `response_formatter`.
나머지 노드는 모두 코드 기반 처리입니다.

---

## API 서버 실행

```bash
PYTHONPATH=. uvicorn api:app --reload
# POST /analyze  — 분석 요청
# POST /clarify  — 추가 질문 응답
```
