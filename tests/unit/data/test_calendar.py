"""Unit tests for the SET trading-calendar lookups.

The behaviour these pin is asymmetric on purpose. Getting a holiday wrong in one
direction wastes six minutes of fetching; getting it wrong in the other silently
loses a live session's data, which cannot be recovered. So the tests that matter
most here are the failure-path ones.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from csm.data.calendar import (
    FALLBACK_SET_HOLIDAYS,
    CalendarUnavailableError,
    fetch_set_holidays,
    is_set_holiday,
)

_BKK = ZoneInfo("Asia/Bangkok")


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

    async def test_live_calendar_overrides_the_fallback(self) -> None:
        """The live payload is authoritative — the two sources are never OR-ed.

        A closure withdrawn upstream must stop being a closure here, so a
        successful fetch has to *replace* the committed table rather than be
        unioned with it. 2026-08-12 is in the fallback; a live calendar that
        omits it must win.
        """
        with patch(
            "settfex.services.set.holiday.get_holidays",
            new=AsyncMock(return_value=_calendar(("2026-09-21", "Some new closure"))),
        ):
            is_holiday, name = await is_set_holiday(date(2026, 8, 12))

        assert is_holiday is False, "a successful fetch must override the committed table"
        assert name == ""


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
        assert "no committed fallback covers 2027" in caplog.text
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
