"""SET trading-calendar lookups.

Wraps settfex's official SET holiday calendar (``settfex>=0.15``, which is why
that floor is load-bearing — the module does not exist below it) behind two
functions:

- :func:`fetch_set_holidays` — strict. Raises :class:`CalendarUnavailableError`
  when the calendar cannot be obtained.
- :func:`is_set_holiday` — resolves "should we treat this day as a market
  closure?" against the live calendar, then :data:`FALLBACK_SET_HOLIDAYS`, and
  only fails open when neither can answer.

The upstream is genuinely unreliable — measured, not assumed
------------------------------------------------------------
On 2026-08-01 this endpoint served the full 2026 calendar, then returned
**HTTP 401 on six consecutive attempts** over the following ~40 minutes. By
2026-08-06 it had returned 401 on **four consecutive scheduled refreshes**
(08-04 → 08-06), and a live probe that day found it 401ing for **2025, 2026 and
2027 alike** — i.e. wholly unavailable, not merely year-scoped. settfex's own
error text says the API "returns 401 both for years it does not serve … and
transiently under load"; its docs add that 401 is the *only* failure code it
emits and is therefore ambiguous by construction.

A failed lookup costs **~7 s** (settfex retries internally) and is bounded at
:data:`CALENDAR_TIMEOUT_SECS`. Against a refresh that runs ~6 minutes that is
~2% — cheap enough to keep, given it saves the entire fetch when it does fire.

Why a committed fallback, and not simply failing closed
-------------------------------------------------------
The invariant worth protecting is *"a real trading day gets refreshed"*. The
calendar is only a **proxy** for whether the market is open, and obtaining it is
a live network call against a WAF-gated host. So a calendar outage must never be
able to suppress a real session's refresh — that failure mode (silently losing a
day of live data) is strictly worse than the one this exists to fix (spending
six wasted minutes fetching on a holiday).

That is why *failing closed on any error* was rejected: with the endpoint 401ing
on every year, "unavailable ⇒ assume closed" would have skipped **every**
session from 2026-08-04 onward and stopped the live test outright. The outage is
the normal case here, not the exception.

:data:`FALLBACK_SET_HOLIDAYS` resolves that tension. A published closure is
answered from a committed table when the network cannot answer, so the skip
works offline, while an unknown date still degrades to "trading day".

**The table's errors are asymmetric, and that governs what may go in it:**

- A **missing** entry is safe. It degrades to the pre-existing behaviour — the
  refresh runs, wastes ~6 minutes, and the data-derived no-fresh-bar guard in
  ``csm.adapters.hooks`` refuses the gateway write anyway.
- A **wrong** entry is not. It suppresses a real session's refresh, which is the
  one outcome this module exists to prevent.

So a date is listed only when it is independently verified, and the table is
deliberately allowed to be incomplete.

The data-derived guard downstream — no fresh price bar ⇒ no gateway write — is
still the ground truth and stays in place regardless. This module only lets the
scheduler skip the *fetch* early; it never decides whether a row is written.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from csm.data.exceptions import DataError

logger: logging.Logger = logging.getLogger(__name__)

#: Bound on the calendar lookup. A hung request must not stall the daily
#: refresh; on timeout the caller falls back to the committed table.
CALENDAR_TIMEOUT_SECS: float = 15.0

#: Description used where a closure's *date* is verified but SET's official
#: wording is not. The date is what the guard acts on; inventing plausible
#: official text would make an unverified string indistinguishable from a
#: fetched one.
_DESCRIPTION_UNAVAILABLE: str = "SET closure (official description unavailable offline)"

#: SET closures consulted when the live calendar cannot be reached, by year.
#:
#: Provenance tag per entry — every date carries at least one:
#:
#: ``[fetch]``  verbatim from the authoritative settfex fetch of 2026-08-01, the
#:              last time the endpoint served. Recorded in
#:              ``docs/live-test/monthly/2026-07.md`` and pinned in
#:              ``tests/unit/data/test_calendar.py::_REAL_2026``.
#: ``[panel]``  derived from ``data/processed/prices_latest.parquet`` on
#:              2026-08-06: a 2026 weekday carrying **no bar for any symbol**
#:              while every trading date in the panel carries 210–211. This is
#:              the same method that originally identified the four closures
#:              whose phantom gateway rows were deleted on 2026-07-31, and it
#:              agreed with the official calendar on all four.
#: ``[docs]``   description cross-checked against settfex's holiday docs
#:              (live-verified 2026-07-27).
#:
#: KNOWN INCOMPLETE. The 2026-08-01 fetch reported **20** closures; 14 are listed
#: below. The remainder fall after 2026-08-06, so they are not yet derivable from
#: the price panel and no second source attests them. One is probable but
#: deliberately **not** listed: 2026-10-16, "Additional special holiday *",
#: which appears in settfex's docs but has only that single source — under the
#: asymmetry above a lone unverified future date is exactly what must not go in.
#: Promote it (and the rest of Q4) once the live endpoint recovers or the dates
#: pass into the panel.
FALLBACK_SET_HOLIDAYS: dict[int, dict[date, str]] = {
    2026: {
        # -- [fetch] + [panel] ------------------------------------------------
        # Date and official wording both from the 2026-08-01 calendar; all four
        # are additionally confirmed by the panel. The strongest entries here.
        date(2026, 6, 1): "Substitution for Visakha Bucha Day (Sunday 31st May 2026)",
        date(2026, 6, 3): "H.M. Queen Suthida Bajrasudhabimalalakshana's Birthday",
        date(2026, 7, 28): "H.M. King Maha Vajiralongkorn Phra Vajiraklaochaoyuhua's Birthday",
        date(2026, 7, 29): "Asarnha Bucha Day",
        # -- [fetch] ----------------------------------------------------------
        # Still ahead of the panel, so the 2026-08-01 fetch is its only source —
        # but that source is the official calendar, and three committed docs
        # record the same date. This is the closure the fallback exists for.
        date(2026, 8, 12): "H.M. Queen Sirikit The Queen Mother's Birthday / Mother's Day",
        # -- [panel] + [docs] -------------------------------------------------
        # Date proven by the panel; wording corroborated by settfex's holiday
        # docs (live-verified 2026-07-27), which agreed with the panel on every
        # date it could be checked against.
        date(2026, 1, 1): "New Year's Day",
        date(2026, 4, 6): "Chakri Memorial Day",
        date(2026, 4, 13): "Songkran Festival",
        date(2026, 4, 14): "Songkran Festival",
        date(2026, 4, 15): "Songkran Festival",
        # -- [panel] ----------------------------------------------------------
        # Date proven by the panel; no second source for SET's official wording.
        # The date is what the guard acts on, so these are safe to list.
        date(2026, 1, 2): _DESCRIPTION_UNAVAILABLE,
        date(2026, 3, 3): _DESCRIPTION_UNAVAILABLE,
        date(2026, 5, 1): _DESCRIPTION_UNAVAILABLE,
        date(2026, 5, 4): _DESCRIPTION_UNAVAILABLE,
    },
}


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
    """Return ``(is_holiday, description)`` for *day*. Never raises.

    Resolution order:

    1. The **live** settfex calendar — authoritative, and the only source that
       can carry a closure the committed table has never seen.
    2. :data:`FALLBACK_SET_HOLIDAYS` for ``day.year`` — a definite answer while
       the endpoint is down, which since 2026-08-04 is the normal state.
    3. Neither available ⇒ ``(False, "")``, logged at ERROR. This is the only
       remaining fail-open path, and it exists because suppressing a real
       session's refresh loses data that cannot be backfilled, whereas wrongly
       fetching on a holiday costs only time.

    Args:
        day: The calendar date to classify, in SET's local (Bangkok) terms.

    Returns:
        ``(True, "<description>")`` when *day* is a known SET closure;
        ``(False, "")`` otherwise, including on any unresolvable failure.
    """
    try:
        holidays = await fetch_set_holidays(day.year)
    except CalendarUnavailableError as exc:
        fallback: dict[date, str] | None = FALLBACK_SET_HOLIDAYS.get(day.year)
        if fallback is None:
            logger.error(
                "SET holiday calendar unavailable for %s and no committed fallback covers "
                "%d — proceeding as a trading day: %s",
                day.isoformat(),
                day.year,
                exc,
            )
            return False, ""
        logger.warning(
            "SET holiday calendar unavailable for %s — resolving against the committed "
            "%d fallback (%d closures): %s",
            day.isoformat(),
            day.year,
            len(fallback),
            exc,
        )
        holidays = fallback

    description: str | None = holidays.get(day)
    if description is None:
        return False, ""
    return True, description


__all__: list[str] = [
    "CALENDAR_TIMEOUT_SECS",
    "FALLBACK_SET_HOLIDAYS",
    "CalendarUnavailableError",
    "fetch_set_holidays",
    "is_set_holiday",
]
