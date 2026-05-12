"""Asset downloader NotebookLM: tipos de artifacts capturados (via gArtLc):
  type=1 Audio Overview (m4a, lh3 URL)
  type=2 Blog Post / Report (texto via v9rmvd)
  type=3 Video Overview (mp4, lh3 URL em ao[8][1])
  type=4 Flashcards / Quiz (JSON via v9rmvd)
  type=7 Data Table / Framework (via v9rmvd)
  type=8 Slide Deck (PDF+PPTX, contribution.usercontent URLs em ao[16])
  type=9 Infographic (via v9rmvd)

Tambem: mind map (via cFji9 UUID + CYK0Xb fetch), page images de sources (hizoJc).
"""

import asyncio
import json
import re
from pathlib import Path

from src.extractors.notebooklm.api_client import NotebookLMClient


# lh3.googleusercontent.com: audios (type=1), videos (type=3), page images (hizoJc)
NBLM_URL_RE = re.compile(
    r'https://lh3\.googleusercontent\.com/notebooklm/[^"\\,\s\'<>]+'
)
# contribution.usercontent.google.com: slide decks type=8 (PDF+PPTX)
CONTRIB_URL_RE = re.compile(
    r'https://contribution\.usercontent\.google\.com/download\?[^"\\,\s\'<>]+'
)


TYPE_AUDIO = 1
TYPE_BLOG = 2
TYPE_VIDEO = 3
TYPE_FLASHCARDS_OR_QUIZ = 4
TYPE_DATA_TABLE = 7
TYPE_SLIDE_DECK = 8
TYPE_INFOGRAPHIC = 9

# Artifacts que tem conteudo JSON/texto (via v9rmvd, sem URL binaria)
TEXT_ARTIFACT_TYPES = {TYPE_BLOG, TYPE_FLASHCARDS_OR_QUIZ, TYPE_DATA_TABLE, TYPE_INFOGRAPHIC}


def _clean_url(u: str) -> str:
    return u.replace("\\u003d", "=").replace("\\u0026", "&")


def _extract_audio_overviews(artifacts_raw) -> list[dict]:
    """type=1 — podcast m4a. URL em ao[6][2] (ou primeira lh3 encontrada)."""
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return []
    items = artifacts_raw[0] if isinstance(artifacts_raw[0], list) else []
    out = []
    for ao in items:
        if not isinstance(ao, list) or len(ao) < 5:
            continue
        if ao[2] != TYPE_AUDIO:
            continue
        ao_id = ao[0] if isinstance(ao[0], str) else ""
        if not ao_id:
            continue
        title = ao[1] if isinstance(ao[1], str) else ""
        serialized = json.dumps(ao, default=str)
        urls = NBLM_URL_RE.findall(serialized)
        url = _clean_url(urls[0]) if urls else None
        out.append({"id": ao_id, "title": title, "type": TYPE_AUDIO, "url": url})
    return out


def _extract_video_overviews(artifacts_raw) -> list[dict]:
    """type=3 — Video Overview real (mp4 narrado com slides).

    URL em ao[8][1] (lh3 URL — mesma familia dos audios).
    """
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return []
    items = artifacts_raw[0] if isinstance(artifacts_raw[0], list) else []
    out = []
    for ao in items:
        if not isinstance(ao, list) or len(ao) < 5:
            continue
        if ao[2] != TYPE_VIDEO:
            continue
        ao_id = ao[0] if isinstance(ao[0], str) else ""
        if not ao_id:
            continue
        title = ao[1] if isinstance(ao[1], str) else ""
        video_url = None
        if len(ao) > 8 and isinstance(ao[8], list) and len(ao[8]) > 1 and isinstance(ao[8][1], str):
            video_url = _clean_url(ao[8][1])
        if not video_url:
            serialized = json.dumps(ao, default=str)
            urls = NBLM_URL_RE.findall(serialized)
            if urls:
                video_url = _clean_url(urls[0])
        out.append({"id": ao_id, "title": title, "type": TYPE_VIDEO, "url": video_url})
    return out


