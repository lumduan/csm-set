"""Rank one cross-section under BOTH price-adjustment modes and diff the selections.

Why this exists (TK-0277)
-------------------------
``OHLCVLoader.fetch`` resolved the price-adjustment mode and then discarded it, so every
momentum factor the live test computed ran on **split-adjusted-only** prices while being
documented as total-return. The fix (2026-08-09) forwards the kwarg to tvkit. This script
answers the question the fix alone cannot: **would the selection actually have differed?**

It is deliberately NOT a re-run of the stored panel. ``data/processed/features_latest.parquet``
holds exactly one adjustment basis, already z-scored, so the difference cannot be recovered from
it. Two *price* fetches are required, each driven through the real
``FeaturePipeline`` → ``PortfolioConstructor`` path.

What it does NOT model — read before quoting the output
--------------------------------------------------------
The live rebalance applies a **per-holding EMA100 fast exit** (a name closing below its own
100-day EMA is evicted regardless of rank). That rule is **not implemented in ``src/csm/``** —
``MomentumBacktest._is_fast_exit`` is an *index-level* equity-scaling rule — and the monthly plans
applied it by hand. Nor does this model the 63-day ADTV liquidity floor, which is applied during
universe construction upstream.

So the output answers *"does the composite ranking and its buffer/floor logic pick different
names?"* It does **not** answer *"was the rebalance wrong"*. Report it as the former.

Usage
-----
    uv run python scripts/compare_adjustment_ranking.py --asof 2026-07-31 --n-holdings 10

Add ``--json out.json`` to persist the full comparison.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# MUST precede the `csm` imports. `csm/config/__init__.py` builds a module-level
# `settings = get_settings()` singleton at import time, so a constructor override arrives too
# late — on a host without CSM_MARKET_DATA_ENGINE_BASE_URL the default `db` source raises during
# import. This comparison is ABOUT the tvkit kwarg, so the tvkit path is the correct source here
# regardless of how the host is configured. `setdefault` leaves an explicit override intact.
os.environ.setdefault("CSM_OHLCV_SOURCE", "parquet")

from csm.config.settings import Settings  # noqa: E402
from csm.data.loader import Adjustment, OHLCVLoader  # noqa: E402
from csm.data.store import ParquetStore  # noqa: E402
from csm.features.pipeline import FeaturePipeline  # noqa: E402
from csm.portfolio.construction import (  # noqa: E402
    PortfolioConstructor,
    SelectionConfig,
    SelectionResult,
)

logger: logging.Logger = logging.getLogger("compare_adjustment")

_INDEX_SYMBOL: str = "SET:SET"

# The seven factor columns the composite averages. Sliced EXPLICITLY because
# PortfolioConstructor.select computes `cross_section.mean(axis=1)` over EVERY column it is
# handed — a stray `fwd_ret_*` or `_rank` column would silently enter the composite.
_FACTOR_COLUMNS: list[str] = [
    "mom_12_1",
    "mom_6_1",
    "mom_3_1",
    "mom_1_0",
    "sharpe_momentum",
    "residual_momentum",
    "sector_rel_strength",
]


def _load_universe(path: Path) -> tuple[list[str], dict[str, str]]:
    """Return (symbols, symbol->sector) from a universe snapshot."""
    frame: pd.DataFrame = pd.read_parquet(path)
    symbols: list[str] = [str(s) for s in frame["symbol"]]
    sectors: dict[str, str] = {}
    if "sector" in frame.columns:
        sectors = {
            str(sym): str(sec)
            for sym, sec in zip(frame["symbol"], frame["sector"], strict=True)
            if pd.notna(sec)
        }
    else:
        logger.warning(
            "universe snapshot has no 'sector' column — sector_rel_strength will be absent, "
            "which changes the composite. Rebuild with scripts/build_universe.py."
        )
    return symbols, sectors


def _qualify(symbol: str) -> str:
    """``SET:``-prefix a bare symbol so it matches the panel's index."""
    sym = symbol.strip()
    return sym if ":" in sym else f"SET:{sym}"


