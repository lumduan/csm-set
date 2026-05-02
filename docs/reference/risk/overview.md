# Risk Module Reference

Reference for `src/csm/risk/` — the risk metrics and market regime detection layer. This subpackage computes risk-adjusted performance statistics, drawdown analytics, and identifies bull/bear market regimes to inform portfolio positioning.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/risk/metrics.py` | Performance metrics — summary statistics (CAGR, Sharpe, Sortino, max DD, win rate) and rolling CAGR |
| `src/csm/risk/drawdown.py` | Drawdown analytics — max drawdown, underwater curve, rolling drawdown, recovery periods |
| `src/csm/risk/regime.py` | Market regime detection — 200-day SMA rule, bull/bear classification, position scaling by regime |
| `src/csm/risk/exceptions.py` | Risk-layer exception classes |

## Public callables

### `PerformanceMetrics`

- **Defined in:** `src/csm/risk/metrics.py`
- **Purpose:** Computes standard portfolio performance statistics from an equity curve.
- **Behaviour:**
  - `summary(equity_curve, benchmark, rf_annual)` → `pd.DataFrame` — one-row summary with: CAGR, annualised volatility, Sharpe ratio, Sortino ratio, maximum drawdown, Calmar ratio, win rate (monthly), best/worst month, positive months %, VaR 95%, CVaR 95%
  - `rolling_cagr(equity_curve, window_months)` → `pd.Series` (static method) — trailing CAGR over a rolling window
  - All metrics are annualised assuming 252 trading days
  - The Sortino ratio uses downside deviation (returns below rf_annual); Sharpe uses total standard deviation
- **Example:**
  ```python
  from csm.risk.metrics import PerformanceMetrics

  pm = PerformanceMetrics()
  stats = pm.summary(equity_curve, benchmark=None, rf_annual=0.02)
  # stats columns: cagr, vol_annual, sharpe_ratio, sortino_ratio, max_drawdown, ...
  ```

### `DrawdownAnalyzer`

- **Defined in:** `src/csm/risk/drawdown.py`
- **Purpose:** Computes drawdown metrics from an equity curve.
- **Behaviour:**
  - `max_drawdown(equity_curve)` → `float` — maximum peak-to-trough decline as a negative fraction (e.g., -0.25 = 25% drawdown)
  - `underwater_curve(equity_curve)` → `pd.Series` — time series of current drawdown from the all-time high; 0 when at a new peak
  - `rolling_drawdown(equity, window)` → `pd.Series` — maximum drawdown within a rolling window
  - `recovery_periods(equity_curve)` → `pd.DataFrame` — start date, end date, depth, and duration (in days) of each drawdown recovery period
- **Example:**
  ```python
  from csm.risk.drawdown import DrawdownAnalyzer

  da = DrawdownAnalyzer()
  max_dd = da.max_drawdown(equity_curve)  # -0.28
  underwater = da.underwater_curve(equity_curve)
  recoveries = da.recovery_periods(equity_curve)
  ```

### `RegimeDetector`

- **Defined in:** `src/csm/risk/regime.py`
- **Purpose:** Classifies the current market regime based on the SET index relative to its 200-day simple moving average. Used by the backtest engine and portfolio overlays to adjust exposure.
- **Behaviour:**
  - `detect(index_prices, as_of)` → `RegimeState` — returns `RegimeState.BULL` if index > 200d SMA, `RegimeState.BEAR` otherwise
  - `position_scale(regime)` → `float` — returns 1.0 (fully invested) for BULL, 0.0 (cash) for BEAR
  - `compute_ema(prices, window)` → `pd.Series` (static method) — exponentially-weighted moving average for a given window
  - `is_bull_market(index_prices, as_of, window)` → `bool` (static method) — convenience: True if price > `window`-day SMA
  - `has_negative_ema_slope(prices, window, slope_window)` → `bool` (static method) — True if the EMA slope over `slope_window` days is negative (early warning of regime shift)
- **Example:**
  ```python
  from csm.risk.regime import RegimeDetector, RegimeState

  detector = RegimeDetector()
  regime = detector.detect(set_index_prices, pd.Timestamp("2024-06-30"))
  scale = detector.position_scale(regime)  # 1.0 or 0.0

  if regime == RegimeState.BEAR:
      print("Market below 200d SMA — moving to cash")
  ```

## Cross-references

- Used by: `src/csm/research/backtest.py`, `src/csm/portfolio/drawdown_circuit_breaker.py`, `src/csm/portfolio/sector_regime_constraint_engine.py`
- Tested in: `tests/unit/risk/`
- Concept: `docs/concepts/momentum.md` § SET universe constraints
- Architecture: `docs/architecture/overview.md` § Runtime data flow
