# Event Report — The HOME host stalled on memory compaction for 66 minutes and came back unclean; this strategy lost nothing, and two things that came back wrong are not this strategy's

**Date surfaced:** 2026-09-10 (found while writing the daily log for that session, from `docker inspect`, not from an alert)
**Event window:** 2026-09-10 **11:43:13 → 13:01:33 BKK** — stall onset to first post-boot journal entry; **65m47s** fully dark (11:55:46 → 13:01:33)
**Category:** Infrastructure — host-level stall and unclean restart (no data-integrity defect in this strategy)
**Severity for THIS strategy: LOW — measured impact NIL.** No refresh window was at risk, no row was lost, no figure in any daily log is affected, and the database recovered its own WAL cleanly.
🔴 **Severity for the PLATFORM: NOT GRADED HERE.** The outage sat **inside live trading hours for five of the six session groups** and one platform service is **still down**. Both are routed, not assessed — see §Routed.
**Status:** **Host RECOVERED 2026-09-10 13:01:33 BKK.** ⚠️ **`quant-monitor` has NOT come back and was still down 8 hours later** (§What did not come back). ⚠️ **Root cause NOT fixed** — the memory pressure that produced the stall is a standing condition, not a one-off.

---

## Summary

The HOME Docker VM (`ubuntu-docker`, 192.168.1.13) **stalled**, it did not crash and it was not
rebooted on purpose. From **11:43:13 BKK** the kernel began reporting tasks blocked in uninterruptible
sleep; the durations escalated **122s → 245s → 368s → 491s → 614s → 737s** on a single `python3`
process while `kcompactd0` — the kernel's memory-compaction daemon — blocked twice on the same path.
The last journal line is **11:55:46**. The machine returns at **13:01:33**, on a **different kernel**,
with **no shutdown record in `wtmp`**.

**csm-set was not harmed in any way that can be measured.** Its only scheduled work is the 18:00 BKK
refresh, which fired **4h58m after recovery** and returned a twenty-eighth consecutive clean run. All
three NAV rows around the event are present and correct. The container came back on its restart
policy with private mode intact.

🔑 **This report exists anyway, for three reasons, and only the first is about this strategy:**
**(1)** it is the first unplanned reboot since the 2026-08-23 service removals, and it is therefore a
**control experiment** the umbrella has been waiting for; **(2)** the outage window sat inside live
trading hours for five of six session groups, which is non-backfillable capture exposure belonging to
other sessions; **(3)** one platform service did not come back **despite `restart: always`**, and
nothing noticed for eight hours.

---

## Timeline (all times Asia/Bangkok)

| Time | Event |
|---|---|
| 11:43:13 | Stall onset — back-derived from the 737-second block reported at 11:55:30 |
| 11:51:24 | Kernel: `task python3:4172567 blocked for more than 491 seconds` |
| 11:53:27 | Kernel: `task kcompactd0:410 blocked for more than 122 seconds` — the compaction daemon joins |
| 11:55:30 | Kernel: `kcompactd0` at **245s**, `python3` at **737s**. Both in `folio_wait_bit_common` → `io_schedule` |
| **11:55:46** | **Last journal entry of boot `a2944ef8`.** Host goes dark |
| — | **65m47s with no logging of any kind** |
| **13:01:22** | Kernel boot timestamp (`uptime -s`) — now `6.8.0-139-generic`, previously `6.8.0-136` |
| 13:01:33 | First journal entry of boot `73bd9d6d` |
| 13:01:46 | `csm-set-csm-1` recorded `FinishedAt` — Docker reaps the pre-reboot container state |
| 13:01:56 | `csm-set-csm-1` `StartedAt` — restarted by `unless-stopped` |
| 13:02:03 | `quant-postgres`: *"database system was not properly shut down; automatic recovery in progress"* |
| 13:02:04 | Postgres redo `174/ED174560 → 174/F0241F68`, **1.23 s, no errors** |
| 13:02:08 | csm-set application startup; APScheduler rebuilt; `CSM_API_KEY` warning re-emitted |
| **18:00:00** | Scheduled daily refresh fires — **4h58m after recovery** |
| 18:02:04 | Refresh completes: `failures=0`, 211 symbols, `index_fetched=true` |

---

## What actually happened — a stall, not a crash, and not an OOM kill

**The distinction matters because all three leave different evidence and imply different fixes.**

Every blocked task shares one call path:

```
__schedule → schedule → io_schedule → folio_wait_bit_common → __folio_lock
           → migrate_folio_unmap → migrate_pages_batch   [kcompactd0]
```

