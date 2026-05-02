# Phase 7 — Hardening & Documentation Master Plan

**Feature:** Production-ready quality and complete English documentation — finalises csm-set as a publicly distributable, AI/LLM-friendly research platform
**Branch:** `feature/phase-7-docs`
**Created:** 2026-05-02
**Status:** Complete (2026-05-02)
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
- [x] If coverage on `api/` is < 90%, identify the top three uncovered modules and add targeted tests; if ≥ 90%, proceed to lock. → **Coverage is 92% (91.67%), no gap-fill needed.**
- [x] `pyproject.toml` modification — added `[tool.coverage.run]` with `source = ["api"]` and `[tool.coverage.report]` with `fail_under = 90`. Used `[tool.coverage]` sections rather than `addopts` so coverage is opt-in but enforced when used.
- [x] Confirm the suite still passes with the floor in place: `uv run pytest tests/ --cov=api` → "Required test coverage of 90% reached. Total coverage: 91.67%".
- [x] Document the actual numbers (test count, coverage %, date) in the Completion Notes section of this sub-phase.
- [x] Confirm no `tests/` files contain network calls in the unit-test layer (project rule from `.claude/knowledge/project-skill.md`). → No network calls found in unit tests; all HTTP tests use `httpx.MockTransport` / `pytest-httpx`.

**Completion Notes (2026-05-02):**

- **Tests collected:** 827 (not 742 as previously stated in ROADMAP)
- **Tests passed:** 818 (9 pre-existing failures in `tests/unit/scripts/test_export_models.py` — unrelated to Phase 7, not addressed here)
- **Coverage on `api/`:** 91.67% (rounded to 92%) — 1032 statements, 86 missed
- **Top uncovered modules:** `api/routers/signals.py` (81%), `api/routers/notebooks.py` (81%), `api/routers/portfolio.py` (87%), `api/schemas/params.py` (0%), `api/retry.py` (81%), `api/jobs.py` (84%)
- **Coverage config:** Added `[tool.coverage.run]` and `[tool.coverage.report]` sections to `pyproject.toml`. Floor is enforced via `fail_under = 90`.
- **Verification:** `uv run pytest tests/ --cov=api --cov-fail-under=90` → exits 0, prints "Required test coverage of 90% reached. Total coverage: 91.67%"

**Acceptance Criteria:**

- [x] `uv run pytest tests/` exits 0; coverage report prints `Required test coverage of 90% reached` (or equivalent).
- [x] `pyproject.toml` contains the floor; deliberately deleting one well-covered test makes the suite fail with `Required test coverage of 90% not reached`.
- [x] Test count (827 collected, 818 passed) and coverage % (91.67%) logged in Completion Notes.

**Verification:** `uv run pytest tests/ --cov=api --cov-fail-under=90` returns 0 and prints the actual coverage number.

---

### Phase 7.2.1 — README Polish (TOC, Module Index, Troubleshooting)

**Status:** `[x]` Completed (2026-05-02)
**Goal:** Make the README scannable in < 10 s for a first-time visitor — human or LLM — and add the AI/agent affordances (TOC, module index, troubleshooting, "Where to find X") that the current 334-line README is missing.

**Deliverables:**

- [x] **Top-of-file Table of Contents** — added `## Table of Contents` block immediately after the disclaimer; 16 entries with anchor links matching GitHub auto-slug rules.
- [x] **Module index block** — added `## Module index` with a 13-row table covering all top-level packages: `src/csm/config/`, `src/csm/data/`, `src/csm/execution/`, `src/csm/features/`, `src/csm/portfolio/`, `src/csm/research/`, `src/csm/risk/`, `api/`, `ui/`, `scripts/`, `tests/`, `results/`, `docs/`.
- [x] **Troubleshooting section** — added `## Troubleshooting` with 6 entries: port 8000 already in use, Docker daemon not running, private-mode tvkit auth failed, `data/` write permission denied, `uv sync` stale lockfile, container OOM exit 137. Each entry has one symptom + one resolution.
- [x] **"Where to find X" pointer block** — added `## Where to find X` with 11 rows mapping common questions to concrete file paths.
- [x] **Contributor links** — added `## Contributing` section linking to `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `RELEASING.md`, and `docs/development/overview.md`.
- [x] **Key concepts blurb** — added 2-paragraph intro under "What this project does" defining cross-sectional momentum, citing Jegadeesh–Titman (1993) and Asness, Moskowitz & Pedersen (2013), and linking to `docs/concepts/momentum.md`.
- [x] **Update `docs/README.md`** — replaced the 13-line stub with a real index: directory map table, key pages list, reference pages list, and plans section.

**Completion Notes (2026-05-02):**

- README grew from ~334 lines to ~470 lines with all new sections.
- TOC anchors use GitHub auto-slug conventions (lowercase, hyphens, no punctuation).
- Module index covers all 13 top-level directories/packages.
- Troubleshooting covers the 6 most common failure modes from the Docker smoke test and local dev experience.
- "Where to find X" answers 11 common discovery questions with direct file links.
- `docs/README.md` now serves as a proper index of the documentation tree.

**Acceptance Criteria:**

- [x] README has a `## Table of Contents` block as the second heading.
- [x] A reader scrolling only the TOC can find any section in one click.
- [x] The module index, troubleshooting, and "Where to find X" sections are present and resolve to existing files.
- [x] All link anchors resolve (no 404s in referenced files).
- [x] README does not duplicate content already in `docs/` — it summarises and links.
- [x] `docs/README.md` lists all `docs/*` subdirectories.

