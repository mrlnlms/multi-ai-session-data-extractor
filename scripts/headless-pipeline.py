#!/usr/bin/env python
"""CLI orquestrador do pipeline 4-stage — roda sem Streamlit, util pra cron/launchd.

Default: 10 plats que rodam headless (sem browser visivel) — exclui ChatGPT
e Perplexity que precisam de Cloudflare interativo.

Uso:
    # 10 plats headless + publish (default)
    PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py

    # Subset especifico, sem publish
    PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py \\
        --plats=Claude.ai,Gemini --no-publish

    # Inclui ChatGPT (vai abrir browser — so funciona com $DISPLAY OK)
    PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py \\
        --plats=ChatGPT,Claude.ai

Exit codes:
    0  pipeline OK (talvez com falhas parciais de plats em stage 1, mas
       stages 2-4 OK)
    1  pipeline falhou em algum stage critico (2/3/4) ou todas plats falharam
    2  erro de invocacao (sem plats sincronizaveis, lockfile ocupado)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from dashboard.data import KNOWN_PLATFORMS
from dashboard.pipeline import STAGE_KEYS, commit_msg_for_scope, persist_run
from dashboard.sync import (
    acquire_pipeline_lock,
    quarto_installed,
    release_pipeline_lock,
    run_publish_streaming,
    run_quarto_streaming,
    run_sync_streaming,
    run_unify_streaming,
    sync_command,
)


# Plats que exigem browser visivel (Cloudflare detecta headless e 403/challenge).
# Derivado de KNOWN_PLATFORMS pra evitar drift quando nova plat for adicionada.
_HEADED_REQUIRED = {"ChatGPT", "Perplexity"}
HEADLESS_DEFAULT = [p for p in KNOWN_PLATFORMS if p not in _HEADED_REQUIRED]


def _log(line: str) -> None:
    """Print com timestamp ISO. Stdout-only (cron/launchd redireciona pra log)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} {line}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--plats",
        default=",".join(HEADLESS_DEFAULT),
        help=f"Lista CSV. Default = 10 headless: {','.join(HEADLESS_DEFAULT)}",
    )
    p.add_argument("--no-publish", action="store_true", help="Pula Stage 4 (DVC + git push).")
    args = p.parse_args()

    plat_names = [p.strip() for p in args.plats.split(",") if p.strip()]
    targets = [p for p in plat_names if sync_command(p)]
    skipped = [p for p in plat_names if not sync_command(p)]

    if not targets:
        _log(f"ERROR: no syncable plats in {plat_names}")
        return 2

    if skipped:
        _log(f"warning: skipping {skipped} (no sync/export script)")

    publish_after = not args.no_publish
    _log(f"=== Pipeline starting: {len(targets)} plats, publish={publish_after} ===")
    _log(f"plats: {targets}")

    lock_err = acquire_pipeline_lock()
    if lock_err:
        _log(f"ERROR: {lock_err}")
        return 2

    try:
        return _run(targets, publish_after)
    finally:
        release_pipeline_lock()


