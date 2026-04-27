"""Reconciler do NotebookLM — merge entre raws de datas diferentes preservando historico.

Diferente do ChatGPT (1 arquivo chatgpt_raw.json com todas as convs), NotebookLM tem
layout por arquivo:
  - notebooks/<uuid>.json   — metadata, guide, chat, notes, audios, mind_map
  - sources/<suid>.json     — source content chunked
  - assets/                 — m4a/png/webp baixados
  - discovery_ids.json      — lista [uuid, title, emoji, update_time, create_time]

Saida em data/merged/NotebookLM/<account>/<date>/ com mesma estrutura.

Padrao build_plan (conforme CLAUDE.md):
  - to_use: UUIDs do raw atual (novos ou update_time > anterior)
  - to_copy: UUIDs inalterados — copia arquivos do merged anterior, nao refaz API
  - preserved_missing: UUIDs no anterior mas nao no atual — deletados no servidor

Features futuras (novos rpcids como Mind Map nodes, Notes content) usam
FEATURES_VERSION no metadata pra forcar refetch seletivo.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# Versao do schema fetchado. Bumpa quando adicionamos novo rpcid (Mind Map nodes,
# Notes content, etc). Raws com version antiga sao refetchados, mesmo se servidor
# nao mudou.
#
# Histórico:
#   v1: initial (rLM1Ne, VfAZjd, khqZz, cFji9, gArtLc, hPTbtc, hizoJc)
#   v2: mapeia types 2/3/4/7/8/9 em gArtLc (antes tratava so types 1 e 8); adiciona
#       v9rmvd (text artifacts) + CYK0Xb (mind map tree fetch)
FEATURES_VERSION = 2

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
}

DROP_THRESHOLD = 0.5  # previous > current/previous → aborta


@dataclass
class NotebookPlan:
    """Plano por notebook_uuid."""
    to_use: list[str] = field(default_factory=list)          # refetch da API ja feito, copia raw atual
    to_copy: list[str] = field(default_factory=list)         # inalterado, copia do anterior
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

    NotebookLM bumpa esses pares periodicamente em vários campos do raw
    (metadata.update_time, notes wrapper, etc). Removemos pra hash semantico.

    Heurística: lista de 2 ints onde primeiro esta em range epoch seconds
    (1.5e9 < N < 2.5e9, cobre 2017-2049) e segundo e nanos (<1e9).
    """
    if isinstance(x, list):
        # Heuristica de timestamp [secs, nanos]
        if (len(x) == 2 and isinstance(x[0], int) and isinstance(x[1], int)
                and 1_500_000_000 < x[0] < 2_500_000_000 and 0 <= x[1] < 1_000_000_000):
            return "_ts"
        return [_strip_timestamps(v) for v in x]
    if isinstance(x, dict):
        return {k: _strip_timestamps(v) for k, v in x.items() if k != "_last_seen_in_server"}
    return x


def _eq_lenient(a, b) -> bool:
    """Comparacao recursiva tolerante a:
    - timestamps voláteis (pares [epoch, nanos] tratados como iguais)
    - None vs valor (RPC pode retornar None vs dado entre captures por flutuacao)
    """
    # None compativel com qualquer
    if a is None or b is None:
        return True
    # Timestamps [secs, nanos]
    if (isinstance(a, list) and isinstance(b, list)
            and len(a) == 2 and len(b) == 2
            and all(isinstance(x, int) for x in a)
            and all(isinstance(x, int) for x in b)
            and 1_500_000_000 < a[0] < 2_500_000_000
            and 1_500_000_000 < b[0] < 2_500_000_000):
        return True
    if type(a) != type(b):
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
    """True se notebook.json for semanticamente igual entre 2 raws."""
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
    """Decide to_use/to_copy/preserved_missing comparando HASH DO CONTEUDO.

    NotebookLM bumpa update_time periodicamente — usar hash do JSON (excluindo
    campos volateis) e mais confiavel pra detectar mudancas semanticas.

    Args:
        current_raw: raw dir novo (com discovery_ids.json + notebooks/ + sources/)
        previous_merged: merged dir anterior, ou None (primeiro run)
        force_refetch_features: rpcids a forcar refetch
        full: True = tudo vira to_use
    """
    current_disc = _load_discovery(current_raw)
    previous_disc = _load_discovery(previous_merged) if previous_merged else {}

    current_ids = set(current_disc.keys())
    previous_ids = set(previous_disc.keys())

    plan = NotebookPlan()
    force_feats = force_refetch_features or set()

    prev_version = None
    if previous_merged:
        meta_path = previous_merged / "reconcile_log.json"
        if meta_path.exists():
            try:
                prev_log = json.loads(meta_path.read_text(encoding="utf-8"))
                prev_version = prev_log.get("features_version")
            except Exception:
                pass

    version_bumped = prev_version is not None and prev_version < FEATURES_VERSION
    has_forced_features = bool(force_feats)

    for uuid in current_ids:
        # Suporta export parcial (--notebook UUID): se notebook.json NAO esta no
        # raw atual mas existe no merged, copia do merged
        raw_has = (current_raw / "notebooks" / f"{uuid}.json").exists()
        merged_has = bool(previous_merged) and (previous_merged / "notebooks" / f"{uuid}.json").exists()

        if not raw_has and merged_has:
            plan.to_copy.append(uuid)
            continue
        if not raw_has and not merged_has:
            # Discovery lista mas ningum tem o notebook — skip
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


