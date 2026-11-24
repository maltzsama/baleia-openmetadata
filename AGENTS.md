# AGENTS.md

Guidance for agents and contributors working in this repository.

## Scope

This package is an OpenMetadata ingestion connector for Baleia's semantic
catalog. It runs inside OpenMetadata's ingestion framework and only reads from
Baleia's semantic catalog API. Physical metadata belongs to OpenMetadata's stock
Trino connector through Baleia's BI gateway; never duplicate it here.

## Commands

| Command | What it does |
|---|---|
| `uv venv && uv pip install -e ".[ingestion]" --group test --group lint` | Set up a development environment. |
| `uv run --no-sync pytest` | Run the tests. |
| `uv run --no-sync ruff check .` | Lint. |
| `uv run --no-sync ruff format --check .` | Check formatting. |
| `uv build && uvx twine check --strict dist/*` | Build and check the distribution. |
| `OPENMETADATA_URL="$(scripts/openmetadata.sh up 2.1.0)" uv run --no-sync pytest tests/integration` | Integration suite against a real OpenMetadata (match `openmetadata-ingestion` to the server; `scripts/openmetadata.sh down 2.1.0` afterwards). Nightly in the `Integration` workflow. |

Definition of done: lint, format check, tests and build pass. CI runs the
tests against every supported `openmetadata-ingestion` release (2.0.x and
2.1.x) on Python 3.11, 3.12, 3.13 and 3.14.

The Python range follows OpenMetadata, because the connector runs in its
ingestion environment: the version in OpenMetadata's official ingestion images
(3.12 today) is always tested, versions past their end of life are dropped, and
newer versions are added when `openmetadata-ingestion` installs and the tests
pass on them. When OpenMetadata changes its images or its tested range, update
the CI matrix, `requires-python`, the classifiers, ruff's `target-version` and
the README compatibility table together.

## Rules

- `openmetadata-ingestion` is never a runtime dependency (see `pyproject.toml`).
  Code must work with every supported release; branch on capabilities, not on
  version strings, when releases differ.
- The BI key is a password credential. Never log it, never put it in an entity
  description or URL, and treat it as a secret in the connection configuration.
- One bad Baleia item never aborts a run: yield `Either(left=StackTraceError(...))`
  for it and continue.
- Deleted Baleia items are soft-deleted in OpenMetadata, never hard-deleted.

## Pull requests

Work is sequential: one PR at a time, from the latest `main`, until it is merged.

1. Write every PR, issue, comment, commit message, code comment and doc in
   English.
2. Run the definition of done before opening the PR, and reference the issues
   it closes with `Closes #<issue>`.
3. Trigger CodeRabbit with a `@coderabbitai review` comment. Read every finding,
   fix the valid ones, and resolve each fixed thread.
4. Merge with a merge commit only: `gh pr merge <n> --merge --delete-branch`.
5. After merging, switch to `main`, `git pull --ff-only`, and check that every
   `Closes` issue is closed.

### Titles, commits and the changelog

release-please builds `CHANGELOG.md` from the commits on `main`.

- Every commit is atomic and conventional: `type(scope): subject`.
- The PR title is a plain sentence, not a conventional commit.
- No two commits of a PR share a subject, and none repeats the PR title. Fold
  fixups into the commit they fix before merging.