def _load_holdings(path: Path, override: str | None) -> list[str]:
    """Return the book to evaluate against.

    ``override`` (a comma-separated list) exists because the buffer and exit-floor rules key on
    *current holdings*, so reproducing a historical decision requires the book **as it stood
    before that rebalance** — not the book in ``live_portfolio.yaml``, which is the post-trade
    state. Passing the wrong one silently answers a different question.
    """
    if override:
        return [_qualify(s) for s in override.split(",") if s.strip()]
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    return [_qualify(str(pos["symbol"])) for pos in raw.get("positions", [])]


async def _prices_for_mode(
    settings: Settings, symbols: list[str], bars: int, mode: Adjustment
) -> dict[str, pd.DataFrame]:
    """Fetch every symbol under one adjustment mode."""
    loader = OHLCVLoader(settings=settings)
    fetched: dict[str, pd.DataFrame] = await loader.fetch_batch(
        symbols=symbols, interval="1D", bars=bars, adjustment=mode.value
    )
    logger.info("mode=%s fetched %d/%d symbols", mode.value, len(fetched), len(symbols))
    return fetched


def _cross_section(
    prices: dict[str, pd.DataFrame],
    sectors: dict[str, str],
    asof: pd.Timestamp,
    scratch: Path,
) -> pd.DataFrame:
    """Build the panel into a scratch store and return the asof cross-section."""
    # Scratch store: FeaturePipeline.build ALWAYS persists to key "features_latest", so pointing
    # it at data/processed/ would clobber the live panel.
    pipeline = FeaturePipeline(store=ParquetStore(scratch))
    panel: pd.DataFrame = pipeline.build(
        prices=prices, rebalance_dates=[asof], symbol_sectors=sectors or None
    )
    if panel.empty:
        return panel
    frame: pd.DataFrame = panel.xs(panel.index.get_level_values("date")[0], level="date")
    missing: list[str] = [c for c in _FACTOR_COLUMNS if c not in frame.columns]
    if missing:
        logger.warning("cross-section is missing factor column(s): %s", ", ".join(missing))
    return frame[[c for c in _FACTOR_COLUMNS if c in frame.columns]]


def _select(frame: pd.DataFrame, holdings: list[str], n: int) -> SelectionResult:
    config = SelectionConfig(n_holdings_min=n, n_holdings_max=n)
    return PortfolioConstructor().select(frame, holdings, config)


def _report(
    asof: pd.Timestamp,
    results: dict[str, SelectionResult],
    frames: dict[str, pd.DataFrame],
    holdings: list[str],
    n: int,
) -> dict[str, Any]:
    """Print the human-readable diff and return the machine-readable payload."""
    spl, div = results["splits"], results["dividends"]
    sel_s, sel_d = set(spl.selected), set(div.selected)

    print(f"\n{'=' * 78}\nCross-section {asof:%Y-%m-%d}   top-{n}   book={len(holdings)} names")
    print(f"symbols ranked: splits={len(frames['splits'])}  dividends={len(frames['dividends'])}")
    print("=" * 78)

    only_div: list[str] = sorted(sel_d - sel_s)
    only_spl: list[str] = sorted(sel_s - sel_d)

    if not only_div and not only_spl:
        print("\nSELECTION IDENTICAL under both adjustment modes.")
    else:
        print(f"\nSELECTION DIFFERS — {len(only_div)} name(s) swap:")
        for sym in only_div:
            print(f"   IN  under dividends, OUT under splits : {sym}")
        for sym in only_spl:
            print(f"   IN  under splits,    OUT under dividends: {sym}")

    # Rank movement for every symbol present in both, largest mover first.
    common: list[str] = sorted(set(spl.ranks) & set(div.ranks))
    moves: list[tuple[str, float, float, float]] = sorted(
        ((s, spl.ranks[s], div.ranks[s], div.ranks[s] - spl.ranks[s]) for s in common),
        key=lambda r: abs(r[3]),
        reverse=True,
    )
    print("\nLargest percentile-rank moves (dividends − splits):")
    for sym, rs, rd, delta in moves[:12]:
        flag = "  <-- held" if sym in holdings else ""
        print(f"   {sym:<16} {rs:6.3f} -> {rd:6.3f}   {delta:+.3f}{flag}")

    print("\nHeld names:")
    for sym in sorted(holdings):
        held_s: float | None = spl.ranks.get(sym)
        held_d: float | None = div.ranks.get(sym)
        if held_s is None or held_d is None:
            print(f"   {sym:<16} (absent from the cross-section)")
            continue
        keep_s = "keep" if sym in sel_s else "EVICT"
        keep_d = "keep" if sym in sel_d else "EVICT"
        mark = "   <-- DECISION CHANGES" if keep_s != keep_d else ""
        print(f"   {sym:<16} {held_s:6.3f} {keep_s:>5}  |  {held_d:6.3f} {keep_d:>5}{mark}")

    return {
        "asof": asof.isoformat(),
        "n_holdings": n,
        "selected": {"splits": sorted(sel_s), "dividends": sorted(sel_d)},
        "only_dividends": only_div,
        "only_splits": only_spl,
        "selection_identical": not only_div and not only_spl,
        "ranks": {
            "splits": {k: float(v) for k, v in spl.ranks.items()},
            "dividends": {k: float(v) for k, v in div.ranks.items()},
        },
        "holdings": sorted(holdings),
    }


