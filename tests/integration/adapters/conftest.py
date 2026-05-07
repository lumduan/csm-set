"""Shared fixtures for ``infra_db`` integration tests against ``db_csm_set`` and ``csm_logs``.

Skipped automatically when ``CSM_DB_CSM_SET_DSN`` / ``CSM_MONGO_URI`` is not set
so the suite is safe to run without the live stack. Each adapter fixture
wipes its own ``test-csm-set`` artefacts before and after the test that
requests it, so tests that touch only one tier do not pay the other tier's
setup cost. ``backtest_results`` documents are wiped by ``run_id`` regex
``^test-csm-set-`` since that collection is keyed on ``run_id`` rather than
``strategy_id``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from csm.adapters.mongo import MongoAdapter
from csm.adapters.postgres import PostgresAdapter

TEST_STRATEGY_ID: str = "test-csm-set"
TEST_RUN_ID_PREFIX: str = "test-csm-set-"


def _live_dsn() -> str | None:
    """Return the live ``db_csm_set`` DSN from env, or ``None`` when unset."""
    return os.environ.get("CSM_DB_CSM_SET_DSN")


def _live_mongo_uri() -> str | None:
    """Return the live ``csm_logs`` URI from env, or ``None`` when unset."""
    return os.environ.get("CSM_MONGO_URI")


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


@pytest_asyncio.fixture
async def mongo_adapter() -> AsyncIterator[MongoAdapter]:
    """Yield a connected ``MongoAdapter`` against the real ``csm_logs``.

    Skips when ``CSM_MONGO_URI`` is not set. Wipes ``test-csm-set`` documents
    before and after the test, then closes the client.
    """
    uri = _live_mongo_uri()
    if not uri:
        pytest.skip("CSM_MONGO_URI must be set for infra_db tests")

    mg = MongoAdapter(uri)
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