def _extract_slide_decks(artifacts_raw) -> list[dict]:
    """type=8 — Slide Deck (PDF + PPTX).

    URLs contribution.usercontent em ao[16][-2] (PDF) e ao[16][-1] (PPTX).
    """
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return []
    items = artifacts_raw[0] if isinstance(artifacts_raw[0], list) else []
    out = []
    for ao in items:
        if not isinstance(ao, list) or len(ao) < 5:
            continue
        if ao[2] != TYPE_SLIDE_DECK:
            continue
        ao_id = ao[0] if isinstance(ao[0], str) else ""
        if not ao_id or len(ao) < 17:
            continue
        title = ao[1] if isinstance(ao[1], str) else ""
        block = ao[16]
        if not isinstance(block, list) or len(block) < 4:
            continue
        pdf_url = None
        pptx_url = None
        if isinstance(block[-2], str) and "contribution.usercontent" in block[-2]:
            pdf_url = block[-2]
        if isinstance(block[-1], str) and "contribution.usercontent" in block[-1]:
            pptx_url = block[-1]
        if not pdf_url or not pptx_url:
            serialized = json.dumps(ao, default=str)
            urls = CONTRIB_URL_RE.findall(serialized)
            if urls:
                pdf_url = pdf_url or urls[0]
                if len(urls) > 1:
                    pptx_url = pptx_url or urls[1]
        out.append({
            "id": ao_id,
            "title": title,
            "type": TYPE_SLIDE_DECK,
            "pdf_url": pdf_url,
            "pptx_url": pptx_url,
        })
    return out


def _extract_text_artifacts(artifacts_raw) -> list[dict]:
    """types 2/4/7/9 — Blog, Flashcards/Quiz, Data Table, Infographic.

    Nao tem URL direta — conteudo vem via v9rmvd por UUID. Retorna lista
    de {id, title, type} pra depois fetcher baixar conteudo.
    """
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return []
    items = artifacts_raw[0] if isinstance(artifacts_raw[0], list) else []
    out = []
    for ao in items:
        if not isinstance(ao, list) or len(ao) < 5:
            continue
        ao_type = ao[2] if isinstance(ao[2], int) else 0
        if ao_type not in TEXT_ARTIFACT_TYPES:
            continue
        ao_id = ao[0] if isinstance(ao[0], str) else ""
        if not ao_id:
            continue
        title = ao[1] if isinstance(ao[1], str) else ""
        out.append({"id": ao_id, "title": title, "type": ao_type})
    return out


def _extract_notes_and_mindmaps(notes_raw) -> tuple[list[dict], list[dict]]:
    """Separa items do cFji9 em briefs/notes (texto) e mind maps (JSON tree inline).

    Schema notes_raw:
        [
            [
                [uuid, [uuid, texto_descritivo, [tipo, num, ts], None, titulo]],
                [uuid, [uuid, '{"name":..., "children":...}']],  # mind map JSON inline
                ...
            ],
            [ts]
        ]

    Diferencia: mind map começa com '{' no primeiro char do texto, briefs sao texto narrativo.
    Retorna (notes, mind_maps) onde cada item e dict.
    """
    notes, mind_maps = [], []
    if not isinstance(notes_raw, list) or not notes_raw:
        return notes, mind_maps
    items = notes_raw[0] if isinstance(notes_raw[0], list) else []
    if not isinstance(items, list):
        return notes, mind_maps
    for it in items:
        if not (isinstance(it, list) and len(it) >= 2):
            continue
        uuid = it[0] if isinstance(it[0], str) else None
        inner = it[1] if isinstance(it[1], list) and len(it[1]) >= 2 else None
        if not (uuid and inner):
            continue
        content = inner[1] if len(inner) >= 2 and isinstance(inner[1], str) else ""
        # Mind map: JSON object
        stripped = content.lstrip()
        if stripped.startswith("{"):
            try:
                tree = json.loads(content)
                mind_maps.append({"uuid": uuid, "tree": tree})
                continue
            except Exception:
                pass
        # Note/brief: texto
        title = inner[4] if len(inner) > 4 and isinstance(inner[4], str) else ""
        notes.append({"uuid": uuid, "content": content, "title": title})
    return notes, mind_maps


