"""Reconciler do Perplexity.

Layout: data/raw/Perplexity Data/<YYYY-MM-DDTHH-MM>/
  - threads/<uuid>.json
  - threads-index.json (cópia do discovery_ids — usar discovery)
  - discovery_ids.json: [{uuid, slug, title, last_query_datetime (ISO), mode, query_count}]
  - assets/

Saida: data/merged/Perplexity/<YYYY-MM-DD>/

Schema usa 'threads' em vez de 'conversations'.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

FEATURES_VERSION = 1
FEATURE_FLAGS = {"threads"}
DROP_THRESHOLD = 0.5


@dataclass
class PerplexityPlan:
    to_use: list[str] = field(default_factory=list)
    to_copy: list[str] = field(default_factory=list)
    preserved_missing: list[str] = field(default_factory=list)


@dataclass
class PerplexityReconcileReport:
    added: int = 0
    updated: int = 0
    copied: int = 0
    preserved_missing: int = 0
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Perplexity: added={self.added}, updated={self.updated}, "
            f"copied={self.copied}, preserved_missing={self.preserved_missing}, "
            f"warnings={len(self.warnings)}"
        )


def _load_discovery(raw_dir: Path) -> dict[str, dict]:
    p = raw_dir / "discovery_ids.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {e["uuid"]: e for e in data if isinstance(e, dict) and e.get("uuid")}


def build_plan(
    current_raw: Path,
    previous_merged: Path | None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> PerplexityPlan:
    curr = _load_discovery(current_raw)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    version_bumped = False
    if previous_merged:
        log = previous_merged / "reconcile_log.json"
        if log.exists():
            try:
                d = json.loads(log.read_text(encoding="utf-8"))
                if d.get("features_version", FEATURES_VERSION) < FEATURES_VERSION:
                    version_bumped = True
            except Exception: pass

    force_all = full or version_bumped or bool(force_refetch_features)
    plan = PerplexityPlan()
    for uid in curr.keys():
        if force_all or uid not in prev:
            plan.to_use.append(uid); continue
        # last_query_datetime é ISO string — comparação lexicográfica funciona
        c_dt = curr[uid].get("last_query_datetime") or ""
        p_dt = prev[uid].get("last_query_datetime") or ""
        c_qc = curr[uid].get("query_count") or 0
        p_qc = prev[uid].get("query_count") or 0
        if c_dt > p_dt or c_qc > p_qc:
            plan.to_use.append(uid)
        else:
            plan.to_copy.append(uid)
    plan.preserved_missing = sorted(set(prev.keys()) - set(curr.keys()))
    plan.to_use.sort(); plan.to_copy.sort()
    return plan


def run_reconciliation(
    raw_dir: Path,
    merged_output_base: Path,
    previous_merged: Path | None = None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> PerplexityReconcileReport:
    if previous_merged is None:
        previous_merged = _find_latest_merged(merged_output_base)
    if previous_merged and not previous_merged.exists():
        previous_merged = None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)
    curr = _load_discovery(raw_dir)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    if prev and len(curr) / max(len(prev), 1) < DROP_THRESHOLD:
        return PerplexityReconcileReport(aborted=True,
            abort_reason=f"Queda drastica: prev={len(prev)} curr={len(curr)}")

    today = datetime.now().strftime("%Y-%m-%d")
    out = merged_output_base / today
    (out / "threads").mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    report = PerplexityReconcileReport()

    def _write_seen(src: Path, dst: Path):
        try:
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
        except Exception as e:
            report.warnings.append(f"{dst.name}: {str(e)[:100]}")

    for uid in plan.to_use:
        s = raw_dir / "threads" / f"{uid}.json"
        d = out / "threads" / f"{uid}.json"
        if s.exists(): _write_seen(s, d)
        else: report.warnings.append(f"to_use {uid}: missing in raw")
    for uid in plan.to_copy:
        if not previous_merged: continue
        s = previous_merged / "threads" / f"{uid}.json"
        d = out / "threads" / f"{uid}.json"
        if s.exists(): _write_seen(s, d)
    for uid in plan.preserved_missing:
        if not previous_merged: continue
        s = previous_merged / "threads" / f"{uid}.json"
        d = out / "threads" / f"{uid}.json"
        if s.exists(): shutil.copy2(s, d)

    _merge_dir(raw_dir / "assets", out / "assets")
    if previous_merged:
        _merge_dir(previous_merged / "assets", out / "assets")

    merged_disc = list(curr.values())
    for uid in plan.preserved_missing:
        if uid in prev:
            e = dict(prev[uid]); e["_deleted_from_server"] = True
            merged_disc.append(e)
    (out / "discovery_ids.json").write_text(json.dumps(merged_disc, ensure_ascii=False, indent=2))

    new_ids = set(plan.to_use) - set(prev.keys())
    report.added = len(new_ids)
    report.updated = len(plan.to_use) - report.added
    report.copied = len(plan.to_copy)
    report.preserved_missing = len(plan.preserved_missing)
    if force_refetch_features:
        report.features_refetched = sorted(force_refetch_features)

    (out / "reconcile_log.json").write_text(json.dumps({
        "reconciled_at": datetime.now().isoformat(),
        "raw_source": str(raw_dir),
        "previous_merged": str(previous_merged) if previous_merged else None,
        "features_version": FEATURES_VERSION,
        "added": report.added, "updated": report.updated,
        "copied": report.copied, "preserved_missing": report.preserved_missing,
        "features_refetched": report.features_refetched,
        "warnings": report.warnings,
    }, ensure_ascii=False, indent=2))
    return report


def _merge_dir(src: Path, dst: Path) -> None:
    if not src.exists(): return
    for item in src.rglob("*"):
        if not item.is_file(): continue
        rel = item.relative_to(src)
        tgt = dst / rel
        if tgt.exists(): continue
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, tgt)


def _find_latest_merged(merged_base: Path) -> Path | None:
    if not merged_base.exists(): return None
    cs = sorted([d for d in merged_base.iterdir() if d.is_dir()])
    return cs[-1] if cs else None
