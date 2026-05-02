# Risk Layer — Module Reference

The `csm.risk` subpackage computes portfolio performance metrics (CAGR, Sharpe, Sortino, drawdowns), detects market regimes (bull/bear via 200-day SMA), and analyses drawdown characteristics.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/risk/metrics.py` | Portfolio performance metrics; `PerformanceMetrics` |
| `src/csm/risk/regime.py` | Market regime detection via 200-day SMA; `RegimeDetector`, `RegimeState` |
| `src/csm/risk/drawdown.py` | Drawdown computation and recovery analysis; `DrawdownAnalyzer` |
| `src/csm/risk/exceptions.py` | Risk-layer exceptions: `RiskError` |

## Public callables

### `class PerformanceMetrics`

- **Defined in:** `src/csm/risk/metrics.py`
- **Purpose:** Computes standard portfolio performance metrics from an equity curve.
- **Key methods:**
  - `summary(self, equity_curve: pd.Series, risk_free_rate: float = 0.0) -> dict[str, float]` — returns a dict with: `cagr`, `annual_volatility`, `sharpe_ratio`, `sortino_ratio`, `max_drawdown`, `calmar_ratio`, `win_rate`, `avg_monthly_return`, `best_month`, `worst_month`, `positive_months`, `negative_months`.
  - `rolling_cagr(equity_curve: pd.Series, window_months: int) -> pd.Series` — static method. Returns a Series of rolling CAGR values.
- **Behaviour:**
  - CAGR = `(final / initial)^(12/n_months) - 1`.
  - Sharpe = `(CAGR - rf) / annual_volatility`.
  - Sortino = `(CAGR - rf) / downside_deviation` (downside defined as returns below 0).
  - Max drawdown = largest peak-to-trough decline.
  - Calmar = `CAGR / abs(max_drawdown)`.
  - Expects monthly equity curve data.
  - Handles edge cases: < 12 months of data (warns, returns NaN for annualised metrics), zero-variance returns (Sharpe = 0).
- **Example:**
  ```python
  from csm.risk import PerformanceMetrics

  metrics = PerformanceMetrics()
  summary = metrics.summary(equity_curve, risk_free_rate=0.02)
  # summary: {"cagr": 0.152, "sharpe_ratio": 0.95, ...}
  ```

### `class DrawdownAnalyzer`

- **Defined in:** `src/csm/risk/drawdown.py`
- **Purpose:** Analyses drawdown characteristics of an equity curve.
- **Key methods:**
  - `max_drawdown(self, equity_curve: pd.Series) -> float` — returns the maximum peak-to-trough decline as a negative fraction (e.g., -0.25 = 25% drawdown).
  - `underwater_curve(self, equity_curve: pd.Series) -> pd.Series` — returns the drawdown from peak at each point in time.
  - `rolling_drawdown(self, equity: pd.Series, window: int) -> pd.Series` — returns the maximum drawdown within each rolling window.
  - `recovery_periods(self, equity_curve: pd.Series) -> pd.DataFrame` — returns a DataFrame of drawdown events with start date, trough date, recovery date, depth, and duration in months.
- **Example:**
  ```python
  from csm.risk import DrawdownAnalyzer

  analyzer = DrawdownAnalyzer()
  max_dd = analyzer.max_drawdown(equity_curve)
  underwater = analyzer.underwater_curve(equity_curve)
  recoveries = analyzer.recovery_periods(equity_curve)
  ```

### `class RegimeDetector`

- **Defined in:** `src/csm/risk/regime.py`
- **Purpose:** Detects the current market regime (BULL or BEAR) based on the SET Index's position relative to its 200-day simple moving average.
- **Key methods:**
  - `detect(self, index_prices: pd.Series, as_of: pd.Timestamp) -> RegimeState` — returns `RegimeState.BULL` if the index is above its 200-day SMA, `RegimeState.BEAR` otherwise.
  - `position_scale(self, regime: RegimeState) -> float` — returns 1.0 for BULL, 0.0 for BEAR (full cash-out).
  - `compute_ema(prices: pd.Series, window: int) -> pd.Series` — static method. Computes exponential moving average.
  - `is_bull_market(index_prices: pd.Series, as_of: pd.Timestamp, window: int = 200) -> bool` — static method. Convenience wrapper returning True if the index is above its SMA.
  - `has_negative_ema_slope(index_prices: pd.Series, as_of: pd.Timestamp, window: int = 200, lookback: int = 20) -> bool` — static method. Returns True if the 200-day EMA slope over the past 20 days is negative (early warning).
- **Behaviour:**
  - SMA lookback is configurable (default 200 trading days).
  - Requires at least `window` days of index price history; returns `RegimeState.UNKNOWN` if insufficient data.
  - `has_negative_ema_slope` provides a secondary signal: even if above the SMA, a flattening/declining EMA slope can signal regime transition.
- **Example:**
  ```python
  from csm.risk import RegimeDetector, RegimeState

  detector = RegimeDetector()
  regime = detector.detect(set_index_prices, pd.Timestamp("2025-01-31"))
  scale = detector.position_scale(regime)
  # scale = 1.0 in BULL → full allocation; 0.0 in BEAR → cash
  ```

### `class RegimeState(StrEnum)`

- **Defined in:** `src/csm/risk/regime.py`
- **Values:** `BULL`, `BEAR`, `UNKNOWN`

## Cross-references

- Used by: `src/csm/portfolio/drawdown_circuit_breaker.py` (triggers on drawdown thresholds), `src/csm/portfolio/sector_regime_constraint_engine.py` (adjusts allocations per regime), `src/csm/research/backtest.py` (filters months by regime)
- Tested in: `tests/unit/risk/test_metrics.py`, `tests/unit/risk/test_regime.py`, `tests/unit/risk/test_drawdown.py`
- Concept: [Architecture Overview](../../architecture/overview.md) § Runtime data flow
- Related: [Portfolio Module Reference](../portfolio/overview.md) — circuit breakers and vol scaling consume risk outputs
