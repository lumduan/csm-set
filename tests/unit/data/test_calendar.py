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

    @pytest.mark.parametrize(
        "failure",
        [RuntimeError("network down"), TimeoutError(), ValueError("garbage payload")],
        ids=["network", "timeout", "garbage"],
    )
    async def test_fails_open_on_any_upstream_failure(self, failure: Exception) -> None:
        """The test that matters most.

        A calendar outage must degrade to "treat it as a trading day". The
        opposite — suppressing a real session's refresh because settfex was
        unreachable — would lose live data that cannot be backfilled, which is a
        strictly worse failure than the wasted fetch this optimisation avoids.
        """
        with patch("settfex.services.set.holiday.get_holidays", new=AsyncMock(side_effect=failure)):
            is_holiday, name = await is_set_holiday(date(2026, 8, 12))

        assert is_holiday is False, "an unavailable calendar must not suppress a refresh"
        assert name == ""

    async def test_fail_open_is_logged_loudly(self, caplog: pytest.LogCaptureFixture) -> None:
        """Silent degradation is not acceptable — the operator must be able to see it."""
        with (
            patch(
                "settfex.services.set.holiday.get_holidays",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level("WARNING", logger="csm.data.calendar"),
        ):
            await is_set_holiday(date(2026, 8, 12))

        assert "proceeding as a trading day" in caplog.text
