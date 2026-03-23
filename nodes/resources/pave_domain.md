# 반도체 PPA 도메인 지식

> pave-agent 프롬프트에 삽입하여 LLM이 PPA 데이터 분석 시 참조하도록 한다.
>
> 본 문서의 도메인 지식은 반도체 업계 3대 학회(IEDM, ISSCC, VLSI Symposium) 및 IEEE 저널 논문, 주요 파운드리(TSMC, Samsung, Intel) 발표 자료, IMEC 등 연구기관 논문을 기반으로 검증되었다.

---

## 1. 파라미터 정의 및 분류

### 1.1 측정 파라미터

| 파라미터 | 분류 | 측정 상태 | 설명 |
|----------|------|-----------|------|
| `freq_ghz` | Performance | Dynamic (RO 발진) | Ring Oscillator 발진 주파수(GHz)로부터 산출. 셀의 intrinsic delay를 반영하는 성능 지표 |
| `d_power` | Power (dynamic) | Dynamic (RO 발진) | 스위칭 활동 기반 소비 전력. P ∝ C·V²·f. RO 발진 중 측정 |
| `d_energy` | Energy (dynamic) | Dynamic (RO 발진) | 1회 switching transition당 소비 에너지. D_ENERGY = ACCEFF × V². 동적 에너지 효율의 직접 지표 |
| `acceff_ff` | Capacitance (effective) | Dynamic (RO 발진) | AC Effective Capacitance(fF). RO 발진 시 switching에 관여하는 실효 커패시턴스. 채널(Cgc), overlap(Cov), junction(Cj), wire(Cwire) 커패시턴스의 합. d_power와 d_energy에 직접 기여 |
| `acreff_kohm` | Resistance (effective) | Dynamic (RO 발진) | AC Effective Resistance(kΩ). RO 발진 시 구동 경로의 실효 저항. RC delay를 통해 freq_ghz에 직접 영향 |
| `s_power` | Power (static/leakage) | Static (입력 고정) | 트랜지스터 off-state 누설전류 기반 전력. 모든 입력을 고정하고 switching이 멈춘 정적 상태에서 측정 |
| `iddq_na` | Power (static) + 품질/신뢰성 | Static (입력 고정) | IDDQ 누설전류(nA). 대기상태(Quiescent state)에서의 공급전류(IDD)를 측정. 이중 성격을 가진다: (1) 정상 범위 내의 값은 leakage 수준 즉 s_power와 직접 상관하는 전력 특성 지표, (2) 비정상적으로 높은 값은 제조 결함을 의미하는 품질 지표 |

### 1.2 설계 파라미터

| 파라미터 | 설명 |
|----------|------|
| `drive_strength` | 셀의 출력 전류 구동 능력. 트랜지스터 W/L ratio에 의해 결정. D1, D2, D3, ... 과 같이 표기하며 숫자가 클수록 구동력이 높다 |
| `nanosheet_width` | GAA(Gate-All-Around) nanosheet FET에서 채널 시트의 가로 폭. nm 수치로 표현하거나 N1, N2, N3, ... 과 같이 단계별로 표기한다. 숫자가 클수록 폭이 넓다. FinFET의 fin 개수 역할을 대체하며 연속적 조절이 가능하다 |
| `cell_height` | Standard cell의 고정 세로 높이. 실무에서는 CH + 물리적 높이(nm) 형태로 표기한다 (예: CH138 = 138nm, CH168 = 168nm, CH200 = 200nm). Track 수 × metal pitch(nm)로 산출되며, CH 값이 클수록 내부에 더 큰 트랜지스터와 라우팅 자원을 확보할 수 있다 |
| `vth` | Threshold Voltage. 트랜지스터 on/off 전환 최소 게이트 전압. ULVT/SLVT/VLVT/LVT/MVT/RVT/HVT 등 multi-Vth 옵션으로 제공되며, 왼쪽일수록 low-Vth(고속, 고leakage), 오른쪽일수록 high-Vth(저속, 저leakage) |

### 1.3 측정 조건

| 조건 | 설명 |
|------|------|
| `temperature` | 측정 온도 조건. 동일 칩이라도 온도에 따라 power, performance 값이 크게 달라진다 |
| `vdd` | 공급 전압. PPA 세 축 모두에 직접 영향을 미치는 핵심 조건이다 |
| `process_corner` | 공정 편차 조건. FF(Fast-Fast), TT(Typical-Typical), SS(Slow-Slow) 등으로 표기한다. pave 시스템에서는 주로 TT와 SSPG가 사용된다 |

pave 시스템의 주요 process corner:
- **TT** (Typical-Typical): NMOS/PMOS 모두 typical한 조건. 기본 조회 및 비교의 기준 corner.
- **SSPG** (SS + Performance + Global): SS(Slow-Slow) 디바이스 모델에 Global Variation(chip-mean, 칩 단위로 나타나는 공정 편차)을 반영한 performance corner. 순수 SS보다 현실적인 worst-case이며, 성능 마진 확인에 사용된다.

---

## 2. PDK (Process Design Kit)

### 2.1 정의

PDK는 파운드리가 설계자에게 제공하는 특정 공정 노드의 설계 도구 모음이다. 해당 공정에서 칩을 설계하는 데 필요한 물리적 특성, 규칙, 모델을 패키지로 포함한다. 섹션 1에서 정의한 모든 파라미터와 측정 조건은 PDK를 기반으로 생성된다.

### 2.2 PDK 구성 요소와 PPA 연관

| 구성 요소 | 내용 | PPA 영향 |
|-----------|------|----------|
| Design Rule | 최소 metal width, spacing, via size 등 레이아웃 규칙 | Area에 직접 영향. rule 변경 시 셀 면적 변동 |
| SPICE Model | 트랜지스터 전기적 특성 모델. PVT corner별로 제공 | Performance, Power 시뮬레이션의 근거. 모델 업데이트 시 delay, power 예측값 변동 |
| Technology File | EDA 툴용 공정 정보. layer 정의, 기생 RC 파라미터, interconnect 모델 | wire delay, parasitic power에 영향 |
| Standard Cell Library | INV, ND2, NR2 등 기본 셀. Liberty(.lib) 파일에 PVT corner별 timing, power, area 정보 포함 | PPA 데이터의 직접적 출처. drive strength 변종(D1, D2, D3, ...)과 multi-Vth 변종(ULVT~HVT)이 모두 포함 |

### 2.3 PDK 버전과 PPA 데이터

- PDK 버전이 바뀌면 동일 설계라도 PPA 결과가 달라진다.
- SPICE 모델 업데이트 → timing/power 시뮬레이션 결과 변동.
- Design rule 변경 → 셀 면적, 라우팅 가능성 변동.
- Cell library 업데이트 → 셀별 timing/power 특성 변동.
- PDK 버전은 PVT corner와 함께 PPA 데이터 비교의 필수 조건이다.

### 2.4 Golden PDK

- PDK는 HSPICE, LVS, PEX 등 세부 버전 조합으로 구성된다.
- `IS_GOLDEN=1`은 (Project, Mask, DK_GDS) 조합별로 관리자가 지정한 대표 PDK 버전을 의미한다.
- 특별한 버전 지정이 없는 한 PPA 데이터 조회 및 비교의 기본 기준으로 사용된다.
- Golden이 아닌 버전은 개발 중이거나 이전 버전일 수 있으며, Golden과 비교하여 회귀/개선을 분석하는 데 활용된다.

---

## 3. PPA 기본 Trade-off

- **Performance ↔ Power**: freq_ghz를 높이면 d_power가 증가한다. voltage를 올리면 power는 V²에 비례하여 급증한다.
- **Performance ↔ Area**: 성능 향상(wider logic, bigger cache)은 die area 증가를 수반한다.
- **Power ↔ Area**: 트랜지스터 수 증가 → s_power(leakage) 증가. 공정 미세화 시 leakage 밀도도 증가할 수 있다.

---

## 4. 기본 셀 타입

### 4.1 INV (Inverter)

