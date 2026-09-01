# Event Report — A second daily bar per session silently zeroed 7 of 10 holdings and destroyed a banked NAV row

**Date:** 2026-09-01
**Category:** Data-integrity defect — silent NAV corruption (live figures wrong; source data intact)
**Severity:** High (the platform's headline NAV read 373,561.70 against a true 1,273,881.70 — a
−71.6% error — and one historical `equity_curve` row was overwritten)
**Status:** **OPEN** — the defect is characterised and the true figures are recovered, but **nothing
has been fixed and nothing has been repaired.** The corruption re-runs at every 18:00 BKK refresh.

---

## Summary

The price vendor began emitting a **second daily bar stamped 10:00 BKK** alongside the long-standing
09:55 one. It first appeared on **2026-08-31** (16 of 211 symbols) and widened on **2026-09-01**
(41 of 211). All 948 preceding bars in `prices_latest.parquet` carry a single 09:55 stamp.

`csm.live.portfolio.compute_live_portfolio_metrics` prices the book off the panel's **last row**.
That row is now the sparse 10:00 bar, so on 2026-09-01 the NAV was computed from the **three** held
names that happened to have a 10:00 print — HANA, GUNKUL and FORTH — with the other seven silently
contributing **zero market value**.

Two consequences, one of which is worse than the other:

1. The 2026-09-01 NAV was written as **373,561.70** instead of **1,273,881.70**.
2. The daily refresh reprices `[entry_date, today]` and UPSERTs every row, so the **2026-08-31
   `equity_curve` row was retroactively overwritten** — from a correct 1,317,530.70 to **303,397.70**,
   priced off *two* names. A banked historical figure was destroyed by a later run.

**No source data was lost.** Both bars are present in the parquet and they are **complementary, not
conflicting**, so the true session is fully recoverable. The 2026-09-01 daily log is published on
that reconstructed basis.

---

## How it happened

### The vendor change

| Date | 09:55 bar | 10:00 bar | Held names on each |
|---|---:|---:|---|
| 2026-08-27 and all 948 earlier bars | 211 / 211 | — | 10 / 10 |
| 2026-08-28 | 211 / 211 | — | 10 / 10 |
| 2026-08-31 | 211 / 211 | **16 / 211** | 10 / 10 · **2 / 10** (HANA, GUNKUL) |
| 2026-09-01 | **170 / 211** | **41 / 211** | **7 / 10** · **3 / 10** (HANA, GUNKUL, FORTH) |

On 2026-09-01 the two rows are **disjoint and exhaustive**: 170 + 41 = 211 universe-wide, and
7 + 3 = 10 across the held book, with no symbol appearing on both. On 2026-08-31, where two held
names *did* appear on both, the values are **identical** (HANA 47.25, GUNKUL 5.15) — confirming the
10:00 row is the same session's daily bar under a different stamp, not a distinct observation.

The refresh runs at 18:00 BKK, well after the 16:30 close, so both stamps are completed daily bars.
The timestamp is a vendor artifact and has wandered before — this log series already records
09:00 → 10:00 → 09:55. What is new is **two stamps coexisting within one session**.

### Three faults, all in one function

`src/csm/live/portfolio.py`, `compute_live_portfolio_metrics`:

| # | Fault | Line(s) |
|---|---|---|
| 1 | The panel is row-per-**bar**, not row-per-**day**. `nav.iloc[-1]` therefore reads the sparse 10:00 bar rather than the session. | `188`, `203` |
| 2 | `panel.mul(shares, axis=1).sum(axis=1)` is pandas-default `skipna=True`, so an **unpriced holding contributes zero market value** instead of propagating NaN. | `200` |
| 3 | The `missing` guard checks **column presence**, never **value presence**. All ten columns exist; their values are NaN. The guard passes. | `177-180` |

Fault 1 alone would be visible — a NaN NAV is obviously wrong. **Fault 2 is what made it silent**: it
converts a missing price into a confident, plausible, wrong number. Fault 3 is the guard that should
have caught it and could not, because it was written to catch a *schema* problem and this is a *data*
problem.

### The refresh's own success criteria cannot see it

```
Completed daily refresh  duration_seconds=132.916  symbol_count=211  failures=0
                         held_symbols_fetched=10   held_symbols_failed=0
                         retry_attempts_used=0     index_fetched=true
```

Every receipt is green, and every receipt is **true**. All 211 symbols were fetched; all 10 held
names were fetched. The refresh counts **fetch failures**, and nothing failed to fetch — the bars
arrived under an unexpected stamp. A completeness check on the *fetch* cannot see a defect in the
*panel shape* it produces.

---

## Detection

