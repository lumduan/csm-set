# <type>(<scope>): <short imperative title>

> Conventional commit types: feat, fix, refactor, perf, test, docs, chore, build, ci.

## Summary
<2-3 sentence overview. What changed and why. User impact in one line.>

## 🎯 Changes
- `src/csm/<module>.py` — <one-line description>
- `tests/<path>.py` — <added regression / coverage for X>
- `docs/...` — <updated section X>

## 🛠️ Technical Implementation
<For non-trivial changes: how the change is implemented, key design decisions, trade-offs.
Skip if the diff is self-explanatory.>

## ✅ Test Plan
- [ ] `uv run pytest tests/<path> -v` — new tests pass.
- [ ] `uv run pytest tests/ -v` — full suite passes.
- [ ] `uv run mypy src/` — clean.
- [ ] `uv run ruff check . && uv run ruff format --check .` — clean.
- [ ] Manual verification: <curl, browser click-through, example script run>.
- [ ] Coverage: `uv run pytest --cov=src/csm --cov-report=term-missing` — no regression below 90 %.

## 🚦 Risk & Rollback
- **Risk level**: low / medium / high.
- **Blast radius**: <which modules / users / endpoints can be affected if this is wrong>.
- **Rollback**: revert this PR (`git revert <sha>`) or … <document any non-trivial rollback step>.

## 📝 Docs / Changelog
- [ ] CHANGELOG entry added (if user-visible).
- [ ] Public docstrings updated.
- [ ] Example added or updated (if user-facing API).

## 📸 Screenshots / Logs (UI / API only)
<Paste curl + response, or NiceGUI screenshot, or before/after images.>

## Related
- Closes #<issue>
- Plan: `docs/plans/<file>.md`
- Memory: `.claude/memory/recurring-bugs.md` (if a regression class)

---
🤖 Co-authored-by: Claude
