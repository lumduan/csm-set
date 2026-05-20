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

- Daily logs (newest last): !`ls /home/batt/docker/quant-trading-system/strategies/csm-set/docs/live-test/daily/*.md 2>/dev/null | tail -5`
- Last refresh marker: !`cat /home/batt/docker/quant-trading-system/strategies/csm-set/results/.tmp/last_refresh.json 2>/dev/null`
- Git status: !`git -C /home/batt/docker/quant-trading-system/strategies/csm-set status --short && git -C /home/batt/docker/quant-trading-system/strategies/csm-set branch --show-current`
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

### 6. Carry stable values

`avg_cost`, `shares`, `cash`, and `entry_date` are the canonical broker-state fields; they live in `configs/live_portfolio.yaml` and **must be read from there, not parsed out of the prior daily log**. The YAML is mutated only at rebalance. Sector groupings and the portfolio-level commission-inclusive Total Cost Basis still come from the prior log because they are not stored in the YAML.

From `configs/live_portfolio.yaml` (the broker source of truth):

- **Held symbols, shares, and `avg_cost`** — parse each position from the `positions:` list. `avg_cost` is the **commission-inclusive per-share basis at 4-decimal precision**; do not round it on read. The number of positions can vary (typically 8–12 after a rebalance).
- **Cash balance** — `cash:` field. Constant between rebalances.
- **Live-test start NAV** — `starting_nav:` field (currently 1,000,000 THB).

From the most recent existing daily log:

- **Total Cost Basis (commission-inclusive)** — read from the prior log's Portfolio summary metrics table. This is the broker's authoritative aggregate (typically ~3–10 THB off from `Σ shares × avg_cost_yaml` due to 2-decimal precision in how the broker first displayed it; the broker number wins). Constant between rebalances.
- **Sector groupings** — parse the prior log's Sector Concentration table. The mapping (which symbols belong to which sector group) is fixed for the current holding period and resets at rebalance. Prior logs may group a symbol differently from the SET-official classification — preserve the prior log's grouping verbatim.

Sanity-check that the rebalance date hasn't passed without an updated YAML: if today is after the last trading day of the current month and `configs/live_portfolio.yaml` `entry_date` is older than that, stop and tell the user — the YAML and a rebalance log are needed before any further daily log can be written.

```bash
uv run python - <<'PY'
import yaml
cfg = yaml.safe_load(open('configs/live_portfolio.yaml'))
print('cash:', cfg['cash'])
print('entry_date:', cfg['entry_date'])
print('starting_nav:', cfg['starting_nav'])
for p in cfg['positions']:
    print(f"  {p['symbol']:<7} shares={p['shares']:>7}  avg_cost={p['avg_cost']:.4f}")
PY
```

### 7. Compute derived values

For each position (using the unrounded `avg_cost` from the YAML, **not** the displayed 2-decimal value the broker shows on screen):
- `MV = shares × today_close`
- `cost_basis = shares × avg_cost`
- `U.PL = MV − cost_basis` (THB)
- `U.PL % = U.PL / cost_basis × 100`

Per-symbol `U.PL %` computed this way reproduces the broker statement exactly. Both `MV` and `cost_basis` are displayed in the snapshot table; the reader can verify the math directly from the columns.