def _run(targets: list[str], publish_after: bool) -> int:
    stage_status = ["pending"] * 4
    if not publish_after:
        stage_status[3] = "skipped"
    results: list[dict] = []

    def _persist():
        persist_run(stage_status, results, publish_after, scope="cli:headless")

    # =================== Stage 1/4 — Sync ===================
    _log(f"=== Stage 1/4 — Sync ({len(targets)} plats) ===")
    stage_status[0] = "running"
    any_ok = False
    any_fail = False
    for i, plat in enumerate(targets, 1):
        _log(f"--- [{i}/{len(targets)}] {plat} ---")
        try:
            rc, tail = run_sync_streaming(plat, on_line=_log)
        except Exception as e:  # noqa: BLE001
            rc, tail = -1, f"exception: {e}"
        status = "ok" if rc == 0 else "failed"
        results.append({
            "stage": STAGE_KEYS[0], "step": plat, "status": status,
            "detail": "" if rc == 0 else f"rc={rc}", "tail": tail[-10000:],
        })
        if rc == 0:
            any_ok = True
            _log(f"  ok: {plat}")
        else:
            any_fail = True
            _log(f"  FAIL: {plat} (rc={rc})")

    if not any_ok:
        stage_status[0] = "failed"
        for idx in (1, 2):
            stage_status[idx] = "aborted"
        if publish_after:
            stage_status[3] = "aborted"
        _log("=== ALL plats failed in Stage 1 — aborting ===")
        _persist()
        return 1

    stage_status[0] = "failed" if any_fail else "done"

    # =================== Stage 2/4 — Unify ===================
    _log("=== Stage 2/4 — Unify parquets ===")
    stage_status[1] = "running"
    try:
        rc, unify_tail = run_unify_streaming(_log)
    except Exception as e:  # noqa: BLE001
        rc, unify_tail = -1, f"exception: {e}"

    if rc != 0:
        stage_status[1] = "failed"
        stage_status[2] = "aborted"
        if publish_after:
            stage_status[3] = "aborted"
        results.append({
            "stage": STAGE_KEYS[1], "step": "unify-parquets", "status": "failed",
            "detail": f"rc={rc}", "tail": unify_tail[-10000:],
        })
        _log(f"=== Stage 2 failed (rc={rc}) — aborting ===")
        _persist()
        return 1

    stage_status[1] = "done"
    results.append({
        "stage": STAGE_KEYS[1], "step": "unify-parquets", "status": "ok",
        "detail": "", "tail": "",
    })
    _log("  ok: unify")

    # =================== Stage 3/4 — Quarto ===================
    _log("=== Stage 3/4 — Quarto render ===")
    stage3_ok = True
    if not quarto_installed():
        stage_status[2] = "skipped"
        results.append({
            "stage": STAGE_KEYS[2], "step": "quarto-render", "status": "skipped",
            "detail": "quarto CLI not installed", "tail": "",
        })
        _log("  skipped: quarto CLI not in PATH")
    else:
        stage_status[2] = "running"
        # CLI roda render filtrado pras plats sincronizadas + cross-overview.
        # Mesma logica do dashboard pra Stage 3 incremental.
        try:
            rc, q_summary = run_quarto_streaming(_log, platforms_filter=targets)
        except Exception as e:  # noqa: BLE001
            rc, q_summary = -1, f"exception: {e}"

        if rc != 0:
            stage_status[2] = "failed"
            stage3_ok = False
            results.append({
                "stage": STAGE_KEYS[2], "step": "quarto-render", "status": "failed",
                "detail": q_summary[:300], "tail": q_summary[-10000:],
            })
            _log(f"  FAIL: quarto ({q_summary})")
        else:
            stage_status[2] = "done"
            results.append({
                "stage": STAGE_KEYS[2], "step": "quarto-render", "status": "ok",
                "detail": q_summary, "tail": "",
            })
            _log(f"  ok: quarto ({q_summary})")

    # =================== Stage 4/4 — Publish ===================
    _log("=== Stage 4/4 — Publish ===")
    if not publish_after:
        results.append({
            "stage": STAGE_KEYS[3], "step": "publish", "status": "skipped",
            "detail": "--no-publish", "tail": "",
        })
        _log("  skipped: --no-publish")
    elif not stage3_ok:
        stage_status[3] = "aborted"
        results.append({
            "stage": STAGE_KEYS[3], "step": "publish", "status": "aborted",
            "detail": "stage 3 quarto failed", "tail": "",
        })
        _log("  ABORTED: quarto failed, not publishing")
        _persist()
        return 1
    else:
        stage_status[3] = "running"
        try:
            rc, pub_summary = run_publish_streaming(
                _log, commit_msg=commit_msg_for_scope("cli:headless")
            )
        except Exception as e:  # noqa: BLE001
            rc, pub_summary = -1, f"exception: {e}"

        if rc != 0:
            stage_status[3] = "failed"
            results.append({
                "stage": STAGE_KEYS[3], "step": "publish", "status": "failed",
                "detail": pub_summary[:200], "tail": pub_summary[-10000:],
            })
            _log(f"  FAIL: publish ({pub_summary[-400:]})")
            _persist()
            return 1
        stage_status[3] = "done"
        results.append({
            "stage": STAGE_KEYS[3], "step": "publish", "status": "ok",
            "detail": pub_summary, "tail": "",
        })
        _log(f"  ok: publish ({pub_summary})")

    _persist()
    _log("=== Pipeline OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
