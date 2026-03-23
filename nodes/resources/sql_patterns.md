# PAVE SQL 패턴

> v8: query_builder 노드가 entity 기반으로 SQL을 동적 조립한다.
> 이 문서는 (1) query_builder 구현 시 참조하는 SQL 패턴 가이드,
> (2) fallback_agent(ReAct)의 시스템 프롬프트에 주입하는 SQL 작성 가이드를 겸한다.

## 안전 규칙 (필수)
1. SELECT 문만 생성 (INSERT/UPDATE/DELETE/DROP 절대 금지)
2. WHERE 조건절 필수 (View 풀스캔 방지)
3. `FETCH FIRST {N} ROWS ONLY` 필수 — 일반: 1000, bulk(anomaly): 15000
4. `antsdb.` 스키마 접두사 사용
5. `AVG()` 등 집계 함수 사용 금지 — 개별 행 조회 후 analyzer에서 계산

## 기본 조회 패턴

### 특정 프로젝트의 Golden PDK 정보
```sql
SELECT v.PAVE_PDK_ID, v.PROJECT, v.PROJECT_NAME, v.MASK, v.DK_GDS,
       v.HSPICE, v.LVS, v.PEX, v.IS_GOLDEN
FROM antsdb.PAVE_PDK_VERSION_VIEW v
WHERE v.PROJECT = '{PROJECT}'
  AND v.IS_GOLDEN = 1
FETCH FIRST 10 ROWS ONLY
```

### 특정 PDK의 PPA 데이터 조회
```sql
SELECT d.CELL, d.DS, d.CORNER, d.TEMP, d.VDD,
       d.FREQ_GHZ, d.D_POWER, d.S_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
  AND d.CORNER = '{CORNER}'
  AND d.TEMP = {TEMP}
FETCH FIRST 100 ROWS ONLY
```

## 비교 분석 패턴

### Golden vs Non-Golden 비교
```sql
SELECT v.PAVE_PDK_ID, v.IS_GOLDEN,
       d.CELL, d.DS, d.FREQ_GHZ, d.D_POWER, d.S_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
JOIN antsdb.PAVE_PDK_VERSION_VIEW v
  ON d.PDK_ID = v.PAVE_PDK_ID
WHERE v.PROJECT = '{PROJECT}'
  AND d.CORNER = '{CORNER}'
  AND d.TEMP = {TEMP}
ORDER BY d.CELL, d.DS, v.IS_GOLDEN DESC
FETCH FIRST 500 ROWS ONLY
```

### CORNER별 성능 비교
```sql
SELECT d.CORNER, d.CELL, d.DS, d.FREQ_GHZ, d.D_POWER, d.S_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
  AND d.TEMP = {TEMP}
ORDER BY d.CORNER, d.CELL, d.DS
FETCH FIRST 200 ROWS ONLY
```
> 평균이 필요하면 개별 행 조회 후 analyzer에서 계산한다.

## 집계/분포 패턴

### 셀별 FREQ_GHZ 랭킹
```sql
SELECT d.CELL, d.DS, d.FREQ_GHZ, d.D_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
  AND d.CORNER = '{CORNER}'
  AND d.TEMP = {TEMP}
ORDER BY d.FREQ_GHZ DESC
FETCH FIRST {N} ROWS ONLY
```

### VDD별 성능 조회
```sql
SELECT d.VDD, d.CELL, d.DS, d.FREQ_GHZ, d.D_POWER, d.S_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
  AND d.CORNER = '{CORNER}'
ORDER BY d.VDD, d.CELL, d.DS
FETCH FIRST 200 ROWS ONLY
```
> 평균이 필요하면 개별 행 조회 후 analyzer에서 계산한다.

## AVG 처리 패턴 (중요 — SQL AVG() 사용 금지)

사용자가 drive_strength 또는 cell을 "AVG"로 요청하는 경우:
- **SQL의 AVG() 집계 함수를 사용하지 않는다.**
- 대표 조합의 개별 행을 모두 SELECT한 뒤, analyzer에서 앱 레벨로 평균을 계산한다.

### drive_strength = AVG → DS IN ('D1', 'D4') 개별 행 조회
```sql
SELECT d.CORNER, d.TEMP, d.VDD, d.DS,
       d.FREQ_GHZ, d.D_POWER, d.S_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
  AND d.DS IN ('D1', 'D4')
  AND d.CORNER = '{CORNER}'
ORDER BY d.VDD, d.DS
FETCH FIRST 200 ROWS ONLY
```

### cell = AVG → 기본 3종(INV, ND2, NR2) 개별 행 조회
```sql
SELECT d.CORNER, d.TEMP, d.VDD, d.DS, d.CELL,
       d.FREQ_GHZ, d.D_POWER, d.S_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
  AND (d.CELL LIKE 'INV%' OR d.CELL LIKE 'ND2%' OR d.CELL LIKE 'NR2%')
  AND d.CORNER = '{CORNER}'
ORDER BY d.VDD, d.CELL, d.DS
FETCH FIRST 200 ROWS ONLY
```

