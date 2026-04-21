"""Research-layer exports for csm-set."""

from csm.research.backtest import BacktestConfig, BacktestResult, MomentumBacktest
from csm.research.exceptions import BacktestError, ResearchError
from csm.research.ic_analysis import ICAnalyzer
from csm.research.ranking import CrossSectionalRanker

__all__: list[str] = [
    "BacktestConfig",
    "BacktestError",
    "BacktestResult",
    "CrossSectionalRanker",
    "ICAnalyzer",
    "MomentumBacktest",
    "ResearchError",
]