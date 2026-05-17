---
name: weekly-report
description: Generate the CSM-SET live-test weekly report from this week's daily logs, then commit and push. Use when the user asks for the weekly report, week summary, or week-end live-test write-up. Reads docs/live-test/daily/*.md for Mon–Fri, mirrors the format of the most recent docs/live-test/weekly/*.md, writes docs/live-test/weekly/<friday>.md, commits with the docs(live-test) prefix, and pushes to origin.
argument-hint: [friday-date YYYY-MM-DD]
disable-model-invocation: true
allowed-tools: Read Write Bash(ls *) Bash(git add *) Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git commit *) Bash(git push *) Bash(date *)
---

# Weekly Report Generator (CSM-SET live test)

Generates `docs/live-test/weekly/<friday>.md` by summarising the Mon–Fri daily logs, mirrors the format of the latest existing weekly report, then commits and pushes.

## Inputs

- `$ARGUMENTS` — optional Friday date `YYYY-MM-DD`. If omitted, target the most recent Friday that has a daily log under `docs/live-test/daily/`.

## Current state

- Daily logs (newest last): !`ls /home/batt/docker/quant-trading/csm-set/docs/live-test/daily/*.md 2>/dev/null | tail -10`
- Weekly reports already written: !`ls /home/batt/docker/quant-trading/csm-set/docs/live-test/weekly/*.md 2>/dev/null`
- Git status: !`cd /home/batt/docker/quant-trading/csm-set && git status --short && git branch --show-current`

## Workflow

### 1. Resolve the target week

- If `$ARGUMENTS` is set, treat it as the Friday `YYYY-MM-DD`. The week is `<friday-4d>` (Mon) through `<friday>` (Fri).
- If `$ARGUMENTS` is empty, pick the Friday from the newest 5 daily-log filenames in the listing above. The 5 files should be the consecutive Mon–Fri set.
- If a weekly report file already exists at `docs/live-test/weekly/<friday>.md`, stop and tell the user before overwriting.

### 2. Read sources

- Read all 5 daily logs for Mon–Fri of the target week from `docs/live-test/daily/`.
- Read the most recent existing file under `docs/live-test/weekly/` as the **format template**. The new report must mirror its section order, table columns, and tone.
- If a daily log for the prior Friday exists, read it too — its NAV is the week-open carry-over baseline.

### 3. Extract data points from each daily log

For each Mon–Fri day, pull from the daily log's tables:

- SET Index close, SMA200, SET vs SMA200 %, regime
- Portfolio MV, Cash, Total NAV, Unrealized P/L (THB and %), Return on NAV %
- Per-position rows (Shares, Avg Cost, Last Price, MV, U.PL %)
- Sector concentration (end-of-week sector table comes from Friday only)
- Risk-note flags, infrastructure notes, executions

### 4. Compute weekly aggregates

- **Week-open NAV** = Total NAV at the close of the prior Friday's daily log (e.g. May 8 close for the week of May 11–15).
- **Week-close NAV** = Total NAV at the target Friday's close.
- **Week P/L (THB)** = week-close NAV − week-open NAV.
- **Week P/L %** = Week P/L / week-open NAV × 100 (2 decimals).
- **Cumulative since live-test start** = week-close NAV − 1,000,000.
- **Position table U.PL** = MV at target Friday − cost basis (cost basis values are stable across the live test — copy from the prior weekly report's table for consistency).
- **Winners / Losers / Flat** = positive / negative / zero U.PL counts at the target Friday's close.
- **SET weekly change** = (target Friday SET close) − (prior Friday SET close), plus %.

### 5. Identify narrative beats

Scan the daily-log "Risk Notes" and "Notes" sections for:

- Largest single-day moves (positive and negative) — names and magnitudes
- New live-test highs/lows in NAV or single positions
- Regime changes, SMA200 cushion swings, support-zone tests
- Infrastructure milestones (cron runs, DB write-back, hook fixes)
- Replacement watch-list candidates ahead of the May 29 rebalance

### 6. Write the report

Create `docs/live-test/weekly/<friday>.md` mirroring the template's structure. Required sections:

1. Title line: `# Weekly Report — <monday> to <friday>`
2. Header block: Period, Phase, Status
3. **Week Summary** — 1 narrative paragraph + bullet list of key events
4. **Portfolio Performance** — NAV table including the prior Friday as carry-over row, then Mon–Fri; plus week-open/close NAV, week P/L, deployed capital, cash drag
5. **Position Performance** — 9-row table with cost basis from prior weekly report, Friday MV, U.PL, U.PL %; winners/losers/flat tally
6. **Market Context** — 5-day SET/SMA200/regime table; week change
7. **Sector Concentration** — Friday close breakdown
8. **Execution Notes** — note "no trades" if applicable; call out automation milestones
9. **Risk Monitor** — drawdown, circuit breaker, regime, sector, liquidity, plus key concerns (named positions)
10. **Infrastructure Health** — component table + any DB-write verification deltas
11. **Next Week Outlook** — rebalance watch list, monitoring focus, expected next daily/weekly report dates
12. **Notes** — meta paragraph

**Formatting rules:**
- Use `−` (U+2212) for negative numbers in headlines and narrative; the table column may use ASCII `-` if the template does.
- Money: THB, 2 decimals, comma thousands separators (e.g. `958,450.71 THB`).
- Percentages: 2 decimals with explicit `+`/`−` sign in narrative.
- No emojis.
- Match the prior weekly report's column widths and section ordering exactly.

### 7. Verify before committing

- Sum the position MVs and confirm they match the Friday daily log's Portfolio MV.
- Confirm Week P/L = week-close NAV − week-open NAV.
- Confirm the per-position U.PL % matches the Friday daily log row-for-row.
- Confirm no sector exceeds the 35% cap.

### 8. Commit and push

Stage and commit with a HEREDOC commit message (mirror the recent log style — `git log --oneline -5`):

```
docs(live-test): add weekly report for <monday> to <friday>

<1–2 sentence summary of week P/L, breadth, and one standout event>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

Then `git push origin <current-branch>`.

### 9. Report back to the user

Output: commit SHA, output file path, week P/L, and a one-line summary (e.g. winners/losers, biggest mover, any replacement candidates flagged).

## Notes

- The skill is intentionally `disable-model-invocation: true` because it writes files, commits, and pushes — only the user should trigger it.
- Cost basis values in the Position Performance table are stable across the live test (no mid-month trades). Copy them from the prior weekly report's table — do not recompute from share × avg-cost, which omits commissions and creates a ~860 THB discrepancy with the daily log's portfolio total. The Week 1 report has this same discrepancy; mirroring it keeps the format consistent.
- If a Monday is a SET holiday (no daily log for it), drop that row from the table and note the holiday in the Week Summary.
- The cash row is constant across the live test until the next rebalance (37,699.71 THB as of Phase A). Use the value from the Friday daily log to stay safe.
- If a daily log is missing for any day of the target week, stop and tell the user — do not extrapolate.