Not by any alarm. The 2026-09-01 daily-log run read `db_gateway.daily_performance` in the ordinary
course of step 3 and found `total_value = 373,561.70` against the prior session's 1,317,530.70. The
figure is absurd on sight — a −71.6% single-session move on a book with no leverage and no trades —
which is the only reason it was caught immediately.

**A smaller version of this defect would not have been caught.** Had the 10:00 bar carried eight of
ten holdings instead of three, the error would have been a plausible −10% and would have been
reported as a bad day.

---

## Blast radius — exactly two rows, and the ranking is clean

### Corrupt

| Table / row | Stored | Correct |
|---|---:|---:|
| `db_gateway.daily_performance` 2026-09-01 | 373,561.70 | 1,273,881.70 |
| `db_gateway.portfolio_snapshot` 2026-09-01 | 373,561.70 | 1,273,881.70 |
| `db_csm_set.equity_curve` 2026-09-01 | 373,561.70 | 1,273,881.70 |
| `db_csm_set.equity_curve` **2026-08-31** | **303,397.70** | **1,317,530.70** |

### Intact — and one of these matters for how prior logs are read

- `equity_curve` **2026-08-03 → 2026-08-28**: every row verified against the published daily logs.
  The reprice window covered them, but their panel rows are single 09:55 bars, so they rewrote to
  the same values.
- 🟢 **`daily_performance` 2026-08-31 still reads 1,317,530.70.** That table is structurally
  **append-only** (`src/csm/adapters/hooks.py:286-294`), so the reprice could not touch it. **The
  2026-08-31 daily log's figures are therefore correct and remain correct** — only `equity_curve`'s
  copy of that day was destroyed. A reader who sees 303,397.70 should not conclude the prior log
  was wrong.

### The September rebalance was not contaminated — verified, not assumed

`data/processed/features_latest.parquet` is a **month-end-only** panel. Its latest date is
**2026-08-31 with 204 symbols and 204 complete six-factor rows** — a full cross-section. The
September 0-out/0-in verdict in `monthly/2026-08.md` was computed on that panel, and its quoted
closes (SMT 6.10, MGC 7.65, GUNKUL 5.15, INSET 4.78, EPG 6.25, IRPC 2.68, EASTW 4.86, KCE 60.50,
FORTH 16.00, HANA 47.25) all match the complete 09:55 row. **The rebalance stands.**

The feature pipeline is robust here because it works per-symbol on each name's own history rather
than off a panel row, so a symbol missing from one stamp is picked up from the other.

🔴 **The deadline this creates.** The next `features_latest` write is **2026-09-30**, the October
rebalance evaluation. If the defect is still live then, the ranking that *does* drive trades is
exposed. That is the date the fix has to beat.

---

## Reconstruction, and why it is trustworthy

The true session is the **union of the day's bars** — `groupby(index.date).ffill().iloc[-1]` — which
is well-defined here precisely because the two rows are complementary and agree wherever they
overlap.

**2026-09-01 closes:** IRPC 2.70 · HANA 45.00 · GUNKUL 4.98 · INSET 4.54 · KCE 57.75 · EASTW 4.80 ·
EPG 6.10 · FORTH 15.50 · SMT 5.80 · MGC 7.35 → **MV 1,270,854.00 + cash 3,027.70 = NAV 1,273,881.70**.

Three independent confirmations, none of which assumes the others:

1. **The corrupt values reproduce to the satang.** Pricing only the 10:00 names gives
   370,534.00 + 3,027.70 = **373,561.70** for 09-01, and only the 08-31 10:00 names gives
   300,370.00 + 3,027.70 = **303,397.70**. Both match the stored values exactly, so the mechanism is
   demonstrated rather than hypothesised — and a mechanism that predicts the wrong number exactly
   also identifies the right one.
2. **The P/L identity closes, unchanged.** `realized_cum + unrealized − (NAV − starting_nav)` =
   −49,091.38 + 204,583.35 − 153,881.70 = **1,610.27**, identical to 2026-08-31's residual, as a
   no-trade day requires. The identity only closes at the reconstructed NAV; at 373,561.70 it is off
   by 900,320.00.
3. **The EMA100 method positive-controls 5 / 5.** Recomputing full-series
   `ewm(span=100, adjust=False)` off the reconstructed panel reproduces every EMA100 reading the
   2026-08-31 log published — MGC +9.06%, EASTW +11.54%, FORTH +14.77%, EPG +19.33%, SMT +61.82% —
   confirming the reconstruction against a known-good prior session rather than against itself.

### Every corrupt DB field is mechanically accounted for

