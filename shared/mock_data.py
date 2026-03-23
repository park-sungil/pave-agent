from __future__ import annotations

import random
import sqlite3

from config import settings

# --- PDK 버전 데이터 ---
PDK_VERSIONS = [
    # SF3 공정: 2개 project
    {
        "pave_pdk_id": 900,
        "process": "SF3",
        "project": "S5E9975",
        "project_name": "Root",
        "mask": "EVT1",
        "dk_gds": "Root EVT1",
        "is_golden": 1,
        "vdd_nominal": 0.72,
        "hspice": "V1.0.0.0",
        "lvs": "V1.0.0.0",
        "pex": "V1.0.0.0",
    },
    {
        "pave_pdk_id": 901,
        "process": "SF3",
        "project": "S5E9975",
        "project_name": "Root",
        "mask": "EVT0",
        "dk_gds": "Root EVT0",
        "is_golden": 0,
        "vdd_nominal": 0.72,
        "hspice": "V0.9.5.0",
        "lvs": "V0.9.5.0",
        "pex": "V0.9.5.0",
    },
    {
        "pave_pdk_id": 902,
        "process": "SF3",
        "project": "S5E9965",
        "project_name": "Solomon",
        "mask": "EVT1",
        "dk_gds": "Solomon EVT1",
        "is_golden": 1,
        "vdd_nominal": 0.72,
        "hspice": "V1.0.0.0",
        "lvs": "V1.0.0.0",
        "pex": "V1.0.0.0",
    },
    # SF2 공정: 1개 project
    {
        "pave_pdk_id": 880,
        "process": "SF2",
        "project": "S5E9945",
        "project_name": "Thetis",
        "mask": "EVT0",
        "dk_gds": "Thetis EVT0",
        "is_golden": 1,
        "vdd_nominal": 0.72,
        "hspice": "V0.9.2.0",
        "lvs": "V0.9.2.0",
        "pex": "V0.9.2.0",
    },
    # SF2P 공정: 1개 project (trend 분석용)
    {
        "pave_pdk_id": 870,
        "process": "SF2P",
        "project": "S5E9955",
        "project_name": "Ulysses",
        "mask": "EVT0",
        "dk_gds": "Ulysses EVT0",
        "is_golden": 1,
        "vdd_nominal": 0.72,
        "hspice": "V0.9.0.0",
        "lvs": "V0.9.0.0",
        "pex": "V0.9.0.0",
    },
]

# --- PPA 데이터 생성 파라미터 ---
CELLS = ["INV", "ND2", "NR2"]
DRIVE_STRENGTHS = ["D1", "D2", "D3", "D4"]
CORNERS = ["TT", "FF", "SS", "SSPG"]
TEMPS = [-25, 25, 125]
VTHS = ["ULVT", "LVT", "RVT", "HVT"]
VDD_STEPS = [0.50, 0.60, 0.72, 0.80]
CELL_HEIGHTS = ["CH138", "CH168"]
CH_TYPES = {"CH138": "uHD", "CH168": "HD"}
NS_WIDTHS = [("N2", 20), ("N3", 25), ("N4", 35)]

# 기준 PPA 값 (INV D1 TT 25C 0.72V LVT CH168 N3)
BASE_PPA = {
    "freq_ghz": 4.5,
    "d_power": 0.12,
    "d_energy": 0.062,
    "acceff_ff": 0.12,
    "acreff_kohm": 1.8,
    "s_power": 0.0015,
    "iddq_na": 2.1,
}


