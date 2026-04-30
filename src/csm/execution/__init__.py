"""Execution simulation and trade list generation (Phase 4.7).

Public API surface:
- ExecutionConfig, ExecutionSimulator
- SlippageModelConfig, SqrtImpactSlippageModel
- ExecutionResult, Trade, TradeList, TradeSide
"""

from csm.execution.simulator import ExecutionConfig, ExecutionSimulator
from csm.execution.slippage import SlippageModelConfig, SqrtImpactSlippageModel
from csm.execution.trade_list import ExecutionResult, Trade, TradeList, TradeSide

__all__: list[str] = [
    "ExecutionConfig",
    "ExecutionResult",
    "ExecutionSimulator",
    "SlippageModelConfig",
    "SqrtImpactSlippageModel",
    "Trade",
    "TradeList",
    "TradeSide",
]
