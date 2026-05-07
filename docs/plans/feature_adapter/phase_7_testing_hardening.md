# Phase 7: Testing & Hardening

**Feature:** csm-set-adapter — Integration layer connecting csm-set to quant-infra-db
**Branch:** `feature/csm-set-adapter`
**Created:** 2026-05-07
**Status:** Complete
**Completed:** 2026-05-07
**Depends On:** Phase 1 (Complete), Phase 2 (Complete), Phase 3 (Complete),
Phase 4 (Complete), Phase 5 (Complete), Phase 6 (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Integration Suite Layout](#integration-suite-layout)
6. [Coverage Gate](#coverage-gate)
7. [CI Workflow](#ci-workflow)
8. [Documentation Updates](#documentation-updates)
9. [Implementation Steps](#implementation-steps)
10. [File Changes](#file-changes)
11. [Acceptance Criteria](#acceptance-criteria)
12. [Risks & Mitigations](#risks--mitigations)
13. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 7 closes the csm-set-adapter feature by turning the work shipped in
Phases 1–6 into an enforceable contract. After this phase the IO boundary that
the adapters cross — another team's `quant-infra-db` stack — is exercised by
integration tests on demand, the line-coverage floor on `src/csm/adapters/` is
written into the build, the project's repo-wide quality gate passes on the
feature branch, and a new operator can enable write-back from `README.md`
alone.

The adapter code is finished. What was missing was the safety net that would
catch schema drift before it reached production: a real round-trip suite, a
coverage gate, a CI workflow that brings up the live stack, and end-user docs.

### Parent Plan Reference

- [docs/plans/feature_adapter/PLAN.md](PLAN.md) — Master plan, Phase 7 section
  (lines 636–692) and Testing Strategy (lines 756–784).

### Key Deliverables

1. **`tests/integration/adapters/`** — round-trip suite already covers the four
   target areas (Postgres, Mongo, Gateway, end-to-end pipeline). Phase 7
   verifies completeness, fills any remaining gaps, and confirms the
   `clean_test_strategy`-style autouse teardown shipped with the existing
   `adapter` / `mongo_adapter` / `gateway_adapter` / `adapter_manager` fixtures.
2. **`pyproject.toml`** — `[tool.coverage.report] fail_under = 90` plus
   `src/csm/adapters/*` added to the coverage source list, so the existing
   `--cov-fail-under=90` invocation enforces the adapter floor alongside the
   `api/` floor.
3. **`.github/workflows/infra-integration.yml`** — workflow that brings up the
   `quant-infra-db` Compose stack, exports the three DSN env vars, runs
   `uv run pytest tests/integration/adapters/ -v -m infra_db`, and tears the
   stack down. Triggers: `push` to `main` and `workflow_dispatch`.
4. **`README.md`** — new "Persisting to quant-infra-db" section with
   prerequisites, env vars, and verification steps.
5. **`docs/architecture/overview.md`** — write-back flow diagram (csm-set →
   AdapterManager → three stores → REST history endpoints).
6. **`.env.example`** — one-line annotation comments on the three new variables.
7. **`CHANGELOG.md`** — Unreleased entry covering the adapter feature.
8. **Tracking docs** — Phase 7 status flipped to `[x] Complete`.

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are tasked with implementing Phase 7 — Testing & Hardening for the csm-set
adapter project. Follow these steps precisely:

1. Preparation
   - Carefully read .claude/knowledge/project-skill.md and
     .claude/playbooks/feature-development.md to internalize all engineering
     standards and workflow expectations.
   - Review docs/plans/feature_adapter/PLAN.md, focusing on the Phase 7 section,
     and ensure you understand all deliverables, acceptance criteria, and
     architectural context.
   - Review docs/plans/feature_adapter/phase_6_api_history_endpoints.md for
     the current state and prior implementation details.

2. Planning
   - Draft a detailed implementation plan for Phase 7 in markdown, using the
     format from docs/plans/examples/phase1-sample.md.
   - Your plan must include: scope, deliverables, acceptance criteria, risks,
     and the full AI agent prompt (this prompt).
   - Save the plan as docs/plans/feature_adapter/phase_7_testing_hardening.md.

3. Implementation
   - Only begin coding after the plan is complete and saved.
   - Implement all deliverables for Phase 7 as specified in PLAN.md:
     - Achieve and enforce 100% test coverage for all public APIs and critical paths.
     - Add or update comprehensive unit and integration tests, including edge
       cases, error conditions, and security scenarios.
     - Harden error handling, logging, and input validation throughout the
       adapter and API layers.
     - Review and improve documentation for accuracy, completeness, and clarity.
     - Address any technical debt or code quality issues identified during
       testing.
   - Ensure all code follows project standards: type safety, async/await,
     Pydantic validation, error handling, and import organization.

4. Documentation and Progress Tracking
   - Update docs/plans/feature_adapter/PLAN.md and
     docs/plans/feature_adapter/phase_7_testing_hardening.md with progress
     notes, completion status, and any issues encountered.
   - Mark acceptance criteria as completed or note any deviations.

5. Commit and Finalization
   - Commit all changes in a single commit with a clear, standards-compliant
     message summarizing the work.
   - Ensure all tests pass and the implementation meets the acceptance criteria.

Files to reference and/or modify:
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- docs/plans/feature_adapter/PLAN.md
- docs/plans/feature_adapter/phase_6_api_history_endpoints.md
- docs/plans/examples/phase1-sample.md
- Target plan file: docs/plans/feature_adapter/phase_7_testing_hardening.md
- All relevant test, API, and adapter modules

Expected deliverables:
- A new plan markdown file at docs/plans/feature_adapter/phase_7_testing_hardening.md
  with the full implementation plan and embedded prompt.
- All Phase 7 deliverables implemented and tested.
- Updated progress/completion notes in both
  docs/plans/feature_adapter/PLAN.md and the new phase plan file.
- Updated relate docs eg. Readme.md , Relate Docs in docs/.
- A single commit with all changes and a standards-compliant message.

Begin by drafting the plan markdown file. Do not start implementation until
the plan is complete and saved.
```

### User-confirmed scope decisions

The user resolved three pre-implementation ambiguities via AskUserQuestion:

| Question | Decision |
|---|---|
| 100% vs ≥ 90% coverage on `src/csm/adapters/` | **≥ 90% per PLAN.md.** The 100% line in the prompt was treated as a stretch goal; PLAN.md is the source of truth for the acceptance criterion. |
| `quant-infra-db` Compose-stack dependency | **Pin a checked-in Compose path via `QUANT_INFRA_COMPOSE_PATH`; trigger only on `push` to `main` and `workflow_dispatch`.** Keeps PR runs fast and deterministic; manual / nightly verification owns the live-stack signal. |
| Hardening beyond PLAN.md deliverables | **Stick strictly to PLAN.md.** Captured the gaps surfaced during exploration (pool exhaustion, NaN serialization, large batches, query-param fuzzing, etc.) as "Out of Scope (deferred follow-ups)" rather than inflating the phase. |

---

## Scope

### In Scope (Phase 7)

| Component | Description | Status |
|---|---|---|
| `tests/integration/adapters/conftest.py` audit | Confirm fixtures + autouse-style teardown semantics meet PLAN.md §7.1 | `[x]` |
| `tests/integration/adapters/test_postgres_io.py` | Round-trip writes/reads for all three Postgres tables | `[x]` |
| `tests/integration/adapters/test_mongo_io.py` | Round-trip writes/reads for `backtest_results`, `signal_snapshots`, `model_params` | `[x]` |
| `tests/integration/adapters/test_gateway_io.py` | Round-trip writes/reads for `daily_performance`, `portfolio_snapshot` | `[x]` |
| `tests/integration/adapters/test_pipeline.py` | Hook → all three DBs end-to-end | `[x]` |
| Coverage gate in `pyproject.toml` | `fail_under = 90` enforced over `src/csm/adapters` and `api` | `[x]` |
| Top-up unit tests on `src/csm/adapters/` (if needed) | Ensure the gate clears with margin | `[x]` |
| `.github/workflows/infra-integration.yml` | Compose-stack integration job; manual + push-to-main triggers | `[x]` |
| `README.md` | "Persisting to quant-infra-db" operator section | `[x]` |
| `docs/architecture/overview.md` | Adapter write-back flow diagram | `[x]` |
| `.env.example` | One-line annotations for `CSM_DB_*` and `CSM_MONGO_URI` | `[x]` |
| `CHANGELOG.md` | Unreleased entry summarising the adapter feature | `[x]` |
| `docs/plans/feature_adapter/PLAN.md` | Phase 7 status flip + Current Status update | `[x]` |

### Out of Scope (Phase 7) — deferred follow-ups

The exploration phase surfaced several defensive-test ideas that go beyond
PLAN.md's acceptance criteria. Per user direction, these are captured here for
a future hardening pass rather than expanded into Phase 7:

- Connection-pool exhaustion / asyncpg pool-acquire timeouts.
- NaN / `±inf` JSON serialization through Postgres `JSONB` and Mongo BSON.
- Large-batch writes (1k+ row `trade_history`, 1k+ symbol `signal_snapshots`).
- History-endpoint query-param fuzzing (boundary stress on `days` / `limit`).
- Concurrent-request stress on `/api/v1/history/*`.
- Postgres-specific error codes (unique violation, auth failure, role missing).
- Mongo replica-set failover / server selection timeout simulation.

These are **not** acceptance-blocking. They live as a known follow-up backlog.

---

## Design Decisions

### 1. Coverage gate scope: `src/csm/adapters/*` + `api/*`, single floor

PLAN.md §7.2 specifies the gate over `src/csm/adapters/*`; the existing
CI invocation enforces a 90% floor on `api/*`. Rather than maintain two
overlapping gates with different paths, Phase 7 widens the single
`fail_under = 90` floor to cover both source trees. This means:

- A single command (`uv run pytest tests/`) is the source of truth.
- Removing the test-time `--cov=api` arg and putting the source list in
  `[tool.coverage.run]` keeps `pyproject.toml` declarative.
- The CI workflow keeps its existing `--cov-fail-under=90` arg unchanged;
  the configured `source` is what widens.

### 2. Dual `addopts` — keep coverage off when running a single test directory

`--cov-fail-under=90` defaults the suite to coverage-on. That's correct for
the full `pytest tests/` invocation but fails locally when targeting a single
directory (e.g. `uv run pytest tests/integration/adapters/`) because the
narrow run never reaches 90%. The gate is therefore enforced via the **CI
command** rather than via `addopts`; the existing `addopts` keeps
`--cov-fail-under=90` so behaviour is unchanged when developers run the full
suite without flags.

This matches the Phase 6 posture where `addopts` was tuned to balance fast
local iteration against strict CI.

### 3. CI workflow runs only on `push` to `main` and `workflow_dispatch`

A live-DB job on every PR would be slow, expensive, and brittle: failures
unrelated to csm-set (network blips, Compose timing) would block code review.
Cadence:

- **PR / branch push:** existing `ci.yml` (lint, type, unit + non-`infra_db`
  pytest). Fast, deterministic, no secrets.
- **`main` push + manual dispatch:** new `infra-integration.yml`. Brings up
  the stack, runs marker-gated tests, tears down.

The `workflow_dispatch` button gives the operator the same signal on demand
without merging.

### 4. `QUANT_INFRA_COMPOSE_PATH` is a documented input, not an embedded asset

The `quant-infra-db` Compose file is owned by another team and lives outside
this repo. Phase 7 does not vendor it. Instead the workflow takes a path
input (`QUANT_INFRA_COMPOSE_PATH`, default
`../quant-infra-db/docker-compose.yml`), which lets the runner check out a
sibling repo or override at dispatch time. The README documents this
contract in the new "Persisting to quant-infra-db" section.

### 5. Existing fixtures already meet PLAN.md §7.1 teardown requirements

PLAN.md §7.1 calls for "teardown deletes everything where
`strategy_id='test-csm-set'`". The Phase 1–6 fixtures already implement this
in [tests/integration/adapters/conftest.py](../../tests/integration/adapters/conftest.py)
(`adapter`, `mongo_adapter`, `gateway_adapter`, `adapter_manager`) using
before- and after-test wipes. The fixtures aren't `autouse=True` because
that would force a connection on every unrelated test in the package; pulling
them in by name is the same effect with better selectivity. Phase 7 keeps
this design — autouse=True is only added to the manager-level fixture if a
new round-trip test needs it.

### 6. Documentation order: README first, architecture diagram second

The README "Persisting to quant-infra-db" section is the operator entry
point; the architecture diagram in `docs/architecture/overview.md` is the
follow-up reference for engineers reading the system. The README is written
to stand alone so the architecture diagram can stay focused on the layered
view rather than rehashing env-var setup.

---

## Integration Suite Layout

The four files required by PLAN.md §7.1 already exist (created across Phases
2, 3, 4, and 5). Phase 7 confirms each carries `pytestmark = pytest.mark.infra_db`,
exercises both writes and reads, and asserts shape / ordering / idempotency.

| File | Coverage |
|---|---|
| `conftest.py` | `adapter`, `mongo_adapter`, `gateway_adapter`, `adapter_manager` fixtures with before-and-after `_wipe` helpers; skips on missing DSN |
| `test_postgres_io.py` | `equity_curve` idempotency, `trade_history` idempotency, `backtest_log` `ON CONFLICT DO NOTHING`, ascending equity-curve reads, descending trade reads, backtest filter |
| `test_mongo_io.py` | `backtest_results` idempotent upsert (latest-wins), `signal_snapshots` idempotent upsert by `(strategy_id, date)`, `model_params` idempotent upsert by `(strategy_id, version)` (created_at preserved), single-doc reads, list with `limit` and slim projection |
| `test_gateway_io.py` | `daily_performance` round-trip + idempotency + `days` filter + ascending order; `portfolio_snapshot` round-trip + idempotency + `days` filter + ascending order |
| `test_pipeline.py` | `run_post_refresh_hook` against live stack with synthetic prices/features; partial-adapter availability; null-manager no-op; `run_post_backtest_hook` round-trip; `run_post_rebalance_hook` no-op |

All tests carry `pytestmark = pytest.mark.infra_db`. Default
`uv run pytest tests/` skips them (they self-skip on missing DSN env vars
even when the marker is included).

---

## Coverage Gate

### `pyproject.toml` change

```toml
[tool.coverage.run]
source = ["src/csm/adapters", "api"]
branch = false

[tool.coverage.report]
fail_under = 90
show_missing = true
skip_empty = true
```

The existing `addopts = ["--cov-fail-under=90", "--import-mode=importlib"]`
remains. The CI workflow continues to call
`pytest --cov=api --cov-report=term --cov-report=xml --cov-fail-under=90`
and benefits transparently from the new `source` list because pytest-cov
honours `[tool.coverage.run].source` when no `--cov` argument is passed and
also additively when `--cov` is passed without a path. To make the additive
behaviour explicit and avoid relying on subtle pytest-cov internals, the CI
command also gains `--cov=src/csm/adapters`.

### Adapter coverage status

The Phase 1–6 unit suites already cover the adapter layer comprehensively:

| Module | Test file | Tests |
|---|---|---|
| `postgres.py` | `tests/unit/adapters/test_postgres.py` | 22 |
| `mongo.py` | `tests/unit/adapters/test_mongo.py` | 29 |
| `gateway.py` | `tests/unit/adapters/test_gateway.py` | 22 |
| `__init__.py` (`AdapterManager`) | `tests/unit/adapters/test_manager.py` | 31 |
| `health.py` | `tests/unit/adapters/test_health.py` | 6 |
| `hooks.py` | `tests/unit/adapters/test_hooks.py` | 22 |

A baseline coverage measurement is part of Phase 7. Any module under 90% is
topped up with targeted tests in `tests/unit/adapters/`.

---

## CI Workflow

### `.github/workflows/infra-integration.yml`

```yaml
name: infra-integration

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      compose_path:
        description: "Path to the quant-infra-db docker-compose.yml"
        required: false
        default: "../quant-infra-db/docker-compose.yml"

concurrency:
  group: infra-integration-${{ github.ref }}
  cancel-in-progress: true

jobs:
  infra-db:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      QUANT_INFRA_COMPOSE_PATH: ${{ github.event.inputs.compose_path || '../quant-infra-db/docker-compose.yml' }}

    steps:
      - name: Checkout csm-set
        uses: actions/checkout@v4
        with:
          path: csm-set

      - name: Checkout quant-infra-db (sibling)
        uses: actions/checkout@v4
        with:
          repository: lumduan/quant-infra-db
          path: quant-infra-db
          token: ${{ secrets.QUANT_INFRA_DB_PAT || github.token }}
        continue-on-error: true

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: latest
          enable-cache: true
          cache-dependency-glob: csm-set/uv.lock

      - name: Install Python
        run: uv python install 3.12
        working-directory: csm-set

      - name: Install dependencies
        run: uv sync --all-groups --frozen
        working-directory: csm-set

      - name: Bring up quant-infra-db stack
        run: |
          if [ ! -f "${QUANT_INFRA_COMPOSE_PATH}" ]; then
            echo "::warning::Compose file not found at ${QUANT_INFRA_COMPOSE_PATH}; skipping live integration job"
            exit 0
          fi
          docker compose -f "${QUANT_INFRA_COMPOSE_PATH}" up -d --wait
        working-directory: csm-set

      - name: Run integration suite
        run: |
          if [ ! -f "${QUANT_INFRA_COMPOSE_PATH}" ]; then
            echo "Compose file unavailable; nothing to run"
            exit 0
          fi
          uv run pytest tests/integration/adapters/ -v -m infra_db
        env:
          CSM_DB_CSM_SET_DSN: postgresql://postgres:postgres@127.0.0.1:5432/db_csm_set
          CSM_DB_GATEWAY_DSN: postgresql://postgres:postgres@127.0.0.1:5432/db_gateway
          CSM_MONGO_URI: mongodb://127.0.0.1:27017/
        working-directory: csm-set

      - name: Tear down stack
        if: always()
        run: |
          if [ -f "${QUANT_INFRA_COMPOSE_PATH}" ]; then
            docker compose -f "${QUANT_INFRA_COMPOSE_PATH}" down -v
          fi
        working-directory: csm-set
```

The workflow tolerates a missing `quant-infra-db` checkout — emits a warning
and exits 0. This avoids spurious `main`-branch failures while the stack
isn't yet wired into CI; once the sibling repo is reachable the job runs in
full.

---

## Documentation Updates

### `README.md` — "Persisting to quant-infra-db" section

Inserted after "Owner workflow", before "Module index". Covers:

- **Prerequisites:** `quant-infra-db` Compose stack running on `quant-network`,
  Postgres and Mongo reachable from the csm-set host.
- **Required env vars:**
  - `CSM_DB_WRITE_ENABLED=true`
  - `CSM_DB_CSM_SET_DSN=postgresql://...db_csm_set`
  - `CSM_DB_GATEWAY_DSN=postgresql://...db_gateway`
  - `CSM_MONGO_URI=mongodb://...`
- **Verification:** `curl http://localhost:8000/health` shows
  `"db": {"postgres": "ok", "mongo": "ok", "gateway": "ok"}` when the stack is
  up; `curl -H "X-API-Key: $CSM_API_KEY" http://localhost:8000/api/v1/history/equity-curve`
  returns the latest curve.
- **Integration tests:** how to run
  `uv run pytest tests/integration/adapters/ -v -m infra_db` locally.

### `docs/architecture/overview.md` — write-back flow diagram

New "Adapter write-back" subsection inside "Runtime data flow" with the
PLAN.md §7.3 ASCII diagram and a brief paragraph linking to
`src/csm/adapters/` and the `/api/v1/history/*` endpoints.

### `.env.example` — annotations

Each of the three new variables gets a one-line comment:

```
# Required when CSM_DB_WRITE_ENABLED=true: Postgres DSN for csm-set's own DB.
CSM_DB_CSM_SET_DSN=postgresql://postgres:<pass>@quant-postgres:5432/db_csm_set
# Required when CSM_DB_WRITE_ENABLED=true: Postgres DSN for the cross-strategy gateway DB.
CSM_DB_GATEWAY_DSN=postgresql://postgres:<pass>@quant-postgres:5432/db_gateway
# Required when CSM_DB_WRITE_ENABLED=true: Mongo URI for backtest results / signals / model params.
CSM_MONGO_URI=mongodb://quant-mongo:27017/
```

### `CHANGELOG.md` — Unreleased entry

```
## [Unreleased]

### Added

- **csm-set ↔ quant-infra-db adapters.** New `src/csm/adapters/` package with
  `PostgresAdapter` (db_csm_set), `MongoAdapter` (csm_logs), and
  `GatewayAdapter` (db_gateway) plus a graceful-degradation `AdapterManager`.
  Pipeline hooks (post-refresh / post-backtest / post-rebalance) write
  through the manager so adapter outages never crash csm-set.
- **`/api/v1/history/*` endpoints.** Six private-mode GETs over the central-DB
  history (equity curve, trades, daily performance, portfolio snapshots,
  backtest summaries, signal snapshots), gated by `X-API-Key` and the new
  `PROTECTED_PREFIXES` set.
- **`infra-integration` GitHub Actions workflow.** Brings up the
  `quant-infra-db` Compose stack and runs the marker-gated suite on push to
  `main` and on manual dispatch.
- **Documentation.** "Persisting to quant-infra-db" section in `README.md`,
  adapter write-back diagram in `docs/architecture/overview.md`, and
  annotations on the new env vars in `.env.example`.
```

---

## Implementation Steps

### Step 1 — Baseline coverage measurement

```bash
uv run pytest tests/unit/adapters/ tests/integration/test_api_history.py \
  --cov=src/csm/adapters --cov=api --cov-report=term-missing --no-cov-on-fail
```

Identify any adapter module under 90% line coverage and patch with targeted
unit tests.

### Step 2 — Update `pyproject.toml`

Add the `[tool.coverage.run]` and `[tool.coverage.report]` blocks with
`source = ["src/csm/adapters", "api"]` and `fail_under = 90`. Keep
`addopts` unchanged.

### Step 3 — Verify the gate clears the full suite

```bash
uv run pytest tests/ -v --cov=src/csm/adapters --cov=api \
  --cov-report=term --cov-fail-under=90
```

If it fails, top-up tests in `tests/unit/adapters/` until it passes.

### Step 4 — Run the full quality gate

```bash
uv run ruff check . && uv run ruff format --check . \
  && uv run mypy src/csm/adapters/ \
  && uv run mypy src/ \
  && uv run pytest tests/ -v
```

All five must exit 0.

### Step 5 — Create `.github/workflows/infra-integration.yml`

Follow the YAML in [CI Workflow](#ci-workflow) above.

### Step 6 — Update documentation

1. README: insert "Persisting to quant-infra-db" after Owner workflow.
2. `docs/architecture/overview.md`: add adapter write-back diagram and link.
3. `.env.example`: annotate the three new env vars.
4. `CHANGELOG.md`: write the Unreleased entry.

### Step 7 — Update tracking docs

1. `docs/plans/feature_adapter/PLAN.md` — flip Phase 7 checkboxes; update
   Current Status table row to `[x] Complete 2026-05-07`.
2. This file — fill the Completion Notes section.

### Step 8 — Commit

Single commit:

```
test(adapters): add coverage gate, infra-integration CI, and docs (Phase 7)

- pyproject.toml: coverage source widened to src/csm/adapters + api,
  fail_under = 90 enforced project-wide
- .github/workflows/infra-integration.yml: brings up quant-infra-db
  Compose stack, runs `pytest -m infra_db`, tears down (push to main +
  manual dispatch)
- README, docs/architecture/overview.md, .env.example, CHANGELOG.md:
  document write-back configuration and verification
- PLAN.md + phase doc: Phase 7 status complete
```

---

## File Changes

| File | Action | Description |
|---|---|---|
| `docs/plans/feature_adapter/phase_7_testing_hardening.md` | CREATE | This document |
| `pyproject.toml` | MODIFY | Coverage source list + `fail_under` block |
| `.github/workflows/infra-integration.yml` | CREATE | Compose-stack integration job |
| `README.md` | MODIFY | "Persisting to quant-infra-db" section |
| `docs/architecture/overview.md` | MODIFY | Adapter write-back flow diagram |
| `.env.example` | MODIFY | Annotate `CSM_DB_*` and `CSM_MONGO_URI` |
| `CHANGELOG.md` | MODIFY | Unreleased entry |
| `docs/plans/feature_adapter/PLAN.md` | MODIFY | Phase 7 progress flips; Current Status update |
| `tests/unit/adapters/*.py` | MODIFY (if needed) | Top up to clear the 90% floor |

No production code under `src/csm/adapters/` or `api/` is modified by this
phase. The adapter and history-router surfaces are frozen at the end of
Phase 6.

---

## Acceptance Criteria

- [x] `uv run ruff check .` clean.
- [x] `uv run ruff format --check .` clean.
- [x] `uv run mypy src/csm/adapters/` clean.
- [x] `uv run mypy src/` clean.
- [x] `uv run pytest tests/ -v` green; coverage on `src/csm/adapters/*` and
  `api/*` ≥ 90% (enforced via `--cov-fail-under=90`).
- [x] `pyproject.toml` declares `[tool.coverage.report] fail_under = 90` and
  the coverage source list includes `src/csm/adapters`.
- [x] `.github/workflows/infra-integration.yml` exists with the correct
  triggers (`push: main`, `workflow_dispatch`), brings up the Compose stack,
  runs `pytest tests/integration/adapters/ -v -m infra_db`, and always tears
  the stack down.
- [x] `README.md` has a "Persisting to quant-infra-db" section that takes a
  new operator from "stack running" to "verified write-back" without reading
  source.
- [x] `docs/architecture/overview.md` shows the adapter write-back flow.
- [x] `.env.example` annotates each of `CSM_DB_CSM_SET_DSN`,
  `CSM_DB_GATEWAY_DSN`, and `CSM_MONGO_URI`.
- [x] `CHANGELOG.md` Unreleased entry covers the adapter feature, history
  endpoints, and the new CI workflow.
- [x] `docs/plans/feature_adapter/PLAN.md` Phase 7 marked Complete; Current
  Status table updated.
- [~] `uv run pytest tests/integration/adapters/ -m infra_db -v` green
  against the live stack — verified self-skip behaviour without DSNs;
  green-against-stack run is gated on the workflow firing in CI.

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Adapter coverage already over 90% — gate is symbolic | Medium | Low | Acceptable; the gate is a tripwire for future regressions, not retroactive proof |
| `infra-integration.yml` fires on `main` push and fails because the sibling repo isn't checked out | Medium | Medium | Workflow tolerates missing Compose file (warning + early exit). Operator runs `workflow_dispatch` once the sibling is wired |
| Widening coverage source breaks the existing `--cov=api` floor (e.g. lower aggregate when adapters are partially covered) | Medium | Medium | Step 1 measures baseline before flipping the gate; Step 3 re-runs against the full suite to confirm |
| Adapter source paths not picked up because `--cov=api` arg overrides `[tool.coverage.run].source` | Medium | Medium | Pass `--cov=src/csm/adapters` alongside `--cov=api` in the CI command and in the README |
| Documentation drift between README and `docs/architecture/overview.md` | Low | Low | README is the operator entry point; architecture overview links to it. Both write paths exit through the same env-var contract |

---

## Completion Notes

### Summary

Phase 7 complete. All deliverables shipped in a single session:

- **Coverage gate** (`pyproject.toml`): added `[tool.coverage.run]` with
  `source = ["src/csm/adapters", "api"]` and `[tool.coverage.report]` with
  `fail_under = 90` and `show_missing = true`. The repo-wide `--cov-fail-under=90`
  in `addopts` now enforces the floor across both the adapter package and the
  API surface in a single run. Baseline measurement showed adapter coverage
  was already comfortably above 90% from the Phase 1–6 unit suites; no
  top-up tests were needed.
- **CI workflow** (`.github/workflows/infra-integration.yml`): authored a
  push-to-`main` + `workflow_dispatch` job that checks out csm-set + the
  sibling `quant-infra-db` repo, brings up the Compose stack, exports the
  three DSN env vars, runs `uv run pytest tests/integration/adapters/ -v -m infra_db`,
  and always tears the stack down. Tolerates a missing sibling checkout to
  avoid spurious failures while the live job is being wired into ops.
- **Documentation**: added the "Persisting to quant-infra-db" section to
  `README.md` (prerequisites, env vars, verification, test command), an
  adapter write-back flow diagram to `docs/architecture/overview.md`, one-line
  annotations to the new env vars in `.env.example`, and an Unreleased entry
  to `CHANGELOG.md` summarising the adapter feature, history endpoints, and
  the integration workflow.
- **Tracking docs**: Phase 7 checkboxes in PLAN.md flipped to `[x]`; Current
  Status table row updated to `[x] Complete 2026-05-07`.
- **Quality gates**: `ruff check`, `ruff format --check`, `mypy src/csm/adapters/`,
  `mypy src/`, and `pytest tests/ -v` all clean.

### Issues Encountered

1. **Coverage source list vs. `--cov=` CLI arg interaction.** Early
   experiments with only `[tool.coverage.run].source` failed to widen the
   gate when CI passed `--cov=api`. Resolved by additionally passing
   `--cov=src/csm/adapters` in the CI command (documented in
   `phase_7_testing_hardening.md`); the declarative source list still helps
   when developers run `pytest --cov` without arguments.
2. **`--cov-fail-under=90` in `addopts` inflates failures on narrow runs.**
   Running a single test directory locally falls below the floor. The
   workaround documented in the plan: pass `--no-cov-on-fail` or run the
   full suite. No change required for CI.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-05-07
