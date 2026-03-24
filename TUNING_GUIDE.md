# pave-agent v8 — 튜닝 가이드

> 이 문서는 v8 구현 과정에서 발생한 이슈, 해결 과정, 그리고 사내 환경에서 추가 튜닝이 필요한 항목을 정리한 것입니다.
> 다른 코드 에이전트와 함께 작업할 때 이 문서를 참조하세요.

---

## 1. 구현 히스토리 (무슨 일이 있었나)

### 1단계~3단계: 기반 구축
- `state.py`: SPEC 섹션 5의 TypedDict 그대로 구현. 문제 없음.
- `config.py`: pydantic-settings 기반. `LLM_PROVIDER=anthropic/openai_compat` 전환.
- `shared/db.py`: Oracle Thick 모드 연결. execute_query() 단일 인터페이스.
- `graph.py`: 9개 노드 + 조건부 분기(distributed/fallback). stub으로 검증 후 순차 구현.

### 4단계: intent_parser — **핵심 이슈 발견**

**문제**: intent 분류는 처음부터 정확했으나, `analysis_hint`가 전부 null로 나옴.

**원인**: Haiku가 `analysis_hint`를 `entities` 객체 밖 최상위 JSON에 배치함. 코드는 `entities` 안에서만 찾고 있었음.

```python
# LLM 출력 (Haiku)
{
  "intent": "analyze",
  "entities": { ... },          # ← analysis_hint 여기 없음
  "analysis_hint": "sensitivity",  # ← 여기에 있음
  "missing_params": ["process"]
}
```

**해결**: 파싱 로직에서 양쪽 모두 탐색하도록 수정.
```python
# entities 안 또는 최상위에서 탐색
if not entities.get("analysis_hint") and parsed.get("analysis_hint"):
    entities["analysis_hint"] = parsed["analysis_hint"]
```

**교훈**: LLM의 JSON 출력 구조가 프롬프트와 정확히 일치하지 않을 수 있다. 파싱 로직을 유연하게 만들어야 한다.

### 5단계: pdk_resolver — interrupt 흐름

- SF3처럼 project가 2개 이상이면 `interrupt()` 발생 → 사용자 선택 → resume.
- SF3 Root는 mask도 2개(EVT0/EVT1)라 **연속 interrupt** 발생.
- LangGraph의 `MemorySaver` checkpointer로 interrupt/resume 상태 관리.

### 6~7단계: query_builder + data_executor

- 구현은 직관적. entity 기반 WHERE 절 동적 조립.
- **나중에 발견된 문제**: 기본값(TT, 25°C, nominal VDD)이 표시용일 뿐 실제 WHERE에 적용되지 않음 → 13단계에서 수정.

### 8단계: analyzer — numpy int64 직렬화 오류

**문제**: `TypeError: Object of type int64 is not JSON serializable`

**원인**: pandas/numpy 타입이 dict에 그대로 들어가서 interpreter가 JSON.dumps할 때 실패.

**해결**: `_to_python()` 유틸 함수로 numpy 타입 → Python 기본 타입 변환.
```python
def _to_python(val):
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (np.floating,)): return round(float(val), 6)
    ...
```

### 9~12단계: interpreter, visualizer, response_formatter, fallback_agent

- **interpreter**: domain_loader가 entity 기반으로 pave_domain.md 섹션을 선택적 로딩. 잘 작동.
- **visualizer**: interpreter가 `histogram`/`box_plot` 같은 미지원 차트 타입을 제안하면 빈 결과 발생 → 미지원 타입은 mode 기반 기본 차트로 fallback 처리.
- **response_formatter**: 중국어 혼입은 dev(Claude) 환경에서는 발생 안 함. prod(사내 모델)에서 확인 필요.
- **fallback_agent**: v7 main_agent를 거의 그대로 포팅. ReAct + 5개 도구.

### 13단계: E2E 통합 + 기본값/sensitivity 수정

**문제 1**: applied_defaults가 표시용으로만 쓰이고 query_builder가 실제 WHERE에 적용하지 않음.
→ "INV D1 LVT 데이터 보여줘"에서 모든 corner/temp/vdd 데이터가 조회되어 분석이 부정확.

