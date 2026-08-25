"""Unit tests for Phase 5.5 — Scheduler production wiring.

Validates cron parametrization, misfire policies, public-mode skip,
runner contract, marker file writing, and failure-safe wrapper behaviour.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from api.scheduler.jobs import (
    _fetch_batch_with_retry,
    _has_usable_data,
    create_scheduler,
    daily_refresh,
    holiday_poll,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from csm.config.constants import INDEX_SYMBOL
from csm.config.settings import Settings
from csm.data.store import ParquetStore
from csm.live.portfolio import LivePortfolioConfig, LivePosition


def _ohlcv(close: float = 100.0, periods: int = 5) -> pd.DataFrame:
    """One synthetic OHLCV frame, shaped as the loaders return them."""
    dates = pd.date_range("2024-01-01", periods=periods, freq="B", tz="Asia/Bangkok")
    return pd.DataFrame(
        {
            "open": [close] * periods,
            "high": [close + 1.0] * periods,
            "low": [close - 1.0] * periods,
            "close": [close] * periods,
            "volume": [1_000_000.0] * periods,
        },
        index=dates,
    )


def _echoing_fetch_batch(*, fail: set[str] | None = None) -> AsyncMock:
    """A ``fetch_batch`` mock that serves whatever symbols are requested.

    ``daily_refresh`` prepends ``INDEX_SYMBOL`` to the universe, so a mock wired
    to a fixed dict leaves the index permanently unserved: it never counts as
    recovered, the retry loop burns every attempt on it, and the run reports a
    spurious failure. Echoing the request keeps these tests about the behaviour
    they name rather than about the fixture's symbol list.

    Args:
        fail: Symbols to omit from the response, simulating a fetch failure.
    """
    omit: set[str] = fail or set()

    async def _fetch(symbols: list[str], **_: object) -> dict[str, pd.DataFrame]:
        return {s: _ohlcv() for s in symbols if s not in omit}

    return AsyncMock(side_effect=_fetch)


@pytest.fixture(autouse=True)
def _never_hit_the_holiday_api() -> Generator[None, None, None]:
    """Stub the SET holiday calendar at the NETWORK boundary for every test here.

    ``daily_refresh`` consults the calendar before fetching, so without this the
    unit suite would make a live settfex request per test — slow, flaky, and
    dependent on a WAF-gated host being reachable from CI.

    Patching ``get_holidays`` rather than ``is_set_holiday`` is deliberate: it
    leaves the real fail-open wrapper in the call path, so a test that wants to
    exercise an outage can simply override this with a ``side_effect`` and still
    go through the production logic.

    The default is an empty calendar — i.e. "not a holiday" — which keeps every
    pre-existing test behaving exactly as it did before the calendar landed.
    """
    with patch(
        "settfex.services.set.holiday.get_holidays",
        new=AsyncMock(return_value=SimpleNamespace(holidays=[])),
    ):
        yield


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
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = _echoing_fetch_batch()

            result = await daily_refresh(settings=settings_override, store=mock_store)

        assert isinstance(result, dict)
        # A + B + the prepended SET index.
        assert result["symbols_fetched"] == 3
        assert result["failures"] == 0
        assert result["index_fetched"] is True
        assert isinstance(result["duration_seconds"], float)
        assert result["duration_seconds"] > 0

    async def test_writes_marker_file(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
        fetched_data: dict[str, pd.DataFrame],
    ) -> None:
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = _echoing_fetch_batch()

            await daily_refresh(settings=settings_override, store=mock_store)

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        assert marker_path.is_file()
        marker = json.loads(marker_path.read_text())
        assert "timestamp" in marker
        assert marker["symbols_fetched"] == 3  # A + B + the SET index
        assert marker["failures"] == 0
        assert marker["index_fetched"] is True
        assert isinstance(marker["duration_seconds"], float)

    async def test_marker_timestamp_is_iso_utc(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
        fetched_data: dict[str, pd.DataFrame],
    ) -> None:
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = _echoing_fetch_batch()

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
        # B fails; A and the prepended index still come back.
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = _echoing_fetch_batch(fail={"B"})

            result = await daily_refresh(settings=settings_override, store=mock_store)

        # A + the index succeed; B does not.
        assert result["symbols_fetched"] == 2
        assert result["failures"] == 1
        assert result["index_fetched"] is True

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        marker = json.loads(marker_path.read_text())
        assert marker["symbols_fetched"] == 2
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


_BKK = ZoneInfo("Asia/Bangkok")


def _frozen_jobs_clock(moment: datetime) -> object:
    """Pin ``daily_refresh``'s notion of "today" to *moment*.

    ``daily_refresh`` derives the date it classifies from ``datetime.now()``, so
    any test whose meaning depends on *which* date that is has to fix it — see
    ``test_calendar_outage_does_not_suppress_a_refresh``. Subclassing rather
    than mocking keeps the module's other ``datetime.now(UTC)`` call (the marker
    timestamp) returning a real datetime.
    """

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

    return patch("api.scheduler.jobs.datetime", _Frozen)


class TestHolidaySkipsTheFetch:
    """On a published SET closure the refresh skips the fetch entirely.

    Purely an optimisation: without it the scheduler fires, spends ~6 minutes
    pulling a couple of hundred symbols that cannot have moved, and is then
    correctly refused by the no-fresh-bar guard at the write. The calendar lets
    it decline earlier and say why.

    The failure asymmetry is what these tests really pin. Skipping a *real*
    session loses live data that cannot be backfilled, so an outage may never
    mean "assume closed" for a date nothing attests. It resolves live calendar →
    committed fallback → open, so a *known* closure is still caught with the
    endpoint down while an unknown date still trades as normal.
    """

    @pytest.fixture(autouse=True)
    def _no_held_phase(self) -> Generator[None, None, None]:
        with (
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            yield

    async def test_holiday_skips_the_fetch_and_records_why(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline") as MockPipeline,
            patch(
                "api.scheduler.jobs.is_set_holiday",
                new=AsyncMock(return_value=(True, "H.M. Queen Sirikit's Birthday")),
            ),
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch()
            result = await daily_refresh(settings=settings_override, store=mock_store)

            MockLoader.return_value.fetch_batch.assert_not_awaited()
            MockPipeline.return_value.build.assert_not_called()

        assert result["skipped_reason"] == "set_holiday"
        assert "Queen Sirikit" in result["skipped_detail"]
        assert result["symbols_fetched"] == 0
        assert result["failures"] == 0

        marker = json.loads(
            (settings_override.results_dir / ".tmp" / "last_refresh.json").read_text()
        )
        # The marker must still be written: a skipped run that leaves yesterday's
        # marker in place is indistinguishable from a scheduler that never fired.
        assert marker["skipped_reason"] == "set_holiday"
        assert "timestamp" in marker

    async def test_trading_day_runs_normally(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs.is_set_holiday", new=AsyncMock(return_value=(False, ""))),
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch()
            result = await daily_refresh(settings=settings_override, store=mock_store)

            MockLoader.return_value.fetch_batch.assert_awaited()

        assert "skipped_reason" not in result
        assert result["symbols_fetched"] == 3  # A + B + the SET index

    async def test_calendar_outage_does_not_suppress_a_refresh(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        """A settfex outage on an ordinary session still fetches, end to end.

        ``is_set_holiday`` swallows its own errors, so this drives the real
        helper with a broken settfex rather than stubbing the helper out.

        The date is pinned rather than taken from the wall clock. Reading
        ``datetime.now()`` made this test's meaning depend on the day it ran:
        once the committed fallback landed it would have passed all week and
        gone red on 2026-08-12 itself, reporting a calendar regression on the
        one day the new behaviour is correct.
        """
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            _frozen_jobs_clock(datetime(2026, 8, 7, 18, 0, tzinfo=_BKK)),
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("settfex unreachable")),
            ),
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch()
            result = await daily_refresh(settings=settings_override, store=mock_store)

            MockLoader.return_value.fetch_batch.assert_awaited()

        assert "skipped_reason" not in result
        assert result["symbols_fetched"] == 3

    async def test_known_closure_skips_even_with_the_calendar_down(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        """The whole point of the committed fallback, proven end to end.

        Same broken settfex as the test above — only the date differs. Before
        the fallback this fetched 210 symbols on a closed market and relied
        entirely on the downstream no-fresh-bar guard to refuse the write; now
        it declines up front and records why.
        """
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline") as MockPipeline,
            _frozen_jobs_clock(datetime(2026, 8, 12, 18, 0, tzinfo=_BKK)),
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("settfex unreachable")),
            ),
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch()
            result = await daily_refresh(settings=settings_override, store=mock_store)

            MockLoader.return_value.fetch_batch.assert_not_awaited()
            MockPipeline.return_value.build.assert_not_called()

        assert result["skipped_reason"] == "set_holiday"
        assert "Queen Sirikit" in result["skipped_detail"]
        assert result["symbols_fetched"] == 0


class TestIndexSymbolIsAlwaysFetched:
    """The SET index must reach the feature pipeline on every refresh.

    ``FeaturePipeline.build`` gates the risk-adjusted factors on ``INDEX_SYMBOL``
    being a key of ``prices``. The scheduled refresh never included it, so
    ``residual_momentum`` — the only factor that cleared the historical
    ICIR > 0.15 gate — and ``sharpe_momentum`` were silently absent from every
    panel it built, forcing a manual re-fetch at three consecutive month-ends.
    """

    @pytest.fixture(autouse=True)
    def _no_held_phase(self) -> Generator[None, None, None]:
        with (
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            yield

    async def test_index_is_prepended_to_the_universe_request(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch()
            await daily_refresh(settings=settings_override, store=mock_store)

            requested = MockLoader.return_value.fetch_batch.call_args.kwargs["symbols"]
        assert requested[0] == INDEX_SYMBOL, "index must lead the universe request"
        assert requested == [INDEX_SYMBOL, "A", "B"]

    async def test_index_reaches_the_feature_pipeline(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        """The assertion that matters — the pipeline's gate is on `prices`, not the request."""
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline") as MockPipeline,
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch()
            await daily_refresh(settings=settings_override, store=mock_store)

            prices = MockPipeline.return_value.build.call_args.kwargs["prices"]
        assert INDEX_SYMBOL in prices

    async def test_index_not_duplicated_when_already_in_the_universe(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        mock_store.load.return_value = pd.DataFrame({"symbol": [INDEX_SYMBOL, "A"]})
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch()
            await daily_refresh(settings=settings_override, store=mock_store)

            requested = MockLoader.return_value.fetch_batch.call_args.kwargs["symbols"]
        assert requested.count(INDEX_SYMBOL) == 1
        assert requested == [INDEX_SYMBOL, "A"]

    async def test_a_missing_index_is_reported_not_swallowed(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        """If the index cannot be fetched, two factors vanish — say so loudly."""
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
        ):
            MockLoader.return_value.fetch_batch = _echoing_fetch_batch(fail={INDEX_SYMBOL})
            result = await daily_refresh(settings=settings_override, store=mock_store)

        assert result["index_fetched"] is False
        assert result["failures"] == 1

        marker_path = settings_override.results_dir / ".tmp" / "last_refresh.json"
        assert json.loads(marker_path.read_text())["index_fetched"] is False


class TestFetchRecoveryRequiresUsableData:
    """A present-but-empty frame is not a successful fetch.

    ``_fetch_batch_with_retry`` used to treat ``symbol in result`` as recovery.
    ``fetch_batch`` omits hard failures, so that is usually right — but a frame
    can arrive structurally valid and carry no data, and such a symbol dropped
    out of the retry set, was never re-requested, and was counted as fetched.
    """

    def test_all_nan_close_is_not_usable(self) -> None:
        frame = _ohlcv()
        frame["close"] = float("nan")
        assert _has_usable_data(frame) is False

    def test_empty_frame_is_not_usable(self) -> None:
        assert _has_usable_data(_ohlcv().iloc[0:0]) is False

    def test_missing_close_column_is_not_usable(self) -> None:
        assert _has_usable_data(_ohlcv().drop(columns=["close"])) is False

    def test_absent_symbol_is_not_usable(self) -> None:
        assert _has_usable_data(None) is False

    def test_real_data_is_usable(self) -> None:
        assert _has_usable_data(_ohlcv()) is True

    async def test_all_nan_symbol_is_retried_and_never_counted_as_fetched(self) -> None:
        """The regression: an all-NaN symbol must stay in the retry set."""
        empty = _ohlcv()
        empty["close"] = float("nan")
        calls: list[list[str]] = []

        async def _fetch(symbols: list[str], **_: object) -> dict[str, pd.DataFrame]:
            calls.append(list(symbols))
            return {s: (empty if s == "DEAD" else _ohlcv()) for s in symbols}

        loader = MagicMock()
        loader.fetch_batch = AsyncMock(side_effect=_fetch)

        with patch("api.scheduler.jobs._sleep", new=AsyncMock()):
            fetched, retries = await _fetch_batch_with_retry(
                loader, ["LIVE", "DEAD"], max_attempts=3, base_delay_secs=0
            )

        assert "LIVE" in fetched
        assert "DEAD" not in fetched, "an all-NaN frame must not count as fetched"
        assert retries == 2, "the dead symbol should have consumed both retries"
        assert calls[1] == ["DEAD"], "only the unusable symbol is re-requested"


class TestDailyRefreshResilience:
    """A+C: outer-loop retry on failed symbols + held-symbols-first priority."""

    async def test_daily_refresh_retries_failed_symbols(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
    ) -> None:
        """Attempt 1 fails one symbol; retry recovers it. ``retry_attempts_used == 1``."""
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()) as mock_sleep,
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(
                side_effect=[
                    # universe attempt 1: index + A land, B missing
                    {INDEX_SYMBOL: _ohlcv_frame(1500.0), "A": _ohlcv_frame(100.0)},
                    {"B": _ohlcv_frame(200.0)},  # universe retry of just ["B"]
                ]
            )

            result = await daily_refresh(settings=settings_override, store=mock_store)

        assert result["symbols_fetched"] == 3  # A + B + the SET index
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
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
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
                    # universe (excluding held), with the prepended index
                    {INDEX_SYMBOL: _ohlcv_frame(1500.0), "SET:B": _ohlcv_frame(200.0)},
                ]
            )

            result = await daily_refresh(settings=settings_override, store=mock_store)

        calls = mock_loader.fetch_batch.call_args_list
        assert len(calls) == 2, "Expected one held-phase call and one universe call"
        # First call is the held batch — sorted, SET-prefixed names. The index is
        # NOT here: it is a data input, not a holding, so it must not distort the
        # held-symbol counters or ride the stricter held retry policy.
        assert calls[0].kwargs["symbols"] == ["SET:A", "SET:X"]
        # Second call is the universe sweep, held names removed, index prepended.
        assert calls[1].kwargs["symbols"] == [INDEX_SYMBOL, "SET:B"]

        assert result["held_symbols_fetched"] == 2
        assert result["held_symbols_failed"] == 0
        # Universe-only "SET:B" + the index + both held "SET:A", "SET:X".
        assert result["symbols_fetched"] == 4

    async def test_daily_refresh_held_failure_still_runs_universe(
        self,
        settings_override: Settings,
        mock_store: MagicMock,
    ) -> None:
        """Held batch exhausts retries; universe phase + hook still run."""
        mock_store.load.return_value = pd.DataFrame({"symbol": ["SET:A", "SET:B"]})
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
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
        assert result["symbols_fetched"] == 3  # "SET:A", "SET:B" and the index
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
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
            # Belt-and-braces: if the mock ever fails to serve a requested symbol
            # this test would otherwise sit through the real backoff windows.
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = _echoing_fetch_batch()

            result = await daily_refresh(settings=settings_override, store=mock_store)

        # Exactly one batch — the universe sweep, with the index prepended.
        assert mock_loader.fetch_batch.await_count == 1
        assert mock_loader.fetch_batch.call_args.kwargs["symbols"] == [INDEX_SYMBOL, "A", "B"]
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
            patch("api.scheduler.jobs.build_ohlcv_loader") as MockLoader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs.load_live_portfolio", return_value=None),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = _echoing_fetch_batch()

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
            "index_fetched",
        ):
            assert key in marker, f"new key {key!r} missing from marker file"


