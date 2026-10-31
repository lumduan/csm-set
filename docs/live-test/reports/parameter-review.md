# Parameter Review — Phase C exit criterion C.3

**Date:** 2026-10-31 (Phase C ended with the 2026-10-30 evaluation; filed during the weekend before the scored window opens)
**Required by:** `docs/plans/live-test/PLAN.md` §Phase C, C.3 *Parameter Sensitivity Re-Check*: re-run the Phase 4.8 notebook's stress tests on actual 2026 price paths, check whether the circuit-breaker thresholds, the vol target and the sector caps calibrated in Phase 4.9 still hold, and *"document the recommendation but do NOT change config mid-test"*.
**Status:** 🟡 **FILED — RECOMMENDATIONS ONLY. Nothing in the configuration, the code or the registered rules was changed.** The forward scoring pre-registration (`reports/2026-10-27-forward-scoring-pre-registration.md`) freezes the rules for 2026-11-02 → 2026-12-30, so every recommendation below is for **after the scored window**, or for a second test.
**Reproduce:** [`parameter-review/`](parameter-review/) holds the two scripts and `results.json`, the output every number below is taken from (see §7).

---

## Summary

Read on the live path from 2026-05-05 to 2026-10-30 (121 sessions), with the engine's own `VolatilityScaler` and `DrawdownCircuitBreaker` run unmodified:

1. **The 15% vol target and the concentrated book do not fit together.** The engine's own estimate of the held book's volatility was **29.29–45.42%** at the six evaluations. Applied, the overlay would have run the book at **33–51% equity** every month; never applied, the target was breached at about twice its level all along (28.39% realized). In-sample, applying it halved both return (+5.92% against +13.10%) and drawdown (−5.58% against −10.71%) and left the Sharpe ratio about where it was (0.9978 against 1.0445).
2. **Without the vol overlay, the −10% breaker is a recurring switch, not a tail guard.** On the live path it tripped once, at the 2026-10-30 evaluation. Resampling the live returns into one-year paths, it trips in **94%** of them and keeps the book in safe mode **35%** of the time. With the vol overlay applied as designed, it trips in **39%**.
3. **The breaker's other parameters barely mattered on this path.** The rolling window (40, 60 or 120 sessions) changed nothing except for a −5% trigger acting daily; a −12.5% or −15% trigger never tripped; a −5% trigger tripped in June and cost 1.63pp under month-end action.
4. **The 35% sector cap was not the binding concentration.** It was exceeded on 22 of 110 measured sessions, every one by drift (the bands bind only at construction), while the two largest sectors together held **53.35–68.46%** of NAV. A position was outside the 5–15% band on 75 of the 110 sessions.
5. **Six months, one regime and one trip cannot calibrate anything.** These are readings of how the recorded parameters behaved, not estimates of better ones (§5).

| # | Recommendation (for the operator; none applied) | When |
|---|---|---|
| R1 | Decide the vol overlay and the vol target **together**: apply the overlay as recorded, or restate the target to the level a 10-name book actually runs | after 2026-12-30 |
| R2 | Decide the breaker **with** R1: the −10% trigger was calibrated beside a 15% vol overlay that the live test never ran | after 2026-12-30 |
| R3 | Decide whether the sector cap is measured on NAV or on the equity sleeve when the book is scaled, and whether any drift rule applies between rebalances ([[TK-0279]]) | after 2026-12-30 |
| R4 | Keep every recorded parameter unchanged through the scored window | now (no action) |

---

## 1. What was re-run, and on what

**The series.** The published daily NAV, 2026-05-04 → 2026-10-30, from `db_gateway.daily_performance`, with the published post-trade values on the two rotation days whose fills landed after the 18:00 refresh (2026-08-03: 1,247,760.70; 2026-10-01: 1,352,210.89). The two capital injections are stripped from their days' returns. That gives **121 daily returns**: **+13.10%** compounded, **28.39%** annualized volatility, Sharpe **1.0445** (rf 0) / **0.9741** (rf 2%), maximum drawdown **−10.71%** on 2026-10-30. These differ in the last digits from the monthly review's figures, which use `daily_performance` as stored (28.35%, 1.0451), because the two rotation days are replaced here by their published values.

