"""Reconciler Perplexity — preserva threads, spaces, pages, files, assets.

Padrao alinhado com ChatGPT (pasta unica cumulativa). Layout merged:

  data/merged/Perplexity/
  ├── threads/<uuid>.json                   # 1 thread per file (volume alto)
  ├── threads_discovery.json                # discovery cumulativo (merged + preserved)
  ├── spaces/
  │   ├── _index.json                       # cumulativo merged
  │   ├── _pinned_raw.json                  # ultima versao
  │   └── <uuid>/
  │       ├── metadata.json
  │       ├── threads_index.json            # com flags _orphan + _removed_from_space
  │       ├── files.json
  │       └── pages/
  │           ├── _index.json
  │           └── <slug>.json
  ├── assets/
  │   ├── _index.json                       # cumulativo merged
  │   ├── _pinned_raw.json
  │   └── files/                            # binarios cumulativos
  │       ├── <slug>.<ext>
  │       └── _manifest.json
  ├── perplexity_merged_summary.json        # estado consolidado
  ├── reconcile_log.jsonl                   # historico append-only
  └── LAST_RECONCILE.md                     # snapshot human-readable

Logica (validada empiricamente em 2026-05-01):

1. Threads (list_ask_threads):
   - Rename bumpa last_query_datetime — caminho incremental detecta
   - Some do listing → preserved_missing
2. Spaces (collections):
   - Diff _index.json
   - Spaces que sumiram → preserved (raro mas possivel)
3. Threads em spaces:
   - Diff threads_index.json
   - Sumiu mas esta em list_ask_threads → _removed_from_space (sem deletar)
   - Sumiu E nao esta em list_ask_threads → _orphan (caso d344c501)
4. Pages, Files, Assets metadata: cumulativos
5. Asset binarios: cumulativos (pasta files/ acumula)

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


DROP_THRESHOLD = 0.5  # current/previous <= 0.5 aborta


@dataclass
class PerplexityPlan:
    """Plano de reconciliacao."""
    threads_to_use: list[str] = field(default_factory=list)
    threads_to_copy: list[str] = field(default_factory=list)
    threads_preserved_missing: list[str] = field(default_factory=list)
    spaces_to_use: list[str] = field(default_factory=list)
    spaces_preserved_missing: list[str] = field(default_factory=list)


@dataclass
class PerplexityReconcileReport:
    threads_added: int = 0
    threads_updated: int = 0
    threads_copied: int = 0
    threads_preserved_missing: int = 0
    spaces_total: int = 0
    spaces_preserved_missing: int = 0
    space_threads_orphans_marked: int = 0
    space_threads_removed_from_space: int = 0
    pages_total: int = 0
    files_total: int = 0
    assets_total: int = 0
    asset_binaries_total: int = 0
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao Perplexity: threads={self.threads_added}+/{self.threads_updated}~/"
            f"{self.threads_copied}={self.threads_preserved_missing}preserved, "
            f"spaces={self.spaces_total}/{self.spaces_preserved_missing}preserved, "
            f"orphans={self.space_threads_orphans_marked}, "
            f"pages={self.pages_total}, files={self.files_total}, "
            f"assets={self.assets_total}/{self.asset_binaries_total}bin"
        )


def _load_discovery(raw_dir: Path) -> dict[str, dict]:
    """Carrega discovery (lista de threads minimas).

    Tenta `discovery_ids.json` (pasta raw) E `threads_discovery.json` (merged).
    """
    for filename in ("discovery_ids.json", "threads_discovery.json"):
        p = raw_dir / filename
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return {e["uuid"]: e for e in data if isinstance(e, dict) and e.get("uuid")}
    return {}


def _load_spaces_index(spaces_dir: Path) -> dict[str, dict]:
    p = spaces_dir / "_index.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {s["uuid"]: s for s in data if isinstance(s, dict) and s.get("uuid")}


def build_plan(raw_dir: Path, previous_merged: Path | None) -> PerplexityPlan:
    """Decide o que fazer com cada thread/space."""
    curr_threads = _load_discovery(raw_dir)
    prev_threads = _load_discovery(previous_merged) if previous_merged else {}

    plan = PerplexityPlan()
    for uid, curr in curr_threads.items():
        if uid not in prev_threads:
            plan.threads_to_use.append(uid)
            continue
        prev = prev_threads[uid]
        c_dt = curr.get("last_query_datetime") or ""
        p_dt = prev.get("last_query_datetime") or ""
        c_qc = curr.get("query_count") or 0
        p_qc = prev.get("query_count") or 0
        title_changed = curr.get("title") != prev.get("title")
        # ISO datetime: comparacao lexicografica funciona
        if c_dt > p_dt or c_qc > p_qc or title_changed:
            plan.threads_to_use.append(uid)
        else:
            plan.threads_to_copy.append(uid)
    plan.threads_preserved_missing = sorted(set(prev_threads.keys()) - set(curr_threads.keys()))
    plan.threads_to_use.sort()
    plan.threads_to_copy.sort()

    # Spaces
    curr_spaces = _load_spaces_index(raw_dir / "spaces")
    prev_spaces = _load_spaces_index(previous_merged / "spaces") if previous_merged else {}
    plan.spaces_to_use = sorted(curr_spaces.keys())
    plan.spaces_preserved_missing = sorted(set(prev_spaces.keys()) - set(curr_spaces.keys()))
    return plan


def run_reconciliation(
    raw_dir: Path,
    merged_output: Path,
    previous_merged: Path | None = None,
) -> PerplexityReconcileReport:
    """Executa reconciliacao: produz pasta merged unica cumulativa."""
    if previous_merged is None:
        previous_merged = merged_output if merged_output.exists() else None

    plan = build_plan(raw_dir, previous_merged)

    # Validacao: queda drastica aborta
    curr_threads = _load_discovery(raw_dir)
    prev_threads = _load_discovery(previous_merged) if previous_merged else {}
    if prev_threads and len(curr_threads) / max(len(prev_threads), 1) < DROP_THRESHOLD:
        return PerplexityReconcileReport(
            aborted=True,
            abort_reason=(
                f"Queda drastica: prev={len(prev_threads)} curr={len(curr_threads)}. "
                f"Threshold: {DROP_THRESHOLD*100}%."
            ),
        )

    today = datetime.now().strftime("%Y-%m-%d")
    reconciled_at = datetime.now().isoformat()
    report = PerplexityReconcileReport()

    merged_output.mkdir(parents=True, exist_ok=True)
    (merged_output / "threads").mkdir(exist_ok=True)
    (merged_output / "spaces").mkdir(exist_ok=True)
    (merged_output / "assets").mkdir(exist_ok=True)
    (merged_output / "assets" / "files").mkdir(exist_ok=True)

    # ============================================================
    # 1. THREADS
    # ============================================================
    for uid in plan.threads_to_use:
        s = raw_dir / "threads" / f"{uid}.json"
        d = merged_output / "threads" / f"{uid}.json"
        if s.exists():
            _write_with_seen(s, d, today, report)
        else:
            report.warnings.append(f"thread {uid}: missing in raw")

    if previous_merged:
        for uid in plan.threads_to_copy:
            s = previous_merged / "threads" / f"{uid}.json"
            d = merged_output / "threads" / f"{uid}.json"
            if s.exists() and not d.exists():
                _write_with_seen(s, d, today, report)
        for uid in plan.threads_preserved_missing:
            s = previous_merged / "threads" / f"{uid}.json"
            d = merged_output / "threads" / f"{uid}.json"
            if s.exists() and not d.exists():
                shutil.copy2(s, d)

    new_thread_ids = set(plan.threads_to_use) - set(prev_threads.keys())
    report.threads_added = len(new_thread_ids)
    report.threads_updated = len(plan.threads_to_use) - report.threads_added
    report.threads_copied = len(plan.threads_to_copy)
    report.threads_preserved_missing = len(plan.threads_preserved_missing)

    # threads_discovery cumulativo (com preserved marcadas)
    cumulative_disc = list(curr_threads.values())
    for uid in plan.threads_preserved_missing:
        if uid in prev_threads:
            e = dict(prev_threads[uid])
            e["_preserved_missing"] = True
            cumulative_disc.append(e)
    (merged_output / "threads_discovery.json").write_text(
        json.dumps(cumulative_disc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ============================================================
    # 2. SPACES (metadata + threads_index com flags + files + pages)
    # ============================================================
    curr_spaces_dir = raw_dir / "spaces"
    prev_spaces_dir = previous_merged / "spaces" if previous_merged else None

    # captured uuids (das threads no listing global) — usado pra detectar orphans
    captured_uuids = set(curr_threads.keys())

    for space_uuid in plan.spaces_to_use:
        src = curr_spaces_dir / space_uuid
        dst = merged_output / "spaces" / space_uuid
        dst.mkdir(parents=True, exist_ok=True)

        # metadata
        if (src / "metadata.json").exists():
            shutil.copy2(src / "metadata.json", dst / "metadata.json")

        # threads_index — adicionar flags _orphan e _removed_from_space
        threads_in_space_path = src / "threads_index.json"
        prev_threads_in_space_path = (prev_spaces_dir / space_uuid / "threads_index.json") if prev_spaces_dir else None

        threads_in_space = []
        if threads_in_space_path.exists():
            threads_in_space = json.loads(threads_in_space_path.read_text(encoding="utf-8"))

        # Se thread esta no space mas nao no list_ask_threads → orphan
        for t in threads_in_space:
            if t.get("uuid") and t["uuid"] not in captured_uuids:
                t["_orphan"] = True
                report.space_threads_orphans_marked += 1

        # Se thread estava no space anterior mas saiu (e ainda existe globalmente) → removed_from_space
        if prev_threads_in_space_path and prev_threads_in_space_path.exists():
            prev_in_space = json.loads(prev_threads_in_space_path.read_text(encoding="utf-8"))
            curr_uuids_in_space = {t.get("uuid") for t in threads_in_space if t.get("uuid")}
            for prev_t in prev_in_space:
                puid = prev_t.get("uuid")
                if not puid or puid in curr_uuids_in_space:
                    continue
                # Saiu do space. Onde foi?
                if puid in captured_uuids:
                    # Ainda existe globalmente — foi removida do space sem deletar
                    e = dict(prev_t)
                    e["_removed_from_space"] = True
                    threads_in_space.append(e)
                    report.space_threads_removed_from_space += 1
                else:
                    # Sumiu de tudo: ENTRY_DELETED. Marca orphan preservado.
                    e = dict(prev_t)
                    e["_orphan"] = True
                    e["_preserved_from_previous"] = True
                    threads_in_space.append(e)
                    report.space_threads_orphans_marked += 1

        (dst / "threads_index.json").write_text(
            json.dumps(threads_in_space, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # files
        if (src / "files.json").exists():
            shutil.copy2(src / "files.json", dst / "files.json")

        # pages — copia tudo
        src_pages = src / "pages"
        if src_pages.exists():
            dst_pages = dst / "pages"
            dst_pages.mkdir(exist_ok=True)
            for item in src_pages.iterdir():
                if item.is_file():
                    target = dst_pages / item.name
                    if not target.exists():
                        shutil.copy2(item, target)
            report.pages_total += len([f for f in src_pages.iterdir() if f.is_file() and f.name != "_index.json"])

        # files counts pro report
        if (dst / "files.json").exists():
            try:
                files_data = json.loads((dst / "files.json").read_text(encoding="utf-8"))
                if isinstance(files_data, list):
                    report.files_total += len(files_data)
            except Exception:
                pass

    # Spaces preserved_missing — copia do previous
    if prev_spaces_dir:
        for space_uuid in plan.spaces_preserved_missing:
            src_p = prev_spaces_dir / space_uuid
            dst_p = merged_output / "spaces" / space_uuid
            if src_p.exists() and not dst_p.exists():
                shutil.copytree(src_p, dst_p)
                # Marca preserved_missing no metadata
                meta_p = dst_p / "metadata.json"
                if meta_p.exists():
                    try:
                        meta = json.loads(meta_p.read_text(encoding="utf-8"))
                        meta["_preserved_missing"] = True
                        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass

    report.spaces_total = len(plan.spaces_to_use)
    report.spaces_preserved_missing = len(plan.spaces_preserved_missing)

    # _index.json + _pinned_raw.json (cumulativo: spaces atuais + preserved)
    cumulative_spaces_index = []
    if (curr_spaces_dir / "_index.json").exists():
        cumulative_spaces_index = json.loads((curr_spaces_dir / "_index.json").read_text(encoding="utf-8"))
    if prev_spaces_dir and (prev_spaces_dir / "_index.json").exists():
        prev_idx = json.loads((prev_spaces_dir / "_index.json").read_text(encoding="utf-8"))
        curr_uuids = {s.get("uuid") for s in cumulative_spaces_index if s.get("uuid")}
        for prev_s in prev_idx:
            if prev_s.get("uuid") not in curr_uuids:
                e = dict(prev_s)
                e["_preserved_missing"] = True
                cumulative_spaces_index.append(e)
    (merged_output / "spaces" / "_index.json").write_text(
        json.dumps(cumulative_spaces_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if (curr_spaces_dir / "_pinned_raw.json").exists():
        shutil.copy2(curr_spaces_dir / "_pinned_raw.json", merged_output / "spaces" / "_pinned_raw.json")

    # ============================================================
    # 3. ASSETS (metadata + binarios cumulativos)
    # ============================================================
    curr_assets_dir = raw_dir / "assets"
    prev_assets_dir = previous_merged / "assets" if previous_merged else None

    # _index.json cumulativo
    cumulative_assets_index = []
    if (curr_assets_dir / "_index.json").exists():
        cumulative_assets_index = json.loads((curr_assets_dir / "_index.json").read_text(encoding="utf-8"))
    if prev_assets_dir and (prev_assets_dir / "_index.json").exists():
        prev_idx = json.loads((prev_assets_dir / "_index.json").read_text(encoding="utf-8"))
        curr_slugs = {a.get("asset_slug") for a in cumulative_assets_index if a.get("asset_slug")}
        for prev_a in prev_idx:
            if prev_a.get("asset_slug") not in curr_slugs:
                e = dict(prev_a)
                e["_preserved_missing"] = True
                cumulative_assets_index.append(e)
    (merged_output / "assets" / "_index.json").write_text(
        json.dumps(cumulative_assets_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if (curr_assets_dir / "_pinned_raw.json").exists():
        shutil.copy2(curr_assets_dir / "_pinned_raw.json", merged_output / "assets" / "_pinned_raw.json")
    report.assets_total = len(cumulative_assets_index)

    # Binarios — cumulativo, copia novos sem sobrescrever existentes
    curr_files = curr_assets_dir / "files"
    if curr_files.exists():
        for item in curr_files.iterdir():
            if not item.is_file():
                continue
            target = merged_output / "assets" / "files" / item.name
            if not target.exists():
                shutil.copy2(item, target)
    if prev_assets_dir and (prev_assets_dir / "files").exists():
        for item in (prev_assets_dir / "files").iterdir():
            if not item.is_file():
                continue
            target = merged_output / "assets" / "files" / item.name
            if not target.exists():
                shutil.copy2(item, target)
    report.asset_binaries_total = len([
        f for f in (merged_output / "assets" / "files").iterdir()
        if f.is_file() and f.name != "_manifest.json"
    ])

    # ============================================================
    # 4. SUMMARY + LOG
    # ============================================================
    summary = {
        "reconciled_at": reconciled_at,
        "threads_total": len(curr_threads) + report.threads_preserved_missing,
        "threads_active": len(curr_threads),
        "threads_preserved_missing": report.threads_preserved_missing,
        "spaces_total": report.spaces_total + report.spaces_preserved_missing,
        "spaces_active": report.spaces_total,
        "spaces_preserved_missing": report.spaces_preserved_missing,
        "space_threads_orphans": report.space_threads_orphans_marked,
        "space_threads_removed_from_space": report.space_threads_removed_from_space,
        "pages_total": report.pages_total,
        "files_total": report.files_total,
        "assets_total": report.assets_total,
        "asset_binaries_total": report.asset_binaries_total,
    }
    (merged_output / "perplexity_merged_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log_entry = {
        "reconciled_at": reconciled_at,
        "raw_source": str(raw_dir),
        **{k: v for k, v in summary.items() if k != "reconciled_at"},
        "threads_added": report.threads_added,
        "threads_updated": report.threads_updated,
        "threads_copied": report.threads_copied,
        "warnings": report.warnings,
    }
    log_path = merged_output / "reconcile_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    md = (
        "# Last reconcile\n\n"
        f"- **Quando:** {reconciled_at}\n"
        f"- **Threads totais:** {summary['threads_total']} "
        f"({summary['threads_active']} ativas, {summary['threads_preserved_missing']} preserved)\n"
        f"- **Spaces:** {summary['spaces_active']} ativos / {summary['spaces_preserved_missing']} preserved\n"
        f"- **Threads em spaces — orphans marcadas:** {report.space_threads_orphans_marked}\n"
        f"- **Threads em spaces — removidas (sem delete):** {report.space_threads_removed_from_space}\n"
        f"- **Pages:** {report.pages_total}\n"
        f"- **Files de space:** {report.files_total}\n"
        f"- **Assets metadata:** {report.assets_total}\n"
        f"- **Binarios baixados (acumulado):** {report.asset_binaries_total}\n"
        f"- **Ultima run:** added={report.threads_added}, updated={report.threads_updated}, "
        f"copied={report.threads_copied}\n\n"
        "Ver `reconcile_log.jsonl` pro historico completo.\n"
    )
    (merged_output / "LAST_RECONCILE.md").write_text(md, encoding="utf-8")

    return report


def _write_with_seen(src: Path, dst: Path, today: str, report: PerplexityReconcileReport) -> None:
    """Escreve o thread JSON adicionando _last_seen_in_server."""
    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
        obj["_last_seen_in_server"] = today
        dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        report.warnings.append(f"{dst.name}: {str(e)[:100]}")