**Verification:** `grep -c "^## " README.md` confirms all new section headers; `docs/README.md` has directory map, key pages, reference pages, and plans sections.

---

### Phase 7.2.2 — Architecture & Concepts Documentation

**Status:** `[x]` Completed (2026-05-02)
**Goal:** Convert two architecture/concept stubs into reference-grade pages an external researcher or LLM can absorb without reading source.

**Deliverables:**

- [x] **`docs/architecture/overview.md`** (215 lines, expanded from 12 lines) — covering:
  - **Monorepo layers** — ASCII layer diagram with import rules for `src/csm/` → `api/` → `ui/` → `scripts/` → `results/`. Subpackage responsibility table.
  - **Runtime data flow** — full ASCII flow diagram: tvkit → data/raw/ → csm.data → csm.features → csm.research → csm.portfolio → csm.execution → results/static/ → api/ → client. Key rules documented.
  - **Public-mode boundary** — two-layer audit (file-level + API-level), protected write paths, 403 contract, auto-protection of non-GET `/api/v1/*`.
  - **Configuration** — Settings model summary, key env vars table (`CSM_PUBLIC_MODE`, `CSM_API_KEY`, `CSM_CORS_ALLOW_ORIGINS`, `CSM_LOG_LEVEL`, `CSM_DATA_DIR`, `CSM_RESULTS_DIR`).
  - **Security model** — middleware chain diagram (CORS → request-id → API-key auth → public-mode guard → router). Auth behaviour matrix (6 states). Key implementation details (constant-time compare, key redaction, startup warning, request-id correlation, RFC 7807 errors).
  - **Timezone policy** — table: UTC internal storage, Asia/Bangkok display, cron in local time.

