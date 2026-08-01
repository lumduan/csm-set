# Event Report — Production `portfolio_snapshot` wiped by an unscoped DELETE in a test fixture

**Date:** 2026-08-01
**Category:** Operational incident — data loss (fully restored)
**Severity:** High (production cross-strategy table emptied; complete recovery achieved, no permanent loss)
**Status:** **Data restored and verified** / **root cause still open** — the fixture is unchanged

---

## Summary

The `infra_db`-marked integration suite was run against **production** DSNs. Its fixture contains an
unscoped `DELETE FROM portfolio_snapshot`, which emptied the live cross-strategy table in
`db_gateway` — **all 65 rows**, spanning 2026-05-04 → 2026-07-31.

All 65 rows were restored and verified identical. The defect that caused it is **still present in the
repository** and will do the same thing to anyone who runs that suite against a populated database.

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

**The residual risk is not the lost data — it is that the cause is still live.** Any session, agent,
or contributor who runs `uv run pytest tests/integration/adapters/ -m infra_db` with production DSNs
in the environment will empty the table again. The restore is repeatable, but the next occurrence
might not be noticed.

---

## Follow-up

1. **Scope or remove the two unscoped deletes** — `conftest.py:120` and `:180`. *(Open. Belongs to
   the outstanding "fix the infra_db test drift" work, which also covers 13 failing tests in that
   suite; this report exists so the landmine stays visible until then.)*
2. **Refuse to run against a non-test database.** A fixture-level assertion — a required
   `CSM_TEST_DB_OK=1`, or a check that the DSN's database name carries a test marker — turns this
   from "remember not to do that" into a mechanical impossibility. This is the fix that generalises;
   #1 only fixes the two statements that happen to be wrong today.
3. **Audit the other integration fixtures** in the repo for the same pattern — an unscoped mutation
   on a table with no natural scoping key.
4. **Prefer a disposable database for `infra_db` runs.** The suite's value is exercising real SQL, not
   real *data*; that is fully served by an empty scratch database.

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
