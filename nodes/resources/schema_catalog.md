# PAVE DB 스키마 카탈로그

## View 1: antsdb.PAVE_PDK_VERSION_VIEW

PDK 버전 정보를 저장하는 뷰.
하나의 PDK 버전은 (PROJECT, MASK, DK_GDS, HSPICE, LVS, PEX) 조합으로 특정된다.
PDK 버전이 바뀌면 동일 설계라도 PPA 결과가 달라진다 (SPICE 모델, Design Rule, Cell Library 변경에 의함).

| 컬럼 | 타입 | 설명 | 예시 값 |
|------|------|------|---------|
| PAVE_PDK_ID | NUMBER | PDK 고유 ID (PK) | 881, 882, 900 |
| PROCESS | VARCHAR2 | 공정명. process → project는 1:N 관계. 사용자가 가장 자주 대화 시작점으로 사용하지만 process만으로는 project를 특정할 수 없음 | LN04LPE, LN04LPP, SF3, SF2, SF2P, SF2PP |
| PROJECT | VARCHAR2 | 프로젝트명 (과제 코드). process(공정명)와는 1:N 관계이므로 process만으로는 project를 특정할 수 없음 | S5E9945, S5E9955, S5E9965, S5E9975 |
| PROJECT_NAME | VARCHAR2 | 프로젝트 별명. PROJECT와 함께 사용자 입력 매칭 시 양쪽 모두 시도 | Root, Solomon, Thetis, Ulysses, Vanguard |
| MASK | VARCHAR2 | 마스크 버전 | EVT0, EVT1 |
| DK_GDS | VARCHAR2 | DK GDS. PDK 버전 특정에 필요한 6개 키 중 하나. 사용자가 처음부터 언급하는 경우는 드묾 | Solomon EVT1, Thetis EVT0, Thetis EVT1, Ulysses EVT0, Ulysses EVT1, Vanguard EVT0 |
| IS_GOLDEN | NUMBER(1) | Golden PDK 여부. (PROJECT, MASK, DK_GDS) 조합별로 관리자가 지정한 대표 버전. 미명시 시 IS_GOLDEN=1을 기본으로 사용 | 0, 1 |
| VDD_NOMINAL| NUMBER | nominal voltage | 0.72, 0.75 |
| HSPICE | VARCHAR2 | HSPICE 도구 버전. 변경 시 timing/power 시뮬레이션 결과 변동 | V0.9.0.0, V0.9.2.0, V0.9.5.0, V1.0.0.0 |
| LVS | VARCHAR2 | LVS 도구 버전. PDK 구성 요소 중 하나 | V0.9.0.0, V0.9.2.0, V0.9.5.0, V1.0.0.0 |
| PEX | VARCHAR2 | PEX 도구 버전. PDK 구성 요소 중 하나 | V0.9.0.0, V0.9.2.0, V0.9.5.0, V1.0.0.0 |
| CREATED_AT | DATE | 생성일 | 2026-03-07 00:50:05 |
| CREATED_BY | VARCHAR2 | 생성자 | si0807.park |

## View 2: antsdb.PAVE_PPA_DATA_VIEW

셀 레벨 PPA 측정 데이터를 저장하는 뷰.
Ring Oscillator(RO) 기반으로 측정된 cell-level PPA 결과이며, 측정 상태에 따라 Dynamic(RO 발진 중)과 Static(입력 고정, 발진 정지)으로 구분된다.

### 설계 파라미터 및 측정 조건

