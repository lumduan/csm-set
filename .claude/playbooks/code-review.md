# Playbook — Code Review

For reviewing PRs / diffs. Read tests first; they document intent.

## 1. Skim Scope

- One logical change? If a PR mixes refactor + feature, ask for a split.
- Does the diff stay within the layer it claims to touch (`src/csm/` vs `api/` vs `ui/`)?

## 2. Read Tests First

- Do the tests describe the **behavior** the feature claims?
- Are edge cases covered: empty input, NaN input, tz-naive input, error paths?
- Is there a regression test for any bug fixed?
- No mocked pandas; no real network in unit tests.

## 3. Read Code

- Standards check against [knowledge/coding-standards.md](../knowledge/coding-standards.md):
  - Full type annotations
  - Pydantic at boundaries
  - Logging not `print`
  - Module-specific exceptions, not bare `Exception`
  - File size budget respected
- Cross-cutting suspects (auto-flag):
  - `requests` in async path → block.
  - Row-wise pandas `apply` / `iterrows` on large frames → flag.
  - Hard-coded paths or secrets → block.
  - Bare `except:` → block.
  - tz-naive Timestamps at module boundary → block.

## 4. Security Pass (run mental [agents/security-reviewer.md](../agents/security-reviewer.md))

- New external surface (FastAPI route, CLI, file I/O on user-controlled input)?
- Missing auth dependency on a non-public route?
- Input validation present?
- Errors leaking internals to clients?

## 5. Performance Pass (run mental [agents/performance-optimizer.md](../agents/performance-optimizer.md))

- New pandas pipeline — vectorized?
- New external call — batched, timed out, retried?
- Parquet read — columns pruned, partition filtered?

## 6. Docs

- Public functions have docstrings (Google style).
- CHANGELOG updated if user-visible.
- `docs/` updated if architectural.
- Examples updated or added if new user-facing API.

## 7. Decide

- **Approve** if all blocks resolved.
- **Request changes** with concrete `file:line` references and a fix per finding.
- **Comment** for non-blocking suggestions, clearly labeled "non-blocking".

## 8. Don't

- Don't approve without reading tests.
- Don't approve a refactor that mixes in a feature.
- Don't nitpick formatting — ruff handles that.
- Don't ask for stylistic preferences as blocking changes.
