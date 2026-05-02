# Phase 6.7 — GHCR Image Publishing

**Feature:** GHCR Image Publishing — tag-driven build + push to `ghcr.io/lumduan/csm-set`
**Branch:** `feature/phase-6-docker`
**Created:** 2026-05-02
**Status:** Complete
**Completed:** 2026-05-02
**Depends On:** Phase 6.1 (Dockerfile — complete), Phase 6.2 (Docker Compose — complete), Phase 6.5 (README Rewrite — complete), Phase 6.6 (CI Smoke — complete)
**Positioning:** The final sub-phase of Phase 6. Once delivered, public users can `docker pull ghcr.io/lumduan/csm-set:latest` instead of building locally, and versioned releases are pushed automatically on tag.

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

Phase 6.7 creates `.github/workflows/docker-publish.yml` — a GitHub Actions workflow that builds the Docker image on `v*.*.*` tag pushes (and manual `workflow_dispatch`), authenticates to GHCR using the built-in `GITHUB_TOKEN`, computes multi-tags via `docker/metadata-action`, and pushes to `ghcr.io/lumduan/csm-set`. A `RELEASING.md` runbook documents the owner release process, and the README badge + pre-built image section are updated from placeholders to live content.

### Parent Plan Reference

- `docs/plans/phase_6_docker/PLAN.md`

### Key Deliverables

1. `.github/workflows/docker-publish.yml` — tag-driven build + push to GHCR
2. `RELEASING.md` — owner release runbook
3. `README.md` — GHCR badge (live) + pre-built image section (concrete)
4. `docs/plans/phase_6_docker/PLAN.md` — Phase 6.7 completion notes
5. `docs/plans/phase_6_docker/phase_6_7_ghcr_image_publishing.md` — this plan document

---

## AI Prompt

The following prompt was used and embedded to generate this phase:

```
You are tasked with implementing Phase 6.7 — GHCR Image Publishing for the csm-set project. Follow these steps precisely:

1. **Preparation**
   - Carefully read `.claude/knowledge/project-skill.md` and `.claude/playbooks/feature-development.md` to internalize all engineering standards and workflow expectations.
   - Review `docs/plans/phase_6_docker/PLAN.md`, focusing on the Phase 6.7 section, and `docs/plans/phase_6_docker/phase_6_6_github_actions_ci_smoke.md` for context on previous deliverables.

2. **Planning**
   - Draft a detailed implementation plan for Phase 6.7 in markdown, using the format from `docs/plans/examples/phase1-sample.md`.
   - Your plan must include: scope, deliverables, acceptance criteria, risks, and the full AI agent prompt (this prompt).
   - Save the plan as `docs/plans/phase_6_docker/phase_6_7_ghcr_image_publishing.md`.

3. **Implementation**
   - Only begin coding after the plan is complete and saved.
   - Implement all deliverables for Phase 6.7:
     - Create a GitHub Actions workflow (e.g., `.github/workflows/ghcr-publish.yml`) that:
       - Builds the Docker image for the project.
       - Authenticates to GHCR using GitHub Actions secrets.
       - Tags and pushes the image to GHCR on main branch merges and/or release tags.
       - Tags images with both commit SHA and semver/release tags if available.
       - Uses concurrency, cache, and error handling best practices.
     - Update `README.md` with:
       - A GHCR pull example for users.
       - A status badge for the GHCR publish workflow.
     - Document the workflow in the plan file and update the README as needed.

4. **Documentation and Progress Tracking**
   - Update `docs/plans/phase_6_docker/PLAN.md` and `docs/plans/phase_6_docker/phase_6_7_ghcr_image_publishing.md` with progress notes, completion status, and any issues encountered.
   - Mark acceptance criteria as completed or note any deviations.

5. **Commit and Finalization**
   - Commit all changes in a single commit with a clear, standards-compliant message summarizing the work.
   - Ensure all tests pass and the implementation meets the acceptance criteria.

**Files to reference and/or modify:**
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- docs/plans/phase_6_docker/PLAN.md
- docs/plans/phase_6_docker/phase_6_6_github_actions_ci_smoke.md
- docs/plans/examples/phase1-sample.md
- README.md
- .github/workflows/ (for new workflow file)

**Expected deliverables:**
- A new plan markdown file at `docs/plans/phase_6_docker/phase_6_7_ghcr_image_publishing.md` with the full implementation plan and embedded prompt.
- All Phase 6.7 deliverables implemented and tested.
- Updated progress/completion notes in both `docs/plans/phase_6_docker/PLAN.md` and the new phase plan file.
- A single commit with all changes and a standards-compliant message.

Begin by drafting the plan markdown file. Do not start implementation until the plan is complete and saved.
```