- 구성: PMOS 1개 + NMOS 1개. 입력 신호를 반전.
- 라이브러리에서 가장 작은 면적의 셀.
- FO4 delay(fanout-of-4 inverter delay)가 공정 노드 간 성능 비교의 표준 메트릭으로 사용된다.
- PPA 측정의 기준점(reference cell).

### 4.2 ND2 (2-input NAND)

- 구성: PMOS 2개 병렬 + NMOS 2개 직렬.
- NMOS 직렬로 인해 pull-down 저항이 INV보다 높아 동일 drive strength에서 INV보다 느리고 면적이 크다.
- Universal gate로서 모든 논리 함수 구현 가능. 디지털 설계에서 가장 빈번하게 사용되는 셀 중 하나.

### 4.3 NR2 (2-input NOR)

- 구성: PMOS 2개 직렬 + NMOS 2개 병렬.
- PMOS 직렬 + PMOS의 낮은 mobility로 인해 pull-up이 NAND의 pull-down보다 느리다.
- 동일 성능을 내려면 PMOS를 더 크게 설계해야 하므로 면적이 ND2보다 크다.
- CMOS 설계에서는 ND2가 NR2보다 면적·속도 면에서 유리하여 NAND 기반 설계가 선호된다.

### 4.4 셀 타입 간 PPA 순서 (동일 입력 수, 동일 drive strength 기준)

| 지표 | 순서 (우수 → 열위) |
|------|---------------------|
| Performance (speed) | INV > ND2 > NR2 |
| Power (낮을수록 우수) | INV < ND2 < NR2 |
| Area (작을수록 우수) | INV < ND2 < NR2 |

### 4.5 Ring Oscillator (RO)

#### 구조와 동작 원리

Ring Oscillator는 홀수 개의 inverter(또는 다른 반전 셀)를 직렬 연결하고 마지막 출력을 첫 번째 입력으로 피드백시킨 구조이다. 별도의 클럭 없이 자체 발진하며, 발진 주파수는 f = 1 / (2 × N × t_pd)로 결정된다 (N = 셀 수, t_pd = 셀당 propagation delay).

#### PPA 측정에서의 역할

단일 셀의 delay는 picosecond 단위로 직접 측정이 어렵다. RO로 수십~수백 개 셀을 연결하면 발진 주파수를 쉽게 측정할 수 있고, 역산으로 셀당 delay를 구할 수 있다. 이 때문에 RO frequency는 공정 성능의 대표 지표로 사용된다:
- PDK 버전 간 성능 비교
- PVT corner별 성능 특성 파악
- Vth / Drive Strength / Nanosheet Width / Cell Height 변경에 따른 성능 영향 평가
- 웨이퍼 내/간 공정 균일성(uniformity) 모니터링

#### RO 변종

INV 기반 RO가 기본이지만, ND2, NR2 등 다른 셀로도 RO를 구성하여 셀 타입별 delay를 비교한다. 또한 같은 셀 타입이라도 drive strength(D1, D2, ...), Vth(ULVT~HVT), cell height(CH138, CH168, ...), nanosheet width(N1, N2, ...) 조합별로 RO를 만들어 PPA를 체계적으로 평가한다.

#### RO와 측정 파라미터의 관계

| 측정 상태 | 파라미터 | 설명 |
|-----------|----------|------|
| Dynamic (RO 발진 중) | freq_ghz, d_power, d_energy, acceff_ff, acreff_kohm | RO가 발진하는 switching 상태에서 측정. 셀의 속도, 동적 전력, 에너지, 실효 RC 특성을 반영 |
| Static (입력 고정, 발진 정지) | s_power, iddq_na | 모든 입력을 고정하고 switching이 완전히 멈춘 정적 상태에서 측정. 셀의 누설전류와 품질을 반영 |

#### Dynamic 측정 파라미터 간 핵심 관계

acceff_ff(Ceff)와 acreff_kohm(Reff)는 RO 특성의 근본 파라미터이며, 다른 Dynamic 측정값의 기반이 된다:

- **Delay ∝ Reff × Ceff**: 셀당 propagation delay는 실효 저항과 실효 커패시턴스의 곱에 비례한다. 따라서 freq_ghz ∝ 1 / (Reff × Ceff). 이 관계는 14nm FinFET RO에서 Ceff의 정량적 모델로 검증되었다 (IEEE, 2018).
- **D_ENERGY = Ceff × VDD²**: 1회 switching당 소비 에너지는 실효 커패시턴스와 전압 제곱에 비례한다.
- **D_POWER = D_ENERGY × freq = Ceff × VDD² × freq**: 동적 전력은 에너지와 주파수의 곱이다.

이 관계에서 Ceff가 줄면 delay 감소(성능↑) + energy 감소(전력↑)로 양쪽 모두 개선되므로, Ceff 저감은 PPA 최적화의 핵심이다. Reff가 줄면 delay 감소(성능↑)이지만 energy에는 직접 영향하지 않는다.

16nm FinFET RO 공정 최적화 연구(Su & Li, IEEE)에서는 gate spacer 두께, S/D proximity, S/D depth, S/D implant가 Ceff, Reff, IDDQ 세 파라미터에 동시에 영향을 미치며, 이 중 gate spacer 두께가 가장 지배적인 변동 요인으로 보고되었다.

이 구분은 데이터 해석에서 중요하다: freq_ghz, d_power, d_energy, acceff_ff, acreff_kohm은 모두 Dynamic 측정으로 함께 변하는 경향이 있고, s_power와 iddq_na도 Static 측정으로 함께 변하는 경향이 있다. 그러나 Dynamic 지표와 Static 지표 간에는 반드시 같은 방향으로 변하지 않을 수 있다.

---

## 5. 설계 파라미터별 PPA 영향

### 5.1 Drive Strength

| PPA 축 | 영향 |
|--------|------|
| Performance | 높을수록 출력 transition 가속. fanout이 크거나 wire가 긴 경우 timing 유리 |
| Power | d_power: switching capacitance 증가. s_power: leakage area 증가. D4는 D1 대비 약 4배 전력 |
| Area | 트랜지스터 크기에 비례하여 셀 면적 증가. D2 ≈ D1의 약 2배 |

- EDA 툴은 timing slack이 충분한 경로에 low drive strength, 빡빡한 경로에 high drive strength를 배치하여 PPA를 최적화한다.
- 실효 구동 능력은 VDD와 온도에 따라 변한다. VDD가 낮거나, temperature inversion이 있는 공정의 저온 조건에서는 drive capability가 저하될 수 있다.
- Ceff/Reff 관점: drive strength가 높아지면(D1→D4) 트랜지스터 폭 증가로 Reff는 감소(구동력↑)하지만 Ceff는 증가(부하↑)한다. delay = Reff × Ceff에서 Reff 감소 효과가 Ceff 증가를 상쇄하므로 성능이 향상되나, d_energy = Ceff × VDD²는 증가한다.

### 5.2 Nanosheet Width

| PPA 축 | 영향 |
|--------|------|
| Performance | 넓을수록 채널 면적 증가 → 전류 구동력 향상 → freq_ghz 유리 |
| Power | d_power: capacitance 증가. s_power: 채널 면적 증가로 leakage 증가 |
| Area | 같은 셀 footprint 내에서 조절 가능하여 FinFET(fin 개수)보다 면적 효율이 높음. 과도하게 키우면 셀 폭 증가 |

- GAA 시대에서 drive strength 조절의 핵심 메커니즘이다. FinFET의 fin 개수 역할을 대체한다.
- Mixed-width 설계: 같은 칩 내에서 critical path에는 wide, non-critical path에는 narrow nanosheet을 사용하여 PPA를 최적화한다. TSMC는 IEDM 2024에서 N2(2nm) 기술의 "NanoFlex"로 이를 구현했으며, Samsung은 IEDM 2018에서 3nm GAA MBCFET의 nanosheet width 조절을 통한 PPA 최적화를 발표하였다.
- Ceff/Reff 관점: nanosheet width가 넓어지면 채널 면적 증가로 Reff 감소(구동력↑) + Ceff 증가(게이트 커패시턴스↑). drive strength 증가와 유사한 trade-off이며, 에너지(d_energy)는 Ceff에 비례하여 증가한다.

