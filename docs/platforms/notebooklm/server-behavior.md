# NotebookLM — server behavior (empirically validated)

UI CRUD battery executed via mobile app + browser on 2026-05-02. Results
documented here (hard project rule: shipped only with validated CRUD).

## Validated CRUD battery (2026-05-02)

| Operation | Validation | Status |
|---|---|---|
| Rename | "Heatmap Studies" → "Heatmap estudos" (`b1b8da1f`) — title matches in parquet | ✅ |
| Delete | "Westward Mushrooms" (`0be7e3ec`) — `is_preserved_missing=True`, `last_seen_in_server=2026-05-02`, title preserved | ✅ |
| Pin/Star | **Feature not exposed in NotebookLM** (confirmed in mobile app) | ✅ N/A |
| Add source | 1 new PDF captured in existing notebook — sources acc-1 = 974 → 975 | ✅ |

## Discovered server behavior

### `update_time` is VOLATILE — not a proxy for "user touched it"

Empirical validation: 93/94 notebooks had `update_time` bumped between
2 consecutive syncs, even without the user modifying them.

**Cause:** server reindexes periodically (likely "last indexed", not
"last modified"). Accessing a notebook in the UI also bumps the timestamp.

**Implication:** `update_time` from the `wXbhsf` listing **cannot** be
used as a proxy for "user did something". Already documented in the
orchestrator.

**Mitigation (already implemented):**
- Reconciler uses **semantic content hash** (excluding timestamps) via
  `_eq_lenient` to decide to_use vs to_copy
- Lite-fetch compares 3 lightweight RPCs (rLM1Ne + cFji9 + gArtLc) to
  classify real changes

### Delete: preservation works

Notebook deleted on server:
- Drops out of current `discovery_ids.json`
- Reconciler marks `_preserved_missing=True` in merged
- Title + last_seen_in_server preserved
- Not re-fetched on subsequent runs (natural skip)

### Accessing a notebook bumps update_time

Confirmed by user: "it always moves up just by accessing it." Accessing
(even without editing) moves the notebook to the top of the list — the
server likely treats access as "interaction".

No impact on the extractor (mitigated by semantic hash).

### Pin/Star: does not exist in NotebookLM

Confirmed in the mobile app by user. NotebookLM has a minimalist UI — no
favorites/pinned. The only visual "ranking" is by descending update_time.

`is_pinned` in the canonical schema stays `None` for all NotebookLM
notebooks. Expected and correct.

## Conclusion

CRUD scenarios applicable to NotebookLM **all validated**. The only
"N/A" case is pin (nonexistent feature). Volatile update_time behavior
was already mitigated in the reconciler design.

**Status:** ✅ ready to ship.