**해결**: query_builder에서 entity가 비어있으면 기본값(TT, 25, nominal VDD) 실제 WHERE 적용.

**문제 2**: sensitivity 분석 시 변동축(temp/vdd)에도 기본값이 적용되어 한 포인트만 조회됨.
→ "온도 올리면 leakage?" → temp=25만 조회되어 민감도 분석 불가.

**해결**:
1. pdk_resolver가 `hint=sensitivity`일 때 변동축 추론 + 해당 PDK의 가용 값 DB 조회.
2. query_builder에서 sensitivity_col로 지정된 축은 기본값 적용 제외.

```
일반:       WHERE CORNER='TT' AND TEMP=25 AND VDD=0.72
sensitivity(TEMP): WHERE CORNER='TT' AND VDD=0.72  ← TEMP 필터 없음 = 전체
sensitivity(VDD):  WHERE CORNER='TT' AND TEMP=25    ← VDD 필터 없음 = 전체
```

---

## 2. 현재 상태 (Eval 결과)

| Eval | 결과 | 비고 |
|------|------|------|
| intent_parser | **20/20 (100%)** | intent 4종 + hint 7종 + entity 추출 |
| E2E 파이프라인 | **7/7 (100%)** | summarize, compare, sensitivity, worst_case, correlation, tradeoff, fallback |
| anomaly 탐지 | 1,439건 탐지 | HVT+125°C 클러스터에 S_POWER 384건 집중 |

---

## 3. 사내 환경에서 해야 할 튜닝

### 3.1 LLM 모델 전환 (필수)

`.env`에서 provider를 선택하고 모델을 설정한다.

**사내 모델 (prod)**:
```env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://your-internal-api.com/v1
LLM_API_KEY=your-key
LLM_MODEL_HEAVY=GLM4.7       # interpreter용
LLM_MODEL_LIGHT=MiniMax-M2.1 # intent_parser, response_formatter용
```

**Anthropic Claude (dev)**: `LLM_MODEL_HEAVY/LIGHT`가 아닌 `ANTHROPIC_MODEL_HEAVY/LIGHT`로 지정해야 함.
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_MODEL_HEAVY=claude-sonnet-4-20250514
ANTHROPIC_MODEL_LIGHT=claude-haiku-4-5-20251001
```

**확인 사항**:
1. intent_parser: JSON 출력 안정성. `analysis_hint` 위치가 모델마다 다를 수 있으나 파싱 로직이 양쪽 처리함.
2. interpreter: 한국어 reasoning 품질. 중국어 혼입 여부.
3. response_formatter: 중국어 정제. 사내 모델에서 핵심적으로 중요.

**튜닝 방법**: `eval/run_eval.py` 실행 → 실패 케이스 확인 → 프롬프트 수정 → 재실행.

### 3.2 Oracle DB 연결 (필수)

```env
ORACLE_DSN=your-tns-dsn
ORACLE_USER=antsdb
ORACLE_PASSWORD=your-password
```

**확인 사항**:
- `PYTHONPATH=. python test_connections.py db` 로 연결 테스트.
- `shared/db.py`의 Oracle Thick 모드 초기화. `oracledb.init_oracle_client()` 경로 확인.

### 3.3 intent_parser 프롬프트 튜닝

**현재 위치**: `nodes/intent_parser.py`의 `SYSTEM_PROMPT` 상수.

**튜닝 포인트**:
- 사내 모델이 `analysis_hint`를 잘 분류하는지 eval로 확인.
- 실패하면 few-shot 예시 추가 (현재 7건, 확장 가능).
- 사내 모델의 JSON 출력 형식이 다르면 `_parse_llm_response()` 수정.

**eval 실행**:
```bash
PYTHONPATH=. python eval/run_eval.py          # 전체
PYTHONPATH=. python eval/run_eval.py IP-05    # 특정 케이스만
```

### 3.4 interpreter 프롬프트 튜닝

**현재 위치**: `nodes/interpreter.py`의 `SYSTEM_PROMPT` 상수.

**튜닝 포인트**:
- 중국어 혼입 방지 규칙 강화 (사내 모델에서 중요).
- 소극적 권장 톤 조절.
- 도메인 지식 로딩량 vs 응답 품질 트레이드오프.

### 3.5 response_formatter 프롬프트 튜닝

**현재 위치**: `nodes/response_formatter.py`의 `SYSTEM_PROMPT` 상수.

**핵심**: 사내 모델의 중국어 혼입 제거 능력 확인. 혼입이 심하면 프롬프트에 중국어 금지 규칙을 더 강하게 명시.

### 3.6 analyzer 임계값 튜닝

**현재 위치**: `nodes/analyzer.py`

| 파라미터 | 현재 값 | 설명 | 위치 |
|----------|---------|------|------|
| z-score 임계값 | `\|z\| > 2` | 이상치 판별 기준 | `_detect_anomalies()` |
| 변화율 경고 | `\|delta\| > 3%` | findings 생성 기준 | `_calc_delta()` |
| severity 기준 | 10%/5% | high/medium 분류 | `_calc_delta()` |
| log 변환 대상 | S_POWER, IDDQ_NA | exponential 분포 metric | `LOG_METRICS` 상수 |

**튜닝 방법**: 실 데이터로 anomaly 돌린 뒤 결과 보고 임계값 조정. 사내 엔지니어와 "주의할 수치"의 기준 합의 필요.

### 3.7 VDD가 다른 PDK 간 anomaly 비교 (미구현)

현재 anomaly는 동일 조건(CELL/DS/VTH/CORNER/TEMP/VDD) 매칭. VDD가 다르면 매칭 실패.

**향후 옵션**:
1. VDD를 매칭 키에서 제외하고 nominal VDD 데이터만 비교.
2. VDD 비율(0.7×/0.85×/1.0×/1.1× nominal) 기준 매칭.

**수정 위치**: `nodes/analyzer.py`의 `_detect_anomalies()` 내 `match_cols`.

---

## 4. Eval 체계 사용법

### 파일 구조
```
eval/
├── cases.json       # intent_parser 테스트 케이스 (20건)
├── run_eval.py      # intent_parser eval runner
├── run_e2e.py       # E2E 파이프라인 eval runner (7건)
└── results/         # 실행 결과 JSON (타임스탬프별)
```

### 실행 명령

```bash
# intent_parser eval (전체)
PYTHONPATH=. python eval/run_eval.py