### 5.3 Cell Height

| PPA 축 | 영향 |
|--------|------|
| Performance | 줄이면 트랜지스터 크기 및 라우팅 트랙 제한 → drive strength 상한 저하, 라우팅 detour에 의한 wire delay 증가 가능 |
| Power | 면적 감소로 capacitance 감소(d_power 유리), 라우팅 혼잡 시 wire length 증가로 power 증가 가능 |
| Area | 줄이면 셀 면적이 직접 감소. 공정 미세화에서 area scaling의 핵심 레버 |

- Track 수가 많을수록(예: 7T > 6T > 5T) 내부에 큰 트랜지스터와 많은 라우팅 자원을 확보할 수 있어 성능이 높지만 면적이 커진다.
- Cell height의 물리적 크기(nm)는 track 수 × metal pitch로 결정되며, 실무에서는 CH + nm 값으로 표기한다 (예: CH138, CH168, CH200).
- CH 값과 track 수의 관계: 동일 track 수라도 metal pitch가 다르면 CH 값이 달라지고, 동일 CH 값이라도 metal pitch에 따라 track 수가 달라진다. CH 값은 물리적 높이를 직접 나타내므로, area 계산에서 track 수보다 직관적이다.
- 공정 노드별 대표 사례:
  - 7nm: 6~6.5T cell, M2 pitch 36nm → CH216~CH240 수준
  - 5nm: 6T cell, M2 pitch 28~30nm → CH168~CH180 수준
  - 3nm/4nm: 5~5.5T cell, M2 pitch 21~24nm → CH105~CH132 수준
  - 2nm: 5T cell, M2 pitch 16~20nm → CH80~CH100 수준 (IMEC/TSMC IEDM 발표 기준)
- 미세공정에서는 pitch scaling 둔화로 cell height reduction이 area scaling의 주요 수단이 되고 있다.
- cell height × nanosheet width × sheet 적층 수가 함께 해당 셀의 최대 구동 능력을 결정한다.

### 5.4 Vth (Threshold Voltage)

| Vth 종류 | 특성 |
|----------|------|
| ULVT (Ultra-Low) | 극고속, 극고 leakage. 최소한의 critical path에만 사용 |
| SLVT (Super-Low) | ULVT보다 약간 완화. 여전히 매우 높은 leakage |
| VLVT (Very-Low) | 고속, 고 leakage. 성능 요구가 높은 경로에 사용 |
| LVT (Low) | 고속, 높은 leakage. critical path의 주력 |
| MVT (Medium) | 속도-leakage 중간. general logic에 활용 |
| RVT (Regular) | 속도-leakage 균형형. 면적 대비 효율 우수 |
| HVT (High) | 저속, 극저 leakage. non-critical path 및 저전력 설계에 사용 |

| PPA 축 | 영향 |
|--------|------|
| Performance | Vth가 낮을수록 gate overdrive(VDD - Vth) 증가 → switching speed 향상. critical path에 ULVT~LVT 배치 |
| Power (s_power) | Vth가 낮을수록 sub-threshold leakage가 exponential 증가. 이론적으로 subthreshold slope(~60mV/decade) 기준 Vth 60mV 감소 시 leakage 10배 증가. FinFET/GAA에서는 subthreshold slope이 개선되어 실제 비율은 이보다 완만할 수 있으나, ULVT는 HVT 대비 수백 배 이상 leakage 차이가 날 수 있다. 업계 경험에 따르면 HVT 사용 시 LVT 대비 leakage를 최대 80% 줄일 수 있으나 timing에 약 20% 영향 |
| Power (d_power) | low-Vth(ULVT~LVT)가 약간 높은 편이나, 빠른 transition으로 short-circuit current 감소 효과도 있어 복합적 |
| Area | 직접 영향 없으나, high-Vth(RVT~HVT)는 느리므로 timing 확보를 위해 높은 drive strength 필요 → 면적 증가 가능. low-Vth(ULVT~LVT)는 작은 셀로도 timing 충족 가능 |

- Vth는 온도와 VDD에 따라 변한다. 고온에서 Vth 하락 → leakage 심화 (s_power 온도 의존성의 근본 원인). VDD 상승 → DIBL로 실효 Vth 하락 → leakage 증가.
- Temperature Inversion은 Vth의 온도 의존성에서 비롯된다. 저온에서 Vth 상승이 mobility 개선을 압도하는 현상. high-Vth(RVT~HVT) 셀에서 가장 두드러지고, low-Vth(ULVT~LVT) 셀에서는 거의 나타나지 않는다.
- 근거: Intel 22nm FinFET IEDM 2012에서 multi-Vth(HP/SP/LP) IV 곡선이 공개되었으며, IEDM 2018에서 IBM이 7nm 공정의 multi-Vt 기법(work function 기반)을 발표하였다.

---

## 6. 조건별 상관관계

### 6.1 Temperature × PPA

#### s_power — 온도 의존성 매우 높음 (exponential)
- 누설전류는 온도에 exponential하게 증가한다. 이는 sub-threshold leakage 수식에서 Vth가 온도에 따라 선형 감소하고, leakage가 exp(-Vth/nkT)에 비례하기 때문이다 (Roy et al., Proc. IEEE, 2003).
- 약 10°C 상승 시 leakage가 대략 1.5~2배 증가하는 것으로 알려져 있으나, 실제 비율은 공정 노드, Vth, 온도 구간에 따라 달라진다.
- 동일 칩이라도 -25°C vs 125°C에서 s_power가 수십 배 차이날 수 있다.
- FinFET에서는 이 온도-leakage positive feedback이 thermal runaway를 유발할 수 있다. Thermal runaway란 leakage 증가 → 발열 → 온도 상승 → leakage 추가 증가의 악순환이 제어 불가능한 수준에 도달하는 현상으로, 칩 손상으로 이어질 수 있다 (IEEE 연구에서 28nm FinFET 대상 보고).

#### d_power — 온도 의존성 낮음 (약한 양의 상관)
- 온도 상승 → carrier mobility 감소 → transition time 증가 → short-circuit current 미세 증가.
- s_power 대비 민감도가 훨씬 낮아 일반적 비교에서는 무시 가능.

#### iddq_na — s_power와 동일한 exponential 온도 의존성
- leakage 기반 지표이므로 s_power와 같은 온도 의존성을 가진다.
- IDDQ 기반 불량 판정 시 반드시 동일 온도 조건의 threshold을 적용해야 한다.

#### freq_ghz — Temperature Inversion 주의
- 전통적 이해 (구형 공정, >65nm): 고온 → carrier mobility 감소 → 속도 저하. worst-case performance = high temperature.
- 미세공정 (65nm 이하): Temperature Inversion 발생. 저온에서 Vth 상승 효과가 mobility 개선을 압도하여, 오히려 저온에서 freq_ghz가 낮아지는 역전 현상. 45nm에서 VDD=0.8V 조건으로 관측되었으며, 7nm 이하에서는 거의 항상 발생.
- Vth 종류에 따라 민감도가 다르다: HVT/RVT 셀은 temperature inversion 효과가 가장 크고, MVT/LVT는 중간, VLVT/SLVT/ULVT는 거의 영향을 받지 않는다. 이는 gate overdrive(VDD - Vth) 크기 차이에 기인한다.
- freq_ghz의 worst-case corner가 high temp인지 low temp인지는 공정 노드와 Vth 종류에 따라 다르다. "고온 = worst performance"로 단순 가정하지 않는다.
- 근거: IEDM/VLSI 학회 발표 및 다수의 IEEE 논문에서 sub-65nm 공정의 temperature inversion이 보고됨.

#### acceff_ff / acreff_kohm — 온도에 따른 변화
- acreff_kohm(Reff): 온도 상승 시 carrier mobility 감소로 Reff가 증가한다. 이는 freq_ghz 저하의 직접 원인이다 (temperature inversion이 없는 경우).
- acceff_ff(Ceff): 온도에 대한 직접 의존성은 Reff보다 약하다. 다만 junction capacitance가 온도에 따라 미세하게 변하고, Vth 변화로 인한 inversion charge 변동이 채널 커패시턴스에 영향을 줄 수 있다.
- d_energy: Ceff가 온도에 비교적 안정적이므로 d_energy = Ceff × VDD²도 온도에 큰 변화를 보이지 않는다. 온도에 따른 전력 변화는 주로 s_power(leakage)가 지배한다.