`kcompactd0` was **compacting memory** — migrating pages to assemble contiguous blocks — and blocked
waiting for a folio lock held by something waiting on I/O. Tasks piled up behind it in `D` state.

🔑 **No OOM killer fired.** Filtering the prior boot's journal to the event window returns **zero**
`oom-kill`, `Out of memory` or `invoked oom-killer` lines. (The boot as a whole contains eight such
lines, but they are dated **2026-08-15** and **2026-08-19** — the boot ran 47 days, so an unfiltered
grep attributes old kills to this event. **The filter is the finding**: this was memory *pressure*
expressed as an I/O stall, not memory *exhaustion* expressed as a kill.)

**The standing pressure it happened under**, from `sar` on the morning of the event:

| 11:00 | 11:30 | 11:50 |
|---|---|---|
| `%commit` **385.85** | **386.55** | **386.19** |
| swap used **71.61%** | **74.89%** | **73.60%** |
| free **1,064,884 kB** | 1,123,588 kB | **627,956 kB** |

⚠️ **Commit ratio near 390% and swap at three-quarters full were the NORMAL state all morning, not a
spike.** Free memory fell to ~613 MB in the last sample before the stall. **A host running at that
commitment does not need an unusual event to stall — it needs an ordinary one.**

### The reboot was not planned, and the kernel change is a consequence rather than a cause

`linux-image-6.8.0-139-generic` was installed **2026-09-05 06:29:17**, five days before the event. It
sat unbooted until the machine came up and GRUB selected the newest kernel.

⚠️ **A reader seeing `6.8.0-136 → 6.8.0-139` across the boundary would reasonably infer a planned
kernel-upgrade reboot. It was not one.** `last -x` records **no `shutdown` entry** for 2026-09-10 —
the only one in the file is from 2026-07-25 — and Postgres independently reports the database *"was
not properly shut down"*. **Two independent sources agree the shutdown was unclean**, which is worth
more than either alone.

---

## Detection — nothing detected it; it was found by looking

🔴 **No alert fired. No watchdog reported it. The daily log's own preconditions all passed.** The
refresh had run, the parquet was fresh, the container was healthy, the DB answered.

It was found because the daily-log procedure reads `docker inspect` for container uptime, and
`StartedAt` said **2026-09-10T06:01:56Z** where five previous logs had recorded
**2026-09-01T14:09:59Z**. Everything downstream came from pulling that thread.

⚠️ **`RestartCount` still reads 0, and a reader checking that field alone would conclude nothing
happened.** The counter tracks policy-driven restarts of a *running* container; a host reboot is
invisible to it. **`StartedAt` / `FinishedAt` are the fields that show it**, and they are not the ones
a health check looks at.

🔑 **The one service whose job is to notice this is the one that did not come back** (§What did not
come back). **There was no observer, and the absence of the observer was itself unobserved for eight
hours.**

---

## Impact on csm-set — nil, and here is the evidence rather than the assertion

| Check | Result |
|---|---|
| Was a refresh window missed? | **No.** The only scheduled work is 18:00 BKK; recovery was 13:01:33 — a **4h58m** margin |
| Did the refresh run clean? | **Yes.** `failures=0`, 211 symbols, `retry_attempts_used=0`, `index_fetched=true`, 122.663 s — the **fastest of the live test** |
| Any lost NAV rows? | **No.** `daily_performance` holds 2026-09-08 / 09 / 10 = 1,292,706.70 / 1,307,517.70 / 1,305,226.70. **89 rows across 89 dates** |
| Any lost equity rows? | **No.** `equity_curve` 88 rows / 88 dates / 0 non-midnight |
| Database integrity? | **Clean.** Postgres replayed WAL `174/ED174560 → 174/F0241F68` in **1.23 s** with no `PANIC`, `FATAL` beyond the expected startup refusals, or corruption |
| Did private mode survive? | **Yes.** `CSM_PUBLIC_MODE=false`, scheduler reconstructed. **The skill's documented public-mode hazard did not bite** — a policy restart replays the create-time config, which carried the private overlay |
| Was the price panel damaged? | **No.** 941 rows, no duplicate dates, 211/211 non-null, and the live-test window is complete at 88 bars |

**No figure in any daily log is affected, and none needs restating.**

🔑 **Why csm-set was structurally safe, stated so the luck is not mistaken for design:** it is an
**end-of-day** strategy whose only time-critical dependency is a single evening cron. **An outage of
this length is survivable for csm-set at almost any hour except 18:00–18:03 BKK.** That is a property
of the strategy's cadence, not of any resilience it possesses — **the same 66 minutes at 18:00 would
have cost the session's refresh entirely**, and nothing in the design would have recovered it.

---

## What did NOT come back — and one of them matters

