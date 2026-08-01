"""Shared fixtures for ``infra_db`` integration tests against ``db_csm_set`` and ``csm_logs``.

Skipped automatically when ``CSM_DB_CSM_SET_DSN`` / ``CSM_MONGO_URI`` is not set
so the suite is safe to run without the live stack. Each adapter fixture
wipes its own ``test-csm-set`` artefacts before and after the test that
requests it, so tests that touch only one tier do not pay the other tier's
setup cost. ``backtest_results`` documents are wiped by ``run_id`` regex
``^test-csm-set-`` since that collection is keyed on ``run_id`` rather than
``strategy_id``.

Point this suite at a **disposable** database
---------------------------------------------
Every fixture here mutates its target. ``portfolio_snapshot`` is the awkward
case: it is cross-strategy, carries **no** ``strategy_id`` column, and its
unique index (``uq_portfolio_snapshot_time``) is on ``time`` alone — so the
``WHERE strategy_id = $1`` convention every other table uses cannot be
expressed for it. This fixture file previously resorted to a bare
``DELETE FROM portfolio_snapshot``, which on 2026-08-01 emptied the live
cross-strategy table when the suite was run against production DSNs (65 rows,
restored; see ``docs/live-test/events/2026-08-01-portfolio-snapshot-wiped-by-test-fixture.md``).

Two mechanisms now prevent a repeat:

1. **Test rows are self-identifying.** Seeded snapshots carry ``TEST_STRATEGY_ID``
   as an ``allocation`` key and a deliberately odd time-of-day
   (:data:`TEST_SNAPSHOT_TIME_OF_DAY`), so they can neither be confused with a
   production row nor collide with one on the ``time``-only unique index —
   production writes midnight buckets exclusively. The wipe is scoped to that
   marker.
2. **The suite refuses to run against a populated table.** :func:`_assert_no_foreign_snapshots`
   fails the test outright when ``portfolio_snapshot`` holds rows this suite did
   not create, rather than deleting them. On an ephemeral CI stack the table is
   empty and nothing changes; against a real database it is a loud error.

Both are deliberate: (1) is the root repair, (2) is the backstop for the next
table that turns out to have no scoping key.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta

import asyncpg
import pytest
import pytest_asyncio

from csm.adapters import AdapterManager
from csm.adapters.gateway import GatewayAdapter
from csm.adapters.mongo import DEFAULT_DB_NAME, MongoAdapter
from csm.adapters.postgres import PostgresAdapter

TEST_STRATEGY_ID: str = "test-csm-set"
TEST_RUN_ID_PREFIX: str = "test-csm-set-"

# Deliberately not midnight. `portfolio_snapshot` is unique on `time` alone and
# production writes 00:00:00 buckets exclusively, so seeding at this offset makes
# a collision with a real row impossible while staying inside the calendar-day
# read window that `read_portfolio_snapshots` applies.
TEST_SNAPSHOT_TIME_OF_DAY: time = time(3, 7, 11, 123)

# Scoped replacements for what used to be a bare `DELETE FROM portfolio_snapshot`.
# `allocation ? $1` is the JSONB key-existence operator — it matches only rows this
# suite seeded, because every seeded snapshot carries TEST_STRATEGY_ID as a key.
_DELETE_TEST_SNAPSHOTS: str = "DELETE FROM portfolio_snapshot WHERE allocation ? $1"
_COUNT_FOREIGN_SNAPSHOTS: str = (
    "SELECT count(*) FROM portfolio_snapshot WHERE allocation IS NULL OR NOT (allocation ? $1)"
)


def snapshot_time_utc(days_ago: int = 0) -> datetime:
    """Return a UTC timestamp ``days_ago`` days back at the test time-of-day.

    Used by both the seed helpers here and the tests, so the marker convention
    lives in exactly one place.
    """
    day = (datetime.now(UTC) - timedelta(days=days_ago)).date()
    return datetime.combine(day, TEST_SNAPSHOT_TIME_OF_DAY, tzinfo=UTC)


async def _assert_no_foreign_snapshots(pool: asyncpg.Pool) -> None:
    """Fail the test when ``portfolio_snapshot`` holds rows this suite did not create.

    The guard keys on the invariant actually being protected — "is there data here
    that isn't mine?" — rather than on a proxy for it such as a database name or an
    opt-in environment variable. A name check would break the CI job, which
    legitimately uses production-looking DSNs against a throwaway stack; an env var
    is one line in a local ``.env`` away from being permanently disabled, which is
    close to how the 2026-08-01 incident happened.
    """
    foreign: object = await pool.fetchval(_COUNT_FOREIGN_SNAPSHOTS, TEST_STRATEGY_ID)
    if foreign:
        pytest.fail(
            f"Refusing to run: portfolio_snapshot holds {foreign} row(s) this suite did not "
            f"create. These fixtures mutate every table they touch and the table has no "
            f"strategy_id to scope by. Point CSM_DB_GATEWAY_DSN at a disposable database."
        )


def _live_dsn() -> str | None:
    """Return the live ``db_csm_set`` DSN from env, or ``None`` when unset."""
    return os.environ.get("CSM_DB_CSM_SET_DSN")


def _live_mongo_uri() -> str | None:
    """Return the live ``csm_logs`` URI from env, or ``None`` when unset."""
    return os.environ.get("CSM_MONGO_URI")


def _live_gateway_dsn() -> str | None:
    """Return the live ``db_gateway`` DSN from env, or ``None`` when unset."""
    return os.environ.get("CSM_DB_GATEWAY_DSN")


def _mongo_db_name() -> str:
    """Return the Mongo database to target, defaulting to production ``csm_logs``.

    The Mongo wipes are all correctly scoped (``strategy_id`` / a ``run_id`` prefix),
    so this is hygiene rather than a fix — it lets a verification run stay entirely
    off the production database. Mongo creates databases lazily, so a scratch name
    needs no setup.
    """
    return os.environ.get("CSM_MONGO_DB_NAME", DEFAULT_DB_NAME)


@pytest_asyncio.fixture
async def adapter() -> AsyncIterator[PostgresAdapter]:
    """Yield a connected ``PostgresAdapter`` against the real ``db_csm_set``.

    Skips when ``CSM_DB_CSM_SET_DSN`` is not set. Wipes ``test-csm-set`` rows
    before and after the test, then closes the pool.
    """
    dsn = _live_dsn()
    if not dsn:
        pytest.skip("CSM_DB_CSM_SET_DSN must be set for infra_db tests")

    pg = PostgresAdapter(dsn)
    await pg.connect()

    async def _wipe() -> None:
        pool = pg._require_pool()  # noqa: SLF001 — test-only access
        for table in ("equity_curve", "trade_history", "backtest_log"):
            await pool.execute(f"DELETE FROM {table} WHERE strategy_id = $1", TEST_STRATEGY_ID)

    try:
        await _wipe()
        yield pg
    finally:
        try:
            await _wipe()
        finally:
            await pg.close()


_UPSERT_DAILY_PERFORMANCE: str = (
    "INSERT INTO daily_performance (time, strategy_id, daily_return, cumulative_return, "
    "total_value, cash_balance, max_drawdown, sharpe_ratio, metadata) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb) "
    "ON CONFLICT (time, strategy_id) DO UPDATE SET "
    "daily_return = EXCLUDED.daily_return, cumulative_return = EXCLUDED.cumulative_return, "
    "total_value = EXCLUDED.total_value, cash_balance = EXCLUDED.cash_balance, "
    "max_drawdown = EXCLUDED.max_drawdown, sharpe_ratio = EXCLUDED.sharpe_ratio, "
    "metadata = EXCLUDED.metadata"
)

_UPSERT_PORTFOLIO_SNAPSHOT: str = (
    "INSERT INTO portfolio_snapshot (time, total_portfolio, weighted_return, "
    "combined_drawdown, active_strategies, allocation) "
    "VALUES ($1, $2, $3, $4, $5, $6::jsonb) "
    "ON CONFLICT (time) DO UPDATE SET "
    "total_portfolio = EXCLUDED.total_portfolio, weighted_return = EXCLUDED.weighted_return, "
    "combined_drawdown = EXCLUDED.combined_drawdown, "
    "active_strategies = EXCLUDED.active_strategies, allocation = EXCLUDED.allocation"
)


async def seed_daily_performance(
    gw: GatewayAdapter,
    when: datetime,
    metrics: dict[str, object],
    strategy_id: str = TEST_STRATEGY_ID,
) -> None:
    """Insert one ``daily_performance`` row directly, for read-path tests.

    ``GatewayAdapter`` is **read-only** — the write path moved to the HTTP ingestion
    contract (``POST /api/v1/ingest/daily-report``) in commit ``0486e5d``. Seeding
    here goes through raw SQL rather than the adapter so these tests exercise the
    thing csm-set still owns: the read window. The upsert clause mirrors the
    gateway service's own so a re-seed behaves the same way, but note that the
    service's idempotency is *its* contract to test, not this suite's.
    """
    pool = gw._require_pool()  # noqa: SLF001 — test-only access
    await pool.execute(
        _UPSERT_DAILY_PERFORMANCE,
        when,
        strategy_id,
        metrics.get("daily_return"),
        metrics.get("cumulative_return"),
        metrics.get("total_value"),
        metrics.get("cash_balance"),
        metrics.get("max_drawdown"),
        metrics.get("sharpe_ratio"),
        metrics,
    )


async def seed_portfolio_snapshot(
    gw: GatewayAdapter,
    when: datetime,
    snapshot: dict[str, object],
) -> None:
    """Insert one ``portfolio_snapshot`` row directly, for read-path tests.

    ``TEST_STRATEGY_ID`` is forced into ``allocation`` so the row is self-identifying:
    it is what the scoped cleanup matches on and what tests filter by when reading a
    table that is cross-strategy by design. Callers should build ``when`` with
    :func:`snapshot_time_utc` so the row cannot collide with a production midnight row.
    """
    allocation_raw: object = snapshot.get("allocation")
    allocation: dict[str, object] = dict(allocation_raw) if isinstance(allocation_raw, dict) else {}
    allocation.setdefault(TEST_STRATEGY_ID, 1.0)

    pool = gw._require_pool()  # noqa: SLF001 — test-only access
    await pool.execute(
        _UPSERT_PORTFOLIO_SNAPSHOT,
        when,
        snapshot.get("total_portfolio"),
        snapshot.get("weighted_return"),
        snapshot.get("combined_drawdown"),
        snapshot.get("active_strategies"),
        allocation,
    )


@pytest_asyncio.fixture
async def mongo_adapter() -> AsyncIterator[MongoAdapter]:
    """Yield a connected ``MongoAdapter`` against the real ``csm_logs``.

    Skips when ``CSM_MONGO_URI`` is not set. Wipes ``test-csm-set`` documents
    before and after the test, then closes the client.
    """
    uri = _live_mongo_uri()
    if not uri:
        pytest.skip("CSM_MONGO_URI must be set for infra_db tests")

    mg = MongoAdapter(uri, db_name=_mongo_db_name())
    await mg.connect()

    async def _wipe() -> None:
        db = mg._db()  # noqa: SLF001 — test-only access
        await db["signal_snapshots"].delete_many({"strategy_id": TEST_STRATEGY_ID})
        await db["model_params"].delete_many({"strategy_id": TEST_STRATEGY_ID})
        await db["backtest_results"].delete_many({"run_id": {"$regex": f"^{TEST_RUN_ID_PREFIX}"}})

    try:
        await _wipe()
        yield mg
    finally:
        try:
            await _wipe()
        finally:
            await mg.close()


@pytest_asyncio.fixture
async def gateway_adapter() -> AsyncIterator[GatewayAdapter]:
    """Yield a connected ``GatewayAdapter`` against the real ``db_gateway``.

    Skips when ``CSM_DB_GATEWAY_DSN`` is not set. Wipes ``test-csm-set``
    rows before and after the test, then closes the pool.
    """
    dsn = _live_gateway_dsn()
    if not dsn:
        pytest.skip("CSM_DB_GATEWAY_DSN must be set for infra_db tests")

    gw = GatewayAdapter(dsn)
    await gw.connect()

    async def _wipe() -> None:
        pool = gw._require_pool()  # noqa: SLF001 — test-only access
        await pool.execute("DELETE FROM daily_performance WHERE strategy_id = $1", TEST_STRATEGY_ID)
        await pool.execute(_DELETE_TEST_SNAPSHOTS, TEST_STRATEGY_ID)

    try:
        # Check before the first wipe, not after: the point is to refuse rather
        # than to delete, so this has to run while there is still something to save.
        await _assert_no_foreign_snapshots(gw._require_pool())  # noqa: SLF001
        await _wipe()
        yield gw
    finally:
        try:
            await _wipe()
        finally:
            await gw.close()


@pytest_asyncio.fixture
async def adapter_manager() -> AsyncIterator[AdapterManager]:
    """Yield a live ``AdapterManager`` with all configured adapters connected.

    Skips when none of the DSN/URI env vars are set. Wipes
    ``test-csm-set`` artefacts from all three stores before and after
    the test, then closes every adapter.
    """
    dsn = _live_dsn()
    mongo_uri = _live_mongo_uri()
    gateway_dsn = _live_gateway_dsn()

    if not dsn and not mongo_uri and not gateway_dsn:
        pytest.skip("No DB DSNs set for infra_db adapter_manager fixture")

    postgres: PostgresAdapter | None = None
    mongo: MongoAdapter | None = None
    gateway: GatewayAdapter | None = None

    if dsn:
        postgres = PostgresAdapter(dsn)
        await postgres.connect()
    if mongo_uri:
        mongo = MongoAdapter(mongo_uri, db_name=_mongo_db_name())
        await mongo.connect()
    if gateway_dsn:
        gateway = GatewayAdapter(gateway_dsn)
        await gateway.connect()

    manager = AdapterManager(postgres=postgres, mongo=mongo, gateway=gateway)

    async def _wipe() -> None:
        if postgres is not None:
            pool = postgres._require_pool()  # noqa: SLF001
            for table in ("equity_curve", "trade_history", "backtest_log"):
                await pool.execute(f"DELETE FROM {table} WHERE strategy_id = $1", TEST_STRATEGY_ID)
        if mongo is not None:
            db = mongo._db()  # noqa: SLF001
            await db["signal_snapshots"].delete_many({"strategy_id": TEST_STRATEGY_ID})
            await db["model_params"].delete_many({"strategy_id": TEST_STRATEGY_ID})
            await db["backtest_results"].delete_many(
                {"run_id": {"$regex": f"^{TEST_RUN_ID_PREFIX}"}}
            )
        if gateway is not None:
            pool = gateway._require_pool()  # noqa: SLF001
            await pool.execute(
                "DELETE FROM daily_performance WHERE strategy_id = $1", TEST_STRATEGY_ID
            )
            await pool.execute(_DELETE_TEST_SNAPSHOTS, TEST_STRATEGY_ID)

    try:
        if gateway is not None:
            await _assert_no_foreign_snapshots(gateway._require_pool())  # noqa: SLF001
        await _wipe()
        yield manager
    finally:
        try:
            await _wipe()
        finally:
            await manager.close()
