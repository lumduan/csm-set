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

On **2026-08-07** it served the full 20-entry calendar again — and then timed out
on the **next two** attempts within the following ten minutes. So "recovered" is
not a state this endpoint durably occupies; availability flickers on a timescale
shorter than a single working session. That is the case for keeping the fallback
permanently rather than treating it as a stopgap for one outage.

**A year can only ever be captured while it is the current one.** settfex's docs
(gotcha 1, live-verified 2026-07-27) record that every year other than the
current one returns 401 — reconfirmed here on 2026-08-06, when 2025 and 2027
failed alongside 2026. So :data:`FALLBACK_SET_HOLIDAYS` is inherently populated
one year at a time: a 2027 table cannot be built in advance and can only be
captured from 2027-01-01 onward, on a day the endpoint happens to be serving.
Until then 2027 dates take the fail-open path below.

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
allowed to be incomplete rather than padded with guesses.

That rule was **tested by outcome on 2026-08-07**, when the endpoint came back
and the whole 2026 calendar could be compared against the table built without
it: of the 14 dates admitted on the conservative rule, **14 were correct** — no
date wrong, none missing that the price panel knew, and 10 already byte-exact on
SET's official wording. The one date deliberately withheld, 2026-10-16
(``Additional special holiday *``), turned out to be **real**. Excluding it was
still right: it rested on a single unverified source, and the rule is judged on
what it protects against, not on whether a given omission happens to be safe.

Keeping the snapshot honest
--------------------------
A committed table is a snapshot, and a snapshot rots quietly. Two ways:

1. **SET adds closures mid-year** — 2026-10-16 is literally "Additional special
   holiday". One announced after the snapshot was taken is simply missing.
2. **The capture window for a year opens once**, on its first day, and is easy
   to miss.

So every *successful* fetch is compared against the committed table by
:func:`_log_table_drift`, which names the dates to promote, drop or reword. It
changes no behaviour; it only removes the need to remember. A missing year is
reported the first time the endpoint serves it, and reported again every session
until it is committed — a dated reminder gets one attempt against an endpoint
that has proven it can be unavailable for four days running.

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

#: SET closures consulted when the live calendar cannot be reached, by year.
#:
#: **2026 is complete: all 20 published closures**, captured verbatim from
#: ``get_holidays(year=2026, lang="en")`` on **2026-08-07 ~10:25 BKK**, during a
#: window when the endpoint was serving. Every date and description below is that
#: payload — none is inferred, and none is edited. Descriptions are **verbatim**,
#: including the trailing ``" *"`` on 2026-10-16, which is SET's own footnote
#: marker for an additional special closure and which settfex deliberately does
#: not strip (its ``Holiday`` model alone omits ``str_strip_whitespace``).
#:
#: Independently corroborated: the **13** entries at or before 2026-08-06 each
#: carry **no bar for any of the 211 symbols** in
#: ``data/processed/prices_latest.parquet``, and conversely the panel knows no
#: 2026 closure this table omits. That is the method that first identified the
#: four closures whose phantom gateway rows were deleted on 2026-07-31.
#:
#: **2027 is absent and cannot be added yet** — see the module docstring: the
#: endpoint serves only the current year, so a 2027 table can only be captured
#: from 2027-01-01 onward. Until then 2027 dates take the fail-open path, which
#: is loud (ERROR) by design.
FALLBACK_SET_HOLIDAYS: dict[int, dict[date, str]] = {
    2026: {
        date(2026, 1, 1): "New Year's Day",
        date(2026, 1, 2): "Additional special holiday",
        date(2026, 3, 3): "Makha Bucha Day",
        date(2026, 4, 6): "Chakri Memorial Day",
        date(2026, 4, 13): "Songkran Festival",
        date(2026, 4, 14): "Songkran Festival",
        date(2026, 4, 15): "Songkran Festival",
        date(2026, 5, 1): "National Labor Day",
        date(2026, 5, 4): "Coronation Day",
        date(2026, 6, 1): "Substitution for Visakha Bucha Day (Sunday 31st May 2026)",
        date(2026, 6, 3): "H.M. Queen Suthida Bajrasudhabimalalakshana's Birthday",
        date(2026, 7, 28): "H.M. King Maha Vajiralongkorn Phra Vajiraklaochaoyuhua's Birthday",
        date(2026, 7, 29): "Asarnha Bucha Day",
        date(2026, 8, 12): "H.M. Queen Sirikit The Queen Mother's Birthday / Mother's Day",
        date(2026, 10, 13): "H.M. King Bhumibol Adulyadej the Great Memorial Day",
        date(2026, 10, 16): "Additional special holiday *",
        date(2026, 10, 23): "H.M. King Chulalongkorn the Great Memorial Day",
        date(2026, 12, 7): (
            "Substitution for H.M. King Bhumibol Adulyadej the Great's Birthday / "
            "National Day / Father's Day (Saturday 5th December 2026)"
        ),
        date(2026, 12, 10): "Constitution Day",
        date(2026, 12, 31): "New Year's Eve",
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


def _iso_list(days: list[date]) -> str:
    """Render *days* for a log line, or ``"-"`` when empty."""
    return ", ".join(d.isoformat() for d in days) if days else "-"


def _log_table_drift(year: int, live: dict[date, str]) -> None:
    """Report how :data:`FALLBACK_SET_HOLIDAYS` compares to the live calendar.

    **Observational only — this never changes what :func:`is_set_holiday`
    returns.** It exists because the committed table is a *snapshot*, and two
    things make snapshots go stale silently:

    - **SET adds closures mid-year.** 2026-10-16 is literally "Additional
      special holiday". A closure announced after the snapshot was taken is
      absent from the table, and nothing else would say so.
    - **A year can only be captured while it is the current one** (see the
      module docstring), so the window to capture 2027 opens on 2027-01-01 and
      is easy to miss. Rather than depend on a dated reminder, the first session
      that reaches a serving endpoint says what is missing — and keeps saying it
      every session until someone commits it.

    All three outcomes are logged, including the good one, so "in sync" is
    distinguishable from "this check never ran" (an outage logs its own
    warning on the fallback path instead).

    Args:
        year: The year that was fetched.
        live: The freshly fetched calendar for *year*.
    """
    committed: dict[date, str] | None = FALLBACK_SET_HOLIDAYS.get(year)
    if committed is None:
        logger.warning(
            "no committed fallback table for %d — the live calendar publishes %d closure(s): "
            "%s. Capture them into FALLBACK_SET_HOLIDAYS while %d is the current year; the "
            "endpoint will not serve it afterwards.",
            year,
            len(live),
            _iso_list(sorted(live)),
            year,
        )
        return

    if committed == live:
        logger.info(
            "committed %d fallback table matches the live calendar (%d closures)", year, len(live)
        )
        return

    logger.warning(
        "committed %d fallback table is STALE vs the live calendar — promote: %s | drop: %s | "
        "reword: %s",
        year,
        _iso_list(sorted(set(live) - set(committed))),
        _iso_list(sorted(set(committed) - set(live))),
        _iso_list(sorted(d for d in set(live) & set(committed) if live[d] != committed[d])),
    )


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
    else:
        # Only meaningful against a live payload — the fallback cannot drift
        # from itself. Deliberately after the fetch and before the lookup, so a
        # stale table is reported even on a day that is not a closure.
        _log_table_drift(day.year, holidays)

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
