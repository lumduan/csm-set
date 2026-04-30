# Commands — csm-set

Canonical commands. Every Python invocation is prefixed with `uv run`. The only exception is `./scripts/publish.sh`, which is a shell script that internally uses `uv`.

## Environment

| Task | Command |
|---|---|
| Sync deps from lockfile | `uv sync` |
| Add a runtime dep | `uv add <pkg>` |
| Add a dev dep | `uv add --dev <pkg>` |
| Add to a group | `uv add --group research <pkg>` |
| Remove a dep | `uv remove <pkg>` |
| Upgrade one package | `uv lock --upgrade-package <pkg> && uv sync` |
| Upgrade all packages | `uv lock --upgrade && uv sync` |
| Show tree | `uv tree` |
| Audit (CVE) | `uv pip audit` |

## Quality Gate

| Task | Command |
|---|---|
| Tests | `uv run pytest tests/ -v` |
| Tests + coverage | `uv run pytest --cov=src/csm --cov-report=term-missing` |
| Single test | `uv run pytest tests/<path>::<test_name> -v` |
| Type check | `uv run mypy src/` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Format check | `uv run ruff format --check .` |
| Pre-commit run | `uv run pre-commit run --all-files` |

## Run

| Task | Command |
|---|---|
| API local (dev reload) | `uv run uvicorn api.main:app --reload` |
| API local (prod-like) | `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000` |
| UI local | `uv run python -m ui.app` |
| Notebook | `uv run jupyter lab` |
| Run an example | `uv run python examples/<name>.py` |
| Run a script | `uv run python scripts/<name>.py` |

## Profiling

| Task | Command |
|---|---|
| cProfile a script | `uv run python -m cProfile -o profile.out scripts/<name>.py` |
| py-spy live | `uv run py-spy top -- python scripts/<name>.py` |
| memray | `uv run memray run scripts/<name>.py && uv run memray flamegraph memray-*.bin` |

## Release

| Task | Command |
|---|---|
| Bump version | edit `pyproject.toml` `[project] version` |
| Update CHANGELOG | edit `CHANGELOG.md` |
| Tag | `git tag vX.Y.Z` |
| Publish | `./scripts/publish.sh` |
| Verify in clean venv | `uv venv /tmp/v && /tmp/v/bin/pip install csm-set==X.Y.Z` |

## Quick combined gates

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run pytest tests/ -v
```
