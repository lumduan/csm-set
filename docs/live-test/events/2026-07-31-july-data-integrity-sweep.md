# Event Report — July data-integrity sweep: truncated universe, phantom holiday rows, duplicated equity curve

**Date surfaced:** 2026-07-31 (July month-end review)
**Date swept / filed:** 2026-08-01
**Category:** Data quality — three independent defects found in one month-end pass
**Severity:** Medium-High (one changed a published trade list; one corrupts every statistic read from the gateway tables; none caused capital loss)
**Status:** 2 of 3 resolved · **1 open** (phantom holiday rows)

---

## Summary

The July month-end review surfaced three data-integrity defects and deliberately deferred filing them
so the review itself could ship. This is that filing. Two have since been fixed; one is open and is
the most consequential of the three for anything that reads the gateway tables.

| # | Defect | Blast radius | Status |
|---|---|---|---|
| 1 | **Universe silently truncated** to 136 of 211 symbols for three months | Changed the published August trade list | **RESOLVED** 2026-08-01 |
| 2 | **Phantom rows written on closed days** into `daily_performance` + `portfolio_snapshot` | Fabricated return observations in every statistic computed off those tables | **OPEN** |
| 3 | **`equity_curve` duplicated** — 97 rows across 60 dates | None on values; every date since the restart carried a duplicate | **RESOLVED** — `b76d709` |

Defect 2 turned out to be **broader than the July review recorded**: it is not a July one-off. See
below.

---

## 1 — The universe was truncated to ~69% of its intended size (RESOLVED)

`data/processed/universe_latest.parquet` held **136 symbols**. Rebuilding the *same* 2026-04-30
snapshot against either the old or the refreshed raw store yields **197**. The current regenerated
universe holds **211**, and the August ranking ran on **204** of them.

**Root cause.** The snapshot was built on **2026-05-04**, while `fetch_history.py` was still
progressively filling the raw store. That script skips symbols already present, so the store filled
across successive runs — and the universe builder captured a partially-filled store as though it were
complete. Nothing failed; the snapshot was internally consistent and simply smaller than intended.

**Impact — this one reached a published recommendation.** The truncated universe spanned the July 1
rebalance and the *originally published* August plan. Regenerating it changed the August trade list
from a **1-out / 1-in** (SELL DELTA, BUY KKP) to a **2-out / 2-in** (SELL DELTA + PTTGC, BUY SMT +
MGC): correcting the universe surfaced a challenger stronger than anything the truncated set
contained, which evicted PTTGC on the buffer rule. The amendment is recorded in
[`monthly/2026-07.md`](../monthly/2026-07.md) (Rebalance section) and commit `c33482c`.

