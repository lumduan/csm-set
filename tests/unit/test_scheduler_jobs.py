"""Unit tests for Phase 5.5 — Scheduler production wiring.

Validates cron parametrization, misfire policies, public-mode skip,
runner contract, marker file writing, and failure-safe wrapper behaviour.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from api.scheduler.jobs import create_scheduler, daily_refresh
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from csm.config.settings import Settings
from csm.data.store import ParquetStore


@pytest.fixture
def mock_store() -> MagicMock:
    """Return a MagicMock spec'd to ParquetStore."""
    store = MagicMock(spec=ParquetStore)
    store.load.return_value = pd.DataFrame({"symbol": ["A", "B"]})
    return store


class TestCreateSchedulerConfig:
    """validate scheduler creation, job registration, and trigger config."""

    def test_returns_none_in_public_mode(
        self, public_settings: Settings, mock_store: MagicMock
    ) -> None:
        assert create_scheduler(public_settings, mock_store) is None

    def test_returns_scheduler_in_private_mode(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_job_registered_with_id_daily_refresh(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        job = scheduler.get_job("daily_refresh")
        assert job is not None
        assert job.id == "daily_refresh"

    def test_trigger_is_crontrigger(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        job = scheduler.get_job("daily_refresh")
        assert isinstance(job.trigger, CronTrigger)

    def test_cron_fields_match_settings(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        trigger = scheduler.get_job("daily_refresh").trigger
        assert isinstance(trigger, CronTrigger)
        field_map = {f.name: str(f) for f in trigger.fields}
        assert field_map["minute"] == "0"
        assert field_map["hour"] == "18"
        assert field_map["day_of_week"] == "1-5"

    def test_misfire_policies(self, settings_override: Settings, mock_store: MagicMock) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        job = scheduler.get_job("daily_refresh")
        assert job.misfire_grace_time == 3600
        assert job.coalesce is True
        assert job.max_instances == 1


class TestDailyRefreshRunner:
    """validate the refactored runner contract and marker file behaviour."""

    @pytest.fixture
    def fetched_data(self) -> dict[str, pd.DataFrame]:
        dates = pd.date_range("2024-01-01", periods=5, freq="B", tz="Asia/Bangkok")
        return {
            "A": pd.DataFrame(
                {
                    "open": [100.0] * 5,
                    "high": [101.0] * 5,
                    "low": [99.0] * 5,
                    "close": [100.5] * 5,
                    "volume": [1_000_000.0] * 5,
                },
                index=dates,
            ),
            "B": pd.DataFrame(
                {
                    "open": [200.0] * 5,
                    "high": [202.0] * 5,
                    "low": [198.0] * 5,
                    "close": [201.0] * 5,
                    "volume": [500_000.0] * 5,
                },
                index=dates,
            ),
        }

    async def test_returns_dict(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
        fetched_data: dict[str, pd.DataFrame],
    ) -> None:
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(return_value=fetched_data)

            result = await daily_refresh(settings=settings_override, store=mock_store)

        assert isinstance(result, dict)
        assert result["symbols_fetched"] == 2
        assert result["failures"] == 0
        assert isinstance(result["duration_seconds"], float)
        assert result["duration_seconds"] > 0

    async def test_writes_marker_file(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
        fetched_data: dict[str, pd.DataFrame],
    ) -> None:
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(return_value=fetched_data)

            await daily_refresh(settings=settings_override, store=mock_store)

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        assert marker_path.is_file()
        marker = json.loads(marker_path.read_text())
        assert "timestamp" in marker
        assert marker["symbols_fetched"] == 2
        assert marker["failures"] == 0
        assert isinstance(marker["duration_seconds"], float)

    async def test_marker_timestamp_is_iso_utc(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
        fetched_data: dict[str, pd.DataFrame],
    ) -> None:
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(return_value=fetched_data)

            await daily_refresh(settings=settings_override, store=mock_store)

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        marker = json.loads(marker_path.read_text())
        ts: str = marker["timestamp"]
        assert ts.endswith("+00:00") or ts.endswith("Z")

    async def test_tracks_failures(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
        fetched_data: dict[str, pd.DataFrame],
    ) -> None:
        """Failures count = requested symbols - successfully fetched."""
        partial = {"A": fetched_data["A"]}
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(return_value=partial)

            result = await daily_refresh(settings=settings_override, store=mock_store)

        assert result["symbols_fetched"] == 1
        assert result["failures"] == 1

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        marker = json.loads(marker_path.read_text())
        assert marker["symbols_fetched"] == 1
        assert marker["failures"] == 1


class TestSchedulerWrapper:
    """validate the APScheduler _job_wrapper does not crash on failure."""

    async def test_wrapper_catches_exception(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        job = scheduler.get_job("daily_refresh")
        wrapper = job.func

        with patch("api.scheduler.jobs.daily_refresh", side_effect=RuntimeError("boom")):
            # The wrapper must not propagate the exception.
            await wrapper()
