# Phase 2 — Signal Research Master Plan

**Feature:** Momentum Signal Research และ IC Analysis บนตลาด SET
**Branch:** `feature/phase-2-signal-research`
**Created:** 2026-04-24
**Status:** In Progress — เริ่มต้น Phase 2
**Positioning:** Research layer — ทดสอบและคัดเลือก momentum signals ที่มี alpha บนตลาดหุ้นไทย ก่อนนำไป backtest ใน Phase 3

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Design Rationale](#design-rationale)
4. [Architecture](#architecture)
5. [Implementation Phases](#implementation-phases)
6. [Data Models](#data-models)
7. [Error Handling Strategy](#error-handling-strategy)
8. [Testing Strategy](#testing-strategy)
9. [Success Criteria](#success-criteria)
10. [Future Enhancements](#future-enhancements)
11. [Commit & PR Templates](#commit--pr-templates)

---

## Overview

### Purpose

Phase 2 คือ **research layer** ที่ใช้ข้อมูล OHLCV ที่ผ่านการทำความสะอาดจาก Phase 1 มาคำนวณ momentum features แล้วทดสอบว่า signal ตัวไหนมี predictive power จริงบน SET ก่อนที่จะลงทุนเวลาพัฒนา backtest engine ใน Phase 3

กระบวนการหลัก:

1. คำนวณ momentum features หลายแบบ (12-1M, 6-1M, 3-1M, 1-0M, risk-adjusted, sector-relative)
2. รวม features เป็น panel DataFrame (date × symbol) พร้อม winsorise + z-score
3. Rank symbols แบบ cross-sectional percentile และ assign quintile labels
4. วัด IC (Information Coefficient) และ ICIR ต่อ signal แต่ละตัวที่ horizons ต่างๆ
5. สรุป composite signal ที่จะนำไป Phase 3

### Scope

Phase 2 ครอบคลุม 7 sub-phases ตาม dependency order:

| Sub-phase | Deliverable | Purpose |
|---|---|---|
| 2.1 | Momentum Features | คำนวณ mom_12_1, mom_6_1, mom_3_1, mom_1_0 |
| 2.2 | Risk-Adjusted Features | sharpe_momentum, residual_momentum |
| 2.3 | Sector Features | relative strength vs sector index |
| 2.4 | Feature Pipeline | รวม features + winsorise + z-score cross-sectionally |
| 2.5 | Ranking | Percentile rank + quintile labels per rebalance date |
| 2.6 | IC Analysis | Pearson IC, Spearman IC, ICIR, decay curves |
| 2.7 | Signal Research Notebook | `02_signal_research.ipynb` — วิเคราะห์ครบ + ตัดสินใจ composite signal |

**Out of scope for Phase 2:**

- Backtest engine (Phase 3)
- Portfolio construction (Phase 4)
- API หรือ UI (Phases 5–6)
- Live data refresh หรือ scheduled jobs (Phase 5)

### Dependency on Phase 1

Phase 2 ต้องการ artefacts ทั้งหมดจาก Phase 1:

| Artefact | Source | ใช้ใน |
|---|---|---|
| `data/raw/dividends/*.parquet` | Phase 1.8 re-fetch | คำนวณ returns ทุก sub-phase |
| `data/processed/*.parquet` | Phase 1.5 PriceCleaner | raw returns ที่ผ่าน gap-fill และ winsorise แล้ว |
| `data/universe/{YYYY-MM-DD}.parquet` | Phase 1.4 UniverseBuilder | กำหนด investable universe per rebalance date |
| `data/universe/symbols.json` | Phase 1.4 | list of all candidate symbols |

Phase 2 **ไม่แตะ** raw OHLCV store โดยตรง — อ่านผ่าน `ParquetStore` เท่านั้น และ **ไม่สร้าง** ข้อมูลใหม่ใน `data/raw/` หรือ `data/processed/`

---

## Problem Statement

ก่อนที่จะเขียน backtest engine ต้องรู้ก่อนว่า signal ตัวไหนมี predictive power จริงบน SET เพราะ:

1. **Emerging market dynamics แตกต่าง** — SET มีสัดส่วน retail investors สูง, bid-ask spreads กว้างกว่า developed markets, และมี sector concentration ที่ต่างจาก US/Europe momentum literature
2. **Look-ahead bias ซ่อนง่าย** — การคำนวณ momentum return ที่ include เดือนล่าสุด (short-term reversal) หรือใช้ข้อมูลอนาคตใน z-score normalization จะทำให้ IC เกินจริง
3. **Redundancy ระหว่าง signals** — ถ้า mom_12_1 และ mom_6_1 correlate สูง การรวมทั้งคู่ไม่ได้เพิ่ม alpha แต่เพิ่ม turnover
4. **IC decay** — signal ที่ทำงานดีที่ 1M forward อาจ decay เร็วหรือช้าแตกต่างกัน ซึ่งส่งผลต่อ rebalancing frequency ที่เหมาะสม
5. **Gate criterion** — ICIR < 0.3 บน signal ใดๆ หมายความว่า signal นั้นไม่ควรเข้า composite score ใน Phase 3

---

## Design Rationale

### Cross-sectional แทน Time-series

Phase 2 ทำ cross-sectional ranking (rank symbols ต่อกันภายใน universe เดียวกัน) ไม่ใช่ time-series momentum (เปรียบเทียบ symbol กับตัวเองในอดีต) เพราะ:

- ลด market beta exposure โดยธรรมชาติ
- สอดคล้องกับ Jegadeesh–Titman (1993) และ Rouwenhorst (1999) ที่ทดสอบบน emerging markets
- ป้องกัน look-ahead bias ได้ง่ายกว่า — แต่ละ rebalance date ใช้ข้อมูล ≤ asof เท่านั้น

### Skip Last Month (Formation Gap)

ทุก momentum feature ใช้ pattern `[t-N : t-1M]` ไม่ใช่ `[t-N : t]` เพื่อหลีกเลี่ยง short-term reversal ที่รู้จักกันดีในตลาด (bid-ask bounce, microstructure noise) ซึ่งจะทำให้ signal ดูแย่ลงใน IC ถ้าไม่ skip

### Z-score Cross-sectionally, Not Time-series

Normalization ทำ per rebalance date cross-sectionally (mean 0, std 1 across symbols ณ วันนั้น) ไม่ใช่ normalize ตาม time series ของ symbol เดิม เพราะ:

- ป้องกัน distribution shift ของ market regime ซึมเข้ามาใน signal
- ทำให้ signal ทุกตัว comparable บน scale เดียวกันสำหรับ composite weighting

### IC vs Quintile Spread

Phase 2 ใช้ทั้ง IC (continuous correlation) และ quintile spread (Q5−Q1) เป็น complementary metrics:

- IC วัด signal quality อย่าง statistically robust
- Quintile spread วัดว่า practical portfolio ที่ long Q5 / short Q1 จะทำกำไรได้จริงแค่ไหน
- ICIR = mean(IC) / std(IC) วัด signal stability ข้าม time periods

### DataFrame Panel Design

Feature pipeline ผลิต panel DataFrame ที่ index เป็น `(date, symbol)` MultiIndex — รูปแบบนี้ทำให้:

- GroupBy per date สำหรับ cross-sectional z-score ง่ายมาก
- Forward join กับ return ที่ horizon ต่างๆ ทำใน pandas โดยตรง
- ง่ายต่อการ export เป็น parquet สำหรับ Phase 3 consumption

---

## Architecture

### Directory Layout

```
src/csm/
├── features/
│   ├── __init__.py
│   ├── momentum.py           # MomentumFeatures — mom_12_1, 6_1, 3_1, 1_0
│   ├── risk_adjusted.py      # RiskAdjustedFeatures — sharpe_momentum, residual_momentum
│   ├── sector.py             # SectorFeatures — relative strength vs sector
│   └── pipeline.py           # FeaturePipeline — combine + winsorise + z-score
├── research/
│   ├── __init__.py
│   ├── ranking.py            # CrossSectionalRanker — percentile rank + quintiles
│   └── ic_analysis.py        # ICAnalyzer — Pearson/Spearman IC, ICIR, decay curves

notebooks/
└── 02_signal_research.ipynb  # IC time series, ICIR table, correlation matrix, decay curves

results/
└── signals/
    └── latest_ranking.json   # exported composite signal scores + quintiles (git-committed)

tests/
├── features/
│   ├── test_momentum.py
│   ├── test_risk_adjusted.py
│   ├── test_sector.py
│   └── test_pipeline.py
└── research/
    ├── test_ranking.py
    └── test_ic_analysis.py
```

### Dependency Graph

```
ParquetStore + UniverseBuilder (Phase 1 — read-only)
    ↑ reads
MomentumFeatures       (pandas, numpy — pure computation, no I/O)
RiskAdjustedFeatures   (pandas, numpy, scipy — regression for residual)
SectorFeatures         (pandas — relative to sector aggregation)
    ↑ combined by
FeaturePipeline        (all features → panel DataFrame; winsorise + z-score)
    ↑ consumed by
CrossSectionalRanker   (percentile rank, quintile labels)
ICAnalyzer             (Pearson/Spearman IC, ICIR, decay)
    ↑ visualised by
02_signal_research.ipynb
```

### Data Flow

```
data/processed/{SYMBOL}.parquet     ← Phase 1.5 cleaned OHLCV (read-only)
data/universe/{YYYY-MM-DD}.parquet  ← Phase 1.4 universe snapshots (read-only)
    ↓  MomentumFeatures.compute()
    ↓  RiskAdjustedFeatures.compute()
    ↓  SectorFeatures.compute()
    ↓  FeaturePipeline.build()
panel_df: (date, symbol) → {features}   ← in-memory panel
    ↓  CrossSectionalRanker.rank()
panel_df + {rank, quintile} columns
    ↓  ICAnalyzer.compute_ic()
ic_results: {signal_name → IC series, ICIR, decay_curve}
    ↓  02_signal_research.ipynb (visualise + decide)
results/signals/latest_ranking.json   ← exported for Phase 5/6 public mode
```

---

## Implementation Phases

### Phase 2.1 — Momentum Features

**Status:** `[ ]` Not started
**Depends On:** Phase 1.5 (processed OHLCV in `data/processed/`)

**Goal:** คำนวณ raw momentum returns ทั้ง 4 แบบต่อ symbol ต่อ rebalance date โดยปราศจาก look-ahead bias

**Deliverables:**

- [ ] `src/csm/features/momentum.py` — `MomentumFeatures`
  - [ ] `compute(close: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
    - [ ] Input: `close` price Series ของ symbol เดียว, DatetimeIndex ของ rebalance dates
    - [ ] Output: DataFrame index = rebalance_dates, columns = signal names
    - [ ] `mom_12_1`: return จาก `t-252` ถึง `t-21` trading days (12 เดือน skip 1 เดือน)
    - [ ] `mom_6_1`: return จาก `t-126` ถึง `t-21` (6 เดือน skip 1 เดือน)
    - [ ] `mom_3_1`: return จาก `t-63` ถึง `t-21` (3 เดือน skip 1 เดือน)
    - [ ] `mom_1_0`: return จาก `t-21` ถึง `t` (1 เดือน ไม่ skip — ใช้เป็น reversal signal)
    - [ ] Return คำนวณเป็น `log(price_end / price_start)` สำหรับ compositing ที่ดีกว่า
    - [ ] ถ้า close ที่ boundary date ไม่มีข้อมูล → NaN (ไม่ backfill ข้าม boundary)
- [ ] Unit test: `mom_12_1` ตรงกับการคำนวณ manual ด้วย pandas
- [ ] Unit test: `mom_6_1`, `mom_3_1`, `mom_1_0` ตรงกับ pandas reference
- [ ] Unit test: no look-ahead — signal ที่ rebalance date `t` ใช้เฉพาะ close ≤ `t-21`
- [ ] Unit test: NaN propagation ถ้า close history สั้นกว่า lookback

**Implementation notes:**

- ใช้ integer offset (trading days) ไม่ใช่ calendar days เพราะ SET หยุดวันหยุดราชการ
- `t-21` ≈ 1 เดือน trading days, `t-63` ≈ 3M, `t-126` ≈ 6M, `t-252` ≈ 12M
- ไม่ annualize return — ใช้ raw log return เพื่อความ consistent กับ IC calculation

---

### Phase 2.2 — Risk-Adjusted Features

**Status:** `[ ]` Not started
**Depends On:** Phase 2.1 (raw momentum returns), Phase 1 OHLCV data

**Goal:** สร้าง features ที่ปรับ return ด้วย risk เพื่อดูว่า risk-adjusted signal มี ICIR ดีกว่า raw momentum หรือไม่

**Deliverables:**

- [ ] `src/csm/features/risk_adjusted.py` — `RiskAdjustedFeatures`
  - [ ] `compute(close: pd.Series, index_close: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
    - [ ] Input: symbol close, SET index close, rebalance dates
    - [ ] Output: DataFrame index = rebalance_dates, columns = signal names
    - [ ] `sharpe_momentum`: `mom_12_1 / vol_12` โดย `vol_12` = annualized std ของ daily returns ใน 252 วันก่อน `t-21`
    - [ ] `residual_momentum`: alpha จาก OLS regression ของ daily returns ของ symbol vs SET index ใน 252 วันก่อน `t-21` (market-beta-neutral)
    - [ ] ทั้งคู่ใช้ window เดียวกับ `mom_12_1` เพื่อความ consistent
- [ ] Unit test: `sharpe_momentum` bounded อย่างสมเหตุสมผล (ไม่ infinity ถ้า vol ≠ 0)
- [ ] Unit test: `residual_momentum` market-neutral — correlation กับ index return ≈ 0
- [ ] Unit test: NaN ถ้า vol = 0 หรือ history สั้นเกินไปสำหรับ regression
- [ ] Unit test: no look-ahead — regression ใช้เฉพาะ data ≤ `t-21`

**Implementation notes:**

- `sharpe_momentum`: ถ้า `vol_12 == 0` ให้ return `NaN` ไม่ใช่ `inf`
- `residual_momentum`: ใช้ `scipy.stats.linregress` หรือ `numpy.linalg.lstsq` — ไม่ต้อง statsmodels (ลด dependency)
- Index close ดึงจาก `data/processed/SET%3ASET.parquet` (tvkit format)

---

### Phase 2.3 — Sector Features

**Status:** `[ ]` Not started
**Depends On:** Phase 1 OHLCV data, `src/csm/config/constants.py` (SET_SECTOR_CODES)

**Goal:** วัด relative strength ของแต่ละ symbol เทียบกับ sector index ของตัวเอง เพราะ momentum บน SET อาจเป็น sector-driven มากกว่า stock-specific

**Deliverables:**

- [ ] `src/csm/features/sector.py` — `SectorFeatures`
  - [ ] `compute(symbol_close: pd.Series, sector_closes: dict[str, pd.Series], symbol_sector: str, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
    - [ ] Input: symbol close, dict ของ sector index closes, sector code ของ symbol, rebalance dates
    - [ ] Output: DataFrame index = rebalance_dates, columns = `["sector_rel_strength"]`
    - [ ] `sector_rel_strength`: `mom_12_1(symbol) - mom_12_1(sector_index)` — excess return ของ symbol vs sector ใน 12 เดือน skip 1 เดือน
    - [ ] ถ้า sector index ไม่มีข้อมูล → NaN (ไม่ fallback เป็น market)
- [ ] Unit test: `sector_rel_strength == 0` เมื่อ symbol close เท่ากับ sector index
- [ ] Unit test: positive เมื่อ symbol outperform sector, negative เมื่อ underperform
- [ ] Unit test: NaN เมื่อไม่มี sector data
- [ ] Unit test: no look-ahead — ใช้เฉพาะ data ≤ `t-21`

**Implementation notes:**

- Sector index สร้างเป็น equal-weight average ของ symbols ใน sector นั้นที่ผ่าน universe filter ณ วันนั้น — ไม่ใช่ SET sector index official (เพราะไม่มีข้อมูลชัดเจนใน tvkit)
- `SET_SECTOR_CODES` ใน `constants.py` ใช้เป็น mapping — แต่ละ symbol ต้องมี `sector` metadata ซึ่งจะต้องดึงจาก `settfex` หรือ hard-code

---

### Phase 2.4 — Feature Pipeline

**Status:** `[ ]` Not started
**Depends On:** Phase 2.1, 2.2, 2.3

**Goal:** รวม features ทั้งหมดเป็น panel DataFrame ที่พร้อมใช้ใน IC analysis และ ranking พร้อม cross-sectional normalization ที่ถูกต้อง

**Deliverables:**

- [ ] `src/csm/features/pipeline.py` — `FeaturePipeline`
  - [ ] `__init__(self, store: ParquetStore, universe_store: ParquetStore, settings: Settings)`
  - [ ] `build(rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
    - [ ] Output: MultiIndex DataFrame `(date, symbol)` → columns = all feature names
    - [ ] ต่อ rebalance date:
      1. Load universe snapshot → list of valid symbols
      2. Load processed OHLCV ต่อ symbol จาก `ParquetStore`
      3. Compute all features (2.1, 2.2, 2.3) ต่อ symbol
      4. Assemble cross-sectional DataFrame ณ วันนั้น
      5. Winsorise แต่ละ feature column ที่ 1st/99th percentile cross-sectionally
      6. Z-score normalize แต่ละ feature column (mean 0, std 1) cross-sectionally
    - [ ] Symbols ที่มี NaN ใน feature ใดๆ → drop จาก panel วันนั้น (ไม่ impute)
  - [ ] `build_forward_returns(panel_df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame`
    - [ ] Compute forward log-return per symbol per date at each horizon (1M, 2M, 3M, 6M, 12M)
    - [ ] Join กับ panel_df ด้วย left join — NaN ถ้า horizon data ยังไม่มี (end of sample)
- [ ] Unit test: z-score mean ≈ 0 และ std ≈ 1 per date per feature
- [ ] Unit test: winsorise ลด extreme outliers ก่อน z-score
- [ ] Unit test: no data leakage — features ที่ date `t` ใช้เฉพาะ data ≤ `t`
- [ ] Unit test: forward return ที่ horizon `h` ใช้ data ≥ `t+h` (ไม่ contaminate signal ด้วย future data)
- [ ] Unit test: symbol ที่มี NaN feature ถูก drop จาก output ณ วันนั้น

**Implementation notes:**

- `build()` เป็น synchronous — ถ้าใช้เวลานาน caller ควร wrap ด้วย `asyncio.to_thread()`
- Log จำนวน symbols ที่ drop per date เพื่อ audit
- Panel DataFrame ขนาด `(N_dates × N_symbols, N_features)` อาจใหญ่ถึง ~50K rows — ใช้ `float32` สำหรับ feature columns เพื่อประหยัด memory

---

### Phase 2.5 — Ranking

**Status:** `[ ]` Not started
**Depends On:** Phase 2.4 (panel DataFrame)

**Goal:** สร้าง cross-sectional rank และ quintile labels ต่อ rebalance date สำหรับใช้ใน IC analysis และ quintile spread analysis

**Deliverables:**

- [ ] `src/csm/research/ranking.py` — `CrossSectionalRanker`
  - [ ] `rank(panel_df: pd.DataFrame, signal_col: str) -> pd.DataFrame`
    - [ ] Input: panel_df ที่มี MultiIndex `(date, symbol)`, ชื่อ column ของ composite signal
    - [ ] Output: panel_df เดิม + column `{signal_col}_rank` (0–1 percentile) + `{signal_col}_quintile` (1–5)
    - [ ] Percentile rank per date: `rank(pct=True)` within date group
    - [ ] Quintile: `pd.qcut(rank, q=5, labels=[1,2,3,4,5])` per date
  - [ ] `rank_all(panel_df: pd.DataFrame) -> pd.DataFrame`
    - [ ] Apply `rank()` ต่อทุก feature column ใน panel_df
    - [ ] Return panel_df พร้อม rank + quintile columns สำหรับทุก feature
- [ ] Unit test: ranks sum ถูกต้อง — percentile ranks bounded [0, 1]
- [ ] Unit test: quintile counts balanced per date (แต่ละ quintile ≈ N/5 symbols)
- [ ] Unit test: highest signal value → quintile 5 (winner), lowest → quintile 1 (loser)
- [ ] Unit test: symbols ที่ NaN ใน signal ถูก drop ออกจาก rank ณ วันนั้น

**Implementation notes:**

- `rank(method='average')` สำหรับ ties — consistent กับ Spearman IC
- Quintile labels เป็น integer (1–5) ไม่ใช่ string เพื่อง่ายต่อการ filter ใน Phase 3

---

### Phase 2.6 — IC Analysis

**Status:** `[ ]` Not started
**Depends On:** Phase 2.4 (panel + forward returns), Phase 2.5 (ranking)

**Goal:** วัด predictive power ของแต่ละ signal และ composite score โดยใช้ IC เพื่อตัดสินใจว่า signal ตัวไหนเข้า composite ใน Phase 3

**Deliverables:**

- [ ] `src/csm/research/ic_analysis.py` — `ICAnalyzer`
  - [ ] `compute_ic(panel_df: pd.DataFrame, signal_col: str, forward_ret_col: str) -> pd.Series`
    - [ ] Input: panel_df ที่มี signal column และ forward return column
    - [ ] Output: IC time series (index = rebalance dates, values = Pearson IC per date)
    - [ ] Pearson IC: `corr(signal_t, forward_return_t)` per date (cross-sectional correlation)
    - [ ] NaN ถ้า < 10 symbols ณ วันนั้น
  - [ ] `compute_rank_ic(panel_df: pd.DataFrame, signal_col: str, forward_ret_col: str) -> pd.Series`
    - [ ] Spearman rank IC (rank ทั้ง signal และ return ก่อน correlate)
  - [ ] `compute_icir(ic_series: pd.Series) -> float`
    - [ ] ICIR = `ic_series.mean() / ic_series.std()`
    - [ ] Return `NaN` ถ้า `ic_series` มีน้อยกว่า 12 periods
  - [ ] `compute_decay_curve(panel_df: pd.DataFrame, signal_col: str, horizons: list[int]) -> pd.Series`
    - [ ] วัด mean IC per horizon: 1M, 2M, 3M, 6M, 12M
    - [ ] Output: Series index = horizons, values = mean IC
  - [ ] `summary_table(panel_df: pd.DataFrame, signal_cols: list[str], horizon: int = 1) -> pd.DataFrame`
    - [ ] Output table: signal_name → {Mean_IC, Std_IC, ICIR, t-stat, % positive IC months}
- [ ] Unit test: IC ต่อ known synthetic data ที่รู้ exact correlation
- [ ] Unit test: ICIR คำนวณถูกต้องเทียบกับ manual mean/std
- [ ] Unit test: decay curve มี horizons ถูกต้อง
- [ ] Unit test: NaN ถ้า < 10 symbols ต่อ date
- [ ] Unit test: summary_table มี columns ถูกต้องและ shape ตาม signal_cols

**Implementation notes:**

- Pearson IC อาจ sensitive ต่อ outliers ใน cross-sectional return → เสริมด้วย Rank IC เป็นหลัก
- t-stat = `ICIR × sqrt(T)` โดย T = number of non-NaN IC observations
- Phase 2.7 notebook จะ visualize และตัดสินใจ — `ICAnalyzer` แค่คำนวณตัวเลข

---

### Phase 2.7 — Signal Research Notebook

**Status:** `[ ]` Not started
**Depends On:** Phase 2.1–2.6 ทั้งหมด

**Goal:** Human sign-off ว่า signal ตัวไหนมี ICIR > 0.3 บน SET และกำหนด composite signal สำหรับ Phase 3

**Deliverables:**

- [ ] `notebooks/02_signal_research.ipynb`
  - [ ] **Section 1: Data Loading** — โหลด panel_df จาก FeaturePipeline + forward returns
  - [ ] **Section 2: IC Time Series** — plot IC time series ต่อ signal (mom_12_1, 6_1, 3_1, 1_0, sharpe_momentum, residual_momentum, sector_rel_strength)
  - [ ] **Section 3: ICIR Summary Table** — rank signals ตาม ICIR พร้อม confidence interval
  - [ ] **Section 4: Signal Correlation Matrix** — heatmap correlation ระหว่าง signals (ตรวจ redundancy)
  - [ ] **Section 5: IC Decay Curves** — mean IC per horizon สำหรับแต่ละ signal
  - [ ] **Section 6: Quintile Return Spreads** — Q5−Q1 annual return ต่อ signal ต่อปี (bar chart)
  - [ ] **Section 7: Composite Signal Design** — อธิบาย weighting scheme ที่เลือก + ICIR ของ composite
  - [ ] **Section 8: Sign-off** — print PASS/FAIL ต่อ exit criteria ทุกข้อ
  - [ ] ทุก markdown cell เขียนเป็นภาษาไทย
  - [ ] จุดสิ้นสุด: ระบุ composite signal formula ที่จะใช้ใน Phase 3 พร้อมเหตุผล

**Implementation notes:**

- Notebook ใช้ `FeaturePipeline`, `CrossSectionalRanker`, `ICAnalyzer` โดยตรง
- ถ้า `data/processed/` ว่าง → แสดง `⚠ DATA NOT AVAILABLE` ต่อ section
- Export ผลการ IC analysis เป็น JSON ใน `results/signals/` สำหรับ Phase 5/6

---

## Data Models

### Feature Column Convention

| Feature Name | Type | Description |
|---|---|---|
| `mom_12_1` | `float32` | 12-1M log return (skip 1M) |
| `mom_6_1` | `float32` | 6-1M log return (skip 1M) |
| `mom_3_1` | `float32` | 3-1M log return (skip 1M) |
| `mom_1_0` | `float32` | 1M log return (no skip — reversal signal) |
| `sharpe_momentum` | `float32` | mom_12_1 / 12M trailing vol |
| `residual_momentum` | `float32` | market-beta-adjusted 12M alpha |
| `sector_rel_strength` | `float32` | symbol mom_12_1 − sector mom_12_1 |

ทุก feature column ใน panel_df ที่ผ่าน `FeaturePipeline.build()` จะถูก winsorise + z-score แล้ว

### Panel DataFrame Schema

```
Index: MultiIndex [(date: pd.Timestamp, symbol: str), ...]
  - date: rebalance date (last trading day of month, UTC)
  - symbol: tvkit format e.g. "SET:AOT"

Columns:
  - mom_12_1, mom_6_1, mom_3_1, mom_1_0      float32 (z-scored)
  - sharpe_momentum, residual_momentum        float32 (z-scored)
  - sector_rel_strength                        float32 (z-scored)
  - fwd_ret_1m, fwd_ret_2m, fwd_ret_3m        float32 (log return, not z-scored)
  - fwd_ret_6m, fwd_ret_12m                   float32 (log return, not z-scored)
  - rank_{feature}, quintile_{feature}        float32 / int8 (added by CrossSectionalRanker)
```

### IC Result Schema

```python
@dataclass
class ICResult:
    signal_name: str
    ic_series: pd.Series          # index = rebalance_dates, values = Pearson IC
    rank_ic_series: pd.Series     # Spearman IC
    icir: float
    rank_icir: float
    mean_ic: float
    std_ic: float
    t_stat: float
    pct_positive: float           # fraction of months with IC > 0
    decay_curve: pd.Series        # index = horizons [1,2,3,6,12], values = mean IC
```

---

## Error Handling Strategy

| Scenario | Behaviour |
|---|---|
| Processed OHLCV ไม่พบสำหรับ symbol | Log warning; symbol ถูก skip ใน pipeline |
| Universe snapshot ไม่พบสำหรับ rebalance date | Log warning; วันนั้นถูก skip ทั้งหมด |
| Feature NaN สำหรับ symbol ณ วันใดวันหนึ่ง | Drop symbol จาก cross-section วันนั้น |
| IC < 10 symbols ต่อ date | Return NaN สำหรับ IC วันนั้น |
| Vol = 0 ใน sharpe_momentum | Return NaN — ไม่ใช่ inf |
| Regression data < 63 days ใน residual_momentum | Return NaN — ไม่พอสำหรับ OLS |
| `public_mode=True` ทุก operation | Phase 2 ทั้งหมดเป็น computation บน local data — ไม่ affected by public_mode |

---

## Testing Strategy

### Coverage Target

Minimum 90% line coverage สำหรับ `src/csm/features/` และ `src/csm/research/` ทั้งหมด

### Mocking Strategy

- Features tests: synthetic close Series ที่รู้ exact expected return — ไม่ต้อง mock I/O
- Pipeline tests: mock `ParquetStore.load` ด้วย synthetic DataFrames
- IC tests: synthetic panel_df ที่ engineered correlation ที่รู้ exact IC value
- No integration tests ที่ต้องการ live data ใน Phase 2

### Test File Map

| Module | Test file |
|---|---|
| `src/csm/features/momentum.py` | `tests/features/test_momentum.py` |
| `src/csm/features/risk_adjusted.py` | `tests/features/test_risk_adjusted.py` |
| `src/csm/features/sector.py` | `tests/features/test_sector.py` |
| `src/csm/features/pipeline.py` | `tests/features/test_pipeline.py` |
| `src/csm/research/ranking.py` | `tests/research/test_ranking.py` |
| `src/csm/research/ic_analysis.py` | `tests/research/test_ic_analysis.py` |

### Key Test Cases

**No look-ahead bias** — test ที่สำคัญที่สุดของ Phase 2:

```python
# ตัวอย่าง: signal ที่ rebalance_date ต้องไม่ใช้ข้อมูลหลัง t-21
def test_no_lookahead_mom_12_1():
    # สร้าง close series ที่ price เปลี่ยนแปลงหลัง t-21
    # assert signal ไม่เปลี่ยนแปลงตาม price หลัง t-21
```

**Synthetic IC verification:**

```python
# สร้าง panel ที่ signal = forward_return + noise
# IC ควรสูงตามสัดส่วนของ signal / noise ratio
```

---

## Success Criteria

| Criterion | Measure |
|---|---|
| อย่างน้อย 1 signal มี ICIR > 0.3 | `ICAnalyzer.compute_icir(ic_series) > 0.3` |
| อย่างน้อย 1 signal มี mean IC > 0.03 | `ic_series.mean() > 0.03` |
| Composite signal ICIR > 0.3 | กำหนดและทดสอบใน notebook Section 7 |
| ไม่มี look-ahead bias | ทุก unit test ที่ test look-ahead ผ่าน |
| Z-score mean ≈ 0, std ≈ 1 per date | unit test pipeline.py |
| All unit tests pass | `uv run pytest tests/ -v -m "not integration"` exits 0 |
| Type checking clean | `uv run mypy src/` exits 0 |
| Linting clean | `uv run ruff check src/ scripts/` exits 0 |
| Notebook sign-off | Section 8 print PASS สำหรับทุกข้อ |
| Composite signal documented | Section 7 ระบุ formula + weights ชัดเจน |

---

## Future Enhancements

- **Fundamental overlay** — Phase 9 เพิ่ม P/BV, ROE signal จาก SET SMART มา composite กับ momentum
- **Foreign flow signal** — ข้อมูล net foreign buy/sell จาก SET website เป็น signal เพิ่มเติม
- **LightGBM ranking model** — Phase 9 ใช้ ML เพื่อ learn optimal combination ของ features แทน linear weighting
- **Regime-conditional IC** — วัด IC แยกตาม market regime (BULL/BEAR/NEUTRAL) เพื่อ dynamic weighting ใน Phase 4
- **Factor decay monitoring** — scheduled agent ตรวจ ICIR รายเดือนหลัง Phase 5 deploy

---

## Commit & PR Templates

### Commit Message (Plan — this commit)

```
plan(signal-research): add master plan for Phase 2 — Signal Research

- Creates docs/plans/phase2_signal_research/PLAN.md
- Covers 7 sub-phases: Momentum Features, Risk-Adjusted Features,
  Sector Features, Feature Pipeline, Ranking, IC Analysis, Research Notebook
- Documents panel DataFrame schema: (date, symbol) MultiIndex
- Specifies IC/ICIR gate criteria: ICIR > 0.3, mean IC > 0.03
- Includes architecture, data models, error handling, test matrix,
  and success criteria

Part of Phase 2 — Signal Research roadmap track.
```

### Commit Message (Phase 2.1)

```
feat(features): add MomentumFeatures — mom_12_1, 6_1, 3_1, 1_0 (Phase 2.1)

- Log-return computation with formation-period skip (t-21 boundary)
- No look-ahead: all signals use close ≤ t-21 only
- Unit tests: reference pandas computation, NaN propagation, look-ahead guard
```

### Commit Message (Phase 2.2–2.3)

```
feat(features): add RiskAdjustedFeatures and SectorFeatures (Phases 2.2–2.3)

- sharpe_momentum: mom_12_1 / trailing vol, NaN on zero vol
- residual_momentum: OLS alpha vs SET index (scipy.stats.linregress)
- sector_rel_strength: symbol vs equal-weight sector momentum
- Unit tests: market-neutrality, bounded sharpe, relative strength direction
```

### Commit Message (Phase 2.4–2.5)

```
feat(features): add FeaturePipeline and CrossSectionalRanker (Phases 2.4–2.5)

- FeaturePipeline: assemble panel (date, symbol), winsorise + z-score per date
- CrossSectionalRanker: percentile rank + quintile labels per signal per date
- Unit tests: z-score properties, no leakage, rank balance, quintile ordering
```

### Commit Message (Phase 2.6)

```
feat(research): add ICAnalyzer — Pearson/Spearman IC, ICIR, decay (Phase 2.6)

- compute_ic, compute_rank_ic, compute_icir, compute_decay_curve, summary_table
- Unit tests: synthetic data verification, ICIR formula, NaN guards
```

### Commit Message (Phase 2.7)

```
feat(notebooks): add signal research notebook 02_signal_research.ipynb (Phase 2.7)

- IC time series, ICIR summary table, correlation matrix, decay curves
- Quintile return spreads Q5-Q1 by year
- Composite signal design and sign-off (Phase 3 gate)
- All markdown cells in Thai
```

### PR Description Template

```markdown
## Summary

- Implements full signal research layer for csm-set (Phase 2 of 9)
- `MomentumFeatures` — mom_12_1, 6_1, 3_1, 1_0 with formation-gap skip
- `RiskAdjustedFeatures` — sharpe_momentum, residual_momentum (market-neutral)
- `SectorFeatures` — relative strength vs equal-weight sector index
- `FeaturePipeline` — panel assembly, cross-sectional winsorise + z-score
- `CrossSectionalRanker` — percentile rank + quintile labels
- `ICAnalyzer` — Pearson/Spearman IC, ICIR, decay curves, summary table
- `notebooks/02_signal_research.ipynb` — IC analysis + composite signal decision

## Test plan

- [ ] `uv run pytest tests/ -v -m "not integration"` — all unit tests pass
- [ ] `uv run mypy src/` — exits 0
- [ ] `uv run ruff check src/ scripts/` — exits 0
- [ ] `uv run ruff format --check src/ scripts/` — no changes
- [ ] Manual: run notebook `02_signal_research.ipynb` — Section 8 prints PASS for all criteria
- [ ] Manual: ICIR > 0.3 for at least one signal on SET data
- [ ] Manual: composite signal defined with formula documented in notebook Section 7
```
