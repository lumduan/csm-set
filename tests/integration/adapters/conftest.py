"""Shared fixtures for ``infra_db`` integration tests against ``db_csm_set``.

Skipped automatically when ``CSM_DB_CSM_SET_DSN`` is not set so the suite is
safe to run without the live stack. The ``test-csm-set`` strategy id is
reserved for these tests; an autouse fixture cleans it up between cases.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from csm.adapters.postgres import PostgresAdapter

TEST_STRATEGY_ID: str = "test-csm-set"


def _live_dsn() -> str | None:
    """Return the live ``db_csm_set`` DSN from env, or ``None`` when unset."""
    return os.environ.get("CSM_DB_CSM_SET_DSN")


@pytest_asyncio.fixture
async def adapter() -> AsyncIterator[PostgresAdapter]:
    """Yield a connected ``PostgresAdapter`` against the real ``db_csm_set``.

    Skips when ``CSM_DB_CSM_SET_DSN`` is not set. Closes the pool on teardown.
    """
    dsn = _live_dsn()
    if not dsn:
        pytest.skip("CSM_DB_CSM_SET_DSN must be set for infra_db tests")

    pg = PostgresAdapter(dsn)
    await pg.connect()
    try:
        yield pg
    finally:
        await pg.close()


@pytest_asyncio.fixture(autouse=True)
async def _wipe_test_strategy(adapter: PostgresAdapter) -> AsyncIterator[None]:
    """Delete every ``test-csm-set`` row before and after each test.

    Keeps integration tests independent of one another and ensures a leftover
    row from a previous failure does not leak into the next run.
    """

    async def _wipe() -> None:
        pool = adapter._require_pool()  # noqa: SLF001 — test-only access
        for table in ("equity_curve", "trade_history", "backtest_log"):
            await pool.execute(f"DELETE FROM {table} WHERE strategy_id = $1", TEST_STRATEGY_ID)

    await _wipe()
    try:
        yield
    finally:
        await _wipe()
