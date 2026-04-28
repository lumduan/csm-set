"""Backtest models and momentum backtest engine."""

import logging
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field

from csm.config.constants import (
    BUFFER_RANK_THRESHOLD,
    BULL_MODE_N_HOLDINGS_MAX,
    BULL_MODE_N_HOLDINGS_MIN,
    EMA_TREND_WINDOW,
    MIN_ADTV_63D_THB,
    SAFE_MODE_MAX_EQUITY,
    TIMEZONE,
)
from csm.data.store import ParquetStore
from csm.portfolio.optimizer import WeightOptimizer
from csm.portfolio.rebalance import RebalanceScheduler
from csm.research.exceptions import BacktestError
from csm.risk.metrics import PerformanceMetrics
from csm.risk.regime import RegimeDetector, RegimeState

logger: logging.Logger = logging.getLogger(__name__)


class MonthlyHoldingRecord(BaseModel):
    """Per-stock holding record within a single rebalance period."""

    symbol: str
    weight: float
    return_pct: float


class MonthlyPeriodReport(BaseModel):
    """Holdings and P&L for one rebalance period."""

    period_end: str
    holdings: list[MonthlyHoldingRecord]
    gross_return: float
    cost: float
    net_return: float
    turnover: float
    nav: float
    mode: str = Field(default="BULL")  # "BULL" | "BEAR" | "NEUTRAL"

    def to_dataframe(self) -> pd.DataFrame:
        """Return a DataFrame of stock-level holdings and contributions for this period."""
        rows: list[dict[str, object]] = [
            {
                "symbol": h.symbol,
                "weight": h.weight,
                "return_pct": h.return_pct,
                "weighted_contribution": h.weight * h.return_pct,
            }
            for h in self.holdings
        ]
        df: pd.DataFrame = pd.DataFrame(rows)
        if not df.empty:
            total_row: pd.DataFrame = pd.DataFrame(
                [
                    {
                        "symbol": "TOTAL",
                        "weight": df["weight"].sum(),
                        "return_pct": float("nan"),
                        "weighted_contribution": self.gross_return,
                    }
                ]
            )
            df = pd.concat([df, total_row], ignore_index=True)
        return df


class MonthlyRebalanceReport(BaseModel):
    """Aggregated monthly rebalance report across all backtest periods."""

    periods: list[MonthlyPeriodReport]

    def to_dataframe(self) -> pd.DataFrame:
        """Return a flat DataFrame with one row per (period, stock).

        Columns: period_end, symbol, weight, return_pct, weighted_contribution,
                 portfolio_gross_return, portfolio_cost, portfolio_net_return, turnover, nav.
        """
        rows: list[dict[str, object]] = []
        for period in self.periods:
            for h in period.holdings:
                rows.append(
                    {
                        "period_end": period.period_end,
                        "symbol": h.symbol,
                        "weight": h.weight,
                        "return_pct": h.return_pct,
                        "weighted_contribution": h.weight * h.return_pct,
                        "portfolio_gross_return": period.gross_return,
                        "portfolio_cost": period.cost,
                        "portfolio_net_return": period.net_return,
                        "turnover": period.turnover,
                        "nav": period.nav,
                    }
                )
        return pd.DataFrame(rows)

    def period_summary(self) -> pd.DataFrame:
        """Return one row per rebalance period with portfolio-level P&L.

        Columns: period_end, n_holdings, gross_return, cost, net_return, turnover, nav.
        """
        rows: list[dict[str, object]] = [
            {
                "period_end": p.period_end,
                "n_holdings": len(p.holdings),
                "gross_return": p.gross_return,
                "cost": p.cost,
                "net_return": p.net_return,
                "turnover": p.turnover,
                "nav": p.nav,
            }
            for p in self.periods
        ]
        return pd.DataFrame(rows)


class BacktestConfig(BaseModel):
    """Configuration for a momentum backtest run."""

    formation_months: int = Field(default=12)
    skip_months: int = Field(default=1)
    top_quantile: float = Field(default=0.2)
    weight_scheme: str = Field(default="equal")
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    transaction_cost_bps: float = Field(default=15.0)
    # Phase 3.5 improvements
    adtv_63d_min_thb: float = Field(default=MIN_ADTV_63D_THB)
    ema_trend_window: int = Field(default=EMA_TREND_WINDOW)
    safe_mode_max_equity: float = Field(default=SAFE_MODE_MAX_EQUITY)
    n_holdings_min: int = Field(default=BULL_MODE_N_HOLDINGS_MIN)
    n_holdings_max: int = Field(default=BULL_MODE_N_HOLDINGS_MAX)
    buffer_rank_threshold: float = Field(default=BUFFER_RANK_THRESHOLD)