def _apply_modifiers(
    base: dict,
    cell: str,
    ds: str,
    corner: str,
    temp: int,
    vdd: float,
    vth: str,
    ch: str,
    wns: str,
    pdk_process: str,
) -> dict:
    """조건별 PPA 수정 계수 적용"""
    v = dict(base)

    # 셀 타입
    cell_mod = {"INV": 1.0, "ND2": 0.85, "NR2": 0.75}
    v["freq_ghz"] *= cell_mod.get(cell, 1.0)
    v["d_power"] *= 2.0 - cell_mod.get(cell, 1.0)
    v["s_power"] *= 2.0 - cell_mod.get(cell, 1.0)
    v["iddq_na"] *= 2.0 - cell_mod.get(cell, 1.0)

    # Drive Strength
    ds_num = int(ds[1:])
    v["freq_ghz"] *= 1.0 + 0.08 * (ds_num - 1)
    v["d_power"] *= ds_num
    v["d_energy"] *= ds_num
    v["acceff_ff"] *= ds_num
    v["acreff_kohm"] /= ds_num
    v["s_power"] *= ds_num
    v["iddq_na"] *= ds_num

    # Corner
    corner_mod = {"TT": 1.0, "FF": 1.15, "SS": 0.82, "SSPG": 0.78}
    cm = corner_mod.get(corner, 1.0)
    v["freq_ghz"] *= cm
    v["d_power"] *= cm
    v["s_power"] *= 1.0 + (cm - 1.0) * 0.5

    # Temperature
    temp_factor = 1.0 + (temp - 25) * 0.001
    v["freq_ghz"] *= 1.0 - (temp - 25) * 0.0003
    v["d_power"] *= temp_factor
    v["s_power"] *= 1.5 ** ((temp - 25) / 50)
    v["iddq_na"] *= 1.5 ** ((temp - 25) / 50)

    # VDD
    vdd_ratio = vdd / 0.72
    v["freq_ghz"] *= vdd_ratio ** 0.8
    v["d_power"] *= vdd_ratio ** 2
    v["d_energy"] *= vdd_ratio ** 2
    v["s_power"] *= vdd_ratio ** 1.2
    v["iddq_na"] *= vdd_ratio ** 1.2

    # VTH
    vth_mod = {
        "ULVT": (1.15, 4.0),
        "LVT": (1.0, 1.0),
        "RVT": (0.88, 0.25),
        "HVT": (0.75, 0.06),
    }
    freq_m, leak_m = vth_mod.get(vth, (1.0, 1.0))
    v["freq_ghz"] *= freq_m
    v["s_power"] *= leak_m
    v["iddq_na"] *= leak_m

    # Cell Height
    ch_mod = {"CH138": 0.92, "CH168": 1.0}
    v["freq_ghz"] *= ch_mod.get(ch, 1.0)

    # Nanosheet Width
    wns_mod = {"N2": 0.85, "N3": 1.0, "N4": 1.12}
    v["freq_ghz"] *= wns_mod.get(wns, 1.0)
    v["d_power"] *= wns_mod.get(wns, 1.0)

    # 공정 세대
    proc_mod = {"SF3": 1.05, "SF2": 1.0, "SF2P": 0.97}
    v["freq_ghz"] *= proc_mod.get(pdk_process, 1.0)

    # 노이즈 추가 (±3%)
    for k in v:
        v[k] *= 1.0 + random.uniform(-0.03, 0.03)
        v[k] = round(v[k], 6)

    return v