Three containers failed to restart. All three failed at the same instant, **13:01:46**, during the
boot storm of 25 simultaneous container starts.

| Container | Exit | Policy | Owner |
|---|---|---|---|
| **`quant-monitor`** | **128** | **`always`** | 🔴 **`session:observability`** (transferred 2026-08-30) |
| `frigate` | 255 | `unless-stopped` | outside the quant platform |
| `gallery-dl-web-backend-1` | 255 | `unless-stopped` | outside the quant platform |

`quant-monitor`'s recorded error:

```
failed to create shim task: OCI runtime create failed: runc create failed:
error during container init: failed to fulfil mount request:
send mount request cancelled: context deadline exceeded
```

🔴 **`quant-monitor` is the platform's live operator UI and host `:8900` is unbound.** Its last log
line is **11:55:58** — it was polling the gateway for `csm-set/report` when the host went dark. **It
had not come back 8 hours later.**

🔑 **AND THIS IS THE OTHER FACE OF A LESSON THE UMBRELLA ALREADY RECORDS.** [[TK-0398]] exists because
`quant-openbb` and `quant-dashboard` were *resurrected 22 seconds after the 2026-07-25 reboot* despite
being deprecated — and the lesson drawn was *"`restart:` is a statement about Docker, and Docker
wins."* **Today the same mechanism failed in the opposite direction: `restart: always` did NOT bring
back the service that was supposed to be running.** ⇒ **A restart policy is not a guarantee in either
direction.** It resurrects what you wanted gone *and* fails to resurrect what you wanted kept, and
**neither outcome announces itself.** The 2026-08-23 removals were verified today by looking; this
failure was found the same way.

⚠️ **NOT ACTED ON.** `quant-monitor` belongs to `session:observability`. Restarting it is a mutation
on another session's service and is theirs to make. **The one-line remedy, for whoever owns it:**
`cd quant-monitor && docker compose up -d`. **Risk: low.** **Recorded here because eight hours of a
dark operator UI is worth someone knowing about, not because this session intends to fix it.**

---

## Routed — the part that is NOT this strategy's, stated because it is the most consequential

🔴 **The outage window sat inside live trading hours for FIVE of the six session groups.**

Session boundaries below are from
[`docs/reference/trading-hours.md`](../../../../../docs/reference/trading-hours.md), **not from memory** —
SET ①②③ **fetched 2026-09-08** from `set.or.th`; TFEX ⓐ **measured** over 20 sessions; TFEX ⓑ
**operator-supplied 2026-08-14, not fetched**.

| Session group | Break covering the window? | Live trading lost |
|---|---|---|
| **SET ① regular equities** | Intermission 12:30–13:30 | **34m14s** (11:55:46 → 12:30) |
| **SET ② foreign-underlying, ASIA** | **NONE — continuous** | 🔴 **all 65m47s** |
| **SET ③ cross-border DRs, EUROPE/US** | **NONE — runs to 17:00** | 🔴 **all 65m47s** |
| **TFEX ⓐ EQUITY** (S50 · SSF) | Break 12:30–13:45 | **34m14s** |
| **TFEX ⓑ METAL + CURRENCY** | **NONE — straight through** | 🔴 **all 65m47s** |
| **Crypto** (24/7) | — | 🔴 **all 65m47s** |

🟢 **Recovery at 13:01:33 preceded SET ① pre-open II (13:30) by 28m27s and the TFEX ⓐ reopen (13:45)
by 43m27s**, so neither reopening was affected.

🔴 **This is non-backfillable capture exposure and it is the platform's stated top priority.** ⚠️ **It
is NOT assessed here and this session has not looked at what the capture planes actually banked.**
Whether the loss is real depends on each plane's buffering and gap-fill, which are that session's to
measure — and **"the containers are up now" is not evidence about a window that has already passed**.

**Routing:** `quant-orderbook-engine`, `quant-ticker-engine`, `quant-data-orchestrator` →
**`session:set-capture`**. `quant-crypto-engine` → its owner. The bridges
(`liberator-trading-api`, `streaming-pro-api`) came back and are `session:lib-research` /
`session:sp-research` respectively.

⚠️ **One neutral observation, offered as a starting point and not as a diagnosis:**
`quant-ticker-engine` reports `Up 4 hours` against `Up 7–8 hours` for every other capture container,
so it restarted **hours after the boot** rather than with it. **That may be routine watchdog
behaviour or it may not; this session did not investigate.**

---

## Root cause — and it is not fixed

**Proximate:** kernel memory-compaction (`kcompactd0`) blocked on a folio lock behind I/O, stalling
every task that needed page migration until the host was unusable and had to be hard-reset.