### 6.2 VDD × PPA

#### d_power — V² 비례 (가장 직접적)
- P_dynamic = C · V² · f 에서 VDD가 제곱으로 기여한다.
- VDD 10% 증가 시 d_power 약 21% 증가. 전력 절감의 가장 효과적인 수단이 VDD 저감이다.

#### s_power — exponential 관계
- VDD 상승 → DIBL(Drain-Induced Barrier Lowering) 효과로 실효 Vth 감소 → sub-threshold leakage exponential 증가.
- Gate leakage도 oxide 양단 전압 증가로 커진다.

#### iddq_na — s_power와 동일 방향
- VDD가 올라가면 leakage 증가로 iddq도 함께 상승한다.

#### freq_ghz — 양의 상관 (비선형)
- VDD 상승 → gate overdrive (VDD - Vth) 증가 → switching speed 향상.
- VDD가 Vth에 근접할수록 성능이 급격히 저하되는 비선형 특성을 가진다.

#### Area — 간접 영향
- VDD 자체가 면적을 변경하지 않으나, 낮은 VDD에서 noise margin 확보를 위해 트랜지스터/회로 추가가 필요할 수 있다.

#### acceff_ff / acreff_kohm — VDD에 따른 변화
- acreff_kohm(Reff): VDD 상승 시 gate overdrive 증가로 채널 저항이 감소하여 Reff가 낮아진다. 이것이 freq_ghz 향상의 직접 메커니즘이다. CFET vs nanosheet 비교 연구(IEEE JEDS)에서 Ceff, Reff vs VDD 특성이 보고되었다.
- acceff_ff(Ceff): VDD에 대해 약한 의존성을 가진다. VDD가 높아지면 inversion charge 증가로 채널 커패시턴스가 약간 증가하지만, Reff 변화에 비해 작은 편이다.
- d_energy = Ceff × VDD²: Ceff가 비교적 안정적이므로, d_energy는 주로 VDD²에 의해 결정된다. VDD를 10% 낮추면 d_energy가 약 19% 감소하여 에너지 효율 개선의 가장 효과적인 수단이다.

---

## 7. IDDQ 테스팅 방법론

### 7.1 원리

IDDQ(IDD Quiescent) 테스팅은 대기상태(Quiescent state)에서의 공급전류(IDD)를 측정하여 제조 결함을 검출하는 회로 테스팅 방법론이다.

정상 CMOS 회로의 기본 특성: 신호 전환(switching) 시에는 순간적으로 전류가 흐르지만, 전환이 완료되고 과도 현상이 사라진 정적 상태에서는 이상적으로 전류가 0에 가까워야 한다. 정상 칩의 quiescent current는 수 nA 수준이다.

결함이 있는 경우: gate-oxide short, metal line 간 bridging, transistor stuck-on 등 공정 결함이 있으면 VDD에서 GND로의 비정상적 전도 경로가 형성되어, 정적 상태에서도 정상 대비 3~5 자릿수(orders of magnitude) 높은 전류가 흐른다.

### 7.2 결함과 기능의 관계

- 결함이 있어도 특정 입력 조건에서는 기능이 정상 동작할 수 있다. 예를 들어, 특정 신호선이 VDD에 short되어 있더라도 해당 선을 '1'로 구동하는 입력에서는 추가 전류가 흐르지 않는다.
- 그러나 다른 입력 조건에서는 비정상 전류가 발생하며, 전력 소비가 증가한다.
- 전력 소비가 과도하게 커지면 전압 강하(IR drop)나 발열로 인해 기능 오류로 이어질 수 있다.
- 따라서 IDDQ 테스팅은 기능 테스트(functional test)를 대체하는 것이 아니라, 기능 테스트가 놓칠 수 있는 결함을 보완적으로 검출하는 수단이다.

### 7.3 검출 가능 결함 유형

- Bridging fault (신호선 간 단락)
- Gate-oxide short (게이트 산화막 결함)
- Transistor stuck-on fault
- Line/drain/source break fault (단선으로 인한 floating node)

### 7.4 미세공정에서의 한계

공정이 미세화되면서 정상 트랜지스터의 leakage current 자체가 높아지고, 칩 내 트랜지스터 수가 증가하여 총 background leakage가 커진다. 이로 인해 결함에 의한 비정상 전류와 자연적 leakage를 구별하기 어려워지는 한계가 있다. 이를 극복하기 위해 power gating(블록별 전원 차단)을 통한 개별 블록 테스트, background current 보상 기법 등이 사용된다.

### 7.5 pave-agent에서의 iddq_na 해석 지침

- iddq_na는 이중 성격을 가진다. 맥락에 따라 해석 방식을 구분한다:
  - **전력 특성 관점**: 정상 범위 내의 iddq_na 값은 해당 칩의 leakage 수준을 반영하며 s_power와 직접 상관한다. "power가 높은 칩", "leakage 비교" 등의 쿼리에서는 iddq_na를 s_power와 함께 전력 지표로 활용할 수 있다.
  - **설계 주의 관점 (v8)**: 두 PDK 간 비교에서 동일 조건 대비 iddq_na 변화율이 비정상적으로 큰 경우, 해당 파라미터 영역에서 설계 시 마진 확보가 필요함을 의미한다. 이는 제조 결함이 아니라 모델링이 정상인 상태에서 나타나는 특성이다.
  - **품질/결함 관점**: 동일 PDK 내에서 통계적으로 비정상적으로 높은 iddq_na는 제조 결함(bridging, gate-oxide short 등)을 의미할 수 있다.
- 정상/비정상의 경계 판단은 동일 조건(동일 온도, 동일 VDD, 동일 셀 타입) 내에서의 분포를 기준으로 한다.
- IDDQ 데이터의 온도·VDD 의존성은 s_power와 동일한 방향(exponential)이므로, 비교 시 반드시 동일 측정 조건을 확인한다.

---

## 8. 쿼리 처리 시 적용 규칙

### 규칙 1: 동일 조건 비교 강제

서로 다른 칩/버전/셀의 PPA 값을 비교할 때, 반드시 동일한 PVT corner(Process-Voltage-Temperature) 조건에서 측정된 데이터를 사용한다.
- 조건이 다른 데이터가 섞여 있으면, 사용자에게 조건 차이를 고지하고 필터링을 권장한다.
- 특히 s_power, iddq_na는 온도·VDD 조건 불일치 시 비교 자체가 무의미하다.

### 규칙 2: PVT Corner 조합의 Worst-case 매핑

| 분석 목적 | Worst-case Corner |
|-----------|-------------------|
| 최대 전력 소비 (power) | High Temp, Slow Process, High Voltage |
| 최저 성능 (performance) | SSPG corner 기준. Temperature Inversion 여부에 따라 worst-case 온도가 달라짐 (섹션 6.1 참조) |
| Leakage 상한 | High Temp, High Voltage |
| IDDQ 불량 판정 | 측정 온도·VDD 조건의 threshold 기준 적용 |

pave 시스템에서 성능 worst-case 분석 시 SSPG corner를 기본으로 사용한다. 사용자가 "worst-case 성능"을 요청하면 SSPG 데이터를 우선 조회한다.

### 규칙 3: iddq_na 맥락별 해석

- "전력 관련" 쿼리 → d_power, s_power를 주 지표로 사용. iddq_na는 leakage 수준의 보조 지표로 함께 제시할 수 있다 (iddq_na와 s_power는 직접 상관).
- "이상치 탐지" 쿼리 (v8: intent=anomaly) → 두 PDK 간 전체 지표의 변화율을 분석. iddq_na는 s_power와 함께 leakage 변화의 지표로 사용하되, 변화율이 비정상적으로 큰 영역을 **설계 시 주의가 필요한 영역**으로 식별한다. 이는 제조 결함 탐지가 아니라 정상 데이터 내의 특성 변화 분석이다.
- "전체 PPA 요약" 쿼리 → d_power, s_power는 Power 축에, iddq_na는 "Leakage/품질" 항목으로 별도 표시하여 이중 성격을 반영.

