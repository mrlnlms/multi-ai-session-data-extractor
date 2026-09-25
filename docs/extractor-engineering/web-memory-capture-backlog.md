# Web memory and context: pending capture

This is the single entry point for **known, unfinished capture work** in the
web memory/configuration front. It is not a list of features to infer from
conversation text. The per-platform `state.md` remains the source for observed
UI, transport and implementation detail; the [memory architecture](../product/agent-memory-architecture.md)
defines the canonical projection.

Last checked against the maintained platform states on 2026-09-25. The
ChatGPT account surfaces, Claude.ai account **and Project** Melange topics,
and Perplexity account Memory are already captured and projected. Project
files, instructions, native memories, Brain and history reuse are distinct
objects even if a product uses them together.

| Source and surface | What is known / why it is still open | Next evidence and action |
|---|---|---|
| [ChatGPT](platforms/web/chatgpt/state.md): Project-specific memory or instructions | Account saved memories, summary and instructions are covered; Project knowledge files are assets. No separate Project memory/instruction record has been mapped into the memory domain. | Inspect the authenticated Project UI and its read-only payloads, including whether a Project-only memory is an independently inspectable item. Preserve any demonstrated scope separately; do not infer it from account entries, project files or chats. |
| [Claude.ai](platforms/web/claude-ai/state.md): legacy Project-memory migration | Current account and Project Melange topics are covered. The UI offered a time-limited export of older Project memory, while dated external snapshots have unproven account identity. | If an owner export/payload is available, preserve it as historical evidence and map identity/scope only when demonstrable. Never replace current Melange records or attribute snapshots to a catalog account by guesswork. |
| [Perplexity](platforms/web/perplexity/state.md): Project Memory | A distinct Settings subsection is visible, but its contents and native payload have not been observed. The account-Memory GraphQL adapter does not cover it. | Open a Project with a readable Memory state; inspect the read-only request, IDs, scope, dates, pagination and empty-state semantics before implementing capture. |
| [Perplexity](platforms/web/perplexity/state.md): Project Brain and Project Instructions | Brain creation controls were visible but no Brain record existed in the observed Project. Instructions are explicitly Project-scoped; their native read payload has not been mapped. | Observe an owner-created Brain after natural use and the Project-settings read payload. Preserve Brain, instructions and Files/Links as separate Project objects; do not label them account Memory. |
| [Perplexity](platforms/web/perplexity/state.md): account Brain | The observed account showed an entitlement gate, not an empty Brain collection. | Revisit only if the owner has access and an inspectable Brain record exists. Do not treat a paywall as a failed capture. |
| [Qwen](platforms/web/qwen/state.md): account Memory and Customize Qwen | Memory Manage and related controls are visible, but no individual record payload has been captured. The scope of Customize Qwen is unresolved; existing Project instructions and `memory_span` are Project context. | Inspect Manage and Customize Qwen read-only, establish native identities, scope and lifecycle, then add cumulative raw capture and projection only for demonstrated records. |
| [Kimi](platforms/web/kimi/state.md): non-empty Memory Instructions, Dream Memory, account instructions and populated Project context | Native raw history now covers the verified empty Memory Instructions list, account settings read, Dream status and Project catalog/detail. The Dream tree returned 404 on the disabled account; the empty account settings/project detail did not establish instruction-value fields or item lifecycle. No canonical projection is claimed. | Observe a non-empty native memory item, instruction value or populated Project context when naturally available (or with an explicitly approved controlled sample). Establish IDs, timestamps, pagination and semantics before projection; keep Saved Prompts outside native memory and Project files distinct. |
| [Gemini](platforms/web/gemini/state.md): Instructions projection and conversation-derived Memory | Account-global Instructions already have cumulative native raw capture, but no canonical projection yet. The enabled learned-Memory control did not expose a readable item list or stable native envelope in the bounded probe. | Compare equivalent account-global instruction surfaces before defining their shared projection. Reopen learned-Memory capture only if an inspectable native record/payload becomes available; do not reconstruct it from answers. |
| [Grok](platforms/web/grok/state.md): account-level personalization/instructions | Workspace `customPersonality` is Project context. No separate account-global memory/instruction record has been established in the maintained capture. | First establish a concrete owner-visible surface and authenticated read payload. Keep workspace settings out of account memory. |

NotebookLM notebook objects and the DeepSeek account screens observed so far do
not establish a separate memory/instruction collection; they are not capture
tasks on this list. Other historical research and UI observations live in the
private workbench, but its earlier verdicts must be checked against current
code, raw data and platform states before reuse.

For each newly demonstrated surface: preserve the full native read response and
its scope in cumulative raw history; distinguish complete from partial reads;
avoid false `preserved_missing`; validate identity, timestamps and lifecycle
before projecting into the canonical tables; then update its platform state,
known limitations and this list. Personal record content stays out of Git.