def _extract_audio_urls(artifacts_raw) -> list[dict]:
    """Retro-compat: retorna so audios (type=1)."""
    return _extract_audio_overviews(artifacts_raw)


def _extract_page_images(source_content_raw) -> list[dict]:
    """Do hizoJc response extrai [{page_uuid, url, start_offset}] de paginas renderizadas.

    Chunks com URL em vez de texto representam paginas renderizadas de PDFs.
    Schema observado: chunk = [start, end, [[[start, end, null, [URL, null, page_uuid]]]]]
    """
    if not isinstance(source_content_raw, list) or len(source_content_raw) < 4:
        return []
    # data[3][0][0] = lista de chunks
    try:
        chunks = source_content_raw[3][0][0]
    except (IndexError, TypeError):
        return []
    if not isinstance(chunks, list):
        return []
    pages = []
    for chunk in chunks:
        if not isinstance(chunk, list) or len(chunk) < 3:
            continue
        start = chunk[0]
        inner = chunk[2]
        if not isinstance(inner, list) or not inner:
            continue
        first = inner[0]
        if not isinstance(first, list) or not first:
            continue
        f0 = first[0]
        # Imagem: f0 = [start, end, null, [URL, null, page_uuid]]
        if isinstance(f0, list) and len(f0) >= 4 and isinstance(f0[3], list) and f0[3]:
            url = f0[3][0] if isinstance(f0[3][0], str) else None
            if url and "googleusercontent.com/notebooklm" in url:
                page_uuid = f0[3][2] if len(f0[3]) > 2 and isinstance(f0[3][2], str) else None
                clean = url.replace("\\u003d", "=").replace("\\u0026", "&")
                pages.append({"page_uuid": page_uuid, "url": clean, "start_offset": start})
    return pages


