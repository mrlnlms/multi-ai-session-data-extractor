# Adding or promoting a platform

Technical checklist for introducing a source or promoting an existing source
to the canonical capture pipeline. Start from the current platform documents
and observable code, not from a historical script name or a copied plan.

## Before implementation

1. Read `AGENTS.md`, the [extractor-engineering README](README.md) and the
   relevant `platforms/<web|cli>/<source>/state.md` if the source already exists.
2. Observe the real platform with an authenticated browser. Capture actual
   network traffic; do not infer endpoint names from UI labels.
3. Decide the smallest supported scope: account model, discovery method,
   conversation/container types, assets and known access-tier limits.
4. Record evidence in `platforms/<source>/discovery.md` or
   `server-behavior.md` according to its role.

## Canonical implementation path

### 1. Capture and preservation

- Use the source's cumulative `data/raw/<Source>/` location; do not create a
  dated snapshot layout for normal operation.
- Preserve capture logs and write a current human-readable summary.
- Make discovery defensive. A partial list must not overwrite a healthy raw
  base; use the source's baseline/fail-fast or refetch-known pattern when
  applicable.
- Download assets idempotently and keep an explicit failure status for
  upstream-deleted assets rather than retrying them forever.

### 2. Reconciliation

- Reconcile the current raw observation with previous merged history.
- Validate the applicable scenarios: new item, updated item, rename, server
  deletion, container/project changes and passive orphans.
- A server-side absence becomes `preserved_missing`, never a local deletion.

### 3. Fixtures and parser

- Explore representative merged data before designing the parser.
- Add sanitized fixtures for distinctive features and edge cases.
- Produce canonical `conversations`, `messages`, `tool_events` and `branches`
  Parquets, plus documented auxiliary tables only when the source needs them.
- Preserve branches, tool activity, assets and source-specific metadata without
  fabricating conversational content.

### 4. Integration and documentation

- Add the parse entry point and ensure the source reaches unification.
- Add the source to the dashboard and descriptive Quarto reports when it is
  promoted.
- Keep `state.md` as the current technical entry point. Put detailed empirical
  evidence in `discovery.md`, validated upstream facts in
  `server-behavior.md`, and major self-contained failures in `incident-*.md`.
- Register genuine gaps in [known-limitations.md](known-limitations.md), not
  as undocumented assumptions.

## Validation standard

Run focused tests while iterating, then the full suite before proposing the
change. Confirm that the output Parquets are current relative to raw and
merged inputs, that repeated runs are idempotent, and that no personal source
data entered Git.

For existing legacy behavior, compare the old and new results with an explicit
explanation of differences. More coverage is welcome, but test quantity alone
is not a completion criterion.

## Recurring lessons

- Network observation beats guessed endpoints.
- UI labels and API names often differ.
- SPA routing may require controlled DOM interaction to reveal identifiers.
- Free, Pro, Team and Enterprise accounts expose different observable data;
  distinguish an upstream limit from an extractor gap.
- Positional APIs require evidence for every index path.
- Rename behavior and timestamps are platform-specific; validate them rather
  than assuming ChatGPT behavior transfers unchanged.
