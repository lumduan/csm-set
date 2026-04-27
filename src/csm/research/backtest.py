"""Backtest models and momentum backtest engine."""

import logging
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field

from csm.config.constants import TIMEZONE
from csm.data.store import ParquetStore
from csm.portfolio.optimizer import WeightOptimizer
from csm.portfolio.rebalance import RebalanceScheduler
from csm.research.exceptions import BacktestError
from csm.risk.metrics import PerformanceMetrics

logger: logging.Logger = logging.getLogger(__name__)


class BacktestConfig(BaseModel):
    """Configuration for a momentum backtest run."""

    formation_months: int = Field(default=12)
    skip_months: int = Field(default=1)
    top_quantile: float = Field(default=0.2)
    weight_scheme: str = Field(default="equal")
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    transaction_cost_bps: float = Field(default=15.0)


class BacktestResult(BaseModel):
    """JSON-serialisable result object for public-safe backtest outputs."""

    config: BacktestConfig
    generated_at: str
    equity_curve: dict[str, float]
    annual_returns: dict[str, float]
    positions: dict[str, list[str]]
    turnover: dict[str, float]
    metrics: dict[str, float]

    def metrics_dict(self) -> dict[str, object]:
        """Return metrics as a JSON-serialisable dict. No raw price data."""

        return {
            "generated_at": self.generated_at,
            "config": self.config.model_dump(),
            **self.metrics,
        }

    def equity_curve_dict(self) -> dict[str, object]:
        """Return equity curve as NAV indexed to 100. No absolute prices."""

        series: list[dict[str, str | float]] = [
            {"date": date, "nav": nav_value} for date, nav_value in self.equity_curve.items()
        ]
        return {
            "description": "NAV indexed to 100. No raw price data.",
            "series": series,
        }

    def annual_returns_dict(self) -> dict[str, float]:
        """Return year-by-year returns. No raw price data."""

        return self.annual_returns


class MomentumBacktest:
    """Vectorised monthly cross-sectional momentum backtest."""

    def __init__(self, store: ParquetStore) -> None:
        self._store: ParquetStore = store
        self._optimizer: WeightOptimizer = WeightOptimizer()
        self._scheduler: RebalanceScheduler = RebalanceScheduler()
        self._metrics: PerformanceMetrics = PerformanceMetrics()

    def _select_top_quantile(
        self, cross_section: pd.DataFrame, top_quantile: float
    ) -> list[str]:
        """Select top-quantile symbols by composite signal.

        Composite signal = cross-sectional mean of all z-scored feature columns.
        At least one symbol is always returned when cross_section is non-empty.
        """

        if cross_section.empty:
            return []
        composite: pd.Series = cross_section.mean(axis=1)
        n_select: int = max(1, int(round(len(composite) * top_quantile)))
        return [str(s) for s in composite.nlargest(n_select).index]

    def run(
        self,
        feature_panel: pd.DataFrame,
        prices: pd.DataFrame,
        config: BacktestConfig,
    ) -> BacktestResult:
        """Run the monthly momentum backtest.

        Args:
            feature_panel: MultiIndex feature panel indexed by `(date, symbol)`.
            prices: Wide close-price matrix indexed by date, columns = symbols.
            config: Backtest configuration.

        Returns:
            Public-safe backtest result.

        Raises:
            BacktestError: If required data is missing or no observations produced.
        """

        if feature_panel.empty or prices.empty:
            raise BacktestError("Feature panel and prices are required to run a backtest.")

        rebalance_dates: list[pd.Timestamp] = list(
            feature_panel.index.get_level_values("date").unique()
        )
        if len(rebalance_dates) < 2:
            raise BacktestError("At least two rebalance dates are required.")

        current_weights: pd.Series = pd.Series(dtype=float)
        nav: float = 100.0
        equity_curve: dict[str, float] = {}
        annual_returns: dict[str, float] = {}
        positions: dict[str, list[str]] = {}
        turnover_map: dict[str, float] = {}

        for current_date, next_date in zip(rebalance_dates[:-1], rebalance_dates[1:], strict=False):
            # Slice cross-section at current rebalance date.
            try:
                cross_section: pd.DataFrame = feature_panel.xs(current_date, level="date")
            except KeyError:
                continue
            if cross_section.empty:
                continue

            # Select top-quantile symbols by composite z-score signal.
            selected: list[str] = self._select_top_quantile(cross_section, config.top_quantile)

            # Filter to symbols present in the price matrix; warn on missing.
            missing: list[str] = [s for s in selected if s not in prices.columns]
            if missing:
                logger.warning(
                    "Symbols absent from price matrix; contributing zero return",
                    extra={"missing": missing, "date": str(current_date)},
                )
            selected = [s for s in selected if s in prices.columns]
            if not selected:
                continue

            trailing_returns: pd.DataFrame = (
                prices[selected].pct_change().dropna(how="all").tail(252)
            )
            if config.weight_scheme == "vol_target":
                target_weights: pd.Series = self._optimizer.vol_target_weight(
                    selected, trailing_returns
                )
            elif config.weight_scheme == "min_variance":
                target_weights = self._optimizer.min_variance_weight(selected, trailing_returns)
            else:
                target_weights = self._optimizer.equal_weight(selected)

            turnover: float = self._scheduler.compute_turnover(current_weights, target_weights)
            period_returns: pd.Series = (
                prices[selected].loc[current_date:next_date].pct_change().dropna(how="all").mean()
            )
            gross_return: float = float(
                period_returns.reindex(target_weights.index).fillna(0.0).dot(target_weights)
            )
            cost: float = turnover * (config.transaction_cost_bps / 10_000.0)
            nav *= 1.0 + gross_return - cost

            date_key: str = next_date.strftime("%Y-%m-%d")
            equity_curve[date_key] = nav
            positions[date_key] = selected
            turnover_map[date_key] = turnover
            annual_returns.setdefault(next_date.strftime("%Y"), 0.0)
            annual_returns[next_date.strftime("%Y")] += gross_return - cost
            current_weights = target_weights

        equity_series: pd.Series = pd.Series(equity_curve, dtype=float)
        if equity_series.empty:
            raise BacktestError("Backtest produced no output observations.")
        equity_series.index = pd.to_datetime(equity_series.index)
        metrics: dict[str, float] = self._metrics.summary(equity_series)
        result: BacktestResult = BacktestResult(
            config=config,
            generated_at=datetime.now(tz=pd.Timestamp.now(tz=TIMEZONE).tz).isoformat(),
            equity_curve={key: float(value) for key, value in equity_curve.items()},
            annual_returns={key: float(value) for key, value in annual_returns.items()},
            positions=positions,
            turnover={key: float(value) for key, value in turnover_map.items()},
            metrics=metrics,
        )
        self._store.save("backtest_equity_curve", equity_series.to_frame(name="nav"))
        logger.info("Completed backtest", extra={"periods": len(equity_curve)})
        return result


__all__: list[str] = ["BacktestConfig", "BacktestResult", "MomentumBacktest"]
