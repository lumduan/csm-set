"""Unit tests for Phase 5.2 — API response schemas.

One round-trip test per schema: construct -> model_dump -> re-parse -> assert equal.
"""

from __future__ import annotations

from api.schemas.backtest import BacktestRunResponse
from api.schemas.data import RefreshResult
from api.schemas.errors import ProblemDetail
from api.schemas.health import HealthStatus
from api.schemas.jobs import JobKind, JobRecord, JobStatus
from api.schemas.notebooks import NotebookEntry, NotebookIndex
from api.schemas.portfolio import Holding, PortfolioSnapshot
from api.schemas.signals import SignalRanking, SignalRow
from api.schemas.universe import UniverseItem, UniverseSnapshot

# ---------------------------------------------------------------------------
# Universe schemas
# ---------------------------------------------------------------------------


class TestUniverseItem:
    def test_round_trip(self) -> None:
        original = UniverseItem(symbol="SET001")
        dumped = original.model_dump()
        restored = UniverseItem(**dumped)
        assert restored == original
        assert restored.symbol == "SET001"

    def test_extra_fields_preserved(self) -> None:
        original = UniverseItem(  # type: ignore[call-arg]
            symbol="SET001",
            asof="2026-04-21",
            sector="BANK",
        )
        dumped = original.model_dump()
        assert dumped["asof"] == "2026-04-21"
        assert dumped["sector"] == "BANK"
        restored = UniverseItem(**dumped)
        assert restored.model_dump()["asof"] == "2026-04-21"


class TestUniverseSnapshot:
    def test_round_trip(self) -> None:
        items = [UniverseItem(symbol="SET001"), UniverseItem(symbol="SET002")]
        original = UniverseSnapshot(items=items, count=2)
        dumped = original.model_dump()
        restored = UniverseSnapshot(**dumped)
        assert restored.count == 2
        assert len(restored.items) == 2
        assert restored.items[0].symbol == "SET001"

    def test_empty(self) -> None:
        original = UniverseSnapshot(items=[], count=0)
        assert original.model_dump()["count"] == 0
        assert original.model_dump()["items"] == []


# ---------------------------------------------------------------------------
# Signal schemas
# ---------------------------------------------------------------------------


class TestSignalRow:
    def test_round_trip(self) -> None:
        original = SignalRow(  # type: ignore[call-arg]
            symbol="SET001",
            mom_12_1=0.15,
            mom_12_1_rank=0.95,
            mom_12_1_quintile=5,
        )
        dumped = original.model_dump()
        restored = SignalRow(**dumped)
        assert restored.symbol == "SET001"
        assert restored.model_dump()["mom_12_1"] == 0.15

    def test_extra_fields_survive_dump_reparse(self) -> None:
        original = SignalRow(symbol="SET002", sharpe_momentum=0.08)  # type: ignore[call-arg]
        dumped = original.model_dump()
        restored = SignalRow(**dumped)
        assert restored.model_dump()["sharpe_momentum"] == 0.08


class TestSignalRanking:
    def test_round_trip(self) -> None:
        rankings = [SignalRow(symbol="SET001", score=0.95)]  # type: ignore[call-arg]
        original = SignalRanking(as_of="2026-04-21", rankings=rankings)
        dumped = original.model_dump()
        restored = SignalRanking(**dumped)
        assert restored.as_of == "2026-04-21"
        assert len(restored.rankings) == 1

    def test_empty_rankings(self) -> None:
        original = SignalRanking(as_of="2026-04-21", rankings=[])
        assert original.model_dump()["rankings"] == []


# ---------------------------------------------------------------------------
# Portfolio schemas
# ---------------------------------------------------------------------------


class TestHolding:
    def test_round_trip(self) -> None:
        original = Holding(symbol="SET001", weight=0.05, sector="BANK")
        dumped = original.model_dump()
        restored = Holding(**dumped)
        assert restored.symbol == "SET001"
        assert restored.weight == 0.05
        assert restored.sector == "BANK"

    def test_default_sector_is_none(self) -> None:
        original = Holding(symbol="SET001", weight=0.05)
        assert original.sector is None

    def test_weight_constraint_enforced(self) -> None:
        Holding(symbol="SET001", weight=0.0)
        Holding(symbol="SET001", weight=1.0)


