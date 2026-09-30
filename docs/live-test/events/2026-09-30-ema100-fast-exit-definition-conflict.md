# Event Report — "EMA100 fast exit" means two different rules, and on 2026-09-30 they disagree about the whole book

**Date:** 2026-09-30 (the September month-end evaluation)
**Category:** Model deviation — the live test's exit rule is not the rule the backtest engine implements
**Severity:** High. The rule decides the October book. Under the live test's reading it sells **one** name (MGC). Under the engine's reading, the same close cuts the book to **20% equity**, a sale of about **1.08M THB**.
**Status:** **OPEN — operator decision.** The October rotation is recommended on the live test's documented rule (SELL MGC); which definition the forward record uses is put to the operator with the pre-registration the 2026-09-11 decision left pending. The README's claim that the live exits "match the Phase 3.8 backtest design exactly" is corrected in the same commit as this report.

---

## Summary

The live test documents four exit mechanisms. Its **EMA100 Fast Exit** is written as a **per-holding** rule: *"Price < EMA100 at rebalance → Close position at rebalance"* (`docs/live-test/README.md`, the `csm-set-monthly-rebalance` procedure, and `configs/live-settings.yaml`, whose `ema100_fast_exit` comment reads *"close position if price < EMA100 at rebalance"*). It has been applied by hand at every month-end since May, and it is what evicted DELTA on 2026-08-03.

**The backtest engine has no per-holding EMA exit.** Its `EXIT_EMA_WINDOW = 100` (`src/csm/config/constants.py:62`) drives an **index** overlay: *"SET < EMA100 in BULL regime → equity scaled to safe_mode_max_equity"* (0.20). It is implemented in `src/csm/research/backtest.py::_is_fast_exit` and `src/csm/portfolio/sector_regime_constraint_engine.py`, and it is part of the Phase 3.8 configuration behind the published backtest figures. A search of `src/csm/` for every `ewm(`, `compute_ema`, `EMA` and `exit_ema` usage finds only index-level uses. The positive control — `_is_fast_exit` itself — is found by the same search.

The difference was already on record in one place: [[TK-0277]] notes that the per-holding EMA100 exit "is what actually evicted DELTA — the in-code `_is_fast_exit` is *index-level* equity scaling", and that it is one of three rules "applied by hand in the monthly plan", outside `src/csm/`. **What was not on record is the consequence**, because until 2026-09-30 the two rules had never disagreed about a trade.

## What happened on 2026-09-30

| Reading | Input at the 2026-09-30 close | Verdict |
|---|---|---|
| Per holding (live test) | MGC 6.45 vs its EMA100 7.0013 (**−7.87%**); every other holding above its own EMA100 (closest FORTH +2.54%) | **SELL MGC** |
| Index (engine) | SET **1,559.01** vs EMA100 **1,570.4464 (−0.73%)**; EMA200 1,504.1862, so the regime is BULL | **equity × 0.20** — sell about **1,081,589.66 THB**, 79.96% of every position |

EMAs are computed as the engine computes them: `RegimeDetector.compute_ema` (`ewm(span=window, adjust=False, min_periods=window)`) on the `SET:SET` series in `prices_latest.parquet` (600 points), and the verdict is `RegimeDetector.is_bull_market(index, asof, window=100)` itself, which returned **False**. The SET had also closed below its EMA100 intra-month on 2026-09-16, which was not a rebalance date and so was not evaluated.

The rank rules (floor 0.35, buffer 0.25), called through `PortfolioConstructor.select()`, retain all ten holdings on both the six- and seven-factor composites. So the two readings produce **1-out / 1-in** against **0-out and 20% equity**.

## Strategy response

- **The October rotation is recommended on the per-holding rule** (SELL MGC, BUY CNT; `monthly/2026-09.md`). It is the rule the live test has run at every rebalance, and the one the published trade record already embeds. **Changing a rule's definition at the one moment the change would alter the trade is a discretionary override.** That contaminates the comparison the live test exists to make, whichever definition turns out to be right.
- **No action was taken under the index reading**, and no trade list was sized for it beyond the magnitude above.
- **The documentation is corrected:** the live-test README's exit table no longer says the four mechanisms "match the Phase 3.8 backtest design exactly". The per-holding EMA100 rule was never in the backtest.

## Impact

- **On the October book:** decisive. It is the difference between one name rotating and roughly 80% of the book being sold.
- **On the published record to date:** four rebalances (June–September) applied the per-holding rule and never the index overlay. The index condition was **not met** at any prior month-end, but the margin fell every month: the SET closed **+9.00%** above its EMA100 on 2026-05-29, **+7.27%** on 06-30, **+6.04%** on 07-31 and **+2.46%** on 08-31, then **−0.73%** on 09-30 (each by `RegimeDetector.is_bull_market(window=100)`). So **no past trade would have differed under the index reading** — except that the backtest also never ran the per-holding rule that evicted DELTA on 2026-08-03. **That one exit is a live-only rule's decision.**
- **On any comparison with the backtest:** the live book and the Phase 3.8 book have run different exit logic since May. The difference was invisible while the index stayed above its EMA100; from 2026-09-30 it is not.

## Follow-up

1. **Operator: which definition governs the forward record** — per holding, index, or both. It belongs with the scoring pre-registration that the 2026-09-11 decision left open, so the rule is fixed **before** it next bites rather than on the day it does.
2. If the per-holding rule is kept, it is a **live-only rule with no backtest behind it**; that should be stated wherever the live results are compared with Phase 3.8.
3. If the index overlay is adopted, its first evaluation is the next month-end. The live test would then also need a decision on the **vol-scaling overlay** (enabled in the recorded configuration, not applied live), which acts on the same equity fraction.
4. `configs/live-settings.yaml` states the per-holding reading, but no code reads the file ([[TK-0566]]); whichever rule is chosen, the recorded configuration should say it in words that match the code that runs it.

## Related

- `monthly/2026-09.md` — Rebalance, Decision 1
- [[TK-0277]] — the earlier note that the per-holding rule is applied by hand outside `src/csm/`
- [[TK-0566]] — `configs/live-settings.yaml` has no code consumer
- [[TK-0570]] — which backtest baseline the production-readiness criteria compare against
