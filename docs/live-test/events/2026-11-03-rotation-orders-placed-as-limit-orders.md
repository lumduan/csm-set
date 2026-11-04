# Event Report — The rotations were placed as limit orders, not at ATO

**Date:** 2026-11-03 (the answer to the slippage audit's question of 2026-11-02)
**Category:** Model deviation (`docs/plans/live-test/PLAN.md` event table). Execution differs from the registered fill rule.
**Severity:** Medium for the scoring record, because the registered rule does not describe how the first scored rotation was executed. No number changes. Low for the books: the recorded prices are the broker's.
**Status:** 🟢 **CLOSED 2026-11-04 by operator ruling: the operator places every order by hand, and the strategy only takes the operator's price updates** (§Decision, and registration §12). No deviation is counted. *(It read OPEN from 2026-11-03 until the ruling.)*

---

## Summary

The slippage audit ([reports/slippage-audit.md](../reports/slippage-audit.md) §5) found that the recorded fill price equals the day's opening price in only **7 of 28** rotation fills, although an ATO order fills at the opening auction's price. Asked how the orders were placed, the operator answered on 2026-11-03:

> **Limit orders, and the securities company's summary statements match the recorded prices.**

- **The books stand.** The recorded prices are the executed prices, so the realized P/L, the published NAV series and `configs/live_portfolio.yaml` are unchanged.
- **The records say "ATO".**
  - The monthly plans and the rotation-day logs describe execution "at ATO".
  - So do registration §4 (*Fills: one ATO order per side; take what fills; no follow-up*) and operator decision D3 of 2026-09-30 (`configs/live_portfolio.yaml`, the 2026-10-01 ledger entry).
  - The word appears in 161 files under `docs/` and `configs/`, counted 2026-11-03 with `grep -rlw ATO docs configs` before this report was written.
  - Those sentences describe **the plan, not the execution.** They stay as written, and this report is their pointer.
- **The first scored rotation, 2026-11-02, was placed with limit orders.** The registered rule names ATO, and nothing in the registration says how to treat the difference. That is the operator's decision.

## What happened

What each rotation's limit execution came to against the registered rule. The ATO counterfactual is the day's opening price for the full quantity. Positive = the limit fills cost more than ATO would have. Source: `reports/slippage-audit/results.json` → `by_rotation`.

| Rotation | Fills | Fill = open | Fill = close | Limit vs ATO counterfactual (THB) |
|---|---:|---:|---:|---:|
| 2026-06-02 | 6 | 2 | 1 | +6,190.00 |
| 2026-06-04 | 1 | 1 | 0 | 0.00 |
| 2026-06-05 | 1 | 1 | 0 | 0.00 |
| 2026-07-01 | 2 | 1 | 0 | +530.00 |
| 2026-08-03 | 4 | 1 | 1 | +23,250.00 |
| 2026-10-01 | 2 | 0 | 1 | −824.00 |
| **2026-11-02** | **12** | **1** | **6** | **−18,681.00** |
| **All** | **28** | **7** | **9** | **+10,465.00** |

- **The counterfactual is approximate.** An opening auction may not absorb the order. CNT's auction on 2026-10-01 printed 500 shares at 3.36, and the book bought 18,200.
- **2026-08-03, SMT:** the stock traded at 4.80 at the open, and the buy filled at 5.80, near the day's high of 5.85. A limit buy fills at its limit or better, so this fill executed when the market had reached about 5.80. That fits an order entered or repriced later in the session. The entry time is not recorded.
- **2026-11-02:** the fills beat the opening price by 18,681.00 THB in total, which is **1.48% of NAV₀** (1,262,159.89). On the day's own tape, every recorded price traded at least 209,600 shares, and the book's order was at most 10.4% of the volume at its price (audit §5a).
- **The 2026-05-05 entry is not covered.** Its log records commission-inclusive averages, not execution prices.

## Strategy response

- **Nothing in the book changes.** No configuration, code or recorded value was edited. The scored series is the published NAV, frozen at publication (registration §5).
- **The slippage audit** records the answer. Its decision-price column is now the reference, and its vs-open column is the ATO counterfactual above (§5, §5a, §7).
- **[[TK-0278]]** carried "the ATO printed 5.80" for SMT and is corrected. Its remedy "use limit orders for the entrants" describes what was already done.
- **Deliberately not edited:**
  - **`configs/live_portfolio.yaml`**: its ledger comments say "executed at ATO" and, for 2026-08-03, "the ATO printed 5.80". A commit to `configs/` inside the scored window would read as a configuration change.
  - **The registration**: it is frozen, and a change to it is a dated amendment (§10). It is edited when the operator decides.
  - This report is the pointer for both.

## Impact

- **Books and NAV:** none.
- **Scoring:** registration §6 #7 counts four kinds of deviation:
  - a trade the §4 rules do not produce;
  - a required trade not placed;
  - a trade outside a rebalance;
  - a capital flow.
  The 2026-11-02 trades carry the plan's names and share counts. Whether an order-type difference is an instance was not written in the registration. ➡️ The operator closed it on 2026-11-04 with no deviation counted (§Decision).
- **The execution choice is large next to the score.** Against the ATO counterfactual it gained 18,681.00 THB on 2026-11-02, and it cost 23,250.00 on 2026-08-03. A judgement of that size, made outside any written rule, becomes part of what the window scores.

## Decision (operator, 2026-11-04) — CLOSED

> *"This is a live test in which I place every order myself. Close this matter. The strategy only waits for my price updates."*
> (The operator's words, translated from Thai.)

- **Neither option below was taken as written.** Execution is the operator's, by hand, outside the
  rules under test.
- The registration records the ruling as a dated amendment to §4 *Fills* (registration §12). The
  rest of that row, *"take what fills; no follow-up"*, is not addressed by the ruling and stands.
- **The fill-rule question is closed, with no deviation counted.**
- The options as they were put to the operator on 2026-11-03 are kept below as history.

## The options put to the operator on 2026-11-03 *(history — superseded by the decision above)*

Registration §10: after the 2026-10-30 evaluation the registration is frozen. A change is a dated amendment, and the verdict reports each affected criterion under the original registration, with the amended reading beside it.

| Option | What it means | What it needs |
|---|---|---|
| **A. Amend §4 Fills to a written limit-order rule** | The practice becomes the registered rule from the 2026-11-30 evaluation's rotation (2026-12-01, registration §3). 2026-11-02 is reported under the original rule, with the amended reading beside it | The rule in writing: when the orders are entered, how each limit price is set, and what happens to an unfilled remainder (D3 says take what fills, no follow-up) |
| **B. Keep ATO as registered** | The December rotation is placed at ATO. 2026-11-02 is recorded as executed outside the fill rule | Nothing new. ATO carries the auction-gap risk and thin auctions (CNT, 2026-10-01: 500 shares) |

**Recommendation: A, if the way the limits are set can be written as a rule before the 2026-11-30 evaluation; otherwise B.** Whichever rule is used has to be one a reader can apply again. Otherwise part of the score is execution judgement rather than the strategy, and on 2026-11-02 that part was 1.48% of NAV₀.

**For A, one question:** on 2026-11-02, when were the orders entered, and how was each limit price chosen?

## Follow-up

- ✅ The operator's decision: closed 2026-11-04 (§Decision). It is recorded in the registration as a dated amendment (§12).
- From the next rotation, record each fill's order type, limit price and entry time from the broker confirmation (audit §7, recommendation 5; [[TK-0565]]).
- The daily-log, weekly-report and monthly-rebalance skills describe execution "at ATO". They are umbrella files. Now that the decision is made, they should say the operator places the orders by hand. That is still to do (2026-11-04).

## Related

- [reports/slippage-audit.md](../reports/slippage-audit.md) §5 and §5a ([[TK-0571]])
- [reports/2026-10-27-forward-scoring-pre-registration.md](../reports/2026-10-27-forward-scoring-pre-registration.md) §4, §6 #7, §10
- `configs/live_portfolio.yaml`: operator decision D3, 2026-09-30
- [[TK-0278]] (order type and sizing, 2026-08-03) · [[TK-0565]] (no queryable fill record)