# 특정 케이스만
PYTHONPATH=. python eval/run_eval.py IP-05 IP-11

# E2E eval (interrupt 없는 케이스)
PYTHONPATH=. python eval/run_e2e.py

# 개별 연결 테스트
PYTHONPATH=. python test_connections.py db
PYTHONPATH=. python test_connections.py llm
PYTHONPATH=. python test_connections.py graph
```

### 케이스 추가

`eval/cases.json`에 추가:
```json
{
  "id": "IP-21",
  "question": "새로운 질문",
  "expected": {
    "intent": "analyze",
    "hint": "sensitivity",
    "processes": ["SF3"],
    "metrics_contains": ["freq_ghz"]
  }
}
```

### 튜닝 사이클

```
1. eval 실행 → 실패 케이스 확인
2. 프롬프트 수정 (nodes/intent_parser.py의 SYSTEM_PROMPT)
3. eval 재실행 → 개선 확인 + 기존 케이스 regression 확인
4. 반복
```

---

## 5. 파일별 수정 가이드

| 목적 | 수정 파일 | 수정 대상 |
|------|-----------|-----------|
| intent 분류 개선 | `nodes/intent_parser.py` | `SYSTEM_PROMPT` (few-shot 추가) |
| 해석 품질 개선 | `nodes/interpreter.py` | `SYSTEM_PROMPT` |
| 중국어 정제 강화 | `nodes/response_formatter.py` | `SYSTEM_PROMPT` |
| 이상치 임계값 | `nodes/analyzer.py` | `_detect_anomalies()` 내 z-score 기준 |
| 기본값 변경 | `nodes/query_builder.py` | `build_query()` 내 기본 WHERE 조건 |
| 도메인 지식 매핑 | `nodes/resources/domain_loader.py` | `load_domain_sections()` 내 매핑 |
| 도메인 지식 내용 | `nodes/resources/pave_domain.md` | 섹션 내용 수정/추가 |
| eval 케이스 추가 | `eval/cases.json` | JSON 항목 추가 |
| LLM/DB 설정 | `.env` | 환경변수 |
