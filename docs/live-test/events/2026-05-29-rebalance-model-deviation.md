# Event Report — Rebalance Model Deviation (documented exits vs systematic ranking)

**Date:** 2026-05-29 (May month-end evaluation; June 2 ATO)
**Category:** Model deviation
**Severity:** Medium (no trades placed yet; affects the June 2 rebalance decision)
**Status:** Surfaced — operator decision pending at June 2 ATO

---

## Summary

The May daily logs frame **IRPC, PTTGC, JTS** as "confirmed exits" for the June rebalance under the **Exit Rank Floor (< 35th percentile)** mechanism. When the real ranking is computed for the first time, **all three rank far above the floor** — IRPC 0.977, PTTGC 0.970, JTS 0.598 — and the engine's own `PortfolioConstructor.select()` **evicts none of the 9 holdings**. The systematic model says *hold all 9*; the daily-log plan says *cut three losers*. The two disagree.

## How it was found

The live test had **never computed a per-symbol ranking**: the daily refresh builds features only from `universe_latest`, which excludes the `SET:SET` index, so `residual_momentum` (an OLS alpha vs the index) was never produced and `features_latest.parquet` held only raw momentum. `results/signals/latest_ranking.json` was a stale (2026-04-29) IC-diagnostic, not a per-symbol rank. A full dividend-adjusted re-fetch on 2026-05-29 (authenticated tvkit, premium tier) restored the index + full history, letting the composite be rebuilt via `FeaturePipeline` → `PortfolioConstructor.select()`.

## Evidence (composite percentile rank, May 29)

| Holding | Composite pct-rank | Documented as exit? | Floor (0.35) breach? |
|---|--:|---|---|
| IRPC | 0.977 | yes | no |
| PTTGC | 0.970 | yes | no |
| JTS | 0.598 | yes | no |
| AGE | 0.735 | soft-watch | no |
| (others) | 0.955–1.000 | hold | no |

`select()` verdict: **evicted = [], retained = all 9.**

## Root cause

1. **Signal lag is by design.** The composite is dominated by 12-/6-/3-month momentum, all of which **skip the most recent month** (formation gap). IRPC/PTTGC cratered in late May, but that month is excluded from the signal, so their trailing-year strength still dominates → high rank.
2. **No stop-loss in the backtested rules.** The README is explicit: no intra-month stop, no per-position trailing/hard stop — "winners ride to the next rebalance." The only exits are rank-floor + buffer (+ a SET-index EMA100 *equity* overlay, not a per-stock exit).
3. **The live exits were discretionary.** Without a computed ranking during May, the operator reasoned from price/U.PL drawdown (IRPC −21%, PTTGC −18%, fresh lows). That is a reasonable risk overlay, but it is **not** what the model does.

## Impact

- The June 2 book differs by scenario: **Option A (systematic)** = hold 9, turnover 0%; **Option B (discretionary)** = 3-out (IRPC/PTTGC/JTS) / 3-in (KCE, EASTW, KKP), turnover ~33%. Both are laid out in `monthly/2026-05.md`.
- No capital impact yet — paper trading, no orders placed.

## Follow-up

1. **Operator decision at June 2 ATO** — strict-systematic (hold) vs discretionary risk overlay (rotate). Record the choice in the June daily logs.
2. **Fix the ranking pipeline** so the live test computes a real ranking going forward: add `SET:SET` to the fetched set in `daily_refresh` (and pass `symbol_sectors`) so `residual_momentum` and the composite are produced into `features_latest` each session. File against the gateway/refresh code.
3. **Decide whether a drawdown overlay should be formalized** into the strategy (and backtested) rather than applied ad hoc — otherwise live results will keep diverging from the backtest baseline.
4. Stop using `latest_ranking.json` (IC diagnostic) as if it were the selection composite.

## Related

- `monthly/2026-05.md` §Rebalance (Option A / Option B) and §Model-Deviation note.
- `events/2026-05-18-scheduler-cron-misfire.md` (separate infra event).