async def _run(args: argparse.Namespace) -> int:
    # ohlcv_source is forced to the tvkit path: this comparison is ABOUT the tvkit kwarg, and the
    # db path resolves adjustment through a different mechanism entirely.
    settings = Settings(ohlcv_source="parquet", public_mode=False)

    symbols, sectors = _load_universe(Path(args.universe))
    holdings: list[str] = _load_holdings(Path(args.portfolio), args.holdings)
    wanted: list[str] = sorted({*symbols, *holdings, _INDEX_SYMBOL})
    logger.info("universe=%d held=%d total-to-fetch=%d", len(symbols), len(holdings), len(wanted))

    results: dict[str, SelectionResult] = {}
    frames: dict[str, pd.DataFrame] = {}
    asof: pd.Timestamp | None = None

    with tempfile.TemporaryDirectory(prefix="tk0277-") as tmp:
        for mode in (Adjustment.SPLITS, Adjustment.DIVIDENDS):
            prices = await _prices_for_mode(settings, wanted, args.bars, mode)
            if not prices:
                print(f"ERROR: no prices fetched for mode={mode.value}", file=sys.stderr)
                return 1
            if asof is None:
                asof = (
                    pd.Timestamp(args.asof, tz="Asia/Bangkok")
                    if args.asof
                    else max(f.index.max() for f in prices.values())
                )
            frame = _cross_section(prices, sectors, asof, Path(tmp) / mode.value)
            if frame.empty:
                print(f"ERROR: empty cross-section for mode={mode.value}", file=sys.stderr)
                return 1
            frames[mode.value] = frame
            results[mode.value] = _select(frame, holdings, args.n_holdings)

    assert asof is not None
    payload = _report(asof, results, frames, holdings, args.n_holdings)

    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(f"\nwrote {args.json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--asof", default=None, help="Rebalance date YYYY-MM-DD (default: latest bar)"
    )
    parser.add_argument("--bars", type=int, default=600, help="Bars per symbol (default: 600)")
    parser.add_argument("--n-holdings", type=int, default=10, help="Book size (default: 10)")
    parser.add_argument("--universe", default="data/processed/universe_latest.parquet")
    parser.add_argument("--portfolio", default="configs/live_portfolio.yaml")
    parser.add_argument(
        "--holdings",
        default=None,
        help=(
            "Comma-separated book to evaluate against, overriding --portfolio. Use the book as "
            "it stood BEFORE the rebalance being reproduced — buffer/floor rules key on it."
        ),
    )
    parser.add_argument("--json", default=None, help="Optional path for the JSON payload")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
