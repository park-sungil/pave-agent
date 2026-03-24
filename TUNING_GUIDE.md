# pave-agent v8 — 튜닝 가이드

> 구현 과정에서 발생한 이슈, 해결 과정, 추가 튜닝 항목 정리.
> 다른 코드 에이전트와 함께 작업할 때 이 문서를 먼저 참조.

---

## 1. 구현 히스토리

### 기반 구축
- `state.py`: SPEC 섹션 5의 TypedDict 구현.
- `config.py`: pydantic-settings. 사내 OpenAI 호환 API + Oracle.
- `shared/db.py`: Oracle Thick 모드. `execute_query()` 단일 인터페이스.
- `shared/pdk_cache.py`: 앱 기동 시 PDK 카탈로그 1회 캐시.
- `graph.py`: 9개 노드 + 조건부 분기(distributed / list / fallback).

### intent_parser — analysis_hint 파싱 이슈

**문제**: LLM이 `analysis_hint`를 `entities` 밖 최상위 JSON에 배치. 코드는 `entities` 안에서만 탐색.

**해결**: 양쪽 탐색.
```python
if not entities.get("analysis_hint") and parsed.get("analysis_hint"):
    entities["analysis_hint"] = parsed["analysis_hint"]
```

**교훈**: LLM의 JSON 출력 구조가 프롬프트와 다를 수 있다. 파싱을 유연하게.

### pdk_resolver — golden 기반 버전 선택

- IS_GOLDEN=1 레코드 기반으로 리팩토링.
- 1개 → 자동, 여러 개 → 전체 컬럼 테이블로 사용자 선택.
- `comparison_version` missing_params → 같은 project의 다른 버전 목록 제시.

### query_builder — 기본값 + sensitivity 축 처리

**문제**: 기본값(TT, 25°C, nominal VDD)이 실제 WHERE에 미적용.

**해결**: entity가 비어있으면 기본값을 WHERE에 적용. sensitivity 축은 제외.
```
일반:              WHERE CORNER='TT' AND TEMP=25 AND VDD=0.72
sensitivity(TEMP): WHERE CORNER='TT' AND VDD=0.72  ← TEMP 전체
sensitivity(VDD):  WHERE CORNER='TT' AND TEMP=25    ← VDD 전체
```

### analyzer — numpy 직렬화

**문제**: `TypeError: Object of type int64 is not JSON serializable`

**해결**: `_to_python()` 유틸로 numpy → Python 기본 타입 변환.

### list intent 추가

- `intent: "list"` → `response_formatter`로 직행 (LLM 없이 코드 기반 포맷).
- `pdk_cache.py`에서 로드한 available_pdks를 인메모리 필터링 → 마크다운 테이블 출력.

---

## 2. 현재 상태

| Eval | 결과 | 비고 |
|------|------|------|
| intent_parser | **20/20 (100%)** | intent 5종 + hint 7종 + entity + missing_params |
| E2E 파이프라인 | **7/7 (100%)** | summarize, compare, sensitivity, worst_case, correlation, tradeoff, fallback |
| eval 케이스 | **30건** | list intent 10건 포함 |

---

## 3. 튜닝 항목

### 3.1 intent_parser 프롬프트

**파일**: `nodes/intent_parser.py`의 `SYSTEM_PROMPT`

**튜닝 포인트**:
- `analysis_hint` 분류 정확도. few-shot 예시 추가로 개선.
- `list` intent 분류. "뭐가 있어", "목록" 키워드.
- `comparison_version` missing_params 탐지.

**eval**: `PYTHONPATH=. python eval/run_eval.py`

### 3.2 interpreter 프롬프트

**파일**: `nodes/interpreter.py`의 `SYSTEM_PROMPT`

**튜닝 포인트**:
- 중국어 혼입 방지.
- 소극적 권장 톤.
- 도메인 지식 로딩량 vs 응답 품질.

### 3.3 response_formatter 프롬프트

**파일**: `nodes/response_formatter.py`의 `SYSTEM_PROMPT`

**핵심**: 중국어 정제 + PDK 버전 테이블 코드 기반 삽입 (`_format_selected_pdks_header`).

### 3.4 analyzer 임계값

**파일**: `nodes/analyzer.py`

| 파라미터 | 현재 값 | 위치 |
|----------|---------|------|
| z-score 임계값 | \|z\| > 2 | `_detect_anomalies()` |
| 변화율 경고 | \|delta\| > 3% | `_calc_delta()` |
| severity 기준 | 10%/5% | `_calc_delta()` |
| log 변환 대상 | S_POWER, IDDQ_NA | `LOG_METRICS` |

### 3.5 VDD가 다른 PDK 간 anomaly (미구현)

**옵션**:
1. VDD를 매칭 키에서 제외, nominal VDD만 비교.
2. VDD 비율 기준 매칭.

**수정 위치**: `nodes/analyzer.py`의 `_detect_anomalies()` 내 `match_cols`.

---

## 4. Eval 사용법

```bash
# intent_parser eval
PYTHONPATH=. python eval/run_eval.py
PYTHONPATH=. python eval/run_eval.py IP-05 IP-21   # 특정 케이스

# E2E eval
PYTHONPATH=. python eval/run_e2e.py

# 연결 테스트
PYTHONPATH=. python test_connections.py db
PYTHONPATH=. python test_connections.py llm
PYTHONPATH=. python test_connections.py graph
```

### 케이스 추가

`eval/cases.json`:
```json
{
  "id": "IP-31",
  "question": "새로운 질문",
  "expected": {
    "intent": "analyze",
    "hint": "sensitivity",
    "processes": ["SF3"],
    "metrics_contains": ["freq_ghz"],
    "missing_contains": ["process"]
  }
}
```

### 튜닝 사이클

```
eval 실행 → 실패 케이스 확인 → 프롬프트 수정 → eval 재실행 → regression 확인
```

---

## 5. 파일별 수정 가이드

| 목적 | 수정 파일 | 수정 대상 |
|------|-----------|-----------|
| intent 분류 | `nodes/intent_parser.py` | `SYSTEM_PROMPT` |
| 해석 품질 | `nodes/interpreter.py` | `SYSTEM_PROMPT` |
| 응답 포맷 | `nodes/response_formatter.py` | `SYSTEM_PROMPT`, `_format_list()` |
| 이상치 임계값 | `nodes/analyzer.py` | `_detect_anomalies()` |
| 기본값 | `nodes/query_builder.py` | `build_query()` |
| 도메인 지식 매핑 | `nodes/resources/domain_loader.py` | `load_domain_sections()` |
| 도메인 지식 내용 | `nodes/resources/pave_domain.md` | 섹션 수정/추가 |
| PDK 버전 선택 | `nodes/pdk_resolver.py` | `_resolve_single_pdk()`, SQL 템플릿 |
| eval 케이스 | `eval/cases.json` | JSON 항목 추가 |
| LLM/DB 설정 | `.env` | 환경변수 |