**How an overlay is applied.** An overlay sets an equity fraction *f* at each month-end evaluation (2026-05-29, 06-30, 07-31, 08-31, 09-30, and the 2026-05-05 entry). *f* applies to every session until the next evaluation, and the counterfactual daily return is *f* × the book's actual return, with cash earning nothing. With *f* = 1 the method reproduces the published series exactly. **This is the notebook's own construction** (weights × returns), applied to the live book instead of synthetic data. It assumes that scaling the book down would not have changed what the book held, which the live sizing rule (held names keep their shares) makes reasonable.

**What maps to what in `notebooks/04_portfolio_optimization.ipynb`:**

| Notebook section | Re-run here? | How |
|---|---|---|
| §3 vol-scaling sensitivity grid | ✅ | `VolatilityScaler.scale()` at each evaluation, on the book held that day (market-value weights from the published log) and tvkit closes up to that day; targets 10–30%, fast blend 0 and 0.3 |
| §4 circuit-breaker stress test | ✅ | `DrawdownCircuitBreaker.apply()` threaded **every session** on the counterfactual NAV path; triggers −5% to −15%, windows 40/60/120, acting at month-end (the registered rule) or daily |
| §6 sector exposure over time | ✅ | measured on every published daily log that states Total NAV (2026-05-20 → 2026-10-30, 110 sessions) |
| §9b block-bootstrap path dependency | ✅ | 2,000 one-year paths of circular 21-session blocks of the live daily returns, seed 42 |
| §2 weighting schemes, §5 capacity, §7 walk-forward, §9a random weights | ❌ | need the engine's backtest or a universe-wide price history, not the live path. Capacity is off at 1M THB by configuration |

**The vol estimate needed prices the panel no longer has.** JTS and MCOT were held in May and June and are not in `prices_latest.parquet`, so every vol estimate uses **tvkit closes fetched on 2026-10-31** for all 19 names the book ever held. These are the vendor's present view of history (§5).

**The parameters reviewed are the recorded ones** (`configs/live-settings.yaml`, overlays): vol target 15%, lookback 63, fast window 21 with blend 0.3, cap 1.5; breaker 60 sessions, −10% trip, −5% recovery held 21 sessions, 20% equity in safe mode; sector cap 35%; position band 5–15%. ⚠️ That file is a record; no code reads it ([[TK-0566]]).

---

## 2. The vol target (15%)

**What the engine would have estimated** (63-session volatility blended 0.7 / 0.3 with the 21-session one, on the book held at each evaluation):

| Evaluation | 2026-05-05 (entry) | 05-29 | 06-30 | 07-31 | 08-31 | 09-30 |
|---|--:|--:|--:|--:|--:|--:|
| Estimated volatility | 45.42% | 33.23% | 31.70% | 32.14% | 35.72% | 29.29% |
| Equity fraction at a 15% target | 0.33 | 0.45 | 0.47 | 0.47 | 0.42 | 0.51 |

**The sensitivity grid, on the live path:**

