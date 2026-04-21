"""Export pre-computed results for public distribution.

Runs all notebooks and exports derived metrics to results/.
No raw price data is written - only NAV series, metrics, and signal scores.

Usage (owner only - requires data/ populated by fetch_history.py):
    uv run python scripts/export_results.py

After running:
    git add results/
    git commit -m "results: update pre-computed outputs YYYY-MM-DD"
    git push
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path

import pandas as pd

from csm.config.settings import settings
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.backtest import BacktestConfig, MomentumBacktest
from csm.research.ranking import CrossSectionalRanker

logger: logging.Logger = logging.getLogger(__name__)


def _assert_safe_exports(results_dir: Path) -> None:
    """Verify that exported JSON files do not contain raw OHLCV columns."""

    forbidden: set[str] = {"open", "high", "low", "close", "volume"}
    for json_path in results_dir.rglob("*.json"):
        payload: object = json.loads(json_path.read_text())
        text: str = json.dumps(payload)
        for column in forbidden:
            if f'"{column}"' in text:
                raise ValueError(f"Raw price field leaked into export: {json_path} contains {column}")


async def main() -> None:
    """Export public-safe notebook, backtest, and signal artifacts."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        raise RuntimeError("export_results.py is owner-only. Set CSM_PUBLIC_MODE=false before running.")

    notebooks_dir: Path = Path("notebooks")
    results_dir: Path = settings.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    for nb_path in sorted(notebooks_dir.glob("*.ipynb")):
        out_path: Path = results_dir / "notebooks" / f"{nb_path.stem}.html"
        subprocess.run(
            [
                "uv",
                "run",
                "jupyter",
                "nbconvert",
                "--to",
                "html",
                "--execute",
                "--no-input",
                "--output",
                str(out_path),
                str(nb_path),
            ],
            check=True,
        )

    store: ParquetStore = ParquetStore(settings.data_dir / "processed")
    feature_panel: pd.DataFrame = FeaturePipeline(store=store).load_latest()
    prices: pd.DataFrame = store.load("prices_latest")
    result = MomentumBacktest(store=store).run(feature_panel=feature_panel, prices=prices, config=BacktestConfig())

    (results_dir / "backtest" / "summary.json").write_text(json.dumps(result.metrics_dict(), indent=2))
    (results_dir / "backtest" / "equity_curve.json").write_text(json.dumps(result.equity_curve_dict(), indent=2))
    (results_dir / "backtest" / "annual_returns.json").write_text(json.dumps(result.annual_returns_dict(), indent=2))

    latest_date: pd.Timestamp = feature_panel.index.get_level_values("date").max()
    ranking: pd.DataFrame = CrossSectionalRanker().rank(feature_panel, latest_date)
    signal_payload: dict[str, object] = {
        "as_of": latest_date.strftime("%Y-%m-%d"),
        "rankings": ranking[["symbol", "quintile", "z_score"]].to_dict(orient="records"),
    }
    (results_dir / "signals" / "latest_ranking.json").write_text(json.dumps(signal_payload, indent=2))
    _assert_safe_exports(results_dir)
    logger.info("Exported public results successfully")


if __name__ == "__main__":
    asyncio.run(main())