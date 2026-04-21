"""Example: compute market regime and performance metrics."""

import asyncio
import logging

import numpy as np
import pandas as pd

from csm.config.settings import settings
from csm.risk.metrics import PerformanceMetrics
from csm.risk.regime import RegimeDetector

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Compute regime and summary metrics for synthetic series."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        logger.warning("Public mode is enabled. This example uses synthetic time series only.")

    equity_curve: pd.Series = pd.Series(
        100.0 * np.exp(np.linspace(0.0, 0.25, 24)),
        index=pd.date_range("2024-01-31", periods=24, freq="ME", tz="Asia/Bangkok"),
    )
    regime_series: pd.Series = pd.Series(
        np.linspace(100.0, 140.0, 260),
        index=pd.date_range("2023-01-02", periods=260, freq="B", tz="Asia/Bangkok"),
    )
    regime = RegimeDetector().detect(regime_series, regime_series.index[-1])
    metrics: dict[str, float] = PerformanceMetrics().summary(equity_curve)
    logger.info("Risk metrics example", extra={"regime": regime.value, **metrics})


if __name__ == "__main__":
    asyncio.run(main())