| Configuration | Equity fraction at the six evaluations | Return | Volatility | Sharpe (rf 0) | Sharpe (rf 2%) | Max drawdown |
|---|---|--:|--:|--:|--:|--:|
| **As run (no overlay)** | 1.00 throughout (equity share 98.12% on average) | **+13.10%** | **28.39%** | **1.0445** | **0.9741** | **−10.71%** |
| target 10%, fast blend 0.0 | 0.20 · 0.28 · 0.31 · 0.31 · 0.28 · 0.31 | +4.07% | 8.21% | 1.0538 | 0.8101 | −3.44% |
| target 10%, fast blend 0.3 | 0.22 · 0.30 · 0.32 · 0.31 · 0.28 · 0.34 | +4.00% | 8.54% | 0.9978 | 0.7637 | −3.74% |
| target 15%, fast blend 0.0 | 0.31 · 0.42 · 0.47 · 0.46 · 0.42 · 0.47 | +6.04% | 12.31% | 1.0538 | 0.8913 | −5.14% |
| **target 15%, fast blend 0.3 (as recorded)** | 0.33 · 0.45 · 0.47 · 0.47 · 0.42 · 0.51 | **+5.92%** | **12.82%** | **0.9978** | **0.8417** | **−5.58%** |
| target 20%, fast blend 0.0 | 0.41 · 0.56 · 0.62 · 0.61 · 0.56 · 0.63 | +7.96% | 16.41% | 1.0538 | 0.9319 | −6.81% |
| target 20%, fast blend 0.3 | 0.44 · 0.60 · 0.63 · 0.62 · 0.56 · 0.68 | +7.78% | 17.09% | 0.9978 | 0.8807 | −7.40% |
| target 25%, fast blend 0.0 | 0.51 · 0.70 · 0.78 · 0.77 · 0.70 · 0.78 | +9.83% | 20.52% | 1.0538 | 0.9563 | −8.47% |
| target 25%, fast blend 0.3 | 0.55 · 0.75 · 0.79 · 0.78 · 0.70 · 0.85 | +9.57% | 21.36% | 0.9978 | 0.9041 | −9.19% |
| target 30%, fast blend 0.0 | 0.61 · 0.84 · 0.93 · 0.92 · 0.84 · 0.94 | +11.64% | 24.62% | 1.0538 | 0.9725 | −10.10% |
| target 30%, fast blend 0.3 | 0.66 · 0.90 · 0.95 · 0.93 · 0.84 · 1.00 | +11.51% | 25.52% | 1.0158 | 0.9374 | −10.71% |

**Reading.**

- **The overlay scales risk and return together; the rf-0 Sharpe hardly moves.** Every target with blend 0 gives the same Sharpe, 1.0538: the six fractions are the same vector times a constant, so the ratio cancels. Below the cap, the target chooses how much of the same risk-adjusted return to take. It does not change the ratio.
- **The rf-2% Sharpe falls as the target falls**, because a smaller equity fraction earns less above the same risk-free rate.
- **The live book runs at about twice the recorded target, every month.** The estimate never fell below 29%. A 15% target is not a cap this book brushes against occasionally; applied, it would have halved the book permanently.
- **PLAN.md C.3 calls these parameters calibrated in Phase 4.9; that calibration ran on synthetic data** (notebook 04 draws its prices from `np.random.default_rng(42)`), with the vol overlay switched on (`docs/plans/examples/PLAN-sample.md` §Phase 4.9). The live test runs the same concentrated selection with the overlay off, so it is a different risk configuration from the one calibrated.

---

## 3. The circuit breaker (−10% over 60 sessions)

**On the live path** (recovery set at half the trigger, the recorded design ratio; the window column is collapsed because 40, 60 and 120 sessions gave identical results in every row except −5% daily, noted below):

| Trigger / recovery | Acting | Trips (dates) | Return | Max drawdown | Sharpe (rf 0) |
|---|---|---|--:|--:|--:|
| −5.0% / −2.50% | month-end | 2026-06-08, 06-15, 06-23, 09-03, 09-16, 09-30, 10-15 | +11.47% | −6.37% | 1.0967 |
| −5.0% / −2.50% | daily | 2026-06-08, 07-27, 08-04, 10-19 (60 sessions) | +2.35% | −6.32% | 0.3661 |
| −7.5% / −3.75% | month-end | 2026-10-29 | +13.10% | −10.71% | 1.0445 |
| −7.5% / −3.75% | daily | 2026-10-29 | +15.45% | −8.86% | 1.2031 |
| **−10.0% / −5.00% (as recorded)** | **month-end** | **2026-10-30** | **+13.10%** | **−10.71%** | **1.0445** |
| −10.0% / −5.00% | daily | 2026-10-30 | +13.10% | −10.71% | 1.0445 |
| −12.5% / −6.25% | either | none | +13.10% | −10.71% | 1.0445 |
| −15.0% / −7.50% | either | none | +13.10% | −10.71% | 1.0445 |

