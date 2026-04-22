"""Fetch SET symbol list and build dated universe snapshots.

Usage:
    uv run python scripts/build_universe.py [--data-dir PATH] [--start YYYY-MM-DD]

Steps:
    1. Fetch all SET-listed symbols via settfex (queries SET API).
    2. Save sorted canonical list to {data_dir}/universe/symbols.json (atomic write).
    3. Generate business-month-end rebalance dates from --start to today.
    4. Apply price / volume / coverage filters at each rebalance date using
       OHLCV data from {data_dir}/raw/, saving one snapshot parquet per date
       to {data_dir}/universe/.

Exit codes:
    0 — success
    1 — symbol fetch failed, empty symbol list, or store write error
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from csm.config.constants import REBALANCE_FREQ
from csm.config.settings import Settings
from csm.data.store import ParquetStore
from csm.data.universe import UniverseBuilder

logger: logging.Logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("./data"),
        help="Root data directory (default: ./data)",
    )
    parser.add_argument(
        "--start",
        default="2009-01-01",
        help="First rebalance date for snapshots (default: 2009-01-01)",
    )
    return parser.parse_args()


async def _fetch_set_symbols() -> list[str]:
    """Fetch SET-listed symbols via settfex and return in canonical tvkit format."""
    from settfex.services.set import get_stock_list  # noqa: PLC0415

    stock_list = await get_stock_list()
    set_stocks = stock_list.filter_by_market("SET")
    if not set_stocks:
        raise RuntimeError("settfex returned an empty symbol list for market='SET'")
    symbols = sorted(f"SET:{s.symbol}" for s in set_stocks)
    logger.info("Fetched %d SET symbols from settfex", len(symbols))
    return symbols


def _save_symbols_json(symbols: list[str], output_path: Path) -> None:
    """Write symbols list atomically (tmp file + rename)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"symbols": symbols}, indent=2))
    tmp.rename(output_path)
    logger.info("Saved %d symbols to %s", len(symbols), output_path)


async def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    app_settings = Settings()
    if app_settings.public_mode:
        logger.error("build_universe.py is owner-only. Set CSM_PUBLIC_MODE=false before running.")
        sys.exit(1)

    data_dir: Path = args.data_dir

    # Step 1 — fetch symbol list from SET API via settfex
    try:
        symbols = await _fetch_set_symbols()
    except Exception:
        logger.exception("Failed to fetch symbol list from settfex")
        sys.exit(1)

    # Step 2 — persist symbols.json atomically
    symbols_path = data_dir / "universe" / "symbols.json"
    try:
        _save_symbols_json(symbols, symbols_path)
    except OSError:
        logger.exception("Failed to write %s", symbols_path)
        sys.exit(1)

    # Step 3 — generate rebalance dates
    rebalance_dates: pd.DatetimeIndex = pd.date_range(
        start=args.start,
        end=pd.Timestamp.now(tz="Asia/Bangkok"),
        freq=REBALANCE_FREQ,
        tz="Asia/Bangkok",
    )
    logger.info("Building snapshots for %d rebalance dates", len(rebalance_dates))

    # Step 4 — build and persist snapshots
    raw_store = ParquetStore(data_dir / "raw")
    universe_store = ParquetStore(data_dir / "universe")
    builder = UniverseBuilder(raw_store, app_settings)
    try:
        builder.build_all_snapshots(symbols, rebalance_dates, snapshot_store=universe_store)
    except Exception:
        logger.exception("Snapshot build failed")
        sys.exit(1)

    logger.info("Done — %d snapshots written to %s", len(rebalance_dates), data_dir / "universe")


if __name__ == "__main__":
    asyncio.run(main())
