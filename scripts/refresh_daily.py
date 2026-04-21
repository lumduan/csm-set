"""Run the owner-side daily refresh pipeline manually."""

import asyncio
import logging
from pathlib import Path

from api.scheduler.jobs import daily_refresh
from csm.config.settings import settings
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Execute the same logic as the scheduled daily refresh job."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        raise RuntimeError("refresh_daily.py is owner-only. Set CSM_PUBLIC_MODE=false before running.")
    store: ParquetStore = ParquetStore(Path(settings.data_dir) / "processed")
    await daily_refresh(settings=settings, store=store)
    logger.info("Manual daily refresh completed")


if __name__ == "__main__":
    asyncio.run(main())