**Underlying:** the HOME box runs at **~386% memory commitment with swap three-quarters full as its
normal state**. That is the condition the daily logs and the umbrella have not been tracking, and it
is unchanged by the reboot — swap is merely empty again because the machine restarted.

⚠️ **The trigger is not identified and this report does not claim one.** The blocked `python3` process
(PID 4172567) cannot be attributed after the reboot; the PID is gone and the prior boot's process
table with it. **What can be said is the condition; what cannot be said is which workload tipped it.**

🔑 **The global operating rule this event tests, verbatim:** *"Especially important where infra
pressure threatens non-backfillable capture: an OOM or a full disk that kills a live capture destroys
data that cannot be recovered."* **This is that scenario, minus the OOM** — and the stall did what an
OOM would have done, without leaving an OOM's evidence.

---

## Resolution

**None was applied by this session.** The host recovered on its own hard reset; csm-set restarted on
its policy; the database recovered its own WAL. **No action was taken and none is proposed within this
strategy's scope**, because nothing in this strategy is broken.

---

## Follow-up

1. 🔴 **`quant-monitor` is DOWN and `:8900` is unbound** — `session:observability`. `cd quant-monitor
   && docker compose up -d`. **Not this session's to run.**
2. 🔴 **Capture-plane exposure across a 65m47s window inside live hours** — `session:set-capture` and
   the crypto owner. **Measure what was banked; do not infer it from current container state.**
3. ⚠️ **Memory pressure on the HOME box is a standing condition** (~386% commit, ~74% swap). **This is
   an infra decision for the operator**, and the umbrella's own rule asks that such observations be
   raised as soon as they are noticed rather than held.
4. ⚠️ **`RestartCount` does not show a host reboot.** Any health check or runbook that reads it as
   *"has this container been disturbed"* is answering a different question. **`StartedAt` is the field.**
5. 🟢 **The `:8100` binding recommendation is UNCHANGED and its window did not arrive.** Twenty-one
   daily logs have said *"the next recreate remains the cheapest moment to act."* **A restart is not a
   recreate** — `Created` is unchanged at 2026-09-01T14:09:41Z and port bindings are fixed at create
   time — **so this reboot could not have changed the binding whatever anyone did.**

---

## Lessons

1. 🔑 **A restart policy is not a guarantee in EITHER direction.** [[TK-0398]] recorded it resurrecting
   what should have been gone. Today it failed to resurrect what should have stayed. **Both failures
   are silent, and the correct response to both is the same: verify by looking, not by policy.**
2. 🔑 **The 2026-08-23 removals were verified by an unplanned reboot rather than argued from one.**
   `quant-openbb`, `quant-dashboard` and the tfex-s50 container are absent and ports 8500 / 3000 /
   8200 are unbound. **Same trigger as 2026-07-25, same policies, opposite outcome — because the
   containers were actually `docker compose down`ed.** *"A deprecation is not enacted until the
   container is gone"* now has a controlled test behind it.
3. ⚠️ **An unfiltered grep attributes an old event to a new one.** The prior boot ran **47 days**, so
   `journalctl -b -1 | grep oom-kill` returns August's kills as though they were today's. **Filtering
   to the window turned "there were OOM kills" into "there were none, and that is the finding."**
4. ⚠️ **Two independent sources beat one for an unclean shutdown.** `wtmp`'s missing `shutdown` record
   and Postgres's *"was not properly shut down"* agree. Either alone would have been suggestive; both
   together are conclusive, and the second came from a service that had no idea it was being asked.
5. 🔑 **A kernel version change across a reboot boundary is not evidence of a planned reboot.** The
   kernel was installed five days earlier and GRUB simply chose it. **The `dpkg.log` install date is
   what distinguishes the two readings**, and without it the natural inference is the wrong one.
6. 🔴 **csm-set survived because of its cadence, not its design.** The same outage at 18:00 BKK would
   have cost the session's refresh outright. **Recording that keeps a lucky outcome from being read as
   a robust one.**

---

## Related

- [[TK-0398]] — the 2026-08-23 stop-and-remove of `quant-openbb` / `quant-dashboard`, whose lesson
  this event tests in both directions
- [`docs/reference/trading-hours.md`](../../../../../docs/reference/trading-hours.md) — the session
  boundaries used in §Routed, with their provenance and dates
- [`daily/2026-09-10.md`](../daily/2026-09-10.md) Risk Note 2 — the same three checks in short form
- [`events/2026-09-01-dual-bar-nav-corruption.md`](2026-09-01-dual-bar-nav-corruption.md) — the
  container recreate whose uptime this event's `StartedAt` replaces