async def download_assets(
    client: NotebookLMClient,
    raw_dir: Path,
    concurrency: int = 8,
    skip_existing: bool = True,
) -> dict:
    """Varre notebooks/*.json + sources/*.json, baixa todos os artifacts de midia:
    audio overviews, video overviews (mp4), slide decks (PDF+PPTX), page images.

    Text artifacts (Blog, Flashcards, Quiz, Data Table, Infographic) e Mind Maps
    sao fetchados via fetch_text_artifacts() em funcao separada.
    """
    assets_dir = raw_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "audios_downloaded": 0, "audios_skipped": 0,
        "videos_downloaded": 0, "videos_skipped": 0,
        "slide_decks_downloaded": 0, "slide_decks_skipped": 0,
        "pages_downloaded": 0, "pages_skipped": 0,
        "errors": [],
    }

    targets: list[tuple[str, Path, str]] = []

    nb_dir = raw_dir / "notebooks"
    if nb_dir.exists():
        for jp in nb_dir.glob("*.json"):
            try:
                with open(jp, encoding="utf-8") as f:
                    nb = json.load(f)
            except Exception:
                continue
            nb_uuid = nb.get("uuid", jp.stem)
            # Nome "audios" mantido retro-compat — ja e o response completo de gArtLc
            artifacts_raw = nb.get("audios")

            # type=1 Audio Overview (m4a)
            for a in _extract_audio_overviews(artifacts_raw):
                if not a.get("url"):
                    continue
                fname = assets_dir / "audio_overviews" / f"{nb_uuid}_{a['id']}.m4a"
                targets.append((a["url"], fname, "audio"))

            # type=3 Video Overview (mp4)
            for v in _extract_video_overviews(artifacts_raw):
                if not v.get("url"):
                    continue
                fname = assets_dir / "video_overviews" / f"{nb_uuid}_{v['id']}.mp4"
                targets.append((v["url"], fname, "video"))

            # type=8 Slide Deck (PDF + PPTX)
            for s in _extract_slide_decks(artifacts_raw):
                deck_dir = assets_dir / "slide_decks" / f"{nb_uuid}_{s['id']}"
                if s.get("pdf_url"):
                    targets.append((s["pdf_url"], deck_dir / "detailed_deck.pdf", "slide_deck"))
                if s.get("pptx_url"):
                    targets.append((s["pptx_url"], deck_dir / "presenter_slides.pptx", "slide_deck"))

    # Page images (PDF rendered) de sources
    src_dir = raw_dir / "sources"
    if src_dir.exists():
        for jp in src_dir.glob("*.json"):
            try:
                with open(jp, encoding="utf-8") as f:
                    s = json.load(f)
            except Exception:
                continue
            pages = _extract_page_images(s.get("raw"))
            suid = s.get("source_uuid", jp.stem)
            pages_dir = assets_dir / "source_pages" / suid
            for i, p in enumerate(pages):
                fname = pages_dir / f"page_{i:03d}_{p.get('page_uuid', 'x')}.webp"
                targets.append((p["url"], fname, "page"))

    print(f"Encontrados {len(targets)} assets pra baixar", flush=True)

    sem = asyncio.Semaphore(concurrency)

    KIND_TIMEOUT = {"audio": 300000, "video": 600000, "slide_deck": 180000, "page": 60000}
    KIND_STAT = {
        "audio": ("audios_downloaded", "audios_skipped"),
        "video": ("videos_downloaded", "videos_skipped"),
        "slide_deck": ("slide_decks_downloaded", "slide_decks_skipped"),
        "page": ("pages_downloaded", "pages_skipped"),
    }

    progress = {"done": 0, "errors_logged": 0}
    total = len(targets)

    async def _one(url: str, fname: Path, kind: str):
        fname.parent.mkdir(parents=True, exist_ok=True)
        dl_key, skip_key = KIND_STAT[kind]
        if skip_existing and fname.exists() and fname.stat().st_size > 0:
            stats[skip_key] += 1
        else:
            async with sem:
                try:
                    timeout = KIND_TIMEOUT[kind]
                    blob = await client.download_asset(url, timeout_ms=timeout)
                    if blob is None:
                        msg = f"{kind} HTTP error"
                        stats["errors"].append((str(fname.name), msg))
                        if progress["errors_logged"] < 5:
                            print(f"  ERR {fname.name}: {msg}", flush=True)
                            progress["errors_logged"] += 1
                    else:
                        fname.write_bytes(blob)
                        stats[dl_key] += 1
                except Exception as e:
                    msg = f"{kind}: {str(e)[:120]}"
                    stats["errors"].append((str(fname.name), msg))
                    if progress["errors_logged"] < 5:
                        print(f"  ERR {fname.name}: {msg}", flush=True)
                        progress["errors_logged"] += 1
        progress["done"] += 1
        # Throttle baixo (a cada 10) pra dashboard ver progresso vivo;
        # runs pequenos (poucos audios) nunca atingiriam 200 antes do final.
        if progress["done"] % 10 == 0 or progress["done"] == total:
            print(
                f"  progresso: {progress['done']}/{total} "
                f"(audios dl={stats['audios_downloaded']} skip={stats['audios_skipped']}, "
                f"videos dl={stats['videos_downloaded']} skip={stats['videos_skipped']}, "
                f"pages dl={stats['pages_downloaded']} skip={stats['pages_skipped']}, "
                f"errors={len(stats['errors'])})",
                flush=True,
            )

    await asyncio.gather(*(_one(u, f, k) for u, f, k in targets))
    return stats