### 규칙 4: Pareto-optimal 안내

사용자가 상충 조건을 요청할 경우 (예: "성능 높고 전력 낮은 칩"), PPA trade-off 특성을 설명하고 pareto frontier 관점의 결과를 제공한다.

### 규칙 5: 설계 파라미터 간 연쇄 관계 인식

drive strength, nanosheet width, cell height, Vth는 서로 연쇄적으로 영향을 미친다. 하나의 파라미터 변화가 다른 파라미터의 실효 영향을 변경할 수 있음을 인지하고, 단일 파라미터만으로 PPA를 판단하지 않는다.
- 예: cell height 축소 → nanosheet width 상한 제한 → drive strength 상한 저하 → performance 영향.
- 예: Vth 낮춤 → 성능 향상 + leakage 급증 → drive strength를 낮춰 area/power 절감 가능.

### 규칙 6: 셀 타입 간 비교 시 동일 셀 타입 강제

INV, ND2, NR2 등 셀 타입이 다르면 PPA 값의 절대적 비교가 무의미하다. 셀 타입 간 비교가 요청되면 동일 drive strength·동일 Vth 조건을 명시하고, 구조적 차이(직렬/병렬 트랜지스터 배치)에 의한 본질적 PPA 차이를 설명한다.

### 규칙 7: PDK 버전 비교 시 조건 명확화

PPA 데이터 비교에는 두 가지 경우가 있다:
- **동일 버전 내 비교** (예: 같은 PDK에서 Vth 간, Drive Strength 간 비교): PDK 버전이 일치하는지 확인한다. 버전이 다르면 비교 자체가 의미 없을 수 있으므로 사용자에게 고지한다.
- **버전 간 비교** (예: "이전 PDK 대비 개선치", "v1.2 vs v1.3"): 실무에서 자주 발생하는 패턴이다. 이 경우 동일 셀 타입 · 동일 Vth · 동일 Drive Strength · 동일 PVT corner 조건을 맞추고, PDK 버전만 다른 데이터를 비교하여 변화율(%)을 제시한다.

### 규칙 8: PDK 버전 특정 및 Golden 기본 선택

#### 8.1 PDK 버전 특정에 필요한 키

하나의 PDK 버전을 특정하려면 다음 6개 키가 모두 필요하다:

| 키 | 설명 | 비고 |
|----|------|------|
| `project` 또는 `project_name` | 과제 코드 또는 별명. DB에 두 컬럼으로 존재 | 사용자는 둘 중 아무거나 사용. 에이전트는 양쪽 모두 매칭 시도 |
| `mask` | 마스크 | 보통 project와 함께 언급됨 |
| `dk_gds` | DK GDS | 사용자가 처음부터 언급하는 경우는 드묾 |
| `hspice` | HSPICE 버전 | 미명시 시 Golden으로 자동 선택 |
| `lvs` | LVS 버전 | 미명시 시 Golden으로 자동 선택 |
| `pex` | PEX 버전 | 미명시 시 Golden으로 자동 선택 |

참고: `process`(공정명)는 DB 키가 아니지만 사용자가 가장 자주 대화 시작점으로 사용한다. process → project는 1:N 관계이므로 process만으로는 project를 특정할 수 없다.

#### 8.2 단계적 축소(Narrowing) 흐름

사용자가 6개 키를 모두 명시하는 경우는 드물다. 에이전트는 사용자가 제공한 정보에서 출발하여, 단계적으로 축소한다.

```
사용자 입력
  │
  ├── [Step 1] Process 또는 Project 식별
  │   ├── Process(공정명)만 언급
  │   │   → DB에서 해당 Process의 Project 목록 조회
  │   │   ├── 1개 → 자동 선택
  │   │   └── N개 → clarification: "해당 공정에 프로젝트가 A, B, C가 있습니다. 어떤 프로젝트를 확인할까요?"
  │   ├── Project(또는 Project Name) 언급
  │   │   → project / project_name 양쪽 컬럼 매칭 시도
  │   └── 둘 다 없음
  │       → clarification: "어떤 공정 또는 프로젝트의 데이터를 확인할까요?"
  │
  ├── [Step 2] Mask 확인
  │   ├── 사용자가 명시 → 확정
  │   ├── Project에 Mask가 1개 → 자동 선택
  │   └── Project에 Mask가 N개 → clarification: "해당 프로젝트에 Mask가 X, Y가 있습니다."
  │
  ├── [Step 3] DK_GDS 확인
  │   ├── 사용자가 명시 → 확정
  │   ├── Project + Mask에 DK_GDS가 1개 → 자동 선택
  │   └── DK_GDS가 N개 → clarification으로 선택지 제시
  │
  └── [Step 4] HSPICE / LVS / PEX 확인
      ├── 사용자가 명시 → 해당 버전 사용
      └── 미명시 → Golden(IS_GOLDEN=1) 자동 선택
```

#### 8.3 Golden 기본 선택

- Project, Mask, DK_GDS가 확정되었으나 HSPICE/LVS/PEX가 명시되지 않은 경우, `IS_GOLDEN=1`인 Golden PDK 버전을 기본으로 사용한다.
- Golden PDK로 조회한 경우, 응답 시 해당 Golden 버전의 HSPICE, LVS, PEX 버전을 함께 안내한다. 사용자가 데이터에 의문을 가질 수 있으므로 어떤 버전 기준인지 투명하게 제공한다.
- 사용자가 명시적으로 특정 버전을 지정한 경우에는 Golden 여부와 관계없이 해당 버전을 사용한다.
- 모든 Project/Mask/DK_GDS 조합에 Golden이 지정되어 있다.

#### 8.4 버전 간 비교 시

"A공정 대비 B공정", "v1.0 대비 v2.0" 같은 비교 요청 시:
- 비교 대상 각각에 대해 Step 1~4를 수행하여 PDK 버전을 특정한다.
- 양쪽 모두 동일한 비교 조건(셀 타입, Vth, Drive Strength, PVT corner)을 맞춘다.
- 한쪽만 버전이 특정되고 다른 쪽이 불명확한 경우, 불명확한 쪽에 대해 clarification을 요청한다.

### 규칙 9: AVG(평균) 처리

사용자가 drive_strength 또는 cell(셀 타입)을 "AVG"로 선택하는 경우, 개별 데이터를 먼저 조회한 뒤 평균을 산출한다.

| 조건 | 조회 대상 | 평균 계산 |
|------|-----------|-----------|
| drive_strength = AVG | D1, D4 | 두 drive strength 데이터의 평균 |
| cell = AVG | INV, ND2, NR2 | 세 셀 타입 데이터의 평균 |
| 둘 다 AVG | D1×INV, D1×ND2, D1×NR2, D4×INV, D4×ND2, D4×NR2 | 6개 조합 데이터의 평균 |

- AVG는 DB에 별도로 저장된 값이 아니라, 에이전트가 개별 데이터를 조회하여 계산하는 값이다.
- **중요: SQL에서 AVG() 등 집계 함수를 사용하지 않는다.** 데이터 정합성을 위해 개별 행을 모두 조회(SELECT)한 뒤, 애플리케이션 레벨에서 평균을 계산한다. 이렇게 하면 누락 데이터나 이상치를 사전에 확인할 수 있다.
- AVG 계산 시 나머지 조건(Vth, PVT corner, PDK 버전 등)은 모두 동일하게 고정한다.
- 사용자가 "평균", "전체 평균", "AVG" 등으로 표현하면 이 규칙을 적용한다.
- 응답 시 AVG 값과 함께 개별 구성 데이터도 제시하면 사용자가 편차를 확인할 수 있다.

---

## 9. 자주 묻는 쿼리 패턴 및 에이전트 대응 가이드

