"""Execution simulation and trade list generation (Phase 4.7).

Public API surface:
- ExecutionConfig, ExecutionSimulator
- SlippageModelConfig, SqrtImpactSlippageModel
- ExecutionResult, Trade, TradeList, TradeSide
- ClosedTrade, RebalanceFill, pair_trades (Phase 1 strategy-report metrics)
- ExecutionEngineAdapter + wire mirrors + run_sim_loop (Phase 5.1 sim trade loop)
"""

from csm.execution.engine_adapter import (
    EXECUTION_ORDERS_PATH,
    EXECUTION_STREAM_PATH,
    STRATEGY_ID,
    ExecutionEngineAdapter,
)
from csm.execution.errors import (
    EngineAdapterError,
    ExecutionError,
    ExecutionModeError,
    OrderRejectedError,
    OrderTimeoutError,
    SimLoopError,
    StreamError,
    StreamResetError,
    TradePairingError,
)
from csm.execution.models import (
    TERMINAL_STATES,
    FillEvent,
    NormalizedOrder,
    NormalizedOrderResult,
    OrderInstruction,
    OrderUpdateEvent,
    SimPortfolio,
    SimPosition,
)
from csm.execution.sim_loop import (
    OrderOutcome,
    SimLoopResult,
    build_order_instructions,
    run_sim_loop,
)
from csm.execution.simulator import ExecutionConfig, ExecutionSimulator
from csm.execution.slippage import SlippageModelConfig, SqrtImpactSlippageModel
from csm.execution.trade_list import ExecutionResult, Trade, TradeList, TradeSide
from csm.execution.trade_pairing import ClosedTrade, RebalanceFill, pair_trades

__all__: list[str] = [
    "EXECUTION_ORDERS_PATH",
    "EXECUTION_STREAM_PATH",
    "STRATEGY_ID",
    "TERMINAL_STATES",
    "ClosedTrade",
    "EngineAdapterError",
    "ExecutionConfig",
    "ExecutionEngineAdapter",
    "ExecutionError",
    "ExecutionModeError",
    "ExecutionResult",
    "ExecutionSimulator",
    "FillEvent",
    "NormalizedOrder",
    "NormalizedOrderResult",
    "OrderInstruction",
    "OrderOutcome",
    "OrderRejectedError",
    "OrderTimeoutError",
    "OrderUpdateEvent",
    "RebalanceFill",
    "SimLoopError",
    "SimLoopResult",
    "SimPortfolio",
    "SimPosition",
    "SlippageModelConfig",
    "SqrtImpactSlippageModel",
    "StreamError",
    "StreamResetError",
    "Trade",
    "TradeList",
    "TradePairingError",
    "TradeSide",
    "build_order_instructions",
    "pair_trades",
    "run_sim_loop",
]
