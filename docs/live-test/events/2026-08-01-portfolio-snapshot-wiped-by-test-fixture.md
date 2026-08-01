# Event Report — Production `portfolio_snapshot` wiped by an unscoped DELETE in a test fixture

**Date:** 2026-08-01
**Category:** Operational incident — data loss (fully restored)
**Severity:** High (production cross-strategy table emptied; complete recovery achieved, no permanent loss)
**Status:** **CLOSED 2026-08-01** — data restored and verified; root cause fixed and the fix proven
against the live database (see Follow-up)

---

## Summary

The `infra_db`-marked integration suite was run against **production** DSNs. Its fixture contains an
unscoped `DELETE FROM portfolio_snapshot`, which emptied the live cross-strategy table in
`db_gateway` — **all 65 rows**, spanning 2026-05-04 → 2026-07-31.

All 65 rows were restored and verified identical. The defect that caused it was **fixed the same
day** — the same invocation now refuses to run and changes nothing (see Follow-up). The narrative
below is written in the past tense of the incident; the fixture no longer behaves this way.

This was a self-inflicted error by the assistant, not a latent failure that surfaced on its own: the
suite was pointed at production deliberately, to get better verification than mocks provide, and its
fixtures were not read first.

---

## How it happened

`tests/integration/adapters/conftest.py`, in the `gateway_adapter` fixture:

```python
await pool.execute("DELETE FROM daily_performance WHERE strategy_id = $1", TEST_STRATEGY_ID)
await pool.execute("DELETE FROM portfolio_snapshot")  # wipe all test snapshots
```

The first statement is correctly scoped. The second has **no `WHERE` clause**, and
`portfolio_snapshot` is not a test table — it is the live cross-strategy snapshot the gateway
auto-emits once every active strategy has reported for a date.

Two things made it worse than a scoping slip:

- **It runs in fixture *setup*.** Every test in the affected file then failed on unrelated API drift,
  so the suite reported nothing but errors — yet the delete had already committed.
- **The comment asserts the opposite of the truth.** `# wipe all test snapshots` reads as though the
  table were test-owned. It is not.

**Why this table specifically was defenceless.** `portfolio_snapshot` has **no `strategy_id`
column** — it is cross-strategy by design, keyed on `time` alone. Every other delete in that fixture
file scopes by `TEST_STRATEGY_ID` or a run-id prefix precisely because those tables *can* be scoped.
The one table that structurally cannot be scoped is the one that was left unscoped, which is exactly
the case that warranted reading the fixture before running it.

---

## Restore

`portfolio_snapshot` is **fully derived** from `db_gateway.daily_performance`, which was untouched
(its delete was correctly scoped to the test strategy). So the table was rebuilt by **replaying the
gateway's own writer** rather than by reconstructing values by hand:

- `maybe_write_snapshot(pool, registry, now)` in
  `quant-api-gateway/src/services/snapshot_writer.py`, invoked once per affected date.
- Using the production code path means the restored rows carry the same `allocation`,
  `active_strategies`, capital-weighted return and `combined_drawdown` logic as the originals —
  there is no hand-computed value anywhere in the restored set.

**Result: 65 / 65 rows written**, 2026-05-04 → 2026-07-31.

### Verification

Six rows had been captured earlier in the same session, *before* the deletion, while reading the
table for an unrelated task. Those are the only independent record of the pre-deletion values, and
every one matches **to the last digit**:

| date | total_portfolio | combined_drawdown | match |
|---|---:|---|:--:|
| 2026-07-24 | 1,248,979.35 | −0.030594633050545883 | ✓ |
| 2026-07-27 | 1,217,741.35 | −0.03537687996987626 | ✓ |
| 2026-07-30 | 1,172,678.35 | −0.0710727180100561 | ✓ |
| 2026-07-31 | 1,226,740.35 | −0.0710727180100561 | ✓ |

`allocation` and `active_strategies` also match on all six. Because the restore is a deterministic
function of `daily_performance`, the four dates not independently captured are recovered with the
same confidence as these.

**A useful confirmation of faithfulness:** the restore also faithfully reproduced the **four phantom
holiday rows** (2026-06-01, 06-03, 07-28, 07-29) documented in
[`2026-07-31-july-data-integrity-sweep.md`](2026-07-31-july-data-integrity-sweep.md). It reproduced
the table's defects along with its data, which is what a faithful replay should do — the restore did
not quietly "improve" the history.

### Blast radius — exactly one table

Every other delete in the fixture file was audited line by line; all are scoped. Row counts
re-verified after the restore:

| Table | Rows | Note |
|---|---:|---|
| `db_gateway.portfolio_snapshot` | 65 | restored |
| `db_gateway.daily_performance` (csm-set) | 65 | untouched — scoped delete |
| `db_csm_set.equity_curve` | 60 | untouched |
| `db_gateway.strategy_report_snapshot` | 51 | untouched |
| `db_csm_set.trade_history` / `backtest_log` | 0 | already empty before the incident |

---

## Root cause

