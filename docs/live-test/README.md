# Live Test Documentation

> Real-world paper-trading validation of the CSM-SET Cross-Sectional Momentum strategy.
> **Period:** May–December 2026 | **Status:** **Phase C — Stress Testing & Optimization (Sep–Oct 2026)**; Phase B closed 2026-08-31 with all three monthly reviews filed.
> Counts and figures in this file are **pointers, not restatements** — see [Key Metrics at a Glance](#key-metrics-at-a-glance).

## Quick Reference

- **Master Plan:** [docs/plans/live-test/PLAN.md](../plans/live-test/PLAN.md)
- **Configuration:** [configs/live-settings.yaml](../../configs/live-settings.yaml) — ⚠️ **a RECORD of the frozen parameters, not an input.** No code reads it ([[TK-0566]]). The values code actually uses are `Settings` defaults plus the container's env; broker state lives in [configs/live_portfolio.yaml](../../configs/live_portfolio.yaml), which **is** read
- **Environment Lock Commit:** `892e78a` (`live-test-v1.0.0`)
- **Phase C audit (2026-09-08):** [reports/2026-09-08-live-test-state-and-cost-model-audit.md](reports/2026-09-08-live-test-state-and-cost-model-audit.md) — live-test state from measurement, and the cost model against the canonical fee schedule

## Directory Map

| Directory | Contents | Update Cadence |
|-----------|----------|----------------|
| [daily/](daily/) | Per-trading-day logs: portfolio state, regime, NAV | Automated, daily |
| [weekly/](weekly/) | Health checks: container, data feed, scheduler, disk | Manual, weekly |
| [monthly/](monthly/) | Performance reviews: metrics, charts, backtest comparison | Manual, monthly |
| [events/](events/) | Significant event reports: downtime, model deviations, regime transitions | Ad-hoc, immediate |
| [graphs/](graphs/) | Exported charts: equity curves, drawdown, monthly returns | As generated |
| [reports/](reports/) | Phase reports: slippage audit, parameter review, final report | Per phase |

## Current Phase

**Phase A — Setup & Calibration (May 2026)** — ✅ CLOSED 2026-05-31 (all exit criteria met)

- [x] A.1 Environment Lock
- [x] A.2 Configuration
- [x] A.3 Infrastructure Check (19/19 May sessions refreshed; scheduler cron bug fixed `7be6762` and validated — 3 consecutive clean unattended fires May 21/22/25; see [events/2026-05-18-scheduler-cron-misfire.md](events/2026-05-18-scheduler-cron-misfire.md))
- [x] A.4 Baseline Reporting (research report complete — 132 symbols ranked, top 10 buy list ready)
- Bonus baseline (not a formal A-deliverable): [monthly/2026-05.md](monthly/2026-05.md)

**Phase B — Execution & Observation (June–August 2026)** — ✅ **CLOSED 2026-08-31** (all three monthly reviews filed)

- [x] June monthly review: [monthly/2026-06.md](monthly/2026-06.md) — the **first fully systematic rebalance** (July 1 ATO = SELL MCOT / BUY FORTH, 1-out/1-in)
- [x] July monthly review: [monthly/2026-07.md](monthly/2026-07.md) — filed 2026-07-31, **rebalance amended 2026-08-01** after a universe defect was corrected (August 3 ATO = SELL DELTA + PTTGC / BUY SMT + MGC, 2-out/2-in)
- [x] August monthly review: [monthly/2026-08.md](monthly/2026-08.md) — filed 2026-08-31; **0-out / 0-in — the live test's first NO-TRADE rebalance** (all three exit rules fire on zero holdings; lowest-ranked holding HANA at pct 0.814). **August closes Phase B.**
- [ ] September monthly review — due ~2026-10-01 (**Phase C**)
- ⚠️ **Phase C's slippage audit is not yet filed** and [reports/](reports/) is still empty; it is a stated Phase C exit criterion — [[TK-0571]]
- Daily automation: one log per trading session since [2026-05-04](daily/2026-05-04.md), zero gaps. **Count the files** — `ls docs/live-test/daily/*.md | wc -l` — rather than trusting a number written here; it must equal `SELECT count(*) FROM daily_performance WHERE strategy_id='csm-set'`
- Weekly health checks: one per Saturday since [weekly/2026-05-08.md](weekly/2026-05-08.md); the newest file in [weekly/](weekly/) is the current one

## Everyday Job Summary

| When | What | How |
|------|------|-----|
| Daily after SET close (~17:00 BKK) | Fetch OHLCV, compute signals, export rankings | `scripts/refresh_daily.py` (APScheduler in private mode) |
| Every Saturday | Health check: container, data feed, scheduler, disk | Manual review (you) — write weekly summary |
| Last trading day of month | Rebalance: compute volatility-target weights, generate trade list (sells + buys) | `ExecutionSimulator` (Phase 4.7) — review before ATO |
| First trading day of month | Execute rebalance at ATO + monthly performance review (metrics, charts, vs backtest) | Manual (settrad click2win for trades, write monthly review) |

## Exit Mechanisms (Backtest-Aligned)

All exits happen at **monthly rebalance** (BME). No intra-month stop-loss. This matches the Phase 3.8 backtest design exactly.

| Mechanism | Threshold | Action |
|-----------|-----------|--------|
| Exit Rank Floor | Below 35th percentile | Unconditional eviction at rebalance |
| Buffer Logic | Replacement ranks 25 pct pts higher | Existing holding evicted only if challenger is significantly better |
| EMA100 Fast Exit | Price < EMA100 at rebalance | Close position at rebalance |
| Circuit Breaker (portfolio) | -10% rolling DD | Reduce equity to 20% until recovery at -5% for 21 days |

These are the **only exit mechanisms tested in the 15-year backtest** (207 rebalance dates, 2009–2026). No per-position trailing stops or hard stops are applied — winners ride to the next rebalance.

## Key Metrics at a Glance

> 🔴 **This section used to RESTATE measurements, and they were five sessions stale within a week of
> every month-close.** Per the umbrella's living-document rule, a restated number in a doc like this
> is stale the week after it is written and re-freshing it only resets the clock. **What is named
> here instead is the target — which does not rot — and where the current value is produced.**

| Metric | Target | Where the CURRENT value is produced |
|---|---|---|
| NAV · daily P/L · positions · sector weights | — | the newest file in [`daily/`](daily/), one per trading session |
| Realized / unrealized / total P/L · commission | — | [`graphs/pnl.csv`](graphs/pnl.csv), one row per session; ledger derivation in [`graphs/README.md`](graphs/README.md) |
| Total return on NAV | positive | `daily_performance.total_value` vs `starting_nav` in [`configs/live_portfolio.yaml`](../../configs/live_portfolio.yaml) — **not** the DB's `cumulative_return`, which re-anchors at every rebalance |
| **Annualized volatility** | **≤ 15%** (warn > 20%) | 🔴 **BREACHED — 29.39% at 2026-09-07, ~2× target.** Computed from `daily_performance`, flows stripped. **This row did not exist before 2026-09-08, which is why 86 sessions passed without the breach surfacing** — [[TK-0564]] |
| Sharpe ratio (since inception) | ≥ 0.5 | ⚠️ **Compute it flow-stripped.** The 2.69 previously published here counted the two capital injections as returns; the correct figure over that window is **1.9298** — [[TK-0568]] |
| Max drawdown | > −15% | the drawdown line in the newest [`daily/`](daily/) log; the circuit breaker has never tripped |
| Data completeness | ≥ 95% | `count(*)` on `daily_performance` vs SET trading days in the period |
| Position bound · sector cap | 5–15% · ≤ 35% | the newest [`daily/`](daily/) log. ⚠️ Both are applied at **rebalance construction only** — there is no intra-month enforcement — [[TK-0279]] |

**Two standing cautions that are not measurements and therefore do not go stale.**

**Read any Sharpe with care.** The live sample is four months of a concentrated ~10-name book. The
honest baseline is the Phase 3.8 backtest's **0.663** on the broad top-quantile book; this expression
of the same edge is higher-variance by construction. ⚠️ **Which backtest baseline the
production-readiness criteria compare against is itself unsettled** — the live configuration's
registered numbers are synthetic-data only — [[TK-0570]].

⚠️ **`configs/live-settings.yaml` is a RECORD, not a control panel.** No code reads it; changing a
value there changes nothing. The container's refresh cron already disagrees with it — [[TK-0566]].

### Realized vs unrealized P/L

![Realized vs Unrealized P/L](graphs/pnl_realized_unrealized.png)

The two halves of the result answer different questions and are reported separately at every cadence
(daily, weekly, monthly):

| | Since inception | Meaning |
|---|---:|---|
| **Realized** | **−49,091.38 THB** | Banked. Only moves when a position is **closed** — i.e. at a rebalance — and can never change again |
| **Unrealized** | **+248,232.35 THB** | Mark-to-market on the open book. Moves every session; can round-trip to zero |
| **Total** | **+199,140.97 THB** | Sum of the two |
| **Commission paid** | **−3,735.16 THB** | All-in fees on every fill @ **0.16799%**. Already *inside* the two rows above — buy-side is capitalised into cost basis, sell-side is netted out of realized. Shown separately because it is otherwise invisible |

Every realisation so far, and the commission behind it. Both exits came from exit rules, not
discretionary calls:

| Date | Event | Realized | Commission |
|---|---|---:|---:|
| 2026-05-05 | Initial entry — 10 names | — | −1,611.15 |
| 2026-06-02 | Rebalance — NEX +6,591.99 · AGE −3,558.45 · JTS −7,385.41 | −4,351.87 | −984.44 |
| 2026-06-04/05 | MCOT filled in two tranches | — | −169.09 |
| 2026-07-01 | SELL MCOT — tripped three independent exit signals | −14,964.06 | −287.83 |
| 2026-08-03 | Rebalance — SELL DELTA (EMA100 exit) −14,392.42 · SELL PTTGC (buffer) −15,383.03 | −29,775.45 | −682.65 |
| 2026-09-01 | **No trades — 0-out / 0-in, all three exit rules fire on zero holdings** | **0.00** | **0.00** |
| | **Cumulative** | **−49,091.38** | **−3,735.16** |

**Commission is 0.28% of NAV but 7.6% of the realized loss.** The NAV denominator makes rotation
friction look free; the realized one is the denominator that carries the consequence, because
friction scales with turnover, not with book size. ⚠️ **The share of the realized loss FELL from
15.8% to 7.6% — and that is not an improvement in friction.** The denominator grew: the 2026-08-03
rotation added 682.65 of commission against 29,775.45 of fresh realized loss. **September's 0%
turnover is the cheapest possible month by construction**, and is the only thing that will actually
hold this figure still.

**Realized P/L being negative while the strategy is up +17.64% is expected, not a warning.** A
momentum book banks its losers at rebalance and lets winners ride to the next one, so realized P/L
skews negative while the gains accumulate unrealized. It becomes worth investigating only if the
*total* stalls, or if realisations start coming from discretionary sales rather than exit rules —
and the total advanced **+70,791.01** in August. ↻ *This section previously projected the 2026-08-03
rotation would take cumulative realized to **−45,048.18 THB**. The executed fills came in worse:
**−49,091.38**. The projection used the 2026-07-31 indicatives; both sells filled under them
(DELTA 272.00 vs ~278.00, PTTGC 36.00 vs ~36.75), which is the same slippage that forced the
20,000 injection.*

_(Next refresh: ~2026-10-01, with the September monthly review. Charts:
[equity curve](graphs/equity_curve.png) · [drawdown](graphs/drawdown.png) ·
[monthly returns](graphs/monthly_returns.png) · [realized vs unrealized P/L](graphs/pnl_realized_unrealized.png)
— see [graphs/README.md](graphs/README.md) before regenerating; they are **not** all built from one
series.)_

## Known Open Issues

Defects found during the live test that are **not yet fixed**. Each links to its event report.

| Issue | Effect | Filed |
|-------|--------|-------|
| **Ex-dividend restatements rewrite banked history** — the vendor back-adjusts a symbol's whole series on each XD; **6 of 10 held names** now carry restated bars | No NAV/cost-basis/U.PL impact, but `equity_curve` historical rows move and three gateway reporting columns are computed on endpoints that shift retroactively. Mechanism fully characterised and predictive | [2026-08-24](events/2026-08-24-ex-dividend-restatement-wave.md) |
| **No dividend-accrual path in the live-test book** — `cash` is a static YAML field mutated only at rebalance | **6,663.00 THB uncredited**; on 2026-08-28 it flipped a reported sign (FORTH shown −0.79% below cost, truly +0.14% above). Above/below-cost count reads 8/2 and is truly 9/1 | [2026-08-24](events/2026-08-24-ex-dividend-restatement-wave.md) |
| **Position/sector bands are applied at rebalance CONSTRUCTION only** — no code path trims drift | INSET outside the 5–15% band on 19 of 20 August sessions (15.24%, 3,130.40 over); AUTO 0.34 pp off the 5% sector floor; the ENERG–ETRON gap moved 0.8 pp in one session | [2026-08-31](monthly/2026-08.md) |
| **Composite factor count is ambiguous** — the live panel carries 7 columns; the documented composite is 6 (`sector_rel_strength` is an entry gate, but `cross_section` feeds `select()` whatever the panel holds) | No effect on the September verdict (0-out/0-in either way), but HANA survives eviction by **0.0098** on the 7-factor reading | [2026-08-31](monthly/2026-08.md) |
| 🔴 **Realized volatility is ~2× the 15% vol target** — 29.39% annualized, flows stripped, against a pre-registered target of ≤15% and a warning threshold of >20% | A pre-registered primary metric in breach for the whole live test. It surfaced only on 2026-09-08 because **volatility was the one primary metric absent from the metrics table** | [[TK-0564]] |
| 🔴 **The strategy reports zero trades and zero commission to the platform** — `hooks.py` passes a hardcoded `trades=[]` | `db_csm_set.trade_history` holds **0 rows after four rebalances**; every gateway payload carries `commission_paid: "0"` against **3,735.16 THB** actually paid. The trade record exists only as prose | [[TK-0565]] |
| ⚠️ **`configs/live-settings.yaml` has no code consumer** — the file three documents call the single source of truth is inert | Nothing is currently wrong *because* of it; the risk is the next person who changes a value there and expects the strategy to change. The container's refresh cron already disagrees with it | [[TK-0566]] |
| ⚠️ **The backtest's 15 bps cost covers 44.6% of this repo's own documented fee rate** and 2.0% of the one rebalance where friction was measured | **Not load-bearing on any live-test result** — live NAV uses real fills. It **is** load-bearing on production-readiness criteria 1 and 4, due Phase D | [[TK-0567]] |
| ⚠️ **Published Sharpe counted capital injections as returns** — 2.6940 against 1.9298 flow-stripped | Verdict unchanged (both clear 0.5); the number was wrong by 40%. **Corrected in this README**; the daily and monthly logs were always right | [[TK-0568]] |
| **`SET:BANPU` has no price history** — the 2026-08-01 "renamed to BANPUU" reading was **retracted**; settfex lists plain `BANPU` and the banked `BANPUU` frame held only 2 bars | BANPU fails the coverage screen, so the 2026-07-31 universe is 210 rather than 211. No trading impact — not held, not in the August 3 list. Re-fetching `SET:BANPU` restores it | [2026-07-31](events/2026-07-31-july-data-integrity-sweep.md) |

_Resolved during the July month-end sweep: the truncated universe (136 → 211 symbols) and the
duplicated `equity_curve` (97 → 60 rows) — both in
[2026-07-31](events/2026-07-31-july-data-integrity-sweep.md). Resolved 2026-08-01: the **unscoped
`DELETE` in the `infra_db` fixture** — deletes are now scoped to self-identifying test rows and the
suite refuses to run against a database holding rows it did not create, verified against the live
`db_gateway` with zero mutations ([2026-08-01](events/2026-08-01-portfolio-snapshot-wiped-by-test-fixture.md));
and the **phantom rows on closed days** — the 12 historical rows were deleted and the write path now
takes its date from the price bar rather than the wall clock, skipping the gateway POST entirely when
no bar arrived for today ([2026-07-31](events/2026-07-31-july-data-integrity-sweep.md) follow-up #1).
**The unattended proof of that guard lands at the next SET closure, candidate 2026-08-12** — expect no
row dated that day and a WARNING in the container log._ **Amended 2026-08-06:** the calendar gained a
committed fallback table that evening, so 2026-08-12 now skips at Phase 0 in seconds and does **not**
reach the no-fresh-bar guard. "No row dated 2026-08-12" still holds and is still the check; the
container line to expect is the holiday skip, not the stale-bar WARNING, and the unattended proof of
the no-bar guard moves to the first unlisted closure — see the amended note in
[2026-07-31](events/2026-07-31-july-data-integrity-sweep.md) §2. **Amended again 2026-08-07:** settfex
recovered and all 20 published 2026 closures were promoted, so **no unlisted 2026 closure remains** and
the holiday route to that proof is closed until a 2027 date. The guard's other job — a session where
the market traded but the fetch came back empty — is untouched and can still fire any day.

_Resolved 2026-08-09: the **price adjustment was never applied** — the `adjustment` kwarg was
resolved, validated and then discarded, so every momentum factor for the live test's first three
months ran on split-adjusted-only prices. Fixed by `e04a292` (PR #33, [[TK-0277]]), store
regenerated and universe snapshots rebuilt; impact quantified in PR #34 and **the selection is
unchanged** ([2026-08-01](events/2026-08-01-price-adjustment-never-applied.md)).
⚠️ **The factor history is still not comparable across 2026-08-09** — the fix does not make the
earlier basis the same quantity as the later one._

_Resolved 2026-09-02/03: **`daily_return` divided by TODAY's NAV** instead of the prior NAV. Fixed in
the gateway (`quant-api-gateway` PR #38), deployed, and verified correct on three consecutive
sessions in both bias directions. ⚠️ **112 historical rows remain on the legacy basis** and the
backfill-vs-cutover decision is open — [[TK-0489]]. The *second*, independent half of that defect —
a restated prior NAV after an ex-dividend — is **not** fixed and stays live under the XD row above._

_Also resolved 2026-08-01: the **ranking-pipeline gap**. `daily_refresh` now fetches `SET:SET` and
passes `symbol_sectors` from the universe, so all **six** factors compute — `residual_momentum`
(the only one that cleared the ICIR > 0.15 gate), `sharpe_momentum` and `sector_rel_strength` were
previously never written, which is why the authoritative composite needed a manual re-fetch at three
consecutive month-ends. The **false-liveness retry** (an all-NaN column reading as "recovered") and
the **null benchmark** (`^SET.BK`, a symbol tvkit never served) are fixed in the same pass._
