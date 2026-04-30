"""Execution simulator producing per-rebalance trade lists.

Accepts target weights, current positions, price data, and volume data.
Produces a deterministic TradeList with lot-rounded shares, slippage
estimates, and capacity-violation flags.

Follows the standalone overlay pattern of Phase 4.3–4.6: raw pandas
input, Pydantic config/result output, no PortfolioState dependency.
"""

from __future__ import annotations

import logging

import pandas as pd
from pydantic import BaseModel, Field

from csm.execution.slippage import SlippageModelConfig, SqrtImpactSlippageModel
from csm.execution.trade_list import (
    ExecutionResult,
    Trade,
    TradeList,
    TradeSide,
)

logger: logging.Logger = logging.getLogger(__name__)


class ExecutionConfig(BaseModel):
    """Execution simulation configuration."""

    enabled: bool = Field(default=True)
    aum_thb: float = Field(default=200_000_000, gt=0.0)
    lot_size: int = Field(default=100, ge=1)
    max_participation_rate: float = Field(default=0.10, gt=0.0, le=1.0)
    slippage_model: SlippageModelConfig = Field(
        default_factory=SlippageModelConfig,
    )
    min_trade_weight: float = Field(default=0.001, ge=0.0)
    adtv_lookback_days: int = Field(default=63, ge=21, le=504)


