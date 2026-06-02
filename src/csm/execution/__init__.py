"""Execution simulation and trade list generation (Phase 4.7).

Public API surface:
- ExecutionConfig, ExecutionSimulator
- SlippageModelConfig, SqrtImpactSlippageModel
- ExecutionResult, Trade, TradeList, TradeSide
- ClosedTrade, RebalanceFill, pair_trades (Phase 1 strategy-report metrics)
"""

from csm.execution.errors import ExecutionError, TradePairingError
from csm.execution.simulator import ExecutionConfig, ExecutionSimulator
from csm.execution.slippage import SlippageModelConfig, SqrtImpactSlippageModel
from csm.execution.trade_list import ExecutionResult, Trade, TradeList, TradeSide
from csm.execution.trade_pairing import ClosedTrade, RebalanceFill, pair_trades

__all__: list[str] = [
    "ClosedTrade",
    "ExecutionConfig",
    "ExecutionError",
    "ExecutionResult",
    "ExecutionSimulator",
    "RebalanceFill",
    "SlippageModelConfig",
    "SqrtImpactSlippageModel",
    "Trade",
    "TradeList",
    "TradePairingError",
    "TradeSide",
    "pair_trades",
]
