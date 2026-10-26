# Forward Scoring Pre-Registration — the Phase D window

**Registered:** 2026-10-27, before that day's session. The commit that adds this file is the
registration timestamp.
**Authority:** the operator's go of 2026-10-27, *"register the scoring criteria"*, given in answer to
the open item that the operator decision of 2026-09-11 left pending. Drafted by `session:csm-set`.
**Status:** **REGISTERED. Open to operator amendment until the 2026-10-30 evaluation**, meaning
before the 18:00 BKK scheduled refresh on 2026-10-30 builds that evaluation's data. **Frozen from
then.** Every choice below that is not already on record is marked **CHOSEN HERE**. Those are the
items the operator may change before that point.

---

## 1. What this registers

The operator decided on 2026-09-11 that the live test's track record restarts forward-only. Every
figure before it became *"pre-registration history — seen, not scored"*, with scoring criteria
*"pending an operator pre-registration"* (`docs/live-test/weekly/2026-09-11.md:210`). This document
is that pre-registration. It fixes four things before any scored data exists:

- **the window:** the Phase D months of November and December 2026, 41 sessions;
- **the rules under test:** including the EMA100 definition that operator decision D1 deferred to
  this document;
- **the formulas and data basis:** for every criterion and metric;
- **the treatment of each open decision:** the ones that bear on a score.

**The thresholds are not chosen here.** They are PLAN.md's, registered on 2026-05-04, before the
first trade (`docs/plans/live-test/PLAN.md:434-472`). `git log -L` on both tables returns only
`a0b673a` (2026-05-04 12:29 +07), so neither has been edited since. They are the only criteria in the record that
predate every result, and changing any of them now would be the move the 2026-09-11 decision rules
out: *"criteria chosen after ninety sessions of visible results are not a test."*

## 2. What is taken from the record, and what is chosen here

| Item | Source | Status |
|---|---|---|
| The 8 production-readiness criteria and their thresholds | `PLAN.md:459-472` | on record, unchanged |
| The 6 primary metrics, their targets and warning levels | `PLAN.md:436-445` | on record, unchanged |
| "All 8 must be met; partial success → a second, extended live test" | `PLAN.md:472` | on record, unchanged |
| No config change mid-test | `PLAN.md:294` (C.3) | on record |
| Forward-only restart; prior figures are seen, not scored | `weekly/2026-09-11.md:210` | on record (operator, 2026-09-11) |
| D1 EMA100, D2 no injection, D3 take what fills | `configs/live_portfolio.yaml:123-141` | on record (operator, 2026-09-30) |
| Exit rules: rank floor 0.35, buffer 0.25, breaker −10% rolling | `docs/live-test/README.md:60-63`, `configs/live-settings.yaml:37-48` | on record |
| Six-factor composite through `PortfolioConstructor.select()` | `monthly/2026-09.md:68` | on record (the practice of the 2026-09-30 evaluation) |
| Phase 3.8 baseline: 12.52% CAGR | `PLAN.md:216` | on record |
| Risk-free rate 2% a year | `src/csm/config/constants.py:79` (`RISK_FREE_RATE_ANNUAL`, used by `src/csm/risk/metrics.py`) | on record (code) |
| Window start, end and anchor NAV | §3 | **CHOSEN HERE** |
| The EMA100 definition for the forward record | §4 | **CHOSEN HERE** (D1 deferred it here) |
| The data basis and every formula | §5 | **CHOSEN HERE** |
| How each criterion is measured and graded | §6 | **CHOSEN HERE** |
| Criterion 4's baseline ([[TK-0570]]) | §6 #4 | **CHOSEN HERE** |
| Treatment of drift, sizing, restatement and dividends | §8 | **CHOSEN HERE** (for scoring only) |

## 3. The scored window

| | |
|---|---|
| **Anchor NAV₀** | the Total NAV published in the daily log for **2026-10-30**, the last session before the window |
| **First scored session** | **2026-11-02**, the November ATO |
| **Last scored session** | **2026-12-30**, the last SET session of 2026 |
| **Sessions** | **41** (November 21, December 20) |
| **Calendar source** | the strategy's banked SET calendar, read through `csm.data.calendar.is_set_holiday` on 2026-10-27 (cache `captured_at 2026-10-26T13:33:01Z`). It lists closures on 2026-12-07, 2026-12-10 and 2026-12-31 inside the window. The positive control: it also lists the observed October closures of 10-13, 10-16 and 10-23 |