1. **An unscoped destructive statement in a fixture that can be pointed at production.** The suite
   self-skips when DSNs are unset, which makes it *look* safe by default — but that safety is
   entirely a property of the environment, not of the code. Supply production DSNs and it is armed.
2. **No guard distinguishes a test database from a production one.** Nothing in the fixture asserts
   it is talking to a throwaway. The `@pytest.mark.infra_db` marker gates *whether* the suite runs,
   never *what it runs against*.
3. **Operator error: fixtures not read before execution.** The proximate cause. Running a suite whose
   setup mutates shared state is a destructive action, and it was taken without the review a
   destructive action requires.

---

## Impact

**No permanent data loss.** The table is byte-identical to its pre-incident state on every value
that can be checked, and derivable-identical on the rest.

**No trading or capital impact.** `portfolio_snapshot` is a read-only reporting aggregate; nothing
routes orders or computes signals from it. No strategy consumed it during the outage window.

**The residual risk was never the lost data — it was that the cause stayed live.** Until it was
fixed, any session, agent, or contributor who ran
`uv run pytest tests/integration/adapters/ -m infra_db` with production DSNs in the environment would
have emptied the table again, and the restore being repeatable was no comfort: the next occurrence
might not have been noticed. That window closed the same day — the fix is verified against the live
database in Follow-up.

---

## Follow-up — all closed 2026-08-01

1. **Scope the two unscoped deletes** — ✅ **DONE.** `conftest.py` now seeds every test snapshot with
   `TEST_STRATEGY_ID` as an `allocation` key, at a deliberately odd time-of-day
   (`03:07:11.000123`), and both deletes became
   `DELETE FROM portfolio_snapshot WHERE allocation ? 'test-csm-set'`. The odd time-of-day matters as
   much as the marker: `uq_portfolio_snapshot_time` is unique on `time` **alone** and production
   writes only midnight buckets, so a test row can no longer *overwrite* a production row either.
2. **Refuse to run against a non-test database** — ✅ **DONE**, though not by either mechanism
   proposed above. A DSN-name check would break the CI job, which legitimately uses
   production-looking DSNs against a throwaway stack; a `CSM_TEST_DB_OK=1` opt-in is one line in a
   local `.env` away from being permanently disabled, which is close to how this incident happened.
   Instead `_assert_no_foreign_snapshots` keys on the invariant actually being protected — *"does
   this table hold rows I did not create?"* — and fails the test rather than deleting them.
3. **Audit the other integration fixtures** — ✅ **DONE.** Swept every `DELETE`/`TRUNCATE`/
   `delete_many` under `tests/`. The two `portfolio_snapshot` statements were the only unscoped ones;
   everything else keys on `strategy_id` or a `run_id` prefix. Confirms the original blast-radius
   finding rather than extending it.
4. **Prefer a disposable database** — ✅ **enforced, not merely recommended.** The guard now makes a
   populated database fail fast, so this is a property of the code instead of a discipline someone
   has to remember.

### The fix is proven, not merely wired

Re-running the suite with `CSM_DB_GATEWAY_DSN` pointed **deliberately at production** — the exact
invocation that caused this incident — now yields **19 errors and zero mutations**:

```
production portfolio_snapshot BEFORE : 65 rows, sum=70846854.34
  -> pytest ... -m infra_db  =>  16 passed, 19 errors
     "Refusing to run: portfolio_snapshot holds 65 row(s) this suite did not create."
production portfolio_snapshot AFTER  : 65 rows, sum=70846854.34
```

`daily_performance` (65), `strategy_report_snapshot` (51) and `equity_curve` (60) were likewise
unchanged, and no `test-csm-set` rows were left behind. Against disposable databases the same suite
is **35 passed, 0 failed** (was 13 failed).

**The guard also caught a real bug during its own development** — the first seed helper passed
`json.dumps(allocation)` into a column whose asyncpg codec already encodes dicts, double-encoding the
value into a JSON *string*. `allocation ? key` then matched nothing, cleanup silently skipped the
row, and the next test's guard reported it as foreign. A guard that only ever passes proves nothing;
this one failed loudly on a genuine defect on its first run.

---

## Lessons

- **A suite that "self-skips when unconfigured" is not a safe suite.** Its safety lives in the
  environment, and the environment is one export away from arming it.
- **The table that cannot be scoped is the table to check first.** The absence of a `strategy_id`
  column on `portfolio_snapshot` was visible before the run and is precisely what made the blast
  radius global.
- **A comment is not evidence.** `# wipe all test snapshots` asserted a fact about the data that was
  false, and reading it as reassurance would have been the same mistake as not reading it at all.
- **Verified recovery beats assumed recovery.** Replaying the production writer, then diffing against
  independently-captured pre-incident values, is what turns "it should be fine" into a checkable
  claim.

---

## Related

- [`2026-07-31-july-data-integrity-sweep.md`](2026-07-31-july-data-integrity-sweep.md) — the phantom
  holiday rows this restore faithfully reproduced.
- `tests/integration/adapters/conftest.py` — lines 120 and 180 (unchanged as of this report).
- `quant-api-gateway/src/services/snapshot_writer.py` — `maybe_write_snapshot`, the writer used to
  restore.
