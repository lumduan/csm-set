"""Rebalance scheduling and turnover utilities."""

import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class RebalanceScheduler:
    """Compute rebalance calendars and turnover diagnostics."""

    def get_rebalance_dates(self, start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
        """Return business month-end rebalance dates between start and end."""

        rebalance_dates: list[pd.Timestamp] = list(pd.date_range(start=start, end=end, freq="BME"))
        logger.info("Computed rebalance dates", extra={"count": len(rebalance_dates)})
        return rebalance_dates

    def compute_turnover(self, current: pd.Series, target: pd.Series) -> float:
        """Compute one-way turnover between current and target weights."""

        symbols: pd.Index = current.index.union(target.index)
        aligned_current: pd.Series = current.reindex(symbols).fillna(0.0)
        aligned_target: pd.Series = target.reindex(symbols).fillna(0.0)
        return float(0.5 * (aligned_target - aligned_current).abs().sum())

    def trade_list(
        self,
        current: pd.Series,
        target: pd.Series,
        portfolio_value: float,
    ) -> pd.DataFrame:
        """Generate a trade list required to rebalance the portfolio."""

        symbols: pd.Index = current.index.union(target.index)
        aligned_current: pd.Series = current.reindex(symbols).fillna(0.0)
        aligned_target: pd.Series = target.reindex(symbols).fillna(0.0)
        delta: pd.Series = aligned_target - aligned_current
        return pd.DataFrame(
            {
                "symbol": symbols,
                "current_weight": aligned_current.to_numpy(),
                "target_weight": aligned_target.to_numpy(),
                "delta_weight": delta.to_numpy(),
                "trade_value_thb": (delta * portfolio_value).to_numpy(),
            }
        )


__all__: list[str] = ["RebalanceScheduler"]
