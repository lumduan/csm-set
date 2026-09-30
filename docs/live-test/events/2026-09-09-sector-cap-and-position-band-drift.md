# Event Report — Two sector-cap crossings, a thirteen-session sector-floor breach and four position-ceiling sessions, all from drift and none enforced

**Date:** 2026-09-09 (first crossing) to 2026-09-30 (month-end evaluation)
**Category:** Model deviation — construction constraints breached by drift between rebalances
**Severity:** Medium. No trade was placed wrongly and no figure is wrong. The book spent most of September outside at least one of the bounds it was built to respect, with no mechanism to act before the month-end.
**Status:** **OPEN — operator decision (the "drift question").** The October rotation resolves two of the four breach types by rule. Whether the bands govern drift between rebalances, or only construction, is still undecided.

---

## Summary

The live book is built at each rebalance under three bounds: **5–15% per position**, **≤35% per sector**, and a **5% sector floor** as the live test has applied it. Between rebalances it holds **fixed share counts**. So weights move with prices, and nothing trims or tops them up until the next month-end. This is by design ([[TK-0279]]), and the daily logs record the distance to each bound every session.

September was the first month of the 2026-08-03 holding period in which **every one** of those bounds was breached, and the first with no trade at its start to reset the weights: the 2026-09-01 rebalance was 0-out / 0-in, so the book drifted from the 2026-08-03 construction for a second month.

| Constraint | Breach | Sessions in September | Deepest |
|---|---|---|---|
| Sector cap 35% | **ENERG** 2026-09-09 | 1 | **35.2791%** (3,648.81 THB over) |
| Sector cap 35% | **ETRON** 2026-09-30 | 1 | **35.0111%** (149.91 THB over) |
| Sector floor 5% | **AUTO** (MGC alone), 2026-09-14 → 2026-09-30 | **13**, consecutive | **4.3768%**, 8,448.59 THB under (09-30) |
| Position ceiling 15% | **INSET** 2026-09-03, 09-04, 09-18, 09-22 | 4 | 15.15% (09-03) |
| Position floor 5% | **MGC** — the same sessions as AUTO | 13 | 4.3768% |

Receipts: each session's Sector Concentration table and Risk Notes in `daily/2026-09-*.md`. The ENERG crossing is `daily/2026-09-09.md` Risk Note 1; the ETRON crossing is `daily/2026-09-30.md` Risk Note 7.

## What the month showed that the earlier instances did not

- **A cap can be crossed on a falling NAV.** On 2026-09-30 ETRON's market value **fell 5,980.00** and its weight still rose **+0.5174pp** past 35%, because the cap (35% of NAV) fell **13,185.20** as the book lost 37,672.00. **A sleeve's distance to its cap moves with the rest of the book**, not only with its own names.
- **The floor breach deepened on sessions when MGC did not move.** On 2026-09-28 MGC closed unchanged and the AUTO gap still widened by 441.10 THB, exactly 5% of that session's NAV gain. **A 5% floor on a shrinking position is breached further by the book's gains.**
- **Four bounds were in play at once.** On 2026-09-30 the book was simultaneously over one sector cap, under the sector floor and under the position floor, with a second name (KCE, 14.62%) 5,115.76 THB inside the position ceiling.

## Strategy response

**No discretionary trim or top-up was recommended at any point, and none was sized.** The bands are construction constraints. A hand-placed correction would be a model deviation of its own and would contaminate the comparison the live test exists to produce. Each breach was recorded daily as a distance, not a forecast.

**At the 2026-09-30 evaluation the rules resolve two of the four by construction.** MGC exits on the EMA100 rule, taking the AUTO sleeve and the position-floor breach with it. On the sizing that seats the entrant inside the band (option B in `monthly/2026-09.md`), the capital injection also brings ETRON back to **33.77%**. The engine's sector cap acts on the **constructed target, never on drifted market weight**: `backtest.py::_apply_sector_cap` caps an **equal-weight name count**, and on that basis no sector exceeded 3 of 10 names (30%) at any point in September; `sector_regime_constraint_engine.py::_apply_sector_cap` scales **target** weights. **The breaches exist only on the market-value basis the daily logs measure**, which is the basis a reader of the book experiences.

## Impact

- **No wrong trade and no wrong figure.** Every breach is visible in the published logs.
- **The live book is not the constructed book for most of every month.** Between rebalances it is a buy-and-hold of the last construction. The backtest re-weights every holding to target at each rebalance; the live test re-trades only exits and entrants. That is the `fix-notional-not-shares` question, and it makes the drift persist across a no-trade month like 2026-09-01.

## Follow-up

1. **Operator: the drift question.** Do the 5–15% band and the 35% / 5% sector bounds govern drift between rebalances, or only construction? If only construction: should a rebalance re-weight **retained** names back into the bands, as the backtest does, or trade only exits and entrants, as the live test has? [[TK-0279]]
2. **Operator: `fix-notional-not-shares`.** The October rotation shows the cost of the current practice: an exit that shrank to 4.4% of NAV cannot fund its replacement into the band without new capital.
3. If the bounds are to govern drift, a code path has to evaluate them; today the daily log is the only place they are measured.

## Related

- `monthly/2026-09.md` — Drawdown & Risk; Rebalance, Decision 2
- `monthly/2026-08.md` — the first instances (INSET outside the band on 19 of 20 August sessions)
- [[TK-0279]] — the band/drift question
