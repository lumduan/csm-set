# Event Report — Four ex-dividend restatements in five sessions rewrite banked price history; a control session decomposes three gateway defects

**Date:** 2026-08-24 → 2026-08-31 (KCE 08-24, INSET 08-25, MGC 08-26, **none 08-27**, FORTH 08-28, none 08-31)
**Category:** Data quality / model deviation (silent — no error was ever raised)
**Severity:** Medium — **no NAV, cost-basis or U.PL impact**; the damage is to three gateway *reporting* columns and to the comparability of banked history. One reported sign was flipped (FORTH, 08-28).
**Status:** **Open — characterised but not fixed.** The mechanism is now fully specified and predictive; the remaining work is a decision (restate vs. mark a cutover date), carried into September. Related: `2026-08-01-price-adjustment-never-applied.md`, which shipped the adjustment path that makes these restatements possible.

---

## Summary

Between 2026-08-24 and 2026-08-28, **four of the ten held names went ex-dividend** — KCE, INSET, MGC and FORTH. On each occasion the vendor applied a **multiplicative backward adjustment** to that symbol's entire price history, so bars the platform had already banked and published **changed after the fact**. Restatement scope across the book went from **2 of 10 names to 6 of 10 in a single week**.

The adjustment is not a defect in itself — it is correct total-return behaviour, and it is the direct consequence of the fix shipped for `2026-08-01-price-adjustment-never-applied.md`. What makes it an event is the second-order effect: **three `db_gateway` / `db_csm_set` columns are computed against endpoints that move retroactively**, so their published values are not reproducible from the values they were originally derived from.

**The most valuable session in the sequence was the one where nothing happened.** 2026-08-27 carried no corporate action, and that absence acted as a **control** which separated two causes that had been superimposed since 08-24. The resulting model was then tested out-of-sample on 08-28 (a restatement) and 08-31 (clean), and predicted all three fields correctly on both.

## How it was found

The daily-log procedure compares each session's stored prior close against **the value the prior log published**. On 2026-08-24 that check returned a mismatch on KCE — the panel's stored 08-21 close had moved. The same check fired on 08-25 (INSET), 08-26 (MGC) and 08-28 (FORTH), and returned clean on 08-27 and 08-31.

**The check is what makes the sequence legible.** Whether a corporate action has occurred is not knowable in advance, and the panel is an invalid source for a prior close after one — so the comparison is run every session regardless, and a null result is the check working rather than the check being unnecessary.

## Evidence

**1. The adjustment is multiplicative, and the factor is recoverable to nine decimal places.** For FORTH (XD 2026-08-28), two unrelated bar pairs give the same factor independently:

```
15.951841 / 16.10 = 0.9907975776
16.744479 / 16.90 = 0.9907975740
```

implying a dividend of `16.30 × (1 − 0.9907975776) = 0.15` THB/share — **795.00 THB** on the book's 5,300 shares.

**2. The THB shift on any historical row is `shares × that date's as-printed price × (1 − factor)` — NOT the flat dividend.** On 2026-08-28 this was used to *predict* the movement of the `cumulative_return` anchor before observing it:

```
5,300 × 17.80 × (1 − 0.9907975776) = 868.16
equity_curve 2026-08-03: 1,241,674.938372 → 1,240,806.779239   (−868.16)
```

Agreement to the satang, computed **forward from the factor** rather than fitted backward to the observation.

**3. The four restatement factors, by name:**

| Name | XD | Factor | Uncredited dividend |
|---|---|---:|---:|
| KCE | 2026-08-24 | 0.98914027 | 1,560.00 (2,600 × 0.60) |
| INSET | 2026-08-25 | 0.98962656 | 2,100.00 (42,000 × 0.05) |
| MGC | 2026-08-26 | 0.97018634 | 2,208.00 (9,200 × 0.24) |
| FORTH | 2026-08-28 | 0.9907975776 | 795.00 (5,300 × 0.15) |
| | | **total** | **6,663.00 THB** |

*(EPG and GUNKUL went ex-dividend earlier in the live test with their amounts also unrecovered, so the true understatement exceeds 6,663.00.)*

**4. The control session, and the two-defect decomposition.** On 2026-08-27 no held name was restated. `daily_return` then reproduced **exactly** as the pure denominator defect and carried no restatement term:

```
stored  +0.9482887%   ==  +12,464.00 / 1,314,367.70   (today's NAV — the wrong denominator)
true    +0.9573673%       +12,464.00 / 1,301,903.70   (prior NAV — correct)
```

**5. Out-of-sample confirmation on a dirty session (08-28).** With FORTH restated, the same model predicted a *different* form, and it held to nine significant figures:

```
stored  −0.003971333638  ==  (1,308,376.70 − 1,313,572.700371) / 1,308,376.70
                              ^ NAV                ^ RESTATED prior NAV      ^ wrong denominator
error decomposes as  −0.0021 pp (denominator)  +0.0608 pp (restatement)  =  +0.0587 pp
```

**The two components oppose in sign on a losing session**, which is why the 2026-08-26 log's conclusion that the field "cannot be corrected by a constant" was right.

**6. Second out-of-sample confirmation on a clean session (08-31)**, reproducing to eighteen significant figures with no restatement term: `+9,154.00 / 1,317,530.70 = 0.006947845693462778…` against a stored `0.006947845693462779`.

**7. `combined_drawdown` went SHALLOWER on a losing session (08-28)** — impossible from price action, since no new trough was made and the reported leg's endpoints both sit inside the restated window. Only a rescaling of both endpoints by different THB amounts produces it.

## Impact

- **None on NAV, cost basis or per-position U.PL.** Those use raw current prices and the YAML `avg_cost`, which is why Total NAV matched `db_gateway.daily_performance` to the satang on every session of the wave, and why the Σ-cost reconciliation delta stayed at **0.00 THB** throughout.
- **`daily_performance` is structurally append-only** (`src/csm/adapters/hooks.py:286-294`) and was never rewritten. **`equity_curve` was** — every row from `entry_date` (2026-08-03) forward moved on each restatement session.
- 🔴 **One reported sign was flipped.** On 2026-08-28 FORTH showed **−0.79% below cost** while being **+0.14% above** it on a total-return basis; the shortfall was 673.10 THB against 795.00 THB of unrecorded dividend. **The book's above/below-cost count read 8/2 and was truly 9/1.** This is the first instance of the uncredited-dividend gap changing a reported fact rather than a magnitude.
- **A three-week-old structural claim became false for an accounting reason** — "the below-cost names are exactly the two 2026-08-03 entrants" stopped holding on 08-28, not because prices moved but because a dividend went unrecorded.
- **Row-integrity checks cannot see any of this.** Row counts and midnight-stamp checks passed on every session of the wave. **Row integrity and value integrity are different properties**, and this wave separated them on four of five sessions.

## Strategy response

**None taken, deliberately.** No position was traded, no figure was hand-corrected, and no historical document was retro-edited. Adding the uncredited dividends to NAV by hand would break the reconciliation against `daily_performance` — the check that has caught every real error in this series — and restating published history would destroy the audit trail that made the mechanism recoverable in the first place.

The **2026-09-01 rebalance was evaluated on the restated panel** and returned 0-out / 0-in; the restatements did not change any exit-rule verdict.

## Follow-up

1. 🔴 **Decide restate-vs-cutover for price history.** Scope is now **6 of 10 held names**, the mechanism is fully characterised, and the decision is **no longer blocked on understanding**. A cutover date is separately what would reduce `daily_return` to a single fixable one-line bug.
2. 🔴 **Decide whether the live-test book accrues dividends.** 6,663.00 THB uncredited; there is no dividend-accrual or receivable path anywhere in the book, and `cash` is a static YAML field mutated only at rebalance.
3. **Fix `daily_return`'s denominator** — it divides by today's NAV where it should divide by the prior NAV. One line, independent of (1).
4. **Keep the mixed-basis caveat on high/low claims** for GUNKUL, INSET, EPG, MGC and FORTH until (1) is settled — their panel highs differ from the values prior logs published.
5. **Do not re-derive the TWR scale factor `k₂` from the current NAV.** It was defined against the 2026-08-03 `equity_curve` anchor of 1,247,760.70, which this wave has since moved to 1,240,806.78; re-deriving it would move published historical chart values to chase a number that itself moved. See `graphs/README.md`.
