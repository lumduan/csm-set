"""Example: read public-safe result payloads from the results directory."""

import asyncio
import json
import logging

from csm.config.settings import settings

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Inspect the committed public result files."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        logger.warning("Public mode is enabled. Reading committed public-safe result files only.")

    signals_path = settings.results_dir / "signals" / "latest_ranking.json"
    backtest_path = settings.results_dir / "backtest" / "summary.json"
    signals_payload: object = json.loads(signals_path.read_text()) if signals_path.exists() else {}
    backtest_payload: object = json.loads(backtest_path.read_text()) if backtest_path.exists() else {}
    logger.info("Public results example", extra={"signals": signals_payload, "backtest": backtest_payload})


if __name__ == "__main__":
    asyncio.run(main())