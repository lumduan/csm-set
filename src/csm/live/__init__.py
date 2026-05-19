"""Live-portfolio state helpers for the CSM-SET paper-trading test.

Reads the canonical ``configs/live_portfolio.yaml`` and reprices the held
positions from ``prices_latest`` so the daily-refresh hook can write the
true portfolio NAV to ``db_gateway.daily_performance`` and
``db_gateway.portfolio_snapshot`` (instead of the synthetic equal-weight
universe NAV that ``equity_curve`` carries).
"""

from csm.live.portfolio import (
    LivePortfolioConfig,
    LivePortfolioMetrics,
    LivePosition,
    compute_live_portfolio_metrics,
    load_live_portfolio,
)

__all__: list[str] = [
    "LivePortfolioConfig",
    "LivePortfolioMetrics",
    "LivePosition",
    "compute_live_portfolio_metrics",
    "load_live_portfolio",
]