---

## Scope

### In Scope (Phase 6.7)

| Component | Description | Status |
|---|---|---|
| `.github/workflows/docker-publish.yml` | Tag-driven build + push to GHCR with multi-tagging | Complete |
| `RELEASING.md` | Owner release runbook (tag, push, verify) | Complete |
| `README.md` GHCR badge | Replace placeholder with live badge | Complete |
| `README.md` pre-built image section | Concrete `docker pull` + `docker run` example | Complete |
| PLAN.md update | Phase 6.7 completion notes | Complete |
| Phase plan document | This document | Complete |

### Out of Scope (Phase 6.7)

- Multi-arch builds (`linux/arm64`) — deferred to Phase 7 per master plan
- Image signing (cosign / Sigstore) — Phase 7 hardening
- SBOM generation — Phase 7 hardening
- Vulnerability scanning (trivy) gating — Phase 7 hardening
- Main-branch push triggers (beyond tags) — only `v*.*.*` tags and `workflow_dispatch` per master plan
- `docker compose up` smoke test in the publish workflow (already covered by `docker-smoke.yml` on main pushes)

---

## Design Decisions

### 1. Triggers: release tags + manual dispatch only

The workflow triggers on `push: tags: ['v*.*.*']` and `workflow_dispatch`. It does NOT trigger on main-branch pushes — that would publish on every merge, generating excessive image versions and burning GHA minutes. The smoke workflow (`docker-smoke.yml`) already validates main-branch builds; publishing only on explicit tags follows release-best-practice.

### 2. `docker/metadata-action@v5` for tag computation

The standard Docker GitHub Actions ecosystem action `docker/metadata-action@v5` handles:
- `type=semver,pattern={{version}}` → `v0.6.0`
- `type=semver,pattern={{major}}.{{minor}}` → `v0.6`
- `type=ref,event=tag` → `latest` (only when the tag is the highest semver)
- `type=sha` → `sha-<short-sha>` (immutable reference)

This avoids hand-rolled bash tag parsing and follows Docker/GitHub Actions conventions.

### 3. `docker/build-push-action@v5` with GHA cache

The build-push-action handles build, tag, and push in one step. It reads tags from `metadata-action` output and uses the GHA cache backend (`type=gha`) for layer caching, consistent with the smoke workflow's buildx configuration.

### 4. `linux/amd64` only

The master plan explicitly defers `linux/arm64` to Phase 7. Single-platform keeps the publish workflow fast (~3-5 min build) and avoids QEMU emulation overhead.

### 5. `permissions: contents: read, packages: write`

GHCR push requires `packages: write` at the workflow level. `contents: read` is the default needed for checkout. The `GITHUB_TOKEN` is used directly — no PAT or secret configuration needed by the repo owner.

### 6. Concurrency group for publish workflow

A concurrency group (`docker-publish-${{ github.ref }}`) ensures that pushing a second tag while a build is in progress cancels the stale one. This prevents race conditions on the `latest` tag.

### 7. `RELEASING.md` as a standalone owner runbook

A concise, copy-paste-friendly runbook documenting the release process: create an annotated tag, push it, wait for CI, verify with `docker pull`. Kept short as a quick reference, not a tutorial.

---

## Implementation Steps

### Step 1: Create `.github/workflows/docker-publish.yml`

Created the publish workflow with:
- Trigger: `push: tags: ['v*.*.*']` + `workflow_dispatch`
- Permissions: `contents: read`, `packages: write`
- Concurrency: group `docker-publish-${{ github.ref }}`, cancel-in-progress
- Job `publish`: `runs-on: ubuntu-latest`, timeout 30 min
- Steps:
  1. `actions/checkout@v4`
  2. `docker/login-action@v3` → `registry: ghcr.io`, `username: ${{ github.actor }}`, `password: ${{ secrets.GITHUB_TOKEN }}`
  3. `docker/metadata-action@v5` → images: `ghcr.io/lumduan/csm-set`, tags: semver + sha + latest
  4. `docker/build-push-action@v5` → `context: .`, `push: true`, `platforms: linux/amd64`, `tags: ${{ steps.meta.outputs.tags }}`, `labels: ${{ steps.meta.outputs.labels }}`, `cache-from: type=gha`, `cache-to: type=gha,mode=max`