> 사용자는 PVT 조건과 파라미터를 모두 명시하지 않고 짧게 질문하는 경우가 많다.
> 에이전트는 아래 패턴을 인식하여 암묵적 조건을 추론하거나, 필요 시 clarification을 요청한다.

### 9.1 PDK 버전 간 비교 (회귀/개선 분석)

- 예시 질문: "새 PDK에서 leakage 나빠졌어?", "v1.2 vs v1.3 비교해줘"
- 사용자 의도: PDK 업데이트로 인한 PPA 변화(회귀 또는 개선)를 확인하고 싶다.
- 에이전트 대응: 동일 셀 타입 · 동일 drive strength · 동일 Vth · 동일 PVT corner 조건에서 두 PDK 버전의 값을 비교한다. 변화율(%)을 함께 제공하고, 유의미한 변화가 있는 파라미터를 하이라이트한다.
- 추천 시각화:
  - **Grouped Bar**: 파라미터별(freq, d_power, s_power, iddq) 두 버전 값을 나란히 비교
  - **변화율 Bar**: 파라미터별 변화율(%)을 bar로 표시. 개선(음수)은 녹색, 회귀(양수)는 적색
  - **Line (버전 히스토리)**: 3개 이상 버전 비교 시, x축 버전 · y축 파라미터 값의 추이 차트

#### 실전 예시 A: 공정명으로 비교 요청 (조건 불완전)

**사용자 질문**: "SF2 대비 SF2P 성능 어때?"

**에이전트 사고 흐름**:
1. SF2 → Project: S5E9965 (Thetis). Mask가 EVT0, EVT1 두 개 → Mask clarification 필요
2. SF2P → Project: S5E9975 (Ulysses). Mask가 EVT0, EVT1 두 개 → Mask clarification 필요
3. "성능"이라는 표현 → 주 지표는 `freq_ghz`, 보조로 `d_power`, `s_power` 포함
4. PVT corner, Vth, cell, drive_strength 미명시 → 기본값 적용 대상

**에이전트 동작**:
- clarification 요청: "SF2(Thetis)에 EVT0과 EVT1이 있고, SF2P(Ulysses)에도 EVT0과 EVT1이 있습니다. 어떤 Mask 버전끼리 비교할까요?"
- 사용자가 Mask 선택 후 → DK_GDS 확인 (Ulysses EVT0은 DK_GDS가 2개이므로 추가 clarification 가능)
- HSPICE/LVS/PEX 미명시 → Golden(IS_GOLDEN=1) 자동 선택
- 기본값 적용: TT corner, 25°C, nominal VDD, CELL AVG(INV/ND2/NR2 평균), DS AVG(D1/D4 평균)
- 양쪽 동일 조건에서 freq_ghz, d_power, s_power 비교 + 변화율(%) 제공

#### 실전 예시 B: 같은 프로젝트 내 DK_GDS 비교

**사용자 질문**: "Ulysses EVT0 최신 DK랑 이전 DK 비교해줘"

**에이전트 사고 흐름**:
1. Ulysses EVT0 → Project: S5E9975, Mask: EVT0
2. DK_GDS가 "Thetis EVT1"과 "Ulysses EVT0" 두 개 존재
3. "최신 DK"와 "이전 DK" → DK_GDS 간 비교 의도. "Ulysses EVT0"이 최신, "Thetis EVT1"이 이전(이전 공정 DK 기반)일 가능성 높음
4. 어떤 지표를 볼지 미명시 → 전체 PPA 요약으로 대응

**에이전트 동작**:
- DK_GDS 목록을 제시: "Ulysses EVT0에 DK_GDS가 2개 있습니다: ① Thetis EVT1 ② Ulysses EVT0. ①이 이전 DK, ②가 최신 DK가 맞으신가요?"
- 사용자 확인 후 → 양쪽 Golden 기준으로 전 지표(freq_ghz, d_power, d_energy, s_power, iddq_na) 비교
- 기본값 적용: TT, 25°C, nominal VDD, CELL AVG, DS AVG

### 9.2 Vth 간 PPA 비교

- 예시 질문: "LVT랑 RVT 차이 얼마나 돼?", "HVT로 바꾸면 leakage 얼마나 줄어?", "ULVT 쓰면 성능 얼마나 올라?"
- 사용자 의도: Vth 변경에 따른 speed-leakage trade-off를 수치로 확인하고 싶다.
- 에이전트 대응: 동일 셀 타입 · 동일 drive strength · 동일 PVT corner에서 Vth별 freq_ghz, s_power, d_power, acreff_kohm을 비교한다. Vth를 낮추면 Reff 감소로 speed↑이지만 leakage↑, 높이면 Reff 증가로 speed↓이지만 leakage↓ 라는 trade-off를 수치와 함께 제시한다.
- 추천 시각화:
  - **Grouped Bar**: Vth별(ULVT/SLVT/VLVT/LVT/MVT/RVT/HVT) 파라미터 값 나란히 비교
  - **Scatter (trade-off)**: x축 freq_ghz · y축 s_power, 각 점에 Vth 라벨. speed-leakage trade-off를 시각적으로 표현

#### 실전 예시: 조건 최소한으로 던지는 질문

**사용자 질문**: "LVT랑 HVT 차이 얼마나 돼?"

**에이전트 사고 흐름**:
1. 어떤 공정/프로젝트인지 전혀 없음 → clarification 필수
2. "차이" → 비교 의도. Vth 간 비교이므로 freq_ghz(speed)와 s_power(leakage) trade-off가 핵심
3. cell, drive_strength, PVT corner 미명시 → 기본값 적용 대상

**에이전트 동작**:
- clarification: "어떤 공정(또는 프로젝트)에서 확인할까요?"
- 사용자가 공정 지정 후 → 규칙 8의 단계적 축소 진행
- 기본값 적용: TT, 25°C, nominal VDD, CELL AVG, DS AVG
- LVT vs HVT의 freq_ghz, s_power, d_power, iddq_na 비교 + 변화율
- trade-off 설명: "LVT는 HVT 대비 freq가 X% 높지만, leakage가 Y배 높습니다"

### 9.3 Worst-case Corner 탐색

- 예시 질문: "leakage 최악 조건이 뭐야?", "가장 느린 corner 알려줘"
- 사용자 의도: spec 마진 확보를 위해 worst-case PVT corner의 PPA 값을 확인하고 싶다.
- 에이전트 대응: 규칙 2의 worst-case 매핑을 참조한다. Leakage worst = high temp + high VDD. Performance worst = SSPG corner 기준으로 조회하되, temperature inversion 여부를 고려한다. 해당 corner의 실측 데이터를 제공한다.
- 추천 시각화:
  - **Heatmap**: x축 Temperature · y축 VDD, 셀 값으로 s_power 또는 freq_ghz. worst-case corner가 시각적으로 즉시 식별됨
  - **Bar (corner 비교)**: 주요 PVT corner(FF/TT/SS × 온도)별 파라미터 값 비교

#### 실전 예시: 모호한 worst-case 질문

**사용자 질문**: "Solomon leakage 최악이 어느 조건이야?"

**에이전트 사고 흐름**:
1. Solomon → Project: S5E9955, Mask: EVT1 (1개 → 자동 선택), DK_GDS: Solomon EVT1 (1개 → 자동 선택)
2. "leakage 최악" → 규칙 2 매핑: High Temp + High VDD가 leakage worst-case
3. HSPICE/LVS/PEX 미명시 → Golden 자동 선택
4. Solomon은 전부 1개씩이므로 clarification 불필요 → 바로 조회 가능

**에이전트 동작**:
- clarification 없이 바로 진행 (모든 키가 자동 특정 가능)
- Golden 버전 기준으로 s_power, iddq_na를 Temperature × VDD 매트릭스로 조회
- 기본값: CELL AVG, DS AVG, Vth는 사용자가 관심 있는 Vth를 확인 (미지정 시 LVT 기본 또는 전 Vth 제시)
- worst-case 조건(가장 높은 s_power를 보이는 Temp/VDD 조합) 하이라이트
- Heatmap 시각화 추천

### 9.4 Drive Strength 간 비교

