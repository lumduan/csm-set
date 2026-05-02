# Features Module Reference

Reference for `src/csm/features/` — the signal computation layer. This subpackage computes momentum signals, risk-adjusted variants, sector aggregates, and orchestrates the full feature computation pipeline that produces the panel DataFrames consumed by the research and portfolio layers.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/features/momentum.py` | Classic cross-sectional momentum signals (12-1M, 6-1M, 3-1M, 1-0M) using trading-day offsets |
| `src/csm/features/risk_adjusted.py` | Risk-adjusted momentum: volatility-scaled, market-beta-neutral, and residual (OLS) momentum |
| `src/csm/features/sector.py` | Sector-level features: sector median momentum and within-sector z-score |
| `src/csm/features/pipeline.py` | Feature computation orchestrator — builds the (date × symbol) panel of all signals + forward returns |
| `src/csm/features/exceptions.py` | Feature-layer exception classes |

## Public callables

### `MomentumFeatures.compute(close: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`

- **Defined in:** `src/csm/features/momentum.py`
- **Purpose:** Compute four momentum signals for a single symbol using trading-day offsets (not calendar-day), correctly handling SET public holidays. Returns `float32` DataFrame with columns `[mom_12_1, mom_6_1, mom_3_1, mom_1_0]` indexed by `rebalance_dates`.
- **Behaviour:**
  - Signals are log returns: `ln(close_{t − end_offset} / close_{t − start_offset})`
  - NaN when insufficient history or a boundary price is invalid
  - `mom_1_0` uses a 0-day skip (captures short-term reversal; distinct from the 12/6/3-month signals which skip 1 month)
  - `close` index must be a `DatetimeIndex`; duplicate timestamps raise `ValueError`
- **Example:**
  ```python
  from csm.features.momentum import MomentumFeatures

  mf = MomentumFeatures()
  signals = mf.compute(close, rebalance_dates)
  # signals.columns → ['mom_12_1', 'mom_6_1', 'mom_3_1', 'mom_1_0']
  ```

### `RiskAdjustedFeatures.compute(prices: dict[str, pd.DataFrame], market_prices: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`

- **Defined in:** `src/csm/features/risk_adjusted.py`
- **Purpose:** Compute risk-adjusted momentum variants: volatility-scaled momentum, CAPM-beta-neutral momentum, and residual (OLS alpha) momentum. Each variant adjusts the raw 12-1M signal for a different risk dimension.
- **Example:**
  ```python
  from csm.features.risk_adjusted import RiskAdjustedFeatures

  raf = RiskAdjustedFeatures()
  ra_signals = raf.compute(prices, market_prices, rebalance_dates)
  ```

### `SectorFeatures.compute(panel_df: pd.DataFrame, sector_map: dict[str, str]) -> pd.DataFrame`

- **Defined in:** `src/csm/features/sector.py`
- **Purpose:** Compute sector-level features from a signal panel: sector median momentum and each stock's within-sector z-score. These serve as conditioning variables for sector-aware portfolio constraints.
- **Example:**
  ```python
  from csm.features.sector import SectorFeatures

  sf = SectorFeatures()
  sector_signals = sf.compute(panel_df, sector_map)
  ```

### `FeaturePipeline(store: ParquetStore, settings: Settings)`

- **Defined in:** `src/csm/features/pipeline.py`
- **Purpose:** Orchestrates the full feature computation pipeline. Loads price data from the store, computes all signals for all symbols, builds a (date × symbol) MultiIndex panel, and attaches forward returns for IC/backtest evaluation.
- **Behaviour:**
  - `build(prices, rebalance_dates)` — compute all signals (momentum + risk-adjusted + sector) for a dict of per-symbol DataFrames, returning a `pd.DataFrame` with `MultiIndex(date, symbol)`
  - `build_forward_returns(prices, rebalance_dates, horizon_days)` — compute forward returns for each rebalance date and specified horizon, for IC analysis and backtest evaluation
  - `load_latest()` — load the most recently persisted feature panel from the store
  - `build_volume_matrix(exclude)` — build a (date × symbol) matrix of average daily volume for liquidity overlays
- **Example:**
  ```python
  from csm.features.pipeline import FeaturePipeline

  pipeline = FeaturePipeline(store, settings)
  panel = pipeline.build(prices, rebalance_dates)
  panel_with_fwd = pipeline.build_forward_returns(prices, rebalance_dates, horizon_days=21)
  ```

## Cross-references

- Used by: `src/csm/research/ranking.py`, `src/csm/research/backtest.py`, `api/routers/signals.py`
- Tested in: `tests/unit/features/`
- Concept: `docs/concepts/momentum.md`
- Architecture: `docs/architecture/overview.md` § Runtime data flow
