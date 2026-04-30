# Project Skill — csm-set Operating Rules

Top-level rules every agent and contributor must follow when working in this repository.

## Hard Rules

1. **Always `uv run`.** Never `python`, `pip`, `poetry`, or `conda` directly.
2. **Async-first I/O.** All HTTP via `httpx.AsyncClient`. `requests` is forbidden in `src/csm/`.
3. **Pydantic everywhere boundaries cross.** Function I/O between modules (especially across `src/csm/`, `api/`, `ui/`) goes through Pydantic models — never raw dicts.
4. **Notebook markdown cells must be in Thai.** Code, identifiers, comments inside code cells stay English.
5. **`docs/plans/` is git-tracked.** Never gitignore it. It's part of the project record.
6. **SET symbols come from `settfex`.** Legacy `thai-securities-data` is removed. Do not reintroduce.
7. **Time zone is `Asia/Bangkok`.** All financial timestamps stored as tz-aware `pandas.Timestamp` in UTC, displayed in `Asia/Bangkok`.
8. **No secrets in repo.** All config via env + `pydantic-settings`.

## Soft Conventions

- File size target: ≤ 400 lines per Python file.
- Coverage target: ≥ 90 % on `src/csm/`.
- Public functions: full type annotations, full docstring with Args / Returns / Raises / Example.
- Logging: `logging.getLogger(__name__)` — never `print` in `src/csm/`.

## Where to Look First

- Architecture: [architecture.md](architecture.md)
- Standards: [coding-standards.md](coding-standards.md)
- Commands: [commands.md](commands.md)
- Stack reasoning: [stack-decisions.md](stack-decisions.md)
- Known recurring bugs: [../memory/recurring-bugs.md](../memory/recurring-bugs.md)
- Anti-patterns to avoid: [../memory/anti-patterns.md](../memory/anti-patterns.md)
