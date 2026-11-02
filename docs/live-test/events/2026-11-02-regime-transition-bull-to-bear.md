# Event Report — The regime estimate turns BEAR for the first time

**Date:** 2026-11-02 (scored session 1 of 41)
**Category:** Regime transition (`docs/plans/live-test/PLAN.md` event table: BULL → BEAR)
**Severity:** Low for the book (no rule acts on it under the registration); recorded because PLAN requires it.
**Status:** OPEN — the regime is read again each session.

---

## Summary

**The SET closed at 1,507.20, below its 200-day SMA of 1,514.0680 (−0.4536%).** By the daily logs' definition (close above SMA200 = BULL, below = BEAR), **this is the first BEAR reading of the live test**: every daily log from 2026-05-05 to 2026-10-30 read BULL.

**The engine's own `RegimeDetector.detect()` also returns BEAR**: price below SMA200 and a 63-session return of **−7.17%**, beyond its −5% threshold. It had returned NEUTRAL on every session since 2026-10-08, because its BULL also requires a positive 63-session return.

## What happened

| Session | SET close | SMA200 | Cushion | Daily-log regime | Engine `detect()` |
|---|---:|---:|---:|---|---|
| 2026-10-28 | 1,566.10 | 1,510.1848 | +3.70% | BULL | NEUTRAL |
| 2026-10-29 | 1,544.60 | 1,511.6376 | +2.18% | BULL | NEUTRAL |
| 2026-10-30 | 1,518.59 | 1,512.9322 | +0.37% | BULL | NEUTRAL |
| **2026-11-02** | **1,507.20** | **1,514.0680** | **−0.45%** | **BEAR** | **BEAR** |

- **Five falls in a row** took the index to its lowest close since 2026-05-12, **−7.0714%** below the 2026-09-08 high.
- **The 3-month return** (66 bars, the daily logs' measure) is **−8.34%**; the engine's 63-session measure is −7.17%.
- **The cushion is the lowest since 2025-09-01**, on bars fetched back to 2024-09-09.
- The SET also sits −3.87% below its EMA100 and −0.51% below its EMA200.

## Strategy response

**None, by design.**

- **The regime filter is not one of the rules registered for the scored window** (`reports/2026-10-27-forward-scoring-pre-registration.md` §4).
- **The book is already in safe mode**: the circuit breaker tripped at the 2026-10-30 evaluation, and the 2026-11-02 ATO scaled every position to about 20% equity (`events/2026-10-30-circuit-breaker-trip.md`). On 2026-11-02 equity was **19.66%** of NAV.
- The engine maps BEAR to a 0.50 exposure scale (`RegimeDetector.position_scale`), which would be looser than the breaker's 0.20 already in force.

## Impact

- **On the book: none today.** The next month-end evaluation is 2026-11-30.
- **On reporting:** PLAN.md asks for the percentage of days in each regime and the capital deployed per regime. From today those figures have a BEAR row.
- **A BEAR → BULL crossing needs the index 6.87 points higher** (+0.46%) at today's SMA200.

## Follow-up

1. Read the regime each session in the daily logs, by both definitions while they disagree.
2. At the 2026-11-30 evaluation, report the regime beside the registered rules, as with the index-overlay condition.

## Related

- [`../daily/2026-11-02.md`](../daily/2026-11-02.md) — Regime State, Risk Note 4
- [`2026-10-30-circuit-breaker-trip.md`](2026-10-30-circuit-breaker-trip.md) — the safe mode already in force
- [`2026-09-30-ema100-fast-exit-definition-conflict.md`](2026-09-30-ema100-fast-exit-definition-conflict.md) — the index overlay, also not applied
