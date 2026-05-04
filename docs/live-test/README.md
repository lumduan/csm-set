# Live Test Documentation

> Real-world paper-trading validation of the CSM-SET Cross-Sectional Momentum strategy.
> **Period:** May–December 2026 | **Status:** Phase A — Setup & Calibration

## Quick Reference

- **Master Plan:** [docs/plans/live-test/PLAN.md](../plans/live-test/PLAN.md)
- **Configuration:** [configs/live-settings.yaml](../../configs/live-settings.yaml)
- **Environment Lock Commit:** _TBD after Phase A.1_

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

- [ ] A.1 Environment Lock
- [ ] A.2 Configuration
- [ ] A.3 Infrastructure Check
- [ ] A.4 Baseline Reporting

## Key Metrics at a Glance

_To be populated as the live test progresses._

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Cumulative Return | — | Positive | — |
| Sharpe Ratio | — | >= 0.5 | — |
| Max Drawdown | — | > -15% | — |
| Data Completeness | — | >= 95% | — |
| System Uptime | — | >= 99% | — |
