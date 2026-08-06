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
| 2 | **Phantom rows written on closed days** into `daily_performance` + `portfolio_snapshot` + `strategy_report_snapshot` | Fabricated return observations in every statistic computed off those tables | **RESOLVED 2026-08-01** — 12 rows deleted **and** the write path fixed ("no fresh bar, no gateway write"). Unattended proof lands at the next closure |
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

### Sub-finding — BANPU ~~was a ticker change~~ **RETRACTED 2026-08-01**

> **This sub-finding did not hold up and is retracted the same day it was filed.** It originally
> read: *"`SET:BANPU` had been the terminal fetch miss since 2026-07-17. settfex lists no BANPU but
> does list `BANPUU` — 'BANPU PUBLIC COMPANY LIMITED', the same company; prices are continuous across
> the rename (5.70 on 2026-05-29 → 5.75 on 2026-07-15)."*
>
> Re-querying settfex later on **2026-08-01** returns **`BANPU`** (type `S`, sector `ENERG`) and **no
> `BANPUU` at all**. Two facts settle it:
>
> - the symbol list went **702 → 701**, with `BANPUU` the only name removed;
> - the `SET:BANPUU` frame actually banked on 2026-08-01 holds **2 bars** (2026-07-15 → 07-16), not
>   the continuous history the original claim asserted. A genuine rename carries its history across.
>
> So `BANPUU` was a **transient listing artifact**, not a rename, and the "prices are continuous"
> evidence was never in the stored data — it was inferred. The canonical ticker is and remains
> `SET:BANPU`.
>
> **Consequence:** `SET:BANPU` is back in `symbols.json` but has no frame in the raw store, so it
> fails the coverage screen and is absent from the regenerated universe — which is why the
> 2026-07-31 snapshot is **210** symbols rather than 211. Re-fetching `SET:BANPU` restores it.
> **No trading impact:** BANPU/BANPUU is neither held nor in the 2026-08-03 ATO trade list.
>
> The lesson is the one this whole sweep keeps repeating: a claim about a symbol's identity has to be
> checked against the **stored frame**, not against the listing API alone. Two bars would have
> falsified it immediately.

`SET:BPP` is a different case and **still stands**: **halted, not broken.** It resolves and returns
bars ending 2026-07-16, and SET carries the last price forward (settfex's YTD close as of 07-30 is
the same 12.00). It therefore fails the 90-bar volume/coverage screen and has dropped out of the
regenerated universe, which is the correct outcome.

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

### Rows deleted 2026-08-01 — and a third affected table

The historical rows were removed on **2026-08-01** at the operator's instruction. The count grew
twice during that work: the July review recorded **2** rows; re-querying found **8** across two
tables; and auditing the third gateway table found **`strategy_report_snapshot` carries them too** —
**12 rows** in total, 4 per table on the 4 closed dates.

The arithmetic on that third table is the cleanest single confirmation of the whole defect:
`strategy_report_snapshot` began on 2026-05-22 and held **51** rows, while `equity_curve` records
**47** real sessions in the same span. 47 + 4 = 51 exactly.

**Each of the 12 was verified phantom four independent ways** before deletion — no price bar in
`prices_latest.parquet`, no `equity_curve` row, no daily log, and a `report` JSONB **byte-identical**
to the prior real session (`md5(2026-07-27) == md5(07-28) == md5(07-29)`; `md5(06-01) == md5(05-29)`;
`md5(06-03) == md5(06-02)`).

**A fifth check landed later the same day, and it is the only fully external one.** The authoritative
SET holiday calendar (`settfex` 0.15.x `get_holidays(year=2026)`) lists exactly four closures inside
the live-test window:

| Date | Official reason |
|---|---|
| 2026-06-01 | Substitution for Visakha Bucha Day (Sunday 31 May 2026) |
| 2026-06-03 | H.M. Queen Suthida Bajrasudhabimalalakshana's Birthday |
| 2026-07-28 | H.M. King Maha Vajiralongkorn Phra Vajiraklaochaoyuhua's Birthday |
| 2026-07-29 | Asarnha Bucha Day |

Those are **precisely** the four dates the deletion targeted — no more, no fewer. The arithmetic
closes as well: **64 business days (2026-05-05 → 07-31) − 4 holidays = 60 expected sessions = 60
`equity_curve` rows.** The four dates had been derived from the data alone; an outside source
agreeing on all four *and* on the total is corroboration, not a restatement.

```
                            before    after
daily_performance (csm-set)     65  ->    61
portfolio_snapshot (all)        65  ->    61
strategy_report_snapshot        51  ->    47
```

A fingerprint over every **surviving** row was captured before the delete and re-checked after —
**identical**, so nothing outside the 12 was touched. `equity_curve` stayed at 60, as it should: it
never had the phantom rows. The residual 61-vs-60 gap is `2026-05-04`, the inception day, which has a
gateway row but no NAV row.

A full `INSERT`-statement restore script for all 12 rows is at
`/home/batt/backups/2026-08-01-phantom-holiday-rows-restore.sql` (outside the repo). It was **proven
by replay** into a scratch database before the deletion, not merely written: the replayed rows
fingerprint identically to the production originals.

**Scoped to `csm-set` deliberately.** `cash-and-carry-set-tfex` has the **same defect** on
2026-07-28/29 (2 rows, `total_value = 0`) and those rows were **left in place** — that strategy
belongs to another session. Flagged, not acted on.

