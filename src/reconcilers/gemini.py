"""Reconciler Gemini — pasta unica cumulativa per-account.

Layout:
    data/raw/Gemini/account-{N}/        (input)
        conversations/<uuid>.json
        discovery_ids.json
        capture_log.jsonl

    data/merged/Gemini/account-{N}/     (output)
        conversations/<uuid>.json       (cumulativo)
        assets/                         (cumulativo)
        discovery_ids.json              (com _deleted_from_server flag)
        gemini_merged_summary.json
        LAST_RECONCILE.md
        reconcile_log.jsonl

Multi-conta: reconciler cobre 1 conta por chamada. Sync orchestrator
(`scripts/gemini-sync.py`) itera ambas e gera summary agregado.

Limitacao: Gemini nao expoe updated_at (so created_at_secs). Novas msgs
numa conv existente NAO bumpam created_at — pra forcar refetch nesses
casos use --full.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

FEATURES_VERSION = 2  # bumpado pra layout pasta unica
DROP_THRESHOLD = 0.5


@dataclass
class GeminiPlan:
    to_use: list[str] = field(default_factory=list)
    to_copy: list[str] = field(default_factory=list)
    preserved_missing: list[str] = field(default_factory=list)


@dataclass
class GeminiReconcileReport:
    added: int = 0
    updated: int = 0
    copied: int = 0
    preserved_missing: int = 0
    asset_binaries_total: int = 0
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Gemini: convs={self.added}+/{self.updated}~/"
            f"{self.copied}={self.preserved_missing}preserved "
            f"(total={self.added + self.updated + self.copied + self.preserved_missing}), "
            f"assets={self.asset_binaries_total}bin"
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
) -> GeminiPlan:
    curr = _load_discovery(current_raw)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    version_bumped = False
    if previous_merged:
        log_path = previous_merged / "reconcile_log.jsonl"
        if log_path.exists():
            try:
                with open(log_path, encoding="utf-8") as f:
                    last_line = None
                    for line in f:
                        if line.strip():
                            last_line = line
                if last_line:
                    prev_log = json.loads(last_line)
                    prev_v = prev_log.get("features_version")
                    if prev_v is not None and prev_v < FEATURES_VERSION:
                        version_bumped = True
            except Exception:
                pass

    force_all = full or version_bumped or bool(force_refetch_features)
    plan = GeminiPlan()
    for uuid in curr.keys():
        if force_all or uuid not in prev:
            plan.to_use.append(uuid)
            continue
        c_ts = curr[uuid].get("created_at_secs") or 0
        p_ts = prev[uuid].get("created_at_secs") or 0
        title_changed = (curr[uuid].get("title") or "") != (prev[uuid].get("title") or "")
        pinned_changed = bool(curr[uuid].get("pinned")) != bool(prev[uuid].get("pinned"))
        if c_ts > p_ts or title_changed or pinned_changed:
            plan.to_use.append(uuid)
        else:
            plan.to_copy.append(uuid)
    plan.preserved_missing = sorted(set(prev.keys()) - set(curr.keys()))
    plan.to_use.sort()
    plan.to_copy.sort()
    return plan


def run_reconciliation(
    raw_dir: Path,
    merged_output: Path,
    previous_merged: Path | None = None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> GeminiReconcileReport:
    if previous_merged is None:
        previous_merged = merged_output if merged_output.exists() else None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)
    curr = _load_discovery(raw_dir)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    if prev and len(curr) / max(len(prev), 1) < DROP_THRESHOLD:
        return GeminiReconcileReport(
            aborted=True,
            abort_reason=f"Queda drastica: prev={len(prev)} curr={len(curr)}",
        )

    today = datetime.now().strftime("%Y-%m-%d")
    reconciled_at = datetime.now().isoformat()
    report = GeminiReconcileReport()

    merged_output.mkdir(parents=True, exist_ok=True)
    (merged_output / "conversations").mkdir(exist_ok=True)
    (merged_output / "assets").mkdir(exist_ok=True)

    # ============================================================
    # CONVERSATIONS
    # ============================================================
    for uuid in plan.to_use:
        src = raw_dir / "conversations" / f"{uuid}.json"
        dst = merged_output / "conversations" / f"{uuid}.json"
        if src.exists():
            try:
                obj = json.loads(src.read_text(encoding="utf-8"))
                obj["_last_seen_in_server"] = today
                obj.pop("_preserved_missing", None)
                dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                report.warnings.append(f"to_use {uuid}: {str(e)[:100]}")
        else:
            report.warnings.append(f"to_use {uuid}: missing in raw")

    # to_copy: do merged anterior (mantem _last_seen antigo), fallback pro raw
    for uuid in plan.to_copy:
        dst = merged_output / "conversations" / f"{uuid}.json"
        prev_src = (previous_merged / "conversations" / f"{uuid}.json") if previous_merged else None
        raw_src = raw_dir / "conversations" / f"{uuid}.json"
        src = prev_src if (prev_src and prev_src.exists()) else raw_src
        if not src.exists():
            report.warnings.append(f"to_copy {uuid}: nem merged anterior nem raw tem arquivo")
            continue
        try:
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            obj.pop("_preserved_missing", None)
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            report.warnings.append(f"to_copy {uuid}: erro {str(e)[:100]}")

    # preserved_missing: marca flag, NAO atualiza _last_seen
    for uuid in plan.preserved_missing:
        if not previous_merged:
            continue
        src = previous_merged / "conversations" / f"{uuid}.json"
        dst = merged_output / "conversations" / f"{uuid}.json"
        if src.exists():
            try:
                obj = json.loads(src.read_text(encoding="utf-8"))
                obj["_preserved_missing"] = True
                dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                shutil.copy2(src, dst)

    # ============================================================
    # ASSETS (cumulativos)
    # ============================================================
    _merge_dir(raw_dir / "assets", merged_output / "assets")
    if previous_merged:
        _merge_dir(previous_merged / "assets", merged_output / "assets")

    # ============================================================
    # DISCOVERY merged (com _deleted_from_server)
    # ============================================================
    merged_disc = list(curr.values())
    for uuid in plan.preserved_missing:
        if uuid in prev:
            entry = dict(prev[uuid])
            entry["_deleted_from_server"] = True
            merged_disc.append(entry)
    (merged_output / "discovery_ids.json").write_text(
        json.dumps(merged_disc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ============================================================
    # COUNTERS + LOGS
    # ============================================================
    new_ids = set(plan.to_use) - set(prev.keys())
    report.added = len(new_ids)
    report.updated = len(plan.to_use) - report.added
    report.copied = len(plan.to_copy)
    report.preserved_missing = len(plan.preserved_missing)
    if force_refetch_features:
        report.features_refetched = sorted(force_refetch_features)

    asset_dir = merged_output / "assets"
    if asset_dir.exists():
        report.asset_binaries_total = sum(1 for _ in asset_dir.rglob("*") if _.is_file())

    # gemini_merged_summary.json
    summary = {
        "reconciled_at": reconciled_at,
        "features_version": FEATURES_VERSION,
        "convs": {
            "added": report.added,
            "updated": report.updated,
            "copied": report.copied,
            "preserved_missing": report.preserved_missing,
            "total": report.added + report.updated + report.copied + report.preserved_missing,
        },
        "asset_binaries_total": report.asset_binaries_total,
        "features_refetched": report.features_refetched,
    }
    (merged_output / "gemini_merged_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # reconcile_log.jsonl (append)
    log_entry = {
        "reconciled_at": reconciled_at,
        "raw_source": str(raw_dir),
        "previous_merged": str(previous_merged) if previous_merged else None,
        "features_version": FEATURES_VERSION,
        "added": report.added,
        "updated": report.updated,
        "copied": report.copied,
        "preserved_missing": report.preserved_missing,
        "features_refetched": report.features_refetched,
        "warnings": report.warnings,
    }
    with open(merged_output / "reconcile_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # LAST_RECONCILE.md
    _write_last_reconcile_md(merged_output, summary)

    print(report.summary())
    return report


def _merge_dir(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        tgt = dst / rel
        if tgt.exists():
            continue
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, tgt)


def _write_last_reconcile_md(merged_output: Path, summary: dict) -> None:
    convs = summary["convs"]
    md = (
        "# Last reconcile\n\n"
        f"- **Quando:** {summary['reconciled_at']}\n"
        f"- **Features version:** {summary['features_version']}\n"
        f"- **Conversations:** "
        f"{convs['added']} added, {convs['updated']} updated, "
        f"{convs['copied']} copied, {convs['preserved_missing']} preserved_missing "
        f"(total={convs['total']})\n"
        f"- **Assets binaries:** {summary['asset_binaries_total']}\n\n"
        "Ver `reconcile_log.jsonl` pro historico completo.\n"
    )
    (merged_output / "LAST_RECONCILE.md").write_text(md, encoding="utf-8")
