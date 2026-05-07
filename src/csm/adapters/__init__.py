"""Database adapters for quant-infra-db integration.

PostgresAdapter (db_csm_set), MongoAdapter (csm_logs), and GatewayAdapter
(db_gateway) are coordinated by AdapterManager from FastAPI lifespan.

Phase 2 ships only the ``PostgresAdapter`` slot; ``mongo`` and ``gateway``
remain ``None`` placeholders until Phases 3 and 4. ``AdapterManager`` is the
single coordination point referenced by the FastAPI lifespan in ``api.main``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from csm.adapters.postgres import PostgresAdapter

if TYPE_CHECKING:
    from csm.config.settings import Settings

logger: logging.Logger = logging.getLogger(__name__)


class AdapterManager:
    """Coordinator owning the lifecycle of every database adapter.

    Constructed once per app instance from ``AdapterManager.from_settings``,
    held on ``app.state.adapters`` by the FastAPI lifespan, and closed on
    shutdown. Adapters are constructed only when ``db_write_enabled`` is True
    *and* the relevant DSN is configured. Connection failures are logged and
    turned into ``None`` slots — the app always boots.

    Attributes:
        postgres: PostgresAdapter for ``db_csm_set``, or ``None`` when disabled.
        mongo: Reserved for ``MongoAdapter`` (Phase 3).
        gateway: Reserved for ``GatewayAdapter`` (Phase 4).
    """

    def __init__(self, *, postgres: PostgresAdapter | None = None) -> None:
        """Initialise the manager with already-connected adapter instances.

        Prefer :meth:`from_settings` over direct construction in production
        code.

        Args:
            postgres: Optional connected ``PostgresAdapter``.
        """
        self.postgres: PostgresAdapter | None = postgres
        self.mongo: object | None = None  # Phase 3 — MongoAdapter slot.
        self.gateway: object | None = None  # Phase 4 — GatewayAdapter slot.

    @classmethod
    async def from_settings(cls, settings: Settings) -> AdapterManager:
        """Construct adapters per ``Settings`` flags.

        When ``db_write_enabled=False``, returns a manager with every slot
        ``None``. When True, the Postgres adapter is constructed only when
        ``db_csm_set_dsn`` is set; missing DSNs and connect failures both
        downgrade the relevant slot to ``None`` with a logged warning.

        Args:
            settings: Application settings carrying DSN fields and the
                ``db_write_enabled`` flag.

        Returns:
            AdapterManager with adapters connected where configuration allows.
        """
        if not settings.db_write_enabled:
            logger.debug(
                "AdapterManager.from_settings: db_write_enabled=False — all adapters set to None"
            )
            return cls()

        postgres: PostgresAdapter | None = None
        if settings.db_csm_set_dsn:
            candidate = PostgresAdapter(settings.db_csm_set_dsn)
            try:
                await candidate.connect()
            except Exception as exc:
                logger.warning(
                    "PostgresAdapter connect failed; postgres slot disabled: %s",
                    exc,
                )
                postgres = None
            else:
                postgres = candidate
        else:
            logger.warning(
                "db_write_enabled=True but db_csm_set_dsn is not set; postgres slot disabled"
            )

        return cls(postgres=postgres)

    async def close(self) -> None:
        """Close every live adapter. Idempotent.

        Failures during close are logged but do not propagate, so a flaky
        teardown cannot prevent app shutdown.
        """
        if self.postgres is not None:
            try:
                await self.postgres.close()
            except Exception:
                logger.warning("PostgresAdapter close raised", exc_info=True)
            self.postgres = None

    async def ping(self) -> dict[str, str]:
        """Return per-adapter pool-based liveness results.

        Only adapters with a live pool contribute keys. The returned dict is
        empty when no adapter is live, so callers can merge it into a wider
        health-status dict without overwriting absent keys.

        Returns:
            Dict like ``{"postgres": "ok"}`` or ``{"postgres": "error:..."}``.
            Empty when no adapter is currently live.
        """
        results: dict[str, str] = {}
        if self.postgres is not None:
            try:
                ok: bool = await self.postgres.ping()
            except Exception as exc:
                results["postgres"] = f"error:{exc}"
            else:
                results["postgres"] = "ok" if ok else "error:select_1_failed"
        return results


__all__: list[str] = ["AdapterManager", "PostgresAdapter"]
