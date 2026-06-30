# Event Report — First Fully Systematic Rebalance (May deviation resolved) + persistent ranking-pipeline gap

**Date:** 2026-06-30 (June month-end evaluation; July 1 ATO)
**Category:** Model deviation (resolution) + Data quality
**Severity:** Low (rebalance now systematic; the data-quality gap is a recurring operational cost, no capital impact)
**Status:** Resolved (rebalance) / Open (pipeline fix)

---

## Summary

Two linked threads from the May rebalance close out or recur this month:

1. **The May model-deviation is resolved.** In May the documented exits (IRPC/PTTGC/JTS) were price/drawdown-driven while the systematic composite ranked them top-quartile and `select()` evicted none — model said *hold*, daily logs said *cut*. This July rebalance is the **first fully systematic one**: with all three tested exit rules applied (rank floor, buffer, **EMA100 fast-exit**) plus the liquidity screen, **exactly one holding — MCOT — trips the rules**, and it does so on three independent grounds. The deep-drawdown names IRPC (−20.56%) and PTTGC (−18.43%) are **retained on signal** (top-14% on the full composite, above their EMA100) — no discretionary override.

2. **The ranking-pipeline data gap persists.** The authoritative 6-factor composite still cannot be produced by the daily refresh — `daily_refresh` builds `features_latest` without the `SET:SET` index or sector map, so it banks only the 4 momentum factors. The composite had to be reproduced via a manual re-fetch again (as on May 29). Event `2026-05-29` follow-up #2/#4 remain open.

## How it was found

Month-end evaluation re-fetched the dividend-adjusted history through Jun 30 incl. the `SET:SET` index, rebuilt the 6-factor panel (`mom_12_1/6_1/3_1/1_0` + `sharpe_momentum` + `residual_momentum`) via `FeaturePipeline.build`, and ran `PortfolioConstructor.select()`. EMA100 was computed per holding from `prices_latest`; 63-day ADTV per name from tvkit. `features_latest.parquet` (stamped 2026-06-30 by the day's 18:01 refresh) was confirmed to carry only the four momentum columns — the same gap as May.

## Evidence (Jun 30 — holdings, composite + EMA100 + liquidity)

| Holding | Composite pct-rank | Below 0.35 floor? | Close < EMA100? | 63d ADTV ≥ 5M? | Verdict |
|---|--:|---|---|---|---|
| GUNKUL | 1.000 | no | no | yes | keep |
| EASTW | 0.992 | no | no | yes | keep |
| KCE | 0.985 | no | no | yes | keep |
| EPG | 0.977 | no | no | yes | keep |
| HANA | 0.970 | no | no | yes | keep |
| INSET | 0.962 | no | no | yes | keep |
| DELTA | 0.955 | no | no | yes | keep |
| IRPC | 0.909 | no | no | yes | **keep (buffer-protected)** |
| PTTGC | 0.871 | no | no | yes | **keep (buffer-protected)** |
| MCOT | 0.545 | no | **yes (5.10 < 5.45)** | **no (3.58M)** | **SELL** |

`PortfolioConstructor.select()` verdict (n=10, floor 0.35, buffer 0.25): **evicted = [MCOT], retained = 9.** Top eligible non-held challenger = **FORTH** (composite #8, pct 0.947, ICT, ADTV 147.7M).

## Root cause

1. **Why the deviation resolved.** The EMA100 fast-exit — not applied in May's write-up — is the systematic mechanism for drawdown-driven exits. This month MCOT is the only holding below its 100-day EMA, and it independently fails the buffer (challenger +0.40 rank-gap) and the 5M ADTV liquidity floor (3.58M). IRPC/PTTGC, despite ugly P&L, are above their EMA100 and rank top-14% on the full composite (residual + sharpe momentum lift them) — so the model holds them. The systematic rules and the risk view converge on MCOT alone.
2. **Why the data gap persists.** `daily_refresh` (`api/scheduler/jobs.py`) calls `FeaturePipeline.build(prices=fetched, rebalance_dates=...)` without `SET:SET` in the fetched set and without `symbol_sectors`, so `residual_momentum`/`sharpe_momentum` (index-dependent) and `sector_rel_strength` are never written. The fix proposed in the May event (add the index + sectors to the refresh) has not landed.

## Impact

- **Rebalance:** a clean systematic 1-out/1-in for July 1 ATO — SELL MCOT (16,700 @ ~5.10), BUY FORTH (~5,300 @ ~15.80); ~7.5% turnover; resulting SET-official sectors all ≤ 30.85%. Selling MCOT realizes ~−15,797.66 THB. No capital impact yet (paper).
- **Data quality:** every month-end still needs a manual re-fetch to compute the real ranking — an operational cost and a single point of human error, but not a capture/NAV-integrity issue.

## Follow-up

1. **Fix the ranking pipeline (carried from May, still open):** add `SET:SET` to `daily_refresh`'s fetched set and pass `symbol_sectors` so `features_latest` carries all six factors (+ `sector_rel_strength`) each session — then the composite is reproducible without a manual re-fetch. File against the refresh code.
2. **Consider formalizing the EMA100 fast-exit in the daily-log / monthly tooling** so the systematic exit set is computed automatically at month-end rather than reconstructed by hand.
3. **Watch MCOT-style liquidity decay** on remaining holdings — the 5M ADTV floor is an entry screen, but a holding decaying below it (as MCOT did) is a useful exit corroborant.
4. Continue to **stop using `latest_ranking.json`** (the stale, single-factor IC diagnostic) as if it were the selection composite.

## Related

- `monthly/2026-06.md` §Rebalance (July 1 ATO) and §Model-Deviation note (resolution).
- `events/2026-05-29-rebalance-model-deviation.md` (the precedent this report closes out).
