# DeepSeek — technical coverage

## Pipeline

- **Pastas cumulativas por conta:** a conta padrao usa `data/raw/DeepSeek/`
  e `data/merged/DeepSeek/`; as demais usam `account-<n>/` sob essas raizes.
- **Sync orchestrator (2 steps):** `python -m src.platforms.deepseek.commands.sync` (capture +
  reconcile).
- **Headless capture.**
- **Auth:** perfis persistentes em `.storage/deepseek-profile-<account>/`
  (gerados via `python -m src.platforms.deepseek.commands.login --account <account>`). A profile can remain present
  after its `userToken` expires, so validate a minimal API request first.

## Coverage

Chat sessions captured. Reconciler v3 (FEATURES_VERSION=2): no
projects (DeepSeek does not expose them).

Binary assets are immutable and enter `merged` through a hardlink when the
filesystem supports it, with a normal copy as the portability fallback.
They do not yet have a validated canonical `assets`/`asset_links` adapter, so
DeepSeek remains library-only in the archive-wide asset coverage matrix.

### Latest validated collection — 2026-08-30

- The profile's stored token had expired and was renewed by interactive login;
  a minimal API list request then confirmed authorization before capture.
- Incremental discovery found 82 current sessions. Three new sessions were
  fetched, 79 were reused, and there were no fetch errors.
- Reconciliation retained the 82 current sessions plus 1 preserved-missing
  historical session (83 total).
- The parser produced 83 conversations, 732 messages, 20 tool events, and
  275 branches; unified parquets were regenerated.

### Additional account collection — 2026-09-12

- A second personal account was captured through its own persistent browser
  profile and isolated raw/merged trees.
- Discovery found 1 current session; the smoke capture fetched it without
  errors, and the following incremental run reused it.
- The combined parser output has 84 conversations, 734 messages, 20 tool
  events, and 276 branches. The canonical `account` field distinguishes the
  two accounts by their configured email addresses.

### Historical reference volume

- 79 chat sessions at the original validation point.
- 722 messages / 20 tool events / 271 branches.

## Canonical parser

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

`src/platforms/deepseek/parser.py` + `_parser_helpers.py`.

### Coverage

- **R1 reasoning → `Message.thinking`** (~31% of msgs in a reference
  corpus — high coverage).
- **`thinking_elapsed_secs`** summarized in
  `settings_json.thinking_elapsed_total_secs`.
- **`accumulated_token_usage`** → `Message.token_count` (~98% coverage).
- **`pinned` → `is_pinned`** (cross-platform).
- **`agent`** (chat/agent) + **`model_type`** (default/thinking) → `mode`.
  - `model_type='expert'` mapped to `mode='research'` (R1 reasoner).
- **`current_message_id` + `parent_id`** (int IDs) → flat DAG branches.
  ~2.4 branches/conv (DeepSeek has lots of regenerate).
- **`search_results`** (rich structure with title/url/metadata) →
  ToolEvent + `Message.citations_json`.
- **`incomplete_message` + `status`** → `Message.finish_reason` (100% cov.).
- **`status` enum:** `FINISHED`/`INCOMPLETE`/`WIP`.
- **Files per msg** → `attachment_names`.
- **`feedback`/`tips`/`ban_edit`/`ban_regenerate`/`thinking_elapsed_secs`**
  preserved in `Message.attachments_json`.

> **Note:** The legacy parser's old schema was OUTDATED (it expected
> `mapping` + `fragments`, but the current API returns flat `chat_messages`
> with dedicated fields). Parser v3 is a complete rewrite.

## Descriptive Quarto

`notebooks/deepseek.qmd`: 8MB HTML, royal blue color.

## Validated CRUD scenarios

| Scenario | Result |
|---|---|
| Rename | title matches in parquet, `updated_at` bumps |
| Pin | `is_pinned=True`, `updated_at` bumps |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preserved |

## Related documents

- `docs/extractor-engineering/platforms/web/deepseek/server-behavior.md` — upstream behavior.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.sync
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.parse
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/deepseek.qmd
```

Para uma conta adicional, use um perfil e uma arvore isolados; o parser reune
as arvores e registra o email configurado em `.storage/accounts.json` no campo
`account` dos Parquets:

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.login --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.parse
```
## Explicit login-health check

A minimal `GET /api/v0/chat_session/fetch_page` listing is the established read-only check; missing or rejected `userToken` means `expired`. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