- **If SET adds a closure later,** the session count is whatever the calendar holds when the day
  arrives. No date in this window is to be supplied from memory.
- **Sessions 2026-10-27 to 2026-10-30 are registered but not scored.** Everything before 2026-10-27
  stays pre-registration history, unchanged.
- **CHOSEN HERE, and why the window starts at a rebalance rather than at registration:**
  - The 2026-10-30 evaluation is the first application of the registered rules, so it opens the
    window.
  - The two scored months are exactly Phase D (`PLAN.md:301`).
  - An engine run for the same period, if one is built for D.1, can start from the same rebalance.

**Rule-application checkpoints inside the window:**

| Evaluation | ATO | Status |
|---|---|---|
| 2026-10-30 | 2026-11-02 | the first rotation under this registration |
| 2026-11-30 | 2026-12-01 | |
| 2026-12-30 | — | the final evaluation. Its January rotation plan lies outside the window |

## 4. The rules under test (frozen for the window)

**None of these is new.** Each is the practice the live test already runs, written down so that the
forward record has a definition and not a habit. `PLAN.md:294` forbids changing configuration
mid-test, so the registration records the configuration as it runs. It does not choose a better one.

| Rule | Registered definition | Source |
|---|---|---|
| Book | about 10 names; rebalances only at month-end (evaluation on the last session, execution at the next session's ATO); no trades between rebalances | `README.md:54-63`; every rotation since May |
| Ranking | equal-weight mean of the six z-scored factors (`mom_12_1`, `mom_6_1`, `mom_3_1`, `mom_1_0`, `sharpe_momentum`, `residual_momentum`), percentile-ranked. Verdict produced by calling `PortfolioConstructor.select()` with n=10, floor 0.35, buffer 0.25, on `features_latest.parquet` as written by the evaluation day's scheduled refresh, imported without the host's `.env`. The seven-factor reading is reported beside it but does not decide (**CHOSEN HERE**) | `monthly/2026-09.md:68` |
| Rank floor | pct-rank < 0.35 → sell | `README.md:60` |
| Buffer | sell only if an eligible challenger ranks ≥ 0.25 higher | `README.md:61` |
| **EMA100 exit (D1, CHOSEN HERE)** | **per holding.** At each evaluation, for every holding: EMA100 = `ewm(span=100, adjust=False, min_periods=100)` of that holding's closes in `prices_latest.parquet` as written by the evaluation day's scheduled refresh. **If the evaluation close is strictly below its EMA100, sell at the ATO.** A holding with fewer than 100 closes cannot trip the rule | `monthly/2026-09.md:70`; `events/2026-09-30-ema100-fast-exit-definition-conflict.md` |
| Index overlay | **not applied.** SET < EMA100 inside BULL → equity × 0.20 (`backtest.py::_is_fast_exit`) has never been applied live. The index condition is still computed and reported at each evaluation, so the consequence of the divergence stays visible | event doc above |
| Vol-scaling overlay | **not applied.** It is enabled in the recorded configuration and has never been applied live | event doc above, Follow-up 3 |
| Entrants | the top-ranked names not held, each with 63-day ADTV ≥ 5,000,000 THB, filling back to about 10 names, with the 35% sector cap checked at construction on SET-official sectors | `monthly/2026-09.md:70` |
| Sizing | only exits and entrants trade. Entrants are sized from exit proceeds plus cash, and held names are not re-weighted | the practice of every rotation; see §8 |
| Capital | **no injection** | D2 |
| Fills | one ATO order per side; take what fills; no follow-up | D3 |
| Fees | 0.16799% all-in on both sides: buy-side fees capitalised into the 4-dp `avg_cost`, sell-side netted from proceeds | `configs/live-settings.yaml:91-96` |
| Circuit breaker | see §6 #8 | `configs/live-settings.yaml:37-43` |

**Why D1 is answered "per holding":**

- It is the rule every rotation since May has applied, the one that evicted DELTA (2026-08-03) and
  MGC (2026-10-01).
- Adopting the index overlay now would change the strategy under test inside its own test, which
  `PLAN.md:294` rules out.
- The cost is stated in the event doc's Follow-up 2 and is repeated here:
  - **the per-holding rule is a live-only rule with no backtest behind it**;
  - the live book and the engine have run different exit logic since May;
  - any live-versus-backtest figure carries that difference (§6 #4).

⚠️ **Timing of any change to D1.** A change made after the 2026-10-29 close carries the
contamination the 2026-09-30 event doc describes: by then the SET's position against its own EMA100
on the evaluation day is largely visible. If the operator wants a different definition, it is
cleanest to say so before then.

## 5. The scored series and the formulas

**The scored series is the Total NAV published in each session's daily log.**

- The daily-log run checks that figure against `db_gateway.daily_performance.total_value` on the
  day it is written.
- **It is frozen at publication.** A later rewrite of any database row, such as a vendor
  ex-dividend back-adjustment re-pricing history, does not change the scored series.
- This settles restate-versus-cutover **for scoring**. See §8.

| Quantity | Formula | Notes |
|---|---|---|
| Daily return rₜ | NAVₜ / NAVₜ₋₁ − 1, published NAVs, r₁ against NAV₀ | not the DB `daily_return`, and not `cumulative_return` (it re-anchors at every rebalance) |
| Capital flow | none expected (D2). If one occurs: rₜ = (NAVₜ − Fₜ) / NAVₜ₋₁ − 1, and the flow is a deviation (§6 #7) | flows stripped, as the 2026-09-08 audit recommends ([[TK-0568]]) |
| Window return | NAV_end / NAV₀ − 1 | flow-adjusted if a flow occurs |
| Annualized volatility | sample std (ddof = 1) of rₜ × √252 | |
| Sharpe | mean(rₜ − rf) / std(rₜ) × √252, with **rf = 0.02 / 252 a session** | **CHOSEN HERE.** PLAN's formula subtracts rf, and the code's 2% is the only rate on record. The rf = 0 figure is reported beside it, because the published live Sharpe uses rf = 0: `README.md:82`'s 1.8276 at 2026-09-30 reproduces exactly that way (n = 102, flows stripped) |
| Max drawdown | min over the window of NAVₜ / running max(NAV₀ … NAVₜ) − 1 | the running peak starts at NAV₀ |
| Tracking error | std(rₜ − bₜ) × √252, with bₜ the daily return of **`SET:SET`** (price index, tvkit) | **CHOSEN HERE.** SET TRI is not captured. The book credits no dividends, so a price index is the like-for-like basis. **A risk metric, not an outperformance claim** |
| Turnover (annualized) | (Σ over the window's rebalances of Σ over names of \|w_after − w_before\|) × 12 / months, with months = 2 | PLAN's formula (two-sided). The one-way figure (half) is reported beside it, as the monthly reviews quote it |

## 6. The eight criteria — how each is measured and graded

Grades are **MET**, **NOT MET**, **NOT MEASURED** (the instrument failed) and, for #8 only,
**MET — NOT EXERCISED**. A criterion graded **NOT MEASURED** counts as **not met** under
`PLAN.md:472`.

| # | Criterion (PLAN, unchanged) | Threshold (unchanged) | Measured as |
|---|---|---|---|
| 1 | Cumulative return | positive | window return > 0 (§5). **CHOSEN HERE:** PLAN's "8-month live period" is read as the scored window, because the 2026-09-11 decision made May–October unscoreable |
| 2 | Sharpe ratio | ≥ 0.5 | §5 Sharpe over the 41 window sessions. "Since inception" is read as "since NAV₀", for the same reason |
| 3 | Maximum drawdown | > −15% | §5 max drawdown over the window |
| 4 | Live vs. backtest return gap | within ±5pp | live window return minus the **registered baseline** (below) |
| 5 | Data completeness | ≥ 95% of trading days | a window session counts as complete if its daily log records that session's refresh receipt with `held_symbols_failed = 0` and `index_fetched = true`, from the scheduled firing or a rerun the same evening. The denominator is the window's sessions. **CHOSEN HERE** over `count(*)` on `daily_performance` (`README.md:84`), because a receipt is stamped by the session it describes |
| 6 | System uptime | ≥ 99% excluding planned maintenance | see below |
| 7 | No unexplained model deviations | zero instances of incorrect trade generation | see below |
| 8 | Circuit breaker behaviour matches design | trips on real DD, recovers per spec, no false trips | see below |

**#4, the baseline ([[TK-0570]]), CHOSEN HERE: Phase 3.8, pro-rated.**

- The baseline window return is **(1 + 0.1252)^(N/252) − 1**, with N the number of scored
  sessions: **+1.9377% for N = 41.**
- Phase 3.8 is chosen because it is the only baseline measured on real SET data, and the one every
  monthly review has quoted.
- TK-0570's objection to Phase 4.9 stands: its 36.24% was *"never measured against a market."*
- **Stated with the number, every time it is quoted:**
  - Phase 3.8 is a different configuration: the broad book, with no per-holding EMA100 exit and no
    concentrated 10-name sizing;
  - its cost model is the flat 15 bps the audit found too low ([[TK-0567]]), and it is **not
    recomputed here**;
  - the ±5pp band was calibrated neither for a comparison across configurations nor for a
    41-session window.
- The audit called the missing baseline *"a pre-registration defect, not a measurement one"*
  (`reports/2026-09-08-live-test-state-and-cost-model-audit.md:199`). This choice is the repair it
  asked for: a baseline fixed before the result.
- This is TK-0570's option (b). A same-period engine run (option (a), and D.1's comparison table)
  may still be built and reported as context. **It does not grade #4.**

**#6, uptime, CHOSEN HERE.**

- The measure is the fraction of the window's wall-clock time that `csm-set-csm-1` was running.
- **Unplanned downtime** is reconstructed from three sources:
  - each daily log's recorded container `StartedAt`, `Created` and `RestartCount`;
  - `State.FinishedAt`, which the daily log records from the window's first session onward (it
    does not today);
  - the host's `last -x` boot and shutdown records.
- **Planned maintenance** is any stop recorded as approved before it began, as both October 2026
  recreates were (2026-10-14 and 2026-10-27).
- If a daily log is missing, more than one restart that day cannot be resolved, and the grade
  carries that limit.

**#7, deviations, CHOSEN HERE.** An instance is any of:

- a trade at a rebalance that the §4 rules, applied to that evaluation's data, do not produce;
- a trade those rules require that is not placed;
- any trade outside a rebalance;
- a capital flow.

An event report **explains** an instance. It does not remove it from the count. The following are
not instances:

- **a bound breach that construction could not avoid within D2's no-injection rule**, the case D2
  records as an accepted known violation;
- **a partial fill under D3.**

**#8, the breaker, CHOSEN HERE.**

- **The breaker is the design rule** (`configs/live-settings.yaml:37-43`): 60-session rolling
  drawdown, trip at −10%, recovery past −5% held for 21 sessions, 20% equity in safe mode.
- **It is evaluated by running `csm.portfolio.DrawdownCircuitBreaker` with those parameters on the
  published NAV series.** The trailing 60 sessions include pre-window sessions, because the breaker
  is a rule of the strategy, not a score.
- The class has **no caller** in `src/`, `api/`, `ui/` or `scripts/`; its only users are notebook 04
  and its unit test (searched 2026-10-27; the same search finds both, which is the positive control). That is why the procedure is
  written here and not left to a code path.
- **It acts at the next month-end evaluation:** a state of TRIPPED at the evaluation close scales the
  book to 20% equity at the ATO. This follows the monthly-only trading rule. **CHOSEN HERE:** if the
  operator wants an intra-month trip, say so.
- **Grading:**
  - **MET** if every evaluation acted as the state required;
  - **MET — NOT EXERCISED** if the trigger was never reached. That label goes wherever the grade
    is quoted, with the plain statement that the trip and recovery paths were never tested live;
  - **NOT MET** on a false trip or a missed one.
- The 2026-09-08 audit read #8 as requiring a trip. This registration reads the PLAN text as
  conditional behaviour, which an untriggered breaker does not violate. **CHOSEN HERE, and the
  operator may reverse it.**
- **The 1,064,000 THB line** that the daily logs and D2 call the breaker line is 5% below
  `starting_nav`. It is **not the design rule.** It stays a reported line and carries no action.
  **CHOSEN HERE:** if the operator meant it as the trip, say so before the window opens.

## 7. The primary metrics (tracked monthly, not pass/fail)

| Metric (PLAN, unchanged) | Target · warning (unchanged) | Measured as |
|---|---|---|
| Cumulative return | positive, within 3pp of backtest · negative for 3 consecutive months | window return. "Within 3pp" uses the §6 #4 baseline. The 3-month warning cannot fire in a 2-month window, and is reported as such |
| Annualized volatility | ≤ 15% · > 20% | §5 |
| Sharpe | ≥ 0.5 · < 0.3 | §5 |
| Max drawdown | > −15% · < −10% | §5 |
| Tracking error vs SET TRI | ≤ 12% · > 18% | §5, against `SET:SET` (labelled as the price index) |
| Turnover | ≤ 150% · > 200% | §5 |

**The volatility target needs a note, because it is a recorded defect, not a new finding.**

- The 2026-09-08 audit found realized volatility of 29.39% against the ≤ 15% target
  (`reports/2026-09-08-live-test-state-and-cost-model-audit.md:162`).
- The recorded configuration carries a 15% vol-target overlay (`configs/live-settings.yaml:29-33`,
  `target_annual: 0.15`). The live book does not run it (§4), and no code reads that file
  ([[TK-0566]]). So the target names a mechanism that is not in the test.
- **The target is kept, because PLAN registered it before any result.** It is reported every month.
- It is a primary metric, not one of the eight criteria, so it does not gate the verdict.

## 8. The open decisions, and how this registration treats them

These were carried to the October evaluation by the daily logs since 2026-10-01 and by
`monthly/2026-09.md:247-254`. **The registration settles each one only for scoring.** Anything
wider stays open where it is filed.

| Decision | Treatment in the scored window (CHOSEN HERE) | What stays open |
|---|---|---|
| EMA100 definition (D1) | per holding (§4) | nothing for the window |
| Backtest baseline ([[TK-0570]]) | Phase 3.8, pro-rated (§6 #4) | whether to fund option (a) as context; [[TK-0567]] |
| Drift at the band ends ([[TK-0279]]) | **bounds bind at construction only, on the names being traded.** Held names are not trimmed or topped up for drift. Breaches are reported each session and are not deviations (§6 #7) | whether a later test should rebalance to target |
| `fix-notional-not-shares` | **current practice:** entrants are sized from proceeds plus cash, and held names keep their shares. Recorded as a divergence from the engine, which re-weights at every rebalance | the sizing rule for any later test |
| Restate-versus-cutover | **the scored series is the published NAV, frozen at publication** (§5). Signals use the pipeline's current price basis. A change of basis inside the window counts as a configuration change | the history question: `equity_curve` rewrites ([[TK-0297]]), charts, and the `daily_return` legacy rows ([[TK-0489]]) |
| Dividend accrual | **not credited.** The scored NAV is price-only, as published. Dividends with an XD date inside the window are reported beside each score as a known downward bias | whether the book should credit dividends; 8,927.00 THB uncredited from pre-registration history |

## 9. What 41 sessions can and cannot show

**This section is part of the registration, so that the verdict cannot be read as more than the
window can support.**

- **Sharpe.** For roughly independent daily returns, the standard error of an annualized Sharpe is
  about √(252/N) (Lo, 2002, small-Sharpe approximation). **For N = 41 that is 2.48.** An observed
  Sharpe of 0.5 cannot be told apart from zero, or from 3, in this window.
- **Criterion 4.** At the volatility seen in pre-registration history (28.54% at 2026-09-30,
  `README.md:81`), one standard deviation of a 41-session return is about **11.5pp**. The ±5pp band
  is less than half of that.
- **Consequence.** A MET or NOT MET on #1, #2 or #4 is a record of what happened in two months, not
  evidence of an edge or of its absence.
- **Every place the verdict is quoted carries this paragraph or a pointer to it.**
- `PLAN.md:472` already provides the path a short window points to: partial success triggers a
  second, extended live test.

## 10. Amendment and reporting rules

- **Until the 2026-10-30 evaluation's data are built,** the operator may amend any CHOSEN HERE item.
  An amendment is a dated commit to this file.
- **After that, the registration is frozen.** Any later change is recorded in this file as a dated
  amendment, and the verdict reports each affected criterion **under the original registration**,
  with the amended reading only beside it.
- **No early stopping.** Interim figures are reported at the November evaluation as interim. The
  verdict is given once, at the 2026-12-30 evaluation, in `reports/final-report.md` (D.1).
- **The daily logs' status line changes with the window:**
  - 2026-10-27 to 2026-10-30: *"registered, not yet scored"*;
  - from 2026-11-02: *"scored window, session k of 41"*;
  - earlier figures keep their label: *pre-registration history — seen, not scored.*

## 11. What this registration does not do

- **It claims no alpha, outperformance or benchmark result**, and registers no hypothesis of one.
  The PLAN criteria contain none.
- **It changes no code, configuration or book entry.** `configs/live_portfolio.yaml` is untouched.
  The D1 text there still reads *"deferred to the pending pre-registration"*, which this file now
  is.
- **It re-labels no history.** Every figure before 2026-10-27 stays pre-registration history.
- **It does not settle the wider decisions** in §8's last column.
