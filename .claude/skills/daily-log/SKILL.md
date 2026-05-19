---
name: daily-log
description: Generate the CSM-SET live-test daily report for a target trading day, then commit and push. Reads the prior daily log for format + stable carry values, pulls NAV from db_gateway, prices from data/processed/prices_latest.parquet, SET Index via tvkit, writes docs/live-test/daily/<date>.md, commits with the docs(live-test) prefix, and pushes to origin.
argument-hint: [date YYYY-MM-DD]
disable-model-invocation: true
allowed-tools: Read Write Bash(ls *) Bash(cat *) Bash(date *) Bash(docker exec *) Bash(docker logs *) Bash(uv run python *) Bash(git add *) Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git commit *) Bash(git push *) Bash(git branch *)
---

# Daily Log Generator (CSM-SET live test)

Generates `docs/live-test/daily/<date>.md` by querying the live gateway tables, the latest price parquet, and tvkit SET Index data, mirrors the format of the most recent existing daily log, then commits and pushes.

## Inputs

- `$ARGUMENTS` — optional target trading day `YYYY-MM-DD`. If omitted, default to **today in `Asia/Bangkok`**.

## Current state

- Daily logs (newest last): !`ls /home/batt/docker/quant-trading/csm-set/docs/live-test/daily/*.md 2>/dev/null | tail -5`
- Last refresh marker: !`cat /home/batt/docker/quant-trading/csm-set/results/.tmp/last_refresh.json 2>/dev/null`
- Git status: !`cd /home/batt/docker/quant-trading/csm-set && git status --short && git branch --show-current`
- Today (Asia/Bangkok): !`TZ=Asia/Bangkok date +%Y-%m-%d`

## Workflow

### 1. Resolve the target day

- If `$ARGUMENTS` is set, treat it as the target `YYYY-MM-DD`.
- If empty, use today's date in `Asia/Bangkok` from the listing above.
- If a daily log already exists at `docs/live-test/daily/<target>.md`, stop and tell the user before overwriting.
- Identify the **prior trading day's log** (the newest existing file under `docs/live-test/daily/`) — this is both the format template and the source of stable carry values.

### 2. Confirm today's refresh has run

- Verify `results/.tmp/last_refresh.json` timestamp is the target date (BKK).
- Read the newest file in `results/.tmp/jobs/` — it's today's `data_refresh` job result. Record `job_id`, `duration_seconds`, `symbols_fetched`, `failures` for the Notes section.
- Run `docker logs csm-set-csm-1 2>&1 | grep -iE "scheduler|trigger|daily_refresh" | tail -20` to determine whether the run was the scheduled cron firing or a manual `POST /api/v1/scheduler/run/daily_refresh`. Flag in Risk Notes if manual.
- If the refresh has not run for the target date, **stop and tell the user** — do not extrapolate.
- If the parquet `data/processed/prices_latest.parquet` mtime is older than the target date (SET holiday), **stop and tell the user**.

### 3. Pull portfolio metrics from Postgres

Run these `docker exec` queries (the gateway container is `quant-postgres`):

```bash
docker exec quant-postgres psql -U postgres -d db_gateway -c "SELECT time, daily_return, cumulative_return, total_value, cash_balance FROM daily_performance WHERE strategy_id='csm-set' ORDER BY time DESC LIMIT 5;"

docker exec quant-postgres psql -U postgres -d db_gateway -c "SELECT time, total_portfolio, combined_drawdown, active_strategies FROM portfolio_snapshot ORDER BY time DESC LIMIT 5;"

docker exec quant-postgres psql -U postgres -d db_csm_set -c "SELECT time, strategy_id, equity FROM equity_curve WHERE strategy_id='csm-set' ORDER BY time DESC LIMIT 5;"
```

Pull the row at `<target> 00:00:00+00` (the gateway writes one row per trading day at UTC midnight). Record:

- `total_value` → Total NAV
- `cash_balance` → Remaining Cash
- `daily_return` → day-over-day NAV % change
- `cumulative_return` → Total Return on NAV (vs 1,000,000 start)
- `combined_drawdown` → portfolio DD (for circuit-breaker buffer)
- `equity_curve` row count and latest value → Notes section

