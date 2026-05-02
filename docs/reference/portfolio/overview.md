# Portfolio Module Reference

Reference for `src/csm/portfolio/` — the portfolio construction, weight optimisation, constraint enforcement, and rebalancing layer. This subpackage converts ranked signals into investable portfolios with realistic constraints.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/portfolio/optimizer.py` | Weight optimisation — equal, vol-target, min-variance, inverse-vol; Monte Carlo efficient frontier |
| `src/csm/portfolio/construction.py` | Portfolio construction — top-N selection with buffer logic, weight assignment, sector capping |
| `src/csm/portfolio/rebalance.py` | Rebalance date calculation, turnover computation, trade-list generation |
| `src/csm/portfolio/constraints.py` | Alias for `construction.py` (legacy import path) |
| `src/csm/portfolio/vol_scaler.py` | Volatility-target position scaling |
| `src/csm/portfolio/liquidity_overlay.py` | Liquidity-capacity overlay — position sizing constrained by ADV |
| `src/csm/portfolio/drawdown_circuit_breaker.py` | Drawdown-based circuit breaker — halts trading after a drawdown threshold breach |
| `src/csm/portfolio/sector_regime_constraint_engine.py` | Sector-level regime constraint engine — caps sector exposure, adjusts based on regime |
| `src/csm/portfolio/quality_filter.py` | Quality filter — screens holdings on fundamental or technical quality criteria |
| `src/csm/portfolio/walkforward_gate.py` | Walk-forward gate — validates backtest walk-forward integrity |
| `src/csm/portfolio/state.py` | Portfolio state and overlay context models (Pydantic) |
| `src/csm/portfolio/exceptions.py` | Portfolio-layer exception classes |

## Public callables

### `WeightOptimizer(settings: Settings)`

- **Defined in:** `src/csm/portfolio/optimizer.py`
- **Purpose:** Computes portfolio weights under different schemes. The `OptimizerConfig` Pydantic model controls constraints (min/max weight, position count, target volatility).
- **Behaviour:**
  - `equal_weight(symbols)` → `pd.Series` — 1/N weights; simplest scheme
  - `vol_target_weight(symbols, returns, target_vol)` → `pd.Series` — inverse-volatility weights scaled to a target portfolio volatility
  - `min_variance_weight(symbols, returns)` → `pd.Series` — minimum-variance portfolio via numerical optimisation (scipy)
  - `monte_carlo_frontier(n_symbols, n_portfolios, returns)` → `MonteCarloResult` — random-portfolio efficient frontier for visualisation
  - `compute(symbols, returns, scheme, config)` → `pd.Series` — dispatch to the selected scheme by `WeightScheme` enum
- **Example:**
  ```python
  from csm.portfolio.optimizer import WeightOptimizer, WeightScheme, OptimizerConfig

  opt = WeightOptimizer(settings)
  config = OptimizerConfig(min_weight=0.02, max_weight=0.15, max_positions=20)
  weights = opt.compute(top_symbols, returns, scheme=WeightScheme.VOL_TARGET, config=config)
  ```

### `PortfolioConstructor(store: ParquetStore, settings: Settings)`

- **Defined in:** `src/csm/portfolio/construction.py`
- **Purpose:** Builds a portfolio from ranked signals. Selects top-N holdings, applies a buffer rule to reduce turnover, and assigns weights.
- **Behaviour:**
  - `select(rankings, config)` → `SelectionResult` — select top-N symbols from ranked list with buffer logic (holdings already in the portfolio stay in if they remain above a lower threshold)
  - `build(selected, weights, as_of)` → `pd.DataFrame` — construct the final portfolio as a DataFrame with symbol, weight, sector, and sizing metadata
- **Example:**
  ```python
  from csm.portfolio.construction import PortfolioConstructor, SelectionConfig

  constructor = PortfolioConstructor(store, settings)
  config = SelectionConfig(top_n=20, buffer_n=5, max_sector_weight=0.40)
  result = constructor.select(rankings_df, config)
  portfolio = constructor.build(result.selected, weights, pd.Timestamp.now())
  ```

### `RebalanceScheduler`

- **Defined in:** `src/csm/portfolio/rebalance.py`
- **Purpose:** Computes rebalance dates, turnover between portfolios, and generates trade lists with execution instructions.
- **Behaviour:**
  - `get_rebalance_dates(start, end)` → `list[pd.Timestamp]` — monthly rebalance dates within the given range
  - `compute_turnover(current, target)` → `float` — one-way turnover as fraction of portfolio value
  - `trade_list(current, target, as_of)` → `pd.DataFrame` — generates buy/sell instructions with target shares
- **Example:**
  ```python
  from csm.portfolio.rebalance import RebalanceScheduler

  scheduler = RebalanceScheduler()
  dates = scheduler.get_rebalance_dates(pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31"))
  turnover = scheduler.compute_turnover(current_weights, target_weights)
  ```

### `VolatilityScaler(config: VolScalingConfig)`

- **Defined in:** `src/csm/portfolio/vol_scaler.py`
- **Purpose:** Scales position weights to target a specific portfolio volatility level. Reduces exposure during high-volatility regimes and increases it during calm periods.
- **Example:**
  ```python
  from csm.portfolio.vol_scaler import VolatilityScaler, VolScalingConfig

  config = VolScalingConfig(target_vol=0.15, max_leverage=1.5, lookback_days=60)
  scaler = VolatilityScaler(config)
  result = scaler.scale(weights, returns)
  ```

### `LiquidityOverlay(config: LiquidityConfig)`

- **Defined in:** `src/csm/portfolio/liquidity_overlay.py`
- **Purpose:** Caps position sizes based on average daily volume (ADV) to ensure positions can be exited without excessive market impact.
- **Example:**
  ```python
  from csm.portfolio.liquidity_overlay import LiquidityOverlay, LiquidityConfig

  config = LiquidityConfig(max_adv_fraction=0.10, max_days_to_liquidate=5)
  overlay = LiquidityOverlay(config)
  capped_weights = overlay.apply(weights, volume_matrix, prices, capital)
  ```

### `DrawdownCircuitBreaker(config: DrawdownCircuitBreakerConfig)`

- **Defined in:** `src/csm/portfolio/drawdown_circuit_breaker.py`
- **Purpose:** Monitors portfolio drawdown and halts trading (moves to cash) when a drawdown threshold is breached, with configurable re-entry rules.
- **Example:**
  ```python
  from csm.portfolio.drawdown_circuit_breaker import DrawdownCircuitBreaker, DrawdownCircuitBreakerConfig

  config = DrawdownCircuitBreakerConfig(drawdown_threshold=-0.15, reentry_rule="peak")
  breaker = DrawdownCircuitBreaker(config)
  result = breaker.check(equity_curve, date)
  ```

### `SectorRegimeConstraintEngine(config: SectorRegimeConstraintConfig)`

- **Defined in:** `src/csm/portfolio/sector_regime_constraint_engine.py`
- **Purpose:** Applies sector-level position caps (e.g., max 40% in any single sector) and can tighten/loosen caps based on the market regime.
- **Example:**
  ```python
  from csm.portfolio.sector_regime_constraint_engine import (
      SectorRegimeConstraintEngine, SectorRegimeConstraintConfig
  )

  config = SectorRegimeConstraintConfig(max_sector_weight=0.40)
  engine = SectorRegimeConstraintEngine(config)
  result = engine.apply(portfolio, sector_map, regime)
  ```

### `WalkForwardGate(config: WalkForwardGateConfig)`

- **Defined in:** `src/csm/portfolio/walkforward_gate.py`
- **Purpose:** Validates walk-forward integrity for backtest folds — ensures no data leakage between training and testing periods.
- **Example:**
  ```python
  from csm.portfolio.walkforward_gate import WalkForwardGate, WalkForwardGateConfig

  config = WalkForwardGateConfig(min_train_years=3, gap_days=0)
  gate = WalkForwardGate(config)
  result = gate.validate(folds)
  ```

### `QualityFilter(config: QualityFilterConfig)`

- **Defined in:** `src/csm/portfolio/quality_filter.py`
- **Purpose:** Filters portfolio holdings on quality criteria (e.g., profitability, leverage, earnings quality) before final portfolio construction.
- **Example:**
  ```python
  from csm.portfolio.quality_filter import QualityFilter, QualityFilterConfig

  config = QualityFilterConfig(min_roe=0.05, exclude_negative_earnings=True)
  qf = QualityFilter(config)
  result = qf.filter(holdings, fundamentals)
  ```

## Cross-references

- Used by: `src/csm/research/backtest.py`, `api/routers/portfolio.py`
- Tested in: `tests/unit/portfolio/`
- Concepts: `docs/concepts/momentum.md`, `docs/architecture/overview.md` § Runtime data flow
