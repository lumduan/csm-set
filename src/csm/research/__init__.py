"""Research-layer exports for csm-set."""

from csm.research.backtest import BacktestConfig, BacktestResult, MomentumBacktest
from csm.research.exceptions import BacktestError, ReportError, ResearchError
from csm.research.ic_analysis import ICAnalyzer, ICResult
from csm.research.ranking import CrossSectionalRanker
from csm.research.strategy_report import build_strategy_report
from csm.research.strategy_report_models import (
    BenchmarkComparison,
    BenchmarkPoint,
    CapitalEfficiency,
    CapitalUsageRow,
    Details,
    DetailsRow,
    DrawdownRow,
    Headline,
    MarginUsage,
    PnLDistributionBucket,
    ProfitStructure,
    Returns,
    ReturnsRow,
    RiskAdjusted,
    RunUpRow,
    RunUpsDrawdowns,
    StrategyReport,
    TradeLogEntry,
    TradesAnalysis,
    WinLossSplit,
)

__all__: list[str] = [
    "BacktestConfig",
    "BacktestError",
    "BacktestResult",
    "BenchmarkComparison",
    "BenchmarkPoint",
    "CapitalEfficiency",
    "CapitalUsageRow",
    "CrossSectionalRanker",
    "Details",
    "DetailsRow",
    "DrawdownRow",
    "Headline",
    "ICAnalyzer",
    "ICResult",
    "MarginUsage",
    "MomentumBacktest",
    "PnLDistributionBucket",
    "ProfitStructure",
    "ReportError",
    "ResearchError",
    "Returns",
    "ReturnsRow",
    "RiskAdjusted",
    "RunUpRow",
    "RunUpsDrawdowns",
    "StrategyReport",
    "TradeLogEntry",
    "TradesAnalysis",
    "WinLossSplit",
    "build_strategy_report",
]
