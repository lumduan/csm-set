"""Manual end-to-end verification of the Phase 5.1 sim trade loop.

Submits a single order through the gateway proxy to the Execution engine
SimAdapter and prints the resulting outcome + sim portfolio. Public-safe: no
secret is ever printed.

Prerequisites (env):

    CSM_EXECUTION_MODE=sim
    CSM_EXECUTION_ACCOUNT=SIM-...
    CSM_GATEWAY_BASE_URL=http://localhost:8080
    CSM_GATEWAY_API_KEY=<shared internal key>

Example:

    uv run python scripts/verify_execution_sim.py --symbol PTT --side BUY \
        --qty 100 --price 35.50

Exit code 0 only when the order reached FILLED and the resulting position
matches: BUY ends at ``qty``; SELL pre-seeds the (long-only) book with ``qty``
shares and must end flat at 0.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal

import pandas as pd

from csm.config.settings import Settings
from csm.execution.models import SimPortfolio, SimPosition
from csm.execution.sim_loop import run_sim_loop
from csm.execution.trade_list import Trade, TradeList, TradeSide

logger: logging.Logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the Phase 5.1 sim trade loop.")
    parser.add_argument("--symbol", required=True, help="SET ticker, e.g. PTT")
    parser.add_argument("--side", required=True, choices=["BUY", "SELL"], help="Order side")
    parser.add_argument("--qty", required=True, type=int, help="Order quantity (shares)")
    parser.add_argument("--price", required=True, help="Limit price (decimal string)")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="Per-order terminal-state timeout (s)"
    )
    return parser.parse_args()


def _build_trade_list(symbol: str, side: str, qty: int) -> TradeList:
    """Build a one-row TradeList with neutral, sim-safe field values."""
    delta = qty if side == "BUY" else -qty
    asof = pd.Timestamp.now(tz="Asia/Bangkok")
    trade = Trade(
        symbol=symbol,
        side=TradeSide(side),
        target_weight=0.0,
        current_weight=0.0,
        delta_weight=0.0,
        target_shares=max(delta, 0),
        delta_shares=delta,
        notional_thb=0.0,
        expected_slippage_bps=0.0,
        participation_rate=0.0,
    )
    return TradeList(
        trades=[trade],
        n_buys=1 if side == "BUY" else 0,
        n_sells=1 if side == "SELL" else 0,
        asof=asof,
    )


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    if settings.execution_mode != "sim":
        logger.error(
            "CSM_EXECUTION_MODE must be 'sim' for this script (got %r)", settings.execution_mode
        )
        return 2

    price = Decimal(args.price)
    trade_list = _build_trade_list(args.symbol, args.side, args.qty)
    prices = {args.symbol: price}

    # The book is long-only and starts fresh each run: a SELL must be pre-seeded
    # with the quantity it is about to sell, and verifies down to flat (0).
    portfolio = SimPortfolio()
    if args.side == "SELL":
        portfolio.positions[args.symbol] = SimPosition(
            symbol=args.symbol, quantity=args.qty, avg_price=price
        )

    result = await run_sim_loop(
        trade_list,
        prices,
        settings=settings,
        portfolio=portfolio,
        order_timeout_seconds=args.timeout,
    )

    if len(result.outcomes) != 1:
        logger.error("expected exactly one outcome, got %d", len(result.outcomes))
        return 1
    outcome = result.outcomes[0]
    logger.info("client_order_id : %s", outcome.client_order_id)
    logger.info("final_state     : %s", outcome.final_state)
    logger.info("filled_qty      : %d", outcome.filled_qty)
    logger.info("avg_fill_price  : %s", outcome.avg_fill_price)
    logger.info("rejected        : %s", outcome.rejected)
    if outcome.rejected:
        logger.info("reject_code     : %s", outcome.reject_code)
        logger.info("reject_message  : %s", outcome.reject_message)

    position = result.portfolio.positions.get(args.symbol, SimPosition(symbol=args.symbol))
    logger.info(
        "position        : %s qty=%d avg=%s",
        position.symbol,
        position.quantity,
        position.avg_price,
    )

    expected_qty = args.qty if args.side == "BUY" else 0
    if outcome.final_state == "FILLED" and position.quantity == expected_qty:
        logger.info("VERIFY OK: order FILLED and position matches.")
        return 0
    logger.error(
        "VERIFY FAILED: final_state=%s position.quantity=%d expected=%d",
        outcome.final_state,
        position.quantity,
        expected_qty,
    )
    return 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
