# Playbook — Feature Development

Repeatable workflow for adding a feature to csm-set. Bias toward minimal, well-tested, well-documented changes.

## 1. Read

- Read related modules under `src/csm/` and the corresponding tests under `tests/`.
- Read [knowledge/architecture.md](../knowledge/architecture.md) to confirm the layer where the feature belongs.
- Search existing helpers — don't reinvent (`grep -r "<keyword>" src/csm/`).

## 2. Design (small)

- Sketch the smallest change that delivers the feature.
- Prefer one new public function, one module touched.
- If the design crosses module boundaries, write a 5-line note in `docs/plans/` first.

## 3. Test First

- Add a failing test in `tests/...` mirroring the source path.
- Test the **behavior**, not the implementation.
- Use real small DataFrames; `httpx.MockTransport` for HTTP; freeze clocks if time-sensitive.

## 4. Implement

- Write the smallest code that makes the test pass.
- Full type annotations; Pydantic for boundary I/O.
- Async at I/O boundaries; sync inside compute.
- File size budget ≤ 400 lines — split if exceeded.

## 5. Quality Gate

```bash
uv run ruff check . && uv run ruff format . && uv run mypy src/ && uv run pytest tests/ -v
```

All four must pass before commit.

## 6. Document

- Docstring on every new public function (Google style — see [knowledge/coding-standards.md](../knowledge/coding-standards.md)).
- Update or add an example in `examples/` if user-visible.
- If the feature changes API behavior, update `docs/` and the API's OpenAPI summaries.

## 7. Commit

- Follow [agents/git-commit-reviewer.md](../agents/git-commit-reviewer.md) standards (conventional commits with emoji section headers).
- One feature per commit; don't bundle unrelated cleanup.
- If you noticed cleanup along the way, do it in a separate refactor commit per [agents/refactor-specialist.md](../agents/refactor-specialist.md).

## 8. Verify in Place

- For API changes: hit the endpoint with curl or HTTPie and confirm the OpenAPI schema is correct.
- For UI changes: run NiceGUI locally and click through the affected views.
- For backtest / signal changes: run a small example end-to-end.
