"""Bulk fetch SET OHLCV history via tvkit and save to parquet.

Usage (owner only — requires tvkit credentials in .env):
    uv run python scripts/fetch_history.py [--data-dir PATH] [--bars N] [--failure-threshold F]

Idempotent: skips symbols already present in <data-dir>/raw/.
Reads the universe symbol list from <data-dir>/universe/symbols.json (produced by
build_universe.py).

Exit codes:
    0 — success; failure rate ≤ threshold
    1 — symbols.json missing/malformed/empty; public mode active; failure rate > threshold
    2 — invalid CLI argument (argparse error)
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, StrictStr, ValidationError

from csm.config.settings import Settings
from csm.data.exceptions import StoreError
from csm.data.loader import OHLCVLoader
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_BARS: int = 5040  # ~20 years × 252 trading days
_DEFAULT_FAILURE_THRESHOLD: float = 0.10


class _SymbolsFile(BaseModel):
    """Strict Pydantic schema for data/universe/symbols.json."""

    symbols: list[StrictStr]


def _positive_int(value: str) -> int:
    """argparse type for --bars: must be > 0."""
    v = int(value)
    if v <= 0:
        raise argparse.ArgumentTypeError(f"--bars must be > 0, got {v}")
    return v


def _unit_float(value: str) -> float:
    """argparse type for --failure-threshold: must be in [0.0, 1.0]."""
    v = float(value)
    if not 0.0 <= v <= 1.0:
        raise argparse.ArgumentTypeError(f"--failure-threshold must be in [0.0, 1.0], got {v}")
    return v


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Root data directory (default: Settings.data_dir)",
    )
    parser.add_argument(
        "--bars",
        type=_positive_int,
        default=_DEFAULT_BARS,
        help=f"Bars per symbol; must be > 0 (default: {_DEFAULT_BARS}, ~20 years × 252)",
    )
    parser.add_argument(
        "--failure-threshold",
        type=_unit_float,
        default=_DEFAULT_FAILURE_THRESHOLD,
        dest="failure_threshold",
        help=(
            f"Max allowed failure rate [0.0, 1.0] before non-zero exit "
            f"(default: {_DEFAULT_FAILURE_THRESHOLD})"
        ),
    )
    return parser.parse_args()


def _load_symbols(path: Path) -> list[str]:
    """Read and strictly validate the universe symbol list from *path*.

    Exits with code 1 on missing file, invalid JSON, Pydantic validation failure
    (including non-list or non-str elements), or an empty symbol list.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("symbols.json not found at %s — run build_universe.py first", path)
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("symbols.json at %s contains invalid JSON: %s", path, exc)
        sys.exit(1)

    try:
        parsed = _SymbolsFile.model_validate(data)
    except ValidationError as exc:
        logger.error("symbols.json at %s has unexpected structure: %s", path, exc)
        sys.exit(1)

    if not parsed.symbols:
        logger.error(
            "symbols.json at %s contains an empty symbol list — run build_universe.py first",
            path,
        )
        sys.exit(1)

    return parsed.symbols


async def main() -> None:
    """Fetch historical OHLCV data for all SET universe symbols."""
    args = _parse_args()
    run_timestamp: datetime = datetime.now(UTC)

    app_settings = Settings()
    logging.basicConfig(level=app_settings.log_level, format="%(levelname)s %(name)s: %(message)s")

    if app_settings.public_mode:
        logger.error(
            "fetch_history.py is owner-only. Set CSM_PUBLIC_MODE=false and provide "
            "tvkit credentials before running."
        )
        sys.exit(1)

    data_dir: Path = args.data_dir if args.data_dir is not None else Path(app_settings.data_dir)
    symbols_path: Path = data_dir / "universe" / "symbols.json"
    raw_dir: Path = data_dir / "raw"
    failures_path: Path = raw_dir / "fetch_failures.json"

    # Ensure raw_dir exists before any parquet or failures-file I/O.
    raw_dir.mkdir(parents=True, exist_ok=True)

    symbols = await asyncio.to_thread(_load_symbols, symbols_path)
    store = ParquetStore(raw_dir)
    loader = OHLCVLoader(settings=app_settings)

    pending: list[str] = [s for s in symbols if store.exists(s) is False]
    skipped = len(symbols) - len(pending)
    logger.info(
        "Found %d symbols in universe; skipping %d already fetched; fetching %d",
        len(symbols),
        skipped,
        len(pending),
    )

    if not pending:
        logger.info("Nothing to fetch — all symbols already in store")
        if failures_path.exists():
            await asyncio.to_thread(failures_path.unlink)
        return

    results: dict[str, pd.DataFrame] = await loader.fetch_batch(pending, "1D", args.bars)

    successfully_saved: set[str] = set()
    for symbol, frame in results.items():
        try:
            await asyncio.to_thread(store.save, symbol, frame)
            successfully_saved.add(symbol)
        except StoreError as exc:
            logger.error("Failed to save %s: %s", symbol, exc)

    failed: list[str] = [s for s in pending if s not in successfully_saved]

    if failed:
        failures_data = {
            "run_timestamp": run_timestamp.isoformat(),
            "failed_symbols": failed,
            "count": len(failed),
        }
        failures_json = json.dumps(failures_data, indent=2)
        await asyncio.to_thread(failures_path.write_text, failures_json, "utf-8")
        logger.warning("%d symbol(s) failed; failures logged to %s", len(failed), failures_path)
    else:
        if failures_path.exists():
            await asyncio.to_thread(failures_path.unlink)

    logger.info(
        "Completed: %d succeeded, %d failed (of %d fetched)",
        len(successfully_saved),
        len(failed),
        len(pending),
    )

    if len(failed) / len(pending) > args.failure_threshold:
        logger.error(
            "Failure rate %.1f%% exceeds threshold %.1f%% — exiting with error",
            100 * len(failed) / len(pending),
            100 * args.failure_threshold,
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
