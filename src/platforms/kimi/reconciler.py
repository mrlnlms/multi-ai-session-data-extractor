"""Reconciler Kimi — pasta unica cumulativa em data/merged/Kimi/.

Padrao alinhado com Qwen/Grok. Layout:

  data/merged/Kimi/
  ├── conversations/<uuid>.json   # 1 chat per file
  ├── skills.json                 # cumulativo + flags _preserved_missing
  ├── discovery_ids.json          # cumulativo (current + preserved)
  ├── kimi_merged_summary.json
  ├── reconcile_log.jsonl
  └── LAST_RECONCILE.md

Idempotente.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.assets.reader import AssetReader
from src.reconciliation.files import link_or_copy

logger = logging.getLogger(__name__)


def _safe_copy(src: Path, dst: Path) -> None:
    """Copia via shutil.copy2 se nao forem o mesmo arquivo fisico."""
    if src.exists() and dst.exists() and src.samefile(dst):
        return
    shutil.copy2(src, dst)


FEATURES_VERSION = 1
DROP_THRESHOLD = 0.5


def preserve_asset_tree(source_root: Path, destination_root: Path) -> None:
    """Preserve every asset file while retaining its nested relative path."""
    if not source_root.exists():
        return
    for source_file in sorted(source_root.rglob("*")):
        if not source_file.is_file():
            continue
        destination_file = destination_root / source_file.relative_to(source_root)
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        link_or_copy(source_file, destination_file)


@dataclass
class KimiPlan:
    to_use: list[str] = field(default_factory=list)
    to_copy: list[str] = field(default_factory=list)
    preserved_missing: list[str] = field(default_factory=list)


@dataclass
class KimiReconcileReport:
    added: int = 0
    updated: int = 0
    copied: int = 0
    preserved_missing: int = 0
    convs_total: int = 0
    skills_official: int = 0
    skills_installed: int = 0
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Kimi: convs={self.added}+/{self.updated}~/"
            f"{self.copied}={self.preserved_missing}preserved "
            f"(total={self.convs_total}), "
            f"skills={self.skills_official}o/{self.skills_installed}i"
        )


def _load_discovery(raw_dir: Path) -> dict[str, dict]:
    p = raw_dir / "discovery_ids.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data if isinstance(e, dict) and e.get("id")}


def _load_skills(raw_dir: Path) -> dict:
    p = raw_dir / "skills.json"
    if not p.exists():
        return {"official": [], "installed": []}
    return json.loads(p.read_text(encoding="utf-8"))


def build_plan(
    current_raw: Path,
    previous_merged: Path | None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> KimiPlan:
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
    plan = KimiPlan()
    for cid in curr.keys():
        if force_all or cid not in prev:
            plan.to_use.append(cid)
            continue
        c_ut = curr[cid].get("updateTime") or ""
        p_ut = prev[cid].get("updateTime") or ""
        name_changed = (curr[cid].get("name") or "") != (prev[cid].get("name") or "")
        if c_ut > p_ut or name_changed:
            plan.to_use.append(cid)
        else:
            plan.to_copy.append(cid)
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
    asset_reader: AssetReader | None = None,
    asset_account_id: str | None = None,
) -> KimiReconcileReport:
    if previous_merged is None:
        previous_merged = merged_output if merged_output.exists() else None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)
    curr = _load_discovery(raw_dir)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    if prev and len(curr) / max(len(prev), 1) < DROP_THRESHOLD:
        return KimiReconcileReport(
            aborted=True,
            abort_reason=f"Queda drastica: prev={len(prev)} curr={len(curr)}",
        )

    today = datetime.now().strftime("%Y-%m-%d")
    reconciled_at = datetime.now().isoformat()
    report = KimiReconcileReport()

    merged_output.mkdir(parents=True, exist_ok=True)
    (merged_output / "conversations").mkdir(exist_ok=True)

    for cid in plan.to_use:
        src = raw_dir / "conversations" / f"{cid}.json"
        dst = merged_output / "conversations" / f"{cid}.json"
        if src.exists():
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            obj.pop("_preserved_missing", None)
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            report.warnings.append(f"to_use {cid}: missing in raw")

    for cid in plan.to_copy:
        dst = merged_output / "conversations" / f"{cid}.json"
        prev_src = (previous_merged / "conversations" / f"{cid}.json") if previous_merged else None
        raw_src = raw_dir / "conversations" / f"{cid}.json"
        src = prev_src if (prev_src and prev_src.exists()) else raw_src
        if not src.exists():
            report.warnings.append(f"to_copy {cid}: nem merged anterior nem raw tem arquivo")
            continue
        try:
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            obj.pop("_preserved_missing", None)
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            report.warnings.append(f"to_copy {cid}: erro lendo {src.name}: {e}")

    for cid in plan.preserved_missing:
        if not previous_merged:
            continue
        src = previous_merged / "conversations" / f"{cid}.json"
        dst = merged_output / "conversations" / f"{cid}.json"
        if src.exists():
            try:
                obj = json.loads(src.read_text(encoding="utf-8"))
                obj["_preserved_missing"] = True
                dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                _safe_copy(src, dst)

    # Skills (sobrescreve do raw atual; pequeno e mutavel)
    skills = _load_skills(raw_dir)
    if skills.get("official") or skills.get("installed"):
        (merged_output / "skills.json").write_text(
            json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    report.skills_official = len(skills.get("official") or [])
    report.skills_installed = len(skills.get("installed") or [])

    # The vault is the authoritative reader, but the cumulative merged tree is
    # still preservation evidence and the manifest below points into it. Keep
    # copying new raw binaries in both reader modes; otherwise a refreshed
    # manifest can reference paths that exist only in raw.
    raw_assets = raw_dir / "assets"
    merged_assets = merged_output / "assets"
    preserve_asset_tree(raw_assets, merged_assets)
    if previous_merged and previous_merged != merged_output:
        preserve_asset_tree(previous_merged / "assets", merged_assets)
    if asset_reader is not None:
        asset_reader.projection_for("kimi", asset_account_id)

    raw_manifest = raw_dir / "assets_manifest.json"
    if raw_manifest.exists():
        _safe_copy(raw_manifest, merged_output / "assets_manifest.json")

    # Discovery cumulativo
    cumulative_disc = list(curr.values())
    for cid in plan.preserved_missing:
        if cid in prev:
            entry = dict(prev[cid])
            entry["_preserved_missing"] = True
            cumulative_disc.append(entry)
    (merged_output / "discovery_ids.json").write_text(
        json.dumps(cumulative_disc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

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
        "skills": {
            "official": report.skills_official,
            "installed": report.skills_installed,
        },
        "features_refetched": report.features_refetched,
    }
    (merged_output / "kimi_merged_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
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
        "skills_official": report.skills_official,
        "skills_installed": report.skills_installed,
        "features_refetched": report.features_refetched,
        "warnings": report.warnings,
    }
    log_path = merged_output / "reconcile_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    _write_last_reconcile_md(merged_output, report, reconciled_at)
    return report


def _write_last_reconcile_md(
    output_dir: Path, report: KimiReconcileReport, reconciled_at: str
) -> None:
    md = (
        "# Last reconcile\n\n"
        f"- **Quando:** {reconciled_at}\n"
        f"- **Conversations:** {report.convs_total} totais "
        f"({report.added} added, {report.updated} updated, "
        f"{report.copied} copied, {report.preserved_missing} preserved)\n"
        f"- **Skills:** {report.skills_official} oficiais, "
        f"{report.skills_installed} instaladas\n"
        f"- **Warnings:** {len(report.warnings)}\n\n"
        "Ver `reconcile_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_RECONCILE.md").write_text(md, encoding="utf-8")
