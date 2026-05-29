# Event Report — Scheduler Cron Day-of-Week Misfire

**Date surfaced:** 2026-05-18 (Mon)
**Date resolved/validated:** 2026-05-21 (Thu)
**Category:** Downtime — automated data refresh did not fire on schedule
**Severity:** Medium (no data loss; manual triggers covered every session; trading unaffected)
**Status:** Resolved and validated in production

---

## Summary

The daily-refresh APScheduler cron, configured with the standard 5-field crontab
`0 18 * * 1-5` (intended Mon–Fri 18:00 BKK), was firing **Tue–Sat instead of
Mon–Fri**. The root cause was a day-of-week numbering mismatch:
`CronTrigger.from_crontab` interprets the numeric DOW field with APScheduler's
internal **0 = Monday** convention, whereas standard crontab uses **0 = Sunday**.
The `1-5` token therefore mapped to Tue–Sat. This skipped the **Monday May 18**
scheduled fire and would have skipped every subsequent Monday.

No market data was lost: every Mon–Fri session's refresh was completed via a
manual `POST /api/v1/scheduler/run/daily_refresh` until the fix was validated.

---

## Timeline

| Date | Event |
|------|-------|
| May 18 (Mon) | Scheduled 18:00 fire did **not** run (cron mapped to Tue–Sat). Detected via the logged next-run timestamp skipping Monday. Refresh triggered manually at 19:50 BKK (70.22s, 136 symbols, 0 failures). |
| May 18 | Fix committed — `7be6762` "fix(scheduler): map crontab day_of_week to APScheduler numbering", adding `_trigger_from_standard_crontab()` to convert numeric DOW tokens to day-name form (`1-5` → `mon-fri`). |
| May 19 (Tue) | Fix deployed via container restart at 19:44 BKK — *after* the 18:00 fire window, so no in-process fire to test. Refresh run manually (81.48s, 136 symbols, 0 failures). |
| May 20 (Wed) | Container was restarted in **public mode** in the morning, which silently disables the scheduler; cron skipped. Private mode restored 22:21 BKK. Refresh run manually. |
| May 21 (Thu) | **First successful unattended 18:00 BKK automated fire** on the fixed trigger (69.37s, 136 symbols, 0 failures). Next-run projection confirmed Tue–Mon coverage with no Saturday phantom and no skipped Monday. |
| May 22 (Fri) | Second clean automated fire (alongside a separate manual mid-day trigger, see related note). |
| May 25–29 | Three further consecutive clean scheduled fires; May 29 completed in 71.0s with zero retries. |

---

## Root Cause

`apscheduler.triggers.cron.CronTrigger.from_crontab()` does not use the standard
crontab Sunday-based day numbering. Its `day_of_week` field is 0=Mon … 6=Sun, so
the operator-supplied `1-5` (meant as Mon–Fri under crontab's 0=Sun) was read as
Tue–Sat. The 5-field string looked correct but mapped to the wrong days.

## Fix

`_trigger_from_standard_crontab()` (commit `7be6762`) normalises numeric
day-of-week tokens to APScheduler's day-name vocabulary before constructing the
`CronTrigger` (e.g. `1-5` → `mon-fri`), making the standard crontab string behave
as written. Verified by projecting the next 7 fire times (Tue 5/19 … Mon 5/25)
and by three consecutive clean unattended fires (May 21, 22, and 25).

## Impact

- **Data:** none lost — manual triggers covered May 18, 19, 20; all completed
  `succeeded` with 136 symbols / 0 failures.
- **Trading:** none — no trades were scheduled during the affected window; the
  strategy holds between monthly rebalances.
- **Reporting:** daily logs were produced every session.

## Model Deviation

None. Strategy logic behaved exactly as designed (hold-through, no intra-month
exits). This was an infrastructure/scheduling defect, not a model deviation.

## Follow-up / Lessons

1. **Container restart hygiene:** always restart with
   `docker compose -f docker-compose.yml -f docker-compose.private.yml up -d` —
   a plain restart lands in public mode, which silently disables the scheduler
   (the May 20 skip).
2. Scheduler is now production-ready; routine operation needs no scheduler watch.
3. Consider a startup assertion that logs the *resolved* fire weekdays so a
   day-of-week mismatch is caught immediately rather than via a skipped fire.

## Related

- Mid-day **dual-trigger** anomaly on May 22 (container restart 10:59 BKK + manual
  trigger writing a preliminary row with stale May 21 prices, later overwritten by
  the 18:00 cron) — idempotent at the row level; flagged as the likely origin of
  the gateway `cumulative_return` divergence. Tracked in the monthly review's Notes.
