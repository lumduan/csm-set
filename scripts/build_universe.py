"""Fetch SET symbol list and build dated universe snapshots.

Usage:
    uv run python scripts/build_universe.py [--data-dir PATH] [--start YYYY-MM-DD]
        [--security-types S [S ...]] [--symbols-only]

Steps:
    1. Fetch SET-listed symbols via settfex (queries SET API).
    2. Filter by security type (default: S = common stocks only).
    3. Save sorted canonical list to {data_dir}/universe/symbols.json (atomic write).
    4. Generate business-month-end rebalance dates from --start to today.
    5. Apply price / volume / coverage filters at each rebalance date using
       OHLCV data from {data_dir}/raw/, saving one snapshot parquet per date
       to {data_dir}/universe/.

Security type codes (--security-types):
    S  Common stock        (default — e.g. SET:AOT, SET:CPALL)
    F  Futures             (e.g. SET:PTT-F)
    V  Derivative Warrants on Thai stocks (e.g. SET:PTT01C2606T)
    W  Company warrants    (e.g. SET:A5-W4)
    X  DW on foreign stocks (e.g. SET:AAPL01)
    P  Preferred shares    (e.g. SET:BH-P)
    Q  Convertible preferred shares
    L  ETF / Infrastructure funds (e.g. SET:1DIV)
    U  Unit trusts

Exit codes:
    0 — success
    1 — symbol fetch failed, empty symbol list, or store write error
    2 — invalid CLI argument
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
from csm.data.symbol_filter import (
    DEFAULT_SECURITY_TYPES,
    SECURITY_TYPE_LABELS,
    SecurityType,
    filter_symbols,
    parse_security_types,
)
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
    parser.add_argument(
        "--security-types",
        nargs="+",
        default=[t.value for t in DEFAULT_SECURITY_TYPES],
        metavar="CODE",
        help=(
            "Security type codes to include (default: S = common stocks). "
            "Codes: S=stock, F=futures, V=DW(Thai), W=warrant, X=DW(foreign), "
            "P=preferred, Q=convertible, L=ETF, U=unit-trust"
        ),
    )
    parser.add_argument(
        "--symbols-only",
        action="store_true",
        help="Save symbols.json and exit — skip snapshot building.",
    )
    return parser.parse_args()


async def _fetch_set_symbols(
    include: frozenset[SecurityType],
) -> list[str]:
    """Fetch SET-listed symbols via settfex, filtered by security type."""
    from settfex.services.set import get_stock_list  # noqa: PLC0415

    stock_list = await get_stock_list()
    all_set = stock_list.filter_by_market("SET")
    if not all_set:
        raise RuntimeError("settfex returned an empty symbol list for market='SET'")

    filtered = filter_symbols(all_set, include=include)
    if not filtered:
        type_names = ", ".join(SECURITY_TYPE_LABELS[t] for t in include)
        raise RuntimeError(f"No symbols found after filtering for security types: {type_names}")

    # Log breakdown by security type
    from collections import Counter  # noqa: PLC0415

    counts = Counter(s.security_type for s in filtered)
    for code, count in sorted(counts.items()):
        stype = SecurityType(code)
        logger.info("  %s (%s): %d symbols", code, SECURITY_TYPE_LABELS[stype], count)

    symbols = sorted(f"SET:{s.symbol}" for s in filtered)
    logger.info("Fetched %d SET symbols (filtered from %d total)", len(symbols), len(all_set))
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

    # Parse and validate security type codes
    try:
        include = parse_security_types(args.security_types)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(2)

    type_names = ", ".join(
        f"{t.value}={SECURITY_TYPE_LABELS[t]}" for t in sorted(include, key=lambda t: t.value)
    )
    logger.info("Security type filter: %s", type_names)

    app_settings = Settings()
    if app_settings.public_mode:
        logger.error("build_universe.py is owner-only. Set CSM_PUBLIC_MODE=false before running.")
        sys.exit(1)

    data_dir: Path = args.data_dir

    # Step 1+2 — fetch and filter symbol list
    try:
        symbols = await _fetch_set_symbols(include)
    except Exception:
        logger.exception("Failed to fetch symbol list from settfex")
        sys.exit(1)

    # Step 3 — persist symbols.json atomically
    symbols_path = data_dir / "universe" / "symbols.json"
    try:
        _save_symbols_json(symbols, symbols_path)
    except OSError:
        logger.exception("Failed to write %s", symbols_path)
        sys.exit(1)

    if args.symbols_only:
        logger.info("--symbols-only: skipping snapshot build.")
        return

    # Step 4 — generate rebalance dates
    rebalance_dates: pd.DatetimeIndex = pd.date_range(
        start=args.start,
        end=pd.Timestamp.now(),
        freq=REBALANCE_FREQ,
        tz="Asia/Bangkok",
    )
    logger.info("Building snapshots for %d rebalance dates", len(rebalance_dates))

    # Step 5 — build and persist snapshots
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
