# Event Report — The circuit breaker trips at the October evaluation close

**Date:** 2026-10-30 (the October month-end evaluation, the first under the forward scoring pre-registration)
**Category:** Risk overlay — the design circuit breaker trips for the first time in the live test
**Severity:** High. Under the registration the book is scaled to **20% equity** at the 2026-11-02 ATO, which sells about 80% of every continuing position.
**Status:** **OPEN — the trade list is a plan.** Nothing is placed until the operator places it, and `configs/live_portfolio.yaml` changes only after fills. The plan and the five points of interpretation it rests on are in [`../monthly/2026-10.md`](../monthly/2026-10.md).

---

## Summary

The registration (`reports/2026-10-27-forward-scoring-pre-registration.md` §6 #8, `cc7bcb1`; confirmed *"keep"* 2026-10-29, `4606aa4`) defines the circuit breaker as the design rule in `configs/live-settings.yaml`:

- a 60-session rolling drawdown;
- trip at −10%;
- recovery past −5%, held for 21 sessions;
- 20% equity in safe mode.

The breaker is evaluated by running `csm.portfolio.DrawdownCircuitBreaker` with those parameters on the published NAV series. A TRIPPED state at the evaluation close scales the book to 20% equity at the ATO.

**At the 2026-10-30 close the procedure returned TRIPPED.** NAV closed at **1,262,159.89 THB**, **−10.7057%** below the 1,413,483.89 peak of 2026-10-07, which sits inside the 60-session window. The equity fraction is **0.20** and the state changed from NORMAL. **Negative control:** the same call on the series to 2026-10-29 returns NORMAL at −8.3929%.

## What happened

| Session | NAV close | Change | 60-session rolling drawdown | State |
|---|---:|---:|---:|---|
| 2026-10-27 | 1,323,719.89 | +784.00 | −6.3505% | NORMAL |
| 2026-10-28 | 1,340,332.89 | +16,613.00 | −5.1752% | NORMAL |
| 2026-10-29 | 1,294,851.89 | −45,481.00 | −8.3929% | NORMAL |
| **2026-10-30** | **1,262,159.89** | **−32,692.00** | **−10.7057%** | **TRIPPED** |

- **Two sessions, −78,173.00.** On 2026-10-29 nothing in the book rose (0 up, 9 down, 1 flat). On 2026-10-30 one name rose (1 up, 8 down, 1 flat).
- **The market fell too.** The SET fell −1.3728% and then −1.6839%, to its lowest close since 2026-05-19, closing only +0.3740% above its SMA200.
- **The 2026-10-29 daily log had put the trip level at 1,272,135.50**, a further −1.7544%. The close came in 9,975.61 THB below it.
- **This is the first trip of the live test.** The previous deepest drawdown was −7.11% (2026-07-30), against the same −10% rule.

## Strategy response

The month-end evaluation applied the registered rules in order (`monthly/2026-10.md`, Rebalance):

1. **Rank rules** (`PortfolioConstructor.select()`, six-factor, floor 0.35, buffer 0.25): **EASTW evicted** by the buffer.
2. **EMA100, per holding:** **EASTW** (−10.36%) and **FORTH** (−5.71%) are below their own EMA100 and are sold.
3. **Entrants**, under the 63-day ADTV ≥ 5M floor and the 35% sector cap at construction: **SPRC** and **RCL**. SSP and BBGI would have taken ENERG over 35%.
4. **Circuit breaker TRIPPED:** the constructed book is scaled to **20% equity**. Every continuing position keeps 20% of its shares, floored to a 100-share lot. The entrants are bought at 20% of their construction size, and the exits are sold in full.

At the 2026-10-30 close as indicative prices, equity falls to about **19.55% of NAV** and cash rises to about **1,013,626.89 THB**. Fees come to about **1,809.00**, and the sales realize about **+181,319.53**. **Fills will differ; the executed figures come from the broker confirmations.**

## Impact

- **On the scored window (2026-11-02 to 2026-12-30): it will very likely be run in safe mode.**
  - Recovery needs the 60-session rolling drawdown back above −5%. The 2026-10-07 peak stays inside the window through 2026-12-30, 55 sessions after it, so NAV would have to reach **1,342,809.70**.
  - From a book about 80% in cash, that needs the equity sleeve to rise by roughly a third.
  - The window's return, volatility and Sharpe will therefore describe a mostly-cash book. The registration's §9 power statement applies with extra force.
- **On criterion 8 (breaker behaviour matches design): the trip path is now exercised**, on a real drawdown. Whether it "recovers per spec, no false trips" is for the window to show.
- **On realized P/L:** the scaling realizes a large part of the unrealized gain. At indicative prices the cumulative realized P/L moves from −88,456.67 to about **+92,862.86**.
- **On the position band and sector cap:** in safe mode every position is 0.86–2.86% of NAV, below the 5% floor. The registration binds the bands at construction on the names being traded, and every name trades in this rotation, so the floor and the breaker conflict. The plan lets the breaker govern; this is interpretation I5 in the October review, for the operator to confirm.

## Follow-up

1. **Operator:**
   - place the 2026-11-02 ATO orders, or say which interpretation (I1–I5 in the October review) differs;
   - report the fills, which update `configs/live_portfolio.yaml`.
2. **Thread the breaker state once per session** in the daily logs (TRIPPED → RECOVERING → NORMAL needs 21 consecutive sessions above −5%). Trades happen only at month-end evaluations.
3. **Phase C reports** (`reports/slippage-audit.md`, `reports/parameter-review.md`) fall due with this month-end. The slippage audit should measure this rotation's fills ([[TK-0571]]).

## Related

- [`../monthly/2026-10.md`](../monthly/2026-10.md) — the evaluation, the trade list, interpretations I1–I5
- [`../reports/2026-10-27-forward-scoring-pre-registration.md`](../reports/2026-10-27-forward-scoring-pre-registration.md) — §6 #8, §4, §8
- [`../daily/2026-10-30.md`](../daily/2026-10-30.md) — Risk Note 8
- [`2026-09-30-ema100-fast-exit-definition-conflict.md`](2026-09-30-ema100-fast-exit-definition-conflict.md) — the index overlay. It is condition-met again (SET −3.22% below its EMA100) and is not applied.
