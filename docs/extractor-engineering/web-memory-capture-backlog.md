# Web memory and context: first pass and follow-ups

This is the single entry point for the web memory/configuration front. **The
practical capture/integration round handled six platforms: ChatGPT, Claude.ai,
Perplexity, Kimi, Qwen and Gemini.** The other three web platforms have only
the bounded capability assessment described below. A follow-up is a separate,
narrower surface or missing evidence, not a claim that an already handled
platform must be repeated. The per-platform `state.md` holds the observed UI
and transport detail; the
[memory architecture](../product/agent-memory-architecture.md) defines the
canonical projection.

## Practical round — six platforms handled

Checked against the maintained platform states on 2026-09-25. "Handled" is
bounded by the demonstrated native surface, not a promise that every feature
called Memory, Brain or Project is captured. Kimi was handled as raw-only
because its observed native collections/values were empty.

| Platform | What the first pass delivered | Outcome |
|---|---|---|
| [ChatGPT](platforms/web/chatgpt/state.md) | Account saved memories, memory summary and Custom Instructions: native raw history and versioned canonical records. | **Captured and projected.** |
| [Claude.ai](platforms/web/claude-ai/state.md) | Native Melange memory topics at account **and Project** scope, plus preserved legacy Markdown exports: raw history and versioned canonical records. | **Captured and projected.** |
| [Perplexity](platforms/web/perplexity/state.md) | Account Memory collection: paginated native raw history and versioned canonical records. | **Captured and projected.** |
| [Kimi](platforms/web/kimi/state.md) | Native reads of the empty Memory Instructions list, account settings, Dream status and Project catalog/detail, with cumulative raw snapshots. | **Handled at the observed empty state; raw only.** No non-empty item or value supported a canonical memory projection. |
| [Qwen](platforms/web/qwen/state.md) | Account saved memories and Customize Qwen instructions: native raw history and versioned canonical records. | **Captured and projected.** |
| [Gemini](platforms/web/gemini/state.md) | Account Instructions: native raw history and versioned canonical records, including one preserved-missing historical item. | **Captured and projected** for Instructions; learned Memory had no inspectable item list in the bounded probe. |

## Other web platforms — bounded capability assessment only

These were considered in the cross-platform census, **not** integrated as
memory capture/projection in the six-platform round. None currently has a
separate, materialized account-memory collection demonstrated in the maintained
evidence; this is not proof that the products lack such a feature.

| Platform | What is currently established | Consequence |
|---|---|---|
| [Grok](platforms/web/grok/state.md) | Workspace `customPersonality` is already Project metadata/context; no separate account-global memory/instruction record was established. | **Bounded assessment, no account-memory collection demonstrated.** |
| [DeepSeek](platforms/web/deepseek/state.md) | Observed account surfaces did not establish a separate memory/instruction collection. | **Bounded assessment, no separate collection demonstrated.** |
| [NotebookLM](platforms/web/notebooklm/state.md) | Notebook sources, notes, chats and generated outputs are ordinary notebook objects, not a separate memory/instruction collection. | **Bounded assessment, no separate collection demonstrated.** |

## Completed Project-memory follow-up

Claude.ai is **closed for the Project-memory evidence currently in hand**.
Its 124 current Melange Project topics were already captured and projected;
the three preserved classic snapshots are now parsed separately into 38
historical Project documents plus one account document, with 41 content
versions and 117 dated-snapshot evidence rows. The classic Project UUID is
retained as scope, not treated as a Melange topic ID. No new owner input or
platform mutation is needed for this Claude memory work. Project Instructions
already live separately in Project metadata (`prompt_template`; 32 nonempty
values in 88 local rows), and Project Context remains distinct from memory.
The Parquets and DVC pointers were published with Git/DVC commit `f4e2559`;
archive assurance passed after publication.

## Follow-ups — separate surfaces, grouped by evidence gate

These are **not unfinished six-platform-round work**. Project files,
instructions, native memories, Brain and history reuse are distinct objects.
An existing Project, chat or file can guide investigation but does not prove a
separate Project-memory record.

### Investigate existing content first — no new owner input needed yet