def save_notes_and_mindmaps(raw_dir: Path, skip_existing: bool = True) -> dict:
    """Extrai notes+briefs+mind maps do cFji9 ja capturado (offline, sem rede).

    Salva:
      assets/notes/<nb_uuid>_<note_uuid>.md  (text + title metadata)
      assets/mind_maps/<nb_uuid>_<mm_uuid>.json (arvore JSON)
    """
    assets_dir = raw_dir / "assets"
    stats = {
        "notes_saved": 0, "notes_skipped": 0,
        "mind_maps_saved": 0, "mind_maps_skipped": 0,
        "errors": [],
    }
    nb_dir = raw_dir / "notebooks"
    if not nb_dir.exists():
        return stats

    for jp in nb_dir.glob("*.json"):
        try:
            nb = json.loads(jp.read_text(encoding="utf-8"))
        except Exception as e:
            stats["errors"].append((jp.name, f"load: {str(e)[:100]}"))
            continue
        nb_uuid = nb.get("uuid", jp.stem)
        notes, mind_maps = _extract_notes_and_mindmaps(nb.get("notes"))

        for n in notes:
            out = assets_dir / "notes" / f"{nb_uuid}_{n['uuid']}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            if skip_existing and out.exists() and out.stat().st_size > 0:
                stats["notes_skipped"] += 1
                continue
            try:
                md = f"# {n.get('title') or 'Untitled note'}\n\n{n['content']}\n"
                out.write_text(md, encoding="utf-8")
                stats["notes_saved"] += 1
            except Exception as e:
                stats["errors"].append((out.name, str(e)[:100]))

        for mm in mind_maps:
            out = assets_dir / "mind_maps" / f"{nb_uuid}_{mm['uuid']}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            if skip_existing and out.exists() and out.stat().st_size > 0:
                stats["mind_maps_skipped"] += 1
                continue
            try:
                out.write_text(
                    json.dumps({"notebook_uuid": nb_uuid, "mind_map_uuid": mm["uuid"],
                                "tree": mm["tree"]}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                stats["mind_maps_saved"] += 1
            except Exception as e:
                stats["errors"].append((out.name, str(e)[:100]))
    return stats


async def fetch_text_artifacts(
    client: NotebookLMClient,
    raw_dir: Path,
    concurrency: int = 5,
    skip_existing: bool = True,
) -> dict:
    """Fetch text artifacts (types 2/4/7/9) via v9rmvd.

    Salva assets/text_artifacts/<nb>_<id>_type<N>.json
    """
    assets_dir = raw_dir / "assets"
    stats = {
        "text_artifacts_fetched": 0, "text_artifacts_skipped": 0,
        "errors": [],
    }
    nb_dir = raw_dir / "notebooks"
    if not nb_dir.exists():
        return stats

    targets: list[tuple[str, str, int, Path]] = []
    for jp in nb_dir.glob("*.json"):
        try:
            nb = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        nb_uuid = nb.get("uuid", jp.stem)
        for t in _extract_text_artifacts(nb.get("audios")):
            out = assets_dir / "text_artifacts" / f"{nb_uuid}_{t['id']}_type{t['type']}.json"
            targets.append((nb_uuid, t["id"], t["type"], out))

    sem = asyncio.Semaphore(concurrency)

    async def _one(nb_uuid: str, art_id: str, art_type: int, out: Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        if skip_existing and out.exists() and out.stat().st_size > 0:
            stats["text_artifacts_skipped"] += 1
            return
        async with sem:
            try:
                data = await client.fetch_artifact(nb_uuid, art_id)
                if data is None:
                    stats["errors"].append((out.name, "fetch_artifact None"))
                    return
                out.write_text(
                    json.dumps({"type": art_type, "artifact_id": art_id,
                                "notebook_uuid": nb_uuid, "content": data},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                stats["text_artifacts_fetched"] += 1
            except Exception as e:
                stats["errors"].append((out.name, str(e)[:150]))

    await asyncio.gather(*(_one(n, a, t, o) for n, a, t, o in targets))
    return stats