*−5% acting daily depends on the window: with 40 sessions it trips on 2026-06-08, 07-30 and 09-03 and returns −3.69%.*

**Reading the live path.**

- **The recorded breaker tripped once, at the first evaluation it governs**, and has not yet acted: its scaling starts at the 2026-11-02 ATO, so no return in this sample reflects it.
- **A tighter trigger would have tripped in June.** At −5%, acting at month-end, the book would have run in safe mode for parts of June to October and given up **1.63pp** (13.10% → 11.47%) for a shallower drawdown (−6.37%). Acting daily, the same trigger gave up 10.76pp, because it repeatedly sold after falls and re-entered after recoveries.
- **The one improvement in the table is one session.** −7.5% acting daily returns +15.45% only because it tripped on 2026-10-29 and took 2026-10-30's −2.52% at 20%. That is not evidence for the parameter.
- **The window did not matter** on this path.

**Resampled paths** (notebook §9b, re-run on the live returns: 2,000 one-year paths of circular 21-session blocks, seed 42; overlays act every 21 sessions):

| Overlay (252-session paths) | Median return | 5th pct return | Median max DD | 5th pct max DD | P(max DD worse than −15%) | P(trip) | Trips/yr | Time in safe mode | Median Sharpe |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| none | +31.41% | −12.19% | −16.74% | −30.96% | 62.50% | 0.00% | 0.00 | 0.00% | 1.09 |
| breaker −7.5% | +19.01% | −11.66% | −13.72% | −22.16% | 37.05% | 99.10% | 1.93 | 42.21% | 0.90 |
| **breaker −10% (as recorded)** | **+20.48%** | **−12.73%** | **−14.30%** | **−23.27%** | **42.80%** | **94.00%** | **1.55** | **35.05%** | **0.91** |
| breaker −15% | +25.11% | −14.70% | −16.33% | −26.27% | 62.50% | 60.65% | 0.72 | 15.80% | 0.99 |
| vol target 15% | +16.67% | −5.81% | −9.30% | −18.35% | 11.40% | 0.00% | 0.00 | 0.00% | 1.09 |
| **vol 15% + breaker −10% (as designed)** | **+15.34%** | **−7.34%** | **−9.30%** | **−15.93%** | **7.65%** | **39.30%** | **0.43** | **9.03%** | **1.04** |
| vol target 25% | +27.71% | −10.60% | −15.10% | −28.94% | 50.35% | 0.00% | 0.00 | 0.00% | 1.09 |

⚠️ **What the bootstrap can and cannot say.** It resamples the live returns, so **it inherits their mean**: the median one-year return of +31.41% with no overlay is six good months annualized by resampling, not a forecast. What it does show is **mechanics**: how often each overlay fires on a book with this volatility and this day-to-day pattern, and what each one trades for what. Its state machine is a fast re-implementation of the engine class; on the live path it agrees with `DrawdownCircuitBreaker` on all 121 daily states at −5%, −7.5% and −10%.

**Reading.**

- **At ~28% volatility, a −10% 60-session drawdown is an ordinary event**, about 1.5 times a year. The breaker then acts as a recurring de-risking switch. It shortened the median drawdown (−16.74% → −14.30%) and cut the share of paths worse than −15% (62.50% → 42.80%), and it cost median return and Sharpe (1.09 → 0.91).
- **The breaker was designed beside the vol overlay.** With both on, the breaker fires in 39% of paths instead of 94%, and the drawdown tail is the shallowest in the table (5th percentile −15.93%; 7.65% of paths worse than −15%).
- **Widening the trigger alone (−15%) changes little in the tail** (62.50% of paths still worse than −15%), because by the time it fires the damage is done.

---

## 4. The sector cap (35%) and the position band (5–15%)

Measured on the **110 published daily logs that state Total NAV**, 2026-05-20 → 2026-10-30:

| Month | Sessions | Sessions with a sector over 35% | Largest sector weight | Sessions with a position outside 5–15% |
|---|--:|--:|--:|--:|
| 2026-05 (from 05-20) | 8 | 0 | 32.97% | 0 |
| 2026-06 | 20 | 0 | 32.33% | 2 |
| 2026-07 | 21 | 0 | 33.38% | 20 |
| 2026-08 | 20 | 1 | 35.0028% | 19 |
| 2026-09 | 22 | 2 | 35.2791% | 15 |
| 2026-10 | 19 | 19 | 37.0766% | 19 |
| **All** | **110** | **22** | **37.0766% (ETRON, 2026-10-28)** | **75** |

- **A sector was above 30% on 101 of the 110 sessions** and never above 40%.
- **The two largest sectors together held 53.35% to 68.46% of NAV.** In this book the cap limits a single sector while two sectors carry two-thirds of the risk.
- **A position was above 15% on 42 sessions and below 5% on 35.** Some sessions had both, so 75 sessions had at least one.
- **Every breach was drift.** The bands bind only at construction, on the names being traded (registration §8, [[TK-0279]]). No code path trims a position or a sector between rebalances.
- **In safe mode the cap cannot bind as defined.** It is a weight on NAV (`sector_max_weight: 0.35`), and a book at 20% equity cannot reach 35% of NAV in any sector. The operator ruled on 2026-10-31 that the cap is checked on the scaled book (I2 in `monthly/2026-10.md`). On the 2026-11-02 book, ENERG is 7.21% of NAV and **36.61% of the stocks held**.

---

## 5. What this review cannot show

- **121 sessions, one regime, one trip.** The SET stayed above its SMA200 on every session; the breaker's recovery path has never run live; no bear-market behaviour is in the sample. Registration §9's power statement applies here with more force: for 121 sessions the standard error of an annualized Sharpe ratio is about √(252/121) ≈ 1.44 (the same approximation as §9), so every Sharpe difference above is well inside one standard error.
- **Counterfactuals assume the overlay changes size, not selection.** A scaled book would have held the same names in smaller amounts, which matches the live sizing rule, and the counterfactual ignores the extra fees of resizing at each evaluation.
- **The vol estimates use tvkit closes as fetched on 2026-10-31**, which the vendor back-adjusts on ex-dividend dates. A later re-run can move the estimates in the second decimal.
- **In-sample is not out-of-sample.** Any parameter chosen because it would have done better on this path is chosen by outcome. Nothing here is a reason to change a parameter inside the scored window, and the registration forbids it.

---

## 6. Recommendations (for the operator; none applied)

1. **R1 — vol target and vol overlay, together, after the scored window.** Either apply the overlay as recorded (the book would run at roughly half size), or restate the target to the volatility a 10-name book runs (the live estimates were 29–45%). Keeping the target at 15% with the overlay off leaves a target that the book breaches every month by construction.
2. **R2 — the breaker, decided with R1.** If the vol overlay is applied, the recorded −10% / 60-session breaker behaves as designed (it fired in 39% of resampled years). If the overlay stays off, the same breaker fires in most years and spends about a third of the time in safe mode; whether that is wanted is a design choice, not a calibration this sample can settle.
3. **R3 — the sector cap's denominator and drift.** Decide whether the cap is measured on NAV or on the equity sleeve when the breaker has scaled the book. Decide also whether a band breach between rebalances should ever trigger a trade. Both stay open beyond the window ([[TK-0279]]).
4. **R4 — no change inside the window.** `PLAN.md:294` and the registration both require it.

---

## 7. Reproduce

The scripts are in [`parameter-review/`](parameter-review/). Run them from a directory with no `.env`, with `CSM_PUBLIC_MODE=true CSM_OHLCV_SOURCE=parquet CSM_DB_WRITE_ENABLED=false`:

    uv run --project <repo> python docs/live-test/reports/parameter-review/fetch_px.py      # tvkit closes → px_tvkit.csv (gitignored)
    uv run --project <repo> python docs/live-test/reports/parameter-review/param_review.py  # → results.json

`param_review.py` reads `db_gateway.daily_performance` read-only, the published daily logs, and `px_tvkit.csv`. It writes `results.json`, from which every table above is taken. The committed `results.json` is the 2026-10-31 run, and a second run of the committed script reproduced it exactly.
