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

Checked against the maintained platform states on 2026-09-26. "Handled" is
bounded by the demonstrated native surface, not a promise that every feature
called Memory, Brain or Project is captured. Kimi was handled as raw-only
because its observed native collections/values were empty.

| Platform | What the first pass delivered | Outcome |
|---|---|---|
| [ChatGPT](platforms/web/chatgpt/state.md) | Account saved memories, memory summary and Custom Instructions: native raw history and versioned canonical records. | **Captured and projected.** |
| [Claude.ai](platforms/web/claude-ai/state.md) | Native Melange memory topics at account **and Project** scope, plus preserved legacy Markdown exports: raw history and versioned canonical records. | **Captured and projected.** |
| [Perplexity](platforms/web/perplexity/state.md) | Account Memory collection and Project Instructions: native raw history with versioned canonical records. | **Captured and projected** for both surfaces. |
| [Kimi](platforms/web/kimi/state.md) | Native reads of the empty Memory Instructions list, account settings, Dream status and Project catalog/detail, with cumulative raw snapshots. | **Handled at the observed empty state; raw only.** No non-empty item or value supported a canonical memory projection. |
| [Qwen](platforms/web/qwen/state.md) | Account saved memories and Customize Qwen instructions: native raw history and versioned canonical records. | **Captured and projected.** |
| [Gemini](platforms/web/gemini/state.md) | Account Instructions: native raw history and versioned canonical records, including one preserved-missing historical item. | **Closed.** Instructions are captured/projected; the learned-Memory surface was explored and yielded no user-readable items. No further Gemini memory work is pending. |

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

ChatGPT Project **settings/detail capture is implemented and locally
materialized**, separate from the already-published account-memory round.
Immutable per-account detail snapshots preserve the complete native response;
nonempty Project instructions project as scoped `project_instructions`, while
memory mode/enabled are raw settings, not memory items. The first read-only
run captured 59 Project details and projected 12 instruction documents. One
historical ID failed a detail read without any missing/deletion inference.
On 2026-09-26 the owner supplied a Project-only sample; its read-only capture
covered all 11 Projects in the selected profile with no errors. The sample's
UI choice **Project-only memory** maps to native `gizmo.memory_scope="project_v2"`;
its nonempty instructions were parsed. `gizmo.memory_enabled=false` is also
preserved as a literal setting, without inferring its semantics. No separate
Project-memory item list analogous to saved personal memories is exposed.
ChatGPT now has 13 projected `project_instructions` documents. The previous
historical read failure remains non-blocking.

Perplexity Project Instructions are **captured and projected**. The normal
Space capture keeps the complete `get_collection` response in
`spaces/<uuid>/metadata.json` and now also writes immutable, hashed settings
snapshots. The native top-level `instructions` field projects to versioned
`project_instructions` scoped by the Space UUID. A focused read-only capture
on 2026-09-26 read 3/3 Projects with no errors; two nonempty instruction
documents were parsed. No owner sample is needed for this surface. Project
Memory and Project Brain remain separate from these instructions.

## Follow-ups — separate surfaces, grouped by evidence gate

These are **not unfinished six-platform-round work**. Project files,
instructions, native memories, Brain and history reuse are distinct objects.
An existing Project, chat or file can guide investigation but does not prove a
separate Project-memory record.

### Needs a materialized owner item or entitlement to establish a baseline

| Surface | Current boundary | Owner input that would unlock the next capture |
|---|---|---|
| [Perplexity](platforms/web/perplexity/state.md) Project Memory and Project Brain | A Project Memory subsection and Brain controls are visible, but no readable Memory contents or Brain record was observed. Account Memory capture does not cover either. | Open an existing populated Project state, or let a Brain appear through normal use; then inspect its read-only payload, IDs, dates, scope and pagination. Do not create one on the owner's behalf without approval. |
| [Perplexity](platforms/web/perplexity/state.md) account Brain | The observed account showed an entitlement gate, not an empty collection. | Revisit only if the owner has access and an inspectable Brain record. |
| [Kimi](platforms/web/kimi/state.md) Memory Instructions, Dream Memory, account instructions and Project context | Native raw reads preserve the observed empty Memory list, settings, Dream status and Project catalog/detail. Dream tree returned 404 while disabled; no non-empty item/value established a canonical projection. | An owner-created or naturally occurring non-empty item, enabled/available Dream tree, instruction value or populated Project context would establish the missing payload and lifecycle. A controlled sample requires explicit approval. Saved Prompts remain outside native memory. |

### Closed for this capture scope — no follow-up task

| Surface | Current boundary | Status |
|---|---|---|
| [Gemini](platforms/web/gemini/state.md) | Instructions collection is implemented and tested, including empty-state and removal preservation. The separate learned-Memory UI was explored; no user-readable items were available to capture. | **Closed.** No more probing, monitoring, sample creation or inference from model answers is part of this work. |
| [Grok](platforms/web/grok/state.md) | The bounded assessment found Project `customPersonality` context, not an account-global memory/instruction collection. | **Closed for current evidence.** No account-memory collection task is established. |

### Owner samples to bring later, one at a time

- **Perplexity:** an existing Project with a nonempty Project Memory item or
  Project Brain record; account Brain only if the entitlement is available.
- **Kimi:** a nonempty Memory Instruction, or a Project with an instruction or
  other populated context; Dream Memory only if it becomes enabled/available.
The Gemini and Grok memory follow-ups are closed; they are not monitoring
items. The ChatGPT Project-only sample gate is also closed; its two chats are
ordinary conversations and are not needed to map memory settings. If those
chats themselves need archival, they require normal conversation sync,
separate from this memory capture.

Qwen has no separately evidenced memory follow-up in this list. DeepSeek and
NotebookLM have no separate memory/instruction capture task until a concrete
owner-visible surface appears. Historical research and UI observations in the
private workbench are evidence, but earlier verdicts must be checked against
current code, raw data and platform states before reuse.

## Resume after a compacted session

Claude Project memory is closed for the current native Melange topics and the
preserved classic snapshots; do not recapture or reproject them to restart this
front. ChatGPT account and Project instructions are captured and projected;
the Project-only sample gate is closed. Its two test chats were not captured
and are not needed for memory coverage. Perplexity account Memory and Project
Instructions are captured and projected. The only evidence-gated memory
surfaces left here are Perplexity Project Memory/Brain or account Brain, and
nonempty Kimi Memory/Instructions/Project context or available Dream. Gemini
and Grok are closed for this scope; do not monitor or probe them.

For each newly demonstrated surface: preserve the full native read response and
its scope in cumulative raw history; distinguish complete from partial reads;
avoid false `preserved_missing`; validate identity, timestamps and lifecycle
before projecting into the canonical tables; then update its platform state,
known limitations and this list. Personal record content stays out of Git.