### 둘 다 AVG → DS + CELL 조건 AND 결합, 개별 행 조회
```sql
SELECT d.CORNER, d.TEMP, d.VDD, d.DS, d.CELL,
       d.FREQ_GHZ, d.D_POWER, d.S_POWER
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
  AND d.DS IN ('D1', 'D4')
  AND (d.CELL LIKE 'INV%' OR d.CELL LIKE 'ND2%' OR d.CELL LIKE 'NR2%')
  AND d.CORNER = '{CORNER}'
ORDER BY d.VDD, d.CELL, d.DS
FETCH FIRST 200 ROWS ONLY
```

> **주의**: 평균 계산은 반드시 analyzer에서 수행한다. SQL에서 GROUP BY + AVG()를 사용하면 안 된다.

## 이상치 분석 패턴 (v8 신규 — intent=anomaly)

### 전체 PPA 데이터 bulk pull
```sql
SELECT d.CELL, d.DS, d.VTH, d.CORNER, d.TEMP, d.VDD,
       d.CH, d.CH_TYPE, d.WNS, d.WNS_VAL,
       d.FREQ_GHZ, d.D_POWER, d.D_ENERGY, d.ACCEFF_FF, d.ACREFF_KOHM,
       d.S_POWER, d.IDDQ_NA
FROM antsdb.PAVE_PPA_DATA_VIEW d
WHERE d.PDK_ID = {PDK_ID}
FETCH FIRST 15000 ROWS ONLY
```
> WHERE 조건을 최소화하여 전체 파라미터 공간을 sweep한다.
> 두 PDK에 대해 각각 실행하여 ~13K행 × 2를 수집한 뒤, analyzer에서 조건 매칭 및 이상치 탐지를 수행한다.
> 타임아웃: 60초 (일반 30초보다 확장).

## 원인 분석 패턴
<!-- 성일: 실무에서 자주 쓰는 원인 분석 쿼리 추가 -->

### 도구 버전 차이 확인
```sql
SELECT v.PAVE_PDK_ID, v.IS_GOLDEN,
       v.HSPICE, v.LVS, v.PEX
FROM antsdb.PAVE_PDK_VERSION_VIEW v
WHERE v.PROJECT = '{PROJECT}'
ORDER BY v.CREATED_AT DESC
FETCH FIRST 10 ROWS ONLY
```

## Oracle 문법 참고
- 문자열은 작은따옴표: `WHERE PROJECT = 'ABC'`
- NULL 비교: `IS NULL` / `IS NOT NULL`
- 날짜: `TO_DATE('2024-01-01', 'YYYY-MM-DD')`
- 페이징: `FETCH FIRST N ROWS ONLY` (Oracle 12c+)
- LIKE: `WHERE CELL LIKE 'INV%'`

## v8 query_builder 동적 SQL 조립 참조

query_builder는 위 패턴을 참조하여, entity의 내용에 따라 WHERE 절을 동적으로 조립한다.

### 기본 SELECT 컬럼 (항상 포함)
```
d.CELL, d.DS, d.VTH, d.CORNER, d.TEMP, d.VDD, d.CH, d.WNS
```

### 측정 지표 컬럼 (entity.metrics에 따라 선택)
| entity.metrics 값 | 포함 컬럼 |
|-------------------|-----------|
| `freq_ghz` | d.FREQ_GHZ |
| `d_power` | d.D_POWER |
| `s_power` | d.S_POWER |
| `iddq_na` | d.IDDQ_NA |
| `d_energy` | d.D_ENERGY |
| `acceff_ff` | d.ACCEFF_FF |
| `acreff_kohm` | d.ACREFF_KOHM |
| (비어있음 또는 전체) | 모든 측정 지표 포함 |

### WHERE 절 조립 규칙
| entity 키 | 값이 있을 때 | 값이 없을 때 (기본값) |
|-----------|-------------|---------------------|
| corners | `AND d.CORNER IN (...)` | `AND d.CORNER = 'TT'` |
| temps | `AND d.TEMP IN (...)` | `AND d.TEMP = 25` |
| vdds | `AND d.VDD IN (...)` | `AND d.VDD = {nominal_vdd}` |
| cells | `AND d.CELL IN (...)` | AVG: `AND (d.CELL LIKE 'INV%' OR ...)` |
| drive_strengths | `AND d.DS IN (...)` | AVG: `AND d.DS IN ('D1', 'D4')` |
| vths | `AND d.VTH IN (...)` | (조건 없음 — 전 Vth 조회) |
| cell_heights | `AND d.CH IN (...)` | (조건 없음) |
| nanosheet_widths | `AND d.WNS IN (...)` | (조건 없음) |

> anomaly intent일 때: WHERE 조건은 `PDK_ID`만. 나머지 조건 없이 전체 sweep.