**The write path was fixed the same day** — see Follow-up #1. Deleting rows alone would have been a
cleanup, not a fix; the scheduler would have written the same carry-forward on the next closure.

**The check that closes this out is unattended and dated.** The next SET closure is
**2026-08-12** — no longer a "candidate": confirmed on 2026-08-01 against the authoritative SET
holiday calendar (`settfex` 0.15.x `get_holidays(year=2026)`, run ephemerally), which lists it as
H.M. Queen Sirikit's Birthday / Mother's Day and shows **no other August closure**. That is the first
time the guard runs without anyone watching. Expected on that date:

- **no new rows** in `daily_performance`, `portfolio_snapshot` or `strategy_report_snapshot`
  (counts stay wherever the intervening sessions leave them, with no row *dated 2026-08-12*);
- a **WARNING** in the `csm-set-csm-1` container log reading
  `skipping gateway daily-report POST — the latest price bar is <prev session>, not today
  (2026-08-12) … consistent with a market closure`.

If a row dated 2026-08-12 appears, the guard did not deploy — check that the image was **rebuilt**,
not just the pin bumped: `src/` is baked into the image, not mounted.

> ⚠️ **AMENDED 2026-08-06 — the second bullet will NOT be observed, and its absence is not a
> failure.** `csm.data.calendar` gained a committed fallback holiday table the same evening (see the
> 2026-08-06 daily log, Risk Note 9), because the settfex endpoint had 401'd on four consecutive
> refreshes and a live probe found it 401ing for 2025, 2026 and 2027 alike. 2026-08-12 is in that
> table, so `daily_refresh` now **declines at Phase 0 and never fetches**. The revised expectation:
>
> - **first bullet unchanged** — still no row dated 2026-08-12 anywhere. This remains the outcome
>   that matters and the one to check.
> - **instead of the no-fresh-bar WARNING**, expect an INFO
>   `daily refresh: 2026-08-12 is a SET holiday (H.M. Queen Sirikit …) — skipping the fetch entirely`,
>   a WARNING that the calendar was resolved from the **committed fallback**, a `last_refresh.json`
>   carrying `"skipped_reason": "set_holiday"`, and a run lasting **seconds rather than ~6 minutes**.
>
> **The cost of that is stated rather than hidden: 2026-08-12 no longer exercises the no-fresh-bar
> guard**, because the early skip means the write path is never reached. That guard is not
> unverified — `tests/unit/adapters/test_hooks.py::test_skips_post_when_latest_bar_is_not_today`
> covers it — but its *unattended* proof now moves to the first closure the fallback table does not
> list (Q4 2026 is deliberately unlisted; see `FALLBACK_SET_HOLIDAYS`). If you want the original
> proof on 2026-08-12 instead, remove that one date from the table before the session.

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

1. ~~**Teach the gateway write path a market calendar.**~~ ✅ **DONE 2026-08-01** — implemented as
   **"no fresh bar, no gateway write"** in `run_post_refresh_hook`, which is what `equity_curve`
   already did right. Two changes, because there were two separable defects:
   - **The date now comes from the data.** `LivePortfolioMetrics.snapshot_time` — the last price bar
     the metrics were computed against — replaces the wall-clock `datetime.now()`. That field already
     existed and was simply being ignored; the wall clock was the whole bug.
   - **The POST is skipped** when that bar's **Bangkok** date is not today's. Bangkok, not UTC: the
     18:00 BKK cron is 11:00 UTC so the two agree by luck, and disagree for any run after 07:00 BKK
     the next morning.

   **No calendar file, deliberately.** The pinned `settfex` **0.1.0 ships no holiday module at all**
   (`modules: ['services', 'utils']`) and `get_holidays()` 401s for 2026. A hand-maintained YAML
   would reintroduce this exact failure the first time a closure was missing from it. "Did a bar
   arrive for today?" is ground truth, needs no maintenance, and also catches
   market-traded-but-our-fetch-broke — which must skip the write too, so the inability to distinguish
   the two never changes behaviour. The log line classifies the cause from the refresh summary
   (`failures == 0` reads as a closure; `failures > 0` as a data problem) for the operator's benefit.

   **One trap found while building it.** Stamping the payload with the raw bar timestamp would have
   written `09:55+07:00` → **02:55 UTC**, while all 61 existing rows are `00:00:00 UTC` and the unique
   index is `(time, strategy_id)` — so every future row would have *inserted* rather than upserted.
   That is precisely the mechanism that took `equity_curve` to 97 rows across 60 dates. Only the
   **date** is data-derived; the stamp stays UTC midnight. A test pins both halves.

   Verified by replaying the hook against the **real** `prices_latest` truncated to 2026-07-27 — the
   exact panel that existed on the 2026-07-28 closure: **0 POSTs**. Against a panel whose last bar is
   today: **1 POST**, stamped `<today>T00:00:00+00:00`.
2. ~~**Backfill-delete the existing phantom rows.**~~ ✅ **DONE 2026-08-01** — 12 rows (not 8; the
   third gateway table was found during the work), backed up with a replay-verified restore script,
   deleted in one transaction, survivors fingerprint-identical. Note this was done **before** #1, so
   the series is clean *today* but will re-dirty on the next market closure.
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
