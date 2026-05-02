# Development Guide

This page covers the complete development workflow for csm-set: environment setup, the quality gate, commit conventions, code style, test layout, and local dev tips.

## Workflow

Follow this sequence for every change:

1. **Read** — understand the relevant modules under `src/csm/` and the corresponding tests under `tests/`. Check `docs/architecture/overview.md` if you're unsure which layer your change belongs in. Search for existing helpers — don't reinvent.
2. **Branch** — create a feature branch: `git checkout -b feature/your-feature-name`.
3. **Test-first** — add a failing test in `tests/` mirroring the source path. Test the behaviour, not the implementation. Use real small DataFrames and `httpx.MockTransport` for HTTP.
4. **Implement** — write the smallest code that makes the test pass. Full type annotations. Pydantic for boundary I/O. Async at I/O boundaries.
5. **Quality gate** — run all four checks (see below). All must pass before committing.
6. **Commit** — conventional commit format (see below). One feature per commit.
7. **PR** — push your branch and open a pull request. CI will run the same quality gate.

---

## Quality gate

Run before every commit. These four commands are the single source of truth for "is this code good enough to merge":

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest tests/ -v
```

### What each command checks

| Command | Purpose |
|---------|---------|
| `ruff check .` | Lint: catches unused imports, undefined names, style violations (E, F, I, UP, B, SIM rules) |
| `ruff format --check .` | Format: verifies code is consistently formatted (100-char line length). No auto-fix in CI — run `uv run ruff format .` locally to fix. |
| `mypy src/` | Type-check: strict mode, catches type errors across the entire `src/` tree |
| `pytest tests/ -v` | Test: runs all 827 tests. With `--cov=api --cov-fail-under=90`, enforces the coverage floor on the API layer |

These exact same commands run in `.github/workflows/ci.yml` on every push and PR. If it passes locally, it passes in CI. No CI-only logic.

---

## Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/) with scopes:

```
type(scope): summary

- Bullet details if needed
```

| Type | When to use |
|------|-------------|
| `feat(scope)` | New feature or capability |
| `fix(scope)` | Bug fix |
| `docs(scope)` | Documentation changes |
| `test(scope)` | Test-only changes |
| `ci(scope)` | CI/CD changes |
| `refactor(scope)` | Code restructuring without behaviour change |
| `chore(scope)` | Tooling, dependency bumps |

Common scopes: `data`, `features`, `portfolio`, `research`, `risk`, `execution`, `api`, `ui`, `docker`, `docs`, `ci`, `config`.

Example:
```
docs(readme): add TOC, module index, troubleshooting

- Top-of-file Table of Contents
- Module index mapping src/csm/* to purpose
- Troubleshooting section with 6 common failure modes
```

---

## Code style summary

- **Pydantic at boundaries** — function I/O between modules (especially across `src/csm/`, `api/`, `ui/`) goes through Pydantic models, never raw dicts.
- **Async I/O** — all HTTP via `httpx.AsyncClient`. `requests` is forbidden in `src/csm/`.
- **File size** — target ≤ 400 lines per Python file. Split if exceeded.
- **Docstrings** — Google-style on every public function: `Args`, `Returns`, `Raises`, `Example`.
- **No `print` in `src/csm/`** — use `logging.getLogger(__name__)`.
- **Full type annotations** — all public functions must have complete type annotations.
- **No secrets in repo** — all config via env + `pydantic-settings`.

See `.claude/knowledge/project-skill.md` for the full rules.

---

## Test layout

Tests mirror the source layout:

```
tests/
├── unit/
│   ├── data/          → tests for src/csm/data/
│   ├── features/      → tests for src/csm/features/
│   ├── portfolio/     → tests for src/csm/portfolio/
│   ├── research/      → tests for src/csm/research/
│   ├── risk/          → tests for src/csm/risk/
│   ├── execution/     → tests for src/csm/execution/
│   └── scripts/       → tests for scripts/
├── integration/
│   ├── test_api_auth.py
│   ├── test_public_data_boundary_*.py
│   └── ...
└── conftest.py        → shared fixtures
```

- `tests/unit/` — tests a single module in isolation. No network, no filesystem outside temp dirs.
- `tests/integration/` — tests across module boundaries. May use temp directories for Parquet store.
- Async tests use `@pytest.mark.asyncio` (or auto-detected via `asyncio_mode = "auto"` in `pyproject.toml`).

---

## Local dev tips

### Running a single test
```bash
uv run pytest tests/unit/data/test_loader.py::test_fetch_single_symbol -v
```

### Debugging the API
```bash
uv run uvicorn api.main:app --reload --port 8000 --log-level debug
```

### Running a notebook
```bash
uv run jupyter lab notebooks/01_data_exploration.ipynb
```

### Regenerating the lockfile
After changing dependencies in `pyproject.toml`:
```bash
uv lock
```

### Running the quality gate on changed files only
```bash
uv run ruff check $(git diff --name-only main...HEAD -- '*.py')
uv run mypy $(git diff --name-only main...HEAD -- '*.py' | grep -v tests/)
```

### Pre-commit hook (optional)
Install a pre-commit hook to run lint and format on every commit:
```bash
uv run pre-commit install
```

---

## Testing security paths

The API-key auth and public-mode enforcement are tested in two locations:

- `tests/integration/test_api_auth.py` — end-to-end auth tests using FastAPI `TestClient`
- `tests/unit/test_api_security.py` — unit tests for `is_protected_path()` and `APIKeyMiddleware`

### Writing a private-mode auth test

Use `monkeypatch.setenv` to set `CSM_API_KEY`, then assert 401 for missing/wrong keys and 200 for correct keys:

```python
def test_protected_endpoint_requires_key(client):
    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 401
    assert "Missing X-API-Key" in resp.json()["detail"]

def test_protected_endpoint_accepts_valid_key(client, monkeypatch):
    monkeypatch.setenv("CSM_API_KEY", "test-key")
    resp = client.post("/api/v1/data/refresh", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
```

### Writing a public-mode 403 test

Set `CSM_PUBLIC_MODE=true`, then assert that write endpoints return 403 with the canonical "Disabled in public mode" body:

```python
def test_write_blocked_in_public_mode(client, monkeypatch):
    monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Disabled in public mode"
```

The `TestClient` fixtures in `tests/conftest.py` provide a pre-configured FastAPI app. See [Public Mode Guide](../guides/public-mode.md) § Configuring API Key for the full operational security documentation.

---

## Cross-references

- [Architecture Overview](../architecture/overview.md) — monorepo layers, data flow, security model
- [Getting Started](../getting-started/overview.md) — Docker + uv quickstart
- [Module Reference](../reference/) — per-subpackage API surface
- [.claude/knowledge/project-skill.md](../../.claude/knowledge/project-skill.md) — full project rules
- [.claude/playbooks/feature-development.md](../../.claude/playbooks/feature-development.md) — feature development playbook
