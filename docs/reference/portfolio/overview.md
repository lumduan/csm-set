# Portfolio Layer — Module Reference

The `csm.portfolio` subpackage handles stock selection, weight optimisation, constraint enforcement, rebalancing, circuit breakers, and liquidity/quality overlays. It is the largest subpackage in terms of module count and public exports.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/portfolio/construction.py` | Stock selection engine with buffer rules; `PortfolioConstructor`, `SelectionConfig`, `SelectionResult` |
| `src/csm/portfolio/optimizer.py` | Weight optimisation (equal-weight, vol-target, min-variance, Monte Carlo); `WeightOptimizer`, `WeightScheme`, `OptimizerConfig`, `MonteCarloResult` |
| `src/csm/portfolio/rebalance.py` | Rebalancing scheduler and turnover computation; `RebalanceScheduler` |
| `src/csm/portfolio/drawdown_circuit_breaker.py` | Drawdown-based trading halt; `DrawdownCircuitBreaker`, `DrawdownCircuitBreakerConfig`, `CircuitBreakerResult` |
| `src/csm/portfolio/liquidity_overlay.py` | Position sizing against ADV limits; `LiquidityOverlay`, `LiquidityConfig`, `LiquidityResult`, `compute_capacity_curve` |
| `src/csm/portfolio/quality_filter.py` | Quality-based filtering (return on equity, debt ratio); `QualityFilter`, `QualityFilterConfig`, `QualityFilterResult` |
| `src/csm/portfolio/sector_regime_constraint_engine.py` | Sector + regime constraint enforcement; `SectorRegimeConstraintEngine`, `SectorRegimeConstraintConfig`, `SectorRegimeConstraintResult` |
| `src/csm/portfolio/state.py` | Portfolio state tracking across rebalances; `PortfolioState`, `CircuitBreakerState`, `OverlayContext`, `OverlayJournalEntry` |
| `src/csm/portfolio/vol_scaler.py` | Portfolio-level volatility scaling; `VolatilityScaler`, `VolScalingConfig`, `VolScalingResult` |
| `src/csm/portfolio/walkforward_gate.py` | Walk-forward validation gate for strategy parameters; `WalkForwardGate`, `WalkForwardGateConfig`, `WalkForwardGateResult`, `FoldGateResult` |
| `src/csm/portfolio/exceptions.py` | Portfolio exceptions: `PortfolioError`, `OptimizationError`, `SelectionError`, `CircuitBreakerTripped` |

## Public callables

### `class PortfolioConstructor`

- **Defined in:** `src/csm/portfolio/construction.py`
- **Purpose:** Selects stocks for the portfolio at each rebalance date. Applies signal ranking, buffer rules (to reduce turnover), and sector caps.
- **Key methods:**
  - `select(self, ranking: pd.DataFrame, current_holdings: list[str], config: SelectionConfig) -> SelectionResult` — returns the list of selected symbols for the next period.
  - `build(self, selected: list[str], weights: pd.Series, as_of: pd.Timestamp) -> pd.DataFrame` — assembles the final portfolio DataFrame with weights.
- **Behaviour:**
  - Buffer rule: stocks in the current portfolio are retained if they remain in the top 40% of the ranking, reducing unnecessary turnover.
  - Sector cap: no more than 30% of the portfolio in a single SET sector.
  - Max holdings: up to 25 names (configurable via `SelectionConfig`).
- **Example:**
  ```python
  from csm.portfolio import PortfolioConstructor, SelectionConfig

  constructor = PortfolioConstructor()
  config = SelectionConfig(n_holdings=25, sector_cap=0.30)
  result = constructor.select(ranking_panel, current_holdings, config)
  ```

### `class WeightOptimizer`

- **Defined in:** `src/csm/portfolio/optimizer.py`
- **Purpose:** Computes portfolio weights using the selected weighting scheme.
- **Key methods:**
  - `equal_weight(self, symbols: list[str]) -> pd.Series` — returns 1/N weights for the given symbols.
  - `vol_target_weight(self, symbols: list[str], returns: pd.DataFrame, target_vol: float = 0.15) -> pd.Series` — weights inversely proportional to trailing volatility, scaled to target annualised volatility.
  - `min_variance_weight(self, symbols: list[str], returns: pd.DataFrame) -> pd.Series` — minimum variance weights via quadratic optimisation with Ledoit-Wolf shrinkage.
  - `monte_carlo_frontier(self, symbols: list[str], returns: pd.DataFrame, n_portfolios: int = 10000) -> MonteCarloResult` — generates random portfolios to approximate the efficient frontier.
  - `compute(self, symbols: list[str], returns: pd.DataFrame, scheme: WeightScheme, config: OptimizerConfig | None = None) -> pd.Series` — dispatches to the appropriate weighting method.
- **Behaviour:**
  - All schemes enforce long-only (`w_i >= 0`) and max position weight (`w_i <= 15%`).
  - Position constraints are enforced via `_enforce_position_constraints` which clips and renormalises.
  - Monte Carlo frontier is for diagnostic/research use, not live trading.
- **Example:**
  ```python
  from csm.portfolio import WeightOptimizer, WeightScheme

  opt = WeightOptimizer()
  weights = opt.compute(symbols, returns, WeightScheme.EQUAL_WEIGHT)
  ```

### `class WeightScheme(StrEnum)`

- **Defined in:** `src/csm/portfolio/optimizer.py`
- **Values:** `EQUAL_WEIGHT`, `VOL_TARGET`, `MIN_VARIANCE`, `MONTE_CARLO`

### `class RebalanceScheduler`

- **Defined in:** `src/csm/portfolio/rebalance.py`
- **Purpose:** Generates rebalance dates and computes turnover between periods.
- **Key methods:**
  - `get_rebalance_dates(self, start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]` — returns month-end rebalance dates.
  - `compute_turnover(self, current: pd.Series, target: pd.Series) -> float` — returns one-way turnover as a fraction (0.0 = no change, 1.0 = 100% replaced).
  - `trade_list(self, current: pd.Series, target: pd.Series) -> pd.DataFrame` — returns a DataFrame of buy/sell orders to bring the portfolio from current to target weights.
- **Example:**
  ```python
  from csm.portfolio import RebalanceScheduler

  scheduler = RebalanceScheduler()
  dates = scheduler.get_rebalance_dates(pd.Timestamp("2020-01-01"), pd.Timestamp("2025-12-31"))
  turnover = scheduler.compute_turnover(old_weights, new_weights)
  ```

### `class DrawdownCircuitBreaker`

- **Defined in:** `src/csm/portfolio/drawdown_circuit_breaker.py`
- **Purpose:** Halts trading when portfolio drawdown exceeds a threshold. Prevents cascading losses during sustained drawdowns.
- **Behaviour:** When the portfolio drawdown from peak exceeds the configured threshold (default 20%), the circuit breaker trips and all positions are liquidated. Trading resumes when the drawdown recovers below a smaller restart threshold.

### `class LiquidityOverlay`

- **Defined in:** `src/csm/portfolio/liquidity_overlay.py`
- **Purpose:** Caps position sizes so that each position does not exceed a fraction of the stock's average daily traded value.
- **Function:** `compute_capacity_curve(adtv: pd.Series, max_fraction: float = 0.10) -> pd.Series` — returns the maximum notional position size per symbol given ADV constraints.

### `class SectorRegimeConstraintEngine`

- **Defined in:** `src/csm/portfolio/sector_regime_constraint_engine.py`
- **Purpose:** Applies sector-level constraints and regime-based adjustments. Limits sector concentration and can adjust allocations based on market regime (bull/bear).

### `class VolatilityScaler`

- **Defined in:** `src/csm/portfolio/vol_scaler.py`
- **Purpose:** Scales portfolio weights to target a specific annualised volatility level. Uses trailing realised volatility of the portfolio.

### `class WalkForwardGate`

- **Defined in:** `src/csm/portfolio/walkforward_gate.py`
- **Purpose:** Validates strategy parameters using walk-forward cross-validation. Splits data into folds, trains on in-sample, validates on out-of-sample, and gates whether the strategy is fit for live trading.

## Cross-references

- Used by: `src/csm/research/backtest.py` (assembles portfolio at each rebalance), `scripts/export_results.py` (computes final weights)
- Tested in: `tests/unit/portfolio/test_optimizer.py`, `tests/unit/portfolio/test_construction.py`, `tests/unit/portfolio/test_rebalance.py`
- Concept: [Architecture Overview](../../architecture/overview.md) § Monorepo layers
- Related: [Risk Module Reference](../risk/overview.md) — drawdown and regime detection used by circuit breakers
