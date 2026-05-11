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
from src.extractors.chatgpt.refetch_known import refetch_known_via_page

logger = logging.getLogger(__name__)


# Quando discovery cai mais que isso vs maior valor historico, o orchestrator
# nao confia no listing e cai pra refetch_known via /conversations/batch (caminho
# que nao depende de discovery — pega pelos IDs ja salvos no raw cumulativo).
# Threshold mantido pra evitar falso-fallback (oscilacoes pequenas sao normais).
DISCOVERY_DROP_FALLBACK_THRESHOLD = 0.20
# Alias retro-compat (codigo/testes antigos referenciam pelo nome velho)
DISCOVERY_DROP_ABORT_THRESHOLD = DISCOVERY_DROP_FALLBACK_THRESHOLD


def _get_max_known_discovery(raw_root: Path) -> int:
    """Procura recursivamente o maior discovery.total ja visto em qualquer capture_log.

    Recursivo de proposito — pega tambem capture_logs em subpastas (ex: _backup-*),
    pra que mover raws antigos pra subpasta nao reseta a baseline.

    Aceita capture_log.jsonl (formato novo, append-only) varrendo todas as linhas,
    e capture_log.json (formato antigo, snapshot) durante transicao.
    """
    if not raw_root.exists():
        return 0
    max_count = 0
    # Formato novo: jsonl com 1 linha por run
    for log_path in raw_root.rglob("capture_log.jsonl"):
        try:
            with open(log_path) as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    count = (data.get("discovery") or {}).get("total", 0)
                    if count > max_count:
                        max_count = count
        except Exception:
            continue
    # Formato antigo: snapshot json
    for log_path in raw_root.rglob("capture_log.json"):
        try:
            with open(log_path) as f:
                data = json.load(f)
            count = (data.get("discovery") or {}).get("total", 0)
            if count > max_count:
                max_count = count
        except Exception:
            continue
    return max_count


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
            # headless=False eh necessario empiricamente (re-validado 2026-05-11):
            # 1. DOM scrape headless: nav "More" menu nao responde a click
            #    (Locator.wait_for timeout em headless).
            # 2. API headless: /api/auth/session devolve HTML do Cloudflare
            #    challenge ("Just a moment...") em vez do JSON com accessToken,
            #    bloqueando ate o refetch_known via page.evaluate.
            # Asset_downloader.py roda headless OK porque usa context.request
            # (cookies herdados da sessao headed previa) — esse caminho passa.
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        client = ChatGPTAPIClient(context.request)

        # Discovery
        logger.info("Discovery...")
        metas, project_names = await discover_all(client, page=page)
        report.discovery_counts = {"total": len(metas)}

        # Discovery parcial vira fallback automatico pra refetch_known.
        # /conversations listing as vezes retorna paginacao incompleta — em vez de
        # confiar nesse listing reduzido (e marcar centenas como deletadas), cai
        # pra refetch_known via /conversations/batch usando os IDs ja salvos no raw.
        baseline = _get_max_known_discovery(output_dir)
        if baseline > 0:
            drop = (baseline - len(metas)) / baseline
            if drop > DISCOVERY_DROP_FALLBACK_THRESHOLD:
                logger.warning(
                    f"Discovery parcial: {len(metas)} convs vs {baseline} no historico "
                    f"(queda {drop:.0%}). Caindo pra refetch_known via /conversations/batch."
                )
                stats = await refetch_known_via_page(page, output_dir)
                report.discovery_counts = {"total": stats["total"]}
                report.fetch_counts = {
                    "attempted": stats["total"],
                    "succeeded": stats["updated"],
                    "total_discovered": stats["total"],
                }
                report.mode = "refetch_known_fallback"
                if stats["errors"]:
                    report.errors.append({
                        "stage": "refetch_known_fallback",
                        "count": stats["errors"],
                    })
                await context.close()
                _finalize_report(report, started_at)
                _append_capture_log(output_dir, report)
                _write_last_capture_md(output_dir, report)
                return report
            logger.info(f"Discovery OK: {len(metas)} convs (baseline historico: {baseline})")

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
            last = _find_last_capture(output_dir)
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

        try:
            pinned_gizmos = await client.list_pinned_gizmos()
            (output_dir / "gizmos_pinned.json").write_text(
                json.dumps(pinned_gizmos, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning(f"Pinned gizmos fetch falhou: {exc}")

        await context.close()

    _finalize_report(report, started_at)
    _append_capture_log(output_dir, report)
    try:
        _write_last_capture_md(output_dir, report)
    except Exception as md_exc:
        logger.error(f"Falha gravando LAST_CAPTURE.md: {md_exc}")

    return report


def _append_capture_log(output_dir: Path, report: CaptureReport) -> None:
    """Append 1 linha JSON em capture_log.jsonl com totals da run."""
    try:
        log_entry = {
            "run_started_at": report.run_started_at,
            "run_finished_at": report.run_finished_at,
            "duration_seconds": report.duration_seconds,
            "mode": report.mode,
            "discovery": report.discovery_counts,
            "fetch": report.fetch_counts,
            "voice_pass": report.voice_pass_counts,
            "errors": report.errors,
        }
        log_path = output_dir / "capture_log.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception as log_exc:
        logger.error(f"Falha gravando capture_log.jsonl: {log_exc}")


def _write_last_capture_md(output_dir: Path, report: CaptureReport) -> None:
    """Gera LAST_CAPTURE.md visivel — bate o olho e ve quando + counts."""
    discovery = report.discovery_counts or {}
    fetch = report.fetch_counts or {}
    voice = report.voice_pass_counts or {}
    errors_n = len(report.errors) if report.errors else 0
    md = (
        "# Last capture\n\n"
        f"- **Quando:** {report.run_started_at}\n"
        f"- **Duracao:** {report.duration_seconds:.0f}s\n"
        f"- **Discovery total:** {discovery.get('total', 0)}\n"
        f"- **Fetch attempted:** {fetch.get('attempted', 0)}\n"
        f"- **Fetch succeeded:** {fetch.get('succeeded', 0)}\n"
        f"- **Voice pass:** candidates={voice.get('candidates', 0)}, captured={voice.get('captured', 0)}\n"
        f"- **Errors:** {errors_n}\n\n"
        "Ver `capture_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")


def _resolve_output_dir(base: Path) -> Path:
    """Pasta unica cumulativa — sempre retorna o mesmo path.

    Antes (deprecado): adicionava sufixo de hora se a pasta ja existisse.
    Agora: a pasta eh mutavel in-place, todas as runs gravam aqui.
    """
    return base


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


def _find_last_capture(raw_dir: Path) -> tuple[Path, datetime] | None:
    """Verifica se a pasta unica tem captura previa valida.

    Pasta unica cumulativa: ou existe chatgpt_raw.json + capture_log.jsonl, ou nao
    ha captura previa. Retorna (path, run_started_at_da_ultima_run) ou None.

    Backward compat: aceita capture_log.json (formato antigo) durante transicao.
    """
    if not raw_dir.exists() or not raw_dir.is_dir():
        return None
    raw = raw_dir / "chatgpt_raw.json"
    if not raw.exists():
        return None

    log_jsonl = raw_dir / "capture_log.jsonl"
    log_json = raw_dir / "capture_log.json"
    started_iso: str | None = None
    try:
        if log_jsonl.exists():
            last_line = None
            with open(log_jsonl) as f:
                for line in f:
                    if line.strip():
                        last_line = line
            if last_line:
                started_iso = json.loads(last_line).get("run_started_at")
        elif log_json.exists():
            with open(log_json) as f:
                started_iso = json.load(f).get("run_started_at")
    except Exception as exc:
        logger.warning(f"Falha lendo log de captura em {raw_dir}: {exc}")
        return None
    if not started_iso:
        return None
    try:
        ts = datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
    except Exception:
        return None
    return raw_dir, ts


def _load_previous_raw(path: Path) -> dict[str, dict]:
    """Carrega chatgpt_raw.json retornando {id: conv}."""
    with open(path) as f:
        data = json.load(f)
    return data.get("conversations", {})


def _filter_incremental_targets(
    metas: list, prev_raw: dict[str, dict], cutoff: datetime
) -> list[str]:
    """Retorna IDs pra fetchar: novos + update_time > cutoff + title-renamed.

    Title rename: se a discovery retorna title diferente do que temos no
    prev_raw local, forca refetch mesmo se update_time nao mudou. Guarda contra
    o caso onde o servidor nao bumpa update_time em rename (nao validado
    empiricamente — guardrail preventivo).
    """
    cutoff_epoch = cutoff.timestamp()
    targets: list[str] = []
    for m in metas:
        if m.id not in prev_raw:
            targets.append(m.id)
            continue
        meta_ut = _parse_ts(m.update_time)
        if meta_ut > cutoff_epoch:
            targets.append(m.id)
            continue
        # Rename detection: discovery tem title diferente do raw local
        if m.title and m.title != prev_raw[m.id].get("title"):
            targets.append(m.id)
    return targets
