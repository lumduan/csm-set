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
- [ ] A.4 Baseline Reporting (daily log created — pending stock purchases)

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