- 예시 질문: "D1이랑 D4 power 차이?", "D2로 충분할까?"
- 사용자 의도: timing 요구를 만족하면서 power/area를 최소화할 수 있는 drive strength를 선택하고 싶다.
- 에이전트 대응: 동일 셀 타입 · 동일 Vth · 동일 PVT corner에서 drive strength별 freq_ghz, d_power, d_energy, acceff_ff, acreff_kohm, s_power를 비교한다. 대략 D가 N배이면 power/area도 약 N배라는 경험칙을 참고하되 실측 데이터 기반으로 답변한다.
- 추천 시각화:
  - **Grouped Bar**: Drive Strength별 파라미터 값 비교
  - **Scatter (trade-off)**: x축 freq_ghz · y축 d_power, 각 점에 D1/D2/D3/D4 라벨. 성능-전력 trade-off 시각화

#### 실전 예시: 짧고 직접적인 질문

**사용자 질문**: "D1이랑 D4 power 몇 배야?"

**에이전트 사고 흐름**:
1. 공정/프로젝트 미지정 → clarification 필요
2. "power" → d_power와 s_power 모두 해당. drive strength 비교에서는 d_power가 주 관심이지만 s_power도 함께 제시
3. "몇 배" → 비율 정보를 원함. 실측 데이터 기반 비율 + 경험칙(약 4배) 비교
4. cell, Vth, PVT corner 미명시 → 기본값 적용

**에이전트 동작**:
- clarification: "어떤 공정(또는 프로젝트)에서 확인할까요?"
- 공정 확정 후 → 규칙 8 진행
- 기본값: TT, 25°C, nominal VDD, CELL AVG, Vth는 LVT 기본 (미지정 시)
- D1 vs D4의 d_power, s_power, freq_ghz 비교
- "D4는 D1 대비 d_power가 약 X배, s_power가 약 Y배입니다. 경험칙상 약 4배인데, 실측은 [값]입니다"

### 9.5 특정 셀의 전체 PPA 프로파일

- 예시 질문: "INV D1 LVT 데이터 보여줘", "ND2 스펙 좀"
- 사용자 의도: 특정 셀의 PPA 값을 한눈에 보고 싶다.
- 에이전트 대응: 해당 셀의 전 PVT corner 또는 대표 corner(TT 기준)에서의 freq_ghz, d_power, d_energy, acceff_ff, acreff_kohm, s_power, iddq_na를 테이블로 제공한다. 조건이 명시되지 않으면 TT corner를 기본으로 사용하고 다른 corner도 필요한지 확인한다.
- 추천 시각화:
  - **Table**: 기본 응답. PVT corner × 파라미터 매트릭스
  - **Radar Chart**: 단일 셀의 PPA 밸런스를 한눈에 (각 축: freq, d_power, s_power, iddq, area를 정규화)
  - **Heatmap**: 복수 PVT corner 데이터가 있을 경우, corner × 파라미터 히트맵

#### 실전 예시 A: 프로젝트명(별명)으로 조회

**사용자 질문**: "Thetis INV D1 데이터 보여줘"

**에이전트 사고 흐름**:
1. Thetis → project_name 매칭 → Project: S5E9965 (SF2)
2. Mask가 EVT0, EVT1 두 개 → clarification 필요
3. CELL=INV, DS=D1 명시 → AVG 아님, 개별 셀 조회
4. Vth, PVT corner 미명시 → Vth는 전체 Vth를 보여줄지, 기본 LVT만 줄지 판단 필요

**에이전트 동작**:
- clarification: "Thetis에 EVT0과 EVT1이 있습니다. 어느 버전을 확인할까요?"
- Mask 확정 후 → DK_GDS 자동 (각 Mask에 DK_GDS 1개), Golden 자동
- 기본값: TT, 25°C, nominal VDD
- INV D1의 전 Vth(ULVT~HVT) 데이터를 테이블로 제시 (해당 공정에서 데이터가 있는 Vth만)
- 전 지표(freq_ghz, d_power, d_energy, acceff_ff, acreff_kohm, s_power, iddq_na) 포함

#### 실전 예시 B: 극도로 짧은 질문

**사용자 질문**: "leakage 좀 보여줘"

**에이전트 사고 흐름**:
1. 공정, 프로젝트, 셀, 조건 모두 없음 → 여러 단계 clarification 필요
2. "leakage" → s_power와 iddq_na가 관련 지표

**에이전트 동작**:
- clarification: "어떤 공정(또는 프로젝트)의 leakage를 확인할까요?"
- 이후 규칙 8의 단계적 축소를 순차 진행
- 최종적으로 s_power, iddq_na를 기본 조건(TT, 25°C, nominal VDD, CELL AVG, DS AVG)으로 제시

### 9.6 이상치 감지 — 설계 주의 영역 식별 (v8 재정의)

- 예시 질문: "이상치 찾아줘", "주의할 수치 있어?", "leakage 튀는 거 없어?"
- 사용자 의도: 두 PDK 간 비교에서 **설계 시 주의가 필요한 수치**를 선제적으로 파악하고 싶다.
- **v8 정의**: 모델링이 정상이라는 전제 하에, 파라미터 공간 내 비선형적 급변 구간, 예상 추세에서 벗어나는 데이터 포인트, 설계 시 마진 확보가 필요한 영역을 식별한다. 이것은 **제조 결함 탐지가 아니다**.

#### 탐지 방법

1. **데이터 수집**: 두 PDK의 전체 PPA 데이터 bulk pull (~13K행 × 2)
2. **조건 매칭**: 동일 CELL/DS/VTH/CORNER/TEMP/VDD 쌍을 매칭
3. **변화율 계산**: 모든 측정 지표(FREQ_GHZ, D_POWER, S_POWER, IDDQ_NA, ACCEFF_FF, ACREFF_KOHM)에 대해 변화율(Δ%) 산출
4. **이상치 탐지**: 지표별 변화율 분포에서 통계적 이상치 식별
   - FREQ_GHZ, D_POWER, ACCEFF_FF, ACREFF_KOHM: z-score 기반 (|z| > 2)
   - S_POWER, IDDQ_NA: log 변환 후 z-score (exponential 분포 특성 고려)
5. **클러스터링**: 이상치가 어떤 파라미터 영역에 집중되는지 그룹핑
   - 예: "VTH=HVT, TEMP=125°C 영역에서 S_POWER 변화율 이상치 8건 집중"
6. **원인 추정**: 파라미터 간 상관관계 + 도메인 지식 기반으로 LLM이 클러스터별 추정 원인 생성

#### 결과 구성

- 이상치 목록: 조건 조합, 지표, 변화율, z-score
- 클러스터 요약: 영역, 건수, 관련 지표
- 추정 원인: 도메인 지식 기반 설명 (예: "HVT 고온 영역에서 Temperature Inversion 효과가 두드러져 freq_ghz 변화가 비선형적으로 나타남")

#### 추천 시각화

- **Scatter (변화율 분포)**: x축 FREQ_GHZ Δ% · y축 S_POWER Δ%, 이상치를 색상/크기로 강조. 2σ 경계선 표시
- **Heatmap (파라미터 공간)**: x축 VTH · y축 TEMP, 셀 값으로 변화율. 이상치 집중 영역이 시각적으로 즉시 식별됨
- **Bar (클러스터별)**: 클러스터별 이상치 건수 + 관련 지표 분포

#### 실전 예시

**사용자 질문**: "Vanguard에서 주의할 수치 있어?"

**에이전트 동작** (v8: intent=anomaly):
1. intent_parser: intent="anomaly", entities={project_names: ["Vanguard"]}
2. pdk_resolver: Vanguard(현재) + 이전 버전 PDK 특정. DK_GDS 2개면 ask_user
3. query_builder: bulk SQL ×2 (WHERE 조건 최소화)
4. data_executor: ~13K행 ×2 수집. SSE: "데이터 수집 완료"
5. analyzer: 조건 매칭 → 변화율 → z-score 탐지 → 클러스터링. SSE: "이상치 17건 탐지"
6. interpreter: 클러스터별 원인 추정 (도메인 지식 섹션 6.1, 6.2, 5.4 로딩). SSE: "원인 분석 중"
7. visualizer: scatter + heatmap
8. response_formatter: 한국어 정제 + 이상치 리포트 포맷팅