### 4. Load closing prices for the 9 held symbols

Read `data/processed/prices_latest.parquet` with pandas. Pull the last two rows for the held tickers:

```bash
uv run python - <<'PY'
import pandas as pd
syms = ['SET:DELTA','SET:IRPC','SET:PTTGC','SET:NEX','SET:AGE','SET:HANA','SET:GUNKUL','SET:INSET','SET:JTS']
df = pd.read_parquet('data/processed/prices_latest.parquet')[syms]
last2 = df.iloc[-2:].T
last2.columns = ['prev','today']
last2['chg'] = last2['today'] - last2['prev']
last2['chg_pct'] = last2['chg'] / last2['prev'] * 100
print(last2.to_string())
print('today date:', df.index[-1])
print('prev date:', df.index[-2])
PY
```

Use these for the Portfolio Snapshot last-price column **and** the Day-over-Day Change table.

### 5. Fetch SET Index context via tvkit

```bash
uv run python - <<'PY'
from tvkit.api.chart.ohlcv import OHLCV
import asyncio
import pandas as pd

async def main():
    async with OHLCV() as o:
        bars = await o.get_historical_ohlcv('SET:SET', interval='1D', bars_count=250)
    closes = pd.Series([b.close for b in bars])
    sma200 = closes.tail(200).mean()
    cushion = (closes.iloc[-1] - sma200) / sma200 * 100
    ret3m = (closes.iloc[-1] - closes.iloc[-66]) / closes.iloc[-66] * 100
    print('today:', bars[-1])
    print('prev:', bars[-2])
    for b in bars[-5:]:
        print(b.timestamp, b.close)
    print(f'sma200={sma200:.2f} cushion={cushion:.2f}% ret3m={ret3m:.2f}%')

asyncio.run(main())
PY
```

Record: today's close, OHLC, SMA200, cushion %, 3-month return, and the last 5 closes for the 5-day SET trend bullet.

Regime is **BULL** when close > SMA200, **BEAR** otherwise.

### 6. Carry stable values from the prior log

These do **not** change between rebalances and must be read from the prior daily log's Portfolio Snapshot table — **do not recompute**:

- Shares + avg cost for each of 9 positions
- Cash: **37,699.71 THB**
- Total Cost Basis: **960,686.43 THB** (commission-inclusive — 860 THB over Σ share×cost)
- Sector groupings:
  - Energy & Utilities = IRPC + AGE + GUNKUL
  - Information & Communication Technology = INSET + JTS
  - Electronic Components = DELTA + HANA
  - Petrochemicals & Chemicals = PTTGC
  - Automotive = NEX

These stay stable until the May 29 rebalance.

### 7. Compute derived values

For each position:
- `MV = shares × today_close`
- `cost = shares × avg_cost`
- `U.PL = MV − cost`
- `U.PL % = U.PL / cost × 100`

Portfolio level:
- `Total MV = Σ position MVs`
- `Unrealized P/L = Total MV − 960,686.43` (THB)
- `U.PL % (snapshot) = Unrealized P/L / 960,686.43 × 100` ← uses commission-inclusive cost basis
- `Total NAV = Total MV + 37,699.71` → must equal `total_value` from `daily_performance`
- `Total Return on NAV = (Total NAV − 1,000,000) / 1,000,000 × 100` ← matches `cumulative_return`
- `Portfolio MV change = today MV − prior log MV` (THB and %)

Sector concentration:
- For each of the 5 sectors: `sector MV = Σ symbol MVs in sector`; `% of NAV = sector MV / Total NAV × 100`
- Cap is **35%** — flag in Risk Notes if any sector approaches.

Regime cushion: `(SET_close − SMA200) / SMA200 × 100`.

Trading-day counter: prior log's Day N + 1.

### 8. Draft narrative beats

For each section, scan the data and the prior log for these threads:

