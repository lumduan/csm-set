# Research Module Reference

Reference for `src/csm/research/` — the ranking, information coefficient (IC) analysis, and walk-forward backtesting layer. This subpackage converts feature panels into ranked signals, evaluates their predictive power, and simulates portfolio performance over historical data.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/research/ranking.py` | Cross-sectional percentile ranking and quintile assignment within each rebalance date |
| `src/csm/research/ic_analysis.py` | Information coefficient (IC) computation — Pearson IC, rank (Spearman) IC, ICIR, decay curves |
| `src/csm/research/backtest.py` | Walk-forward momentum backtest engine — position sizing, turnover, sector caps, regime overlay |
| `src/csm/research/walk_forward.py` | Walk-forward fold construction and cross-validation utilities |
| `src/csm/research/exceptions.py` | Research-layer exception classes |

## Public callables

### `CrossSectionalRanker`

- **Defined in:** `src/csm/research/ranking.py`
- **Purpose:** Ranks symbols cross-sectionally within each rebalance date. Computes percentile ranks and quintile labels for momentum signals.
- **Behaviour:**
  - `rank(panel_df, signal_col)` → `pd.DataFrame` — for one signal column, appends `{signal_col}_rank` (float64, percentile) and `{signal_col}_quintile` (Int8, 1–5) columns. NaN-signal symbols are excluded from ranking on that date
  - `rank_all(panel_df)` → `pd.DataFrame` — applies `rank()` to every numeric feature column, skipping forward-return columns (`fwd_ret_*`) and existing rank/quintile columns; operates on a single shared copy
  - Quintile assignment uses `pd.qcut` with a fallback to sparse labels for very small or highly tied cross-sections
  - Input must have a `MultiIndex(date, symbol)`; raises `ValueError` otherwise
- **Example:**
  ```python
  from csm.research.ranking import CrossSectionalRanker

  ranker = CrossSectionalRanker()
  ranked = ranker.rank_all(panel_df)
  # panel_df columns: [mom_12_1, mom_6_1, ...]
  # ranked columns: [..., mom_12_1_rank, mom_12_1_quintile, ...]
  ```

### `ICAnalyzer`

- **Defined in:** `src/csm/research/ic_analysis.py`
- **Purpose:** Computes information coefficient (IC) statistics — the cross-sectional correlation between signal values at time *t* and forward returns over a holding period. A positive, statistically significant IC indicates predictive power.
- **Behaviour:**
  - `compute_ic(panel_df, signal_col, fwd_return_col)` → `ICResult` — Pearson IC (cross-sectional correlation) for each date; returns mean IC, IC standard deviation, t-statistic, IR, and hit rate
  - `compute_rank_ic(panel_df, signal_col, fwd_return_col)` → `ICResult` — Spearman (rank) IC; robust to outliers, preferred for non-normal return distributions
  - `compute_icir(ic_series)` → `float` — Information Coefficient Information Ratio (mean IC / std IC); a measure of signal consistency
  - `compute_decay_curve(panel_df, signal_col, fwd_return_col, horizons)` → `pd.Series` — IC at multiple forward horizons, showing how predictive power decays over time
  - `summary_table(panel_df, signal_cols, fwd_return_col)` → `pd.DataFrame` — one-row-per-signal summary of IC statistics
- **Example:**
  ```python
  from csm.research.ic_analysis import ICAnalyzer

  analyzer = ICAnalyzer()
  result = analyzer.compute_rank_ic(panel_df, "mom_12_1", "fwd_ret_21d")
  # result.mean_ic, result.ic_std, result.t_stat, result.ir, result.hit_rate
  decay = analyzer.compute_decay_curve(panel_df, "mom_12_1", "fwd_ret_21d", [5, 10, 21, 63])
  ```

### `MomentumBacktest(config: BacktestConfig)`

- **Defined in:** `src/csm/research/backtest.py`
- **Purpose:** Walk-forward momentum backtest engine. Runs a full historical simulation with configurable position sizing, turnover buffer, sector capping, regime overlay, liquidity filters, and transaction costs.
- **Behaviour:**
  - `run(panel_df, prices, volume_matrix, sector_map, index_prices)` → `BacktestResult` — executes the full backtest; returns period-by-period reports, equity curve, annual returns, and summary metrics
  - Internally applies: ADTV filter → top-N selection with buffer logic → sector cap enforcement → volatility scaling → drawdown circuit breaker check → rebalance execution
  - `BacktestResult` includes `.metrics_dict()`, `.equity_curve_dict()`, `.annual_returns_dict()` for JSON export
  - Configurable via `BacktestConfig`: start date, end date, top N, buffer N, max sector weight, transaction cost (bps), vol target, drawdown threshold, ADTV constraint, fast exit/re-entry rules
- **Example:**
  ```python
  from csm.research.backtest import MomentumBacktest, BacktestConfig

  config = BacktestConfig(
      start_date=pd.Timestamp("2015-01-01"),
      end_date=pd.Timestamp("2024-12-31"),
      top_n=20,
      buffer_n=5,
      max_sector_weight=0.40,
      transaction_cost_bps=25,
  )
  bt = MomentumBacktest(config)
  result = bt.run(panel_df, prices, volume_matrix, sector_map, index_prices)
  summary = result.metrics_dict()  # CAGR, Sharpe, Sortino, max DD, win rate, ...
  ```

## Cross-references

- Used by: `api/routers/backtest.py`, `api/routers/signals.py`, `scripts/export_results.py`
- Tested in: `tests/unit/research/`
- Concept: `docs/concepts/momentum.md`
- Architecture: `docs/architecture/overview.md` § Runtime data flow
