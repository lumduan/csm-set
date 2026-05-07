"""MongoAdapter for csm_logs write-back and history reads.

Owns one ``motor.AsyncIOMotorClient`` and exposes idempotent write methods for
the three ``csm_logs`` collections (``backtest_results``, ``signal_snapshots``,
``model_params``) plus typed read methods returning frozen Pydantic models.

The collections themselves are owned by the ``quant-infra-db`` stack and are
not declared here — ``MongoAdapter`` only writes against existing collections.

Lifecycle:

>>> async with MongoAdapter(uri) as mongo:  # doctest: +SKIP
...     await mongo.write_signal_snapshot("csm-set", today, rankings)

For best-effort persistence, callers wrap each call in their own
``try/except`` and log a warning on failure (see PLAN.md Phase 5 hooks).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

from csm.adapters.models import (
    BacktestResultDoc,
    BacktestSummaryRow,
    ModelParamsDoc,
    SignalSnapshotDoc,
)

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_DB_NAME: str = "csm_logs"
DEFAULT_SERVER_SELECTION_TIMEOUT_MS: int = 5000


@dataclass(frozen=True)
class _Collections:
    """Centralised collection names for ``csm_logs``.

    No inline string literals in adapter methods — every collection name lives
    here and is referenced by attribute. Mirrors the ``_SQLStatements`` pattern
    in ``PostgresAdapter``.
    """

    BACKTEST_RESULTS: str = "backtest_results"
    SIGNAL_SNAPSHOTS: str = "signal_snapshots"
    MODEL_PARAMS: str = "model_params"


_COLL: _Collections = _Collections()

# Excludes the Mongo-internal ``_id`` field on every read so consumers never
# see ObjectIds.
_DROP_ID: dict[str, int] = {"_id": 0}


class MongoAdapter:
    """Async adapter for the ``csm_logs`` MongoDB database.

    Owns one ``motor.AsyncIOMotorClient``. Writes upsert on natural keys
    (``run_id``; ``(strategy_id, date)``; ``(strategy_id, version)``) so
    re-running a daily refresh or replaying a backtest is idempotent. Reads
    return frozen Pydantic models with the Mongo-internal ``_id`` stripped.

    Attributes:
        uri: MongoDB connection URI (read-only).
        db_name: Target database name (defaults to ``"csm_logs"``).
    """

    def __init__(self, uri: str, db_name: str = DEFAULT_DB_NAME) -> None:
        """Initialise without connecting.

        Args:
            uri: MongoDB connection URI for ``csm_logs``.
            db_name: Database name (default ``"csm_logs"``).
        """
        self._uri: str = uri
        self._db_name: str = db_name
        self._client: AsyncIOMotorClient[dict[str, Any]] | None = None

    @property
    def uri(self) -> str:
        """Return the configured URI (read-only)."""
        return self._uri

    @property
    def db_name(self) -> str:
        """Return the target database name (read-only)."""
        return self._db_name

    async def connect(self) -> None:
        """Open the motor client and verify connectivity. Idempotent.

        Constructs ``AsyncIOMotorClient(uri, tz_aware=True,
        serverSelectionTimeoutMS=5000)`` then issues an explicit
        ``admin.command("ping")`` so server-unreachable / auth failures
        surface here rather than at first write.

        Raises:
            pymongo.errors.PyMongoError: When the server is unreachable, auth
                fails, or the ping times out.
        """
        if self._client is not None:
            return
        client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
            self._uri,
            tz_aware=True,
            serverSelectionTimeoutMS=DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
        )
        try:
            await client.admin.command("ping")
        except Exception:
            client.close()
            raise
        self._client = client
        logger.info("MongoAdapter client opened (db=%s, tz_aware=True)", self._db_name)

    async def close(self) -> None:
        """Close the motor client. Idempotent — second call is a no-op."""
        if self._client is None:
            return
        client = self._client
        self._client = None
        client.close()
        logger.info("MongoAdapter client closed")

    async def __aenter__(self) -> MongoAdapter:
        """Open the client and return self."""
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Close the client."""
        await self.close()

    async def ping(self) -> bool:
        """Issue ``admin.command("ping")`` to confirm liveness.

        Returns:
            ``True`` when the server returns ``{"ok": 1.0}``; ``False``
            otherwise.

        Raises:
            RuntimeError: When the client has not been opened.
            pymongo.errors.PyMongoError: When the server is unreachable.
        """
        client = self._require_client()
        result: dict[str, Any] = await client.admin.command("ping")
        return result.get("ok") == 1.0

    def _require_client(self) -> AsyncIOMotorClient[dict[str, Any]]:
        """Return the live client or raise if ``connect()`` was never called."""
        if self._client is None:
            raise RuntimeError(
                "MongoAdapter is not connected. Call 'await adapter.connect()' "
                "or use 'async with adapter:' first."
            )
        return self._client

    def _db(self) -> AsyncIOMotorDatabase[dict[str, Any]]:
        """Return the target ``AsyncIOMotorDatabase`` handle."""
        return self._require_client()[self._db_name]

    def _coll(self, name: str) -> AsyncIOMotorCollection[dict[str, Any]]:
        """Return the named collection handle within the target database."""
        return self._db()[name]

    async def write_backtest_result(self, result_doc: dict[str, object]) -> None:
        """Upsert one backtest result document keyed on ``run_id``.

        Uses ``replace_one`` so re-running a backtest with the same ``run_id``
        cleanly replaces the prior payload (vs. merging via ``$set``).

        Args:
            result_doc: Backtest result payload. Must contain a ``run_id`` key.

        Raises:
            RuntimeError: When the client has not been opened.
            KeyError: When ``result_doc`` is missing ``run_id``.
            pymongo.errors.PyMongoError: On database error.
        """
        if "run_id" not in result_doc:
            raise KeyError("result_doc is missing required key: 'run_id'")
        coll = self._coll(_COLL.BACKTEST_RESULTS)
        run_id: object = result_doc["run_id"]
        await coll.replace_one({"run_id": run_id}, result_doc, upsert=True)
        logger.debug("write_backtest_result run_id=%s", run_id)

    async def write_signal_snapshot(
        self,
        strategy_id: str,
        date: datetime,
        rankings: list[dict[str, object]],
    ) -> None:
        """Upsert a daily signal snapshot keyed on ``(strategy_id, date)``.

        Uses ``update_one`` with ``$set`` so re-runs that add fields extend
        rather than overwrite the document.

        Args:
            strategy_id: Strategy identifier (e.g. ``"csm-set"``).
            date: tz-aware timestamp (UTC) representing the trading day.
            rankings: Per-symbol ranking records.

        Raises:
            RuntimeError: When the client has not been opened.
            pymongo.errors.PyMongoError: On database error.
        """
        coll = self._coll(_COLL.SIGNAL_SNAPSHOTS)
        doc: dict[str, object] = {
            "strategy_id": strategy_id,
            "date": date,
            "rankings": rankings,
        }
        await coll.update_one(
            {"strategy_id": strategy_id, "date": date},
            {"$set": doc},
            upsert=True,
        )
        logger.debug(
            "write_signal_snapshot strategy=%s date=%s rankings=%d",
            strategy_id,
            date,
            len(rankings),
        )

    async def write_model_params(
        self,
        strategy_id: str,
        version: str,
        params: dict[str, object],
    ) -> None:
        """Upsert a versioned model-params snapshot.

        Keyed on ``(strategy_id, version)``. Uses ``update_one`` with ``$set``
        so future field additions extend rather than overwrite.

        Args:
            strategy_id: Strategy identifier.
            version: Free-form version label (e.g. ``"v0.7.1"``).
            params: Parameter snapshot dict.

        Raises:
            RuntimeError: When the client has not been opened.
            pymongo.errors.PyMongoError: On database error.
        """
        coll = self._coll(_COLL.MODEL_PARAMS)
        doc: dict[str, object] = {
            "strategy_id": strategy_id,
            "version": version,
            "params": params,
        }
        await coll.update_one(
            {"strategy_id": strategy_id, "version": version},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(tz=UTC)}},
            upsert=True,
        )
        logger.debug("write_model_params strategy=%s version=%s", strategy_id, version)

    async def read_backtest_result(self, run_id: str) -> BacktestResultDoc | None:
        """Return the backtest result document for ``run_id`` or ``None``.

        Args:
            run_id: Unique backtest run identifier.

        Returns:
            ``BacktestResultDoc`` when the document exists; ``None`` otherwise.

        Raises:
            RuntimeError: When the client has not been opened.
            pymongo.errors.PyMongoError: On database error.
        """
        coll = self._coll(_COLL.BACKTEST_RESULTS)
        doc: dict[str, Any] | None = await coll.find_one({"run_id": run_id}, _DROP_ID)
        if doc is None:
            return None
        return BacktestResultDoc.model_validate(doc)

    async def read_signal_snapshot(
        self, strategy_id: str, date: datetime
    ) -> SignalSnapshotDoc | None:
        """Return the signal snapshot for ``(strategy_id, date)`` or ``None``.

        Args:
            strategy_id: Strategy identifier.
            date: tz-aware timestamp (UTC) representing the trading day.

        Returns:
            ``SignalSnapshotDoc`` when the document exists; ``None`` otherwise.

        Raises:
            RuntimeError: When the client has not been opened.
            pymongo.errors.PyMongoError: On database error.
        """
        coll = self._coll(_COLL.SIGNAL_SNAPSHOTS)
        doc: dict[str, Any] | None = await coll.find_one(
            {"strategy_id": strategy_id, "date": date}, _DROP_ID
        )
        if doc is None:
            return None
        return SignalSnapshotDoc.model_validate(doc)

    async def read_model_params(self, strategy_id: str, version: str) -> ModelParamsDoc | None:
        """Return the model-params snapshot for ``(strategy_id, version)`` or ``None``.

        Args:
            strategy_id: Strategy identifier.
            version: Version label.

        Returns:
            ``ModelParamsDoc`` when the document exists; ``None`` otherwise.

        Raises:
            RuntimeError: When the client has not been opened.
            pymongo.errors.PyMongoError: On database error.
        """
        coll = self._coll(_COLL.MODEL_PARAMS)
        doc: dict[str, Any] | None = await coll.find_one(
            {"strategy_id": strategy_id, "version": version}, _DROP_ID
        )
        if doc is None:
            return None
        return ModelParamsDoc.model_validate(doc)

    async def list_backtest_results(
        self,
        strategy_id: str | None = None,
        limit: int = 50,
    ) -> list[BacktestSummaryRow]:
        """Return slim summary rows for the most recent backtests.

        Excludes the potentially-large ``equity_curve`` and ``trades`` arrays
        via projection so listing payloads stay cheap.

        Args:
            strategy_id: When set, filter to rows for this strategy. ``None``
                returns rows across all strategies.
            limit: Maximum number of rows to return. Defaults to 50.

        Returns:
            ``BacktestSummaryRow`` list ordered by ``created_at`` descending.

        Raises:
            RuntimeError: When the client has not been opened.
            pymongo.errors.PyMongoError: On database error.
        """
        coll = self._coll(_COLL.BACKTEST_RESULTS)
        filter_doc: dict[str, object] = {}
        if strategy_id is not None:
            filter_doc["strategy_id"] = strategy_id
        projection: dict[str, int] = {
            "_id": 0,
            "run_id": 1,
            "strategy_id": 1,
            "created_at": 1,
            "metrics": 1,
        }
        cursor = coll.find(filter_doc, projection).sort("created_at", -1).limit(limit)
        docs: list[dict[str, Any]] = await cursor.to_list(length=limit)
        return [BacktestSummaryRow.model_validate(d) for d in docs]


__all__: list[str] = ["MongoAdapter"]