class TestHolidayPollJob:
    """The opportunistic SET holiday poller (added 2026-08-25).

    Its value is entirely in cadence — see ``csm.data.calendar``'s "Why a
    poller, and not a longer retry". These pin the wiring that delivers it.
    """

    def test_registered_alongside_daily_refresh(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        assert scheduler.get_job("holiday_poll") is not None
        assert scheduler.get_job("daily_refresh") is not None, "must not displace the refresh"

    def test_not_registered_in_public_mode(
        self, public_settings: Settings, mock_store: MagicMock
    ) -> None:
        """Public mode builds no scheduler at all, so the poller cannot fire —
        the same guard that keeps the refresh from running there."""
        assert create_scheduler(public_settings, mock_store) is None

    def test_interval_matches_settings(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        trigger = scheduler.get_job("holiday_poll").trigger
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval == timedelta(minutes=settings_override.holiday_poll_minutes)

    def test_first_run_is_soon_after_boot_not_a_full_interval_away(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        """A container starting the morning of a closure must still get a chance
        to bank the calendar before the 18:00 refresh reads it."""
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        job = scheduler.get_job("holiday_poll")
        delay = job.next_run_time - datetime.now(tz=ZoneInfo("Asia/Bangkok"))
        assert delay < timedelta(minutes=2), "first poll must not wait a full interval"

    def test_misfires_are_dropped_never_queued(
        self, settings_override: Settings, mock_store: MagicMock
    ) -> None:
        """A poll is worth nothing after the fact — the next one is minutes away
        and samples a fresh 60-second cache window. A backlog would fire a burst
        of pointless attempts after any pause."""
        scheduler = create_scheduler(settings_override, mock_store)
        assert scheduler is not None
        job = scheduler.get_job("holiday_poll")
        assert job.coalesce is True
        assert job.misfire_grace_time is not None
        assert job.misfire_grace_time <= 60

    async def test_polls_the_current_bangkok_year(self, settings_override: Settings) -> None:
        """The endpoint only ever serves the current year, so the year argument
        is not configurable — and at the year boundary this starts asking for
        the new one unprompted, which is what closes the 2027 capture hole."""
        with patch(
            "api.scheduler.jobs.capture_set_holidays", new=AsyncMock(return_value=True)
        ) as capture:
            assert await holiday_poll(settings=settings_override) is True

        year, path = capture.await_args.args
        assert year == datetime.now(tz=ZoneInfo("Asia/Bangkok")).year
        assert path == settings_override.results_dir / ".tmp" / "set_holidays.json"

    async def test_a_failed_poll_is_not_an_error(self, settings_override: Settings) -> None:
        """The endpoint's normal state is down; returning False is routine."""
        with patch("api.scheduler.jobs.capture_set_holidays", new=AsyncMock(return_value=False)):
            assert await holiday_poll(settings=settings_override) is False