**Fix.** Regenerated end-to-end on 2026-08-01: symbol list refreshed from settfex (703 → **702**;
`+BANPUU +TBSP` / `−BANPU −PTECH −SVI`), the full raw store re-fetched (693 of 703; the 10 failures
are `&`/`-` tickers tvkit's symbol normalizer cannot parse, and were never in the old store either),
and snapshots rebuilt for 2026-05-29 / 06-30 / 07-31. `scripts/fetch_history.py` gained a
`--refresh` flag (`e5218f1`) so an existing store can be brought current instead of only ever being
appended to — the absence of that flag is why the store went stale in the first place.

**Deliberately not done:** snapshots before 2026-05-29 were **not** rebuilt. The current symbol list
no longer contains delisted names (BANPU, PTECH, SVI), so rebuilding historical snapshots would drop
those names from the past and inject **survivorship bias** into any point-in-time backtest.

### Sub-finding — BANPU was a ticker change, not a fetch failure

`SET:BANPU` had been the terminal fetch miss since 2026-07-17. settfex lists no BANPU but does list
**`BANPUU` — "BANPU PUBLIC COMPANY LIMITED"**, the same company; prices are continuous across the
rename (5.70 on 2026-05-29 → 5.75 on 2026-07-15). Corrected in both the engine store and the
universe.

`SET:BPP` is a different case: **halted, not broken.** It resolves and returns bars ending
2026-07-16, and SET carries the last price forward (settfex's YTD close as of 07-30 is the same
12.00). It therefore fails the 90-bar volume/coverage screen and has dropped out of the regenerated
universe, which is the correct outcome.

**Still open:** the **false-liveness retry defect** in `daily_refresh` — an all-NaN column reads as
"recovered", so a symbol that never actually returned data is counted as a success.

---

## 2 — Phantom rows on closed days (OPEN — and broader than first recorded)

The scheduler holds **no market calendar**. It fires Mon–Fri on `CSM_REFRESH_CRON` regardless of
whether SET traded, and on a closed day it writes a row that is an **exact carry-forward of the
previous real session — both `total_value` and `daily_return`.**

The July review recorded this as "two phantom holiday rows". Re-querying on 2026-08-01 shows the
defect has fired on **every market closure since inception** — four dates, **eight rows** across the
two gateway tables:

```
     d      | ret_pct | total_value
------------+---------+-------------
 2026-05-29 | -2.0410 |  1003342.71     ← real session
 2026-06-01 | -2.0410 |  1003342.71     ← PHANTOM (SET holiday)
 2026-06-02 |  1.4278 |  1014485.27     ← real session
 2026-06-03 |  1.4278 |  1014485.27     ← PHANTOM (SET holiday)
 ...
 2026-07-27 | -2.5652 |  1217741.35     ← real session
 2026-07-28 | -2.5652 |  1217741.35     ← PHANTOM (market closure)
 2026-07-29 | -2.5652 |  1217741.35     ← PHANTOM (market closure)
```

`portfolio_snapshot` carries the matching four rows (`2026-06-01`, `2026-06-03`, `2026-07-28`,
`2026-07-29`).

**Why it is worse than a duplicate.** A repeated `total_value` is harmless — it is genuinely still
the last known NAV. The damage is the repeated **`daily_return`**: `−2.5652%` appears **three times**
for a single real session, and `−2.0410%` / `+1.4278%` twice each. Any mean, σ, Sharpe or
hit-rate computed off `daily_performance` silently ingests fabricated observations. For July alone,
including them would inject two spurious −2.57% sessions.

**`db_csm_set.equity_curve` behaved correctly and wrote nothing on any of the four days** — 60 rows
for 60 real sessions. That disagreement between the two write paths is the cleanest evidence that
the gateway path, not the market data, is at fault.

**Current mitigation is manual and does not scale.** Both the June and July reviews computed their
statistics by excluding these rows by hand. That works only for as long as a human remembers.

**Not fixed here, deliberately.** Deleting the rows is a mutation of a live cross-strategy table and
is out of scope for a documentation pass. The durable fix is a market-calendar check before the
gateway write — see Follow-up.

---

## 3 — `equity_curve` duplicated: 97 rows across 60 dates (RESOLVED)

On 2026-07-31 the table went from 76 rows to **97** in a single session: 21 new rows stamped
`02:55 UTC` spanning the whole 2026-07-01 → 07-31 window, inserted *alongside* the existing `03:00`
rows rather than upserted onto them.

**Root cause — the vendor's bar time-of-day moved, and the upsert key was the full timestamp.**
`_reconstruct_live_equity` (`src/csm/adapters/hooks.py`) returned a series indexed by the *price
bar's* timestamp, tz-converted to UTC but never date-normalized, while `write_equity_curve` upserts
on `(time, strategy_id)`. So each time the vendor's bar time changed, every key in the window changed
and the entire window was **inserted** instead of updated:

| Bar time (BKK) | Stored stamp | Rows | Dates |
|---|---|---:|---|
| 09:00 | 02:00 UTC | 56 | 2026-05-05 → 07-23 |
| 10:00 | 03:00 UTC | 20 | 2026-07-01 → 07-30 |
| 09:55 | 02:55 UTC | 21 | 2026-07-01 → 07-31 |

**Correcting the July review's diagnosis.** That review stated *"the csm-set container is ruled
out … no equity write in its logs."* That reasoning was unsound: `write_equity_curve` logs at
`DEBUG`, and the container runs at `INFO`, so its absence from the logs proved nothing. **The
container was the writer.** The sibling serializer `_series_to_equity_curve`
(`src/csm/adapters/payload.py`) had documented the intended "at most one point per UTC date"
contract all along — only the DB write path never got it.

**Impact on reported figures: none.** Values at matching dates were identical, so NAV and every
published statistic were unaffected. The damage was structural — and it was *silently shrinking the
API's history window*, because `read_equity_curve(days)` was mapping `days` straight to a row
`LIMIT`, so each duplicate consumed a slot that should have held an older day.

**Fix.** Date-normalize the series in the producer (`b76d709`), so the upsert key is the calendar
day. Migrated the table in one transaction — DELETE + INSERT of a collapsed set, since a plain
`UPDATE` would violate the `(time, strategy_id)` unique index — **97 → 60 rows**, verified
value-for-value against a pre-migration fingerprint. Re-verified 2026-08-01: **60 rows / 60 distinct
dates / 0 rows off midnight.** The related `days`-means-rows defect was fixed separately in
`26eebbe`.

---

## Impact

**No capital impact from any of the three.** No trade was executed on bad data: the universe defect
was caught before the 2026-08-03 ATO, and defects 2 and 3 affect stored statistics rather than
signals.

The one that reached a decision is **#1** — the originally published August trade list was wrong and
had to be amended. The one that will keep costing is **#2**: until the scheduler learns the market
calendar, every review must remember to exclude the phantom rows by hand, and any external consumer
of `daily_performance` has no way to know they should.

---

## Follow-up

1. **Teach the gateway write path a market calendar** *(open, highest value)*. The scheduler should
   not write a `daily_performance` / `portfolio_snapshot` row on a day SET did not trade. Note that
   `settfex.get_holidays()` returns **HTTP 401 for 2026** and csm-set's pinned `settfex` (0.1.0)
   ships no holiday module, so the calendar source is itself an open question — the cheapest correct
   guard is "no new price bar ⇒ no write", which is exactly what `equity_curve` already does right.
2. **Backfill-delete the 8 existing phantom rows** once #1 is in place, so the historical series is
   clean. Requires an explicit operator decision — it mutates a live cross-strategy table.
3. **Fix the false-liveness retry defect** in `daily_refresh` — an all-NaN column must not count as a
   recovered symbol.
4. **Close the ranking-pipeline gap** — still open, now the third rebalance running. Cross-referenced
   rather than restated here; see
   [`2026-06-30-rebalance-systematic-and-pipeline-gap.md`](2026-06-30-rebalance-systematic-and-pipeline-gap.md)
   follow-up #1. It matters because `residual_momentum` is the only signal that passed the historical
   ICIR > 0.15 gate and it is the one not being computed.
5. **Add a universe-size regression check** — a snapshot that drops materially below the prior one
   should fail loudly rather than be written.

---

## Related

- [`monthly/2026-07.md`](../monthly/2026-07.md) — the review that surfaced all three; its Notes
  section is the source for items 1–3 and its Rebalance section carries the amended trade list.
- [`2026-08-01-price-adjustment-never-applied.md`](2026-08-01-price-adjustment-never-applied.md) —
  a fourth defect found in the same pass, filed separately because it predates July and affects every
  factor ever computed.
- [`2026-08-01-portfolio-snapshot-wiped-by-test-fixture.md`](2026-08-01-portfolio-snapshot-wiped-by-test-fixture.md)
  — the `portfolio_snapshot` rows discussed here were deleted and restored on 2026-08-01; the restore
  faithfully reproduced the phantom rows, which is why they still appear above.
- [`2026-06-30-rebalance-systematic-and-pipeline-gap.md`](2026-06-30-rebalance-systematic-and-pipeline-gap.md)
  — the still-open ranking-pipeline gap.
- Commits: `c33482c` (universe amendment) · `e5218f1` (`--refresh`) · `b76d709` (equity
  normalization) · `26eebbe` (`days` means days).
