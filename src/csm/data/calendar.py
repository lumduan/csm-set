"""SET trading-calendar lookups.

Wraps settfex's official SET holiday calendar (``settfex>=0.15``, which is why
that floor is load-bearing — the module does not exist below it) behind three
functions:

- :func:`fetch_set_holidays` — strict. Raises :class:`CalendarUnavailableError`
  when the calendar cannot be obtained.
- :func:`capture_set_holidays` — the **poller** entry point. Tries the endpoint
  once and banks a success to :data:`HOLIDAY_CACHE_PATH`. Never raises.
- :func:`is_set_holiday` — resolves "should we treat this day as a market
  closure?" against the **banked cache**, then :data:`FALLBACK_SET_HOLIDAYS`,
  and only fails open when neither can answer. **Does no network I/O.**

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
current one returns 401. So :data:`FALLBACK_SET_HOLIDAYS` is inherently populated
one year at a time: a 2027 table cannot be built in advance and can only be
captured from 2027-01-01 onward, on a day the endpoint happens to be serving.
The poller closes that by construction — on 2027-01-01 "the current year"
becomes 2027 and it simply starts trying, dozens of times a day, with no dated
reminder to miss.

.. warning::
    **The year-scoping claim is not what makes it 401 today, and this docstring
    used to imply it was.** The 2026-08-06 probe that found 2025, 2026 and 2027
    all failing was read as evidence about *years*; the 2026-08-25 investigation
    showed the simpler cause — the origin was down for every year at once. Do
    not diagnose a 401 as "wrong year" without a same-moment control.

Why it fails, measured 2026-08-25 — NOT "transiently under load"
----------------------------------------------------------------
settfex's error string says the API "returns 401 both for years it does not
serve … and transiently under load". The second half is wrong, and it misled
this module for three weeks. What is actually happening:

- **The 401 is the origin, not the WAF.** Imperva answers a blocked request with
  **403** and an ~880-byte body; the holiday endpoint returns a bare **401 with
  an empty body**. A same-second control against ``/api/set/index/list``
  returned **200** on every attempt while the holiday endpoint returned 401.
- **It is not us.** Ruled out by direct probe: source IP (the AWS node in a
  different region got the identical 401), cookies (a bare ``curl`` with none
  behaved the same), TLS fingerprint, ``Referer``, ``lang``, and year.
- **It only *looks* intermittent because successes are edge-cached.** A 200
  carries ``cache-control: max-age=60, public``; a 401 carries no
  ``cache-control`` at all. So one origin success is served from Imperva's cache
  to everyone for the next 60 s. A single daily request therefore succeeds only
  if some *other* client got a 200 into that cache in the preceding minute.
- **Measured duty cycle: 0 × 200 in 24 probes spaced 30 s apart over 12 minutes**,
  with the control returning 200 throughout. Observed origin success rate was
  ~1 in 38 attempts (~2.6 %).

Why a poller, and not a longer retry
------------------------------------
The obvious fix — retry harder — does not work here, for two independent reasons:

1. **The budget cannot be widened where it was.** settfex retries 4 times over
   ~7 s (``max_retries=3``, ``retry_delay=1.0`` → 1 + 2 + 4), and
   :data:`CALENDAR_TIMEOUT_SECS` caps the whole lookup at 15 s. Widening it to
   match an outage measured in *hours* would put minutes onto the daily
   refresh's critical path, to buy a lottery ticket.
2. **Attempts are worth more spread out than bunched.** At ~2.6 % per attempt,
   4 attempts inside 7 s is ~10 % — which is roughly the historical hit rate
   (2 of the 9 sessions 2026-08-13 → 08-25). The *same* 4 attempts spread across
   a day sample four independent 60-second cache windows instead of one.

So the network attempt moved **off** the critical path entirely.
:func:`capture_set_holidays` runs on its own schedule, banks any success to
:data:`HOLIDAY_CACHE_PATH`, and :func:`is_set_holiday` reads local state only.
At a 30-minute interval that is ~48 attempts/day against ~4, and the refresh
pays **0 s** instead of ~7 s.

⚠️ **The poller is silent when it fails, and that is deliberate** — 48 failures a
day would bury the one line that matters. Calendar health surfaces once per day
instead, on the ``is_set_holiday`` line that names which source answered and
when it was captured. **If that line stops advancing its capture stamp, the
endpoint has been down since it.**

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
import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from csm.data.exceptions import DataError

logger: logging.Logger = logging.getLogger(__name__)

#: Bound on the calendar lookup. A hung request must not stall the daily
#: refresh; on timeout the caller falls back to the committed table.
CALENDAR_TIMEOUT_SECS: float = 15.0

#: Where :func:`capture_set_holidays` banks a successful live payload.
#:
#: Under ``results/.tmp/``, which is gitignored (``.gitignore:66``) and mounted
#: read-write in the private overlay — the same directory ``last_refresh.json``
#: already uses. The file is runtime state, not a committed artifact: it is a
#: *cache*, and :data:`FALLBACK_SET_HOLIDAYS` remains the committed source of
#: truth that survives losing it.
HOLIDAY_CACHE_PATH: Final[Path] = Path("results/.tmp/set_holidays.json")

#: Schema version for the cache file. Bumped only on an incompatible change;
#: a file carrying any other value is ignored rather than guessed at.
_CACHE_SCHEMA: Final[int] = 1

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


def _parse_cached_year(year_key: str, raw: Any) -> tuple[int, dict[date, str]] | None:
    """Validate one ``{"2026": {"2026-01-01": "..."}}`` entry, or return ``None``.

    **Validation is deliberately strict, and the asymmetry from the module
    docstring governs which way it errs.** A cache entry that wrongly says a
    date *is* a closure suppresses a real session's refresh — the one outcome
    this module exists to prevent — so anything malformed is dropped entirely
    rather than partially salvaged. Dropping is safe: the caller falls through
    to :data:`FALLBACK_SET_HOLIDAYS`, which is exactly the pre-cache behaviour.

    An **empty** year map is rejected too. A real SET year publishes ~20
    closures, so ``{}`` is a failed capture rather than a year with no
    holidays — and accepting it would silently mask every closure in that year.
    """
    try:
        year = int(year_key)
    except (TypeError, ValueError):
        return None

    if not isinstance(raw, dict) or not raw:
        return None

    parsed: dict[date, str] = {}
    for iso, description in raw.items():
        if not isinstance(iso, str) or not isinstance(description, str) or not description.strip():
            return None
        try:
            day = date.fromisoformat(iso)
        except ValueError:
            return None
        # A date filed under the wrong year means the file was hand-edited or
        # written by a different schema; neither is safe to interpret.
        if day.year != year:
            return None
        parsed[day] = description

    return year, parsed


def read_holiday_cache(path: Path | None = None) -> dict[int, dict[date, str]]:
    """Return the banked calendar by year. **Never raises.**

    A missing, unreadable, malformed or schema-mismatched file yields ``{}`` —
    the caller then behaves exactly as it did before the cache existed. This is
    read on the daily refresh's critical path, so it must not be able to fail
    the run.
    """
    path = path or HOLIDAY_CACHE_PATH
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("holiday cache at %s is unreadable — ignoring it: %s", path, exc)
        return {}

    if not isinstance(payload, dict) or payload.get("schema") != _CACHE_SCHEMA:
        logger.warning(
            "holiday cache at %s has schema %r, expected %d — ignoring it",
            path,
            payload.get("schema") if isinstance(payload, dict) else None,
            _CACHE_SCHEMA,
        )
        return {}

    years: Any = payload.get("years")
    if not isinstance(years, dict):
        logger.warning("holiday cache at %s has no 'years' mapping — ignoring it", path)
        return {}

    out: dict[int, dict[date, str]] = {}
    for year_key, raw in years.items():
        entry = _parse_cached_year(year_key, raw)
        if entry is None:
            logger.warning(
                "holiday cache at %s has a malformed entry for %r — dropping that year",
                path,
                year_key,
            )
            continue
        out[entry[0]] = entry[1]
    return out


def cache_captured_at(path: Path | None = None) -> str | None:
    """Return the cache's ``captured_at`` stamp, or ``None``. Never raises.

    Reported once per day by :func:`is_set_holiday` so the age of the banked
    calendar is visible without reading the file — a cache that silently stopped
    updating months ago would otherwise look identical to a fresh one.
    """
    path = path or HOLIDAY_CACHE_PATH
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stamp = payload.get("captured_at") if isinstance(payload, dict) else None
    return stamp if isinstance(stamp, str) else None


def write_holiday_cache(year: int, holidays: dict[date, str], path: Path | None = None) -> None:
    """Merge *holidays* for *year* into the cache at *path*, atomically.

    Other years already banked are preserved, so a 2026 capture never destroys a
    2027 one (and vice versa at the year boundary — see the module docstring on
    why a year can only ever be captured while it is the current one).

    The write is ``tempfile`` + :func:`os.replace` so a crash mid-write cannot
    leave a truncated file that the next read would have to interpret.
    """
    path = path or HOLIDAY_CACHE_PATH
    merged: dict[int, dict[date, str]] = read_holiday_cache(path)
    merged[year] = holidays

    payload: dict[str, Any] = {
        "schema": _CACHE_SCHEMA,
        "captured_at": datetime.now(tz=UTC).isoformat(),
        "years": {
            str(y): {d.isoformat(): desc for d, desc in sorted(days.items())}
            for y, days in sorted(merged.items())
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".set_holidays-", suffix=".json"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        # Leave no partial file behind on any failure, including cancellation.
        Path(tmp_name).unlink(missing_ok=True)
        raise


@contextmanager
def _settfex_logging_muted() -> Iterator[None]:
    """Silence settfex's own loguru output for the duration of one poll.

    ⚠️ **Without this the poller is not actually quiet, and the whole logging
    design collapses.** ``settfex`` keeps its *own* loguru logger and emits an
    ``ERROR`` from ``_fetch_with_retry`` on every exhausted fetch — independent
    of this module's ``logging`` calls. Muting *our* line while settfex emits
    its own would put ~48 ERROR lines/day into the container log, which is
    exactly the noise the poller exists to remove. Caught by an end-to-end smoke
    test on 2026-08-25, after the unit tests had (correctly, and uselessly)
    confirmed that *our* logger stayed silent.

    Scope is deliberately narrow — the mute lasts only for the wrapped call.
    ``logger.disable`` is process-global, so this is safe here only because
    ``csm.data.calendar`` is the sole settfex consumer in this codebase and the
    poll job runs with ``max_instances=1``. A concurrent *direct* call to
    :func:`fetch_set_holidays` could have its settfex ERROR swallowed; the cost
    is one suppressed log line, never a wrong answer.

    Imported lazily, mirroring :func:`fetch_set_holidays` — loguru reaches us
    only as a settfex dependency, and module import stays cheap.
    """
    from loguru import logger as _loguru  # noqa: PLC0415

    _loguru.disable("settfex")
    try:
        yield
    finally:
        _loguru.enable("settfex")


async def capture_set_holidays(year: int, path: Path | None = None) -> bool:
    """Try the live endpoint once and bank the result. **Never raises.**

    This is the *only* network path the calendar now takes, and it is
    deliberately off the daily refresh's critical path — see the module
    docstring's "Why a poller, and not a longer retry" section.

    Returns:
        ``True`` if the endpoint served and the cache was written, else ``False``.
    """
    path = path or HOLIDAY_CACHE_PATH
    with _settfex_logging_muted():
        try:
            live = await fetch_set_holidays(year)
        except CalendarUnavailableError as exc:
            # DEBUG, not WARNING: the poller runs dozens of times a day against an
            # endpoint whose normal state is down. Logging each failure would emit
            # ~48 lines/day and bury the one line that matters. Calendar health is
            # reported once per day instead, by is_set_holiday.
            logger.debug("holiday poll for %d found the endpoint down: %s", year, exc)
            return False

    if not live:
        # A 200 carrying an empty array is not a usable capture; banking it
        # would mask every closure in the year (see _parse_cached_year).
        logger.warning("holiday poll for %d returned an EMPTY calendar — not banking it", year)
        return False

    previous: dict[date, str] | None = read_holiday_cache(path).get(year)
    try:
        write_holiday_cache(year, live, path)
    except OSError as exc:
        logger.warning("holiday poll for %d could not write the cache at %s: %s", year, path, exc)
        return False

    if previous is None:
        logger.info(
            "holiday poll BANKED %d for the first time — %d closure(s) now cached at %s",
            year,
            len(live),
            path,
        )
        _log_table_drift(year, live)
    elif previous != live:
        logger.warning(
            "holiday poll: the live %d calendar CHANGED since the last capture — added: %s | "
            "removed: %s | reworded: %s",
            year,
            _iso_list(sorted(set(live) - set(previous))),
            _iso_list(sorted(set(previous) - set(live))),
            _iso_list(sorted(d for d in set(live) & set(previous) if live[d] != previous[d])),
        )
        _log_table_drift(year, live)
    else:
        # The overwhelmingly common success case. Quiet by construction.
        logger.debug("holiday poll refreshed %d unchanged (%d closures)", year, len(live))
    return True


async def is_set_holiday(day: date, cache_path: Path | None = None) -> tuple[bool, str]:
    """Return ``(is_holiday, description)`` for *day*. Never raises, never blocks.

    Resolution order:

    1. The **banked cache** at *cache_path* for ``day.year`` — a live payload
       captured by :func:`capture_set_holidays`, and the only source that can
       carry a closure the committed table has never seen.
    2. :data:`FALLBACK_SET_HOLIDAYS` for ``day.year`` — a definite answer while
       the endpoint has never served, which since 2026-08-04 is the normal state.
    3. Neither available ⇒ ``(False, "")``, logged at ERROR. This is the only
       remaining fail-open path, and it exists because suppressing a real
       session's refresh loses data that cannot be backfilled, whereas wrongly
       fetching on a holiday costs only time.

    ⚠️ **This function no longer touches the network** (changed 2026-08-25). It
    used to call :func:`fetch_set_holidays` inline, which cost a fixed ~7 s of
    settfex retries on every run for a ~10 % chance of a fresh answer. The
    network attempt now belongs to the poller, so this resolves from local state
    in microseconds and cannot stall or fail the refresh. See the module
    docstring's "Why a poller, and not a longer retry".

    Args:
        day: The calendar date to classify, in SET's local (Bangkok) terms.
        cache_path: Location of the banked calendar. Overridable for tests.

    Returns:
        ``(True, "<description>")`` when *day* is a known SET closure;
        ``(False, "")`` otherwise, including on any unresolvable failure.
    """
    cache_path = cache_path or HOLIDAY_CACHE_PATH
    cached: dict[date, str] | None = read_holiday_cache(cache_path).get(day.year)
    holidays: dict[date, str]

    if cached is not None:
        # Once per day, on the refresh — the single line that makes calendar
        # health visible without reading the file. The poller itself is silent
        # on failure by design, so if this line ever stops moving forward, the
        # endpoint has been down since the stamp it reports.
        logger.info(
            "SET holiday calendar for %s resolved from the banked cache (%d closures, captured %s)",
            day.isoformat(),
            len(cached),
            cache_captured_at(cache_path) or "at an unknown time",
        )
        holidays = cached
        # Only meaningful against a live payload — the fallback cannot drift
        # from itself. Deliberately before the lookup, so a stale table is
        # reported even on a day that is not a closure.
        _log_table_drift(day.year, cached)
    else:
        fallback: dict[date, str] | None = FALLBACK_SET_HOLIDAYS.get(day.year)
        if fallback is None:
            logger.error(
                "SET holiday calendar for %s is neither banked nor covered by a committed "
                "fallback for %d — proceeding as a trading day",
                day.isoformat(),
                day.year,
            )
            return False, ""
        logger.warning(
            "SET holiday calendar for %s is not banked — resolving against the committed "
            "%d fallback (%d closures). The endpoint has not served since this container "
            "started polling.",
            day.isoformat(),
            day.year,
            len(fallback),
        )
        holidays = fallback

    description: str | None = holidays.get(day)
    if description is None:
        return False, ""
    return True, description


__all__: list[str] = [
    "CALENDAR_TIMEOUT_SECS",
    "FALLBACK_SET_HOLIDAYS",
    "HOLIDAY_CACHE_PATH",
    "CalendarUnavailableError",
    "cache_captured_at",
    "capture_set_holidays",
    "fetch_set_holidays",
    "is_set_holiday",
    "read_holiday_cache",
    "write_holiday_cache",
]