class BacktestResult(BaseModel):
    """JSON-serialisable result object for public-safe backtest outputs."""

    config: BacktestConfig
    generated_at: str
    equity_curve: dict[str, float]
    annual_returns: dict[str, float]
    positions: dict[str, list[str]]
    turnover: dict[str, float]
    metrics: dict[str, float]
    monthly_report: MonthlyRebalanceReport

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
        self._regime: RegimeDetector = RegimeDetector()

    def _apply_adtv_filter(
        self,
        cross_section: pd.DataFrame,
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
        asof: pd.Timestamp,
        min_adtv_thb: float,
        lookback_days: int = 63,
    ) -> pd.DataFrame:
        """Remove symbols with 63-day trailing ADTV below *min_adtv_thb* THB.

        ADTV = mean(close × volume) over the last *lookback_days* calendar bars
        available at *asof* (no look-ahead).  Symbols absent from *prices* or
        *volumes* are conservatively dropped.
        """
        keep: list[str] = []
        for sym in cross_section.index:
            if sym not in prices.columns or sym not in volumes.columns:
                continue
            close_hist: pd.Series = prices[sym].loc[:asof].dropna().tail(lookback_days)
            vol_hist: pd.Series = volumes[sym].loc[:asof].dropna().tail(lookback_days)
            min_len = min(len(close_hist), len(vol_hist))
            if min_len == 0:
                continue
            adtv: float = float((close_hist.iloc[-min_len:] * vol_hist.iloc[-min_len:]).mean())
            if adtv >= min_adtv_thb:
                keep.append(sym)
        excluded: int = len(cross_section) - len(keep)
        if excluded:
            logger.debug("ADTV filter excluded %d symbols at %s", excluded, asof)
        return cross_section.loc[keep]

    def _apply_buffer_logic(
        self,
        current_holdings: list[str],
        candidates: list[str],
        cross_section: pd.DataFrame,
        buffer_threshold: float,
    ) -> list[str]:
        """Retain existing holdings unless a replacement ranks buffer_threshold better.

        Uses cross-sectional percentile rank (0–1) of the composite z-score so
        comparisons are scale-invariant across rebalance dates.
        """
        if not current_holdings:
            return candidates

        composite: pd.Series = cross_section.mean(axis=1)
        pct_rank: pd.Series = composite.rank(pct=True)

        candidate_set: set[str] = set(candidates)
        final: list[str] = []

        for sym in current_holdings:
            if sym in candidate_set:
                final.append(sym)
                candidate_set.discard(sym)
            else:
                current_rank: float = float(pct_rank.get(sym, 0.0))
                best_replacement_rank: float = max(
                    (float(pct_rank.get(c, 0.0)) for c in candidate_set), default=0.0
                )
                if best_replacement_rank - current_rank >= buffer_threshold:
                    pass  # evict — will be replaced by top candidates below
                else:
                    final.append(sym)

        # Fill remaining slots with highest-ranked new candidates not yet included.
        final_set: set[str] = set(final)
        new_entries: list[str] = [c for c in candidates if c not in final_set]
        final.extend(new_entries)
        return final

    def _select_holdings(
        self,
        cross_section: pd.DataFrame,
        config: BacktestConfig,
        current_holdings: list[str],
    ) -> list[str]:
        """Select 80–100 holdings using composite z-score + buffer logic.

        Falls back to top_quantile selection when cross_section is too small to
        fill n_holdings_min, ensuring at least one symbol is always returned.
        """
        if cross_section.empty:
            return []
        composite: pd.Series = cross_section.mean(axis=1)
        # Take top n_holdings_max candidates by raw composite score.
        n_max: int = min(config.n_holdings_max, len(composite))
        candidates: list[str] = [str(s) for s in composite.nlargest(n_max).index]
        # Apply buffer to reduce unnecessary churn.
        buffered: list[str] = self._apply_buffer_logic(
            current_holdings, candidates, cross_section, config.buffer_rank_threshold
        )
        # Enforce bounds: cap at n_holdings_max, ensure at least n_holdings_min.
        buffered = buffered[: config.n_holdings_max]
        if len(buffered) < config.n_holdings_min and len(candidates) >= config.n_holdings_min:
            # Top-up from candidates preserving order.
            extra: list[str] = [c for c in candidates if c not in set(buffered)]
            buffered.extend(extra[: config.n_holdings_min - len(buffered)])
        return buffered if buffered else candidates[:1]

    def _compute_mode(
        self,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        ema_window: int,
    ) -> RegimeState:
        """Return BULL when SET:SET is above its EMA-*ema_window*, else BEAR."""
        if self._regime.is_bull_market(index_prices, asof, window=ema_window):
            return RegimeState.BULL
        return RegimeState.BEAR

    def run(
        self,
        feature_panel: pd.DataFrame,
        prices: pd.DataFrame,
        config: BacktestConfig,
        volumes: pd.DataFrame | None = None,
        index_prices: pd.Series | None = None,
    ) -> BacktestResult:
        """Run the monthly momentum backtest.

        Args:
            feature_panel: MultiIndex feature panel indexed by `(date, symbol)`.
            prices: Wide close-price matrix indexed by date, columns = symbols.
            config: Backtest configuration.
            volumes: Optional wide daily-volume matrix (same shape as prices).
                     Required for the ADTV hard filter; skipped with a warning if None.
            index_prices: Optional SET:SET daily close series for EMA-200 trend filter.
                          Stays in Bull Mode for all periods when None.

        Returns:
            Public-safe backtest result.

        Raises:
            BacktestError: If required data is missing or no observations produced.
        """

        if feature_panel.empty or prices.empty:
            raise BacktestError("Feature panel and prices are required to run a backtest.")

        if volumes is None:
            logger.warning("volumes not provided — ADTV filter skipped")
        if index_prices is None:
            logger.warning("index_prices not provided — EMA trend filter skipped (Bull Mode)")

        rebalance_dates: list[pd.Timestamp] = list(
            feature_panel.index.get_level_values("date").unique()
        )
        if len(rebalance_dates) < 2:
            raise BacktestError("At least two rebalance dates are required.")

        current_weights: pd.Series = pd.Series(dtype=float)
        current_holdings: list[str] = []
        nav: float = 100.0
        equity_curve: dict[str, float] = {}
        annual_returns: dict[str, float] = {}
        positions: dict[str, list[str]] = {}
        turnover_map: dict[str, float] = {}
        period_reports: list[MonthlyPeriodReport] = []

        for current_date, next_date in zip(rebalance_dates[:-1], rebalance_dates[1:], strict=False):
            # Slice cross-section at current rebalance date.
            try:
                cross_section: pd.DataFrame = feature_panel.xs(current_date, level="date")
            except KeyError:
                continue
            if cross_section.empty:
                continue

            # Apply ADTV hard filter before ranking.
            if volumes is not None:
                cross_section = self._apply_adtv_filter(
                    cross_section, prices, volumes, current_date, config.adtv_63d_min_thb
                )
            if cross_section.empty:
                continue

            # Determine market regime (Mode A: Bull / Mode B: Bear).
            mode: RegimeState = (
                self._compute_mode(index_prices, current_date, config.ema_trend_window)
                if index_prices is not None
                else RegimeState.BULL
            )

            # Select 80-100 holdings with buffer logic.
            selected: list[str] = self._select_holdings(cross_section, config, current_holdings)

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

            # Safe Mode (Mode B): scale equity exposure down, remainder is cash.
            if mode is RegimeState.BEAR:
                target_weights = target_weights * config.safe_mode_max_equity

            turnover: float = self._scheduler.compute_turnover(current_weights, target_weights)
            prices_window: pd.DataFrame = prices[selected].loc[current_date:next_date]
            if len(prices_window) < 2:
                logger.warning(
                    "Insufficient price data for period — skipping",
                    extra={"current_date": str(current_date), "next_date": str(next_date)},
                )
                continue
            period_returns: pd.Series = prices_window.iloc[-1] / prices_window.iloc[0] - 1.0
            aligned_returns: pd.Series = period_returns.reindex(target_weights.index).fillna(0.0)
            gross_return: float = float(aligned_returns.dot(target_weights))
            cost: float = turnover * (config.transaction_cost_bps / 10_000.0)
            nav *= 1.0 + gross_return - cost

            date_key: str = next_date.strftime("%Y-%m-%d")
            equity_curve[date_key] = nav
            positions[date_key] = selected
            turnover_map[date_key] = turnover
            annual_returns.setdefault(next_date.strftime("%Y"), 0.0)
            annual_returns[next_date.strftime("%Y")] += gross_return - cost
            current_weights = target_weights
            current_holdings = selected

            holdings: list[MonthlyHoldingRecord] = [
                MonthlyHoldingRecord(
                    symbol=sym,
                    weight=float(target_weights[sym]),
                    return_pct=float(aligned_returns[sym]),
                )
                for sym in target_weights.index
            ]
            period_reports.append(
                MonthlyPeriodReport(
                    period_end=date_key,
                    holdings=holdings,
                    gross_return=gross_return,
                    cost=cost,
                    net_return=gross_return - cost,
                    turnover=turnover,
                    nav=nav,
                    mode=str(mode),
                )
            )

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
            monthly_report=MonthlyRebalanceReport(periods=period_reports),
        )
        self._store.save("backtest_equity_curve", equity_series.to_frame(name="nav"))
        logger.info("Completed backtest", extra={"periods": len(equity_curve)})
        return result


__all__: list[str] = [
    "BacktestConfig",
    "BacktestResult",
    "MomentumBacktest",
    "MonthlyHoldingRecord",
    "MonthlyPeriodReport",
    "MonthlyRebalanceReport",
]
