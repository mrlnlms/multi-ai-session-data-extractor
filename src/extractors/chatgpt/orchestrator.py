"""Orchestrator — amarra auth + discovery + fetcher + dom_voice + save.

Entry point chamado por scripts/chatgpt-export.py.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from src.extractors.chatgpt.api_client import ChatGPTAPIClient
from src.extractors.chatgpt.auth import get_profile_dir
from src.extractors.chatgpt.discovery import discover_all
from src.extractors.chatgpt.dom_voice import capture_voice_dom, detect_voice_candidates
from src.extractors.chatgpt.fetcher import fetch_all
from src.extractors.chatgpt.models import CaptureOptions, CaptureReport

logger = logging.getLogger(__name__)


async def run_capture(output_dir: Path, options: CaptureOptions) -> CaptureReport:
    """Roda captura completa do ChatGPT.

    Args:
        output_dir: diretorio datado onde salvar (ex: data/raw/ChatGPT Data 2026-04-23/).
                    Se existir, adiciona sufixo de hora pra nao sobrescrever.
        options: flags CLI.

    Returns:
        CaptureReport com counts, duration, errors.
    """
    output_dir = _resolve_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc)
    report = CaptureReport(
        run_started_at=started_at.isoformat(),
        run_finished_at="",
        duration_seconds=0.0,
    )

    profile_dir = get_profile_dir()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        client = ChatGPTAPIClient(context.request)

        # Discovery
        logger.info("Discovery...")
        metas, project_names = await discover_all(client, page=page)
        report.discovery_counts = {"total": len(metas)}

        # Salva IDs da discovery (permite diff contra fetched pra achar falhas)
        discovery_path = output_dir / "discovery_ids.json"
        with open(discovery_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "captured_at": started_at.isoformat(),
                    "total": len(metas),
                    "ids": [m.id for m in metas],
                },
                f, ensure_ascii=False, indent=2,
            )
        logger.info(f"Discovery IDs salvos em {discovery_path}")

        if options.dry_run:
            logger.info(f"DRY RUN — descoberta retornou {len(metas)} convs. Abortando.")
            _finalize_report(report, started_at)
            return report

        # Decide fetch targets:
        # - --full: brute force (fetcha tudo)
        # - senao, tenta achar captura anterior: se acha, incremental; se nao, brute force
        prev_raw: dict[str, dict] = {}
        if options.full:
            logger.info("Modo: completo (--full) — fetcha todas as convs")
            ids_to_fetch = [m.id for m in metas]
        else:
            last = _find_last_capture(output_dir.parent)
            if last is None:
                logger.info("Nenhuma captura anterior — modo completo (primeira run)")
                ids_to_fetch = [m.id for m in metas]
            else:
                prev_dir, cutoff_dt = last
                prev_raw_path = prev_dir / "chatgpt_raw.json"
                logger.info(
                    f"Modo incremental: base={prev_dir.name}, "
                    f"cutoff={cutoff_dt.isoformat()}"
                )
                prev_raw = _load_previous_raw(prev_raw_path)
                ids_to_fetch = _filter_incremental_targets(
                    metas, prev_raw, cutoff_dt
                )
                logger.info(
                    f"Incremental: {len(ids_to_fetch)} convs a fetchar "
                    f"(de {len(metas)} na discovery)"
                )

        # Fetch
        logger.info(f"Fetch de {len(ids_to_fetch)} convs...")
        raws = await fetch_all(client, ids_to_fetch, on_progress=_log_progress)
        report.fetch_counts = {
            "attempted": len(ids_to_fetch),
            "succeeded": len(raws),
            "total_discovered": len(metas),
        }

        # Monta raw final: unchanged do prev_raw (se incremental) + fetched novos
        today = started_at.strftime("%Y-%m-%d")
        final_raws: dict[str, dict] = {}
        discovery_ids = {m.id for m in metas}

        if prev_raw:
            # Copia unchanged: convs que estao na discovery mas nao foram fetchadas.
            # Convs que sumiram da discovery (deletadas no servidor) NAO vao pro raw
            # novo — o reconciler detecta via previous_ids - current_ids e preserva no
            # merged (contrato: raw reflete o servidor, merged preserva historico).
            unchanged_count = 0
            for cid, conv in prev_raw.items():
                if cid in discovery_ids and cid not in raws:
                    final_raws[cid] = conv
                    final_raws[cid]["_last_seen_in_server"] = today
                    unchanged_count += 1
            logger.info(f"Incremental: {unchanged_count} convs copiadas do raw anterior sem fetch")

        # Sobrescreve com fetched (sejam novos ou atualizados) + enriquece metadata
        for meta in metas:
            if meta.id in raws:
                raws[meta.id]["_archived"] = meta.archived
                raws[meta.id]["_project_id"] = meta.project_id
                raws[meta.id]["_project_name"] = (
                    project_names.get(meta.project_id) if meta.project_id else None
                )
                raws[meta.id]["_last_seen_in_server"] = today
                final_raws[meta.id] = raws[meta.id]

        # Enriquece tambem convs do prev_raw que nao foram refetchadas
        # (senao elas ficam com _project_name antigo/ausente)
        if prev_raw:
            for cid, conv in final_raws.items():
                if cid not in raws:  # so as que vieram do prev_raw
                    pid = conv.get("_project_id")
                    if pid and project_names.get(pid):
                        conv["_project_name"] = project_names[pid]

        # Salva raw
        raw_path = output_dir / "chatgpt_raw.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(
                {"captured_at": started_at.isoformat(), "conversations": final_raws},
                f, ensure_ascii=False, indent=2,
            )
        logger.info(f"Raw salvo em {raw_path} ({len(final_raws)} convs)")
        # raws usado abaixo (voice pass) deve conter conteúdo útil — usa final_raws
        raws = final_raws

        # Voice pass (se nao skipado)
        if not options.skip_voice:
            candidates = detect_voice_candidates({"conversations": raws})
            logger.info(f"Voice pass: {len(candidates)} candidatos")
            if candidates:
                voice_data = await capture_voice_dom(page, candidates)
                voice_path = output_dir / "chatgpt_voice_dom.json"
                with open(voice_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "captured_at": started_at.isoformat(),
                            "conversations": {
                                cid: {
                                    "title": cap.title,
                                    "messages": [
                                        {
                                            "dom_sequence": m.dom_sequence,
                                            "role": m.role,
                                            "text": m.text,
                                            "duration_seconds": m.duration_seconds,
                                            "was_voice": m.was_voice,
                                        } for m in cap.messages
                                    ],
                                }
                                for cid, cap in voice_data.items()
                            },
                        },
                        f, ensure_ascii=False, indent=2,
                    )
                report.voice_pass_counts = {
                    "candidates": len(candidates),
                    "captured": len(voice_data),
                }
            else:
                report.voice_pass_counts = {"candidates": 0, "captured": 0}

        # Memories + Instructions
        try:
            memories = await client.fetch_memories()
            (output_dir / "chatgpt_memories.md").write_text(memories, encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Memories fetch falhou: {exc}")

        try:
            instructions = await client.fetch_instructions()
            (output_dir / "chatgpt_instructions.json").write_text(
                json.dumps(instructions, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning(f"Instructions fetch falhou: {exc}")

        await context.close()

    _finalize_report(report, started_at)

    # Salva capture_log.json — try/finally garante gravacao mesmo se algo falhar acima
    try:
        log_path = output_dir / "capture_log.json"
        log_path.write_text(
            json.dumps(
                {
                    "run_started_at": report.run_started_at,
                    "run_finished_at": report.run_finished_at,
                    "duration_seconds": report.duration_seconds,
                    "discovery": report.discovery_counts,
                    "fetch": report.fetch_counts,
                    "voice_pass": report.voice_pass_counts,
                    "errors": report.errors,
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as log_exc:
        logger.error(f"Falha gravando capture_log.json: {log_exc}")

    return report


def _resolve_output_dir(base: Path) -> Path:
    """Se base ja existe, adiciona sufixo de hora pra nao sobrescrever."""
    if not base.exists():
        return base
    hour = datetime.now().strftime("T%H-%M")
    return base.parent / f"{base.name}{hour}"


def _finalize_report(report: CaptureReport, started_at: datetime) -> None:
    finished = datetime.now(timezone.utc)
    report.run_finished_at = finished.isoformat()
    report.duration_seconds = (finished - started_at).total_seconds()


def _log_progress(fetched: int, total: int) -> None:
    pct = (fetched / total * 100) if total else 0
    logger.info(f"  Fetched {fetched}/{total} ({pct:.0f}%)")


def _parse_ts(v) -> float:
    """Normaliza timestamp (ISO string, float epoch, None) pra epoch."""
    if v is None or v == 0 or v == 0.0:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0.0
    return 0.0


def _find_last_capture(raw_root: Path) -> tuple[Path, datetime] | None:
    """Acha o ultimo ChatGPT Data */ com chatgpt_raw.json + capture_log.json.

    Retorna (path_do_dir, run_started_at) do mais recente por run_started_at.
    """
    if not raw_root.exists():
        return None
    candidates: list[tuple[datetime, Path]] = []
    for d in raw_root.iterdir():
        if not d.is_dir() or not d.name.startswith("ChatGPT Data"):
            continue
        log = d / "capture_log.json"
        raw = d / "chatgpt_raw.json"
        if not log.exists() or not raw.exists():
            continue
        try:
            with open(log) as f:
                data = json.load(f)
            started = data.get("run_started_at")
            if not started:
                continue
            ts = datetime.fromisoformat(started.replace("Z", "+00:00"))
            candidates.append((ts, d))
        except Exception as exc:
            logger.warning(f"Skip {d.name}: {exc}")
    if not candidates:
        return None
    ts, path = max(candidates, key=lambda x: x[0])
    return path, ts


def _load_previous_raw(path: Path) -> dict[str, dict]:
    """Carrega chatgpt_raw.json retornando {id: conv}."""
    with open(path) as f:
        data = json.load(f)
    return data.get("conversations", {})


def _filter_incremental_targets(
    metas: list, prev_raw: dict[str, dict], cutoff: datetime
) -> list[str]:
    """Retorna IDs pra fetchar: novos (nao estao em prev_raw) + update_time > cutoff."""
    cutoff_epoch = cutoff.timestamp()
    targets: list[str] = []
    for m in metas:
        if m.id not in prev_raw:
            targets.append(m.id)
            continue
        meta_ut = _parse_ts(m.update_time)
        if meta_ut > cutoff_epoch:
            targets.append(m.id)
    return targets
