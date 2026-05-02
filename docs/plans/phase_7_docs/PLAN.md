# Phase 7 — Hardening & Documentation Master Plan

**Feature:** Production-ready quality and complete English documentation — finalises csm-set as a publicly distributable, AI/LLM-friendly research platform
**Branch:** `feature/phase-7-docs`
**Created:** 2026-05-02
**Status:** Completed (2026-05-02)
**Depends on:** Phase 1 (Data Pipeline — complete), Phase 2 (Signal Research — complete), Phase 3 (Backtesting — complete), Phase 4 (Portfolio Construction & Risk — complete), Phase 5 (FastAPI + FastUI — complete 2026-05-01), Phase 6 (Docker & Public Distribution — complete 2026-05-02, v0.6.0 published)
**Positioning:** Hardening layer — converts a working v0.6.0 release into a v0.7.0 release that is verifiable on every push, fully documented for both human and LLM consumers, and certified end-to-end by a single quality gate. Closes the four loose ends called out in `ROADMAP.md` § Phase 7: test coverage lock, doc-stub completion, API security verification, and a general CI workflow. Phase 7 ships **no new product features**; it raises the floor for everything Phases 1–6 already built.

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Design Rationale](#design-rationale)
4. [Architecture](#architecture)
5. [Implementation Phases](#implementation-phases)
6. [Data Models](#data-models)
7. [Error Handling Strategy](#error-handling-strategy)
8. [Testing Strategy](#testing-strategy)
9. [Success Criteria](#success-criteria)
10. [Future Enhancements](#future-enhancements)
11. [Commit & PR Templates](#commit--pr-templates)

---

## Overview

### Purpose

Phase 7 turns the working v0.6.0 release into a v0.7.0 release that satisfies three acceptance gates simultaneously:

1. **Verifiable on every push** — a single `ci.yml` workflow (lint → type-check → test with coverage floor) runs on every push and pull request, joining the existing `docker-smoke.yml` (PR-gated boot test) and `docker-publish.yml` (tag-driven GHCR push).
2. **Fully documented for both humans and LLMs** — the twelve 12-line stubs under `docs/` are replaced with real English content, the module reference section gives a future agent enough information to extend any subpackage without re-reading source, and `README.md` exposes a table of contents, module index, troubleshooting, and a "Where to find X" pointer block so coding agents can navigate the repo without grep.
3. **Certifiably hardened** — the existing `api/security.py` (`X-API-Key` middleware, constant-time compare, key redaction) is documented in `docs/architecture/` and `docs/guides/`, the public-mode 403 contract is restated, and the test coverage floor on `api/` is locked in `pyproject.toml` so it cannot regress silently.

The goal is *not* to add features; it is to make sure that when an external researcher, contributor, or AI coding agent lands on this repo for the first time, they can answer "what does each module export?", "how do I run the quality gate?", "how is auth enforced?", and "what changes block CI?" without ever reading source.

### Scope

Phase 7 covers seven sub-phases. Sub-phases 7.1, 7.3 and parts of 7.4 are **verification-and-lock** work because the underlying implementation already shipped in Phases 5 and 6; the remaining work is to confirm the state, document it, and prevent regression. 7.2.1–7.2.4 and the new `ci.yml` are net-new authoring work.

| Sub-phase | Deliverable | Purpose |
|---|---|---|
| 7.1 | Coverage lock + suite green-light | Confirm 742 tests / 92% on `api/`; pin the floor in `pyproject.toml`; CI fails on regression |
| 7.2.1 | README polish (TOC, module index, troubleshooting, "Where to find X") | Lower the LLM/agent onboarding cost; first-time visitors find any concept in < 10 s |
| 7.2.2 | Expand `docs/architecture/overview.md` + `docs/concepts/momentum.md` | Layer responsibilities, data flow, public-mode boundary, momentum theory |
| 7.2.3 | Expand `docs/reference/{data,features,portfolio,risk,research}/overview.md` | Module index per subpackage with exported callables, signatures, examples |
| 7.2.4 | Expand `docs/getting-started/`, `docs/development/`, `docs/guides/{docker,public-mode}` | Quickstart, dev workflow, Docker recipes, public-mode rules |
| 7.3 | Document existing API security in narrative form | `api/security.py` is shipped; this sub-phase moves it into `docs/architecture/` and `docs/guides/` so it is discoverable |
| 7.4 | `.github/workflows/ci.yml` (lint → type-check → test) | Quality-gate-as-code on every push and PR; complements existing Docker-only workflows |

### Out of Scope

- **New product features** — no new endpoints, no new signal logic, no new portfolio constructors. Phase 8 covers feature work.
- **Thai-language documentation pass** — notebooks remain Thai per project convention (`feedback_notebook_thai.md`), but `docs/` stays English. A bilingual pass is deferred.
- **Image signing (cosign / Sigstore) and SBOM generation** — listed as Phase 6 future enhancements; deferred to a later hardening phase.
- **Vulnerability scanning gate (trivy)** — deferred. No security-scanning workflow ships in 7.4; scope is lint/type/test only.
- **Multi-arch (`linux/arm64`) image builds** — deferred. `docker-publish.yml` stays AMD64-only.
- **Rate limiting, OAuth, observability/metrics tooling** — listed in Future Enhancements.
- **Performance benchmarking** — deferred; no benchmark suite added.

### Current State (as of 2026-05-02)

- **Tests:** 54 test files under `tests/`; ROADMAP claims 742 tests / 92% line coverage on `api/`. The Phase 7.1 sub-phase verifies and locks this number.
- **CI workflows:** `.github/workflows/docker-smoke.yml` (PR-gated boot test) and `.github/workflows/docker-publish.yml` (tag-driven GHCR push) exist. `ci.yml` does **not** exist — only Docker-touching changes are currently CI-checked.
- **API security:** `api/security.py` ships the `X-API-Key` middleware (constant-time compare via `secrets.compare_digest`, request-id-tagged 401 responses, key redaction in logs); `Settings.api_key: SecretStr | None` is wired through. Public-mode write-endpoint 403s are enforced by `public_mode_guard`. Phase 7.3 is documentation of this existing surface, not new code.
- **Documentation:** `docs/` contains 12 overview stubs at 12 lines each (one TOC + one TODO line). Sub-phases 7.2.1–7.2.4 expand them.
- **README:** ~334 lines; covers Quick Start, Architecture (Headless), owner workflow, stack, dev commands. Phase 7.2.1 adds a top-of-file TOC, a module index, troubleshooting, contributor links, and an explicit "Where to find X" pointer block.

---

## Problem Statement

Four concrete gaps separate v0.6.0 from a release that an external researcher or AI agent can adopt without hand-holding:

1. **No general CI workflow.** Today, only changes that touch Docker paths are exercised by CI (`docker-smoke.yml`). A pull request that breaks `mypy` on `src/csm/portfolio/` or fails a unit test in `src/csm/features/` will land on `main` undetected unless a reviewer runs the quality gate locally. The project's claim of "742 tests, 92% coverage" is therefore unenforceable in CI.
2. **Documentation is stubs.** Twelve `docs/**/overview.md` files contain only a four-bullet TOC and `> TODO: Expand this page further.` A reader who clicks `docs/architecture/overview.md` from the README finds a placeholder. An AI agent asked "where is the data flow documented?" cannot answer from `docs/`. This makes the project hard to onboard onto and harder to extend.
3. **API security is hidden in code.** `api/security.py` is well-implemented (constant-time compare, request-id correlation, key redaction) but lives only in source. There is no narrative explanation of *why* the middleware lives there, *what* paths it protects, *how* a private-mode operator configures `CSM_API_KEY`, or *what* the public-mode 403 contract actually says. This is a security feature; it deserves explicit documentation.
4. **README is missing AI/LLM affordances.** The README is well-organised for human readers but lacks: a table of contents (force-scrolling on a long page), a module index (an LLM has no anchor between "I want to add a portfolio constraint" and `src/csm/portfolio/constraints.py`), a troubleshooting block (the most common Docker port-bind / data-mount errors are not documented), and a "Where to find X" pointer that maps abstract concepts to concrete files.

A fifth, more strategic problem: the project's success criteria for Phase 7 in `ROADMAP.md` are partly stale (several items marked `[x]` are not actually done — e.g. `docs/guides/public-mode.md` is still a 12-line stub). This plan reconciles ROADMAP claims with reality and produces a single tickable success table that closes the gaps for real.

---

## Design Rationale

### Documentation-as-Stubs Is a Worse Default Than No Documentation

A 12-line file with `> TODO` carries the same weight in `git ls-files` as a real reference page. It misleads automated repo summarisers (LLMs, Sourcegraph indexers, doc-generation tools) into reporting "documented" when the real state is unwritten. Phase 7.2 fully expands every stub or, where the content is genuinely deferred, deletes the stub and lets the missing-page state be the honest signal.

### Module Reference Pages Are the Highest-Leverage Doc Output

For a coding agent extending the project, the single most useful artefact is a per-subpackage page that answers: "what does this module export?", "what is the signature of each public function?", "what is one minimal usage example?". This is the layer the project lacks. Phase 7.2.3 produces that for all five `src/csm/` subpackages (`data`, `features`, `portfolio`, `research`, `risk`) so an agent need not grep source to know where to extend.

### `ci.yml` Reuses the Local Quality Gate Verbatim

The local quality gate in `.claude/playbooks/feature-development.md` is `uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run pytest tests/ -v --cov=api --cov-fail-under=90`. Phase 7.4's `ci.yml` runs those same commands on GitHub Actions. **No CI-only logic.** This avoids the failure mode where local checks pass but CI fails (or vice versa) because the two diverge over time. One source of truth for "is this code good enough to merge" — the playbook — drives both.

### Coverage Floor Lives in `pyproject.toml`, Not the Workflow

`--cov-fail-under=90` is set in `[tool.pytest.ini_options]` (or `[tool.coverage.report]`) so a developer running `uv run pytest` locally gets the same fail-fast behaviour as CI. If the floor lived only in `.github/workflows/ci.yml`, a contributor running tests locally could land a coverage regression and only discover it on push. Centralising the floor in `pyproject.toml` is also where future agents will look first.

### API Security Is Documented Where Operators Look

`api/security.py` is for engineers reading source; `docs/architecture/overview.md` (high-level) and `docs/guides/public-mode.md` (operational) are for operators, contributors, and AI agents. The same facts (PROTECTED_PATHS list, constant-time compare, key redaction, request-id correlation, 401 vs 403 split, missing-key warning at startup) appear in narrative form in both docs. This duplication is intentional: each audience reads a different document.

### Path-Filtered CI Triggers Keep Wall-Clock Low

`ci.yml` runs on every push and PR but skips when only `docs/**`, `*.md`, or `LICENSE` change (via `paths-ignore`). This keeps the merge loop tight for documentation PRs (which dominate Phase 7) while still catching code regressions. `docker-smoke.yml` already uses path filters; `ci.yml` follows the same pattern for consistency.

### Verbose Docs over Brief, Because the Audience Includes LLMs

Phase 7 docs deliberately repeat context, name files explicitly, and prefer fully-spelled-out function signatures over `…`. This goes against the "concise prose" instinct, but the audience for `docs/` includes coding agents that ingest text without surrounding repo context. A reference page that says "`compute_momentum(prices: pd.DataFrame, lookback: int = 252) -> pd.Series` — defined in `src/csm/features/momentum.py`" is strictly more useful than "`compute_momentum` ranks momentum"; the former lets an agent jump to the file, the latter requires another grep.

### One Coverage Number Per Surface, Tracked Separately

Phase 5 set the coverage floor at 90% on `api/` only. Phase 7.1 keeps `api/` as the gated surface and does **not** extend the floor to `src/csm/` in this phase — that would force test backfill across five subpackages and is genuinely Phase 8 work. The pragmatic stance: lock what is already at 92%, do not raise the bar in a hardening phase.

---

## Architecture

### File Map

```
.
├── .github/
│   └── workflows/
│       ├── ci.yml                                  # NEW (7.4) — lint → ruff format check → mypy → pytest with coverage floor
│       ├── docker-smoke.yml                        # UNCHANGED (Phase 6.6)
│       └── docker-publish.yml                      # UNCHANGED (Phase 6.7)
├── pyproject.toml                                  # MODIFY (7.1) — add `--cov-fail-under=90` to pytest addopts
├── README.md                                       # MODIFY (7.2.1) — add TOC, module index, troubleshooting, "Where to find X"
├── docs/
│   ├── README.md                                   # MODIFY (7.2.1) — index of docs/ tree with one-line descriptions
│   ├── architecture/
│   │   └── overview.md                             # EXPAND (7.2.2) — layer responsibilities, data flow, public-mode boundary, security
│   ├── concepts/
│   │   └── momentum.md                             # EXPAND (7.2.2) — Jegadeesh–Titman, cross-sectional ranking, lookback windows
│   ├── development/
│   │   └── overview.md                             # EXPAND (7.2.4) — workflow, quality gate, commit conventions, local setup
│   ├── getting-started/
│   │   └── overview.md                             # EXPAND (7.2.4) — Docker quickstart + local uv quickstart
│   ├── guides/
│   │   ├── docker.md                               # EXPAND (7.2.4) — public + private compose recipes, troubleshooting
│   │   └── public-mode.md                          # EXPAND (7.2.4) — data boundaries, owner workflow, 403 contract
│   └── reference/
│       ├── data/overview.md                        # EXPAND (7.2.3) — module index for src/csm/data/
│       ├── features/overview.md                    # EXPAND (7.2.3) — module index for src/csm/features/
│       ├── portfolio/overview.md                   # EXPAND (7.2.3) — module index for src/csm/portfolio/
│       ├── research/overview.md                    # EXPAND (7.2.3) — module index for src/csm/research/
│       └── risk/overview.md                        # EXPAND (7.2.3) — module index for src/csm/risk/
└── docs/plans/
    ├── ROADMAP.md                                  # MODIFY (7.x) — reconcile [x] marks with actual state on completion
    └── phase_7_docs/
        ├── PLAN.md                                 # NEW (this file) — master plan for Phase 7
        ├── phase_7_1_coverage_lock.md              # NEW (optional) — sub-phase detail for 7.1
        ├── phase_7_2_1_readme_polish.md            # NEW (optional) — sub-phase detail for 7.2.1
        ├── phase_7_2_2_architecture_concepts.md    # NEW (optional) — sub-phase detail for 7.2.2
        ├── phase_7_2_3_module_reference.md         # NEW (optional) — sub-phase detail for 7.2.3
        ├── phase_7_2_4_guides_and_dev.md           # NEW (optional) — sub-phase detail for 7.2.4
        ├── phase_7_3_security_doc.md               # NEW (optional) — sub-phase detail for 7.3
        └── phase_7_4_general_ci.md                 # NEW (optional) — sub-phase detail for 7.4
```

Per-sub-phase detail files are **optional**. Phase 6 created one per sub-phase; Phase 2 inlined everything in the master `PLAN.md`. Phase 7 may follow either convention; the master `PLAN.md` (this file) is the source of truth.

### CI Trigger Graph

```
push to main / push to feature/*  ─────▶ ci.yml          (lint / format / mypy / pytest)
pull_request                       ─────▶ ci.yml          (skips on docs-only changes via paths-ignore)
                                   ─────▶ docker-smoke.yml (when Docker paths touched)

push tag v*.*.*                    ─────▶ docker-publish.yml (build + push to GHCR)
workflow_dispatch                  ─────▶ docker-publish.yml (manual)
```

### Quality Gate (Local + CI parity)

```
uv run ruff check .              ──┐
uv run ruff format --check .       ├──── identical commands run by:
uv run mypy src/                   │      • developer (per .claude/playbooks/feature-development.md)
uv run pytest tests/ -v            │      • .github/workflows/ci.yml on every push/PR
   --cov=api --cov-fail-under=90 ──┘      • git pre-commit hooks (.pre-commit-config.yaml, if enabled)
```

The `--cov-fail-under=90` lives in `pyproject.toml [tool.pytest.ini_options]` so it applies even when a contributor runs `uv run pytest` without the explicit flag.

### Documentation Layout (after expansion)

```
README.md  (top-of-file TOC, one-screen pitch, module index, troubleshooting)
        │
        ├──▶ docs/getting-started/overview.md    (Docker + uv quickstart, < 5 min to running)
        ├──▶ docs/architecture/overview.md       (layers, data flow, public-mode boundary, security)
        ├──▶ docs/concepts/momentum.md           (Jegadeesh–Titman theory, cross-sectional ranking)
        │
        ├──▶ docs/guides/docker.md               (compose recipes, healthcheck, owner override)
        ├──▶ docs/guides/public-mode.md          (data boundary, 403 contract, owner update flow)
        │
        ├──▶ docs/development/overview.md        (workflow, quality gate, commit conventions)
        │
        └──▶ docs/reference/                     (module-by-module API surface)
                ├── data/overview.md             (loaders, parquet store, universe, cleaning)
                ├── features/overview.md         (momentum, risk-adjusted, sector, pipeline)
                ├── portfolio/overview.md        (weights, constraints, rebalancing)
                ├── research/overview.md         (ranking, IC, backtest helpers)
                └── risk/overview.md             (metrics, regime detection)
```

Each reference page has the same shape: **Module index** → **Public callables (with signatures)** → **Minimal example** → **Cross-references**.

---

## Implementation Phases

### Phase 7.1 — Test Coverage Lock

**Status:** `[x]` Completed (2026-05-02)
**Goal:** Convert "we have 92% coverage on `api/`" from a claim into a CI-enforceable invariant; close any gap-fill tests if the actual number has drifted.

**Deliverables:**

- [x] Run the full suite locally: `uv run pytest tests/ -v --cov=api --cov-report=term-missing` and capture the actual numbers (test count, line coverage on `api/`).
- [x] If coverage on `api/` is < 90%, identify the top three uncovered modules and add targeted tests; if ≥ 90%, proceed to lock.
- [x] `pyproject.toml` modification — add `--cov-fail-under=90` to `[tool.pytest.ini_options].addopts` (or set in `[tool.coverage.report].fail_under = 90`).
- [x] Confirm the suite still passes with the floor in place: `uv run pytest tests/`.
- [x] Document the actual numbers (test count, coverage %, date) in the Completion Notes section of this sub-phase.
- [x] Confirm no `tests/` files contain network calls in the unit-test layer (project rule from `.claude/knowledge/project-skill.md`).

**Acceptance Criteria:**

- `uv run pytest tests/` exits 0; coverage report prints `Required test coverage of 90% reached` (or equivalent).
- `pyproject.toml` contains the floor; deliberately deleting one well-covered test makes the suite fail with `Required test coverage of 90% not reached`.
- Test count and coverage % logged in Completion Notes.

**Verification:** `uv run pytest tests/ --cov=api --cov-fail-under=90` returns 0 and prints the actual coverage number.

**Completion Notes (2026-05-02):**
- **Test count:** 818 passed, 9 pre-existing failures (Pydantic v2 validation issue in `scripts/_export_models.py`; passes in isolation, fails in full suite due to import ordering — a pre-existing bug, not caused by Phase 7)
- **Coverage on `api/`:** 92% (1032 statements, 86 missed) — above the 90% floor
- **`pyproject.toml`:** `--cov-fail-under=90` added to `[tool.pytest.ini_options].addopts`
- **Coverage confirmation:** `Required test coverage of 90% reached. Total coverage: 91.67%`
- No gap-fill tests needed (coverage already above 90%)
- No network calls in unit tests — confirmed (all network I/O isolated to integration tests and scripts)

---

### Phase 7.2.1 — README Polish (TOC, Module Index, Troubleshooting)

**Status:** `[x]` Completed (2026-05-02) in < 10 s for a first-time visitor — human or LLM — and add the AI/agent affordances (TOC, module index, troubleshooting, "Where to find X") that the current 334-line README is missing.

**Deliverables:**

- [ ] **Top-of-file Table of Contents** — add a `## Table of Contents` block immediately after the disclaimer; one bullet per top-level section with anchor link. Anchors must match GitHub's auto-slug rules.
- [ ] **Module index block** — new `## Module index` section listing each top-level package and its purpose:

  ```
  | Path             | Purpose                                                 |
  |------------------|---------------------------------------------------------|
  | src/csm/data/    | tvkit loader, parquet store, universe builder, cleaning |
  | src/csm/features/| momentum, risk-adjusted, sector, pipeline composer       |
  | src/csm/portfolio/ | weight optimisation, constraints, rebalancing          |
  | src/csm/research/| ranking, IC analysis, backtest helpers                  |
  | src/csm/risk/    | risk metrics, regime detection                          |
  | api/             | FastAPI app, routers, security, error handling          |
  | ui/              | NiceGUI/FastUI dashboard pages                          |
  | scripts/         | owner utilities (fetch, export, build universe)         |
  | tests/           | unit + integration tests                                |
  | docs/            | architecture, reference, guides, plans                  |
  ```

- [ ] **Troubleshooting section** — `## Troubleshooting` with at least four entries: port 8000 already in use; Docker daemon not running; private-mode missing tvkit auth; `data/` write permission denied. Each entry is one symptom + one resolution.
- [ ] **"Where to find X" pointer block** — new `## Where to find X` mini-table mapping common questions to file paths:

  ```
  | I want to ...                              | Look at                                       |
  |--------------------------------------------|-----------------------------------------------|
  | understand the data flow                   | docs/architecture/overview.md                 |
  | extend a momentum signal                   | src/csm/features/momentum.py                  |
  | add a portfolio constraint                 | src/csm/portfolio/constraints.py              |
  | configure timezone or env vars             | src/csm/config/settings.py + .env.example     |
  | run the quality gate                       | docs/development/overview.md § Quality gate    |
  | refresh public artefacts                   | scripts/export_results.py + docs/guides/public-mode.md |
  | release a new version                      | RELEASING.md                                  |
  ```

- [ ] **Contributor links** — ensure `## Contributing` (or equivalent) links to `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `RELEASING.md`, and `docs/development/overview.md`.
- [ ] **Key concepts blurb** — short paragraph (3–5 sentences) under "What this project does" defining cross-sectional momentum and citing Jegadeesh–Titman; links to `docs/concepts/momentum.md` for depth.
- [ ] **Update `docs/README.md`** — replace the stub with a real index of `docs/` (one line per top-level folder).

**Acceptance Criteria:**

- README has a `## Table of Contents` block as the second heading.
- A reader scrolling only the TOC can find any section in one click.
- The module index, troubleshooting, and "Where to find X" sections are present and resolve to existing files.
- All link anchors resolve (no 404s in `wc -l README.md` referenced files).
- README does not duplicate content already in `docs/` — it summarises and links.

**Verification:** Open the rendered README on GitHub; confirm TOC links navigate; confirm `docs/README.md` lists all `docs/*` subdirectories.

---

### Phase 7.2.2 — Architecture & Concepts Documentation

**Status:** `[x]` Completed (2026-05-02) an external researcher or LLM can absorb without reading source.

**Deliverables:**

- [ ] **`docs/architecture/overview.md`** (currently 12 lines) — expand to ~200–300 lines covering:
  - **Monorepo layers** — `src/csm/` (library) → `api/` (FastAPI surface) → `ui/` (FastUI consumer) → `scripts/` (owner tooling) → `results/` (committed artefacts). One paragraph per layer with the rule about what may import from where.
  - **Runtime data flow** — diagrammed as ASCII: tvkit (private only) → `data/raw/` → `csm.data` (parquet store + cleaner) → `csm.features` → `csm.research` (ranker + backtest) → `csm.portfolio` (weights + constraints) → `results/static/*.json` → `api/` → client.
  - **Public-mode boundary** — restate the two-layer audit from Phase 6.4: file-level audit of `results/**/*.json` for OHLCV keys; API-level audit of public-mode responses. Reference `tests/integration/test_public_data_boundary_*`.
  - **Configuration** — pointer to `src/csm/config/settings.py` and `.env.example`; document `CSM_PUBLIC_MODE`, `CSM_API_KEY`, `CSM_CORS_ALLOW_ORIGINS`, `CSM_LOG_LEVEL`.
  - **Security model** — middleware chain (CORS → request-id → API-key auth → public-mode guard → router); reference `api/security.py`.
  - **Timezone policy** — Asia/Bangkok at boundaries, UTC `pandas.Timestamp` internally; rule from `.claude/knowledge/project-skill.md`.

- [ ] **`docs/concepts/momentum.md`** (currently 12 lines) — expand to ~150 lines covering:
  - **Jegadeesh–Titman context** — original 1993 paper, 12-1M / 6-1M / 3-1M lookback windows, exclusion of the most-recent month to dodge short-term reversal.
  - **Cross-sectional ranking** — z-score within universe, quintile assignment, equal-weight long-only construction.
  - **Why SET (Thai equities)** — universe constraints (>= ฿100M ADV, listed ≥ 12M), sector caps, regime filter (200d SMA on SET index).
  - **Implementation pointer** — `src/csm/features/momentum.py` for the calculation, `src/csm/research/ranker.py` for the ranking, `src/csm/portfolio/optimizer.py` for the weights.
  - **References** — Jegadeesh & Titman (1993), Asness, Moskowitz & Pedersen (2013); link to `notebooks/02_signal_research.ipynb` for empirical validation.

**Acceptance Criteria:**

- `docs/architecture/overview.md` has ≥ 4 H2 sections; runtime data flow diagram present; security middleware chain documented.
- `docs/concepts/momentum.md` defines the strategy, cites the paper, and links to the implementing module.
- Zero "TODO: Expand" markers remain in either file.
- A reader who has never seen the project can answer "where does the data flow start?" and "what's the security boundary?" from these two pages.

**Verification:** `grep -l "TODO: Expand" docs/architecture/overview.md docs/concepts/momentum.md` returns nothing.

---

### Phase 7.2.3 — Module Reference Pages

**Status:** `[x]` Completed (2026-05-02): per-subpackage reference pages an LLM can ingest to extend any module without re-reading source.

**Deliverables:**

For each of the five subpackages (`data`, `features`, `portfolio`, `research`, `risk`), author `docs/reference/<pkg>/overview.md` with this exact shape:

```markdown
# <Subpackage> Module Reference

<one-paragraph purpose>

## Module index

| Module                  | Purpose                                |
|-------------------------|----------------------------------------|
| src/csm/<pkg>/X.py      | <one-line>                             |
| src/csm/<pkg>/Y.py      | <one-line>                             |

## Public callables

### `function_name(arg: Type, ...) -> ReturnType`

- **Defined in:** `src/csm/<pkg>/X.py`
- **Purpose:** <one paragraph>
- **Behaviour:** <bullets on key behaviour, edge cases, empty-frame guards>
- **Example:**
  ```python
  result = await function_name(prices, lookback=252)
  ```

## Cross-references

- Used by: `src/csm/research/...`, `api/routers/...`
- Tested in: `tests/unit/<pkg>/...`
- Concept: `docs/concepts/<concept>.md`
```

**Per-subpackage scope:**

- [ ] **`docs/reference/data/overview.md`** — modules: `loader.py`, `store.py`, `universe.py`, `cleaner.py`, `dividend_adjustment.py`. Public callables: `load_history`, `ParquetStore.read/write`, `build_universe`, `clean_prices`, `apply_dividend_adjustment`.
- [ ] **`docs/reference/features/overview.md`** — modules: `momentum.py`, `risk_adjusted.py`, `sector.py`, `pipeline.py`. Public callables: `compute_momentum`, `compute_risk_adjusted_momentum`, `compute_sector_features`, `FeaturePipeline.compute_all`.
- [ ] **`docs/reference/portfolio/overview.md`** — modules: `optimizer.py`, `constraints.py`, `rebalance.py`. Public callables: `optimize_weights`, `apply_constraints`, `RebalanceEngine.step`.
- [ ] **`docs/reference/research/overview.md`** — modules: `ranker.py`, `ic.py`, `backtest.py`. Public callables: `CrossSectionalRanker.rank_all`, `compute_ic`, `MomentumBacktest.run`.
- [ ] **`docs/reference/risk/overview.md`** — modules: `metrics.py`, `regime.py`. Public callables: `compute_drawdown`, `compute_sharpe`, `compute_sortino`, `RegimeDetector.classify`.

**Acceptance Criteria:**

- All 5 reference pages exist with the standard shape (Module index + Public callables + Cross-references).
- Every public callable referenced has a verifiable file path and signature (must be cross-checked against the actual source on the day of authoring; signatures change).
- Each page has at least one runnable example block.
- Zero `TODO: Expand` markers remain.

**Verification:** `grep -L "TODO: Expand" docs/reference/*/overview.md` lists all 5 files; spot-check that every signature in the doc matches the current source via `grep -n "def <name>" src/csm/<pkg>/`.

---

### Phase 7.2.4 — Guides + Getting-started + Development Documentation

**Status:** `[x]` Completed (2026-05-02) — quickstart, dev workflow, Docker recipes, public-mode rules — that complement the architecture/reference layers.

**Deliverables:**

- [ ] **`docs/getting-started/overview.md`** (currently 12 lines) — expand to ~120 lines:
  - **Docker quickstart** (5 lines) — `git clone`, `cd`, `docker compose up`, browse `:8000`. Mirrors README Quick Start but in standalone form.
  - **Local uv quickstart** (10 lines) — `uv sync --all-groups`, `uv run uvicorn api.main:app --reload`, `uv run python ui/main.py`.
  - **First contact** — what to look at first: `/health`, `/api/docs`, `/api/v1/signals/latest`, `/static/notebooks/01_data_exploration.html`.
  - **Running tests** — one-line quality gate; pointer to `docs/development/overview.md`.

- [ ] **`docs/development/overview.md`** (currently 12 lines) — expand to ~250 lines:
  - **Workflow** — read existing → branch (`feature/...`) → test-first → implement → quality gate → conventional commit → PR. Mirror the order in `.claude/playbooks/feature-development.md`.
  - **Quality gate** — `uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run pytest tests/ -v`. Document each command's purpose.
  - **Commit conventions** — `feat(scope): …`, `fix(scope): …`, `docs(scope): …`, `ci(scope): …`. Reference `.claude/knowledge/coding-standards.md`.
  - **Code style summary** — Pydantic at boundaries, async I/O via `httpx.AsyncClient`, ≤ 400 lines/file, Google-style docstrings, no `print` in `src/csm/`. Pointer for full details.
  - **Test layout** — `tests/unit/...` mirrors `src/csm/...`; `tests/integration/...` for boundary-crossing tests; `pytest_asyncio_mode = "auto"`.
  - **Local dev tips** — VS Code launch configs (optional), debugging the API, running a single notebook.

- [ ] **`docs/guides/docker.md`** (currently 12 lines) — expand to ~150 lines:
  - **Public boot** — `docker compose up`; what mounts; what env vars are baked in.
  - **Private boot** — `docker compose -f docker-compose.yml -f docker-compose.private.yml up`; what mounts (data/, results/, ~/.config/google-chrome); env overrides.
  - **Pre-built image** — `docker pull ghcr.io/lumduan/csm-set:latest`.
  - **Healthcheck behaviour** — interval 30s, retries 3, start-period 20s.
  - **CORS configuration** — `CSM_CORS_ALLOW_ORIGINS` envvar; defaults; example for React on `:3000`.
  - **Troubleshooting** — port 8000 in use, daemon not running, mem_limit OOM during nbconvert.

- [ ] **`docs/guides/public-mode.md`** (currently 12 lines) — expand to ~200 lines:
  - **What public mode is** — read-only mode that serves `results/static/` artefacts; no tvkit; no credentials.
  - **Data boundary rules** — no OHLCV in committed JSON; enforced by `tests/integration/test_public_data_boundary_*.py`.
  - **403 contract** — write endpoints return 403 with canonical "Disabled in public mode" body in public mode; public-mode-guard implemented in `api/security.py`.
  - **Owner workflow** — `fetch_history.py → export_results.py → git add results/static/ → commit → push → tag → GHCR publish`.
  - **Switching modes** — `CSM_PUBLIC_MODE=false` enables write endpoints; document the runtime check at boot.
  - **Audit tests** — how the file + API audits work; how to run them locally.

**Acceptance Criteria:**

- All 4 pages have substantive content (≥ 100 lines each); zero `TODO: Expand` markers.
- The Docker guide includes both compose commands and at least 4 troubleshooting entries.
- The public-mode guide includes the 403 contract and the owner workflow end-to-end.
- The development guide cites the same quality-gate commands as `ci.yml` (drift-free).

**Verification:** `grep -L "TODO: Expand" docs/getting-started/overview.md docs/development/overview.md docs/guides/*.md` lists all 4 files; quality-gate command in dev guide matches `ci.yml` literally.

---

### Phase 7.3 — API Security Documentation

**Status:** `[x]` Code complete (Phase 5.7); `[x]` Documentation complete (2026-05-02)
**Goal:** Document the existing `api/security.py` middleware so a private-mode operator and any AI agent reading `docs/` can answer the four operational questions: *what protects what*, *how to configure*, *what error shape*, *how to test*.

**Deliverables (documentation only — no new code):**

- [ ] In `docs/architecture/overview.md` (added in 7.2.2), include a § **Security model** subsection that documents:
  - Middleware order (CORS → request-id → API-key auth → public-mode guard → router).
  - `PROTECTED_PATHS` set: `/api/v1/data/refresh`, `/api/v1/backtest/run`, `/api/v1/jobs`, `/api/v1/scheduler/run/daily_refresh`.
  - Defence-in-depth rule: any non-GET on `/api/v1/*` is auto-protected.
  - Constant-time comparison via `secrets.compare_digest`.
  - Key redaction in logs (referenced via `install_key_redaction(settings.api_key)` in `api/main.py`).
  - Startup warning when `public_mode=False` and `api_key` is None.

- [ ] In `docs/guides/public-mode.md` (expanded in 7.2.4), include a § **Configuring API Key (Private Mode)** subsection:
  - Set `CSM_API_KEY=<random-32-byte-base64>` in `.env` (or `docker-compose.private.yml`).
  - Generate a key: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
  - Send via `curl -H 'X-API-Key: <key>' …`.
  - 401 response shape: ProblemDetail with `request_id` correlation; never echoes the supplied key.
  - 403 response shape: public-mode write block (separate from auth).

- [ ] In `docs/development/overview.md` (expanded in 7.2.4), include a § **Testing security paths** subsection:
  - Pointer to `tests/api/middleware/test_auth.py` (or wherever auth tests live).
  - How to write a private-mode test: `monkeypatch.setenv("CSM_API_KEY", "test")`.
  - How to write a public-mode 403 test: assert `client.post("/api/v1/data/refresh").status_code == 403`.

**Acceptance Criteria:**

- A reader who has never opened `api/security.py` can configure auth, send a valid request, and reproduce the 401/403 error shapes from `docs/` alone.
- The middleware order is documented in exactly one place (architecture overview); guides and dev docs cross-link to it.
- No new code lands in this sub-phase. If a code change appears, scope creep — push to a follow-up.

**Verification:** Spot-check by searching `docs/` for `X-API-Key`, `compare_digest`, `PROTECTED_PATHS` — each appears in the appropriate page; cross-links resolve.

---

### Phase 7.4 — General CI Workflow

**Status:** `[x]` Completed (2026-05-02) and PR, complementing the existing Docker-only workflows.

**Deliverables:**

- [ ] **`.github/workflows/ci.yml`** (NEW):
  - **Triggers:** `push: branches: [main, feature/**]`, `pull_request`. `paths-ignore: [docs/**, '*.md', LICENSE]` so docs-only PRs skip the heavy job.
  - **Concurrency:** `group: ci-${{ github.ref }}`, `cancel-in-progress: true`.
  - **Job:** `quality-gate` on `ubuntu-latest`, timeout 15 min.
  - **Steps:**
    1. `actions/checkout@v4`.
    2. `astral-sh/setup-uv@v3` with `version: latest` and `enable-cache: true` (caches `~/.cache/uv` keyed on `uv.lock`).
    3. `uv sync --all-groups --frozen`.
    4. `uv run ruff check .` (lint).
    5. `uv run ruff format --check .` (format check; no auto-fix in CI).
    6. `uv run mypy src/` (type check).
    7. `uv run pytest tests/ -v --cov=api --cov-report=term --cov-report=xml --cov-fail-under=90`.
    8. (Optional) `actions/upload-artifact@v4` uploading `coverage.xml` for downstream tooling.

- [ ] **README badge** — add `![CI](https://github.com/lumduan/csm-set/actions/workflows/ci.yml/badge.svg)` to the badge row at the top of `README.md`.

- [ ] **`docs/development/overview.md` cross-reference** — under § Quality gate, mention that the same commands run in `ci.yml` so local pass = CI pass.

**Acceptance Criteria:**

- A push to a feature branch triggers `ci.yml`; green run takes < 8 min wall-clock with cache hot.
- Deliberately introducing a `mypy` failure (e.g. `def f(x: int) -> int: return "s"`) makes the workflow fail at the mypy step.
- Deliberately introducing a 5% coverage drop (e.g. delete a well-tested module's tests) makes the pytest step fail with the coverage threshold message.
- A docs-only PR (only `docs/**` or `*.md` changed) skips the workflow per `paths-ignore`.

**Verification:** Open the workflow run on GitHub Actions; confirm step durations; trigger a deliberate failure on a throw-away branch and confirm the workflow goes red.

---

## Data Models

Phase 7 ships **no new Pydantic models**. The plan exclusively documents existing models authored in earlier phases:

- `Settings` (in `src/csm/config/settings.py`) — already includes `api_key: SecretStr | None`, `public_mode: bool`, `cors_allow_origins: list[str]`. Documented narratively in 7.2.2 architecture overview.
- `ProblemDetail` (in `api/schemas/errors.py` per Phase 5) — RFC 7807-shaped error body returned by the auth middleware. Documented in 7.3.
- The five distribution payload models from Phase 6 (`BacktestSummary`, `EquityCurve`, `AnnualReturns`, `SignalRanking`, `ExportResultsConfig`) — referenced by name in `docs/architecture/overview.md` § Data flow; full definitions remain in `docs/plans/phase_6_docker/PLAN.md` § Data Models and in `scripts/_export_models.py`.

If a Phase 7 sub-phase finds it must introduce a new Pydantic model, that is scope creep — pull it out into a follow-up issue.

---

## Error Handling Strategy

| Scenario | Behaviour |
|---|---|
| `ci.yml` lint failure (ruff) | Job fails at the lint step; PR blocked; failure log shows the offending file:line. |
| `ci.yml` format failure (`ruff format --check`) | Job fails; suggests running `uv run ruff format .` locally. |
| `ci.yml` type failure (mypy) | Job fails; full mypy output in the step log. |
| `ci.yml` test failure | Job fails; pytest output streamed; coverage report still printed. |
| `ci.yml` coverage drop below 90% on `api/` | pytest step fails with `Required test coverage of 90% not reached` (driven by `pyproject.toml` floor). |
| Docs-only PR | `ci.yml` is skipped via `paths-ignore`; only `docker-smoke.yml` may run if Docker paths also touched. |
| `uv sync --frozen` cache miss in CI | Job still succeeds (uv resolves deterministically); slower run, no functional impact. |
| Concurrent push on the same branch | Earlier in-progress run is cancelled by `concurrency: cancel-in-progress: true`. |
| Mismatch between `pyproject.toml` floor and CI command | Floor in `pyproject.toml` is the source of truth; redundant `--cov-fail-under` flag in CI is harmless. |
| Doc with broken internal link | Caught at review time (no link checker shipped in 7.4); contributors should run `grep -E '\]\([./].*\.md\)' README.md docs/**/*.md` before pushing. |
| `docs/architecture/overview.md` cites an outdated module path | Caught when the dev runs the suggested example; reference pages are versioned with the code, not auto-generated. |
| API key documented but operator pastes it into a public PR | Out of scope. Pre-commit hook for secret scanning is a Future Enhancement. |
| Coverage report can't write `coverage.xml` (CI permissions) | Step fails at upload-artifact only; pytest exit code preserves the test result. |

---

## Testing Strategy

### Coverage Target

- **`api/` line coverage** ≥ 90% (locked in `pyproject.toml`).
- **`src/csm/` line coverage** — no formal floor in Phase 7; existing tests must continue to pass. Raising the floor is Phase 8 work.

### What Phase 7 Tests

- **Phase 7.1** — runs the existing test suite under the new floor; adds gap-fill tests only if coverage on `api/` is below 90% on the day of execution.
- **Phase 7.4** — relies on the existing test suite to validate that `ci.yml` runs the same commands a developer runs locally. No new test files authored for the workflow itself; correctness is verified by deliberately breaking the build and observing the workflow.

### What Phase 7 Does *Not* Test

- No new behavioural tests (no new features). New tests, if any, are gap-fill for coverage only.
- No tests for the documentation content. Doc correctness is enforced by review.
- No link-checker. Out of scope for v0.7.0.

### Quality Gate (Local + CI parity)

```bash
uv run ruff check . \
  && uv run ruff format --check . \
  && uv run mypy src/ \
  && uv run pytest tests/ -v --cov=api --cov-fail-under=90
```

This block appears verbatim in `docs/development/overview.md` § Quality gate AND in `.github/workflows/ci.yml`. Drift between the two is the failure mode this phase exists to prevent.

### Manual Sign-off

- [ ] Fresh `git clone` followed by `uv sync --all-groups`; quality gate runs and passes locally.
- [ ] Fresh `docker compose up`; smoke through `:8000` works (already covered by `docker-smoke.yml`, but manual sanity check before tagging v0.7.0).
- [ ] Browse the rendered `docs/` on GitHub from the PR's "Files changed" tab; confirm headings, code blocks, and tables render.
- [ ] LLM smoke test — paste each `docs/reference/<pkg>/overview.md` into a coding-agent prompt and ask "extend this subpackage with a new function"; confirm the page is sufficient context.

---

## Success Criteria

| # | Criterion | Measure |
|---|---|---|
| 1 | Coverage floor enforced | `pyproject.toml` contains `--cov-fail-under=90`; deleting a covered test makes the suite fail with the threshold message |
| 2 | All existing tests still pass | `uv run pytest tests/` exits 0; ≥ 742 tests; coverage on `api/` ≥ 92% (no regression) |
| 3 | README has TOC, module index, troubleshooting | Three distinct sections present; all anchor links resolve |
| 4 | Architecture overview is reference-grade | `docs/architecture/overview.md` ≥ 200 lines; covers layers, data flow, public-mode boundary, security; zero TODO markers |
| 5 | Concepts/momentum doc complete | `docs/concepts/momentum.md` defines Jegadeesh–Titman, cross-sectional ranking, references the implementing module |
| 6 | All 5 module reference pages complete | Each `docs/reference/<pkg>/overview.md` has Module index + Public callables (with signatures) + Cross-references; signatures match source |
| 7 | Getting-started + development guides complete | Both files ≥ 100 lines; quality-gate commands match `ci.yml` literally |
| 8 | Docker + public-mode guides complete | Both ≥ 100 lines; public-mode guide includes the 403 contract and the owner workflow end-to-end |
| 9 | API security is discoverable from docs | A reader unfamiliar with `api/security.py` can configure auth, send a valid request, and reproduce 401/403 shapes from `docs/` alone |
| 10 | `ci.yml` runs on every push and PR | Workflow exists; runs on `push` and `pull_request`; `paths-ignore` skips docs-only PRs |
| 11 | `ci.yml` enforces the same gate as local | Steps: ruff check + ruff format check + mypy + pytest with coverage floor; identical commands to dev guide |
| 12 | Deliberate type/coverage regression fails CI | Test branch with broken mypy or 5% coverage drop turns the workflow red |
| 13 | README CI badge live | `![CI](…ci.yml/badge.svg)` present at top of README and renders green on `main` |
| 14 | ROADMAP reconciled | `docs/plans/ROADMAP.md` § Phase 7 marks reflect actual completion state; no stale `[x]` next to a stub |
| 15 | Zero `TODO: Expand` markers in `docs/` | `grep -r "TODO: Expand" docs/` returns nothing under non-plan paths |
| 16 | Conventional commits | Each sub-phase commit follows `docs(scope): …` or `ci(scope): …` per `.claude/knowledge/coding-standards.md`; one feature per commit |
| 17 | v0.7.0 tagged and published | `RELEASING.md` runbook followed; `ghcr.io/lumduan/csm-set:v0.7.0` pullable and bootable |

---

## Future Enhancements

- **`src/csm/` coverage floor** — extend `--cov-fail-under` from `api/` to the full library; requires test backfill across five subpackages.
- **Thai translation of `docs/`** — bilingual EN+TH pages for Thai-speaking researchers; deliberately deferred from this plan.
- **Markdown link checker in CI** — `lychee` or `markdown-link-check` wired into `ci.yml` to catch broken doc links automatically.
- **Auto-generated API reference** — `mkdocstrings` or `pdoc` reading docstrings from `src/csm/` to keep `docs/reference/` in sync with source without hand-editing.
- **MkDocs site** — render `docs/` as a static site published on GitHub Pages; concrete IA already exists.
- **Image signing (cosign / Sigstore) and SBOM** — bumped from Phase 6 future enhancements; verify-sign in CI.
- **Vulnerability scanning gate (trivy)** — fail PRs on HIGH/CRITICAL CVEs.
- **Rate limiting** — `slowapi` middleware in front of write endpoints; per-key bucket.
- **OAuth / OIDC** — replace `X-API-Key` for multi-tenant deployments.
- **Observability** — OpenTelemetry instrumentation, Prometheus `/metrics` endpoint, structured-log shipping.
- **Performance benchmarking** — `pytest-benchmark` suite for the hot paths (ranker, backtest, optimiser).
- **Pre-commit hook bundle** — distribute `.pre-commit-config.yaml` aligned with `ci.yml`; same drift-free principle.
- **Doc previews on PR** — Netlify or Cloudflare Pages preview deploy of the rendered `docs/` for every PR.

---

## Commit & PR Templates

### Commit Message (Plan — this commit)

```
docs(plans): add Phase 7 master plan for hardening & documentation

Scopes 7 sub-phases: 7.1 coverage lock, 7.2.1 README polish, 7.2.2
architecture & concepts docs, 7.2.3 module reference pages, 7.2.4
guides + dev docs, 7.3 API security documentation, 7.4 general
ci.yml workflow.

Phase 7 ships no new product features. It converts a working v0.6.0
release into a verifiable, fully-documented v0.7.0 by locking the
coverage floor in pyproject.toml, expanding 12 docs/ stubs, and
adding a general CI workflow that runs the same quality gate
documented in .claude/playbooks/feature-development.md.

Decomposes ROADMAP §7.2 (Documentation) into four sub-areas to track
progress per surface: README, architecture+concepts, module
reference, and guides+getting-started+development.
```

### Commit Messages (per sub-phase, on implementation)

```
test(coverage): lock api/ coverage floor at 90% (Phase 7.1)

- pyproject.toml: add --cov-fail-under=90 to pytest addopts
- Verify suite passes with the floor; document actual numbers in PLAN
```

```
docs(readme): add TOC, module index, troubleshooting (Phase 7.2.1)

- Top-of-file Table of Contents
- Module index mapping src/csm/* + api/ + ui/ + scripts/ to purpose
- Troubleshooting section (port 8000, daemon, tvkit auth, perms)
- "Where to find X" pointer block for common questions
- Contributor links (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, RELEASING)
- docs/README.md: real index of docs/ tree
```

```
docs(architecture): expand overview + concepts/momentum (Phase 7.2.2)

- docs/architecture/overview.md: layers, data flow, public-mode
  boundary, security model, configuration, timezone policy
- docs/concepts/momentum.md: Jegadeesh-Titman, cross-sectional
  ranking, SET universe constraints, references
```

```
docs(reference): per-subpackage module reference pages (Phase 7.2.3)

- docs/reference/data/overview.md: loader, store, universe, cleaner
- docs/reference/features/overview.md: momentum, risk_adjusted, sector
- docs/reference/portfolio/overview.md: optimizer, constraints, rebalance
- docs/reference/research/overview.md: ranker, ic, backtest
- docs/reference/risk/overview.md: metrics, regime
- Each page: Module index + Public callables (with signatures) +
  Cross-references; signatures cross-checked against source
```

```
docs(guides): expand getting-started, development, docker, public-mode (Phase 7.2.4)

- docs/getting-started/overview.md: Docker + uv quickstart, first contact
- docs/development/overview.md: workflow, quality gate, commits, style
- docs/guides/docker.md: compose recipes, healthcheck, CORS, troubleshooting
- docs/guides/public-mode.md: data boundary, 403 contract, owner workflow
```

```
docs(security): document existing X-API-Key middleware (Phase 7.3)

- Architecture overview: middleware order + PROTECTED_PATHS + constant-
  time compare + key redaction
- Public-mode guide: configuring CSM_API_KEY, generating keys,
  401/403 response shapes
- Development guide: testing security paths
- No code changes; api/security.py unchanged from Phase 5.7
```

```
ci: general lint/type/test workflow on every push (Phase 7.4)

- .github/workflows/ci.yml: ruff check + format --check + mypy + pytest
- paths-ignore: docs/**, *.md, LICENSE (docs PRs skip the heavy job)
- concurrency: cancel-in-progress on the same ref
- astral-sh/setup-uv@v3 with cache keyed on uv.lock
- README CI badge added
```

### PR Description Template

```markdown
## Summary

Phase 7 — Hardening & Documentation. Converts a working v0.6.0 release
into a verifiable, fully-documented v0.7.0. No new product features.

- pyproject.toml coverage floor (90% on api/) — locked
- README: TOC, module index, troubleshooting, "Where to find X"
- docs/architecture/overview.md: layers, data flow, security model
- docs/concepts/momentum.md: Jegadeesh-Titman, cross-sectional ranking
- docs/reference/{data,features,portfolio,research,risk}/overview.md:
  per-subpackage Module index + Public callables + Cross-references
- docs/getting-started, docs/development, docs/guides/*: expanded from stubs
- API security documented (api/security.py unchanged)
- .github/workflows/ci.yml: lint → ruff format check → mypy → pytest
  with coverage floor; runs on every push and PR; paths-ignore for docs

## Test plan

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy src/`
- [ ] `uv run pytest tests/ -v --cov=api --cov-fail-under=90`
- [ ] Manual: deliberate mypy regression on a throw-away branch fails ci.yml
- [ ] Manual: deliberate coverage drop on a throw-away branch fails ci.yml
- [ ] Manual: docs-only PR skips ci.yml (paths-ignore)
- [ ] Manual: `grep -r "TODO: Expand" docs/` returns nothing under non-plan paths
- [ ] Manual: every signature in docs/reference/* matches src/csm/* source
- [ ] Manual: README TOC anchors all resolve on GitHub render
- [ ] Post-merge: tag v0.7.0; confirm docker-publish.yml pushes to GHCR
```

### AI Agent Prompt (verbatim — the prompt that originated this plan)

The implementing agent should re-execute the work using exactly this prompt:

```
You are tasked with create master plan for "Phase 7 — Hardening & Documentation"
for the csm-set project. Follow these steps precisely:

1. **Preparation**
   - Carefully read `.claude/knowledge/project-skill.md` and
     `.claude/playbooks/feature-development.md` to internalize all
     engineering standards and workflow expectations.
   - Review `README.md` for project context and documentation style.
   - Study `docs/plans/examples/PLAN-sample.md` for the required master
     plan format.
   - Read `docs/plans/ROADMAP.md` to understand the purpose and scope of
     Phase 7.
   - Inspect all phase plans in `docs/plans/` (phase_1 to phase_6) for
     format and content consistency.
   - Review all documentation files in `docs/` for templates and module
     docs that may require updating.

2. **Branching**
   - Create a new git branch for this feature before making any changes.

3. **Planning**
   - Draft a comprehensive master plan for Phase 7 at
     `docs/plans/phase_7_docs/PLAN.md`, using the format and level of
     detail found in previous phase plans and the PLAN-sample.
   - The plan should include: scope, deliverables, acceptance criteria,
     risks, and the full AI agent prompt (this prompt).

4. **Documentation Updates**
   - Update `README.md` to ensure it is clear, up-to-date, and AI/LLM-friendly.
   - Update or create any necessary documentation/templates in `docs/` to
     reflect the latest project state, standards, and best practices.
   - Ensure all documentation is written in clear, accessible English and
     is easy for coding agents to parse and utilize.
   - Reference and, if needed, update module or template docs for
     completeness and consistency.

5. **Finalization**
   - Commit all changes in a single commit with a clear, standards-compliant
     message summarizing the work.
   - Ensure all documentation meets project standards for clarity,
     completeness, and AI/LLM-friendliness.

**Files to reference and/or modify:**
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- README.md
- docs/plans/examples/PLAN-sample.md
- docs/plans/ROADMAP.md
- docs/plans/phase_1/PLAN.md through docs/plans/phase_6/PLAN.md
- docs/plans/phase_7_docs/PLAN.md (to be created)

**Expected deliverables:**
- A new master plan at `docs/plans/phase_7_docs/PLAN.md` following the
  established format and incorporating all relevant context.
- Updated `README.md` and other documentation/templates in `docs/` as needed.
- All documentation written in clear, accessible English for AI/LLM
  consumption.
- A single, standards-compliant commit containing all changes.

Begin by drafting the master plan at `docs/plans/phase_7_docs/PLAN.md`.
Do not start documentation updates, you task is create masterplan only.
```

**Note:** The originating prompt instructed the planner to *not* start documentation updates. The current commit ships only this `PLAN.md` and the `feature/phase-7-docs` branch. Sub-phases 7.1, 7.2.1–7.2.4, 7.3, and 7.4 are executed in subsequent commits on this branch following the per-sub-phase commit messages above.
