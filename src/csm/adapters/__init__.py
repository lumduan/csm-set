"""Database adapters for quant-infra-db integration.

PostgresAdapter (db_csm_set), MongoAdapter (csm_logs), and GatewayAdapter
(db_gateway) are coordinated by AdapterManager from FastAPI lifespan.

Phase 2 shipped the ``PostgresAdapter`` slot. Phase 3 filled the ``MongoAdapter``
slot. Phase 4 fills the ``GatewayAdapter`` slot.
``AdapterManager`` is the single coordination point referenced by the FastAPI
lifespan in ``api.main``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from csm.adapters.gateway import GatewayAdapter
from csm.adapters.mongo import MongoAdapter
from csm.adapters.postgres import PostgresAdapter

if TYPE_CHECKING:
    from csm.config.settings import Settings

logger: logging.Logger = logging.getLogger(__name__)


class AdapterManager:
    """Coordinator owning the lifecycle of every database adapter.

    Constructed once per app instance from ``AdapterManager.from_settings``,
    held on ``app.state.adapters`` by the FastAPI lifespan, and closed on
    shutdown. Adapters are constructed only when ``db_write_enabled`` is True
    *and* the relevant DSN / URI is configured. Connection failures are logged
    and turned into ``None`` slots — the app always boots.

    Attributes:
        postgres: PostgresAdapter for ``db_csm_set``, or ``None`` when disabled.
        mongo: MongoAdapter for ``csm_logs``, or ``None`` when disabled.
        gateway: Reserved for ``GatewayAdapter`` (Phase 4).
    """

    def __init__(
        self,
        *,
        postgres: PostgresAdapter | None = None,
        mongo: MongoAdapter | None = None,
        gateway: GatewayAdapter | None = None,
    ) -> None:
        """Initialise the manager with already-connected adapter instances.

        Prefer :meth:`from_settings` over direct construction in production
        code.

        Args:
            postgres: Optional connected ``PostgresAdapter``.
            mongo: Optional connected ``MongoAdapter``.
            gateway: Optional connected ``GatewayAdapter``.
        """
        self.postgres: PostgresAdapter | None = postgres
        self.mongo: MongoAdapter | None = mongo
        self.gateway: GatewayAdapter | None = gateway

    @classmethod
    async def from_settings(cls, settings: Settings) -> AdapterManager:
        """Construct adapters per ``Settings`` flags.

        When ``db_write_enabled=False``, returns a manager with every slot
        ``None``. When True, each adapter is constructed only when its
        corresponding DSN / URI is set; missing config and connect failures
        both downgrade the relevant slot to ``None`` with a logged warning.

        Args:
            settings: Application settings carrying DSN / URI fields and the
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
            pg_candidate = PostgresAdapter(settings.db_csm_set_dsn)
            try:
                await pg_candidate.connect()
            except Exception as exc:
                logger.warning(
                    "PostgresAdapter connect failed; postgres slot disabled: %s",
                    exc,
                )
                postgres = None
            else:
                postgres = pg_candidate
        else:
            logger.warning(
                "db_write_enabled=True but db_csm_set_dsn is not set; postgres slot disabled"
            )

        mongo: MongoAdapter | None = None
        if settings.mongo_uri:
            mongo_candidate = MongoAdapter(settings.mongo_uri)
            try:
                await mongo_candidate.connect()
            except Exception as exc:
                logger.warning(
                    "MongoAdapter connect failed; mongo slot disabled: %s",
                    exc,
                )
                mongo = None
            else:
                mongo = mongo_candidate
        else:
            logger.warning("db_write_enabled=True but mongo_uri is not set; mongo slot disabled")

        gateway: GatewayAdapter | None = None
        if settings.db_gateway_dsn:
            gw_candidate = GatewayAdapter(settings.db_gateway_dsn)
            try:
                await gw_candidate.connect()
            except Exception as exc:
                logger.warning(
                    "GatewayAdapter connect failed; gateway slot disabled: %s",
                    exc,
                )
                gateway = None
            else:
                gateway = gw_candidate
        else:
            logger.warning(
                "db_write_enabled=True but db_gateway_dsn is not set; gateway slot disabled"
            )

        return cls(postgres=postgres, mongo=mongo, gateway=gateway)

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
        if self.mongo is not None:
            try:
                await self.mongo.close()
            except Exception:
                logger.warning("MongoAdapter close raised", exc_info=True)
            self.mongo = None
        if self.gateway is not None:
            try:
                await self.gateway.close()
            except Exception:
                logger.warning("GatewayAdapter close raised", exc_info=True)
            self.gateway = None

    async def ping(self) -> dict[str, str]:
        """Return per-adapter pool/client-based liveness results.

        Only adapters with a live client contribute keys. The returned dict is
        empty when no adapter is live, so callers can merge it into a wider
        health-status dict without overwriting absent keys.

        Returns:
            Dict like ``{"postgres": "ok", "mongo": "ok"}`` with values either
            ``"ok"`` or ``"error:<msg>"``. Empty when no adapter is currently
            live.
        """
        results: dict[str, str] = {}
        if self.postgres is not None:
            try:
                ok: bool = await self.postgres.ping()
            except Exception as exc:
                results["postgres"] = f"error:{exc}"
            else:
                results["postgres"] = "ok" if ok else "error:select_1_failed"
        if self.mongo is not None:
            try:
                ok_mongo: bool = await self.mongo.ping()
            except Exception as exc:
                results["mongo"] = f"error:{exc}"
            else:
                results["mongo"] = "ok" if ok_mongo else "error:ping_failed"
        if self.gateway is not None:
            try:
                ok_gw: bool = await self.gateway.ping()
            except Exception as exc:
                results["gateway"] = f"error:{exc}"
            else:
                results["gateway"] = "ok" if ok_gw else "error:ping_failed"
        return results


__all__: list[str] = ["AdapterManager", "GatewayAdapter", "MongoAdapter", "PostgresAdapter"]
