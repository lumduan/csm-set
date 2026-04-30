"""Backtest models and momentum backtest engine."""

import logging
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field

from csm.config.constants import (
    BUFFER_RANK_THRESHOLD,
    BULL_MODE_N_HOLDINGS_MAX,
    BULL_MODE_N_HOLDINGS_MIN,
    EMA_SLOPE_LOOKBACK_DAYS,
    EMA_TREND_WINDOW,
    EXIT_EMA_WINDOW,
    EXIT_RANK_FLOOR,
    FAST_REENTRY_EMA_WINDOW,
    MIN_ADTV_63D_THB,
    REBALANCE_EVERY_N,
    SAFE_MODE_MAX_EQUITY,
    SECTOR_MAX_WEIGHT,
    TIMEZONE,
    VOL_LOOKBACK_DAYS,
    VOL_SCALE_CAP,
    VOL_TARGET_ANNUAL,
)
from csm.data.store import ParquetStore
from csm.portfolio.construction import PortfolioConstructor, SelectionConfig
from csm.portfolio.optimizer import WeightOptimizer
from csm.portfolio.rebalance import RebalanceScheduler
from csm.portfolio.vol_scaler import VolScalingConfig
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
    # Phase 3.6 improvements
    bear_full_cash: bool = Field(default=True)  # 0% equity when EMA slope is negative
    ema_slope_lookback_days: int = Field(default=EMA_SLOPE_LOOKBACK_DAYS)
    # Phase 3.7 improvements
    rs_filter_mode: str = Field(default="entry_only")  # "off" | "entry_only" | "all"
    rs_lookback_months: int = Field(default=12)
    fast_reentry_ema_window: int = Field(default=FAST_REENTRY_EMA_WINDOW)
    # Phase 3.8 improvements — fast-exit overlay (engages safe-mode equity in BULL when SET<EMA100)
    exit_ema_window: int = Field(default=EXIT_EMA_WINDOW)
    # Phase 3.9 improvements — turnover control, vol scaling, sector neutralisation
    # 1=monthly, 2=bimonthly, 3=quarterly
    rebalance_every_n: int = Field(default=REBALANCE_EVERY_N)
    exit_rank_floor: float = Field(default=EXIT_RANK_FLOOR)  # evict holdings ranked below this pct
    vol_scaling_enabled: bool = Field(default=True)  # FLIPPED: on by default
    vol_lookback_days: int = Field(default=VOL_LOOKBACK_DAYS)
    vol_target_annual: float = Field(default=VOL_TARGET_ANNUAL)
    vol_scale_cap: float = Field(default=VOL_SCALE_CAP)
    vol_scaling_config: VolScalingConfig | None = Field(default=None)
    sector_max_weight: float = Field(default=SECTOR_MAX_WEIGHT)


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

    def __init__(
        self,
        store: ParquetStore,
        portfolio_constructor: PortfolioConstructor | None = None,
    ) -> None:
        self._store: ParquetStore = store
        self._portfolio_constructor: PortfolioConstructor = (
            portfolio_constructor or PortfolioConstructor()
        )
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

    def _select_holdings(
        self,
        cross_section: pd.DataFrame,
        config: BacktestConfig,
        current_holdings: list[str],
        *,
        entry_mask: set[str] | None = None,
    ) -> list[str]:
        """Select 40–60 holdings using composite z-score + buffer logic.

        Delegates to :class:`PortfolioConstructor.select` (Phase 4.1).
        """
        sel_config: SelectionConfig = SelectionConfig(
            n_holdings_min=config.n_holdings_min,
            n_holdings_max=config.n_holdings_max,
            buffer_rank_threshold=config.buffer_rank_threshold,
            exit_rank_floor=config.exit_rank_floor,
        )
        result = self._portfolio_constructor.select(
            cross_section, current_holdings, sel_config, entry_mask=entry_mask
        )
        return result.selected

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

    def _has_negative_ema_slope(
        self,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        ema_window: int,
        slope_lookback: int,
    ) -> bool:
        """Return True when EMA-*ema_window* is falling at *asof*."""
        return self._regime.has_negative_ema_slope(
            index_prices, asof, window=ema_window, slope_lookback=slope_lookback
        )

    # ━ Phase 3.7: entry-only RS filter + EMA50 fast re-entry ━━━━━━━━━

    def _apply_relative_strength_filter(
        self,
        cross_section: pd.DataFrame,
        prices: pd.DataFrame,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        lookback_months: int = 12,
    ) -> set[str]:
        """Compute the set of stocks whose 12M return beats or matches the SET index.

        When ``rs_filter_mode`` is ``"entry_only"`` this set acts as a gate on
        new entries — candidates are drawn from it, but existing holdings are NOT
        evicted by it.  When ``"all"`` (Phase 3.6 behaviour) the gate is applied
        to everything.

        Returns an empty set when benchmark history is insufficient (conservative
        — re-opens the gate entirely rather than closing it).
        """
        lookback_days: int = lookback_months * 21
        idx_hist: pd.Series = (
            index_prices.loc[index_prices.index <= asof].dropna().tail(lookback_days)
        )
        if len(idx_hist) < 2:
            logger.debug("RS filter skipped — insufficient benchmark history at %s", asof)
            return set()
        index_return: float = float(idx_hist.iloc[-1] / idx_hist.iloc[0] - 1.0)
        passing: set[str] = set()
        for sym in cross_section.index:
            if sym not in prices.columns:
                continue
            hist: pd.Series = prices[sym].loc[:asof].dropna().tail(lookback_days)
            if len(hist) < 2:
                continue
            stock_return: float = float(hist.iloc[-1] / hist.iloc[0] - 1.0)
            if stock_return >= index_return:
                passing.add(str(sym))
        excluded: int = len(cross_section) - len(passing)
        if excluded:
            logger.debug("RS filter excluded %d symbols at %s", excluded, asof)
        return passing

    def _is_fast_reentry(
        self,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        ema_window: int = 50,
    ) -> bool:
        """Return True when SET > EMA-*ema_window* — override Bear mode to full equity.

        Provides a faster re-entry trigger after crashes than waiting for
        EMA-200 to recover.
        """
        return self._regime.is_bull_market(index_prices, asof, window=ema_window)

    # ━ Phase 3.8: fast-exit overlay (SET < EMA100 inside BULL → safe-mode equity) ━━━━

    def _is_fast_exit(
        self,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        ema_window: int,
    ) -> bool:
        """Return True when SET is below EMA-*ema_window* at *asof*.

        Used as an overlay inside the BULL regime: when the index drops below
        a faster EMA (default 100) while still above EMA-200, equity is
        scaled down to ``safe_mode_max_equity`` to trim drawdown ahead of a
        full bear-regime flip.
        """
        return not self._regime.is_bull_market(index_prices, asof, window=ema_window)

    # ━ Phase 3.9: sector cap, vol scaling ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _apply_sector_cap(
        self,
        selected: list[str],
        cross_section: pd.DataFrame,
        sector_map: dict[str, str],
        max_weight: float,
    ) -> list[str]:
        """Trim *selected* so no single sector exceeds *max_weight* equal-weight fraction.

        Drops the lowest-ranked (by composite z-score) stocks within any over-weight
        sector until the sector's fraction ≤ max_weight. Returns the pruned list in
        the original selection order.
        """
        if not selected or max_weight >= 1.0:
            return selected

        composite: pd.Series = cross_section.mean(axis=1)
        sector_groups: dict[str, list[str]] = {}
        for sym in selected:
            sector: str = sector_map.get(sym, "__unknown__")
            sector_groups.setdefault(sector, []).append(sym)

        evict: set[str] = set()
        total: int = len(selected)
        max_count: int = max(1, int(total * max_weight))  # max stocks allowed per sector
        for _sector, members in sector_groups.items():
            while sum(1 for m in members if m not in evict) > max_count:
                ranked: list[str] = sorted(
                    [m for m in members if m not in evict],
                    key=lambda s: float(composite.get(s, float("-inf"))),
                )
                if not ranked:
                    break
                evict.add(ranked[0])  # drop lowest composite in the overweight sector

        pruned: list[str] = [s for s in selected if s not in evict]
        if len(evict) > 0:
            logger.debug("Sector cap evicted %d symbols", len(evict))
        return pruned

    def _compute_portfolio_vol(
        self,
        prices: pd.DataFrame,
        holdings: list[str],
        asof: pd.Timestamp,
        lookback_days: int,
    ) -> float:
        """Return annualised equal-weight portfolio daily return std.

        Computes over the last *lookback_days* bars ending at *asof*.
        Returns NaN when fewer than 21 bars are available.
        """
        cols: list[str] = [h for h in holdings if h in prices.columns]
        if not cols:
            return float("nan")
        hist: pd.DataFrame = prices[cols].loc[prices.index <= asof].tail(lookback_days)
        if len(hist) < 21:
            return float("nan")
        daily_ret: pd.Series = hist.pct_change().dropna(how="all").mean(axis=1)
        return float(daily_ret.std() * (252**0.5))

    def _apply_vol_scaling(
        self,
        prices: pd.DataFrame,
        holdings: list[str],
        asof: pd.Timestamp,
        equity_fraction: float,
        lookback_days: int,
        vol_target: float,
        vol_scale_cap: float,
    ) -> float:
        """Scale *equity_fraction* by (vol_target / realized_vol), clamped to vol_scale_cap.

        Returns *equity_fraction* unchanged when realized vol is NaN (insufficient history).
        Result is capped at 1.0 — no leverage is applied.
        """
        realized_vol: float = self._compute_portfolio_vol(prices, holdings, asof, lookback_days)
        if realized_vol != realized_vol or realized_vol <= 0.0:  # NaN guard
            return equity_fraction
        raw_scale: float = vol_target / realized_vol
        vol_scale: float = min(max(raw_scale, 0.0), vol_scale_cap)
        scaled: float = min(equity_fraction * vol_scale, 1.0)
        logger.debug(
            "Vol scaling at %s: rv=%.3f tgt=%.3f scale=%.3f → eq %.3f→%.3f",
            asof,
            realized_vol,
            vol_target,
            vol_scale,
            equity_fraction,
            scaled,
        )
        return scaled

    def run(
        self,
        feature_panel: pd.DataFrame,
        prices: pd.DataFrame,
        config: BacktestConfig,
        volumes: pd.DataFrame | None = None,
        index_prices: pd.Series | None = None,
        sector_map: dict[str, str] | None = None,
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
            sector_map: Optional mapping from symbol to sector code (e.g. "BANK").
                        When provided, enables the sector weight cap in Phase 3.9.

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
        current_mode: RegimeState = RegimeState.BULL
        nav: float = 100.0
        equity_curve: dict[str, float] = {}
        annual_returns: dict[str, float] = {}
        positions: dict[str, list[str]] = {}
        turnover_map: dict[str, float] = {}
        period_reports: list[MonthlyPeriodReport] = []

        for rebalance_idx, (current_date, next_date) in enumerate(
            zip(rebalance_dates[:-1], rebalance_dates[1:], strict=False)
        ):
            date_key: str = next_date.strftime("%Y-%m-%d")

            # Phase 3.9: skip rebalancing on non-rebalance periods; accrue at current weights.
            if config.rebalance_every_n > 1 and rebalance_idx % config.rebalance_every_n != 0:
                if not current_holdings:
                    continue
                hold_cols: list[str] = [h for h in current_holdings if h in prices.columns]
                if not hold_cols:
                    continue
                prices_window_hold: pd.DataFrame = prices[hold_cols].loc[current_date:next_date]
                if len(prices_window_hold) < 2:
                    continue
                hold_returns: pd.Series = (
                    prices_window_hold.iloc[-1] / prices_window_hold.iloc[0] - 1.0
                )
                hold_aligned: pd.Series = hold_returns.reindex(current_weights.index).fillna(0.0)
                gross_return_hold: float = float(hold_aligned.dot(current_weights))
                nav *= 1.0 + gross_return_hold
                equity_curve[date_key] = nav
                positions[date_key] = current_holdings
                turnover_map[date_key] = 0.0
                annual_returns.setdefault(next_date.strftime("%Y"), 0.0)
                annual_returns[next_date.strftime("%Y")] += gross_return_hold
                hold_records: list[MonthlyHoldingRecord] = [
                    MonthlyHoldingRecord(
                        symbol=sym,
                        weight=float(current_weights[sym]),
                        return_pct=float(hold_aligned.get(sym, 0.0)),
                    )
                    for sym in current_weights.index
                ]
                period_reports.append(
                    MonthlyPeriodReport(
                        period_end=date_key,
                        holdings=hold_records,
                        gross_return=gross_return_hold,
                        cost=0.0,
                        net_return=gross_return_hold,
                        turnover=0.0,
                        nav=nav,
                        mode=str(current_mode),
                    )
                )
                continue

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

            # Compute RS entry gate — stocks eligible for new entry (Phase 3.7).
            rs_pass: set[str] | None = None
            if config.rs_filter_mode != "off" and index_prices is not None:
                rs_pass = self._apply_relative_strength_filter(
                    cross_section,
                    prices,
                    index_prices,
                    current_date,
                    lookback_months=config.rs_lookback_months,
                )
                if config.rs_filter_mode == "all":
                    # Phase 3.6 behaviour — gate applied to everything.
                    if rs_pass:
                        cross_section = cross_section.loc[cross_section.index.isin(rs_pass)]
                    if cross_section.empty:
                        continue

            # Determine market regime (Bull / Bear).
            current_mode = (
                self._compute_mode(index_prices, current_date, config.ema_trend_window)
                if index_prices is not None
                else RegimeState.BULL
            )

            # Select 40-60 holdings with buffer logic and entry-only RS gate.
            entry_gate: set[str] | None = rs_pass if config.rs_filter_mode == "entry_only" else None
            selected: list[str] = self._select_holdings(
                cross_section,
                config,
                current_holdings,
                entry_mask=entry_gate,
            )

            # Phase 3.9: apply sector weight cap when sector_map is provided.
            if sector_map is not None:
                selected = self._apply_sector_cap(
                    selected, cross_section, sector_map, config.sector_max_weight
                )

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

            # Phase 3.8 equity fraction. In BULL the EMA100 fast-exit overlay
            # scales equity down ahead of a full regime flip; in BEAR the EMA50
            # fast re-entry can override back to full equity.
            # Priority — BULL: 1) SET<EMA100 → safe_mode (0.20)  2) BULL → 100%
            #            BEAR: 1) SET>EMA50 → 100%  2) Strong Bear → 0%  3) Weak Bear → 20%
            if index_prices is not None:
                equity_fraction: float
                if current_mode is RegimeState.BULL:
                    if self._is_fast_exit(index_prices, current_date, config.exit_ema_window):
                        equity_fraction = config.safe_mode_max_equity
                        logger.debug(
                            "fast-exit overlay engaged at %s (SET<EMA%d)",
                            current_date,
                            config.exit_ema_window,
                        )
                    else:
                        equity_fraction = 1.0
                elif self._is_fast_reentry(
                    index_prices, current_date, config.fast_reentry_ema_window
                ):
                    equity_fraction = 1.0
                elif config.bear_full_cash and self._has_negative_ema_slope(
                    index_prices,
                    current_date,
                    config.ema_trend_window,
                    config.ema_slope_lookback_days,
                ):
                    equity_fraction = 0.0
                else:
                    equity_fraction = config.safe_mode_max_equity

                # Phase 3.9: continuous vol scaling overlay (only when enabled).
                if config.vol_scaling_enabled and equity_fraction > 0.0 and current_holdings:
                    equity_fraction = self._apply_vol_scaling(
                        prices,
                        current_holdings,
                        current_date,
                        equity_fraction,
                        config.vol_lookback_days,
                        config.vol_target_annual,
                        config.vol_scale_cap,
                    )

                target_weights = target_weights * equity_fraction

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
                    mode=str(current_mode),
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
