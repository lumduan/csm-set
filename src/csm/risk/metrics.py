"""Performance metrics for backtest evaluation."""

import logging

import numpy as np
import pandas as pd

from csm.config.constants import RISK_FREE_RATE_ANNUAL
from csm.risk.drawdown import DrawdownAnalyzer

logger: logging.Logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """Compute summary statistics for an equity curve."""

    def summary(
        self,
        equity_curve: pd.Series,
        benchmark: pd.Series | None = None,
    ) -> dict[str, float]:
        """Compute annualised performance metrics.

        Args:
            equity_curve: Portfolio equity curve indexed by date.
            benchmark: Optional benchmark equity curve indexed by date.

        Returns:
            Dictionary of annualised performance metrics.
        """

        monthly_returns: pd.Series = equity_curve.pct_change().dropna()
        if monthly_returns.empty:
            return {
                "cagr": 0.0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "calmar": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "avg_monthly_return": 0.0,
                "volatility": 0.0,
            }
        periods: int = len(monthly_returns.index)
        years: float = periods / 12.0
        cagr: float = (
            float((equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1.0 / years) - 1.0)
            if years > 0
            else 0.0
        )
        annual_return: float = float(monthly_returns.mean() * 12.0)
        annual_volatility: float = float(monthly_returns.std(ddof=0) * np.sqrt(12.0))
        downside: pd.Series = monthly_returns[monthly_returns < 0.0]
        downside_volatility: float = (
            float(downside.std(ddof=0) * np.sqrt(12.0)) if not downside.empty else 0.0
        )
        excess_return: float = annual_return - RISK_FREE_RATE_ANNUAL
        sharpe: float = 0.0 if annual_volatility == 0.0 else excess_return / annual_volatility
        sortino: float = 0.0 if downside_volatility == 0.0 else excess_return / downside_volatility
        drawdown_analyzer: DrawdownAnalyzer = DrawdownAnalyzer()
        max_drawdown: float = drawdown_analyzer.max_drawdown(equity_curve)
        calmar: float = 0.0 if max_drawdown == 0.0 else cagr / abs(max_drawdown)
        metrics: dict[str, float] = {
            "cagr": cagr,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown": max_drawdown,
            "win_rate": float((monthly_returns > 0.0).mean()),
            "avg_monthly_return": float(monthly_returns.mean()),
            "volatility": annual_volatility,
        }

        if benchmark is not None and not benchmark.empty:
            aligned: pd.DataFrame = pd.concat(
                [monthly_returns.rename("portfolio"), benchmark.pct_change().rename("benchmark")],
                axis=1,
                sort=False,
            ).dropna()
            if not aligned.empty:
                covariance: float = float(aligned.cov(ddof=0).loc["portfolio", "benchmark"])
                benchmark_variance: float = float(aligned["benchmark"].var(ddof=0))
                beta: float = covariance / benchmark_variance if benchmark_variance != 0.0 else 0.0
                alpha: float = (
                    float(aligned["portfolio"].mean() - beta * aligned["benchmark"].mean()) * 12.0
                )
                tracking_error: float = float(
                    (aligned["portfolio"] - aligned["benchmark"]).std(ddof=0) * np.sqrt(12.0)
                )
                information_ratio: float = 0.0
                if tracking_error != 0.0:
                    information_ratio = float(
                        (aligned["portfolio"] - aligned["benchmark"]).mean() * 12.0 / tracking_error
                    )
                metrics["alpha"] = alpha
                metrics["beta"] = beta
                metrics["information_ratio"] = information_ratio

        logger.info("Computed performance metrics", extra={"periods": periods})
        return metrics

    @staticmethod
    def rolling_cagr(equity_curve: pd.Series, window_months: int) -> pd.Series:
        """Compute rolling annualised CAGR over a sliding window of months.

        Args:
            equity_curve: NAV series indexed by date.
            window_months: Number of months in the rolling window.

        Returns:
            Series of annualised CAGR values; NaN for the first `window_months` entries.
        """
        if window_months < 1:
            raise ValueError("window_months must be >= 1")
        years: float = window_months / 12.0
        return (equity_curve / equity_curve.shift(window_months)) ** (1.0 / years) - 1.0


__all__: list[str] = ["PerformanceMetrics"]
