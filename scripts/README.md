# Script command map

Each source has one home under `src/platforms/<source_id>/`. Web platforms
expose login, sync, and parse modules under `commands/`; CLI platforms expose
sync and parse modules there. Web sync commands capture assets and reconcile; the
dashboard/headless workflow then runs the corresponding parser before
unification. CLI sync commands already copy and parse.

Platform command modules are the executable interface. Shared workflows, the
dashboard, and tests reuse them rather than copying source rules into scripts.

For example:

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.login
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.parse
PYTHONPATH=. .venv/bin/python scripts/workflows/headless-pipeline.py --no-publish
PYTHONPATH=. .venv/bin/python scripts/workflows/unify-parquets.py
```

For setup and normal command examples, use
[`docs/SETUP.md`](../docs/SETUP.md) and
[`docs/operations/pipeline.md`](../docs/operations/pipeline.md).

## Workflows

`workflows/` contains cross-platform operations: shared CLI copying, the
headless pipeline, manual-save ingestion, unification, and local serving of
Quarto output.

## Probes

`src/platforms/<source_id>/probes/` contains that source's empirical investigation
tools. Run a probe only to answer a specific platform question, and record
durable findings in the source's engineering documentation. Probes may open
browsers or call internal APIs and are not part of routine collection.

## Operator tools and historical inputs

`tools/` contains optional operator commands that are useful to the repository
but are not pipeline stages. `prune-dvc-history.py` deliberately removes remote
DVC objects outside the current workspace state; it uses the configured default
remote or one selected with `--remote`, so forks are not tied to Google Drive.

Source-specific exceptional tools remain with their platform; for example,
Antigravity CLI's `commands.recover_legacy` decodes copied legacy containers
before the normal parser consumes their sidecars. Historical format adapters
are part of their platform's official parser: NotebookLM's parse command includes
immutable old-format snapshots from `data/external/notebooklm-snapshots/`.

Operator tools and exceptional recovery commands are not normal pipeline stages;
read the relevant runbook or source state record linked from
[`docs/README.md`](../docs/README.md) before using them.
