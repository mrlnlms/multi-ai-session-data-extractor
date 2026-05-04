# Roadmap

Open work items. Closed via shipped releases are removed from this list
(see `git log` for history). For broader context, see
[README.md](../README.md) and [CLAUDE.md](../CLAUDE.md).

## Operational

### ChatGPT capture-delete cycle

The reconciler infrastructure (with `preserved_missing` flag for items
removed from the server) is in place and validated. Operational next
step: gradually delete old conversations on the server. The next
incremental capture (`--since last`) should surface deleted IDs as
`preserved_missing` while keeping the local raw intact. Replicable to
other platforms once their reconcilers are equally validated.

This is mostly a manual operational task — kept here as a reference
point when reviewing chat details and deciding what to remove from the
server. Automation is feasible (script that lists conversations older
than N days without recent updates and calls the delete endpoint) but
risky: a bug in the selection logic deletes the wrong conversations
server-side, and although the reconciler preserves the local copy, you
lose the ability to re-fetch updated versions from the server. Start
manual; consider automation only after confidence is high.
