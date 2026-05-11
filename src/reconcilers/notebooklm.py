"""Reconciler do NotebookLM — pasta unica cumulativa per-account.

Layout (in-place na pasta unica):
  - notebooks/<uuid>.json                          — metadata, guide, chat, notes, audios, mind_map
  - notebooks/<uuid>_artifacts/<art_uuid>.json     — conteudo individual de tipos 2/4/7/9
  - notebooks/<uuid>_mind_map_tree.json            — arvore CYK0Xb
  - sources/<suid>.json                            — source content chunked
  - assets/                                        — m4a/mp4/pdf/pptx baixados
  - discovery_ids.json                             — lista [uuid, title, ...] cumulativa

Padrao build_plan:
  - to_use: UUIDs do raw atual com mudanca semantica (refetch da API ja feito)
  - to_copy: UUIDs inalterados — no-op (ja estao no merged in-place)
  - preserved_missing: UUIDs no merged anterior mas nao no atual

Pasta unica: NAO cria subpasta dated. Sobrescreve in-place.

Features futuras (novos rpcids) usam FEATURES_VERSION pra forcar refetch seletivo.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# Versao do schema fetchado. Bumpa quando adicionamos novo rpcid.
#
# Histórico:
#   v1: initial (rLM1Ne, VfAZjd, khqZz, cFji9, gArtLc, hPTbtc, hizoJc)
#   v2: mapeia types 2/3/4/7/8/9 em gArtLc (antes tratava so types 1 e 8); adiciona
#       v9rmvd (text artifacts) + CYK0Xb (mind map tree fetch). Pasta unica
#       cumulativa per-account (sem subpastas dated).
#   v3: adiciona tr032e (source-level summary + tags + suggested questions).
FEATURES_VERSION = 3

FEATURE_FLAGS = {
    "rLM1Ne_metadata",
    "VfAZjd_guide",
    "khqZz_chat",
    "cFji9_notes",
    "gArtLc_artifacts",
    "v9rmvd_text_artifacts",
    "CYK0Xb_mind_map_tree",
    "hPTbtc_mind_map_uuid",
    "hizoJc_source_content",
    "tr032e_source_guide",
}

DROP_THRESHOLD = 0.5  # current/previous → aborta se < threshold


@dataclass
class NotebookPlan:
    """Plano por notebook_uuid."""
    to_use: list[str] = field(default_factory=list)             # refetch da API ja feito, copia raw atual
    to_copy: list[str] = field(default_factory=list)            # inalterado, ja esta no merged in-place
    preserved_missing: list[str] = field(default_factory=list)  # deletado no servidor


@dataclass
class ReconcileReport:
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
            f"Reconciliacao NotebookLM: added={self.added}, updated={self.updated}, "
            f"copied={self.copied}, preserved_missing={self.preserved_missing}, "
            f"warnings={len(self.warnings)}"
        )


def _load_discovery(raw_dir: Path) -> dict[str, dict]:
    """Le discovery_ids.json → {uuid: {title, update_time, ...}}."""
    path = raw_dir / "discovery_ids.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return {}
    return {nb["uuid"]: nb for nb in data if isinstance(nb, dict) and nb.get("uuid")}


def _strip_timestamps(x):
    """Walk recursivo: substitui pares [epoch_secs, nanos] por placeholder.

    NotebookLM bumpa esses pares periodicamente — removemos pra hash semantico.
    """
    if isinstance(x, list):
        if (len(x) == 2 and isinstance(x[0], int) and isinstance(x[1], int)
                and 1_500_000_000 < x[0] < 2_500_000_000 and 0 <= x[1] < 1_000_000_000):
            return "_ts"
        return [_strip_timestamps(v) for v in x]
    if isinstance(x, dict):
        return {k: _strip_timestamps(v) for k, v in x.items() if k != "_last_seen_in_server"}
    return x


def _is_googleusercontent_presigned(s) -> bool:
    """True se for URL presigned de asset NotebookLM (audio/video).

    Server regenera essa URL a cada request — comparar string-equal causa
    falso-DIFF mesmo quando o asset nao mudou. Validado 2026-05-11: 3 de 5
    notebooks divergem em audios[0][N][6][2] mesmo sem mudanca real.
    """
    return isinstance(s, str) and s.startswith(
        "https://lh3.googleusercontent.com/notebooklm/"
    )


def _eq_lenient(a, b) -> bool:
    """Comparacao recursiva tolerante a timestamps voláteis.

    Semântica de None:
    - `None == None`: True (ambos vazios)
    - `None vs populado`: False (conteúdo divergente — força refetch)

    Bug histórico (corrigido 2026-05-03 via cross-review): versão anterior
    retornava True pra QUALQUER lado None, fazendo notebook que ganhou
    chat/guide/mind_map novo virar `to_copy` em vez de `to_use` — perda
    silenciosa de dados novos no merged.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if _is_googleusercontent_presigned(a) and _is_googleusercontent_presigned(b):
        return True
    if (isinstance(a, list) and isinstance(b, list)
            and len(a) == 2 and len(b) == 2
            and all(isinstance(x, int) for x in a)
            and all(isinstance(x, int) for x in b)
            and 1_500_000_000 < a[0] < 2_500_000_000
            and 1_500_000_000 < b[0] < 2_500_000_000):
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_eq_lenient(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        keys = set(a.keys()) | set(b.keys())
        return all(_eq_lenient(a.get(k), b.get(k)) for k in keys)
    return a == b


def _content_eq(raw_a: Path, raw_b: Path, uuid: str) -> bool:
    """True se notebook.json for semanticamente igual entre 2 dirs."""
    pa = raw_a / "notebooks" / f"{uuid}.json"
    pb = raw_b / "notebooks" / f"{uuid}.json"
    if not (pa.exists() and pb.exists()):
        return False
    try:
        na = json.loads(pa.read_text(encoding="utf-8"))
        nb = json.loads(pb.read_text(encoding="utf-8"))
    except Exception:
        return False
    na.pop("_last_seen_in_server", None)
    nb.pop("_last_seen_in_server", None)
    return _eq_lenient(na, nb)


def build_plan(
    current_raw: Path,
    previous_merged: Path | None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> NotebookPlan:
    """Decide to_use/to_copy/preserved_missing comparando hash do conteudo."""
    current_disc = _load_discovery(current_raw)
    previous_disc = _load_discovery(previous_merged) if previous_merged else {}

    current_ids = set(current_disc.keys())
    previous_ids = set(previous_disc.keys())

    plan = NotebookPlan()
    force_feats = force_refetch_features or set()

    prev_version = None
    if previous_merged:
        log_path = previous_merged / "reconcile_log.jsonl"
        if log_path.exists():
            try:
                # Le ultima entrada (jsonl)
                lines = log_path.read_text(encoding="utf-8").strip().split("\n")
                if lines:
                    last = json.loads(lines[-1])
                    prev_version = last.get("features_version")
            except Exception:
                pass

    version_bumped = prev_version is not None and prev_version < FEATURES_VERSION
    has_forced_features = bool(force_feats)

    for uuid in current_ids:
        raw_has = (current_raw / "notebooks" / f"{uuid}.json").exists()
        merged_has = bool(previous_merged) and (previous_merged / "notebooks" / f"{uuid}.json").exists()

        if not raw_has and merged_has:
            plan.to_copy.append(uuid)
            continue
        if not raw_has and not merged_has:
            continue

        if full or version_bumped or has_forced_features:
            plan.to_use.append(uuid)
            continue
        if uuid not in previous_ids:
            plan.to_use.append(uuid)  # novo
            continue
        if previous_merged and _content_eq(current_raw, previous_merged, uuid):
            plan.to_copy.append(uuid)
        else:
            plan.to_use.append(uuid)

    plan.preserved_missing = sorted(previous_ids - current_ids)
    plan.to_use = sorted(plan.to_use)
    plan.to_copy = sorted(plan.to_copy)
    return plan


def _copy_sources_for_notebook(uuid: str, src_root: Path, dst_root: Path) -> None:
    """Copia sources/<suid>.json do notebook uuid a partir do seu metadata."""
    nb_path = src_root / "notebooks" / f"{uuid}.json"
    if not nb_path.exists():
        return
    try:
        nb = json.loads(nb_path.read_text(encoding="utf-8"))
    except Exception:
        return
    meta = nb.get("metadata")
    if not (meta and isinstance(meta, list) and meta and isinstance(meta[0], list)):
        return
    src_list = meta[0][1] if len(meta[0]) > 1 else None
    if not isinstance(src_list, list):
        return
    for src_entry in src_list:
        if not (isinstance(src_entry, list) and src_entry and isinstance(src_entry[0], list) and src_entry[0]):
            continue
        suid = src_entry[0][0] if isinstance(src_entry[0][0], str) else None
        if not suid:
            continue
        src_path = src_root / "sources" / f"{suid}.json"
        dst_path = dst_root / "sources" / f"{suid}.json"
        if src_path.exists() and not dst_path.exists():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
        # Source guide (tr032e — summary + tags + questions)
        src_guide = src_root / "sources" / f"{suid}_guide.json"
        dst_guide = dst_root / "sources" / f"{suid}_guide.json"
        if src_guide.exists() and not dst_guide.exists():
            dst_guide.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_guide, dst_guide)


def _copy_artifacts_and_mindmap(uuid: str, src_root: Path, dst_root: Path) -> None:
    """Copia notebooks/<uuid>_artifacts/* e <uuid>_mind_map_tree.json."""
    src_art = src_root / "notebooks" / f"{uuid}_artifacts"
    dst_art = dst_root / "notebooks" / f"{uuid}_artifacts"
    if src_art.exists():
        dst_art.mkdir(parents=True, exist_ok=True)
        for f in src_art.glob("*.json"):
            tgt = dst_art / f.name
            if not tgt.exists():
                shutil.copy2(f, tgt)
    src_mm = src_root / "notebooks" / f"{uuid}_mind_map_tree.json"
    dst_mm = dst_root / "notebooks" / f"{uuid}_mind_map_tree.json"
    if src_mm.exists() and not dst_mm.exists():
        shutil.copy2(src_mm, dst_mm)


def _merge_assets(raw_dir: Path, output_dir: Path) -> None:
    """Copia assets do raw atual pro merged. Skip-existing."""
    src = raw_dir / "assets"
    dst = output_dir / "assets"
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


def _write_last_reconcile_md(merged_dir: Path, log_entry: dict) -> None:
    """Snapshot human-readable da ultima reconciliacao."""
    md = (
        f"# Last Reconcile — NotebookLM (account {log_entry.get('account', '?')})\n\n"
        f"**Run:** {log_entry['reconciled_at']}\n"
        f"**Features version:** {log_entry['features_version']}\n\n"
        f"## Totals\n\n"
        f"- Added: {log_entry['added']}\n"
        f"- Updated: {log_entry['updated']}\n"
        f"- Copied: {log_entry['copied']}\n"
        f"- Preserved missing: {log_entry['preserved_missing']}\n"
        f"- Warnings: {len(log_entry.get('warnings', []))}\n"
    )
    if log_entry.get("features_refetched"):
        md += f"\n**Forced refetch:** {', '.join(log_entry['features_refetched'])}\n"
    (merged_dir / "LAST_RECONCILE.md").write_text(md, encoding="utf-8")


def run_reconciliation(
    raw_dir: Path,
    merged_output_base: Path,
    previous_merged: Path | None = None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> ReconcileReport:
    """Executa reconciliacao in-place na pasta unica per-account.

    Args:
        raw_dir: raw recem capturado (data/raw/NotebookLM/account-{N}/)
        merged_output_base: data/merged/NotebookLM/account-{N}/ (cumulativa)
        previous_merged: override default (default: merged_output_base mesmo — in-place)
        force_refetch_features: rpcids a forcar refetch
        full: True = ignora previous, usa tudo atual
    """
    started_at = datetime.now(timezone.utc)
    today = started_at.strftime("%Y-%m-%d")

    merged_output_base.mkdir(parents=True, exist_ok=True)
    output_dir = merged_output_base
    (output_dir / "notebooks").mkdir(exist_ok=True)
    (output_dir / "sources").mkdir(exist_ok=True)
    (output_dir / "assets").mkdir(exist_ok=True)

    # Pasta unica: previous = merged_output_base mesmo (a menos que override)
    if previous_merged is None:
        previous_merged = merged_output_base if (merged_output_base / "discovery_ids.json").exists() else None

    plan = build_plan(raw_dir, previous_merged, force_refetch_features, full)

    current_disc = _load_discovery(raw_dir)
    previous_disc = _load_discovery(previous_merged) if previous_merged else {}

    # Validacao: queda drastica aborta
    if previous_disc and len(previous_disc) > 0:
        ratio = len(current_disc) / len(previous_disc)
        if ratio < DROP_THRESHOLD:
            return ReconcileReport(
                aborted=True,
                abort_reason=(
                    f"Queda drastica: previous={len(previous_disc)}, current={len(current_disc)} "
                    f"(ratio={ratio:.2f} < {DROP_THRESHOLD}). Investigue."
                ),
            )

    report = ReconcileReport()

    # to_use: copia do raw atual (sobrescreve in-place)
    for uuid in plan.to_use:
        src_nb = raw_dir / "notebooks" / f"{uuid}.json"
        dst_nb = output_dir / "notebooks" / f"{uuid}.json"
        if src_nb.exists():
            nb = json.loads(src_nb.read_text(encoding="utf-8"))
            nb["_last_seen_in_server"] = today
            dst_nb.write_text(json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            report.warnings.append(f"to_use {uuid}: notebook.json faltando em raw")

        _copy_sources_for_notebook(uuid, raw_dir, output_dir)
        _copy_artifacts_and_mindmap(uuid, raw_dir, output_dir)

    # to_copy: ja esta in-place. Atualizar so _last_seen_in_server.
    for uuid in plan.to_copy:
        dst_nb = output_dir / "notebooks" / f"{uuid}.json"
        if not dst_nb.exists() and previous_merged and previous_merged != output_dir:
            # Se previous_merged for diferente do output (override), copia
            src_nb = previous_merged / "notebooks" / f"{uuid}.json"
            if src_nb.exists():
                shutil.copy2(src_nb, dst_nb)
        if dst_nb.exists():
            try:
                nb = json.loads(dst_nb.read_text(encoding="utf-8"))
                nb["_last_seen_in_server"] = today
                dst_nb.write_text(json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                report.warnings.append(f"to_copy {uuid}: falha ao atualizar _last_seen_in_server")
        else:
            report.warnings.append(f"to_copy {uuid}: notebook.json faltando em merged")

    # preserved_missing: ja esta in-place. Marcar mas NAO atualizar _last_seen_in_server.
    # Se previous_merged for override e diferente, copia o anterior.
    for uuid in plan.preserved_missing:
        dst_nb = output_dir / "notebooks" / f"{uuid}.json"
        if not dst_nb.exists() and previous_merged and previous_merged != output_dir:
            src_nb = previous_merged / "notebooks" / f"{uuid}.json"
            if src_nb.exists():
                shutil.copy2(src_nb, dst_nb)

    # Assets do raw atual
    _merge_assets(raw_dir, output_dir)

    # Discovery do merged: discovery atual + tag preserved_missing pros deletados
    merged_disc = list(current_disc.values())
    if previous_disc:
        for uuid in plan.preserved_missing:
            if uuid in previous_disc:
                d = dict(previous_disc[uuid])
                d["_deleted_from_server"] = True
                merged_disc.append(d)
    (output_dir / "discovery_ids.json").write_text(
        json.dumps(merged_disc, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # Contagens
    new_ids = set(plan.to_use) - set(previous_disc.keys())
    updated_ids = set(plan.to_use) - new_ids
    report.added = len(new_ids)
    report.updated = len(updated_ids)
    report.copied = len(plan.to_copy)
    report.preserved_missing = len(plan.preserved_missing)
    if force_refetch_features:
        report.features_refetched = sorted(force_refetch_features)

    # Determina account a partir do path (data/merged/NotebookLM/account-{N}/)
    account = output_dir.name.replace("account-", "") if output_dir.name.startswith("account-") else "?"

    # reconcile_log.jsonl (append-only)
    log_entry = {
        "reconciled_at": started_at.isoformat(),
        "account": account,
        "raw_source": str(raw_dir),
        "previous_merged": str(previous_merged) if previous_merged else None,
        "features_version": FEATURES_VERSION,
        "added": report.added,
        "updated": report.updated,
        "copied": report.copied,
        "preserved_missing": report.preserved_missing,
        "features_refetched": report.features_refetched,
        "warnings": report.warnings[:10],  # primeiros 10
    }
    log_path = output_dir / "reconcile_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")

    _write_last_reconcile_md(output_dir, log_entry)

    return report