Portfolio level (let `COST_BASIS` be the prior log's commission-inclusive Total Cost Basis and `CASH` be the YAML cash balance):
- `Total MV = Σ position MVs`
- `Unrealized P/L = Total MV − COST_BASIS` (THB) ← uses broker's authoritative aggregate, not Σ per-symbol cost_basis
- `U.PL % (portfolio) = Unrealized P/L / COST_BASIS × 100`
- `Total NAV = Total MV + CASH` → must equal `total_value` from `daily_performance`
- `Total Return on NAV = (Total NAV − starting_nav) / starting_nav × 100` ← matches `cumulative_return`
- `Portfolio MV change = today MV − prior log MV` (THB and %)

If `Σ per-symbol cost_basis` (from the YAML) drifts from the prior log's `Total Cost Basis` by more than ~10 THB, note the reconciliation delta in a sub-bullet under the Portfolio Snapshot table.

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
4. `## Portfolio Snapshot` — N-row position table with columns `# | Symbol | Shares | Avg Cost | Last Price | Market Value | Cost Basis | U.PL %` (Avg Cost at 4 decimals, matches YAML; Cost Basis = shares × Avg Cost), followed by two summary subsections:
    - `### Portfolio summary` — Total Cost Basis, Total Market Value, Unrealized P/L (THB + %), Realized P/L
    - `### Account summary` — Remaining Cash, Total NAV, Total Return on NAV
   (Cash and Total NAV are deliberately split into the Account summary so they're visually distinct from the position-level aggregates.)
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
- Per-symbol `U.PL %` computed against `shares × avg_cost` where `avg_cost` is the **4-decimal commission-inclusive value from `configs/live_portfolio.yaml`** — this reproduces the broker statement's per-position `%U.PL` exactly.
- Portfolio-level `U.PL %` uses the prior log's commission-inclusive `Total Cost Basis` (broker's authoritative aggregate), not `Σ` per-symbol `cost_basis`. If the two differ by more than ~10 THB, surface it as a reconciliation note under the snapshot table.
- Position count matches the YAML's `positions:` list (unless today is the rebalance execution day, in which case the YAML has been updated and the count may have changed).
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
- **`configs/live_portfolio.yaml` is the source of truth for positions, shares, `avg_cost`, and cash.** Read these from the YAML every run — do not parse them out of the prior daily log. Sector groupings and the prior log's commission-inclusive Total Cost Basis still come from the prior log (they are not in the YAML).
- **`avg_cost` in the YAML is commission-inclusive and stored at 4 decimals.** This matches the broker's internal precision. The displayed broker `Avg` rounds to 2 decimals on screen but the broker computes `%U.PL` against the unrounded value — that's why daily logs must use the 4-decimal YAML value and not re-round it before computing per-symbol U.PL. Per-symbol `%U.PL` then reproduces the broker statement exactly.
- **Two cost-basis numbers exist in tension and both are correct:** (a) `Σ shares × avg_cost_yaml` is the per-symbol-level cost basis used for per-symbol `%U.PL`; (b) the prior log's `Total Cost Basis` is the broker's authoritative commission-inclusive aggregate and used for the portfolio-level `Unrealized P/L %`. Until the next rebalance writes both fresh from broker trade confirmations, these may differ by a few THB; surface the delta as a reconciliation note under the snapshot table.
- **Sector groupings come from the prior log**, not from a SET-classification lookup. Prior logs sometimes group a symbol differently from the SET-official sector (e.g. IRPC has historically been grouped under "Energy & Utilities" instead of the official Petrochemicals & Chemicals). Preserve the prior log's grouping for continuity.
- The two portfolio-level percentages will diverge slightly once Total MV moves: **U.PL %** uses commission-inclusive cost basis; **Total Return on NAV** uses the starting NAV (1,000,000 THB). Report both — the snapshot's Portfolio summary table shows U.PL %; the Account summary table shows Total Return on NAV.
- If the cron schedule looks suspicious (next-run timestamp wrong, container restart since last firing, manual triggers, etc.), call it out as Risk Note #1. The cron historically misfired due to `CronTrigger.from_crontab` day-of-week numbering; commit `7be6762` introduced `_trigger_from_standard_crontab()` to fix it.
- **Public mode silently disables the scheduler.** If `csm-set-csm-1` is restarted under the base `docker-compose.yml` only, `CSM_PUBLIC_MODE=true` and APScheduler is never constructed — the 18:00 BKK cron will not fire even though the container is healthy. Always restart with `docker compose -f docker-compose.yml -f docker-compose.private.yml up -d`. Flag in Risk Notes if any 18:00 BKK fire window was missed because of a public-mode restart.
- Data fetched via tvkit (TradingView, free tier) — always disclaim in the final Notes bullet.
- If a daily refresh failed (`failures > 0` in the job result) or is partial, stop and tell the user — do not write a report on incomplete data.
- **On rebalance execution day** (first trading day of each month, when the trade list from the prior month's last-trading-day plan is executed at ATO), positions in `configs/live_portfolio.yaml` change — new symbols enter, old ones exit, cash/cost basis update. Take `avg_cost` for new positions directly from the broker's executed-trade confirmations (price × commission-loaded multiplier per share, at 4 decimals) — **do not back-derive from displayed `%U.PL`**, which only works as a one-time bootstrap (see commit history for 2026-05-20). Resume normal daily logs from the next session.
