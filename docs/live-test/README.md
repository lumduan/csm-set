# Live Test Documentation

> Real-world paper-trading validation of the CSM-SET Cross-Sectional Momentum strategy.
> **Period:** May–December 2026 | **Status:** Phase A — Setup & Calibration

## Quick Reference

- **Master Plan:** [docs/plans/live-test/PLAN.md](../plans/live-test/PLAN.md)
- **Configuration:** [configs/live-settings.yaml](../../configs/live-settings.yaml)
- **Environment Lock Commit:** `892e78a` (`live-test-v1.0.0`)

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

**Phase A — Setup & Calibration (May 2026)**

- [x] A.1 Environment Lock
- [x] A.2 Configuration
- [ ] A.3 Infrastructure Check (container healthy — 72h stability period started 2026-05-04)
- [x] A.4 Baseline Reporting (research report complete — 132 symbols ranked, top 10 buy list ready)

## Everyday Job Summary

| When | What | How |
|------|------|-----|
| Daily after SET close (~17:00 BKK) | Fetch OHLCV, compute signals, export rankings | `scripts/refresh_daily.py` (APScheduler in private mode) |
| **Daily — every trading day** | **Cut-loss watch:** check each position vs entry price. Flag at -7%, sell at -10% | Manual (settrad click2win) — report in daily log |
| Every Saturday | Health check: container, data feed, scheduler, disk | Manual review (you) — write weekly summary |
| Last trading day of month | Rebalance: compute volatility-target weights, generate trade list (sells + buys) | `ExecutionSimulator` (Phase 4.7) — review before ATO |
| First trading day of month | Execute rebalance at ATO + monthly performance review (metrics, charts, vs backtest) | Manual (settrad click2win for trades, write monthly review) |

## Cut-Loss Rules (Per Position)

| Rule | Threshold | Action |
|------|-----------|--------|
| Warning | -7% from entry price | Flag in daily log — prepare to exit |
| Hard Stop | -10% from entry price | **Sell immediately** — do not wait for month-end rebalance |
| Trailing Stop | After +10% gain | Raise stop to breakeven (entry price) — protect profits |

These rules operate **alongside** the portfolio-level circuit breaker (-10% portfolio DD → cap equity at 20%). Per-position cut-loss catches single-stock blow-ups between monthly rebalances.

## Key Metrics at a Glance

_Last updated: 2026-05-04_

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Cumulative Return | 0.00% | Positive | — |
| NAV | 1,000,000 THB | — | — |
| Sharpe Ratio | N/A | >= 0.5 | — |
| Max Drawdown | 0.00% | > -15% | — |
| Data Completeness | 100% (1/1 days) | >= 95% | OK |
| System Uptime | Container healthy @ 8100 | >= 99% | OK |
