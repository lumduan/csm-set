"""Integration tests for ``MongoAdapter`` against the real ``csm_logs``.

Requires ``quant-mongo`` running on ``quant-network`` with the
``backtest_results``, ``signal_snapshots``, and ``model_params`` collections
live (and the implied unique indexes on natural keys). Skipped by default —
run with ``pytest -m infra_db``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from csm.adapters.models import (
    BacktestResultDoc,
    BacktestSummaryRow,
    ModelParamsDoc,
    SignalSnapshotDoc,
)
from csm.adapters.mongo import MongoAdapter

pytestmark = pytest.mark.infra_db

TEST_STRATEGY_ID: str = "test-csm-set"
TEST_RUN_ID_PREFIX: str = "test-csm-set-"


def _result_doc(run_id: str, sharpe: float = 1.5) -> dict[str, object]:
    return {
        "run_id": run_id,
        "strategy_id": TEST_STRATEGY_ID,
        "created_at": datetime(2024, 1, 2, tzinfo=UTC),
        "config": {"top_n": 5, "rebalance": "monthly"},
        "metrics": {"sharpe": sharpe, "max_dd": -0.18},
        "equity_curve": {"2024-01-02": 100.0, "2024-01-03": 101.5},
        "trades": [{"symbol": "PTT", "side": "buy", "quantity": 100}],
    }


async def test_write_backtest_result_idempotent(mongo_adapter: MongoAdapter) -> None:
    run_id = f"{TEST_RUN_ID_PREFIX}001"

    await mongo_adapter.write_backtest_result(_result_doc(run_id, sharpe=1.5))
    await mongo_adapter.write_backtest_result(_result_doc(run_id, sharpe=2.0))

    db = mongo_adapter._db()  # noqa: SLF001
    count = await db["backtest_results"].count_documents({"run_id": run_id})
    assert count == 1
    fetched = await db["backtest_results"].find_one({"run_id": run_id}, {"_id": 0})
    assert fetched is not None
    # replace_one semantics: latest write wins.
    assert fetched["metrics"]["sharpe"] == 2.0


async def test_write_signal_snapshot_idempotent(mongo_adapter: MongoAdapter) -> None:
    date = datetime(2024, 1, 5, tzinfo=UTC)
    rankings_v1: list[dict[str, object]] = [
        {"symbol": "PTT", "rank": 0.95, "quintile": 5},
        {"symbol": "BBL", "rank": 0.10, "quintile": 1},
    ]
    rankings_v2: list[dict[str, object]] = [
        {"symbol": "PTT", "rank": 0.80, "quintile": 4},
        {"symbol": "BBL", "rank": 0.15, "quintile": 1},
    ]

    await mongo_adapter.write_signal_snapshot(TEST_STRATEGY_ID, date, rankings_v1)
    await mongo_adapter.write_signal_snapshot(TEST_STRATEGY_ID, date, rankings_v2)

    db = mongo_adapter._db()  # noqa: SLF001
    count = await db["signal_snapshots"].count_documents(
        {"strategy_id": TEST_STRATEGY_ID, "date": date}
    )
    assert count == 1
    fetched = await db["signal_snapshots"].find_one(
        {"strategy_id": TEST_STRATEGY_ID, "date": date}, {"_id": 0}
    )
    assert fetched is not None
    assert fetched["rankings"][0]["rank"] == 0.80


async def test_write_model_params_idempotent(mongo_adapter: MongoAdapter) -> None:
    version = "test-v1"
    params_v1: dict[str, object] = {"formation_months": 12, "top_quantile": 0.2}
    params_v2: dict[str, object] = {"formation_months": 12, "top_quantile": 0.25}

    await mongo_adapter.write_model_params(TEST_STRATEGY_ID, version, params_v1)
    await mongo_adapter.write_model_params(TEST_STRATEGY_ID, version, params_v2)

    db = mongo_adapter._db()  # noqa: SLF001
    count = await db["model_params"].count_documents(
        {"strategy_id": TEST_STRATEGY_ID, "version": version}
    )
    assert count == 1
    fetched = await db["model_params"].find_one(
        {"strategy_id": TEST_STRATEGY_ID, "version": version}, {"_id": 0}
    )
    assert fetched is not None
    assert fetched["params"]["top_quantile"] == 0.25
    # created_at survived the second write (set on insert only).
    created_at = fetched["created_at"]
    assert isinstance(created_at, datetime)
    assert created_at.tzinfo is not None


async def test_read_backtest_result_round_trip(mongo_adapter: MongoAdapter) -> None:
    run_id = f"{TEST_RUN_ID_PREFIX}002"
    await mongo_adapter.write_backtest_result(_result_doc(run_id, sharpe=1.42))

    result = await mongo_adapter.read_backtest_result(run_id)

    assert isinstance(result, BacktestResultDoc)
    assert result.run_id == run_id
    assert result.strategy_id == TEST_STRATEGY_ID
    assert result.metrics["sharpe"] == 1.42
    assert result.created_at.tzinfo is not None


async def test_read_backtest_result_missing_returns_none(
    mongo_adapter: MongoAdapter,
) -> None:
    assert await mongo_adapter.read_backtest_result(f"{TEST_RUN_ID_PREFIX}nope") is None


async def test_read_signal_snapshot_round_trip(mongo_adapter: MongoAdapter) -> None:
    base = datetime(2024, 1, 5, tzinfo=UTC)
    rankings_a: list[dict[str, object]] = [{"symbol": "PTT", "rank": 0.9}]
    rankings_b: list[dict[str, object]] = [{"symbol": "BBL", "rank": 0.7}]
    await mongo_adapter.write_signal_snapshot(TEST_STRATEGY_ID, base, rankings_a)
    await mongo_adapter.write_signal_snapshot(
        TEST_STRATEGY_ID, base + timedelta(days=1), rankings_b
    )

    snap_a = await mongo_adapter.read_signal_snapshot(TEST_STRATEGY_ID, base)
    snap_b = await mongo_adapter.read_signal_snapshot(TEST_STRATEGY_ID, base + timedelta(days=1))

    assert isinstance(snap_a, SignalSnapshotDoc)
    assert snap_a.rankings[0]["symbol"] == "PTT"
    assert isinstance(snap_b, SignalSnapshotDoc)
    assert snap_b.rankings[0]["symbol"] == "BBL"
    assert snap_a.date.tzinfo is not None


async def test_read_model_params_round_trip(mongo_adapter: MongoAdapter) -> None:
    await mongo_adapter.write_model_params(TEST_STRATEGY_ID, "test-vA", {"formation_months": 12})
    await mongo_adapter.write_model_params(TEST_STRATEGY_ID, "test-vB", {"formation_months": 6})

    a = await mongo_adapter.read_model_params(TEST_STRATEGY_ID, "test-vA")
    b = await mongo_adapter.read_model_params(TEST_STRATEGY_ID, "test-vB")

    assert isinstance(a, ModelParamsDoc)
    assert a.params["formation_months"] == 12
    assert isinstance(b, ModelParamsDoc)
    assert b.params["formation_months"] == 6


async def test_list_backtest_results_descending_with_limit(
    mongo_adapter: MongoAdapter,
) -> None:
    base = datetime(2024, 1, 2, tzinfo=UTC)
    for i in range(5):
        doc = _result_doc(f"{TEST_RUN_ID_PREFIX}list-{i:02d}", sharpe=1.0 + i * 0.1)
        doc["created_at"] = base + timedelta(days=i)
        await mongo_adapter.write_backtest_result(doc)

    rows = await mongo_adapter.list_backtest_results(TEST_STRATEGY_ID, limit=3)

    assert len(rows) == 3
    assert all(isinstance(r, BacktestSummaryRow) for r in rows)
    times = [r.created_at for r in rows]
    assert times == sorted(times, reverse=True)
    # Slim projection — must not carry equity_curve / trades fields.
    raw = rows[0].model_dump()
    assert "equity_curve" not in raw
    assert "trades" not in raw
