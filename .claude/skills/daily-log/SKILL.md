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

### 4. Load closing prices for the currently held symbols

**Do not hard-code the held set.** The portfolio composition changes at every monthly rebalance — read the symbol list (and shares + avg cost) from the prior daily log's Portfolio Snapshot table. After parsing, prefix each ticker with `SET:` to match the parquet column names.

```bash
uv run python - <<'PY'
import pandas as pd, sys
# syms is parsed from the prior log's Portfolio Snapshot table — pass via argv or inline
syms = [f"SET:{s}" for s in sys.argv[1:]]
df = pd.read_parquet('data/processed/prices_latest.parquet')[syms]
last2 = df.iloc[-2:].T
last2.columns = ['prev','today']
last2['chg'] = last2['today'] - last2['prev']
last2['chg_pct'] = last2['chg'] / last2['prev'] * 100
print(last2.to_string())
print('today date:', df.index[-1])
print('prev date:', df.index[-2])
PY DELTA IRPC PTTGC NEX AGE HANA GUNKUL INSET JTS  # ← replace with symbols parsed from prior log
```

If a parsed symbol is missing from the parquet columns, stop and tell the user — a renamed/delisted ticker needs human review before the report can be written.

Use these prices for the Portfolio Snapshot last-price column **and** the Day-over-Day Change table.

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

These do **not** change between rebalances and must be read from the prior daily log — **do not recompute or assume**. They reset at each monthly rebalance (last trading day of month), so every value here must be parsed fresh from the most recent daily log:

- **Held symbols, shares, and avg cost** — parse the Portfolio Snapshot table (one row per position). The number of positions can vary (typically 8–12 after a rebalance).
- **Cash balance** — read from the prior log's summary metrics table ("Remaining Cash"). Constant between rebalances.
- **Total Cost Basis** — read from the prior log's summary metrics table. Commission-inclusive; typically a few hundred THB above `Σ shares × avg_cost`. Constant between rebalances.
- **Sector groupings** — parse the prior log's Sector Concentration table. The mapping (which symbols belong to which sector group) is fixed for the current holding period and resets at rebalance. Prior logs may group a symbol differently from the SET-official classification — preserve the prior log's grouping verbatim.
- **Live-test start NAV** — `1,000,000 THB` (truly constant; only resets if a new live test starts).

Sanity-check that the rebalance date hasn't passed without an updated log: if today is after the last trading day of the current month and the prior log still references pre-rebalance positions, stop and tell the user — a rebalance log is needed before any further daily log can be written.

### 7. Compute derived values

For each position:
- `MV = shares × today_close`
- `cost = shares × avg_cost`
- `U.PL = MV − cost`
- `U.PL % = U.PL / cost × 100`

Portfolio level (let `COST_BASIS` and `CASH` be the values parsed in step 6):
- `Total MV = Σ position MVs`
- `Unrealized P/L = Total MV − COST_BASIS` (THB)
- `U.PL % (snapshot) = Unrealized P/L / COST_BASIS × 100` ← uses commission-inclusive cost basis from prior log
- `Total NAV = Total MV + CASH` → must equal `total_value` from `daily_performance`
- `Total Return on NAV = (Total NAV − 1,000,000) / 1,000,000 × 100` ← matches `cumulative_return`
- `Portfolio MV change = today MV − prior log MV` (THB and %)

Sector concentration:
- For each sector in the prior log's Sector Concentration table: `sector MV = Σ symbol MVs in sector`; `% of NAV = sector MV / Total NAV × 100`
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
4. `## Portfolio Snapshot` — N-row position table (N = held positions from prior log) + summary metrics table
5. `## Day-over-Day Change (vs <Prior Weekday> <Prior Date>)` — N-row delta table + gainers/losers/flat tally + 1 narrative paragraph
6. `## Market Context` — SET/SMA200/regime table
7. `## Regime State` — bullet list + 1 narrative paragraph including 5-day SET trend
8. `## Sector Concentration` — sector table (rows = sectors from prior log) + 1 narrative paragraph
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
- Per-symbol `U.PL %` computed against `shares × avg_cost` (NOT the commission-inclusive `COST_BASIS` — that's only for the portfolio-level row).
- Position count matches the prior log's count (unless today is the rebalance execution day).
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
- **Never hard-code symbols, shares, avg costs, cash, total cost basis, or sector groupings.** All of these reset at every monthly rebalance — read them fresh from the prior daily log's Portfolio Snapshot, summary metrics, and Sector Concentration tables on every run.
- **Total Cost Basis is commission-inclusive** and will not equal `Σ shares × avg_cost` from the position table (typically a few hundred THB higher due to execution commissions). Use the value printed in the prior log's summary metrics row, not a re-derivation.
- **Sector groupings come from the prior log**, not from a SET-classification lookup. Prior logs sometimes group a symbol differently from the SET-official sector (e.g. IRPC has historically been grouped under "Energy & Utilities" instead of the official Petrochemicals & Chemicals). Preserve the prior log's grouping for continuity.
- The two portfolio-level percentages will diverge slightly once Total MV moves: **U.PL %** uses commission-inclusive cost basis; **Total Return on NAV** uses the 1,000,000 starting NAV. Report both — the prior log's snapshot table shows both lines.
- If the cron schedule looks suspicious (next-run timestamp wrong, container restart since last firing, manual triggers, etc.), call it out as Risk Note #1. The cron historically misfired due to `CronTrigger.from_crontab` day-of-week numbering; commit `7be6762` introduced `_trigger_from_standard_crontab()` to fix it.
- Data fetched via tvkit (TradingView, free tier) — always disclaim in the final Notes bullet.
- If a daily refresh failed (`failures > 0` in the job result) or is partial, stop and tell the user — do not write a report on incomplete data.
- **On rebalance execution day** (first trading day of each month, when the trade list from the prior month's last-trading-day plan is executed at ATO), the position table will change — new symbols enter, old ones exit, cash/cost basis update. The skill still works: parse positions/cash/cost basis from the **post-execution** rebalance log (which a human writes), then resume normal daily logs from the next session.