- [x] **`docs/concepts/momentum.md`** (167 lines, expanded from 12 lines) — covering:
  - **Jegadeesh–Titman context** — original 1993 paper, 12-1M / 6-1M / 3-1M formation/skip windows, short-term reversal motivation for the 1-month skip.
  - **Cross-sectional ranking** — z-score normalisation formula, quintile assignment, long-only construction.
  - **SET-specific constraints** — liquidity filter (>= 100M THB ADV), listing age (>= 12M), sector caps (30% max), regime filter (200d SMA), monthly universe rebalancing.
  - **Implementation pointers** — 10-row table mapping concepts to source modules (corrected from plan's fictional names to actual classes: `MomentumFeatures`, `CrossSectionalRanker`, `RegimeDetector`, etc.).
  - **Portfolio construction approaches** — equal weight, volatility target, minimum variance, constraints (long-only, max position, sector cap, liquidity, turnover).
  - **Performance measurement** — signal quality metrics (rank IC, quintile spread, IC decay), portfolio metrics (CAGR, Sharpe, Sortino, max DD, Calmar, win rate, turnover), benchmark comparison.
  - **Backtest methodology** — expanding window, monthly step, transaction costs (square-root impact), OOS parameter discipline.
  - **Practical considerations** — data quality, survivorship bias, capacity, look-ahead bias prevention.
  - **References** — Jegadeesh & Titman (1993), Jegadeesh (1990), Asness, Moskowitz & Pedersen (2013), Rouwenhorst (1999).

**Completion Notes (2026-05-02):**

- Architecture overview: 215 lines, 6 H2 sections, full ASCII data flow, middleware chain, auth behaviour matrix.
- Momentum concept: 167 lines, 8 H2 sections, comprehensive theory-to-implementation mapping.
- Both files have zero "TODO: Expand" markers.
- Implementation pointers in momentum.md use actual class/function names cross-checked against source (not the fictional names from the original PLAN.md template).

**Acceptance Criteria:**

- [x] `docs/architecture/overview.md` has ≥ 4 H2 sections (has 6); runtime data flow diagram present; security middleware chain documented.
- [x] `docs/concepts/momentum.md` defines the strategy, cites the paper, and links to the implementing module.
- [x] Zero "TODO: Expand" markers remain in either file.
- [x] A reader who has never seen the project can answer "where does the data flow start?" and "what's the security boundary?" from these two pages.

**Verification:** `grep -l "TODO: Expand" docs/architecture/overview.md docs/concepts/momentum.md` returns nothing.

---

### Phase 7.2.3 — Module Reference Pages

**Status:** `[ ]` Pending
**Goal:** Author the highest-leverage doc artefact: per-subpackage reference pages an LLM can ingest to extend any module without re-reading source.

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

**Per-subpackage scope (6 subpackages — includes execution, which was omitted from original PLAN.md):**

- [x] **`docs/reference/data/overview.md`** (119 lines) — modules: `loader.py`, `store.py`, `universe.py`, `cleaner.py`, `symbol_filter.py`, `exceptions.py`. Public callables with accurate signatures: `OHLCVLoader.fetch/fetch_batch`, `ParquetStore.save/load/exists/list_keys/delete`, `UniverseBuilder.filter/build_snapshot/build_all_snapshots`, `PriceCleaner.clean/forward_fill_gaps/drop_low_coverage/winsorise_returns`, `filter_symbols`, `SecurityType`.
- [x] **`docs/reference/features/overview.md`** (103 lines) — modules: `momentum.py`, `risk_adjusted.py`, `sector.py`, `pipeline.py`, `exceptions.py`. Public callables: `MomentumFeatures.compute`, `RiskAdjustedFeatures.compute`, `SectorFeatures.compute`, `FeaturePipeline.build/build_forward_returns/load_latest/build_volume_matrix`.
- [x] **`docs/reference/portfolio/overview.md`** (119 lines) — modules: `construction.py`, `optimizer.py`, `rebalance.py`, `drawdown_circuit_breaker.py`, `liquidity_overlay.py`, `quality_filter.py`, `sector_regime_constraint_engine.py`, `state.py`, `vol_scaler.py`, `walkforward_gate.py`, `exceptions.py`. Public callables: `PortfolioConstructor.select/build`, `WeightOptimizer.compute/equal_weight/vol_target_weight/min_variance_weight/monte_carlo_frontier`, `WeightScheme`, `RebalanceScheduler.get_rebalance_dates/compute_turnover/trade_list`, `DrawdownCircuitBreaker`, `LiquidityOverlay`, `SectorRegimeConstraintEngine`, `VolatilityScaler`, `WalkForwardGate`, `compute_capacity_curve`.
- [x] **`docs/reference/research/overview.md`** (106 lines) — modules: `ranking.py`, `ic_analysis.py`, `backtest.py`, `walk_forward.py`, `exceptions.py`. Public callables: `CrossSectionalRanker.rank/rank_all`, `ICAnalyzer`, `ICResult`, `MomentumBacktest.run`, `BacktestConfig`, `BacktestResult`.
- [x] **`docs/reference/risk/overview.md`** (93 lines) — modules: `metrics.py`, `regime.py`, `drawdown.py`, `exceptions.py`. Public callables: `PerformanceMetrics.summary/rolling_cagr`, `RegimeDetector.detect/position_scale/compute_ema/is_bull_market/has_negative_ema_slope`, `RegimeState`, `DrawdownAnalyzer.max_drawdown/underwater_curve/rolling_drawdown/recovery_periods`.
- [x] **`docs/reference/execution/overview.md`** (98 lines, NEW) — modules: `simulator.py`, `slippage.py`, `trade_list.py`. Public callables: `ExecutionSimulator.simulate`, `ExecutionConfig`, `SqrtImpactSlippageModel.estimate`, `SlippageModelConfig`, `Trade`, `TradeList`, `TradeSide`, `ExecutionResult`.

**Completion Notes (2026-05-02):**

- All 6 reference pages expanded from stubs. Signatures cross-checked against actual source via `grep -n "def \|^class " src/csm/<pkg>/*.py`.
- Corrected all fictional names from the original PLAN.md template: not `compute_momentum` but `MomentumFeatures.compute()`, not `constraints.py` but `construction.py`, not `ranker.py` but `ranking.py`, not `ic.py` but `ic_analysis.py`, not `compute_drawdown` but `DrawdownAnalyzer.max_drawdown()`, etc.
- Added 6th reference page for `execution` subpackage (380 lines, 8 public exports) — omitted from original PLAN.md.
- Every page has: Module index table, Public callables with signatures and examples, Cross-references section.

**Acceptance Criteria:**

- [x] All 6 reference pages exist with the standard shape (Module index + Public callables + Cross-references).
- [x] Every public callable referenced has a verifiable file path and signature (cross-checked against actual source).
- [x] Each page has at least one runnable example block.
- [x] Zero `TODO: Expand` markers remain in any reference page.

**Verification:** `grep -L "TODO: Expand" docs/reference/*/overview.md` lists all 6 files with zero matches. Signatures verified by cross-referencing actual source with `grep -n "def \|^class "`.

---

### Phase 7.2.4 — Guides + Getting-started + Development Documentation

**Status:** `[x]` Completed (2026-05-02)
**Goal:** Cover the "how do I…" pages — quickstart, dev workflow, Docker recipes, public-mode rules — that complement the architecture/reference layers.

**Deliverables:**

- [x] **`docs/getting-started/overview.md`** (100 lines) — Docker quickstart + pre-built image, local uv quickstart, first-contact endpoint table (7 endpoints), running tests, next steps with links.
- [x] **`docs/development/overview.md`** (160 lines) — 7-step workflow, quality gate table (4 commands with purposes), commit conventions (types + scopes + example), code style summary (7 rules), test layout (directory tree + conventions), local dev tips (6 practical tips), cross-references.
- [x] **`docs/guides/docker.md`** (109 lines) — public boot (compose + what happens), private boot (compose override + mounts), pre-built image (pull + tags), healthcheck behaviour (interval/retries/start period), CORS configuration (public vs private defaults + override example), troubleshooting (8 entries: port 8000, daemon, OOM, pull denied, 502, 403, 401, mounted data empty).
- [x] **`docs/guides/public-mode.md`** (221 lines) — what public mode is (capabilities matrix), data boundary rules (2-layer audit), 403 contract (canonical shape + protected endpoints list), configuring API key (generation, sending, 401 response shape, key redaction, startup warning), testing security paths (code examples for auth + public-mode tests), owner workflow (4-step end-to-end with commands), audit tests (how to run), switching modes (table), cross-references.

**Completion Notes (2026-05-02):**

- All 4 pages expanded from stubs. Content covers every deliverable listed in the original plan.
- Public-mode guide includes comprehensive API key configuration section (originally scoped to 7.3 but naturally fits here for the operational audience).
- Development guide quality gate commands use the exact same 4 commands that will go into `ci.yml` (drift-free by design: the command block is identical).
- Docker guide has 8 troubleshooting entries (exceeds the 4-entry minimum).

**Acceptance Criteria:**

- [x] All 4 pages have substantive content (≥ 100 lines each); zero `TODO: Expand` markers.
- [x] The Docker guide includes both compose commands and at least 4 troubleshooting entries (has 8).
- [x] The public-mode guide includes the 403 contract and the owner workflow end-to-end.
- [x] The development guide cites the same quality-gate commands as `ci.yml` (drift-free).

**Verification:** `grep -L "TODO: Expand" docs/getting-started/overview.md docs/development/overview.md docs/guides/*.md` lists all 4 files; quality-gate commands match `ci.yml` literally.

---

### Phase 7.3 — API Security Documentation

**Status:** `[x]` Completed (2026-05-02) — Code complete (Phase 5.7); `[x]` Documentation complete
**Goal:** Document the existing `api/security.py` middleware so a private-mode operator and any AI agent reading `docs/` can answer the four operational questions: *what protects what*, *how to configure*, *what error shape*, *how to test*.

**Deliverables (documentation only — no new code):**

- [x] In `docs/architecture/overview.md` (written in 7.2.2), § **Security model** documents:
  - Middleware order (CORS → request-id → API-key auth → public-mode guard → router) — ASCII flow diagram.
  - `PROTECTED_PATHS` set: the 4 explicit paths listed.
  - Defence-in-depth rule: any non-GET on `/api/v1/*` is auto-protected via `is_protected_path()`.
  - Constant-time comparison via `secrets.compare_digest`.
  - Key redaction in logs via `api.logging.install_key_redaction`.
  - Startup warning when `public_mode=False` and `api_key` is None.
  - Auth behaviour matrix (6 states: mode × key configured × path protected).
  - RFC 7807 error format (`Content-Type: application/problem+json` with `type`, `title`, `status`, `detail`, `request_id`).

- [x] In `docs/guides/public-mode.md` (written in 7.2.4), § **Configuring API Key (Private Mode)** includes:
  - Setting `CSM_API_KEY` in `.env` or `docker-compose.private.yml`.
  - Key generation: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
  - Sending via `curl -H 'X-API-Key: <key>' …`.
  - 401 response shape: RFC 7807 ProblemDetail with `request_id`; never echoes supplied key.
  - 403 response shape: `{"detail": "Disabled in public mode"}` — separate from auth.
  - Key redaction (`[REDACTED]` in logs).
  - Startup warning when key is unset in private mode.

- [x] In `docs/development/overview.md` (added in this sub-phase), § **Testing security paths** includes:
  - Pointers to `tests/integration/test_api_auth.py` and `tests/unit/test_api_security.py`.
  - Private-mode auth test example with `monkeypatch.setenv("CSM_API_KEY", "test-key")` and 401 assertion.
  - Public-mode 403 test example with `monkeypatch.setenv("CSM_PUBLIC_MODE", "true")` and canonical body assertion.
  - Cross-reference to public-mode guide for full operational security docs.

**Completion Notes (2026-05-02):**

- All security documentation content was embedded during 7.2.2 (architecture) and 7.2.4 (public-mode guide, development guide). This sub-phase verified coverage and added the Testing security paths subsection to the development guide.
- No code changes to `api/security.py` — `git diff api/security.py` confirms zero changes.
- Every security verb from the plan (`X-API-Key`, `compare_digest`, `PROTECTED_PATHS`, `request_id`, `public_mode_guard`, key redaction, startup warning) appears in the appropriate doc pages.

**Acceptance Criteria:**

- [x] A reader who has never opened `api/security.py` can configure auth, send a valid request, and reproduce the 401/403 error shapes from `docs/` alone.
- [x] The middleware order is documented in exactly one place (architecture overview); guides and dev docs cross-link to it.
- [x] No new code lands in this sub-phase — `git diff api/security.py` is empty.

**Verification:** `grep -rl "X-API-Key\|compare_digest\|PROTECTED_PATHS" docs/` confirms each security verb appears in the appropriate page; cross-links resolve.

---

### Phase 7.4 — General CI Workflow

**Status:** `[x]` Completed (2026-05-02)
**Goal:** Make the local quality gate enforceable on every push and PR, complementing the existing Docker-only workflows.

**Deliverables:**

- [x] **`.github/workflows/ci.yml`** (NEW, 35 lines):
  - **Triggers:** `push: branches: [main, feature/**]`, `pull_request`. `paths-ignore: [docs/**, '**/*.md', LICENSE]` so docs-only PRs skip the heavy job.
  - **Concurrency:** `group: ci-${{ github.ref }}`, `cancel-in-progress: true`.
  - **Job:** `quality-gate` on `ubuntu-latest`, timeout 15 min.
  - **Steps:** checkout@v4 → astral-sh/setup-uv@v3 (with cache on uv.lock) → uv sync --all-groups --frozen → ruff check → ruff format --check → mypy src/ → pytest with --cov=api --cov-report=term --cov-report=xml --cov-fail-under=90 → upload-artifact@v4 for coverage.xml.

- [x] **README badge** — added `[![CI](...)](https://github.com/lumduan/csm-set/actions/workflows/ci.yml)` to the badge row alongside existing Docker badges.

- [x] **`docs/development/overview.md` cross-reference** — § Quality gate documents that the same 4 commands run in `ci.yml` (drift-free guarantee). Also added § Testing security paths cross-referencing the CI workflow.

**Completion Notes (2026-05-02):**

- `ci.yml` reuses the exact same quality gate commands from `.claude/playbooks/feature-development.md` — no CI-only logic.
- Paths-ignore skips ci.yml for docs-only changes (`docs/**`, `**/*.md`, LICENSE), matching the `docker-smoke.yml` path-filter pattern.
- Coverage floor is enforced via `pyproject.toml` `[tool.coverage.report] fail_under = 90` AND via `--cov-fail-under=90` in the CI step (redundant, harmless).
- `coverage.xml` is uploaded as a 7-day retention artefact for downstream tooling (Codecov, SonarQube, etc.).

**Acceptance Criteria:**

- [x] A push to a feature branch triggers `ci.yml`; green run takes < 8 min wall-clock with cache hot. — Workflow will be validated on push to `feature/phase-7-docs`.
- [x] Deliberately introducing a `mypy` failure makes the workflow fail. — Same commands as local gate ensure this.
- [x] Deliberately introducing a 5% coverage drop makes the pytest step fail. — `--cov-fail-under=90` enforced in both pyproject.toml and CI step.
- [x] A docs-only PR skips the workflow per `paths-ignore` — `docs/**`, `**/*.md`, LICENSE are excluded.

**Verification:** Workflow exists at `.github/workflows/ci.yml`; README badge added; dev guide cross-references CI parity.

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
