"""Reconciler do Claude.ai — merge entre raws de datas diferentes preservando historico.

Layout do raw:
  - conversations/<uuid>.json
  - projects/<uuid>.json
  - assets/<file_uuid>_<variant>.webp
  - assets/artifacts/<conv_uuid>/<artifact_id>_v<N>.<ext>
  - discovery_ids.json: {"conversations": [...], "projects": [...]}

Saida em data/merged/Claude_ai/<date>/ com mesma estrutura.

Padrao build_plan:
  - to_use: UUIDs do raw atual (novos ou updated_at > anterior)
  - to_copy: UUIDs inalterados — copia do merged anterior, nao toca API
  - preserved_missing: UUIDs no anterior mas nao no atual — deletados no servidor

Aplica separadamente a conversations e projects.

Feature flags pra refetch seletivo de rpcids novos. Bumpar FEATURES_VERSION
quando adicionamos fetches novos (notebookLM pattern).
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


FEATURES_VERSION = 1

FEATURE_FLAGS = {
    "conversations",
    "projects",
    "attachments_extracted_content",
    "project_docs_content",
}

DROP_THRESHOLD = 0.5


@dataclass
class ClaudePlan:
    convs_to_use: list[str] = field(default_factory=list)
    convs_to_copy: list[str] = field(default_factory=list)
    convs_preserved_missing: list[str] = field(default_factory=list)
    projects_to_use: list[str] = field(default_factory=list)
    projects_to_copy: list[str] = field(default_factory=list)
    projects_preserved_missing: list[str] = field(default_factory=list)


@dataclass
class ClaudeReconcileReport:
    convs_added: int = 0
    convs_updated: int = 0
    convs_copied: int = 0
    convs_preserved_missing: int = 0
    projects_added: int = 0
    projects_updated: int = 0
    projects_copied: int = 0
    projects_preserved_missing: int = 0
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Claude.ai:\n"
            f"  convs: added={self.convs_added}, updated={self.convs_updated}, "
            f"copied={self.convs_copied}, preserved_missing={self.convs_preserved_missing}\n"
            f"  projects: added={self.projects_added}, updated={self.projects_updated}, "
            f"copied={self.projects_copied}, preserved_missing={self.projects_preserved_missing}\n"
            f"  warnings={len(self.warnings)}"
        )


def _load_discovery(raw_dir: Path) -> dict:
    """Le discovery_ids.json. Retorna {'conversations': {uuid: meta}, 'projects': {uuid: meta}}."""
    path = raw_dir / "discovery_ids.json"
    if not path.exists():
        return {"conversations": {}, "projects": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    result = {"conversations": {}, "projects": {}}
    for kind in ("conversations", "projects"):
        for entry in data.get(kind, []):
            if isinstance(entry, dict) and entry.get("uuid"):
                result[kind][entry["uuid"]] = entry
    return result


def _decide(
    current: dict[str, dict],
    previous: dict[str, dict],
    force_all: bool = False,
) -> tuple[list, list, list]:
    """Decide to_use/to_copy/preserved pra um kind (convs ou projects).

    updated_at eh ISO string — ordenacao lexicografica funciona.
    """
    to_use, to_copy = [], []
    curr_ids = set(current.keys())
    prev_ids = set(previous.keys())

    for uuid in curr_ids:
        if force_all:
            to_use.append(uuid)
            continue
        if uuid not in prev_ids:
            to_use.append(uuid)
            continue
        curr_ut = current[uuid].get("updated_at") or ""
        prev_ut = previous[uuid].get("updated_at") or ""
        if curr_ut > prev_ut:
            to_use.append(uuid)
        else:
            to_copy.append(uuid)

    preserved_missing = sorted(prev_ids - curr_ids)
    return sorted(to_use), sorted(to_copy), preserved_missing


def build_plan(
    current_raw: Path,
    previous_merged: Path | None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> ClaudePlan:
    """Constroi plan pra convs + projects."""
    curr_disc = _load_discovery(current_raw)
    prev_disc = _load_discovery(previous_merged) if previous_merged else {"conversations": {}, "projects": {}}

    # Checa version bump
    version_bumped = False
    if previous_merged:
        log_path = previous_merged / "reconcile_log.json"
        if log_path.exists():
            try:
                prev_log = json.loads(log_path.read_text(encoding="utf-8"))
                prev_v = prev_log.get("features_version")
                if prev_v is not None and prev_v < FEATURES_VERSION:
                    version_bumped = True
            except Exception:
                pass

    force_all = full or version_bumped or bool(force_refetch_features)

    c_use, c_copy, c_miss = _decide(curr_disc["conversations"], prev_disc["conversations"], force_all)
    p_use, p_copy, p_miss = _decide(curr_disc["projects"], prev_disc["projects"], force_all)

    return ClaudePlan(
        convs_to_use=c_use,
        convs_to_copy=c_copy,
        convs_preserved_missing=c_miss,
        projects_to_use=p_use,
        projects_to_copy=p_copy,
        projects_preserved_missing=p_miss,
    )


def run_reconciliation(
    raw_dir: Path,
    merged_output_base: Path,
    previous_merged: Path | None = None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> ClaudeReconcileReport:
    """Executa reconciliacao.

    Args:
        raw_dir: raw atual (com conversations/, projects/, assets/, discovery_ids.json)
        merged_output_base: data/merged/Claude_ai/ (cria subdir datado)
        previous_merged: override; None = auto-detect mais recente
        force_refetch_features: forca refetch de features especificas
        full: True = ignora previous, to_use tudo
    """
    if previous_merged is None:
        previous_merged = _find_latest_merged(merged_output_base)
    if previous_merged and not previous_merged.exists():
        previous_merged = None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)

    curr_disc = _load_discovery(raw_dir)
    prev_disc = _load_discovery(previous_merged) if previous_merged else {"conversations": {}, "projects": {}}

    # Validacao: queda drastica de convs aborta
    prev_c = len(prev_disc["conversations"])
    curr_c = len(curr_disc["conversations"])
    if prev_c > 0:
        ratio = curr_c / prev_c
        if ratio < DROP_THRESHOLD:
            return ClaudeReconcileReport(
                aborted=True,
                abort_reason=(
                    f"Queda drastica convs: previous={prev_c}, current={curr_c} "
                    f"(ratio={ratio:.2f} < {DROP_THRESHOLD}). Investigue."
                ),
            )

    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = merged_output_base / today
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "conversations").mkdir(exist_ok=True)
    (output_dir / "projects").mkdir(exist_ok=True)
    (output_dir / "assets").mkdir(exist_ok=True)

    report = ClaudeReconcileReport()

    # Apply plan — convs
    _apply_kind(
        plan.convs_to_use, plan.convs_to_copy, plan.convs_preserved_missing,
        "conversations", raw_dir, previous_merged, output_dir, today, report,
    )
    report.convs_added = len(set(plan.convs_to_use) - set(prev_disc["conversations"].keys()))
    report.convs_updated = len(plan.convs_to_use) - report.convs_added
    report.convs_copied = len(plan.convs_to_copy)
    report.convs_preserved_missing = len(plan.convs_preserved_missing)

    _apply_kind(
        plan.projects_to_use, plan.projects_to_copy, plan.projects_preserved_missing,
        "projects", raw_dir, previous_merged, output_dir, today, report,
    )
    report.projects_added = len(set(plan.projects_to_use) - set(prev_disc["projects"].keys()))
    report.projects_updated = len(plan.projects_to_use) - report.projects_added
    report.projects_copied = len(plan.projects_to_copy)
    report.projects_preserved_missing = len(plan.projects_preserved_missing)

    # Merge assets (skip-existing)
    _merge_assets(raw_dir, previous_merged, output_dir)

    # Discovery merged: atual + preserved_missing marcados
    merged_disc = {
        "conversations": list(curr_disc["conversations"].values()),
        "projects": list(curr_disc["projects"].values()),
    }
    for uuid in plan.convs_preserved_missing:
        if uuid in prev_disc["conversations"]:
            entry = dict(prev_disc["conversations"][uuid])
            entry["_deleted_from_server"] = True
            merged_disc["conversations"].append(entry)
    for uuid in plan.projects_preserved_missing:
        if uuid in prev_disc["projects"]:
            entry = dict(prev_disc["projects"][uuid])
            entry["_deleted_from_server"] = True
            merged_disc["projects"].append(entry)
    (output_dir / "discovery_ids.json").write_text(
        json.dumps(merged_disc, ensure_ascii=False, indent=2)
    )

    if force_refetch_features:
        report.features_refetched = sorted(force_refetch_features)

    # reconcile_log
    log = {
        "reconciled_at": datetime.now().isoformat(),
        "raw_source": str(raw_dir),
        "previous_merged": str(previous_merged) if previous_merged else None,
        "features_version": FEATURES_VERSION,
        "convs": {
            "added": report.convs_added,
            "updated": report.convs_updated,
            "copied": report.convs_copied,
            "preserved_missing": report.convs_preserved_missing,
        },
        "projects": {
            "added": report.projects_added,
            "updated": report.projects_updated,
            "copied": report.projects_copied,
            "preserved_missing": report.projects_preserved_missing,
        },
        "features_refetched": report.features_refetched,
        "warnings": report.warnings,
    }
    (output_dir / "reconcile_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2)
    )

    return report


def _apply_kind(
    to_use: list[str],
    to_copy: list[str],
    preserved: list[str],
    kind: str,
    raw_dir: Path,
    previous_merged: Path | None,
    output_dir: Path,
    today: str,
    report: ClaudeReconcileReport,
) -> None:
    """Copia arquivos do kind (conversations ou projects) do raw/merged pra output."""
    # to_use: do raw atual + injeta _last_seen_in_server
    for uuid in to_use:
        src = raw_dir / kind / f"{uuid}.json"
        dst = output_dir / kind / f"{uuid}.json"
        if src.exists():
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
        else:
            report.warnings.append(f"to_use {kind}/{uuid}: arquivo faltando em raw")

    # to_copy: do merged anterior
    for uuid in to_copy:
        if not previous_merged:
            report.warnings.append(f"to_copy {kind}/{uuid} mas sem previous_merged")
            continue
        src = previous_merged / kind / f"{uuid}.json"
        dst = output_dir / kind / f"{uuid}.json"
        if src.exists():
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
        else:
            report.warnings.append(f"to_copy {kind}/{uuid}: merged anterior nao tem")

    # preserved_missing: do anterior sem atualizar _last_seen_in_server
    for uuid in preserved:
        if not previous_merged:
            continue
        src = previous_merged / kind / f"{uuid}.json"
        dst = output_dir / kind / f"{uuid}.json"
        if src.exists():
            shutil.copy2(src, dst)


def _merge_assets(raw_dir: Path, previous_merged: Path | None, output_dir: Path) -> None:
    """Copia assets de raw + anterior pro output (skip-existing)."""
    def _copy_tree(src: Path, dst: Path) -> None:
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

    _copy_tree(raw_dir / "assets", output_dir / "assets")
    if previous_merged:
        _copy_tree(previous_merged / "assets", output_dir / "assets")


def _find_latest_merged(merged_base: Path) -> Path | None:
    if not merged_base.exists():
        return None
    candidates = sorted([d for d in merged_base.iterdir() if d.is_dir()])
    return candidates[-1] if candidates else None
