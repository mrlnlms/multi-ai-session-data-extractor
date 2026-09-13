# Script command map

Each source has one home under `platform/<source>/`. Web platforms expose
`login.py`, `sync.py`, and `parse.py`; CLI platforms expose `sync.py` and
`parse.py`. Web sync commands capture assets and reconcile; the
dashboard/headless workflow then runs the corresponding parser before
unification. CLI sync commands already copy and parse.

For example:

```bash
PYTHONPATH=. .venv/bin/python scripts/platform/chatgpt/login.py
PYTHONPATH=. .venv/bin/python scripts/platform/chatgpt/sync.py
PYTHONPATH=. .venv/bin/python scripts/platform/chatgpt/parse.py
PYTHONPATH=. .venv/bin/python scripts/workflows/headless-pipeline.py --no-publish
PYTHONPATH=. .venv/bin/python scripts/workflows/unify-parquets.py
```

For setup and normal command examples, use
[`docs/SETUP.md`](../docs/SETUP.md) and
[`docs/operations/pipeline.md`](../docs/operations/pipeline.md).

## Platforms

`platform/<source>/` contains both the source's operational commands and its
secondary capture, reconcile, asset, and refetch helpers. Their contracts and
known limits live in the relevant
[`docs/extractor-engineering/platforms/`](../docs/extractor-engineering/platforms/)
record.

## Workflows

`workflows/` contains cross-platform operations: shared CLI copying, the
headless pipeline, manual-save ingestion, unification, and local serving of
Quarto output.

## Probes

`platform/<source>/probes/` contains that source's empirical investigation
tools. Run a probe only to answer a specific platform question, and record
durable findings in the source's engineering documentation. Probes may open
browsers or call internal APIs and are not part of routine collection.

## Maintenance and historical inputs

`maintenance/` contains deliberate cross-platform storage upkeep commands:
local asset deduplication and DVC remote garbage collection. Source-specific
exceptional tools remain with their platform; for example, Antigravity CLI's
`recover-legacy.py` decodes copied legacy containers before the normal parser
consumes their sidecars. Historical format adapters are part of their
platform's official parser: NotebookLM's normal `parse.py` includes immutable
old-format snapshots from `data/external/notebooklm-snapshots/`.

Maintenance and exceptional recovery commands are not normal pipeline stages;
read the relevant runbook or source state record linked from
[`docs/README.md`](../docs/README.md) before using them.
