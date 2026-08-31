# Event Report — SET holiday-calendar endpoint outage; fixed by moving it off the refresh critical path

**Date:** 2026-08-17 → 2026-08-26 (first failure 08-17; five consecutive failures 08-19 → 08-25; fix deployed 08-25; resolved 08-26)
**Category:** Downtime — third-party dependency
**Severity:** Low — **operational impact nil throughout.** The committed 20-closure fallback resolved every failing session correctly; no refresh was missed, no trading day was misclassified, and no figure in any daily log was affected.
**Status:** ✅ **RESOLVED 2026-08-26** by `452ba69` (`feat(calendar): opportunistic SET holiday poller off the refresh critical path`, PR #36), deployed 2026-08-25 14:52:10 UTC. Four consecutive clean sessions since.

---

## Summary

The upstream SET holiday-calendar endpoint became unreliable in mid-August: it failed on 2026-08-17, succeeded once on 08-18, then **failed five consecutive times from 08-19 through 08-25**. Because the calendar was fetched **on the 18:00 refresh's critical path**, each failure was a single-shot attempt at a fixed time — if the endpoint was unavailable at 18:00, the refresh got nothing, regardless of whether it was available at 17:30 or 18:30.

**The resolution was not the endpoint recovering.** It was a design change: an **opportunistic 30-minute poller** that runs independently of the refresh and banks the calendar whenever the endpoint happens to answer. The refresh now reads a banked cache and never contacts the endpoint itself.

## How it was found

Ordinary daily-log infrastructure monitoring. The pattern was mis-read twice before it was read correctly, and that is the part worth recording:

- **2026-08-19** described availability as *"intermittent, roughly alternating"*.
- **2026-08-20** withdrew the alternation sub-claim after a second consecutive failure.
- **2026-08-21** noted a third consecutive failure made *"sustained outage"* a live alternative to *"intermittent"*, and — importantly — **set a threshold in advance**: *"The thing to watch is Monday 2026-08-24 — a fourth consecutive 401 should be treated as an outage and investigated, not logged."*

**Every pattern read into the sequence failed within four sessions of being proposed, twice, in opposite directions.** The stable statement was the narrow one: availability is intermittent, uncorrelated with anything the system controls, and unpredictable.

## Evidence

**1. The failure sequence.** Success 2026-08-18; failures 08-17, 08-19, 08-20, 08-21, then a **fourth consecutive** on 08-24 and a **fifth** on 08-25 — meeting the threshold the 08-21 log had set in advance.

**2. The fix, and its first success.** Container recreated 2026-08-25 14:52:10 UTC (`RestartCount=0`, `CSM_PUBLIC_MODE=false`). The new poller banked the live calendar the next morning:

```
2026-08-26 11:52 BKK  holiday poll BANKED 2026 for the first time — 20 closure(s)
2026-08-26 16:52 BKK  refreshed
2026-08-26 18:00 BKK  SET holiday calendar for 2026-08-26 resolved from the banked cache (20 closures)
                      committed 2026 fallback table matches the live calendar (20 closures)
```

**3. Four consecutive clean sessions since** — 08-26, 08-27, 08-28, 08-31 — each resolving from the banked cache with the committed fallback matching, giving a **third through sixth independent validation** of that fallback (after 2026-08-13 and 08-18).

**4. ⚠️ A counting caveat discovered 2026-08-28, recorded so it is not re-learned.** A naive `grep -c 401` over the container log returns **73 hits and means nothing** — every one is a timestamp substring (`11:00:46.401034`, `08:22:53.401000`, a `233.401` duration). A targeted `grep -cE 'HTTP 401|status.?401|401 Unauthorized'` returns **0** on the current container. **The failure counts above were sourced from the calendar logger's own lines, not from a raw grep** — but the container carrying that history was replaced on 08-25, so they are no longer independently re-checkable from this side.

**5. An evidential correction made 2026-08-27.** The 2026-08-26 log stated the container *"ran ~14 hours after recreation before a poll succeeded, so the 401s continued and the poller simply outlasted them."* The first half is observable from timestamps. **The second half was an inference stated as fact** — the poller emits no failure line at INFO, so the outcome of the intervening polls is not recorded anywhere and "the 401s continued" cannot be read off the log. The conclusion is unaffected; only the evidence for one clause of it was weaker than stated.

## Impact

**Nil, operationally.** Every failing session resolved correctly from the committed 20-closure fallback table. No refresh was skipped, no trading day was misclassified as a closure or vice versa, and no NAV, return or ranking figure in any August daily log depends on the endpoint. **The fallback being the safe default is the point of the design** — it carried four of five sessions in the worst week without incident.

The one real cost was **diagnostic**: for four sessions the daily logs carried a degraded-component row and three successive attempts to characterise a pattern that did not exist.

## Strategy response

No trading response — the component has no path to a position. The engineering response was to **remove the dependency from the critical path rather than harden the call**, on the reasoning that a fixed-time single-shot fetch against an endpoint with unpredictable availability will fail at a rate set entirely by the endpoint. A 30-minute opportunistic poller converts that into an eventual success and decouples it from the 18:00 deadline.

## Follow-up

1. **Capture the 2027 holiday table from 2027-01-01.** The banked cache and the committed fallback both cover 2026 only; the same failure in January 2027 would have no fallback to fall back to.
2. **Consider emitting a WARNING on poll failure.** The poller is silent when it fails, which is what made the 2026-08-26 inference unverifiable. A single line per failed poll would make the next outage measurable rather than inferable.
3. **Prefer the calendar logger's own lines over `grep 401`** when counting failures — see Evidence 4.
