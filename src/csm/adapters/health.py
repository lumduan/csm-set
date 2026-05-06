"""Database connectivity health checks for quant-infra-db."""

from __future__ import annotations

import logging
from typing import Any

from csm.config.settings import Settings

logger = logging.getLogger(__name__)


async def check_db_connectivity(settings: Settings) -> dict[str, str] | None:
    """Check connectivity to quant-postgres and quant-mongo.

    Uses short-lived connections so the check can run before lifespan startup
    and independently of any connection pool. Each check runs independently
    so one failure does not block the other.

    Args:
        settings: Application settings with DSN fields and db_write_enabled flag.

    Returns:
        ``None`` when ``db_write_enabled`` is ``False``.
        ``{"postgres": "ok"|"error:<msg>", "mongo": "ok"|"error:<msg>"}`` otherwise.

    Example:
        >>> status = await check_db_connectivity(settings)
        >>> print(status)
        {'postgres': 'ok', 'mongo': 'ok'}
    """
    if not settings.db_write_enabled:
        return None

    postgres_status: str = "error:not checked"
    mongo_status: str = "error:not checked"

    if settings.db_csm_set_dsn:
        try:
            import asyncpg

            conn = await asyncpg.connect(dsn=settings.db_csm_set_dsn, timeout=5)
            await conn.close()
            postgres_status = "ok"
        except Exception as exc:
            postgres_status = f"error:{exc}"
            logger.warning("PostgreSQL connectivity check failed: %s", exc)
    else:
        postgres_status = "error:db_csm_set_dsn not configured"

    if settings.mongo_uri:
        try:
            import motor.motor_asyncio

            mongo_client: motor.motor_asyncio.AsyncIOMotorClient[Any] = (
                motor.motor_asyncio.AsyncIOMotorClient(
                    settings.mongo_uri, serverSelectionTimeoutMS=5000
                )
            )
            await mongo_client.admin.command("ping")
            mongo_client.close()
            mongo_status = "ok"
        except Exception as exc:
            mongo_status = f"error:{exc}"
            logger.warning("MongoDB connectivity check failed: %s", exc)
    else:
        mongo_status = "error:mongo_uri not configured"

    return {"postgres": postgres_status, "mongo": mongo_status}
