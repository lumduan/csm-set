# Live Test — Master Plan

**Feature:** Real-world paper-trading validation of the CSM-SET Cross-Sectional Momentum strategy
**Branch:** `feature/live-test`
**Created:** 2026-05-04
**Status:** Planning
**Depends on:** Phase 7 (Hardening & Documentation — complete), Phase 4.9 (Signal Robustness & Risk Stabilization — complete)
**Positioning:** Post-MVP validation phase — runs the full strategy stack against live SET market data for 8 months (May–Dec 2026) to gather real-world evidence before any production deployment with real capital.

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Design Rationale](#design-rationale)
4. [Repository Structure](#repository-structure)
5. [Live Test Roadmap](#live-test-roadmap)
6. [Operational Protocols](#operational-protocols)
7. [Metrics & Success Criteria](#metrics--success-criteria)
8. [Documentation Standards](#documentation-standards)
9. [Risk Register](#risk-register)
10. [Commit & PR Templates](#commit--pr-templates)

---

## Overview

### Purpose

The live test phase validates the CSM-SET strategy under real market conditions over an 8-month horizon (May–December 2026). Every component built in Phases 0–7 — data ingestion, signal computation, portfolio construction, risk overlays, execution simulation, API serving — runs daily against live SET prices fetched via tvkit. The strategy generates paper trades (no real capital), logs every decision with full audit trail, and produces weekly and monthly performance reports comparing live results against the backtest baseline.

This is **not** a code-heavy phase. The strategy logic is frozen; changes are limited to critical bug fixes. The primary output is evidence: does the strategy perform in production as the backtest predicts?

### Scope

The live test covers four phases:

| Phase | Period | Focus |
|-------|--------|-------|
| A — Setup & Calibration | May 2026 | Environment lock, infrastructure check, baseline reporting |
| B — Execution & Observation | June–August 2026 | Automated daily logs, weekly health checks, monthly performance reviews |
| C — Stress Testing & Optimization | September–October 2026 | Market event analysis, slippage audit, parameter sensitivity re-check |
| D — Final Evaluation & Documentation | November–December 2026 | Comprehensive report, production-readiness assessment, README update |

**Out of scope:**

- Real capital deployment (that's a post-live-test decision)
- New strategy features or signal research (code is frozen)
- Broker integration (paper trading only; trade lists generated but not submitted)
- UI/dashboard changes beyond what's needed for live monitoring

---

## Problem Statement

Phase 7 delivered a production-grade strategy stack with 742 tests and 92% coverage. The backtest reports CAGR 12.52%, Sharpe 0.663, Max DD −31.03% (Phase 3.9 baseline). Phase 4.9's concentrated retail-scale configuration reports Sharpe 2.70 and Max DD −10.54% on synthetic data.

These numbers are promising but share one critical limitation: they are **historical**. Three questions can only be answered by running the strategy live:

1. **Does the signal hold out-of-sample in 2026?** Backtests use expanding-window walk-forward validation, but the final holdout is always the future. Live trading from May to December 2026 provides a genuine out-of-sample test.
2. **Do the risk overlays behave as designed under real market stress?** The drawdown circuit breaker, volatility scaling, and capacity overlay were tested on synthetic and historical data. Live markets may surface edge cases the synthetic scenarios missed.
3. **Is the operational infrastructure reliable enough for production?** Docker stability, data feed uptime, scheduler reliability, and logging completeness can only be stress-tested by running continuously for months.

Answering these three questions is the prerequisite for any decision to deploy real capital.

---

## Design Rationale

### Code Freeze, Observation Focus

The strategy code is frozen at the start of Phase A. The only permitted changes during the live test are:

- Critical bug fixes (data pipeline failures, incorrect trade calculations)
- Configuration tuning in `configs/live-settings.yaml` (rebalance dates, AUM parameter)
- Logging and reporting improvements (not strategy logic)

This is intentional: if the code changes mid-test, the results are not a clean out-of-sample validation. The live test measures the strategy as built, not the strategy as iterated.

### Paper Trading with Full Audit Trail

Every rebalance generates a `TradeList` via the Phase 4.7 `ExecutionSimulator`. These trade lists are logged but not submitted to any broker. The paper portfolio tracks:

- Daily NAV (marked to live prices)
- Every trade decision with rationale (which signal fired, which overlay adjusted it)
- Slippage estimates vs. what actual market spreads would have been

The audit trail is the deliverable. If the live test shows poor performance, the logs must answer *why* — was it the signal, the regime filter, the vol scaler, or just a bad market?

### Daily Automation, Weekly Human Review

The scheduler (APScheduler from Phase 5) runs daily data refresh and signal computation. Human review happens weekly: check container health, review the trade log, confirm the regime detection is sensible, note any anomalies. Monthly reviews are deeper: full performance metrics vs. backtest baseline, drawdown analysis, turnover check.

This cadence balances automation (reduces operator toil) with oversight (catches issues before they compound).

### `configs/live-settings.yaml` as Single Source of Truth

All live-test parameters — AUM, rebalance schedule, overlay toggles, reporting thresholds — live in one YAML file. This is distinct from `.env` (which holds secrets and environment-level config) and from `BacktestConfig` Pydantic defaults (which are code). The YAML file is the operator's control panel: change parameters without touching code.

---

## Repository Structure

```
csm-set/
├── configs/
│   └── live-settings.yaml              # Live test configuration (NEW)
├── docs/
│   ├── live-test/                       # Live test logs, reports, graphs (NEW)
│   │   ├── README.md                    # Index and navigation for live test docs
│   │   ├── daily/                       # Daily logs: YYYY-MM-DD.md
│   │   │   ├── 2026-05-04.md
│   │   │   └── ...
│   │   ├── weekly/                      # Weekly health check reports
│   │   │   ├── 2026-W19.md
│   │   │   └── ...
│   │   ├── monthly/                     # Monthly performance reviews
│   │   │   ├── 2026-05.md
│   │   │   └── ...
│   │   ├── events/                      # Significant event logs
│   │   │   ├── 2026-05-04-system-downtime.md
│   │   │   └── ...
│   │   ├── graphs/                      # Exported charts (equity curves, DD, etc.)
│   │   └── reports/                     # Phase C stress test reports, Phase D final report
│   └── plans/
│       └── live-test/
│           └── PLAN.md                  # This file
└── README.md                            # Updated in Phase D with "Real-world Performance 2026"
```

### `configs/live-settings.yaml` Schema

```yaml
live_test:
  enabled: true
  start_date: "2026-05-04"
  end_date: "2026-12-31"
  aum_thb: 1_000_000          # Paper portfolio size (retail scale per Phase 4.9)
  rebalance:
    frequency: monthly         # last trading day of month
    execution_time_utc: "09:00"
  data:
    refresh_cron: "30 13 * * 1-5"  # After SET market close (17:00 BKK = 10:00 UTC)
    tvkit_rate_limit_rps: 5
  overlays:
    vol_scaling:
      enabled: true
      target_annual: 0.15
    circuit_breaker:
      enabled: true
      trigger_threshold: -0.10
    capacity:
      enabled: false           # Disabled at retail AUM (1M THB)
    quality_filter:
      enabled: true
  reporting:
    daily_log_enabled: true
    weekly_health_check_day: "Saturday"
    monthly_review_day: 5      # By the 5th of each month
  alerts:
    drawdown_warning_threshold: -0.05
    drawdown_critical_threshold: -0.10
    data_gap_hours: 24
    container_memory_mb: 1800
```

---

## Live Test Roadmap

### Phase A — Setup & Calibration (May 2026)

**Goal:** Lock the environment, verify infrastructure, and establish the baseline.

**Deliverables:**

- [ ] **A.1 Environment Lock**
  - Freeze strategy code: tag the commit as `live-test-v1.0.0` in git
  - Document the exact commit SHA in `docs/live-test/README.md`
  - Create `feature/live-test` branch off the locked commit
  - Disable all non-critical code changes via branch protection or social contract

- [ ] **A.2 Configuration**
  - Create `configs/live-settings.yaml` with initial parameters (retail scale: 1M THB AUM, concentrated top-10 portfolio, quality filter on, capacity overlay off)
  - Create `.env.live` from `.env.example` with tvkit credentials and `CSM_PUBLIC_MODE=false`
  - Validate configuration loads correctly via `Settings` pydantic model

- [ ] **A.3 Infrastructure Check**
  - Verify Docker container starts and stays healthy for 72 consecutive hours
  - Confirm APScheduler triggers daily data refresh without failures for 5 consecutive trading days
  - Confirm tvkit authentication is stable (no session expiry within the trading week)
  - Set up auto-restart policy (`restart: unless-stopped` in compose)
  - Verify disk space: ensure >= 10 GB free for 8 months of parquet data accumulation

- [ ] **A.4 Baseline Reporting**
  - Generate initial portfolio composition snapshot (what the strategy would buy today)
  - Generate initial regime state report (BULL/BEAR/NEUTRAL, SMA200 position)
  - Log the current SET index level and 200-day SMA for future comparison
  - Export current backtest summary metrics as the comparison baseline

**Exit criteria:** Container stable for 72 hours, 5 consecutive successful daily refreshes, baseline report committed.

---

### Phase B — Execution & Observation (June–August 2026)

**Goal:** Run the strategy daily with minimal intervention. Collect data. Observe.

**Deliverables:**

- [ ] **B.1 Daily Automation**
  - APScheduler triggers data refresh every trading day after SET close
  - Signal computation runs after data refresh completes
  - Daily log auto-generated with:
    - Current portfolio holdings and weights
    - Regime state (BULL/BEAR/NEUTRAL) and detected transitions
    - Any circuit breaker trips or overlay adjustments
    - Data quality metrics (symbols fetched, failures, gaps)
    - Paper NAV and day-over-day change
  - Daily log saved as `docs/live-test/daily/YYYY-MM-DD.md`

- [ ] **B.2 Weekly Health Checks**
  - Every Saturday (or last trading day of the week): manual review of:
    - Container uptime and memory usage
    - Data feed completeness (all symbols fetched? any gaps?)
    - Scheduler job history (any failures or misfires?)
    - Log file sizes and disk usage
  - Weekly summary saved as `docs/live-test/weekly/YYYY-Www.md`
  - Template format: status table (Container / Data / Scheduler / Disk), any incidents, action items

- [ ] **B.3 Monthly Performance Reviews**
  - By the 5th of each month (June, July, August): comprehensive review
  - Metrics computed against live paper portfolio:
    - Month-over-month return
    - Cumulative return since live test start
    - Realized volatility (annualized)
    - Sharpe ratio (rolling, since inception)
    - Maximum drawdown (peak-to-trough, since inception)
    - Tracking error vs. SET TRI benchmark
    - Turnover rate (annualized)
    - Comparison vs. backtest prediction for the same period
  - Monthly review saved as `docs/live-test/monthly/YYYY-MM.md`
  - Include exported charts in `docs/live-test/graphs/`

**Exit criteria:** 3 consecutive months of daily logs, weekly health checks, and monthly reviews. No data gaps exceeding 24 hours. No unexplained strategy behavior.

---

### Phase C — Stress Testing & Optimization (September–October 2026)

**Goal:** Actively test edge cases while the strategy is still paper-trading. Audit slippage assumptions.

**Deliverables:**

- [ ] **C.1 Market Event Analysis**
  - Identify any significant market events during May–August (Fed decisions, Thai political events, SET circuit breaker triggers, sector-specific shocks)
  - For each event: replay the strategy's response — what did the regime detector report? Did the circuit breaker trip? Were trades generated correctly?
  - Document model behavior: did the strategy react appropriately or reveal a blind spot?
  - Event analysis saved as `docs/live-test/events/<date>-<event-name>.md`

- [ ] **C.2 Slippage Audit**
  - Compare `ExecutionSimulator` estimated slippage against actual SET bid-ask spread data for the stocks the strategy traded
  - If the sqrt-impact model consistently under- or over-estimates, document the calibration gap
  - If possible, collect snapshots of actual Level 1 quotes at rebalance times via tvkit or alternative source
  - Slippage audit report saved as `docs/live-test/reports/slippage-audit.md`

- [ ] **C.3 Parameter Sensitivity Re-Check**
  - Using live data from May–August, re-run the Phase 4.8 notebook's stress tests with actual (not synthetic) 2026 price paths
  - Check whether the circuit breaker thresholds, vol target, and sector caps calibrated in Phase 4.9 still hold
  - If live experience suggests a parameter change, document the recommendation but do NOT change config mid-test (preserve clean out-of-sample period)
  - Sensitivity report saved as `docs/live-test/reports/parameter-review.md`

**Exit criteria:** Event analysis complete for all major market events. Slippage audit report with calibration findings. Parameter review with recommendations for Phase D.

---

### Phase D — Final Evaluation & Documentation (November–December 2026)

**Goal:** Produce the comprehensive final report. Decide on production readiness.

**Deliverables:**

- [ ] **D.1 Comprehensive Final Report**
  - Full 8-month performance analysis:
    - Cumulative return vs. SET TRI vs. backtest prediction
    - Monthly return table with commentary
    - Drawdown chart with event annotations
    - Rolling Sharpe (3-month window)
    - Turnover analysis (how much of turnover was signal-driven vs. overlay-driven)
    - Regime exposure breakdown (% of days in BULL/NEUTRAL/BEAR, % of capital deployed per regime)
    - Circuit breaker history (trips, recoveries, false positives/negatives)
  - Comparison table: live vs. backtest for the same 8-month period
    - Return deviation (live - backtest)
    - Volatility deviation
    - Max DD deviation
    - Turnover deviation
  - Lessons learned: what worked, what surprised, what needs to change before production
  - Final report saved as `docs/live-test/reports/final-report.md`

- [ ] **D.2 Transition Plan for Production**
  - If the live test meets success criteria (see Metrics section): document the path to production
    - Broker selection and integration scope
    - Capital deployment schedule (phased or lump-sum)
    - Operational runbook (who monitors, escalation paths, emergency stop procedure)
    - Legal/compliance checklist for Thai securities regulation
  - If the live test does NOT meet success criteria: document what failed, what needs to be re-engineered, and whether a second live test is warranted
  - Transition plan saved as `docs/live-test/reports/transition-plan.md`

- [ ] **D.3 README Update**
  - Add "Real-world Performance 2026" section to README.md
  - Include summary metrics from the live test (cumulative return, Sharpe, max DD vs. benchmark)
  - Link to the full final report in `docs/live-test/reports/final-report.md`
  - Update the roadmap status: Phase "Live Test" marked complete with key findings

- [ ] **D.4 Remove `docs/AI_CONTEXT.md`**
  - Once the master plan is complete and the live test infrastructure is in place, remove `docs/AI_CONTEXT.md` as requested — its contents are subsumed by the live test documentation and plan

**Exit criteria:** Final report complete. Transition plan filed. README updated. All live test documentation committed and tagged.

---

## Operational Protocols

### Daily Protocol (Automated)

1. **Data Refresh** — APScheduler triggers `scripts/fetch_history.py` -> `scripts/build_universe.py` -> `scripts/export_results.py --signals-only` after SET market close (~17:00 BKK / 10:00 UTC)
2. **Signal Computation** — Feature pipeline runs on latest data, cross-sectional ranking generated
3. **Portfolio Update** — If it's a rebalance day (last trading day of month), `ExecutionSimulator.simulate()` generates trade list; otherwise, portfolio is marked to market at latest closing prices
4. **Daily Log Generation** — Automated script produces `docs/live-test/daily/YYYY-MM-DD.md` with:
   - Regime state and any transitions
   - Portfolio NAV and day change
   - Number of symbols in universe, any data gaps
   - Scheduler job statuses
   - Any warnings or errors

### Weekly Protocol (Manual Review)

Every Saturday (or last trading day of the week):

1. Check container health: `docker compose ps`, `docker stats --no-stream`
2. Review scheduler job history: any failures or misfires in the past 7 days?
3. Review daily logs for the week: any anomalies or patterns?
4. Check disk usage: `df -h` on the data volume
5. Verify tvkit authentication is still valid (session cookies can expire)
6. Write weekly summary to `docs/live-test/weekly/YYYY-Www.md`

Weekly summary template:

```markdown
# Week YYYY-Www — Health Check

## Status
| Component | Status | Notes |
|-----------|--------|-------|
| Container | OK / WARN / DOWN | |
| Data Feed | OK / GAPS / DOWN | symbols fetched, any failures |
| Scheduler | OK / WARN / FAIL | job history summary |
| Disk | OK / WARN | usage % and trend |
| Auth | OK / EXPIRED | tvkit session status |

## Incidents
- (date) — description, impact, resolution

## Action Items
- [ ] ...
```

### Monthly Protocol (Deep Review)

By the 5th of each month:

1. Compute all performance metrics (see Metrics section below)
2. Generate charts: equity curve vs. SET TRI, drawdown plot, monthly return bars
3. Write narrative commentary: what drove performance this month? Any regime changes?
4. Compare against backtest prediction for the same period
5. Save monthly review to `docs/live-test/monthly/YYYY-MM.md`

### Significant Event Protocol

When any of the following occurs, log it immediately in `docs/live-test/events/`:

| Event | Trigger | Required Info |
|-------|---------|---------------|
| System downtime | Container exits or becomes unresponsive | Date, duration, root cause, resolution |
| Data feed failure | tvkit returns errors for > 50% of symbols | Date, affected symbols, error type, resolution |
| Model deviation | Strategy produces clearly wrong output (e.g., negative weights, 0 holdings) | Date, what was expected vs. observed, root cause, fix |
| Circuit breaker trip | DrawdownCircuitBreaker trips to TRIPPED state | Date, rolling DD level, safe-mode equity fraction applied |
| Regime transition | BULL -> BEAR, BEAR -> BULL, or NEUTRAL transitions | Date, SMA200 level vs. price, 3M return value |
| Infrastructure update | Docker image rebuild, dependency upgrade, config change | Date, what changed, why |
| Market event | SET index moves > 5% in a single day, or major news event | Date, event description, strategy response |

Event log template:

```markdown
# [Event Type]: [Brief Description]
- **Date:** YYYY-MM-DD
- **Detected by:** (automated alert / weekly review / manual observation)
- **Impact:** (what was affected — data, portfolio, reporting)
- **Root cause:** (if known)
- **Resolution:** (what was done, or planned)
- **Prevention:** (how to prevent recurrence)
```

---

## Metrics & Success Criteria

### Primary Metrics (Tracked Monthly)

| Metric | Definition | Target | Warning Threshold |
|--------|-----------|--------|-------------------|
| Cumulative Return | (NAV_t / NAV_0) - 1 | Positive, within 3pp of backtest | Negative for 3 consecutive months |
| Annualized Volatility | std(daily_returns) x sqrt(252) | <= 15% | > 20% |
| Sharpe Ratio (since inception) | mean(daily_return - rf) / std(daily_return) x sqrt(252) | >= 0.5 | < 0.3 |
| Maximum Drawdown | peak-to-trough decline | > -15% | < -10% (triggers circuit breaker review) |
| Tracking Error vs. SET TRI | std(strategy_return - benchmark_return) x sqrt(252) | <= 12% | > 18% |
| Turnover (annualized) | sum(|delta_w|) x 12 / months | <= 150% | > 200% |

### Secondary Metrics

| Metric | Definition | Purpose |
|--------|-----------|---------|
| Live vs. Backtest Return Gap | cumulative_return_live - cumulative_return_backtest | Measures out-of-sample decay |
| Win Rate | % of months with positive return | Sanity check |
| Avg. Holdings Count | mean number of positions held | Confirm portfolio construction is working |
| Sector Concentration | max sector weight at each rebalance | Verify sector cap overlay |
| Slippage Realized vs. Estimated | mean(trade_execution_price - paper_signal_price) | Calibrate slippage model |
| Data Completeness | % of trading days with successful data refresh | Infrastructure reliability |
| Circuit Breaker Trip Frequency | trips per month | Assess risk overlay calibration |

### Success Criteria for Production Readiness (Phase D)

| # | Criterion | Threshold |
|---|-----------|-----------|
| 1 | Cumulative return | Positive over the 8-month live period |
| 2 | Sharpe ratio (since inception) | >= 0.5 |
| 3 | Maximum drawdown | > -15% |
| 4 | Live vs. backtest return gap | Within +/-5pp |
| 5 | Data completeness | >= 95% of trading days |
| 6 | System uptime | >= 99% (excluding planned maintenance) |
| 7 | No unexplained model deviations | Zero instances of incorrect trade generation |
| 8 | Circuit breaker behavior matches design | Trips on real DD, recovers per spec, no false trips |

All 8 criteria must be met to recommend production deployment. Partial success (some criteria met) triggers a recommendation for a second, extended live test period rather than production.

---

## Documentation Standards

### File Naming and Location

| Content | Location | Format | Naming |
|---------|----------|--------|--------|
| Daily log | `docs/live-test/daily/` | Markdown | `YYYY-MM-DD.md` |
| Weekly health check | `docs/live-test/weekly/` | Markdown | `YYYY-Www.md` |
| Monthly review | `docs/live-test/monthly/` | Markdown | `YYYY-MM.md` |
| Significant event | `docs/live-test/events/` | Markdown | `YYYY-MM-DD-<slug>.md` |
| Charts and graphs | `docs/live-test/graphs/` | PNG or SVG | `YYYY-MM-DD-<description>.png` |
| Phase reports | `docs/live-test/reports/` | Markdown | `<report-name>.md` |
| Live settings | `configs/` | YAML | `live-settings.yaml` |

### Required Elements in Every Log

- **Timestamp:** All entries must include date and time in `Asia/Bangkok` timezone (per project standard)
- **As-of marker:** Daily logs must state the data's "as of" date clearly at the top
- **Objectivity:** Logs report facts (what happened) not opinions (what should have happened)
- **Auditability:** Every trade decision references the signal value, rank percentile, and overlay state that produced it

### Git Tracking

- All files under `docs/live-test/` are committed to git (per project rule: `docs/plans/` is git-tracked; extend this to `docs/live-test/`)
- `configs/live-settings.yaml` is committed to git (it contains no secrets)
- `.env.live` is **never** committed (contains tvkit credentials)
- Daily logs are committed weekly as a batch; monthly reviews are committed immediately

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| tvkit session expiry | Medium | High — data feed stops | Weekly auth check; document cookie refresh procedure in runbook |
| TradingView API rate limiting | Low | Medium — delayed data | Rate limit configured at 5 rps; retry with backoff already implemented |
| Container OOM during backtest | Low | High — service down | Monitor memory weekly; increase `mem_limit` if trend approaches 1.8 GB |
| SET market holiday calendar mismatch | Medium | Low — scheduler runs on non-trading day | Use SET official calendar; scheduler handles no-data gracefully |
| Strategy logic bug discovered mid-test | Low | Critical — invalidates live period | Code freeze limits this; if critical bug found, document and decide: fix + restart or continue with known issue |
| Prolonged bear market (regime stays BEAR) | Medium | Medium — strategy at 50% cash, low returns | This is expected behavior; document but don't override. The regime filter is being tested too. |
| Disk exhaustion from 8 months of daily parquet | Low | Medium — data pipeline fails | Monitor weekly; 8 months x ~200 symbols x daily bars ~= 2-4 GB, well within 10 GB budget |
| Operator unavailability (vacation, illness) | Medium | Medium — weekly checks missed | Automation handles daily operations; weekly check can be delayed up to 2 weeks; monthly review can shift by a few days |

---

## Verification

1. **Phase A verification:** Container runs for 72 hours without restart; `docker compose ps` shows healthy; `/health` endpoint returns 200; 5 consecutive daily refreshes complete without errors.
2. **Phase B verification:** Daily logs exist for every trading day; weekly checks completed each Saturday; monthly reviews contain all required metrics and charts.
3. **Phase C verification:** Event analysis covers >= 3 significant market events; slippage audit compares estimated vs. actual spreads for >= 20 trades; parameter review references live data.
4. **Phase D verification:** Final report contains all 8 success criteria with PASS/FAIL verdict; README updated; all docs committed and pushed.