| Field | Stored | Derivation |
|---|---|---|
| `total_value` | 373,561.70 | HANA + GUNKUL + FORTH only |
| `daily_return` | −1.4182021336769801 | `daily_pnl(−529,786.00) ÷ TODAY's NAV` — the long-standing denominator defect, running on corrupt inputs. Reproduces to 17 significant figures. |
| `cumulative_return` | −0.6989364450113249 | `373,561.70 ÷ 1,240,806.7792389998 − 1`. The `entry_date` anchor row **held** — it was not restated. |
| `combined_drawdown` | −0.7706435442961985 | The trough is **the corrupt 2026-08-31 10:00 row**, not today: `303,397.70 ÷ 1,322,819.41 − 1`. Reproduces to 6 significant figures. |

The two previously-characterised gateway defects (`daily_return`'s denominator, `cumulative_return`'s
`entry_date` re-anchor) **behaved exactly as their model predicts** throughout. They did not cause
this and were not confused by it.

---

## Impact

- **No trading decision was affected.** The book is paper-only, the September rotation is 0-out/0-in
  and was decided on clean 2026-08-31 features, and `configs/live_portfolio.yaml` is unmodified.
- **Downstream consumers read the wrong NAV.** `portfolio_snapshot` feeds the gateway's
  cross-strategy aggregation and `quant-monitor`; anything that read csm-set's NAV between the
  2026-09-01 18:02 write and a future repair sees 373,561.70.
- **One banked historical figure was destroyed** and will be re-destroyed nightly until the code is
  fixed.
- **The 2026-09-01 daily log deviates from its own verification gate.** Skill step 10 requires
  `Total NAV` to equal `daily_performance.total_value`; that check is **waived and recorded**, with
  the three validations above standing in its place.

---

## Root cause

A guard that checks the shape of the data it *expects* rather than the property it *needs*, combined
with a summation that treats absence as zero.

The panel's contract — *"one row per trading day"* — was true for 948 consecutive bars and was never
asserted anywhere. When the vendor broke it, three separate pieces of code that each silently relied
on it failed together, and the one guard positioned to catch the failure was checking a different
question.

---

## Follow-up — all OPEN

1. **Collapse the panel to one row per trading day.** Either at read time in
   `compute_live_portfolio_metrics` (`groupby(index.date).ffill().iloc[-1]`) or, better, by
   normalising the bar stamp at write time in the refresh path so every consumer benefits.
2. **Make faults 2 and 3 fail loudly.** Check value presence, not only column presence, and refuse
   to price a book in which any holding is NaN rather than summing it to zero. *A missing price must
   never be able to present as a valid number.*
3. **Assert the panel invariant in the refresh** — exactly one row per trading date — so the next
   vendor stamp change is caught where it happens instead of four layers downstream.
4. **Repair the two corrupt rows.** Deliberately **not** done before (1): a repair without the fix is
   undone by the next 18:00 refresh, so it would create a false impression of resolution.
5. **Deadline: 2026-09-30**, the next `features_latest` write and the October rebalance evaluation.

Deliberately **not** done in the unit of work that produced this report: no code change and no DB
write. A change to the live NAV path needs its own review and quality gate, and is not something to
attach to a documentation run.

---

## Lessons

- **A success receipt describes what it measures, not what you wanted to know.** `failures=0`,
  `symbol_count=211` and `held_symbols_failed=0` were all true while the panel was unusable. The
  refresh counted fetches; the defect was in shape.
- **`skipna=True` turns a missing input into a confident wrong answer.** Summing a book with seven
  unpriced holdings should be impossible, not merely inaccurate. This is the same family as the
  standing platform rule that *"we are blind"* must stay distinguishable from *"the market is quiet"*.
- **A guard is only as good as the question it asks.** Checking that columns exist is not checking
  that prices exist, and the difference is invisible until the day it is the whole problem.
- **An invariant nobody asserts is a convention, not a contract** — and 948 consecutive confirmations
  of a convention is exactly what makes the 949th case surprising.
- **It was caught because it was absurd.** A −71.6% move is unmissable; a −10% one is a bad Tuesday.
  The size of this error is the only reason it was detected on the same day, which is an argument for
  the assertion in follow-up 3, not a reason for comfort.
- **Repricing a window and UPSERTing it makes every past row a liability.** A read defect became a
  write defect the moment the reconstruction touched history.

---

## Related

- `docs/live-test/daily/2026-09-01.md` — the log published on the reconstructed basis
- `docs/live-test/events/2026-08-01-price-adjustment-never-applied.md` — the vendor-restatement
  mechanism that also rewrites banked history
- `docs/live-test/events/2026-08-01-portfolio-snapshot-wiped-by-test-fixture.md` — the nearest
  precedent: a production table corrupted by a path that reported success
- `docs/live-test/monthly/2026-08.md` — the September 0-out/0-in rebalance, verified uncontaminated