### 9.7 온도/전압 민감도 분석

- 예시 질문: "온도 올리면 leakage 얼마나 변해?", "VDD 낮추면 성능 얼마나 떨어져?"
- 사용자 의도: 특정 파라미터의 온도 또는 VDD에 대한 민감도를 파악하고 싶다.
- 에이전트 대응: 동일 셀에서 온도 또는 VDD만 다른 복수 데이터 포인트를 조회하여 변화 추이를 제공한다. 섹션 6의 상관관계 지식을 기반으로 변화의 물리적 원인도 함께 설명한다.
- 추천 시각화:
  - **Line (온도 민감도)**: x축 Temperature · y축 s_power/iddq_na. exponential 증가 추이 시각화. 또한 acreff_kohm의 온도별 변화로 Reff 증가 추이도 확인 가능
  - **Line (VDD 민감도)**: x축 VDD · y축 freq_ghz. 비선형 성능 변화 시각화. acreff_kohm vs VDD로 Reff 감소 추이, d_energy vs VDD로 에너지 효율도 함께 확인 가능
  - **Multi-line**: 동일 차트에 Vth별(ULVT~HVT) 라인을 겹쳐서 민감도 차이 비교

#### 실전 예시: 일상적 민감도 질문

**사용자 질문**: "온도 올리면 leakage 얼마나 변해?"

**에이전트 사고 흐름**:
1. 공정 미지정 → clarification 필요
2. "온도 올리면 leakage" → s_power 또는 iddq_na의 온도 민감도 분석
3. 어떤 온도 범위인지 미명시 → DB에 있는 전 온도 포인트를 사용

**에이전트 동작**:
- clarification: "어떤 공정(또는 프로젝트)에서 확인할까요?"
- 공정 확정 후 → 규칙 8 진행
- 기본값: TT corner, nominal VDD, CELL AVG, DS AVG, LVT 기본
- 가용한 전 온도 포인트에서 s_power, iddq_na 조회
- Line 차트로 온도별 추이 시각화
- 물리적 설명: "s_power는 온도에 exponential하게 증가합니다. 약 10°C당 1.5~2배 증가하는 경향이 있습니다"

### 9.8 Nanosheet Width / Cell Height 영향 분석

- 예시 질문: "nanosheet 넓히면 성능 얼마나 올라?", "CH138이랑 CH168 차이?"
- 사용자 의도: 구조적 설계 파라미터 변경에 따른 PPA 영향을 확인하고 싶다.
- 에이전트 대응: 동일 셀 타입 · 동일 Vth · 동일 PVT corner에서 해당 파라미터만 다른 데이터를 비교한다. 섹션 5의 연쇄 관계(cell height → nanosheet width → drive strength → PPA)를 고려하여 설명한다.
- 추천 시각화:
  - **Grouped Bar**: Nanosheet Width별(N1/N2/N3) 또는 Cell Height별(CH138/CH168/CH200) 파라미터 비교
  - **Scatter (trade-off)**: x축 freq_ghz · y축 d_power, 각 점에 CH 또는 N 라벨. 구조적 파라미터 변경에 따른 PPA trade-off 시각화

#### 실전 예시: 구조적 파라미터 비교

**사용자 질문**: "CH138이랑 CH168 차이 좀 알려줘"

**에이전트 사고 흐름**:
1. 공정 미지정 → clarification 필요 (cell height 값으로 공정 추정 가능할 수도 있으나, 확인 필요)
2. "차이" → 전체 PPA 비교 의도. freq_ghz, d_power, s_power 중심
3. 동일 셀 타입, Vth, PVT corner에서 cell height만 다른 데이터 비교

**에이전트 동작**:
- clarification: "어떤 공정(또는 프로젝트)에서 비교할까요?"
- 공정 확정 후 → 규칙 8 진행
- 기본값: TT, 25°C, nominal VDD, CELL AVG, DS AVG, LVT 기본
- CH138 vs CH168의 전 지표 비교 + 변화율
- 물리적 설명: "CH168은 CH138 대비 높이가 커서 더 큰 트랜지스터와 라우팅 자원을 확보할 수 있어 성능이 유리하지만, 면적이 증가합니다"

### 9.9 조건 누락 시 기본 동작

사용자가 조건을 명시하지 않은 경우:
- **PVT corner 누락**: TT corner(Typical Process, Nominal VDD, 25°C)를 기본값으로 사용한다.
- **PDK 버전 누락**: 규칙 8의 단계적 축소 흐름(8.2)에 따라 Process → Project → Mask → DK_GDS → Golden 순으로 좁혀간다. 자동 축소가 가능한 단계는 자동으로, 불가능한 단계는 clarification으로 처리한다.
- **비교 분석**: 조건 명시를 요청하는 clarification을 보낸다. "어떤 PVT corner에서 비교할까요? (예: TT@0.75V@25°C)"
- **Worst-case 관련**: 규칙 2의 매핑을 기반으로 적절한 corner를 자동 선택한다.

#### 기본값 요약표

| 조건 | 미지정 시 기본값 | 근거 |
|------|------------------|------|
| process_corner | TT | Typical-Typical, 가장 일반적인 비교 기준 |
| temperature | 25°C | Room temperature, 표준 측정 조건 |
| vdd | Nominal VDD | 해당 공정의 표준 동작 전압 |
| cell (셀 타입) | AVG (INV, ND2, NR2 평균) | 단일 셀 편향 방지, 전체 경향 파악 |
| drive_strength | AVG (D1, D4 평균) | 단일 DS 편향 방지, 전체 경향 파악 |
| vth | clarification 요청 또는 전 Vth 제시 | Vth는 사용자 의도에 따라 크게 달라지므로 임의 기본값 지정 지양 |
| PDK 버전 (HSPICE/LVS/PEX) | Golden (IS_GOLDEN=1) | 관리자 지정 대표 버전 |

#### clarification 우선순위

모든 정보가 없는 극단적 질문(예: "leakage 좀 보여줘")의 경우, 아래 순서로 확인한다:
1. **공정 또는 프로젝트** — 가장 먼저 확인. 이것 없이는 아무것도 조회 불가
2. **Mask** — 1개면 자동, N개면 clarification
3. **DK_GDS** — 1개면 자동, N개면 clarification
4. **HSPICE/LVS/PEX** — 미지정 시 Golden 자동
5. **PVT corner, cell, drive_strength** — 미지정 시 기본값 자동 적용하고, 적용한 기본값을 응답에 명시

---

## 10. 시각화 유형 요약

> 에이전트가 쿼리 패턴을 인식한 후, 아래 매핑을 참조하여 적절한 시각화 유형을 선택한다.

| 시각화 유형 | 적합한 쿼리 패턴 | 설명 |
|-------------|-------------------|------|
| Grouped Bar | 9.1, 9.2, 9.4, 9.8 | 카테고리별 파라미터 값 나란히 비교. 가장 범용적 |
| 변화율 Bar | 9.1 | 두 버전 간 변화율(%)을 방향+색상으로 표시 |
| Line | 9.1(3+버전), 9.7 | 연속 변수(온도, VDD, 버전 히스토리)에 따른 추이 |
| Multi-line | 9.7 | 같은 차트에 조건별(Vth 등) 라인 겹침 비교 |
| Scatter | 9.2, 9.4, 9.6, 9.8 | 두 파라미터 간 trade-off 또는 분포. Pareto frontier 식별 |
| Heatmap | 9.3, 9.5 | 2차원 매트릭스(Temperature×VDD, Corner×파라미터). 전체 조감 |
| Histogram | 9.6 | 단일 파라미터 분포. 이상치 tail 식별 |
| Box Plot | 9.6 | 조건별 분포 비교. outlier 즉시 식별 |
| Radar Chart | 9.5 | 단일 셀의 다차원 PPA 밸런스 시각화 |
| Table | 9.5 | 정밀 수치가 필요한 경우. 시각화의 기본 보완 |
