# Research Layer — Module Reference

The `csm.research` subpackage handles cross-sectional ranking, information coefficient (IC) analysis, walk-forward backtesting, and the backtest engine that ties the full signal-to-portfolio pipeline together.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/research/ranking.py` | Cross-sectional ranking and quintile assignment; `CrossSectionalRanker` |
| `src/csm/research/ic_analysis.py` | Information coefficient computation (Spearman rank IC, Pearson IC); `ICAnalyzer`, `ICResult` |
| `src/csm/research/backtest.py` | Walk-forward backtest engine; `MomentumBacktest`, `BacktestConfig`, `BacktestResult` |
| `src/csm/research/walk_forward.py` | Walk-forward cross-validation for parameter selection |
| `src/csm/research/exceptions.py` | Research-layer exceptions: `ResearchError`, `BacktestError` |

## Public callables

### `class CrossSectionalRanker`

- **Defined in:** `src/csm/research/ranking.py`
- **Purpose:** Ranks stocks within each rebalance date by a signal column. Assigns z-scores, percentiles, and quintiles.
- **Key methods:**
  - `rank(self, panel_df: pd.DataFrame, signal_col: str) -> pd.DataFrame` — returns the panel with added `z_score`, `rank_pct`, and `quintile` columns for the given signal.
  - `rank_all(self, panel_df: pd.DataFrame) -> pd.DataFrame` — ranks on all momentum columns (`mom_12_1`, `mom_6_1`, `mom_3_1`) simultaneously, adding `_z_score`, `_rank_pct`, `_quintile` suffixed columns for each.
- **Behaviour:**
  - Z-score: within each date group, `(signal - mean) / std`.
  - Rank percentile: within each date group, `rank / (n - 1)`.
  - Quintile: 1 (weakest) to 5 (strongest), equal-sized groups.
  - Handles empty panels and single-stock dates gracefully (returns `NaN` z-scores).
  - The panel must have a `date` column; groupby is on `date`.
- **Example:**
  ```python
  from csm.research import CrossSectionalRanker

  ranker = CrossSectionalRanker()
  ranked = ranker.rank(panel, signal_col="mom_12_1")
  # ranked columns: ..., z_score, rank_pct, quintile
  full = ranker.rank_all(panel)
  # full columns: ..., mom_12_1_z_score, mom_12_1_rank_pct, mom_12_1_quintile, ...
  ```

### `class ICAnalyzer`

- **Defined in:** `src/csm/research/ic_analysis.py`
- **Purpose:** Computes information coefficients between signal values at time t and forward returns. Measures signal predictive power.
- **Key types:**
  - `ICResult` — data class containing Spearman rank IC, Pearson IC, t-statistic, and p-value for each period.
- **Behaviour:**
  - Rank IC = Spearman correlation between signal z-score at t and forward return at t+h.
  - Pearson IC = Pearson correlation (more sensitive to outliers, included for comparison).
  - Computed cross-sectionally at each date, then averaged across dates.
  - t-statistic tests whether the mean IC is significantly different from zero.
- **Example:**
  ```python
  from csm.research import ICAnalyzer

  analyzer = ICAnalyzer()
  ic = analyzer.compute(panel, signal_col="mom_12_1_z_score", forward_col="fwd_1m")
  ```

### `class MomentumBacktest`

- **Defined in:** `src/csm/research/backtest.py`
- **Purpose:** The central backtest engine. Runs a walk-forward simulation: at each rebalance date, re-selects stocks, recomputes weights, simulates execution, and tracks performance.
- **Constructor:** `__init__(self, store: ParquetStore, config: BacktestConfig, universe_builder: UniverseBuilder) -> None`
- **Key method:**
  - `run(self, start: pd.Timestamp, end: pd.Timestamp) -> BacktestResult` — runs the full backtest and returns a `BacktestResult` with equity curve, monthly reports, and summary metrics.
- **Behaviour:**
  - Expanding window: initial training uses first 36 months; each subsequent step adds one month.
  - At each step: rebuild universe → recompute signals → rank → select → optimise weights → simulate execution → record performance.
  - Internal methods handle ADV filter, sector caps, vol scaling, regime-based position scaling, and fast re-entry/exit logic.
  - Returns `BacktestResult` which can be serialised via `.metrics_dict()`, `.equity_curve_dict()`, `.annual_returns_dict()`.
- **Example:**
  ```python
  from csm.research import MomentumBacktest, BacktestConfig

  config = BacktestConfig(
      n_holdings=25,
      lookback_window="12-1M",
      weight_scheme="equal_weight",
  )
  backtest = MomentumBacktest(store, config, universe_builder)
  result = backtest.run(
      start=pd.Timestamp("2018-01-01"),
      end=pd.Timestamp("2025-12-31"),
  )
  print(result.metrics_dict())
  ```

### `class BacktestConfig(BaseModel)`

- **Defined in:** `src/csm/research/backtest.py`
- **Purpose:** Configuration for `MomentumBacktest`. Fields include: `n_holdings`, `lookback_window`, `weight_scheme`, `sector_cap`, `max_position_weight`, `turnover_limit`, `transaction_cost_bps`, `use_regime_filter`, `use_circuit_breaker`.

### `class BacktestResult(BaseModel)`

- **Defined in:** `src/csm/research/backtest.py`
- **Purpose:** Output of `MomentumBacktest.run()`. Contains `equity_curve`, `monthly_reports`, `annual_returns`, and summary fields (CAGR, Sharpe, Sortino, max DD, win rate, turnover). Serialisable via `.metrics_dict()`, `.equity_curve_dict()`, `.annual_returns_dict()`.

## Cross-references

- Used by: `scripts/export_results.py` (runs backtest and exports results to `results/static/`)
- Tested in: `tests/unit/research/test_backtest.py`, `tests/unit/research/test_ranking.py`
- Concepts: [Momentum Concept](../../concepts/momentum.md) § Backtest methodology
- Related: [Features Module Reference](../features/overview.md) — signals consumed by the ranker
- Related: [Portfolio Module Reference](../portfolio/overview.md) — weight optimisation used by the backtest
- Related: [Risk Module Reference](../risk/overview.md) — performance metrics computed from backtest results
