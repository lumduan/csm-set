"""Unit tests for the SET trading-calendar lookups.

The behaviour these pin is asymmetric on purpose. Getting a holiday wrong in one
direction wastes six minutes of fetching; getting it wrong in the other silently
loses a live session's data, which cannot be recovered. So the tests that matter
most here are the failure-path ones.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from csm.data.calendar import (
    FALLBACK_SET_HOLIDAYS,
    CalendarUnavailableError,
    cache_captured_at,
    capture_set_holidays,
    fetch_set_holidays,
    is_set_holiday,
    read_holiday_cache,
    write_holiday_cache,
)

_BKK = ZoneInfo("Asia/Bangkok")


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module default at a per-test file.

    Autouse and unconditional: the real default is ``results/.tmp/set_holidays.json``
    *relative to the working directory*, so without this a test run inside a
    deployed checkout would read — and ``write_holiday_cache`` would clobber —
    live runtime state. Every test then exercises the same default-resolution
    path production does, rather than a parameter production never passes.
    """
    cache = tmp_path / "set_holidays.json"
    monkeypatch.setattr("csm.data.calendar.HOLIDAY_CACHE_PATH", cache)
    return cache


def _seed_cache(path: Path, *entries: tuple[str, str], year: int = 2026) -> None:
    """Bank *entries* as though the poller had captured them.

    Deliberately routed through the real ``write_holiday_cache`` rather than
    hand-written JSON, so a test can never assert against a file shape the
    writer does not actually produce.
    """
    write_holiday_cache(year, {date.fromisoformat(d): desc for d, desc in entries}, path)


def _calendar(*entries: tuple[str, str]) -> SimpleNamespace:
    """Build a stand-in for settfex's ``HolidayCalendar``."""
    return SimpleNamespace(
        holidays=[
            SimpleNamespace(
                holiday_date=datetime.fromisoformat(f"{d}T00:00:00").replace(tzinfo=_BKK),
                description=desc,
            )
            for d, desc in entries
        ]
    )


# The four real 2026 closures inside the live-test window, as published by SET.
_REAL_2026 = (
    ("2026-06-01", "Substitution for Visakha Bucha Day (Sunday 31st May 2026)"),
    ("2026-06-03", "H.M. Queen Suthida Bajrasudhabimalalakshana's Birthday"),
    ("2026-07-28", "H.M. King Maha Vajiralongkorn Phra Vajiraklaochaoyuhua's Birthday"),
    ("2026-07-29", "Asarnha Bucha Day"),
    ("2026-08-12", "H.M. Queen Sirikit The Queen Mother's Birthday / Mother's Day"),
)


class TestFetchSetHolidays:
    async def test_returns_date_to_description_mapping(self) -> None:
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(return_value=_calendar(*_REAL_2026)),
        ):
            holidays = await fetch_set_holidays(2026)

        assert holidays[date(2026, 8, 12)].startswith("H.M. Queen Sirikit")
        assert set(holidays) == {
            date(2026, 6, 1),
            date(2026, 6, 3),
            date(2026, 7, 28),
            date(2026, 7, 29),
            date(2026, 8, 12),
        }

    async def test_upstream_failure_raises(self) -> None:
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("WAF blocked the request")),
            ),
            pytest.raises(CalendarUnavailableError, match="could not be fetched"),
        ):
            await fetch_set_holidays(2026)

    async def test_timeout_raises(self) -> None:
        """Exercises the real ``asyncio.wait_for`` bound, not a mocked-away one.

        A hung upstream must not stall the daily refresh, so the timeout is part
        of the contract rather than an implementation detail.
        """

        async def _hang(*_a: object, **_kw: object) -> object:
            await asyncio.sleep(10)
            raise AssertionError("should have timed out")

        with (
            patch("settfex.services.set.holiday.get_holidays", new=_hang),
            patch("csm.data.calendar.CALENDAR_TIMEOUT_SECS", 0.01),
            pytest.raises(CalendarUnavailableError, match="timed out"),
        ):
            await fetch_set_holidays(2026)

    async def test_unexpected_payload_shape_raises(self) -> None:
        broken = SimpleNamespace(holidays=[SimpleNamespace(nope=1)])
        with (
            patch("settfex.services.set.holiday.get_holidays", new=AsyncMock(return_value=broken)),
            pytest.raises(CalendarUnavailableError, match="unexpected shape"),
        ):
            await fetch_set_holidays(2026)


