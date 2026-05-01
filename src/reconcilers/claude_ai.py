"""Reconciler Claude.ai — pasta unica cumulativa em data/merged/Claude.ai/.

Padrao alinhado com ChatGPT e Perplexity (sem subpastas datadas). Layout:

  data/merged/Claude.ai/
  ├── conversations/<uuid>.json         # 1 conv per file, com _last_seen_in_server
  ├── projects/<uuid>.json              # 1 project per file
  ├── assets/                           # cumulativo (binarios + artifacts extraidos)
  │   ├── {file_uuid}_preview.webp
  │   └── artifacts/<conv_uuid>/...
  ├── discovery_ids.json                # cumulativo (current + preserved)
  ├── claude_ai_merged_summary.json     # estado consolidado (counts)
  ├── reconcile_log.jsonl               # historico append-only
  └── LAST_RECONCILE.md                 # snapshot human-readable

Logica:

1. Conversations:
   - updated_at bumpou ou nova → to_use (do raw)
   - inalterada → to_copy (do merged anterior, atualiza _last_seen_in_server)
   - sumiu da discovery → preserved_missing (mantem arquivo, marca flag)

2. Projects: mesma logica.

3. Assets binarios: cumulativos (skip-existing). Garantia 'capturar uma vez,
   nunca rebaixar'.

4. Idempotente: rodar 2x produz mesmos bytes.
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

FEATURE_FLAGS = {
    "conversations",
    "projects",
    "attachments_extracted_content",
    "project_docs_content",
}

DROP_THRESHOLD = 0.5  # current/previous < 0.5 aborta


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
    convs_total: int = 0
    projects_added: int = 0
    projects_updated: int = 0
    projects_copied: int = 0
    projects_preserved_missing: int = 0
    projects_total: int = 0
    asset_binaries_total: int = 0
    artifacts_total: int = 0
    features_refetched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Claude.ai: "
            f"convs={self.convs_added}+/{self.convs_updated}~/"
            f"{self.convs_copied}={self.convs_preserved_missing}preserved "
            f"(total={self.convs_total}), "
            f"projects={self.projects_added}+/{self.projects_updated}~/"
            f"{self.projects_copied}={self.projects_preserved_missing}preserved "
            f"(total={self.projects_total}), "
            f"assets={self.asset_binaries_total}bin / artifacts={self.artifacts_total}"
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
        # Title rename detection: discovery title diferente do que tinhamos
        title_changed = (current[uuid].get("name") or "") != (previous[uuid].get("name") or "")
        if curr_ut > prev_ut or title_changed:
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
    prev_disc = (
        _load_discovery(previous_merged) if previous_merged
        else {"conversations": {}, "projects": {}}
    )

    # Version bump force-all (espelho ChatGPT)
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

    c_use, c_copy, c_miss = _decide(
        curr_disc["conversations"], prev_disc["conversations"], force_all
    )
    p_use, p_copy, p_miss = _decide(
        curr_disc["projects"], prev_disc["projects"], force_all
    )

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
    merged_output: Path,
    previous_merged: Path | None = None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> ClaudeReconcileReport:
    """Executa reconciliacao em pasta unica.

    Args:
        raw_dir: raw atual (data/raw/Claude.ai/)
        merged_output: pasta unica merged (data/merged/Claude.ai/) — pode nao existir
        previous_merged: override; None = usa merged_output se existir
        force_refetch_features: forca refetch de features especificas
        full: True = ignora previous, to_use tudo
    """
    if previous_merged is None:
        previous_merged = merged_output if merged_output.exists() else None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)

    curr_disc = _load_discovery(raw_dir)
    prev_disc = (
        _load_discovery(previous_merged) if previous_merged
        else {"conversations": {}, "projects": {}}
    )

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
    reconciled_at = datetime.now().isoformat()
    report = ClaudeReconcileReport()

    merged_output.mkdir(parents=True, exist_ok=True)
    (merged_output / "conversations").mkdir(exist_ok=True)
    (merged_output / "projects").mkdir(exist_ok=True)
    (merged_output / "assets").mkdir(exist_ok=True)

    # ============================================================
    # 1. CONVERSATIONS
    # ============================================================
    _apply_kind(
        plan.convs_to_use, plan.convs_to_copy, plan.convs_preserved_missing,
        "conversations", raw_dir, previous_merged, merged_output, today, report,
    )
    new_conv_ids = set(plan.convs_to_use) - set(prev_disc["conversations"].keys())
    report.convs_added = len(new_conv_ids)
    report.convs_updated = len(plan.convs_to_use) - report.convs_added
    report.convs_copied = len(plan.convs_to_copy)
    report.convs_preserved_missing = len(plan.convs_preserved_missing)
    report.convs_total = (
        report.convs_added + report.convs_updated + report.convs_copied
        + report.convs_preserved_missing
    )

    # ============================================================
    # 2. PROJECTS
    # ============================================================
    _apply_kind(
        plan.projects_to_use, plan.projects_to_copy, plan.projects_preserved_missing,
        "projects", raw_dir, previous_merged, merged_output, today, report,
    )
    new_proj_ids = set(plan.projects_to_use) - set(prev_disc["projects"].keys())
    report.projects_added = len(new_proj_ids)
    report.projects_updated = len(plan.projects_to_use) - report.projects_added
    report.projects_copied = len(plan.projects_to_copy)
    report.projects_preserved_missing = len(plan.projects_preserved_missing)
    report.projects_total = (
        report.projects_added + report.projects_updated + report.projects_copied
        + report.projects_preserved_missing
    )

    # ============================================================
    # 3. ASSETS (cumulativos, skip-existing)
    # ============================================================
    _merge_assets(raw_dir, previous_merged, merged_output)
    assets_dir = merged_output / "assets"
    if assets_dir.exists():
        # binarios = arquivos diretos em assets/ (excluindo subpasta artifacts/)
        report.asset_binaries_total = sum(
            1 for p in assets_dir.glob("*") if p.is_file()
        )
        artifacts_root = assets_dir / "artifacts"
        if artifacts_root.exists():
            # Conta soh arquivos de conteudo (nao .meta.json)
            report.artifacts_total = sum(
                1 for p in artifacts_root.rglob("*")
                if p.is_file() and not p.name.endswith(".meta.json")
            )

    # ============================================================
    # 4. DISCOVERY CUMULATIVO
    # ============================================================
    cumulative_convs = list(curr_disc["conversations"].values())
    for uuid in plan.convs_preserved_missing:
        if uuid in prev_disc["conversations"]:
            entry = dict(prev_disc["conversations"][uuid])
            entry["_preserved_missing"] = True
            cumulative_convs.append(entry)

    cumulative_projs = list(curr_disc["projects"].values())
    for uuid in plan.projects_preserved_missing:
        if uuid in prev_disc["projects"]:
            entry = dict(prev_disc["projects"][uuid])
            entry["_preserved_missing"] = True
            cumulative_projs.append(entry)

    (merged_output / "discovery_ids.json").write_text(
        json.dumps(
            {"conversations": cumulative_convs, "projects": cumulative_projs},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    # ============================================================
    # 5. SUMMARY + LOGS
    # ============================================================
    if force_refetch_features:
        report.features_refetched = sorted(force_refetch_features)

    summary = {
        "reconciled_at": reconciled_at,
        "features_version": FEATURES_VERSION,
        "convs": {
            "added": report.convs_added,
            "updated": report.convs_updated,
            "copied": report.convs_copied,
            "preserved_missing": report.convs_preserved_missing,
            "total": report.convs_total,
        },
        "projects": {
            "added": report.projects_added,
            "updated": report.projects_updated,
            "copied": report.projects_copied,
            "preserved_missing": report.projects_preserved_missing,
            "total": report.projects_total,
        },
        "asset_binaries_total": report.asset_binaries_total,
        "artifacts_total": report.artifacts_total,
        "features_refetched": report.features_refetched,
    }
    (merged_output / "claude_ai_merged_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log_entry = {
        "reconciled_at": reconciled_at,
        "raw_source": str(raw_dir),
        "features_version": FEATURES_VERSION,
        "convs_total": report.convs_total,
        "convs_added": report.convs_added,
        "convs_updated": report.convs_updated,
        "convs_copied": report.convs_copied,
        "convs_preserved_missing": report.convs_preserved_missing,
        "projects_total": report.projects_total,
        "projects_added": report.projects_added,
        "projects_updated": report.projects_updated,
        "projects_copied": report.projects_copied,
        "projects_preserved_missing": report.projects_preserved_missing,
        "asset_binaries_total": report.asset_binaries_total,
        "artifacts_total": report.artifacts_total,
        "features_refetched": report.features_refetched,
        "warnings": report.warnings,
    }
    log_path = merged_output / "reconcile_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    _write_last_reconcile_md(merged_output, report, reconciled_at)

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
    """Copia arquivos do kind (conversations ou projects) raw/merged → output."""
    # to_use: do raw atual + injeta _last_seen_in_server
    for uuid in to_use:
        src = raw_dir / kind / f"{uuid}.json"
        dst = output_dir / kind / f"{uuid}.json"
        if src.exists():
            obj = json.loads(src.read_text(encoding="utf-8"))
            obj["_last_seen_in_server"] = today
            # Garante que _preserved_missing nao persiste se reapareceu
            obj.pop("_preserved_missing", None)
            dst.write_text(
                json.dumps(obj, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            report.warnings.append(f"to_use {kind}/{uuid}: arquivo faltando em raw")

    # to_copy: do merged anterior, atualizando _last_seen_in_server
    for uuid in to_copy:
        if not previous_merged:
            report.warnings.append(f"to_copy {kind}/{uuid} mas sem previous_merged")
            continue
        src = previous_merged / kind / f"{uuid}.json"
        dst = output_dir / kind / f"{uuid}.json"
        # Se previous_merged == output_dir (pasta unica self-update),
        # ler e reescrever com _last_seen_in_server bumpado e clear de preserved_missing.
        if src.exists():
            try:
                obj = json.loads(src.read_text(encoding="utf-8"))
                obj["_last_seen_in_server"] = today
                obj.pop("_preserved_missing", None)
                dst.write_text(
                    json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                report.warnings.append(f"to_copy {kind}/{uuid}: erro lendo merged anterior: {e}")
        else:
            report.warnings.append(f"to_copy {kind}/{uuid}: merged anterior nao tem arquivo")

    # preserved_missing: marca flag, NAO atualiza _last_seen_in_server
    for uuid in preserved:
        if not previous_merged:
            continue
        src = previous_merged / kind / f"{uuid}.json"
        dst = output_dir / kind / f"{uuid}.json"
        if src.exists():
            try:
                obj = json.loads(src.read_text(encoding="utf-8"))
                obj["_preserved_missing"] = True
                dst.write_text(
                    json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                # Fallback: copy bytes (sem injetar flag se JSON corromper)
                shutil.copy2(src, dst)


def _merge_assets(raw_dir: Path, previous_merged: Path | None, output_dir: Path) -> None:
    """Copia assets de raw + anterior pro output (skip-existing). Cumulativo."""
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
    if previous_merged and previous_merged != output_dir:
        _copy_tree(previous_merged / "assets", output_dir / "assets")


def _write_last_reconcile_md(
    output_dir: Path, report: ClaudeReconcileReport, reconciled_at: str
) -> None:
    """LAST_RECONCILE.md — snapshot human-readable, sobrescreve a cada run."""
    md = (
        "# Last reconcile\n\n"
        f"- **Quando:** {reconciled_at}\n"
        f"- **Conversations:** {report.convs_total} totais "
        f"({report.convs_added} added, {report.convs_updated} updated, "
        f"{report.convs_copied} copied, {report.convs_preserved_missing} preserved)\n"
        f"- **Projects:** {report.projects_total} totais "
        f"({report.projects_added} added, {report.projects_updated} updated, "
        f"{report.projects_copied} copied, {report.projects_preserved_missing} preserved)\n"
        f"- **Asset binarios:** {report.asset_binaries_total} (cumulativo)\n"
        f"- **Artifacts extraidos:** {report.artifacts_total}\n"
        f"- **Warnings:** {len(report.warnings)}\n\n"
        "Ver `reconcile_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_RECONCILE.md").write_text(md, encoding="utf-8")
