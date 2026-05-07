"""Integration tests for check_db_connectivity against the real quant-infra-db stack.

Requires quant-postgres and quant-mongo running on quant-network.
Skipped by default — run explicitly with: pytest -m infra_db
"""

from __future__ import annotations

import os

import pytest

from csm.adapters.health import check_db_connectivity
from csm.config.settings import Settings

pytestmark = pytest.mark.infra_db


def _env_settings() -> Settings | None:
    """Build a Settings instance from live env vars, or return None if unconfigured."""
    dsn = os.environ.get("CSM_DB_CSM_SET_DSN")
    mongo_uri = os.environ.get("CSM_MONGO_URI")
    if not dsn or not mongo_uri:
        return None
    return Settings(
        db_csm_set_dsn=dsn,
        mongo_uri=mongo_uri,
        db_write_enabled=True,
    )


@pytest.mark.asyncio
async def test_check_db_connectivity_returns_ok_against_live_stack() -> None:
    """check_db_connectivity reports ok for both postgres and mongo against the real stack."""
    s = _env_settings()
    if s is None:
        pytest.skip("CSM_DB_CSM_SET_DSN and CSM_MONGO_URI must be set for infra_db tests")

    result = await check_db_connectivity(s)

    assert result is not None
    assert result["postgres"] == "ok", f"PostgreSQL not ok: {result['postgres']}"
    assert result["mongo"] == "ok", f"MongoDB not ok: {result['mongo']}"
