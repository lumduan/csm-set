# Playbook — Release Checklist

Owned by [agents/release-manager.md](../agents/release-manager.md). Every step gated; no skipping.

## 1. Pre-flight

- [ ] Working tree clean: `git status` shows nothing.
- [ ] On the correct branch (release branch or `main`, per project policy).
- [ ] `uv sync` is clean — no drift in `uv.lock`.

## 2. Quality Gate (must be 100% green)

- [ ] `uv run pytest tests/ -v`
- [ ] `uv run pytest --cov=src/csm --cov-report=term-missing` — coverage ≥ 90 %.
- [ ] `uv run mypy src/` — clean.
- [ ] `uv run ruff check .` — clean.
- [ ] `uv run ruff format --check .` — clean.

## 3. Version Bump

- [ ] Edit `pyproject.toml` `[project] version` per SemVer:
  - **MAJOR** for breaking changes.
  - **MINOR** for backward-compatible features.
  - **PATCH** for backward-compatible fixes only.
- [ ] Run `uv lock` to refresh lockfile metadata.

## 4. CHANGELOG

- [ ] Add a new section `## [X.Y.Z] — YYYY-MM-DD`.
- [ ] Subsections: `Added`, `Changed`, `Fixed`, `Removed`, `Security` (omit empty ones).
- [ ] Entries describe **user-visible** impact, not internal churn.
- [ ] Reference any breaking change with a "Migration" note.

## 5. Commit & Tag

- [ ] Commit version bump + CHANGELOG together: `chore(release): vX.Y.Z`.
- [ ] Tag locally: `git tag vX.Y.Z`.
- [ ] **Pause for explicit user approval before pushing the tag.**
- [ ] Push: `git push && git push --tags`.

## 6. Publish

- [ ] Run `./scripts/publish.sh`.
- [ ] Confirm artifact appears on the registry.

## 7. Smoke Test (clean venv)

```bash
uv venv /tmp/csm-verify
/tmp/csm-verify/bin/pip install csm-set==X.Y.Z
/tmp/csm-verify/bin/python -c "import csm; print(csm.__version__)"
```

- [ ] Output matches `X.Y.Z`.
- [ ] A trivial public function imports and runs.

## 8. Announce

- [ ] Post release notes (CHANGELOG section) wherever the team consumes them.
- [ ] Close any milestone / project tracking the release.

## 9. Rollback Plan (in case of regressions)

- [ ] Yank affected version from registry if critical.
- [ ] Open a hotfix branch from the previous tag.
- [ ] Cut a `X.Y.Z+1` patch following this checklist.
