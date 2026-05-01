"""Export pre-computed results for public distribution.

Produces the frontend-agnostic data contract under ``results/static/``:
- Notebooks → HTML (nbconvert, no-input mode — code cells stripped)
- Backtest → JSON + JSON Schema sidecars (summary, equity curve, annual returns)
- Signals → JSON + JSON Schema sidecars (latest cross-sectional ranking)

Every output JSON carries ``schema_version: "1.0"`` and a sibling
``<name>.schema.json`` so any client can auto-generate types.

Usage (owner only — requires ``data/`` populated by ``fetch_history.py``)::

    uv run python scripts/export_results.py
    uv run python scripts/export_results.py --notebooks-only
    uv run python scripts/export_results.py --skip-notebooks
    uv run python scripts/export_results.py --output-dir results/static

After running::

    git add results/static/
    git commit -m "results: update pre-computed outputs YYYY-MM-DD"
    git push
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import resource
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel

from csm.config.settings import settings
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.backtest import BacktestConfig, MomentumBacktest
from csm.research.ranking import CrossSectionalRanker
from scripts._export_models import (
    AnnualReturns,
    AnnualRow,
    BacktestConfigSnapshot,
    BacktestMetrics,
    BacktestPeriod,
    BacktestSummary,
    EquityCurve,
    EquityPoint,
    ExportResultsConfig,
    RankingEntry,
    SignalRanking,
)

logger: logging.Logger = logging.getLogger(__name__)

TZ_BANGKOK: ZoneInfo = ZoneInfo("Asia/Bangkok")
JSON_WRITE_KWARGS: dict[str, object] = {"indent": 2, "ensure_ascii": False}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export pre-computed results for public distribution."
    )
    parser.add_argument(
        "--notebook-dir",
        default="notebooks",
        help="Directory containing .ipynb files (default: notebooks/)",
    )
    parser.add_argument(
        "--output-dir",
        default="results/static",
        help="Output directory for exported artefacts (default: results/static/)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="nbconvert timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--memory-budget",
        type=int,
        default=2048,
        help="Memory budget in MB for logging (default: 2048)",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--notebooks-only",
        action="store_true",
        help="Export only notebooks to HTML",
    )
    group.add_argument(
        "--backtest-only",
        action="store_true",
        help="Export only backtest results",
    )
    group.add_argument(
        "--signals-only",
        action="store_true",
        help="Export only signal rankings",
    )
    group.add_argument(
        "--skip-notebooks",
        action="store_true",
        help="Export backtest and signals but skip notebooks",
    )

    return parser.parse_args()


def _write_json(path: Path, model: BaseModel) -> None:
    """Write a Pydantic model as sorted-key JSON with indent=2."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(**JSON_WRITE_KWARGS), encoding="utf-8")  # type: ignore[arg-type]


