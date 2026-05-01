"""Reconciler Qwen — pasta unica cumulativa em data/merged/Qwen/.

Padrao alinhado com ChatGPT, Claude.ai, Perplexity. Layout:

  data/merged/Qwen/
  ├── conversations/<uuid>.json   # 1 conv per file, com _last_seen_in_server
  ├── projects.json               # cumulativo + flags _preserved_missing
  ├── assets/                     # cumulativo (skip-existing)
  ├── discovery_ids.json          # cumulativo (current + preserved)
  ├── qwen_merged_summary.json    # estado consolidado
  ├── reconcile_log.jsonl         # historico append-only
  └── LAST_RECONCILE.md           # snapshot human-readable

Idempotente: rodar 2x produz mesmos bytes.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


FEATURES_VERSION = 2  # bumpado pra layout pasta unica
FEATURE_FLAGS = {"conversations", "projects"}
DROP_THRESHOLD = 0.5


@dataclass
class QwenPlan:
    to_use: list[str] = field(default_factory=list)
    to_copy: list[str] = field(default_factory=list)
    preserved_missing: list[str] = field(default_factory=list)


@dataclass
class QwenReconcileReport:
    added: int = 0
    updated: int = 0
    copied: int = 0
    preserved_missing: int = 0
    convs_total: int = 0
    projects_total: int = 0
    projects_preserved_missing: int = 0
    asset_binaries_total: int = 0
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Qwen: convs={self.added}+/{self.updated}~/"
            f"{self.copied}={self.preserved_missing}preserved "
            f"(total={self.convs_total}), "
            f"projects={self.projects_total} "
            f"({self.projects_preserved_missing} preserved), "
            f"assets={self.asset_binaries_total}bin"
        )


def _load_discovery(raw_dir: Path) -> dict[str, dict]:
    p = raw_dir / "discovery_ids.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data if isinstance(e, dict) and e.get("id")}


def _load_projects(raw_dir: Path) -> dict[str, dict]:
    p = raw_dir / "projects.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data if isinstance(e, dict) and e.get("id")}


def build_plan(
    current_raw: Path,
    previous_merged: Path | None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> QwenPlan:
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
    plan = QwenPlan()
    for uid in curr.keys():
        if force_all or uid not in prev:
            plan.to_use.append(uid)
            continue
        c_ut = curr[uid].get("updated_at") or 0
        p_ut = prev[uid].get("updated_at") or 0
        # Title rename detection
        title_changed = (curr[uid].get("title") or "") != (prev[uid].get("title") or "")
        if c_ut > p_ut or title_changed:
            plan.to_use.append(uid)
        else:
            plan.to_copy.append(uid)
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
) -> QwenReconcileReport:
    if previous_merged is None:
        previous_merged = merged_output if merged_output.exists() else None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)
    curr = _load_discovery(raw_dir)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    if prev and len(curr) / max(len(prev), 1) < DROP_THRESHOLD:
        return QwenReconcileReport(
            aborted=True,
            abort_reason=f"Queda drastica: prev={len(prev)} curr={len(curr)}",
        )

    today = datetime.now().strftime("%Y-%m-%d")
    reconciled_at = datetime.now().isoformat()
    report = QwenReconcileReport()

    merged_output.mkdir(parents=True, exist_ok=True)
    (merged_output / "conversations").mkdir(exist_ok=True)
    (merged_output / "assets").mkdir(exist_ok=True)

    # ============================================================
    # CONVERSATIONS
    # ============================================================
    # to_use: do raw + injeta _last_seen_in_server
    for uid in plan.to_use:
        src = raw_dir / "conversations" / f"{uid}.json"
        dst = merged_output / "conversations" / f"{uid}.json"
        if src.exists():
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            obj.pop("_preserved_missing", None)
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            report.warnings.append(f"to_use {uid}: missing in raw")

    # to_copy: do merged anterior, fallback pro raw atual (gap fix igual Claude.ai)
    for uid in plan.to_copy:
        dst = merged_output / "conversations" / f"{uid}.json"
        prev_src = (previous_merged / "conversations" / f"{uid}.json") if previous_merged else None
        raw_src = raw_dir / "conversations" / f"{uid}.json"

        src = prev_src if (prev_src and prev_src.exists()) else raw_src
        if not src.exists():
            report.warnings.append(f"to_copy {uid}: nem merged anterior nem raw tem arquivo")
            continue
        try:
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            obj.pop("_preserved_missing", None)
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            report.warnings.append(f"to_copy {uid}: erro lendo {src.name}: {e}")

    # preserved_missing: marca flag, NAO atualiza _last_seen
    for uid in plan.preserved_missing:
        if not previous_merged:
            continue
        src = previous_merged / "conversations" / f"{uid}.json"
        dst = merged_output / "conversations" / f"{uid}.json"
        if src.exists():
            try:
                obj = json.loads(src.read_text(encoding="utf-8"))
                obj["_preserved_missing"] = True
                dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                shutil.copy2(src, dst)

    # ============================================================
    # PROJECTS (com preservation)
    # ============================================================
    curr_projs = _load_projects(raw_dir)
    prev_projs = _load_projects(previous_merged) if previous_merged else {}
    projs_preserved = sorted(set(prev_projs.keys()) - set(curr_projs.keys()))

    cumulative_projects = list(curr_projs.values())
    for pid in projs_preserved:
        if pid in prev_projs:
            entry = dict(prev_projs[pid])
            entry["_preserved_missing"] = True
            cumulative_projects.append(entry)

    if cumulative_projects:
        (merged_output / "projects.json").write_text(
            json.dumps(cumulative_projects, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    report.projects_total = len(curr_projs)
    report.projects_preserved_missing = len(projs_preserved)

    # ============================================================
    # ASSETS (cumulativos, skip-existing) + manifest
    # ============================================================
    _merge_dir(raw_dir / "assets", merged_output / "assets")
    if previous_merged and previous_merged != merged_output:
        _merge_dir(previous_merged / "assets", merged_output / "assets")
    assets_dir = merged_output / "assets"
    if assets_dir.exists():
        report.asset_binaries_total = sum(1 for p in assets_dir.rglob("*") if p.is_file())

    # Manifest dos assets (gerado pelo download_assets) — copiar pro merged
    # pra parser conseguir resolver asset_paths via lookup.
    raw_manifest = raw_dir / "assets_manifest.json"
    if raw_manifest.exists():
        shutil.copy2(raw_manifest, merged_output / "assets_manifest.json")

    # ============================================================
    # DISCOVERY CUMULATIVO
    # ============================================================
    cumulative_disc = list(curr.values())
    for uid in plan.preserved_missing:
        if uid in prev:
            entry = dict(prev[uid])
            entry["_preserved_missing"] = True
            cumulative_disc.append(entry)
    (merged_output / "discovery_ids.json").write_text(
        json.dumps(cumulative_disc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ============================================================
    # STATS + LOGS
    # ============================================================
    new_ids = set(plan.to_use) - set(prev.keys())
    report.added = len(new_ids)
    report.updated = len(plan.to_use) - report.added
    report.copied = len(plan.to_copy)
    report.preserved_missing = len(plan.preserved_missing)
    report.convs_total = (
        report.added + report.updated + report.copied + report.preserved_missing
    )
    if force_refetch_features:
        report.features_refetched = sorted(force_refetch_features)

    summary = {
        "reconciled_at": reconciled_at,
        "features_version": FEATURES_VERSION,
        "convs": {
            "added": report.added,
            "updated": report.updated,
            "copied": report.copied,
            "preserved_missing": report.preserved_missing,
            "total": report.convs_total,
        },
        "projects": {
            "total": report.projects_total,
            "preserved_missing": report.projects_preserved_missing,
        },
        "asset_binaries_total": report.asset_binaries_total,
        "features_refetched": report.features_refetched,
    }
    (merged_output / "qwen_merged_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log_entry = {
        "reconciled_at": reconciled_at,
        "raw_source": str(raw_dir),
        "features_version": FEATURES_VERSION,
        "convs_total": report.convs_total,
        "convs_added": report.added,
        "convs_updated": report.updated,
        "convs_copied": report.copied,
        "convs_preserved_missing": report.preserved_missing,
        "projects_total": report.projects_total,
        "projects_preserved_missing": report.projects_preserved_missing,
        "asset_binaries_total": report.asset_binaries_total,
        "features_refetched": report.features_refetched,
        "warnings": report.warnings,
    }
    log_path = merged_output / "reconcile_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    _write_last_reconcile_md(merged_output, report, reconciled_at)

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


def _write_last_reconcile_md(
    output_dir: Path, report: QwenReconcileReport, reconciled_at: str
) -> None:
    md = (
        "# Last reconcile\n\n"
        f"- **Quando:** {reconciled_at}\n"
        f"- **Conversations:** {report.convs_total} totais "
        f"({report.added} added, {report.updated} updated, "
        f"{report.copied} copied, {report.preserved_missing} preserved)\n"
        f"- **Projects:** {report.projects_total} ativos "
        f"({report.projects_preserved_missing} preserved)\n"
        f"- **Asset binarios:** {report.asset_binaries_total} (cumulativo)\n"
        f"- **Warnings:** {len(report.warnings)}\n\n"
        "Ver `reconcile_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_RECONCILE.md").write_text(md, encoding="utf-8")
