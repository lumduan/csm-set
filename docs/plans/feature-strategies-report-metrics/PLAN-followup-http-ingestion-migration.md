# Follow-up — strategies/csm-set — Migrate gateway write-back to HTTP ingestion contract

| Field | Value |
|---|---|
| Track | Follow-up to `feature-strategies-report-metrics` (post-Phase 1) |
| Date | 2026-05-21 |
| Author | Claude (Opus 4.7), acting on lumduan's behalf |
| Branch | `feat/http-ingestion-migration` |
| Target | `main` |
| Linked roadmap | `../../../plans/feature-strategies-report-metrics/ROADMAP.md` |
| Companion plans | `quant-api-gateway/docs/plans/feature-strategies-report-metrics/PLAN-followup-strategy-type-field.md`, `quant-dashboard/docs/plans/feature-strategies-report-metrics/PLAN-followup-strategy-type-verification.md` |
| Plan file location (in repo) | `docs/plans/feature-strategies-report-metrics/PLAN-followup-http-ingestion-migration.md` |

---

## Context

The umbrella `CLAUDE.md` defines a **standard ingestion contract** that
every Strategy Service is expected to use:

```
POST /api/v1/ingest/daily-report
Header: X-API-Key: $INTERNAL_API_KEY
{
  "strategy_metadata":   { "id", "type", "last_updated" },
  "performance_metrics": { "daily_pnl", "equity_curve": [...],
                           "max_drawdown", "sharpe_ratio" },
  "current_exposure":    { "total_value", "cash_balance", "positions_count" },
  "extended_data":       { ... }   // strategy-specific (e.g. report block)
}
```

csm-set's current implementation does **not** use this contract. Phase 4
of csm-set's own roadmap shipped `GatewayAdapter`
(`src/csm/adapters/gateway.py`), which connects to `db_gateway` via the
DSN `settings.db_gateway_dsn` and writes directly to:

- `daily_performance` (via `write_daily_performance`)
- `portfolio_snapshot` (via `write_portfolio_snapshot`)

The post-refresh hook (`src/csm/adapters/hooks.py` lines 183–215) already
builds the per-strategy `StrategyReport` payload (Phase 1 of
`feature-strategies-report-metrics`) and attaches it to
`live_metrics.report`. However, `GatewayAdapter.write_daily_performance`
**never writes to `strategy_report_snapshot`** — it logs whether a
`report` field is present (line 211) and then silently drops it. The
result is that the gateway's `strategy_report_snapshot` table stays
empty, the dashboard's report tab returns
`404 — no strategy_report_snapshot for 'csm-set'`, and the Phase 3
read-side endpoints have nothing to serve.

The straightforward fix (add a `write_strategy_report` method to
`GatewayAdapter`) would close the data gap but double down on a deeper
architectural problem: csm-set holds a writeable DSN to a database owned
by another service. The right fix is to migrate the write-back path to
the documented HTTP contract — which the gateway has already implemented
end-to-end (its `services/ingestion.py::persist_daily_report` does the
dual UPSERT `daily_performance` + `strategy_report_snapshot` inside one
`conn.transaction()`).

Migrating to HTTP gives us:

| Concern | Direct DSN (today) | HTTP POST (target) |
|---|---|---|
| Schema validation | Silent until SQL error in prod | Pydantic validates at the door |
| Audit trail | Scattered DB writes | One ingress, one structured log per report |
| Auth | DB password = god mode on `db_gateway` | `X-API-Key` per strategy, revocable |
| Adding TFEX next quarter | Teach each strategy the SQL | TFEX just POSTs JSON; gateway owns its tables |
| Ownership | `db_gateway` writers = csm-set + gateway | `db_gateway` writers = gateway only |
| Atomicity (perf + report) | Two separate writes (today: one is missing) | One `conn.transaction()` server-side |
| Idempotency | Per-table UPSERT in client code | Already handled at endpoint |

