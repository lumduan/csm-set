# Phase 6.6 — GitHub Actions CI Smoke Workflow

**Feature:** GitHub Actions CI Smoke — PR-gated Docker boot + endpoint verification
**Branch:** `feature/phase-6-docker`
**Created:** 2026-05-02
**Status:** Complete
**Completed:** 2026-05-02
**Depends On:** Phase 6.1 (Dockerfile — complete), Phase 6.2 (Docker Compose — complete), Phase 6.5 (README Rewrite — complete)
**Positioning:** The CI safety net that makes "the public release works" a per-PR invariant. Without this workflow, any PR can silently break the Docker build or API bootstrap, and public users would only discover it after merge.

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Risks and Mitigations](#risks-and-mitigations)
9. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 6.6 creates `.github/workflows/docker-smoke.yml` — a GitHub Actions workflow that boots the full Docker Compose stack, verifies the API starts and serves correct responses, and gates PRs against regressions. The workflow runs on every PR targeting `main` and on every push to `main`.

### Parent Plan Reference

- `docs/plans/phase_6_docker/PLAN.md`

### Key Deliverables

1. `.github/workflows/docker-smoke.yml` — build + compose up + curl-based smoketest
2. `README.md` — badge update (placeholder → live badge)
3. `docs/plans/phase_6_docker/PLAN.md` — Phase 6.6 completion notes
4. `docs/plans/phase_6_docker/phase_6_6_github_actions_ci_smoke.md` — this document

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Implement Phase 6.6 — GitHub Actions CI Smoke Workflow for the csm-set project. Follow these steps precisely:

1. **Preparation**
   - Carefully read `.claude/knowledge/project-skill.md` and `.claude/playbooks/feature-development.md` to internalize all engineering standards and workflow expectations.
   - Review `docs/plans/phase_6_docker/PLAN.md`, focusing on the Phase 6.6 section, and `docs/plans/phase_6_docker/phase_6_5_readme_rewrite.md` for context on previous deliverables.

2. **Planning**
   - Draft a detailed implementation plan for Phase 6.6 in markdown, using the format from `docs/plans/examples/phase1-sample.md`.
   - Your plan must include: scope, deliverables, acceptance criteria, risks, and the full AI agent prompt (this prompt).
   - Save the plan as `docs/plans/phase_6_docker/phase_6_6_github_actions_ci_smoke.md`.

3. **Implementation**
   - Only begin coding after the plan is complete and saved.
   - Implement all deliverables for Phase 6.6:
     - Create a GitHub Actions workflow (e.g., `.github/workflows/docker-smoke.yml`) that:
       - Builds the Docker image for the project.
       - Runs a container and verifies that the API starts successfully (e.g., waits for port 8000, checks a health endpoint or root URL).
       - Optionally, runs a minimal test (e.g., curl http://localhost:8000 and checks for a 200 response).
     - Ensure the workflow is efficient and does not run unnecessary steps.
     - Add a status badge for the workflow to the top of `README.md`, replacing the placeholder from Phase 6.5.
     - Document the workflow in the plan file and update the README as needed.

4. **Documentation and Progress Tracking**
   - Update `docs/plans/phase_6_docker/PLAN.md` and `docs/plans/phase_6_docker/phase_6_6_github_actions_ci_smoke.md` with progress notes, completion status, and any issues encountered.
   - Mark acceptance criteria as completed or note any deviations.

5. **Commit and Finalization**
   - Commit all changes in a single commit with a clear, standards-compliant message summarizing the work.
   - Ensure all tests pass and the implementation meets the acceptance criteria.
```

---

## Scope

### In Scope (Phase 6.6)

| Component | Description | Status |
|---|---|---|
| `.github/workflows/docker-smoke.yml` | PR + main: compose up + curl + assertions | Complete |
| README CI badge | Replace placeholder with live badge | Complete |
| PLAN.md update | Phase 6.6 completion notes | Complete |
| Phase plan document | This document | Complete |

### Out of Scope (Phase 6.6)

- Full integration test suite (those exist in `tests/` and are run locally)
- GHCR publishing (Phase 6.7)
- Multi-arch builds (Phase 7)
- Vulnerability scanning / trivy gating (Phase 7)
- SBOM generation (Phase 7)
- Image signing (Phase 7)

---

## Design Decisions

### 1. `docker compose up --wait` relies on existing HEALTHCHECK

The Dockerfile already has `HEALTHCHECK` and `docker-compose.yml` has a `healthcheck` stanza. Using `--wait` means compose polls the container's health status and only returns when healthy — no need for a manual sleep loop in the workflow. This keeps the workflow declarative and DRY.

### 2. Path filters on PR trigger

The PR trigger includes `paths:` to avoid running the full Docker build on PRs that only touch docs or non-code files. This conserves GHA minutes and keeps CI feedback fast.

### 3. `--retry-all-errors` on curl retry loop

Health endpoint curl uses `--retry-all-errors` (curl ≥ 7.71) so transient connection-refused errors during container startup are retried, not just HTTP 5xx. The `start_period: 20s` on the healthcheck already handles startup delay; the retry loop is a second safety net.

### 4. Write-endpoint 403 assertion included

The workflow curls `POST /api/v1/data/refresh` and asserts a 403 response. This confirms the public-mode guard middleware is active and write endpoints are correctly blocked — a critical data-boundary invariant.

### 5. Failure logs artefact

On any failure, `docker compose logs csm` is captured and uploaded as an artefact. This gives PR authors immediate access to container logs without needing to reproduce the failure locally.

### 6. `docker compose down -v` in `if: always()`

Cleanup runs unconditionally — even if prior steps fail — to prevent orphaned containers from consuming GHA runner disk across workflow re-runs.

---

## Implementation Steps

### Step 1: Create `.github/workflows/docker-smoke.yml`

Created the workflow YAML with:
- Concurrency group + cancel-in-progress
- Path-filtered PR trigger + push-to-main trigger
- Single `smoke` job with 15-minute timeout
- Buildx setup with GHA cache backend
- `docker compose up -d --wait`
- Curl health retry loop
- Read-endpoint smoke assertions (4 endpoints)
- Write-endpoint 403 assertion
- Failure logs artefact upload
- Cleanup step with `if: always()`

### Step 2: Update README.md badge

Replaced the placeholder `coming in 6.6` badge with a live GitHub Actions badge URL pointing to `docker-smoke.yml`.

### Step 3: Update Phase 6 sub-progress

Updated the Phase 6 sub-progress line in README.md from "CI smoke workflow (6.6 — pending)" to "CI smoke workflow (6.6 ✓)".

### Step 4: Update PLAN.md

Marked Phase 6.6 status `[x]` Complete in the master plan, added completion notes with file paths and acceptance criteria status.

### Step 5: Quality gate

Ran `uv run ruff check .`, `uv run ruff format .`, and `uv run pytest tests/ -v` — all green.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `.github/workflows/docker-smoke.yml` | CREATE | PR-gated docker compose smoke test workflow |
| `README.md` | MODIFY | CI smoke badge (placeholder → live) + sub-progress text |
| `docs/plans/phase_6_docker/PLAN.md` | MODIFY | Phase 6.6 status + completion notes |
| `docs/plans/phase_6_docker/phase_6_6_github_actions_ci_smoke.md` | CREATE | This phase plan document |

---

## Success Criteria

- [x] `.github/workflows/docker-smoke.yml` created with all specified steps and triggers
- [x] Workflow uses concurrency group with cancel-in-progress
- [x] Workflow includes path filters on PR trigger
- [x] Smoke assertions cover: /health, /api/v1/signals/latest, /api/v1/portfolio/current, /api/v1/notebooks, /static/notebooks/01_data_exploration.html (200), and POST /api/v1/data/refresh (403)
- [x] Failure logs artefact upload configured
- [x] Cleanup step with `if: always()` ensures teardown
- [x] README badge updated to live GitHub Actions badge URL
- [x] Phase 6 sub-progress text updated
- [x] PLAN.md Phase 6.6 marked `[x]` Complete with completion notes
- [x] Quality gate green: ruff check, ruff format, pytest
- [ ] Workflow passes on actual GitHub Actions runner — *pending push to remote*
- [ ] Wall-clock time on a green run < 5 min — *pending GitHub Actions runner*
- [ ] Workflow file passes `actionlint` — *actionlint not installed locally; verified via manual YAML review*

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Docker build OOM on GHA runner | Low | Medium | `mem_limit: 2g` already in compose; runner has 7 GB RAM |
| nbconvert execution blocks startup | Low | Low | Not triggered in public mode; healthcheck handles long startup |
| GHCR rate limit on `ghcr.io/astral-sh/uv:latest` | Low | Medium | GHA runners share Docker Hub / GHCR with authenticated pulls |
| Port 8000 already bound on runner | Very Low | High | Workflow runs on fresh VM; no other services on 8000 |
| Health check never becomes healthy | Low | High | `--wait` has 2× compose timeout; 15-min workflow timeout catches hangs |

---

## Completion Notes

### Summary

Phase 6.6 complete. Created a GitHub Actions smoke workflow that builds the Docker image via `docker compose up --wait`, verifies the health endpoint and 4 read endpoints return 200, asserts write endpoints return 403, uploads container logs on failure, and tears down unconditionally. The README badge was updated from a placeholder to the live GitHub Actions badge URL.

The workflow is designed end-to-end per the master plan: concurrency group cancels stale runs; path filters avoid unnecessary builds; the healthcheck `--wait` pattern avoids manual sleep loops; write-endpoint assertion verifies public-mode guard; and failure logs artefact provides immediate debugging context.

### Issues Encountered

- **actionlint not available locally:** Verified YAML correctness manually against GitHub Actions schema conventions and existing workflows in the ecosystem. actionlint will be available on CI or can be installed via `brew install actionlint` for local validation.

### Deviations from Master Plan

- **Path filters added to PR trigger:** The master plan specified `pull_request` without path filters. Added `paths:` to avoid building Docker on docs-only PRs — this is a defensive optimization with no functional impact.
- **Portfolio endpoint included:** The master plan listed `/api/v1/backtest/summary` which does not exist in the current API. Replaced with `/api/v1/portfolio/current` which is an actual read endpoint serving portfolio state.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-05-02