def _write_schema(path: Path, model_class: type[BaseModel]) -> None:
    """Write JSON Schema draft-2020-12 sidecar for the model class."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = model_class.model_json_schema()
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    path.write_text(
        json.dumps(schema, **JSON_WRITE_KWARGS),  # type: ignore[arg-type]
        encoding="utf-8",
    )


async def export_notebooks(config: ExportResultsConfig) -> None:
    """Execute all notebooks and export to HTML via nbconvert.

    Uses ``--no-input`` to strip code cells — only markdown and outputs
    appear in the rendered HTML. Logs peak RSS after each notebook.
    """
    out_dir: Path = config.output_dir / "notebooks"
    out_dir.mkdir(parents=True, exist_ok=True)

    notebook_dir: Path = Path(config.notebook_dir)
    nb_paths: list[Path] = sorted(notebook_dir.glob("*.ipynb"))
    if not nb_paths:
        logger.warning("No .ipynb files found in %s", notebook_dir)
        return

    for nb_path in nb_paths:
        html_path: Path = out_dir / f"{nb_path.stem}.html"
        logger.info("Exporting notebook %s → %s", nb_path.name, html_path)

        start: float = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "jupyter",
            "nbconvert",
            "--to",
            "html",
            "--execute",
            "--no-input",
            f"--ExecutePreprocessor.timeout={config.timeout_s}",
            "--ExecutePreprocessor.kernel_name=python3",
            "--output",
            str(html_path),
            str(nb_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        elapsed: float = time.monotonic() - start

        if proc.returncode != 0:
            err_text: str = stderr.decode() if stderr else ""
            logger.error(
                "nbconvert failed for %s: returncode=%d",
                nb_path.name,
                proc.returncode,
            )
            logger.error("stderr: %s", err_text)
            raise RuntimeError(f"nbconvert failed for {nb_path.name} (exit {proc.returncode})")

        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        # macOS reports ru_maxrss in bytes; Linux reports in kilobytes.
        # Normalise to MB.
        peak_mb: float = (
            usage.ru_maxrss / (1024 * 1024)
            if usage.ru_maxrss > 1_000_000
            else usage.ru_maxrss / 1024
        )
        logger.info(
            "Notebook %s exported in %.1fs (peak %.0f MB / budget %d MB)",
            nb_path.name,
            elapsed,
            peak_mb,
            config.memory_budget_mb,
        )


async def export_backtest(
    config: ExportResultsConfig,
    backtest_config: BacktestConfig | None = None,
) -> None:
    """Run the momentum backtest and export validated JSON + schema sidecars.

    Args:
        config: Export pipeline configuration.
        backtest_config: Optional BacktestConfig override. When ``None``,
            the production default ``BacktestConfig()`` is used. Tests pass
            a shorter-horizon config to work with synthetic data.
    """
    bt_config: BacktestConfig = backtest_config or BacktestConfig()
    store: ParquetStore = ParquetStore(settings.data_dir / "processed")

    feature_panel: pd.DataFrame = FeaturePipeline(store=store).load_latest()
    prices: pd.DataFrame = store.load("prices_latest")
    result = MomentumBacktest(store=store).run(
        feature_panel=feature_panel,
        prices=prices,
        config=bt_config,
    )

    # ── Backtest period from equity curve dates ──────────────────────
    eq_dates: list[str] = sorted(result.equity_curve.keys())
    if not eq_dates:
        logger.error("Backtest produced empty equity curve — check data and config")
        raise RuntimeError("Backtest produced empty equity curve")

    bt_period = BacktestPeriod(
        start=datetime.strptime(eq_dates[0], "%Y-%m-%d").date(),
        end=datetime.strptime(eq_dates[-1], "%Y-%m-%d").date(),
    )

    # ── Config snapshot ──────────────────────────────────────────────
    config_snapshot = BacktestConfigSnapshot(
        formation_months=bt_config.formation_months,
        skip_months=bt_config.skip_months,
        top_quantile=bt_config.top_quantile,
        weight_scheme=bt_config.weight_scheme,
        transaction_cost_bps=int(bt_config.transaction_cost_bps),
        rebalance_every_n=bt_config.rebalance_every_n,
        vol_scaling_enabled=bt_config.vol_scaling_enabled,
        sector_max_weight=bt_config.sector_max_weight,
    )

    # ── Metrics ──────────────────────────────────────────────────────
    m = result.metrics
    metrics = BacktestMetrics(
        cagr=float(m.get("cagr", 0.0)),
        sharpe=float(m.get("sharpe", 0.0)),
        sortino=float(m.get("sortino", 0.0)),
        calmar=float(m.get("calmar", 0.0)),
        max_drawdown=float(m.get("max_drawdown", 0.0)),
        win_rate=float(m.get("win_rate", 0.0)),
        volatility=float(m.get("volatility", 0.0)),
        alpha=float(v) if (v := m.get("alpha")) is not None else None,
        beta=float(v) if (v := m.get("beta")) is not None else None,
        information_ratio=float(v) if (v := m.get("information_ratio")) is not None else None,
    )

    # ── Build and validate models ────────────────────────────────────
    summary_model = BacktestSummary(
        generated_at=datetime.now(tz=TZ_BANGKOK),
        backtest_period=bt_period,
        config=config_snapshot,
        metrics=metrics,
    )

    eq_series: list[EquityPoint] = [
        EquityPoint(
            date=datetime.strptime(d, "%Y-%m-%d").date(),
            nav=float(v),
        )
        for d, v in sorted(result.equity_curve.items())
    ]
    equity_model = EquityCurve(series=eq_series)

    annual_pairs = sorted(
        (int(y), float(v)) for y, v in result.annual_returns.items()
    )
    annual_model = AnnualReturns(
        rows=[AnnualRow(year=y, portfolio_return=r) for y, r in annual_pairs]
    )

    # ── Write JSON + schema sidecars ─────────────────────────────────
    bt_dir: Path = config.output_dir / "backtest"

    _write_json(bt_dir / "summary.json", summary_model)
    _write_schema(bt_dir / "summary.schema.json", BacktestSummary)

    _write_json(bt_dir / "equity_curve.json", equity_model)
    _write_schema(bt_dir / "equity_curve.schema.json", EquityCurve)

    _write_json(bt_dir / "annual_returns.json", annual_model)
    _write_schema(bt_dir / "annual_returns.schema.json", AnnualReturns)

    logger.info(
        "Backtest exported: %d equity points, %d annual rows → %s",
        len(eq_series),
        len(annual_pairs),
        bt_dir,
    )


async def export_signals(config: ExportResultsConfig) -> None:
    """Compute cross-sectional rankings and export validated JSON + schema sidecar.

    Uses ``rank_all()`` to rank every numeric feature column, then extracts
    the primary momentum signal (``mom_12_1``) for the latest rebalance date.
    """
    store: ParquetStore = ParquetStore(settings.data_dir / "processed")

    feature_panel: pd.DataFrame = FeaturePipeline(store=store).load_latest()
    ranked: pd.DataFrame = CrossSectionalRanker().rank_all(feature_panel)

    latest_date: pd.Timestamp = ranked.index.get_level_values("date").max()
    latest_cross: pd.DataFrame = ranked.xs(latest_date, level="date")

    # ── Sector mapping from universe ─────────────────────────────────
    sector_map: dict[str, str] = {}
    try:
        universe_df: pd.DataFrame = store.load("universe_latest")
        sector_map = dict(zip(universe_df["symbol"], universe_df["sector"], strict=True))
    except (KeyError, FileNotFoundError):
        logger.warning("universe_latest not found — sectors will be 'UNKNOWN'")

    # ── Build ranking entries from mom_12_1 signal ───────────────────
    entries: list[RankingEntry] = []
    if isinstance(latest_cross, pd.Series):
        # xslice returned a Series for a single-row cross-section
        if "mom_12_1" in latest_cross.index:
            entry = _build_ranking_entry(latest_cross, sector_map)
            if entry is not None:
                entries.append(entry)
    else:
        for _symbol, row in latest_cross.iterrows():
            entry = _build_ranking_entry(row, sector_map)
            if entry is not None:
                entries.append(entry)

    if not entries:
        logger.warning("No valid signal entries — check feature panel data")

    ranking_model = SignalRanking(
        as_of=latest_date.date(),
        rankings=entries,
    )

    sig_dir: Path = config.output_dir / "signals"
    _write_json(sig_dir / "latest_ranking.json", ranking_model)
    _write_schema(sig_dir / "latest_ranking.schema.json", SignalRanking)

    logger.info(
        "Signals exported: %d ranked symbols as of %s → %s",
        len(entries),
        latest_date.date(),
        sig_dir,
    )


def _build_ranking_entry(row: pd.Series, sector_map: dict[str, str]) -> RankingEntry | None:
    """Build a RankingEntry from a single cross-section row, or None if NaN."""
    mom_val = row.get("mom_12_1")
    rank_pct = row.get("mom_12_1_rank")
    quintile = row.get("mom_12_1_quintile")

    if pd.isna(mom_val) or pd.isna(rank_pct):
        return None

    symbol: str = str(row.get("symbol", row.name))
    return RankingEntry(
        symbol=symbol,
        sector=sector_map.get(symbol, "UNKNOWN"),
        quintile=int(quintile) if not pd.isna(quintile) else 0,
        z_score=float(mom_val),
        rank_pct=float(rank_pct),
    )


async def main() -> None:
    """Orchestrate the export pipeline based on CLI flags."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    )

    if settings.public_mode:
        raise RuntimeError(
            "export_results.py is owner-only. Set CSM_PUBLIC_MODE=false before running."
        )

    args: argparse.Namespace = _parse_args()
    config = ExportResultsConfig(
        notebook_dir=Path(args.notebook_dir),
        output_dir=Path(args.output_dir),
        timeout_s=args.timeout,
        memory_budget_mb=args.memory_budget,
    )

    # ── Resolve mutex group into three booleans ──────────────────────
    run_notebooks: bool = True
    run_backtest: bool = True
    run_signals: bool = True

    if args.notebooks_only:
        run_backtest = False
        run_signals = False
    elif args.backtest_only:
        run_notebooks = False
        run_signals = False
    elif args.signals_only:
        run_notebooks = False
        run_backtest = False
    elif args.skip_notebooks:
        run_notebooks = False

    config.output_dir.mkdir(parents=True, exist_ok=True)

    if run_notebooks:
        await export_notebooks(config)
    if run_backtest:
        await export_backtest(config)
    if run_signals:
        await export_signals(config)

    logger.info("Export completed successfully to %s", config.output_dir)


if __name__ == "__main__":
    asyncio.run(main())
