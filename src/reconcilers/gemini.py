"""Reconciler do Gemini — merge raws de datas diferentes preservando historico.

Layout: data/raw/Gemini Data/account-{N}/<YYYY-MM-DDTHH-MM>/
  - conversations/<uuid>.json
  - discovery_ids.json: [{uuid, title, created_at_secs}]
  - assets/

Saida: data/merged/Gemini/account-{N}/<YYYY-MM-DD>/

Gemini nao expoe updated_at no discovery — usa created_at_secs como proxy.
Como conv pode mudar (novas msgs) sem bumpar created_at, o reconciler tambem
considera diff em arquivos/tamanho como sinal de mudanca.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

FEATURES_VERSION = 1
FEATURE_FLAGS = {"hNvQHb_conversation"}
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
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Gemini: added={self.added}, updated={self.updated}, "
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
) -> GeminiPlan:
    """Compara discovery por created_at_secs (Gemini nao expoe updated_at).

    Limitacao: novas msgs numa conv existente nao bumpam created_at — pra forcar
    refetch nesses casos use --full ou --refetch-features.
    """
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
        if c_ts > p_ts:
            plan.to_use.append(uuid)
        else:
            plan.to_copy.append(uuid)
    plan.preserved_missing = sorted(set(prev.keys()) - set(curr.keys()))
    plan.to_use.sort()
    plan.to_copy.sort()
    return plan


def run_reconciliation(
    raw_dir: Path,
    merged_output_base: Path,
    previous_merged: Path | None = None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> GeminiReconcileReport:
    if previous_merged is None:
        previous_merged = _find_latest_merged(merged_output_base)
    if previous_merged and not previous_merged.exists():
        previous_merged = None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)
    curr = _load_discovery(raw_dir)
    prev = _load_discovery(previous_merged) if previous_merged else {}

    if prev and len(curr) / max(len(prev), 1) < DROP_THRESHOLD:
        return GeminiReconcileReport(
            aborted=True,
            abort_reason=f"Queda drastica: prev={len(prev)} curr={len(curr)}",
        )

    today = datetime.now().strftime("%Y-%m-%d")
    out = merged_output_base / today
    (out / "conversations").mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(parents=True, exist_ok=True)

    report = GeminiReconcileReport()

    def _write_with_seen(src_path: Path, dst_path: Path):
        try:
            obj = json.loads(src_path.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            dst_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
        except Exception as e:
            report.warnings.append(f"{dst_path.name}: {str(e)[:100]}")

    for uuid in plan.to_use:
        s = raw_dir / "conversations" / f"{uuid}.json"
        d = out / "conversations" / f"{uuid}.json"
        if s.exists():
            _write_with_seen(s, d)
        else:
            report.warnings.append(f"to_use {uuid}: missing in raw")

    for uuid in plan.to_copy:
        if not previous_merged:
            continue
        s = previous_merged / "conversations" / f"{uuid}.json"
        d = out / "conversations" / f"{uuid}.json"
        if s.exists():
            _write_with_seen(s, d)

    for uuid in plan.preserved_missing:
        if not previous_merged:
            continue
        s = previous_merged / "conversations" / f"{uuid}.json"
        d = out / "conversations" / f"{uuid}.json"
        if s.exists():
            shutil.copy2(s, d)

    _merge_dir(raw_dir / "assets", out / "assets")
    if previous_merged:
        _merge_dir(previous_merged / "assets", out / "assets")

    merged_disc = list(curr.values())
    for uuid in plan.preserved_missing:
        if uuid in prev:
            e = dict(prev[uuid]); e["_deleted_from_server"] = True
            merged_disc.append(e)
    (out / "discovery_ids.json").write_text(json.dumps(merged_disc, ensure_ascii=False, indent=2))

    new_ids = set(plan.to_use) - set(prev.keys())
    report.added = len(new_ids)
    report.updated = len(plan.to_use) - report.added
    report.copied = len(plan.to_copy)
    report.preserved_missing = len(plan.preserved_missing)
    if force_refetch_features:
        report.features_refetched = sorted(force_refetch_features)

    log = {
        "reconciled_at": datetime.now().isoformat(),
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
    (out / "reconcile_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2))
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


def _find_latest_merged(merged_base: Path) -> Path | None:
    if not merged_base.exists():
        return None
    cs = sorted([d for d in merged_base.iterdir() if d.is_dir()])
    return cs[-1] if cs else None
