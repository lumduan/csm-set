"""SET trading-calendar lookups.

Wraps settfex's official SET holiday calendar (``settfex>=0.15``, which is why
that floor is load-bearing — the module does not exist below it) behind two
functions:

- :func:`fetch_set_holidays` — strict. Raises :class:`CalendarUnavailableError`
  when the calendar cannot be obtained.
- :func:`is_set_holiday` — **fail-open**. Answers "should we treat today as a
  market closure?" and returns ``False`` on *any* failure.

The upstream is genuinely unreliable — measured, not assumed
------------------------------------------------------------
On 2026-08-01 this endpoint served the full 2026 calendar, then returned
**HTTP 401 on six consecutive attempts** over the following ~40 minutes.
settfex's own error text says the API "returns 401 both for years it does not
serve … and transiently under load". So the unavailable path is not a rare
contingency to be defended against in principle; it is a **common** one, and the
skip this module enables is best-effort by nature.

A failed lookup costs **~7 s** (settfex retries internally) and is bounded at
:data:`CALENDAR_TIMEOUT_SECS`. Against a refresh that runs ~6 minutes that is
~2% — cheap enough to keep, given it saves the entire fetch when it does fire.
What it must never do is turn that flakiness into lost data, hence:

Why fail-open is the design and not a detail
--------------------------------------------
The invariant worth protecting is *"a real trading day gets refreshed"*. The
calendar is only a **proxy** for whether the market is open, and obtaining it is
a live network call against a WAF-gated host. So a calendar outage must never
be able to suppress a real session's refresh — that failure mode (silently
losing a day of live data) is strictly worse than the one this exists to fix
(spending six wasted minutes fetching on a holiday).

The data-derived guard downstream — no fresh price bar ⇒ no gateway write — is
the ground truth and stays in place regardless. This module only lets the
scheduler skip the *fetch* early when it can cheaply prove the market is shut;
it never decides whether a row is written, and it catches nothing the no-bar
guard does not already catch.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from csm.data.exceptions import DataError

logger: logging.Logger = logging.getLogger(__name__)

#: Bound on the calendar lookup. A hung request must not stall the daily
#: refresh; on timeout the caller proceeds as though the market were open.
CALENDAR_TIMEOUT_SECS: float = 15.0


class CalendarUnavailableError(DataError):
    """Raised when the SET holiday calendar cannot be fetched or parsed."""


async def fetch_set_holidays(year: int) -> dict[date, str]:
    """Return ``{holiday_date: official description}`` for *year*.

    Args:
        year: Calendar year to fetch, e.g. ``2026``.

    Returns:
        Mapping of each SET closure in *year* to its official description.

    Raises:
        CalendarUnavailableError: When settfex cannot be reached, returns an
            error, or yields an unparseable payload.
    """
    # Imported lazily so module import stays cheap and settfex's network stack
    # is only touched when a lookup actually happens — mirrors
    # ``scripts/build_universe.py``.
    from settfex.services.set.holiday import get_holidays  # noqa: PLC0415

    try:
        calendar = await asyncio.wait_for(
            get_holidays(year=year, lang="en"), timeout=CALENDAR_TIMEOUT_SECS
        )
    except TimeoutError as exc:
        raise CalendarUnavailableError(
            f"SET holiday calendar for {year} timed out after {CALENDAR_TIMEOUT_SECS}s"
        ) from exc
    except Exception as exc:  # settfex raises a variety of fetch/parse errors
        raise CalendarUnavailableError(
            f"SET holiday calendar for {year} could not be fetched: {exc}"
        ) from exc

    try:
        return {h.holiday_date.date(): h.description for h in calendar.holidays}
    except (AttributeError, TypeError) as exc:
        raise CalendarUnavailableError(
            f"SET holiday calendar for {year} returned an unexpected shape: {exc}"
        ) from exc


async def is_set_holiday(day: date) -> tuple[bool, str]:
    """Return ``(is_holiday, description)`` for *day*, **failing open**.

    Never raises. When the calendar is unavailable this returns
    ``(False, "")`` — i.e. "treat it as a trading day" — because wrongly
    skipping a live session costs data that cannot be recovered, whereas
    wrongly fetching on a holiday costs only time.

    Args:
        day: The calendar date to classify, in SET's local (Bangkok) terms.

    Returns:
        ``(True, "<official description>")`` when *day* is a published SET
        closure; ``(False, "")`` otherwise, including on any failure.
    """
    try:
        holidays = await fetch_set_holidays(day.year)
    except CalendarUnavailableError as exc:
        logger.warning(
            "SET holiday calendar unavailable for %s — proceeding as a trading day: %s",
            day.isoformat(),
            exc,
        )
        return False, ""

    description: str | None = holidays.get(day)
    if description is None:
        return False, ""
    return True, description


__all__: list[str] = [
    "CALENDAR_TIMEOUT_SECS",
    "CalendarUnavailableError",
    "fetch_set_holidays",
    "is_set_holiday",
]
