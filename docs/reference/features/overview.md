# Features Layer — Module Reference

The `csm.features` subpackage computes momentum, risk-adjusted momentum, and sector-relative features from cleaned price data, and orchestrates them through a configurable pipeline.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/features/momentum.py` | Raw momentum signal computation (12-1M, 6-1M, 3-1M); `MomentumFeatures` |
| `src/csm/features/risk_adjusted.py` | Volatility-scaled and alpha-based momentum; `RiskAdjustedFeatures` |
| `src/csm/features/sector.py` | Sector-relative momentum features; `SectorFeatures` |
| `src/csm/features/pipeline.py` | Feature orchestration, panel construction, forward returns; `FeaturePipeline` |
| `src/csm/features/exceptions.py` | Feature-layer exceptions: `FeatureError`, `InsufficientDataError` |

## Public callables

### `class MomentumFeatures`

- **Defined in:** `src/csm/features/momentum.py`
- **Purpose:** Computes raw momentum signals using the Jegadeesh–Titman formation/skip methodology. Supports multiple lookback windows simultaneously.
- **Key methods:**
  - `compute(self, prices: dict[str, pd.DataFrame], rebalance_dates: list[pd.Timestamp]) -> pd.DataFrame` — returns a DataFrame indexed by `(date, symbol)` with momentum columns for each configured window.
- **Behaviour:**
  - Computes 12-1M, 6-1M, and 3-1M momentum by default.
  - The most recent month (t-1) is always skipped to avoid short-term reversal.
  - Returns `NaN` for symbols with insufficient history (< formation window + skip).
  - Prices dict keys are symbols, values are DataFrames with at minimum an `adj_close` column.
- **Example:**
  ```python
  from csm.features import MomentumFeatures

  momentum = MomentumFeatures()
  panel = momentum.compute(prices_dict, rebalance_dates)
  # panel columns: date, symbol, mom_12_1, mom_6_1, mom_3_1
  ```

### `class RiskAdjustedFeatures`

- **Defined in:** `src/csm/features/risk_adjusted.py`
- **Purpose:** Computes risk-adjusted momentum variants: volatility-scaled momentum and alpha (residual return after market beta adjustment).
- **Key methods:**
  - `compute(self, prices: dict[str, pd.DataFrame], market_prices: pd.DataFrame, rebalance_dates: list[pd.Timestamp]) -> pd.DataFrame` — returns a DataFrame with `vol_scaled_mom` and `alpha` columns.
- **Behaviour:**
  - Vol-scaled momentum = raw momentum / annualised trailing volatility.
  - Alpha = intercept from OLS of stock returns on market (SET index) returns, annualised.
  - Requires >= 60 trading days of price history per symbol.
- **Example:**
  ```python
  from csm.features import RiskAdjustedFeatures

  radj = RiskAdjustedFeatures()
  panel = radj.compute(prices_dict, set_index_prices, rebalance_dates)
  ```

### `class SectorFeatures`

- **Defined in:** `src/csm/features/sector.py`
- **Purpose:** Computes sector-relative momentum features: each stock's momentum relative to its sector median.
- **Key methods:**
  - `compute(self, panel_df: pd.DataFrame) -> pd.DataFrame` — adds `sector_relative_mom` column to the panel by subtracting the sector median from each stock's momentum.
- **Behaviour:**
  - Requires the panel to already have a `sector` column (joined from symbol metadata).
  - Sector median is computed within each rebalance date.
  - If fewer than 3 stocks in a sector, the sector median is `NaN` and no sector-relative feature is computed.
- **Example:**
  ```python
  from csm.features import SectorFeatures

  sector = SectorFeatures()
  panel = sector.compute(panel_with_momentum)
  ```

### `class FeaturePipeline`

- **Defined in:** `src/csm/features/pipeline.py`
- **Purpose:** Orchestrates feature computation end-to-end: loads prices, builds the panel, computes all registered features, and optionally builds forward returns for model training.
- **Constructor:** `__init__(self, store: ParquetStore, features: list[str] | None = None) -> None`
- **Key methods:**
  - `build(self, prices: dict[str, pd.DataFrame], rebalance_dates: list[pd.Timestamp], symbols: list[str]) -> pd.DataFrame` — runs all registered feature computations and returns the combined panel.
  - `build_forward_returns(self, prices: dict[str, pd.DataFrame], rebalance_dates: list[pd.Timestamp], horizon_months: list[int] = [1, 3, 6, 12]) -> pd.DataFrame` — adds forward return columns (fwd_1m, fwd_3m, etc.) for signal validation.
  - `load_latest(self) -> pd.DataFrame` — loads the most recent feature panel from the store.
  - `build_volume_matrix(self, exclude: tuple[str, ...] = (_INDEX_SYMBOL,)) -> pd.DataFrame` — builds a date × symbol matrix of trading volumes for liquidity analysis.
- **Behaviour:**
  - Default features list: `["momentum", "risk_adjusted", "sector"]`.
  - Validates inputs: prices dict must not be empty, rebalance dates must be sorted, all symbols must be present in prices.
  - Panel output is a `pd.DataFrame` with a `(date, symbol)` MultiIndex.
- **Example:**
  ```python
  from csm.features import FeaturePipeline
  from csm.data.store import ParquetStore

  store = ParquetStore(Path("./data/processed"))
  pipeline = FeaturePipeline(store)
  panel = pipeline.build(prices_dict, rebalance_dates, symbols)
  forward_returns = pipeline.build_forward_returns(prices_dict, rebalance_dates)
  ```

## Cross-references

- Used by: `src/csm/research/ranking.py` (ranks stocks on momentum features), `src/csm/research/backtest.py` (builds panels for backtest)
- Tested in: `tests/unit/features/test_momentum.py`, `tests/unit/features/test_pipeline.py`
- Concepts: [Momentum Concept](../../concepts/momentum.md) — theory and academic references
- Architecture: [Architecture Overview](../../architecture/overview.md) § Runtime data flow
