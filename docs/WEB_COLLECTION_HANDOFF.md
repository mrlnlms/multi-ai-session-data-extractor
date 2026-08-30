# Web collection handoff

Operational handoff for an agent refreshing the nine web sources. It is a
runbook, not a replacement for platform `state.md` files: use it to sequence
work and report evidence, then use each state file for extractor-specific
behavior and recovery.

## Current baseline

As of 2026-08-30, the four local CLIs are current and validated. The next
collection scope is web only. Treat the reconciled raw/merged tree as a
preservation baseline: a failed discovery must never overwrite it.

The canonical flow is:

```text
extractor/copy -> raw -> reconciler -> merged -> parser -> processed -> unify -> unified
```

Web `*-sync.py` commands perform capture, assets where applicable, and
reconciliation. They do **not** parse when called directly: run the matching
`*-parse.py` only after a successful sync, then update the unified parquets.

### Continuation point — 2026-08-30

This is the observed stopping point for the next session; re-check the
relevant platform state and login before acting, because browser sessions can
expire.

| Source | Observed status | Next safe action |
|---|---|---|
| NotebookLM | **success** — accounts 1 and 2 reconciled and parsed; unified regenerated | Do not reopen the lite-fetch regression unless a no-UI incremental run again produces fetches. Read its `state.md` and `server-behavior.md` first. Account 3 remains a preserved legacy snapshot. |
| Grok | **success** — synced, parsed, and included in unified | No rerun needed in this collection unless the user requests a fresher capture. |
| ChatGPT | **success** — headed incremental discovery, reconcile and parser completed | No rerun needed unless fresher capture is requested. Contract changes are documented in its platform state/server behavior. |
| Claude.ai | `blocked_login` | Renew the local session through its documented login path. |
| Gemini | `blocked_login` for both live accounts | Renew the local sessions; do not treat a missing XSRF/session value as an extractor defect. |
| Qwen | `blocked_login` | Renew the local session. |
| DeepSeek | `blocked_login` | Renew the local session. |
| Perplexity | **success** — incremental sync, reconcile and parser completed | No rerun needed unless fresher capture is requested. |
| Kimi | `blocked_login` | Renew the local session. |

NotebookLM regression resolution: `rLM1Ne` lite metadata regenerates a
per-source URL and two server-derived text fields. The classifier masks only
those fields, with a per-source structural guard; source identity, notes,
artifacts, full reconciliation, and preservation behavior remain checked.
The controlled no-UI validations ended at `0 fetch / 53 copy` for account 2
and `0 fetch / 129 copy` for account 1. This is documented in the platform
state and server-behavior files and covered by focused tests. Do not broaden
the mask or suppress note differences without a fresh controlled comparison.

## Required reading and safety boundary

Before changing or running a platform:

1. Read `AGENTS.md`, `README.md`, `docs/README.md`, and this document.
2. Read `docs/platforms/<platform>/state.md`; also read its
   `server-behavior.md` when it exists.
3. Inspect `git status --short`. Preserve unrelated changes.
4. Do not delete, reset, or make raw/merged data “match”. Existing files
   represent preserved history, including server-deleted conversations.
5. Do not run `dvc gc`. A `dvc push` requires explicit user authorization.
6. Do not commit or push unless the user asks. Never expose cookie, token,
   message, or asset contents in the report.

If login has expired, report the platform as blocked and request the user to
complete the corresponding headed login. Do not attempt workarounds that
extract credentials from browser storage.

## Sources and entrypoints

| Source | Scope | Sync | Parse | Platform state |
|---|---|---|---|---|
| ChatGPT | one account; headed / Cloudflare | `chatgpt-sync.py --no-voice-pass` | `chatgpt-parse.py` | `platforms/chatgpt/state.md` |
| Claude.ai | one account | `claude-sync.py` | `claude-parse.py` | `platforms/claude-ai/state.md` |
| Gemini | accounts 1 and 2 | `gemini-sync.py` | `gemini-parse.py` | `platforms/gemini/state.md` |
| NotebookLM | live accounts 1 and 2; account 3 is a preserved legacy snapshot | `notebooklm-sync.py` | `notebooklm-parse.py` | `platforms/notebooklm/state.md` |
| Qwen | one account | `qwen-sync.py` | `qwen-parse.py` | `platforms/qwen/state.md` |
| DeepSeek | one account | `deepseek-sync.py` | `deepseek-parse.py` | `platforms/deepseek/state.md` |
| Perplexity | one account | `perplexity-sync.py` | `perplexity-parse.py` | `platforms/perplexity/state.md` |
| Grok | one account | `grok-sync.py` | `grok-parse.py` | `platforms/grok/state.md` |
| Kimi | one account | `kimi-sync.py` | `kimi-parse.py` | `platforms/kimi/state.md` |

Run commands with `PYTHONPATH=. .venv/bin/python scripts/<command>`.
Some states document flags or recovery helpers that override this compact
table. The direct platform documentation wins.

## Recommended execution order

Work in small, observable batches; do not open all platforms simultaneously.

1. **Read-only readiness:** inspect the source states, capture/reconcile logs,
   existing processed timestamps, and persistent-profile presence. Record the
   result for all nine sources before downloading.
2. **Stable single-account sources:** Claude.ai, Perplexity, Qwen, DeepSeek.
   For each: sync -> confirm reconcile health -> parse -> record totals.
3. **Multi-account sources:** Gemini and NotebookLM. Run the documented
   all-account command unless only one account is explicitly in scope.
4. **Interactive or likely-fragile sources:** ChatGPT (headed) and then Grok
   and Kimi. Diagnose a UI/API change before altering selectors or requests.
5. **Consolidate:** when every successful platform has a fresh processed
   output, run `scripts/unify-parquets.py`, validate unified freshness, and
   render only the affected Quarto profiles if useful.

This order is a risk-management default, not a claim about platform priority.
If the user names a platform, start there and keep the same per-platform
validation gates.

## Per-platform validation gate

For every attempted source, capture these facts in the final report:

- command and flags used (never credentials);
- discovery result and whether it passed the platform's partial-discovery
  guardrail;
- new/updated/preserved-missing counts from capture and reconcile logs;
- parse output counts and whether processed parquet is newer than raw/merged;
- status: `success`, `blocked_login`, `partial_discovery`, `upstream_change`,
  or `failed`; and the safe next action.

Only after a successful reconcile should the parser run. If discovery is
partial, preserve the existing raw/merged material and use the documented
`refetch_known` path where available. Do not label the platform green when a
parquet predates its raw or merged input.

## Interface-change protocol

An unexpected UI/API response is evidence, not a reason to make a broad
rewrite.

1. Stop that platform after preserving its logs and identify the failed
   discovery/fetch boundary.
2. Inspect only the relevant extractor, platform state, and browser/network
   evidence available in the authenticated session.
3. Make the narrowest compatible change; add or update a regression test.
4. Run focused tests, then rerun that platform in a safe incremental mode.
5. Continue to the next platform only after reporting the result.

## Completion and handoff

At the end, provide a compact table with one row per web source and the
validation facts above. State which sources were not attempted and why.
Include test commands/results and whether `unify-parquets.py` ran.

Update this document only for cross-platform operational decisions. Put a
platform-specific new fact in that platform's `state.md` or
`server-behavior.md`, so the next collection begins from observed evidence.