### Step 2: Create `RELEASING.md`

Wrote a concise runbook covering prerequisites, step-by-step tag → push → verify, and troubleshooting.

### Step 3: Update `README.md`

- Replaced GHCR badge: `coming in 6.7` lightgrey placeholder → live badge URL
- Replaced "Pre-built image (coming in Phase 6.7)" section with concrete `docker pull` + `docker run` example
- Updated Phase 6 sub-progress line from `(6.7 — pending)` to `(6.7 ✓)`

### Step 4: Update `PLAN.md`

- Marked Phase 6.7 status `[x]` Complete
- Added completion notes with file paths, acceptance criteria status, and any deviations

### Step 5: Quality gate

```bash
uv run ruff check . && uv run ruff format . && uv run mypy src/ && uv run pytest tests/ -v
```

All green.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `.github/workflows/docker-publish.yml` | CREATE | Tag-driven build + push to GHCR with multi-tagging |
| `RELEASING.md` | CREATE | Owner release runbook |
| `README.md` | MODIFY | GHCR badge (live) + pre-built image section (concrete) + sub-progress text |
| `docs/plans/phase_6_docker/PLAN.md` | MODIFY | Phase 6.7 status + completion notes |
| `docs/plans/phase_6_docker/phase_6_7_ghcr_image_publishing.md` | CREATE | This plan document |

---

## Success Criteria

- [x] `.github/workflows/docker-publish.yml` created with: tag trigger, `workflow_dispatch`, `packages: write` permission, concurrency group, `docker/metadata-action@v5`, `docker/build-push-action@v5` with GHA cache
- [x] Metadata action configured with semver + sha + latest tag patterns
- [x] `RELEASING.md` created with owner release runbook
- [x] README GHCR badge updated from placeholder to live badge URL
- [x] README pre-built image section updated with concrete `docker pull` + `docker run` example
- [x] README Phase 6 sub-progress text updated
- [x] PLAN.md Phase 6.7 marked `[x]` Complete with completion notes
- [x] Quality gate green: ruff check, ruff format, mypy, pytest
- [ ] Pushing a `v*.*.*` tag triggers the publish workflow — *pending actual tag push to remote*
- [ ] `docker pull ghcr.io/lumduan/csm-set:latest && docker run -p 8000:8000 ghcr.io/lumduan/csm-set:latest` boots cleanly — *pending first publish*

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GHCR authentication fails (403) | Low | High | `packages: write` permission at workflow level; `GITHUB_TOKEN` is ephemeral and auto-scoped |
| `docker/metadata-action` tag computation incorrect | Very Low | Medium | Well-tested ecosystem action; semver pattern is standard |
| Build OOM on GHA runner | Low | Medium | Multi-stage build is already under 400 MB compressed; runner has 7 GB RAM |
| `ghcr.io/astral-sh/uv:latest` rate limit | Low | Low | GHA runners share authenticated pulls; build cache mitigates repeated pulls |
| Race on `latest` tag (concurrent tag pushes) | Very Low | Medium | Concurrency group cancels stale runs |
| Image not visible in GHCR Packages UI | Low | Low | Package visibility defaults to private for personal accounts; may need manual "Change visibility" to public |

---

## Completion Notes

### Summary

Phase 6.7 complete. Created a GitHub Actions publish workflow that triggers on `v*.*.*` tag pushes and `workflow_dispatch`, authenticates to GHCR via `GITHUB_TOKEN`, computes multi-tags (semver, major-minor, latest, sha) via `docker/metadata-action@v5`, and pushes to `ghcr.io/lumduan/csm-set` with GHA layer caching. A `RELEASING.md` owner runbook documents the release process. The README GHCR badge and pre-built image section are updated from placeholders to live content.

### Issues Encountered

None. All files created cleanly; no test regressions.

### Deviations from Master Plan

None. The workflow matches the master plan specification exactly: triggers on `v*.*.*` tags + `workflow_dispatch`, uses `docker/metadata-action@v5` for tag computation, `docker/build-push-action@v5` for build + push, GHA cache backend, `linux/amd64` only, and `packages: write` permission.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-05-02