class TestPortfolioSnapshot:
    def test_round_trip(self) -> None:
        holdings = [Holding(symbol="SET001", weight=0.05)]
        original = PortfolioSnapshot(
            as_of="2026-04-21T00:00:00+07:00",
            holdings=holdings,
            summary_metrics={"cagr": 0.15, "sharpe": 1.2},
        )
        dumped = original.model_dump()
        restored = PortfolioSnapshot(**dumped)
        assert restored.as_of == "2026-04-21T00:00:00+07:00"
        assert restored.summary_metrics["cagr"] == 0.15

    def test_empty_holdings(self) -> None:
        original = PortfolioSnapshot(
            as_of="2026-04-21T00:00:00Z",
            holdings=[],
        )
        assert original.holdings == []
        assert original.summary_metrics == {}

    def test_extra_fields_preserved(self) -> None:
        original = PortfolioSnapshot(  # type: ignore[call-arg]
            as_of="2026-04-21T00:00:00Z",
            holdings=[],
            max_drawdown=-0.15,
        )
        dumped = original.model_dump()
        assert dumped["max_drawdown"] == -0.15


# ---------------------------------------------------------------------------
# Backtest schemas
# ---------------------------------------------------------------------------


class TestBacktestRunResponse:
    def test_round_trip(self) -> None:
        original = BacktestRunResponse(job_id="abc123def456", status="accepted")
        dumped = original.model_dump()
        restored = BacktestRunResponse(**dumped)
        assert restored.job_id == "abc123def456"
        assert restored.status == "accepted"


# ---------------------------------------------------------------------------
# Data schemas
# ---------------------------------------------------------------------------


class TestRefreshResult:
    def test_round_trip(self) -> None:
        original = RefreshResult(refreshed=50, requested=50)
        dumped = original.model_dump()
        restored = RefreshResult(**dumped)
        assert restored.refreshed == 50
        assert restored.requested == 50

    def test_zero_counts(self) -> None:
        original = RefreshResult(refreshed=0, requested=0)
        assert original.refreshed == 0
        assert original.requested == 0


# ---------------------------------------------------------------------------
# Health schemas
# ---------------------------------------------------------------------------


class TestHealthStatus:
    def test_round_trip(self) -> None:
        original = HealthStatus(status="ok", version="0.1.0", public_mode=False)
        dumped = original.model_dump()
        restored = HealthStatus(**dumped)
        assert restored.status == "ok"
        assert restored.version == "0.1.0"
        assert restored.public_mode is False

    def test_public_mode_flag(self) -> None:
        public = HealthStatus(status="ok", version="0.1.0", public_mode=True)
        assert public.public_mode is True


# ---------------------------------------------------------------------------
# Error schemas
# ---------------------------------------------------------------------------


class TestProblemDetail:
    def test_round_trip(self) -> None:
        original = ProblemDetail(detail="Not found", request_id="01HXYEXAMPLE9K")
        dumped = original.model_dump()
        restored = ProblemDetail(**dumped)
        assert restored.detail == "Not found"
        assert restored.request_id == "01HXYEXAMPLE9K"


# ---------------------------------------------------------------------------
# Job schemas (re-exports from api.jobs)
# ---------------------------------------------------------------------------


class TestJobSchemas:
    def test_job_status_enum_values(self) -> None:
        assert JobStatus.ACCEPTED.value == "accepted"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.SUCCEEDED.value == "succeeded"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"

    def test_job_kind_enum_values(self) -> None:
        assert JobKind.DATA_REFRESH.value == "data_refresh"
        assert JobKind.BACKTEST_RUN.value == "backtest_run"

    def test_job_record_round_trip(self) -> None:
        from datetime import UTC, datetime

        original = JobRecord(
            job_id="test-id",
            kind=JobKind.BACKTEST_RUN,
            status=JobStatus.ACCEPTED,
            accepted_at=datetime(2026, 4, 21, tzinfo=UTC),
        )
        dumped = original.model_dump(mode="json")
        restored = JobRecord(**dumped)
        assert restored.job_id == "test-id"
        assert restored.kind == JobKind.BACKTEST_RUN
        assert restored.status == JobStatus.ACCEPTED


# ---------------------------------------------------------------------------
# Notebook schemas
# ---------------------------------------------------------------------------


class TestNotebookEntry:
    def test_round_trip(self) -> None:
        original = NotebookEntry(
            name="05_api_validation.html",
            path="/static/notebooks/05_api_validation.html",
            size_bytes=1024,
            last_modified="2026-04-30T12:00:00Z",
        )
        dumped = original.model_dump()
        restored = NotebookEntry(**dumped)
        assert restored.name == "05_api_validation.html"
        assert restored.size_bytes == 1024


class TestNotebookIndex:
    def test_round_trip(self) -> None:
        entry = NotebookEntry(
            name="test.html",
            path="/static/notebooks/test.html",
            size_bytes=512,
            last_modified="2026-04-30T12:00:00Z",
        )
        original = NotebookIndex(items=[entry])
        dumped = original.model_dump()
        restored = NotebookIndex(**dumped)
        assert len(restored.items) == 1

    def test_empty(self) -> None:
        original = NotebookIndex(items=[])
        assert original.model_dump()["items"] == []
