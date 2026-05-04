"""Parse merged → 8 parquets canonicos+auxiliares (multi-conta).

Le data/merged/NotebookLM/account-{1,2}/ e escreve data/processed/NotebookLM/
(8 parquets agregando ambas contas). Idempotente.

Uso: PYTHONPATH=. .venv/bin/python scripts/notebooklm-parse.py
"""

import json
from pathlib import Path

from src.parsers.notebooklm import NotebookLMParser


MERGED_BASE = Path("data/merged/NotebookLM")
PROCESSED_DIR = Path("data/processed/NotebookLM")


def _load_account(account_dir: Path, account: str) -> dict:
    """Le notebooks/sources/artifacts/mind_map_trees do merged dir per-account.

    Retorna dict com 'notebooks' (list) e 'sources' (dict).
    """
    notebooks = []
    sources = {}
    source_guides = {}

    nb_dir = account_dir / "notebooks"
    sources_dir = account_dir / "sources"

    if not nb_dir.exists():
        return {"notebooks": notebooks, "sources": sources, "source_guides": source_guides}

    # Discovery do merged: pra timestamps create_time/update_time atualizados
    discovery = {}
    disc_path = account_dir / "discovery_ids.json"
    if disc_path.exists():
        try:
            disc_list = json.loads(disc_path.read_text(encoding="utf-8"))
            for d in disc_list:
                if isinstance(d, dict) and d.get("uuid"):
                    discovery[d["uuid"]] = d
        except Exception:
            pass

    for nb_path in sorted(nb_dir.glob("*.json")):
        # Skip _mind_map_tree.json e _artifacts dir
        if "_mind_map_tree" in nb_path.name or nb_path.name.endswith("_artifacts"):
            continue
        try:
            nb = json.loads(nb_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        nb_uuid = nb.get("uuid")
        if not nb_uuid:
            continue

        # Inject account
        nb["account"] = account

        # Merge timestamps from discovery se disponivel
        disc = discovery.get(nb_uuid)
        if disc:
            if "create_time" in disc and disc["create_time"] is not None:
                nb.setdefault("create_time", disc["create_time"])
            if "update_time" in disc and disc["update_time"] is not None:
                nb.setdefault("update_time", disc["update_time"])
            # _last_seen_in_server pode vir do discovery se preserved
            if disc.get("_deleted_from_server"):
                nb["_preserved_missing"] = True

        # Carregar artifacts individuais
        art_dir = nb_dir / f"{nb_uuid}_artifacts"
        if art_dir.exists():
            individual = {}
            for art_path in art_dir.glob("*.json"):
                try:
                    art = json.loads(art_path.read_text(encoding="utf-8"))
                    individual[art["artifact_uuid"]] = art
                except Exception:
                    continue
            nb["_artifacts_individual"] = individual

        # Carregar mind_map: metadata (CYK0Xb) + tree completa (asset)
        # - notebooks/<nb>_mind_map_tree.json: metadata do RPC com mm_uuid
        # - assets/mind_maps/<nb>_<mm>.json: tree completa com {name, children}
        # Nota: mm_uuid do metadata pode divergir do nome do asset (regenerate
        # bumpa o mm_uuid). Procurar por prefixo nb_uuid* eh mais confiavel.
        mm_path = nb_dir / f"{nb_uuid}_mind_map_tree.json"
        if mm_path.exists():
            try:
                mm_metadata = json.loads(mm_path.read_text(encoding="utf-8"))
                nb["_mind_map_tree"] = mm_metadata
            except Exception:
                pass

        # Buscar tree completa por prefixo nb_uuid em assets/mind_maps/
        mm_assets_dir = account_dir / "assets" / "mind_maps"
        if mm_assets_dir.exists():
            asset_matches = sorted(
                mm_assets_dir.glob(f"{nb_uuid}_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,  # mais recente primeiro
            )
            if asset_matches:
                try:
                    asset_data = json.loads(asset_matches[0].read_text(encoding="utf-8"))
                    if asset_data.get("tree"):
                        nb["_mind_map_tree"] = {
                            **(nb.get("_mind_map_tree") or {}),
                            "tree": asset_data["tree"],
                            # Se metadata divergir, usar mm_uuid do asset (mais novo)
                            "mind_map_uuid": asset_data.get("mind_map_uuid"),
                        }
                except Exception:
                    pass

        notebooks.append(nb)

    # Sources + source guides (tr032e)
    if sources_dir.exists():
        for src_path in sources_dir.glob("*.json"):
            try:
                s = json.loads(src_path.read_text(encoding="utf-8"))
                if "source_uuid" not in s:
                    continue
                if src_path.stem.endswith("_guide"):
                    source_guides[s["source_uuid"]] = s
                else:
                    sources[s["source_uuid"]] = s
            except Exception:
                continue

    return {"notebooks": notebooks, "sources": sources, "source_guides": source_guides}


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    merged_combined = {"notebooks": [], "sources": {}, "source_guides": {}}

    if not MERGED_BASE.exists():
        print(f"ERRO: merged base nao existe: {MERGED_BASE}")
        return 1

    for account_dir in sorted(MERGED_BASE.glob("account-*")):
        account = account_dir.name.replace("account-", "")
        data = _load_account(account_dir, account)
        merged_combined["notebooks"].extend(data["notebooks"])
        merged_combined["sources"].update(data["sources"])
        merged_combined["source_guides"].update(data.get("source_guides", {}))
        print(f"  {account_dir.name}: {len(data['notebooks'])} notebooks, "
              f"{len(data['sources'])} sources, {len(data.get('source_guides', {}))} source guides")

    parser = NotebookLMParser()
    stats = parser.parse(merged_combined, output_dir=PROCESSED_DIR)
    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nParquets em: {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