class TestIsSetHoliday:
    async def test_true_for_a_published_closure(self) -> None:
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(return_value=_calendar(*_REAL_2026)),
        ):
            is_holiday, name = await is_set_holiday(date(2026, 8, 12))

        assert is_holiday is True
        assert "Queen Sirikit" in name

    async def test_false_for_a_trading_day(self) -> None:
        """2026-08-03 — the Monday the August ATO executes on."""
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(return_value=_calendar(*_REAL_2026)),
        ):
            is_holiday, name = await is_set_holiday(date(2026, 8, 3))

        assert is_holiday is False
        assert name == ""

    async def test_banked_cache_overrides_the_fallback(self, _isolated_cache: Path) -> None:
        """The banked payload is authoritative — the two sources are never OR-ed.

        A closure withdrawn upstream must stop being a closure here, so a
        captured calendar has to *replace* the committed table rather than be
        unioned with it. 2026-08-12 is in the fallback; a cache that omits it
        must win.
        """
        _seed_cache(_isolated_cache, ("2026-09-21", "Some new closure"))
        is_holiday, name = await is_set_holiday(date(2026, 8, 12))

        assert is_holiday is False, "a banked capture must override the committed table"
        assert name == ""


class TestTableDriftIsReported:
    """The committed table is a snapshot; these make it say when it has rotted.

    This is what replaces a dated reminder to capture 2027: the first session
    that reaches a serving endpoint reports the gap, and keeps reporting it.
    """

    async def test_missing_year_is_reported_with_the_dates_to_capture(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """The 2027-01-01 case, which is the whole point.

        The endpoint serves only the current year, so this warning is the only
        notice that the capture window is open.
        """
        assert 2027 not in FALLBACK_SET_HOLIDAYS
        _seed_cache(
            _isolated_cache,
            ("2027-01-01", "New Year's Day"),
            ("2027-04-06", "Chakri Memorial Day"),
            year=2027,
        )
        with caplog.at_level("WARNING", logger="csm.data.calendar"):
            await is_set_holiday(date(2027, 1, 1))

        assert "no committed fallback table for 2027" in caplog.text
        assert "2027-01-01" in caplog.text and "2027-04-06" in caplog.text
        assert "current year" in caplog.text

    async def test_a_closure_added_after_the_snapshot_is_reported(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """SET inserting a new special closure mid-year — otherwise invisible."""
        _seed_cache(_isolated_cache, *_REAL_2026, ("2026-11-20", "Additional special holiday *"))
        with caplog.at_level("WARNING", logger="csm.data.calendar"):
            await is_set_holiday(date(2026, 8, 3))

        assert "STALE" in caplog.text
        assert "promote: 2026-11-20" in caplog.text

    async def test_drift_is_reported_even_on_an_ordinary_trading_day(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """Staleness must not depend on today happening to be a closure.

        2026-08-03 is a normal Monday; the check runs before the lookup, so the
        report does not wait for the next holiday to surface.
        """
        _seed_cache(_isolated_cache, ("2026-11-20", "Additional special holiday *"))
        with caplog.at_level("WARNING", logger="csm.data.calendar"):
            is_holiday, _ = await is_set_holiday(date(2026, 8, 3))

        assert is_holiday is False
        assert "STALE" in caplog.text

    async def test_in_sync_is_stated_rather_than_silent(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """ "Matches" must be distinguishable from "the check never ran"."""
        _seed_cache(
            _isolated_cache,
            *[(d.isoformat(), desc) for d, desc in FALLBACK_SET_HOLIDAYS[2026].items()],
        )
        with caplog.at_level("INFO", logger="csm.data.calendar"):
            await is_set_holiday(date(2026, 8, 3))

        assert "matches the live calendar (20 closures)" in caplog.text
        assert "STALE" not in caplog.text

    async def test_drift_reporting_never_changes_the_verdict(self, _isolated_cache: Path) -> None:
        """Observational only. A stale table must not alter what is returned."""
        _seed_cache(_isolated_cache, ("2026-11-20", "Additional special holiday *"))
        # 2026-08-12 is in the committed table but NOT in this banked payload,
        # so the banked answer must still win despite the drift warning.
        assert await is_set_holiday(date(2026, 8, 12)) == (False, "")
        assert await is_set_holiday(date(2026, 11, 20)) == (
            True,
            "Additional special holiday *",
        )

    async def test_no_drift_report_when_the_endpoint_is_down(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The fallback cannot drift from itself — reporting it would be noise
        that trains the operator to ignore the real signal."""
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("401")),
            ),
            caplog.at_level("INFO", logger="csm.data.calendar"),
        ):
            await is_set_holiday(date(2026, 8, 12))

        assert "STALE" not in caplog.text
        assert "matches the live calendar" not in caplog.text


class TestFallbackWhenTheCalendarIsDown:
    """The 2026-08-04 → 08-06 outage state: settfex 401s on every year.

    Failing closed on any error was rejected precisely because of this — it
    would have skipped every session from 08-04 onward. The fallback answers
    known closures offline while leaving unknown dates open.
    """

    @pytest.mark.parametrize(
        "failure",
        [RuntimeError("network down"), TimeoutError(), ValueError("garbage payload")],
        ids=["network", "timeout", "garbage"],
    )
    async def test_known_closure_is_caught_offline(self, failure: Exception) -> None:
        """The point of the change: 2026-08-12 skips with the endpoint down."""
        with patch("settfex.services.set.holiday.get_holidays", new=AsyncMock(side_effect=failure)):
            is_holiday, name = await is_set_holiday(date(2026, 8, 12))

        assert is_holiday is True, "a committed closure must survive a calendar outage"
        assert "Queen Sirikit" in name

    async def test_trading_day_still_runs_offline(self) -> None:
        """The other half — the fallback must not over-skip.

        2026-08-07 is a normal Friday session. If an outage made this return
        True the refresh would be suppressed on a live trading day, which is the
        failure this module exists to prevent.
        """
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(side_effect=RuntimeError("401")),
        ):
            is_holiday, name = await is_set_holiday(date(2026, 8, 7))

        assert is_holiday is False
        assert name == ""

    async def test_uncovered_year_fails_open_loudly(self, caplog: pytest.LogCaptureFixture) -> None:
        """The only remaining open path, and it must be audible.

        2027 has no committed table. Losing a real session is worse than a
        wasted fetch, so this stays open — but silently degrading is not
        acceptable, hence ERROR rather than WARNING.
        """
        assert 2027 not in FALLBACK_SET_HOLIDAYS, "test presumes 2027 is uncovered"
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level("ERROR", logger="csm.data.calendar"),
        ):
            is_holiday, name = await is_set_holiday(date(2027, 8, 12))

        assert is_holiday is False
        assert name == ""
        assert "neither banked nor covered by a committed fallback for 2027" in caplog.text
        assert "proceeding as a trading day" in caplog.text

    async def test_fallback_use_is_logged_loudly(self, caplog: pytest.LogCaptureFixture) -> None:
        """Running on stale committed data must never be invisible."""
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level("WARNING", logger="csm.data.calendar"),
        ):
            await is_set_holiday(date(2026, 8, 12))

        assert "committed" in caplog.text
        assert "fallback" in caplog.text


class TestFallbackTableIntegrity:
    """Structural checks on the committed table.

    A wrong entry here suppresses a real session's refresh — the one outcome
    the module exists to prevent — and a typo is the likeliest way to get one.
    """

    def test_every_date_matches_its_year_key(self) -> None:
        for year, holidays in FALLBACK_SET_HOLIDAYS.items():
            for day in holidays:
                assert day.year == year, f"{day} filed under {year}"

    def test_no_entry_falls_on_a_weekend(self) -> None:
        """SET is shut at weekends anyway, so a weekend entry signals a typo."""
        for holidays in FALLBACK_SET_HOLIDAYS.values():
            for day in holidays:
                assert day.weekday() < 5, f"{day} is a {day:%A} — not a market day to begin with"

    def test_every_entry_carries_a_description(self) -> None:
        for holidays in FALLBACK_SET_HOLIDAYS.values():
            for day, description in holidays.items():
                assert description.strip(), f"{day} has an empty description"

    def test_the_2026_closures_verified_from_the_live_fetch_are_all_present(self) -> None:
        """Guards against an entry being dropped in a future edit.

        These five are the subset whose dates *and* official wording came from
        the authoritative 2026-08-01 fetch, so they are the strongest entries in
        the table and the ones a regression would hurt most.
        """
        table = FALLBACK_SET_HOLIDAYS[2026]
        for iso, description in _REAL_2026:
            day = date.fromisoformat(iso)
            assert day in table, f"{iso} missing from the committed 2026 table"
            assert table[day] == description, f"{iso} wording drifted from the fetched calendar"

    def test_2026_holds_all_twenty_published_closures(self) -> None:
        """2026 is complete — a short table means entries were lost, not that
        SET published fewer. The count is pinned separately from the dates so a
        failure says *which* of the two went wrong."""
        assert len(FALLBACK_SET_HOLIDAYS[2026]) == 20

    @pytest.mark.parametrize(
        ("iso", "description"),
        [
            ("2026-10-13", "H.M. King Bhumibol Adulyadej the Great Memorial Day"),
            ("2026-10-16", "Additional special holiday *"),
            ("2026-10-23", "H.M. King Chulalongkorn the Great Memorial Day"),
            (
                "2026-12-07",
                "Substitution for H.M. King Bhumibol Adulyadej the Great's Birthday / "
                "National Day / Father's Day (Saturday 5th December 2026)",
            ),
            ("2026-12-10", "Constitution Day"),
            ("2026-12-31", "New Year's Eve"),
        ],
    )
    def test_q4_closures_promoted_from_the_2026_08_07_fetch(
        self, iso: str, description: str
    ) -> None:
        """The six Q4 dates, promoted once the endpoint came back.

        None is derivable from the price panel — they are all still in the
        future — so the live payload is their only source and the wording is
        asserted verbatim rather than by prefix.
        """
        table = FALLBACK_SET_HOLIDAYS[2026]
        day = date.fromisoformat(iso)
        assert day in table, f"{iso} was not promoted"
        assert table[day] == description

    def test_the_footnote_marker_is_not_stripped(self) -> None:
        """``" *"`` is SET's own marker for an additional special closure.

        settfex preserves it deliberately — ``Holiday`` is the one SET model that
        does not enable ``str_strip_whitespace`` — so "tidying" it here would
        silently diverge from the upstream payload this table is a copy of.
        """
        assert FALLBACK_SET_HOLIDAYS[2026][date(2026, 10, 16)].endswith(" *")

    def test_2027_is_absent_because_it_cannot_yet_be_captured(self) -> None:
        """Not an oversight: the endpoint serves only the current year, so a
        2027 table can only be built from 2027-01-01. Pinning this stops it
        being "fixed" by inventing dates."""
        assert 2027 not in FALLBACK_SET_HOLIDAYS


class TestHolidayCacheFile:
    """The banked cache is now the primary source, so its parser is load-bearing.

    Every rejection test here carries a **positive control** — the same call
    against a valid file — because ``read_holiday_cache`` returning ``{}`` is
    satisfied by literally any failure, including one that never parsed
    anything. Without the control, a parser that always returned ``{}`` would
    pass the whole class.
    """

    def test_roundtrip(self, _isolated_cache: Path) -> None:
        write_holiday_cache(2026, {date(2026, 8, 12): "Mother's Day"}, _isolated_cache)
        assert read_holiday_cache(_isolated_cache) == {2026: {date(2026, 8, 12): "Mother's Day"}}
        assert cache_captured_at(_isolated_cache) is not None

    def test_missing_file_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert read_holiday_cache(tmp_path / "nope.json") == {}
        assert cache_captured_at(tmp_path / "nope.json") is None

    def test_a_second_year_does_not_destroy_the_first(self, _isolated_cache: Path) -> None:
        """The 2026/2027 boundary. A year is only capturable while it is current,
        so a 2027 capture overwriting the banked 2026 would be unrecoverable."""
        write_holiday_cache(2026, {date(2026, 8, 12): "Mother's Day"}, _isolated_cache)
        write_holiday_cache(2027, {date(2027, 1, 1): "New Year's Day"}, _isolated_cache)

        banked = read_holiday_cache(_isolated_cache)
        assert set(banked) == {2026, 2027}
        assert banked[2026] == {date(2026, 8, 12): "Mother's Day"}

    def test_recapturing_a_year_replaces_it_rather_than_merging(
        self, _isolated_cache: Path
    ) -> None:
        """A closure withdrawn upstream must disappear, not linger via a union."""
        write_holiday_cache(2026, {date(2026, 8, 12): "A", date(2026, 9, 9): "B"}, _isolated_cache)
        write_holiday_cache(2026, {date(2026, 8, 12): "A"}, _isolated_cache)

        assert read_holiday_cache(_isolated_cache)[2026] == {date(2026, 8, 12): "A"}

    @pytest.mark.parametrize(
        ("payload", "reason"),
        [
            ("{ not json", "unparseable"),
            ('{"schema": 99, "years": {"2026": {"2026-08-12": "x"}}}', "schema mismatch"),
            ('{"schema": 1}', "no years mapping"),
            ('{"schema": 1, "years": {"2026": {}}}', "empty year is a failed capture"),
            ('{"schema": 1, "years": {"2026": {"2027-01-01": "x"}}}', "date under the wrong year"),
            ('{"schema": 1, "years": {"2026": {"not-a-date": "x"}}}', "unparseable date"),
            ('{"schema": 1, "years": {"2026": {"2026-08-12": ""}}}', "blank description"),
            ('{"schema": 1, "years": {"2026": {"2026-08-12": 7}}}', "non-string description"),
            ('{"schema": 1, "years": {"2026": ["2026-08-12"]}}', "year is not a mapping"),
        ],
    )
    def test_malformed_cache_is_dropped(
        self, _isolated_cache: Path, payload: str, reason: str
    ) -> None:
        """Dropping is the SAFE direction: the caller falls through to the
        committed fallback, which is exactly the pre-cache behaviour. Salvaging
        a partial file risks the one outcome this module must never produce —
        wrongly reporting a trading day as closed."""
        _isolated_cache.write_text(payload, encoding="utf-8")
        assert read_holiday_cache(_isolated_cache).get(2026) is None, reason

    def test_positive_control_for_the_rejection_cases(self, _isolated_cache: Path) -> None:
        """The control the class docstring demands: a *well-formed* file at the
        same path, through the same call, must parse. Without this, a parser
        that unconditionally returned {} would pass every case above."""
        _isolated_cache.write_text(
            '{"schema": 1, "years": {"2026": {"2026-08-12": "Mother\'s Day"}}}', encoding="utf-8"
        )
        assert read_holiday_cache(_isolated_cache) == {2026: {date(2026, 8, 12): "Mother's Day"}}

    def test_write_leaves_no_partial_file_behind(self, _isolated_cache: Path) -> None:
        """A crash mid-write must not leave a truncated file the next read has
        to interpret — the write is tmp + os.replace for exactly this."""
        with (
            patch("csm.data.calendar.json.dump", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            write_holiday_cache(2026, {date(2026, 8, 12): "x"}, _isolated_cache)

        assert not _isolated_cache.exists()
        assert list(_isolated_cache.parent.glob(".set_holidays-*")) == []


class TestCaptureSetHolidays:
    """The poller's single attempt. It must never raise and never bank junk."""

    async def test_success_banks_the_calendar(self, _isolated_cache: Path) -> None:
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(return_value=_calendar(*_REAL_2026)),
        ):
            assert await capture_set_holidays(2026, _isolated_cache) is True

        assert read_holiday_cache(_isolated_cache)[2026][date(2026, 8, 12)].startswith("H.M. Queen")

    async def test_failure_returns_false_and_writes_nothing(self, _isolated_cache: Path) -> None:
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(side_effect=RuntimeError("401")),
        ):
            assert await capture_set_holidays(2026, _isolated_cache) is False

        assert not _isolated_cache.exists()

    async def test_failure_does_not_clobber_an_existing_capture(
        self, _isolated_cache: Path
    ) -> None:
        """The endpoint is down ~97% of the time, so this path runs constantly.
        A failure that wiped the cache would make the poller strictly harmful."""
        _seed_cache(_isolated_cache, ("2026-08-12", "Mother's Day"))
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(side_effect=RuntimeError("401")),
        ):
            await capture_set_holidays(2026, _isolated_cache)

        assert read_holiday_cache(_isolated_cache)[2026] == {date(2026, 8, 12): "Mother's Day"}

    async def test_an_empty_200_is_not_banked(self, _isolated_cache: Path) -> None:
        """A 200 carrying an empty array is a failed capture, not a year with no
        holidays. Banking it would mask EVERY closure in the year — the exact
        wrong-direction error the module is built to avoid."""
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(return_value=_calendar()),
            ),
            patch("csm.data.calendar.write_holiday_cache") as writer,
        ):
            assert await capture_set_holidays(2026, _isolated_cache) is False

        writer.assert_not_called()

    async def test_routine_failure_is_SILENT(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """~48 polls/day against an endpoint whose normal state is down. If each
        failure logged at WARNING it would emit ~48 lines/day and bury the one
        line that matters, which is the failure mode the poller exists to fix."""
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("401")),
            ),
            caplog.at_level("INFO", logger="csm.data.calendar"),
        ):
            await capture_set_holidays(2026, _isolated_cache)

        assert caplog.text == "", "a routine poll failure must not log above DEBUG"

    async def test_first_capture_is_announced(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """The rare, genuinely newsworthy event — and the counterpart control to
        the silence test above, proving the logger is wired at all."""
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(return_value=_calendar(*_REAL_2026)),
            ),
            caplog.at_level("INFO", logger="csm.data.calendar"),
        ):
            await capture_set_holidays(2026, _isolated_cache)

        assert "BANKED 2026 for the first time" in caplog.text

    async def test_an_unchanged_recapture_is_quiet(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """The overwhelmingly common success case, once banked."""
        live = _calendar(*_REAL_2026)
        with patch("settfex.services.set.holiday.get_holidays", new=AsyncMock(return_value=live)):
            await capture_set_holidays(2026, _isolated_cache)
            caplog.clear()
            with caplog.at_level("INFO", logger="csm.data.calendar"):
                await capture_set_holidays(2026, _isolated_cache)

        assert caplog.text == "", "an unchanged recapture must not log above DEBUG"

    async def test_a_changed_calendar_is_loud(
        self, caplog: pytest.LogCaptureFixture, _isolated_cache: Path
    ) -> None:
        """SET adding a closure mid-year is exactly what nothing else would catch."""
        _seed_cache(_isolated_cache, *_REAL_2026)
        added = _calendar(*_REAL_2026, ("2026-11-20", "Additional special holiday *"))
        with (
            patch("settfex.services.set.holiday.get_holidays", new=AsyncMock(return_value=added)),
            caplog.at_level("WARNING", logger="csm.data.calendar"),
        ):
            await capture_set_holidays(2026, _isolated_cache)

        assert "CHANGED since the last capture" in caplog.text
        assert "added: 2026-11-20" in caplog.text


class TestIsSetHolidayDoesNoNetworkIO:
    """The contract change of 2026-08-25, and the reason the poller exists.

    ``is_set_holiday`` runs on the daily refresh's critical path. It used to
    spend a fixed ~7 s there on settfex retries for a ~10% chance of a fresh
    answer. If a future edit reintroduces an inline fetch, this fails.
    """

    async def test_no_fetch_when_the_cache_answers(self, _isolated_cache: Path) -> None:
        _seed_cache(_isolated_cache, *_REAL_2026)
        with patch("settfex.services.set.holiday.get_holidays", new=AsyncMock()) as fetcher:
            assert (await is_set_holiday(date(2026, 8, 12)))[0] is True

        fetcher.assert_not_called()

    async def test_no_fetch_when_falling_back_either(self, tmp_path: Path) -> None:
        """The cache-miss path is the one that used to make the network call."""
        with patch("settfex.services.set.holiday.get_holidays", new=AsyncMock()) as fetcher:
            assert (await is_set_holiday(date(2026, 8, 12), tmp_path / "absent.json"))[0] is True

        fetcher.assert_not_called()

    async def test_a_hanging_endpoint_cannot_stall_the_refresh(self, tmp_path: Path) -> None:
        """Previously bounded only by CALENDAR_TIMEOUT_SECS=15. Now unreachable:
        with no inline fetch there is nothing to time out."""

        async def _never_returns(*_a: object, **_k: object) -> None:
            await asyncio.sleep(3600)

        with patch("settfex.services.set.holiday.get_holidays", new=_never_returns):
            result = await asyncio.wait_for(
                is_set_holiday(date(2026, 8, 12), tmp_path / "absent.json"), timeout=2.0
            )

        assert result[0] is True