- **Day-over-Day commentary**: gainers/losers/flat counts; biggest single-symbol moves (absolute % terms); new live-test highs/lows in any position; rotation pattern vs prior session.
- **Regime State**: 5-day SET close sequence; intraday range today vs prior session; cushion delta vs prior log.
- **Sector Concentration**: each sector's % delta vs prior log with the symbol driving the move.
- **Risk Notes** (numbered): scheduler / infrastructure status if relevant; per-position drawdown updates (especially new highs/lows in U.PL); portfolio-level DD vs circuit-breaker trigger; rebalance watch list update.
- **Notes**: refresh job receipts (job_id, duration, symbols_fetched, write-back row deltas); any follow-ups for tomorrow; tvkit data-source disclaimer.

### 9. Write the report

Output to `docs/live-test/daily/<target>.md`. Mirror the section order in the most recent existing daily log:

1. Title: `# Daily Log — <date> (<Weekday>)`
2. Header block: `**As of:**` / `**Phase:**` / `**Day:**` N / `**Status:**`
3. `## Execution Summary` — typically "No trades today" until rebalance
4. `## Portfolio Snapshot` — 9-row position table + summary metrics table
5. `## Day-over-Day Change (vs <Prior Weekday> <Prior Date>)` — 9-row delta table + gainers/losers/flat tally + 1 narrative paragraph
6. `## Market Context` — SET/SMA200/regime table
7. `## Regime State` — bullet list + 1 narrative paragraph including 5-day SET trend
8. `## Sector Concentration` — 5-row sector table + 1 narrative paragraph
9. `## Risk Notes` — numbered list (typically 8–12 items)
10. `## Notes` — bulleted list with refresh receipts and meta

**Formatting rules:**
- Use `−` (U+2212) for negative numbers in headlines/narrative; ASCII `-` allowed inside tables if the prior log does it.
- Money: THB, 2 decimals, comma thousands (e.g. `953,987.71 THB`).
- Percentages: 2 decimals with explicit `+`/`−` sign in narrative.
- No emojis.
- Match the prior daily log's column widths and section ordering exactly.

### 10. Verify before committing

- `Σ position MV` must equal Portfolio Snapshot's `Total Market Value`.
- `Total NAV` must equal `total_value` from `db_gateway.daily_performance` for the target row.
- Per-symbol `U.PL %` computed against `shares × avg_cost` (NOT the commission-inclusive 960,686.43 — that's only for the portfolio-level row).
- No sector > 35% cap.
- Day counter incremented by exactly 1 vs prior log.
- Day-over-day close prices in the table match the prices parquet exactly.

### 11. Commit and push

Stage and commit with a HEREDOC commit message (mirror the recent log style — `git log --oneline -5`):

```
docs(live-test): add daily log for <target-date>

<1–2 sentences: NAV close + day change + cumulative, breadth, one standout event>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

Then `git push origin <current-branch>` (typically `live-test`).

### 12. Report back to the user

Output: commit SHA, output file path, NAV close + day change, cumulative %, one-line breadth/standout summary.

## Notes

- The skill is intentionally `disable-model-invocation: true` because it writes files, commits, and pushes — only the user should trigger it.
- **Cost basis is 960,686.43 THB** (commission-inclusive). Do not recompute it from `Σ shares × avg_cost` — that produces 959,823.00 (~860 THB short). The discrepancy is the May-5 execution commissions and is locked in until the next rebalance.
- **Cash is 37,699.71 THB**, constant through the May 29 rebalance. Use the value from the prior daily log to stay safe.
- **Sector groupings come from the prior log**, not from a SET-classification lookup. The prior logs group IRPC under "Energy & Utilities" (not the SET-official Petrochemicals & Chemicals); preserve that grouping for week-to-week consistency.
- The two portfolio-level percentages will diverge slightly once Total MV moves: **U.PL %** uses commission-inclusive cost basis (960,686.43); **Total Return on NAV** uses the 1,000,000 starting NAV. Report both — the prior log's snapshot table shows both lines.
- If the cron schedule looks suspicious (next-run timestamp wrong, container restart since last firing, manual triggers, etc.), call it out as Risk Note #1. The cron historically misfired due to `CronTrigger.from_crontab` day-of-week numbering; commit `7be6762` introduced `_trigger_from_standard_crontab()` to fix it.
- Data fetched via tvkit (TradingView, free tier) — always disclaim in the final Notes bullet.
- If a daily refresh failed (`failures > 0` in the job result) or is partial, stop and tell the user — do not write a report on incomplete data.
