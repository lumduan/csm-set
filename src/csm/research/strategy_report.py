"""Pure builder for the TradingView-style :class:`StrategyReport` payload.

:func:`build_strategy_report` is the single entry point: it consumes
already-paired closed trades, an equity series, an optional benchmark
series, and the initial capital, and returns a fully-populated
:class:`StrategyReport`. The function performs no I/O and no logging
beyond DEBUG; it is safe to call from the live-refresh hook on every
trading day.

All numeric outputs are :class:`decimal.Decimal`. Equity / benchmark
series remain ``float`` (pandas / numpy realities) until they cross the
report boundary, at which point each value is wrapped in
``Decimal(str(...))`` to avoid binary-float artefacts.

Sub-builders (`_compute_*`) are private — they exist to keep the file
under the 400-line budget and to make the structure of the report
obvious to readers. They have no external callers.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from csm.execution.trade_pairing import ClosedTrade
from csm.research.exceptions import ReportError
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
    PositionScope,
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
from csm.risk.drawdown import DrawdownAnalyzer
from csm.risk.trade_metrics import (
    avg_bars_in_losing_trades,
    avg_bars_in_trades,
    avg_bars_in_winning_trades,
    avg_losing_trade,
    avg_winning_trade,
    expected_payoff,
    gross_loss,
    gross_profit,
    largest_losing_trade,
    largest_winning_trade,
    losing_trades,
    net_pnl,
    outliers_count,
    outliers_pnl,
    pct_profitable,
    profit_factor,
    ratio_avg_win_avg_loss,
    winning_trades,
)

logger: logging.Logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR: int = 252
ZERO: Decimal = Decimal("0")
DEFAULT_BUCKET_LOW: Decimal = Decimal("-0.10")
DEFAULT_BUCKET_HIGH: Decimal = Decimal("0.10")
DEFAULT_BUCKET_WIDTH: Decimal = Decimal("0.01")


def build_strategy_report(
    *,
    trades: Sequence[ClosedTrade],
    equity: pd.Series,
    initial_capital: Decimal,
    as_of: datetime,
    benchmark: pd.Series | None = None,
    commission_paid: Decimal | None = None,
    currency: str = "THB",
) -> StrategyReport:
    """Build a :class:`StrategyReport` from paired trades + an equity series.

    Args:
        trades: Already-paired round-trip trades. Empty input is allowed —
            the headline reports ``total_trades=0`` and trade-derived
            sections fall to documented zero values.
        equity: Strategy equity series indexed by tz-aware UTC dates.
        initial_capital: NAV at inception.
        as_of: Report timestamp; must be tz-aware UTC.
        benchmark: Optional buy-and-hold benchmark NAV series (matching
            initial capital). Omit to suppress benchmark comparison.
        commission_paid: Optional override for total commission. Defaults to
            the sum across ``trades``.
        currency: ISO-style currency code (defaults to ``"THB"``).

    Returns:
        Fully populated :class:`StrategyReport`.

    Raises:
        ReportError: When ``equity`` is empty or ``as_of`` is tz-naive.
    """

    if as_of.tzinfo is None:
        msg = "build_strategy_report: as_of must be tz-aware (UTC)"
        raise ReportError(msg)
    if equity.empty:
        msg = "build_strategy_report: equity series must be non-empty"
        raise ReportError(msg)

    if commission_paid is None:
        commission_paid = sum((t.commission for t in trades), start=ZERO)

    as_of_utc: datetime = as_of.astimezone(UTC)
    headline: Headline = _compute_headline(
        trades=trades, equity=equity, initial_capital=initial_capital
    )
    profit_structure: ProfitStructure = _compute_profit_structure(
        trades=trades, commission_paid=commission_paid
    )
    returns: Returns = _compute_returns(
        trades=trades,
        initial_capital=initial_capital,
        commission_paid=commission_paid,
    )
    risk_adjusted: RiskAdjusted = _compute_risk_adjusted(equity=equity)
    trades_analysis: TradesAnalysis = _compute_pnl_distribution(trades=trades)
    details: Details = _compute_details(trades=trades)
    capital_efficiency: CapitalEfficiency = _compute_capital_efficiency(
        trades=trades, equity=equity, initial_capital=initial_capital
    )
    runups_drawdowns: RunUpsDrawdowns = _compute_runups_drawdowns(
        equity=equity, initial_capital=initial_capital
    )
    benchmark_comparison: BenchmarkComparison | None = None
    benchmark_curve: list[BenchmarkPoint] = []
    if benchmark is not None and not benchmark.empty:
        benchmark_comparison = _compute_benchmark_comparison(
            equity=equity, benchmark=benchmark, initial_capital=initial_capital
        )
        benchmark_curve = [
            BenchmarkPoint(date=_to_utc(idx), value=_to_decimal(value))
            for idx, value in benchmark.items()
        ]
    trade_log: list[TradeLogEntry] = [
        TradeLogEntry(
            entry_time=t.entry_time,
            exit_time=t.exit_time,
            symbol=t.symbol,
            side=t.side,
            qty=t.qty,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            realized_pnl=t.realized_pnl,
            duration_bars=t.duration_bars,
            commission=t.commission,
        )
        for t in trades
    ]

    return StrategyReport(
        as_of=as_of_utc,
        currency=currency,
        initial_capital=initial_capital,
        headline=headline,
        profit_structure=profit_structure,
        returns=returns,
        benchmark_comparison=benchmark_comparison,
        risk_adjusted=risk_adjusted,
        trades_analysis=trades_analysis,
        details=details,
        capital_efficiency=capital_efficiency,
        runups_drawdowns=runups_drawdowns,
        trades=trade_log,
        benchmark_equity_curve=benchmark_curve,
    )


def _compute_headline(
    *,
    trades: Sequence[ClosedTrade],
    equity: pd.Series,
    initial_capital: Decimal,
) -> Headline:
    total_pnl: Decimal = _to_decimal(equity.iloc[-1]) - initial_capital
    total_pnl_pct: Decimal = _safe_div(total_pnl, initial_capital)
    max_dd_pct: Decimal = _to_decimal(DrawdownAnalyzer().max_drawdown(equity))
    max_dd: Decimal = max_dd_pct * initial_capital
    return Headline(
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        max_equity_drawdown=max_dd,
        max_equity_drawdown_pct=max_dd_pct,
        total_trades=len(trades),
        profitable_trades=len(winning_trades(trades)),
        profitable_pct=pct_profitable(trades),
        profit_factor=profit_factor(trades),
    )


def _compute_profit_structure(
    *, trades: Sequence[ClosedTrade], commission_paid: Decimal
) -> ProfitStructure:
    return ProfitStructure(
        total_profit=gross_profit(trades),
        open_pnl=ZERO,
        total_loss=gross_loss(trades),
        commission=commission_paid,
        net_pnl=net_pnl(trades),
    )


def _compute_returns(
    *,
    trades: Sequence[ClosedTrade],
    initial_capital: Decimal,
    commission_paid: Decimal,
) -> Returns:
    def row(scoped: Sequence[ClosedTrade]) -> ReturnsRow:
        return ReturnsRow(
            initial_capital=initial_capital,
            open_pnl=ZERO,
            net_pnl=net_pnl(scoped),
            gross_profit=gross_profit(scoped),
            gross_loss=gross_loss(scoped),
            profit_factor=profit_factor(scoped),
            commission_paid=sum((t.commission for t in scoped), start=ZERO)
            if scoped is not trades
            else commission_paid,
            expected_payoff=expected_payoff(scoped),
        )

    long_trades: list[ClosedTrade] = [t for t in trades if t.side == "LONG"]
    short_trades: list[ClosedTrade] = [t for t in trades if t.side == "SHORT"]
    return Returns(all=row(trades), long=row(long_trades), short=row(short_trades))


def _compute_risk_adjusted(*, equity: pd.Series) -> RiskAdjusted:
    if len(equity) < 2:
        return RiskAdjusted(sharpe_ratio=ZERO, sortino_ratio=ZERO)
    returns: pd.Series = equity.pct_change().dropna()
    if returns.empty:
        return RiskAdjusted(sharpe_ratio=ZERO, sortino_ratio=ZERO)
    mean: float = float(returns.mean())
    std: float = float(returns.std(ddof=1))
    annualisation: float = float(Decimal(TRADING_DAYS_PER_YEAR).sqrt())
    sharpe: Decimal = _to_decimal((mean / std) * annualisation) if std > 0 else ZERO
    downside: pd.Series = returns[returns < 0.0]
    downside_std: float = float(downside.std(ddof=1)) if not downside.empty else 0.0
    sortino: Decimal = (
        _to_decimal((mean / downside_std) * annualisation) if downside_std > 0 else ZERO
    )
    return RiskAdjusted(sharpe_ratio=sharpe, sortino_ratio=sortino)


def _compute_pnl_distribution(*, trades: Sequence[ClosedTrade]) -> TradesAnalysis:
    buckets: list[PnLDistributionBucket] = []
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    avg_loss_pct: Decimal = ZERO
    avg_profit_pct: Decimal = ZERO
    if trades:
        returns: list[Decimal] = [_safe_div(t.realized_pnl, t.entry_price * t.qty) for t in trades]
        wins = sum(1 for r in returns if r > ZERO)
        losses = sum(1 for r in returns if r < ZERO)
        breakeven = len(returns) - wins - losses
        if wins:
            avg_profit_pct = sum((r for r in returns if r > ZERO), start=ZERO) / Decimal(wins)
        if losses:
            avg_loss_pct = sum((r for r in returns if r < ZERO), start=ZERO) / Decimal(losses)
        buckets = _bucket_returns(returns)
    return TradesAnalysis(
        pnl_distribution=buckets,
        win_loss_split=WinLossSplit(wins=wins, losses=losses, breakeven=breakeven),
        avg_loss_pct=avg_loss_pct,
        avg_profit_pct=avg_profit_pct,
    )


def _bucket_returns(returns: Sequence[Decimal]) -> list[PnLDistributionBucket]:
    """Bucket per-trade returns into the documented 1%-wide histogram bins."""

    edges: list[Decimal] = []
    current: Decimal = DEFAULT_BUCKET_LOW
    while current < DEFAULT_BUCKET_HIGH:
        edges.append(current)
        current += DEFAULT_BUCKET_WIDTH
    edges.append(DEFAULT_BUCKET_HIGH)
    counts: list[int] = [0] * (len(edges) - 1)
    overflow_low: int = 0
    overflow_high: int = 0
    for r in returns:
        if r < edges[0]:
            overflow_low += 1
            continue
        if r >= edges[-1]:
            overflow_high += 1
            continue
        for i in range(len(edges) - 1):
            if edges[i] <= r < edges[i + 1]:
                counts[i] += 1
                break
    buckets: list[PnLDistributionBucket] = []
    if overflow_low:
        buckets.append(
            PnLDistributionBucket(
                bucket_low_pct=DEFAULT_BUCKET_LOW - DEFAULT_BUCKET_WIDTH,
                bucket_high_pct=DEFAULT_BUCKET_LOW,
                count=overflow_low,
                kind="loss",
            )
        )
    for i, count in enumerate(counts):
        if count == 0:
            continue
        low: Decimal = edges[i]
        high: Decimal = edges[i + 1]
        kind: str = "loss" if high <= ZERO else "profit" if low >= ZERO else "breakeven"
        buckets.append(
            PnLDistributionBucket(
                bucket_low_pct=low,
                bucket_high_pct=high,
                count=count,
                kind=kind,  # type: ignore[arg-type]
            )
        )
    if overflow_high:
        buckets.append(
            PnLDistributionBucket(
                bucket_low_pct=DEFAULT_BUCKET_HIGH,
                bucket_high_pct=DEFAULT_BUCKET_HIGH + DEFAULT_BUCKET_WIDTH,
                count=overflow_high,
                kind="profit",
            )
        )
    return buckets


def _compute_details(*, trades: Sequence[ClosedTrade]) -> Details:
    def row(scoped: Sequence[ClosedTrade]) -> DetailsRow:
        wins: list[ClosedTrade] = winning_trades(scoped)
        losses: list[ClosedTrade] = losing_trades(scoped)
        gp: Decimal = gross_profit(scoped)
        gl: Decimal = gross_loss(scoped)
        largest_win: Decimal = largest_winning_trade(scoped)
        largest_loss: Decimal = largest_losing_trade(scoped)
        return DetailsRow(
            total_trades=len(scoped),
            total_open_trades=0,
            winning_trades=len(wins),
            losing_trades=len(losses),
            percent_profitable=pct_profitable(scoped),
            avg_pnl=expected_payoff(scoped),
            avg_winning_trade=avg_winning_trade(scoped),
            avg_losing_trade=avg_losing_trade(scoped),
            ratio_avg_win_avg_loss=ratio_avg_win_avg_loss(scoped),
            largest_winning_trade=largest_win,
            largest_winning_trade_pct=_safe_div(
                largest_win,
                _entry_notional(_find_trade(scoped, largest_win)),
            ),
            largest_winner_pct_of_gross_profit=_safe_div(largest_win, gp),
            largest_losing_trade=largest_loss,
            largest_losing_trade_pct=_safe_div(
                largest_loss,
                _entry_notional(_find_trade(scoped, largest_loss)),
            ),
            largest_loser_pct_of_gross_loss=_safe_div(largest_loss, gl) if gl != ZERO else ZERO,
            outliers_count=outliers_count(scoped),
            outliers_pnl=outliers_pnl(scoped),
            avg_bars_in_trades=avg_bars_in_trades(scoped),
            avg_bars_in_winning_trades=avg_bars_in_winning_trades(scoped),
            avg_bars_in_losing_trades=avg_bars_in_losing_trades(scoped),
        )

    long_trades: list[ClosedTrade] = [t for t in trades if t.side == "LONG"]
    short_trades: list[ClosedTrade] = [t for t in trades if t.side == "SHORT"]
    return Details(all=row(trades), long=row(long_trades), short=row(short_trades))


def _compute_capital_efficiency(
    *,
    trades: Sequence[ClosedTrade],
    equity: pd.Series,
    initial_capital: Decimal,
) -> CapitalEfficiency:
    def row(scoped: Sequence[ClosedTrade]) -> CapitalUsageRow:
        net: Decimal = net_pnl(scoped)
        largest_loss: Decimal = largest_losing_trade(scoped)
        peak_capital: Decimal = max(initial_capital, initial_capital + net)
        return CapitalUsageRow(
            annualized_return_cagr=_cagr(equity, initial_capital) if scoped is trades else ZERO,
            return_on_initial_capital=_safe_div(net, initial_capital),
            account_size_required=peak_capital,
            return_on_account_size_required=_safe_div(net, peak_capital),
            net_profit_pct_of_largest_loss=_safe_div(net, -largest_loss)
            if largest_loss != ZERO
            else ZERO,
        )

    long_trades: list[ClosedTrade] = [t for t in trades if t.side == "LONG"]
    short_trades: list[ClosedTrade] = [t for t in trades if t.side == "SHORT"]
    rows: dict[PositionScope, CapitalUsageRow] = {
        "all": row(trades),
        "long": row(long_trades),
        "short": row(short_trades),
    }
    return CapitalEfficiency(capital_usage=rows, margin_usage=MarginUsage())


def _compute_runups_drawdowns(*, equity: pd.Series, initial_capital: Decimal) -> RunUpsDrawdowns:
    analyzer: DrawdownAnalyzer = DrawdownAnalyzer()
    dd_episodes: pd.DataFrame = analyzer.recovery_periods(equity)
    max_dd_pct: Decimal = _to_decimal(analyzer.max_drawdown(equity))
    avg_dd_pct: Decimal = (
        _to_decimal(float(dd_episodes["depth"].mean())) if not dd_episodes.empty else ZERO
    )
    avg_dd_dur: Decimal = (
        _to_decimal(float(dd_episodes["duration_days"].mean())) if not dd_episodes.empty else ZERO
    )
    drawdown_row: DrawdownRow = DrawdownRow(
        avg_duration_days=avg_dd_dur,
        avg_drawdown=avg_dd_pct * initial_capital,
        max_drawdown_close_to_close=max_dd_pct * initial_capital,
        max_drawdown_intrabar=None,
        max_drawdown_pct_initial_capital_intrabar=None,
        return_of_max_drawdown=max_dd_pct,
    )
    max_runup_pct: Decimal = _to_decimal(analyzer.max_runup(equity))
    avg_runup_dur: Decimal = _to_decimal(analyzer.avg_runup_duration(equity))
    avg_runup_pct: Decimal = _to_decimal(analyzer.avg_runup_pct(equity))
    runup_row: RunUpRow = RunUpRow(
        avg_duration_days=avg_runup_dur,
        avg_runup=avg_runup_pct * initial_capital,
        max_runup_close_to_close=max_runup_pct * initial_capital,
        max_runup_intrabar=None,
        max_runup_pct_initial_capital_intrabar=None,
    )
    return RunUpsDrawdowns(runups=runup_row, drawdowns=drawdown_row)


def _compute_benchmark_comparison(
    *,
    equity: pd.Series,
    benchmark: pd.Series,
    initial_capital: Decimal,
) -> BenchmarkComparison:
    bh_return: Decimal = _to_decimal(benchmark.iloc[-1]) - initial_capital
    bh_pct: Decimal = _safe_div(bh_return, initial_capital)
    strategy_return: Decimal = _to_decimal(equity.iloc[-1]) - initial_capital
    strategy_pct: Decimal = _safe_div(strategy_return, initial_capital)
    return BenchmarkComparison(
        buy_and_hold_return=bh_return,
        buy_and_hold_pct=bh_pct,
        strategy_outperformance=strategy_pct - bh_pct,
    )


def _cagr(equity: pd.Series, initial_capital: Decimal) -> Decimal:
    if equity.empty:
        return ZERO
    final: Decimal = _to_decimal(equity.iloc[-1])
    if initial_capital == ZERO:
        return ZERO
    n_days: int = len(equity)
    years: Decimal = Decimal(n_days) / Decimal(TRADING_DAYS_PER_YEAR)
    if years == ZERO:
        return ZERO
    ratio: Decimal = final / initial_capital
    if ratio <= ZERO:
        return ZERO
    return _to_decimal(float(ratio) ** float(Decimal(1) / years) - 1.0)


def _entry_notional(trade: ClosedTrade | None) -> Decimal:
    if trade is None:
        return ZERO
    return trade.entry_price * trade.qty


def _find_trade(trades: Sequence[ClosedTrade], target_pnl: Decimal) -> ClosedTrade | None:
    if target_pnl == ZERO:
        return None
    for t in trades:
        if t.realized_pnl == target_pnl:
            return t
    return None


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == ZERO:
        return ZERO
    return numerator / denominator


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return Decimal(str(value))


def _to_utc(value: object) -> datetime:
    ts: pd.Timestamp = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
    result: datetime = ts.to_pydatetime()
    return result.astimezone(UTC)


__all__: list[str] = ["build_strategy_report"]
