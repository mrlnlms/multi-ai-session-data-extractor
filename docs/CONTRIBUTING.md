# Contributing

Contributions are welcome: issue reports, fixes, tests, documentation and
platform coverage. The project preserves personal AI-session data, so changes
must favor evidence, reproducibility and never downgrading captured history.

## Report a problem

1. Check [known limitations](extractor-engineering/known-limitations.md): some
   observed behaviors are upstream limits, not bugs.
2. Reproduce with the current code.
3. Open an issue with the affected platform, exact command, full error,
   Python version and operating system.

For a security issue, follow [SECURITY.md](SECURITY.md) instead of disclosing
credentials or private data publicly.

## Submit a pull request

1. Fork the repository and work on a branch, not `main`.
2. Keep the change focused and explain its observable effect.
3. Run the relevant tests and the full suite before submitting:

   ```bash
   PYTHONPATH=. .venv/bin/pytest
   ```

4. Add or update tests for changed behavior. Do not rely on a fixed test
   count; parametrization and coverage evolve.
5. Never commit captured conversations, browser profiles, OAuth material or
   private paths. Review `git diff` before committing.
6. Update the documentation that owns the changed behavior.

Use Conventional Commit messages (`feat:`, `fix:`, `docs:`, `refactor:`,
`test:`). Portuguese or English is fine; be clear and consistent.

## Platform and schema changes

Before changing an extractor, reconciler or parser, read `AGENTS.md`, the
platform's `state.md` and the canonical schema in `src/schema/models.py`.
The schema is the boundary between capture and analysis: a breaking change
needs explicit discussion and validation before publication.

The technical playbook for adding or substantially promoting a platform is
[extractor-engineering/adding-a-platform.md](extractor-engineering/adding-a-platform.md).
It covers discovery, capture, reconciliation, fixtures, parser, validation and
documentation.

## Project conventions

- Code and identifiers are English. Documentation may use Portuguese or
  English consistently within each file.
- Follow the surrounding code style; there is no required project-wide linter.
- Use sanitized fixtures. Never place personal source data in Git.
- Preserve records absent from the server as `preserved_missing`; do not clean
  data merely to make a run appear consistent.
- Run relevant validation after moving documentation or changing paths.

## Scope

The project is a capture and preservation system. Interpretive analysis
features such as sentiment, clustering and topic detection belong in a
consumer or analysis layer, not in this capture pipeline. For a large change,
open a discussion issue before investing heavily in implementation.
