"""Parse current and historical NotebookLM data into canonical Parquets.

Reads every account under data/merged/NotebookLM/ plus immutable old-format
snapshots under data/external/notebooklm-snapshots/. Writes one family of eleven
Parquets under data/processed/NotebookLM/. Idempotent.

Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.parse
"""

import argparse
import json
from pathlib import Path

from src.accounts import account_email
from src.account_identity import resolve_account_id
from src.platforms.notebooklm.parser import NotebookLMParser
from src.platforms.notebooklm.historical_parser import (
    NotebookLMHistoricalResult,
    parse_historical_archives,
)


MERGED_BASE = Path("data/merged/NotebookLM")
PROCESSED_DIR = Path("data/processed/NotebookLM")
HISTORICAL_ROOT = Path("data/external/notebooklm-snapshots")


def _load_account(
    account_dir: Path, account_key: str, account_label: str, account_id: str,
) -> dict:
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
        nb["account"] = account_label
        nb["account_key"] = account_key
        nb["account_id"] = account_id
        nb["_account_dir"] = str(account_dir)

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


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged-root", type=Path, default=MERGED_BASE)
    ap.add_argument("--output-dir", type=Path, default=PROCESSED_DIR)
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
    ap.add_argument(
        "--historical-root",
        type=Path,
        default=HISTORICAL_ROOT,
        help="directory containing immutable old-format snapshot directories",
    )
    ap.add_argument(
        "--without-historical",
        action="store_true",
        help="explicitly rebuild current accounts without historical snapshots",
    )
    args = ap.parse_args(argv)
    merged_combined = {"notebooks": [], "sources": {}, "source_guides": {}}

    if not args.merged_root.exists():
        print(f"ERRO: merged base nao existe: {args.merged_root}")
        return 1

    historical = NotebookLMHistoricalResult()
    if not args.without_historical:
        try:
            archive_account_ids = {
                path.name: resolve_account_id(
                    "NotebookLM", f"archive:{path.name}", args.catalog_path,
                )
                for path in args.historical_root.iterdir()
                if path.is_dir()
            }
            historical = parse_historical_archives(
                args.historical_root, account_ids=archive_account_ids,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERRO: {exc}")
            print("Restaure o snapshot via DVC ou use --without-historical conscientemente.")
            return 1

    for account_dir in sorted(args.merged_root.glob("account-*")):
        account_key = account_dir.name.replace("account-", "")
        account_label = account_email("notebooklm", account_dir.name, args.accounts_file) or account_key
        account_id = resolve_account_id("NotebookLM", account_dir.name, args.catalog_path)
        data = _load_account(account_dir, account_key, account_label, account_id)
        merged_combined["notebooks"].extend(data["notebooks"])
        merged_combined["sources"].update(data["sources"])
        merged_combined["source_guides"].update(data.get("source_guides", {}))
        print(f"  {account_dir.name}: {len(data['notebooks'])} notebooks, "
              f"{len(data['sources'])} sources, {len(data.get('source_guides', {}))} source guides")

    print(
        f"  historical archives: {len(historical.conversations)} notebooks, "
        f"{len(historical.messages)} messages, {len(historical.sources)} sources"
    )

    parser = NotebookLMParser()
    stats = parser.parse(
        merged_combined,
        output_dir=args.output_dir,
        historical=historical,
    )
    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nParquets em: {args.output_dir}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