Trade-off: one HTTP round-trip per refresh hook (we ship daily, not
high-frequency — negligible). The migration is one network call,
auth handling, and removal of write-side `GatewayAdapter` surface.

---

## Scope

### In scope

1. **`src/csm/adapters/gateway_client.py`** (new) — async HTTP client
   that owns one shared `httpx.AsyncClient`, posts the contract payload,
   handles retries with exponential backoff (max 3 attempts), and
   surfaces typed errors. Idempotent semantics: re-posting the same date
   is safe because the gateway UPSERTs.
2. **`src/csm/adapters/payload.py`** (new) — pure function
   `build_ingestion_payload(strategy_id, today, live_metrics, snapshot)`
   that assembles the four required blocks
   (`strategy_metadata`, `performance_metrics`, `current_exposure`,
   `extended_data`) from already-existing inputs. `extended_data.report`
   is populated from `live_metrics.report` when present.
3. **`src/csm/config/settings.py`** —
   - **add** `gateway_base_url: str` (e.g. `http://quant-api-gateway:8000`,
     required when `gateway_enabled` is true; documented in `.env.example`)
   - **add** `gateway_api_key: SecretStr` (the shared `INTERNAL_API_KEY`)
   - **deprecate** `db_gateway_dsn` — mark optional with a deprecation
     note. Keep it around for the **read-side** methods (see "Out of
     scope" + "Risks" below), but emit a `DeprecationWarning` when the
     write methods are still constructed.
4. **`src/csm/adapters/hooks.py`** — replace the two `manager.gateway.write_*`
   calls in `post_refresh` with a single
   `await manager.gateway_client.post_daily_report(payload)`. The new
   client is tolerant of transient 5xx (3 retries); 4xx surfaces as an
   error that we log + skip but do not raise (matches the existing
   "non-fatal write-back" semantics).
5. **`src/csm/adapters/__init__.py`** — the `AdapterManager` factory
   gains `gateway_client` alongside (or instead of) `gateway`. The
   factory inspects settings: if `gateway_base_url` is set, build the
   HTTP client; the legacy `gateway` adapter is constructed only when
   `db_gateway_dsn` is *also* set (read-side compatibility).
6. **`src/csm/adapters/gateway.py`** — **remove** `write_daily_performance`
   and `write_portfolio_snapshot`. Keep the two `read_*` methods and the
   `ping` method (still needed by health-check and history-read code
   paths). Update class docstring to reflect read-only role.
7. **`.env.example`** — add `GATEWAY_BASE_URL` and `GATEWAY_API_KEY`,
   document the deprecation of `DB_GATEWAY_DSN` for write paths.
8. **Tests**:
   - `tests/adapters/test_gateway_client.py` (new) — happy path,
     retry-on-5xx, give-up-on-4xx, missing api-key handling, schema
     contract assertion (golden-file payload).
   - `tests/adapters/test_payload.py` (new) — payload builder unit
     tests including the report-present and report-absent branches.
   - `tests/adapters/test_hooks.py` — update mocks: `manager.gateway`
     write-side mock removed; `gateway_client.post_daily_report` mock
     added; assert one call per refresh.
   - `tests/adapters/test_gateway.py` — remove the deleted-method tests;
     keep read-side tests.
   - `tests/config/test_settings.py` — new settings validated; missing
     `gateway_base_url` with `gateway_enabled=True` raises a clear error.
9. **Docs** — short paragraph in `docs/architecture/adapters.md` (if it
   exists, otherwise in the relevant module docstring) describing the
   write-via-HTTP / read-via-DSN split.

### Out of scope

- **Read-side migration** — `GatewayAdapter.read_daily_performance` and
  `read_portfolio_snapshots` continue to read directly from
  `db_gateway`. They serve backtest analytics and history APIs where
  bulk reads via SQL are significantly cheaper than per-row HTTP. A
  future plan can address those if/when read endpoints exist for the
  same data.
- **Caching the HTTP client across requests** beyond the basic shared
  `AsyncClient` instance. No connection pooling tuning in this plan.
- **Authentication scheme change** — we use the existing
  `X-API-Key` shared secret as the gateway already requires; no
  per-strategy keys or rotation tooling here.
- **Backfill of historic days** that were missed while
  `strategy_report_snapshot` writes were absent. If needed, that is a
  separate one-shot operator task.
- **Removing `db_gateway_dsn` entirely** — leave it as opt-in for the
  read path; only the write methods are deleted in this PR.

---

## Deliverables

### Created

- `src/csm/adapters/gateway_client.py`
- `src/csm/adapters/payload.py`
- `tests/adapters/test_gateway_client.py`
- `tests/adapters/test_payload.py`
- `docs/plans/feature-strategies-report-metrics/PLAN-followup-http-ingestion-migration.md`
  (this plan)

### Modified

- `src/csm/config/settings.py` — `+gateway_base_url`, `+gateway_api_key`;
  deprecation note on `db_gateway_dsn`.
- `src/csm/adapters/__init__.py` — `AdapterManager` wires both
  `gateway_client` and (optionally) read-only `gateway`.
- `src/csm/adapters/hooks.py` — single HTTP write call replaces the two
  direct-DSN writes.
- `src/csm/adapters/gateway.py` — remove `write_*` methods; update
  class docstring.
- `.env.example` — new vars, deprecation note.
- `tests/adapters/test_hooks.py`, `tests/adapters/test_gateway.py`,
  `tests/config/test_settings.py` — updated per the scope above.

### Untouched (do not modify in this PR)

- `src/csm/research/strategy_report.py`,
  `src/csm/research/strategy_report_models.py` — the report payload
  itself is already correct; we only change how it gets to the gateway.
- `src/csm/live/portfolio.py` — `LiveMetrics.report` field already
  exists and is correctly populated.
- Any backtest / signal / data-refresh code paths — unrelated.
- `Dockerfile`, `docker-compose.yml` — only an env-var addition; no
  build change.

---

## Implementation Order

1. **Branch**: `git checkout -b feat/http-ingestion-migration`.
2. **Settings first** — add `gateway_base_url` and `gateway_api_key` to
   `csm/config/settings.py` with clear docstrings and `min_length=1`.
   Write `tests/config/test_settings.py` cases:
   - Both vars set → settings parse.
   - `gateway_base_url` missing while `gateway_enabled=True` →
     `ValidationError`.
   - `gateway_api_key` returned as `SecretStr` (never `str`).
3. **Payload builder** — write
   `tests/adapters/test_payload.py` with a golden-file fixture (a
   verbatim contract payload, hand-edited from one real refresh's
   output) and a property test for the report-absent case. Implement
   `build_ingestion_payload` to pass.
4. **HTTP client** — write `tests/adapters/test_gateway_client.py`
   using `respx` (httpx's test transport):
   - 200 → no exception, body discarded.
   - 503 then 503 then 200 → succeeds after 2 retries.
   - 503 × 3 → raises `GatewayWriteError`.
   - 401 / 403 / 422 → raises immediately (no retry).
   - Asserts `X-API-Key` header is set.
   - Asserts `Content-Type: application/json` and correct body shape.
   Implement `gateway_client.py` to pass. Backoff uses `tenacity` if
   already a dep; else hand-roll `await asyncio.sleep(min(2**n, 8))`.
5. **AdapterManager wiring** — update `src/csm/adapters/__init__.py`
   to construct `gateway_client` from settings and attach it to
   `manager.gateway_client`. The legacy `manager.gateway` becomes
   read-only and is only built when `db_gateway_dsn` is configured.
6. **Hook rewrite** — in `src/csm/adapters/hooks.py::post_refresh`:
   - Replace lines 205–215 (the `write_daily_performance` block) with
     `payload = build_ingestion_payload(...)` followed by
     `await manager.gateway_client.post_daily_report(payload)` inside a
     `try/except GatewayWriteError` that logs warning and continues.
   - Delete the `write_portfolio_snapshot` block (lines 220+) **only
     after** confirming the gateway's ingestion endpoint emits the
     `portfolio_snapshot` row automatically when all active strategies
     have reported for the day (it does — see umbrella `CLAUDE.md`:
     *"Once every active strategy has reported for the date, the
     gateway auto-emits a combined `portfolio_snapshot` row"*).
   - Update `tests/adapters/test_hooks.py` accordingly.
7. **GatewayAdapter cleanup** — remove `write_daily_performance` and
   `write_portfolio_snapshot` plus their `_SQL` constants. Rename the
   class docstring to "read-only history adapter for `db_gateway`".
   Remove the corresponding tests in `tests/adapters/test_gateway.py`.
8. **`.env.example`** — add the new vars; mark `DB_GATEWAY_DSN` as
   "optional, read-only history access".
9. **Quality gate**:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src tests
   uv run pytest
   ```
   Coverage must stay ≥ 90% on `adapters/` and `api/`.
10. **Live verification** (requires gateway up and reachable on
    `quant-network`):
    ```bash
    docker compose up -d --force-recreate csm
    # Wait for the next data_refresh; or trigger it:
    curl -X POST http://localhost:8100/api/v1/data/refresh
    # Then check the gateway side:
    docker exec quant-postgres psql -U postgres -d db_gateway \
      -c "SELECT strategy_id, time FROM strategy_report_snapshot ORDER BY time DESC LIMIT 5;"
    # Expect a row for csm-set with today's date.
    ```
11. **Commit**: single conventional commit
    `feat(csm-set): migrate gateway write-back to HTTP ingestion contract`.

---

## Critical Files (reuse rather than recreate)

- `src/csm/adapters/hooks.py` lines 183–215 — the `_build_strategy_report_safe`
  result already lives on `live_metrics.report`; reuse it as the
  `extended_data.report` source.
- `src/csm/research/strategy_report_models.py::StrategyReport` — already
  matches the gateway-side Pydantic model field-for-field (Phase 1
  contract). Do not redefine.
- `src/csm/live/portfolio.py::LiveMetrics` — `as_dict()` is the existing
  serialiser; the payload builder will use it for the
  `performance_metrics` block.
- `src/csm/config/settings.py` — existing `SecretStr` fields are the
  template for `gateway_api_key`.
- Gateway-side reference: `quant-api-gateway/src/api/v1/ingest.py` and
  `quant-api-gateway/src/services/ingestion.py::persist_daily_report` —
  the canonical contract consumer. Our payload must satisfy
  `IngestionRequest` (in `quant-api-gateway/src/schemas/strategy.py`)
  exactly.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Gateway unreachable during a scheduled refresh → write-back silently lost | Retry with exponential backoff (3 attempts). On final failure, log WARNING with the payload size + strategy_id but do not raise — same non-fatal semantics as today's direct-DSN write. Operators surface persistent failures via Grafana / `/health` of the gateway. |
| Payload schema drift between csm-set and gateway Pydantic models | Both already derive from the same Phase 1 contract. Add an integration test (marker `integration`) that posts a real payload to a running gateway and asserts `201 Created`. Re-run as part of the verification step. |
| `INTERNAL_API_KEY` rotation breaks csm-set silently | The HTTP client raises immediately on 401/403 (no retry). The post-refresh log emits the `request_id` returned by the gateway when present, so failures are correlatable. |
| Removing `write_portfolio_snapshot` from csm-set could lose snapshot data if gateway's auto-emit is gated on a configuration we don't control | Verified during step 6 against gateway code + umbrella `CLAUDE.md`. The auto-emit fires whenever `len(reports_for_date) == len(registry.active_strategies())`. With csm-set as the only active strategy today, every post triggers an emit. Document this assumption in the hook comment. |
| Latency budget — daily refresh now adds 1 HTTP round-trip | Gateway typical latency for `/api/v1/ingest/daily-report` is < 200 ms on the local network. Refresh cadence is daily; the cost is negligible. |
| Existing `db_gateway_dsn`-using read paths break when DSN is unset in `.env` | Keep `db_gateway_dsn` as optional; only `gateway_base_url` becomes required. The factory in `adapters/__init__.py` constructs `gateway` (read-only) only when DSN is present, mirroring today's `if gw_candidate is not None` guard at line 121. |
| Tests use real `httpx.AsyncClient` and hit the network | Mandatory use of `respx` (or `httpx_mock`) so tests are hermetic. The integration test (marker `integration`) is opt-in and runs only against an explicitly-started gateway. |
| Coverage drop from removing tested write methods | The replacement code in `gateway_client.py` + `payload.py` is fully tested; net coverage on `adapters/` should rise, not fall. |
| Operator forgets to set the two new env vars when upgrading | Pydantic raises a clear `ValidationError` at startup naming the missing fields. Add an explicit one-liner to the CSM_SET upgrade notes referencing this plan. |

---

## Acceptance Criteria

- [ ] `uv run ruff check .` — zero findings.
- [ ] `uv run ruff format --check .` — no drift.
- [ ] `uv run mypy src tests` — zero strict-mode errors.
- [ ] `uv run pytest` — green; coverage ≥ 90% on
      `adapters/` and `api/`.
- [ ] `uv run pytest -m integration` — green when the `quant-network`
      stack is up.
- [ ] After a refresh run, `db_gateway.strategy_report_snapshot` has a
      row for `csm-set` with today's date.
- [ ] After a refresh run, `db_gateway.daily_performance` still has the
      same row count and shape as before the migration.
- [ ] `src/csm/adapters/gateway.py` has no `write_*` methods.
- [ ] `manager.gateway_client.post_daily_report` is called exactly once
      per `post_refresh` invocation (assert via mock).
- [ ] Dashboard's **Report** tab renders for `csm-set` with no 404.
- [ ] `INTERNAL_API_KEY` mismatch surfaces as a single WARNING log line
      naming the strategy_id; the refresh job continues.
- [ ] Single conventional commit:
      `feat(csm-set): migrate gateway write-back to HTTP ingestion contract`.

---

## Verification Plan

```bash
# 1. Quality gate
git checkout feat/http-ingestion-migration
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv run pytest -m integration   # requires gateway up

# 2. End-to-end through the running stack
docker compose up -d --force-recreate csm
curl -X POST http://localhost:8100/api/v1/data/refresh
# Wait for job to succeed (poll /api/v1/jobs)
docker exec quant-postgres psql -U postgres -d db_gateway -c \
  "SELECT strategy_id, time, octet_length(report::text) AS bytes
   FROM strategy_report_snapshot
   ORDER BY time DESC LIMIT 5;"

# 3. Gateway-side check (the dashboard's actual call)
curl -s http://localhost:8080/api/v1/strategies/csm-set/report | jq '.report.headline_kpis'

# 4. Dashboard check
#    Open http://localhost:3000, navigate to CSM SET Strategy → Report tab.
#    Confirm the report renders with no error state.
```

---

## Sequencing with companion plans

This plan **depends on** the gateway type-field fix being available so
the dashboard dispatches to `CSMSetAdapter` correctly; otherwise the
Report tab will not render even after the snapshot table is populated.

Recommended order:

1. `quant-api-gateway/.../PLAN-followup-strategy-type-field.md` →
   unblocks **Metrics** tab (small).
2. **This plan** → unblocks **Report** tab + **List of trades** tab
   (bigger, architectural).
3. `quant-dashboard/.../PLAN-followup-strategy-type-verification.md` →
   end-to-end browser verification + screenshots; no code change in the
   dashboard unless a regression surfaces.
