# Issue Templates

Two flavors. Pick one and delete the other.

---

## 🐛 Bug

### Title
`bug(<scope>): <short imperative description>`

### Reproduction
Smallest steps to reproduce. Prefer a code snippet or shell command runnable on a fresh checkout.

```bash
uv sync
uv run python -c "<minimal repro>"
```

### Expected
<What should have happened.>

### Actual
<What actually happened. Include the full traceback if any.>

### Environment
- csm-set version / git SHA: `git rev-parse HEAD`
- Python: `uv run python --version`
- OS: <macOS 25.4 / Ubuntu 22.04 / …>
- Key deps: `uv tree | grep -E "pandas|pydantic|fastapi|httpx|settfex"`

### Logs / Artifacts
```
<paste relevant log lines, redact any secret>
```

### Related
- Memory: any recurring bug class? Link to `.claude/memory/recurring-bugs.md` section if so.
- Recent commits: `git log -p -S<symbol> -- src/csm/<file>.py`.

---

## ✨ Feature

### Title
`feat(<scope>): <short imperative description>`

### Problem
<What user-visible problem are we solving? Who feels it?>

### Proposal
<What should the user be able to do? Describe the behavior, not the implementation.
Include shape of inputs and outputs if it's a new API.>

### Alternatives Considered
- <Option A — why not chosen>
- <Option B — why not chosen>

### Acceptance Criteria
- [ ] <Observable behavior 1>
- [ ] <Observable behavior 2>
- [ ] Tests cover happy path + edge cases (empty, NaN, tz boundary).
- [ ] Public API has docstring + example.
- [ ] CHANGELOG entry.

### Out of Scope
- <Explicit non-goals.>

### Stakeholders
- Requested by: <name / role>
- Affected modules: <`src/csm/...`, `api/...`, `ui/...`>
