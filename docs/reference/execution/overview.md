# Execution Layer — Module Reference

The `csm.execution` subpackage simulates trade execution, models slippage and market impact, and generates trade lists for portfolio rebalancing.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/execution/simulator.py` | Execution simulation engine; `ExecutionSimulator`, `ExecutionConfig` |
| `src/csm/execution/slippage.py` | Slippage and market impact models; `SqrtImpactSlippageModel`, `SlippageModelConfig` |
| `src/csm/execution/trade_list.py` | Trade order data models; `Trade`, `TradeList`, `TradeSide`, `ExecutionResult` |

## Public callables

### `class ExecutionSimulator`

- **Defined in:** `src/csm/execution/simulator.py`
- **Purpose:** Simulates trade execution for a list of target trades. Applies slippage, commission, and lot-size rounding. Computes realised cash flows and fills.
- **Constructor:** `__init__(self) -> None`
- **Key methods:**
  - `simulate(self, trades: pd.DataFrame, prices: dict[str, pd.DataFrame], execution_date: pd.Timestamp, config: ExecutionConfig | None = None) -> ExecutionResult` — runs the execution simulation and returns filled trades, costs, and resulting portfolio.
- **Behaviour:**
  - Applies square-root impact model for slippage.
  - Rounds share quantities to board lot sizes (100 shares for most SET stocks).
  - Deducts commission (default 0.15% per trade, configurable).
  - Tracks total slippage cost and fill rate (fraction of notional filled).
  - Simulates at the next trading day's VWAP (volume-weighted average price) after the signal date.
  - Internal `_round_to_lot` and `_round_down_to_lot` helpers for lot-size rounding.
- **Example:**
  ```python
  from csm.execution import ExecutionSimulator, ExecutionConfig

  simulator = ExecutionSimulator()
  config = ExecutionConfig(commission_bps=15, use_vwap=True)
  result = simulator.simulate(
      target_trades,
      prices_dict,
      execution_date=pd.Timestamp("2025-06-30"),
      config=config,
  )
  ```

### `class ExecutionConfig(BaseModel)`

- **Defined in:** `src/csm/execution/simulator.py`
- **Purpose:** Configuration for the execution simulator.
- **Fields:** `commission_bps` (int, default 15), `slippage_model` (str, default `"sqrt_impact"`), `use_vwap` (bool, default True), `lot_size` (int, default 100).

### `class SqrtImpactSlippageModel`

- **Defined in:** `src/csm/execution/slippage.py`
- **Purpose:** Estimates slippage using a square-root market impact model. Estimates slippage as `σ * sqrt(Q / ADV)` where *Q* is the order size, *σ* is the stock's daily volatility, and *ADV* is average daily value.
- **Constructor:** `__init__(self, config: SlippageModelConfig | None = None) -> None`
- **Key methods:**
  - `estimate(self, notional_thb: float, adtv_thb: float) -> float` — returns the estimated slippage in basis points for a given notional size and average daily traded value.
- **Behaviour:**
  - Square-root form captures the concave relationship between order size and price impact.
  - Calibrated for Thai equity market microstructure (typically lower impact than US due to smaller order sizes).
  - Configurable `impact_coefficient` parameter (default 0.1).
- **Example:**
  ```python
  from csm.execution import SqrtImpactSlippageModel, SlippageModelConfig

  model = SqrtImpactSlippageModel(SlippageModelConfig(impact_coefficient=0.1))
  slippage_bps = model.estimate(notional_thb=1_000_000, adtv_thb=50_000_000)
  ```

### `class SlippageModelConfig(BaseModel)`

- **Defined in:** `src/csm/execution/slippage.py`
- **Fields:** `impact_coefficient` (float, default 0.1), `min_slippage_bps` (float, default 0.5), `max_slippage_bps` (float, default 100.0).

### `class Trade(BaseModel)`

- **Defined in:** `src/csm/execution/trade_list.py`
- **Purpose:** A single trade order. Fields: `symbol`, `side` (BUY/SELL), `shares`, `price`, `notional_thb`, `commission_thb`, `slippage_thb`.

### `class TradeList(BaseModel)`

- **Defined in:** `src/csm/execution/trade_list.py`
- **Purpose:** A collection of trades for one rebalance date. Fields: `date`, `trades` (list of `Trade`), `total_notional`, `total_commission`, `total_slippage`, `net_cash_flow`.

### `class ExecutionResult(BaseModel)`

- **Defined in:** `src/csm/execution/trade_list.py`
- **Purpose:** Output of `ExecutionSimulator.simulate()`. Fields: `date`, `filled_trades` (TradeList), `unfilled_trades` (TradeList), `fill_rate` (float), `portfolio_value` (float), `cash_balance` (float).

### `class TradeSide(StrEnum)`

- **Defined in:** `src/csm/execution/trade_list.py`
- **Values:** `BUY`, `SELL`

## Cross-references

- Used by: `src/csm/research/backtest.py` (simulates execution at each rebalance)
- Tested in: `tests/unit/execution/test_simulator.py`, `tests/unit/execution/test_slippage.py`
- Concept: [Momentum Concept](../../concepts/momentum.md) § Backtest methodology (transaction costs)
- Related: [Portfolio Module Reference](../portfolio/overview.md) — rebalancing generates target trades consumed by the simulator
