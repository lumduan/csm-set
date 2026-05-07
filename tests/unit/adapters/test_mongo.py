"""Unit tests for ``MongoAdapter`` with a mocked motor client."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from csm.adapters.models import (
    BacktestResultDoc,
    BacktestSummaryRow,
    ModelParamsDoc,
    SignalSnapshotDoc,
)
from csm.adapters.mongo import MongoAdapter

URI: str = "mongodb://test:test@localhost:27017/"


def _make_collection() -> MagicMock:
    """Build a ``MagicMock`` shaped like an ``AsyncIOMotorCollection``."""
    coll = MagicMock()
    coll.replace_one = AsyncMock()
    coll.update_one = AsyncMock()
    coll.find_one = AsyncMock(return_value=None)
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])
    coll.find = MagicMock(return_value=cursor)
    coll._cursor = cursor  # exposed for assertions
    return coll


def _make_client(coll: MagicMock | None = None) -> MagicMock:
    """Build a ``MagicMock`` shaped like ``AsyncIOMotorClient``.

    ``client.admin.command(...)`` is an ``AsyncMock`` returning ``{"ok": 1.0}``.
    ``client.close()`` is a sync ``MagicMock``. ``client[db][coll]`` returns
    the supplied (or freshly built) collection mock so adapter methods always
    operate on a single, inspectable collection.
    """
    if coll is None:
        coll = _make_collection()
    client = MagicMock()
    client.admin.command = AsyncMock(return_value={"ok": 1.0})
    client.close = MagicMock()
    db = MagicMock()
    db.__getitem__.return_value = coll
    client.__getitem__.return_value = db
    client._db = db  # exposed for assertions
    client._coll = coll
    return client


class TestLifecycle:
    async def test_connect_constructs_client_with_expected_kwargs(self) -> None:
        client = _make_client()
        cls_mock = MagicMock(return_value=client)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=cls_mock):
            adapter = MongoAdapter(URI)
            await adapter.connect()

        cls_mock.assert_called_once()
        args = cls_mock.call_args.args
        kwargs = cls_mock.call_args.kwargs
        assert args[0] == URI
        assert kwargs["tz_aware"] is True
        assert kwargs["serverSelectionTimeoutMS"] == 5000
        client.admin.command.assert_awaited_once_with("ping")

    async def test_connect_is_idempotent(self) -> None:
        client = _make_client()
        cls_mock = MagicMock(return_value=client)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=cls_mock):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            await adapter.connect()

        cls_mock.assert_called_once()
        client.admin.command.assert_awaited_once()

    async def test_connect_propagates_ping_failure_and_closes_client(self) -> None:
        client = _make_client()
        client.admin.command = AsyncMock(side_effect=OSError("unreachable"))
        cls_mock = MagicMock(return_value=client)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=cls_mock):
            adapter = MongoAdapter(URI)
            with pytest.raises(OSError, match="unreachable"):
                await adapter.connect()

        client.close.assert_called_once()

    async def test_close_calls_client_close(self) -> None:
        client = _make_client()
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            await adapter.close()

        client.close.assert_called_once()

    async def test_close_without_connect_is_noop(self) -> None:
        adapter = MongoAdapter(URI)
        # Must not raise.
        await adapter.close()

    async def test_close_is_idempotent(self) -> None:
        client = _make_client()
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            await adapter.close()
            await adapter.close()

        client.close.assert_called_once()

    async def test_aenter_aexit(self) -> None:
        client = _make_client()
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            async with MongoAdapter(URI) as adapter:
                assert isinstance(adapter, MongoAdapter)

        client.close.assert_called_once()

    async def test_uri_and_db_name_properties(self) -> None:
        adapter = MongoAdapter(URI)
        assert adapter.uri == URI
        assert adapter.db_name == "csm_logs"

        adapter_custom = MongoAdapter(URI, db_name="alt")
        assert adapter_custom.db_name == "alt"


class TestPing:
    async def test_ping_returns_true_when_ok_one(self) -> None:
        client = _make_client()
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            client.admin.command.reset_mock()
            assert await adapter.ping() is True

        client.admin.command.assert_awaited_once_with("ping")

    async def test_ping_returns_false_when_unexpected_value(self) -> None:
        client = _make_client()
        client.admin.command = AsyncMock(return_value={"ok": 0.0})
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            # connect runs an initial ping that returns the same mock value;
            # we want ok=1.0 on connect but ok=0.0 for the explicit ping call.
            # Stage two return values via side_effect.
            client.admin.command = AsyncMock(side_effect=[{"ok": 1.0}, {"ok": 0.0}])
            await adapter.connect()
            assert await adapter.ping() is False

    async def test_ping_raises_when_not_connected(self) -> None:
        adapter = MongoAdapter(URI)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.ping()


class TestWriteBacktestResult:
    async def test_replace_one_called_with_run_id_filter(self) -> None:
        coll = _make_collection()
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            doc: dict[str, object] = {
                "run_id": "run-001",
                "strategy_id": "csm-set",
                "created_at": datetime(2024, 1, 2, tzinfo=UTC),
                "config": {"top_n": 5},
                "metrics": {"sharpe": 1.42},
                "equity_curve": {"2024-01-02": 100.0},
                "trades": [{"symbol": "PTT", "side": "buy"}],
            }
            await adapter.write_backtest_result(doc)

        coll.replace_one.assert_awaited_once_with({"run_id": "run-001"}, doc, upsert=True)
        client.__getitem__.assert_any_call("csm_logs")
        client._db.__getitem__.assert_any_call("backtest_results")

    async def test_missing_run_id_raises_keyerror(self) -> None:
        coll = _make_collection()
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            with pytest.raises(KeyError, match="run_id"):
                await adapter.write_backtest_result({"strategy_id": "csm-set"})

        coll.replace_one.assert_not_awaited()


class TestWriteSignalSnapshot:
    async def test_update_one_called_with_compound_filter(self) -> None:
        coll = _make_collection()
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            date = datetime(2024, 1, 5, tzinfo=UTC)
            rankings: list[dict[str, object]] = [
                {"symbol": "PTT", "rank": 0.95, "quintile": 5},
                {"symbol": "BBL", "rank": 0.10, "quintile": 1},
            ]
            await adapter.write_signal_snapshot("csm-set", date, rankings)

        coll.update_one.assert_awaited_once()
        filter_arg, update_arg = coll.update_one.await_args.args
        assert filter_arg == {"strategy_id": "csm-set", "date": date}
        assert "$set" in update_arg
        assert update_arg["$set"]["strategy_id"] == "csm-set"
        assert update_arg["$set"]["date"] == date
        assert update_arg["$set"]["rankings"] == rankings
        assert coll.update_one.await_args.kwargs["upsert"] is True
        client._db.__getitem__.assert_any_call("signal_snapshots")


class TestWriteModelParams:
    async def test_update_one_called_with_compound_filter(self) -> None:
        coll = _make_collection()
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            params: dict[str, object] = {"formation_months": 12, "top_quantile": 0.2}
            await adapter.write_model_params("csm-set", "v0.7.1", params)

        coll.update_one.assert_awaited_once()
        filter_arg, update_arg = coll.update_one.await_args.args
        assert filter_arg == {"strategy_id": "csm-set", "version": "v0.7.1"}
        assert update_arg["$set"]["params"] == params
        assert "$setOnInsert" in update_arg
        created_at = update_arg["$setOnInsert"]["created_at"]
        assert isinstance(created_at, datetime)
        assert created_at.tzinfo is not None
        assert coll.update_one.await_args.kwargs["upsert"] is True
        client._db.__getitem__.assert_any_call("model_params")


class TestReads:
    async def test_read_backtest_result_returns_model(self) -> None:
        coll = _make_collection()
        record: dict[str, Any] = {
            "run_id": "run-001",
            "strategy_id": "csm-set",
            "created_at": datetime(2024, 1, 2, tzinfo=UTC),
            "config": {"top_n": 5},
            "metrics": {"sharpe": 1.42},
            "equity_curve": {"2024-01-02": 100.0},
            "trades": [],
        }
        coll.find_one = AsyncMock(return_value=record)
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            result = await adapter.read_backtest_result("run-001")

        assert isinstance(result, BacktestResultDoc)
        assert result.run_id == "run-001"
        # _id projection used
        filter_arg, projection_arg = coll.find_one.await_args.args
        assert filter_arg == {"run_id": "run-001"}
        assert projection_arg == {"_id": 0}

    async def test_read_backtest_result_returns_none_when_missing(self) -> None:
        coll = _make_collection()
        coll.find_one = AsyncMock(return_value=None)
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            assert await adapter.read_backtest_result("nope") is None

    async def test_read_signal_snapshot_returns_model(self) -> None:
        coll = _make_collection()
        date = datetime(2024, 1, 5, tzinfo=UTC)
        record: dict[str, Any] = {
            "strategy_id": "csm-set",
            "date": date,
            "rankings": [{"symbol": "PTT", "rank": 0.95}],
        }
        coll.find_one = AsyncMock(return_value=record)
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            result = await adapter.read_signal_snapshot("csm-set", date)

        assert isinstance(result, SignalSnapshotDoc)
        assert result.strategy_id == "csm-set"
        filter_arg, _ = coll.find_one.await_args.args
        assert filter_arg == {"strategy_id": "csm-set", "date": date}

    async def test_read_signal_snapshot_returns_none(self) -> None:
        coll = _make_collection()
        coll.find_one = AsyncMock(return_value=None)
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            assert await adapter.read_signal_snapshot("csm-set", datetime.now(tz=UTC)) is None

    async def test_read_model_params_returns_model(self) -> None:
        coll = _make_collection()
        record: dict[str, Any] = {
            "strategy_id": "csm-set",
            "version": "v0.7.1",
            "params": {"top_quantile": 0.2},
            "created_at": datetime(2024, 1, 2, tzinfo=UTC),
        }
        coll.find_one = AsyncMock(return_value=record)
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            result = await adapter.read_model_params("csm-set", "v0.7.1")

        assert isinstance(result, ModelParamsDoc)
        assert result.version == "v0.7.1"
        filter_arg, _ = coll.find_one.await_args.args
        assert filter_arg == {"strategy_id": "csm-set", "version": "v0.7.1"}

    async def test_read_model_params_returns_none(self) -> None:
        coll = _make_collection()
        coll.find_one = AsyncMock(return_value=None)
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            assert await adapter.read_model_params("csm-set", "x") is None

    async def test_list_backtest_results_descending_with_filter_and_limit(self) -> None:
        coll = _make_collection()
        records: list[dict[str, Any]] = [
            {
                "run_id": f"run-00{i}",
                "strategy_id": "csm-set",
                "created_at": datetime(2024, 1, 2 + i, tzinfo=UTC),
                "metrics": {"sharpe": 1.0 + i * 0.1},
            }
            for i in range(3)
        ]
        coll._cursor.to_list = AsyncMock(return_value=records)
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            result = await adapter.list_backtest_results("csm-set", limit=10)

        assert len(result) == 3
        assert all(isinstance(r, BacktestSummaryRow) for r in result)
        # Filter + projection assertions
        filter_arg, projection_arg = coll.find.call_args.args
        assert filter_arg == {"strategy_id": "csm-set"}
        assert projection_arg["_id"] == 0
        assert projection_arg["run_id"] == 1
        assert "equity_curve" not in projection_arg
        assert "trades" not in projection_arg
        # Ordering
        coll._cursor.sort.assert_called_once_with("created_at", -1)
        coll._cursor.limit.assert_called_once_with(10)

    async def test_list_backtest_results_no_filter(self) -> None:
        coll = _make_collection()
        coll._cursor.to_list = AsyncMock(return_value=[])
        client = _make_client(coll=coll)
        with patch("csm.adapters.mongo.AsyncIOMotorClient", new=MagicMock(return_value=client)):
            adapter = MongoAdapter(URI)
            await adapter.connect()
            result = await adapter.list_backtest_results()

        assert result == []
        filter_arg, _ = coll.find.call_args.args
        assert filter_arg == {}


class TestRequiresClient:
    async def test_ping_raises_when_not_connected(self) -> None:
        adapter = MongoAdapter(URI)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.ping()

    async def test_write_backtest_result_raises_when_not_connected(self) -> None:
        adapter = MongoAdapter(URI)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.write_backtest_result({"run_id": "r1"})

    async def test_write_signal_snapshot_raises_when_not_connected(self) -> None:
        adapter = MongoAdapter(URI)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.write_signal_snapshot("csm-set", datetime.now(tz=UTC), [])

    async def test_write_model_params_raises_when_not_connected(self) -> None:
        adapter = MongoAdapter(URI)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.write_model_params("csm-set", "v0", {})

    async def test_read_backtest_result_raises_when_not_connected(self) -> None:
        adapter = MongoAdapter(URI)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.read_backtest_result("r1")

    async def test_list_backtest_results_raises_when_not_connected(self) -> None:
        adapter = MongoAdapter(URI)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.list_backtest_results()
