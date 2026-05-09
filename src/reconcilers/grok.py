"""Reconciler Grok — pasta unica cumulativa em data/merged/Grok/.

Padrao alinhado com Qwen/DeepSeek/Claude.ai. Layout:

  data/merged/Grok/
  ├── conversations/<uuid>.json   # 1 conv per file, com _last_seen_in_server
  ├── workspaces.json             # cumulativo + flags _preserved_missing
  ├── discovery_ids.json          # cumulativo (current + preserved)
  ├── grok_merged_summary.json    # estado consolidado
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


FEATURES_VERSION = 1
DROP_THRESHOLD = 0.5


@dataclass
class GrokPlan:
    to_use: list[str] = field(default_factory=list)
    to_copy: list[str] = field(default_factory=list)
    preserved_missing: list[str] = field(default_factory=list)


@dataclass
class GrokReconcileReport:
    added: int = 0
    updated: int = 0
    copied: int = 0
    preserved_missing: int = 0
    convs_total: int = 0
    workspaces_total: int = 0
    workspaces_preserved_missing: int = 0
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Grok: convs={self.added}+/{self.updated}~/"
            f"{self.copied}={self.preserved_missing}preserved "
            f"(total={self.convs_total}), "
            f"workspaces={self.workspaces_total} "
            f"({self.workspaces_preserved_missing} preserved)"
        )


def _load_discovery(raw_dir: Path) -> dict[str, dict]:
    p = raw_dir / "discovery_ids.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {
        e["conversationId"]: e
        for e in data
        if isinstance(e, dict) and e.get("conversationId")
    }


def _load_workspaces(raw_dir: Path) -> dict[str, dict]:
    p = raw_dir / "workspaces.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {
        e["workspaceId"]: e
        for e in data
        if isinstance(e, dict) and e.get("workspaceId")
    }


def build_plan(
    current_raw: Path,
    previous_merged: Path | None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> GrokPlan:
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
    plan = GrokPlan()
    for cid in curr.keys():
        if force_all or cid not in prev:
            plan.to_use.append(cid)
            continue
        c_ut = curr[cid].get("modifyTime") or ""
        p_ut = prev[cid].get("modifyTime") or ""
        title_changed = (curr[cid].get("title") or "") != (prev[cid].get("title") or "")
        if c_ut > p_ut or title_changed:
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
) -> GrokReconcileReport:
    if previous_merged is None:
        previous_merged = merged_output if merged_output.exists() else None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)
    curr = _load_discovery(raw_dir)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    if prev and len(curr) / max(len(prev), 1) < DROP_THRESHOLD:
        return GrokReconcileReport(
            aborted=True,
            abort_reason=f"Queda drastica: prev={len(prev)} curr={len(curr)}",
        )

    today = datetime.now().strftime("%Y-%m-%d")
    reconciled_at = datetime.now().isoformat()
    report = GrokReconcileReport()

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
                shutil.copy2(src, dst)

    curr_ws = _load_workspaces(raw_dir)
    prev_ws = _load_workspaces(previous_merged) if previous_merged else {}
    ws_preserved = sorted(set(prev_ws.keys()) - set(curr_ws.keys()))

    cumulative_workspaces = list(curr_ws.values())
    for wid in ws_preserved:
        if wid in prev_ws:
            entry = dict(prev_ws[wid])
            entry["_preserved_missing"] = True
            cumulative_workspaces.append(entry)

    if cumulative_workspaces:
        (merged_output / "workspaces.json").write_text(
            json.dumps(cumulative_workspaces, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    report.workspaces_total = len(curr_ws)
    report.workspaces_preserved_missing = len(ws_preserved)

    cumulative_disc = list(curr.values())
    for cid in plan.preserved_missing:
        if cid in prev:
            entry = dict(prev[cid])
            entry["_preserved_missing"] = True
            cumulative_disc.append(entry)
    (merged_output / "discovery_ids.json").write_text(
        json.dumps(cumulative_disc, ensure_ascii=False, indent=2),
        encoding="utf-8",
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
        "workspaces": {
            "total": report.workspaces_total,
            "preserved_missing": report.workspaces_preserved_missing,
        },
        "features_refetched": report.features_refetched,
    }
    (merged_output / "grok_merged_summary.json").write_text(
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
        "workspaces_total": report.workspaces_total,
        "workspaces_preserved_missing": report.workspaces_preserved_missing,
        "features_refetched": report.features_refetched,
        "warnings": report.warnings,
    }
    log_path = merged_output / "reconcile_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    _write_last_reconcile_md(merged_output, report, reconciled_at)

    return report


def _write_last_reconcile_md(
    output_dir: Path, report: GrokReconcileReport, reconciled_at: str
) -> None:
    md = (
        "# Last reconcile\n\n"
        f"- **Quando:** {reconciled_at}\n"
        f"- **Conversations:** {report.convs_total} totais "
        f"({report.added} added, {report.updated} updated, "
        f"{report.copied} copied, {report.preserved_missing} preserved)\n"
        f"- **Workspaces:** {report.workspaces_total} ativos "
        f"({report.workspaces_preserved_missing} preserved)\n"
        f"- **Warnings:** {len(report.warnings)}\n\n"
        "Ver `reconcile_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_RECONCILE.md").write_text(md, encoding="utf-8")
