# Script command map

The `scripts/` root is the supported operational interface. Routine commands
use stable names: `<source>-login.py`, `<source>-sync.py`, and
`<source>-parse.py`. Web sync commands capture assets and reconcile; the
dashboard/headless pipeline then runs the corresponding parser before
unification. CLI sync commands already copy and parse.

For setup and normal command examples, use
[`docs/SETUP.md`](../docs/SETUP.md) and
[`docs/operations/pipeline.md`](../docs/operations/pipeline.md).

## Platform internals

`platform/<source>/` contains secondary capture, reconcile, asset, and
refetch helpers used by the stable root commands. These are engineering
interfaces rather than the normal starting point. Their contracts and known
limits live in the relevant
[`docs/extractor-engineering/platforms/`](../docs/extractor-engineering/platforms/)
record.

## Probes

`probes/<source>/` contains empirical investigation tools. Run a probe only
to answer a specific platform question, and record durable findings in the
source's engineering documentation. Probes may open browsers or call internal
APIs and are not part of routine collection.

## Maintenance and recovery

`maintenance/` contains exceptional cross-platform upkeep and validation
commands. `recovery/` contains historical reconstruction tools. Before using
either class, read the authoritative runbook or source state record linked
from [`docs/README.md`](../docs/README.md); these commands may inspect or
rewrite derived data and are not normal pipeline stages.