| Surface | Existing evidence | Next read-only check / possible later gate |
|---|---|---|
| [ChatGPT](platforms/web/chatgpt/state.md) Project settings and possible Project memory items | Account memory surfaces are covered. The UI and direct reads of `GET /backend-api/gizmos/{project_id}` return Project detail with `gizmo.instructions`, `memory_scope` and `memory_enabled`; the pictured Default Project has native scope `global`. The earlier generic "session expired" error was an HTTP 403 from using the wrong account profile for that Project; the correct profile returned 200. Current capture retains only files, and no separate Project-memory item list was observed. | Preserve Project detail/settings cumulatively under the correct account; keep instructions as Project-scoped guidance and memory mode as metadata, not as native memory items. Check a Project-only payload or independent memory-item collection only when observable; no more owner screenshots or re-login needed now. |
| [Perplexity](platforms/web/perplexity/state.md) Project Instructions | Existing Project Settings exposes explicitly Project-scoped instructions, but their native read payload is not mapped. | Inspect the settings read without changing the Project. A non-empty owner sample may be needed only if the available settings are empty; keep instructions separate from Memory, Brain and Files/Links. |

### Needs a materialized owner item or entitlement to establish a baseline

| Surface | Current boundary | Owner input that would unlock the next capture |
|---|---|---|
| [Perplexity](platforms/web/perplexity/state.md) Project Memory and Project Brain | A Project Memory subsection and Brain controls are visible, but no readable Memory contents or Brain record was observed. Account Memory capture does not cover either. | Open an existing populated Project state, or let a Brain appear through normal use; then inspect its read-only payload, IDs, dates, scope and pagination. Do not create one on the owner's behalf without approval. |
| [Perplexity](platforms/web/perplexity/state.md) account Brain | The observed account showed an entitlement gate, not an empty collection. | Revisit only if the owner has access and an inspectable Brain record. |
| [Kimi](platforms/web/kimi/state.md) Memory Instructions, Dream Memory, account instructions and Project context | Native raw reads preserve the observed empty Memory list, settings, Dream status and Project catalog/detail. Dream tree returned 404 while disabled; no non-empty item/value established a canonical projection. | An owner-created or naturally occurring non-empty item, enabled/available Dream tree, instruction value or populated Project context would establish the missing payload and lifecycle. A controlled sample requires explicit approval. Saved Prompts remain outside native memory. |

### Wait for a demonstrable native surface, not a synthetic answer

| Surface | Current boundary | Reopen only when |
|---|---|---|
| [Gemini](platforms/web/gemini/state.md) conversation-derived Memory | Account Instructions are already projected. The enabled learned-Memory control exposed no readable item list or stable native envelope in the bounded probe. | The product/account exposes an inspectable native record or payload; do not reconstruct learned memory from model answers. |
| [Grok](platforms/web/grok/state.md) account-level personalization/instructions | Workspace `customPersonality` is Project context; no separate account-global record is established. | A concrete owner-visible account surface and authenticated read payload can be identified; do not promote workspace settings to account memory. |

### Owner samples to bring later, one at a time

- **Perplexity:** an existing Project with a nonempty Project Memory item or
  Project Brain record; account Brain only if the entitlement is available.
  Project Instructions can be investigated without a new sample first.
- **Kimi:** a nonempty Memory Instruction, or a Project with an instruction or
  other populated context; Dream Memory only if it becomes enabled/available.
- **ChatGPT:** a Project-only mode example would confirm that mode's native
  value. Do not change an existing Project solely for this investigation;
  Project-detail capture can proceed from the current Default example.

No artificial sample is requested for Gemini or Grok until the product shows
an inspectable native record/surface. The owner need not collect all examples
before the next engineering step.

Qwen has no separately evidenced memory follow-up in this list. DeepSeek and
NotebookLM have no separate memory/instruction capture task until a concrete
owner-visible surface appears. Historical research and UI observations in the
private workbench are evidence, but earlier verdicts must be checked against
current code, raw data and platform states before reuse.

## Resume after a compacted session

Claude Project memory is closed for the current native Melange topics and the
preserved classic snapshots; do not recapture or reproject them to restart this
front. The ChatGPT Project **read-only transport diagnosis is done**. The
pictured Project is accessible through `account-2`, not `default`; its detail
GET exposes instructions and memory-scope settings but no observed item-level
Project memory. The next engineering step without owner input is cumulative
Project-detail preservation under the correct account. Perplexity Project
Instructions can also be inspected without a new item. The owner-item gates
for Perplexity and Kimi, plus the unobserved native surfaces for Gemini and
Grok, remain separate below. Ask only for the specific item or entitlement
that unlocks a chosen gap.

For each newly demonstrated surface: preserve the full native read response and
its scope in cumulative raw history; distinguish complete from partial reads;
avoid false `preserved_missing`; validate identity, timestamps and lifecycle
before projecting into the canonical tables; then update its platform state,
known limitations and this list. Personal record content stays out of Git.