def run_reconciliation(
    raw_dir: Path,
    merged_output_base: Path,
    previous_merged: Path | None = None,
    force_refetch_features: set[str] | None = None,
    full: bool = False,
) -> ReconcileReport:
    """Executa reconciliacao: raw + previous merged → novo merged.

    Args:
        raw_dir: raw recem capturado (com notebooks/, sources/, assets/, discovery_ids.json)
        merged_output_base: data/merged/NotebookLM/<account>/ (cria subdir datado)
        previous_merged: override auto-detect; None = pega mais recente
        force_refetch_features: rpcids a forcar refetch
        full: True = ignora previous, usa tudo atual

    Preserva estrutura: notebooks/, sources/, assets/.
    """
    if previous_merged is None:
        previous_merged = _find_latest_merged(merged_output_base)
    if previous_merged and not previous_merged.exists():
        previous_merged = None

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

    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = merged_output_base / today
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "notebooks").mkdir(exist_ok=True)
    (output_dir / "sources").mkdir(exist_ok=True)
    (output_dir / "assets").mkdir(exist_ok=True)

    report = ReconcileReport()

    # to_use: copia do raw atual
    for uuid in plan.to_use:
        src_nb = raw_dir / "notebooks" / f"{uuid}.json"
        dst_nb = output_dir / "notebooks" / f"{uuid}.json"
        if src_nb.exists():
            # Injeta _last_seen_in_server
            nb = json.loads(src_nb.read_text(encoding="utf-8"))
            nb["_last_seen_in_server"] = today
            dst_nb.write_text(json.dumps(nb, ensure_ascii=False, indent=2))
        else:
            report.warnings.append(f"to_use {uuid}: notebook.json faltando em raw")

        # Copia sources desse notebook (descobre via metadata)
        _copy_sources_for_notebook(uuid, raw_dir, output_dir)

    # to_copy: copia do merged anterior
    for uuid in plan.to_copy:
        if not previous_merged:
            report.warnings.append(f"to_copy {uuid} mas sem previous_merged")
            continue
        src_nb = previous_merged / "notebooks" / f"{uuid}.json"
        dst_nb = output_dir / "notebooks" / f"{uuid}.json"
        if src_nb.exists():
            nb = json.loads(src_nb.read_text(encoding="utf-8"))
            nb["_last_seen_in_server"] = today
            dst_nb.write_text(json.dumps(nb, ensure_ascii=False, indent=2))
        else:
            report.warnings.append(f"to_copy {uuid}: merged anterior nao tem notebook")
        _copy_sources_for_notebook(uuid, previous_merged, output_dir)

    # preserved_missing: copia do anterior, NAO atualiza _last_seen_in_server
    for uuid in plan.preserved_missing:
        if not previous_merged:
            continue
        src_nb = previous_merged / "notebooks" / f"{uuid}.json"
        dst_nb = output_dir / "notebooks" / f"{uuid}.json"
        if src_nb.exists():
            shutil.copy2(src_nb, dst_nb)
        _copy_sources_for_notebook(uuid, previous_merged, output_dir)

    # Assets: link/copy (skip-existing) do raw atual + do merged anterior
    _merge_assets(raw_dir, previous_merged, output_dir)

    # Discovery do merged = discovery atual (tag preserved_missing marca quem foi deletado)
    merged_disc = list(current_disc.values())
    if previous_disc:
        for uuid in plan.preserved_missing:
            if uuid in previous_disc:
                d = dict(previous_disc[uuid])
                d["_deleted_from_server"] = True
                merged_disc.append(d)
    (output_dir / "discovery_ids.json").write_text(
        json.dumps(merged_disc, ensure_ascii=False, indent=2)
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

    # reconcile_log.json
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
    (output_dir / "reconcile_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2)
    )

    return report


def _copy_sources_for_notebook(uuid: str, src_root: Path, dst_root: Path) -> None:
    """Copia sources/<suid>.json do notebook uuid a partir do seu metadata."""
    nb_path = src_root / "notebooks" / f"{uuid}.json"
    if not nb_path.exists():
        return
    try:
        nb = json.loads(nb_path.read_text(encoding="utf-8"))
    except Exception:
        return
    # source UUIDs em metadata[0][1] — lista de [[suid], name, ...]
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
            shutil.copy2(src_path, dst_path)


def _merge_assets(raw_dir: Path, previous_merged: Path | None, output_dir: Path) -> None:
    """Copia assets de raw atual e merged anterior pro output. Skip-existing."""
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

    assets_out = output_dir / "assets"
    _copy_tree(raw_dir / "assets", assets_out)
    if previous_merged:
        _copy_tree(previous_merged / "assets", assets_out)


def _find_latest_merged(merged_base: Path) -> Path | None:
    """Pega o merged dir mais recente em merged_base/<YYYY-MM-DD>/."""
    if not merged_base.exists():
        return None
    candidates = sorted([d for d in merged_base.iterdir() if d.is_dir()])
    return candidates[-1] if candidates else None