class ExecutionSimulator:
    """Produces a per-rebalance TradeList from target weights and positions.

    This is a stateless utility.  All relevant state is passed via the
    simulate() method parameters.
    """

    def __init__(self) -> None:
        self._slippage_model: SqrtImpactSlippageModel = SqrtImpactSlippageModel()

    def simulate(
        self,
        target_weights: pd.Series,
        current_positions: dict[str, int],
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
        config: ExecutionConfig,
    ) -> tuple[pd.Series, ExecutionResult]:
        """Simulate execution and produce a trade list.

        Args:
            target_weights: Symbol → target weight Series (sum ≤ 1.0).
            current_positions: Symbol → current shares held.
            prices: OHLCV price DataFrame with symbols as columns.
            volumes: OHLCV volume DataFrame with symbols as columns.
            config: Execution configuration.

        Returns:
            (executed_weights, ExecutionResult) tuple.  Executed weights
            reflect lot-rounded positions and cash drag.
        """
        if not config.enabled:
            return target_weights.copy(), ExecutionResult(
                trade_list=TradeList(trades=[], asof=pd.Timestamp.now()),
                post_execution_equity_fraction=1.0,
            )

        if target_weights.empty:
            empty: pd.Series = pd.Series(dtype=float)
            return empty, ExecutionResult(
                trade_list=TradeList(trades=[], asof=pd.Timestamp.now()),
                post_execution_equity_fraction=0.0,
            )

        latest_prices: pd.Series = prices.iloc[-1]
        aum: float = config.aum_thb
        lot: int = config.lot_size

        # Current notional per symbol (shares × latest price)
        current_notional: dict[str, float] = {}
        for sym, shares in current_positions.items():
            price: float = float(latest_prices.get(sym, 0.0))
            if price > 0.0:
                current_notional[sym] = shares * price

        total_current_notional: float = sum(current_notional.values())
        if total_current_notional <= 0.0:
            total_current_notional = aum

        # ADTV per symbol
        adtv: pd.Series = self._compute_adtv(
            prices, volumes, config.adtv_lookback_days
        )

        trades: list[Trade] = []
        executed_weights: dict[str, float] = {}

        for sym in target_weights.index:
            target_w: float = float(target_weights[sym])
            current_w: float = 0.0
            current_price: float = float(latest_prices.get(sym, 0.0))
            cur_notional: float = current_notional.get(sym, 0.0)

            if total_current_notional > 0.0:
                current_w = cur_notional / total_current_notional

            target_notional: float = target_w * aum
            delta_notional: float = target_notional - cur_notional
            delta_w: float = target_w - current_w

            target_shares_raw: float = (
                target_notional / current_price if current_price > 0.0 else 0.0
            )
            target_shares: int = self._round_down_to_lot(target_shares_raw, lot)

            delta_shares_raw: float = delta_notional / current_price if current_price > 0.0 else 0.0
            delta_shares: int = self._round_to_lot(delta_shares_raw, lot)

            # Determine side
            side: TradeSide
            if abs(delta_w) < config.min_trade_weight and abs(delta_shares) == 0:
                side = TradeSide.HOLD
            elif delta_shares > 0:
                side = TradeSide.BUY
            elif delta_shares < 0:
                side = TradeSide.SELL
            else:
                side = TradeSide.HOLD

            # Slippage and capacity
            sym_adtv: float = float(adtv.get(sym, 0.0))
            notional_for_slip: float = abs(delta_notional)

            if sym_adtv <= 0.0 or not sym_adtv or notional_for_slip <= 0.0:
                slip_bps: float = 0.0
                part_rate: float = 0.0
            else:
                part_rate = notional_for_slip / sym_adtv
                slip_bps = self._slippage_model.estimate(
                    notional_for_slip, sym_adtv
                )

            capacity_violation: bool = (
                sym_adtv > 0.0 and part_rate > config.max_participation_rate
            )

            # Execute notional (what we actually deploy after lot rounding)
            executed_notional: float = float(target_shares) * current_price

            executed_weights[sym] = (
                executed_notional / aum if aum > 0.0 else 0.0
            )

            trades.append(
                Trade(
                    symbol=sym,
                    side=side,
                    target_weight=target_w,
                    current_weight=current_w,
                    delta_weight=delta_w,
                    target_shares=target_shares,
                    delta_shares=delta_shares,
                    notional_thb=executed_notional,
                    expected_slippage_bps=slip_bps,
                    participation_rate=part_rate,
                    capacity_violation=capacity_violation,
                )
            )

        # Aggregate statistics
        n_buys: int = sum(1 for t in trades if t.side == TradeSide.BUY)
        n_sells: int = sum(1 for t in trades if t.side == TradeSide.SELL)
        n_holds: int = sum(1 for t in trades if t.side == TradeSide.HOLD)
        n_capacity_violations: int = sum(
            1 for t in trades if t.capacity_violation
        )

        # Turnover: sum of abs(delta_notional) / (2 × AUM)
        total_delta_notional: float = sum(
            abs(t.delta_weight) * aum for t in trades
        )
        total_turnover: float = (
            total_delta_notional / (2.0 * aum) if aum > 0.0 else 0.0
        )

        # Turnover-weighted average slippage cost
        total_slip_cost: float = 0.0
        slip_weight_sum: float = 0.0
        for t in trades:
            if t.side != TradeSide.HOLD:
                slip_weight: float = abs(t.delta_weight)
                total_slip_cost += t.expected_slippage_bps * slip_weight
                slip_weight_sum += slip_weight
        weighted_slip: float = (
            total_slip_cost / slip_weight_sum if slip_weight_sum > 0.0 else 0.0
        )

        post_equity_fraction: float = (
            sum(executed_weights.values()) if executed_weights else 0.0
        )

        executed_series: pd.Series = pd.Series(
            executed_weights, dtype=float
        )

        trade_list: TradeList = TradeList(
            trades=trades,
            total_turnover=total_turnover,
            total_slippage_cost_bps=weighted_slip,
            n_buys=n_buys,
            n_sells=n_sells,
            n_holds=n_holds,
            n_capacity_violations=n_capacity_violations,
            asof=prices.index[-1],
        )

        return executed_series, ExecutionResult(
            trade_list=trade_list,
            post_execution_equity_fraction=post_equity_fraction,
        )

    @staticmethod
    def _compute_adtv(
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
        lookback_days: int,
    ) -> pd.Series:
        """Compute average daily traded value (ADTV) per symbol.

        ADTV = mean(close × volume) over the trailing *lookback_days*
        calendar bars.  Follows the same formula as LiquidityOverlay.
        """
        adtv_values: dict[str, float] = {}
        common_symbols: set[str] = set(prices.columns) & set(volumes.columns)

        for sym in common_symbols:
            close_hist: pd.Series = prices[sym].dropna().tail(lookback_days)
            vol_hist: pd.Series = volumes[sym].dropna().tail(lookback_days)
            min_len: int = min(len(close_hist), len(vol_hist))
            if min_len == 0:
                continue
            turnover: pd.Series = (
                close_hist.iloc[-min_len:] * vol_hist.iloc[-min_len:]
            )
            adtv_values[sym] = float(turnover.mean())

        return pd.Series(adtv_values, dtype=float)

    @staticmethod
    def _round_down_to_lot(shares: float, lot_size: int) -> int:
        """Round raw share count down to nearest lot boundary."""
        if shares <= 0.0:
            return 0
        return int(shares // lot_size) * lot_size

    @staticmethod
    def _round_to_lot(shares: float, lot_size: int) -> int:
        """Round share delta down to nearest lot (floor toward zero).

        Positive deltas floor down; negative deltas floor up (more negative).
        """
        if shares >= 0.0:
            return int(shares // lot_size) * lot_size
        # Negative: round away from zero (more negative)
        abs_shares: float = abs(shares)
        rounded: int = int(abs_shares // lot_size) * lot_size
        return -rounded


__all__: list[str] = [
    "ExecutionConfig",
    "ExecutionSimulator",
]
