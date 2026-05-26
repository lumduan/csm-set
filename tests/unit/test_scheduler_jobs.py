"""Unit tests for Phase 5.5 — Scheduler production wiring.

Validates cron parametrization, misfire policies, public-mode skip,
runner contract, marker file writing, and failure-safe wrapper behaviour.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from api.scheduler.jobs import create_scheduler, daily_refresh
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from csm.config.settings import Settings
from csm.data.store import ParquetStore
from csm.live.portfolio import LivePortfolioConfig, LivePosition


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
        # APScheduler's numeric day_of_week uses 0=Mon..6=Sun, which would
        # silently shift the standard-crontab "1-5" by one day. The scheduler
        # translates the day_of_week field to day-name form (``mon-fri``) so
        # the resulting trigger fires on the calendar weekdays the operator
        # specified (Mon-Fri).
        assert field_map["day_of_week"] == "mon-fri"

    def test_misfire_policies(self, settings_override: Settings, mock_store: MagicMock) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        job = scheduler.get_job("daily_refresh")
        assert job.misfire_grace_time == 3600
        assert job.coalesce is True
        assert job.max_instances == 1


class TestDailyRefreshRunner:
    """validate the refactored runner contract and marker file behaviour."""

    @pytest.fixture(autouse=True)
    def _isolate_from_resilience_features(self) -> Generator[None, None, None]:
        """Skip Phase 1 (held symbols) and short-circuit retry sleeps.

        These legacy tests pre-date the held-priority / outer-retry features
        and use ``mock_store`` symbols ("A", "B") that intentionally diverge
        from the real ``configs/live_portfolio.yaml``. Patching
        ``load_live_portfolio`` keeps them focused on the universe path, and
        patching ``_sleep`` keeps retry-bearing tests like
        ``test_tracks_failures`` from waiting on real backoff windows."""
        with (
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            yield

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


def _ohlcv_frame(close_price: float = 100.0) -> pd.DataFrame:
    """Build a minimal OHLCV frame for fetch_batch mocks."""
    dates = pd.date_range("2024-01-01", periods=5, freq="B", tz="Asia/Bangkok")
    return pd.DataFrame(
        {
            "open": [close_price] * 5,
            "high": [close_price * 1.01] * 5,
            "low": [close_price * 0.99] * 5,
            "close": [close_price] * 5,
            "volume": [1_000_000.0] * 5,
        },
        index=dates,
    )


def _held_config(*symbols: str) -> LivePortfolioConfig:
    """Build a LivePortfolioConfig with the given bare symbols as positions."""
    return LivePortfolioConfig(
        strategy_id="test",
        entry_date=date(2026, 5, 5),
        starting_nav=1_000_000.0,
        cash=0.0,
        positions=tuple(LivePosition(symbol=s, shares=100.0, avg_cost=100.0) for s in symbols),
    )


class TestDailyRefreshResilience:
    """A+C: outer-loop retry on failed symbols + held-symbols-first priority."""

    async def test_daily_refresh_retries_failed_symbols(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
    ) -> None:
        """Attempt 1 fails one symbol; retry recovers it. ``retry_attempts_used == 1``."""
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()) as mock_sleep,
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(
                side_effect=[
                    {"A": _ohlcv_frame(100.0)},  # universe attempt 1: B missing
                    {"B": _ohlcv_frame(200.0)},  # universe retry of just ["B"]
                ]
            )

            result = await daily_refresh(settings=settings_override, store=mock_store)

        assert result["symbols_fetched"] == 2
        assert result["failures"] == 0
        assert result["retry_attempts_used"] == 1
        # Retry call must request only the failed subset.
        second_call = mock_loader.fetch_batch.call_args_list[1]
        assert second_call.kwargs["symbols"] == ["B"]
        # The sleep happened once (before the retry).
        mock_sleep.assert_awaited_once()

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        marker = json.loads(marker_path.read_text())
        assert marker["retry_attempts_used"] == 1
        assert marker["failures"] == 0

    async def test_daily_refresh_fetches_held_symbols_first(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
    ) -> None:
        """Held batch must run before universe; universe call must exclude held names.

        Mirrors production: ``universe_latest.parquet`` stores SET-prefixed
        symbols and held positions resolve to the same prefixed form via
        ``LivePosition.qualified_symbol``.
        """
        # Universe stores prefixed names (production reality).
        mock_store.load.return_value = pd.DataFrame({"symbol": ["SET:A", "SET:B"]})
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch(
                "api.scheduler.jobs.load_live_portfolio",
                # Bare names in YAML are common; qualified_symbol prefixes them.
                return_value=_held_config("A", "X"),
            ),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(
                side_effect=[
                    {"SET:A": _ohlcv_frame(100.0), "SET:X": _ohlcv_frame(50.0)},  # held
                    {"SET:B": _ohlcv_frame(200.0)},  # universe (excluding held)
                ]
            )

            result = await daily_refresh(settings=settings_override, store=mock_store)

        calls = mock_loader.fetch_batch.call_args_list
        assert len(calls) == 2, "Expected one held-phase call and one universe call"
        # First call is the held batch — sorted, SET-prefixed names.
        assert calls[0].kwargs["symbols"] == ["SET:A", "SET:X"]
        # Second call is the universe sweep, with held names removed.
        assert calls[1].kwargs["symbols"] == ["SET:B"]

        assert result["held_symbols_fetched"] == 2
        assert result["held_symbols_failed"] == 0
        # Universe-only "SET:B" + both held "SET:A", "SET:X" all counted.
        assert result["symbols_fetched"] == 3

    async def test_daily_refresh_held_failure_still_runs_universe(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
    ) -> None:
        """Held batch exhausts retries; universe phase + hook still run."""
        mock_store.load.return_value = pd.DataFrame({"symbol": ["SET:A", "SET:B"]})
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch(
                "api.scheduler.jobs.load_live_portfolio",
                # "X" → qualified_symbol "SET:X", which never succeeds.
                return_value=_held_config("X"),
            ),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(
                side_effect=lambda symbols, **_: (
                    {}  # held batch: nothing ever succeeds for "SET:X"
                    if symbols == ["SET:X"]
                    else {s: _ohlcv_frame(100.0) for s in symbols}  # universe: full success
                )
            )

            hook_mock = AsyncMock()
            with patch("csm.adapters.hooks.run_post_refresh_hook", new=hook_mock):
                # Pass a sentinel non-None adapters so the hook is invoked.
                result = await daily_refresh(
                    settings=settings_override,
                    store=mock_store,
                    adapters=MagicMock(),
                )

        assert result["held_symbols_fetched"] == 0
        assert result["held_symbols_failed"] == 1
        # Universe still completed.
        assert result["symbols_fetched"] == 2  # "SET:A" and "SET:B"
        # Hook was still called despite the held failure — it will internally
        # skip the gateway POST when compute_live_portfolio_metrics returns None.
        hook_mock.assert_awaited_once()

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        marker = json.loads(marker_path.read_text())
        assert marker["held_symbols_failed"] == 1
        # Held batch was retried up to its max-attempts setting.
        assert marker["retry_attempts_used"] >= settings_override.refresh_held_max_attempts - 1

    async def test_daily_refresh_no_live_portfolio_config(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
    ) -> None:
        """No YAML → held phase skipped; single universe fetch_batch runs."""
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(
                return_value={
                    "A": _ohlcv_frame(100.0),
                    "B": _ohlcv_frame(200.0),
                }
            )

            result = await daily_refresh(settings=settings_override, store=mock_store)

        # Exactly one batch — the universe sweep.
        assert mock_loader.fetch_batch.await_count == 1
        assert mock_loader.fetch_batch.call_args.kwargs["symbols"] == ["A", "B"]
        assert result["held_symbols_fetched"] == 0
        assert result["held_symbols_failed"] == 0
        assert result["retry_attempts_used"] == 0

    async def test_marker_file_extended_fields(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
    ) -> None:
        """Marker file contains the new fields AND preserves the original four."""
        with (
            patch("api.scheduler.jobs.OHLCVLoader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(
                return_value={
                    "A": _ohlcv_frame(100.0),
                    "B": _ohlcv_frame(200.0),
                }
            )

            await daily_refresh(settings=settings_override, store=mock_store)

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        marker = json.loads(marker_path.read_text())
        # Original keys preserved verbatim.
        for key in ("timestamp", "symbols_fetched", "duration_seconds", "failures"):
            assert key in marker, f"original key {key!r} missing from marker file"
        # New keys present.
        for key in (
            "held_symbols_fetched",
            "held_symbols_failed",
            "retry_attempts_used",
        ):
            assert key in marker, f"new key {key!r} missing from marker file"