| 컬럼 | 타입 | 설명 | 예시 값 |
|------|------|------|---------|
| PDK_ID | NUMBER | PDK ID (FK → PAVE_PDK_VERSION_VIEW.PAVE_PDK_ID) | |
| CELL | VARCHAR2 | 셀 이름. 기본 셀 타입 3종: INV(Inverter, 가장 빠름/작음), ND2(2-input NAND), NR2(2-input NOR, 가장 느림/큼). 동일 셀 타입 내에서만 PPA 비교가 유의미함 | INV, ND2, NR2 |
| DS | VARCHAR2 | Drive Strength. D1, D2, D3, ... 형태로 표기. 트랜지스터 W/L ratio에 의해 결정되며, 숫자가 클수록 구동력이 높음. D가 N배이면 power/area도 약 N배 | D1, D2, D3, D4 |
| CORNER | VARCHAR2 | Process corner. 공정 편차 조건. FF=Fast-Fast, TT=Typical-Typical, SS=Slow-Slow, SF=Slow-Fast, FS=Fast-Slow | TT, SSPG |
| TEMP | NUMBER | 측정 온도 (°C). s_power/iddq_na는 온도에 exponential 의존 (약 10°C당 1.5~2배 증가). freq_ghz는 미세공정에서 Temperature Inversion 발생 가능 (저온에서 오히려 느려짐) | -25, 25, 125 |
| VDD | NUMBER | 공급 전압 (V). d_power는 V²에 비례 (10% 증가 시 d_power 약 21% 증가). freq_ghz와 양의 상관(비선형). s_power/iddq_na는 DIBL 효과로 exponential 증가 | 0.5, 0.72, 0.8, ... <!-- TODO: 실제 예시 --> |
| VTH | VARCHAR2 | Threshold Voltage 타입. low-Vth(ULVT쪽)일수록 고속/고leakage, high-Vth(HVT쪽)일수록 저속/저leakage. Temperature Inversion은 HVT에서 가장 두드러짐 | ULVT, SLVT, VLVT, LVT, MVT, RVT, HVT |
| WNS | VARCHAR2 | GAA nanosheet 채널 폭 (Nanosheet Width). wNS 형태로 표기. 숫자가 클수록 폭이 넓고 구동력이 높음. FinFET의 fin 개수 역할을 대체 | N1, N2, N3, N4, N5 |
| WNS_VAL | NUMBER | Nanosheet Width 값 (nm). GAA nanosheet 채널의 물리적 폭 | 15, 20, 25, 35, 45, 50 |
| CH | VARCHAR2 | Cell Height. CH + 물리적 높이(nm) 형태로 표기 (예: CH138, CH168, CH200). Track 수 × metal pitch로 결정. 줄이면 면적 감소하지만 drive strength 상한 저하 및 라우팅 제약 | CH138, CH148, CH168, CH200 |
| CH_TYPE | VARCHAR2 | Cell Height 타입 | uHD, HD, HP |

### 측정 파라미터 — Dynamic (RO 발진 중 측정, 함께 변하는 경향)

| 컬럼 | 타입 | 단위 | 설명 |
|------|------|------|------|
| FREQ_GHZ | NUMBER | GHz | RO 발진 주파수. f = 1/(2×N×t_pd)로부터 산출. 셀의 intrinsic delay를 반영하는 **성능 대표 지표**. PDK 버전 간 비교, PVT corner별 특성 파악에 사용 |
| D_POWER | NUMBER | mW | 동적 전력. P = C·V²·f. 스위칭 활동 기반 소비 전력 |
| D_ENERGY | NUMBER | | 1회 switching transition당 소비 에너지. D_ENERGY = ACCEFF_FF × V². 동적 에너지 효율의 직접 지표 |
| ACCEFF_FF | NUMBER | fF | AC Effective Capacitance. switching에 관여하는 실효 커패시턴스 (채널+overlap+junction+wire 합). d_power와 d_energy에 직접 기여 |
| ACREFF_KOHM | NUMBER | kΩ | AC Effective Resistance. 구동 경로의 실효 저항. RC delay를 통해 freq_ghz에 직접 영향 |

### 측정 파라미터 — Static (입력 고정, 발진 정지 상태에서 측정, 함께 변하는 경향)

| 컬럼 | 타입 | 단위 | 설명 |
|------|------|------|------|
| S_POWER | NUMBER | mW | 정적(누설) 전력. 트랜지스터 off-state 누설전류 기반. 온도에 exponential 의존 (-25°C vs 125°C에서 수십 배 차이 가능) |
| IDDQ_NA | NUMBER | nA | IDDQ 누설전류. 이중 성격: (1) 정상 범위 내 → s_power와 직접 상관하는 leakage 지표, (2) 동일 조건 대비 비정상적으로 높은 값 → 제조 결함(bridging, gate-oxide short 등) 가능성. 비교 시 반드시 동일 온도·VDD 조건 필요 |


## 조인 관계

```sql
-- 두 View 조인
SELECT v.PROJECT, v.MASK, d.CELL, d.FREQ_GHZ
FROM antsdb.PAVE_PPA_DATA_VIEW d
JOIN antsdb.PAVE_PDK_VERSION_VIEW v
  ON d.PDK_ID = v.PAVE_PDK_ID
WHERE v.PROJECT = '...'
```

## AVG 처리

사용자가 drive_strength 또는 cell을 "AVG"로 요청하는 경우:
- DS = AVG → DS IN ('D1', 'D4') 개별 행 조회 후 앱 레벨에서 평균 계산
- CELL = AVG → 기본 3종(INV, ND2, NR2) 개별 행 조회 후 앱 레벨에서 평균 계산
- SQL의 AVG() 집계 함수를 사용하지 않는다.

## 주의사항
- 모든 쿼리에 `antsdb.` 스키마 접두사 사용
- WHERE 조건절 필수 (View 풀스캔 방지)
- `FETCH FIRST N ROWS ONLY`로 결과 제한
- PPA 비교 시 반드시 동일 PVT corner(Process, VDD, Temperature) 조건 확인