def create_mock_db() -> str:
    """SQLite mock DB 생성. 반환값: DB 파일 경로"""
    random.seed(42)
    db_path = settings.sqlite_path
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 테이블 생성
    cur.execute("""
        CREATE TABLE IF NOT EXISTS PAVE_PDK_VERSION_VIEW (
            PAVE_PDK_ID INTEGER PRIMARY KEY,
            PROCESS TEXT,
            PROJECT TEXT,
            PROJECT_NAME TEXT,
            MASK TEXT,
            DK_GDS TEXT,
            IS_GOLDEN INTEGER,
            VDD_NOMINAL REAL,
            HSPICE TEXT,
            LVS TEXT,
            PEX TEXT,
            CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP,
            CREATED_BY TEXT DEFAULT 'mock'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS PAVE_PPA_DATA_VIEW (
            PDK_ID INTEGER,
            CELL TEXT,
            DS TEXT,
            CORNER TEXT,
            TEMP INTEGER,
            VDD REAL,
            VTH TEXT,
            WNS TEXT,
            WNS_VAL INTEGER,
            CH TEXT,
            CH_TYPE TEXT,
            FREQ_GHZ REAL,
            D_POWER REAL,
            D_ENERGY REAL,
            ACCEFF_FF REAL,
            ACREFF_KOHM REAL,
            S_POWER REAL,
            IDDQ_NA REAL
        )
    """)

    # PDK 버전 삽입
    for pdk in PDK_VERSIONS:
        cur.execute(
            """INSERT OR REPLACE INTO PAVE_PDK_VERSION_VIEW
            (PAVE_PDK_ID, PROCESS, PROJECT, PROJECT_NAME, MASK, DK_GDS,
             IS_GOLDEN, VDD_NOMINAL, HSPICE, LVS, PEX)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pdk["pave_pdk_id"], pdk["process"], pdk["project"],
                pdk["project_name"], pdk["mask"], pdk["dk_gds"],
                pdk["is_golden"], pdk["vdd_nominal"], pdk["hspice"],
                pdk["lvs"], pdk["pex"],
            ),
        )

    # PPA 데이터 생성
    wns_map = {w: v for w, v in NS_WIDTHS}
    ppa_rows = []
    for pdk in PDK_VERSIONS:
        pdk_id = pdk["pave_pdk_id"]
        process = pdk["process"]
        vdd_nom = pdk["vdd_nominal"]
        vdds = [round(vdd_nom * r, 2) for r in [0.7, 0.85, 1.0, 1.1]]

        for cell in CELLS:
            for ds in DRIVE_STRENGTHS:
                for corner in CORNERS:
                    for temp in TEMPS:
                        for vdd in vdds:
                            for vth in VTHS:
                                for ch in CELL_HEIGHTS:
                                    # 1개 NS width만 사용 (데이터량 조절)
                                    wns, wns_val = "N3", 25
                                    ppa = _apply_modifiers(
                                        BASE_PPA, cell, ds, corner,
                                        temp, vdd, vth, ch, wns, process,
                                    )
                                    ppa_rows.append((
                                        pdk_id, cell, ds, corner, temp,
                                        vdd, vth, wns, wns_val, ch,
                                        CH_TYPES[ch],
                                        ppa["freq_ghz"], ppa["d_power"],
                                        ppa["d_energy"], ppa["acceff_ff"],
                                        ppa["acreff_kohm"], ppa["s_power"],
                                        ppa["iddq_na"],
                                    ))

    # SF3(900)에 의도적 이상치 삽입: 특정 조건에서 비정상적 변화
    # HVT + 125°C 영역에서 S_POWER/IDDQ_NA 급등 (설계 주의 수치)
    anomaly_conditions = {
        ("HVT", 125, "CH138"): {"s_power": 5.0, "iddq_na": 5.0},  # 5배 급등
        ("HVT", 125, "CH168"): {"s_power": 4.0, "iddq_na": 4.5},
        # ULVT + 고전압에서 FREQ 비정상 하락
        ("ULVT", -25, "CH138"): {"freq_ghz": 0.7},  # 30% 하락
    }
    for i, row in enumerate(ppa_rows):
        pdk_id_r = row[0]
        if pdk_id_r != 900:  # SF3 Root에만 이상치
            continue
        vth_r, temp_r, ch_r = row[5 + 1], row[4], row[9]  # VTH, TEMP, CH
        key = (vth_r, temp_r, ch_r)
        if key in anomaly_conditions:
            mods = anomaly_conditions[key]
            row_list = list(row)
            if "s_power" in mods:
                row_list[16] = round(row_list[16] * mods["s_power"], 6)
            if "iddq_na" in mods:
                row_list[17] = round(row_list[17] * mods["iddq_na"], 6)
            if "freq_ghz" in mods:
                row_list[11] = round(row_list[11] * mods["freq_ghz"], 6)
            ppa_rows[i] = tuple(row_list)

    cur.executemany(
        """INSERT INTO PAVE_PPA_DATA_VIEW
        (PDK_ID, CELL, DS, CORNER, TEMP, VDD, VTH, WNS, WNS_VAL, CH,
         CH_TYPE, FREQ_GHZ, D_POWER, D_ENERGY, ACCEFF_FF, ACREFF_KOHM,
         S_POWER, IDDQ_NA)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ppa_rows,
    )

    conn.commit()
    row_count = cur.execute("SELECT COUNT(*) FROM PAVE_PPA_DATA_VIEW").fetchone()[0]
    pdk_count = cur.execute("SELECT COUNT(*) FROM PAVE_PDK_VERSION_VIEW").fetchone()[0]
    conn.close()

    return f"Mock DB 생성 완료: {db_path} (PDK {pdk_count}건, PPA {row_count}행)"


if __name__ == "__main__":
    print(create_mock_db())
